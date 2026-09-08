"""Two writers on the platform-key meter, PostgreSQL 18 - audit H4.

`claim_platform_quota` is the sixth `UPDATE ... WHERE ...; rowcount`
compare-and-set in this service, and it is the first one whose WHERE clause is
an inequality rather than an identity: `WHERE used < cap`. That difference is
exactly what needs a second writer on the dialect production runs on. SQLite is
a single writer, so `tests/service/test_platform_quota.py` proves the shape and
nothing about what PostgreSQL's row locks do when two transactions hold the
same row at once. This is that test, written in
`tests/pg/test_two_writers.py`'s shape and for the same reason.

Two races, and they decide different things:

| Race                | Winner            | Loser sees                          |
| ------------------- | ----------------- | ----------------------------------- |
| the LAST unit       | one CAS           | `rowcount == 0`, `(False, cap)`     |
| the FIRST claim     | one INSERT        | a unique violation, then the CAS    |

The first race is the one the cap depends on. Under READ COMMITTED the second
transaction blocks on the first's row lock and then RE-EVALUATES `used < cap`
against the committed row - so on a cap of one, two simultaneous claimants
produce exactly one grant. That re-evaluation is a PostgreSQL guarantee this
repository has never before relied on in an inequality, and it is why a
portable UPDATE was chosen over a dialect-specific `ON CONFLICT DO UPDATE ...
WHERE`: one code path, and this test drives it.

The second race is the day's first claim, where there is no row to lock. Both
children INSERT, one loses on the primary key, and `claim_platform_quota`
retries the UPDATE - so both still get a unit when the cap allows two, and the
table holds one row rather than two.

**Two PROCESSES, not threads** - SQLAlchemy pools are per process. The race is
made deterministic by two barriers: one releases both children together, the
second is taken INSIDE the transaction from a `before_cursor_execute` listener
at `UPDATE platform_tool_usage` (or `INSERT INTO platform_tool_usage`), so both
transactions are open at the decisive statement before either proceeds.

Skipped unless `TEST_DATABASE_URL` is set. The server it names is left as it
was found: a throwaway database `platform_quota_<hex>` is created for the run
and dropped afterwards.

Local recipe (Docker):

    docker start pg18-test
    $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres"
    .\\.venv\\Scripts\\python.exe -m unittest tests.pg.test_platform_quota -v
"""

from __future__ import annotations

import multiprocessing
import os
from typing import Any
import unittest
import uuid

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

PROVIDER = "firecrawl"
WRITERS = ("writer-a", "writer-b")
JOIN_TIMEOUT_SECONDS = 90
BARRIER_TIMEOUT_SECONDS = 60


