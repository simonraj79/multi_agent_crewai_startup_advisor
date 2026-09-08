"""The seven plain constants, and `/health` calling rather than restating (2, 13).

**Criterion 2** - seven constants with **no env override**. The distinction is
not cosmetic: `ADMIN_EMAILS` and `LANGFUSE_PROJECT_ID` are knobs a deployment
sets and are counted by `docs/tech-stack.md` section 6's scan; these seven are
bounds on a read, and a bound somebody can widen from a shell is a bound that
is not there. The assertion is that the canonical scan does **not** find them.

**Criterion 13** - `/api/admin/health` CALLS `health_payload` and
`exporter_state`; it does not restate either. The proof is that its
`observability` block equals `/readyz`'s exactly, on the same process, at the
same moment. A copy would agree on the day it was written and drift on the day
somebody added a key to one of them.
"""

from __future__ import annotations

import pathlib
import re
import unittest
from unittest.mock import patch

from brief_crew import config
from tests.service.admin_fixtures import ALICE, AdminCase

#: The canonical scan from `docs/tech-stack.md` section 1 - MULTILINE, never
#: line-anchored, because a wrapped `os.getenv(` hid four knobs once and that
#: is gotchas 6.
ENV_SCAN = re.compile(
    r"(?:os\.getenv|os\.environ\.get|_env_[a-z_]+)\(\s*\"([A-Z_][A-Z0-9_]*)\"", re.S
)

PLAIN_CONSTANTS = (
    "ADMIN_DEFAULT_WINDOW_DAYS",
    "ADMIN_MAX_WINDOW_DAYS",
    "ADMIN_MAX_SCAN_ROWS",
    "ADMIN_PAGE_LIMIT_MAX",
    "ADMIN_PROVIDER_CACHE_SECONDS",
    "ADMIN_PROVIDER_TIMEOUT_SECONDS",
    "LANGFUSE_BILLED_PAGE_LIMIT",
)


class PlainConstantTests(unittest.TestCase):
    def test_all_seven_exist_with_the_documented_defaults(self) -> None:
        self.assertEqual(config.ADMIN_DEFAULT_WINDOW_DAYS, 30)
        self.assertEqual(config.ADMIN_MAX_WINDOW_DAYS, 365)
        self.assertEqual(config.ADMIN_MAX_SCAN_ROWS, 5000)
        self.assertEqual(config.ADMIN_PAGE_LIMIT_MAX, 200)
        self.assertEqual(config.ADMIN_PROVIDER_CACHE_SECONDS, 60.0)
        self.assertEqual(config.ADMIN_PROVIDER_TIMEOUT_SECONDS, 5.0)
        self.assertEqual(config.LANGFUSE_BILLED_PAGE_LIMIT, 5)

    def test_none_of_the_seven_is_an_environment_knob(self) -> None:
        """A bound somebody can widen from a shell is not a bound.

        Run against the canonical scan rather than by reading the source, so
        the answer is the same one `tests/test_env_knob_doc.py` and
        `docs/tech-stack.md` section 6 get.
        """

        root = pathlib.Path(__file__).resolve().parents[2]
        found: set[str] = set()
        for name in ("src/brief_crew/config.py", "src/brief_crew/service/app.py"):
            found |= set(ENV_SCAN.findall((root / name).read_text(encoding="utf-8")))
        for constant in PLAIN_CONSTANTS:
            with self.subTest(constant=constant):
                self.assertNotIn(constant, found)

    def test_the_two_that_ARE_knobs_are_in_the_scan(self) -> None:
        """The control: without it, the assertion above would pass over a
        scan that found nothing at all."""

        root = pathlib.Path(__file__).resolve().parents[2]
        found = set(
            ENV_SCAN.findall(
                (root / "src/brief_crew/config.py").read_text(encoding="utf-8")
            )
        )
        self.assertIn("ADMIN_EMAILS", found)
        self.assertIn("LANGFUSE_PROJECT_ID", found)

    def test_the_three_probe_urls_are_constants_and_not_knobs(self) -> None:
        """`OPENROUTER_GENERATION_URL`'s precedent: the probe module names no
        URL of its own, so there is one place to look and no way to point a
        probe somewhere else from a shell."""

        self.assertEqual(
            config.OPENROUTER_CREDITS_URL, "https://openrouter.ai/api/v1/credits"
        )
        self.assertEqual(config.OPENROUTER_KEY_URL, "https://openrouter.ai/api/v1/key")
        self.assertEqual(
            config.OPENROUTER_KEY_URL_FALLBACK, "https://openrouter.ai/api/v1/auth/key"
        )
        self.assertEqual(
            config.FIRECRAWL_CREDIT_USAGE_URL,
            "https://api.firecrawl.dev/v2/team/credit-usage",
        )

    def test_the_vault_probe_url_is_NOT_changed(self) -> None:
        """Plan 17 section 4A says so in capitals.

        Whether `/api/v1/key` and `/api/v1/auth/key` are aliases is
        undocumented, and the vault probe has worked on the second for
        months. `providers.py` retries; `credentials.py` is left alone.
        """

        self.assertEqual(
            config.OPENROUTER_KEY_PROBE_URL, "https://openrouter.ai/api/v1/auth/key"
        )


