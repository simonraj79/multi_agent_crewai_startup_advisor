"""What a published builder graph actually runs with.

`builder_api.publish` compiles a user's canvas into a `crewai.flow/v1`
declaration and registers it; this is the other half - the thing
`RunRegistry._execute` calls once a run of that workflow is admitted. Until it
existed, `create_app` installed a runner that raised, so a user could compose,
wire, price, bound and publish a graph and then not run it.

**Why a runner per workflow rather than one runner for all of them.**
`RunExecution` carries `run_id`, `inputs`, the capture adapter, `flow_id`,
`persistence` and the cancel flag - and no `workflow_id`. The registry resolves
`runtime = self._runtime_for(record.workflow_id)` and then calls
`runtime.runner(execution)`, so the runner is never told which graph it is.
Rather than widen a frozen dataclass that four other runners share and then
have this one look the workflow back up out of a module global, `publish`
builds one `BuilderFlowRunner` per graph and closes it over the compiled
definition. The closure is also the natural home for the `FlowDefinition` that
`resume` must reuse - see below.

**Four things here fail SILENTLY if they are dropped**, which is why each one
is written out rather than assumed:

1. `builder_cancellation(execution.cancel_requested)` around both calls.
   `builder/runtime.py::checkpoint` reads that ContextVar at the head of every
   node entrypoint and raises `HookAborted`, which is the exception
   `RunRegistry._execute` already turns into CANCELLED rather than FAILED.
   The registry's own `InterceptionPoint.PRE_STEP` guard covers the same ground
   for declarative methods, so omitting this does *not* break cancel in the
   service path - it breaks it for a graph made of transforms and routers with
   no agent step to intercept, and for every caller that is not the registry.
2. The `FlowDefinition` built ONCE and handed to `from_pending`. Without
   `definition=`, `from_pending` falls through to `cls(persistence=...)` - a
   bare `Flow` with no methods on it - and the resume returns having produced
   nothing at all. No exception, no frame, no output.
3. `persistence=` on both paths. `from_pending` falls back to
   `default_flow_persistence()` when it is omitted, which is a stray SQLite
   file on container disk rather than the run's own store.
4. A no-cost path. It is a `use_crew_factories` swap and NOT a second runner:
   a double that diverges from its subject certifies nothing, and this repo has
   paid for that lesson twice (CLAUDE.md closed items 20 and 33). `SYNTHETIC=1`
   therefore runs the REAL compiled definition, through the REAL engine, over
   the REAL gates - only the thing that would have called a model is replaced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
import os
from typing import TYPE_CHECKING, Any, Callable

from brief_crew.builder.runtime import (
    DefaultCrewFactories,
    builder_cancellation,
    builder_state_sink,
    replay_source,
    use_crew_factories,
)
from brief_crew.service.credentials import credential_scope
from brief_crew.service.runner import RunExecution, Runner

if TYPE_CHECKING:  # pragma: no cover - typing only; the import is not free
    from brief_crew.builder.descriptor import BuilderWorkflow

__all__ = [
    "BuilderFlowRunner",
    "BuilderRunnerFactory",
    "SYNTHETIC_FAILURE_REASONS",
    "SyntheticBadCredential",
    "SyntheticCrewFactories",
    "SyntheticMalformedOutput",
    "SyntheticNodeFailure",
    "SyntheticRateLimitError",
    "SyntheticRefusal",
    "SyntheticToolTimeout",
    "parse_synthetic_failures",
    "synthetic_builder_runner",
]

#: What `create_app` and `create_builder_router` thread around instead of a
#: single `Runner`: `publish` calls it with the workflow it has just compiled
#: and registers whatever comes back.
BuilderRunnerFactory = Callable[["BuilderWorkflow"], Runner]


@dataclass(slots=True)
class BuilderFlowRunner:
    """Run and resume ONE compiled builder graph on the service persistence.

    Field for field the shape of `ValidatorFlowRunner`, deliberately: the lazy
    import inside each method, `inputs["id"]`, and `crew_factories` as an
    injected field defaulting to the real thing. That last one is the whole
    no-cost seam, and it is a seam the paid path uses too, so it cannot rot.
    """

    workflow: "BuilderWorkflow"
    crew_factories: Any = None
    #: Parsed on first use and kept. Deliberately not settable through `init=`:
    #: a caller handing in a definition that is not this workflow's own is
    #: exactly the mismatch `resume` would then rebuild a flow from.
    _definition: Any = field(default=None, init=False, repr=False, compare=False)

    def __call__(self, execution: RunExecution) -> Any:
        from crewai.flow.flow import Flow

        derived = dict(execution.derived or {})
        flow = Flow.from_declaration(
            contents=self._definition_for(derived),
            persistence=execution.persistence,
        )
        inputs = dict(execution.inputs)
        # Assigned AFTER the copy, so a request body that smuggled an `id` key
        # cannot choose the flow's identity: `flow_id == run_id` is what every
        # gate reply, every `from_pending` resume and every restart recovery
        # resolves through.
        inputs["id"] = execution.flow_id or execution.run_id
        self._emit_plan(execution)
        # `credential_scope` is the plan 01 D5 seam: the run's OWNER and the
        # service store, scoped over this thread and every worker CrewAI
        # starts from it, so `resolve_credential` inside an entrypoint answers
        # for this person and nobody else. An execution with no owner resolves
        # nothing, which is the right answer for a run nobody signed in for.
        with builder_cancellation(execution.cancel_requested):
            with credential_scope(
                user_id=execution.user_id, persistence=execution.persistence
            ):
                # The saved outputs a derived plan replays, scoped over the
                # kickoff and nothing else. An ordinary run enters this with an
                # empty mapping, which is what makes `replay_output` fail loudly
                # rather than quietly if a plain plan ever compiled one.
                with replay_source(derived.get("values"), derived.get("errors")):
                    with builder_state_sink(self._state_sink(execution)):
                        with use_crew_factories(self._factories()):
                            return flow.kickoff(inputs=inputs)

    def _definition_for(self, derived: Mapping[str, Any]) -> Any:
        """This graph's declaration, or the DERIVED plan when one was asked for.

        A derived plan is compiled fresh per request and cached nowhere: it is
        never published, never priced onto a document and never rehydrated at
        boot, so the `_definition` field above deliberately does not hold it -
        one run's resume point must not become the next run's flow.
        """

        if not derived.get("node_id"):
            return self._flow_definition()
        from crewai.flow.flow_definition import FlowDefinition

        from brief_crew.builder.compiler import compile_replay_plan

        compiled = compile_replay_plan(
            self.workflow.document,
            node_id=str(derived["node_id"]),
            mode=str(derived.get("mode") or "resume_from"),
            source=str(derived.get("source") or "run"),
        )
        return FlowDefinition.from_declaration(contents=compiled.definition)

    def _emit_plan(self, execution: RunExecution) -> None:
        """C6's `stage` frames - the whole plan, before the first node runs.

        One per topological layer, all at kickoff, so a console can draw the
        route before anything has happened rather than discovering it a node at
        a time. Emitted from the RUNNER because it is a statement about the
        graph rather than about any node in it, and the runner is the one place
        that holds the document and the capture adapter at once.

        Best effort: a run whose plan could not be narrated still runs.
        """

        from brief_crew.builder.descriptor import plan_layers
        from brief_crew.events import FrameKind, UIEventType

        try:
            layers = plan_layers(self.workflow.document)
        except Exception:  # noqa: BLE001 - telemetry must not fail a run
            return
        labels = {
            node.id: (node.label or node.id) for node in self.workflow.document.nodes
        }
        total = len(layers)
        for index, layer in enumerate(layers, start=1):
            execution.capture.emit(
                kind=FrameKind.RUN_STATE,
                event_type=UIEventType.NODE_START,
                node_id=self.workflow.node_registry.workflow_node_id,
                message=f"Stage {index} of {total}",
                details={
                    "stage": "plan",
                    "index": index,
                    "of": total,
                    "label": ", ".join(labels.get(node_id, node_id) for node_id in layer),
                    "node_ids": list(layer),
                },
            )

    def resume(self, execution: RunExecution, *, context: Any, feedback: str) -> Any:
        from crewai.flow.flow import Flow

        flow = Flow.from_pending(
            context.flow_id,
            execution.persistence,
            definition=self._flow_definition(),
        )
        with builder_cancellation(execution.cancel_requested):
            with credential_scope(
                user_id=execution.user_id, persistence=execution.persistence
            ):
                with builder_state_sink(self._state_sink(execution)):
                    with use_crew_factories(self._factories()):
                        return flow.resume(feedback)

    def _state_sink(self, execution: RunExecution) -> Any:
        """Checkpoint each node's state to the run's own store, or nothing.

        **CrewAI persists nothing for an ordinary declarative run.** Measured:
        a two-node graph published, launched and completed on the service
        persistence leaves `flow_states` empty - the only writer is
        `save_pending_feedback`, on the pause a gate raises. So a run that never
        met a gate had no state at all afterwards, which is what
        `GET /api/runs/{id}/state?step=` reads and what a `resume_from` replays
        from. Both are plan 10's, so the write is.

        One row per node rather than one per run, deliberately: `?step=` is a
        question about a MOMENT, and a single end-of-run row would answer every
        step with the final state and look exactly as if it worked.

        `method_name` is the AUTHOR's node id, not the compiled identifier. This
        table's other writer stores a CrewAI method name and nothing joins the
        two columns, so the useful value here is the one a person asking "what
        did the state look like after `scoper`" already has.
        """

        persistence = execution.persistence
        flow_uuid = execution.flow_id or execution.run_id
        if persistence is None or not hasattr(persistence, "save_state"):
            return None

        def sink(node_id: str, state: Mapping[str, Any]) -> None:
            persistence.save_state(flow_uuid, node_id, dict(state))

        return sink

    def _flow_definition(self) -> Any:
        """This graph's declaration, parsed once and shared by both paths.

        `FlowDefinition.from_declaration` short-circuits on an instance of
        itself, so handing the parsed object to `Flow.from_declaration` costs
        nothing; handing it the raw dict re-validates the whole document on
        every launch and every resume instead.
        """

        if self._definition is None:
            from crewai.flow.flow_definition import FlowDefinition

            self._definition = FlowDefinition.from_declaration(
                contents=self.workflow.compiled.definition
            )
        return self._definition

    def _factories(self) -> Any:
        return self.crew_factories or DefaultCrewFactories()


class SyntheticNodeFailure(RuntimeError):
    """A failure the free path can be ASKED for, so the retry loop is testable.

    `SYNTHETIC_FAILURE` is the only way to exercise 10 D3 and D4 without money:
    every other route to a failing billable node either calls a model or
    replaces the factory with something that is not the one `SYNTHETIC=1`
    installs - and a double that diverges from its subject certifies nothing
    (CLAUDE.md closed items 20 and 33).
    """

    error_class = "synthetic-failure"


class SyntheticRateLimitError(SyntheticNodeFailure):
    """429. Retryable, and classified by `status_code` rather than by name.

    Deliberately the status path and not the name path: `_RETRYABLE_ERROR_NAMES`
    lists provider class names this repository does not own and cannot construct
    in a test, while `status_code` is the branch a wrapped provider error
    actually takes. Exercising the one that will fire in production is worth
    more than exercising the one that is easy to name.
    """

    error_class = "rate_limit"
    status_code = 429


class SyntheticRefusal(SyntheticNodeFailure):
    """A refusal. NOT retryable, and that is decision 16 made observable.

    A model that declines is a decision, not a transport fault; retrying it with
    a fallback model is asking a second judge until one agrees. This class
    carries no status and no listed name, so `_is_retryable` says no.
    """

    error_class = "refusal"


class SyntheticBadCredential(SyntheticNodeFailure):
    """401. 12 D8's first mode: the key the node names is not accepted.

    NOT retryable, and the status is what says so rather than a rule written
    here: 401 is absent from `_RETRYABLE_STATUS_CODES` because a rejected
    credential rejects identically on the second attempt and the only repair is
    a human changing the key. Its recovery path is the credential picker, then
    **Re-run from here**.

    Raised from the FACTORY, which is where a real one lands: CrewAI builds the
    provider client at construction, so a bad key fails before a token is spent.
    """

    error_class = "auth"
    status_code = 401


class SyntheticToolTimeout(SyntheticNodeFailure):
    """408. 12 D8's second mode: a tool or MCP call ran past its `timeout`.

    Retryable, by the status rather than by the name, for the reason
    `SyntheticRateLimitError` already gives: `status_code` is the branch a
    wrapped provider or transport error actually takes, and exercising the one
    that will fire in production is worth more than the one that is easy to
    name. 408 is Request Timeout, which is what a timed-out call is.
    """

    error_class = "tool_timeout"
    status_code = 408


class SyntheticMalformedOutput(SyntheticNodeFailure):
    """12 D8's fourth mode: the response failed the node's `output_schema`.

    NOT retryable by the node loop, and this is the one exclusion in
    `_RETRYABLE_ERROR_NAMES`'s comment that is easiest to get wrong. CrewAI
    already loops a guardrail with the agent's own llm
    (`guardrail_max_retries`), so a whole-node retry on top would multiply an
    answer that has already been asked for twice - and the repair is the
    schema or the retry count, not another attempt at the same prompt.
    """

    error_class = "schema"


#: `SYNTHETIC_FAILURE` reasons, as the exceptions they raise.
#:
#: FIVE of 12 D8's six modes. The sixth, `cyclic_graph`, has no entry here on
#: purpose: a loop closed by a non-router is refused by `bounds.py` at validate
#: and again at publish, so it NEVER RUNS and there is no node for a factory to
#: fail. A reason that produced a run would be a synthetic double diverging from
#: its subject, which is the one thing this module exists not to do.
SYNTHETIC_FAILURE_REASONS: Mapping[str, type[SyntheticNodeFailure]] = {
    "bad_key": SyntheticBadCredential,
    "malformed_output": SyntheticMalformedOutput,
    "rate_limit": SyntheticRateLimitError,
    "refusal": SyntheticRefusal,
    "tool_timeout": SyntheticToolTimeout,
}


@dataclass(frozen=True, slots=True)
class _FailurePlan:
    """One parsed `SYNTHETIC_FAILURE` entry: which node, what, how many times."""

    node_id: str | None
    error: type[SyntheticNodeFailure]
    times: int | None

    def applies_to(self, node_id: str) -> bool:
        return self.node_id is None or self.node_id == node_id


def parse_synthetic_failures(
    raw: str | None, *, default_node: str | None = None
) -> tuple[_FailurePlan, ...]:
    """`SYNTHETIC_FAILURE` as plans. Anything unreadable is NO failure.

    The grammar is `[node:]reason[:times]`, comma separated:

    * `rate_limit` - every billable node fails, every time;
    * `b:rate_limit` - node `b` fails, every time;
    * `b:rate_limit:2` - node `b` fails its first two attempts and then works,
      which is the shape that proves a FALLBACK model succeeded rather than
      merely that three attempts happened.

    `default_node` is `SYNTHETIC_FAILURE_NODE` (12 D8), and it applies only to
    an entry that names no node of its own. It exists because the E2E and a
    hand-driven browser session set one knob at the shell and want ONE node to
    fail - on a graph whose ids they did not write, the `node:` prefix is a
    thing you have to go and look up, and "every billable node fails" makes a
    six-node template unreadable at exactly the moment a critic is reading it.
    An entry that does name a node still wins, so nothing already written moves.

    Unreadable input yields nothing rather than raising: this is a testing knob
    read on a code path that runs for real, and a typo in it must not be how a
    free backend refuses to start.
    """

    plans: list[_FailurePlan] = []
    for entry in str(raw or "").split(","):
        parts = [part.strip() for part in entry.split(":") if part.strip()]
        if not parts:
            continue
        node_id: str | None = None
        if parts[0] not in SYNTHETIC_FAILURE_REASONS and len(parts) > 1:
            node_id, parts = parts[0], parts[1:]
        error = SYNTHETIC_FAILURE_REASONS.get(parts[0] if parts else "")
        if error is None:
            continue
        times: int | None = None
        if len(parts) > 1:
            try:
                times = max(0, int(parts[1]))
            except ValueError:
                times = None
        plans.append(
            _FailurePlan(
                node_id=node_id if node_id is not None else (default_node or None),
                error=error,
                times=times,
            )
        )
    return tuple(plans)


class _SyntheticCrew:
    """Whatever a real Crew would have cost, for free - and in the same shape.

    JSON rather than prose, because `gate_payload` parses a JSON object into
    the fields an operator edits and turns anything else into one `summary`
    blob. A double that produced prose would leave every synthetic gate
    rendering a single read-only string, and the gate form - the half of the
    builder that most needs exercising for free - would be untestable.
    """

    __slots__ = ("_node_id", "_produced_by", "_tier")

    def __init__(self, *, node_id: str, produced_by: str, tier: str) -> None:
        self._node_id = node_id
        self._produced_by = produced_by
        self._tier = tier

    def kickoff(self, inputs: Mapping[str, Any] | None = None) -> str:
        payload = json.dumps(
            {
                "node_id": self._node_id,
                "produced_by": self._produced_by,
                "tier": self._tier,
                "summary": f"Synthetic output for {self._node_id}; no model was called.",
                # Echoed so a test - and an operator watching a free run - can
                # see that the upstream node's value actually reached the
                # prompt. Bounded already, by admission and by `seed_input`.
                "prompt_inputs": {
                    str(key): str(value) for key, value in dict(inputs or {}).items()
                },
            },
            sort_keys=True,
        )
        self._speak(payload)
        return payload

    def _speak(self, text: str) -> None:
        """The chunk frames and the `utterance` a real completion would raise.

        Without this a published graph ran on the free path and said NOTHING:
        `LLMStreamChunkEvent` and `LLMCallCompletedEvent` are raised by CrewAI's
        own LLM, and a synthetic crew never builds one - so the dialogue rail,
        which exists to show what an agent said, was blank for every E2E run,
        every local `SYNTHETIC=1` session and every capture. That is the
        divergence CLAUDE.md's closed items 20 and 33 both record: a double
        that cannot produce the thing under test certifies nothing.

        Shapes copied from `events/serializer.py` (`stage="utterance"`) and
        `events/adapter.py::_merged_chunk` (a coalesced chunk carries
        `call_id`, `stage` and `chunk`, and nothing else). Emitted through
        `runtime._emit_frame`, which is what every other builder-side frame
        goes through and which already degrades to a debug log if no capture
        context is scoped - telemetry must never fail a run.

        AND THE TOKEN FRAME, WHICH WAS MISSING - the same defect
        `SyntheticValidatorRunner._token_usage` records one layer up, met a
        second time in the half of the product where a stranger's graph spends
        the money. Chunks and an `utterance` carrying `prompt_tokens` reached
        the dialogue rail, which rendered `512 in - 78 out`; the client's
        `applyTokenUsage` fires on `kind === 'token'` and nothing else, so the
        status panel beside it read `TOKENS 0 - $0.0000` on a COMPLETED builder
        run. Emitting TOKEN also gets METRICS for free: `_on_frames` routes a
        token frame into `_record_usage`, which is what marks the run's usage
        dirty and what `metrics_frame` snapshots, so `CALLS` and `ELAPSED` come
        back through the production path rather than a second one written for
        the double.

        THE MODEL IS RESOLVED FROM THE TIER, and that is not cosmetic either.
        This double reported `model: "cheap"` - a tier name where the serializer
        writes a model id - so nothing downstream could price it, and
        `compute_cost_usd("cheap", ...)` correctly answers `None`. `_model_for`
        is the same tier -> constant map the real factory uses, and the
        `openrouter/` prefix is dropped because CrewAI's `LLM.__new__` strips it
        before `LLMCallCompletedEvent` is raised - which is why the paid run's
        frames say `google/gemini-3.5-flash-lite:nitro`. `compute_cost_usd`
        resolves both spellings, so the price is right either way; the SPELLING
        is what a double has to match.
        """

        from brief_crew.builder.runtime import _emit_frame, _model_for
        from brief_crew.events.models import FrameKind, UIEventType

        call_id = f"synthetic:{self._node_id}"
        # The tier's own constant, minus the provider prefix - see the docstring.
        model = _model_for(str(self._tier)).split("/", 1)[-1]
        size = max(1, -(-len(text) // 3))
        for start in range(0, len(text), size):
            _emit_frame(
                FrameKind.LLM,
                UIEventType.MODEL_CALL,
                node_id=self._node_id,
                message="Model stream chunk",
                details={
                    "stage": "chunk",
                    "call_id": call_id,
                    "chunk": text[start : start + size],
                },
            )
        prompt_tokens = 512
        completion_tokens = max(1, len(text) // 4)
        _emit_frame(
            FrameKind.LLM,
            UIEventType.MODEL_CALL,
            node_id=self._node_id,
            message=f"{model} said",
            details={
                "stage": "utterance",
                "call_id": call_id,
                "text": text,
                "truncated": False,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "model": model,
            },
        )
        self._bill(call_id, model, prompt_tokens, completion_tokens)

    def _bill(
        self,
        call_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """The TOKEN frame, last, exactly as the serializer orders it.

        Chunks, then `utterance`, then TOKEN - `events/serializer.py` drafts
        them in that order for one call, and a console that renders the spend
        before the words would be a double teaching the client a sequence the
        real path never produces.

        `cost_usd` is NESTED inside `usage` as well as sitting beside it, and
        that duplication is load-bearing: the client reads
        `details.usage.cost_usd` and narrows to `usage` the moment that key is
        an object, so a cost written only alongside totals `$0.0000` with every
        token frame present. CLAUDE.md section 8 records that as one of the two
        independent bugs behind the first paid run's `$0.00`.

        `compute_cost_usd` rather than a literal, so a synthetic run prices the
        way a paid one does and a `PRICES` edit moves both. It returns `None`
        for a model with no price on file, which is not `0.0` - the same
        distinction the real path draws, and the reason a tier name here used to
        make the panel unpriceable rather than merely wrong.
        """

        from brief_crew.builder.runtime import _emit_frame
        from brief_crew.config import compute_cost_usd
        from brief_crew.events.models import FrameKind, UIEventType

        cost_usd = compute_cost_usd(model, prompt_tokens, completion_tokens)
        usage: dict[str, Any] = {
            "successful_requests": 1,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "call_count": 1,
            "cost_usd": cost_usd,
        }
        _emit_frame(
            FrameKind.TOKEN,
            UIEventType.MODEL_CALL,
            node_id=self._node_id,
            message="Token usage recorded",
            details={
                "call_id": call_id,
                "model": model,
                "usage": usage,
                "cost_usd": cost_usd,
            },
        )


class SyntheticCrewFactories:
    """The `CrewFactories` protocol, satisfied without OpenRouter.

    This is the ONLY thing `SYNTHETIC=1` replaces on a builder run. The
    compiled definition, the engine, the gates, the routers, the revise
    counters, the persistence and the cancellation are all the production ones.

    `SYNTHETIC_FAILURE` makes a node fail on demand, and
    `SYNTHETIC_FAILURE_NODE` says which one when the entry does not - see
    `parse_synthetic_failures`. BOTH are read PER INSTANCE rather than at
    import, so a test sets them with `patch.dict(os.environ, ...)` and a free
    backend picks them up on the next publish without a restart. That per-
    instance read is what makes 12 criterion 5 possible at all: a critic
    triggering six failure modes from a browser would otherwise be restarting
    the backend six times.

    `calls` records `(node_id, model)` per built crew, in order. It is the only
    way to see WHICH model an attempt ran on: the fallback is chosen inside the
    entrypoint and never reaches a frame except as a name, so without this a
    test could prove three attempts happened and not that the third was the
    fallback.
    """

    def __init__(self, failures: str | None = None, *, node: str | None = None) -> None:
        self.plans = parse_synthetic_failures(
            failures if failures is not None else os.getenv("SYNTHETIC_FAILURE"),
            default_node=node if node is not None else os.getenv("SYNTHETIC_FAILURE_NODE"),
        )
        self.calls: list[tuple[str, str]] = []
        self._attempts: dict[str, int] = {}

    def _record(self, node_id: str, model: str) -> None:
        """Count this attempt, and raise if `SYNTHETIC_FAILURE` says to.

        Raised from the FACTORY rather than from `kickoff`, because that is
        where a real credential refusal, a bad model id and a constructor
        failure all land - and those are the failures a builder graph actually
        meets before any token is spent.
        """

        self.calls.append((node_id, model))
        attempt = self._attempts.get(node_id, 0) + 1
        self._attempts[node_id] = attempt
        for plan in self.plans:
            if not plan.applies_to(node_id):
                continue
            if plan.times is not None and attempt > plan.times:
                continue
            raise plan.error(
                f"SYNTHETIC_FAILURE: {node_id} attempt {attempt} "
                f"({plan.error.__name__})"
            )

    def agent_crew(
        self,
        *,
        node_id: str,
        agent_id: str,
        tier: str,
        tools: Sequence[str],
        max_iter: int,
        guardrail_max_retries: int,
        # Accepted and ignored: a synthetic run resolves the author's credential
        # (the vault is a database read, not a network call) and then calls no
        # model, so the key has nowhere to go.
        api_key: str | None = None,
        **_: Any,
    ) -> _SyntheticCrew:
        self._record(node_id, tier)
        return _SyntheticCrew(node_id=node_id, produced_by=agent_id, tier=tier)

    def crew(
        self,
        *,
        node_id: str,
        crew_id: str,
        tier: str,
        max_iter: int,
        guardrail_max_retries: int,
        **_: Any,
    ) -> _SyntheticCrew:
        self._record(node_id, tier)
        return _SyntheticCrew(node_id=node_id, produced_by=crew_id, tier=tier)

    # The two AUTHORED builders (09 D1). Without them `SYNTHETIC=1` could run a
    # library graph and not the thing the gauntlet is about - and the E2E suite,
    # the rubric-11 harness and every free local run would all be exercising the
    # half of the compiler that was never the hard part.
    #
    # `produced_by` is the author's own ROLE rather than a registry id, which is
    # what makes the synthetic output identify the node the way a real one would.
    def authored_agent_crew(self, *, node_id: str, spec: Any) -> _SyntheticCrew:
        self._record(node_id, str(dict(spec.llm or {}).get("model") or spec.tier))
        return _SyntheticCrew(node_id=node_id, produced_by=spec.role, tier=spec.tier)

    def authored_crew(self, *, node_id: str, spec: Any) -> _SyntheticCrew:
        self._record(node_id, str(spec.process))
        return _SyntheticCrew(
            node_id=node_id,
            produced_by=f"{spec.process} crew of {len(spec.members)}",
            tier=spec.tier,
        )


def synthetic_builder_runner(workflow: "BuilderWorkflow") -> BuilderFlowRunner:
    """The factory `create_app(synthetic=True)` installs."""

    return BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
