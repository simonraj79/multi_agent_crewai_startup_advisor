"""The ten compiler-owned entrypoints a compiled builder graph runs.

Every `do.ref` in a compiled `crewai.flow/v1` definition resolves to a name in
this module or to `gates:GATE_PROVIDER`, and `BUILDER_ACTION_REFS` names all
ten. That closed set IS the answer to code execution on a canvas: an author
document carries no ref, no module path and no Python, so the only code a
builder graph can run is the code written here. Author data reaches these
functions as `with:` arguments - values, never names.

**Every entrypoint is a bound method of the live flow.** CrewAI's `CodeAction`
does `handler.__get__(self.flow, type(self.flow))` for any plain callable
(`crewai/flow/runtime/_actions.py:83-85`), so the first parameter is the flow
instance and the signature the engine sees is the rest. That is why these are
module-level functions taking `flow` first rather than methods on a class.

**Two calling conventions, and the difference is load-bearing.** An action with
a `with:` block is called `handler(**rendered)` and never sees a positional
argument; an action without one is called `handler(*args)` and receives the
triggering method's output. `route_gate` is the one entrypoint that must read
that positional - it is how the operator's actual reply reaches the router - so
it is the one entrypoint the compiler emits with no `with:` block, and it
identifies itself through CrewAI's own `current_flow_method_name` instead.

**State is flat, on purpose.** Every node writes its result to
`state["out__<node_id>"]`, because `${state.a_value}` is the only reference
shape that was ever measured resolving; nested access into a sub-dict was not.
`compiler.py` seeds every key any `with:` block mentions, because CEL raises
`ExpressionError: no such member in mapping` on a key that is absent rather
than rendering it as empty.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from brief_crew.builder.gates import gate_decision, gate_payload
from brief_crew.config import (
    BUILDER_ROUTER_COMPARISONS,
    BUILDER_ROUTER_OTHERWISE,
    BUILDER_STATE_OUTPUT_PREFIX,
    BUILDER_TRANSFORM_OPS,
    CHEAP_MODEL,
    ESCALATION_MODEL,
    MAX_RUN_RESULT_BODY_CHARS,
    VALIDATOR_BRANCH_MAX_ITER,
)

__all__ = [
    "BUILDABLE_BUILDER_CREW_IDS",
    "BUILDER_AGENT_LIBRARY",
    "BUILDER_CREW_LIBRARY",
    "UNBUILDABLE_BUILDER_CREWS",
    "BuilderRuntimeError",
    "CrewFactories",
    "DefaultCrewFactories",
    "builder_cancellation",
    "checkpoint",
    "current_cancel_flag",
    "emit_output",
    "missing_prompt_inputs",
    "rejoin",
    "render_gate",
    "route_branch",
    "route_gate",
    "run_agent",
    "run_crew",
    "seed_input",
    "transform",
    "unbuildable_crew_reason",
    "use_crew_factories",
]

# Where `route_gate` finds what it may return. `compiler.py` writes this block
# into the compiled `state.default`; the key is deliberately dunder-shaped so a
# request input named `gates` or `routes` cannot collide with it, and Phase 3
# should register it as a reserved run input key on the builder workflow.
#
# It lives here rather than in `config.py` because it is a wire detail between
# two modules in this package, not a platform constant: nothing outside the
# compiler writes it and nothing outside this module reads it.
BUILDER_STATE_KEY = "__builder__"

# Per-gate revise counters, flat beside the `out__` keys and for the same
# reason. `VALIDATOR_MAX_GATE_TURNS`'s own note explains why a durable state
# field is the only place this bound can live: `Flow.max_method_calls` is a
# `PrivateAttr` that every `from_pending()` resume resets to 1.
BUILDER_STATE_TURNS_PREFIX = "turns__"


class BuilderRuntimeError(RuntimeError):
    """A compiled graph asked for something this runtime will not do.

    Raised rather than degraded in every case where degrading would spend money
    on a node that cannot produce what the next node was promised - an unknown
    agent id, a prompt the YAML task needs and the document never supplied, a
    routing table a request input has overwritten.
    """


# --------------------------------------------------------------------------
# Cancellation - blocker 7's per-node checkpoint
# --------------------------------------------------------------------------
#: The run's cancel flag, run-scoped so a pooled worker thread cannot inherit
#: another run's. `service/registry.py` already registers an
#: `InterceptionPoint.PRE_STEP` hook that covers agent and crew steps, and
#: CrewAI dispatches PRE_STEP for declarative methods too - so this is not the
#: only brake. It is the one that makes granularity exactly one NODE: a graph
#: of nothing but transforms and routers has no agent step to intercept, and
#: without a checkpoint of its own it would run to completion after Cancel.
current_cancel_flag: ContextVar[threading.Event | None] = ContextVar(
    "brief_crew_builder_cancel", default=None
)


@contextmanager
def builder_cancellation(flag: threading.Event | None) -> Iterator[None]:
    """Scope one run's cancel flag over everything this thread starts.

    The runner wraps a kickoff in this; CrewAI copies the context into every
    worker thread and task it spawns, so a parallel branch checkpoints against
    the same flag without being handed it.
    """

    token = current_cancel_flag.set(flag)
    try:
        yield
    finally:
        current_cancel_flag.reset(token)


def checkpoint(step_name: str) -> None:
    """Abort at a node boundary when this run has been cancelled.

    `HookAborted` deliberately, and imported where it is used the way
    `service/runner.py` imports it: it is the same exception CrewAI's own
    PRE_STEP guard raises, so `RunRegistry._execute`'s existing
    `except HookAborted` branch does the announcing and a cancelled builder run
    reaches CANCELLED rather than FAILED.
    """

    flag = current_cancel_flag.get()
    if flag is not None and flag.is_set():
        from crewai.hooks import HookAborted

        raise HookAborted(f"cancelled before {step_name}")


# --------------------------------------------------------------------------
# The agent and crew allowlists - prompts stay in YAML
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _AgentSpec:
    """One allowlisted agent: its YAML agent entry and the task it performs."""

    agent_key: str
    task_key: str


#: The six agents a document may name, each paired with the YAML task that
#: carries its instructions. A document names an id and never a role, a goal, a
#: backstory or a description - the platform rule is that prompts live in YAML,
#: and a document that carried them would be a second place they live.
#:
#: `tests/builder/test_compiler.py` asserts every key here exists in the two
#: YAML files, so renaming a YAML entry fails a test rather than silently
#: making an agent unbindable at the first paid run.
BUILDER_AGENT_LIBRARY: Mapping[str, _AgentSpec] = {
    "scoper": _AgentSpec("scoper", "scoping_task"),
    "market_analyst": _AgentSpec("market_analyst", "market_task"),
    "sentiment_analyst": _AgentSpec("sentiment_analyst", "sentiment_task"),
    "feasibility_analyst": _AgentSpec("feasibility_analyst", "feasibility_task"),
    "synthesist": _AgentSpec("synthesist", "synthesis_task"),
    "reporter": _AgentSpec("reporter", "reporting_task"),
}

#: The six registered `@CrewBase` classes, by the id a document names. Imported
#: lazily inside the factory: `crews.validator_crew` pulls in Firecrawl, the HN
#: client and the GitHub client, and compiling a document must not.
BUILDER_CREW_LIBRARY: Mapping[str, str] = {
    "scope": "ScopeCrew",
    "market": "MarketCrew",
    "sentiment": "SentimentCrew",
    "feasibility": "FeasibilityCrew",
    "synthesis": "SynthesisCrew",
    "report": "ReportCrew",
}

#: Of those six, the ones `DefaultCrewFactories.crew` cannot actually build,
#: mapped to the constructor arguments they demand. The factory's whole body is
#: `getattr(validator_crew, class_name)().crew()` - a bare zero-argument call -
#: and two of the six classes do not have a zero-argument `__init__`:
#: `SynthesisCrew(market, sentiment, feasibility)` and
#: `ReportCrew(verdict, tool_urls)` take TYPED PYDANTIC FINDINGS from upstream
#: nodes, which the validator flow hands over in Python and a drawn document
#: has no way to express at all.
#:
#: THE FAILURE THIS EXISTS TO MOVE. Until `library_problems` read this, a
#: document naming `crew_id: "synthesis"` validated clean, published clean, was
#: priced, registered and launchable - and then raised a bare `TypeError` from
#: inside the crew factory at the moment that node ran, which is AFTER the
#: scoper and all three research branches have billed real money for context
#: nothing would ever consume. The refusal belongs at validate, where it costs
#: nothing, and the id belongs out of `crew_ids` so no picker offers it.
#:
#: Declared here rather than derived by `inspect.signature`, because deriving
#: it means importing `crews.validator_crew` - Firecrawl, the HN client and the
#: GitHub client - inside the compiler, and the note above this pair says
#: compiling a document must not do that. What keeps a declaration honest is
#: `tests/builder/test_crew_library_arity.py`, which imports the module for
#: real and asserts this map is EXACTLY the required arguments of all six
#: `__init__`s. Add a seventh crew, or give one of these a default, and that
#: test fails rather than a paid run doing it.
UNBUILDABLE_BUILDER_CREWS: Mapping[str, tuple[str, ...]] = {
    "synthesis": ("market", "sentiment", "feasibility"),
    "report": ("verdict", "tool_urls"),
}

#: The crew ids a document may actually name. This, not `BUILDER_CREW_LIBRARY`,
#: is what the vocabulary endpoint publishes: an id that can never run is not
#: part of the vocabulary, and listing it would be the quietly-divergent double
#: this repo keeps writing entries about.
BUILDABLE_BUILDER_CREW_IDS: frozenset[str] = frozenset(BUILDER_CREW_LIBRARY) - frozenset(
    UNBUILDABLE_BUILDER_CREWS
)


def unbuildable_crew_reason(crew_id: str) -> str | None:
    """Why this registered crew cannot be constructed, or ``None`` if it can.

    One sentence, shared by the compiler's refusal and the factory's, so the
    author reads the same explanation whichever layer catches it.
    """

    required = UNBUILDABLE_BUILDER_CREWS.get(crew_id)
    if not required:
        return None
    class_name = BUILDER_CREW_LIBRARY.get(crew_id, crew_id)
    return (
        f"the crew {crew_id!r} cannot be built from a document: {class_name} requires "
        f"{', '.join(required)} at construction, and those are typed findings the "
        "validator flow hands over in Python rather than anything a drawn graph can "
        f"supply. The crews a document may name are {', '.join(sorted(BUILDABLE_BUILDER_CREW_IDS))}"
    )

#: Tier -> the model constant that tier means. Two entries because `config.py`
#: declares two models; a node names a tier and never a model, which is what
#: keeps model choice where the platform rules put it.
_MODEL_BY_TIER: Mapping[str, str] = {
    "cheap": CHEAP_MODEL,
    "escalation": ESCALATION_MODEL,
}

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "crews" / "validator_crew" / "config"

# What CrewAI interpolates: a `{name}` whose body is an identifier. A JSON
# example inside a prompt (`{"url": ...}`) is not matched, which is why the
# body pattern is anchored rather than `.+?`.
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@lru_cache(maxsize=2)
def _yaml_config(name: str) -> Mapping[str, Any]:
    """One of the validator crew's two YAML files, parsed and cached."""

    text = (_CONFIG_DIR / name).read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, Mapping):
        raise BuilderRuntimeError(f"{name} did not parse to a mapping")
    return parsed


