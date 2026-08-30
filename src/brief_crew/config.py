"""Single source of truth for models, prices, embedding conventions and thresholds.

Every constant here is referenced by `agents/00-shared-config.md` or
`agents/06-retrieval-layer.md`. If a value changes, change it here and update the
spec section named in the comment - never in two places. The two embedding
prefixes in particular MUST stay paired: if they drift apart nothing raises,
retrieval quality just quietly degrades.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

# --------------------------------------------------------------------------
# Models - 00-shared-config.md §3
# --------------------------------------------------------------------------
# OpenRouter is a NATIVE CrewAI provider. Do not install crewai[litellm]; the
# model string alone resolves base_url and the key from OPENROUTER_API_KEY.
CHEAP_MODEL = "openrouter/z-ai/glm-5.3-flash"
ESCALATION_MODEL = "openrouter/google/gemini-3.7-flash"

# USD per million tokens, (prompt, completion). Used to ESTIMATE cost, because
# CrewAI discards OpenRouter's per-generation cost before it reaches any event.
# Keys are written the way this project configures a model - with the
# `openrouter/` provider prefix - and `resolve_price_model` below accepts the
# de-prefixed spelling CrewAI actually reports.
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


# CrewAI hands a NATIVE provider the model with its provider prefix already
# stripped: `LLM.__new__` sets `model_string = model_part` on the openrouter
# branch (crewai/llm.py), so `LLMCallCompletedEvent.model` reads
# "z-ai/glm-5.3-flash" while every key in PRICES reads
# "openrouter/z-ai/glm-5.3-flash". `PRICES.get(model, (0.0, 0.0))` therefore
# missed on every real call, and a (0.0, 0.0) default turned "I have no price
# for this model" into "this call was free" - which is how the first paid run
# reported cost_usd 0.0 over 128,069 genuinely billed tokens.
#
# The index accepts both spellings in both directions, because the LiteLLM
# fallback path still reports the prefixed name, and casefolds because an
# OpenRouter slug is lowercase by convention rather than by enforcement.
_OPENROUTER_PREFIX = "openrouter/"


def _build_price_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for key in PRICES:
        folded = key.casefold()
        index[folded] = key
        if folded.startswith(_OPENROUTER_PREFIX):
            index[folded[len(_OPENROUTER_PREFIX) :]] = key
    return index


PRICE_MODEL_INDEX: dict[str, str] = _build_price_index()


def resolve_price_model(model: str | None) -> str | None:
    """The PRICES key a reported model name refers to, or None if it has none."""
    name = str(model or "").strip().casefold()
    if not name:
        return None
    resolved = PRICE_MODEL_INDEX.get(name)
    if resolved is None and name.startswith(_OPENROUTER_PREFIX):
        resolved = PRICE_MODEL_INDEX.get(name[len(_OPENROUTER_PREFIX) :])
    return resolved


def compute_cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float | None:
    """ESTIMATED cost in USD from token counts and the §3 price table.

    An estimate, not an invoice. CrewAI never sets
    ``extra_body={"usage": {"include": True}}`` and
    ``_extract_openai_token_usage`` whitelists only token counts, so
    OpenRouter's own per-generation cost figure never reaches any event. Every
    dollar figure this project reports is computed here from the published
    per-million rates above, and the billed total can differ: cached-prompt
    discounts, BYOK fees, per-request rounding, and any price change made after
    this table was written all move the real number.

    Returns ``None`` - never 0.0 - for a model the table does not price,
    because "no price on file" and "this call was free" are different facts and
    reporting the second for the first is the whole of the bug above.
    """
    key = resolve_price_model(model)
    if key is None:
        return None
    prompt_price, completion_price = PRICES[key]
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
# `market_paying_segments` is the D=5 and M=5 clause. `sentiment_usable_threads`
# now counts threads that are not OFF_TOPIC, so the D=0/D=1 boundary is
# arithmetic rather than the Synthesist's alone.
#
# ⚠️ A floor needs TWO mechanical clauses, not one: what the branch found,
# and that the branch looked hard enough for the finding to mean anything.
# The 2026-08-30 review (`docs/rubric-review.md`, F2) measured a final,
# non-provisional `REJECT - no demand` at confidence 0.60 built on ONE
# off-hand Hacker News comment, because D=0 asked only for "1 usable thread
# and no problem thread". Worse, `sentiment_coverage` counts PROBLEM threads,
# so it is 0 exactly when D=0 fires and the low-confidence override is
# structurally unable to intervene. D=0 therefore now requires
# `RUBRIC_FLOOR_MIN_USABLE_THREADS` usable threads, and M=0 additionally
# requires that the Market Analyst recorded no paying segment - the one
# structured fact that contradicts "none of them names a buyer segment".
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
#   free product         - a named Competitor whose `free_core_coverage`
#                          records how much of the core job a no-cost
#                          offering covers: WHOLE_JOB, MOST_OF_JOB or
#                          SEPARABLE_PART. `None` means the market branch
#                          did not establish one, which is a different
#                          claim from "nothing free covers this".
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
# ⚠️ D=1 carries the PRD's "fewer than 3 usable threads" clause again, and
# ONLY in conjunction with "and no problem thread". The unconditional "<3"
# test stays dropped for the reasons the audit gave: it duplicates
# `DimensionScore.evidence_thin` and the coverage term of confidence, and
# pushing thinness into the score is the one thing PRD §10.2 says must not
# happen - "this is what keeps composite_score and confidence measuring
# different things"; and unconditionally it collided head-on with D=2 ("1-2
# threads state the problem"), so a run with two HAS_PROBLEM threads matched
# anchor 1 and anchor 2 at once. The conjunct removes that collision: D=2
# needs at least one problem thread and D=1 now needs none, so the two stay
# disjoint. The narrow reintroduction is forced by arithmetic rather than by
# taste. Raising D=0 to 3 usable threads orphans the states "1 or 2 usable
# threads, none of them a problem thread", and they belong nowhere else: D=2
# requires a problem thread. Left unhoused they are a DEADLOCK, not a dead
# band - `zero_ok` false, `one_ok` false and the ceiling at 1 means every
# score 0-5 is rejected and the synthesis task can never pass its guardrail.
# Two on-topic comments in which nobody states the problem is exactly "the
# evidence does not reach this question", so level 1 is where they go, and a
# branch that did reach the question still cannot claim 1.
# --------------------------------------------------------------------------
ANCHOR_MATCH_THRESHOLD = 0.85
LEVEL_ONE_ANCHOR = "Evidence does not reach this question"

# D - Demand. Is anyone actively trying to solve this today? Weight 0.30.
# D=0 is a hard floor (REJECT), and it fires only when the branch reached the
# question: at least RUBRIC_FLOOR_MIN_USABLE_THREADS on-topic threads, none of
# them a problem thread. Counted over SentimentFindings.sources, with
# the paying-segment clause at anchor 5 reading MarketFindings.paying_segments,
# so top demand needs the market branch to agree - a failed market branch caps
# D at 4, deliberately.
DEMAND_ANCHORS: dict[int, str] = {
    0: (
        "At least 3 usable threads, and none of them is a problem thread: nobody in the "
        "evidence describes having this problem."
    ),
    1: (
        f"{LEVEL_ONE_ANCHOR} — the sentiment branch returned fewer than 3 usable threads "
        "and no problem thread."
    ),
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
# ⚠️ "None of them names a buyer segment" cannot be settled without reading
# the sources, so M=0 remains the one floor of the four that is not fully
# countable (`docs/rubric-review.md` F3). One necessary condition IS
# countable and is now enforced: a branch that recorded a paying segment has,
# by `market_task`'s own definition of that field, an attributed source
# naming a buyer segment, so `market_paying_segments >= 1` contradicts this
# anchor. That bound needs no change to the anchor text, which is why it is
# taken here and the review's second conjunct - "at least 3 sources" - is
# not: raising the count would orphan the 1-2 source states the way D=0
# orphaned the 1-2 thread states, and M=1 is reserved for a branch that
# returned nothing at all.
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
# both read the same GitHub results.
#
# ⚠️ The ladder used to run on GitHub repositories at 0 and 2 and on free
# PRODUCTS at 3, and no schema field could express a product. The 2026-08-30
# review (F1) measured the consequence: a live, free, named product covering
# most of the core job scored X=3, cleared `min(scores) >= 3` and returned
# `VALIDATE` at composite 9.4 and confidence 0.90, while an ARCHIVED
# repository doing the same job scored 2 and blocked the idea. The dead
# competitor killed the run and the living one did not. `Competitor` now
# carries `free_core_coverage`, so both halves of the ladder read a structured
# field and the severity ordering is one ordering:
#   a free substitute repo, live and permissive, OR a free
#     product covering the whole core job                 -> 0
#   a free substitute repo, dead or non-commercial, OR a
#     free product covering most of the core job          -> 2
#   no substitute, and every named free product covers
#     no more than a separable part                       -> 3
#   nothing free, except one PARTIAL repo covering most    -> 4
#   nothing free, PARTIAL repos are separable parts only   -> 5
#   no relevant repository and no free product named       -> 1
# The 0/2 split asks one question of both halves - is the free thing ALIVE -
# and 3 closes the band the review found empty at F5, where a free product
# covering part of the job satisfied no anchor at all.
HEADROOM_ANCHORS: dict[int, str] = {
    0: (
        "At least 1 free substitute repository is not marked archived, permits commercial use "
        "and was pushed within 12 months, or at least 1 free product covers the whole core job."
    ),
    1: (
        f"{LEVEL_ONE_ANCHOR} — no repository is marked SOLVES_ENTIRELY or PARTIAL and no free "
        "product is named."
    ),
    2: (
        "At least 1 free substitute repository exists, and every one of them is marked "
        "archived, licensed against commercial use, or was last pushed more than 12 months "
        "ago; or at least 1 free product covers most of the core job."
    ),
    3: (
        "No free substitute repository exists, and at least 1 free product is named, none "
        "covering more than a separable part of the core job."
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
# Making the ladders binding on arithmetic - F16
#
# `anchor_problems` only checks that `anchor_matched` is the TEXT of the anchor
# for the score claimed. It cannot tell whether the EVIDENCE satisfies that
# text, so a Synthesist could quote the D=5 anchor verbatim over two stale
# threads and pass every mechanical check. Now that the ladders score on terms
# `compute_evidence_counts` recomputes, `score_support_problems` closes that:
# it derives, per dimension, the highest level the counted evidence can carry
# and rejects a claim above it.
#
# The three numbers the anchors quote live here, not in the checker.
#
# ⚠️ `RUBRIC_RECENCY_GRACE_MONTHS` is a deliberate slackening, in the only
# direction that is safe. The bound is an UPPER bound on a claim, so counting
# one extra source as recent can only let an honest score through; refusing one
# is what produces a false rejection. Two things make the boundary fuzzy and
# neither is the Synthesist's fault: `VALIDATOR_DAYS_PER_MONTH` makes 24
# "months" 720 days, about 23.7 calendar months, so a model reasoning in
# calendar months disagrees with this file near the edge; and the anchors are
# written against the scope's `as_of` while the guardrail runs at wall-clock
# now. A guardrail that fires on honest scores gets disabled, which is worse
# than no guardrail at all.
# --------------------------------------------------------------------------
RUBRIC_RECENCY_MONTHS = 24
RUBRIC_RECENCY_GRACE_MONTHS = 1.0
RUBRIC_REUSABLE_MAX_PUSH_MONTHS = 12

# How much on-topic evidence a branch must have returned before its REJECT
# floor can fire. D=0 says "the branch looked and nobody has this problem",
# and that sentence is only true of a branch that looked: one on-topic
# comment in which nobody happens to state a problem is not a finding about
# the world. 3 is a judgement, not a derivation - it is the unit the rest of
# the Demand ladder already counts in ("at least 3 problem threads" at D=3)
# and the number `docs/rubric-review.md` proposes for the same repair on M
# and F. It bounds a floor only: it never raises a score, and D=1 absorbs
# every state it excludes.
RUBRIC_FLOOR_MIN_USABLE_THREADS = 3

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

# How long a resubmission waits for a still-settling run future before it
# refuses the caller.
#
# The gate is published to the client *before* the worker thread has returned
# from the run: _mark_pending marks the run WAITING, writes the durable gate
# and pushes GATE_OPEN, and only then does _execute return and its future
# complete. A reply that lands inside that window used to be refused outright
# even though the server had already accepted it durably, which wedged the run
# in RUNNING with no gate to answer. _submit now waits here instead.
#
# Seconds, because that tail is milliseconds: it queues frames rather than
# writing them and does no network I/O. Anything still running after this
# window is a genuinely busy run, and refusing it is the correct answer.
try:
    RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS = float(
        os.getenv("RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS", "5.0")
    )
except ValueError as exc:
    raise ValueError(
        "RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS must be a positive number"
    ) from exc
if RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS <= 0:
    raise ValueError("RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS must be a positive number")

# --------------------------------------------------------------------------
# Public-API admission control - the deployed service is UNAUTHENTICATED
#
# https://agentic-crew-ai-api.onrender.com serves an open demo: anyone may POST
# /api/sessions/{id}/runs and the owner pays for what that run spends. There is
# deliberately NO mandatory authentication - a login would end the demo - so
# everything below is defence in depth, chosen to be invisible to one honest
# visitor pressing Launch and expensive for a script.
#
# What each layer actually buys, honestly:
#
#   MAX_REQUEST_BODY_BYTES / MAX_RUN_INPUT_* bound the PROMPT. The
#     `confirm_scope` gate already stops the expensive half of a validator run
#     (three research branches, Firecrawl, Synthesist and Reporter all sit
#     behind it), so an anonymous request buys exactly one escalation-tier LLM
#     call - but `inputs` was `dict[str, Any]` with no length bound at all, so
#     the PROMPT half of that call was attacker-controlled and a megabyte of
#     text turned a fraction of a cent into dollars. Bounding the input is what
#     makes the cost of an anonymous request a constant.
#   MAX_QUEUED_RUNS bounds AVAILABILITY, and it is the layer that holds against
#     a determined attacker, because it is keyless. RUN_CONCURRENCY bounds
#     parallelism, not admission: CPython's ThreadPoolExecutor has an unbounded
#     internal work queue, so a flood of accepted runs starved the owner's own
#     run for as long as the flood lasted.
#   RUN_RATE_LIMIT_* is a courtesy limiter, NOT a security control. See its own
#     note below.
# --------------------------------------------------------------------------


def _env_positive_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Read a bounded integer knob, refusing a bad value at import."""
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer >= {minimum}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _env_positive_float(name: str, default: float) -> float:
    """Read a strictly positive float knob, refusing a bad value at import."""
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean knob the way an operator would write one."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# The whole HTTP request body, refused at the ASGI edge on Content-Length
# before FastAPI parses anything. 64 KiB matches WS_MAX_MESSAGE_BYTES, so the
# two transports into this service agree on what "too big" means. Every legal
# body here is a few hundred bytes: a workflow id, an idea, a gate reply.
# WARNING: a chunked request sends no Content-Length and slips past this check.
# The per-field bounds below are what actually stops that one, which is why
# both layers exist.
MAX_REQUEST_BODY_BYTES = 64 * 1024

