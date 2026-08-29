"""Single source of truth for models, prices, embedding conventions and thresholds.

Every constant here is referenced by `agents/00-shared-config.md` or
`agents/06-retrieval-layer.md`. If a value changes, change it here and update the
spec section named in the comment - never in two places. The two embedding
prefixes in particular MUST stay paired: if they drift apart nothing raises,
retrieval quality just quietly degrades.
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------
# Models - 00-shared-config.md §3
# --------------------------------------------------------------------------
# OpenRouter is a NATIVE CrewAI provider. Do not install crewai[litellm]; the
# model string alone resolves base_url and the key from OPENROUTER_API_KEY.
CHEAP_MODEL = "openrouter/z-ai/glm-5.3-flash"
ESCALATION_MODEL = "openrouter/google/gemini-3.7-flash"

# USD per million tokens, (prompt, completion). Used to COMPUTE cost, because
# CrewAI discards OpenRouter's per-generation cost before it reaches any event.
PRICES: dict[str, tuple[float, float]] = {
    CHEAP_MODEL: (0.075, 0.250),
    ESCALATION_MODEL: (0.75, 3.75),
}

# --------------------------------------------------------------------------
# Embeddings - 00-shared-config.md §4, 06-retrieval-layer.md
# --------------------------------------------------------------------------
EMBED_MODEL = "google/gemini-embedding-2"
EMBED_DIMENSIONS = 768
EMBED_ENDPOINT = "https://openrouter.ai/api/v1/embeddings"

# gemini-embedding-2 removed the structured `task_type` field, so the
# document/query asymmetry is a STRING CONVENTION and ours to enforce. These two
# constants are the whole enforcement mechanism - never inline either one.
DOC_PREFIX = "Represent this document for retrieval: "
QUERY_PREFIX = "Represent this query for retrieving relevant documents: "

# --------------------------------------------------------------------------
# Vector store - 00-shared-config.md §5
# --------------------------------------------------------------------------
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "agentic-crew-ai-index")

# Retrieve 20 candidates so the reranker has something to discriminate between;
# return 5 so the agent's context does not bloat. 06-retrieval-layer.md.
RETRIEVE_CANDIDATES = 20
RETRIEVE_TOP_K = 5

# --------------------------------------------------------------------------
# Rerank - 00-shared-config.md §6
# --------------------------------------------------------------------------
RERANK_MODEL = "rerank-v4.0-fast"
RERANK_ENDPOINT = "https://api.cohere.com/v2/rerank"

# --------------------------------------------------------------------------
# The staleness gate - 06-retrieval-layer.md, the @router's only decision.
# All three must hold for cache_hit. Deterministic: zero LLM calls.
# --------------------------------------------------------------------------
MIN_RERANK_HITS = 3
MIN_RERANK_SCORE = 0.30  # on the RERANK score, not the cosine score
MAX_INDEX_AGE_DAYS = 60

# Chunking - well below the 8,192-token embedding ceiling, for retrieval
# precision rather than to respect a limit.
CHUNK_MIN_TOKENS = 200
CHUNK_MAX_TOKENS = 800
CHUNK_OVERLAP_TOKENS = 50


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Cost in USD from token counts and the §3 price table.

    CrewAI never sets ``extra_body={"usage": {"include": True}}``, and
    ``_extract_openai_token_usage`` whitelists only token counts - so
    OpenRouter's own cost figure never reaches us. Every dollar figure this
    project reports is computed here.
    """
    prompt_price, completion_price = PRICES.get(model, (0.0, 0.0))
    return (prompt_tokens * prompt_price + completion_tokens * completion_price) / 1_000_000