def agent_spec(agent_id: str) -> _AgentSpec:
    """The allowlisted agent, or a refusal naming the six that exist."""

    spec = BUILDER_AGENT_LIBRARY.get(agent_id)
    if spec is None:
        raise BuilderRuntimeError(
            f"unknown agent id {agent_id!r}; a document may name one of "
            f"{', '.join(sorted(BUILDER_AGENT_LIBRARY))}. Agent instructions live in "
            "config/agents.yaml and a document names one, so an agent that is not "
            "there has no prompt to run"
        )
    return spec


def task_placeholders(agent_id: str) -> frozenset[str]:
    """Every `{name}` the agent's YAML task interpolates.

    Read off the YAML rather than listed here, because the prompts are the
    thing that moves and a list would be a second copy of it.
    """

    spec = agent_spec(agent_id)
    task = _yaml_config("tasks.yaml").get(spec.task_key)
    if not isinstance(task, Mapping):
        raise BuilderRuntimeError(
            f"agent {agent_id!r} is bound to the task {spec.task_key!r}, which "
            "config/tasks.yaml does not declare"
        )
    found: set[str] = set()
    for field in ("description", "expected_output"):
        value = task.get(field)
        if isinstance(value, str):
            found.update(_PLACEHOLDER.findall(value))
    return frozenset(found)


