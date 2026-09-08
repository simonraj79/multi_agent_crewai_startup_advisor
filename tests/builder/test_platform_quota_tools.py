"""A tool on the PLATFORM key claims before it calls - audit H4, the tool half.

Two places in this package build a research tool that spends the DEPLOYMENT's
Firecrawl account rather than the author's, and both were unmetered:

1. `builder/tools.py::_market_research` with no credential attached. This is
   the one `BUILDER_PLATFORM_FIRECRAWL_DEFAULT` governs - the flag makes
   `research_market_landscape` publishable without a key of one's own, and
   `MarketResearchTool._run` then reads `FIRECRAWL_API_KEY` off the process
   environment.
2. `builder/runtime.py::_tool_instance`, which binds the same class for a
   LIBRARY agent node. That path carries no credential and never could - a
   library agent's `tools` is a list of names with nowhere to put a key - so it
   was unbounded WITHOUT the flag, and the shipped idea-validator template
   reaches it.

What this module pins: one claim per call, a refusal envelope rather than an
exception once the day is spent, no claim at all when the author brought their
own credential, and a refusal rather than a spend outside a run scope. That
last one is the inversion the fix rests on - `None` means "no platform key",
never "unlimited" - because a call nobody can be charged for is a call nobody
can be capped for either.

Nothing here touches the network. `MarketResearchTool._run` is replaced on the
BASE class, so the metered subclass's `super()._run` reaches a canned envelope;
a test that let the real one run would need a key, and a test that needed a key
would be a test that could spend one.
"""

from __future__ import annotations

import json
from typing import Any
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.builder.runtime import _tool_instance
from brief_crew.builder.tools import resolved_tool
from brief_crew.platform_quota import (
    current_platform_quota,
    platform_metered,
    platform_quota_scope,
)
from brief_crew.tools.market_research import MarketResearchTool

MARKET = "research_market_landscape"
GRANTED = json.dumps({"status": "ok", "tool": MARKET, "results": ["real evidence"]})


