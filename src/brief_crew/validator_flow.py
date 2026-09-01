#!/usr/bin/env python
"""Headless six-agent validator orchestration."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, TypeVar

from crewai.flow import Flow, and_, listen, or_, router, start
from crewai.flow.async_feedback import (
    HumanFeedbackPending,
    HumanFeedbackProvider,
    PendingFeedbackContext,
)
from crewai.flow.human_feedback import HumanFeedbackResult, human_feedback
from crewai.flow.types import FlowMethodName
from pydantic import BaseModel, Field, PrivateAttr, ValidationError

from brief_crew.config import (
    GATE_REVISE_TURNS_METADATA_KEY,
    VALIDATOR_BRANCH_TURN_TIMEOUT_SECONDS,
    VALIDATOR_FEASIBILITY_CACHE_ENABLED,
    VALIDATOR_MAX_GATE_TURNS,
    VALIDATOR_MAX_METHOD_CALLS,
    VALIDATOR_SEQUENTIAL_BRANCHES,
)
from brief_crew.crews.validator_crew import (
    FeasibilityCrew,
    MarketCrew,
    ReportCrew,
    ScopeCrew,
    SentimentCrew,
    SynthesisCrew,
)
from brief_crew.events.verdict import publish_verdict
from brief_crew.schemas import (
    FeasibilityFindings,
    MarketFindings,
    ScopedIdea,
    SentimentFindings,
    ValidationReport,
    Verdict,
)
from brief_crew.validator_guardrails import findings_urls, parse_raw_model
from brief_crew.validator_cache import (
    BranchName,
    CapturedToolResult,
    capture_tool_results,
    format_cached_evidence,
    index_captured_evidence,
    lookup_branch_cache,
    resolve_namespace,
)

OUTPUT_PATH = Path("output") / "validation.md"
ModelT = TypeVar("ModelT", bound=BaseModel)

# The order the three research branches take when the sequential fallback is
# armed. Left to right on the fixed live topology (service/graph.py positions
# market at x=35, sentiment at x=430, feasibility at x=825), so a serialized
# trace reads the same way the graph does.
BRANCH_ORDER: tuple[BranchName, ...] = ("market", "sentiment", "feasibility")

# Branch -> Flow method name. These ARE the graph node ids: the same strings
# CrewAI's static structure exposes, that service/graph.py overlays, and that
# events/registry.py resolves frames onto. Sequential mode changes when a
# branch runs, never what it is called.
BRANCH_NODES: dict[BranchName, str] = {
    "market": "research_market",
    "sentiment": "research_sentiment",
    "feasibility": "research_feasibility",
}

# PRD R-3's escape hatch. Both now live in config.py, where the project rule
# says constants belong; the module-level names are kept as aliases so the
# call sites below stay readable. VALIDATOR_SEQUENTIAL_BRANCHES reads an env
# var, so withdrawing the fan-out is a deploy-time flip, not a code edit.
SEQUENTIAL_BRANCHES_DEFAULT = VALIDATOR_SEQUENTIAL_BRANCHES
BRANCH_TURN_TIMEOUT_SECONDS = VALIDATOR_BRANCH_TURN_TIMEOUT_SECONDS


# ------------------------------------------------------------- gate turn bound

GateName = Literal["scope", "verdict"]

# Gate node id -> the short name the state fields are keyed on. The node ids
# are the Flow method names, which is what `PendingFeedbackContext.method_name`
# carries and what `service/registry.py` calls SCOPE_GATE_NODE /
# VERDICT_GATE_NODE. Kept as a mapping rather than two `if`s so a third gate
# would be one line here and nothing else.
GATE_NODES: dict[str, GateName] = {
    "confirm_scope": "scope",
    "review_verdict": "verdict",
}

# Gate -> (turns-used field, capped field) on `ValidatorState`. Both are
# declared fields, so both are persisted by CrewAI and reloaded by
# `from_pending()`. That is the entire point: see the long note on
# VALIDATOR_MAX_GATE_TURNS in config.py for why `Flow.max_method_calls` cannot
# carry this bound.
GATE_TURN_FIELDS: dict[GateName, tuple[str, str]] = {
    "scope": ("scope_revise_turns", "scope_revise_capped"),
    "verdict": ("verdict_revise_turns", "verdict_revise_capped"),
}


def revise_turns_used(state: ValidatorState, gate: GateName) -> int:
    """Revise replies this gate has already spent. Never negative."""
    used_field, _ = GATE_TURN_FIELDS[gate]
    return max(0, int(getattr(state, used_field)))


def claim_revise_turn(state: ValidatorState, gate: GateName) -> bool:
    """Spend one revise turn at ``gate``, or refuse because the cap is reached.

    Returns True when the revise is honoured, having recorded the spend on the
    persisted state. Returns False at the cap, having recorded *that* - the
    `_capped` flag is the "why" behind a reply the operator sent as a revise
    and the run treated as an approval, and it is the only durable trace of it,
    because `scope_route` legitimately reads "scope_approved" in both cases.

    Read-modify-write on the flow's own state, called only from a router. Both
    routers run on the Flow's single execution path (never inside the three
    branch worker threads), so no lock is needed and adding one would be
    misleading about where concurrency lives in this file.
    """
    used_field, capped_field = GATE_TURN_FIELDS[gate]
    used = revise_turns_used(state, gate)
    if used >= VALIDATOR_MAX_GATE_TURNS:
        setattr(state, capped_field, True)
        return False
    setattr(state, used_field, used + 1)
    return True


class KickoffRunner(Protocol):
    def kickoff(self, inputs: dict[str, Any]) -> Any: ...


def _scope_runner() -> KickoffRunner:
    return ScopeCrew().crew()


def _market_runner() -> KickoffRunner:
    return MarketCrew().crew()


def _sentiment_runner() -> KickoffRunner:
    return SentimentCrew().crew()


def _feasibility_runner() -> KickoffRunner:
    return FeasibilityCrew().crew()


def _synthesis_runner(
    market: MarketFindings,
    sentiment: SentimentFindings,
    feasibility: FeasibilityFindings,
) -> KickoffRunner:
    return SynthesisCrew(market, sentiment, feasibility).crew()


def _report_runner(verdict: Verdict, tool_urls: set[str]) -> KickoffRunner:
    return ReportCrew(verdict, tool_urls).crew()


@dataclass(frozen=True)
class ValidatorCrewFactories:
    scope: Callable[[], KickoffRunner] = _scope_runner
    market: Callable[[], KickoffRunner] = _market_runner
    sentiment: Callable[[], KickoffRunner] = _sentiment_runner
    feasibility: Callable[[], KickoffRunner] = _feasibility_runner
    synthesis: Callable[
        [MarketFindings, SentimentFindings, FeasibilityFindings], KickoffRunner
    ] = _synthesis_runner
    report: Callable[[Verdict, set[str]], KickoffRunner] = _report_runner


try:  # pragma: no cover - import shape depends on the installed CrewAI
    from crewai.hooks import HookAborted as _HookAborted

    #: Exceptions that are CONTROL FLOW, not branch failure, and must never be
    #: swallowed by the degrade path below.
    #:
    #: `HookAborted` subclasses plain `Exception` and is the single signal for
    #: BOTH operator cancel and the run cost ceiling. A bare `except Exception`
    #: around a branch would therefore silently break the Cancel button and the
    #: budget cap - turning a safety fix into a safety hole.
    _BRANCH_CONTROL_FLOW: tuple[type[BaseException], ...] = (
        HumanFeedbackPending,
        _HookAborted,
    )
except Exception:  # pragma: no cover
    _BRANCH_CONTROL_FLOW = (HumanFeedbackPending,)


def _degraded_findings(
    model: type[ModelT], branch: str, exc: BaseException
) -> ModelT:
    """An honest empty-evidence result for a branch that did not complete.

    Before this existed, one slow branch destroyed the entire run. The three
    branches run under `asyncio.gather` with no `return_exceptions=True`, so the
    first exception propagated immediately, `and_(...)` never fired, synthesis
    never ran - and the OTHER TWO BRANCHES' completed, already-paid-for evidence
    was discarded along with the escalation-tier scope and the operator's time
    at the gate. That is what "ValidatorFlow failed / Run failed" was.

    The timeout that caused it could not be caught where you would expect.
    CrewAI raises it from `Agent._execute_with_timeout`, on a different thread
    from the tool's own `try`, and `Agent.execute_task` re-raises `TimeoutError`
    deliberately rather than routing it through `_handle_execution_error` like
    every other exception. So the tool's careful `failed` / `rate_limited`
    envelopes were unreachable for the one failure that actually happened.

    Everything downstream already handles this shape, which is why the fix is
    small: `tool_status="failed"` is a declared `ToolStatus`, `branches_ok`
    drops to 2 and applies its penalty, the branch's coverage goes to 0.0, and
    `rubric_support`'s `one_ok` predicates all admit an empty branch. The run
    reaches a real verdict - low confidence, `provisional`, with a `gaps` entry
    naming what broke - instead of a stack trace. Not a usable answer, but an
    honest one, and the operator keeps the report and the two good branches.
    """

    payload: dict[str, Any] = {
        "sources": [],
        "source_urls": [],
        "tool_status": "failed",
        "gaps": [
            f"The {branch} branch did not complete and contributed no evidence: "
            f"{type(exc).__name__}: {exc}"[:500]
        ],
    }
    # MarketFindings alone carries these; `paying_segments` has a default.
    if "competitors" in model.model_fields:
        payload["competitors"] = []
    return model.model_validate(payload)


def _edit_error_summary(error: ValidationError) -> str:
    """One readable sentence naming the fields that failed, for an operator.

    Pydantic's own string carries the whole model schema and a docs URL, which
    is noise in a gate reply. Field names and messages are the actionable part.
    Bounded, because this reaches a frame and a report.
    """

    parts = [
        f"{'.'.join(str(item) for item in problem['loc']) or '(root)'}: {problem['msg']}"
        for problem in error.errors()[:5]
    ]
    return "the edit was not applied - " + "; ".join(parts)


class ValidatorFeedbackProvider(HumanFeedbackProvider):
    """Auto-approve explicit no-gates runs; otherwise pause for native resume."""

    def request_feedback(
        self,
        context: PendingFeedbackContext,
        flow: Flow[Any],
    ) -> str:
        if getattr(flow.state, "no_gates", False):
            return json.dumps({"decision": "approve"})
        # Stamp how many revise turns this gate has already spent, so the layer
        # that builds the operator's prompt can stop OFFERING a Revise button
        # the router would decline to honour. This is the only place that holds
        # both halves: the provider is handed the live flow (and therefore the
        # persisted counters) and the context that is about to be written to
        # `pending_feedback`. `service/registry.py` reads it back out.
        #
        # A NEW dict, never a mutation of the existing one.
        # `_run_human_feedback_step` builds the context with
        # `metadata=metadata or {}` taken straight off the `@human_feedback`
        # definition (crewai/flow/runtime/__init__.py:3630-3641), so when a
        # decorator does declare metadata the context shares that object with
        # every other run of the same flow. Ours declares none, so the `or {}`
        # branch gives a fresh dict today - but writing in place would make
        # adding `metadata=` to the decorator a cross-run data leak, which is
        # not a trap worth leaving armed.
        gate = GATE_NODES.get(context.method_name)
        if gate is not None:
            context.metadata = {
                **context.metadata,
                GATE_REVISE_TURNS_METADATA_KEY: revise_turns_used(flow.state, gate),
            }
        raise HumanFeedbackPending(
            context=context,
            callback_info={"gate": context.method_name},
        )


FEEDBACK_PROVIDER = ValidatorFeedbackProvider()


class ValidatorState(BaseModel):
    idea: str = ""
    no_gates: bool = False
    # PRD R-3's withdrawal switch. False keeps the shipped parallel fan-out;
    # True makes the three research branches take one turn each. Part of the
    # state, not a constructor argument, so it survives a gate pause and is
    # settable per run through kickoff inputs - which is also how the service
    # reaches it, since ValidatorFlowRunner passes request inputs straight in.
    sequential_branches: bool = SEQUENTIAL_BRANCHES_DEFAULT
    namespace: str = ""
    feasibility_cache_enabled: bool = VALIDATOR_FEASIBILITY_CACHE_ENABLED
    source_run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    scope: ScopedIdea | None = None
    market: MarketFindings | None = None
    sentiment: SentimentFindings | None = None
    feasibility: FeasibilityFindings | None = None
    verdict: Verdict | None = None
    report: ValidationReport | None = None
    scope_gate_reply: str = ""
    verdict_gate_reply: str = ""
    scope_revision: str = ""
    verdict_revision: str = ""
    scope_route: str = ""
    verdict_route: str = ""
    # Revise turns spent at each gate, and whether a revise was ever converted
    # to an approval because the cap had been reached.
    #
    # These are DECLARED fields, and that word is doing all the work. CrewAI
    # persists the state model and `from_pending()` reloads it, so a counter
    # here survives the fresh flow object every gate reply builds - which is
    # precisely what `Flow._method_call_counts` does not do, being a
    # `PrivateAttr`. Nothing else in this file is durable across a resume, so
    # nothing else could hold this bound.
    #
    # Counting semantics: `*_revise_turns` counts revises ALREADY HONOURED, so
    # it is 0 when the gate first opens and the operator has spent nothing.
    # With VALIDATOR_MAX_GATE_TURNS = N the Nth revise is honoured and the
    # (N+1)th is not.
    scope_revise_turns: int = 0
    verdict_revise_turns: int = 0
    scope_revise_capped: bool = False
    # Why an operator's edit was dropped, if it was. Carried on the state
    # rather than raised, so the run survives and the reason still reaches the
    # operator instead of dying in a stack trace.
    scope_edit_error: str = ""
    verdict_edit_error: str = ""
    verdict_revise_capped: bool = False


def _extract_model(result: Any, model: type[ModelT]) -> ModelT:
    if isinstance(result, model):
        return result
    structured = getattr(result, "pydantic", None)
    if isinstance(structured, model):
        return structured
    if structured is not None:
        return model.model_validate(structured)
    raw = getattr(result, "raw", result)
    return parse_raw_model(str(raw), model)


def _require(value: ModelT | None, label: str) -> ModelT:
    if value is None:
        raise RuntimeError(f"{label} is unavailable at this Flow step")
    return value


def _gate_payload(feedback: str) -> dict[str, Any]:
    try:
        payload = json.loads(feedback or "{}")
    except json.JSONDecodeError:
        payload = {"decision": feedback.strip().lower()}
    return payload if isinstance(payload, dict) else {}


# ------------------------------------------------------- branch serialization


class BranchSequencer:
    """Give the three research branches one turn each, in ``BRANCH_ORDER``.

    PRD R-3 promises a sequential fallback: *the same agents, the same graph,
    worse latency*. That rules out the obvious implementation. Collapsing the
    three sibling ``@listen("scope_approved")`` methods into one method that
    calls three crews in a row would delete two nodes from the topology, two
    ``and_()`` join edges from the graph descriptor, and two node identities
    the UI and the event spine are built on - and it would leave two divergent
    Flow definitions to keep in step.

    So the Flow definition does not change at all. CrewAI still dispatches all
    three listeners through ``asyncio.gather`` and still runs each synchronous
    method in ``asyncio.to_thread(ctx.run, ...)``, which is what gives every
    branch the copied context the stream sinks and event correlation live in
    (PRD R-12 - no thread is hand-rolled here, and none may be). What changes
    is only *when* each branch does its work: a branch waits at this turnstile
    until the branches ahead of it in ``BRANCH_ORDER`` have finished.

    Serializing the whole method body, not just ``kickoff()``, is the point.
    ``scripts/perf_arms.py`` locks the crew factories from outside and says so:
    the per-branch cache lookup and evidence write-back still overlap there.
    Here they do not, so peak memory and connection pressure fall too.
    """

    def __init__(self, timeout_s: float = BRANCH_TURN_TIMEOUT_SECONDS) -> None:
        self._condition = threading.Condition()
        self._served = 0
        self._timeout_s = timeout_s

    @property
    def served(self) -> int:
        """Turns completed so far, across every fan-out cycle."""
        with self._condition:
            return self._served

    @contextmanager
    def turn(self, branch: BranchName, *, enabled: bool) -> Iterator[None]:
        """Hold this branch until its turn, or pass straight through."""
        if not enabled:
            yield
            return

        length = len(BRANCH_ORDER)
        index = BRANCH_ORDER.index(branch)
        with self._condition:
            granted = self._condition.wait_for(
                lambda: self._served % length == index,
                timeout=self._timeout_s,
            )
            if not granted:
                # A branch that never arrives must not strand the others. Take
                # the turn, resynchronise the turnstile on this branch, and
                # degrade to the parallel behaviour rather than deadlocking.
                print(
                    f"[validator] sequential turn for {branch} timed out after "
                    f"{self._timeout_s:.0f}s - proceeding without ordering"
                )
                self._served += (index - self._served) % length
        try:
            yield
        finally:
            with self._condition:
                self._served += 1
                self._condition.notify_all()


# ---------------------------------------------------------- branch output tag

_branch_prefix: ContextVar[str] = ContextVar(
    "brief_crew_validator_branch_prefix", default=""
)
_stdout_lock = threading.Lock()
_stdout_state: dict[str, Any] = {"depth": 0, "original": None}


class PrefixedStdout:
    """Stamp every line a research branch prints with its node id (F40).

    Three crews sharing one stdout is PRD 7.5's unreadable trace. The prefix is
    chosen per *context*, not per stream: CrewAI runs each branch in its own
    ``asyncio.to_thread(ctx.run, ...)`` worker, so the ContextVar read here is
    that branch's. Anything written from outside a branch - the CLI's own
    output, the service, another thread - reads an empty prefix and is passed
    through untouched.

    Whole lines only. A partial write is buffered per prefix until its newline
    arrives, so two branches cannot interleave inside one line, and nothing is
    inserted into the middle of a rich control sequence.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._lock = threading.RLock()
        self._partials: dict[str, str] = {}

    def __getattr__(self, name: str) -> Any:
        # Everything this class does not override - encoding, isatty, fileno,
        # buffer - belongs to the wrapped stream. Reading _stream through
        # object.__getattribute__ keeps a missing attribute from recursing.
        return getattr(object.__getattribute__(self, "_stream"), name)

    def write(self, data: str) -> int:
        prefix = _branch_prefix.get()
        if not prefix or not data:
            return self._stream.write(data)
        with self._lock:
            pending = self._partials.pop(prefix, "") + data
            head, newline, tail = pending.rpartition("\n")
            self._partials[prefix] = tail
            if newline:
                self._stream.write(
                    "".join(f"{prefix} {line}\n" for line in head.split("\n"))
                )
        return len(data)

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        prefix = _branch_prefix.get()
        if prefix:
            with self._lock:
                tail = self._partials.pop(prefix, "")
            if tail:
                self._stream.write(f"{prefix} {tail}\n")
        self._stream.flush()


