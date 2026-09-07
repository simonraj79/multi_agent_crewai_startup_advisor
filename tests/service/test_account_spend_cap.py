"""The per-ACCOUNT spend cap: what one signed-in person may spend, in total.

``MAX_RUN_COST_USD`` bounds one run. Nothing bounded the person: a signed-in
stranger could launch a $9 run ten times a minute and the only thing between
them and a $90 bill was the owner noticing. ``USER_SPEND_CAP_USD`` is that
bound, enforced at the two places the per-run ceiling already is - admission
(402) and the step boundary (the run is admitted with its ceiling tightened to
the account's remaining headroom) - and it applies to everybody except the
accounts on ``USER_SPEND_CAP_EXEMPT``.

What each test here is actually defending:

* the cap is a LIFETIME figure across runs, and it survives a restart because
  the durable rows are what it is summed over;
* a run in flight holds its promised headroom, so N concurrent launches cannot
  each be granted the whole cap;
* a run that runs the account dry stops DISTINGUISHABLY from one that hit its
  own ceiling and from one an operator cancelled - a person told "this run was
  expensive" would raise the wrong knob;
* an anonymous caller, an exempt account and ``USER_SPEND_CAP_USD=0`` are all
  untouched, because a cap that fires on the owner gets turned off;
* the refusal over HTTP is 402 with both figures in the sentence.

Everything runs on injected runners and hand-built CrewAI events, or on the
synthetic double. No model is called and nothing here costs money.
"""

from __future__ import annotations

import importlib.util
import time
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.config import MAX_RUN_COST_USD, user_spend_cap_usd
from brief_crew.events import FrameKind
from brief_crew.service.graph import VALIDATOR_GRAPH
from brief_crew.service.models import RunStatus
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.registry import (
    ACCOUNT_CAP_ERROR_PREFIX,
    ACCOUNT_CAP_REASON,
    COST_CEILING_REASON,
    AccountSpendCapError,
    RunRegistry,
)

from tests.service.test_cost_ceiling import (
    CALL_COST,
    BudgetRunner,
    OperatorCancelRunner,
    QuietCeilingLogMixin,
    _registry,
)

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None

ALICE = "user_alice"
BOB = "user_bob"


def _launch(
    registry: RunRegistry,
    user_id: str | None,
    *,
    cap: float | None,
    session: str = "session-cap",
):
    record = registry.create_run(
        session_id=session,
        workflow_id=VALIDATOR_GRAPH.id,
        inputs={"idea": "A classroom polling assistant"},
        user_id=user_id,
        account_cap_usd=cap,
    )
    registry.start_run(record.run_id)
    return record


class CapResolutionTests(unittest.TestCase):
    """``user_spend_cap_usd`` is the one place the exemption is decided."""

    def test_the_default_is_one_dollar_and_on(self) -> None:
        self.assertEqual(config.USER_SPEND_CAP_USD, 1.0)

    def test_an_anonymous_caller_has_no_account_to_cap(self) -> None:
        with patch.object(config, "USER_SPEND_CAP_USD", 1.0):
            self.assertIsNone(user_spend_cap_usd(None, None))
            self.assertIsNone(user_spend_cap_usd("", "nobody@example.test"))

    def test_zero_disables_the_cap_for_everyone(self) -> None:
        with patch.object(config, "USER_SPEND_CAP_USD", 0.0):
            self.assertIsNone(user_spend_cap_usd(ALICE, "alice@example.test"))

    def test_a_signed_in_stranger_gets_the_cap(self) -> None:
        with patch.object(config, "USER_SPEND_CAP_USD", 2.5):
            self.assertEqual(user_spend_cap_usd(ALICE, "alice@example.test"), 2.5)

    def test_an_exempt_email_matches_case_insensitively(self) -> None:
        with (
            patch.object(config, "USER_SPEND_CAP_USD", 1.0),
            patch.object(config, "USER_SPEND_CAP_EXEMPT", ("Owner@Example.test",)),
            patch.object(config, "_USER_SPEND_CAP_EXEMPT_LOWER", frozenset({"owner@example.test"})),
        ):
            self.assertIsNone(user_spend_cap_usd(ALICE, "owner@example.test"))
            self.assertIsNone(user_spend_cap_usd(ALICE, "  OWNER@EXAMPLE.TEST "))
            self.assertEqual(user_spend_cap_usd(BOB, "bob@example.test"), 1.0)

    def test_an_exempt_user_id_matches_exactly(self) -> None:
        with (
            patch.object(config, "USER_SPEND_CAP_USD", 1.0),
            patch.object(config, "USER_SPEND_CAP_EXEMPT", (ALICE,)),
            patch.object(config, "_USER_SPEND_CAP_EXEMPT_LOWER", frozenset({ALICE.lower()})),
        ):
            self.assertIsNone(user_spend_cap_usd(ALICE, None))
            self.assertEqual(user_spend_cap_usd(BOB, None), 1.0)
            # An id is opaque and case-sensitive; only the email is folded.
            self.assertEqual(user_spend_cap_usd("USER_ALICE", None), 1.0)


