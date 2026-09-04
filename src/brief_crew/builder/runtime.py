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
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from brief_crew.builder.gates import gate_decision, gate_payload
from brief_crew.config import (
    BUILDER_DEFAULT_TOOL_FAILURE_POLICY,
    AGENT_CREDENTIAL_KIND,
    BUILDER_ROUTER_COMPARISONS,
    BUILDER_ROUTER_OTHERWISE,
    BUILDER_STATE_ERROR_PREFIX,
    BUILDER_STATE_OUTPUT_PREFIX,
    BUILDER_TRANSFORM_OPS,
    CHEAP_MODEL,
    ESCALATION_MODEL,
    GRAPH_BUDGET_CALL_COMPLETION_TOKENS,
    MAX_FRAME_PREVIEW_CHARS,
    MAX_NODE_ERROR_CHARS,
    MAX_RUN_RESULT_BODY_CHARS,
    OPENROUTER_MODEL_PREFIX,
    VALIDATOR_BRANCH_MAX_ITER,
    openrouter_authored_params,
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
    "builder_state_sink",
    "checkpoint",
    "current_cancel_flag",
    "emit_output",
    "missing_prompt_inputs",
    "rejoin",
    "render_gate",
    "ReplayMissingOutput",
    "replay_output",
    "route_branch",
    "route_gate",
    "run_agent",
    "run_crew",
    "replay_source",
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


class ReplayMissingOutput(BuilderRuntimeError):
    """A derived plan replayed a node whose saved output is not in the source.

    Its own class only so it can carry C6's `error_class`: the operator's next
    move is different from every other runtime refusal - they picked a resume
    point the source run never reached.
    """

    error_class = "replay-missing-output"


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


#: Where a node's state is checkpointed after it writes its output, or None.
#:
#: **CrewAI persists NOTHING for an ordinary declarative run**, and that was
#: measured rather than assumed: a two-node graph published, launched and
#: completed on the service persistence leaves `flow_states` EMPTY. The only
#: writer is `save_pending_feedback`, on the pause a gate raises. So a run that
#: never met a gate had no state to read afterwards - which makes C7's
#: `GET /state?step=` answer `{}` for every step, and makes 10 D5's `resume_from`
#: have nothing to replay from. Both of those are this plan's, so the write is
#: this plan's too.
#:
#: A ContextVar rather than an argument, for the reason `current_cancel_flag`
#: gives one line down: the entrypoints are called by CrewAI, not by us, and
#: the context is copied into every worker thread a fan-out starts.
current_state_sink: ContextVar["Callable[[str, Mapping[str, Any]], None] | None"] = (
    ContextVar("brief_crew_builder_state_sink", default=None)
)


@contextmanager
def builder_state_sink(
    sink: "Callable[[str, Mapping[str, Any]], None] | None",
) -> Iterator[None]:
    """Checkpoint every node's state through `sink` for the length of this run."""

    token = current_state_sink.set(sink)
    try:
        yield
    finally:
        current_state_sink.reset(token)


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
        # Plans 06, 07 and 08, defaulted for the same reason: every test double
        # in this repository predates them and must keep satisfying this
        # protocol without an edit.
        attachments: Any = None,
        tool_failure_policy: str = BUILDER_DEFAULT_TOOL_FAILURE_POLICY,
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

    # The two AUTHORED builders (09 D1). Given bodies rather than `...` so
    # every double written before 09 keeps satisfying this protocol without an
    # edit - the same reason `api_key`, `attachments` and `tool_failure_policy`
    # are defaulted above. A double that does not override them falls back to
    # its own library builder, which is what a test that only cares about
    # "something ran here" wants; a double that DOES override gets the whole
    # authored spec and can assert on it.
    def authored_agent_crew(self, *, node_id: str, spec: "AuthoredAgentSpec") -> Any:
        return self.agent_crew(
            node_id=node_id,
            agent_id=spec.role,
            tier=spec.tier,
            tools=(),
            max_iter=spec.max_iter,
            guardrail_max_retries=spec.guardrail_max_retries,
        )

    def authored_crew(self, *, node_id: str, spec: "AuthoredCrewSpec") -> Any:
        return self.crew(
            node_id=node_id,
            crew_id=spec.process,
            tier=spec.tier,
            max_iter=spec.max_iter,
            guardrail_max_retries=spec.guardrail_max_retries,
        )


@dataclass(frozen=True)
class AuthoredAgentSpec:
    """One authored agent node's whole `with:` block, as one object.

    A dataclass rather than fourteen keyword arguments because the SAME object
    is a crew member (09 D2 folds a `member` agent's block into its crew's
    `members` list), and threading fourteen keywords through two call sites is
    how the two spellings drift. Every field is a VALUE the author typed or an
    OPAQUE ID the entrypoint dereferences - never a name, a path or a callable
    (FD10).
    """

    role: str
    goal: str
    backstory: str
    task: Mapping[str, Any]
    llm: Mapping[str, Any]
    tier: str = "cheap"
    max_iter: int = VALIDATOR_BRANCH_MAX_ITER
    guardrail_max_retries: int = 0
    advanced: Mapping[str, Any] = field(default_factory=dict)
    expert: Mapping[str, Any] = field(default_factory=dict)
    tools: tuple[Mapping[str, Any], ...] = ()
    mcps: tuple[Mapping[str, Any], ...] = ()
    skills: tuple[str, ...] = ()
    prompt_inputs: Mapping[str, Any] = field(default_factory=dict)
    tool_failure_policy: str = BUILDER_DEFAULT_TOOL_FAILURE_POLICY
    credential_id: str | None = None

    def attachment_list(self) -> tuple[dict[str, Any], ...]:
        """The three C5 lists as the one discriminated list `bind_attachments` reads.

        C5 spells an authored agent's attachments as three keys and plans 06 to
        08 shipped `bind_attachments` over one `kind`-discriminated list. Both
        are the same data; this is the one line that says so, rather than two
        wire formats nobody reconciles.
        """

        return (
            *(
                {"kind": "tool", **{str(k): v for k, v in dict(entry).items()}}
                for entry in self.tools
            ),
            *(
                {"kind": "mcp", **{str(k): v for k, v in dict(entry).items()}}
                for entry in self.mcps
            ),
            *({"kind": "skill", "skill_id": str(skill)} for skill in self.skills),
        )


@dataclass(frozen=True)
class AuthoredCrewSpec:
    """One authored crew node's `with:` block, members and all."""

    process: str
    members: tuple[AuthoredAgentSpec, ...] = ()
    task_order: tuple[str, ...] = ()
    member_ids: tuple[str, ...] = ()
    manager_llm: Mapping[str, Any] | None = None
    manager_agent: str | None = None
    tier: str = "cheap"
    max_iter: int = VALIDATOR_BRANCH_MAX_ITER
    guardrail_max_retries: int = 0
    memory: bool = False
    cache: bool = True
    max_rpm: int | None = None
    planning: bool = False
    planning_llm: Mapping[str, Any] | None = None
    verbose: bool = False
    prompt_inputs: Mapping[str, Any] = field(default_factory=dict)
    tools: tuple[Mapping[str, Any], ...] = ()
    mcps: tuple[Mapping[str, Any], ...] = ()


def _failure_policy(name: str) -> Any:
    from crewai.tools.tool_failure import ToolFailurePolicy

    return ToolFailurePolicy(name)


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
        attachments: Any = None,
        tool_failure_policy: str = BUILDER_DEFAULT_TOOL_FAILURE_POLICY,
    ) -> Any:
        from crewai import LLM, Agent, Crew, Process, Task

        spec = agent_spec(agent_id)
        agents_config = _yaml_config("agents.yaml")
        tasks_config = _yaml_config("tasks.yaml")
        bound = attachments or BoundAttachments()
        agent = Agent(
            config=dict(agents_config[spec.agent_key]),
            tools=[_tool_instance(name) for name in tools] + list(bound.tools),
            # `None` rather than `[]` for both, and it is not cosmetic: CrewAI
            # walks its MCP resolver and its skill loader for an empty list and
            # skips them for `None`.
            mcps=list(bound.mcps) or None,
            skills=list(bound.skills) or None,
            # `warn` is CrewAI's own default and stays this product's; `raise`
            # is what makes plan 12's error edge fire, because only a raised
            # `ToolExecutionFailedError` leaves the step.
            tool_failure_policy=_failure_policy(tool_failure_policy),
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

    # ---------------------------------------------------------- authored
    def authored_agent_crew(self, *, node_id: str, spec: AuthoredAgentSpec) -> Any:
        """The author's own `Agent`, their own `Task`, one `Crew` around them.

        THE PROMPT IS THE DOCUMENT'S, and that is the one place in this product
        where that is true. `config/agents.yaml` is where THIS repository's
        prompts live and the platform rule keeps them there; an authored node's
        prompt has no YAML to live in, so the document is not a second home for
        it - it is the only one. Nothing here reads a file.
        """

        from crewai import Crew, Process

        agent = self._authored_agent(spec, node_id=node_id)
        task = _authored_task(spec, agent)
        advanced = dict(spec.advanced)
        return Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            memory=bool(advanced.get("memory", False)),
            cache=bool(advanced.get("cache", True)),
            # 10 D7, and it is the Crew half of the same switch `_authored_llm`
            # sets on the model: without both, `LLMStreamChunkEvent` is never
            # raised and the dialogue rail has nothing to render until the call
            # completes.
            stream=True,
            verbose=False,
        )

    def _authored_agent(self, spec: AuthoredAgentSpec, *, node_id: str) -> Any:
        from crewai import Agent

        advanced = dict(spec.advanced)
        expert = dict(spec.expert)
        bound = bind_attachments(
            spec.attachment_list(),
            node_id=node_id,
            failure_policy=spec.tool_failure_policy,
        )
        planning_config = expert.get("planning_config")
        return Agent(
            role=spec.role,
            goal=spec.goal,
            backstory=spec.backstory,
            llm=_authored_llm(spec.llm, credential_id=spec.credential_id, node_id=node_id),
            tools=list(bound.tools),
            # `None` rather than `[]` for both: CrewAI walks its MCP resolver
            # and its skill loader for an empty list and skips them for `None`.
            mcps=list(bound.mcps) or None,
            skills=list(bound.skills) or None,
            max_iter=spec.max_iter,
            allow_delegation=bool(advanced.get("allow_delegation", False)),
            memory=bool(advanced.get("memory", False)),
            cache=bool(advanced.get("cache", True)),
            respect_context_window=bool(advanced.get("respect_context_window", True)),
            tool_failure_policy=_failure_policy(spec.tool_failure_policy),
            # The S9 deprecation ruling, applied at the constructor: `reasoning`
            # and `max_reasoning_attempts` are NOT passed, `planning` and
            # `planning_config` are. CrewAI folds the old pair into the new one
            # and warns; the switch an author sees is the one the package keeps.
            planning=bool(expert.get("planning", False)),
            **({"planning_config": dict(planning_config)} if planning_config else {}),
            **_present(
                max_rpm=advanced.get("max_rpm"),
                max_execution_time=advanced.get("max_execution_time"),
                system_template=expert.get("system_template"),
                prompt_template=expert.get("prompt_template"),
                response_template=expert.get("response_template"),
            ),
        )

    def authored_crew(self, *, node_id: str, spec: AuthoredCrewSpec) -> Any:
        """The author's own team: one `Agent` and one `Task` per member.

        `task_order` is the order the tasks run in, which for a sequential
        process IS the crew's behaviour. A hierarchical crew needs a manager and
        `document.py` already refuses one without - CrewAI raises at
        construction, which on a builder graph means after every upstream node
        has billed.
        """

        from crewai import Crew, Process

        agents = [
            self._authored_agent(member, node_id=member_id)
            for member_id, member in zip(spec.member_ids, spec.members)
        ]
        by_id = {
            member_id: (member, agent)
            for member_id, member, agent in zip(spec.member_ids, spec.members, agents)
        }
        ordered = [node for node in spec.task_order if node in by_id]
        ordered += [node for node in spec.member_ids if node not in ordered]
        tasks = [_authored_task(by_id[node][0], by_id[node][1]) for node in ordered]

        extra: dict[str, Any] = {}
        if spec.process == "hierarchical":
            manager = by_id.get(str(spec.manager_agent), (None, None))[1]
            if manager is not None:
                extra["manager_agent"] = manager
            elif spec.manager_llm:
                extra["manager_llm"] = _authored_llm(spec.manager_llm, node_id=node_id)
        if spec.planning and spec.planning_llm:
            extra["planning_llm"] = _authored_llm(spec.planning_llm, node_id=node_id)
        return Crew(
            agents=agents,
            tasks=tasks,
            process=Process.hierarchical if spec.process == "hierarchical" else Process.sequential,
            memory=spec.memory,
            cache=spec.cache,
            planning=spec.planning,
            stream=True,
            verbose=spec.verbose,
            **({"max_rpm": spec.max_rpm} if spec.max_rpm else {}),
            **extra,
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


def _present(**values: Any) -> dict[str, Any]:
    """Only the keyword arguments that were actually set.

    An authored field left blank must not become an explicit `None` on a CrewAI
    constructor: several of these have package defaults that are not `None`, and
    passing one would replace a default with a hole.
    """

    return {name: value for name, value in values.items() if value is not None}


def _authored_llm(
    spec: Mapping[str, Any] | None,
    *,
    credential_id: str | None = None,
    node_id: str = "",
) -> Any:
    """`LlmConfig` -> `crewai.LLM`, with the author's own key when they named one.

    The model is the author's; the KEY is resolved here - inside the entrypoint,
    for the run's owner and nobody else - exactly as `run_agent`'s library branch
    resolves it. The price ceiling is not negotiated here either: it is a
    property of the request `config.py` builds, and a caller's own key does not
    exempt a run from it (decision 14).
    """

    from crewai import LLM

    fields = dict(spec or {})
    model = str(fields.get("model") or "")
    if not model:
        raise BuilderRuntimeError(
            f"node {node_id!r} is an authored node with no model; every authored "
            "node names one out of the registry"
        )
    if not model.startswith(OPENROUTER_MODEL_PREFIX):
        model = f"{OPENROUTER_MODEL_PREFIX}{model}"
    optional = _present(
        temperature=fields.get("temperature"),
        top_p=fields.get("top_p"),
        max_tokens=fields.get("max_tokens"),
        timeout=fields.get("timeout"),
        response_format=fields.get("response_format"),
        frequency_penalty=fields.get("frequency_penalty"),
        presence_penalty=fields.get("presence_penalty"),
        seed=fields.get("seed"),
    )
    # `max_tokens` is ALWAYS set, and it is the number the budget already
    # priced with (10 D1). Until this line the estimate and the call disagreed
    # in one direction only: `budget.py` prices every call at
    # GRAPH_BUDGET_CALL_COMPLETION_TOKENS completion tokens and NOTHING capped
    # a completion, so the one bound the $10 ceiling was computed against did
    # not exist at run time. An author who names their own value wins - it is
    # their model and their money - and the default is the figure the ceiling
    # was measured from.
    optional.setdefault("max_tokens", GRAPH_BUDGET_CALL_COMPLETION_TOKENS)
    stop = tuple(fields.get("stop") or ())
    if stop:
        optional["stop"] = list(stop)
    key = fields.get("credential_id") or credential_id
    if key:
        optional["api_key"] = _agent_api_key(node_id, str(key))
    # `reasoning_effort` is NOT an `LLM` kwarg here, and that is the whole
    # point: CrewAI drops the field for every non-o1 model (config.py's own
    # note), so naming it on the constructor is a control an author sets and
    # nothing sends. `openrouter_authored_params` puts it in `extra_body`,
    # where it reaches OpenRouter - and carries the §6a price ceiling in the
    # same one `provider` object, because two writers of that key means the
    # second wins silently.
    effort = fields.get("reasoning_effort")
    return LLM(
        model=model,
        # 10 D7: streaming is on for authored nodes, so the dialogue rail has
        # per-token frames to render rather than one block of text at the end.
        # The chunks are coalesced in the serializer, not here.
        stream=True,
        additional_params=openrouter_authored_params(
            str(effort) if effort else None
        ),
        **optional,
    )


def _authored_task(spec: "AuthoredAgentSpec", agent: Any) -> Any:
    """The author's own `Task`, with their declared output schema if any.

    `output_schema` is a FLAT map of name to scalar type, turned into a pydantic
    model here with `create_model`. Flat deliberately: a nested JSON Schema would
    be a second document format inside the document, and `create_model` over an
    author-supplied nesting is a place to hide a type nobody looked at.
    """

    from crewai import Task

    fields = dict(spec.task)
    schema = fields.get("output_schema") or None
    extra: dict[str, Any] = {}
    if schema:
        extra["output_pydantic"] = _output_model(dict(schema))
    return Task(
        description=str(fields.get("description", "")),
        expected_output=str(fields.get("expected_output", "")),
        agent=agent,
        markdown=bool(fields.get("markdown", False)),
        async_execution=bool(fields.get("async_execution", False)),
        guardrail_max_retries=spec.guardrail_max_retries,
        **extra,
    )


#: The four scalar types `TaskConfig.output_schema` admits, as python types.
_SCALAR_TYPES: Mapping[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
}


def _output_model(schema: Mapping[str, Any]) -> Any:
    """A pydantic model for one authored task's declared output shape."""

    from pydantic import create_model

    unknown = sorted({str(kind) for kind in schema.values()} - set(_SCALAR_TYPES))
    if unknown:
        raise BuilderRuntimeError(
            f"an output schema names the type(s) {', '.join(unknown)}; the declared "
            f"types are {', '.join(sorted(_SCALAR_TYPES))}"
        )
    return create_model(
        "AuthoredOutput",
        **{str(key): (_SCALAR_TYPES[str(kind)], ...) for key, kind in schema.items()},
    )


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


def _checkpoint_state(flow: Any, node_id: str) -> None:
    """Write this flow's state as of `node_id`, if anybody is listening.

    Best effort and never fatal: a run whose state could not be checkpointed
    still runs, and the alternative - a node that fails because its telemetry
    did - is strictly worse than a `?step=` that answers coarsely.
    """

    sink = current_state_sink.get()
    if sink is None:
        return
    try:
        sink(node_id, _state(flow))
    except Exception:  # noqa: BLE001 - see the docstring
        LOGGER.debug("could not checkpoint state after %s", node_id, exc_info=True)


def _record(flow: Any, node_id: str, value: Any) -> Any:
    """Publish one node's result under the flat key downstream nodes reference."""

    _state(flow)[f"{BUILDER_STATE_OUTPUT_PREFIX}{node_id}"] = value
    _checkpoint_state(flow, node_id)
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


#: For the one thing in here that must never fail a run: an attachment that
#: will not clean up. A leaked client is a defect; a run failed at its last
#: line by a leaked client is a worse one.
LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# FD10 for the attachment family - plans 06, 07 and 08
#
# Author data reaches an entrypoint as VALUES and OPAQUE IDS, never names,
# paths or code, and the entrypoint dereferences them against the run's user
# inside the call. That is the whole rule, and everything below is it applied
# three times:
#
#   tool      tool_id   -> a server-owned catalogue entry -> a BaseTool
#   mcp       server_id -> the caller's own mcp_servers row -> an MCPServer*
#   skill     skill_id  -> a built-in or the caller's pack -> a crewai Skill
#
# None of the three can name a class, a module, a command or a file. A `tool_id`
# outside the catalogue is refused, a `server_id` that is not the run owner's is
# refused, and a stdio server is refused unless a deployment flag AND a command
# allow-list both admit it.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class BoundAttachments:
    """What one agent node's attachments became, plus how to let them go."""

    tools: tuple[Any, ...] = ()
    mcps: tuple[Any, ...] = ()
    skills: tuple[Any, ...] = ()
    closers: tuple[Any, ...] = ()

    def cleanup(self) -> None:
        for closer in self.closers:
            try:
                closer()
            except Exception:  # noqa: BLE001 - a failed cleanup must not fail a run
                LOGGER.warning("an attachment failed to clean up", exc_info=True)


def release_mcp_clients(crew: Any) -> None:
    """Close every MCP client this crew's agents opened. Never raises.

    **CrewAI cleans up only on the happy path**, and that is a measured fact
    rather than a precaution: `agent/core.py` calls `_cleanup_mcp_clients()`
    after the completion event is emitted, so a task that RAISES skips it and
    the client survives the step. A builder graph can fail a step for a dozen
    ordinary reasons - a guardrail, a cancel, a cost ceiling - so this runs in
    `run_agent`'s `finally` and covers the paths the package does not.

    A failure here is logged and swallowed for the same reason
    `BoundAttachments.cleanup` swallows one: a leaked client is a defect, and a
    run failed at its last line BY a leaked client is a worse one.
    """

    for agent in getattr(crew, "agents", ()) or ():
        closer = getattr(agent, "_cleanup_mcp_clients", None)
        if closer is None:
            continue
        try:
            closer()
        except Exception:  # noqa: BLE001 - see the docstring
            LOGGER.warning("an MCP client failed to close", exc_info=True)


def _credential_fields(
    node_id: str, credential_id: Any, *, kind: str | None
) -> dict[str, str] | None:
    """The plaintext fields for one attachment, or None when it names no key.

    Imported inside the function for the reason `_agent_api_key` gives:
    `service/credentials.py` pulls in SQLAlchemy through the persistence module,
    and compiling or pricing a document must not pay for that. A credential of
    the wrong KIND is refused here by kind name alone - never by value - so a
    `github` token on a Firecrawl tool fails this node instead of failing inside
    somebody's HTTP client after the run has started.
    """

    if not credential_id:
        return None
    from brief_crew.service.credentials import resolve_credential

    resolved = resolve_credential(str(credential_id))
    if kind is not None and resolved.kind != kind:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the credential {credential_id}, which is a "
            f"{resolved.kind} credential; this attachment needs a {kind} one"
        )
    return dict(resolved.fields)


