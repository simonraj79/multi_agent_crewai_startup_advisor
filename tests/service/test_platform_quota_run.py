"""A real run charges the launching account - audit H4, the seam end to end.

The two halves are proved elsewhere: `tests/service/test_platform_quota.py`
that the counter is atomic, `tests/builder/test_platform_quota_tools.py` that a
platform tool claims before it calls. Neither says the two ever meet. This
module runs the PRODUCTION runner over a compiled graph and asserts that a
`platform_tool_usage` row appears against the person who pressed Launch.

That is the assertion that would have failed had the claim been scoped
anywhere but `credential_scope` - which `BuilderFlowRunner` already enters
around `kickoff` and `resume`, and which CrewAI copies into every worker a
fan-out starts. Wiring the quota into that existing seam rather than adding a
second one is the whole reason this test is short.

**Nothing spends anything and nothing is synthetic about the part under test.**
The crew factory is a test double - `SYNTHETIC=1` installs one exactly like it
and it is what makes a runner test free - but the tool it builds is the real
`resolved_tool(...)` product, metered by the real wrapper, claiming through the
real store. Only `MarketResearchTool._run` is replaced, on the base class, so
the metered subclass's `super()._run` reaches a canned envelope instead of
Firecrawl.
"""

from __future__ import annotations

import json
from typing import Any
import unittest
from unittest.mock import patch

from brief_crew import config
from brief_crew.builder.descriptor import build_builder_workflow
from brief_crew.builder.tools import resolved_tool
from brief_crew.events.adapter import StreamSinkAdapter
from brief_crew.events.buffer import FrameBuffer
from brief_crew.service.builder_runner import BuilderFlowRunner, SyntheticCrewFactories
from brief_crew.service.credentials import platform_quota_claim
from brief_crew.service.persistence import PostgresFlowPersistence
from brief_crew.service.runner import RunExecution
from brief_crew.tools.market_research import MarketResearchTool
from tests.builder.test_compiler import straight_line

MARKET = "research_market_landscape"
PROVIDER = config.PLATFORM_FIRECRAWL_PROVIDER
GRANTED = json.dumps({"status": "ok", "tool": MARKET, "results": ["real evidence"]})


class ResearchingCrew:
    """A crew whose one act is to run the platform research tool, `calls` times.

    Built through `resolved_tool` with `credential=None`, which is what an
    agent node carrying `research_market_landscape` and no key of its own
    compiles to when `BUILDER_PLATFORM_FIRECRAWL_DEFAULT` is on.
    """

    def __init__(self, calls: int, bodies: list[str]) -> None:
        self._calls = calls
        self._bodies = bodies

    def kickoff(self, inputs: Any = None) -> str:
        tool = resolved_tool(MARKET, params={}, credential=None)
        for _ in range(self._calls):
            self._bodies.append(tool._run("clinics scheduling"))
        return json.dumps({"segment": "clinics"})


class ResearchingFactories(SyntheticCrewFactories):
    def __init__(self, calls: int) -> None:
        self.calls = calls
        self.bodies: list[str] = []

    def agent_crew(self, **kwargs: Any) -> ResearchingCrew:
        return ResearchingCrew(self.calls, self.bodies)


class PlatformQuotaThroughARunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = PostgresFlowPersistence("sqlite:///:memory:")
        self.addCleanup(self.store.close)
        patcher = patch.object(
            MarketResearchTool, "_run", lambda self, *args, **kwargs: GRANTED
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.workflow = build_builder_workflow(straight_line())

    def run_graph(self, *, user_id: str | None, calls: int, run_id: str) -> list[str]:
        factories = ResearchingFactories(calls)
        runner = BuilderFlowRunner(self.workflow, crew_factories=factories)
        runner(
            RunExecution(
                run_id=run_id,
                inputs={"idea": "a scheduling assistant for clinics"},
                capture=StreamSinkAdapter(
                    run_id=run_id,
                    buffer=FrameBuffer(),
                    registry=self.workflow.node_registry,
                ),
                flow_id=run_id,
                persistence=self.store,
                user_id=user_id,
            )
        )
        return factories.bodies

    def test_a_run_records_used_rows_against_the_account_that_launched_it(self) -> None:
        bodies = self.run_graph(user_id="alice", calls=3, run_id="run-alice")

        self.assertEqual([json.loads(b)["status"] for b in bodies], ["ok"] * 3)
        self.assertEqual(self.store.platform_quota_used("alice", PROVIDER), 3)
        # Nobody else was charged for it.
        self.assertEqual(self.store.platform_quota_used("bob", PROVIDER), 0)

    def test_a_second_run_by_the_same_account_adds_to_the_same_day(self) -> None:
        self.run_graph(user_id="alice", calls=2, run_id="run-1")
        self.run_graph(user_id="alice", calls=2, run_id="run-2")
        self.assertEqual(self.store.platform_quota_used("alice", PROVIDER), 4)

    def test_two_accounts_have_separate_allowances(self) -> None:
        self.run_graph(user_id="alice", calls=2, run_id="run-alice")
        self.run_graph(user_id="bob", calls=5, run_id="run-bob")
        self.assertEqual(self.store.platform_quota_used("alice", PROVIDER), 2)
        self.assertEqual(self.store.platform_quota_used("bob", PROVIDER), 5)

    def test_a_run_past_the_cap_gets_refusal_envelopes_and_still_completes(self) -> None:
        """The graph finishes; the branch reports what it could not do."""

        with patch.dict(
            config.PLATFORM_TOOL_DAILY_CAPS, {PROVIDER: 2}, clear=False
        ):
            bodies = self.run_graph(user_id="alice", calls=4, run_id="run-alice")

        statuses = [json.loads(body)["status"] for body in bodies]
        self.assertEqual(statuses, ["ok", "ok", "failed", "failed"])
        self.assertEqual(self.store.platform_quota_used("alice", PROVIDER), 2)
        spent = json.loads(bodies[-1])
        self.assertIn("00:00 UTC", spent["notes"])

    def test_an_unowned_run_spends_nothing_and_writes_no_rows(self) -> None:
        """A run nobody signed in for cannot be charged, so it cannot spend."""

        from sqlalchemy import func, select

        from brief_crew.service.persistence import platform_tool_usage

        bodies = self.run_graph(user_id=None, calls=2, run_id="run-anon")

        self.assertEqual([json.loads(b)["status"] for b in bodies], ["failed", "failed"])
        with self.store.connect() as connection:
            rows = connection.execute(
                select(func.count()).select_from(platform_tool_usage)
            ).scalar_one()
        self.assertEqual(int(rows), 0)


class PlatformQuotaClaimTests(unittest.TestCase):
    """The binding `credential_scope` makes, in isolation."""

    def setUp(self) -> None:
        self.store = PostgresFlowPersistence("sqlite:///:memory:")
        self.addCleanup(self.store.close)

    def test_an_owner_and_the_service_store_produce_a_claim(self) -> None:
        claim = platform_quota_claim("alice", self.store)
        self.assertIsNotNone(claim)
        self.assertEqual(claim(PROVIDER), (True, 1))

    def test_no_owner_produces_no_claim(self) -> None:
        self.assertIsNone(platform_quota_claim(None, self.store))
        self.assertIsNone(platform_quota_claim("", self.store))

    def test_a_bare_crewai_persistence_produces_no_claim(self) -> None:
        """No `platform_tool_usage` table there, and no place to keep spending."""

        from crewai.flow.persistence.sqlite import SQLiteFlowPersistence
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            bare = SQLiteFlowPersistence(str(Path(directory) / "flows.db"))
            self.assertIsNone(platform_quota_claim("alice", bare))
        self.assertIsNone(platform_quota_claim("alice", None))

    def test_the_cap_is_read_at_claim_time_not_at_scope_time(self) -> None:
        """Lowering the knob bites the runs already in flight."""

        claim = platform_quota_claim("alice", self.store)
        assert claim is not None
        with patch.dict(config.PLATFORM_TOOL_DAILY_CAPS, {PROVIDER: 0}, clear=False):
            self.assertEqual(claim(PROVIDER), (False, 0))
        self.assertEqual(claim(PROVIDER), (True, 1))

    def test_a_provider_with_no_declared_cap_is_refused(self) -> None:
        """A closed set: adding a platform key without a cap refuses, not grants."""

        claim = platform_quota_claim("alice", self.store)
        assert claim is not None
        self.assertEqual(claim("some-unmetered-provider"), (False, 0))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
