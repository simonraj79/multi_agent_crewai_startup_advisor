"""GitHub repository evidence for the startup validator."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Type
from urllib.parse import urlparse

import requests
from crewai.tools import BaseTool, EnvVar
from pydantic import BaseModel, Field

TOOL_NAME = "assess_technical_feasibility"
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_REPOSITORY_URL = "https://api.github.com/repos/{full_name}"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_USER_AGENT = "brief-crew-validator/0.1"
REQUEST_TIMEOUT_SECONDS = 20
UNAUTHENTICATED_REQUESTS_PER_MINUTE = 8
AUTHENTICATED_REQUESTS_PER_MINUTE = 24

_QUERY_STOPWORDS = {
    "and",
    "app",
    "application",
    "for",
    "from",
    "into",
    "software",
    "that",
    "the",
    "this",
    "tool",
    "using",
    "with",
}
_COMMERCIAL_SPDX_LICENSES = {
    "0BSD",
    "AGPL-3.0",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSL-1.0",
    "CC0-1.0",
    "CDDL-1.0",
    "EPL-2.0",
    "GPL-2.0",
    "GPL-3.0",
    "ISC",
    "LGPL-2.1",
    "LGPL-3.0",
    "MIT",
    "MPL-2.0",
    "Unlicense",
}


class GitHubFeasibilityInput(BaseModel):
    """Input schema for GitHub feasibility research."""

    query: str = Field(..., min_length=1, description="The exact repository search query.")
    limit: int = Field(default=5, ge=1, le=5, description="Repositories to inspect.")


class _TokenBucket:
    """A small thread-safe bucket shared by every tool instance in this process."""

    def __init__(self, rate_per_minute: int) -> None:
        self.rate_per_minute = rate_per_minute
        self._capacity = float(rate_per_minute)
        self._tokens = float(rate_per_minute)
        self._refill_per_second = rate_per_minute / 60.0
        self._updated_at = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = max(0.0, now - self._updated_at)
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._refill_per_second,
                )
                self._updated_at = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_seconds = (1.0 - self._tokens) / self._refill_per_second
            time.sleep(wait_seconds)


_TOKEN_BUCKETS = {
    False: _TokenBucket(UNAUTHENTICATED_REQUESTS_PER_MINUTE),
    True: _TokenBucket(AUTHENTICATED_REQUESTS_PER_MINUTE),
}


class _RateLimitedError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": GITHUB_USER_AGENT,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _response_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    message = payload.get("message")
    return message if isinstance(message, str) else ""


def _is_rate_limited(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    remaining = response.headers.get("X-RateLimit-Remaining")
    message = _response_message(response).lower()
    return remaining == "0" or "rate limit" in message or "secondary rate" in message


def _request_json(
    url: str,
    *,
    headers: dict[str, str],
    bucket: _TokenBucket,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bucket.acquire()
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if _is_rate_limited(response):
        raise _RateLimitedError("GitHub API rate limit reached")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("GitHub returned a non-object JSON payload")
    return payload


def _valid_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _valid_full_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", candidate):
        return candidate
    return None


def _license_permits_commercial(repository: dict[str, Any]) -> bool:
    license_data = repository.get("license")
    if not isinstance(license_data, dict):
        return False
    spdx_id = license_data.get("spdx_id")
    return isinstance(spdx_id, str) and spdx_id in _COMMERCIAL_SPDX_LICENSES


def _archived(*payloads: Any) -> bool | None:
    """GitHub's ``archived`` flag, or ``None`` when no payload reports one.

    Costs no request. ``/search/repositories`` items are full repository
    representations and already carry ``archived``, and so does the detail
    payload this tool already fetches per result. The shared 10 req/min per-IP
    budget (PRD R-7) therefore sees the same 1 + N calls it saw before.

    ``None`` means "not reported", which is not the claim ``False`` makes: an
    unreported flag must never read as "confirmed still maintained".
    """
    for payload in payloads:
        if isinstance(payload, dict) and isinstance(payload.get("archived"), bool):
            return bool(payload["archived"])
    return None


def _months_since_push(value: Any, now: datetime) -> int | None:
    """Whole months since ``pushed_at``, or ``None`` when GitHub reported none.

    ``None``, not -1. The sentinel was unrepresentable: `Repo.months_since_push`
    constrains the field to ``>= 0``, so a model copying the -1 this tool
    advertised in its own notes failed validation and had to either drop the
    repository or invent an age. Unknown activity is now sayable, and every
    "pushed within 12 months" clause treats it as not satisfied.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        pushed_at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if pushed_at.tzinfo is None:
        pushed_at = pushed_at.replace(tzinfo=timezone.utc)
    elapsed = now - pushed_at.astimezone(timezone.utc)
    return max(0, elapsed.days // 30)


def _query_terms(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) >= 3 and token not in _QUERY_STOPWORDS
    }