class HealthCallsRatherThanRestatesTests(AdminCase):
    def test_the_observability_block_equals_readyz_exactly(self) -> None:
        """Criterion 13, and the only construction under which it cannot drift."""

        readyz = self.client.get("/readyz").json()
        health = self.ok("/health")
        self.assertEqual(health["readyz"]["observability"], readyz["observability"])
        self.assertEqual(health["readyz"]["dependencies"], readyz["dependencies"])
        self.assertEqual(health["readyz"]["status"], readyz["status"])
        self.assertEqual(set(health["readyz"]), set(readyz))

    def test_it_calls_health_payload_rather_than_building_its_own(self) -> None:
        """Patch what `/readyz` calls and BOTH move - which a copy would not."""

        with patch.object(
            self.app.state.run_registry,
            "dependency_status",
            return_value={"invented": {"status": "not_configured"}},
        ):
            readyz = self.client.get("/readyz").json()
            health = self.ok("/health")
        self.assertEqual(health["readyz"]["dependencies"], readyz["dependencies"])
        self.assertIn("invented", health["readyz"]["dependencies"])

    def test_the_integrity_totals_come_from_the_runs_table(self) -> None:
        self.seed_run("r-1", cost="0.0100")
        self.store.update_run_status(
            "r-1", "completed", dropped_frames=3, frame_gaps=1, emit_errors=2
        )
        body = self.ok("/health")
        self.assertEqual(body["integrity"]["dropped"], 3)
        self.assertEqual(body["integrity"]["gaps"], 1)
        self.assertEqual(body["integrity"]["emit_errors"], 2)
        # The figure a SUM cannot give: one run that dropped 400 frames and
        # 400 runs that dropped one each are the same total and completely
        # different problems.
        self.assertEqual(body["integrity"]["runs_with_drop"], 1)

    def test_the_ceilings_are_the_live_constants(self) -> None:
        with patch.object(config, "MAX_RUN_COST_USD", 7.5), patch.object(
            config, "USER_SPEND_CAP_USD", 2.0
        ), patch.object(config, "BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP", 42):
            body = self.ok("/health")
        self.assertEqual(
            body["ceilings"],
            {"run_usd": 7.5, "account_usd": 2.0, "margin": 1.25, "firecrawl_daily": 42},
        )

    def test_it_says_what_it_is_blind_to_in_words(self) -> None:
        """Plan 17 risk 14: **do not let a blank tile imply zero.**

        None of these is recorded by either server, so a zero on screen would
        be the console reporting a measurement it never made.
        """

        body = self.ok("/health")
        blind = " ".join(body["blind_to"]).lower()
        for subject in ("sign-in", "page view", "latency", "cli run", "firecrawl"):
            with self.subTest(subject=subject):
                self.assertIn(subject, blind)

    def test_orphans_counts_stale_runs(self) -> None:
        body = self.ok("/health")
        self.assertEqual(body["orphans"], 0)
        self.seed_run("r-stuck", status="running")
        self.assertEqual(self.ok("/health")["orphans"], 1)

    def test_retention_is_reported_because_raising_it_destroys_this_console(self) -> None:
        """Plan 17 risk 4: a purge cascades to `run_frames`,
        `run_node_metrics` and `run_gates`, so verdicts, gate latency AND the
        lifetime spend the cap is computed from all go - silently resetting a
        cap."""

        self.assertEqual(self.ok("/health")["retention_days"], 0)
        with patch.object(config, "VALIDATOR_RUN_RETENTION_DAYS", 30):
            self.assertEqual(self.ok("/health")["retention_days"], 30)

    def test_the_shape_is_section_3s(self) -> None:
        self.assertEqual(
            set(self.ok("/health")),
            {"readyz", "integrity", "orphans", "retention_days", "ceilings", "blind_to"},
        )


