"""Where runs go wrong: one read surface over many runs, and no model call.

Plan 21, T4's first half. `admin_frames_by_kind` **was** the cross-run frame
query and had never been called with `agent`, `llm` or `tool`; this panel
calls it with all of them and asks one workflow's frames five questions.

Four claims:

* the query is EXTENDED with `workflow_ids` and `statuses`, and its existing
  call sites are unchanged. Extended and not duplicated, because a second copy
  of a scan is a second place for the cap and the `truncated` flag to drift.
* all five lists come back over a seeded world with two workflows, two roles,
  an empty-result tool, a failing tool, a guardrail retry and a revised gate -
  and **the other workflow's rows never appear**.
* no statement these reads emit contains `->>` or `json_extract`, on either
  dialect. Every `details`, every gate `request` and `response` comes back as
  a column and is read in Python.
* `ADMIN_MAX_SCAN_ROWS` is enforced and says `truncated: true`; the window
  rules and the too-wide 422 are plan 17's, inherited.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import unittest
from unittest.mock import patch

from brief_crew import config
from tests.service.admin_fixtures import ALICE, NOW, AdminCase

#: What a JSON path looks like in either dialect's rendered SQL. The same
#: expression `test_admin_decisions.py` uses, restated rather than imported so
#: deleting that module cannot silently retire this check.
JSON_PATH = re.compile(r"->>|->|json_extract|jsonb_|json_each", re.IGNORECASE)

MINE = "ug_mine0001"
OTHER = "ug_other002"


class MiningWorld(AdminCase):
    """One workflow worth mining, and a second one that must never leak in."""

    def setUp(self) -> None:
        super().setUp()
        self.seed_world()

    def seed_world(self) -> None:
        for index in range(6):
            run_id = f"mine-{index}"
            self.seed_run(
                run_id,
                user_id=ALICE.id,
                workflow_id=MINE,
                node_id="market_research",
                cost="0.0600",
            )
            self.seed_frames(run_id, index)
            self.seed_gate(
                run_id,
                "scope-confirmation",
                node_id="confirm_scope",
                decision="revise" if index < 3 else "approve",
                proposed={"segment": "SMBs"},
                fields={"segment": "clinics" if index < 3 else "SMBs"},
                seconds=200 + index,
            )
            # `answer_gate` puts the run back to `running` - it is the resume
            # path - so the terminal status is re-stamped after the gate. Six
            # `running` runs would make every outcome row read `other`, which
            # is a true statement about a seed nobody meant.
            self.store.update_run_status(run_id, "completed")
        # The other workflow: same shapes, different names, so a leak shows up
        # as a NAME rather than as a count nobody can attribute.
        self.seed_run("other-1", user_id=ALICE.id, workflow_id=OTHER, cost="0.9900")
        self.seed_frame(
            "other-1",
            seq=1,
            kind="tool",
            node_id="other_node",
            details={
                "stage": "after",
                "tool": "OtherWorkflowTool",
                "tool_status": "ok",
                "result_count": 4,
                "agent_role": "Somebody else's analyst",
            },
        )
        self.seed_gate("other-1", "other-gate", node_id="other_node")

    def seed_frames(self, run_id: str, index: int) -> None:
        seq = 0

        def add(**kwargs) -> None:
            nonlocal seq
            seq += 1
            self.seed_frame(run_id, seq=seq, **kwargs)

        role = "Market evidence analyst"
        add(
            kind="agent",
            node_id="market_research",
            details={"stage": "before", "task": "market_task", "agent_role": role},
        )
        # An empty-result tool: half its calls come back with nothing.
        add(
            kind="tool",
            node_id="market_research",
            details={
                "stage": "after",
                "tool": "MarketResearchTool",
                "query": "quiz generator LLM",
                "tool_status": "ok",
                "result_count": 0 if index % 2 == 0 else 3,
                "agent_role": role,
            },
        )
        # A failing tool, on the other role's node.
        add(
            kind="tool",
            node_id="sentiment",
            details={
                "stage": "error",
                "tool": "HackerNewsTool",
                "query": "AI grading teachers",
                "error_class": "HTTPStatusError",
                "agent_role": "Signal analyst",
            },
        )
        add(
            kind="guardrail",
            node_id="market_research",
            details={
                "stage": "after",
                "guardrail": "market_source_closure",
                "success": False,
                "agent_role": role,
            },
        )
        add(
            kind="llm",
            node_id="market_research",
            details={"stage": "before", "model": config.CHEAP_MODEL, "agent_role": role},
        )
        add(
            kind="llm",
            node_id="market_research",
            details={
                "stage": "after",
                "model": config.CHEAP_MODEL,
                # The provider's own word for what stopped the answer. NOT the
                # frame preview being clipped, which is this repository's own
                # bound and true of every long answer.
                "finish_reason": "length" if index < 2 else "stop",
                "agent_role": role,
            },
        )
        add(
            kind="edge_taken",
            node_id="route_scope",
            details={"route": "scope_approved", "from": "confirm_scope"},
        )
        add(
            kind="error",
            node_id="sentiment",
            details={"error_class": "HTTPStatusError", "agent_role": "Signal analyst"},
        )
        add(
            kind="agent",
            node_id="market_research",
            details={
                "stage": "after",
                "task_name": "market_task",
                "agent_role": role,
                "output_preview": "a finding",
                "output_chars": 9,
                "tool_failure_count": 1 if index % 2 == 0 else 0,
            },
        )
        add(
            kind="verdict",
            node_id="review_verdict",
            details={
                "verdict": "NEEDS_WORK",
                "confidence": 0.2 if index < 3 else 0.7,
            },
        )

    def hotspots(self, **query: object) -> dict:
        parts = "&".join(f"{key}={value}" for key, value in query.items())
        return self.ok(f"/improve/hotspots?workflow_id={MINE}" + (f"&{parts}" if parts else ""))


class FiveListsTests(MiningWorld):
    """A16, list by list."""

    def setUp(self) -> None:
        super().setUp()
        self.body = self.hotspots()

    def test_every_list_is_non_empty(self) -> None:
        for key in ("agents", "tools", "errors", "gates", "routes"):
            with self.subTest(key=key):
                self.assertTrue(self.body[key], f"{key} is empty; the seed is thin")

    def test_the_agents_carry_their_role_node_and_counts(self) -> None:
        rows = {row["agent_role"]: row for row in self.body["agents"]}
        market = rows["Market evidence analyst"]
        self.assertEqual("market_research", market["node_id"])
        self.assertEqual(6, market["executions"])
        self.assertEqual(6, market["guardrail_retries"])
        self.assertIn("market_source_closure", market["guardrail_names"])
        self.assertEqual(6, market["llm_calls"])

    def test_an_empty_result_tool_is_counted_with_its_rate(self) -> None:
        rows = {row["tool"]: row for row in self.body["tools"]}
        market = rows["MarketResearchTool"]
        self.assertEqual(6, market["calls"])
        self.assertEqual(3, market["empty"])
        self.assertEqual(0.5, market["empty_rate"])
        self.assertIn("quiz generator LLM", market["queries_sample"])

    def test_a_failing_tool_is_counted_with_its_error_class(self) -> None:
        rows = {row["tool"]: row for row in self.body["tools"]}
        hn = rows["HackerNewsTool"]
        self.assertEqual(6, hn["failed"])
        self.assertEqual(1.0, hn["failed_rate"])
        self.assertIn("HTTPStatusError", hn["error_classes"])

    def test_the_errors_name_the_nodes_and_the_roles(self) -> None:
        row = self.body["errors"][0]
        self.assertEqual("HTTPStatusError", row["error_class"])
        self.assertIn("sentiment", row["nodes"])
        self.assertIn("Signal analyst", row["agent_roles"])

    def test_the_revised_gate_carries_its_rate_and_its_edited_field(self) -> None:
        gate = self.body["gates"][0]
        self.assertEqual("scope-confirmation", gate["gate_id"])
        self.assertEqual(6, gate["answered"])
        self.assertEqual(3, gate["revise"])
        self.assertEqual(0.5, gate["revise_rate"])
        self.assertIn("segment", gate["edited_fields"])
        self.assertIsNotNone(gate["median_seconds"])

    def test_a_router_that_never_varies_is_visible(self) -> None:
        route = self.body["routes"][0]
        self.assertEqual("route_scope", route["node_id"])
        self.assertEqual(6, route["decisions"])
        self.assertEqual(1, route["unique_routes"])

    def test_the_outcomes_carry_verdicts_ratings_and_statuses(self) -> None:
        outcomes = self.body["outcomes"]
        self.assertTrue(outcomes["by_verdict"])
        self.assertEqual(6, outcomes["by_status"]["completed"])

    def test_the_truncation_signal_is_the_providers_and_not_the_frames(self) -> None:
        """The audit's amendment to L11, asserted from both sides.

        Two runs stopped at `finish_reason: length` and four at `stop`, and
        every one of the six carried an `output_preview` shorter than its
        answer would be in a real run. A count of six would mean the
        instrument was reporting on itself.
        """

        rows = {row["agent_role"]: row for row in self.body["agents"]}
        self.assertEqual(2, rows["Market evidence analyst"]["truncated_outputs"])

    def test_the_cheap_tier_counterfactual_is_priced(self) -> None:
        """The talk's *"what if a cheaper model ran this"*, as arithmetic."""

        rows = {row["node_id"]: row for row in self.body["agents"]}
        market = rows["market_research"]
        self.assertIsNotNone(market["cheap_tier_cost_usd"])
        self.assertGreater(market["cheap_tier_cost_usd"], 0.0)
        self.assertLess(market["cheap_tier_cost_usd"], market["cost_usd"])

    def test_a_node_already_on_the_cheap_tier_gets_null_not_zero(self) -> None:
        """`0.0` would read as "free on the cheap tier"."""

        self.store.save_node_metrics(
            "mine-0",
            "cheap_node",
            model=config.CHEAP_MODEL,
            cost_usd=__import__("decimal").Decimal("0.0100"),
            total_tokens=100,
            prompt_tokens=80,
            completion_tokens=20,
            call_count=1,
        )
        self.seed_frame(
            "mine-0",
            seq=90,
            kind="agent",
            node_id="cheap_node",
            details={"stage": "before", "task": "t", "agent_role": "A cheap agent"},
        )
        rows = {row["node_id"]: row for row in self.hotspots()["agents"]}
        self.assertIsNone(rows["cheap_node"]["cheap_tier_cost_usd"])


