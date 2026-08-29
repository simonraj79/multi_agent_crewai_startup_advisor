"""Firecrawl market evidence for the startup validator."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Type
from urllib.parse import urlparse

from crewai.tools import BaseTool, EnvVar
from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions
from pydantic import BaseModel, Field

TOOL_NAME = "research_market_landscape"
MAX_CLAIM_CHARS = 4_000


class MarketResearchInput(BaseModel):
    """Input schema for market research."""

    query: str = Field(..., min_length=1, description="The exact market query to run.")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum search results.")


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
    text = _first_text(item, "summary", "markdown", "description", "title")
    if text:
        return text[:MAX_CLAIM_CHARS]

    metadata = _metadata(item)
    text = _first_text(metadata, "description", "og_description", "title")
    return text[:MAX_CLAIM_CHARS]


def _publication_date(item: Any, fallback: str) -> tuple[str, bool]:
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
    return "failed", f"Firecrawl search failed: {type(exc).__name__}: {message}"


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

    def _run(self, query: str, limit: int = 5) -> str:
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
            response = Firecrawl(api_key=api_key).search(
                actual_query,
                limit=limit,
                scrape_options=ScrapeOptions(formats=["markdown"]),
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
                f"Used retrieval time for {retrieval_dated_count} result(s) without a publication date."
            )
        return _envelope(
            status="ok",
            query=actual_query,
            retrieved_at=retrieved_at,
            results=results,
            notes=" ".join(notes_parts) or "Market evidence retrieved successfully.",
        )


__all__ = ["MarketResearchInput", "MarketResearchTool"]