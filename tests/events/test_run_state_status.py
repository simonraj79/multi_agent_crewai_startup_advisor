"""The RUN_STATE contract the Studio client reads - pinned to both sides.

`useValidatorRun.applyRunState` moves the console out of its pre-run state by
reading `details.status` off a `run_state` frame. Nothing ever checked that the
serializer put that key there, and for a long time it did not: a real run
streamed every node to `completed` while the header still read "queued". The
whole frontend suite stayed green through it, because every spec hand-wrote its
own frames and `SyntheticRunner` emitted `{"result": ...}` with no status.

This module is the pin. It builds frames from the real CrewAI events through the
real serializer, asserts the contract in Python, and writes those same frames to
a JSON fixture that `frontend/tests/realFrameShape.spec.ts` feeds to the real
composable. Change the emitted shape on either side and one of the two suites
fails. Regenerate the fixture deliberately with:

    .\\.venv\\Scripts\\python.exe tests\\events\\test_run_state_status.py --write
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

from crewai.events import FlowFailedEvent, FlowFinishedEvent, FlowStartedEvent

from brief_crew.events import (
    FrameBuffer,
    FrameData,
    NodeRegistry,
    StreamSinkAdapter,
)
from brief_crew.service.runner import RunExecution, SyntheticRunner


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "frontend" / "tests" / "fixtures" / "backendRunStateFrames.json"

#: Must equal `RUN_ID` in `frontend/tests/helpers.ts`. The composable drops any
#: frame whose `run_id` is not the run it is watching, so a fixture built under
#: a different id would be silently ignored rather than failing loudly.
FIXTURE_RUN_ID = "run-under-test"

#: Frozen so the fixture is byte-stable and a diff means a real shape change.
FIXTURE_TS = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)

FIXTURE_INPUTS = {"idea": "A scheduling assistant for clinics"}
FIXTURE_RESULT = {"verdict": "NEEDS_WORK"}


def build_flow_frames() -> tuple[FrameData, ...]:
    """The three flow-lifecycle frames, straight out of the real serializer."""

    buffer = FrameBuffer(capacity=16)
    adapter = StreamSinkAdapter(
        run_id=FIXTURE_RUN_ID,
        buffer=buffer,
        registry=NodeRegistry(),
    )
    adapter(
        None,
        FlowStartedEvent(
            flow_name="ValidatorFlow",
            inputs=dict(FIXTURE_INPUTS),
            timestamp=FIXTURE_TS,
        ),
    )
    adapter(
        None,
        FlowFinishedEvent(
            flow_name="ValidatorFlow",
            result=dict(FIXTURE_RESULT),
            state={},
            timestamp=FIXTURE_TS,
        ),
    )
    adapter(
        None,
        FlowFailedEvent(
            flow_name="ValidatorFlow",
            error=RuntimeError("Firecrawl rate limit exhausted."),
            timestamp=FIXTURE_TS,
        ),
    )
    # An emit that raised would be swallowed into `emit_errors` and would leave a
    # short, silently-wrong fixture behind, so refuse to build one.
    stats = buffer.stats()
    if stats.emit_errors or stats.dropped:
        raise AssertionError(f"frame capture lost frames: {stats}")
    return buffer.replay()


def fixture_payload() -> str:
    frames = [frame.to_dict() for frame in build_flow_frames()]
    return json.dumps(frames, indent=2) + "\n"


class RunStateStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = build_flow_frames()
        self.started, self.finished, self.failed = self.frames

    def test_flow_started_run_state_carries_running(self) -> None:
        self.assertEqual(self.started.kind.value, "run_state")
        self.assertEqual(self.started.event_type.value, "WORKFLOW_START")
        self.assertEqual(self.started.details["status"], "running")
        # The status is additive: the inputs payload the frame already carried
        # must survive alongside it.
        self.assertEqual(dict(self.started.details["inputs"]), FIXTURE_INPUTS)

    def test_flow_finished_run_state_carries_completed(self) -> None:
        self.assertEqual(self.finished.kind.value, "run_state")
        self.assertEqual(self.finished.event_type.value, "WORKFLOW_END")
        self.assertEqual(self.finished.details["status"], "completed")
        self.assertEqual(dict(self.finished.details["result"]), FIXTURE_RESULT)

    def test_a_failed_flow_is_an_error_frame_not_a_run_state(self) -> None:
        """The precondition the client's `WORKFLOW_END` fallback rests on.

        `applyRunState` treats a statusless `run_state` + `WORKFLOW_END` as a
        completion. That is only sound while a failed flow leaves by a different
        door: `FrameKind.ERROR`, which the client routes to `error` without
        consulting `applyRunState` at all. If this ever becomes a `run_state`
        frame, the client fallback starts reporting failures as successes.
        """

        self.assertEqual(self.failed.kind.value, "error")
        self.assertEqual(self.failed.level.value, "ERROR")
        self.assertNotIn("status", self.failed.details)

    def test_the_synthetic_double_emits_the_serializer_shape(self) -> None:
        """A double that lies about the contract is how this bug survived.

        `SyntheticRunner` backs the service's no-cost mode and several
        integration tests. Its `run_state` frames must carry the same keys the
        real serializer emits, or the synthetic path keeps passing over a
        defect the live path has.
        """

        buffer = FrameBuffer(capacity=16)
        adapter = StreamSinkAdapter(
            run_id="synthetic-run",
            buffer=buffer,
            registry=NodeRegistry(),
        )
        SyntheticRunner()(
            RunExecution(
                run_id="synthetic-run",
                inputs={"topic": "a topic"},
                capture=adapter,
            )
        )
        run_states = [
            frame for frame in buffer.replay() if frame.kind.value == "run_state"
        ]
        self.assertEqual(
            [frame.event_type.value for frame in run_states],
            ["WORKFLOW_START", "WORKFLOW_END"],
        )
        for synthetic, real in zip(run_states, (self.started, self.finished)):
            self.assertEqual(
                sorted(synthetic.details), sorted(real.details), synthetic.message
            )
        self.assertEqual(run_states[0].details["status"], "running")
        self.assertEqual(run_states[1].details["status"], "completed")

    def test_frontend_fixture_matches_the_serializer(self) -> None:
        """The other half of the pin.

        `frontend/tests/realFrameShape.spec.ts` drives the real composable with
        this file. If the serializer's output moves and the fixture does not,
        the frontend goes on being tested against a shape the backend no longer
        emits - which is exactly the failure this whole module exists to stop.
        """

        self.assertTrue(
            FIXTURE_PATH.is_file(),
            f"missing {FIXTURE_PATH}; regenerate with --write",
        )
        self.assertEqual(
            FIXTURE_PATH.read_text(encoding="utf-8"),
            fixture_payload(),
            "the serializer no longer emits the frames the frontend fixture "
            "holds. Review the change on both sides, then regenerate:\n"
            "    .\\.venv\\Scripts\\python.exe "
            "tests\\events\\test_run_state_status.py --write",
        )


def _write_fixture() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(fixture_payload(), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        _write_fixture()
    else:
        unittest.main()
