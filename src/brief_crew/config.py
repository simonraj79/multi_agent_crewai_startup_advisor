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