class AccountSpendAcrossRunsTests(QuietCeilingLogMixin, unittest.TestCase):
    """The cap is a lifetime figure, and the step-boundary brake honours it."""

    def test_spend_accumulates_across_runs_until_the_account_is_refused(self) -> None:
        cap = CALL_COST * 2.5
        registry = _registry(BudgetRunner(calls=1), max_run_cost_usd=0)
        self.addCleanup(registry.close)

        first = _launch(registry, ALICE, cap=cap)
        registry.wait(first.run_id, timeout=10)
        self.assertEqual(first.status, RunStatus.COMPLETED)
        self.assertEqual(first.ceiling_kind, "account")
        self.assertAlmostEqual(first.max_cost_usd, cap)

        second = _launch(registry, ALICE, cap=cap)
        registry.wait(second.run_id, timeout=10)
        self.assertEqual(second.status, RunStatus.COMPLETED)
        # The second run was promised only what the first left over.
        self.assertAlmostEqual(second.max_cost_usd, cap - CALL_COST)

        balance = registry.account_spend(ALICE)
        self.assertAlmostEqual(balance["spent"], CALL_COST * 2)
        self.assertEqual(balance["committed"], 0.0)

        third = _launch(registry, ALICE, cap=cap)
        registry.wait(third.run_id, timeout=10)
        self.assertEqual(third.status, RunStatus.CANCELLED)
        self.assertEqual(third.stop_reason, ACCOUNT_CAP_REASON)
        self.assertTrue(third.error and third.error.startswith(ACCOUNT_CAP_ERROR_PREFIX))
        self.assertAlmostEqual(third.max_cost_usd, cap - CALL_COST * 2)

        with self.assertRaises(AccountSpendCapError) as refused:
            _launch(registry, ALICE, cap=cap)
        self.assertEqual(refused.exception.user_id, ALICE)
        self.assertAlmostEqual(refused.exception.cap, cap)
        self.assertGreaterEqual(refused.exception.spent, cap)
        self.assertEqual(registry.admission_status()["refused"], 1)

    def test_another_account_is_untouched_by_the_first_ones_spend(self) -> None:
        cap = CALL_COST * 1.5
        registry = _registry(BudgetRunner(calls=1), max_run_cost_usd=0)
        self.addCleanup(registry.close)
        for _ in range(2):
            record = _launch(registry, ALICE, cap=cap)
            registry.wait(record.run_id, timeout=10)
        with self.assertRaises(AccountSpendCapError):
            _launch(registry, ALICE, cap=cap)
        bob = _launch(registry, BOB, cap=cap)
        registry.wait(bob.run_id, timeout=10)
        self.assertEqual(bob.status, RunStatus.COMPLETED)
        self.assertAlmostEqual(registry.account_spend(BOB)["spent"], CALL_COST)

    def test_the_account_stop_is_distinguishable_on_the_terminal_frame(self) -> None:
        cap = CALL_COST * 0.5
        registry = _registry(BudgetRunner(calls=3), max_run_cost_usd=0)
        self.addCleanup(registry.close)
        record = _launch(registry, ALICE, cap=cap)
        registry.wait(record.run_id, timeout=10)
        self.assertEqual(record.status, RunStatus.CANCELLED)
        self.assertEqual(record.stop_reason, ACCOUNT_CAP_REASON)
        self.assertNotEqual(record.stop_reason, COST_CEILING_REASON)
        ends = [
            frame
            for frame in record.buffer.replay()
            if frame.kind == FrameKind.RUN_STATE and frame.details.get("reason")
        ]
        self.assertEqual(len(ends), 1)
        details = ends[0].details
        self.assertEqual(details["reason"], ACCOUNT_CAP_REASON)
        self.assertAlmostEqual(details["account_cap_usd"], cap)
        self.assertAlmostEqual(details["ceiling_usd"], cap)
        self.assertIn("spend allowance", ends[0].message)

    def test_the_tighter_of_the_two_ceilings_wins(self) -> None:
        # A per-run ceiling below the account's headroom is still the per-run
        # ceiling, with the per-run sentence: the account is not what stopped it.
        registry = _registry(BudgetRunner(calls=3), max_run_cost_usd=CALL_COST * 0.5)
        self.addCleanup(registry.close)
        record = _launch(registry, ALICE, cap=CALL_COST * 50)
        registry.wait(record.run_id, timeout=10)
        self.assertEqual(record.ceiling_kind, "run")
        self.assertAlmostEqual(record.max_cost_usd, CALL_COST * 0.5)
        self.assertEqual(record.stop_reason, COST_CEILING_REASON)

    def test_no_cap_means_the_per_run_ceiling_and_nothing_else(self) -> None:
        registry = _registry(BudgetRunner(calls=1))
        self.addCleanup(registry.close)
        record = _launch(registry, ALICE, cap=None)
        registry.wait(record.run_id, timeout=10)
        self.assertEqual(record.ceiling_kind, "run")
        self.assertEqual(record.max_cost_usd, MAX_RUN_COST_USD)
        self.assertIsNone(record.account_cap_usd)
        anonymous = _launch(registry, None, cap=None)
        registry.wait(anonymous.run_id, timeout=10)
        self.assertEqual(anonymous.status, RunStatus.COMPLETED)

    def test_a_cap_must_be_positive_when_given(self) -> None:
        registry = _registry(BudgetRunner(calls=1))
        self.addCleanup(registry.close)
        with self.assertRaises(ValueError):
            _launch(registry, ALICE, cap=0.0)


