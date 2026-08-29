from __future__ import annotations

import json
import os
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from crewai.events import ToolUsageFinishedEvent, crewai_event_bus
from crewai.utilities.string_utils import sanitize_tool_name

# The concrete type `FirecrawlScrapeWebsiteTool._run` returns. The whole point
# of `scrape_tool.py` is what CrewAI does with THIS object, so the tests use it
# rather than a stand-in: if firecrawl-py restructures it, this fix needs
# re-checking and an import error is the right way to be told.
from firecrawl.v2.types import Document, DocumentMetadata

from brief_crew.crews.brief_crew.scrape_tool import ScrapedPage, ScrapeWebsiteTool
from brief_crew.indexing import _MAX_CHARS, chunk_markdown, index_documents
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


_PANEL_PATCH = patch(
    "crewai.events.utils.console_formatter.ConsoleFormatter.print_panel",
    lambda *args, **kwargs: None,
)


def setUpModule() -> None:
    """Stop CrewAI's Rich panels from reprinting every fixture page.

    The console formatter is built with ``verbose=True`` process-wide, so every
    emitted tool event echoes its whole output into the suite's log. These
    tests emit multi-kilobyte pages on purpose - that is what chunking needs -
    and the panels bury the actual results.
    """
    _PANEL_PATCH.start()


def tearDownModule() -> None:
    _PANEL_PATCH.stop()


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

    def test_the_requested_url_beats_the_url_the_page_reports(self) -> None:
        # Provenance comes from the tool's INPUT. The envelope now carries a
        # `source_url` of Firecrawl's choosing, and a redirect, a canonical tag
        # or an outright wrong one must not be able to reattribute the page.
        rendered = ScrapeWebsiteTool().format_output_for_agent(
            Document(
                markdown="# Adoption\n\nAdoption reached 92% in 2026.",
                metadata=DocumentMetadata(source_url="https://elsewhere.test/mirror"),
            )
        )
        self.assertIn("elsewhere.test", rendered)

        with _capture_scraped_pages() as pages:
            crewai_event_bus.emit(
                self, scrape_event("https://example.com/stats", rendered)
            )

        self.assertEqual(pages[0]["url"], "https://example.com/stats")

    def test_a_scrape_that_returned_nothing_yields_no_document(self) -> None:
        # Honest degradation. An envelope with no body is a scrape that came
        # back empty; indexing the envelope would file CrewAI's wrapper in the
        # corpus as though it were the page, under a real URL.
        empty = ScrapeWebsiteTool().format_output_for_agent(Document())
        self.assertEqual(json.loads(empty), {"markdown": "", "metadata": {}})

        with _capture_scraped_pages() as pages:
            crewai_event_bus.emit(self, scrape_event("https://example.com/empty", empty))
            crewai_event_bus.emit(self, scrape_event("https://example.com/blank", ""))
            crewai_event_bus.emit(self, scrape_event("https://example.com/none", None))
            crewai_event_bus.emit(
                self,
                scrape_event(
                    "https://example.com/dead", empty, failure={"message": "404"}
                ),
            )
            # No URL to attribute it to, so there is no document to make.
            crewai_event_bus.emit(self, scrape_event("", empty))

        self.assertEqual(pages, [])

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

    @patch("brief_crew.main.index_documents", return_value=2)
    def test_the_narrative_stays_out_even_when_pages_were_captured(
        self, index_documents_mock: MagicMock
    ) -> None:
        # The other half of R-15: with a captured page in hand it would be easy
        # to let the notes ride along as extra context. Nothing the Researcher
        # wrote may reach the corpus, however well sourced it looks.
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
            }
        ]

        flow.index_content()

        documents = index_documents_mock.call_args.kwargs["documents"]
        self.assertEqual(len(documents), 1)
        for phrase in ("Competing views", "Unverified / gaps", "Example Bank disagrees"):
            for document in documents:
                self.assertNotIn(phrase, document["text"])

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


# --------------------------------------------------------------- chunk quality
#
# `crewai_tools.FirecrawlScrapeWebsiteTool` declared no `result_schema`, so
# CrewAI's `_format_tool_output_for_agent` fell through to `str(raw_result)`
# and handed both the Researcher and the capture sink a pydantic repr of the
# `Document`. Provenance was unaffected - the URL comes from the tool's input -
# but a repr has no headings and no blank lines, so a whole page arrived as one
# unstructured block and was cut on character counts. These tests fix the
# boundary behaviour in place.

HEADING_RE = re.compile(r"^#{1,6}\s")

PAGE_MARKDOWN = "\n\n".join(
    (
        "# Cashless adoption",
        "Adoption climbed steadily through the year. " * 30,
        "## Findings",
        "The regulator reported a 92 percent share. " * 30,
        "## Competing readings",
        "One bank argues the figure double counts wallets. " * 30,
    )
).strip()