# One run input - `inputs.idea` or `inputs.topic` - in characters.
#
# 2,000 is deliberately generous: a real startup idea is a sentence or two, the
# frontend's own default idea is 62 characters, and PRD section 10.1's scoping
# prompt wants a description, not a document. 2,000 leaves roughly a 30x margin
# over a typical submission while capping the Scoper's prompt at ~500 tokens -
# and that number is the point, because the prompt is the only
# attacker-controlled term in the cost of an anonymous request.
MAX_RUN_INPUT_CHARS = 2000

# `inputs` is typed `dict[str, Any]`, so the named input is not the only way in.
# These bound the mapping itself: a key count no legitimate client approaches
# (the UI sends exactly one key), and a total JSON size that caps the durable
# run row, the flow state and the frame payloads the run will carry.
MAX_RUN_INPUT_KEYS = 16
MAX_RUN_INPUT_BYTES = 8 * 1024

# Runs queued or executing, across every caller, above which a NEW run is
# refused with 429. Gate replies and resumes are never refused by this: they
# belong to a run the caller already holds, and refusing one would strand a
# human at a gate.
#
# 8 is sized off what the queue actually drains. A queued run holds a slot only
# until it reaches the scope gate - one escalation call, ~10-30 s - because a
# run WAITING on a human has already returned its worker thread. At
# RUN_CONCURRENCY=1 a full queue therefore clears in a few minutes, so eight
# simultaneous strangers all get served and the ninth is told to come back
# instead of silently joining an unbounded queue behind them.
MAX_QUEUED_RUNS = _env_positive_int("MAX_QUEUED_RUNS", 8)