@contextmanager
def branch_output(node_id: str) -> Iterator[None]:
    """Prefix this branch's terminal output with its Flow node id.

    Installation is reference counted and the original stream is restored by
    the last branch out, so a run leaves ``sys.stdout`` exactly as it found it.
    Nothing here touches the event spine: frames come from CrewAI events, not
    from stdout.
    """
    prefix = f"[{node_id}]"
    with _stdout_lock:
        if _stdout_state["depth"] == 0:
            _stdout_state["original"] = sys.stdout
            sys.stdout = PrefixedStdout(sys.stdout)
        _stdout_state["depth"] += 1
    token = _branch_prefix.set(prefix)
    try:
        yield
    finally:
        stream = sys.stdout
        if isinstance(stream, PrefixedStdout):
            try:
                stream.flush()
            except Exception:
                pass
        _branch_prefix.reset(token)
        with _stdout_lock:
            _stdout_state["depth"] -= 1
            if _stdout_state["depth"] == 0:
                if isinstance(sys.stdout, PrefixedStdout):
                    sys.stdout = _stdout_state["original"]
                _stdout_state["original"] = None


class ValidatorFlow(Flow[ValidatorState]):
    """Scope, fan out three evidence crews, synthesize, review and persist."""

    _skip_auto_memory: ClassVar[bool] = True
    crew_factories: ValidatorCrewFactories = Field(
        default_factory=ValidatorCrewFactories,
        exclude=True,
    )
    # CrewAI's in-process loop guard, lowered from its shipped 100 to something
    # proportionate to a 14-node flow. `max_method_calls` is a plain pydantic
    # Field on `Flow` (crewai/flow/runtime/__init__.py:614), so redeclaring it
    # here is the supported way to change it from a subclass: `from_pending()`
    # builds the instance with `cls(persistence=..., **kwargs)`, so every
    # resumed flow gets this default too.
    #
    # Note which of the two `max_method_calls` is upstream, because the obvious
    # guess is backwards. `FlowDefinition.config.max_method_calls`
    # (crewai/flow/flow_definition.py:219) reads like the declared knob, but
    # `_build_config_definition` (crewai/flow/dsl/_utils.py:221-238) builds that
    # config by copying CLASS FIELD defaults into it, and the enforcement at
    # runtime/__init__.py:3333 reads `self.max_method_calls`, the instance
    # field. So this line is the source and the definition merely reflects it;
    # writing the definition's config instead would have been a no-op that read
    # as a fix. Both directions are asserted in
    # `tests/validator/test_gate_turns.py`, and the enforcement itself is
    # proved there by a deliberately-too-low cap raising RecursionError.
    #
    # This is the backstop, never the bound: it resets on every resume, so on
    # the durable service path it can never see more than two calls of any
    # method. The durable bound is VALIDATOR_MAX_GATE_TURNS on the state above.
    max_method_calls: int = Field(default=VALIDATOR_MAX_METHOD_CALLS)
    # Run-local and never serialized: a turnstile is not flow state, and a
    # resumed flow starts a fresh fan-out anyway.
    _branch_sequencer: BranchSequencer = PrivateAttr(default_factory=BranchSequencer)

    @contextmanager
    def _branch_turn(self, branch: BranchName) -> Iterator[None]:
        """Order and label one research branch without moving its node."""
        with self._branch_sequencer.turn(
            branch, enabled=self.state.sequential_branches
        ):
            with branch_output(BRANCH_NODES[branch]):
                yield

    @start()
    def scope_idea(self) -> ScopedIdea:
        """Turn the idea into the shared research contract."""
        result = self.crew_factories.scope().kickoff(
            inputs={"idea": self.state.idea, "human_override": ""}
        )
        self.state.scope = _extract_model(result, ScopedIdea)
        return self.state.scope

    @listen("scope_revise")
    def revise_scope(self) -> ScopedIdea:
        """Regenerate scope from the operator's requested correction."""
        # Re-arm the scope gate before re-running the Scoper.
        #
        # `confirm_scope` listens on a *multi-event* `or_(scope_idea,
        # revise_scope)`, and CrewAI fires such a listener at most once per flow
        # object: `_find_triggered_methods` records the name in
        # `_fired_or_listeners` and skips it for the rest of the run
        # (crewai/flow/runtime/__init__.py:3288-3290). The one automatic re-arm
        # (:1067-1092) only discards a listener whose own condition contains the
        # label the router just emitted - `route_scope` emits "scope_revise",
        # which `confirm_scope` does not listen on - so it never matches here.
        #
        # Without this line a revise answered *in process* burns an
        # escalation-tier Scoper call and then ends the flow silently: no second
        # gate, no research, no report, and an ordinary return value that reads
        # as success. It is latent rather than absent today only because every
        # shipped gate reply goes through `from_pending()`/`resume()`, and
        # `_fired_or_listeners` is a PrivateAttr that is never persisted, so a
        # resumed flow starts with an empty set. Anything that answers a gate on
        # a live flow object - a scripted provider, a future auto mode, a test -
        # walks straight into it.
        #
        # Private API, knowingly. CrewAI's own cyclic-flow support leans on the
        # same hook family: the runtime calls the coarser `_clear_or_listeners()`
        # in three places and `ConversationalFlowMixin` declares it in its typed
        # protocol (conversational_mixin.py:279, called at :1148). The declared
        # alternative was to move the `or_()` onto a router, which routers are
        # exempt from (`and not is_router` at :3288) - correct, but it adds two
        # nodes and two edges to a topology that `service/graph.py`'s
        # VALIDATOR_OVERLAY, the mock graph, `crewStages.ts` and the E2E
        # node/edge counts are all pinned to, for two pass-through nodes
        # carrying no agent and no decision. If a CrewAI upgrade ever removes
        # this hook, the guard test in tests/validator/test_flow.py fails loudly
        # and the router variant is still available.
        self._discard_or_listener(FlowMethodName("confirm_scope"))
        result = self.crew_factories.scope().kickoff(
            inputs={
                "idea": self.state.idea,
                "human_override": self.state.scope_revision,
            }
        )
        self.state.scope = _extract_model(result, ScopedIdea)
        return self.state.scope

    @human_feedback(
        message=(
            "Confirm the parsed scope. Reply with JSON using decision=approve, or "
            "decision=revise plus feedback and an optional edited scope object."
        ),
        emit=None,
        # `llm=None`, deliberately. `emit=None` means CrewAI never collapses the
        # reply to an outcome, so the gate LLM is unreachable - but
        # `_run_human_feedback_step` deserializes it *before* it checks `emit`
        # (crewai/flow/runtime/__init__.py:3608-3611), so naming a model here
        # built two OpenAICompatibleCompletion clients per run, four httpx
        # pools and four SSL trust stores, and discarded all of it: 0.73s of
        # measured wall clock buying nothing. `_validate_human_feedback_options`
        # only requires `llm` when `emit is not None`
        # (crewai/flow/human_feedback.py:211-218), so None is legal here.
        llm=None,
        provider=FEEDBACK_PROVIDER,
    )
    @listen(or_(scope_idea, revise_scope))
    def confirm_scope(self, _: ScopedIdea) -> str:
        """Pause after scoping so the operator can approve or revise it."""
        return _require(self.state.scope, "scope").model_dump_json(indent=2)

    @router(confirm_scope)
    def route_scope(
        self, result: HumanFeedbackResult
    ) -> Literal["scope_approved", "scope_revise"]:
        """Route the structured scope reply without an LLM call."""
        self.state.scope_gate_reply = result.feedback
        payload = _gate_payload(result.feedback)
        edited_scope = payload.get("scope")
        if isinstance(edited_scope, dict):
            # Degrade, do not die.
            #
            # This used to be a bare `model_validate`, and a mistyped value in a
            # field the gate ITSELF offered for editing - `assumptions: "5"`
            # where a list belongs - raised here, inside the router, after the
            # gate had already been durably answered. The run ended `failed`
            # with no gate to retry and no recovery, discarding an
            # escalation-tier Scoper call, and the operator had been told
            # `202 Accepted`.
            #
            # A malformed edit is a client defect, not a reason to destroy a
            # paid run. The operator's *decision* is still legible and is still
            # honoured; only the edit is dropped, and the reason is recorded on
            # the state so it reaches the report and the frames instead of
            # vanishing into a stack trace. No revise turn is spent on it -
            # charging the operator a turn for their client sending the wrong
            # JSON type would be punishing the wrong party.
            try:
                self.state.scope = ScopedIdea.model_validate(edited_scope)
            except ValidationError as error:
                self.state.scope_edit_error = _edit_error_summary(error)
        decision = str(payload.get("decision", "approve")).strip().lower()
        # `claim_revise_turn` is evaluated only when the operator asked to
        # revise, so an approve never spends a turn and never trips the cap.
        # At the cap the revise becomes an approval and the run goes forward:
        # the alternatives are worse. Failing the run would discard an
        # escalation-tier scope the operator already paid for; refusing the
        # reply would leave the run parked at a gate with nothing left to do
        # but expire. Going forward is the only outcome that keeps the money
        # already spent and still bounds the money not yet spent.
        if decision == "revise" and claim_revise_turn(self.state, "scope"):
            self.state.scope_revision = str(
                payload.get("feedback") or result.feedback
            )
            self.state.scope_route = "scope_revise"
            return "scope_revise"
        self.state.scope_route = "scope_approved"
        return "scope_approved"

    @listen("scope_approved")
    def research_market(self) -> MarketFindings:
        """Run the market branch in a Flow-managed worker thread."""
        with self._branch_turn("market"):
            scope = _require(self.state.scope, "scope")
            namespace = resolve_namespace(self.state.namespace)
            cached = self._cached_evidence("market", scope, namespace)
            tool_results: list[CapturedToolResult] = []
            try:
                with capture_tool_results("market") as tool_results:
                    result = self.crew_factories.market().kickoff(
                        inputs={
                            "scoped_idea_json": scope.model_dump_json(indent=2),
                            "market_query": scope.market_query,
                            "cached_evidence_block": format_cached_evidence(cached),
                        }
                    )
                findings = _extract_model(result, MarketFindings)
            except _BRANCH_CONTROL_FLOW:
                raise
            except Exception as exc:
                findings = _degraded_findings(MarketFindings, "market", exc)
            self.state.market = findings
            self._index_evidence("market", scope, namespace, tool_results)
        return findings

    @listen("scope_approved")
    def research_sentiment(self) -> SentimentFindings:
        """Run the sentiment branch in a Flow-managed worker thread."""
        with self._branch_turn("sentiment"):
            scope = _require(self.state.scope, "scope")
            namespace = resolve_namespace(self.state.namespace)
            tool_results: list[CapturedToolResult] = []
            try:
                with capture_tool_results("sentiment") as tool_results:
                    result = self.crew_factories.sentiment().kickoff(
                        inputs={
                            "scoped_idea_json": scope.model_dump_json(indent=2),
                            "community_queries_block": "\n".join(
                                scope.community_queries
                            ),
                        }
                    )
                findings = _extract_model(result, SentimentFindings)
            except _BRANCH_CONTROL_FLOW:
                raise
            except Exception as exc:
                findings = _degraded_findings(SentimentFindings, "sentiment", exc)
            self.state.sentiment = findings
            self._index_evidence("sentiment", scope, namespace, tool_results)
        return findings

    @listen("scope_approved")
    def research_feasibility(self) -> FeasibilityFindings:
        """Run the feasibility branch in a Flow-managed worker thread."""
        with self._branch_turn("feasibility"):
            scope = _require(self.state.scope, "scope")
            namespace = resolve_namespace(self.state.namespace)
            cached = self._cached_evidence("feasibility", scope, namespace)
            tool_results: list[CapturedToolResult] = []
            try:
                with capture_tool_results("feasibility") as tool_results:
                    result = self.crew_factories.feasibility().kickoff(
                        inputs={
                            "scoped_idea_json": scope.model_dump_json(indent=2),
                            "tech_queries_block": "\n".join(scope.tech_queries),
                            "cached_evidence_block": format_cached_evidence(cached),
                        }
                    )
                findings = _extract_model(result, FeasibilityFindings)
            except _BRANCH_CONTROL_FLOW:
                raise
            except Exception as exc:
                findings = _degraded_findings(
                    FeasibilityFindings, "feasibility", exc
                )
            self.state.feasibility = findings
            self._index_evidence("feasibility", scope, namespace, tool_results)
        return findings

    @listen(and_(research_market, research_sentiment, research_feasibility))
    def synthesize(self) -> Verdict:
        """Join all three branches before applying the deterministic rubric."""
        return self._run_synthesis("")

    @listen("verdict_revise")
    def revise_verdict(self) -> Verdict:
        """Re-run synthesis using the operator's requested correction."""
        # The same re-arm, for the verdict gate: `review_verdict` listens on
        # `or_(synthesize, revise_verdict)` and `route_verdict` emits
        # "verdict_revise", which is not in that condition, so CrewAI will not
        # re-arm it either. See `revise_scope` for why this is needed at all and
        # why it is a private call.
        self._discard_or_listener(FlowMethodName("review_verdict"))
        return self._run_synthesis(self.state.verdict_revision)

    @human_feedback(
        message=(
            "Review the scored verdict. Reply with JSON using decision=approve, or "
            "decision=revise plus feedback and an optional edited verdict object."
        ),
        emit=None,
        # `llm=None`, deliberately. `emit=None` means CrewAI never collapses the
        # reply to an outcome, so the gate LLM is unreachable - but
        # `_run_human_feedback_step` deserializes it *before* it checks `emit`
        # (crewai/flow/runtime/__init__.py:3608-3611), so naming a model here
        # built two OpenAICompatibleCompletion clients per run, four httpx
        # pools and four SSL trust stores, and discarded all of it: 0.73s of
        # measured wall clock buying nothing. `_validate_human_feedback_options`
        # only requires `llm` when `emit is not None`
        # (crewai/flow/human_feedback.py:211-218), so None is legal here.
        llm=None,
        provider=FEEDBACK_PROVIDER,
    )
    @listen(or_(synthesize, revise_verdict))
    def review_verdict(self, _: Verdict) -> str:
        """Pause after synthesis so the operator can approve or revise it."""
        return _require(self.state.verdict, "verdict").model_dump_json(indent=2)

    @router(review_verdict)
    def route_verdict(
        self, result: HumanFeedbackResult
    ) -> Literal["verdict_approved", "verdict_revise"]:
        """Route the structured verdict reply without an LLM call."""
        self.state.verdict_gate_reply = result.feedback
        payload = _gate_payload(result.feedback)
        edited_verdict = payload.get("verdict")
        if isinstance(edited_verdict, dict):
            # Unreachable from a client today - every `Verdict` field is
            # `derived`, so `_feedback` never builds a verdict edit - but the
            # scope gate's version of this line survived precisely because
            # nobody checked the twin. Defensive, and cheap.
            try:
                self.state.verdict = Verdict.model_validate(edited_verdict)
            except ValidationError as error:
                self.state.verdict_edit_error = _edit_error_summary(error)
        decision = str(payload.get("decision", "approve")).strip().lower()
        # Same bound, same reasoning as `route_scope`, and the counters are
        # per-gate: five revises spent on the scope leave all five available on
        # the verdict. They are separate conversations about separate artefacts
        # and they re-run different crews.
        if decision == "revise" and claim_revise_turn(self.state, "verdict"):
            self.state.verdict_revision = str(
                payload.get("feedback") or result.feedback
            )
            self.state.verdict_route = "verdict_revise"
            return "verdict_revise"
        self.state.verdict_route = "verdict_approved"
        return "verdict_approved"

    @listen("verdict_approved")
    def write_report(self) -> ValidationReport:
        """Turn the deterministic verdict and its evidence into the final brief."""
        scope = _require(self.state.scope, "scope")
        market = _require(self.state.market, "market findings")
        sentiment = _require(self.state.sentiment, "sentiment findings")
        feasibility = _require(self.state.feasibility, "feasibility findings")
        verdict = _require(self.state.verdict, "verdict")
        tool_urls = set().union(
            findings_urls(market),
            findings_urls(sentiment),
            findings_urls(feasibility),
        )
        result = self.crew_factories.report(verdict, tool_urls).kickoff(
            inputs={
                "scoped_idea_json": scope.model_dump_json(indent=2),
                "market_findings_json": market.model_dump_json(indent=2),
                "sentiment_findings_json": sentiment.model_dump_json(indent=2),
                "feasibility_findings_json": feasibility.model_dump_json(indent=2),
                "verdict_json": verdict.model_dump_json(indent=2),
            }
        )
        self.state.report = _extract_model(result, ValidationReport)
        return self.state.report

    @listen(write_report)
    def persist(self) -> ValidationReport:
        """Write only the human-readable report body to output/validation.md."""
        report = _require(self.state.report, "validation report")
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(report.markdown_body, encoding="utf-8")
        return report

    def _run_synthesis(self, human_override: str) -> Verdict:
        scope = _require(self.state.scope, "scope")
        market = _require(self.state.market, "market findings")
        sentiment = _require(self.state.sentiment, "sentiment findings")
        feasibility = _require(self.state.feasibility, "feasibility findings")
        result = self.crew_factories.synthesis(
            market,
            sentiment,
            feasibility,
        ).kickoff(
            inputs={
                "scoped_idea_json": scope.model_dump_json(indent=2),
                "market_findings_json": market.model_dump_json(indent=2),
                "sentiment_findings_json": sentiment.model_dump_json(indent=2),
                "feasibility_findings_json": feasibility.model_dump_json(indent=2),
                "human_override": human_override,
            }
        )
        self.state.verdict = _extract_model(result, Verdict)
        # Published here rather than in `synthesize`, and that is the whole
        # reason this helper is the emit site. `synthesize` and `revise_verdict`
        # are two entry points to one computation, and a verdict is only real
        # once `_extract_model` has run: that call is what turns the
        # Synthesist's text into a `Verdict`, which is what runs
        # `compute_mechanical_result` and overwrites the model's arithmetic.
        # Emitting from `synthesize` would publish the first score and stay
        # silent through every correction the operator asked for, leaving a
        # stale composite on screen and in `GET /api/runs/{id}` after a revise
        # deliberately changed it. Emitting from both would duplicate the first.
        #
        # The one recomputation this does not cover is `route_verdict`
        # revalidating an operator-supplied `verdict` object on an *approve*.
        # That path is unreachable through the service - `_gate_derived_keys`
        # prunes every field of the verdict gate, so no edit can be sent - and a
        # revise, which is the lever the gate does offer, comes back through
        # here.
        publish_verdict(self, self.state.verdict)
        return self.state.verdict

    def _cached_evidence(
        self,
        branch: BranchName,
        scope: ScopedIdea,
        namespace: str,
    ) -> list[dict[str, Any]]:
        try:
            return lookup_branch_cache(
                scope,
                branch,
                namespace,
                feasibility_enabled=self.state.feasibility_cache_enabled,
            )
        except Exception:
            return []

    def _index_evidence(
        self,
        branch: BranchName,
        scope: ScopedIdea,
        namespace: str,
        tool_results: list[CapturedToolResult],
    ) -> None:
        try:
            index_captured_evidence(
                tool_results,
                branch=branch,
                scope=scope,
                source_run_id=self.state.source_run_id,
                namespace=namespace,
            )
        except Exception:
            pass


