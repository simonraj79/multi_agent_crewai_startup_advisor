"""Every `GET` answers its plan 17 section 3 shape over real rows (5, 6, 8, 11).

Four criteria, and each one is a way a dashboard lies quietly rather than
loudly:

* **5** - the shapes, against a SEEDED database, including the three cases an
  aggregate silently drops: a run with `user_id IS NULL`, a run with no
  `run_node_metrics` row at all, and an empty window. None of the three is an
  error and all three have wrong answers that look plausible.
* **6** - every `group_by` total equals the sum of its own rows, **to the
  cent, in `Decimal`**. Never `assertAlmostEqual` on floats: money compared
  approximately is money that reconciles approximately.
* **8** - the refusal counts IMPORT `registry.ACCOUNT_CAP_ERROR_PREFIX` and
  `COST_CEILING_ERROR_PREFIX`. Patching the constant changes the count, which
  is the only thing that proves no literal was re-typed - a copy would pass a
  test that merely seeded the current sentence.
* **11** - `ADMIN_MAX_SCAN_ROWS` is enforced and a fixture above it answers
  `truncated: true` rather than describing a prefix as the whole.
"""

from __future__ import annotations

from decimal import Decimal
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.service import registry as registry_module
from tests.service.admin_fixtures import ALICE, BOB, AdminCase