# --------------------------------------------------------------------------
# Validator - PRD §§9-10
# --------------------------------------------------------------------------
VALIDATOR_MIN_RERANK_HITS = 3
VALIDATOR_MIN_RERANK_SCORE = 0.35
VALIDATOR_MAX_INDEX_AGE_DAYS = 30
VALIDATOR_GITHUB_RATE_LIMIT_UNAUTH = 8
VALIDATOR_GITHUB_RATE_LIMIT_AUTHED = 24
VALIDATOR_FRAME_BATCH_SIZE = 100
VALIDATOR_PERSIST_QUEUE_CAPACITY = 4096
VALIDATOR_GATE_TIMEOUT_SECONDS = 1800

# --------------------------------------------------------------------------
# Validator rubric anchors - PRD §10.2, F15
#
# The anchors ARE the rubric. `validator_guardrails.anchor_problems` rejects a
# DimensionScore whose `anchor_matched` falls below ANCHOR_MATCH_THRESHOLD
# token overlap with the anchor for that dimension at that score, and the
# Synthesist prompt in `crews/validator_crew/config/tasks.yaml` quotes the same
# text so the model can reach it. Two readers, one constant: they live here
# because drift between the guardrail and the prompt silently unbinds the
# rubric - the exact failure §10.4 calls out ("the Synthesist writes a number
# and a paraphrase").
#
# ⚠️ These ladders were AUDITED AND REWRITTEN on 2026-08-29. PRD §10.2 writes
# out only the Demand ladder and labels it "Illustrative"; M/C/F/X never
# existed in the spec and were derived. The audit found the derivation - and
# the PRD's own illustration - unsound in six ways, all now fixed:
#
#   1. D=4 CONTRADICTED D=3. Anchor 3 ended "...but nobody describes a
#      workaround or a price paid" and anchor 4 read "Anchor 3, and ≥1
#      describes a manual workaround". No evidence state could satisfy 4.
#   2. D=0 scored on classification "ADJACENT", which is not a value of
#      `ThreadClassification`. Unscoreable against the schema.
#   3. D had an unreachable band: ≥3 threads whose newest was 24-36 months old
#      matched neither anchor 2 (not "all older than 36 months") nor anchor 3
#      (nothing "within 24 months").
#   4. X=4 was all but unreachable. It read "Anchor 3, and every repository
#      that covers most of the job is archived...", but anchor 3 asserted every
#      repository is partial - so the added clause was vacuous under the
#      natural reading and the 0-5 scale silently collapsed to 0-3-5.
#   5. X had a hole exactly where the PRD's most valuable output lives: a
#      repository that solves the WHOLE job but is archived or non-commercial
#      matched no anchor at all (X=0 needs it maintained and permissive, X=3
#      needs every repository partial). It is now X=2.
#   6. F=5 and X=5 were mutually exclusive by accident. Both are scored from
#      one GitHub result set, and "3 repositories cover the separable parts of
#      the v1" (F=5) contradicted "no repository addresses the core job"
#      (X=5). The distinction meant was COMPONENTS YOU BUILD WITH versus A
#      COMPLETE FREE SUBSTITUTE, and the wording did not carry it. It does
#      now: F counts `reusable repositories`, X keys on `free substitute`
#      (relevance SOLVES_ENTIRELY) and on whether any PARTIAL repository
#      covers most of the job on its own. F=5 with X=5 is the intended,
#      reachable state of "three libraries, each a separable part, no
#      substitute".
#
# Two rules make the ladders scoreable, and the Synthesist prompt states both:
#
#   - Score the HIGHEST level whose anchor is fully satisfied. Anchors phrased
#     "Anchor N, and ..." are cumulative; the ladders below are otherwise a
#     total, disjoint partition of the evidence states, so exactly one level
#     applies to any run.
#   - Partial satisfaction of anchor N scores N-1 (PRD §10.2).
#
# Every clause is checkable against a field the schemas actually carry:
# `Thread.classification` and `.date`; `Evidence.dated`; `Competitor.pricing`
# and `.vendor_owned`; `MarketFindings.paying_segments`; `Repo.relevance`,
# `.license_permits_commercial`, `.months_since_push` and `.archived`.
#
# `Repo.archived` appears in X=0 and X=2 only, and NON-BLOCKINGLY: the flag is
# tri-state, so "is not marked archived" is satisfied by both `False` and the
# `None` GitHub did not report, and the X floor behaves exactly as it would
# without the flag whenever it is absent. PRD §10.2 makes archived state
# load-bearing for that floor - an archived project is not maintained - and an
# anchor that let a dead project kill an idea would be the worst false REJECT
# this system can produce.
#
# ⚠️ `Thread.points` and `Thread.num_comments` are populated too, and no anchor
# uses them ON PURPOSE, not for want of data. PRD §10.2: "a single ReAct agent
# reads HN sentiment as approval of the IDEA rather than evidence of the
# PROBLEM. Anchoring D on workarounds and payments rather than upvotes is the
# substantive improvement." A popularity term in the Demand ladder would undo
# the one thing this rubric exists to do. For the same reason `Repo` carries no
# star count and none is wanted, and the PRD's "popular" in the X=0 kill is
# dropped rather than guessed at.
#
# Most clauses land on a counter `validator_guardrails.compute_evidence_counts`
# already recomputes from the branch lists and enforces against the model:
# `sentiment_problem_threads` is exactly this file's "problem thread",
# `feasibility_relevant_repos` is F=0/F=2's SOLVES_ENTIRELY-or-PARTIAL set,
# `feasibility_complete_repos` is X's "free substitute", and
# `market_paying_segments` is the D=5 and M=5 clause. ⚠️ One boundary is NOT
# covered: there is no counter for OFF_TOPIC threads, so nothing can recompute
# "usable thread" and D=0 (a search that reached the question and found no
# demand - a REJECT floor) is separated from D=1 (a search that missed) by the
# Synthesist alone. A `sentiment_usable_threads` counter would close it.
#
# The shorthand terms below are defined once in the Synthesist prompt and used
# to keep anchors short - short anchors stay far apart under the overlap
# metric, which is what stops the guardrail accepting the neighbouring level's
# text (`tests/validator/test_crews.py` asserts the separation):
#
#   usable thread        - a Thread not classified OFF_TOPIC.
#   problem thread       - a Thread classified HAS_PROBLEM, PAYS or
#                          BUILT_WORKAROUND.
#   reusable repository  - a Repo marked SOLVES_ENTIRELY or PARTIAL, with
#                          license_permits_commercial true and
#                          months_since_push <= 12.
#   free substitute      - a Repo marked SOLVES_ENTIRELY: it covers the whole
#                          core job on its own.
#   free product         - a product a market or sentiment source shows is
#                          available at no cost. Need not be a repository.
#   vendor owned         - Competitor.vendor_owned: owned by or bundled into a
#                          larger platform vendor rather than sold standalone.
#
# ⚠️ Level 1 is reserved for "the evidence does not reach this question" and is
# matched VERBATIM, never by inference. Weak demand *with* evidence is a 2.
# That reservation is what keeps composite_score and confidence measuring
# different things. Every ladder now states the branch condition that fires it,
# which the derived M/C/F/X ladders did not: without it the boundary between a
# fatal floor (M=0, F=0, X=0) and "we did not look hard enough" was undefined,
# and three of the four hard floors are decided on exactly that boundary.
#
# ⚠️ The level-1 clause is "the branch returned nothing usable", NOT the PRD's
# "or fewer than 3 usable threads". The "<3" test is deliberately dropped: it
# duplicates `DimensionScore.evidence_thin` (which IS len(evidence_urls) < 3)
# and the coverage term of confidence, and pushing it into the score as well
# is the one thing PRD §10.2 says must not happen - "this is what keeps
# composite_score and confidence measuring different things". It also
# collided head-on with D=2 ("1-2 threads state the problem"), so a run with
# two HAS_PROBLEM threads matched anchor 1 and anchor 2 at once.
# --------------------------------------------------------------------------
ANCHOR_MATCH_THRESHOLD = 0.85
LEVEL_ONE_ANCHOR = "Evidence does not reach this question"