def missing_prompt_inputs(agent_id: str, prompt_inputs: Mapping[str, Any]) -> tuple[str, ...]:
    """Placeholders the YAML task needs that this node does not supply.

    Checked by the compiler, not only here, because the alternative is finding
    out at the first paid run: CrewAI interpolates inside `kickoff`, after the
    upstream nodes have already been billed for the context this one was going
    to use.
    """

    return tuple(sorted(task_placeholders(agent_id) - set(prompt_inputs)))


# --------------------------------------------------------------------------
# Crew construction, behind an injectable seam
# --------------------------------------------------------------------------
class CrewFactories(Protocol):
    """What `run_agent` and `run_crew` build their work with.

    A protocol with a ContextVar behind it, for the same reason
    `ValidatorFlow` takes injected crew factories: every test in this repo that
    executes a flow has to be able to replace the thing that would call a
    model, and a seam the production path also uses is one that cannot rot.
    """

    def agent_crew(
        self,
        *,
        node_id: str,
        agent_id: str,
        tier: str,
        tools: Sequence[str],
        max_iter: int,
        guardrail_max_retries: int,
        # Only passed when the node names a credential (plan 01 D5/D7), so a
        # factory written before the keyword existed keeps satisfying this
        # protocol; one that ignores it must still ACCEPT it.
        api_key: str | None = None,
    ) -> Any: ...

    def crew(
        self,
        *,
        node_id: str,
        crew_id: str,
        tier: str,
        max_iter: int,
        guardrail_max_retries: int,
    ) -> Any: ...


