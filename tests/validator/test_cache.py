from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from crewai.events import ToolUsageFinishedEvent, crewai_event_bus

from brief_crew.schemas import ScopedIdea
from brief_crew.validator_cache import (
    CapturedToolResult,
    capture_tool_results,
    format_cached_evidence,
    index_captured_evidence,
    lookup_branch_cache,
    resolve_namespace,
    tool_results_to_documents,
)


def scope_fixture() -> ScopedIdea:
    return ScopedIdea(
        startup_idea="A scheduling assistant for clinics.",
        category="Clinic scheduling software",
        target_user="Clinic operations managers",
        problem="Manual scheduling creates avoidable administrative work.",
        technology_claim="A constrained assistant can automate scheduling.",
        market_query="clinic scheduling software pricing market",
        community_queries=["clinic scheduling manual workaround"],
        tech_queries=["clinic scheduling assistant"],
        assumptions=[
            "Clinics own the workflow",
            "Scheduling is repetitive",
            "Data is exportable",
        ],
        scoping_gaps=["Willingness to pay is unknown."],
        as_of="2026-08-29",
    )


def cache_hits(now: datetime, *, score: float, age_days: int) -> list[dict[str, object]]:
    return [
        {
            "text": f"Cached passage {position}",
            "url": f"https://example.com/{position}",
            "publisher": "Example",
            "published_date": "2026-08-01",
            "indexed_at": (now - timedelta(days=age_days)).isoformat(),
            "rerank_score": score,
        }
        for position in range(3)
    ]


class ValidatorCacheTests(unittest.TestCase):
    @patch("brief_crew.validator_cache.retrieve")
    def test_market_always_uses_strict_policy_filter_and_namespace(
        self,
        retrieve: MagicMock,
    ) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        retrieve.return_value = cache_hits(now, score=0.35, age_days=30)
        scope = scope_fixture()

        accepted = lookup_branch_cache(
            scope,
            "market",
            "validator-user",
            now=now,
        )

        self.assertEqual(len(accepted), 3)
        retrieve.assert_called_once_with(
            scope.market_query,
            metadata_filter={
                "branch": {"$eq": "market"},
                "category": {"$eq": scope.category},
            },
            namespace="validator-user",
        )

    @patch("brief_crew.validator_cache.retrieve")
    def test_sentiment_never_retrieves_and_feasibility_requires_opt_in(
        self,
        retrieve: MagicMock,
    ) -> None:
        scope = scope_fixture()

        self.assertEqual(
            lookup_branch_cache(scope, "sentiment", "validator-user"), []
        )
        self.assertEqual(
            lookup_branch_cache(
                scope,
                "feasibility",
                "validator-user",
                feasibility_enabled=False,
            ),
            [],
        )
        retrieve.assert_not_called()

    @patch("brief_crew.validator_cache.retrieve")
    def test_feasibility_opt_in_uses_rate_limit_policy(
        self,
        retrieve: MagicMock,
    ) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        retrieve.return_value = cache_hits(now, score=0.40, age_days=90)
        scope = scope_fixture()

        accepted = lookup_branch_cache(
            scope,
            "feasibility",
            "validator-user",
            feasibility_enabled=True,
            now=now,
        )

        self.assertEqual(len(accepted), 3)
        retrieve.assert_called_once_with(
            "\n".join(scope.tech_queries),
            metadata_filter={
                "branch": {"$eq": "feasibility"},
                "category": {"$eq": scope.category},
            },
            namespace="validator-user",
        )

    def test_namespace_is_stable_and_opaque(self) -> None:
        first = resolve_namespace("session-alice@example.com")
        second = resolve_namespace("session-alice@example.com")

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("validator-"))
        self.assertNotIn("alice", first)
        self.assertNotIn("@", first)

    def test_cache_format_is_dated_and_explicitly_supplemental(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        block = format_cached_evidence(
            cache_hits(now, score=0.5, age_days=2),
            retrieved_at=now,
        )

        self.assertIn("SUPPLEMENTAL, NOT A CONCLUSION", block)
        self.assertIn("still call", block)
        self.assertIn("source_date: 2026-08-01", block)
        self.assertIn("indexed_at:", block)

    def test_capture_is_scoped_and_synchronous(self) -> None:
        now = datetime.now(timezone.utc)
        with capture_tool_results("market") as captured:
            crewai_event_bus.emit(
                self,
                ToolUsageFinishedEvent(
                    tool_name="research_market_landscape",
                    tool_args={"query": "clinic scheduling"},
                    started_at=now,
                    finished_at=now,
                    output='{"status": "ok"}',
                ),
            )
            self.assertEqual(len(captured), 1)

        crewai_event_bus.emit(
            self,
            ToolUsageFinishedEvent(
                tool_name="research_market_landscape",
                tool_args={"query": "outside scope"},
                started_at=now,
                finished_at=now,
                output='{"status": "ok"}',
            ),
        )
        self.assertEqual(len(captured), 1)

    def test_tool_results_become_one_document_per_source_url(self) -> None:
        envelope = json.dumps(
            {
                "status": "ok",
                "tool": "analyze_community_sentiment",
                "retrieved_at": "2026-08-29T00:00:00Z",
                "results": [
                    {
                        "classification": "HAS_PROBLEM",
                        "quote": "We do this manually.",
                        "url": "https://news.ycombinator.com/item?id=1",
                        "date": "2026-08-01",
                    },
                    {
                        "classification": "BUILT_WORKAROUND",
                        "quote": "I built a spreadsheet.",
                        "url": "https://news.ycombinator.com/item?id=1",
                        "date": "2026-08-01",
                    },
                ],
            }
        )

        documents = tool_results_to_documents(
            [CapturedToolResult("analyze_community_sentiment", envelope)],
            "sentiment",
        )

        self.assertEqual(len(documents), 1)
        self.assertIn("We do this manually", documents[0]["text"])
        self.assertIn("I built a spreadsheet", documents[0]["text"])
        self.assertEqual(documents[0]["publisher"], "Hacker News")

    @patch("brief_crew.validator_cache.index_documents", return_value=1)
    def test_indexing_uses_only_captured_source_envelopes(
        self,
        index_documents: MagicMock,
    ) -> None:
        scope = scope_fixture()
        envelope = json.dumps(
            {
                "status": "ok",
                "tool": "research_market_landscape",
                "retrieved_at": "2026-08-29T00:00:00Z",
                "results": [
                    {
                        "claim": "A market source exists.",
                        "url": "https://example.com/market",
                        "publisher": "Example",
                        "dated": "2026-08-01",
                        "retrieved_via": "firecrawl",
                    }
                ],
            }
        )

        written = index_captured_evidence(
            [CapturedToolResult("research_market_landscape", envelope)],
            branch="market",
            scope=scope,
            source_run_id="run-123",
            namespace="validator-user",
        )

        self.assertEqual(written, 1)
        kwargs = index_documents.call_args.kwargs
        self.assertEqual(len(kwargs["documents"]), 1)
        self.assertEqual(kwargs["documents"][0]["url"], "https://example.com/market")
        self.assertEqual(kwargs["source_run_id"], "run-123")
        self.assertEqual(kwargs["namespace"], "validator-user")
        self.assertEqual(
            kwargs["metadata"],
            {
                "branch": "market",
                "category": scope.category,
                "idea_hash": unittest.mock.ANY,
            },
        )


if __name__ == "__main__":
    unittest.main()