def _headings_with_their_first_sentence(page: str) -> list[tuple[str, str]]:
    """Each heading line paired with the first sentence of the text beneath it."""
    pairs: list[tuple[str, str]] = []
    lines = page.splitlines()
    for position, line in enumerate(lines):
        if not HEADING_RE.match(line):
            continue
        beneath = next(
            (later for later in lines[position + 1 :] if later.strip()), ""
        )
        pairs.append((line.strip(), beneath.strip().split(".")[0]))
    return pairs


class ChunkStructureTests(unittest.TestCase):
    """A retrieved passage has to be readable on its own."""

    def test_a_heading_is_never_severed_from_the_text_beneath_it(self) -> None:
        # Sized so the lead paragraph plus the next heading still fits in one
        # chunk but the heading's body does not - the exact shape that used to
        # close a chunk on `## Findings` and open the next one on its text,
        # leaving the title in a vector that answers nothing.
        heading = "## Findings"
        sentence = "Adoption climbed steadily through the year. "
        lead = (sentence * (1 + _MAX_CHARS // len(sentence)))[
            : _MAX_CHARS - len(heading) - 8
        ]
        lead = lead[: lead.rfind(" ")]
        body = ("The regulator reported a 92 percent share. " * 30).strip()
        page = f"{lead}\n\n{heading}\n\n{body}"

        chunks = chunk_markdown(page)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            last_line = chunk.rstrip().splitlines()[-1]
            self.assertIsNone(
                HEADING_RE.match(last_line),
                f"chunk ends on a bare heading: {last_line!r}",
            )
        holding = [chunk for chunk in chunks if heading in chunk]
        self.assertTrue(holding, "the heading vanished")
        for chunk in holding:
            self.assertIn("The regulator reported a 92 percent share", chunk)

    def test_every_heading_travels_with_its_own_first_sentence(self) -> None:
        chunks = chunk_markdown(PAGE_MARKDOWN)
        self.assertGreater(len(chunks), 1)
        for heading, first_sentence in _headings_with_their_first_sentence(
            PAGE_MARKDOWN
        ):
            with self.subTest(heading=heading):
                self.assertTrue(
                    any(
                        heading in chunk and first_sentence in chunk
                        for chunk in chunks
                    ),
                    f"{heading!r} was separated from {first_sentence!r}",
                )

    def test_no_chunk_begins_or_ends_part_way_through_a_word(self) -> None:
        # The overlap used to be a blind `chunk[-_OVERLAP_CHARS:]` slice and an
        # oversized block was cut at exactly `_MAX_CHARS`, so a retrieved
        # passage could open mid-word. Every boundary now lands on a paragraph,
        # a sentence or at worst a word break.
        words = set(PAGE_MARKDOWN.split())
        for chunk in chunk_markdown(PAGE_MARKDOWN):
            tokens = chunk.split()
            self.assertIn(tokens[0], words)
            self.assertIn(tokens[-1], words)

    def test_a_block_with_no_boundary_at_all_still_terminates(self) -> None:
        # A minified page has nowhere better to cut than the character limit.
        # It must still produce chunks and must not loop.
        chunks = chunk_markdown("x" * (_MAX_CHARS * 3))
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks).count("x"), _MAX_CHARS * 3)

    def test_empty_and_whitespace_only_text_index_nothing(self) -> None:
        for value in ("", "   ", "\n\n \n"):
            with self.subTest(value=value):
                self.assertEqual(chunk_markdown(value), [])

    def test_the_pydantic_repr_is_what_it_used_to_chunk(self) -> None:
        # The defect, held still: `str(Document)` has no newline anywhere, so
        # `chunk_markdown` sees one block, cuts it on a character count, and
        # files CrewAI's own plumbing in the corpus as though it were the page.
        rendering = str(
            Document(
                markdown=PAGE_MARKDOWN,
                metadata=DocumentMetadata(source_url="https://example.com/stats"),
            )
        )
        self.assertNotIn("\n", rendering)
        self.assertIn("\\n", rendering)

        repr_chunks = chunk_markdown(rendering)
        self.assertGreater(len(repr_chunks), 1)
        self.assertTrue(
            any("metadata=DocumentMetadata(" in chunk for chunk in repr_chunks)
        )
        for heading, _ in _headings_with_their_first_sentence(PAGE_MARKDOWN):
            self.assertFalse(
                any(chunk.lstrip().startswith(heading) for chunk in repr_chunks),
                "a repr cannot chunk on headings - that is the whole defect",
            )