def _tool_instance(name: str) -> Any:
    """One registered research tool by the name it declares.

    Imported inside the function: each of these modules pulls in an HTTP client
    at import, and compiling or pricing a document must not pay for that.
    """

    from brief_crew.tools.github_feasibility import TOOL_NAME as GITHUB_TOOL
    from brief_crew.tools.github_feasibility import GitHubFeasibilityTool
    from brief_crew.tools.hn_sentiment import TOOL_NAME as HN_TOOL
    from brief_crew.tools.hn_sentiment import HackerNewsSentimentTool
    from brief_crew.tools.market_research import TOOL_NAME as MARKET_TOOL
    from brief_crew.tools.market_research import MarketResearchTool

    registry = {
        MARKET_TOOL: MarketResearchTool,
        HN_TOOL: HackerNewsSentimentTool,
        GITHUB_TOOL: GitHubFeasibilityTool,
    }
    tool_cls = registry.get(name)
    if tool_cls is None:
        raise BuilderRuntimeError(
            f"unknown tool {name!r}; a document may bind "
            f"{', '.join(sorted(registry))}"
        )
    return tool_cls()


class DefaultCrewFactories:
    """Builds the real thing: a YAML agent, its YAML task, one Crew around them."""

    def agent_crew(
        self,
        *,
        node_id: str,
        agent_id: str,
        tier: str,
        tools: Sequence[str],
        max_iter: int,
        guardrail_max_retries: int,
        api_key: str | None = None,
    ) -> Any:
        from crewai import LLM, Agent, Crew, Process, Task

        spec = agent_spec(agent_id)
        agents_config = _yaml_config("agents.yaml")
        tasks_config = _yaml_config("tasks.yaml")
        agent = Agent(
            config=dict(agents_config[spec.agent_key]),
            tools=[_tool_instance(name) for name in tools],
            # The author's own OpenRouter key when the node named one, else the
            # platform key from the environment (plan 01 D7). Passed straight in
            # and dropped: the string lives in this constructor call and nowhere
            # this module could log it. Admission, `MAX_RUN_COST_USD` and the
            # per-user rate limit are unchanged by whose key it is.
            llm=LLM(model=_model_for(tier), **({"api_key": api_key} if api_key else {})),
            allow_delegation=False,
            max_iter=max_iter,
        )
        # The YAML's own `guardrail_max_retries` is overridden rather than
        # passed beside it: `Task(config=...)` and an explicit keyword are two
        # sources for one field, and the node's value is the one the document
        # was priced on.
        task = Task(
            config={
                **dict(tasks_config[spec.task_key]),
                "guardrail_max_retries": guardrail_max_retries,
            },
            agent=agent,
        )
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            memory=False,
            # Tool results are cached within this one crew run, which is what
            # makes a guardrail retry - which re-runs the WHOLE task, byte
            # identical query included - stop paying twice for one scrape.
            cache=True,
            verbose=True,
        )

    def crew(
        self,
        *,
        node_id: str,
        crew_id: str,
        tier: str,
        max_iter: int,
        guardrail_max_retries: int,
    ) -> Any:
        import brief_crew.crews.validator_crew as validator_crew

        class_name = BUILDER_CREW_LIBRARY.get(crew_id)
        if class_name is None:
            raise BuilderRuntimeError(
                f"unknown crew id {crew_id!r}; a document may name one of "
                f"{', '.join(sorted(BUILDABLE_BUILDER_CREW_IDS))}"
            )
        # The call below is `Class().crew()` - zero arguments - so a class with
        # a required `__init__` raised a bare `TypeError` here, from inside a
        # worker thread, on a paid run. `library_problems` now refuses such a
        # document at validate; this is the same refusal at the site that would
        # actually have failed, because a document published before that check
        # existed is still stored and a direct factory call skips the compiler
        # entirely.
        reason = unbuildable_crew_reason(crew_id)
        if reason is not None:
            raise BuilderRuntimeError(reason)
        return getattr(validator_crew, class_name)().crew()