def bind_attachments(
    attachments: Sequence[Mapping[str, Any]],
    *,
    node_id: str,
    failure_policy: str = BUILDER_DEFAULT_TOOL_FAILURE_POLICY,
) -> "BoundAttachments":
    """Dereference every attachment for the run's owner. Never before.

    Order is the order the author drew them, which is the order the agent's tool
    list is rendered in - so two authors who wired the same tools the same way
    get the same prompt.
    """

    from brief_crew.builder import mcp as mcp_module
    from brief_crew.builder import skills as skills_module
    from brief_crew.builder import tools as tools_module

    tools: list[Any] = []
    mcps: list[Any] = []
    skills: list[Any] = []
    closers: list[Any] = []

    for attachment in attachments:
        kind = str(attachment.get("kind", ""))
        if kind == "tool":
            tool_id = str(attachment.get("tool_id", ""))
            params = dict(attachment.get("params") or {})
            entry = tools_module.builtin(tool_id)
            custom = None
            if entry is None:
                custom = _custom_tool_spec(node_id, tool_id)
                credential_kind = "http_header" if custom.request.header_name else None
            else:
                credential_kind = entry.kind_for(params)
            tools.append(
                tools_module.resolved_tool(
                    tool_id,
                    params=params,
                    credential=_credential_fields(
                        node_id, attachment.get("credential_id"), kind=credential_kind
                    ),
                    failure_policy=failure_policy,
                    custom=custom,
                )
            )
        elif kind == "mcp":
            record = _mcp_record(node_id, str(attachment.get("server_id", "")))
            header = _credential_fields(
                node_id, record.header_credential_id, kind="mcp_header"
            )
            env = _credential_fields(
                node_id, record.env_credential_id, kind="mcp_header"
            )
            mcps.append(
                mcp_module.server_config(
                    record,
                    tool_names=tuple(attachment.get("tool_names") or ()),
                    header=(
                        {header["name"]: header["header_value"]} if header else None
                    ),
                    env={env["name"]: env["header_value"]} if env else None,
                )
            )
        elif kind == "skill":
            skills.append(
                skills_module.loaded_skill(
                    _skill_pack(node_id, str(attachment.get("skill_id", "")))
                )
            )
        else:
            raise BuilderRuntimeError(
                f"node {node_id!r} carries an attachment of kind {kind!r}; the "
                "attachment kinds are tool, mcp and skill"
            )
    return BoundAttachments(
        tools=tuple(tools),
        mcps=tuple(mcps),
        skills=tuple(skills),
        closers=tuple(closers),
    )


