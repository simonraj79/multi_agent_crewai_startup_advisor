"""The Firecrawl scrape tool, with the result schema it never declared.

``crewai_tools.FirecrawlScrapeWebsiteTool`` returns a ``firecrawl.Document``
and sets no ``result_schema``. CrewAI reads that field in
``crewai.tools.structured_tool._format_tool_output_for_agent``; with it unset
the function falls through to ``str(raw_result)``, so what reaches the
Researcher - and ``main.py``'s capture sink - is a pydantic repr::

    markdown='# Adoption\\n\\nAdoption reached 92%...' html=None raw_html=None
    json=None summary=None metadata=DocumentMetadata(title='...', ...)

One line, roughly sixty unset ``=None`` fields, and the page's own newlines
escaped inside ``markdown='...'``.

Provenance is unaffected - the URL is read from the tool's *input* - but chunk
quality is not. ``indexing.chunk_markdown`` splits on markdown headings and
blank lines, and a repr contains neither, so a whole page arrives as one
oversized block and gets cut on character counts instead. That is the defect:
passages that begin mid-sentence, and headings severed from the text they
introduce.

Declaring ``result_schema`` puts CrewAI's own documented branch back in play -
``result_schema.model_validate(...)`` then ``model_dump_json()`` - so the tool
result is a JSON envelope whose ``markdown`` field holds the page's markdown
verbatim. Nothing here rewrites, summarises or annotates a page: the schema
only selects the two fields worth carrying and drops the unset ones.

Why a subclass rather than ``FirecrawlScrapeWebsiteTool(result_schema=...)`` at
the call site: the schema and the tool have to travel together. A second
construction that forgot the keyword would silently reinstate the repr, and the
symptom - slightly worse retrieval months later - is not one anybody traces
back to a missing argument.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from crewai_tools import FirecrawlScrapeWebsiteTool
from pydantic import BaseModel, Field, field_validator


class ScrapedPage(BaseModel):
    """The part of a Firecrawl ``Document`` worth handing on: body and metadata.

    ``metadata`` stays a free-form mapping on purpose. Its keys are the page's
    own ``<meta>`` tags as Firecrawl found them, which is source data, not
    something this system gets to define a shape for.
    """

    markdown: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("markdown", mode="before")
    @classmethod
    def _body_or_blank(cls, value: Any) -> Any:
        # A page that came back empty says so with an empty body rather than
        # with null, so no reader downstream has to special-case None. It stays
        # empty: an empty scrape must remain visibly empty.
        return "" if value is None else value

    @field_validator("metadata", mode="before")
    @classmethod
    def _drop_unset(cls, value: Any) -> Any:
        # DocumentMetadata declares ~40 optional fields and a real page sets a
        # handful. Carrying the rest as nulls would triple the envelope the
        # Researcher reads and buy nothing.
        if not isinstance(value, Mapping):
            return {}
        return {key: item for key, item in value.items() if item not in (None, "", [], {})}


class ScrapeWebsiteTool(FirecrawlScrapeWebsiteTool):
    """``FirecrawlScrapeWebsiteTool`` that hands on the document, not its repr.

    ``name`` is inherited unchanged, so this is still ``firecrawl_web_scrape_tool``
    once CrewAI sanitises it onto an event - the exact string ``main.py``'s
    capture sink filters on (``main.SCRAPE_TOOL_NAME``). Do not rename it here.
    """

    result_schema: type[BaseModel] | None = ScrapedPage
