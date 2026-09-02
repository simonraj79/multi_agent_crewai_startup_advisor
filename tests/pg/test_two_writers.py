"""Two writers on PostgreSQL 18 - plan 15 D8; CLAUDE.md remaining-work item 3.

Five paths in this service decide a race with `UPDATE ... WHERE ...` and
`rowcount`, and until this module none of them had ever met a second writer on
the dialect production runs on. SQLite is a single-writer database: every
existing test of these paths proves the SHAPE of the compare-and-set and
nothing about what PostgreSQL's row locks do when two transactions hold the
same row at once. `builder/store.py` was written to match the four older paths
precisely so that one test would cover all five. This is that test.

| Path                     | Winner                | Loser sees                             |
| ------------------------ | --------------------- | -------------------------------------- |
| `pending_feedback` write | one insert            | integrity error -> handled as pending  |
| gate reply               | one CAS               | `GateAnswerResult.conflict` (the 409)  |
| `reopen_gate` rollback   | one CAS               | no-op, gate already open               |
| orphan sweep fail        | one CAS (the claim)   | row already terminal                   |
| document `save`          | one CAS               | `DocumentVersionConflict` (the 409)    |

**Two PROCESSES, not threads** - SQLAlchemy pools are per process, and two
threads on one engine would be one process's pool talking to itself.
`multiprocessing`'s `spawn` context is used explicitly, on every platform, so
the children inherit no engine, no connection and no lock from the parent.

**The race is made deterministic, not hoped for.** A start barrier releases
both children together, and a second barrier is taken INSIDE the transaction,
from a `before_cursor_execute` listener, at the exact statement each path
decides on - `UPDATE run_gates`, `UPDATE builder_documents`, `UPDATE runs`,
`INSERT INTO pending_feedback`. Both transactions are therefore open at the
decisive statement before either proceeds; PostgreSQL then blocks the second
on the first's row lock (or unique index), re-evaluates the WHERE after the
first commits, and the second reads `rowcount == 0` - or, for the insert, a
unique violation. Every assertion below is on that rowcount, observed from an
`after_cursor_execute` listener, plus the loser's typed refusal. Nothing in
production code changes for the test; the listeners are the test's.

Skipped unless `TEST_DATABASE_URL` is set. The server it names is left as it
was found: a throwaway database `two_writers_<hex>` is created on it for the
run and dropped afterwards, so nothing is written into the database the URL
names.

Local recipe (Docker):

    docker run --name pg18-test -e POSTGRES_PASSWORD=test -p 5433:5432 -d postgres:18
    $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres"
    .\\.venv\\Scripts\\python.exe -m unittest tests.pg.test_two_writers -v

In CI the `postgres` job in `.github/workflows/ci.yml` provides the service
and sets the same variable; it runs on `main` only (PLANS.md decision 25).

The status codes in the table are the HTTP mappings the SQLite suite already
pins - `test_app.py` for the duplicate gate reply, `test_gate_resume_race.py`
for the reopen, `test_builder_validate_and_history.py` for the document 409.
What this module owns is the layer underneath them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import multiprocessing
import os
from typing import Any
import unittest
import uuid

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

GATE = "scope-confirmation"
WRITERS = ("writer-a", "writer-b")
JOIN_TIMEOUT_SECONDS = 90
BARRIER_TIMEOUT_SECONDS = 60

#: The statement each path decides on, as SQLAlchemy compiles it. The child
#: pauses at the first statement with this prefix and records its rowcount.
DECISIVE_STATEMENT = {
    "pending_feedback": "insert into pending_feedback",
    "answer_gate": "update run_gates",
    "reopen_gate": "update run_gates",
    "orphan_sweep": "update runs",
    "document_save": "update builder_documents",
}


# --------------------------------------------------------------------------
# The child. Module-level and picklable by name, because `spawn` re-imports
# this module in the child and looks the target up there.
# --------------------------------------------------------------------------
def _install_observers(engine: Any, prefix: str, at_statement: Any) -> dict[str, Any]:
    """Pause at the decisive statement and record its rowcount, once each."""

    from sqlalchemy import event

    observed: dict[str, Any] = {"rowcount": None, "held": False}

    @event.listens_for(engine, "before_cursor_execute")
    def _hold(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if not observed["held"] and statement.lstrip().lower().startswith(prefix):
            observed["held"] = True
            at_statement.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    @event.listens_for(engine, "after_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if observed["rowcount"] is None and statement.lstrip().lower().startswith(prefix):
            observed["rowcount"] = cursor.rowcount

    return observed


def _pending_feedback(store: Any, subject: str, marker: str) -> dict[str, Any]:
    from crewai.flow.async_feedback.types import PendingFeedbackContext

    context = PendingFeedbackContext(
        flow_id=subject,
        flow_class="tests.pg.TwoWritersFlow",
        method_name="confirm_scope",
        method_output={"marker": marker},
        message="Confirm the scope",
        emit=None,
        default_outcome=None,
        metadata={"marker": marker},
        llm=None,
        requested_at=datetime.now(timezone.utc),
        execution_uuid=marker,
    )
    stored = store.save_pending_feedback(subject, context, {"id": subject, "marker": marker})
    return {"stored": bool(stored)}


def _answer_gate(store: Any, subject: str, marker: str) -> dict[str, Any]:
    result = store.answer_gate(subject, GATE, outcome=marker)
    response = result.gate.get("response") or {}
    return {
        "accepted": bool(result.accepted),
        "conflict": bool(result.conflict),
        "stored_outcome": response.get("outcome"),
    }


def _reopen_gate(store: Any, subject: str, marker: str) -> dict[str, Any]:
    gate = store.reopen_gate(subject, GATE)
    return {"status": gate["status"], "answered": gate["answered_at"] is not None}


def _orphan_sweep(store: Any, subject: str, marker: str) -> dict[str, Any]:
    """A registry over the store IS a restart: construction runs the sweep."""

    from brief_crew.service.graph import VALIDATOR_GRAPH, VALIDATOR_NODE_REGISTRY
    from brief_crew.service.registry import RunRegistry, WorkflowRuntime
    from brief_crew.service.runner import SyntheticValidatorRunner

    logging.getLogger("brief_crew.service.registry").setLevel(logging.CRITICAL)
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
        orphan_grace=0,
        recover_orphans=True,
    )
    try:
        status = registry.maintenance_status()
        # The subject's fate, not a global counter: `require` reads the row
        # this process holds in memory, and the loser dropped its copy, so a
        # rehydrated FAILED here is storage's answer rather than this
        # process's own write.
        return {
            "interrupted": int(status["interrupted_runs"]),
            "status_seen": registry.require(subject).status.value,
        }
    finally:
        registry.close()


def _document_save(store: Any, subject: str, marker: str) -> dict[str, Any]:
    from brief_crew.builder.store import BuilderDocumentStore, DocumentVersionConflict

    documents = BuilderDocumentStore(store)
    stored = documents.load(subject)
    try:
        saved = documents.save(
            stored.document.model_copy(update={"name": marker}), expected_version=1
        )
    except DocumentVersionConflict as exc:
        return {"saved": False, "conflict": str(exc)}
    return {"saved": True, "version": saved.head_version}


PATHS = {
    "pending_feedback": _pending_feedback,
    "answer_gate": _answer_gate,
    "reopen_gate": _reopen_gate,
    "orphan_sweep": _orphan_sweep,
    "document_save": _document_save,
}


def _writer(
    path: str,
    database_url: str,
    subject: str,
    marker: str,
    released: Any,
    at_statement: Any,
    results: Any,
) -> None:
    """One of the two writers. Reports a dict; never raises into the parent."""

    report: dict[str, Any] = {"marker": marker, "rowcount": None, "outcome": None, "error": None}
    try:
        from brief_crew.service.persistence import PostgresFlowPersistence

        store = PostgresFlowPersistence(database_url, initialize=False)
        try:
            observed = _install_observers(store.engine, DECISIVE_STATEMENT[path], at_statement)
            released.wait(timeout=BARRIER_TIMEOUT_SECONDS)
            report["outcome"] = PATHS[path](store, subject, marker)
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

    name = f"two_writers_{uuid.uuid4().hex[:12]}"
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
class TwoWritersOnPostgres(unittest.TestCase):
    """One throwaway database PER TEST, not per class.

    The orphan sweep lists every stale live row in the database, so with one
    shared database the gate-reply test's leftover `running` row was swept by
    the orphan test's two children as well - each child won a different row,
    both counted an interrupted run, and the assertion that exactly one of
    them had failed the subject failed on the leftover instead. A test that
    depends on what the previous test left behind is the shape CLAUDE.md's
    "tests that pass for the wrong reason" section exists for; a fresh
    database per test costs one `create_all` and removes the dependency.
    """

    def setUp(self) -> None:
        from brief_crew.service.persistence import PostgresFlowPersistence

        self.database_url, drop_database = _throwaway_database(TEST_DATABASE_URL)
        self.addCleanup(drop_database)
        PostgresFlowPersistence(self.database_url).close()  # create_all
        self.store = PostgresFlowPersistence(self.database_url, initialize=False)
        self.addCleanup(self.store.close)
        self.spawn = multiprocessing.get_context("spawn")

    # ------------------------------------------------------------ plumbing
    def race(self, path: str, subject: str) -> dict[str, dict[str, Any]]:
        """Two processes through one path, from two barriers. Reports by marker."""

        released = self.spawn.Barrier(2)
        at_statement = self.spawn.Barrier(2)
        results = self.spawn.Queue()
        children = [
            self.spawn.Process(
                target=_writer,
                args=(path, self.database_url, subject, marker, released, at_statement, results),
                name=f"{path}-{marker}",
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

    def assert_exactly_one_rowcount_of_one(self, reports: dict[str, dict[str, Any]]) -> str:
        """The D8 invariant. Returns the winner's marker."""

        winners = [m for m, r in reports.items() if r["rowcount"] == 1]
        self.assertEqual(len(winners), 1, {m: r["rowcount"] for m, r in reports.items()})
        return winners[0]

    def new_run(self, *, status: str = "queued", age: timedelta = timedelta(0)) -> str:
        from brief_crew.service.graph import VALIDATOR_GRAPH

        run_id = f"run-{uuid.uuid4().hex[:12]}"
        self.store.create_run(
            run_id=run_id,
            session_id="two-writers",
            workflow_id=VALIDATOR_GRAPH.id,
            graph_version=VALIDATOR_GRAPH.version,
            inputs={"idea": "two writers, one row"},
            flow_id=run_id,
            status=status,
            created_at=datetime.now(timezone.utc) - age,
        )
        return run_id

    def open_gate(self, run_id: str) -> None:
        self.store.open_gate(
            run_id, GATE, node_id="confirm_scope", request={"title": "Confirm the scope"}
        )

    # -------------------------------------------------------------- paths
    def test_pending_feedback_one_insert_the_other_handled_as_already_pending(self) -> None:
        from sqlalchemy import func, select

        from brief_crew.service.persistence import flow_states

        flow_uuid = f"flow-{uuid.uuid4().hex[:12]}"
        reports = self.race("pending_feedback", flow_uuid)

        winner = self.assert_exactly_one_rowcount_of_one(reports)
        loser = next(m for m in WRITERS if m != winner)
        # The loser's INSERT raised, so it observed no rowcount at all, and
        # its integrity error came back as "already pending" - False - rather
        # than propagating.
        self.assertIsNone(reports[loser]["rowcount"])
        self.assertEqual(reports[winner]["outcome"], {"stored": True})
        self.assertEqual(reports[loser]["outcome"], {"stored": False})
        # The winner's context is the one anchor a resume may read.
        loaded = self.store.load_pending_feedback(flow_uuid)
        self.assertIsNotNone(loaded)
        state, context = loaded
        self.assertEqual(context.execution_uuid, winner)
        self.assertEqual(state["marker"], winner)
        # Nothing half-written remains: the loser's flow_states row rolled back.
        with self.store.connect() as connection:
            rows = connection.execute(
                select(func.count()).select_from(flow_states).where(flow_states.c.flow_uuid == flow_uuid)
            ).scalar_one()
        self.assertEqual(int(rows), 1)

    def test_gate_reply_one_cas_the_other_a_conflict(self) -> None:
        run_id = self.new_run()
        self.open_gate(run_id)
        reports = self.race("answer_gate", run_id)

        winner = self.assert_exactly_one_rowcount_of_one(reports)
        loser = next(m for m in WRITERS if m != winner)
        self.assertEqual(reports[loser]["rowcount"], 0)
        self.assertEqual(reports[winner]["outcome"]["accepted"], True)
        self.assertEqual(reports[loser]["outcome"], {
            "accepted": False,
            "conflict": True,
            "stored_outcome": winner,
        })
        gate = self.store.get_gate(run_id, GATE)
        self.assertEqual(gate["response"]["outcome"], winner)
        self.assertEqual(self.store.get_run(run_id)["status"], "running")

    def test_reopen_gate_one_cas_the_other_a_no_op(self) -> None:
        run_id = self.new_run()
        self.open_gate(run_id)
        self.assertTrue(self.store.answer_gate(run_id, GATE, outcome="first").accepted)
        reports = self.race("reopen_gate", run_id)

        winner = self.assert_exactly_one_rowcount_of_one(reports)
        loser = next(m for m in WRITERS if m != winner)
        self.assertEqual(reports[loser]["rowcount"], 0)
        # Both hand back an open gate; only one of them opened it.
        for marker in WRITERS:
            self.assertEqual(reports[marker]["outcome"], {"status": "open", "answered": False})
        self.assertEqual(self.store.get_run(run_id)["status"], "waiting")
        self.assertIsNotNone(self.store.get_pending_gate(run_id))

    def test_orphan_sweep_one_claim_the_other_finds_the_row_already_terminal(self) -> None:
        run_id = self.new_run(status="running", age=timedelta(hours=1))
        reports = self.race("orphan_sweep", run_id)

        winner = self.assert_exactly_one_rowcount_of_one(reports)
        loser = next(m for m in WRITERS if m != winner)
        self.assertEqual(reports[loser]["rowcount"], 0)
        self.assertEqual(reports[winner]["outcome"], {"interrupted": 1, "status_seen": "failed"})
        self.assertEqual(reports[loser]["outcome"], {"interrupted": 0, "status_seen": "failed"})
        row = self.store.get_run(run_id)
        self.assertEqual(row["status"], "failed")
        self.assertIsNotNone(row["completed_at"])
        # Exactly one process wrote the failure frame.
        messages = [
            frame["message"]
            for frame in self.store.replay_frames(run_id)
            if frame["kind"] == "error"
        ]
        self.assertEqual(messages, ["Run interrupted by a service restart"])

    def test_document_save_one_cas_the_other_a_version_conflict(self) -> None:
        from brief_crew.builder.store import BuilderDocumentStore, new_document_id
        from tests.builder.test_compiler import straight_line

        documents = BuilderDocumentStore(self.store)
        document_id = new_document_id()
        documents.create(straight_line().model_copy(update={"id": document_id}))
        reports = self.race("document_save", document_id)

        winner = self.assert_exactly_one_rowcount_of_one(reports)
        loser = next(m for m in WRITERS if m != winner)
        self.assertEqual(reports[loser]["rowcount"], 0)
        self.assertEqual(reports[winner]["outcome"], {"saved": True, "version": 2})
        self.assertFalse(reports[loser]["outcome"]["saved"])
        self.assertIn("is at version 2, not 1", reports[loser]["outcome"]["conflict"])
        head = documents.load(document_id)
        self.assertEqual(head.head_version, 2)
        self.assertEqual(head.document.name, winner)
        self.assertEqual(documents.versions(document_id), [2, 1])


if __name__ == "__main__":
    unittest.main()
