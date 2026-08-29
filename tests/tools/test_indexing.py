from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from crewai.events import ToolUsageFinishedEvent, crewai_event_bus

from brief_crew.indexing import index_documents
from brief_crew.main import (
    SCRAPE_TOOL_NAME,
    BriefFlow,
    _capture_scraped_pages,
)
from brief_crew.schemas import ScopedIdea, ValidationReport, Verdict

# What the Track B Researcher actually hands back as `research_notes`: its own
# writing. The claims are reworded, the selection is its judgement, and the
# last two sections are entirely its own. Splitting this by URL would file an
# agent's sentence in the corpus as a publisher's evidence - PRD R-15.
RESEARCH_NOTES = """## Verified findings
1. Adoption reached 92% in 2026.
   Example Statistics Office, 2026-07-01, https://example.com/stats

## Competing views
Example Bank disagrees, arguing the figure double-counts wallets.

## Unverified / gaps
Could not confirm the over-60 breakdown; the regulator page 404s.

## Sources consulted
- https://example.com/stats
"""


def scrape_event(
    url: str,
    output: object,
    *,
    tool_name: str = SCRAPE_TOOL_NAME,
    failure: object = None,
) -> ToolUsageFinishedEvent:
    now = datetime.now(timezone.utc)
    return ToolUsageFinishedEvent(
        tool_name=tool_name,
        tool_args={"url": url},
        started_at=now,
        finished_at=now,
        output=output,
        failure=failure,
    )


class IndexingBoundaryTests(unittest.TestCase):
    @patch.dict(os.environ, {"PINECONE_API_KEY": "test-key"})
    @patch("brief_crew.indexing.embed_documents", return_value=[[0.1, 0.2]])
    @patch("pinecone.Pinecone")
    def test_adds_shared_and_per_source_metadata(
        self,
        pinecone: MagicMock,
        embed_documents: MagicMock,
    ) -> None:
        written = index_documents(
            documents=[
                {
                    "text": "A directly retrieved market claim.",
                    "url": "https://example.com/source",
                    "publisher": "Example Research",
                    "published_date": "2026-08-01",
                    "metadata": {
                        "retrieved_at": "2026-08-29T00:00:00Z",
                        "source_payload": '{"claim": "retrieved"}',
                    },
                }
            ],
            topic="Clinic scheduling software",
            source_run_id="run-123",
            namespace="validator-test",
            metadata={
                "branch": "market",
                "category": "Clinic scheduling software",
                "idea_hash": "idea-456",
            },
        )

        self.assertEqual(written, 1)
        embed_documents.assert_called_once_with(
            ["A directly retrieved market claim."]
        )
        upsert = pinecone.return_value.Index.return_value.upsert
        vectors = upsert.call_args.kwargs["vectors"]
        self.assertEqual(upsert.call_args.kwargs["namespace"], "validator-test")
        self.assertEqual(vectors[0]["metadata"]["branch"], "market")
        self.assertEqual(
            vectors[0]["metadata"]["category"], "Clinic scheduling software"
        )
        self.assertEqual(vectors[0]["metadata"]["idea_hash"], "idea-456")
        self.assertEqual(vectors[0]["metadata"]["source_run_id"], "run-123")
        self.assertEqual(
            vectors[0]["metadata"]["retrieved_at"], "2026-08-29T00:00:00Z"
        )

    @patch("brief_crew.indexing.embed_documents")
    def test_rejects_generated_models_and_unsupported_objects_before_embedding(
        self,
        embed_documents: MagicMock,
    ) -> None:
        unsupported = (
            ScopedIdea.model_construct(),
            Verdict.model_construct(),
            ValidationReport.model_construct(),
            object(),
        )

        for value in unsupported:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(TypeError):
                    index_documents(  # type: ignore[arg-type]
                        value,
                        topic="test",
                        source_run_id="run",
                    )

        with self.assertRaises(TypeError):
            index_documents(  # type: ignore[list-item]
                [ScopedIdea.model_construct()],
                topic="test",
                source_run_id="run",
            )
        embed_documents.assert_not_called()


class _EmittingCrew:
    """A crew double that emits tool events the way a real scrape would."""

    def __init__(self, events: list[ToolUsageFinishedEvent]) -> None:
        self.events = events

    def kickoff(self, inputs: dict[str, object]) -> MagicMock:
        for event in self.events:
            crewai_event_bus.emit(self, event)
        result = MagicMock()
        result.tasks_output = [MagicMock(raw=RESEARCH_NOTES)]
        result.raw = "# Brief\n\nBody.\n"
        result.token_usage = None
        return result