# D - Demand. Is anyone actively trying to solve this today? Weight 0.30.
# D=0 is a hard floor (REJECT). Counted over SentimentFindings.sources, with
# the paying-segment clause at anchor 5 reading MarketFindings.paying_segments,
# so top demand needs the market branch to agree - a failed market branch caps
# D at 4, deliberately.
DEMAND_ANCHORS: dict[int, str] = {
    0: (
        "At least 1 usable thread, and none is a problem thread: nobody in the evidence "
        "describes having this problem."
    ),
    1: f"{LEVEL_ONE_ANCHOR} — the sentiment branch returned no usable thread.",
    2: (
        "1 or 2 problem threads, or at least 3 problem threads none of which is dated "
        "within 24 months."
    ),
    3: "At least 3 problem threads, and at least 1 of them dated within 24 months.",
    4: "Anchor 3, and at least 1 problem thread is classified BUILT_WORKAROUND or PAYS.",
    5: (
        "Anchor 4, and at least 5 problem threads are dated within 24 months, at least 2 of "
        "them classified BUILT_WORKAROUND or PAYS, and the market branch names at least 1 "
        "paying segment."
    ),
}

# M - Market. Is there money, and can you name whose? Weight 0.20.
# M=0 with D<=2 is a hard floor (REJECT). The PRD floor is "no money, no
# nameable buyer"; the operative half is the buyer, because the dimension's
# question is "can you name whose?" - money nobody can attribute to a segment
# is not an answer to it.
MARKET_ANCHORS: dict[int, str] = {
    0: (
        "The market branch returned sources, and none of them names a buyer segment for this "
        "problem."
    ),
    1: f"{LEVEL_ONE_ANCHOR} — the market branch returned no source.",
    2: "At least 1 market source names a buyer segment for this problem.",
    3: (
        "Anchor 2, and at least 1 source or competitor states a price or a budget that segment "
        "spends."
    ),
    4: "Anchor 3, and at least 2 market sources dated within 24 months name that same segment.",
    5: (
        "Anchor 4, and the market branch records that segment in paying_segments, supported by "
        "at least 3 sources dated within 24 months."
    ),
}