# The Retry-After sent with an admission refusal. Advisory, and deliberately a
# fixed hint rather than a computed queue-drain estimate: the live queue depth
# of a public endpoint is not a number to hand back to whoever is flooding it.
RUN_ADMISSION_RETRY_AFTER_SECONDS = 30

# --------------------------------------------------------------------------
# The terminal result - what a COMPLETED run hands back over HTTP
# --------------------------------------------------------------------------
# `SerializerLimits.max_string` (4,096) exists to bound a STREAMING FRAME: one
# of up to 2,000 in a ring, fanned out to every live subscriber, where nothing
# downstream needs a whole document. Until this constant existed it was also
# what bounded the run's final deliverable, because `RunRecord.mark_completed`
# clipped the result with the frame serializer. So the first paid run's
# validation report came back cut off mid-URL - "...(https://www.mentimeter.com
# /blog/educatio" - and citation closure, the one thing the paid acceptance run
# exists to establish, could not be assessed at all. `output/validation.md` is
# ephemeral container disk on Render, so the API response is the only copy of
# that report anyone can reach.
#
# 64 KiB of characters, and the number is not free-hand:
#   * it is exactly `service/persistence.py::MAX_STRING_LENGTH`, the durable
#     layer's own per-string ceiling. A larger bound would be accepted in
#     memory and then REJECTED at write time by `_sanitize_json`, which raises
#     rather than truncates - losing the whole run row instead of the tail of
#     one string;
#   * a real report is far smaller. The first paid run spent 46,787 completion
#     tokens across eleven calls for the WHOLE pipeline; the Reporter's
#     markdown body is one of those calls, order 10-15 KB. This is roughly a
#     4-6x margin over a real report, not a guess at one;
#   * it is deliberately NOT unbounded. The database is `basic_256mb` with no
#     retention policy, and 64 KiB is the worst case rather than the typical
#     row: ~4,000 completed runs to fill the disk at the ceiling, ~20,000 at a
#     realistic 12 KB.
MAX_RUN_RESULT_BODY_CHARS = 64 * 1024