def _attachment_store(factory_name: str) -> tuple[Any, Any]:
    """One of the three stores, bound to the run's own persistence and user.

    The vault's ContextVars are the only thing that says whose run this is, and
    they are set by `service/builder_runner.py` around `kickoff` and `resume` -
    so an attachment resolves for the run's OWNER and for nobody else, exactly
    as a credential does, and an unowned run resolves nothing at all.
    """

    from brief_crew.service import attachments as attachment_stores
    from brief_crew.service.credentials import _current_store, current_run_user

    vault = _current_store.get()
    user_id = current_run_user.get()
    if vault is None or not user_id:
        return None, None
    persistence = getattr(vault, "_store", None)
    if persistence is None:  # pragma: no cover - a vault always carries one
        return None, None
    return getattr(attachment_stores, factory_name)(persistence), user_id


def _custom_tool_spec(node_id: str, tool_id: str) -> Any:
    store, user_id = _attachment_store("CustomToolStore")
    if store is None:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the custom tool {tool_id}, and this run has no "
            "identity to look it up for"
        )
    from brief_crew.service.attachments import AttachmentNotYours

    try:
        return store.get(user_id, tool_id)
    except AttachmentNotYours as exc:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the tool {tool_id}, which is not one of yours"
        ) from exc


def _mcp_record(node_id: str, server_id: str) -> Any:
    store, user_id = _attachment_store("McpServerStore")
    if store is None:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the MCP server {server_id}, and this run has no "
            "identity to look it up for"
        )
    from brief_crew.service.attachments import AttachmentNotYours

    try:
        return store.get(user_id, server_id)
    except AttachmentNotYours as exc:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the MCP server {server_id}, which is not one of "
            "yours"
        ) from exc


