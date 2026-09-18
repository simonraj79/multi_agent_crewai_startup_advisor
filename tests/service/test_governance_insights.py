"""The admin's deterministic, content-free governance findings."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import update

from brief_crew import config
from brief_crew.service.persistence import runs
from brief_crew.service import registry as registry_module
from tests.service.admin_fixtures import AdminCase, NOW


class GovernanceInsightsTests(AdminCase):
    def seed_three(self, workflow: str = "wf-a") -> None:
        for number in range(3):
            self.seed_run(
                f"{workflow}-{number}",
                workflow_id=workflow,
                status="failed" if number < 2 else "completed",
                cost=f"0.0{number + 1}",
            )
            self.seed_frame(
                f"{workflow}-{number}", kind="agent", details={"stage": "after"}
            )

    def test_failed_runs_become_one_evidence_backed_finding(self) -> None:
        self.seed_three()
        body = self.ok("/insights")
        finding = body["findings"][0]
        self.assertEqual(
            (finding["rule_id"], finding["affected_runs"], finding["total_runs"]),
            ("failed_run", 2, 3),
        )
        self.assertEqual(body["thresholds"], {"min_runs": 3, "min_affected_runs": 2})
        self.assertEqual(finding["samples"][0]["user_id"], "user_alice")
        self.assertIn("cost_usd", finding["samples"][0])

    def test_rules_deduplicate_multiple_frames_from_one_run(self) -> None:
        for n in range(3):
            rid = self.seed_run(f"r-{n}", workflow_id="wf", status="completed")
            self.seed_frame(
                rid,
                seq=1,
                kind="guardrail",
                node_id="writer",
                details={"stage": "after", "retry_count": 1, "success": False},
            )
            if n < 2:
                self.seed_frame(
                    rid,
                    seq=2,
                    kind="guardrail",
                    node_id="writer",
                    details={"stage": "after", "retry_count": 2, "success": False},
                )
        finding = self.ok("/insights")["findings"][0]
        self.assertEqual((finding["affected_runs"], finding["total_runs"]), (3, 3))
        self.assertEqual(len(finding["samples"]), 3)

    def test_gate_revision_and_fallback_rules_use_metadata_only(self) -> None:
        for n in range(3):
            rid = self.seed_run(f"meta-{n}", workflow_id="wf-meta")
            self.seed_frame(
                rid,
                kind="node_state",
                node_id="research",
                details={
                    "stage": "retry",
                    "attempt": 2,
                    "of": 2,
                    "model": "private-model-name",
                },
            )
            self.seed_gate(
                rid, gate_id="review", node_id="review-node", decision="revise"
            )
            self.store.update_run_status(rid, "completed")
        answer = self.ok("/insights")
        findings = {row["rule_id"]: row for row in answer["findings"]}
        self.assertIn("fallback_model", findings, answer)
        self.assertEqual(findings["fallback_model"]["affected_runs"], 3)
        self.assertEqual(findings["gate_revise"]["affected_runs"], 3)
        rendered = str(findings)
        self.assertNotIn("private-model-name", rendered)
        self.assertNotIn("the segment is right", rendered)

    def test_workflow_and_window_isolate_the_denominator(self) -> None:
        self.seed_three("wf-a")
        self.seed_three("wf-b")
        body = self.ok("/insights?workflow_id=wf-a")
        self.assertEqual(body["workflows"], [{"workflow_id": "wf-a", "runs": 3}])
        self.assertTrue(all(row["workflow_id"] == "wf-a" for row in body["findings"]))

        cutoff = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        outside = self.ok(f"/insights?workflow_id=wf-a&from={cutoff}")
        self.assertEqual(outside["coverage"]["runs_scanned"], 0)

    def test_nonterminal_runs_are_not_in_the_sample(self) -> None:
        self.seed_three()
        self.seed_run("still-running", workflow_id="wf-a", status="running")
        body = self.ok("/insights?workflow_id=wf-a")
        self.assertEqual(body["coverage"]["runs_scanned"], 3)

    def test_policy_stops_are_not_called_execution_failures(self) -> None:
        prefixes = (
            registry_module.ACCOUNT_CAP_ERROR_PREFIX,
            registry_module.COST_CEILING_ERROR_PREFIX,
        )
        for n in range(3):
            self.seed_run(
                f"cap-{n}",
                workflow_id="caps",
                status="failed",
                error=f"{prefixes[n % 2]} reached",
            )
            self.seed_frame(f"cap-{n}", kind="agent", details={"stage": "after"})
        rules = {
            row["rule_id"] for row in self.ok("/insights?workflow_id=caps")["findings"]
        }
        self.assertNotIn("failed_run", rules)

    def test_insufficient_and_suppressed_are_explicit(self) -> None:
        self.seed_run("only", workflow_id="small", status="failed")
        body = self.ok("/insights")
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["insufficient"][0]["total_runs"], 1)
        self.assertEqual(body["suppressed_count"], 1)

    def test_one_affected_run_is_suppressed_below_the_affected_floor(self) -> None:
        for n in range(3):
            self.seed_run(
                f"floor-{n}",
                workflow_id="floor",
                status="failed" if n == 0 else "completed",
            )
            self.seed_frame(f"floor-{n}", kind="agent", details={"stage": "after"})
        body = self.ok("/insights?workflow_id=floor")
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["suppressed_count"], 1)

    def test_no_sensitive_content_crosses_the_response(self) -> None:
        self.seed_three()
        self.seed_gate("wf-a-0", decision="revise", note="SECRET HUMAN WORDS")
        self.seed_gate("wf-a-1", decision="revise", note="ANOTHER SECRET")
        self.store.update_run_status("wf-a-0", "failed")
        self.store.update_run_status("wf-a-1", "failed")
        text = self.get("/insights").text
        self.assertNotIn("SECRET", text)
        self.assertNotIn("response", text)
        self.assertNotIn("error", text.lower())

    def test_retention_and_scan_caps_make_coverage_incomplete(self) -> None:
        self.seed_three()
        with (
            patch.object(config, "VALIDATOR_RUN_RETENTION_DAYS", 7),
            patch.object(config, "ADMIN_MAX_SCAN_ROWS", 2),
        ):
            body = self.ok("/insights")
        self.assertTrue(body["coverage"]["truncated"])
        self.assertTrue(body["coverage"]["incomplete"])
        self.assertEqual(body["coverage"]["retention_days"], 7)

    def test_exactly_at_the_run_cap_is_not_truncated(self) -> None:
        self.seed_three()
        with patch.object(config, "ADMIN_MAX_SCAN_ROWS", 3):
            body = self.ok("/insights")
        self.assertFalse(body["coverage"]["truncated"])

    def test_integrity_loss_is_reported(self) -> None:
        self.seed_three()
        with self.store._begin() as connection:
            connection.execute(
                update(runs).where(runs.c.id == "wf-a-0").values(dropped_frames=1)
            )
        body = self.ok("/insights")
        self.assertEqual(body["coverage"]["runs_with_integrity_loss"], 1)
        self.assertTrue(body["coverage"]["incomplete"])

    def test_capped_details_do_not_turn_existing_frames_into_missing_frames(
        self,
    ) -> None:
        for n in range(3):
            rid = self.seed_run(f"bounded-{n}", workflow_id="bounded")
            for seq in (1, 2):
                self.seed_frame(
                    rid,
                    seq=seq,
                    kind="guardrail",
                    node_id="writer",
                    details={"stage": "after", "retry_count": seq},
                )
        with patch.object(config, "ADMIN_MAX_SCAN_ROWS", 3):
            body = self.ok("/insights")
        self.assertEqual(body["coverage"]["runs_missing_frames"], 0)
        self.assertEqual(body["coverage"]["frames_scanned"], 3)
        self.assertTrue(body["coverage"]["truncated"])
        finding = body["findings"][0]
        self.assertEqual((finding["affected_runs"], finding["total_runs"]), (2, 3))
        self.assertTrue(finding["explanation"].startswith("At least "))

    def test_unrelated_frames_do_not_consume_the_signal_scan_budget(self) -> None:
        for n in range(3):
            rid = self.seed_run(f"quiet-{n}", workflow_id="quiet")
            for seq in range(1, 8):
                self.seed_frame(rid, seq=seq, kind="agent")
        with patch.object(config, "ADMIN_MAX_SCAN_ROWS", 3):
            body = self.ok("/insights")
        self.assertEqual(body["coverage"]["frames_scanned"], 0)
        self.assertEqual(body["coverage"]["runs_missing_frames"], 0)
        self.assertFalse(body["coverage"]["incomplete"])

    def test_gate_outcomes_use_the_existing_admin_normalization(self) -> None:
        for n in range(3):
            rid = self.seed_run(f"space-{n}", workflow_id="spaces")
            self.seed_gate(rid, decision=" revise ")
            self.store.update_run_status(rid, "completed")
        body = self.ok("/insights")
        self.assertEqual(body["findings"][0]["rule_id"], "gate_revise")

    def test_guardrail_uses_after_frames_with_positive_integer_retry_only(self) -> None:
        for n in range(3):
            rid = self.seed_run(f"sem-{n}", workflow_id="semantics")
            self.seed_frame(
                rid,
                seq=1,
                kind="guardrail",
                node_id="writer",
                details={"stage": "before", "retry_count": 9},
            )
            self.seed_frame(
                rid,
                seq=2,
                kind="guardrail",
                node_id="writer",
                details={
                    "stage": "after",
                    "retry_count": "malformed",
                    "success": False,
                },
            )
        body = self.ok("/insights?workflow_id=semantics")
        self.assertEqual(body["findings"], [])
        self.assertGreaterEqual(body["suppressed_count"], 0)

    def test_unknown_gate_outcome_does_not_count_as_revision(self) -> None:
        for n in range(3):
            rid = self.seed_run(f"gate-{n}", workflow_id="gates")
            self.seed_frame(rid, kind="agent", details={"stage": "after"})
            self.seed_gate(rid, gate_id="review", decision="defer")
            self.store.update_run_status(rid, "completed")
        rules = {
            row["rule_id"] for row in self.ok("/insights?workflow_id=gates")["findings"]
        }
        self.assertNotIn("gate_revise", rules)

    # -- plan 20: the labels strip and the `rated_bad` rule ----------------

    def rate(self, run_id: str, rating: str | None, note: str | None = None) -> None:
        self.store.set_run_rating(
            run_id, rating=rating, note=note, rated_by="user_alice"
        )

    def test_labels_count_every_scanned_terminal_run(self) -> None:
        """`unrated` is a real count, not a remainder the client works out -
        and early on it is nearly everything, which is the point."""

        self.seed_three("wf-a")
        self.rate("wf-a-0", "good")
        self.rate("wf-a-1", "bad")
        body = self.ok("/insights?workflow_id=wf-a")
        self.assertEqual(
            body["labels"], {"good": 1, "bad": 1, "unsure": 0, "unrated": 1}
        )
        self.assertEqual(
            sum(body["labels"].values()), body["coverage"]["runs_scanned"]
        )

    def test_labels_obey_the_workflow_and_window_scope(self) -> None:
        self.seed_three("wf-a")
        self.seed_three("wf-b")
        self.rate("wf-a-0", "good")
        self.rate("wf-b-0", "bad")
        self.assertEqual(
            self.ok("/insights?workflow_id=wf-a")["labels"],
            {"good": 1, "bad": 0, "unsure": 0, "unrated": 2},
        )
        cutoff = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        outside = self.ok(f"/insights?from={cutoff}")
        self.assertEqual(
            outside["labels"], {"good": 0, "bad": 0, "unsure": 0, "unrated": 0}
        )

    def test_a_non_terminal_run_is_in_neither_the_labels_nor_the_rule(self) -> None:
        self.seed_three("wf-a")
        self.seed_run("still-running", workflow_id="wf-a", status="running")
        self.rate("still-running", "bad")
        body = self.ok("/insights?workflow_id=wf-a")
        self.assertEqual(body["labels"]["bad"], 0)
        self.assertEqual(body["labels"]["unrated"], 3)

    def test_rated_bad_fires_at_the_floors(self) -> None:
        self.seed_three("wf-a")
        self.rate("wf-a-0", "bad", note="SECRET HUMAN WORDS")
        self.rate("wf-a-1", "bad")
        findings = {
            row["rule_id"]: row
            for row in self.ok("/insights?workflow_id=wf-a")["findings"]
        }
        self.assertIn("rated_bad", findings)
        row = findings["rated_bad"]
        self.assertEqual(
            (row["severity"], row["node_id"], row["gate_id"]), ("high", "(run)", None)
        )
        self.assertEqual((row["affected_runs"], row["total_runs"]), (2, 3))
        self.assertEqual(len(row["samples"]), 2)
        self.assertIn("judgement", row["explanation"])

    def test_the_raters_note_is_nowhere_in_the_finding(self) -> None:
        """A note is free text a person typed. This response is metadata."""

        self.seed_three("wf-a")
        self.rate("wf-a-0", "bad", note="SECRET HUMAN WORDS")
        self.rate("wf-a-1", "bad", note="ANOTHER SECRET")
        text = self.get("/insights?workflow_id=wf-a").text
        self.assertNotIn("SECRET", text)
        self.assertNotIn("HUMAN WORDS", text)

    def test_one_bad_rating_is_suppressed_below_the_affected_floor(self) -> None:
        self.seed_three("wf-a")
        self.rate("wf-a-2", "bad")
        rules = {
            row["rule_id"]
            for row in self.ok("/insights?workflow_id=wf-a")["findings"]
        }
        self.assertNotIn("rated_bad", rules)

    def test_two_bad_ratings_under_the_run_floor_are_suppressed(self) -> None:
        for number in range(2):
            self.seed_run(f"tiny-{number}", workflow_id="tiny")
            self.rate(f"tiny-{number}", "bad")
        body = self.ok("/insights?workflow_id=tiny")
        self.assertEqual(body["findings"], [])
        self.assertEqual(body["labels"]["bad"], 2)

    def test_good_and_unsure_and_cleared_never_fire_the_rule(self) -> None:
        """Only `bad` is a complaint. `unsure` is a person declining to say."""

        self.seed_three("wf-a")
        self.rate("wf-a-0", "good")
        self.rate("wf-a-1", "unsure")
        self.rate("wf-a-2", "bad")
        self.rate("wf-a-2", None)
        rules = {
            row["rule_id"]
            for row in self.ok("/insights?workflow_id=wf-a")["findings"]
        }
        self.assertNotIn("rated_bad", rules)

    def test_a_bad_run_is_still_counted_by_the_other_rules(self) -> None:
        """Two facts about one run, not one: somebody disliked it AND it
        failed, and collapsing those would lose the half that names a node."""

        self.seed_three("wf-a")  # wf-a-0 and wf-a-1 are `failed`
        self.rate("wf-a-0", "bad")
        self.rate("wf-a-1", "bad")
        findings = {
            row["rule_id"]: row
            for row in self.ok("/insights?workflow_id=wf-a")["findings"]
        }
        self.assertEqual(findings["failed_run"]["affected_runs"], 2)
        self.assertEqual(findings["rated_bad"]["affected_runs"], 2)

    def test_a_judgement_outranks_a_retry_and_yields_to_a_crash(self) -> None:
        self.seed_three("wf-a")
        self.rate("wf-a-0", "bad")
        self.rate("wf-a-1", "bad")
        for run_id in ("wf-a-0", "wf-a-1"):
            self.seed_frame(
                run_id,
                seq=7,
                kind="guardrail",
                node_id="writer",
                details={"stage": "after", "retry_count": 1},
            )
        order = [row["rule_id"] for row in self.ok("/insights?workflow_id=wf-a")["findings"]]
        self.assertEqual(
            order.index("failed_run") < order.index("rated_bad") < order.index("guardrail_retry"),
            True,
            order,
        )

    def test_non_admin_gets_the_unknown_route_shape(self) -> None:
        response = self.client.get("/api/admin/insights", headers=self.as_alice())
        unknown = self.client.get("/api/admin/not-a-route", headers=self.as_alice())
        self.assertEqual(
            (response.status_code, response.content),
            (unknown.status_code, unknown.content),
        )


if __name__ == "__main__":
    unittest.main()