# The result keys that ARE the deliverable, and so earn the bound above.
# Everything else in a flow result stays on the frame limit, because the
# generic clip's job is to bound an object nobody has read: one 64 KiB string
# is a report, and sixty-four of them is a way to fill a 256 MB database. This
# is why the bypass is per-key rather than a bigger `SerializerLimits`.
# `ValidationReport.markdown_body` is the only member today.
RUN_RESULT_BODY_KEYS: tuple[str, ...] = ("markdown_body",)

# --------------------------------------------------------------------------
# Per-client rate limit, on run creation only
#
# WARNING: read this before trusting it. This is an IN-PROCESS token bucket in
# ONE instance. It is not a distributed rate limit and it is not a security
# control:
#
#   - It resets on every deploy and every restart, and Render restarts a
#     starter instance for its own reasons.
#   - If the service is ever scaled past one instance, each instance keeps its
#     own bucket and the effective limit multiplies by the instance count.
#   - The key is an IP, and behind Render's proxy the only source for that is
#     X-Forwarded-For, which the client writes. Anyone willing to rotate a
#     header bypasses it completely.
#
# What it does buy: a runaway client loop, a retry storm from a broken
# frontend, and casual scripted abuse all stop costing money, and they stop
# without a legitimate visitor ever noticing. The layer that holds against
# someone who is actually trying is MAX_QUEUED_RUNS above, because that one is
# keyless and cannot be rotated around. A real limiter later means Redis or a
# proxy rule, not a bigger number here.
#
# The numbers are deliberately loose, because this is fairness rather than the
# cost bound. The COST bound is elsewhere and it is arithmetic: at
# RUN_CONCURRENCY=1 the server drains one scope call at a time, so total
# throughput is capped by the queue no matter how many clients ask. What a
# per-client bucket adds is that one caller cannot occupy that queue.
#
# 10 runs per 60 s is a burst of ten, refilling at one run per 6 s. A demo
# visitor does not produce ten launches in a minute; the Playwright E2E suite
# produces five, and the headroom over it is deliberate - a limiter that fails
# the project's own tests would just be turned off. Set
# RUN_RATE_LIMIT_MAX_RUNS=0 to disable it, which is the intended escape hatch
# for load testing against a private deployment.
# --------------------------------------------------------------------------
RUN_RATE_LIMIT_MAX_RUNS = _env_positive_int("RUN_RATE_LIMIT_MAX_RUNS", 10, minimum=0)
RUN_RATE_LIMIT_WINDOW_SECONDS = _env_positive_float(
    "RUN_RATE_LIMIT_WINDOW_SECONDS", 60.0
)

