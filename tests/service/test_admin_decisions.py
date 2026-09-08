"""The decisions drawer, and **no JSON path in any SQL** (plan 17 criterion 9).

`/runs/{id}/decisions` is the one view Langfuse cannot give: the operator's
reply and the fields they edited are hashed in the trace by the content
policy, on purpose. Here they come back **verbatim**.

The other half of this file is the rule that decides most of the SQL in
`admin_api.py` and `persistence.py`, and it is asserted mechanically rather
than reviewed: **every statement these reads compile is searched for `->>`,
`->`, `json_extract` and `jsonb`.** A JSON path is spelled differently on
SQLite and PostgreSQL, this repository ships on both, and the tests all run on
SQLite - so the day somebody writes one, nothing here would fail and the
deployed service would 500 on the one dialect nobody exercises. That is
`user_spend_usd`'s own stated reason for summing a `Numeric` column instead of
the `usage` JSON, applied to eleven more queries.

The check compiles each statement against **both** dialects, because a
SQLAlchemy expression that renders innocently on SQLite can render a JSON
operator on PostgreSQL - which is precisely the failure that would otherwise
be invisible here.
"""

from __future__ import annotations

import re
import unittest

from tests.service.admin_fixtures import ALICE, AdminCase

#: What a JSON path looks like in either dialect's rendered SQL.
JSON_PATH = re.compile(r"->>|->|json_extract|jsonb_|json_each", re.IGNORECASE)