_FACTORIES: ContextVar[CrewFactories | None] = ContextVar(
    "brief_crew_builder_factories", default=None
)


@contextmanager
def use_crew_factories(factories: CrewFactories) -> Iterator[CrewFactories]:
    """Run everything in this scope against `factories` instead of the real ones."""

    token = _FACTORIES.set(factories)
    try:
        yield factories
    finally:
        _FACTORIES.reset(token)


def _factories() -> CrewFactories:
    return _FACTORIES.get() or DefaultCrewFactories()


def _model_for(tier: str) -> str:
    model = _MODEL_BY_TIER.get(tier)
    if model is None:
        raise BuilderRuntimeError(
            f"unknown tier {tier!r}; the tiers are "
            f"{', '.join(sorted(_MODEL_BY_TIER))}"
        )
    return model


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def _state(flow: Any) -> dict[str, Any]:
    """The flow's dict state, refused loudly if a graph was compiled otherwise."""

    state = flow.state
    if not isinstance(state, dict):
        raise BuilderRuntimeError(
            "a builder graph runs on dict state; this flow was built with "
            f"{type(state).__name__}"
        )
    return state


def _record(flow: Any, node_id: str, value: Any) -> Any:
    """Publish one node's result under the flat key downstream nodes reference."""

    _state(flow)[f"{BUILDER_STATE_OUTPUT_PREFIX}{node_id}"] = value
    return value


def _as_text(value: Any) -> str:
    """Whatever a node produced, as the text the next prompt will carry."""

    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw = getattr(value, "raw", None)
    if isinstance(raw, str):
        return raw
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, default=str)
    return str(value)


def _routing_entry(flow: Any, method_name: str | None) -> Mapping[str, Any]:
    """This router's own row of the compiled routing table.

    Identity comes from CrewAI's `current_flow_method_name`, which
    `_execute_method` sets around every method it runs - the same ContextVar
    `events/registry.py` already resolves frames through. A `ref` cannot carry
    a closure, so this is how a shared entrypoint knows which node it is.
    """

    state = _state(flow)
    table = state.get(BUILDER_STATE_KEY)
    entry = (
        table.get("gates", {}).get(method_name)
        if isinstance(table, Mapping) and method_name is not None
        else None
    )
    if not isinstance(entry, Mapping):
        raise BuilderRuntimeError(
            f"no compiled routing entry for {method_name!r}. The compiler writes "
            f"state[{BUILDER_STATE_KEY!r}] and nothing else may: a run whose "
            "inputs overwrote it would route a gate on data the operator sent"
        )
    return entry


def _rearm(flow: Any, entry: Mapping[str, Any]) -> None:
    """Re-arm the multi-event `or_()` listeners this router is about to re-enter.

    CrewAI adds such a listener to `_fired_or_listeners` the first time it
    fires and skips it forever after; the run then ends normally having
    produced nothing. Its own `_rearm_or_listeners_for_trigger` already covers
    the shape this compiler emits - a back edge's target listens on the very
    label the router returns - so this is the belt to that braces, and it is
    what the locked spec asked for. `_discard_or_listener` is private API,
    knowingly, and `test_compiler.py` pins its existence so a CrewAI upgrade
    that removes it fails loudly rather than silently ending runs.
    """

    discard = getattr(flow, "_discard_or_listener", None)
    if not callable(discard):
        return
    from crewai.flow.types import FlowMethodName

    for method_name in entry.get("rearm", ()):  # type: ignore[union-attr]
        discard(FlowMethodName(str(method_name)))