# Distinct client keys held at once, evicted least-recently-seen first, and the
# ceiling on how much of a key is kept. The map is keyed by attacker-supplied
# text, so it needs its own bounds or the limiter becomes the
# memory-exhaustion bug it was added to prevent.
RUN_RATE_LIMIT_MAX_CLIENTS = 4096
RUN_RATE_LIMIT_KEY_MAX_CHARS = 64

# Trust the leftmost X-Forwarded-For entry as the client identity.
#
# On by default because this service is deployed behind Render's proxy, where
# the socket peer IS the proxy: without this every visitor on earth shares one
# bucket and the first person to click Launch rate-limits everybody else. That
# is a worse failure than the spoofing it admits, and the note above is already
# explicit that spoofing defeats this limiter. Turn it OFF wherever the service
# is reachable directly and the peer address is the real one.
RUN_RATE_LIMIT_TRUST_FORWARDED_FOR = _env_flag(
    "RUN_RATE_LIMIT_TRUST_FORWARDED_FOR", True
)

# --------------------------------------------------------------------------
# Unattended runs
# --------------------------------------------------------------------------
# Whether this deployment will accept `gates: "auto"` - a run that answers its
# own scope and verdict gates and executes the whole pipeline unattended.
#
# Default OFF, and that is a cost decision rather than a security one. A gated
# run stops after the Scoper: one escalation-tier call, and if nobody replies
# the run simply expires. Human inaction is the de facto spend cap, which is
# why an unauthenticated Launch button was ever survivable. An auto run has no
# such brake - Scoper, three branches with live Firecrawl/HN/GitHub calls,
# Synthesist at reasoning_effort=high, then Reporter, bounded only by the
# agents' summed max_iter.
#
# RUN_RATE_LIMIT_MAX_RUNS was calibrated against runs that stop at the first
# gate. Ten *complete* pipelines per minute per client is a different order of
# spend, so leave this off anywhere the endpoint is public and turn it on for
# local and CI use, where it is the only way to get an end-to-end run without
# a human sitting at the console.
VALIDATOR_ALLOW_AUTO_GATES = _env_flag("VALIDATOR_ALLOW_AUTO_GATES", False)