class PromisedHeadroomTests(QuietCeilingLogMixin, unittest.TestCase):
    """A run in flight holds what it was promised."""

    def test_a_live_run_holds_its_headroom_against_a_second_launch(self) -> None:
        runner = OperatorCancelRunner()
        registry = _registry(runner, max_run_cost_usd=0)
        self.addCleanup(registry.close)
        cap = CALL_COST
        first = _launch(registry, ALICE, cap=cap)
        self.assertTrue(runner.started.wait(5))
        balance = registry.account_spend(ALICE)
        self.assertEqual(balance["spent"], 0.0)
        self.assertAlmostEqual(balance["committed"], cap)
        with self.assertRaises(AccountSpendCapError) as refused:
            _launch(registry, ALICE, cap=cap)
        self.assertAlmostEqual(refused.exception.spent, cap)
        # Let it go: a finished run releases its promise and only its real
        # spend (none, here) counts against the account from then on.
        registry.cancel(first.run_id)
        registry.wait(first.run_id, timeout=10)
        self.assertEqual(first.status, RunStatus.CANCELLED)
        self.assertIsNone(first.stop_reason)
        self.assertEqual(registry.account_spend(ALICE)["committed"], 0.0)
        second = registry.create_run(
            session_id="session-cap",
            workflow_id=VALIDATOR_GRAPH.id,
            inputs={"idea": "A classroom polling assistant"},
            user_id=ALICE,
            account_cap_usd=cap,
        )
        self.assertEqual(second.ceiling_kind, "account")
        self.assertAlmostEqual(second.max_cost_usd, cap)

    def test_a_refused_launch_leaves_no_promise_behind(self) -> None:
        runner = OperatorCancelRunner()
        registry = _registry(runner, max_run_cost_usd=0, max_queued_runs=1)
        self.addCleanup(registry.close)
        first = _launch(registry, ALICE, cap=CALL_COST * 10)
        self.assertTrue(runner.started.wait(5))
        # The server is full: Bob's launch clears HIS cap check (nothing
        # spent, nothing promised) and is then refused for capacity, and the
        # headroom it was about to be promised must not linger as a
        # commitment against his account.
        from brief_crew.service.registry import RunAdmissionError

        with self.assertRaises(RunAdmissionError):
            _launch(registry, BOB, cap=CALL_COST * 10)
        self.assertEqual(registry.account_spend(BOB)["committed"], 0.0)
        self.assertEqual(len(registry._reserved_headroom), 0)
        registry.cancel(first.run_id)
        registry.wait(first.run_id, timeout=10)