# --------------------------------------------------------------------------
# The entrypoints
# --------------------------------------------------------------------------
def seed_input(
    flow: Any,
    *,
    node_id: str,
    field: str,
    max_chars: int,
    required: bool = True,
) -> str:
    """`input` - take one named request input and publish it as this node's output."""

    checkpoint(node_id)
    state = _state(flow)
    raw = state.get(field)
    value = "" if raw is None else str(raw)
    if required and not value.strip():
        raise BuilderRuntimeError(
            f"this graph declares the input {field!r} and the run did not carry it; "
            "there is nothing to seed the first node with"
        )
    # Bounded here as well as at admission, because a resumed run re-seeds from
    # persisted state that no request validator ever saw.
    return _record(flow, node_id, value[:max_chars])


def run_agent(
    flow: Any,
    *,
    node_id: str,
    agent_id: str,
    tier: str,
    tools: Sequence[str] = (),
    max_iter: int = VALIDATOR_BRANCH_MAX_ITER,
    guardrail_max_retries: int = 0,
    prompt_inputs: Mapping[str, Any] | None = None,
    credential_id: str | None = None,
) -> str:
    """`agent` - one YAML agent, on one tier, doing its YAML task.

    `credential_id` is the ONLY thing the compiled definition carries about a
    credential (C5): an opaque `cr_` id, resolved here - inside the entrypoint,
    for the run's owner and nobody else - and handed to the factory as the one
    keyword argument its constructor takes (plan 01 D5). The definition, the
    trace and the store never see a key.
    """

    checkpoint(node_id)
    inputs = dict(prompt_inputs or {})
    missing = missing_prompt_inputs(agent_id, inputs)
    if missing:
        raise BuilderRuntimeError(
            f"node {node_id!r} runs the agent {agent_id!r}, whose task needs "
            f"{', '.join(missing)} and this node supplies "
            f"{', '.join(sorted(inputs)) or 'nothing'}. Fill those in on the canvas: "
            "the prompt would otherwise fail to interpolate after the upstream "
            "nodes had already been billed"
        )
    # Resolved BEFORE the factory is asked for anything, so a foreign or
    # deleted credential fails this node with nothing billed - and only passed
    # when set, so every factory written before the keyword existed is
    # untouched.
    resolved_key = (
        {"api_key": _agent_api_key(node_id, credential_id)} if credential_id else {}
    )
    crew = _factories().agent_crew(
        node_id=node_id,
        agent_id=agent_id,
        tier=tier,
        tools=tuple(tools),
        max_iter=max_iter,
        guardrail_max_retries=guardrail_max_retries,
        **resolved_key,
    )
    return _record(flow, node_id, _as_text(crew.kickoff(inputs=inputs)))


#: The credential kind an agent node's model key must be. An agent's
#: `credential_id` is Stage 1's stand-in for C1 v2's `llm.credential_id`
#: (00 S1 ruling 8), and the model is always OpenRouter here.
_AGENT_CREDENTIAL_KIND = "openrouter"


def _agent_api_key(node_id: str, credential_id: str) -> str:
    """The plaintext key for this node, for the run's owner, or a refusal.

    Imported inside the function: `service/credentials.py` pulls in SQLAlchemy
    through the persistence module, and compiling or pricing a document must
    not pay for that. `CredentialNotYours` and `VaultUnavailable` propagate
    unchanged - the first is the `credential-not-yours` `node_error` (C6), and
    neither sentence carries a field value. A credential of the wrong KIND is
    refused here by kind name alone, for the same reason.
    """

    from brief_crew.service.credentials import resolve_credential

    resolved = resolve_credential(credential_id)
    if resolved.kind != _AGENT_CREDENTIAL_KIND:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the credential {credential_id}, which is a "
            f"{resolved.kind} credential; an agent's model key must be an "
            f"{_AGENT_CREDENTIAL_KIND} credential"
        )
    return resolved.fields["api_key"]


def run_crew(
    flow: Any,
    *,
    node_id: str,
    crew_id: str,
    tier: str,
    max_iter: int = VALIDATOR_BRANCH_MAX_ITER,
    guardrail_max_retries: int = 0,
    prompt_inputs: Mapping[str, Any] | None = None,
) -> str:
    """`crew` - one registered `@CrewBase`, run whole, with its own guardrails."""

    checkpoint(node_id)
    crew = _factories().crew(
        node_id=node_id,
        crew_id=crew_id,
        tier=tier,
        max_iter=max_iter,
        guardrail_max_retries=guardrail_max_retries,
    )
    return _record(flow, node_id, _as_text(crew.kickoff(inputs=dict(prompt_inputs or {}))))