# C - Competitive room. Is the incumbent set beatable on a stated axis?
# Weight 0.20. C has no floor, so C=0 costs 0.4 of composite and nothing more.
# The ladder splits on whether ANY source states an axis of beatability;
# `vendor_owned` separates 0 from 2 below that line and gates 5 above it,
# because it is the only structured fact `Competitor` carries besides pricing.
COMPETITIVE_ROOM_ANCHORS: dict[int, str] = {
    0: (
        "At least 1 competitor is named, every named competitor is vendor owned, and no source "
        "states an axis on which any of them is beatable."
    ),
    1: f"{LEVEL_ONE_ANCHOR} — the market branch named no competitor.",
    2: (
        "The named competitors include at least 1 that is not vendor owned, but no source "
        "states an axis of beatability."
    ),
    3: "At least 1 source states an axis on which a named competitor is beatable.",
    4: (
        "Anchor 3, and at least 2 competitors are named, and at least 1 source dated within "
        "24 months describes a need the named incumbents do not serve."
    ),
    5: (
        "Anchor 4, and at least 2 sources dated within 24 months describe the same unserved "
        "need, and no named competitor is vendor owned."
    ),
}

# F - Feasibility. Can 2-3 engineers ship a v1? Weight 0.15.
# F=0 caps the run at NEEDS_WORK, never REJECT: "not buildable by this team" is
# a fact about the team, not the idea (PRD §10.2). F counts REUSABLE
# repositories - things you build WITH - which is why F=5 and X=5 can hold at
# once. ⚠️ F=0 is the most aggressive anchor here: it fires whenever the tech
# queries returned repositories and the branch marked none of them
# SOLVES_ENTIRELY or PARTIAL. That over-fires for a v1 whose stack is so
# ordinary nobody publishes it. It is deliberately mechanical anyway, because
# the alternative - "the scoped v1 cannot be shipped by two or three engineers
# on this evidence" - rested on no field at all, and an unreachable floor is
# worse than a cautious one. Review this one before the paid run.
FEASIBILITY_ANCHORS: dict[int, str] = {
    0: (
        "The feasibility branch returned repositories, and none of them is marked "
        "SOLVES_ENTIRELY or PARTIAL."
    ),
    1: f"{LEVEL_ONE_ANCHOR} — the feasibility branch returned no repository.",
    2: (
        "At least 1 repository is marked SOLVES_ENTIRELY or PARTIAL, and none of them is "
        "reusable."
    ),
    3: (
        "At least 1 repository in the feasibility evidence is reusable: marked SOLVES_ENTIRELY "
        "or PARTIAL, licensed for commercial use, and pushed within 12 months."
    ),
    4: "Anchor 3, and at least 2 reusable repositories are in the evidence.",
    5: (
        "Anchor 4, and at least 3 reusable repositories together cover the separable parts of "
        "the scoped v1."
    ),
}

