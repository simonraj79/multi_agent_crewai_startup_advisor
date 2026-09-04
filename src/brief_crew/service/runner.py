"""Injectable production and synthetic run implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import time
from threading import Event
from typing import Any, Mapping, Protocol

from brief_crew.events import (
    FrameKind,
    FrameLevel,
    StreamSinkAdapter,
    UIEventType,
)
from brief_crew.events.verdict import (
    VERDICT_NODE_ID,
    verdict_frame_details,
    verdict_frame_message,
)
from brief_crew.schemas.validator import DimensionScore, Verdict


@dataclass(frozen=True, slots=True)
class RunExecution:
    run_id: str
    inputs: Mapping[str, Any]
    capture: StreamSinkAdapter
    flow_id: str | None = None
    persistence: Any = None
    cancel_requested: Event | None = None
    #: Who launched the run, or None for an unowned one. The builder runner
    #: scopes the credential vault to it (plan 01 D5): a credential is
    #: resolved for the run's owner and nobody else, so an execution that
    #: does not know its owner can resolve nothing - which is the right
    #: answer for the four runners that never read this field.
    user_id: str | None = None
    #: Which KIND of run this is - C7's `mode`. `run` for the four runners that
    #: never read it, and for every run written before the field existed.
    mode: str = "run"
    #: The derived-plan instruction for a `resume_from` or a `node_test`, or
    #: None for an ordinary run:
    #: `{"node_id": ..., "mode": "resume_from" | "node_test", "source": "run" |
    #: "test_input", "values": {node id: saved output}}`.
    #:
    #: A MAPPING and not a compiled plan, deliberately. The compile needs the
    #: workflow's own document, which only the builder runner holds - the
    #: registry does not have it and `RunExecution` is shared with four runners
    #: that must not learn what a `BuilderDocument` is. What travels here is the
    #: request, resolved and owner-checked; what compiles it is
    #: `BuilderFlowRunner`.
    derived: Mapping[str, Any] | None = None

    def checkpoint(self, step_name: str) -> None:
        """Abort at an explicit runner boundary when cancellation was requested."""
        if self.cancel_requested is not None and self.cancel_requested.is_set():
            from crewai.hooks import HookAborted

            raise HookAborted(f"cancelled before {step_name}")


#: Which research node calls which tool, and the query template it reports.
#: Keyed on the live Flow method names so the synthetic frames land on the same
#: graph nodes the real ones do - a double that attributes frames elsewhere
#: would let a node-attribution regression pass unnoticed.
_BRANCH_TOOLS: dict[str, tuple[str, str]] = {
    "research_market": ("research_market_landscape", "{idea} market landscape"),
    "research_sentiment": ("analyze_community_sentiment", "{idea}"),
    "research_feasibility": ("assess_technical_feasibility", "{idea}"),
}


def _synthetic_branch_delay_seconds() -> float:
    """Seconds each synthetic branch spends 'working'. Default 0.

    Read per call rather than at import so a test can set it with
    `patch.dict(os.environ, ...)` without reloading the module. Bounded at 120
    because this exists to reproduce a slow branch, not to hang a suite: an
    unbounded value here would be a foot-gun in the one place whose whole
    purpose is making a hang observable.
    """

    raw = os.getenv("SYNTHETIC_BRANCH_DELAY_SECONDS", "0").strip()
    try:
        return max(0.0, min(120.0, float(raw)))
    except ValueError:
        return 0.0


class Runner(Protocol):
    def __call__(self, execution: RunExecution) -> Any: ...


class ResumableRunner(Runner, Protocol):
    def resume(
        self,
        execution: RunExecution,
        *,
        context: Any,
        feedback: str,
    ) -> Any: ...


class BriefFlowRunner:
    """Run the existing BriefFlow; imported lazily to keep service imports light."""

    def __call__(self, execution: RunExecution) -> Any:
        from brief_crew.main import BriefFlow

        return BriefFlow().kickoff(inputs=dict(execution.inputs))


@dataclass(slots=True)
class ValidatorFlowRunner:
    """Run and resume ValidatorFlow with the service persistence backend."""

    crew_factories: Any = None

    def __call__(self, execution: RunExecution) -> Any:
        from brief_crew.validator_flow import ValidatorCrewFactories, ValidatorFlow

        factories = self.crew_factories or ValidatorCrewFactories()
        flow = ValidatorFlow(
            persistence=execution.persistence,
            crew_factories=factories,
        )
        inputs = dict(execution.inputs)
        inputs["id"] = execution.flow_id or execution.run_id
        return flow.kickoff(inputs=inputs)

    def resume(
        self,
        execution: RunExecution,
        *,
        context: Any,
        feedback: str,
    ) -> Any:
        from brief_crew.validator_flow import ValidatorCrewFactories, ValidatorFlow

        factories = self.crew_factories or ValidatorCrewFactories()
        flow = ValidatorFlow.from_pending(
            context.flow_id,
            execution.persistence,
            crew_factories=factories,
        )
        return flow.resume(feedback)


class SyntheticRunner:
    """Deterministic no-network runner for tests and local transport checks.

    The RUN_STATE frames below mirror
    `events/serializer.py::FieldBoundedSerializer.drafts` field for field -
    `{"status": ..., "inputs": ...}` on the way in and
    `{"status": ..., "result": ...}` on the way out. A double that emits a
    different shape is not a double: this one used to omit `status`, which is
    the key the Studio client reads, and the omission hid a real defect behind
    a green suite.
    """

    def __call__(self, execution: RunExecution) -> dict[str, Any]:
        topic = str(execution.inputs.get("topic", "synthetic topic"))
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_START,
            node_id="workflow",
            message="Synthetic run started",
            details={"status": "running", "inputs": {"topic": topic}},
        )
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_START,
            node_id="retrieve_cached",
            message="retrieve_cached started",
        )
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_END,
            node_id="retrieve_cached",
            message="retrieve_cached completed",
        )
        result = {"synthetic": True, "topic": topic}
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_END,
            node_id="workflow",
            message="Synthetic run completed",
            details={"status": "completed", "result": result},
            level=FrameLevel.INFO,
        )
        return result


SYNTHETIC_REPORT_MARKDOWN = """# Validation report - {verdict}