def _skill_pack(node_id: str, skill_id: str) -> Any:
    from brief_crew.builder import skills as skills_module

    for pack in skills_module.load_builtins():
        if pack.id == skill_id:
            return pack
    store, user_id = _attachment_store("SkillStore")
    if store is None:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the skill {skill_id}, and this run has no "
            "identity to look it up for"
        )
    from brief_crew.service.attachments import AttachmentNotYours

    try:
        return store.get(user_id, skill_id)
    except AttachmentNotYours as exc:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the skill {skill_id}, which is not one of yours"
        ) from exc


#: Exceptions a retry loop and an error policy must NEVER swallow. Both are
#: control flow rather than failure: `HookAborted` is how a cancelled run stops
#: and `HumanFeedbackPending` is how a gate pauses, and a node that caught
#: either would turn Cancel into a shrug and a gate into a dropped run.
def _is_control_flow(exc: BaseException) -> bool:
    from crewai.flow.async_feedback import HumanFeedbackPending
    from crewai.hooks import HookAborted

    return isinstance(exc, (HookAborted, HumanFeedbackPending))


# --------------------------------------------------------------------------
# What is worth trying again - 10 D3's closed list
# --------------------------------------------------------------------------
#: The exception NAMES a retry is willing to spend a second call on. Names, not
#: classes, because importing litellm, httpx and the MCP client here to write
#: five `isinstance` checks would pull three HTTP stacks into a module that is
#: also imported to PRICE a document. The whole `__mro__` is checked, so a
#: provider subclass of `RateLimitError` matches its base.
#:
#: The list is CLOSED, and what it leaves out is the point. A guardrail
#: rejection, a malformed structured output and a model REFUSAL are failures
#: of judgement, not of transport: CrewAI already loops guardrails with the
#: agent's own llm (`guardrail_max_retries`), and decision 16 rules that a
#: refusal is a decision rather than an error - retrying one with a fallback
#: model is asking a second judge until one agrees. `BuilderRuntimeError` is
#: excluded for the same reason in a different key: every one of them is a
#: document, wiring or credential fault, and the second attempt fails
#: identically having told nobody anything new.
_RETRYABLE_ERROR_NAMES: frozenset[str] = frozenset(
    {
        # crewai
        "ToolExecutionFailedError",
        "LLMCallFailedError",
        # litellm / the OpenAI SDK shapes CrewAI raises through
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "APIStatusError",
        "InternalServerError",
        "ServiceUnavailableError",
        "Timeout",
        # httpx / stdlib transport
        "TimeoutError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        # MCP transport (plan 07)
        "McpError",
        "ClosedResourceError",
        "BrokenResourceError",
    }
)

