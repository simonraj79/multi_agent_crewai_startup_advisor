"""Firecrawl market evidence for the startup validator."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Type
from urllib.parse import urlparse

import requests
from crewai.tools import BaseTool, EnvVar
from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions
from pydantic import BaseModel, Field

from brief_crew.config import (
    VALIDATOR_FIRECRAWL_MAX_AGE_MS,
    VALIDATOR_FIRECRAWL_MAX_RETRIES,
    VALIDATOR_FIRECRAWL_SCRAPE_TIMEOUT_MS,
    VALIDATOR_FIRECRAWL_TIMEOUT_SECONDS,
    VALIDATOR_MARKET_SEARCH_LIMIT,
    VALIDATOR_MAX_CLAIM_CHARS,
)

TOOL_NAME = "research_market_landscape"
#: Kept as a module name because tests and readers reach for it here, but the
#: value now lives in config.py with the measurement that chose it.
MAX_CLAIM_CHARS = VALIDATOR_MAX_CLAIM_CHARS


class MarketResearchInput(BaseModel):
    """Input schema for market research."""

    query: str = Field(..., min_length=1, description="The exact market query to run.")
    # `le` is the SAME constant as the default, and that is the load-bearing
    # part. Firecrawl's `search` scrapes every result it returns to markdown,
    # so `limit` is not "how many rows" - it is how many full page fetches this
    # one call makes, at 10-30s each. A default the agent can raise to 10 is a
    # suggestion; matching the ceiling to it is the cap.
    limit: int = Field(
        default=VALIDATOR_MARKET_SEARCH_LIMIT,
        ge=1,
        le=VALIDATOR_MARKET_SEARCH_LIMIT,
        description=(
            "Maximum search results; each one is also scraped, so this is the "
            "page-fetch budget for the call."
        ),
    )


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _metadata(item: Any) -> Any:
    return _value(item, "metadata") or {}


def _valid_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _source_url(item: Any) -> str | None:
    """Read only URLs actually present on Firecrawl response objects."""
    direct = _valid_url(_value(item, "url"))
    if direct:
        return direct

    metadata = _metadata(item)
    return _valid_url(_value(metadata, "source_url")) or _valid_url(
        _value(metadata, "url")
    )


def _first_text(item: Any, *keys: str) -> str:
    for key in keys:
        value = _value(item, key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _claim(item: Any) -> str:
    """The one or two sentences that make this source citable.

    The preference order is load-bearing and it CHANGED when MAX_CLAIM_CHARS
    dropped from 4,000 to 500.

    `markdown` used to be tried before any description, and the clip is a plain
    head-clip of whitespace-flattened text. At 4,000 characters that was at
    least substantive prose. At 500 the first 500 characters of a scraped page
    are the nav bar, the cookie banner and the logo alt text - so the shorter
    bound would have quietly made every market claim worse rather than merely
    shorter.

    A page's own `description` / `og_description` is already a one-sentence
    summary written to be quoted, which is exactly what a claim is for. So the
    order is now: an explicit summary, then the page's description, and only
    then body text as a last resort.
    """

    text = _first_text(item, "summary")
    if not text:
        # Firecrawl puts `description` on `metadata` for a scraped Document and
        # at the top level for an unscraped search result. Try both before
        # falling back to body text.
        text = _first_text(_metadata(item), "description", "og_description")
    if not text:
        text = _first_text(item, "description")
    if not text:
        text = _first_text(item, "markdown", "title")
    if not text:
        text = _first_text(_metadata(item), "title")
    return text[:MAX_CLAIM_CHARS]


def _publication_date(item: Any, fallback: str) -> tuple[str, bool]:
    """The page's own date, or ``(retrieval time, True)`` when it reports none.

    The second element is the honesty flag. It reaches `Evidence` as
    `dated_is_retrieval_time` so the confidence path can tell an age it measured
    from one it merely observed; without it an undated page reads as published
    today, and the staleness multiplier is kindest exactly where recency is
    least known.
    """
    metadata = _metadata(item)
    for key in (
        "published_time",
        "modified_time",
        "dc_date",
        "dc_date_created",
        "dc_terms_created",
    ):
        value = _value(metadata, key)
        if isinstance(value, str) and value.strip():
            return value.strip(), False
    return fallback, True


def _publisher(url: str, item: Any) -> str:
    metadata = _metadata(item)
    named = _first_text(metadata, "og_site_name")
    return named or urlparse(url).netloc.lower()


def _envelope(
    *,
    status: str,
    query: str,
    retrieved_at: str,
    results: list[dict[str, Any]],
    notes: str,
) -> str:
    return json.dumps(
        {
            "status": status,
            "tool": TOOL_NAME,
            "query": query,
            "retrieved_at": retrieved_at,
            "result_count": len(results),
            "results": results,
            "notes": notes,
        },
        ensure_ascii=True,
    )


def _error_status(exc: Exception) -> tuple[str, str]:
    status_code = getattr(exc, "status_code", None)
    message = str(exc)
    lowered = message.lower()
    if status_code == 429 or "rate limit" in lowered:
        return "rate_limited", "Firecrawl rate limit reached; no market evidence returned."
    if status_code == 402 or any(term in lowered for term in ("credit", "payment required", "plan limit")):
        return "failed", "Firecrawl plan or credit limit prevented the search."
    if _looks_like_timeout(exc, lowered):
        # Named explicitly because the SDK reports a timeout as gibberish.
        # `handle_response_error(response, action)` reads `response.status_code`,
        # and a timed-out request has NO response - so the failure surfaced to a
        # real operator as `AttributeError: 'NoneType' object has no attribute
        # 'status_code'`, which reads like a bug in this repo rather than a slow
        # page. It reached the verdict, the report and the evidence gaps that way.
        return "failed", (
            "Firecrawl did not respond within the time limit; no market evidence "
            "returned. Raise VALIDATOR_FIRECRAWL_TIMEOUT_SECONDS if this recurs."
        )
    return "failed", f"Firecrawl search failed: {type(exc).__name__}: {message}"


def _looks_like_timeout(exc: Exception, lowered: str) -> bool:
    """Whether `exc` is a request that ran out of time rather than a real answer.

    Three signatures, because the SDK loses the original exception type on the
    way out: a genuine `Timeout`, the words themselves, and the `NoneType ...
    status_code` AttributeError that is what a timeout ACTUALLY looks like once
    the SDK's error handler has tried to read a status off a response that never
    arrived. That last one is a guess about someone else's internals, so it is
    matched narrowly - an AttributeError mentioning `status_code` - rather than
    by swallowing every AttributeError as a timeout.
    """

    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if any(term in lowered for term in ("timed out", "timeout", "read timed out")):
        return True
    return isinstance(exc, AttributeError) and "status_code" in lowered


class MarketResearchTool(BaseTool):
    name: str = TOOL_NAME
    description: str = (
        "Search and scrape current market sources with Firecrawl. Returns a JSON "
        "envelope containing attributed evidence only; rows without a source URL "
        "are omitted."
    )
    args_schema: Type[BaseModel] = MarketResearchInput
    env_vars: list[EnvVar] = [
        EnvVar(
            name="FIRECRAWL_API_KEY",
            description="Firecrawl search and scrape API key",
            required=True,
        )
    ]

    def _run(self, query: str, limit: int = VALIDATOR_MARKET_SEARCH_LIMIT) -> str:
        actual_query = query.strip()
        retrieved_at = _retrieved_at()
        api_key = os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            return _envelope(
                status="failed",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes="FIRECRAWL_API_KEY is not configured; no market evidence returned.",
            )

        try:
            # Every bound below was absent, and each absence had a cost.
            #
            # `timeout` on the CLIENT: the SDK defaults it to None, which
            # becomes `requests.post(..., timeout=None)` - a socket wait with
            # no deadline. `max_retries` defaults to 3 against a 300s server
            # ceiling, and 3 x 300s is where a 600s branch timeout comes from.
            # Neither is reachable from the `except` below, because an
            # exception that never raises cannot be caught.
            client = Firecrawl(
                api_key=api_key,
                timeout=float(VALIDATOR_FIRECRAWL_TIMEOUT_SECONDS),
                max_retries=VALIDATOR_FIRECRAWL_MAX_RETRIES,
            )
            response = client.search(
                actual_query,
                limit=limit,
                scrape_options=ScrapeOptions(
                    formats=["markdown"],
                    # Per PAGE, in ms. One pathological page must not eat the
                    # whole call's budget.
                    timeout=VALIDATOR_FIRECRAWL_SCRAPE_TIMEOUT_MS,
                    # Reuse a recently cached page: measured 10.36s cold
                    # against 2.26s warm for the same query.
                    max_age=VALIDATOR_FIRECRAWL_MAX_AGE_MS,
                    # Disable PDF parsing. Market-research hosts serve report
                    # PDFs that are billed per page and are slow to parse, and
                    # a PDF is never the citable source this branch wants.
                    parsers=[],
                ),
            )
        except Exception as exc:
            status, notes = _error_status(exc)
            return _envelope(
                status=status,
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes=notes,
            )

        results: list[dict[str, Any]] = []
        missing_url_count = 0
        retrieval_dated_count = 0
        for item in getattr(response, "web", None) or []:
            url = _source_url(item)
            if not url:
                missing_url_count += 1
                continue
            dated, used_retrieval_date = _publication_date(item, retrieved_at)
            retrieval_dated_count += int(used_retrieval_date)
            results.append(
                {
                    "claim": _claim(item),
                    "url": url,
                    "publisher": _publisher(url, item),
                    "dated": dated,
                    "dated_is_retrieval_time": used_retrieval_date,
                    "retrieved_via": "firecrawl",
                }
            )

        if not results:
            notes = "Firecrawl returned no attributable web results."
            if missing_url_count:
                notes += f" Omitted {missing_url_count} result(s) with no source URL."
            return _envelope(
                status="empty",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes=notes,
            )

        notes_parts = []
        if missing_url_count:
            notes_parts.append(f"Omitted {missing_url_count} result(s) with no source URL.")
        if retrieval_dated_count:
            notes_parts.append(
                f"Used retrieval time for {retrieval_dated_count} result(s) without a publication "
                "date; each is flagged dated_is_retrieval_time=true and must not be reported as "
                "freshly published."
            )
        return _envelope(
            status="ok",
            query=actual_query,
            retrieved_at=retrieved_at,
            results=results,
            notes=" ".join(notes_parts) or "Market evidence retrieved successfully.",
        )


__all__ = ["MarketResearchInput", "MarketResearchTool"]