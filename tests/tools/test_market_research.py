from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from firecrawl.v2.types import Document, DocumentMetadata, SearchData, SearchResultWeb

from brief_crew.tools.market_research import MarketResearchTool


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

        _, kwargs = firecrawl.return_value.search.call_args
        self.assertEqual(kwargs["limit"], 5)
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
        self.assertIn("rate limit", envelope["notes"].lower())


if __name__ == "__main__":
    unittest.main()