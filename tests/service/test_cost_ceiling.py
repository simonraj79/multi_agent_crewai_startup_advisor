"""The per-run spend ceiling: the first limit in this service denominated in USD.

Every other bound on the public run endpoint counts something - bytes,
characters, keys, queued runs, runs per minute. None of them bounded what one
admitted run could SPEND once it was executing: ``compute_cost_usd`` priced each
call, ``RunRecord._record_usage`` added it to ``usage["cost_usd"]``, and nothing
anywhere compared that total to anything. A run that looped inside an agent's
``max_iter`` was bounded only by the agent's own patience.

The figures the default is calibrated against come from run ``8b5a0a78``,
recovered from the deployed API: 11 calls, 128,069 tokens, $0.1309 - a typical
clean run at $0.13-$0.18, an observed worst case of $2-$4 and a $7 tail.

What each test here is actually defending:

* the ceiling does not touch an honest run (the failure mode that gets a cost
  control turned off, after which it protects nothing);
* a runaway stops, and stops *distinguishably* - an operator must be able to
  tell "I cancelled this" from "this ran out of money" without reading logs;
* an UNPRICED model contributes ``None``, never ``0.0``, and can therefore
  never trip the ceiling however many tokens it burns;
* ``MAX_RUN_COST_USD=0`` really is off;
* and the enforcement is re-entrant against the lock ``_record_usage`` already
  holds - which is the one way this change could deadlock the capture thread.

Everything runs on injected runners and hand-built CrewAI events. No model is
called, no network is touched and nothing here costs money.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import logging
import time
import unittest
from threading import Event, RLock, Thread

from crewai.events import LLMCallCompletedEvent, LLMCallStartedEvent
from crewai.events.types.llm_events import LLMCallType

from brief_crew.config import (
    CHEAP_MODEL,
    MAX_RUN_COST_USD,
    compute_cost_usd,
)
from brief_crew.events import FrameKind, UIEventType
from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
from brief_crew.service.models import RunStatus, RunStatusResponse
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    COST_CEILING_ERROR_PREFIX,
    COST_CEILING_REASON,
    RunRecord,
    RunRegistry,
)
from brief_crew.service.runner import RunExecution


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

# The token counts of the one real paid run this project has, so a "call" here
# is the size of a call that actually happened rather than a round number.
PROMPT_TOKENS = 81_282
COMPLETION_TOKENS = 46_787

_CALL_COST = compute_cost_usd(CHEAP_MODEL, PROMPT_TOKENS, COMPLETION_TOKENS)
# Derived from PRICES rather than hardcoded: a price change must move the
# ceilings these tests set, not silently change what they are testing.
assert _CALL_COST is not None, "CHEAP_MODEL must be priced in config.PRICES"
CALL_COST: float = _CALL_COST


def emit_model_call(execution: RunExecution, model: str, index: int) -> None:
    """Fire one real ``LLMCall{Started,Completed}`` pair for a priced model.

    The ``call_id`` is unique per call because ``_track_llm_timing`` pops its
    timing entry by ``(node_id, call_id)``; reusing one id would make the second
    call look like a duplicate completion of the first.
    """

    started_at = datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)
    call_id = f"call-{index}"
    execution.capture(
        None,
        LLMCallStartedEvent(
            timestamp=started_at,
            agent_role="Scoper",
            model=model,
            call_id=call_id,
            messages=[],
            call_type=LLMCallType.LLM_CALL,
        ),
    )
    execution.capture(
        None,
        LLMCallCompletedEvent(
            timestamp=started_at + timedelta(milliseconds=515),
            agent_role="Scoper",
            model=model,
            call_id=call_id,
            response="done",
            call_type=LLMCallType.LLM_CALL,
            usage={
                "prompt_tokens": PROMPT_TOKENS,
                "completion_tokens": COMPLETION_TOKENS,
                "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
                "successful_requests": 1,
            },
        ),
    )


class BudgetRunner:
    """Make ``calls`` priced model calls, checking for cancellation between them.

    ``execution.checkpoint`` performs exactly the test ``_cancel_guard`` performs
    at every CrewAI ``PRE_STEP`` boundary, so the granularity this double models
    is the real one: the ceiling can only be acted on BETWEEN calls, never during
    one.
    """

    def __init__(self, *, calls: int, model: str = CHEAP_MODEL) -> None:
        self.calls = calls
        self.model = model
        self.completed_calls = 0

    def __call__(self, execution: RunExecution) -> dict[str, int]:
        for index in range(self.calls):
            execution.checkpoint(f"call {index}")
            emit_model_call(execution, self.model, index)
            self.completed_calls += 1
        execution.checkpoint("finish")
        return {"calls": self.completed_calls}


class OperatorCancelRunner:
    """Sit at a step boundary until somebody presses Cancel.

    The contrast case for the whole "distinguishable" requirement: this run stops
    by the SAME cooperative path a budget stop uses - ``cancel_requested`` set,
    ``HookAborted`` at a boundary - so anything that tells the two apart has to
    come from the reason, not from the mechanism.
    """

    def __init__(self) -> None:
        self.started = Event()

    def __call__(self, execution: RunExecution) -> str:
        self.started.set()
        for _ in range(2_000):
            execution.checkpoint("next step")
            time.sleep(0.005)
        return "never reached"


class QuietCeilingLogMixin:
    """Silence the ceiling warning, which is otherwise emitted per tripped run.

    The warning is deliberately loud in production - it is how an operator finds
    out a run stopped itself - so a suite that trips it a dozen times drowns its
    own output. `assertLogs` sets the level itself, so the one test that asserts
    on the warning is unaffected by this.
    """

    def setUp(self) -> None:  # noqa: D102 - unittest hook
        super().setUp()  # type: ignore[misc]
        logger = logging.getLogger("brief_crew.service.registry")
        previous = logger.level
        logger.setLevel(logging.CRITICAL)
        self.addCleanup(logger.setLevel, previous)  # type: ignore[attr-defined]


def _registry(runner: object, **kwargs: object) -> RunRegistry:
    return RunRegistry(
        graph_version=VALIDATOR_GRAPH.version,
        node_registry=VALIDATOR_NODE_REGISTRY,
        runner=runner,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


class CostCeilingConstantTests(unittest.TestCase):
    """The default is a judgement, so the judgement is written down and checked."""

    def test_the_default_clears_the_worst_run_anyone_has_actually_seen(self) -> None:
        # $7 is the observed tail of a real run. A ceiling at or below it would
        # cut short an honest one, and a cost control that fires on honest work
        # gets raised or disabled - after which it bounds nothing.
        self.assertGreater(MAX_RUN_COST_USD, 7.0)

    def test_the_default_is_far_above_a_typical_run_and_far_below_unbounded(
        self,
    ) -> None:
        typical_clean_run = 0.18
        self.assertGreater(MAX_RUN_COST_USD, typical_clean_run * 25)
        # ...and still a brake rather than a blank cheque. 8 concurrent runs
        # (MAX_QUEUED_RUNS) at the ceiling is the aggregate exposure, and that
        # number has to stay something an owner would notice rather than a
        # number nobody would ever reach.
        self.assertLessEqual(MAX_RUN_COST_USD, 25.0)

    def test_the_ceiling_is_a_float_knob_and_zero_is_a_legal_value(self) -> None:
        from brief_crew.config import _env_non_negative_float

        self.assertIsInstance(MAX_RUN_COST_USD, float)
        self.assertEqual(_env_non_negative_float("BRIEF_CREW_UNSET_KNOB", 0.0), 0.0)

    def test_a_negative_ceiling_is_refused_rather_than_read_as_disabled(self) -> None:
        """A nonsense value must not silently become "no ceiling"."""

        import os
        from unittest.mock import patch

        from brief_crew.config import _env_non_negative_float

        with patch.dict(os.environ, {"BRIEF_CREW_TEST_CEILING": "-1"}):
            with self.assertRaises(ValueError):
                _env_non_negative_float("BRIEF_CREW_TEST_CEILING", 10.0)
        with patch.dict(os.environ, {"BRIEF_CREW_TEST_CEILING": "banana"}):
            with self.assertRaises(ValueError):
                _env_non_negative_float("BRIEF_CREW_TEST_CEILING", 10.0)

    def test_the_ceiling_covers_the_worst_legitimate_revise_budget(self) -> None:
        """The worst honest run is a clean run plus every revise turn on offer.

        A revise at either gate re-runs an ESCALATION-tier agent, so the worst
        legitimate spend is the clean run plus two gates' worth of them. Priced
        at the measured escalation average, that has to fit inside the ceiling
        with room to spare - the 4x factor covers the Synthesist running at
        reasoning_effort=high, which is dearer than the average.

        This is the test that fails if the gate-turn cap is ever raised far
        enough to make the ceiling the binding constraint on an honest run.
        Imported by value rather than from `config`, because the gate-turn knob
        is being changed in a concurrent branch and this file must not fail to
        import if it moves.
        """

        escalation_call_usd = 0.024488  # measured on run 8b5a0a78
        clean_run_usd = 0.18
        max_gate_turns = 5  # config.VALIDATOR_MAX_GATE_TURNS
        worst_case = clean_run_usd + 2 * max_gate_turns * escalation_call_usd

        self.assertLess(worst_case * 4, MAX_RUN_COST_USD)


class CostCeilingEnforcementTests(QuietCeilingLogMixin, unittest.TestCase):
    """The ceiling on a run, through the registry, end to end."""

    def _run(self, runner: object, *, ceiling: float) -> tuple[RunRegistry, str]:
        registry = _registry(runner, max_run_cost_usd=ceiling)
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-ceiling",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=10)
        return registry, record.run_id

    @staticmethod
    def _terminal_frame(registry: RunRegistry, run_id: str) -> object:
        record = registry.require(run_id)
        return next(
            frame
            for frame in reversed(record.buffer.replay())
            if frame.kind is FrameKind.RUN_STATE
            and frame.event_type is UIEventType.WORKFLOW_END
        )

    def test_a_run_under_the_ceiling_is_left_completely_alone(self) -> None:
        """The case that matters most: an honest run must not notice this exists."""

        runner = BudgetRunner(calls=3)
        registry, run_id = self._run(runner, ceiling=CALL_COST * 10)
        payload = registry.status_payload(run_id)
        record = registry.require(run_id)

        self.assertEqual(payload["status"], RunStatus.COMPLETED)
        self.assertEqual(runner.completed_calls, 3)
        self.assertIsNone(payload["stop_reason"])
        self.assertIsNone(payload["error"])
        # Not merely "not cancelled" - never even ASKED to cancel, which is the
        # flag a later step would trip over.
        self.assertFalse(record.cancel_requested.is_set())
        self.assertLess(payload["usage"]["cost_usd"], CALL_COST * 10)

    def test_a_run_that_crosses_the_ceiling_stops_at_the_next_boundary(self) -> None:
        runner = BudgetRunner(calls=20)
        registry, run_id = self._run(runner, ceiling=CALL_COST * 2.5)
        payload = registry.status_payload(run_id)

        self.assertEqual(payload["status"], RunStatus.CANCELLED)
        # Three calls, not twenty: the third crossed 2.5x, and the fourth never
        # started because the checkpoint before it aborted.
        self.assertEqual(runner.completed_calls, 3)
        self.assertAlmostEqual(
            payload["usage"]["cost_usd"], CALL_COST * 3, places=10
        )

    def test_the_stop_names_itself_so_it_is_not_read_as_an_operator_cancel(
        self,
    ) -> None:
        registry, run_id = self._run(BudgetRunner(calls=20), ceiling=CALL_COST * 2.5)
        payload = registry.status_payload(run_id)

        self.assertEqual(payload["stop_reason"], COST_CEILING_REASON)
        assert payload["error"] is not None
        self.assertTrue(payload["error"].startswith(COST_CEILING_ERROR_PREFIX))
        # The three caveats are in the operator-facing sentence, not only in a
        # source comment nobody reading an API response will see.
        self.assertIn("estimate", payload["error"])
        self.assertIn("Firecrawl", payload["error"])
        self.assertIn("MAX_RUN_COST_USD", payload["error"])

    def test_the_terminal_frame_carries_the_reason_and_the_figures(self) -> None:
        """The trace has to explain itself too, the way an interrupted run does."""

        registry, run_id = self._run(BudgetRunner(calls=20), ceiling=CALL_COST * 2.5)
        frame = self._terminal_frame(registry, run_id)

        details = frame.details  # type: ignore[attr-defined]
        self.assertEqual(details["status"], "cancelled")
        self.assertEqual(details["reason"], COST_CEILING_REASON)
        self.assertAlmostEqual(details["cost_usd"], CALL_COST * 3, places=10)
        self.assertAlmostEqual(details["ceiling_usd"], CALL_COST * 2.5, places=10)
        self.assertIn("cost ceiling", frame.message)  # type: ignore[attr-defined]

    def test_an_operator_cancel_is_the_same_status_and_a_different_reason(
        self,
    ) -> None:
        """The contrast the whole requirement rests on, asserted side by side."""

        runner = OperatorCancelRunner()
        registry = _registry(runner)
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-operator",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        registry.start_run(record.run_id)
        self.assertTrue(runner.started.wait(timeout=10))
        registry.cancel(record.run_id)
        registry.wait(record.run_id, timeout=10)

        payload = registry.status_payload(record.run_id)
        frame = self._terminal_frame(registry, record.run_id)

        # Same terminal status as a budget stop...
        self.assertEqual(payload["status"], RunStatus.CANCELLED)
        # ...and every distinguishing mark absent.
        self.assertIsNone(payload["stop_reason"])
        self.assertIsNone(payload["error"])
        self.assertNotIn("reason", frame.details)  # type: ignore[attr-defined]
        self.assertNotIn("cost", frame.message)  # type: ignore[attr-defined]

    def test_the_ceiling_is_announced_once_not_once_per_later_call(self) -> None:
        """A tripped run keeps streaming frames; the warning must not repeat."""

        with self.assertLogs("brief_crew.service.registry", level=logging.WARNING) as logs:
            self._run(BudgetRunner(calls=20), ceiling=CALL_COST * 2.5)

        tripped = [line for line in logs.output if "cost ceiling" in line]
        self.assertEqual(len(tripped), 1, logs.output)

    def test_a_zero_ceiling_disables_enforcement_entirely(self) -> None:
        """0 is the documented escape hatch; unset is NOT, and gives the default."""

        runner = BudgetRunner(calls=6)
        registry, run_id = self._run(runner, ceiling=0.0)
        payload = registry.status_payload(run_id)

        self.assertEqual(payload["status"], RunStatus.COMPLETED)
        self.assertEqual(runner.completed_calls, 6)
        self.assertIsNone(payload["stop_reason"])
        # ...and the run really did spend past what any sane ceiling would be,
        # so this is "disabled", not "never reached".
        self.assertGreater(payload["usage"]["cost_usd"], CALL_COST * 5)

    def test_a_registry_with_no_ceiling_argument_inherits_the_configured_one(
        self,
    ) -> None:
        registry = _registry(BudgetRunner(calls=1))
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-default",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        self.assertEqual(registry.max_run_cost_usd, MAX_RUN_COST_USD)
        self.assertEqual(record.max_cost_usd, MAX_RUN_COST_USD)

    def test_a_negative_registry_ceiling_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            _registry(BudgetRunner(calls=1), max_run_cost_usd=-1.0)


class UnpricedModelTests(QuietCeilingLogMixin, unittest.TestCase):
    """`compute_cost_usd` returns None - never 0.0 - for a model it cannot price.

    `_record_usage` adds `priced` (0.0) to the total rather than the None, so an
    unpriced model contributes nothing to the figure the ceiling reads. That is
    deliberate and it is a real hole: guessing a price in order to enforce a
    limit would invent exactly the number the None convention exists to refuse.
    These two tests pin the behaviour AND the fact that it is a hole, so nobody
    later "fixes" it by defaulting an unknown model to a made-up rate.
    """

    def test_an_unpriced_model_cannot_trip_the_ceiling_however_much_it_burns(
        self,
    ) -> None:
        runner = BudgetRunner(calls=8, model="acme/never-heard-of-it")
        registry = _registry(runner, max_run_cost_usd=0.000001)
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-unpriced",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        with self.assertLogs("brief_crew.service.registry", level=logging.WARNING):
            registry.start_run(record.run_id)
            registry.wait(record.run_id, timeout=10)
        payload = registry.status_payload(record.run_id)

        # A ceiling of a ten-thousandth of a cent, and eight full-size calls.
        self.assertEqual(payload["status"], RunStatus.COMPLETED)
        self.assertEqual(runner.completed_calls, 8)
        self.assertIsNone(payload["stop_reason"])
        self.assertEqual(payload["usage"]["cost_usd"], 0.0)
        # The tokens were real, so the 0.0 total is visibly a partial sum.
        self.assertEqual(
            payload["usage"]["total_tokens"],
            8 * (PROMPT_TOKENS + COMPLETION_TOKENS),
        )

    def test_a_none_price_never_reaches_the_arithmetic_as_a_number(self) -> None:
        self.assertIsNone(compute_cost_usd("acme/never-heard-of-it", 10**6, 10**6))
        self.assertIsNotNone(compute_cost_usd(CHEAP_MODEL, 10**6, 10**6))


class CeilingBoundaryAndLockingTests(QuietCeilingLogMixin, unittest.TestCase):
    """The two things only a unit test can pin: the comparison, and the lock."""

    def _record(self, *, ceiling: float) -> RunRecord:
        return RunRecord(
            run_id="record-under-test",
            session_id="session-unit",
            workflow_id=VALIDATOR_GRAPH.id,
            graph_version=VALIDATOR_GRAPH.version,
            inputs={},
            node_registry=VALIDATOR_NODE_REGISTRY,
            max_cost_usd=ceiling,
        )

    def test_spending_exactly_the_ceiling_trips_it(self) -> None:
        """`>=`, not `>`: a budget with nothing left is spent."""

        record = self._record(ceiling=1.0)
        record.usage["cost_usd"] = 1.0
        record._enforce_cost_ceiling()

        self.assertEqual(record.stop_reason, COST_CEILING_REASON)
        self.assertEqual(record.status, RunStatus.CANCELLING)
        self.assertTrue(record.cancel_requested.is_set())

    def test_spending_a_cent_under_the_ceiling_does_not(self) -> None:
        record = self._record(ceiling=1.0)
        record.usage["cost_usd"] = 0.99

        record._enforce_cost_ceiling()

        self.assertIsNone(record.stop_reason)
        self.assertEqual(record.status, RunStatus.QUEUED)
        self.assertFalse(record.cancel_requested.is_set())

    def test_the_stop_uses_the_existing_cooperative_cancellation_path(self) -> None:
        """Not a raise inside a CrewAI event handler - the Event the guard reads."""

        record = self._record(ceiling=1.0)
        record.usage["cost_usd"] = 5.0
        record._enforce_cost_ceiling()

        execution = RunExecution(
            run_id=record.run_id,
            inputs={},
            capture=record.capture,
            cancel_requested=record.cancel_requested,
        )
        from crewai.hooks import HookAborted

        with self.assertRaises(HookAborted):
            execution.checkpoint("research_market")

    def test_the_ceiling_can_be_enforced_while_the_record_lock_is_held(self) -> None:
        """`_record_usage` holds `_lock`, and `mark_cancelling()` takes it again.

        That is only safe because `_lock` is an RLock. Run it on a worker thread
        with a join timeout, so a regression to a plain `threading.Lock` FAILS
        this test rather than hanging the whole suite - which is what the same
        mistake would do to the capture thread in production.
        """

        record = self._record(ceiling=1.0)
        self.assertIsInstance(record._lock, type(RLock()))
        finished = Event()

        def trip() -> None:
            with record._lock:  # exactly what `_on_frames` already holds
                record.usage["cost_usd"] = 2.0
                record._enforce_cost_ceiling()
            finished.set()

        worker = Thread(target=trip, daemon=True)
        worker.start()
        worker.join(timeout=5)

        self.assertTrue(
            finished.is_set(),
            "enforcing the ceiling under _lock deadlocked; is _lock still an RLock?",
        )
        self.assertEqual(record.stop_reason, COST_CEILING_REASON)

    def test_enforcement_emits_no_frame_from_inside_the_capture_callback(self) -> None:
        """The other half of the deadlock: `StreamSinkAdapter` holds a plain Lock.

        `_record_usage` runs inside `adapter._notify`, which is called while that
        non-reentrant lock is held. If enforcement ever emitted a frame there it
        would deadlock the capture thread, so it must add nothing to the buffer.
        """

        record = self._record(ceiling=1.0)
        before = len(record.buffer.replay())
        record.usage["cost_usd"] = 2.0

        record._enforce_cost_ceiling()

        self.assertEqual(len(record.buffer.replay()), before)


class CostCeilingDurabilityTests(QuietCeilingLogMixin, unittest.TestCase):
    """The reason has to survive the restart that a `stop_reason` column would not.

    `metadata.create_all()` never adds a column to an existing table, so the live
    PostgreSQL database would not have one - the reason therefore rides in the
    `error` column, and `_restored_stop_reason` reads it back out.
    """

    def test_a_budget_stopped_run_reloads_with_its_reason_intact(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from brief_crew.service.registry import WorkflowRuntime

        with TemporaryDirectory() as directory:
            database_url = (
                "sqlite+pysqlite:///"
                f"{(Path(directory) / 'ceiling.db').as_posix()}"
            )
            runner = BudgetRunner(calls=20)
            first_store = PostgresFlowPersistence(database_url)
            first = _registry(
                runner,
                persistence=first_store,
                max_run_cost_usd=CALL_COST * 2.5,
                gate_sweep_interval=0.0,
            )
            record = first.create_run(
                session_id="session-durable-ceiling",
                workflow_id=VALIDATOR_GRAPH.id,
                inputs={"idea": "A classroom polling assistant"},
            )
            run_id = record.run_id
            first.start_run(run_id)
            first.wait(run_id, timeout=10)
            self.assertEqual(first.status_payload(run_id)["status"], RunStatus.CANCELLED)
            first.close()
            first_store.close()

            # The restart.
            second_store = PostgresFlowPersistence(database_url)
            second = RunRegistry(
                graph_version=VALIDATOR_GRAPH.version,
                node_registry=VALIDATOR_NODE_REGISTRY,
                runner=BudgetRunner(calls=1),
                workflows={
                    VALIDATOR_GRAPH.id: WorkflowRuntime(
                        graph_version=VALIDATOR_GRAPH.version,
                        node_registry=VALIDATOR_NODE_REGISTRY,
                        runner=BudgetRunner(calls=1),
                    )
                },
                persistence=second_store,
                gate_sweep_interval=0.0,
            )
            try:
                payload = second.status_payload(run_id)
                self.assertEqual(payload["status"], RunStatus.CANCELLED)
                self.assertEqual(payload["stop_reason"], COST_CEILING_REASON)
                assert payload["error"] is not None
                self.assertTrue(
                    payload["error"].startswith(COST_CEILING_ERROR_PREFIX)
                )
            finally:
                # Closed inside the TemporaryDirectory, not through addCleanup:
                # on Windows an open SQLite handle makes the directory
                # undeletable and the test errors on teardown instead of
                # reporting its own result.
                second.close()
                second_store.close()

    def test_an_ordinary_stored_error_is_not_mistaken_for_a_budget_stop(self) -> None:
        from brief_crew.service.registry import _restored_stop_reason

        self.assertIsNone(_restored_stop_reason(None))
        self.assertIsNone(_restored_stop_reason("interrupted by a service restart"))
        self.assertIsNone(_restored_stop_reason(17))
        self.assertEqual(
            _restored_stop_reason(f"{COST_CEILING_ERROR_PREFIX} spent $99"),
            COST_CEILING_REASON,
        )


class StopReasonContractTests(unittest.TestCase):
    """`RunStatusResponse` is `extra="forbid"`, so the payload and the model must agree."""

    def test_the_status_response_accepts_the_payload_the_registry_builds(self) -> None:
        registry = _registry(BudgetRunner(calls=1))
        self.addCleanup(registry.close)
        record = registry.create_run(
            session_id="session-contract",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
        )
        registry.start_run(record.run_id)
        registry.wait(record.run_id, timeout=10)

        response = RunStatusResponse.model_validate(
            registry.status_payload(record.run_id)
        )
        self.assertIsNone(response.stop_reason)


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class CostCeilingOverHttpTests(QuietCeilingLogMixin, unittest.TestCase):
    """An operator reads this over the API, not out of a log file."""

    def test_get_run_reports_the_budget_stop_and_the_reason(self) -> None:
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        registry = _registry(
            BudgetRunner(calls=20),
            persistence=store,
            max_run_cost_usd=CALL_COST * 2.5,
        )
        self.addCleanup(registry.close)
        client = TestClient(create_app(registry=registry))
        self.addCleanup(client.close)

        created = client.post(
            "/api/sessions/session-http-ceiling/runs",
            json={
                "workflow_id": VALIDATOR_GRAPH.id,
                "inputs": {"idea": "A classroom polling assistant"},
            },
        )
        self.assertEqual(created.status_code, 202)
        run_id = created.json()["run_id"]
        registry.wait(run_id, timeout=10)

        status = client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["stop_reason"], COST_CEILING_REASON)
        self.assertTrue(status["error"].startswith(COST_CEILING_ERROR_PREFIX))
        self.assertGreaterEqual(status["usage"]["cost_usd"], CALL_COST * 2.5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