#: HTTP statuses a tool or a provider may report that mean "again, later".
#: Read off `status_code` or `status`, because a wrapped provider error often
#: carries the number and a name this list has never heard of.
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})


def _is_retryable(exc: BaseException) -> bool:
    """Is this failure one 10 D3 will spend another attempt on?"""

    if isinstance(exc, BuilderRuntimeError):
        return False
    if any(base.__name__ in _RETRYABLE_ERROR_NAMES for base in type(exc).__mro__):
        return True
    for attribute in ("status_code", "status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and value in _RETRYABLE_STATUS_CODES:
            return True
    return False


def _error_class(exc: BaseException) -> str:
    """The C6 discriminator for one failure.

    Read off an `error_class` attribute first - the same attribute
    `events/serializer.py::error_class_of` reads, so the two never disagree
    about a `credential-not-yours` - and falls back to the exception's own type
    name, which is at least a stable string a client can switch on.
    """

    declared = getattr(exc, "error_class", None)
    if isinstance(declared, str) and declared:
        return declared[:64]
    return type(exc).__name__[:64]


def _emit_frame(
    kind: Any,
    event_type: Any,
    *,
    node_id: str,
    message: str,
    details: Mapping[str, Any],
    level: Any = None,
) -> None:
    """One C6 frame from inside an entrypoint, or nothing at all.

    The runtime raises frames the SERIALIZER cannot: a retry, a routed failure
    and a replayed node are decisions this module makes, and CrewAI has no
    event for any of them. `current_capture` is the run's own adapter, set by
    `capture_events` and copied into every worker thread CrewAI starts, so a
    parallel branch's frames land on the same ring in the same order as its
    model frames.

    Emitting is BEST EFFORT and never raises. A node that failed to narrate
    itself must still run: the adapter already counts an emit error, and a run
    that died because its telemetry did would be the worst possible trade.
    """

    try:
        from brief_crew.events.context import current_capture

        context = current_capture.get()
        if context is None:
            return
        from brief_crew.events.models import FrameLevel

        context.adapter.emit(
            kind=kind,
            event_type=event_type,
            node_id=node_id,
            message=message,
            details=dict(details),
            level=level or FrameLevel.INFO,
        )
    except Exception:  # noqa: BLE001 - telemetry must never fail a run
        LOGGER.debug("could not emit a builder frame for %s", node_id, exc_info=True)


def _node_error_frame(
    node_id: str,
    exc: BaseException,
    *,
    attempt: int,
    will_retry: bool,
    fallback_model: str | None,
    routed: bool,
) -> None:
    """C6 `node_error`: this attempt failed, and what happens next."""

    from brief_crew.events.models import FrameKind, FrameLevel, UIEventType

    _emit_frame(
        FrameKind.ERROR,
        UIEventType.NODE_END,
        node_id=node_id,
        message=f"{node_id} failed on attempt {attempt}",
        details={
            "stage": "error",
            "error_class": _error_class(exc),
            "message": f"{type(exc).__name__}: {exc}"[:MAX_NODE_ERROR_CHARS],
            "attempt": attempt,
            "will_retry": will_retry,
            "fallback_model": fallback_model,
            "routed": routed,
        },
        level=FrameLevel.ERROR,
    )


def _retry_frame(
    node_id: str, *, attempt: int, of: int, backoff_ms: int, model: str | None
) -> None:
    """C6 `retry`: attempt N of M is about to start, after this long."""

    from brief_crew.events.models import FrameKind, UIEventType

    _emit_frame(
        FrameKind.NODE_STATE,
        UIEventType.NODE_START,
        node_id=node_id,
        message=f"{node_id} retrying, attempt {attempt} of {of}",
        details={
            "stage": "retry",
            "attempt": attempt,
            "of": of,
            "backoff_ms": backoff_ms,
            "model": model,
        },
    )


def _attempted(
    flow: Any,
    *,
    node_id: str,
    retry: Mapping[str, Any] | None,
    on_error: str,
    work: "Callable[[str | None], str]",
) -> str:
    """One node's work, under its retry loop and its error policy (09 D3, D4).

    THE LOOP IS HERE AND NOT IN THE FLOW, and that is the measured reason for
    the shape: a retry that re-entered a Flow method would need CrewAI to re-fire
    a listener, which is the very mechanism closed item 35 had to work around.
    Inside one entrypoint call it is an ordinary `for`.

    `fallback_model` is offered to the LAST attempt only, and only when there
    was an earlier one - a fallback on a node that never retried would silently
    move the whole graph onto a model the author did not choose. A model REFUSAL
    is not a failure and never reaches here (decision 16).

    `on_error: 'route'` means this method returns NORMALLY on failure, having
    written `err__<node>`; its paired router reads that key and takes the error
    port. Only a `@router` can choose an event, so a step that raised past its
    own listener would end the run instead of taking the recovery path the
    author drew.
    """

    spec = dict(retry or {})
    attempts = max(1, int(spec.get("max_retries", 0) or 0) + 1)
    backoff = float(spec.get("backoff_seconds", 0) or 0)
    fallback = spec.get("fallback_model") or None
    failure: BaseException | None = None

    def model_for(index: int) -> str | None:
        """The fallback model attempt `index` runs on, or None for the author's.

        Offered to the LAST attempt only, and only when there was an earlier
        one - a fallback on a node that never retried would silently move the
        whole graph onto a model the author did not choose.
        """

        return str(fallback) if fallback and index == attempts - 1 and index else None

    for attempt in range(attempts):
        last_attempt = attempt == attempts - 1
        # Per ATTEMPT, not per node (10 D3). `checkpoint` is where a Cancel and
        # the run's own `MAX_RUN_COST_USD` ceiling both land, and a node with
        # three attempts that checked once could spend two more calls after
        # either had already said stop.
        checkpoint(node_id)
        try:
            return work(model_for(attempt))
        except BaseException as exc:  # noqa: BLE001 - re-raised below unless routed
            if _is_control_flow(exc):
                raise
            failure = exc
            retryable = _is_retryable(exc)
            will_retry = bool(not last_attempt and retryable)
            _node_error_frame(
                node_id,
                exc,
                attempt=attempt + 1,
                will_retry=will_retry,
                fallback_model=model_for(attempt),
                routed=bool(on_error == "route" and not will_retry),
            )
            LOGGER.warning(
                "builder node %s failed on attempt %s of %s", node_id, attempt + 1, attempts
            )
            if not will_retry:
                # A failure this list does not recognise stops HERE rather than
                # burning the author's remaining attempts on a verdict that
                # cannot change - see `_RETRYABLE_ERROR_NAMES` for what the list
                # deliberately leaves out.
                break
            delay = backoff * (2 ** attempt)
            _retry_frame(
                node_id,
                attempt=attempt + 2,
                of=attempts,
                backoff_ms=int(delay * 1000),
                model=model_for(attempt + 1),
            )
            if delay:
                time.sleep(delay)

    assert failure is not None  # pragma: no cover - the loop runs at least once
    if on_error == "route":
        # A STRING and not D4's `{error_class, message}` mapping, deliberately.
        # `${state.err__<node>}` is how an author's recovery node reads this,
        # and this module's own docstring records that a flat key is the only
        # reference shape ever measured resolving - nested access into a
        # sub-dict was not. A mapping here would be a value the error port's
        # successor cannot read, which is the one thing the key exists for. The
        # discriminator is not lost: the string is `ClassName: sentence`, and
        # the machine-readable `error_class` is on the `node_error` frame above.
        _state(flow)[f"{BUILDER_STATE_ERROR_PREFIX}{node_id}"] = (
            f"{type(failure).__name__}: {failure}"
        )
        return _record(flow, node_id, "")
    raise failure


def run_agent(
    flow: Any,
    *,
    node_id: str,
    agent_id: str | None = None,
    tier: str = "cheap",
    tools: Sequence[Any] = (),
    max_iter: int = VALIDATOR_BRANCH_MAX_ITER,
    guardrail_max_retries: int = 0,
    prompt_inputs: Mapping[str, Any] | None = None,
    credential_id: str | None = None,
    attachments: Sequence[Mapping[str, Any]] = (),
    tool_failure_policy: str = BUILDER_DEFAULT_TOOL_FAILURE_POLICY,
    # --- the AUTHORED arm (09 D1). Present exactly when the author wrote the
    # prompt themselves; `role` is the discriminator, mirroring the parser's
    # own exactly-one rule (C1).
    role: str | None = None,
    goal: str | None = None,
    backstory: str | None = None,
    task: Mapping[str, Any] | None = None,
    llm: Mapping[str, Any] | None = None,
    advanced: Mapping[str, Any] | None = None,
    expert: Mapping[str, Any] | None = None,
    mcps: Sequence[Mapping[str, Any]] = (),
    skills: Sequence[str] = (),
    retry: Mapping[str, Any] | None = None,
    on_error: str = "fail",
) -> str:
    """`agent` - a YAML agent the deployment registered, or one the author wrote.

    ONE ENTRYPOINT, TWO ARMS, and the arm is decided by the presence of
    `agent_id` versus `role` - the parser's own rule, applied at the other end.
    Two refs would have doubled `BUILDER_ACTION_REFS` for no security gain: the
    allowlist bounds what code can run, and both arms run the same code.

    `credential_id` is the ONLY thing the compiled definition carries about a
    credential (C5): an opaque `cr_` id, resolved here - inside the entrypoint,
    for the run's owner and nobody else - and handed to the factory as the one
    keyword argument its constructor takes (plan 01 D5). The definition, the
    trace and the store never see a key.

    `attachments` is FD10 applied to plans 06, 07 and 08: a list of
    `{kind, tool_id | server_id | skill_id, params, credential_id}` mappings,
    every one of them an id or a value and never a name, a path or a class.
    They are dereferenced HERE, against the run's user, by `bind_attachments` -
    so a foreign credential, a deleted MCP server or somebody else's custom tool
    fails this node before a model is called rather than after three branches
    have billed.
    """

    checkpoint(node_id)
    inputs = dict(prompt_inputs or {})
    if role is not None:
        return _run_authored_agent(
            flow,
            node_id=node_id,
            spec=AuthoredAgentSpec(
                role=role,
                goal=str(goal or ""),
                backstory=str(backstory or ""),
                task=dict(task or {}),
                llm=dict(llm or {}),
                tier=tier,
                max_iter=max_iter,
                guardrail_max_retries=guardrail_max_retries,
                advanced=dict(advanced or {}),
                expert=dict(expert or {}),
                tools=tuple(dict(entry) for entry in tools if isinstance(entry, Mapping)),
                mcps=tuple(dict(entry) for entry in mcps),
                skills=tuple(str(skill) for skill in skills),
                prompt_inputs=inputs,
                tool_failure_policy=tool_failure_policy,
                credential_id=credential_id,
            ),
            retry=retry,
            on_error=on_error,
        )
    if not agent_id:
        raise BuilderRuntimeError(
            f"node {node_id!r} compiled to run_agent with neither an agent_id nor a "
            "role. One names a registered agent, the other carries the prompt; a "
            "node with neither has nothing to run"
        )
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
    bound = bind_attachments(
        attachments, node_id=node_id, failure_policy=tool_failure_policy
    )
    # Passed ONLY when they say something, exactly as `resolved_key` above is.
    # Every crew-factory double in this repository predates plans 06 to 08 and
    # has a fixed signature; handing them a keyword they do not declare turned
    # 46 green tests red in one edit, which is the measured reason this is a
    # conditional rather than two more arguments in the call.
    extra: dict[str, Any] = {}
    if attachments:
        extra["attachments"] = bound
    if tool_failure_policy != BUILDER_DEFAULT_TOOL_FAILURE_POLICY:
        extra["tool_failure_policy"] = tool_failure_policy

    def _once(_fallback_model: str | None) -> str:
        crew = _factories().agent_crew(
            node_id=node_id,
            agent_id=str(agent_id),
            tier=tier,
            tools=tuple(str(name) for name in tools),
            max_iter=max_iter,
            guardrail_max_retries=guardrail_max_retries,
            **extra,
            **resolved_key,
        )
        try:
            return _record(flow, node_id, _as_text(crew.kickoff(inputs=inputs)))
        finally:
            # `cleanup()` in a `finally`, always. CrewAI's MCP resolver opens a
            # client when the agent binds its tools, and a client that outlives
            # the step is a socket this process has forgotten it holds - which
            # on a stdio transport is also a child process nobody will reap.
            bound.cleanup()
            release_mcp_clients(crew)

    return _attempted(flow, node_id=node_id, retry=retry, on_error=on_error, work=_once)


def _run_authored_agent(
    flow: Any,
    *,
    node_id: str,
    spec: AuthoredAgentSpec,
    retry: Mapping[str, Any] | None,
    on_error: str,
) -> str:
    """The authored arm of `run_agent`, under the same retry and error policy."""

    def _once(fallback_model: str | None) -> str:
        attempt = spec
        if fallback_model:
            attempt = replace(spec, llm={**dict(spec.llm), "model": fallback_model})
        crew = _factories().authored_agent_crew(node_id=node_id, spec=attempt)
        try:
            return _record(
                flow,
                node_id,
                _as_text(crew.kickoff(inputs=dict(spec.prompt_inputs))),
            )
        finally:
            release_mcp_clients(crew)

    return _attempted(flow, node_id=node_id, retry=retry, on_error=on_error, work=_once)


#: The credential kind an agent node's model key must be. An agent's
#: `credential_id` is Stage 1's stand-in for C1 v2's `llm.credential_id`
#: (00 S1 ruling 8), and the model is always OpenRouter here. The value is
#: config.py's, checked there against CREDENTIAL_KINDS at import.
_AGENT_CREDENTIAL_KIND = AGENT_CREDENTIAL_KIND


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
    crew_id: str | None = None,
    tier: str = "cheap",
    max_iter: int = VALIDATOR_BRANCH_MAX_ITER,
    guardrail_max_retries: int = 0,
    prompt_inputs: Mapping[str, Any] | None = None,
    # --- the AUTHORED arm (09 D1), discriminated by `process` exactly as the
    # parser discriminates `crew_id` from `process`.
    process: str | None = None,
    members: Sequence[Mapping[str, Any]] = (),
    task_order: Sequence[str] = (),
    manager_llm: Mapping[str, Any] | None = None,
    manager_agent: str | None = None,
    memory: bool = False,
    cache: bool = True,
    max_rpm: int | None = None,
    planning: bool = False,
    planning_llm: Mapping[str, Any] | None = None,
    verbose: bool = False,
    # A crew may HOLD attachments too - `ATTACH_TARGET_KINDS` is agent and crew
    # - so the fold reaches here as well, and the entrypoint must accept the
    # keys the compiler emits or the step raises a bare TypeError at the moment
    # it runs, after everything upstream has billed.
    tools: Sequence[Mapping[str, Any]] = (),
    mcps: Sequence[Mapping[str, Any]] = (),
    attachments: Sequence[Mapping[str, Any]] = (),
    retry: Mapping[str, Any] | None = None,
    on_error: str = "fail",
) -> str:
    """`crew` - one registered `@CrewBase`, or a team the author assembled.

    **The library arm does NOT honour `tier`** (decision 12). A registered crew
    builds its own LLMs from `config.py`, inside the crew, and honouring the
    document's word would mean rebuilding them from outside - the crew library
    is the one place in the builder where the code is ours and not the author's.
    The word still prices and bounds the graph, which is what it is for, and
    `library_problems` says so on the node rather than leaving an author to
    infer it. `max_iter` IS honoured, and reaches the factory.
    """

    checkpoint(node_id)
    inputs = dict(prompt_inputs or {})
    if process is not None:
        specs = tuple(_member_spec(member) for member in members)
        spec = AuthoredCrewSpec(
            process=process,
            members=tuple(spec for _, spec in specs),
            member_ids=tuple(member_id for member_id, _ in specs),
            task_order=tuple(str(item) for item in task_order),
            manager_llm=dict(manager_llm) if manager_llm else None,
            manager_agent=manager_agent,
            tier=tier,
            max_iter=max_iter,
            guardrail_max_retries=guardrail_max_retries,
            memory=memory,
            cache=cache,
            max_rpm=max_rpm,
            planning=planning,
            planning_llm=dict(planning_llm) if planning_llm else None,
            verbose=verbose,
            prompt_inputs=inputs,
            tools=tuple(dict(entry) for entry in tools),
            mcps=tuple(dict(entry) for entry in mcps),
        )

        def _authored(_fallback_model: str | None) -> str:
            crew = _factories().authored_crew(node_id=node_id, spec=spec)
            try:
                return _record(flow, node_id, _as_text(crew.kickoff(inputs=inputs)))
            finally:
                release_mcp_clients(crew)

        return _attempted(
            flow, node_id=node_id, retry=retry, on_error=on_error, work=_authored
        )

    if not crew_id:
        raise BuilderRuntimeError(
            f"node {node_id!r} compiled to run_crew with neither a crew_id nor a "
            "process. One names a registered crew, the other assembles one"
        )

    def _library(_fallback_model: str | None) -> str:
        crew = _factories().crew(
            node_id=node_id,
            crew_id=str(crew_id),
            tier=tier,
            max_iter=max_iter,
            guardrail_max_retries=guardrail_max_retries,
        )
        return _record(flow, node_id, _as_text(crew.kickoff(inputs=inputs)))

    return _attempted(flow, node_id=node_id, retry=retry, on_error=on_error, work=_library)