class AuditM5ReservationSurvivesARaisedCapTests(
    QuietCeilingLogMixin, unittest.TestCase
):
    """The cap must reserve what it GRANTED, not only what it tightened.

    Audit M5. The promise used to be recorded only when the account cap was
    the *tighter* of the two limits (`ceiling_kind == "account"`), and
    `account_spend` counted only records wearing that same label. Today
    USER_SPEND_CAP_USD is $1 against a $10 per-run ceiling, so the account is
    always tighter and the promise is always recorded - which is why nothing
    noticed. `config.py` invites the owner to raise the cap per deployment,
    and at any value above MAX_RUN_COST_USD the condition flips and NO promise
    is recorded at all.

    What that buys an attacker: a run WAITING at a gate holds no admission slot
    and is never terminal, so at ten launches a minute a hundred parked runs
    each carrying the full per-run ceiling sit against a cap that has seen none
    of them. Then answer the gates.

    The arithmetic below is the audit's own: cap $50 over a $10 per-run
    ceiling. Two admitted runs must commit $20; five must exhaust the cap; the
    sixth must be refused.
    """

    CAP = 50.0
    PER_RUN = 10.0

    def _parked_registry(self) -> tuple[RunRegistry, OperatorCancelRunner]:
        runner = OperatorCancelRunner()
        registry = _registry(runner, max_run_cost_usd=self.PER_RUN)
        self.addCleanup(registry.close)
        return registry, runner

    def _drain(self, registry: RunRegistry, records: list) -> None:
        """Let every parked run go, and do not care how it stopped.

        With RUN_CONCURRENCY at 1 only the first of these is inside the runner;
        the rest are QUEUED, and cancelling a queued run cancels its future
        outright - so ``wait`` raises ``CancelledError`` rather than returning.
        That is correct behaviour and not what any test here is about.
        """
        from concurrent.futures import CancelledError

        for record in records:
            registry.cancel(record.run_id)
        for record in records:
            try:
                registry.wait(record.run_id, timeout=10)
            except CancelledError:
                pass

    def test_m5_two_admitted_runs_commit_twenty_dollars(self) -> None:
        registry, runner = self._parked_registry()
        records = [_launch(registry, ALICE, cap=self.CAP) for _ in range(2)]
        self.addCleanup(self._drain, registry, records)
        self.assertTrue(runner.started.wait(5))

        # Both were admitted under the PER-RUN ceiling: the account cap is the
        # looser limit here, which is exactly the state the old condition
        # ignored.
        for record in records:
            self.assertEqual(record.ceiling_kind, "run")
            self.assertAlmostEqual(record.max_cost_usd, self.PER_RUN)
            self.assertAlmostEqual(record.account_cap_usd or 0.0, self.CAP)

        balance = registry.account_spend(ALICE)
        self.assertEqual(balance["spent"], 0.0)
        self.assertAlmostEqual(
            balance["committed"],
            20.0,
            msg=(
                "two runs admitted at a $10 ceiling promised "
                f"{balance['committed']} against a $50 account cap"
            ),
        )

    def test_m5_the_sixth_launch_is_refused_once_the_cap_is_promised_away(
        self,
    ) -> None:
        registry, runner = self._parked_registry()
        records = [_launch(registry, ALICE, cap=self.CAP) for _ in range(5)]
        self.addCleanup(self._drain, registry, records)
        self.assertTrue(runner.started.wait(5))

        # 5 x $10 is the whole $50, with nothing actually spent yet.
        balance = registry.account_spend(ALICE)
        self.assertEqual(balance["spent"], 0.0)
        self.assertAlmostEqual(balance["committed"], self.CAP)

        with self.assertRaises(AccountSpendCapError) as refused:
            _launch(registry, ALICE, cap=self.CAP)
        self.assertAlmostEqual(refused.exception.spent, self.CAP)
        self.assertAlmostEqual(refused.exception.cap, self.CAP)

    def test_m5_another_account_is_untouched_by_the_promises(self) -> None:
        """The promise is per owner, or one busy account would refuse everyone."""
        registry, runner = self._parked_registry()
        records = [_launch(registry, ALICE, cap=self.CAP) for _ in range(5)]
        self.addCleanup(self._drain, registry, records)
        self.assertTrue(runner.started.wait(5))

        self.assertEqual(registry.account_spend(BOB)["committed"], 0.0)
        bob = _launch(registry, BOB, cap=self.CAP)
        records.append(bob)
        self.assertEqual(bob.ceiling_kind, "run")

    def test_m5_a_terminal_run_releases_its_promise(self) -> None:
        """A promise is money the account can still spend, not money it spent."""
        registry, runner = self._parked_registry()
        records = [_launch(registry, ALICE, cap=self.CAP) for _ in range(2)]
        self.assertTrue(runner.started.wait(5))
        self.assertAlmostEqual(registry.account_spend(ALICE)["committed"], 20.0)

        self._drain(registry, records)

        self.assertEqual(registry.account_spend(ALICE)["committed"], 0.0)


