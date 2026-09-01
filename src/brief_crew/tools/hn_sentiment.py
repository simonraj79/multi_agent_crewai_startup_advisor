"""Hacker News comment evidence for the startup validator."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Type

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from brief_crew.config import VALIDATOR_SENTIMENT_STORY_LIMIT

TOOL_NAME = "analyze_community_sentiment"
HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
HN_ITEM_URL = "https://hn.algolia.com/api/v1/items/{item_id}"
HN_CITATION_URL = "https://news.ycombinator.com/item?id={item_id}"
REQUEST_TIMEOUT_SECONDS = 20
MAX_QUOTE_CHARS = 1_000

_SIGNAL_TERMS = {
    "PAYS": ("pay", "paid", "spend", "spent", "budget", "subscription", "cost us"),
    "BUILT_WORKAROUND": (
        "workaround",
        "spreadsheet",
        "manual process",
        "built my own",
        "built our own",
        "we built",
        "i built",
        "hack together",
    ),
    "HAS_PROBLEM": (
        "problem",
        "pain",
        "struggle",
        "frustrat",
        "difficult",
        "takes hours",
        "waste time",
        "annoying",
    ),
}
_QUERY_STOPWORDS = {
    "and",
    "for",
    "from",
    "into",
    "market",
    "solution",
    "that",
    "the",
    "this",
    "tool",
    "using",
    "with",
}


def _representative_comment(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """The one comment that stands for its story. Deterministic, no judgement.

    Ranked on observations the tool ALREADY reports as evidence, never on a
    label it invents - which is what keeps this clear of rubric finding F4. The
    analyst still reads the quote and still decides the classification.

    1. On-topic beats off-topic (`query_terms_present`). An off-topic
       representative would misrepresent a story that does discuss the topic,
       and that error pushes toward a FALSE REJECT - the expensive direction.
    2. More signal terms beats fewer: more for the analyst to weigh.
    3. Longer quote breaks a tie: more context, still bounded by
       MAX_QUOTE_CHARS.
    4. Document order settles the rest, so two identical calls agree. In
       practice that is the story's own text when it has one.

    Known cost, stated rather than hidden: a story with one HAS_PROBLEM comment
    and one PAYS comment now yields whichever rung 2 prefers, so D=5's
    `recent_acted >= 2` needs two SEPARATE stories. That is a real tightening,
    and it is the correct direction - two people paying in one thread is one
    conversation's worth of evidence.
    """

    return max(
        enumerate(candidates),
        key=lambda pair: (
            bool(pair[1].get("query_terms_present")),
            len(pair[1].get("signal_terms_matched") or ()),
            len(str(pair[1].get("quote") or "")),
            -pair[0],
        ),
    )[1]


class HackerNewsSentimentInput(BaseModel):
    """Input schema for Hacker News sentiment research."""

    query: str = Field(..., min_length=1, description="The exact HN search query.")
    # DISTINCT THREADS == story_limit: every row from one story shares one URL
    # and the task keeps at most one Thread per URL. The REJECT floor needs
    # `>= RUBRIC_FLOOR_MIN_USABLE_THREADS` (3), so the old default of 3 sat
    # exactly ON the floor - one OFF_TOPIC classification fired a final
    # "no demand" REJECT that was arithmetic, not evidence. The margin used to
    # come from the broadening retries; with one call it comes from here.
    story_limit: int = Field(
        default=VALIDATOR_SENTIMENT_STORY_LIMIT,
        ge=1,
        le=VALIDATOR_SENTIMENT_STORY_LIMIT,
        description="Stories to inspect; each becomes at most one usable thread.",
    )
    comments_per_story: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum story body and comments returned per thread.",
    )


class _CommentHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in {"br", "p", "div", "li", "pre"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in {"p", "div", "li", "pre"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self.parts).split())


class _RateLimitedError(RuntimeError):
    pass


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _html_to_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parser = _CommentHTMLParser()
    parser.feed(value)
    parser.close()
    return parser.text()


def _request_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 429:
        raise _RateLimitedError("Hacker News Algolia returned HTTP 429")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Hacker News Algolia returned a non-object JSON payload")
    return payload


def _walk_comments(item: dict[str, Any]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    root = dict(item)
    children = root.pop("children", None)
    if root.get("text"):
        comments.append(root)

    stack = list(reversed(children if isinstance(children, list) else []))
    while stack:
        comment = stack.pop()
        if not isinstance(comment, dict):
            continue
        if comment.get("text") and not comment.get("deleted") and not comment.get("dead"):
            comments.append(comment)
        nested = comment.get("children")
        if isinstance(nested, list):
            stack.extend(reversed(nested))
    return comments


def _query_terms(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) >= 3 and token not in _QUERY_STOPWORDS
    }


def _signal_terms_matched(text: str) -> list[str]:
    """Which signal words appear in the comment - NOT what they mean.

    This used to be `_classify`, returning one of `Thread.classification`'s own
    enum values under the envelope key `classification`. Two things were wrong
    with that, and rubric review finding F4 is about both:

    * It shipped a schema-valid answer under the schema's own field name, so
      copying it was the cheapest valid output a cheap-tier branch agent could
      produce. Three of the four fatal floors and the whole VALIDATE gate turn
      on labels the analysts are supposed to *judge*.
    * The judgement it offered was a substring test. `_classify("Payload CMS
      handles this already.")` returned `PAYS`, because "Payload" contains
      "pay". D=4 and D=5's "someone acted on it" clause therefore reduced to
      whether the substring `pay` occurred anywhere in a sentence.

    Reporting the matched terms keeps everything the heuristic actually knows -
    the analyst can still see that "pay" occurred - while making the inference
    theirs. A flat list, deliberately: grouping the terms under their old
    classification keys would hand the label straight back.
    """

    lowered = text.lower()
    matched = [
        term
        for terms in _SIGNAL_TERMS.values()
        for term in terms
        if _contains_word(lowered, term)
    ]
    # Stable order, no duplicates, so the envelope is reproducible.
    return sorted(set(matched))


def _contains_word(haystack: str, term: str) -> bool:
    """Word-boundary match, not a substring test.

    Reporting the matched terms instead of a label would have moved the F4
    substring problem rather than fixed it: `"Payload CMS handles this"` still
    matched `pay`, so the analyst would be handed misleading evidence in place
    of a misleading conclusion. Anchoring on word boundaries is what actually
    stops `pay` firing on `Payload`, `paid` on `unpaid`, and `cost us` on
    `cost usage`. Multi-word terms work unchanged - the boundary is around the
    whole phrase.
    """

    return re.search(rf"\b{re.escape(term)}\b", haystack) is not None


def _query_terms_present(text: str, query: str) -> bool:
    """Whether any word of the query appears at all.

    The one part of the old `_classify` worth keeping mechanical: "this comment
    is about something else entirely" is closer to a fact than a judgement, and
    `OFF_TOPIC` gates the usable-thread count that D=0 and D=1 rest on. Reported
    as the observation rather than as the label, so the analyst still decides.
    """

    terms = _query_terms(query)
    if not terms:
        return True
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _story_metric(*payloads: Any, key: str) -> int | None:
    """The first non-negative integer ``key`` any payload reports, else ``None``.

    Algolia carries ``points`` and ``num_comments`` on the story record returned
    by ``/search``, and ``points`` again on the ``/items`` root; comments carry
    neither. Both are read from responses this tool already fetches, so no extra
    request is made for them.

    Tri-state on purpose. A story genuinely at zero points and a story whose
    score Algolia did not report are different claims, so anything that is not a
    usable count returns ``None`` rather than 0.
    """
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value >= 0:
            return value
    return None


def _comment_date(comment: dict[str, Any], fallback: str) -> tuple[str, bool]:
    """The item's own date, or ``(retrieval time, True)`` when it carries none.

    The second element is the honesty flag. It reaches `Thread` as
    `date_is_retrieval_time`, because the Demand ladder - the heaviest of the
    five dimensions - scores on "dated within 24 months", and a fallback date
    is always within 24 months of today. Without the flag an undated thread
    silently supports D's top anchors.
    """
    created_at = comment.get("created_at")
    if isinstance(created_at, str) and created_at.strip():
        return created_at.strip(), False
    created_at_i = comment.get("created_at_i")
    if isinstance(created_at_i, (int, float)):
        date = datetime.fromtimestamp(created_at_i, tz=timezone.utc)
        return date.isoformat(timespec="seconds").replace("+00:00", "Z"), False
    return fallback, True


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


class HackerNewsSentimentTool(BaseTool):
    name: str = TOOL_NAME
    description: str = (
        "Search Hacker News stories and inspect their comment trees for problem, "
        "payment, workaround, opinion, and off-topic signals. Returns a JSON envelope."
    )
    args_schema: Type[BaseModel] = HackerNewsSentimentInput

    def _run(
        self,
        query: str,
        story_limit: int = VALIDATOR_SENTIMENT_STORY_LIMIT,
        comments_per_story: int = 5,
    ) -> str:
        actual_query = query.strip()
        retrieved_at = _retrieved_at()
        try:
            search_payload = _request_json(
                HN_SEARCH_URL,
                params={
                    "query": actual_query,
                    "tags": "story",
                    "hitsPerPage": story_limit,
                },
            )
            hits = search_payload.get("hits")
            if not isinstance(hits, list):
                raise ValueError("Hacker News search response did not contain a hits list")

            results: list[dict[str, Any]] = []
            retrieval_dated_count = 0
            inspected_stories = 0
            unreported_metric_stories = 0
            for hit in hits[:story_limit]:
                if not isinstance(hit, dict):
                    continue
                item_id = hit.get("objectID")
                if item_id is None or not str(item_id).strip():
                    continue
                item_id = str(item_id).strip()
                thread = _request_json(HN_ITEM_URL.format(item_id=item_id))
                inspected_stories += 1
                # Story-level signals, shared by every row cited to this thread:
                # the rows all carry the story's HN item URL, so they all
                # describe how public that one story was.
                points = _story_metric(hit, thread, key="points")
                num_comments = _story_metric(hit, thread, key="num_comments")
                unreported_metric_stories += int(points is None or num_comments is None)
                # ONE row per story, chosen here rather than asked for in prose.
                #
                # Every row cited to a story carries the SAME HN item URL, and
                # `SentimentFindings` requires `source_urls` to mirror
                # `sources[].url` positionally AND to be duplicate-free - which
                # together mean at most one Thread per URL. That collapse used
                # to be one sentence in a 21-line prompt paragraph, and on a
                # live run it cost the whole branch: the model emitted 5 rows
                # from 3 stories, and the two ways of writing that down each
                # failed a different validator.
                #
                # It is also the right SEMANTICS, not merely the enforceable
                # one. Five comments in one thread are one conversation, one
                # headline, one day, one self-selected audience - not five
                # independent observations. The Demand ladder counts Thread
                # objects, so letting them through would let a single popular
                # story reach D=5, the heaviest dimension in the rubric.
                # `VALIDATOR_SENTIMENT_STORY_LIMIT` was calibrated against the
                # identity "distinct threads == story_limit"; this makes that
                # identity true by construction instead of by request.
                candidates: list[dict[str, Any]] = []
                for comment in _walk_comments(thread)[:comments_per_story]:
                    quote = _html_to_text(comment.get("text"))
                    if not quote:
                        continue
                    date, used_retrieval_date = _comment_date(comment, retrieved_at)
                    candidates.append(
                        {
                            "signal_terms_matched": _signal_terms_matched(quote),
                            "query_terms_present": _query_terms_present(
                                quote, actual_query
                            ),
                            "quote": quote[:MAX_QUOTE_CHARS],
                            "url": HN_CITATION_URL.format(item_id=item_id),
                            "date": date,
                            "date_is_retrieval_time": used_retrieval_date,
                            "points": points,
                            "num_comments": num_comments,
                        }
                    )
                if not candidates:
                    continue
                chosen = _representative_comment(candidates)
                # Counted on the SURVIVING row only: the flag describes the
                # evidence that is actually reported, and counting discarded
                # candidates would overstate how much of the branch is
                # retrieval-dated.
                retrieval_dated_count += int(chosen["date_is_retrieval_time"])
                # How many were looked at, so the sampling is auditable. Nothing
                # scores on it; it exists so a reader can see "1 of 5" rather
                # than assume the thread held exactly one comment.
                chosen["comments_scanned"] = len(candidates)
                results.append(chosen)
        except _RateLimitedError:
            return _envelope(
                status="rate_limited",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes="Hacker News Algolia returned HTTP 429; partial evidence was discarded.",
            )
        except (requests.RequestException, ValueError) as exc:
            return _envelope(
                status="failed",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes=f"Hacker News research failed: {type(exc).__name__}: {exc}",
            )

        if not results:
            return _envelope(
                status="empty",
                query=actual_query,
                retrieved_at=retrieved_at,
                results=[],
                notes=f"Inspected {inspected_stories} HN thread(s) but found no usable text.",
            )

        notes = f"Inspected {inspected_stories} HN thread(s) and fetched their comment trees."
        if retrieval_dated_count:
            notes += (
                f" Used retrieval time for {retrieval_dated_count} item(s) without a source "
                "date; each is flagged date_is_retrieval_time=true and is never dated within "
                "24 months."
            )
        if unreported_metric_stories:
            notes += (
                f" Algolia reported no score or comment count for {unreported_metric_stories} "
                "thread(s); those fields are null rather than zero."
            )
        return _envelope(
            status="ok",
            query=actual_query,
            retrieved_at=retrieved_at,
            results=results,
            notes=notes,
        )


__all__ = ["HackerNewsSentimentInput", "HackerNewsSentimentTool"]