**Idea.** {idea}

> This report is produced by `SyntheticValidatorRunner`. No model was called
> and no source was retrieved. It exists so the console's report rendering is
> exercisable at zero cost.

## Score breakdown

| Dimension | Score | Weight | Note |
| --- | --- | --- | --- |
| Demand | {demand} | 0.30 | Synthetic placeholder |
| Market | {market} | 0.20 | Synthetic placeholder |
| Competitive room | {competitive_room} | 0.20 | Synthetic placeholder |
| Feasibility | {feasibility} | 0.15 | Synthetic placeholder |
| Headroom over free | {headroom_over_free} | 0.15 | Synthetic placeholder |

Composite **{composite}** at `{band}` confidence.

## Cheapest next test

1. Interview five target users.
2. Price the wedge against the free alternative.

## Sources

- [Synthetic market note](https://example.com/synthetic-market)
- [Synthetic HN thread](https://news.ycombinator.com/item?id=1)
"""


def _synthetic_report_markdown(idea: str) -> str:
    """The report body, agreeing with `_synthetic_verdict()` by construction."""
    verdict = _synthetic_verdict()
    return SYNTHETIC_REPORT_MARKDOWN.format(
        idea=idea,
        verdict=verdict.verdict,
        demand=verdict.demand.score,
        market=verdict.market.score,
        competitive_room=verdict.competitive_room.score,
        feasibility=verdict.feasibility.score,
        headroom_over_free=verdict.headroom_over_free.score,
        composite=f"{verdict.composite_score:.1f}",
        band=verdict.confidence_band,
    )


def _synthetic_verdict() -> Verdict:
    """A real `Verdict`, not a hand-written summary of one.

    Built through the schema so `compute_mechanical_result` decides the label,
    the composite, the band and the floors here exactly as it does on the paid
    path. A dict of plausible-looking numbers would be a double that certifies
    nothing - the same trap `_finish` records for the report body - and the
    arithmetic is precisely what this frame exists to carry.

    The inputs are chosen so the answer matches what this runner's verdict gate
    already shows: three coverages of 0.62 with a fresh median source age and
    all three branches reporting gives confidence 0.62, and five 3s give a
    composite of 6.0, which is NEEDS_WORK with no floor and no override.
    """

    dimension = DimensionScore(
        score=3,
        anchor_matched="Synthetic evidence supports a middling score.",
        evidence_urls=["https://example.com/synthetic-market"],
    )
    return Verdict(
        demand=dimension,
        market=dimension,
        competitive_room=dimension,
        feasibility=dimension,
        headroom_over_free=dimension,
        evidence_counts={"market_sources": 1, "sentiment_sources": 1},
        market_coverage=0.62,
        sentiment_coverage=0.62,
        feasibility_coverage=0.62,
        median_market_source_age_months=1,
        branches_ok=3,
        cheapest_next_test="Interview five target users.",
    )


# How many revisions this double honours per gate before treating a further one
# as an approval. `ValidatorFlow` makes the same trade through
# `claim_revise_turn` and `VALIDATOR_MAX_GATE_TURNS`, and for the same reason:
# refusing the reply would park the run at a gate with nothing left to do.
SYNTHETIC_MAX_REVISE_TURNS = 3


class SyntheticValidatorRunner:
    """Synthetic validator that exercises two durable pause/resume rounds."""

    def __call__(self, execution: RunExecution) -> Any:
        execution.checkpoint("scope_idea")
        idea = str(execution.inputs.get("idea", "synthetic idea"))
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_START,
            node_id="workflow",
            message="Synthetic validator started",
            details={"status": "running", "inputs": {"idea": idea}},
        )
        self._node(execution, "scope_idea", "Scoper")
        # Unattended mode runs straight through, the way ValidatorFlow does
        # when `ValidatorFeedbackProvider` answers its own gates. Without this
        # branch the toggle would be untestable at zero cost - the double would
        # pause where the real flow does not, which is the same divergence that
        # let the missing report body survive behind a green suite.
        if execution.inputs.get("no_gates"):
            return self._run_unattended(execution, idea)
        return self._pending(
            execution,
            method_name="confirm_scope",
            message="Confirm the parsed scope.",
            output={
                "startup_idea": idea,
                "category": "Synthetic market",
                "target_user": "Synthetic operator",
                "market_query": f"{idea} market",
            },
            stage=1,
        )

    def _run_unattended(self, execution: RunExecution, idea: str) -> Any:
        """Both gates auto-approved: every node runs, nothing pauses."""
        for node_id, label in (
            ("confirm_scope", "Confirm scope"),
            ("route_scope", "Scope router"),
        ):
            self._node(execution, node_id, label)
        execution.checkpoint("research_market")
        for node_id, label in (
            ("research_market", "Market Analyst"),
            ("research_sentiment", "Sentiment Analyst"),
            ("research_feasibility", "Feasibility Analyst"),
            ("synthesize", "Synthesist"),
        ):
            self._node(execution, node_id, label, idea)
        # Unattended is the mode where this frame is the ONLY way the score
        # reaches anyone: no verdict gate opens, so there is no `derived` block
        # to read it out of.
        self._verdict(execution)
        for node_id, label in (
            ("review_verdict", "Review verdict"),
            ("route_verdict", "Verdict router"),
        ):
            self._node(execution, node_id, label)
        execution.checkpoint("write_report")
        self._node(execution, "write_report", "Reporter")
        self._node(execution, "persist", "Validation brief")
        return self._finish(execution, idea, {"decision": "approve", "unattended": True})

    def resume(
        self,
        execution: RunExecution,
        *,
        context: Any,
        feedback: str,
    ) -> Any:
        """Answer a gate, and - unlike before - actually branch on the answer.

        This used to read ``synthetic_stage`` alone and never look at
        ``decision``, so a ``revise`` reply advanced exactly as an ``approve``
        did. The revise loop was therefore never exercised end to end by
        anything: not by a unit test, not by the E2E suite, and not by a local
        synthetic run. The one E2E test that mentions it is honestly titled - it
        proves the reply is *accepted*, not that anything loops back.

        That mattered more than it looked. A console that draws a revision - a
        boat rowing back, a lap counter, a per-node pass count - cannot be
        verified against a double with no revisions in it, and the graph's own
        revise edges (``route_scope -> revise_scope`` and
        ``route_verdict -> revise_verdict``) were dead on the free path.

        The loop is bounded the way the real flow bounds it. ``ValidatorFlow``
        spends a turn per revise through ``claim_revise_turn`` and, at the cap,
        treats a further revise as an approval rather than failing the run or
        parking it at a gate with nothing left to do.
        """

        payload = json.loads(feedback or "{}")
        revising = str(payload.get("decision", "approve")).strip().lower() == "revise"
        stage = int(context.metadata.get("synthetic_stage", 1))
        turns = int(context.metadata.get("synthetic_revise_turns", 0) or 0)
        idea = str(execution.inputs.get("idea", "synthetic idea"))

        if stage == 1:
            # The router runs on every reply - reading the decision is its whole
            # job - and only then does the path fork.
            self._node(execution, "route_scope", "Scope router")
            if revising and turns < SYNTHETIC_MAX_REVISE_TURNS:
                self._node(execution, "revise_scope", "Revise scope")
                return self._pending(
                    execution,
                    method_name="confirm_scope",
                    message="Confirm the revised scope.",
                    # The reopened gate shows the REVISED scope, not the
                    # original one again. On the paid path `revise_scope` re-runs
                    # the Scoper with the operator's note as `human_override` and
                    # the gate reopens over its new output; carrying the
                    # operator's own edits forward is the cheapest faithful
                    # stand-in for that, and it is what an operator expects to
                    # see - a gate that reopened showing the text they had just
                    # corrected would read as the edit having been dropped.
                    #
                    # Echoing the raw reply here instead was tried and is wrong:
                    # the scope gate is fully editable, so every key of this dict
                    # reaches the console as an INPUT, and the operator would get
                    # a text box full of reply JSON.
                    output=self._revised_scope(idea, payload),
                    stage=1,
                    revise_turns=turns + 1,
                )
            execution.checkpoint("research_market")
            for node_id, label in (
                ("research_market", "Market Analyst"),
                ("research_sentiment", "Sentiment Analyst"),
                ("research_feasibility", "Feasibility Analyst"),
                ("synthesize", "Synthesist"),
            ):
                self._node(execution, node_id, label, idea)
            self._verdict(execution)
            return self._pending(
                execution,
                method_name="review_verdict",
                message="Review the scored verdict.",
                output={
                    "verdict": "NEEDS_WORK",
                    "confidence": 0.62,
                    "cheapest_next_test": "Interview five target users.",
                    "scope_reply": payload,
                },
                stage=2,
                # Turns are counted per gate, so the verdict gate starts fresh -
                # the same way `claim_revise_turn` keys on "scope" or "verdict".
                revise_turns=0,
            )

        self._node(execution, "route_verdict", "Verdict router")
        if revising and turns < SYNTHETIC_MAX_REVISE_TURNS:
            # `revise_verdict` re-runs synthesis and re-opens the same gate,
            # which is the shape of the real flow's
            # `revise_verdict -> review_verdict` edge.
            self._node(execution, "revise_verdict", "Revise verdict")
            self._verdict(execution)
            return self._pending(
                execution,
                method_name="review_verdict",
                message="Review the rescored verdict.",
                output={
                    "verdict": "NEEDS_WORK",
                    "confidence": 0.62,
                    "cheapest_next_test": "Interview five target users.",
                },
                stage=2,
                revise_turns=turns + 1,
            )
        execution.checkpoint("write_report")
        self._node(execution, "write_report", "Reporter")
        self._node(execution, "persist", "Validation brief")
        return self._finish(execution, idea, payload)

    @staticmethod
    def _finish(execution: RunExecution, idea: str, payload: Any) -> Any:
        # Shaped like `schemas/validator.py::ValidationReport`, because the
        # console reads `result.markdown_body` and this double used to return a
        # result with no body at all. That made report rendering *untestable*
        # on the free path - no unit test, no E2E test and no local synthetic
        # run could ever exercise it - which is how the client came to drop the
        # report at three layers behind 133 green tests. Keep this in the real
        # shape; a double that diverges from its subject certifies nothing.
        result = {
            "synthetic": True,
            # Rendered from the SAME `Verdict` the verdict frame carries, not from
            # hardcoded numbers. They disagreed once - the scorecard read 6.0
            # while the prose underneath it read 5.6 - and a double whose two
            # halves contradict each other is worse than no double, because it
            # teaches whoever reads it that one of the two is lying without
            # saying which.
            "markdown_body": _synthetic_report_markdown(idea),
            "provisional": True,
            "thin_dimensions": ["D", "X"],
            "sources": [
                {"url": "https://example.com/synthetic-market", "title": "Synthetic market note"},
                {"url": "https://news.ycombinator.com/item?id=1", "title": "Synthetic HN thread"},
            ],
            "idea": idea,
            "verdict": "NEEDS_WORK",
            "feedback": payload,
        }
        execution.capture.emit(
            kind=FrameKind.RUN_STATE,
            event_type=UIEventType.WORKFLOW_END,
            node_id="workflow",
            message="Synthetic validator completed",
            details={"status": "completed", "result": result},
        )
        return result

    @staticmethod
    def _verdict(execution: RunExecution) -> None:
        """Publish the deterministic score the way the real serializer does.

        The paid path raises a `VerdictComputedEvent` and the serializer turns
        it into this frame; a synthetic run has no flow to raise one, so it
        emits the frame directly - through the same payload builder, so the two
        cannot drift.
        """

        verdict = _synthetic_verdict()
        execution.capture.emit(
            kind=FrameKind.VERDICT,
            event_type=UIEventType.VERDICT_COMPUTED,
            node_id=VERDICT_NODE_ID,
            message=verdict_frame_message(verdict),
            details=verdict_frame_details(verdict),
        )

    @staticmethod
    def _node(
        execution: RunExecution, node_id: str, label: str, idea: str = ""
    ) -> None:
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_START,
            node_id=node_id,
            message=f"{label} started",
        )
        SyntheticValidatorRunner._tool_call(execution, node_id, idea)
        execution.capture.emit(
            kind=FrameKind.NODE_STATE,
            event_type=UIEventType.NODE_END,
            node_id=node_id,
            message=f"{label} completed",
        )

    @staticmethod
    def _tool_call(execution: RunExecution, node_id: str, idea: str) -> None:
        """Emit the TOOL frame pair a research branch produces, or nothing.

        This runner emitted NO tool, llm, token or metrics frames at all, and
        the omission was not cosmetic. Every Playwright test, every `SYNTHETIC=1`
        session and every hand-inspection of the console ran against a backend
        that never produced a tool frame - so the parts of the UI that render
        one were structurally unobservable on the free path, and a six-minute
        branch that showed the operator nothing shipped behind a green suite.

        That is the third time this exact shape of defect has landed here (see
        CLAUDE.md closed items 20 and 33): a double that diverges from its
        subject certifies nothing.

        The details below mirror `events/serializer.py` field for field - the
        `before` draft at :432 and the `after` draft at :438-441 with
        `_TOOL_ENVELOPE_FIELDS` merged in. `query` is on BOTH stages on purpose:
        it is the string the UI shows while a call is in flight, which is the
        whole point of having it.
        """

        spec = _BRANCH_TOOLS.get(node_id)
        if spec is None:
            return
        tool_name, query = spec[0], spec[1].format(idea=idea or "synthetic idea")
        execution.capture.emit(
            kind=FrameKind.TOOL,
            event_type=UIEventType.TOOL_CALL,
            node_id=node_id,
            message=f"{tool_name} started",
            details={
                "stage": "before",
                "tool": tool_name,
                "query": query,
                "args": {"query": query},
            },
        )
        # A knob rather than a constant: this is the ONLY way to reproduce the
        # slow-branch case at zero cost, and reproducing it is what stops the
        # next liveness regression shipping the way this one did. Off by
        # default so the E2E suite stays fast.
        delay = _synthetic_branch_delay_seconds()
        if delay > 0:
            # Waiting on the cancel Event rather than sleeping means Cancel
            # still works during a simulated slow branch - which is exactly the
            # window an operator watching a stalled console reaches for it.
            if execution.cancel_requested is not None:
                execution.cancel_requested.wait(delay)
            else:
                time.sleep(delay)
        execution.capture.emit(
            kind=FrameKind.TOOL,
            event_type=UIEventType.TOOL_CALL,
            node_id=node_id,
            message=f"{tool_name} completed",
            details={
                "stage": "after",
                "tool": tool_name,
                "query": query,
                "from_cache": False,
                "failure": None,
                "tool_status": "ok",
                "result_count": 3,
                "notes": f"Synthetic evidence for {query!r}; no network call was made.",
                "retrieved_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            },
        )

    @staticmethod
    def _revised_scope(idea: str, payload: Any) -> dict[str, Any]:
        """The scope as it stands after a revision.

        Starts from the same defaults the first gate offered and lays the
        operator's edits over them, so a field they changed comes back changed
        and one they left alone comes back untouched. `_feedback` has already
        pruned the edit to the keys the gate declared editable, so nothing
        unexpected can arrive here.
        """
        scope: dict[str, Any] = {
            "startup_idea": idea,
            "category": "Synthetic market",
            "target_user": "Synthetic operator",
            "market_query": f"{idea} market",
        }
        edited = payload.get("scope") if isinstance(payload, dict) else None
        if isinstance(edited, dict):
            for key, value in edited.items():
                if key in scope and isinstance(value, str):
                    scope[key] = value
        note = payload.get("feedback") if isinstance(payload, dict) else None
        if isinstance(note, str) and note.strip():
            # Round-tripped so the operator can see what the revision was asked
            # to address, in the one field that is a free-text note anyway.
            scope["revision_note"] = note.strip()
        return scope

    @staticmethod
    def _pending(
        execution: RunExecution,
        *,
        method_name: str,
        message: str,
        output: dict[str, Any],
        stage: int,
        revise_turns: int = 0,
    ) -> Any:
        from crewai.flow.async_feedback import HumanFeedbackPending, PendingFeedbackContext

        return HumanFeedbackPending(
            context=PendingFeedbackContext(
                flow_id=execution.flow_id or execution.run_id,
                flow_class="brief_crew.service.runner.SyntheticValidatorRunner",
                method_name=method_name,
                method_output=output,
                message=message,
                emit=None,
                metadata={
                    "synthetic_stage": stage,
                    "synthetic_revise_turns": revise_turns,
                },
                requested_at=datetime.now(timezone.utc),
            ),
            callback_info={"synthetic": True},
        )