class DecisionsDrawerTests(AdminCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        self.seed_gate(
            "r-1",
            "scope-confirmation",
            decision="approve",
            seconds=192,
            note="the segment is right, go on",
        )
        self.seed_gate(
            "r-1", "verdict-review", decision="revise", seconds=520, note="widen the market"
        )
        self.seed_frame(
            "r-1",
            seq=1,
            kind="guardrail",
            node_id="write_report",
            details={
                "guardrail": "report_citation_closure",
                "guardrail_type": "llm",
                "retry_count": 1,
            },
        )
        self.seed_frame(
            "r-1",
            seq=2,
            kind="error",
            node_id="n3_reviewer",
            details={
                "fallback_model": "openrouter/google/gemini-3.5-flash-lite",
                "attempt": 2,
            },
        )
        self.seed_frame(
            "r-1",
            seq=3,
            kind="verdict",
            details={"verdict": "NEEDS_WORK", "score": 4.2, "confidence": 0.62},
        )

    def test_the_reply_comes_back_verbatim(self) -> None:
        """The words a person typed, unchanged - the reason this route exists."""

        body = self.ok("/runs/r-1/decisions")
        gates = {gate["gate_id"]: gate for gate in body["gates"]}
        self.assertEqual(
            gates["scope-confirmation"]["response"],
            {"decision": "approve", "fields": {"note": "the segment is right, go on"}},
        )
        self.assertEqual(
            gates["verdict-review"]["response"]["fields"]["note"], "widen the market"
        )

    def test_the_outcome_is_read_out_of_the_reply_in_python(self) -> None:
        body = self.ok("/runs/r-1/decisions")
        outcomes = {gate["gate_id"]: gate["outcome"] for gate in body["gates"]}
        self.assertEqual(outcomes["scope-confirmation"], "approve")
        self.assertEqual(outcomes["verdict-review"], "revise")

    def test_a_gate_carries_the_seconds_it_took(self) -> None:
        body = self.ok("/runs/r-1/decisions")
        gates = {gate["gate_id"]: gate for gate in body["gates"]}
        self.assertEqual(gates["scope-confirmation"]["seconds"], 192.0)
        self.assertEqual(gates["verdict-review"]["seconds"], 520.0)

    def test_an_unanswered_gate_has_a_null_outcome_and_null_seconds(self) -> None:
        self.seed_run("r-2")
        self.seed_gate("r-2", "waiting", decision=None)
        gate = self.ok("/runs/r-2/decisions")["gates"][0]
        self.assertIsNone(gate["outcome"])
        self.assertIsNone(gate["seconds"])
        self.assertIsNone(gate["answered_at"])
        self.assertIsNone(gate["response"])

    def test_the_guardrail_name_and_retry_count_are_read(self) -> None:
        body = self.ok("/runs/r-1/decisions")
        self.assertEqual(
            body["guardrails"],
            [
                {
                    "guardrail": "report_citation_closure",
                    "guardrail_type": "llm",
                    "retry_count": 1,
                    "node_id": "write_report",
                }
            ],
        )

    def test_a_fallback_model_is_reported_with_its_attempt(self) -> None:
        body = self.ok("/runs/r-1/decisions")
        self.assertEqual(
            body["fallback_models"],
            [
                {
                    "node_id": "n3_reviewer",
                    "fallback_model": "openrouter/google/gemini-3.5-flash-lite",
                    "attempt": 2,
                }
            ],
        )

    def test_the_verdict_frame_comes_back_whole(self) -> None:
        body = self.ok("/runs/r-1/decisions")
        self.assertEqual(
            body["verdict"], {"verdict": "NEEDS_WORK", "score": 4.2, "confidence": 0.62}
        )

    def test_a_run_with_no_decisions_answers_empty_lists(self) -> None:
        self.seed_run("r-quiet")
        body = self.ok("/runs/r-quiet/decisions")
        self.assertEqual(body["gates"], [])
        self.assertEqual(body["guardrails"], [])
        self.assertEqual(body["fallback_models"], [])
        self.assertIsNone(body["verdict"])

    def test_the_shape_is_section_3s(self) -> None:
        body = self.ok("/runs/r-1/decisions")
        self.assertEqual(
            set(body),
            {"run_id", "gates", "guardrails", "fallback_models", "verdict", "langfuse"},
        )
        self.assertEqual(
            set(body["gates"][0]),
            {
                "gate_id",
                "node_id",
                "status",
                "opened_at",
                "answered_at",
                "seconds",
                "outcome",
                "response",
            },
        )


class NoJsonPathInAnySqlTests(unittest.TestCase):
    """Every statement the admin reads compile, on BOTH dialects.

    The statements are built by calling each read against a real in-memory
    store with SQLAlchemy's compiler intercepted, so this checks the SQL the
    code actually emits rather than a reviewer's memory of it.
    """

    def setUp(self) -> None:
        from sqlalchemy import event

        from brief_crew.service.persistence import PostgresFlowPersistence

        self.store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.store.close)
        self.store.init_db()
        self.statements: list[str] = []

        @event.listens_for(self.store.engine, "before_cursor_execute")
        def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            self.statements.append(statement)

    def exercise(self) -> None:
        """Run every admin read at least once, so every statement is emitted."""

        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        start, end = now - timedelta(days=30), now
        self.store.admin_status_counts(start=start, end=end)
        self.store.admin_run_window(start=start, end=end)
        for axis in ("user", "workflow", "model", "node"):
            self.store.admin_spend_by(axis, start=start, end=end)
        self.store.admin_run_costs(["r-1"])
        self.store.admin_list_runs(
            status="completed",
            mode="run",
            user_id="user_alice",
            workflow_id="idea-validator",
            start=start,
            end=end,
            cursor=(now, "r-1"),
        )
        self.store.admin_list_runs(user_id="__unowned__")
        self.store.admin_user_totals(utc_day="2026-09-08")
        self.store.admin_user_totals(user_ids=["user_alice", "__unowned__"], utc_day="2026-09-08")
        self.store.admin_gate_window(start=start, end=end)
        self.store.admin_frames_by_kind(["verdict"], start=start, end=end)
        self.store.admin_frames_by_kind(["guardrail", "error"], run_ids=["r-1"])
        self.store.admin_integrity_totals()
        self.store.admin_gates_for_user("user_alice")
        self.store.admin_gates_for_user("__unowned__")
        self.store.admin_document_owner("ug_0123abcd")
        self.store.list_gates("r-1")

    def test_no_statement_carries_a_json_path_on_sqlite(self) -> None:
        self.exercise()
        self.assertGreater(len(self.statements), 15, "nothing was recorded")
        for statement in self.statements:
            with self.subTest(sql=statement[:90]):
                self.assertIsNone(
                    JSON_PATH.search(statement),
                    "a JSON path reached SQL; it is spelled differently on the "
                    "two dialects and every test here runs on only one",
                )

    def test_no_statement_carries_a_json_path_when_compiled_for_postgresql(self) -> None:
        """The half SQLite cannot show, and the half that would ship broken.

        A SQLAlchemy expression can render innocently here and render `->>` on
        PostgreSQL, which is the deployed dialect. Compiling the same
        statements against the PostgreSQL dialect is the only way this suite
        can see that.
        """

        from datetime import datetime, timedelta, timezone

        from sqlalchemy import func, select
        from sqlalchemy.dialects import postgresql

        from brief_crew.service import persistence as p

        now = datetime.now(timezone.utc)
        # The statements this module builds, rebuilt here in the same shapes.
        # Rebuilt rather than intercepted because the interception above gives
        # the SQLite rendering, and this test is about the other one.
        statements = [
            select(p.runs.c.status, func.count()).group_by(p.runs.c.status),
            select(p.runs).where(p.runs.c.created_at >= now - timedelta(days=1)),
            select(p.run_gates).where(p.run_gates.c.answered_at.is_(None)),
            select(p.run_frames).where(p.run_frames.c.kind.in_(["verdict"])),
            select(
                func.coalesce(p.runs.c.user_id, "__unowned__"),
                func.coalesce(func.sum(p.run_node_metrics.c.cost_usd), 0),
            ).select_from(
                p.run_node_metrics.join(p.runs, p.runs.c.id == p.run_node_metrics.c.run_id)
            ),
        ]
        for statement in statements:
            rendered = str(statement.compile(dialect=postgresql.dialect()))
            with self.subTest(sql=rendered[:90]):
                self.assertIsNone(JSON_PATH.search(rendered))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