class CountingClaim:
    """A claim callable that grants `cap` units and then refuses, counting."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.used = 0
        self.providers: list[str] = []

    def __call__(self, provider: str) -> tuple[bool, int]:
        self.providers.append(provider)
        if self.used >= self.cap:
            return False, self.used
        self.used += 1
        return True, self.used


class PlatformToolCase(unittest.TestCase):
    """The shared no-network seam: the base class answers, the wrapper meters."""

    def setUp(self) -> None:
        patcher = patch.object(
            MarketResearchTool, "_run", lambda self, *args, **kwargs: GRANTED
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def platform_tool(self) -> Any:
        return resolved_tool(MARKET, params={}, credential=None)

    def credential_tool(self) -> Any:
        return resolved_tool(MARKET, params={}, credential={"api_key": "fc-not-real"})


class ClaimsOncePerCall(PlatformToolCase):
    def test_the_wrapper_claims_exactly_one_unit_per_call(self) -> None:
        claim = CountingClaim(cap=10)
        tool = self.platform_tool()
        with platform_quota_scope(claim):
            for _ in range(4):
                self.assertEqual(json.loads(tool._run("clinics"))["status"], "ok")
        self.assertEqual(claim.used, 4)
        self.assertEqual(claim.providers, [config.PLATFORM_FIRECRAWL_PROVIDER] * 4)

    def test_the_claim_happens_BEFORE_the_call_it_pays_for(self) -> None:
        """A refusal must not be able to arrive after the key was spent."""

        order: list[str] = []

        def claim(provider: str) -> tuple[bool, int]:
            order.append("claim")
            return True, 1

        def called(self: Any, *args: Any, **kwargs: Any) -> str:
            order.append("call")
            return GRANTED

        with patch.object(MarketResearchTool, "_run", called):
            with platform_quota_scope(claim):
                self.platform_tool()._run("clinics")
        self.assertEqual(order, ["claim", "call"])


class StopsAtTheCap(PlatformToolCase):
    def test_the_call_after_the_cap_returns_a_failed_envelope_and_never_calls(
        self,
    ) -> None:
        claim = CountingClaim(cap=2)
        tool = self.platform_tool()
        reached: list[str] = []

        def counted(self: Any, *args: Any, **kwargs: Any) -> str:
            reached.append("call")
            return GRANTED

        with patch.object(MarketResearchTool, "_run", counted):
            with platform_quota_scope(claim):
                self.assertEqual(json.loads(tool._run("a"))["status"], "ok")
                self.assertEqual(json.loads(tool._run("b"))["status"], "ok")
                spent = json.loads(tool._run("c"))

        # The key was reached twice and not a third time.
        self.assertEqual(len(reached), 2)
        self.assertEqual(spent["status"], "failed")
        self.assertEqual(spent["tool"], MARKET)
        self.assertEqual(spent["query"], "c")
        self.assertEqual(spent["result_count"], 0)
        self.assertEqual(spent["results"], [])

    def test_the_refusal_names_the_figure_the_reset_and_the_way_out(self) -> None:
        claim = CountingClaim(cap=0)
        with platform_quota_scope(claim):
            spent = json.loads(self.platform_tool()._run("clinics"))
        notes = spent["notes"]
        self.assertIn(str(config.BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP), notes)
        self.assertIn("00:00 UTC", notes)
        self.assertIn("credential", notes)
        self.assertIn(config.PLATFORM_FIRECRAWL_PROVIDER, notes)

    def test_a_spent_allowance_never_raises(self) -> None:
        """A quota is not an outage: the branch reports and the run carries on."""

        with platform_quota_scope(CountingClaim(cap=0)):
            try:
                body = self.platform_tool()._run("clinics")
            except Exception as exc:  # pragma: no cover - the assertion is the point
                self.fail(f"a spent allowance raised {type(exc).__name__}: {exc}")
        self.assertEqual(json.loads(body)["status"], "failed")

    def test_the_envelope_carries_every_key_the_repository_shape_declares(self) -> None:
        with platform_quota_scope(CountingClaim(cap=0)):
            spent = json.loads(self.platform_tool()._run("clinics"))
        self.assertEqual(
            list(spent),
            [
                "status",
                "tool",
                "query",
                "retrieved_at",
                "result_count",
                "results",
                "notes",
            ],
        )


class ACredentialIsNeverMetered(PlatformToolCase):
    def test_a_tool_built_with_the_authors_own_key_claims_nothing(self) -> None:
        claim = CountingClaim(cap=10)
        tool = self.credential_tool()
        with platform_quota_scope(claim):
            for _ in range(5):
                self.assertEqual(json.loads(tool._run("clinics"))["status"], "ok")
        self.assertEqual(claim.used, 0, "the author's own key was rationed")
        self.assertEqual(claim.providers, [])

    def test_a_credential_tool_works_with_no_scope_at_all(self) -> None:
        """Their key, their allowance - a CLI run must still be able to use it."""

        self.assertIsNone(current_platform_quota.get())
        self.assertEqual(json.loads(self.credential_tool()._run("clinics"))["status"], "ok")


class OutsideARunScope(PlatformToolCase):
    def test_the_platform_tool_refuses_rather_than_spending_the_key(self) -> None:
        reached: list[str] = []

        def counted(self: Any, *args: Any, **kwargs: Any) -> str:
            reached.append("call")
            return GRANTED

        self.assertIsNone(current_platform_quota.get())
        with patch.object(MarketResearchTool, "_run", counted):
            body = json.loads(self.platform_tool()._run("clinics"))

        self.assertEqual(reached, [], "the platform key was spent outside a run")
        self.assertEqual(body["status"], "failed")
        self.assertIn("signed-in run", body["notes"])

    def test_an_unowned_run_is_the_same_answer_as_no_run(self) -> None:
        """`platform_quota_scope(None)` is what an unowned execution scopes."""

        with platform_quota_scope(None):
            body = json.loads(self.platform_tool()._run("clinics"))
        self.assertEqual(body["status"], "failed")
        self.assertIn("signed-in run", body["notes"])


class TheLibraryAgentBindingIsMeteredToo(PlatformToolCase):
    """`_tool_instance` never carries a credential, so it is always platform."""

    def test_a_library_agents_market_tool_claims_like_a_catalogue_one(self) -> None:
        claim = CountingClaim(cap=1)
        tool = _tool_instance(MARKET)
        with platform_quota_scope(claim):
            self.assertEqual(json.loads(tool._run("clinics"))["status"], "ok")
            self.assertEqual(json.loads(tool._run("clinics"))["status"], "failed")
        self.assertEqual(claim.used, 1)

    def test_the_two_free_library_tools_are_not_metered(self) -> None:
        """HN and GitHub spend no key of this deployment's; do not ration them."""

        claim = CountingClaim(cap=10)
        with platform_quota_scope(claim):
            for name in ("analyze_community_sentiment", "assess_technical_feasibility"):
                self.assertIsNotNone(_tool_instance(name))
        self.assertEqual(claim.used, 0)


class TheWrapperKeepsTheToolsIdentity(PlatformToolCase):
    def test_the_metered_subclass_is_named_after_its_parent(self) -> None:
        """The class name reaches an agent's tool list; keep it honest."""

        tool = self.platform_tool()
        self.assertEqual(type(tool).__name__, "MarketResearchTool")
        self.assertEqual(tool.name, MARKET)
        self.assertIsInstance(tool, MarketResearchTool)

    def test_neither_the_provider_nor_the_account_becomes_a_field(self) -> None:
        """A closure cell and a ContextVar, so no serialiser can reach them."""

        dumped = self.platform_tool().model_dump()
        self.assertNotIn("provider", dumped)
        self.assertNotIn("user_id", dumped)

    def test_the_wrapper_is_generic_over_the_class_it_wraps(self) -> None:
        class Fake:
            name = "fake_tool"

            def _run(self, query: str) -> str:
                return "real"

        metered = platform_metered(Fake, provider="firecrawl")
        with platform_quota_scope(CountingClaim(cap=1)):
            self.assertEqual(metered()._run("x"), "real")
            refused = json.loads(metered()._run("x"))
        self.assertEqual(refused["tool"], "fake_tool")
        self.assertEqual(refused["status"], "failed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