# X - Headroom over free. Is the core already free and good? Weight 0.15.
# X=0 is a hard floor (REJECT) and the PRD calls it the most valuable output
# this system produces. X asks whether a COMPLETE FREE SUBSTITUTE exists, which
# is a different question from F's "are there parts to build with", even though
# both read the same GitHub results. The ladder is a total partition:
#   a free substitute exists, live and permissive        -> 0
#   a free substitute exists, dead or non-commercial     -> 2
#   no substitute, but a named free product covers most  -> 3
#   nothing free, except one PARTIAL repo covering most  -> 4
#   nothing free, PARTIAL repos are separable parts only -> 5
#   no relevant repository and no free product named     -> 1
HEADROOM_ANCHORS: dict[int, str] = {
    0: (
        "At least 1 free substitute repository is not marked archived, permits commercial use "
        "and was pushed within 12 months."
    ),
    1: (
        f"{LEVEL_ONE_ANCHOR} — no repository is marked SOLVES_ENTIRELY or PARTIAL and no free "
        "product is named."
    ),
    2: (
        "At least 1 free substitute repository exists, and every one of them is marked "
        "archived, licensed against commercial use, or was last pushed more than 12 months ago."
    ),
    3: (
        "No free substitute repository exists, and a market or sentiment source names a free "
        "product that covers most of the core job."
    ),
    4: (
        "No free substitute and no free product, but a repository marked PARTIAL covers most "
        "of the core job."
    ),
    5: (
        "No free substitute and no free product, and every repository marked PARTIAL covers "
        "only a separable part of the core job, with at least 1 such repository in the "
        "evidence."
    ),
}

# Keyed by DimensionCode. All five dimensions are anchored: an unanchored
# dimension accepts any prose at any score and is not a rubric.
RUBRIC_ANCHORS: dict[str, dict[int, str]] = {
    "D": DEMAND_ANCHORS,
    "M": MARKET_ANCHORS,
    "C": COMPETITIVE_ROOM_ANCHORS,
    "F": FEASIBILITY_ANCHORS,
    "X": HEADROOM_ANCHORS,
}

# --------------------------------------------------------------------------
# Mechanical confidence inputs - PRD §10.3, F11
#
# Confidence is "separate, mechanical, gating both directions". Mechanical
# means COMPUTED, so the three coverage ratios and the median market-source age
# are recomputed from the branch findings by
# `validator_guardrails.compute_confidence_inputs` and the model's assertions
# are rejected against them - the same treatment `compute_evidence_counts`
# already gives the counts.
#
# The denominator is the source count at which a branch is considered fully
# covered; the divisor converts an evidence age in days to months and matches
# `tools/github_feasibility._months_since_push`, so both age figures in the
# system use one calendar convention.
# --------------------------------------------------------------------------
VALIDATOR_COVERAGE_TARGET_SOURCES = 5
VALIDATOR_DAYS_PER_MONTH = 30.0