# Keys a caller must never be able to set through the free-form `inputs` map.
# `ValidatorState` is a pydantic model and CrewAI merges kickoff inputs into it
# wholesale (`{**current_state, **inputs}` then `model_validate`), so every
# field on that state was reachable from the public request body - including
# `no_gates`, which turned a two-gate run into an unattended one with no flag,
# no validation and no record. Control belongs in a declared request field;
# these names are stripped from `inputs` before it reaches the flow.
#
# The public surface is deliberately tiny: the one prompt each workflow reads,
# plus the cache namespace. `topic` is Brief Crew's; `idea` is the validator's.
PUBLIC_RUN_INPUT_KEYS: frozenset[str] = frozenset({"idea", "topic", "namespace"})

# Everything else `ValidatorState` declares. Listed by hand because `config.py`
# cannot import `validator_flow` (that import runs the other way), and pinned by
# `tests/service/test_gates_mode.py::ReservedKeyCoverageTests`, which fails if a
# new state field is added without a decision about whether the public endpoint
# may set it. That test is the point of this constant: the first version of it
# named two keys while its own comment claimed to describe all of them, and the
# fourteen it missed included `feasibility_cache_enabled` - a deployment env
# knob (`VALIDATOR_FEASIBILITY_CACHE_ENABLED`) that an anonymous caller could
# therefore flip per run - and `source_run_id`, which stamps the attribution on
# indexed cache evidence.
#
# The model-shaped slots (`scope`, `verdict`, `report`, the findings) are
# reserved for a different reason: a caller-supplied value of the wrong shape
# raises inside CrewAI's `_initialize_state` and fails the run *after* it has
# taken an admission slot.
RESERVED_RUN_INPUT_KEYS: frozenset[str] = frozenset(
    {
        # Control knobs.
        "no_gates",
        "sequential_branches",
        "feasibility_cache_enabled",
        "source_run_id",
        # Result slots the flow fills in itself.
        "scope",
        "market",
        "sentiment",
        "feasibility",
        "verdict",
        "report",
        # Gate machinery.
        "scope_gate_reply",
        "scope_revision",
        "scope_route",
        "verdict_gate_reply",
        "verdict_revision",
        "verdict_route",
    }
)