def _member_spec(member: Mapping[str, Any]) -> tuple[str, AuthoredAgentSpec]:
    """One folded `member` agent's `with:` block, back into a spec.

    A member carries no `retry` and no `on_error` (C5): it is not a step, so it
    has no error port to route out of and no listener to re-enter. Its crew owns
    both.
    """

    fields = dict(member)
    return str(fields.get("node_id", "")), AuthoredAgentSpec(
        role=str(fields.get("role", "")),
        goal=str(fields.get("goal", "")),
        backstory=str(fields.get("backstory", "")),
        task=dict(fields.get("task") or {}),
        llm=dict(fields.get("llm") or {}),
        tier=str(fields.get("tier", "cheap")),
        max_iter=int(fields.get("max_iter", VALIDATOR_BRANCH_MAX_ITER)),
        guardrail_max_retries=int(fields.get("guardrail_max_retries", 0)),
        advanced=dict(fields.get("advanced") or {}),
        expert=dict(fields.get("expert") or {}),
        tools=tuple(dict(entry) for entry in fields.get("tools") or ()),
        mcps=tuple(dict(entry) for entry in fields.get("mcps") or ()),
        skills=tuple(str(skill) for skill in fields.get("skills") or ()),
        prompt_inputs=dict(fields.get("prompt_inputs") or {}),
        tool_failure_policy=str(
            fields.get("tool_failure_policy") or BUILDER_DEFAULT_TOOL_FAILURE_POLICY
        ),
        credential_id=fields.get("credential_id"),
    )


