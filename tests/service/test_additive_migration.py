"""`init_db` against a database that already shipped.

`metadata.create_all()` is create-if-absent **per table**. It does nothing at
all to a table that already exists, so a column added to a `Table()` definition
appears on a fresh database and is silently missing on every deployed one - and
the failure is not at startup but at the first INSERT, which names the new
column and gets "no such column" from a production database mid-request.

Every other test in this suite starts from an empty file, so every other test
would pass while that was broken. This one builds the `runs` table **as it
shipped** - raw DDL, no `user_id`, no `ix_runs_user_created` - and then asserts
the upgrade. Raw DDL rather than the `Table` object with a column removed,
because the latter is not what a deployed database contains and a first attempt
at this test failed for exactly that reason: the index definition still
referenced the column that had been taken away.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from brief_crew.service.persistence import PostgresFlowPersistence

# The pre-authentication shape of `runs`, verbatim.
LEGACY_RUNS_DDL = """
CREATE TABLE runs (
    id VARCHAR(128) NOT NULL PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    workflow_id VARCHAR(128) NOT NULL,
    flow_id VARCHAR(128),
    graph_version VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    inputs JSON NOT NULL,
    usage JSON NOT NULL,
    result JSON,
    error TEXT,
    captured_frames INTEGER NOT NULL,
    dropped_frames INTEGER NOT NULL,
    frame_gaps INTEGER NOT NULL,
    emit_errors INTEGER NOT NULL,
    subscriber_dropped INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    started_at DATETIME,
    completed_at DATETIME,
    updated_at DATETIME NOT NULL
)
"""

LEGACY_ROW = (
    "INSERT INTO runs VALUES ('old-run','s','idea-validator',NULL,'v1',"
    "'completed','{}','{}',NULL,NULL,0,0,0,0,0,"
    "'2026-01-01','2026-01-01','2026-01-01','2026-01-01')"
)


class AdditiveMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(directory.name) / 'legacy.db'}")
        # Registered AFTER the directory so it runs BEFORE it - addCleanup is
        # LIFO. Windows refuses to unlink a file that still has an open handle,
        # so a temp dir removed while the engine holds the database raises
        # PermissionError and turns six passing tests into seven errors.
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text(LEGACY_RUNS_DDL))
            connection.execute(text(LEGACY_ROW))

    def columns(self) -> set[str]:
        return {c["name"] for c in inspect(self.engine).get_columns("runs")}

    def indexes(self) -> set[str]:
        return {i["name"] for i in inspect(self.engine).get_indexes("runs")}

    def upgrade(self) -> PostgresFlowPersistence:
        store = PostgresFlowPersistence(self.engine, initialize=False)
        store.init_db()
        return store

    def test_the_fixture_really_is_the_old_shape(self) -> None:
        """The control. Without it the test below could pass on a fresh table."""
        self.assertNotIn("user_id", self.columns())
        self.assertNotIn("ix_runs_user_created", self.indexes())

    def test_the_missing_column_is_added(self) -> None:
        self.upgrade()
        self.assertIn("user_id", self.columns())

    def test_the_index_on_the_new_column_is_created_too(self) -> None:
        """`create_all` only makes indexes alongside their own table.

        A table that already exists is skipped whole, index and all, so an index
        over a newly added column has to be asked for separately. Missing it
        costs a full scan of every run by every user on the one query the
        history list makes.
        """
        self.upgrade()
        self.assertIn("ix_runs_user_created", self.indexes())

    def test_rows_written_before_the_column_existed_survive_with_no_owner(self) -> None:
        """This is why `user_id` is NULLable and why it has no ForeignKey.

        There is no owner to invent for these rows. A NOT NULL column could not
        be added to the live table at all, and a constraint would fail the
        ALTER outright.
        """
        self.upgrade()
        with self.engine.begin() as connection:
            row = connection.execute(text("SELECT id, user_id FROM runs")).one()
        self.assertEqual(row.id, "old-run")
        self.assertIsNone(row.user_id)

    def test_running_it_twice_changes_nothing(self) -> None:
        """It runs on every boot, so it has to be safe on every boot."""
        self.upgrade()
        self.upgrade()
        self.assertIn("user_id", self.columns())
        with self.engine.begin() as connection:
            self.assertEqual(
                connection.execute(text("SELECT COUNT(*) FROM runs")).scalar_one(), 1
            )

    def test_it_is_safe_on_a_database_that_never_existed(self) -> None:
        """The fresh-install path still goes through create_all, not the ALTER."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        engine = create_engine(f"sqlite:///{Path(directory.name) / 'fresh.db'}")
        self.addCleanup(engine.dispose)
        PostgresFlowPersistence(engine, initialize=False).init_db()
        columns = {c["name"] for c in inspect(engine).get_columns("runs")}
        self.assertIn("user_id", columns)


if __name__ == "__main__":
    unittest.main()
