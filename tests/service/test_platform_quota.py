"""The per-user daily meter on a PLATFORM key - audit H4, the counter half.

`BUILDER_PLATFORM_FIRECRAWL_DEFAULT` hands the deployment's own Firecrawl key
to every signed-in user's research tools. Its manifest comment cited
`BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` as the bound, and that constant had
exactly one reader - its own definition in `config.py`. So the grant was
unbounded, and invisible to both spend caps: `MAX_RUN_COST_USD` and
`USER_SPEND_CAP_USD` are computed from LLM token events and a Firecrawl call
raises none.

This module pins the storage layer on SQLite: the cap holds, one user's
spending does not reach another's, the day boundary is UTC, and four threads
racing the last units never hand out more than the cap.
`tests/pg/test_platform_quota.py` drives two real PROCESSES into the same
UPDATE on PostgreSQL, which is the only dialect where a row lock is what
decides it.

The thread race here is worth naming for what it does and does not prove.
SQLite is a single writer, so it proves the API is safe to call concurrently
and that nothing in this method reads-then-writes across a transaction
boundary; it does not prove anything about row locks. That is the PostgreSQL
module's job, and it is the same division `test_orphan_sweep_claim.py` draws
against `tests/pg/test_two_writers.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
import unittest

from brief_crew.service.persistence import PostgresFlowPersistence, platform_tool_usage

PROVIDER = "firecrawl"
CAP = 50


class PlatformQuotaCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresFlowPersistence("sqlite:///:memory:")
        self.addCleanup(self.store.close)

    def test_the_table_exists_after_create_all(self) -> None:
        """A NEW table, so `create_all` makes it whole - no additive column."""

        from sqlalchemy import inspect

        inspector = inspect(self.store.engine)
        self.assertIn("platform_tool_usage", set(inspector.get_table_names()))
        columns = {
            column["name"] for column in inspector.get_columns("platform_tool_usage")
        }
        self.assertEqual(
            columns, {"user_id", "provider", "utc_day", "used", "updated_at"}
        )

    def test_fifty_claims_are_granted_and_the_fifty_first_is_refused(self) -> None:
        for expected in range(1, CAP + 1):
            granted, used = self.store.claim_platform_quota("alice", PROVIDER, CAP)
            self.assertTrue(granted, f"claim {expected} was refused")
            self.assertEqual(used, expected)

        granted, used = self.store.claim_platform_quota("alice", PROVIDER, CAP)
        self.assertFalse(granted)
        # The refusal reports what is spent, not what would have been spent.
        self.assertEqual(used, CAP)
        self.assertEqual(self.store.platform_quota_used("alice", PROVIDER), CAP)

    def test_a_different_user_is_unaffected_by_a_spent_account(self) -> None:
        for _ in range(CAP):
            self.store.claim_platform_quota("alice", PROVIDER, CAP)
        self.assertFalse(self.store.claim_platform_quota("alice", PROVIDER, CAP)[0])

        granted, used = self.store.claim_platform_quota("bob", PROVIDER, CAP)
        self.assertTrue(granted)
        self.assertEqual(used, 1)
        self.assertEqual(self.store.platform_quota_used("alice", PROVIDER), CAP)

    def test_a_different_provider_has_its_own_allowance(self) -> None:
        for _ in range(CAP):
            self.store.claim_platform_quota("alice", PROVIDER, CAP)
        granted, used = self.store.claim_platform_quota("alice", "somethingelse", CAP)
        self.assertTrue(granted)
        self.assertEqual(used, 1)

    def test_the_next_utc_day_resets_it(self) -> None:
        today = datetime(2026, 9, 7, 23, 59, 59, tzinfo=timezone.utc)
        for _ in range(CAP):
            self.store.claim_platform_quota("alice", PROVIDER, CAP, now=today)
        self.assertFalse(
            self.store.claim_platform_quota("alice", PROVIDER, CAP, now=today)[0]
        )

        # One second later is a new UTC day and a fresh allowance; the spent
        # day is still spent, so this is a reset and not an amnesty.
        tomorrow = today + timedelta(seconds=1)
        granted, used = self.store.claim_platform_quota(
            "alice", PROVIDER, CAP, now=tomorrow
        )
        self.assertTrue(granted)
        self.assertEqual(used, 1)
        self.assertEqual(
            self.store.platform_quota_used("alice", PROVIDER, now=today), CAP
        )

    def test_the_day_boundary_is_utc_and_not_the_callers_offset(self) -> None:
        """An offset datetime lands on the day UTC says, always."""

        # 2026-09-07T20:00 at UTC-08:00 is 2026-09-08T04:00 UTC: the NEXT day.
        west = datetime(2026, 9, 7, 20, 0, tzinfo=timezone(timedelta(hours=-8)))
        self.store.claim_platform_quota("alice", PROVIDER, CAP, now=west)
        self.assertEqual([row["utc_day"] for row in self._rows("alice")], ["2026-09-08"])

    def test_a_cap_of_zero_refuses_and_writes_nothing(self) -> None:
        granted, used = self.store.claim_platform_quota("alice", PROVIDER, 0)
        self.assertFalse(granted)
        self.assertEqual(used, 0)
        self.assertEqual(self._rows("alice"), [])

    def test_a_lowered_cap_refuses_an_account_already_over_it(self) -> None:
        """The knob can move after the day started; the row is still right."""

        for _ in range(10):
            self.store.claim_platform_quota("alice", PROVIDER, CAP)
        granted, used = self.store.claim_platform_quota("alice", PROVIDER, 5)
        self.assertFalse(granted)
        self.assertEqual(used, 10)

    def test_four_threads_racing_the_last_units_never_exceed_the_cap(self) -> None:
        """Four threads, twenty claims against a cap of eight, one store."""

        cap = 8
        attempts = 20
        granted: list[bool] = []
        lock = threading.Lock()
        start = threading.Barrier(4)

        def claim() -> None:
            start.wait(timeout=30)
            for _ in range(attempts // 4):
                ok, _used = self.store.claim_platform_quota("alice", PROVIDER, cap)
                with lock:
                    granted.append(ok)

        threads = [threading.Thread(target=claim) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
            self.assertFalse(thread.is_alive())

        self.assertEqual(len(granted), attempts)
        self.assertEqual(sum(granted), cap, "more units were handed out than the cap")
        self.assertEqual(self.store.platform_quota_used("alice", PROVIDER), cap)

    def test_used_reads_zero_for_an_account_that_has_never_claimed(self) -> None:
        self.assertEqual(self.store.platform_quota_used("nobody", PROVIDER), 0)

    def _rows(self, user_id: str) -> list[dict]:
        from sqlalchemy import select

        with self.store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(platform_tool_usage).where(
                        platform_tool_usage.c.user_id == user_id
                    )
                ).mappings()
            ]


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