def _query_term_overlap(query: str, repository: dict[str, Any]) -> dict[str, Any]:
    """Which query words appear in the repository's own text - NOT what it does.

    This used to be `_relevance`, returning one of `Repo.relevance`'s own enum
    values under the envelope key `relevance`. Rubric review finding F4:

    * It handed a schema-valid answer back under the schema's own field name, so
      copying it was the cheapest valid output a cheap-tier branch agent could
      produce - and `FLOOR_ALREADY_FREE`, a REJECT, reads `SOLVES_ENTIRELY`.
    * The answer was word overlap. A repository named `acme/clinic-scheduling`
      described as "A demo clinic scheduling app, abandoned" scored
      `SOLVES_ENTIRELY` against the query "clinic scheduling", because the words
      matched. Whether a dead student demo solves the job is exactly the
      judgement the Feasibility Analyst exists to make, and the ratio test made
      it sensitive to *how many words the Scoper put in the query*: adding one
      word to the query turned the same repository into `PARTIAL`.

    Reporting the overlap keeps everything the heuristic knew and returns the
    inference to the analyst, who can also see `months_since_push`, `archived`
    and the licence - the facts that tell a live project from an abandoned one,
    and which no amount of name-matching can substitute for.
    """

    topics = repository.get("topics")
    topic_text = " ".join(str(topic) for topic in topics) if isinstance(topics, list) else ""
    searchable = " ".join(
        str(repository.get(key) or "") for key in ("name", "full_name", "description")
    )
    searchable = f"{searchable} {topic_text}".lower()
    terms = _query_terms(query)
    matched = [term for term in terms if _contains_word(searchable, term)]
    return {
        "matched": sorted(set(matched)),
        "query_terms": sorted(set(terms)),
    }


def _contains_word(haystack: str, term: str) -> bool:
    """Word-boundary match, not a substring test.

    Without this, reporting the matched terms would only move F4's substring
    problem into the evidence: a repository called `payments-api` would still
    report a match for the query word `pay`. Multi-word terms work unchanged.
    """

    return re.search(rf"\b{re.escape(term)}\b", haystack) is not None


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


class GitHubFeasibilityTool(BaseTool):
    name: str = TOOL_NAME
    description: str = (
        "Search GitHub repositories and return license, recent-activity, and query-relevance "
        "signals in a JSON envelope. Popularity alone is not treated as feasibility."
    )
    args_schema: Type[BaseModel] = GitHubFeasibilityInput
    env_vars: list[EnvVar] = [
        EnvVar(
            name="GITHUB_TOKEN",
            description="Optional token for a higher GitHub API request budget",
            required=False,
        )
    ]

    def _run(self, query: str, limit: int = 5) -> str:
        actual_query = query.strip()
        now = _utc_now()
        retrieved_at = _isoformat(now)
        token = os.getenv("GITHUB_TOKEN") or None
        headers = _headers(token)
        bucket = _TOKEN_BUCKETS[bool(token)]

        try:
            search_payload = _request_json(
                GITHUB_SEARCH_URL,
                headers=headers,
                bucket=bucket,
                params={
                    "q": actual_query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": limit,
                },
            )
            items = search_payload.get("items")
            if not isinstance(items, list):
                raise ValueError("GitHub search response did not contain an items list")

            results: list[dict[str, Any]] = []
            skipped_count = 0
            unknown_activity_count = 0
            unreported_archived_count = 0
            for item in items[:limit]:
                if not isinstance(item, dict):
                    skipped_count += 1
                    continue
                full_name = _valid_full_name(item.get("full_name"))
                if not full_name:
                    skipped_count += 1
                    continue
                repository = _request_json(
                    GITHUB_REPOSITORY_URL.format(full_name=full_name),
                    headers=headers,
                    bucket=bucket,
                )
                url = _valid_url(repository.get("html_url")) or _valid_url(item.get("html_url"))
                if not url:
                    skipped_count += 1
                    continue
                months_since_push = _months_since_push(
                    repository.get("pushed_at") or item.get("pushed_at"),
                    now,
                )
                unknown_activity_count += int(months_since_push is None)
                archived = _archived(repository, item)
                unreported_archived_count += int(archived is None)
                results.append(
                    {
                        "name": str(repository.get("full_name") or full_name),
                        "license_permits_commercial": _license_permits_commercial(repository),
                        "months_since_push": months_since_push,
                        "query_term_overlap": _query_term_overlap(actual_query, repository),
                        "url": url,
                        "archived": archived,
                    }
                )
        except _RateLimitedError:
            return _envelope(
                status="rate_limited",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes="GitHub API rate limit reached; partial repository evidence was discarded.",
            )
        except (requests.RequestException, ValueError) as exc:
            return _envelope(
                status="failed",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes=f"GitHub feasibility research failed: {type(exc).__name__}: {exc}",
            )

        if not results:
            return _envelope(
                status="empty",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes="GitHub returned no attributable repository details for this query.",
            )

        notes_parts = [
            f"Inspected {len(results)} repository detail response(s); stars were not used as a relevance signal."
        ]
        if skipped_count:
            notes_parts.append(f"Skipped {skipped_count} malformed or unattributed result(s).")
        if unknown_activity_count:
            notes_parts.append(
                f"Activity was unknown for {unknown_activity_count} result(s); months_since_push "
                "is null rather than a number, and null is not 'pushed recently'."
            )
        if unreported_archived_count:
            notes_parts.append(
                f"GitHub reported no archive state for {unreported_archived_count} result(s); "
                "archived is null rather than false."
            )
        return _envelope(
            status="ok",
            query=actual_query,
            retrieved_at=retrieved_at,
            results=results,
            notes=" ".join(notes_parts),
        )


__all__ = ["GitHubFeasibilityInput", "GitHubFeasibilityTool"]