class BriefCrewProvenanceTests(unittest.TestCase):
    """06-retrieval-layer.md: index the pages, with the URL that produced them.

    Before this, `index_content` wrote the Researcher's notes as ONE document
    with `url=""`, so a later cache hit rendered `url: unknown` over passages
    full of real URLs and `run_sources.from_cache` had nothing to record.
    """

    def test_scraped_pages_are_captured_with_the_url_that_produced_them(self) -> None:
        structured = {
            "markdown": "# Adoption\n\nAdoption reached 92% in 2026.",
            "metadata": {
                "og_site_name": "Example Statistics Office",
                "published_time": "2026-07-01T00:00:00Z",
            },
        }
        with _capture_scraped_pages() as pages:
            crewai_event_bus.emit(
                self, scrape_event("https://example.com/stats", json.dumps(structured))
            )
            # CrewAI stringifies a Firecrawl Document before it reaches an
            # event, so the unparseable case must still index, with the tool's
            # own rendering as the body and the requested URL as provenance.
            crewai_event_bus.emit(
                self,
                scrape_event(
                    "https://example.com/bank",
                    "markdown='Example Bank disagrees.' metadata=DocumentMetadata(...)",
                ),
            )
            # Same page twice is one source document.
            crewai_event_bus.emit(
                self, scrape_event("https://example.com/stats", json.dumps(structured))
            )
            # A different tool, a failed call, and a URL-less call are not evidence.
            crewai_event_bus.emit(
                self,
                scrape_event(
                    "https://example.com/search",
                    "results",
                    tool_name="firecrawl_web_search_tool",
                ),
            )
            crewai_event_bus.emit(
                self,
                scrape_event(
                    "https://example.com/dead", "boom", failure={"message": "404"}
                ),
            )
            crewai_event_bus.emit(self, scrape_event("not-a-url", "body"))

        self.assertEqual([page["url"] for page in pages], [
            "https://example.com/stats",
            "https://example.com/bank",
        ])
        self.assertEqual(pages[0]["publisher"], "Example Statistics Office")
        self.assertEqual(pages[0]["published_date"], "2026-07-01T00:00:00Z")
        self.assertIn("Adoption reached 92%", pages[0]["text"])
        # An unknown publication date stays unknown rather than borrowing
        # today's, so an undated page can never look freshly published.
        self.assertEqual(pages[1]["publisher"], "example.com")
        self.assertEqual(pages[1]["published_date"], "")
        self.assertEqual(pages[1]["metadata"]["retrieved_via"], SCRAPE_TOOL_NAME)

    def test_capture_stops_at_the_end_of_the_block(self) -> None:
        with _capture_scraped_pages() as pages:
            crewai_event_bus.emit(self, scrape_event("https://example.com/a", "body"))
        crewai_event_bus.emit(self, scrape_event("https://example.com/b", "body"))
        self.assertEqual(len(pages), 1)

    def test_scrape_web_records_pages_alongside_the_notes(self) -> None:
        flow = BriefFlow()
        flow.state.topic = "cashless payments in Singapore"
        crew = _EmittingCrew(
            [scrape_event("https://example.com/stats", "Adoption reached 92%.")]
        )
        with patch("brief_crew.main.BriefCrew") as brief_crew:
            brief_crew.return_value.crew.return_value = crew
            flow.scrape_web()

        brief_crew.assert_called_once_with(track="B")
        self.assertEqual(flow.state.research_notes, RESEARCH_NOTES)
        self.assertEqual(len(flow.state.scraped_sources), 1)
        self.assertEqual(
            flow.state.scraped_sources[0]["url"], "https://example.com/stats"
        )

    @patch("brief_crew.main.index_documents", return_value=4)
    def test_index_content_writes_one_document_per_source_page(
        self, index_documents_mock: MagicMock
    ) -> None:
        flow = BriefFlow()
        flow.state.topic = "cashless payments in Singapore"
        flow.state.research_notes = RESEARCH_NOTES
        flow.state.scraped_sources = [
            {
                "text": "Adoption reached 92% in 2026.",
                "url": "https://example.com/stats",
                "publisher": "Example Statistics Office",
                "published_date": "2026-07-01T00:00:00Z",
                "metadata": {"retrieved_via": SCRAPE_TOOL_NAME},
            },
            {
                "text": "Example Bank disagrees.",
                "url": "https://example.com/bank",
                "publisher": "example.com",
                "published_date": "",
                "metadata": {"retrieved_via": SCRAPE_TOOL_NAME},
            },
        ]

        flow.index_content()

        documents = index_documents_mock.call_args.kwargs["documents"]
        self.assertEqual(len(documents), 2)
        self.assertEqual(
            {document["url"] for document in documents},
            {"https://example.com/stats", "https://example.com/bank"},
        )
        for document in documents:
            self.assertTrue(document["url"].startswith("https://"))
            self.assertTrue(document["publisher"])
        self.assertEqual(
            index_documents_mock.call_args.kwargs["source_run_id"], flow.state.run_id
        )

    @patch("brief_crew.main.index_documents")
    def test_the_researcher_narrative_is_never_indexed(
        self, index_documents_mock: MagicMock
    ) -> None:
        # PRD R-15. The notes are a conclusion: an agent's selection and
        # rewording, plus sections it authored outright. With no captured page
        # there is nothing indexable, and splitting the prose by the URLs it
        # mentions is exactly the circular-evidence failure that is forbidden.
        flow = BriefFlow()
        flow.state.topic = "cashless payments in Singapore"
        flow.state.research_notes = RESEARCH_NOTES
        flow.state.scraped_sources = []

        flow.index_content()

        index_documents_mock.assert_not_called()

    @patch("brief_crew.main.index_documents", side_effect=RuntimeError("pinecone down"))
    def test_a_failed_write_back_never_fails_the_run(
        self, index_documents_mock: MagicMock
    ) -> None:
        flow = BriefFlow()
        flow.state.scraped_sources = [
            {"text": "body", "url": "https://example.com/a", "publisher": "example.com"}
        ]
        flow.index_content()
        index_documents_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()