# --------------------------------------------------------------------------
# Reasoning effort - PRD F09, agents/00-shared-config.md §3
#
# ⚠️ `LLM(reasoning_effort=...)` is silently DROPPED for every OpenRouter model
# in CrewAI 1.15.18. `OpenAICompatibleCompletion` inherits
# `OpenAICompletion._prepare_completion_params`, which forwards the field only
# under `if self.is_o1_model` (llm/providers/openai/completion.py:1822), and
# `is_o1_model` is `"o1" in model.lower()` (:283). Neither CHEAP_MODEL nor
# ESCALATION_MODEL matches, so the setting never reaches the request body.
#
# `additional_params` IS merged into the request (:1800), and the OpenAI SDK's
# `chat.completions.create` takes no **kwargs - so an unknown top-level
# `reasoning=` key would raise TypeError. `extra_body` is the accepted kwarg
# that carries provider-specific JSON, and OpenRouter's unified reasoning
# control is the `reasoning` object it then receives. Hence the shape below.
# `openrouter_reasoning_params()` is the only place it is spelled out.
#
# F09: the Synthesist is the judgement step. It gets an EXPLICIT effort rather
# than the provider default, and explicitly NOT the Evaluator's "minimal"
# (agents/05-evaluator.md) - that setting is a cost control for a fixed
# checklist, and copying it onto a five-dimension rubric call is the mistake
# F09 names.
# --------------------------------------------------------------------------
VALIDATOR_SYNTHESIST_REASONING_EFFORT = "high"


def openrouter_reasoning_params(effort: str | None) -> dict[str, object]:
    """`LLM(additional_params=...)` that puts a reasoning effort on the wire.

    Returns an empty mapping for ``None`` so a caller can express "provider
    default" without a second code path.
    """
    if effort is None:
        return {}
    return {"extra_body": {"reasoning": {"effort": effort}}}


# --------------------------------------------------------------------------
# Human-gate expiry - PRD F03 and R-2
#
# F03: an unanswered gate past VALIDATOR_GATE_TIMEOUT_SECONDS is marked
# `expired` and a frame is pushed. The run is NOT failed and NOT
# auto-answered - it stays resumable, so a late reply still resumes it.
#
# R-2: `a gate_open with no gate_closed after timeout+60s raises an alert`.
# The 60 s is that grace period; the sweep interval is how often the server
# looks. Both belong here, never inlined at the call site.
# --------------------------------------------------------------------------
VALIDATOR_GATE_EXPIRY_ALERT_GRACE_SECONDS = 60
VALIDATOR_GATE_SWEEP_INTERVAL_SECONDS = 15.0