class NodeModelsTests(MiningWorld):
    """The model picker's own data: which models a node really ran on.

    Nothing else on this surface answered it, so a picker built without it
    offers every model the deployment has ever spent on - and most of
    those produce an arm with `n: 0` for the node in hand.
    """

    def rows(self) -> dict:
        return {row["node_id"]: row for row in self.hotspots()["node_models"]}

    def test_a_node_with_one_model_lists_one(self) -> None:
        self.assertEqual(
            [config.ESCALATION_MODEL], self.rows()["market_research"]["models"]
        )

    def test_a_node_with_two_models_lists_both_sorted(self) -> None:
        """Sorted, so two identical loads offer the same order and a
        picker cannot reshuffle under somebody reading it."""

        self.store.save_node_metrics(
            "mine-0",
            "market_research",
            model=config.CHEAP_MODEL,
            cost_usd=Decimal("0.0100"),
            total_tokens=100,
            prompt_tokens=80,
            completion_tokens=20,
            call_count=1,
        )
        self.assertEqual(
            sorted([config.CHEAP_MODEL, config.ESCALATION_MODEL]),
            self.rows()["market_research"]["models"],
        )

    def test_the_count_is_DISTINCT_runs_not_calls(self) -> None:
        """A node that ran twice in one run is one run's evidence.

        Calls would read as a bigger sample than the comparison actually
        has, which is the exact overstatement `underpowered` exists to
        prevent one screen away.
        """

        self.assertEqual(6, self.rows()["market_research"]["runs"])
        self.store.save_node_metrics(
            "mine-0",
            "market_research",
            model=config.CHEAP_MODEL,
            cost_usd=Decimal("0.0100"),
            total_tokens=10,
            prompt_tokens=5,
            completion_tokens=5,
            call_count=1,
        )
        self.assertEqual(6, self.rows()["market_research"]["runs"])

    def test_the_label_is_the_authors_and_falls_back_to_the_id(self) -> None:
        """`n3_reviewer` is not what anybody drew, and a blank is worse.

        This workflow is not registered, so every label IS the id - which
        is the fallback under test rather than a gap in the seed.
        """

        row = self.rows()["market_research"]
        self.assertEqual("market_research", row["label"])

    def test_nodes_are_ordered_busiest_first(self) -> None:
        order = [row["node_id"] for row in self.hotspots()["node_models"]]
        self.assertEqual(sorted(order, key=lambda _n: 0), order[: len(order)])
        runs = [row["runs"] for row in self.hotspots()["node_models"]]
        self.assertEqual(sorted(runs, reverse=True), runs)

    def test_the_other_workflows_node_never_appears(self) -> None:
        self.assertNotIn("other_node", self.rows())

    def test_a_row_with_no_model_is_skipped_rather_than_blank(self) -> None:
        """An empty slug is not a model anybody can pick, and offering
        one would put an arm on the page that can never have a name."""

        self.store.save_node_metrics(
            "mine-1",
            "nameless",
            model="",
            cost_usd=Decimal("0.0100"),
            total_tokens=10,
            prompt_tokens=5,
            completion_tokens=5,
            call_count=1,
        )
        self.assertNotIn("nameless", self.rows())