#: Where a replayed node's value comes from. Two words and no third: a saved run
#: (`persistence.load_state`) or a saved test input's mocked values (C7).
REPLAY_SOURCES: tuple[str, ...] = ("run", "test_input")

#: The replay values for one derived plan, run-scoped so two replays in one
#: process cannot read each other's. Set by whoever compiled the derived plan -
#: `10-runtime.md`'s resume endpoint or `13-flow-testing.md`'s node test - and
#: read by `replay_output` and by nothing else.
current_replay_values: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "brief_crew_builder_replay", default=None
)


@contextmanager
def replay_source(values: Mapping[str, Any] | None) -> Iterator[Mapping[str, Any]]:
    """Scope one derived plan's replayed outputs over a kickoff."""

    resolved = dict(values or {})
    token = current_replay_values.set(resolved)
    try:
        yield resolved
    finally:
        current_replay_values.reset(token)


def replay_output(
    flow: Any,
    *,
    node_id: str,
    source: str = "run",
) -> str:
    """The ELEVENTH ref (09 D7) - publish a node's saved output without running it.

    A derived replay plan compiles every node UPSTREAM of a resume point or a
    node under test to this instead of to the entrypoint that would have billed.
    It writes `out__<node>` from the saved source and returns, so every
    downstream listener fires exactly as it would after a real run - the flow
    engine cannot tell the difference, which is the whole point, and no model is
    called.

    It widens what an entrypoint ACCEPTS and not what the allowlist is FOR:
    `node_id` and one of two source words, both values, neither a name, a path
    nor a callable (FD10).
    """

    checkpoint(node_id)
    if source not in REPLAY_SOURCES:
        raise BuilderRuntimeError(
            f"node {node_id!r} compiles a replay from {source!r}; a replayed value "
            f"comes from {' or '.join(REPLAY_SOURCES)}"
        )
    values = current_replay_values.get() or {}
    if node_id not in values:
        raise ReplayMissingOutput(
            f"the replay plan has no saved output for {node_id!r}. Every node upstream "
            "of the replay point needs one, or the node downstream would be handed a "
            "blank with nothing saying why"
        )
    # 10 D5: the frames say `replayed`, so a console can draw the node dimmed
    # rather than pretending it ran. They are emitted HERE and not by the
    # serializer because CrewAI raises its own `MethodExecutionStarted/Finished`
    # for this method too - those are honest about a method running, and these
    # are the only statement anywhere that no model was called.
    from brief_crew.events.models import FrameKind, UIEventType

    value = _as_text(values[node_id])
    _emit_frame(
        FrameKind.NODE_STATE,
        UIEventType.NODE_START,
        node_id=node_id,
        message=f"{node_id} replayed from a saved {source}",
        details={"stage": "before", "replayed": True, "source": source},
    )
    recorded = _record(flow, node_id, value)
    _emit_frame(
        FrameKind.NODE_STATE,
        UIEventType.NODE_END,
        node_id=node_id,
        message=f"{node_id} replayed",
        details={
            "stage": "after",
            "replayed": True,
            "source": source,
            "output_preview": value[:MAX_FRAME_PREVIEW_CHARS],
        },
    )
    return recorded


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