# --------------------------------------------------------------------------
# Interactive API documentation
#
# /docs, /redoc and /openapi.json hand a reader the exact body shape of every
# endpoint, including the one that spends money. That is useful locally and it
# is free reconnaissance on a public deployment, so it is OFF by default and ON
# for a synthetic (no-cost) app - which is what local development and the E2E
# suite run. Set EXPOSE_API_DOCS=1 to serve them from a paid instance
# deliberately.
#
# This is obscurity, not security: the endpoints are unchanged and a reader can
# still find them. It is listed as what it is - one cheap subtraction from an
# attacker's convenience, not a control.
# --------------------------------------------------------------------------
EXPOSE_API_DOCS = _env_flag("EXPOSE_API_DOCS", False)

# --------------------------------------------------------------------------
# Cross-origin access - PRD section 9.6, F44
#
# Locally this is invisible: Vite serves the app and proxies /api and /ws to
# 127.0.0.1:8000 (frontend/vite.config.ts), so every request is same-origin and
# no CORS header is ever involved. In production the frontend is a SEPARATE
# static site (render.yaml: agentic-crew-ai-web) that calls the API by absolute
# URL through VITE_API_URL, so every request IS cross-origin and the browser
# discards the response unless the API names the caller's origin.
#
# CORS_ALLOW_ORIGINS is a comma-separated list of ORIGINS - scheme, host and
# optional port, nothing else:
#
#     CORS_ALLOW_ORIGINS=https://agentic-crew-ai-web.onrender.com
#     CORS_ALLOW_ORIGINS=https://studio.example.com,http://localhost:5173
#
# The default is EMPTY, which is no cross-origin access at all. Same-origin
# traffic and the Vite proxy do not go through this list, so nothing local
# changes; what an empty default buys is that a new deployment fails CLOSED and
# the operator names the frontend origin deliberately, instead of the service
# shipping "*" and nobody ever revisiting it.
#
# A trailing slash is the single most common way this is got wrong. Starlette
# compares the browser's Origin header against these strings EXACTLY, and a
# browser never sends a trailing slash, so "https://x.onrender.com/" matches
# nothing and fails in a way that looks like the middleware is missing. It is
# refused here at import, with the corrected value in the message, rather than
# normalised away: what the operator wrote and what the service enforces should
# never be two different things.
#
# The literal "*" is accepted as the WHOLE list for an operator who genuinely
# wants an open API. That is safe only because CORS_ALLOW_CREDENTIALS is False
# below - see the note there before changing either.
# --------------------------------------------------------------------------

CORS_WILDCARD = "*"


def _normalise_cors_origin(candidate: str) -> str:
    """Return one canonical origin, or raise naming what to write instead.

    An origin is scheme + host + optional port. Anything else - a path, a
    trailing slash, a query, credentials, a scheme no browser will send from a
    page - can never equal an Origin header, so accepting it would only mean
    shipping a rule that silently matches nothing.
    """
    origin = candidate.strip()
    if origin == CORS_WILDCARD:
        return origin

    parts = urlsplit(origin)
    corrected = ""
    if parts.scheme in {"http", "https"} and parts.hostname:
        host = parts.hostname.lower()
        if ":" in host:  # IPv6 literal, which urlsplit hands back unbracketed
            host = f"[{host}]"
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError(
                f"CORS_ALLOW_ORIGINS entry {origin!r} has an invalid port"
            ) from exc
        corrected = f"{parts.scheme}://{host}"
        if port is not None:
            corrected = f"{corrected}:{port}"

    if not corrected:
        raise ValueError(
            f"CORS_ALLOW_ORIGINS entry {origin!r} is not an origin; write a "
            "scheme, host and optional port, e.g. "
            "https://studio.example.com or http://localhost:5173"
        )
    if "@" in parts.netloc:
        raise ValueError(
            f"CORS_ALLOW_ORIGINS entry {origin!r} carries credentials; "
            f"write {corrected} instead"
        )
    if parts.path in {"", "/"} and not parts.query and not parts.fragment:
        if parts.path == "/":
            raise ValueError(
                f"CORS_ALLOW_ORIGINS entry {origin!r} has a trailing slash, "
                "which no browser ever sends in an Origin header; write "
                f"{corrected} instead"
            )
        return corrected
    raise ValueError(
        f"CORS_ALLOW_ORIGINS entry {origin!r} is a URL, not an origin; drop "
        f"the path and any query or fragment and write {corrected} instead"
    )


