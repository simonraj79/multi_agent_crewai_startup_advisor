"""Plan 21 T1 on the dialect that ships: `runs.document_version`, `improve_digests`.

`tests/service/test_additive_migration.py::DocumentVersionColumnTests` proves
the same migration on SQLite, which is what every other test in this
repository runs on. That is not enough here, for the reasons
`tests/pg/test_rating_columns.py` and `tests/pg/test_run_ceiling_columns.py`
already give and one this plan adds:

* **SQLite's `ALTER TABLE ... ADD COLUMN` is permissive to the point of being
  uninformative.** It accepts a type name it does not implement and stores
  whatever it is handed, so a green SQLite run says the statement parsed, not
  that the column production gets is the column the `Table()` describes.
  PostgreSQL either creates a real `integer` or refuses.
* **`improve_digests` takes a DIFFERENT route from the column beside it.** It
  is a new table, so `create_all()` makes it whole and `_ADDITIVE_COLUMNS`
  neither does nor should carry a row for it - and `create_all()` is
  create-if-absent PER TABLE, so the one thing worth proving is that it
  really does create a new table on a database that already has `runs`. That
  is the half a fresh-database test cannot reach.
* **`numeric(12, 6)` is money.** `cost_usd` comes back as a `Decimal` here and
  as a float on SQLite, and `digest_cost_total` sums in the column rather than
  in Python - so a `None` row contributing nothing (never a zero) is only
  proved on the dialect that has the type.

Skipped unless `TEST_DATABASE_URL` is set, and a throwaway database is created
on the server that URL names, so nothing is written into the database itself.
`_throwaway_database` is IMPORTED from `test_two_writers` rather than copied -
a copy is how two halves drift.

Local recipe (Docker):

    docker start pg18-test
    $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres"
    .\\.venv\\Scripts\\python.exe -m unittest tests.pg.test_document_version_column -v
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from tests.pg.test_run_ceiling_columns import SHIPPED_RUNS_DDL, SHIPPED_ROW
from tests.pg.test_two_writers import _throwaway_database

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

DIGEST_COLUMNS = {
    "id",
    "workflow_id",
    "created_by",
    "window_from",
    "window_to",
    "sample_runs",
    "sample_frames",
    "truncated_sample",
    "model",
    "prompt_tokens",
    "completion_tokens",
    "cost_usd",
    "over_cap",
    "error",
    "body",
    "created_at",
}


@unittest.skipUnless(
    TEST_DATABASE_URL, "TEST_DATABASE_URL is not set; see the module docstring"
)
class DocumentVersionOnPostgres(unittest.TestCase):
    """One throwaway database per test, as the two-writers module does.

    The fixture is `runs` as it shipped BEFORE the ceiling columns, so the
    migration under test adds eight columns to one table in one pass AND
    creates several new tables beside it - which is what a real deployment
    does on its next boot.
    """

    def setUp(self) -> None:
        from sqlalchemy import create_engine, text

        self.database_url, drop_database = _throwaway_database(TEST_DATABASE_URL)
        self.addCleanup(drop_database)
        self.engine = create_engine(self.database_url)
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text(SHIPPED_RUNS_DDL))
            connection.execute(text(SHIPPED_ROW))

    def columns(self, table: str = "runs") -> dict[str, object]:
        from sqlalchemy import inspect

        return {c["name"]: c["type"] for c in inspect(self.engine).get_columns(table)}

    def tables(self) -> set[str]:
        from sqlalchemy import inspect

        return set(inspect(self.engine).get_table_names())

    def upgrade(self):
        from brief_crew.service.persistence import PostgresFlowPersistence

        store = PostgresFlowPersistence(self.database_url, initialize=False)
        self.addCleanup(store.close)
        store.init_db()
        return store

    def test_the_fixture_really_is_the_shipped_shape(self) -> None:
        """The control. Every assertion below must be able to fail."""

        self.assertIn("user_id", self.columns())
        self.assertNotIn("document_version", self.columns())
        self.assertNotIn("improve_digests", self.tables())

    def test_init_db_adds_the_column_to_a_shipped_table(self) -> None:
        self.upgrade()
        self.assertIn("document_version", self.columns())

    def test_the_column_type_is_what_the_table_declares(self) -> None:
        """The assertion SQLite cannot make: a real `integer`, created here."""

        from sqlalchemy import Integer

        self.upgrade()
        self.assertIsInstance(self.columns()["document_version"], Integer)

    def test_the_row_written_before_it_keeps_a_null(self) -> None:
        from sqlalchemy import text

        self.upgrade()
        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT id, document_version FROM runs")
            ).one()
        self.assertEqual(row.id, "capped-before-the-columns")
        self.assertIsNone(row.document_version)

    def test_create_run_stamps_it_and_improve_runs_reads_it_back(self) -> None:
        store = self.upgrade()
        store.create_run(
            session_id="s1",
            workflow_id="ug_doc",
            graph_version="deadbeefdeadbeef",
            document_version=2,
        )
        store.create_run(
            session_id="s1",
            workflow_id="idea-validator",
            graph_version="cafecafecafecafe",
        )
        rows, truncated = store.improve_runs()
        self.assertFalse(truncated)
        versions = {row["workflow_id"]: row["document_version"] for row in rows}
        self.assertEqual(2, versions["ug_doc"])
        # NOT zero. A hand-written flow has no document, and "version 0" is a
        # version somebody could compare against that nothing ever wrote.
        self.assertIsNone(versions["idea-validator"])

    def test_create_all_makes_the_new_table_on_a_database_that_already_has_runs(
        self,
    ) -> None:
        """The half a fresh-database test cannot reach.

        `create_all()` is create-if-absent PER TABLE, which is the trap
        `_add_missing_columns` exists for on the column side; on the table side
        it is the thing that works, and this is where it is proved.
        """

        self.upgrade()
        self.assertIn("improve_digests", self.tables())
        self.assertEqual(DIGEST_COLUMNS, set(self.columns("improve_digests")))

    def test_the_new_table_takes_create_all_and_its_LATER_column_an_alter(
        self,
    ) -> None:
        """Both routes, and the pair is the point.

        The TABLE is made by `create_all()` - an `ALTER TABLE` against a table
        that does not exist yet would fail the boot it is supposed to survive.
        Its `error` column is a different case: it landed after the table did,
        so a database created in between has the table WITHOUT the column and
        `create_all()` does nothing to a table that already exists. That is
        exactly what `_ADDITIVE_COLUMNS` is for, and the assertion below
        changed from "not in the list" to "only this column is" when the money
        brakes landed.
        """

        rows = {
            (table, column)
            for table, column, _type in self.upgrade()._ADDITIVE_COLUMNS
        }
        improve = {column for table, column in rows if table == "improve_digests"}
        self.assertEqual({"error"}, improve)

    def test_the_new_table_carries_its_index(self) -> None:
        from sqlalchemy import inspect

        self.upgrade()
        names = {
            index["name"]
            for index in inspect(self.engine).get_indexes("improve_digests")
        }
        self.assertIn("ix_improve_digests_workflow", names)

    def test_a_review_round_trips_and_an_unpriced_one_contributes_nothing(
        self,
    ) -> None:
        """`None` is "no price on file" and 0.0 is "this call was free".

        `numeric(12, 6)` keeps them apart and `digest_cost_total` sums in the
        column, so an unpriced row adds nothing rather than a zero - which is
        the conflation that once priced 128,069 real tokens at $0.00.
        """

        store = self.upgrade()
        moment = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
        store.save_digest(
            {
                "id": "dg_00000001",
                "workflow_id": "ug_doc",
                "created_by": "user_alice",
                "window_from": moment,
                "window_to": moment,
                "sample_runs": 3,
                "sample_frames": 40,
                "truncated_sample": True,
                "model": "openrouter/x/cheap",
                "prompt_tokens": 1200,
                "completion_tokens": 300,
                "cost_usd": 0.004321,
                "over_cap": False,
                "error": None,
                "body": "## What went well\n\nNothing yet.",
                "created_at": moment,
            }
        )
        store.save_digest(
            {
                "id": "dg_00000002",
                "workflow_id": "ug_doc",
                "created_by": None,
                "window_from": moment,
                "window_to": moment,
                "model": "openrouter/x/unpriced",
                "cost_usd": None,
                "over_cap": True,
                "body": "",
                "created_at": moment,
            }
        )
        rows = store.list_digests("ug_doc")
        self.assertEqual(2, len(rows))
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(0.004321, by_id["dg_00000001"]["cost_usd"])
        self.assertTrue(by_id["dg_00000001"]["truncated_sample"])
        self.assertFalse(by_id["dg_00000001"]["over_cap"])
        self.assertIsNone(by_id["dg_00000002"]["cost_usd"])
        self.assertTrue(by_id["dg_00000002"]["over_cap"])
        self.assertIsNotNone(by_id["dg_00000001"]["created_at"].tzinfo)
        self.assertEqual(Decimal("0.004321"), store.digest_cost_total("ug_doc"))
        self.assertEqual(Decimal("0"), store.digest_cost_total("ug_other"))

    def test_running_it_twice_changes_nothing(self) -> None:
        """It runs on every boot, so it has to be safe on every boot."""

        from sqlalchemy import text

        self.upgrade()
        before = set(self.columns())
        self.upgrade()
        self.assertEqual(before, set(self.columns()))
        with self.engine.begin() as connection:
            self.assertEqual(
                1, connection.execute(text("SELECT COUNT(*) FROM runs")).scalar_one()
            )


if __name__ == "__main__":
    unittest.main()