# --------------------------------------------------------------------------
# Validator branch cache - PRD §10.5, F17-F18
# --------------------------------------------------------------------------
VALIDATOR_FEASIBILITY_CACHE_ENABLED = os.getenv(
    "VALIDATOR_FEASIBILITY_CACHE_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
VALIDATOR_FEASIBILITY_MIN_RERANK_SCORE = 0.40
VALIDATOR_FEASIBILITY_MAX_INDEX_AGE_DAYS = 90

# --------------------------------------------------------------------------
# Service runtime - PRD §9.6
# --------------------------------------------------------------------------
try:
    RUN_CONCURRENCY = int(os.getenv("RUN_CONCURRENCY", "1"))
except ValueError as exc:
    raise ValueError("RUN_CONCURRENCY must be a positive integer") from exc
if RUN_CONCURRENCY < 1:
    raise ValueError("RUN_CONCURRENCY must be a positive integer")

# --------------------------------------------------------------------------
# WebSocket inbound control channel - PRD F27/F37
#
# The socket now carries operator commands (gate replies), not just the
# outbound frame stream, so every inbound message is treated as hostile until
# proved otherwise. These three bounds are the whole defence and belong here,
# never at the call site.
#
# WS_MAX_MESSAGE_BYTES caps a single inbound text/binary frame before it is
# handed to json.loads, so a multi-megabyte body is rejected without being
# parsed. 64 KiB is orders of magnitude above the largest legitimate gate
# reply (a handful of short scope fields) and far below anything that would
# strain the event loop.
#
# WS_MAX_GATE_FIELDS / WS_MAX_GATE_FIELD_CHARS bound the reply payload itself,
# so a well-formed-but-abusive message cannot push thousands of keys into a
# persisted gate answer.
# --------------------------------------------------------------------------
WS_MAX_MESSAGE_BYTES = 64 * 1024
WS_MAX_GATE_FIELDS = 32
WS_MAX_GATE_FIELD_CHARS = 8192

# --------------------------------------------------------------------------
# Fan-out performance targets - PRD section 13 and F42
#
# PRD risk R-3 makes these load-bearing rather than aspirational: if the
# measured speedup misses the target, the parallel implementation is withdrawn
# in favour of sequential execution. They live here so the benchmark harness
# and any future acceptance gate read the same numbers.
#
# The RSS ceiling is 400 MB against a 512 MB Render `starter` with a ~210 MB
# baseline. The comparison is strict (<), so exactly 400 MB is a miss.
# --------------------------------------------------------------------------
VALIDATOR_PERF_TARGET_FANOUT_SPEEDUP = 1.8
VALIDATOR_PERF_TARGET_PEAK_RSS_BYTES = 400 * 1024 * 1024
VALIDATOR_PERF_TARGET_GATE_RESUME_MS = 500.0
VALIDATOR_PERF_TARGET_DROPPED_FRAMES = 0
VALIDATOR_PERF_RUNS_PER_ARM = 5
VALIDATOR_PERF_SAMPLE_INTERVAL_S = 0.025

# --------------------------------------------------------------------------
# Frame persistence cadence - PRD F31
#
# Frames enter a bounded queue and are written by a separate batching thread
# so database latency never reaches a CrewAI event handler. The writer wakes
# on whichever comes first: VALIDATOR_FRAME_BATCH_SIZE frames, or this
# interval. Batching on size alone stalls the last partial batch of a quiet
# run indefinitely, which is what a reconnecting client sees as a gap.
# --------------------------------------------------------------------------
VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS = 0.25

# --------------------------------------------------------------------------
# In-memory run retention - PRD F30
#
# RunRegistry keeps a record per run for replay and status. Nothing pruned
# them, so the map grew for the lifetime of the process. Terminal runs older
# than this are evicted from memory; their durable rows and frames are
# untouched, so a later GET still recovers them from storage.
# --------------------------------------------------------------------------
VALIDATOR_RUN_RETENTION_SECONDS = 6 * 60 * 60

# --------------------------------------------------------------------------
# Fan-out execution mode - PRD F04 and risk R-3
#
# R-3's escape hatch: if the measured speedup misses
# VALIDATOR_PERF_TARGET_FANOUT_SPEEDUP, the parallel fan-out is withdrawn in
# favour of sequential execution of the same six agents - same graph, worse
# latency. Parallel stays the shipped default until measurement says
# otherwise, and the env var makes the withdrawal a deploy-time flip rather
# than a code edit.
#
# The turnstile timeout is the upper bound on how long one branch waits for
# its turn before taking it anyway. A stuck branch must degrade to parallel
# behaviour, never deadlock a run queue.
# --------------------------------------------------------------------------
VALIDATOR_SEQUENTIAL_BRANCHES = os.getenv(
    "VALIDATOR_SEQUENTIAL_BRANCHES", "false"
).strip().lower() in {"1", "true", "yes", "on"}
VALIDATOR_BRANCH_TURN_TIMEOUT_SECONDS = 900.0