class ProvidersRouteTests(AdminCase):
    def test_the_langfuse_entry_is_local_and_makes_no_call(self) -> None:
        """`exporter_state` plus the project id. No outbound request at all."""

        body = self.ok("/providers")
        self.assertEqual(
            set(body["langfuse"]),
            {"available", "reason", "exporter", "environment", "project_configured"},
        )
        self.assertFalse(body["langfuse"]["project_configured"])
        self.assertEqual(body["langfuse"]["exporter"], "disabled")

    def test_an_unconfigured_deployment_answers_unavailable_not_500(self) -> None:
        body = self.ok("/providers")
        self.assertFalse(body["openrouter"]["available"])
        self.assertIn("OPENROUTER", body["openrouter"]["reason"])
        self.assertFalse(body["firecrawl"]["available"])
        self.assertIn("FIRECRAWL_API_KEY", body["firecrawl"]["reason"])

    def test_the_shape_is_section_3s(self) -> None:
        body = self.ok("/providers")
        self.assertEqual(set(body), {"openrouter", "firecrawl", "langfuse"})
        self.assertEqual(
            set(body["openrouter"]),
            {
                "available",
                "reason",
                "source",
                "total_credits",
                "total_usage",
                "remaining_usd",
                "usage",
                "limit",
                "limit_remaining",
                "is_free_tier",
                "label",
                "checked_at",
                "age_seconds",
            },
        )
        self.assertEqual(
            set(body["firecrawl"]),
            {
                "available",
                "reason",
                "remaining_credits",
                "plan_credits",
                "billing_period_start",
                "billing_period_end",
                "checked_at",
                "age_seconds",
            },
        )


class UsersDetailShapeTests(AdminCase):
    def test_the_detail_is_the_row_plus_three(self) -> None:
        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        self.seed_gate("r-1", decision="approve", seconds=192)
        row = self.ok("/users")["rows"][0]
        detail = self.ok(f"/users/{ALICE.id}")
        self.assertEqual(set(detail) - set(row), {"gates", "recent_runs", "langfuse"})
        self.assertEqual(detail["gates"], {"answered": 1, "expired": 0, "median_seconds": 192.0})
        self.assertEqual(len(detail["recent_runs"]), 1)
        self.assertEqual(detail["langfuse"], {"user_url": None})

    def test_the_unowned_bucket_is_reachable_by_its_key(self) -> None:
        """`__unowned__` maps to `user_id IS NULL` - the whole reason the key
        exists, because pre-auth runs are real spend."""

        self.seed_run("r-nobody", user_id=None, cost="0.0300")
        detail = self.ok("/users/__unowned__")
        self.assertEqual(detail["user_id"], "__unowned__")
        self.assertEqual(detail["spent_usd"], 0.03)
        self.assertIsNone(detail["cap_usd"])
        self.assertFalse(detail["exempt"])

    def test_committed_travels_with_its_own_volatility_flag(self) -> None:
        """Plan 17 risk 5: `committed` is memory-only and lost on a restart,
        so it is never folded into a single headline figure."""

        self.seed_run("r-1", user_id=ALICE.id, cost="0.0500")
        row = self.ok("/users")["rows"][0]
        self.assertTrue(row["committed_is_volatile"])
        self.assertIn("committed_usd", row)
        self.assertNotEqual(row["spent_usd"], row["committed_usd"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
