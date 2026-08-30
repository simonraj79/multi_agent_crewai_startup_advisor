"""Validator-only branch cache policy and source-evidence write-back."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

from crewai.events import ToolUsageFinishedEvent
from crewai.events.stream_context import add_stream_sink, reset_stream_sinks

from brief_crew.config import (
    VALIDATOR_FEASIBILITY_CACHE_ENABLED,
    VALIDATOR_FEASIBILITY_MAX_INDEX_AGE_DAYS,
    VALIDATOR_FEASIBILITY_MIN_RERANK_SCORE,
    VALIDATOR_MAX_INDEX_AGE_DAYS,
    VALIDATOR_MIN_RERANK_HITS,
    VALIDATOR_MIN_RERANK_SCORE,
)
from brief_crew.indexing import index_documents
from brief_crew.schemas import ScopedIdea
from brief_crew.tools.pinecone_retrieval import retrieve

BranchName = Literal["market", "sentiment", "feasibility"]

_TOOL_BY_BRANCH: dict[BranchName, str] = {
    "market": "research_market_landscape",
    "sentiment": "analyze_community_sentiment",
    "feasibility": "assess_technical_feasibility",
}


@dataclass(frozen=True, slots=True)
class CapturedToolResult:
    """One successful raw tool output captured before model synthesis."""

    tool_name: str
    output: Any


def resolve_namespace(namespace: str | None = None) -> str:
    """Return a stable opaque namespace without exposing a raw identity."""

    explicit = (namespace or os.getenv("VALIDATOR_CACHE_NAMESPACE", "")).strip()
    if explicit:
        source = f"explicit:{explicit}"
    else:
        source = f"local:{getpass.getuser()}@{platform.node()}"
    digest = hashlib.sha256(
        f"brief-crew-validator-namespace-v1\n{source}".encode()
    ).hexdigest()[:24]
    return f"validator-{digest}"


def idea_hash(scope: ScopedIdea) -> str:
    """Create an opaque audit/revocation key for the scoped idea."""

    normalized = " ".join(scope.startup_idea.casefold().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cache_policy(
    branch: BranchName,
    feasibility_enabled: bool | None,
) -> tuple[float, int] | None:
    if branch == "sentiment":
        return None
    if branch == "market":
        return VALIDATOR_MIN_RERANK_SCORE, VALIDATOR_MAX_INDEX_AGE_DAYS

    enabled = (
        VALIDATOR_FEASIBILITY_CACHE_ENABLED
        if feasibility_enabled is None
        else feasibility_enabled
    )
    if not enabled:
        return None
    # This cache absorbs GitHub's shared-IP rate-limit pressure; it is not a
    # cost optimization because GitHub search itself is free.
    return (
        VALIDATOR_FEASIBILITY_MIN_RERANK_SCORE,
        VALIDATOR_FEASIBILITY_MAX_INDEX_AGE_DAYS,
    )


def lookup_branch_cache(
    scope: ScopedIdea,
    branch: BranchName,
    namespace: str,
    *,
    feasibility_enabled: bool | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Retrieve fresh, relevant branch evidence without routing around live work."""

    policy = _cache_policy(branch, feasibility_enabled)
    if policy is None:
        return []

    minimum_score, maximum_age_days = policy
    query = (
        scope.market_query
        if branch == "market"
        else "\n".join(scope.tech_queries)
    )
    hits = retrieve(
        query,
        metadata_filter={
            "branch": {"$eq": branch},
            "category": {"$eq": scope.category},
        },
        namespace=namespace,
    )

    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    qualified: list[dict[str, Any]] = []
    for hit in hits:
        indexed_at = _parse_datetime(hit.get("indexed_at"))
        score = float(hit.get("rerank_score", 0.0))
        if indexed_at is None or score < minimum_score:
            continue
        age_days = max(0, (checked_at - indexed_at).days)
        if age_days <= maximum_age_days:
            qualified.append(hit)

    if len(qualified) < VALIDATOR_MIN_RERANK_HITS:
        return []
    return qualified


def format_cached_evidence(
    hits: list[dict[str, Any]],
    *,
    retrieved_at: datetime | None = None,
) -> str:
    """Render cache hits as dated supplemental evidence, never conclusions."""

    checked_at = (retrieved_at or datetime.now(timezone.utc)).isoformat()
    if not hits:
        return (
            "CACHED EVIDENCE: none accepted by the branch relevance/freshness "
            "gate. Live tool research is still required."
        )

    blocks = [
        "CACHED EVIDENCE (SUPPLEMENTAL, NOT A CONCLUSION)",
        f"Cache lookup time: {checked_at}",
        "You must still call the branch's live research tool. Treat these passages "
        "as dated evidence or search leads, never as a prior verdict.",
    ]
    for position, hit in enumerate(hits, start=1):
        blocks.append(
            "\n".join(
                (
                    f"Passage {position}:",
                    f"source_url: {hit.get('url') or 'unknown'}",
                    f"publisher: {hit.get('publisher') or 'unknown'}",
                    f"source_date: {hit.get('published_date') or 'unknown'}",
                    f"indexed_at: {hit.get('indexed_at') or 'unknown'}",
                    f"rerank_score: {float(hit.get('rerank_score', 0.0)):.4f}",
                    f"passage: {hit.get('text') or ''}",
                )
            )
        )
    return "\n\n".join(blocks)