class SummaryShapeTests(AdminCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_run("run-alice-1", user_id=ALICE.id, cost="0.0500", age_hours=2)
        self.seed_run("run-alice-2", user_id=ALICE.id, cost="0.0250", age_hours=3)
        self.seed_run("run-bob-1", user_id=BOB.id, cost="0.1000", status="failed")
        # The two cases an aggregate drops if nobody names them.
        self.seed_run("run-unowned", user_id=None, cost="0.0100")
        self.seed_run("run-free", user_id=ALICE.id, cost=None)

    def test_the_summary_carries_every_key_section_3_names(self) -> None:
        body = self.ok("/summary")
        self.assertEqual(
            set(body),
            {
                "spend_usd_estimate",
                "estimate",
                "error_note",
                "runs",
                "people_active",
                "people_total",
                "people_new",
                "refusals",
                "spend_by_day",
                "top_accounts",
                "attention",
                "truncated",
            },
        )
        self.assertTrue(body["estimate"])
        self.assertEqual(
            set(body["runs"]),
            {
                "queued",
                "running",
                "waiting",
                "completed",
                "failed",
                "cancelling",
                "cancelled",
            },
        )

    def test_the_estimate_is_the_sum_of_every_seeded_run(self) -> None:
        body = self.ok("/summary")
        self.assertEqual(
            Decimal(str(body["spend_usd_estimate"])), Decimal("0.1850")
        )

    def test_status_counts_come_from_the_group_by(self) -> None:
        body = self.ok("/summary")
        self.assertEqual(body["runs"]["completed"], 4)
        self.assertEqual(body["runs"]["failed"], 1)
        self.assertEqual(body["runs"]["queued"], 0)

    def test_a_run_with_no_owner_lands_in_the_reserved_key(self) -> None:
        """Never dropped and never merged with a real account (criterion 5).

        Its spend is real money: pre-auth rows and every run made on a
        deployment with no identity are in this bucket, and a `GROUP BY` that
        let them fall out would under-report the total by exactly the amount
        nobody can attribute.
        """

        body = self.ok("/summary")
        accounts = {row["user_id"]: row for row in body["top_accounts"]}
        self.assertIn("__unowned__", accounts)
        self.assertEqual(Decimal(str(accounts["__unowned__"]["spent_usd"])), Decimal("0.0100"))
        self.assertIsNone(accounts["__unowned__"]["email"])
        # It is not an account, so it has no cap and is not exempt from one.
        self.assertIsNone(accounts["__unowned__"]["cap_usd"])
        self.assertFalse(accounts["__unowned__"]["exempt"])

    def test_a_run_with_no_metrics_row_costs_zero_rather_than_vanishing(self) -> None:
        """An inner join would have dropped `run-free` from every figure."""

        body = self.ok("/runs")
        rows = {row["run_id"]: row for row in body["rows"]}
        self.assertIn("run-free", rows)
        self.assertEqual(rows["run-free"]["cost_usd"], 0.0)
        # And it still counts as a run in the status counts.
        self.assertEqual(self.ok("/summary")["runs"]["completed"], 4)

    def test_an_empty_window_answers_zeroes_and_not_a_404(self) -> None:
        body = self.ok(
            "/summary", params={"from": "2020-01-01T00:00:00Z", "to": "2020-01-02T00:00:00Z"}
        )
        self.assertEqual(body["spend_usd_estimate"], 0.0)
        self.assertEqual(body["spend_by_day"], [])
        self.assertEqual(body["top_accounts"], [])
        self.assertEqual(body["runs"]["completed"], 0)

    def test_the_day_bucket_is_utc_and_sums_to_the_total(self) -> None:
        body = self.ok("/summary")
        total = sum(
            (Decimal(str(day["usd"])) for day in body["spend_by_day"]), Decimal("0")
        )
        self.assertEqual(total, Decimal(str(body["spend_usd_estimate"])))
        for day in body["spend_by_day"]:
            self.assertRegex(day["day"], r"^\d{4}-\d{2}-\d{2}$")

    def test_an_unanswered_gate_reaches_attention(self) -> None:
        self.seed_gate("run-alice-1", decision=None, age_hours=26)
        body = self.ok("/summary")
        kinds = {(item["kind"], item["run_id"]) for item in body["attention"]}
        self.assertIn(("gate_open_long", "run-alice-1"), kinds)
        hours = next(item["hours"] for item in body["attention"])
        self.assertGreater(hours, 25.0)

    def test_a_window_wider_than_the_maximum_is_refused(self) -> None:
        """Refused, never silently clamped - a dashboard that answers a
        different question from the one asked is how a figure gets quoted for
        the wrong period."""

        response = self.get(
            "/summary",
            params={"from": "2020-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("limited to", response.json()["detail"])

    def test_a_malformed_window_is_422_and_names_the_parameter(self) -> None:
        response = self.get("/summary", params={"from": "last tuesday"})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("from", response.json()["detail"])


class SpendAxisTests(AdminCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_run(
            "run-a",
            user_id=ALICE.id,
            cost="0.0500",
            model="openrouter/google/gemini-3.8-flash",
            node_id="scope_idea",
        )
        self.seed_run(
            "run-b",
            user_id=BOB.id,
            cost="0.0250",
            model="openrouter/google/gemini-3.5-flash-lite",
            node_id="market",
            workflow_id="brief-flow",
        )
        self.seed_run("run-c", user_id=None, cost="0.0125", node_id="market")

    def test_every_axis_answers_and_totals_to_its_own_rows(self) -> None:
        """Criterion 6, in `Decimal` and never in float equality."""

        for axis in ("user", "day", "workflow", "model", "node"):
            with self.subTest(group_by=axis):
                body = self.ok("/spend", params={"group_by": axis})
                self.assertEqual(body["group_by"], axis)
                rows = sum(
                    (Decimal(str(row["cost_usd"])) for row in body["rows"]),
                    Decimal("0"),
                )
                self.assertEqual(rows, Decimal(str(body["total_usd"])))
                self.assertEqual(rows, Decimal("0.0875"))

    def test_the_user_axis_carries_the_reserved_key(self) -> None:
        body = self.ok("/spend", params={"group_by": "user"})
        self.assertIn("__unowned__", {row["key"] for row in body["rows"]})

    def test_the_model_axis_names_the_models(self) -> None:
        body = self.ok("/spend", params={"group_by": "model"})
        self.assertEqual(
            {row["key"] for row in body["rows"]},
            {
                "openrouter/google/gemini-3.8-flash",
                "openrouter/google/gemini-3.5-flash-lite",
            },
        )

    def test_tokens_and_calls_ride_along_on_the_four_sql_axes(self) -> None:
        body = self.ok("/spend", params={"group_by": "node"})
        by_key = {row["key"]: row for row in body["rows"]}
        self.assertEqual(by_key["market"]["call_count"], 4)
        self.assertEqual(by_key["market"]["runs"], 2)
        self.assertEqual(
            by_key["scope_idea"]["prompt_tokens"]
            + by_key["scope_idea"]["completion_tokens"],
            by_key["scope_idea"]["total_tokens"],
        )

    def test_an_unknown_axis_is_422(self) -> None:
        response = self.get("/spend", params={"group_by": "colour"})
        self.assertEqual(response.status_code, 422, response.text)


class RefusalCountingTests(AdminCase):
    """Criterion 8: the prefixes are imported, and patching one proves it."""

    def seed_refusals(self) -> None:
        self.seed_run(
            "capped",
            error=registry_module.ACCOUNT_CAP_ERROR_PREFIX + " you have spent it all",
            status="failed",
        )
        self.seed_run(
            "ceilinged",
            error=registry_module.COST_CEILING_ERROR_PREFIX + " this run cost too much",
            status="failed",
        )
        self.seed_run("ordinary", error="something else went wrong", status="failed")

    def test_both_prefixes_are_counted_and_nothing_else_is(self) -> None:
        self.seed_refusals()
        body = self.ok("/summary")
        self.assertEqual(body["refusals"], {"account_cap": 1, "run_ceiling": 1})

    def test_patching_the_constant_changes_the_count(self) -> None:
        """A re-typed literal would keep counting the old sentence.

        The rows are seeded with the CURRENT prefix and then the constant is
        moved; a reader that imported it now finds nothing, and a reader that
        copied the string still finds two. There is no way to write a copy
        that passes this.
        """

        self.seed_refusals()
        with patch.object(
            registry_module, "ACCOUNT_CAP_ERROR_PREFIX", "a completely different stop:"
        ), patch.object(
            registry_module, "COST_CEILING_ERROR_PREFIX", "another different stop:"
        ):
            body = self.ok("/summary")
        self.assertEqual(body["refusals"], {"account_cap": 0, "run_ceiling": 0})

    def test_stop_reason_on_a_run_row_comes_from_the_same_module(self) -> None:
        """`_restored_stop_reason` is the one place that knows which is which.

        The same function `_restore_record` uses when a run comes back after a
        restart, so an admin reading "why did this stop" and the registry
        rebuilding a record cannot disagree.
        """

        self.seed_refusals()
        rows = {row["run_id"]: row for row in self.ok("/runs")["rows"]}
        self.assertEqual(rows["capped"]["stop_reason"], registry_module.ACCOUNT_CAP_REASON)
        self.assertEqual(
            rows["ceilinged"]["stop_reason"], registry_module.COST_CEILING_REASON
        )
        self.assertIsNone(rows["ordinary"]["stop_reason"])


class ScanCapTests(AdminCase):
    """Criterion 11: a fixture above the cap says so rather than lying."""

    def test_a_window_above_the_cap_answers_truncated(self) -> None:
        for index in range(6):
            self.seed_run(f"run-{index}", cost="0.0100", age_hours=index + 1)
        with patch.object(config, "ADMIN_MAX_SCAN_ROWS", 3):
            body = self.ok("/summary")
        self.assertTrue(body["truncated"])
        # And the figure it DID compute is the prefix it read, not a guess.
        self.assertEqual(Decimal(str(body["spend_usd_estimate"])), Decimal("0.0300"))

    def test_under_the_cap_is_not_truncated(self) -> None:
        for index in range(3):
            self.seed_run(f"run-{index}", cost="0.0100", age_hours=index + 1)
        with patch.object(config, "ADMIN_MAX_SCAN_ROWS", 50):
            body = self.ok("/summary")
        self.assertFalse(body["truncated"])

    def test_the_spend_axes_report_truncation_too(self) -> None:
        for index in range(6):
            self.seed_run(f"run-{index}", cost="0.0100", node_id=f"node{index}")
        with patch.object(config, "ADMIN_MAX_SCAN_ROWS", 2):
            self.assertTrue(self.ok("/spend", params={"group_by": "node"})["truncated"])


class RunsAndGatesAndVerdictsShapeTests(AdminCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        self.seed_gate("r-1", decision="approve", seconds=120)
        self.seed_gate("r-1", "verdict-review", decision="revise", seconds=300)
        self.seed_frame("r-1", details={"verdict": "NEEDS_WORK", "score": 4.2})

    def test_a_run_row_carries_every_key_section_3_names(self) -> None:
        row = self.ok("/runs")["rows"][0]
        self.assertEqual(
            set(row),
            {
                "run_id",
                "user_id",
                "email",
                "workflow_id",
                "mode",
                "status",
                "created_at",
                "started_at",
                "completed_at",
                "duration_ms",
                "cost_usd",
                "ceiling_kind",
                "max_cost_usd",
                "account_cap_usd",
                "stop_reason",
                "error",
                "verdict",
                "integrity",
                "langfuse",
            },
        )
        self.assertEqual(row["verdict"], "NEEDS_WORK")
        self.assertEqual(row["duration_ms"], 60000)
        self.assertEqual(set(row["integrity"]), {"captured", "dropped", "gaps"})
        self.assertEqual(set(row["langfuse"]), {"session_url", "trace_url"})

    def test_the_gates_panel_counts_outcomes_and_medians(self) -> None:
        body = self.ok("/gates")
        self.assertEqual(body["approve"], 1)
        self.assertEqual(body["revise"], 1)
        self.assertEqual(body["unanswered"], 0)
        self.assertEqual(body["median_seconds"], 210.0)
        by_gate = {bucket["gate_id"]: bucket for bucket in body["by_gate"]}
        self.assertEqual(by_gate["scope-confirmation"]["median_seconds"], 120.0)
        self.assertEqual(by_gate["verdict-review"]["median_seconds"], 300.0)

    def test_an_unanswered_gate_has_no_median_rather_than_zero(self) -> None:
        """`None`, never `0`: a zero draws as "answered instantly" on the one
        tile that exists to find the ones nobody answered."""

        self.seed_run("r-2")
        self.seed_gate("r-2", "nobody-answered", decision=None)
        body = self.ok("/gates")
        by_gate = {bucket["gate_id"]: bucket for bucket in body["by_gate"]}
        self.assertIsNone(by_gate["nobody-answered"]["median_seconds"])
        self.assertEqual(body["unanswered"], 1)

    def test_verdicts_are_counted_and_labelled_fragile(self) -> None:
        body = self.ok("/verdicts")
        self.assertEqual(body["rows"], [{"verdict": "NEEDS_WORK", "count": 1}])
        self.assertTrue(body["complete"])
        self.assertIn("VALIDATOR_RUN_RETENTION_DAYS", body["note"])

    def test_retention_above_zero_makes_the_verdict_tile_incomplete(self) -> None:
        """Plan 17 risk 3: a purge cascades to `run_frames` and takes these.

        `complete: false` is the tile's own admission that it is describing a
        window somebody may already have deleted.
        """

        with patch.object(config, "VALIDATOR_RUN_RETENTION_DAYS", 30):
            self.assertFalse(self.ok("/verdicts")["complete"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
