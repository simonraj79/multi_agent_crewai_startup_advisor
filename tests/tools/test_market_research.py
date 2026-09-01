from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from firecrawl.v2.types import Document, DocumentMetadata, SearchData, SearchResultWeb

from brief_crew.config import VALIDATOR_MARKET_SEARCH_LIMIT
from brief_crew.schemas import Evidence, staleness_multiplier
from brief_crew.tools.market_research import MarketResearchTool
from brief_crew.validator_guardrails import median_market_source_age_months


class MarketResearchToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = MarketResearchTool()

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-key"})
    @patch("brief_crew.tools.market_research.Firecrawl")
    def test_returns_attributed_document_and_search_result_urls(self, firecrawl: MagicMock) -> None:
        firecrawl.return_value.search.return_value = SearchData(
            web=[
                Document(
                    markdown="Clinics spend on intake automation.",
                    metadata=DocumentMetadata(
                        source_url="https://example.com/report",
                        og_site_name="Example Research",
                        published_time="2026-08-01T00:00:00Z",
                    ),
                ),
                SearchResultWeb(
                    url="https://vendor.test/pricing",
                    title="Clinic automation pricing",
                    description="Published plans start at $49.",
                ),
                Document(markdown="This row has no attributable URL."),
            ]
        )

        envelope = json.loads(self.tool._run("  clinic intake automation market  "))

        self.assertEqual(envelope["status"], "ok")
        self.assertEqual(envelope["tool"], "research_market_landscape")
        self.assertEqual(envelope["query"], "clinic intake automation market")
        self.assertEqual(envelope["result_count"], 2)
        self.assertEqual(
            [result["url"] for result in envelope["results"]],
            ["https://example.com/report", "https://vendor.test/pricing"],
        )
        self.assertIn("Omitted 1 result(s)", envelope["notes"])
        # The dated page keeps its own date; the undated one is flagged.
        self.assertEqual(envelope["results"][0]["dated"], "2026-08-01T00:00:00Z")
        self.assertIs(envelope["results"][0]["dated_is_retrieval_time"], False)
        self.assertIs(envelope["results"][1]["dated_is_retrieval_time"], True)
        self.assertEqual(envelope["results"][1]["dated"], envelope["retrieved_at"])
        self.assertIn("must not be reported as freshly published", envelope["notes"])

        _, kwargs = firecrawl.return_value.search.call_args
        # Asserted against the constant, not a literal. `limit` is not "how many
        # rows" - `scrape_options` makes `search` scrape every result it
        # returns, so this is the page-fetch budget for the call, at 10-30s
        # each. A literal here would drift from config.py the moment the budget
        # is tuned, and the test would then pin the old cost.
        self.assertEqual(kwargs["limit"], VALIDATOR_MARKET_SEARCH_LIMIT)
        self.assertEqual(kwargs["scrape_options"].formats, ["markdown"])

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-key"})
    @patch("brief_crew.tools.market_research.Firecrawl")
    def test_rate_limit_returns_empty_honest_envelope(self, firecrawl: MagicMock) -> None:
        error = RuntimeError("too many requests")
        error.status_code = 429  # type: ignore[attr-defined]
        firecrawl.return_value.search.side_effect = error

        envelope = json.loads(self.tool._run("clinic intake automation"))

        self.assertEqual(envelope["status"], "rate_limited")
        self.assertEqual(envelope["result_count"], 0)
        self.assertEqual(envelope["results"], [])
        self.assertEqual(
            set(envelope),
            {"status", "tool", "query", "retrieved_at", "result_count", "results", "notes"},
        )
        self.assertIn("rate limit", envelope["notes"].lower())


class UndatedSourceReachesTheConfidenceInputTests(unittest.TestCase):
    """The fallback date must stay distinguishable all the way to confidence.

    `_publication_date` substitutes the retrieval timestamp for a page that
    publishes no date. These tests take the tool's own envelope, parse it into
    the `Evidence` the Market Analyst is required to copy, and hand it to the
    single figure the confidence formula consumes: the median market source age.
    """

    NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)

    def setUp(self) -> None:
        self.tool = MarketResearchTool()

    def _document(self, url: str, published_time: str | None = None) -> Document:
        metadata = DocumentMetadata(source_url=url, og_site_name="Example")
        if published_time is not None:
            metadata.published_time = published_time
        return Document(markdown="Clinics spend on intake automation.", metadata=metadata)

    def _market_sources(self, firecrawl: MagicMock, *documents: Document) -> list[Evidence]:
        firecrawl.return_value.search.return_value = SearchData(web=list(documents))
        envelope = json.loads(self.tool._run("clinic intake automation market"))
        self.assertEqual(envelope["status"], "ok")
        return [Evidence.model_validate(row) for row in envelope["results"]]

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-key"})
    @patch("brief_crew.tools.market_research.Firecrawl")
    def test_mostly_undated_evidence_yields_no_measured_age(self, firecrawl: MagicMock) -> None:
        """Old behaviour: three retrieval-dated rows read as ~0 months, so the
        staleness multiplier was 1.00. Unknown recency is not freshness."""
        sources = self._market_sources(
            firecrawl,
            self._document("https://vendor.test/a"),
            self._document("https://vendor.test/b"),
            self._document("https://analyst.test/c", published_time="2026-08-01T00:00:00Z"),
        )

        self.assertEqual(
            [source.dated_is_retrieval_time for source in sources],
            [True, True, False],
        )
        median = median_market_source_age_months(sources, self.NOW)
        self.assertIsNone(median)
        self.assertEqual(staleness_multiplier(median), 0.70)

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-key"})
    @patch("brief_crew.tools.market_research.Firecrawl")
    def test_a_dated_majority_still_reports_its_real_age(self, firecrawl: MagicMock) -> None:
        sources = self._market_sources(
            firecrawl,
            self._document("https://analyst.test/a", published_time="2026-08-01T00:00:00Z"),
            self._document("https://analyst.test/b", published_time="2026-08-01T00:00:00Z"),
            self._document("https://vendor.test/c"),
        )

        median = median_market_source_age_months(sources, self.NOW)
        self.assertEqual(median, 0.9)
        self.assertEqual(staleness_multiplier(median), 1.00)


if __name__ == "__main__":
    unittest.main()