@contextmanager
def capture_tool_results(branch: BranchName) -> Iterator[list[CapturedToolResult]]:
    """Capture successful tool outputs synchronously in the current run context."""

    expected_tool = _TOOL_BY_BRANCH[branch]
    captured: list[CapturedToolResult] = []

    def sink(source: Any, event: Any) -> None:
        del source
        if (
            isinstance(event, ToolUsageFinishedEvent)
            and event.tool_name == expected_tool
            and event.failure is None
        ):
            captured.append(
                CapturedToolResult(tool_name=event.tool_name, output=event.output)
            )

    token = add_stream_sink(sink)
    try:
        yield captured
    finally:
        reset_stream_sinks(token)


def _envelope(output: Any) -> Mapping[str, Any] | None:
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return None
    return output if isinstance(output, Mapping) else None


def _valid_source_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return value.strip()


def _source_text(branch: BranchName, result: Mapping[str, Any]) -> str | None:
    if branch == "market":
        claim = result.get("claim")
        return claim.strip() if isinstance(claim, str) and claim.strip() else None
    if branch == "sentiment":
        quote = result.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            return None
        # The matched signal words, not a classification. The tools stopped
        # emitting `classification` / `relevance` under the schema's own field
        # names (rubric review F4), so the indexed text follows: a cached
        # document still carrying a pre-computed label would hand back on the
        # retrieval path the very answer the tool no longer offers live.
        signals = result.get("signal_terms_matched")
        signal_text = ", ".join(signals) if isinstance(signals, list) and signals else "none"
        return f"signal terms matched: {signal_text}\nquote: {quote.strip()}"
    required = (
        "name",
        "license_permits_commercial",
        "months_since_push",
        "query_term_overlap",
    )
    if any(key not in result for key in required):
        return None
    return json.dumps({key: result[key] for key in required}, sort_keys=True)


def tool_results_to_documents(
    captured: list[CapturedToolResult],
    branch: BranchName,
) -> list[dict[str, Any]]:
    """Convert raw tool envelopes into exactly one source document per URL."""

    expected_tool = _TOOL_BY_BRANCH[branch]
    grouped: dict[str, dict[str, Any]] = {}
    for captured_result in captured:
        if captured_result.tool_name != expected_tool:
            continue
        envelope = _envelope(captured_result.output)
        if envelope is None or envelope.get("status") != "ok":
            continue
        retrieved_at = envelope.get("retrieved_at")
        if not isinstance(retrieved_at, str) or _parse_datetime(retrieved_at) is None:
            continue
        results = envelope.get("results")
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, Mapping):
                continue
            url = _valid_source_url(result.get("url"))
            text = _source_text(branch, result)
            if url is None or text is None:
                continue
            published_date = result.get("dated") or result.get("date") or retrieved_at
            if not isinstance(published_date, str) or _parse_datetime(published_date) is None:
                published_date = retrieved_at
            publisher = result.get("publisher")
            if not isinstance(publisher, str) or not publisher.strip():
                publisher = "Hacker News" if branch == "sentiment" else "GitHub"

            document = grouped.setdefault(
                url,
                {
                    "texts": [],
                    "payloads": [],
                    "url": url,
                    "publisher": publisher,
                    "published_date": published_date,
                    "retrieved_at": retrieved_at,
                },
            )
            if text not in document["texts"]:
                document["texts"].append(text)
                document["payloads"].append(dict(result))

    documents: list[dict[str, Any]] = []
    for document in grouped.values():
        payloads = document["payloads"]
        documents.append(
            {
                "text": "\n\n".join(document["texts"]),
                "url": document["url"],
                "publisher": document["publisher"],
                "published_date": document["published_date"],
                "metadata": {
                    "retrieved_at": document["retrieved_at"],
                    "retrieved_via": branch,
                    "source_payload": json.dumps(
                        payloads[0] if len(payloads) == 1 else payloads,
                        sort_keys=True,
                    ),
                },
            }
        )
    return documents


def index_captured_evidence(
    captured: list[CapturedToolResult],
    *,
    branch: BranchName,
    scope: ScopedIdea,
    source_run_id: str,
    namespace: str,
) -> int:
    """Index only source records captured from this branch's tool events."""

    documents = tool_results_to_documents(captured, branch)
    if not documents:
        return 0
    return index_documents(
        documents=documents,
        topic=scope.category,
        source_run_id=source_run_id,
        namespace=namespace,
        metadata={
            "branch": branch,
            "category": scope.category,
            "idea_hash": idea_hash(scope),
        },
    )


__all__ = [
    "BranchName",
    "CapturedToolResult",
    "capture_tool_results",
    "format_cached_evidence",
    "idea_hash",
    "index_captured_evidence",
    "lookup_branch_cache",
    "resolve_namespace",
    "tool_results_to_documents",
]