def _print_result(result: ValidationReport | HumanFeedbackPending) -> None:
    if isinstance(result, HumanFeedbackPending):
        print(
            json.dumps(
                {
                    "status": "pending_human_feedback",
                    "flow_id": result.context.flow_id,
                    "gate": result.context.method_name,
                    "message": result.context.message,
                    "output": result.context.method_output,
                },
                indent=2,
            )
        )
        return
    print(result.markdown_body)


def validate(
    idea: str | None = None,
    *,
    no_gates: bool = False,
    namespace: str | None = None,
    feasibility_cache_enabled: bool | None = None,
    sequential_branches: bool | None = None,
    crew_factories: ValidatorCrewFactories | None = None,
) -> ValidationReport | HumanFeedbackPending:
    """Run or start the validator without requiring the web studio."""
    if idea is None:
        return _run_cli()
    if not idea.strip():
        raise ValueError("idea must contain non-whitespace text")
    flow = ValidatorFlow(
        crew_factories=crew_factories or ValidatorCrewFactories(),
    )
    inputs: dict[str, Any] = {
        "idea": idea.strip(),
        "no_gates": no_gates,
        "namespace": namespace or "",
    }
    if feasibility_cache_enabled is not None:
        inputs["feasibility_cache_enabled"] = feasibility_cache_enabled
    # Left out entirely when unset, so the state default - and therefore every
    # existing caller - keeps the parallel fan-out.
    if sequential_branches is not None:
        inputs["sequential_branches"] = sequential_branches
    result = flow.kickoff(inputs=inputs)
    if isinstance(result, HumanFeedbackPending):
        return result
    return _extract_model(result, ValidationReport)