class SpendSurvivesARestartTests(QuietCeilingLogMixin, unittest.TestCase):
    """The durable rows are what the cap is summed over."""

    def test_a_fresh_registry_on_the_same_store_still_refuses(self) -> None:
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        cap = CALL_COST * 1.5
        before = _registry(BudgetRunner(calls=1), persistence=store, max_run_cost_usd=0)
        for _ in range(2):
            record = _launch(before, ALICE, cap=cap)
            before.wait(record.run_id, timeout=10)
        before.close()

        after = _registry(BudgetRunner(calls=1), persistence=store, max_run_cost_usd=0)
        self.addCleanup(after.close)
        self.assertAlmostEqual(after.account_spend(ALICE)["spent"], CALL_COST * 2, places=6)
        with self.assertRaises(AccountSpendCapError):
            _launch(after, ALICE, cap=cap)
        # Somebody else's rows are not this account's spend.
        self.assertEqual(after.account_spend(BOB)["spent"], 0.0)

    def test_the_store_sums_only_the_named_account_and_can_exclude_runs(self) -> None:
        store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(store.close)
        registry = _registry(BudgetRunner(calls=1), persistence=store, max_run_cost_usd=0)
        self.addCleanup(registry.close)
        alice = _launch(registry, ALICE, cap=CALL_COST * 10)
        bob = _launch(registry, BOB, cap=CALL_COST * 10)
        registry.wait(alice.run_id, timeout=10)
        registry.wait(bob.run_id, timeout=10)
        self.assertAlmostEqual(float(store.user_spend_usd(ALICE)), CALL_COST, places=6)
        self.assertEqual(float(store.user_spend_usd(ALICE, exclude_run_ids=[alice.run_id])), 0.0)
        self.assertEqual(float(store.user_spend_usd("")), 0.0)


