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


class GauntletSchemaTests(AdditiveMigrationTests):
    """Contract C10 (.agent/plans/15-persistence.md D6) against a shipped `runs`.

    Same legacy fixture as the class above - `runs` as it shipped, no `user_id`,
    no `mode`, none of the five new tables - because that is what every deployed
    database looks like on the boot after this lands. The five tables are new,
    so `create_all()` makes them with their indexes and constraints; `mode` is
    a column on a table that already exists, so it has to come through
    `_ADDITIVE_COLUMNS` or it never reaches production at all.
    """

    EXPECTED_INDEXES = {
        "user_credentials": {"ix_user_credentials_user_kind"},
        "user_skills": {"ix_user_skills_user_updated"},
        "mcp_servers": {"ix_mcp_servers_user_updated"},
        "user_tools": set(),
        "builder_test_inputs": {"ix_builder_test_inputs_document_updated"},
    }
    EXPECTED_UNIQUE = {
        "user_credentials": {"uq_user_credentials_user_label"},
        "user_skills": {"uq_user_skills_user_name"},
        "mcp_servers": set(),
        "user_tools": {"uq_user_tools_user_name"},
        "builder_test_inputs": set(),
    }

    def test_the_fixture_has_no_mode_column_and_none_of_the_tables(self) -> None:
        """The control, again: the assertions below must be able to fail."""
        self.assertNotIn("mode", self.columns())
        tables = set(inspect(self.engine).get_table_names())
        for name in self.EXPECTED_INDEXES:
            self.assertNotIn(name, tables)

    def test_the_mode_column_is_added_to_a_shipped_runs_table(self) -> None:
        self.upgrade()
        self.assertIn("mode", self.columns())

    def test_a_row_written_before_mode_existed_keeps_a_null_mode(self) -> None:
        """NULL is the stored value; reading it as `run` is C7's rule, applied in
        the service layer by 10-runtime.md, not invented here by a DEFAULT that
        the ALTER could not apply to existing rows anyway."""
        self.upgrade()
        with self.engine.begin() as connection:
            row = connection.execute(text("SELECT id, mode FROM runs")).one()
        self.assertEqual(row.id, "old-run")
        self.assertIsNone(row.mode)

    def test_a_null_mode_reads_back_as_run_through_the_service_layer(self) -> None:
        """C7's half of it, and 10 criterion 9's second clause.

        The ALTER cannot backfill and a DEFAULT would not reach the rows that
        already exist, so the mapping has to be a READ. `run_mode` is the one
        place it happens, and `_run_dict` is the one caller - which is why a
        row from before the column and a row from an ordinary run are
        indistinguishable rather than merely similar.
        """

        from brief_crew.service.persistence import DEFAULT_RUN_MODE, run_mode

        self.upgrade()
        self.assertEqual(run_mode(None), "run")
        self.assertEqual(run_mode(""), "run")
        self.assertEqual(run_mode("   "), "run")
        self.assertEqual(run_mode("test"), "test")
        self.assertEqual(DEFAULT_RUN_MODE, "run")

    def test_the_upgraded_row_is_readable_and_says_run(self) -> None:
        """End to end over the ACTUAL legacy row, not over the mapper alone."""

        self.upgrade()
        store = PostgresFlowPersistence(self.engine, initialize=False)
        self.addCleanup(store.close)
        self.assertEqual(store.get_run("old-run")["mode"], "run")

    def test_all_five_tables_arrive_with_their_indexes_and_constraints(self) -> None:
        self.upgrade()
        inspector = inspect(self.engine)
        tables = set(inspector.get_table_names())
        for name, indexes in self.EXPECTED_INDEXES.items():
            with self.subTest(table=name):
                self.assertIn(name, tables)
                self.assertTrue(indexes <= {i["name"] for i in inspector.get_indexes(name)})
                self.assertTrue(
                    self.EXPECTED_UNIQUE[name]
                    <= {u["name"] for u in inspector.get_unique_constraints(name)}
                )
                self.assertIn("user_id", {c["name"] for c in inspector.get_columns(name)})

    def test_every_new_table_refuses_an_ownerless_row(self) -> None:
        """Isolation rule 1 (01 D2): `user_id` is NOT NULL on every new table.

        `runs.user_id` and `builder_documents.user_id` are nullable because they
        have legacy rows; these five have none, so the column can say so.
        """
        self.upgrade()
        inspector = inspect(self.engine)
        for name in self.EXPECTED_INDEXES:
            with self.subTest(table=name):
                column = next(c for c in inspector.get_columns(name) if c["name"] == "user_id")
                self.assertFalse(column["nullable"])

    def test_running_it_twice_is_still_a_no_op(self) -> None:
        self.upgrade()
        self.upgrade()
        self.assertIn("mode", self.columns())
        tables = set(inspect(self.engine).get_table_names())
        for name in self.EXPECTED_INDEXES:
            self.assertIn(name, tables)

    def test_a_fresh_database_has_mode_without_the_alter(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        engine = create_engine(f"sqlite:///{Path(directory.name) / 'fresh.db'}")
        self.addCleanup(engine.dispose)
        PostgresFlowPersistence(engine, initialize=False).init_db()
        columns = {c["name"] for c in inspect(engine).get_columns("runs")}
        self.assertIn("mode", columns)
        self.assertTrue(set(self.EXPECTED_INDEXES) <= set(inspect(engine).get_table_names()))


# `builder_documents` and `builder_document_versions` exactly as they shipped
# on 2026-09-02 (`b4ef654`), before `source` existed.
LEGACY_BUILDER_DOCUMENTS_DDL = """
CREATE TABLE builder_documents (
    id VARCHAR(128) NOT NULL PRIMARY KEY,
    user_id VARCHAR(128),
    name VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL,
    status VARCHAR(16) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""
LEGACY_BUILDER_VERSIONS_DDL = """
CREATE TABLE builder_document_versions (
    document_id VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL,
    document JSON NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (document_id, version),
    FOREIGN KEY(document_id) REFERENCES builder_documents (id) ON DELETE CASCADE
)
"""
LEGACY_BUILDER_ROWS = (
    "INSERT INTO builder_documents VALUES ('ug_0ld0ld00',NULL,'Old graph',1,'draft',"
    "'2026-09-02','2026-09-02')",
    "INSERT INTO builder_document_versions VALUES ('ug_0ld0ld00',1,'{\"name\":\"Old graph\"}',"
    "'2026-09-02')",
)


class VersionSourceColumnTests(unittest.TestCase):
    """Plan 15 D6 amended 2026-09-03 (C10; round 2 D-15-3): `builder_document_versions.source`.

    The second column to reach a SHIPPED table by the additive path. The
    fixture is the two builder tables as `b4ef654` created them, with one
    version row; `init_db` must add the column, leave that row's source NULL
    (which the route reads as `stored`), and do nothing on a second call.
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(directory.name) / 'legacy-builder.db'}")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text(LEGACY_BUILDER_DOCUMENTS_DDL))
            connection.execute(text(LEGACY_BUILDER_VERSIONS_DDL))
            for statement in LEGACY_BUILDER_ROWS:
                connection.execute(text(statement))

    def columns(self) -> set[str]:
        return {c["name"] for c in inspect(self.engine).get_columns("builder_document_versions")}

    def upgrade(self) -> PostgresFlowPersistence:
        store = PostgresFlowPersistence(self.engine, initialize=False)
        store.init_db()
        return store

    def test_the_fixture_really_is_the_shipped_shape(self) -> None:
        self.assertNotIn("source", self.columns())

    def test_the_source_column_is_added_to_a_shipped_versions_table(self) -> None:
        self.upgrade()
        self.assertIn("source", self.columns())

    def test_a_row_written_before_source_existed_keeps_a_null_source(self) -> None:
        self.upgrade()
        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT document_id, version, source FROM builder_document_versions")
            ).one()
        self.assertEqual((row.document_id, row.version), ("ug_0ld0ld00", 1))
        self.assertIsNone(row.source)

    def test_running_it_twice_changes_nothing(self) -> None:
        self.upgrade()
        before = self.columns()
        self.upgrade()
        self.assertEqual(self.columns(), before)

    def test_a_fresh_database_has_source_without_the_alter(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        engine = create_engine(f"sqlite:///{Path(directory.name) / 'fresh.db'}")
        self.addCleanup(engine.dispose)
        PostgresFlowPersistence(engine, initialize=False).init_db()
        columns = {c["name"] for c in inspect(engine).get_columns("builder_document_versions")}
        self.assertIn("source", columns)


# `runs` exactly as it SHIPPED at `ea611a9` - the audit-fix merge, one commit
# before the three ceiling columns existed. `user_id` and `mode` are on it,
# because both reached production through this same list long ago; what is
# absent is the ceiling a run was admitted under.
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

SHIPPED_ROW = (
    "INSERT INTO runs VALUES ('capped-before-the-columns','s','alice',"
    "'idea-validator',NULL,'v1','queued',NULL,'{}','{}',NULL,NULL,0,0,0,0,0,"
    "'2026-09-07','2026-09-07',NULL,'2026-09-07')"
)

CEILING_COLUMNS = ("max_cost_usd", "ceiling_kind", "account_cap_usd")


class RunCeilingColumnsTests(unittest.TestCase):
    """Audit H1 follow-up: `runs.max_cost_usd` / `ceiling_kind` / `account_cap_usd`.

    The third, fourth and fifth columns to reach a SHIPPED table by the
    additive path, and the reason they had to: a run's ceiling was decided at
    admission and kept only on the in-memory `RunRecord`, so a $1-capped
    account's run came back after any restart under the global $10 ceiling and
    its outstanding promise vanished from `account_spend`'s committed figure.

    The fixture is `runs` as `ea611a9` left it - `user_id` and `mode` present,
    the three absent - with one queued row owned by `alice`, which is exactly
    the row the migration must add columns to without disturbing.
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(directory.name) / 'shipped.db'}")
        self.addCleanup(self.engine.dispose)
        with self.engine.begin() as connection:
            connection.execute(text(SHIPPED_RUNS_DDL))
            connection.execute(text(SHIPPED_ROW))

    def columns(self) -> set[str]:
        return {c["name"] for c in inspect(self.engine).get_columns("runs")}

    def upgrade(self) -> PostgresFlowPersistence:
        store = PostgresFlowPersistence(self.engine, initialize=False)
        store.init_db()
        self.addCleanup(store.close)
        return store

    def test_the_fixture_really_is_the_shipped_shape(self) -> None:
        """The control. Without it every assertion below could pass on a fresh table."""

        present = self.columns()
        self.assertIn("user_id", present)
        self.assertIn("mode", present)
        for name in CEILING_COLUMNS:
            with self.subTest(column=name):
                self.assertNotIn(name, present)

    def test_the_three_columns_are_added_to_a_shipped_runs_table(self) -> None:
        self.upgrade()
        for name in CEILING_COLUMNS:
            with self.subTest(column=name):
                self.assertIn(name, self.columns())

    def test_a_row_written_before_them_keeps_three_nulls(self) -> None:
        """Nothing is backfilled, and nothing could be.

        The cap in force when this row was admitted was never recorded, and
        `config.user_spend_cap_usd` exempts by e-mail as well as by id - so a
        value derived here would silently cap an exempt owner after a deploy.
        """

        self.upgrade()
        with self.engine.begin() as connection:
            row = connection.execute(
                text("SELECT id, max_cost_usd, ceiling_kind, account_cap_usd FROM runs")
            ).one()
        self.assertEqual(row.id, "capped-before-the-columns")
        self.assertIsNone(row.max_cost_usd)
        self.assertIsNone(row.ceiling_kind)
        self.assertIsNone(row.account_cap_usd)

    def test_the_null_row_reads_back_as_no_ceiling_recorded_and_kind_run(self) -> None:
        """The read mapping, at the layer restart recovery actually consults.

        `max_cost_usd` and `account_cap_usd` stay None rather than becoming 0,
        because 0 is a legitimate value for the first - it means *no* per-run
        ceiling - so folding a missing value into it would turn an unrecorded
        ceiling into an unlimited one. `ceiling_kind` can be defaulted, because
        `run` is the only thing a NULL there ever meant.
        """

        store = self.upgrade()
        snapshot = store.get_run("capped-before-the-columns")
        self.assertIsNone(snapshot["max_cost_usd"])
        self.assertIsNone(snapshot["account_cap_usd"])
        self.assertEqual(snapshot["ceiling_kind"], "run")

    def test_the_null_row_rehydrates_to_the_process_defaults(self) -> None:
        """End to end: what a legacy row becomes when a registry restores it.

        Exactly the behaviour it had before these columns existed, which is
        the whole claim a NULL makes.
        """

        from brief_crew.config import MAX_RUN_COST_USD
        from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
        from brief_crew.service.registry import RunRegistry, WorkflowRuntime
        from brief_crew.service.runner import SyntheticValidatorRunner

        store = self.upgrade()
        runner = SyntheticValidatorRunner()
        registry = RunRegistry(
            graph_version=VALIDATOR_GRAPH.version,
            node_registry=VALIDATOR_NODE_REGISTRY,
            runner=runner,
            workflows={
                VALIDATOR_GRAPH.id: WorkflowRuntime(
                    graph_version=VALIDATOR_GRAPH.version,
                    node_registry=VALIDATOR_NODE_REGISTRY,
                    runner=runner,
                )
            },
            persistence=store,
            gate_sweep_interval=0.0,
            recover_orphans=False,
        )
        self.addCleanup(registry.close)

        restored = registry.require("capped-before-the-columns")
        self.assertEqual(restored.max_cost_usd, MAX_RUN_COST_USD)
        self.assertEqual(restored.ceiling_kind, "run")
        self.assertIsNone(restored.account_cap_usd)

    def test_running_it_twice_changes_nothing(self) -> None:
        """It runs on every boot, so it has to be safe on every boot."""

        self.upgrade()
        before = self.columns()
        self.upgrade()
        self.assertEqual(self.columns(), before)
        with self.engine.begin() as connection:
            self.assertEqual(
                connection.execute(text("SELECT COUNT(*) FROM runs")).scalar_one(), 1
            )

    def test_a_fresh_database_has_all_three_without_the_alter(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        engine = create_engine(f"sqlite:///{Path(directory.name) / 'fresh.db'}")
        self.addCleanup(engine.dispose)
        PostgresFlowPersistence(engine, initialize=False).init_db()
        columns = {c["name"] for c in inspect(engine).get_columns("runs")}
        for name in CEILING_COLUMNS:
            with self.subTest(column=name):
                self.assertIn(name, columns)

    def test_each_column_is_declared_in_the_additive_list_too(self) -> None:
        """A `Table()` column with no `_ADDITIVE_COLUMNS` row reaches a fresh
        database and no deployed one, and the failure is the first INSERT
        naming it - in production, mid-request. This is the pin for that."""

        # Read off an INSTANCE: `PostgresFlowPersistence` is a pydantic model,
        # so an underscore-prefixed class attribute is a `ModelPrivateAttr` on
        # the class and the tuple itself only on an instance - which is also
        # the spelling `_add_missing_columns` uses.
        declared = {
            (table, column)
            for table, column, _type in self.upgrade()._ADDITIVE_COLUMNS
        }
        for name in CEILING_COLUMNS:
            with self.subTest(column=name):
                self.assertIn(("runs", name), declared)


if __name__ == "__main__":
    unittest.main()