def _run_cli() -> ValidationReport | HumanFeedbackPending:
    parser = argparse.ArgumentParser(description="Validate a startup idea.")
    parser.add_argument("--idea", help="One-line startup idea to validate.")
    parser.add_argument("--resume", metavar="FLOW_ID", help="Resume a pending gate.")
    parser.add_argument(
        "--feedback",
        default=json.dumps({"decision": "approve"}),
        help="Structured JSON feedback supplied when resuming.",
    )
    parser.add_argument(
        "--no-gates",
        "--auto-approve",
        action="store_true",
        dest="no_gates",
        help="Approve both gates without pausing; intended for tests and CI.",
    )
    parser.add_argument(
        "--namespace",
        help="Non-sensitive user/session namespace seed for cache isolation.",
    )
    parser.add_argument(
        "--feasibility-cache",
        action="store_true",
        default=None,
        help="Use feasibility cache as a GitHub rate-limit shock absorber.",
    )
    parser.add_argument(
        "--sequential-branches",
        action="store_true",
        default=None,
        dest="sequential_branches",
        help=(
            "Run the three research branches one at a time instead of in "
            "parallel. Same six agents and same graph; worse latency."
        ),
    )
    args = parser.parse_args()

    if args.resume:
        flow = ValidatorFlow.from_pending(args.resume)
        flow.state.no_gates = args.no_gates
        if args.sequential_branches is not None:
            flow.state.sequential_branches = args.sequential_branches
        resumed = flow.resume(args.feedback)
        result = (
            resumed
            if isinstance(resumed, HumanFeedbackPending)
            else _extract_model(resumed, ValidationReport)
        )
    else:
        if not args.idea:
            parser.error("--idea is required unless --resume is supplied")
        result = validate(
            args.idea,
            no_gates=args.no_gates,
            namespace=args.namespace,
            feasibility_cache_enabled=args.feasibility_cache,
            sequential_branches=args.sequential_branches,
        )

    _print_result(result)
    return result


if __name__ == "__main__":
    validate()