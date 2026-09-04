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
    "SyntheticCrewFactories",
    "SyntheticNodeFailure",
    "SyntheticRateLimitError",
    "SyntheticRefusal",
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
                with replay_source(derived.get("values")):
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
                with use_crew_factories(self._factories()):
                    return flow.resume(feedback)

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

    status_code = 429


class SyntheticRefusal(SyntheticNodeFailure):
    """A refusal. NOT retryable, and that is decision 16 made observable.

    A model that declines is a decision, not a transport fault; retrying it with
    a fallback model is asking a second judge until one agrees. This class
    carries no status and no listed name, so `_is_retryable` says no.
    """


#: `SYNTHETIC_FAILURE` reasons, as the exceptions they raise.
SYNTHETIC_FAILURE_REASONS: Mapping[str, type[SyntheticNodeFailure]] = {
    "rate_limit": SyntheticRateLimitError,
    "refusal": SyntheticRefusal,
}


@dataclass(frozen=True, slots=True)
class _FailurePlan:
    """One parsed `SYNTHETIC_FAILURE` entry: which node, what, how many times."""

    node_id: str | None
    error: type[SyntheticNodeFailure]
    times: int | None

    def applies_to(self, node_id: str) -> bool:
        return self.node_id is None or self.node_id == node_id


def parse_synthetic_failures(raw: str | None) -> tuple[_FailurePlan, ...]:
    """`SYNTHETIC_FAILURE` as plans. Anything unreadable is NO failure.

    The grammar is `[node:]reason[:times]`, comma separated:

    * `rate_limit` - every billable node fails, every time;
    * `b:rate_limit` - node `b` fails, every time;
    * `b:rate_limit:2` - node `b` fails its first two attempts and then works,
      which is the shape that proves a FALLBACK model succeeded rather than
      merely that three attempts happened.

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
        plans.append(_FailurePlan(node_id=node_id, error=error, times=times))
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
        return json.dumps(
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


class SyntheticCrewFactories:
    """The `CrewFactories` protocol, satisfied without OpenRouter.

    This is the ONLY thing `SYNTHETIC=1` replaces on a builder run. The
    compiled definition, the engine, the gates, the routers, the revise
    counters, the persistence and the cancellation are all the production ones.

    `SYNTHETIC_FAILURE` makes a node fail on demand - see
    `parse_synthetic_failures`. It is read PER INSTANCE rather than at import,
    so a test sets it with `patch.dict(os.environ, ...)` and a free backend
    picks it up on the next publish without a restart.

    `calls` records `(node_id, model)` per built crew, in order. It is the only
    way to see WHICH model an attempt ran on: the fallback is chosen inside the
    entrypoint and never reaches a frame except as a name, so without this a
    test could prove three attempts happened and not that the third was the
    fallback.
    """

    def __init__(self, failures: str | None = None) -> None:
        self.plans = parse_synthetic_failures(
            failures if failures is not None else os.getenv("SYNTHETIC_FAILURE")
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
