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
from typing import TYPE_CHECKING, Any, Callable

from brief_crew.builder.runtime import (
    DefaultCrewFactories,
    builder_cancellation,
    use_crew_factories,
)
from brief_crew.service.credentials import credential_scope
from brief_crew.service.runner import RunExecution, Runner

if TYPE_CHECKING:  # pragma: no cover - typing only; the import is not free
    from brief_crew.builder.descriptor import BuilderWorkflow

__all__ = [
    "BuilderFlowRunner",
    "BuilderRunnerFactory",
    "SyntheticCrewFactories",
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

        flow = Flow.from_declaration(
            contents=self._flow_definition(),
            persistence=execution.persistence,
        )
        inputs = dict(execution.inputs)
        # Assigned AFTER the copy, so a request body that smuggled an `id` key
        # cannot choose the flow's identity: `flow_id == run_id` is what every
        # gate reply, every `from_pending` resume and every restart recovery
        # resolves through.
        inputs["id"] = execution.flow_id or execution.run_id
        # `credential_scope` is the plan 01 D5 seam: the run's OWNER and the
        # service store, scoped over this thread and every worker CrewAI
        # starts from it, so `resolve_credential` inside an entrypoint answers
        # for this person and nobody else. An execution with no owner resolves
        # nothing, which is the right answer for a run nobody signed in for.
        with builder_cancellation(execution.cancel_requested):
            with credential_scope(
                user_id=execution.user_id, persistence=execution.persistence
            ):
                with use_crew_factories(self._factories()):
                    return flow.kickoff(inputs=inputs)

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
        # Accepted and ignored: a synthetic run resolves the author's credential
        # (the vault is a database read, not a network call) and then calls no
        # model, so the key has nowhere to go.
        api_key: str | None = None,
    ) -> _SyntheticCrew:
        return _SyntheticCrew(node_id=node_id, produced_by=agent_id, tier=tier)

    def crew(
        self,
        *,
        node_id: str,
        crew_id: str,
        tier: str,
        max_iter: int,
        guardrail_max_retries: int,
    ) -> _SyntheticCrew:
        return _SyntheticCrew(node_id=node_id, produced_by=crew_id, tier=tier)


def synthetic_builder_runner(workflow: "BuilderWorkflow") -> BuilderFlowRunner:
    """The factory `create_app(synthetic=True)` installs."""

    return BuilderFlowRunner(workflow, crew_factories=SyntheticCrewFactories())