class ScrapeToolResultTests(unittest.TestCase):
    """The fix at the source: the tool declares the schema it never had."""

    def test_the_tool_declares_a_result_schema_and_keeps_its_event_name(self) -> None:
        tool = ScrapeWebsiteTool()
        self.assertIs(tool.result_schema, ScrapedPage)
        # The sink filters on this exact string. Renaming the tool in the
        # subclass would silently stop every capture without failing anything.
        self.assertEqual(sanitize_tool_name(tool.name), SCRAPE_TOOL_NAME)
        # And CrewAI carries the schema onto the tool it actually invokes.
        self.assertIs(tool.to_structured_tool().result_schema, ScrapedPage)

    def test_the_stock_tool_still_declares_nothing(self) -> None:
        # If crewai_tools ever ships a result_schema of its own, this subclass
        # should be reconsidered rather than left to shadow it.
        from crewai_tools import FirecrawlScrapeWebsiteTool

        self.assertIsNone(FirecrawlScrapeWebsiteTool().result_schema)

    def test_a_page_reaches_the_capture_sink_as_markdown(self) -> None:
        document = Document(
            markdown=PAGE_MARKDOWN,
            metadata=DocumentMetadata(
                og_site_name="Example Statistics Office",
                published_time="2026-07-01T00:00:00Z",
                source_url="https://example.com/stats",
            ),
        )
        rendered = ScrapeWebsiteTool().format_output_for_agent(document)

        with _capture_scraped_pages() as pages:
            crewai_event_bus.emit(
                self, scrape_event("https://example.com/stats", rendered)
            )

        self.assertEqual(len(pages), 1)
        # Markdown, byte for byte - not a repr, and nothing a model wrote.
        self.assertEqual(pages[0]["text"], PAGE_MARKDOWN)
        self.assertNotIn("markdown='", pages[0]["text"])
        self.assertNotIn("DocumentMetadata(", pages[0]["text"])
        self.assertNotIn("\\n", pages[0]["text"])
        # The page's own meta tags now survive the hop, so the corpus can carry
        # a real publisher and a real publication date instead of a hostname.
        self.assertEqual(pages[0]["publisher"], "Example Statistics Office")
        self.assertEqual(pages[0]["published_date"], "2026-07-01T00:00:00Z")

    def test_the_envelope_carries_only_the_metadata_the_page_actually_set(
        self,
    ) -> None:
        # DocumentMetadata declares ~40 optional fields. Shipping the unset
        # ones as nulls would bloat what the Researcher reads for nothing.
        rendered = ScrapeWebsiteTool().format_output_for_agent(
            Document(markdown="# T\n\nBody.", metadata=DocumentMetadata(title="T"))
        )
        self.assertEqual(
            json.loads(rendered), {"markdown": "# T\n\nBody.", "metadata": {"title": "T"}}
        )

    def test_a_tool_format_reminder_stapled_to_the_result_is_ignored(self) -> None:
        # `ToolUsage._format_result` appends the tool-format block to every
        # third tool result. The envelope is still readable; the tail is not
        # part of the page and must not be indexed as one.
        rendered = ScrapeWebsiteTool().format_output_for_agent(
            Document(markdown=PAGE_MARKDOWN)
        )
        with _capture_scraped_pages() as pages:
            crewai_event_bus.emit(
                self,
                scrape_event(
                    "https://example.com/stats",
                    f"{rendered}\n\nTool Name: firecrawl_web_scrape_tool\nUse this format",
                ),
            )
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["text"], PAGE_MARKDOWN)


class CapturedPageIndexingTests(unittest.TestCase):
    """The whole path: a scraped page becomes structurally chunked vectors."""

    @patch.dict(os.environ, {"PINECONE_API_KEY": "test-key"})
    @patch("pinecone.Pinecone")
    @patch(
        "brief_crew.indexing.embed_documents",
        side_effect=lambda chunks: [[0.1, 0.2] for _ in chunks],
    )
    def test_a_captured_page_is_indexed_as_structural_chunks(
        self, embed_documents: MagicMock, pinecone: MagicMock
    ) -> None:
        document = Document(
            markdown=PAGE_MARKDOWN,
            metadata=DocumentMetadata(
                og_site_name="Example Statistics Office",
                published_time="2026-07-01T00:00:00Z",
            ),
        )
        rendered = ScrapeWebsiteTool().format_output_for_agent(document)

        flow = BriefFlow()
        flow.state.topic = "cashless payments in Singapore"
        with _capture_scraped_pages() as pages:
            crewai_event_bus.emit(
                self, scrape_event("https://example.com/stats", rendered)
            )
        flow.state.scraped_sources = pages
        flow.index_content()

        vectors = pinecone.return_value.Index.return_value.upsert.call_args.kwargs[
            "vectors"
        ]
        self.assertGreater(len(vectors), 1)
        words = set(PAGE_MARKDOWN.split())
        for vector in vectors:
            chunk = vector["metadata"]["text"]
            self.assertEqual(vector["metadata"]["url"], "https://example.com/stats")
            self.assertEqual(
                vector["metadata"]["publisher"], "Example Statistics Office"
            )
            self.assertNotIn("DocumentMetadata(", chunk)
            self.assertIn(chunk.split()[0], words)
            self.assertIsNone(HEADING_RE.match(chunk.rstrip().splitlines()[-1]))


if __name__ == "__main__":
    unittest.main()