def render_gate(
    flow: Any,
    *,
    node_id: str,
    source: Any = None,
    editable_fields: Sequence[str] = (),
) -> str:
    """`gate`, method 1 of 2 - what the operator is shown, as JSON.

    The pause itself is `GATE_PROVIDER`, declared on this method's
    `human_feedback` block; this method only produces the payload, which CrewAI
    persists as `context.method_output` and the service splits into editable
    fields and read-only derived values.
    """

    checkpoint(node_id)
    payload = gate_payload(node_id, _latest(source), editable_fields)
    return _record(flow, node_id, json.dumps(payload, default=str))


def _latest(source: Any) -> Any:
    """The freshest of a gate's predecessors' outputs.

    A gate with several predecessors is compiled with a LIST of references,
    normal ones first and the revise loop last, and the last one carrying a
    value wins. That is what makes a revise loop show the revision: the loop
    branch's output is still null on the first pass, so the gate shows the
    original, and on the second pass it is the thing the operator asked for.
    """

    if not isinstance(source, (list, tuple)):
        return source
    latest: Any = None
    for value in source:
        if value is not None and value != "":
            latest = value
    return latest


def route_gate(flow: Any, *args: Any, **_: Any) -> str:
    """`gate`, method 2 of 2 - the operator's decision, as a declared event.

    Deliberately the one entrypoint compiled WITHOUT a `with:` block. With one,
    `CodeAction.run` calls `handler(**rendered)` and the `HumanFeedbackResult`
    that arrives positionally is dropped - the router would then route on
    nothing, which is the same silent approval the `emit`+`llm:null` trap
    produces. Identity comes from the routing table instead.
    """

    from crewai.flow.flow_context import current_flow_method_name

    entry = _routing_entry(flow, current_flow_method_name.get())
    node_id = str(entry["node_id"])
    checkpoint(node_id)

    result = args[0] if args else None
    decision, reply = gate_decision(getattr(result, "feedback", result))
    state = _state(flow)
    turns_key = f"{BUILDER_STATE_TURNS_PREFIX}{node_id}"
    used = max(0, int(state.get(turns_key, 0) or 0))
    max_turns = max(0, int(entry.get("max_turns", 0) or 0))

    honoured = decision == "revise" and used < max_turns
    if honoured:
        # Read-modify-write on the flow's own persisted state, so the count
        # survives the resume that answers the next turn. At the cap the revise
        # becomes an approval and the run goes FORWARD: failing would discard
        # everything already paid for, and refusing would park the run at a
        # gate with nothing left to do but expire.
        state[turns_key] = used + 1
    _record(
        flow,
        node_id,
        {
            "decision": decision,
            "honoured": honoured,
            "turns_used": state.get(turns_key, used),
            **reply,
        },
    )
    if honoured:
        _rearm(flow, entry)
        return str(entry["revise"])
    return str(entry["approve"])


def _compare(op: str, left: Any, right: Any) -> bool:
    """One declared comparison, false rather than raising on mismatched types.

    A router must always produce a branch: raising here would wedge a run at a
    node whose whole job is to choose, and `otherwise` exists precisely so an
    unmatched value goes forward.
    """

    if op not in BUILDER_ROUTER_COMPARISONS:
        raise BuilderRuntimeError(
            f"unknown router comparison {op!r}; the comparisons are "
            f"{', '.join(sorted(BUILDER_ROUTER_COMPARISONS))}"
        )
    try:
        if op == "eq":
            return bool(left == right)
        if op == "ne":
            return bool(left != right)
        if op == "contains":
            if isinstance(left, str):
                return str(right) in left
            return isinstance(left, (list, tuple, dict, set)) and right in left
        if left is None or right is None:
            return False
        if op == "gt":
            return bool(left > right)
        if op == "gte":
            return bool(left >= right)
        if op == "lt":
            return bool(left < right)
        return bool(left <= right)
    except TypeError:
        return False


def route_branch(
    flow: Any,
    *,
    node_id: str,
    rules: Sequence[Mapping[str, Any]],
    rearm: Sequence[str] = (),
    source: Any = None,
) -> str:
    """`router` - the first declared comparison that matches, else `otherwise`.

    A router PASSES ITS INPUT THROUGH to `out__<node_id>` rather than recording
    the branch it chose. Which branch was taken is already in the EDGE_TAKEN
    frame, and the console draws a router as plumbing rather than as a step -
    so what a downstream node wants from `${state.out__<router>}` is the thing
    that flowed through it. It is also what makes a gate re-entered by a revise
    loop show the revision rather than the string `e5_retry`.
    """

    checkpoint(node_id)
    state = _state(flow)
    fallback: str | None = None
    chosen: str | None = None
    for rule in rules:
        label = str(rule["label"])
        op = str(rule["op"])
        if op == BUILDER_ROUTER_OTHERWISE:
            fallback = label
            continue
        if chosen is None and _compare(op, state.get(str(rule.get("key"))), rule.get("value")):
            chosen = label
    selected = chosen or fallback
    if selected is None:
        raise BuilderRuntimeError(
            f"router {node_id!r} matched no branch and declares no otherwise; "
            "the run would stop here with nothing said"
        )
    _record(flow, node_id, _latest(source))
    if rearm:
        _rearm(flow, {"rearm": rearm})
    return selected