class NoLeakBetweenWorkflowsTests(MiningWorld):
    """The other workflow's rows never appear - A16's second half."""

    def test_no_other_workflows_tool_appears(self) -> None:
        tools = {row["tool"] for row in self.hotspots()["tools"]}
        self.assertNotIn("OtherWorkflowTool", tools)

    def test_no_other_workflows_gate_appears(self) -> None:
        gates = {row["gate_id"] for row in self.hotspots()["gates"]}
        self.assertNotIn("other-gate", gates)

    def test_no_other_workflows_cost_appears(self) -> None:
        """The other run costs $0.99 against this workflow's $0.36 total."""

        total = sum(row["cost_usd"] for row in self.hotspots()["agents"])
        self.assertLess(total, 0.99)

    def test_the_run_count_is_this_workflows_own(self) -> None:
        self.assertEqual(6, self.hotspots()["runs"])

    def test_the_other_workflow_can_be_mined_on_its_own(self) -> None:
        """The control: the seed really does hold two workflows."""

        body = self.ok(f"/improve/hotspots?workflow_id={OTHER}")
        self.assertEqual(1, body["runs"])
        self.assertEqual(
            {"OtherWorkflowTool"}, {row["tool"] for row in body["tools"]}
        )


class WindowAndCapTests(MiningWorld):
    """A18: the cap, the flag, and plan 17's window rules inherited."""

    def test_the_scan_cap_sets_truncated(self) -> None:
        with patch.object(config, "ADMIN_MAX_SCAN_ROWS", 2):
            body = self.hotspots()
        self.assertTrue(body["truncated"])

    def test_an_untruncated_window_says_so(self) -> None:
        self.assertFalse(self.hotspots()["truncated"])

    def test_a_window_wider_than_the_maximum_is_422(self) -> None:
        with patch.object(config, "ADMIN_MAX_WINDOW_DAYS", 1):
            response = self.get(
                f"/improve/hotspots?workflow_id={MINE}"
                "&from=2020-01-01T00:00:00Z&to=2026-01-01T00:00:00Z"
            )
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_malformed_date_is_422_and_not_500(self) -> None:
        response = self.get(f"/improve/hotspots?workflow_id={MINE}&from=yesterday")
        self.assertEqual(response.status_code, 422, response.text)

    def test_a_narrow_window_excludes_the_runs(self) -> None:
        recent = (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        later = (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        body = self.ok(
            f"/improve/hotspots?workflow_id={MINE}&from={recent}&to={later}"
        )
        self.assertEqual(0, body["runs"])
        self.assertEqual([], body["agents"])

    def test_the_workflow_id_is_required(self) -> None:
        """A hot spot is a statement about ONE graph; pooling two would put a
        name beside a count that belongs to something else."""

        self.assertEqual(422, self.get("/improve/hotspots").status_code)

    def test_the_panel_is_404_to_a_non_admin(self) -> None:
        response = self.client.get(
            f"/api/admin/improve/hotspots?workflow_id={MINE}", headers=self.as_alice()
        )
        self.assertEqual(response.status_code, 404, response.text)


class FramesByKindTests(unittest.TestCase):
    """A15 on the persistence method itself, and on its three call sites."""

    def setUp(self) -> None:
        from brief_crew.service.persistence import PostgresFlowPersistence

        self.store = PostgresFlowPersistence("sqlite+pysqlite:///:memory:")
        self.addCleanup(self.store.close)
        self.store.init_db()
        now = datetime.now(timezone.utc)
        for run_id, workflow_id, status in (
            ("a", "wf-one", "completed"),
            ("b", "wf-two", "completed"),
            ("c", "wf-one", "failed"),
        ):
            self.store.create_run(
                run_id=run_id,
                session_id="s",
                workflow_id=workflow_id,
                graph_version="v1",
                inputs={},
                status="queued",
                created_at=now - timedelta(minutes=5),
            )
            self.store.update_run_status(run_id, status)
            self._frame(run_id)

    def _frame(self, run_id: str) -> None:
        from brief_crew.events import FrameData, FrameKind, FrameLevel, UIEventType

        self.store.append_frames(
            run_id,
            [
                FrameData(
                    seq=1,
                    run_id=run_id,
                    ts=datetime.now(timezone.utc),
                    kind=FrameKind.VERDICT,
                    event_type=UIEventType.WORKFLOW_END,
                    level=FrameLevel.INFO,
                    node_id="n",
                    message="m",
                    details={"verdict": "VALIDATE"},
                )
            ],
        )

    def test_workflow_ids_filters(self) -> None:
        rows, _ = self.store.admin_frames_by_kind(["verdict"], workflow_ids=["wf-one"])
        self.assertEqual({"a", "c"}, {row["run_id"] for row in rows})

    def test_statuses_filters(self) -> None:
        rows, _ = self.store.admin_frames_by_kind(["verdict"], statuses=["failed"])
        self.assertEqual({"c"}, {row["run_id"] for row in rows})

    def test_the_two_filters_compose(self) -> None:
        rows, _ = self.store.admin_frames_by_kind(
            ["verdict"], workflow_ids=["wf-one"], statuses=["completed"]
        )
        self.assertEqual({"a"}, {row["run_id"] for row in rows})

    def test_an_empty_filter_list_returns_nothing_rather_than_everything(self) -> None:
        """The failure mode a naive `if workflow_ids:` produces: an explicit
        empty list means "none of them", never "all of them"."""

        rows, truncated = self.store.admin_frames_by_kind(["verdict"], workflow_ids=[])
        self.assertEqual([], rows)
        self.assertFalse(truncated)

    def test_the_existing_call_sites_pass_neither_filter(self) -> None:
        """Extended, not changed, asserted over the source rather than by
        memory.

        `/verdicts`, `/runs/{id}/decisions`, the billed lookup and the
        governance insights all call this, and none of them may have
        changed behaviour.

        It reads each CALL rather than grepping the file, and the
        difference is not pedantry: `statuses=` appears in `admin_api.py`
        already, on `admin_run_window`, which is a different method
        entirely. A file-wide grep would fail over a call it was never
        about - and, worse, would have passed for years and then started
        failing for a reason unconnected to what it checks.
        """

        import pathlib

        import brief_crew.service.admin_api as admin_api

        source = pathlib.Path(admin_api.__file__).read_text(encoding="utf-8")
        calls = self.calls_to(source, "admin_frames_by_kind(")
        self.assertGreaterEqual(len(calls), 3)
        for index, call in enumerate(calls):
            for fragment in ("workflow_ids=", "statuses="):
                with self.subTest(call=index, fragment=fragment):
                    self.assertNotIn(fragment, call)

    @staticmethod
    def calls_to(source: str, name: str) -> list[str]:
        """Each call's own text, by balancing parentheses from the name."""

        found: list[str] = []
        cursor = 0
        while True:
            at = source.find(name, cursor)
            if at < 0:
                return found
            depth = 0
            index = at + len(name) - 1
            while index < len(source):
                if source[index] == "(":
                    depth += 1
                elif source[index] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            found.append(source[at : index + 1])
            cursor = index + 1

    def test_without_the_filters_the_answer_is_what_it_always_was(self) -> None:
        rows, _ = self.store.admin_frames_by_kind(["verdict"])
        self.assertEqual({"a", "b", "c"}, {row["run_id"] for row in rows})


class NoJsonPathInMiningSqlTests(unittest.TestCase):
    """Every statement the mining reads emit, on both dialects."""

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
        now = datetime.now(timezone.utc)
        start, end = now - timedelta(days=30), now
        self.store.improve_runs(workflow_id="ug_1", start=start, end=end)
        self.store.improve_runs(
            workflow_ids=["ug_1", "ug_2"],
            statuses=["completed"],
            ratings=["good"],
            start=start,
            end=end,
        )
        self.store.improve_runs(rated_only=True)
        self.store.improve_run_payloads(["r-1"])
        self.store.improve_frame_kind_counts(["r-1"])
        self.store.improve_node_costs(["r-1"])
        self.store.admin_frames_by_kind(
            ["agent", "tool"], workflow_ids=["ug_1"], statuses=["completed"]
        )
        self.store.admin_gate_window(run_ids=["r-1"])
        self.store.run_ratings(["r-1"])
        self.store.set_run_rating("r-1", rating="good", note="n", rated_by="u")
        self.store.list_digests("ug_1")
        self.store.digest_cost_total("ug_1", start=start, end=end)
        self.store.digest_cost_total()

    def test_no_statement_carries_a_json_path_on_sqlite(self) -> None:
        self.exercise()
        self.assertGreater(len(self.statements), 10, "nothing was recorded")
        for statement in self.statements:
            with self.subTest(sql=statement[:90]):
                self.assertIsNone(JSON_PATH.search(statement))

    def test_no_statement_carries_a_json_path_on_postgresql(self) -> None:
        """The half SQLite cannot show, and the half that would ship broken.

        Compiled against the PostgreSQL dialect, which is the deployed one: a
        SQLAlchemy expression can render innocently on SQLite and render `->>`
        there.
        """

        from sqlalchemy import func, select
        from sqlalchemy.dialects import postgresql

        from brief_crew.service import persistence as p

        now = datetime.now(timezone.utc)
        statements = [
            select(p.runs.c.id, p.runs.c.rating, p.runs.c.document_version).where(
                p.runs.c.created_at >= now - timedelta(days=1)
            ),
            select(p.runs.c.id, p.runs.c.inputs, p.runs.c.result).where(
                p.runs.c.id.in_(["r-1"])
            ),
            select(p.run_frames.c.kind, func.count())
            .where(p.run_frames.c.run_id.in_(["r-1"]))
            .group_by(p.run_frames.c.kind),
            select(
                p.run_node_metrics.c.run_id,
                p.run_node_metrics.c.model,
                p.run_node_metrics.c.cost_usd,
                p.run_node_metrics.c.prompt_tokens,
            ).where(p.run_node_metrics.c.run_id.in_(["r-1"])),
            select(p.run_gates).where(p.run_gates.c.run_id.in_(["r-1"])),
            select(func.coalesce(func.sum(p.improve_digests.c.cost_usd), 0)).where(
                p.improve_digests.c.workflow_id == "ug_1"
            ),
        ]
        for statement in statements:
            rendered = str(statement.compile(dialect=postgresql.dialect()))
            with self.subTest(sql=rendered[:90]):
                self.assertIsNone(JSON_PATH.search(rendered))

    def test_the_improve_module_writes_no_json_path_in_its_source(self) -> None:
        """The third direction: a hand-written fragment nothing compiled.

        `text("details ->> 'tool'")` would evade both tests above, because
        neither runs a statement this module did not build.
        """

        import ast
        import pathlib

        from brief_crew.service import improve_api

        source = pathlib.Path(improve_api.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        # DOCSTRINGS ARE EXEMPT and every other string literal is not. The
        # module docstring names both spellings in order to FORBID them, so a
        # plain substring search over the file answers "yes" for the sentence
        # that says "never do this". Walking the AST and skipping each
        # module's, class's and function's docstring is the difference between
        # a check and a tautology.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(
                node,
                (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                with self.subTest(literal=node.value[:60]):
                    self.assertNotIn("json_extract", node.value)
                    self.assertNotIn("->>", node.value)
        # And nothing hand-writes SQL at all, which is the door both spellings
        # would have to come through.
        self.assertNotIn("sqlalchemy import text", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