# --------------------------------------------------------------------------
# The child. Module-level and picklable by name, because `spawn` re-imports
# this module in the child and looks the target up there.
# --------------------------------------------------------------------------
def _install_observers(engine: Any, prefixes: tuple[str, ...], at_statement: Any) -> dict[str, Any]:
    """Pause at the decisive statement and record its rowcount, once each."""

    from sqlalchemy import event

    observed: dict[str, Any] = {"rowcount": None, "held": False}

    def _decisive(statement: str) -> bool:
        lowered = statement.lstrip().lower()
        return any(lowered.startswith(prefix) for prefix in prefixes)

    @event.listens_for(engine, "before_cursor_execute")
    def _hold(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if not observed["held"] and _decisive(statement):
            observed["held"] = True
            at_statement.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    @event.listens_for(engine, "after_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if observed["rowcount"] is None and _decisive(statement):
            observed["rowcount"] = cursor.rowcount

    return observed


def _writer(
    database_url: str,
    user_id: str,
    cap: int,
    marker: str,
    released: Any,
    at_statement: Any,
    results: Any,
) -> None:
    """One of the two claimants. Reports a dict; never raises into the parent."""

    report: dict[str, Any] = {
        "marker": marker,
        "rowcount": None,
        "granted": None,
        "used": None,
        "error": None,
    }
    try:
        from brief_crew.service.persistence import PostgresFlowPersistence

        store = PostgresFlowPersistence(database_url, initialize=False)
        try:
            observed = _install_observers(
                store.engine,
                ("update platform_tool_usage", "insert into platform_tool_usage"),
                at_statement,
            )
            released.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            granted, used = store.claim_platform_quota(user_id, PROVIDER, cap)
            report["granted"] = bool(granted)
            report["used"] = int(used)
            report["rowcount"] = observed["rowcount"]
            report["held"] = observed["held"]
        finally:
            store.close()
    except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            at_statement.abort()
        except Exception:  # pragma: no cover - the barrier may already be gone
            pass
    results.put(report)


# --------------------------------------------------------------------------
# The parent.
# --------------------------------------------------------------------------
def _throwaway_database(admin_url: str) -> tuple[str, Any]:
    """A fresh database on the server `admin_url` names, and how to drop it."""

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    name = f"platform_quota_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(admin_url).set(database=name)

    def drop() -> None:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()

    return url.render_as_string(hide_password=False), drop


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not set; see the module docstring")
class PlatformQuotaOnPostgres(unittest.TestCase):
    """One throwaway database PER TEST, for the reason `test_two_writers` gives."""

    def setUp(self) -> None:
        from brief_crew.service.persistence import PostgresFlowPersistence

        self.database_url, drop_database = _throwaway_database(TEST_DATABASE_URL)
        self.addCleanup(drop_database)
        PostgresFlowPersistence(self.database_url).close()  # create_all
        self.store = PostgresFlowPersistence(self.database_url, initialize=False)
        self.addCleanup(self.store.close)
        self.spawn = multiprocessing.get_context("spawn")

    def race(self, user_id: str, cap: int) -> dict[str, dict[str, Any]]:
        """Two processes claiming one allowance, from two barriers."""

        released = self.spawn.Barrier(2)
        at_statement = self.spawn.Barrier(2)
        results = self.spawn.Queue()
        children = [
            self.spawn.Process(
                target=_writer,
                args=(self.database_url, user_id, cap, marker, released, at_statement, results),
                name=f"quota-{marker}",
            )
            for marker in WRITERS
        ]
        for child in children:
            child.start()
        reports: dict[str, dict[str, Any]] = {}
        try:
            for _ in children:
                report = results.get(timeout=JOIN_TIMEOUT_SECONDS)
                reports[report["marker"]] = report
        finally:
            for child in children:
                child.join(timeout=JOIN_TIMEOUT_SECONDS)
                if child.is_alive():
                    child.terminate()
        self.assertEqual(sorted(reports), sorted(WRITERS), reports)
        for marker, report in reports.items():
            self.assertIsNone(report["error"], f"{marker} raised: {report['error']}")
            self.assertTrue(report.get("held"), f"{marker} never reached the decisive statement")
        return reports

    def test_two_processes_racing_the_last_unit_and_only_one_gets_it(self) -> None:
        """The invariant. Cap one, one unit already spent by neither: one grant."""

        user_id = f"u-{uuid.uuid4().hex[:8]}"
        reports = self.race(user_id, cap=1)

        winners = [m for m, r in reports.items() if r["granted"]]
        self.assertEqual(len(winners), 1, {m: r for m, r in reports.items()})
        loser = next(m for m in WRITERS if m != winners[0])
        self.assertEqual(reports[winners[0]]["used"], 1)
        # The loser is told what is spent, and it is the cap - not two.
        self.assertFalse(reports[loser]["granted"])
        self.assertEqual(reports[loser]["used"], 1)
        self.assertEqual(self.store.platform_quota_used(user_id, PROVIDER), 1)

    def test_the_row_never_passes_the_cap_even_when_both_start_from_it(self) -> None:
        """The row already sits AT the cap: both must be refused, nothing moves."""

        user_id = f"u-{uuid.uuid4().hex[:8]}"
        self.assertEqual(self.store.claim_platform_quota(user_id, PROVIDER, 1), (True, 1))
        reports = self.race(user_id, cap=1)

        self.assertEqual([r["granted"] for r in reports.values()], [False, False])
        self.assertEqual({r["used"] for r in reports.values()}, {1})
        self.assertEqual({r["rowcount"] for r in reports.values()}, {0})
        self.assertEqual(self.store.platform_quota_used(user_id, PROVIDER), 1)

    def test_two_first_claimers_of_a_day_produce_one_row_and_two_units(self) -> None:
        """No row exists, so the INSERT races; the loser retries the UPDATE."""

        from sqlalchemy import func, select

        from brief_crew.service.persistence import platform_tool_usage

        user_id = f"u-{uuid.uuid4().hex[:8]}"
        reports = self.race(user_id, cap=5)

        self.assertEqual([r["granted"] for r in reports.values()], [True, True])
        self.assertEqual({r["used"] for r in reports.values()}, {1, 2})
        self.assertEqual(self.store.platform_quota_used(user_id, PROVIDER), 2)
        with self.store.connect() as connection:
            rows = connection.execute(
                select(func.count())
                .select_from(platform_tool_usage)
                .where(platform_tool_usage.c.user_id == user_id)
            ).scalar_one()
        self.assertEqual(int(rows), 1, "the losing INSERT left a second row behind")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