@unittest.skipUnless(
    FASTAPI_AVAILABLE,
    "FastAPI is not installed; install the existing project service extra",
)
class AccountSpendCapOverHttpTests(QuietCeilingLogMixin, unittest.TestCase):
    """402, with both figures, and only for the accounts it applies to."""

    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient

        from brief_crew.service.app import create_app

        # Smaller than one synthetic run's fabricated spend, so the FIRST run
        # uses the allowance up and the second is refused. The synthetic double
        # prices its calls through `compute_cost_usd`, so this is real
        # arithmetic over PRICES and not a magic number.
        patches = [
            patch.object(config, "USER_SPEND_CAP_USD", 0.0001),
            patch.object(config, "USER_SPEND_CAP_EXEMPT", ("owner@synthetic",)),
            patch.object(config, "_USER_SPEND_CAP_EXEMPT_LOWER", frozenset({"owner@synthetic"})),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = create_app(synthetic=True)
        self.registry = self.app.state.run_registry
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _launch(self, user: str | None) -> object:
        headers = {"X-Synthetic-User": user} if user else {}
        return self.client.post(
            "/api/sessions/session-cap-http/runs",
            json={
                "workflow_id": VALIDATOR_GRAPH.id,
                "inputs": {"idea": "A classroom polling assistant"},
                "gates": "auto",
            },
            headers=headers,
        )

    def _settle(self, run_id: str, user: str | None) -> dict:
        self.registry.wait(run_id, timeout=10)
        headers = {"X-Synthetic-User": user} if user else {}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = self.client.get(f"/api/runs/{run_id}", headers=headers).json()
            if status["status"] in {"completed", "failed", "cancelled"}:
                return status
            time.sleep(0.02)
        raise AssertionError(f"run {run_id} never reached a terminal state")

    def test_a_capped_account_is_refused_with_402_once_it_has_spent_its_allowance(self) -> None:
        first = self._launch("alice")
        self.assertEqual(first.status_code, 202, first.text)
        status = self._settle(first.json()["run_id"], "alice")
        self.assertGreater(status["usage"]["cost_usd"], config.USER_SPEND_CAP_USD)

        second = self._launch("alice")
        self.assertEqual(second.status_code, 402, second.text)
        detail = second.json()["detail"]
        self.assertIn("$0.00 spend allowance", detail)
        self.assertIn("USER_SPEND_CAP_USD", detail)
        self.assertIn("exempt your account", detail)
        self.assertNotIn("alice", detail)

    def test_an_exempt_account_and_an_anonymous_caller_are_not_capped(self) -> None:
        for _ in range(2):
            owner = self._launch("owner")
            self.assertEqual(owner.status_code, 202, owner.text)
            self._settle(owner.json()["run_id"], "owner")
        with patch.object(config, "VALIDATOR_ALLOW_AUTO_GATES", True):
            for _ in range(2):
                nobody = self._launch(None)
                self.assertEqual(nobody.status_code, 202, nobody.text)
                self._settle(nobody.json()["run_id"], None)

    def test_a_dry_run_is_answered_before_the_cap_is_consulted(self) -> None:
        first = self._launch("alice")
        self._settle(first.json()["run_id"], "alice")
        preview = self.client.post(
            "/api/sessions/session-cap-http/runs",
            json={
                "workflow_id": VALIDATOR_GRAPH.id,
                "inputs": {"idea": "A classroom polling assistant"},
                "mode": "dry_run",
            },
            headers={"X-Synthetic-User": "alice"},
        )
        # The validator is Python, so its dry run is a 422 from `dry_run_payload`
        # - which is answered ABOVE the cap. A 402 here would mean the order
        # had moved; the sentence is the preview's own, not the cap's.
        self.assertEqual(preview.status_code, 422, preview.text)
        self.assertIn("dry run", preview.json()["detail"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