def _parse_cors_allow_origins(raw: str) -> tuple[str, ...]:
    """Parse the comma-separated env value into canonical, de-duplicated origins."""
    origins: list[str] = []
    for chunk in raw.split(","):
        if not chunk.strip():
            continue
        origin = _normalise_cors_origin(chunk)
        if origin not in origins:
            origins.append(origin)
    if CORS_WILDCARD in origins and len(origins) > 1:
        raise ValueError(
            "CORS_ALLOW_ORIGINS mixes '*' with named origins; '*' already "
            "allows every origin, so the named ones would be dead text"
        )
    return tuple(origins)


CORS_ALLOW_ORIGINS: tuple[str, ...] = _parse_cors_allow_origins(
    os.getenv("CORS_ALLOW_ORIGINS", "")
)

# Deliberately a constant and NOT an env var. Access-Control-Allow-Credentials
# is what makes "*" dangerous, because it turns every page on the internet into
# an authenticated caller. This service has no ambient credential to abuse: no
# cookie, no session middleware, no Authorization header is read anywhere in
# service/app.py. A run is reached by an unguessable uuid4 run_id the caller
# must already hold, and the socket additionally requires a matching
# session_id; a browser sends neither of those automatically, so a hostile page
# gains nothing from an allowed origin. Leaving credentials off is therefore
# free, and it is what keeps the "*" escape hatch above survivable.
# If cookie or header auth is ever added, this flips to True and "*" must be
# rejected in the same commit.
CORS_ALLOW_CREDENTIALS = False

# The verbs and request headers the client actually sends
# (frontend/src/services/studioApi.ts): GET for graph, run, frames and logs;
# POST for run creation, gate replies and cancel; Accept and Content-Type on
# those. OPTIONS is the preflight itself. Nothing else is granted.
CORS_ALLOW_METHODS = ("GET", "POST", "OPTIONS")
CORS_ALLOW_HEADERS = ("Accept", "Content-Type")

# ETag is NOT on the CORS-safelist for response headers, so a cross-origin
# reader of /api/workflows/{id}/graph cannot see the graph version unless it is
# named here. Content-Disposition is deliberately absent: downloadLogs names
# the file itself from the run id.
# Retry-After joins it for the same reason: run creation answers 429 with
# one, and a cross-origin client cannot read it unless it is named here.
CORS_EXPOSE_HEADERS = ("ETag", "Retry-After")

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
# Interrupted-run recovery - a run that was EXECUTING when the process died
#
# A run parked at a human gate has a durable anchor: the `run_gates` row plus
# the `pending_feedback` row CrewAI writes when it raises
# HumanFeedbackPending, so from_pending()/resume() picks it up again. A run
# that was mid-method has neither. Flow.from_pending() raises ValueError
# without a pending_feedback row, and kickoff(inputs={"id": ...}) restores the
# STATE with an empty completed-method set, which re-runs the flow from
# @start rather than resuming it - CrewAI's own comment in
# flow/runtime/__init__.py says so. So a mid-execution run is not resumable;
# it is failable, and the honest thing is to say so instead of leaving a row
# that reports `running` forever.
#
# The grace period is how long a `queued`, `running` or `cancelling` row may
# go without ANY durable write before this process treats it as interrupted.
# It is not decoration - three live situations need to fit inside it:
#
#   * Render's zero-downtime deploy overlaps the draining instance and the
#     booting one for up to maxShutdownDelaySeconds (300 s in render.yaml), so
#     the new process can see a row the old one is still executing.
#   * A gate reply spends up to RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS between
#     emitting GATE_CLOSED - which puts the record back to RUNNING - and
#     installing the resume future, so for that window a perfectly healthy run
#     has no live future in this process.
#   * `runs.updated_at` is bumped by every frame batch, so it is a heartbeat -
#     but a run sitting inside one slow escalation-tier call emits nothing for
#     as long as that call takes.
#
# 900 s clears all three with room to spare while still converging an orphan
# in minutes rather than never.
#
# The recovery switch exists for a deployment that runs more than one API
# process against one database. The "is anything still executing this?" test
# is process-local (a live future in THIS registry), so a second instance
# would be judging work it cannot see. render.yaml deploys a single instance
# with RUN_CONCURRENCY=1; scale that out and turn this off.
# --------------------------------------------------------------------------
VALIDATOR_ORPHAN_RUN_GRACE_SECONDS = _env_positive_int(
    "VALIDATOR_ORPHAN_RUN_GRACE_SECONDS", 900
)
VALIDATOR_ORPHAN_RUN_RECOVERY = _env_flag("VALIDATOR_ORPHAN_RUN_RECOVERY", True)

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
