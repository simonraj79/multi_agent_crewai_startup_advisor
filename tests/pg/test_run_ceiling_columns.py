"""The three ceiling columns reach a SHIPPED PostgreSQL `runs` table - audit H1 follow-up.

`tests/service/test_additive_migration.py::RunCeilingColumnsTests` proves the
same migration on SQLite, which is what every other test in this repository
runs on. That is not enough for this particular change, for two reasons that
only PostgreSQL can answer:

* **SQLite's `ALTER TABLE ... ADD COLUMN` is permissive to the point of being
  uninformative.** It accepts a type name it does not implement and stores
  whatever it is given (`NUMERIC(12, 6)` included), so a green SQLite run says
  the statement parsed, not that the column production gets is the column the
  `Table()` definition describes. PostgreSQL is the dialect the deployed API
  runs on (`/readyz` answers `"backend":"postgresql"`), and it either creates a
  `numeric(12,6)` or refuses.
* **The value is money, and it round-trips through `Numeric`.** `Decimal` is
  native on PostgreSQL and emulated on SQLite, so the write-then-read assertion
  at the bottom is a different assertion on the two dialects and only one of
  them is the one that ships.

The shape is `tests/pg/test_two_writers.py`'s, deliberately: skipped unless
`TEST_DATABASE_URL` is set, and a throwaway database created on the server that
URL names, so nothing is written into the database itself. Its
`_throwaway_database` is imported rather than copied - a copy is how two halves
drift, and this module wants exactly the same create-and-drop.

Local recipe (Docker):

    docker start pg18-test          # or: docker run --name pg18-test \\
                                    #   -e POSTGRES_PASSWORD=test -p 5433:5432 -d postgres:18
    $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres"
    .\\.venv\\Scripts\\python.exe -m unittest tests.pg.test_run_ceiling_columns -v

In CI the `postgres` job in `.github/workflows/ci.yml` provides the service and
sets the same variable; it runs on `main` only (PLANS.md decision 25).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest

from tests.pg.test_two_writers import _throwaway_database

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

#: `runs` as PostgreSQL held it at `ea611a9` - the audit-fix merge, one commit
#: before the ceiling columns existed. Raw DDL rather than the `Table` object
#: with three columns removed, for the reason the SQLite module gives: the
#: latter is not what a deployed database contains.
SHIPPED_RUNS_DDL = """
CREATE TABLE runs (
    id VARCHAR(128) NOT NULL PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128),
    workflow_id VARCHAR(128) NOT NULL,
    flow_id VARCHAR(128),
    graph_version VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    mode VARCHAR(16),
    inputs JSONB NOT NULL,
    usage JSONB NOT NULL,
    result JSONB,
    error TEXT,
    captured_frames INTEGER NOT NULL,
    dropped_frames INTEGER NOT NULL,
    frame_gaps INTEGER NOT NULL,
    emit_errors INTEGER NOT NULL,
    subscriber_dropped INTEGER NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
)
"""

SHIPPED_ROW = """
INSERT INTO runs VALUES (
    'capped-before-the-columns', 's', 'alice', 'idea-validator', NULL, 'v1',
    'queued', NULL, '{}'::jsonb, '{}'::jsonb, NULL, NULL, 0, 0, 0, 0, 0,
    now(), now(), NULL, now()
)
"""

CEILING_COLUMNS = ("max_cost_usd", "ceiling_kind", "account_cap_usd")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not set; see the module docstring")
class RunCeilingColumnsOnPostgres(unittest.TestCase):
    """One throwaway database per test, as the two-writers module does."""

    def setUp(self) -> None:
        from sqlalchemy import create_engine, text

        self.database_url, drop_database = _throwaway_database(TEST_DATABASE_URL)
        self.addCleanup(drop_database)
        self.engine = create_engine(self.database_url)
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text(SHIPPED_RUNS_DDL))
            connection.execute(text(SHIPPED_ROW))

    def columns(self) -> dict[str, object]:
        from sqlalchemy import inspect

        return {c["name"]: c["type"] for c in inspect(self.engine).get_columns("runs")}

    def upgrade(self):
        from brief_crew.service.persistence import PostgresFlowPersistence

        store = PostgresFlowPersistence(self.database_url, initialize=False)
        self.addCleanup(store.close)
        store.init_db()
        return store

    def test_the_fixture_really_is_the_shipped_shape(self) -> None:
        """The control. Every assertion below must be able to fail."""

        present = self.columns()
        self.assertIn("user_id", present)
        self.assertIn("mode", present)
        for name in CEILING_COLUMNS:
            with self.subTest(column=name):
                self.assertNotIn(name, present)

    def test_init_db_adds_all_three_to_a_shipped_table(self) -> None:
        self.upgrade()
        present = self.columns()
        for name in CEILING_COLUMNS:
            with self.subTest(column=name):
                self.assertIn(name, present)

    def test_the_money_columns_really_are_numeric_12_6(self) -> None:
        """The assertion SQLite cannot make.

        It stores what it is handed and reports the declared text back; here
        the server has to have created a real `numeric(12,6)`, or the value a
        cap is compared against is a float with a different rounding rule from
        the one `run_node_metrics.cost_usd` already uses.
        """

        self.upgrade()
        present = self.columns()
        for name in ("max_cost_usd", "account_cap_usd"):
            with self.subTest(column=name):
                column_type = present[name]
                self.assertEqual(column_type.__class__.__name__, "NUMERIC")
                self.assertEqual((column_type.precision, column_type.scale), (12, 6))
        self.assertEqual(present["ceiling_kind"].length, 16)

    def test_the_row_written_before_them_keeps_three_nulls(self) -> None:
        from sqlalchemy import text

        self.upgrade()
        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT id, max_cost_usd, ceiling_kind, account_cap_usd FROM runs")
            ).one()
        self.assertEqual(row.id, "capped-before-the-columns")
        self.assertIsNone(row.max_cost_usd)
        self.assertIsNone(row.ceiling_kind)
        self.assertIsNone(row.account_cap_usd)

    def test_the_null_row_reads_back_as_no_ceiling_recorded(self) -> None:
        """NULL means "the process defaults", which is what the row already meant."""

        store = self.upgrade()
        snapshot = store.get_run("capped-before-the-columns")
        self.assertIsNone(snapshot["max_cost_usd"])
        self.assertIsNone(snapshot["account_cap_usd"])
        self.assertEqual(snapshot["ceiling_kind"], "run")

    def test_a_capped_run_round_trips_through_the_new_columns(self) -> None:
        """Write then read on the dialect that ships, with a Decimal in between."""

        store = self.upgrade()
        created = store.create_run(
            run_id="capped-after-the-columns",
            session_id="s",
            workflow_id="idea-validator",
            graph_version="v1",
            inputs={"idea": "x"},
            user_id="alice",
            max_cost_usd=1.0,
            ceiling_kind="account",
            account_cap_usd=1.0,
            created_at=datetime.now(timezone.utc),
        )
        self.assertEqual(created["max_cost_usd"], 1.0)
        self.assertEqual(created["ceiling_kind"], "account")
        self.assertEqual(created["account_cap_usd"], 1.0)

        from sqlalchemy import text

        with self.engine.begin() as connection:
            stored = connection.execute(
                text(
                    "SELECT max_cost_usd, ceiling_kind, account_cap_usd FROM runs "
                    "WHERE id = 'capped-after-the-columns'"
                )
            ).one()
        # The server's own value, not the mapper's: `Decimal`, exact, scale 6.
        self.assertEqual(stored.max_cost_usd, Decimal("1.000000"))
        self.assertEqual(stored.ceiling_kind, "account")
        self.assertEqual(stored.account_cap_usd, Decimal("1.000000"))

    def test_running_it_twice_changes_nothing(self) -> None:
        """It runs on every boot, so it has to be safe on every boot."""

        from sqlalchemy import text

        self.upgrade()
        before = set(self.columns())
        self.upgrade()
        self.assertEqual(set(self.columns()), before)
        with self.engine.begin() as connection:
            self.assertEqual(
                connection.execute(text("SELECT COUNT(*) FROM runs")).scalar_one(), 1
            )


if __name__ == "__main__":  # pragma: no cover - parity with the other suites
    unittest.main()
