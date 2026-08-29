#!/usr/bin/env python
"""Entry points: the Track A crew, and the Track B Flow.

Track A - ``run_crew()``. Three agents, three tasks, one ``Crew``, no
infrastructure beyond the API keys. This is slide 52's half-way checkpoint and
every stretch in this repository presupposes it works. Run it first.

Track B - ``kickoff()``. The same crew wrapped in a Flow that checks a warm
Pinecone cache before any agent runs. The one genuinely dynamic decision in the
system is cache hit versus miss, and a ``@router`` resolves it deterministically
for **zero LLM calls**::

    @start()                                  retrieve_cached
    @router(retrieve_cached)                  check_cache -> hit | miss
    @listen("cache_miss")   scrape_web        Researcher, Firecrawl tools
    @listen(scrape_web)     index_content     chunk / embed / upsert
    @listen(or_(...))       write_brief       Analyst + Writer
    @listen(write_brief)    persist           brief.md (+ Postgres, Track B live)

A Flow rather than ``Process.hierarchical`` because a Manager agent would make
the identical binary decision and charge an LLM call per run to do it. A Flow
rather than ``Process.sequential`` because sequential cannot branch at all, and
the cache-hit path must skip scraping entirely.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from crewai.flow import Flow, listen, or_, router, start
from pydantic import BaseModel, Field

from brief_crew.config import (
    MAX_INDEX_AGE_DAYS,
    MIN_RERANK_HITS,
    MIN_RERANK_SCORE,
    compute_cost_usd,
)
from brief_crew.crews.brief_crew.brief_crew import BriefCrew
from brief_crew.indexing import index_documents
from brief_crew.tools.pinecone_retrieval import retrieve

# Credentials are loaded in brief_crew/__init__.py, on package import.

DEFAULT_TOPIC = "cashless payments in Singapore"
OUTPUT_DIR = Path("output")


class BriefState(BaseModel):
    """Flow state. Structured, so a typo in a field name is an error, not a shrug."""

    topic: str = DEFAULT_TOPIC
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    retrieved: list[dict[str, Any]] = Field(default_factory=list)
    route: str = ""
    # 07-deployment.md names this field `scraped`. It is `research_notes` here
    # because what the step actually yields is the Researcher's structured notes,
    # not raw scraped markdown - and that is what gets indexed.
    research_notes: str = ""
    brief: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)


def _format_hits(hits: list[dict[str, Any]]) -> str:
    """Render retrieved chunks as research material the Analyst can read.

    Every passage carries its indexing date, because the downstream constraint is
    that a cached fact must never be presented as freshly verified.
    """
    blocks = []
    for i, hit in enumerate(hits, start=1):
        blocks.append(
            f"### Passage {i}\n"
            f"- publisher: {hit.get('publisher') or 'unknown'}\n"
            f"- published_date: {hit.get('published_date') or 'unknown'}\n"
            f"- indexed_at: {hit.get('indexed_at') or 'unknown'}\n"
            f"- url: {hit.get('url') or 'unknown'}\n"
            f"- rerank_score: {hit.get('rerank_score'):.4f}\n\n"
            f"{hit.get('text', '')}"
        )
    return "\n\n".join(blocks)


class BriefFlow(Flow[BriefState]):
    """Track B - the hosted service."""

    @start()
    def retrieve_cached(self) -> None:
        """Query the corpus before any agent runs. Pinecone + Cohere, no model."""
        print(f"[flow] retrieving cached material for: {self.state.topic}")
        try:
            self.state.retrieved = retrieve(self.state.topic)
        except Exception as exc:
            # A retrieval failure is a cache miss, not a run failure. Falling
            # through to the live web is the correct degradation.
            print(f"[flow] retrieval failed ({type(exc).__name__}: {exc}) - treating as miss")
            self.state.retrieved = []
        print(f"[flow] {len(self.state.retrieved)} reranked hit(s)")

    @router(retrieve_cached)
    def check_cache(self) -> Literal["cache_hit", "cache_miss"]:
        """The staleness gate. Three conditions, all must hold. Zero LLM calls.

        Thresholds are imported from ``brief_crew.config`` rather than restated
        here, so the router and the spec cannot drift apart.
        """
        hits = self.state.retrieved

        if len(hits) < MIN_RERANK_HITS:
            reason = f"only {len(hits)} hit(s), need {MIN_RERANK_HITS}"
        elif (top := hits[0].get("rerank_score", 0.0)) < MIN_RERANK_SCORE:
            # Threshold is on the RERANK score, not the cosine score. Cosine
            # scores for a good match and an irrelevant one span ~0.06 on this
            # index - there is no defensible cutoff inside that band.
            reason = f"top rerank_score {top:.4f} below {MIN_RERANK_SCORE}"
        elif (age := _age_days(hits[0].get("indexed_at"))) is None:
            reason = "top hit has no usable indexed_at"
        elif age > MAX_INDEX_AGE_DAYS:
            reason = f"top hit indexed {age} days ago, over the {MAX_INDEX_AGE_DAYS}-day limit"
        else:
            self.state.route = "cache_hit"
            print(f"[flow] route=cache_hit (top score {hits[0]['rerank_score']:.4f}, {age}d old)")
            return "cache_hit"

        self.state.route = "cache_miss"
        print(f"[flow] route=cache_miss ({reason})")
        return "cache_miss"

    @listen("cache_miss")
    def scrape_web(self) -> None:
        """The Researcher, with two tools. Track B: no retrieval tool, no step 0."""
        print("[flow] scraping the live web")
        result = (
            BriefCrew(track="B")
            .crew()
            .kickoff(inputs={"topic": self.state.topic})
        )
        # On this path the full three-agent crew has already produced the brief,
        # so capture both the notes (for indexing) and the finished output.
        self.state.research_notes = str(result.tasks_output[0].raw)
        self.state.brief = str(result.raw)
        self.state.usage = _usage_dict(result)

    @listen(scrape_web)
    def index_content(self) -> None:
        """Write back what was scraped. Always, unconditionally, as plumbing.

        Index what was scraped, not what was used: if write-back were conditional
        on the brief being good, the cache would only ever accumulate material
        that already worked, biasing what future runs can find.
        """
        if not self.state.research_notes:
            print("[flow] nothing to index")
            return
        try:
            written = index_documents(
                documents=[{"text": self.state.research_notes, "url": "", "publisher": ""}],
                topic=self.state.topic,
                source_run_id=self.state.run_id,
            )
            print(f"[flow] indexed {written} chunk(s) under run {self.state.run_id}")
        except Exception as exc:
            # Write-back is an optimisation for the *next* run. Never fail this
            # run because the cache could not be refilled.
            print(f"[flow] indexing failed ({type(exc).__name__}: {exc}) - continuing")

    @listen(or_("cache_hit", index_content))
    def write_brief(self) -> None:
        """Analyst + Writer. On a miss the brief already exists; on a hit it does not."""
        if self.state.route == "cache_miss":
            print("[flow] brief already produced on the scrape path")
            return

        print("[flow] writing brief from cached material")
        result = (
            BriefCrew(from_notes=True)
            .crew()
            .kickoff(
                inputs={
                    "topic": self.state.topic,
                    "research_notes": _format_hits(self.state.retrieved),
                }
            )
        )
        self.state.brief = str(result.raw)
        self.state.usage = _usage_dict(result)

    @listen(write_brief)
    def persist(self) -> None:
        """The durable artifact. Postgres row goes here too under the live service."""
        OUTPUT_DIR.mkdir(exist_ok=True)
        (OUTPUT_DIR / "brief.md").write_text(self.state.brief, encoding="utf-8")

        record = {
            "run_id": self.state.run_id,
            "topic": self.state.topic,
            "route": self.state.route,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            **self.state.usage,
        }
        (OUTPUT_DIR / "last_run.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

        print(f"[flow] brief -> output/brief.md   route={self.state.route}")
        # Key must match _usage_dict exactly. It read `cost_usd` here against a
        # dict that only ever held `cost_usd_upper_bound`, so .get() fell through
        # to the default and every run printed "cost=$0.000000" while
        # last_run.json carried the right figure all along.
        print(
            f"[flow] calls={record.get('successful_requests')}  "
            f"cost<=${record.get('cost_usd_upper_bound', 0):.6f} (upper bound, escalation-tier priced)"
        )


def _age_days(indexed_at: Any) -> int | None:
    """Days since `indexed_at`, or None if it is missing or unparseable.

    Missing metadata is treated as a miss rather than as fresh. A cache that
    silently serves undated material as current is the worst failure this
    architecture can produce - the brief looks well-sourced while being wrong.
    """
    if not indexed_at:
        return None
    try:
        stamp = datetime.fromisoformat(str(indexed_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).days


def _usage_dict(result: Any) -> dict[str, Any]:
    """Token counts from CrewOutput, plus a cost we compute ourselves.

    There is no cost field on the way in: CrewAI's `_extract_openai_token_usage`
    whitelists token counts only, and it never asks OpenRouter to include usage
    cost. Every dollar figure here is arithmetic over the §3 price table.
    """
    usage = getattr(result, "token_usage", None)
    if usage is None:
        return {}
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    from brief_crew.config import ESCALATION_MODEL

    return {
        "successful_requests": getattr(usage, "successful_requests", 0),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": getattr(usage, "total_tokens", 0),
        # Crew-level totals are not split by model, so this is an upper bound
        # priced at the escalation tier. For the per-agent split, subscribe a
        # BaseEventListener to LLMCallCompletedEvent - it carries `model`,
        # `task_id` and `agent_id`. See agents/08-observability.md.
        "cost_usd_upper_bound": compute_cost_usd(ESCALATION_MODEL, prompt, completion),
    }


# ---------------------------------------------------------------- entry points


def run_crew(topic: str = DEFAULT_TOPIC) -> Any:
    """Track A - the classroom crew. Start here.

    `verbose=True` on the Crew is the trace to watch: it is the only view you
    have of who handed off to whom. `token_usage.successful_requests` is the
    call count that turns "whether you'd keep it" into a number.
    """
    result = BriefCrew(track="A").crew().kickoff(inputs={"topic": topic})
    print("\n--- token usage ---")
    print(result.token_usage)
    return result


def kickoff(topic: str = DEFAULT_TOPIC) -> Any:
    """Track B - the Flow, with the warm-cache router."""
    flow = BriefFlow()
    return flow.kickoff(inputs={"topic": topic})


def plot() -> None:
    BriefFlow().plot("brief_flow")


if __name__ == "__main__":
    kickoff()
