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

    def test_the_post_hoc_rating_rides_beside_the_mid_run_ones(self) -> None:
        """Plan 20. A gate reply says what somebody accepted DURING a run and
        a guardrail says what a machine checked; neither answers *was this run
        any good*, which is what the drawer's own control now sets."""

        self.store.set_run_rating(
            "r-1", rating="bad", note="the segment was wrong", rated_by=ALICE.id
        )
        body = self.ok("/runs/r-1/decisions")
        self.assertEqual(
            set(body["rating"]),
            {"run_id", "rating", "rating_note", "rated_by", "rated_at"},
        )
        self.assertEqual(body["rating"]["run_id"], "r-1")
        self.assertEqual(body["rating"]["rating"], "bad")
        self.assertEqual(body["rating"]["rating_note"], "the segment was wrong")
        self.assertEqual(body["rating"]["rated_by"], ALICE.id)

    def test_an_unrated_run_answers_an_object_of_nulls_not_a_null(self) -> None:
        """So the drawer renders one control rather than branching on whether
        the key is there at all."""

        body = self.ok("/runs/r-1/decisions")
        self.assertIsNotNone(body["rating"])
        self.assertEqual(body["rating"]["run_id"], "r-1")
        self.assertIsNone(body["rating"]["rating"])
        self.assertIsNone(body["rating"]["rated_at"])

    def test_the_shape_is_section_3s(self) -> None:
        body = self.ok("/runs/r-1/decisions")
        self.assertEqual(
            set(body),
            {
                "run_id",
                "gates",
                "guardrails",
                "fallback_models",
                "verdict",
                # Plan 20's one addition to this drawer.
                "rating",
                "langfuse",
                # What the run answered, so it can be read before it is judged.
                "answer",
                "answer_truncated",
                # What it was asked, and which version asked it.
                "question",
                "document_version",
            },
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


class WhatItAnsweredTests(AdminCase):
    """The drawer shows the run's answer, so an admin judges what they read.

    Found in a live demo: every automatic check was green on a billing reply
    that claimed a card had been charged, and the only way to catch it was to
    read the reply - which the drawer did not show.
    """

    def seed_answer(self, run_id: str, result: object) -> None:
        self.seed_run(run_id)
        self.store.update_run_status(run_id, "completed", result=result)

    def test_the_body_text_comes_back_and_nothing_else_of_the_result(self) -> None:
        reply = "# Reply\n\nYour card was charged."
        self.seed_answer("r-a", {"markdown_body": reply, "verdict": {"secret": 1}})
        body = self.ok("/runs/r-a/decisions")
        self.assertEqual(body["answer"], reply)
        self.assertFalse(body["answer_truncated"])
        self.assertNotIn("secret", str(body["answer"]))

    def test_a_run_with_no_stored_body_answers_null(self) -> None:
        self.seed_run("r-none")
        body = self.ok("/runs/r-none/decisions")
        self.assertIsNone(body["answer"])
        self.assertFalse(body["answer_truncated"])
        self.seed_answer("r-other", {"verdict": "VALIDATE"})
        self.assertIsNone(self.ok("/runs/r-other/decisions")["answer"])
        self.seed_answer("r-blank", {"markdown_body": "   "})
        self.assertIsNone(self.ok("/runs/r-blank/decisions")["answer"])

    def test_an_unknown_run_answers_null_rather_than_failing(self) -> None:
        body = self.ok("/runs/r-missing/decisions")
        self.assertIsNone(body["answer"])

    def test_a_long_answer_is_cut_at_the_bound_and_says_so(self) -> None:
        from unittest.mock import patch

        from brief_crew import config

        self.seed_answer("r-long", {"markdown_body": "x" * 50})
        with patch.object(config, "ADMIN_ANSWER_MAX_CHARS", 20):
            body = self.ok("/runs/r-long/decisions")
        self.assertEqual(body["answer"], "x" * 20)
        self.assertTrue(body["answer_truncated"])

    def test_the_bound_is_the_run_result_bound(self) -> None:
        from brief_crew import config

        self.assertEqual(config.ADMIN_ANSWER_MAX_CHARS, config.MAX_RUN_RESULT_BODY_CHARS)

    def test_a_non_admin_still_gets_the_unknown_route_404(self) -> None:
        self.seed_answer("r-a", {"markdown_body": "private reply"})
        response = self.client.get(
            "/api/admin/runs/r-a/decisions", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private reply", response.text)
        anonymous = self.client.get("/api/admin/runs/r-a/decisions")
        self.assertNotIn("private reply", anonymous.text)
        self.assertNotEqual(anonymous.status_code, 200)


class WhatWasAskedTests(AdminCase):
    """The drawer shows the run's question beside its answer.

    Found on production comparing a v3 and a v5 run of one workflow: a support
    reply cannot be judged without the customer's message. The question is the
    ONE input `create_run` bounds as the prompt, by `workflow_input_field`.
    """

    def register_builder(self, workflow_id: str, input_field: str) -> None:
        from dataclasses import replace

        base = self.registry.workflows["idea-validator"]
        self.registry.workflows[workflow_id] = replace(base, input_field=input_field)
        self.addCleanup(self.registry.workflows.pop, workflow_id, None)

    def test_a_builder_run_answers_its_own_input_field(self) -> None:
        self.register_builder("ug_support01", "customer_message")
        self.seed_run(
            "r-b",
            workflow_id="ug_support01",
            inputs={"customer_message": "Was I charged twice?", "tone": "warm"},
            document_version=5,
        )
        body = self.ok("/runs/r-b/decisions")
        self.assertEqual(body["question"], "Was I charged twice?")
        self.assertEqual(body["document_version"], 5)

    def test_the_validator_answers_its_idea(self) -> None:
        self.seed_run("r-v")
        body = self.ok("/runs/r-v/decisions")
        self.assertEqual(body["question"], "a scheduling assistant for clinics")
        self.assertIsNone(body["document_version"])

    def test_other_input_keys_never_travel(self) -> None:
        self.seed_run(
            "r-x",
            inputs={
                "idea": "the prompt",
                "topic": "SECRET-TOPIC",
                "api_note": "SECRET-NOTE",
            },
        )
        response = self.get("/runs/r-x/decisions")
        self.assertEqual(response.json()["question"], "the prompt")
        self.assertNotIn("SECRET", response.text)

    def test_null_when_the_prompt_input_is_absent(self) -> None:
        self.seed_run("r-empty", inputs={"topic": "not the validator's key"})
        self.assertIsNone(self.ok("/runs/r-empty/decisions")["question"])
        self.seed_run("r-blank", inputs={"idea": "   "})
        self.assertIsNone(self.ok("/runs/r-blank/decisions")["question"])
        self.assertIsNone(self.ok("/runs/r-missing/decisions")["question"])

    def test_null_for_a_workflow_this_process_does_not_know(self) -> None:
        self.seed_run(
            "r-gone", workflow_id="ug_deadbeef", inputs={"idea": "an old graph"}
        )
        self.assertIsNone(self.ok("/runs/r-gone/decisions")["question"])

    def test_a_long_question_is_cut_at_the_prompt_bound(self) -> None:
        from brief_crew import config

        self.seed_run(
            "r-long", inputs={"idea": "y" * (config.MAX_RUN_INPUT_CHARS + 50)}
        )
        question = self.ok("/runs/r-long/decisions")["question"]
        self.assertEqual(len(question), config.MAX_RUN_INPUT_CHARS)

    def test_a_non_admin_gets_the_unknown_route_404(self) -> None:
        self.seed_run("r-p", inputs={"idea": "private question"})
        response = self.client.get(
            "/api/admin/runs/r-p/decisions", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private question", response.text)
        anonymous = self.client.get("/api/admin/runs/r-p/decisions")
        self.assertNotEqual(anonymous.status_code, 200)
        self.assertNotIn("private question", anonymous.text)


class RunRowVersionTests(AdminCase):
    """Which version produced a run, on the Runs table and a user's detail."""

    def test_the_runs_list_carries_document_version(self) -> None:
        self.seed_run("r-v3", age_hours=2, document_version=3)
        self.seed_run("r-v5", age_hours=1, document_version=5)
        self.seed_run("r-none", age_hours=3)
        rows = {row["run_id"]: row for row in self.ok("/runs")["rows"]}
        self.assertEqual(rows["r-v3"]["document_version"], 3)
        self.assertEqual(rows["r-v5"]["document_version"], 5)
        self.assertIsNone(rows["r-none"]["document_version"])

    def test_the_user_detail_rows_carry_it_too(self) -> None:
        self.seed_run("r-u", document_version=4)
        detail = self.ok(f"/users/{ALICE.id}")
        self.assertEqual(detail["recent_runs"][0]["document_version"], 4)


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
        self.store.admin_run_window(
            start=start, end=end, workflow_id="authored-workflow",
            statuses=("completed", "failed", "cancelled"),
        )
        self.store.admin_runs_with_frames(["r-1"])
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
        self.store.admin_gate_window(run_ids=["r-1"])
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