def _merge_into(target: dict[str, Any], name: str, value: Any) -> None:
    """Fold one `merge` argument in: a mapping by its keys, anything else by name."""

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = value
        value = parsed
    if isinstance(value, Mapping):
        target.update(value)
    else:
        target[name] = value


def transform(
    flow: Any,
    *,
    node_id: str,
    op: str,
    args: Mapping[str, Any] | None = None,
) -> Any:
    """`transform` - one of six fixed operations over `with:` data. No user Python."""

    checkpoint(node_id)
    if op not in BUILDER_TRANSFORM_OPS:
        raise BuilderRuntimeError(
            f"unknown transform op {op!r}; the operations are "
            f"{', '.join(sorted(BUILDER_TRANSFORM_OPS))}"
        )
    values = dict(args or {})

    if op == "pick":
        source = values.get("source")
        if isinstance(source, str):
            try:
                source = json.loads(source)
            except (json.JSONDecodeError, TypeError):
                source = {}
        key = str(values.get("key", ""))
        result: Any = source.get(key) if isinstance(source, Mapping) else None
    elif op == "merge":
        merged: dict[str, Any] = {}
        for name, value in values.items():
            _merge_into(merged, name, value)
        result = merged
    elif op == "join_text":
        separator = str(values.pop("separator", "\n\n"))
        result = separator.join(_as_text(value) for value in values.values() if value is not None)
    elif op == "to_json":
        result = json.dumps(values["value"] if "value" in values else values, default=str)
    elif op == "default":
        value = values.get("value")
        # `value or default` would eat a legitimate 0 or False, which is the
        # same defect that once priced a 128,069-token run at nothing. Only
        # None and the empty string count as absent.
        result = values.get("default") if value is None or value == "" else value
    else:  # format
        result = _format(str(values.get("template", "")), values)

    return _record(flow, node_id, result)


def _format(template: str, values: Mapping[str, Any]) -> str:
    """`{name}` substitution that is NOT `str.format`.

    `str.format` on an author-supplied template is an attribute-read primitive:
    `{a.__class__.__init__.__globals__}` walks straight out of the data. This
    substitutes only the names the node actually declares, and leaves every
    other brace as the literal text the author typed.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "template" or name not in values:
            return match.group(0)
        return _as_text(values[name])

    return _PLACEHOLDER.sub(replace, template)


def rejoin(flow: Any, *args: Any, node_id: str = "", label: str = "", **_: Any) -> str:
    """Return a declared rejoin label so a loop-closing node re-arms its target.

    Reserved and currently unemitted: `bounds.py` refuses a back edge whose
    source is not a gate or a router, and both of those already return a branch
    label of their own, so there is no shape left for this to compile from. It
    stays in the allowlist and stays working because the taxonomy declares it,
    and a ref that exists but is never emitted costs nothing while a missing
    one would fail at kickoff.
    """

    checkpoint(node_id or "rejoin")
    if not label:
        raise BuilderRuntimeError("a rejoin node must be compiled with its label")
    if node_id:
        _record(flow, node_id, label)
    return label


def emit_output(
    flow: Any,
    *,
    node_id: str,
    body_key: str,
    source: Any = None,
) -> dict[str, Any]:
    """`output` - the run's result, under a key that escapes the frame clip.

    `RUN_RESULT_BODY_KEYS` is not a formality: those are the keys
    `mark_completed` gives `MAX_RUN_RESULT_BODY_CHARS` instead of the streaming
    serializer's clip, and a body written anywhere else comes back truncated
    mid-sentence - which is exactly how the first paid run's report was lost.
    """

    checkpoint(node_id)
    body = _as_text(source)[:MAX_RUN_RESULT_BODY_CHARS]
    result = {body_key: body, "node_id": node_id}
    _record(flow, node_id, body)
    return result
