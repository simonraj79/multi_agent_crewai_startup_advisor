"""Single source of truth for models, prices, embedding conventions and thresholds.

Every constant here is referenced by `agents/00-shared-config.md` or
`agents/06-retrieval-layer.md`. If a value changes, change it here and update the
spec section named in the comment - never in two places. The two embedding
prefixes in particular MUST stay paired: if they drift apart nothing raises,
retrieval quality just quietly degrades.
"""

from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Iterable
from typing import NamedTuple
from urllib.parse import urlsplit

# --------------------------------------------------------------------------
# Models - 00-shared-config.md §3
# --------------------------------------------------------------------------
# OpenRouter is a NATIVE CrewAI provider. Do not install crewai[litellm]; the
# model string alone resolves base_url and the key from OPENROUTER_API_KEY.
# The `:nitro` suffix is OpenRouter's shorthand for "route this to the fastest
# provider" - equivalent to a `provider: {"sort": "throughput"}` body, but
# expressible in the model string, which matters because CrewAI's `LLM` gives
# no clean channel for provider routing (see the `reasoning_effort` note below
# for how that has bitten this project before).
#
# MEASURED, n=4 each, same 4,000-char prompt asking for the same JSON:
#
#   z-ai/glm-5.3-flash                    median 37.91s   max 47.23s
#   google/gemini-3.5-flash-lite          median  1.70s   max  1.78s
#   google/gemini-3.5-flash-lite:nitro    median  1.38s   max  1.42s
#   google/gemini-3.7-flash (escalation)  median  9.60s   max 12.30s
#
# ~27x faster than glm at the median, and the tail is the real story: nitro's
# WORST case (1.42s) beats plain flash-lite's BEST (1.53s), while glm ranged
# 18.5-47.2s. A research branch is ~3 sequential model calls, so glm's spread
# alone was most of a two-minute branch, and its tail is what pushed
# `market_task` past its ceiling and failed whole runs.
#
# It is NOT cheaper: $0.30/$2.50 per Mtok against glm's $0.075/$0.250 - 4x the
# prompt price and 10x the completion price. At ~71K tokens across the three
# branches that is roughly +$0.023 a run. Still less than moving one branch to
# the escalation tier (+$0.033) and seven times faster than that tier.
#
# ⚠️ `:nitro` does not appear in `GET /api/v1/models` - only `:batch` is listed
# as a variant - but it resolves and bills correctly; the benchmark above is a
# real call. Because nitro picks the fastest provider rather than the cheapest,
# the price below is the published floor and the effective rate may be higher.
CHEAP_MODEL = "openrouter/google/gemini-3.5-flash-lite:nitro"

# ⚠️ The escalation tier moved 3.7-flash -> 3.8-flash on 2026-09-04. The three
# benchmark comments above and the two cost comments further down were measured
# on 3.7-flash and have NOT been re-measured; they are kept because a
# measurement of 3.7-flash remains a true measurement of 3.7-flash, and
# rewriting the model name in them would fabricate data this project never
# collected. Re-measure before quoting one as current.
#
# The swap needs no argument because it is free. Measured against the live
# OpenRouter catalogue on 2026-09-04 (`mcp__openrouter__get-model`):
#
#   google/gemini-3.8-flash   $0.75 / $3.75   AA 58.7 / 76.3 / 50.0
#   google/gemini-3.7-flash   $0.75 / $3.75   AA 56.0 / 76.1 / 45.1
#
# Byte-identical price, higher on all three Artificial Analysis indices
# (intelligence / coding / agentic). The half-price `:batch` variant
# ($0.375 / $1.875) is NOT usable here: batch is a queued lane, and a run with
# streaming frames and a human waiting at a gate cannot be queued.
#
# The CHEAP tier deliberately did NOT move. 3.8-flash would cost it 2.5x on
# prompt ($0.75 against $0.30), and the cheap tier exists to be cheap - three
# tool-using research analysts run on it.
ESCALATION_MODEL = "openrouter/google/gemini-3.8-flash"

# --------------------------------------------------------------------------
# The model registry - plan 05, contract C3. DATA, not constants.
# --------------------------------------------------------------------------
#
# Everything above this line is two models and a hand-typed pair of numbers per
# model. That was never a registry, and this file said so twice over: one slug
# has MANY endpoint prices, and a two-row table cannot express that. Measured
# 2026-09-04, `google/gemini-3.5-flash-lite` is served by eight endpoints from
# $0.15 to $0.54 per million input - a 3.6x spread with the $0.30 headline
# sitting in the middle.
#
# WHY A COMMITTED FILE AND NOT A FETCH. This module is imported by every test
# and by the service at boot; the suite must run with no network and CI has no
# credentials; and a boot that depends on a third-party catalogue is a boot that
# fails at 3 a.m. `scripts/refresh_models.py` regenerates the file and prints a
# unified diff, so a price that moves is a visible line in a commit rather than
# a silent drift - the failure this repository has recorded six times about its
# own counts.
#
# THE PLATFORM RULE STILL HOLDS. "Constants stay in config.py" is about a model
# name, a price or a threshold never being inlined at a call site. This file
# still names the path, still owns the ceiling, and is still the only place
# `PRICES` is built. What moved out is the DATA - ten rows of catalogue facts
# that nobody in this repository decides.
MODEL_REGISTRY_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "models.json"

#: CrewAI's native-provider prefix, declared here rather than beside
#: `_build_price_index` (where its reasoning lives) because
#: `load_model_registry` below runs at import and needs it first.
_OPENROUTER_PREFIX = "openrouter/"

#: The same prefix, publicly, for the modules that must PRODUCE a model id
#: rather than parse one - `builder/runtime.py` building an authored node's
#: `LLM`, and `builder/budget.py` pricing it. They may not spell it
#: themselves: `test_compiler.py::test_no_builder_module_inlines_a_model_name`
#: asserts the platform rule by scanning those files for the literal, and the
#: rule is right - a provider prefix is a model fact, and model facts live
#: here.
OPENROUTER_MODEL_PREFIX = _OPENROUTER_PREFIX

#: The schema string `data/models.json` must declare. Bumped only with a
#: migration, the same discipline BUILDER_DOCUMENT_SCHEMA follows.
MODEL_REGISTRY_SCHEMA = "models/v1"

#: `speed_tier` is CURATED, not derived: the public catalogue publishes no
#: throughput figure, and the ordering behind these three words came from the
#: MCP's `sort: throughput-high-to-low`. Kept a closed set so a picker can group
#: on it without inventing a fourth word.
MODEL_SPEED_TIERS = ("fast", "balanced", "deep")


class RegistryModel(NamedTuple):
    """One row of `data/models.json` - C3, and every field is a catalogue fact.

    A `NamedTuple` and NOT a frozen dataclass, and the difference is not taste.
    `tests/service/test_cors.py` executes THIS FILE by path through a loader
    that never registers the module in `sys.modules`, which is the only way to
    observe an import-time refusal without poisoning every module that already
    imported a constant from here. `dataclasses` resolves `KW_ONLY` through
    `sys.modules[cls.__module__].__dict__` and dies with `AttributeError:
    'NoneType' object has no attribute '__dict__'` under that loader - so a
    dataclass anywhere in this file turns a CORS assertion into a traceback
    about dataclasses. `NamedTuple` reads its own `__annotations__` and does
    not care.

    TWO price columns, and reporting only one of them is what produced the
    mistake this plan had to correct. `cost_in` is what a run is PRICED at - the
    plain slug's headline, which is also a real endpoint. `cost_in_max_endpoint`
    is the dearest endpoint serving the same slug, and it is what says how much
    exposure `provider.max_price` is actually filtering away.
    """

    id: str
    name: str
    provider: str
    context_window: int
    supports_tools: bool
    supports_vision: bool
    supports_json_mode: bool
    supports_reasoning: bool
    #: USD per MILLION prompt tokens, the plain slug's headline.
    cost_in: float
    #: USD per MILLION completion tokens, the plain slug's headline.
    cost_out: float
    #: USD per million prompt tokens on the DEAREST endpoint serving this slug.
    #: Measured once at build time (plan 05 decision 6); `refresh_models.py`
    #: preserves it across a price refresh rather than guessing it from
    #: NITRO_PRICE_FACTOR, because the measured per-model ratios run 1.0x to
    #: 9.5x and no single constant was ever going to be right.
    cost_in_max_endpoint: float
    speed_tier: str
    recommended_for: tuple[str, ...]


def load_model_registry(path: "pathlib.Path | str | None" = None) -> dict[str, object]:
    """Parse and CHECK `data/models.json`. Raises on anything malformed.

    Raises rather than degrading, and that is the one place this file is
    deliberately fragile: a registry that half-loads is a product that offers
    half a roster and prices the rest at nothing, which is the same shape as the
    defect that reported a 128,069-token run at $0.00. A missing or malformed
    registry has to stop the process at import, where the traceback names the
    file.

    Takes a path so a test can load a fixture registry without an environment
    knob. There are thirty-nine of those already and this needed none.
    """

    source = pathlib.Path(path) if path is not None else MODEL_REGISTRY_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema") != MODEL_REGISTRY_SCHEMA:
        raise ValueError(
            f"{source} declares schema {payload.get('schema')!r}; this build reads "
            f"{MODEL_REGISTRY_SCHEMA!r}"
        )

    ceiling = float(payload["ceiling_usd_per_m_input"])
    rows = payload["models"]
    if not 1 <= len(rows) <= 10:
        raise ValueError(f"{source} carries {len(rows)} models; C3 admits 1 to 10")

    models: list[RegistryModel] = []
    seen: set[str] = set()
    for row in rows:
        model = RegistryModel(
            id=str(row["id"]),
            name=str(row["name"]),
            provider=str(row["provider"]),
            context_window=int(row["context_window"]),
            supports_tools=bool(row["supports_tools"]),
            supports_vision=bool(row["supports_vision"]),
            supports_json_mode=bool(row["supports_json_mode"]),
            supports_reasoning=bool(row["supports_reasoning"]),
            cost_in=float(row["cost_in"]),
            cost_out=float(row["cost_out"]),
            cost_in_max_endpoint=float(row["cost_in_max_endpoint"]),
            speed_tier=str(row["speed_tier"]),
            recommended_for=tuple(str(value) for value in row["recommended_for"]),
        )
        # A base slug, never a variant and never the provider prefix. Both
        # spellings exist in this codebase for good reasons and a registry keyed
        # on either would miss - `resolve_price_model`'s whole docstring is the
        # history of that miss.
        if model.id.startswith(_OPENROUTER_PREFIX) or ":" in model.id:
            raise ValueError(f"{model.id!r} is not a base slug: drop the prefix and the variant")
        if model.id in seen:
            raise ValueError(f"{source} lists {model.id!r} twice")
        seen.add(model.id)
        if model.speed_tier not in MODEL_SPEED_TIERS:
            raise ValueError(f"{model.id}: speed_tier {model.speed_tier!r} is not one of {MODEL_SPEED_TIERS}")
        # THE ADMISSION PREDICATE, and it is the headline rather than the max
        # endpoint on purpose. The owner ruled the ceiling is the MAX endpoint
        # price, and `provider.max_price` enforces exactly that at the API - so
        # what this check has to answer is the OTHER half of the same ruling: a
        # model whose cheapest endpoint is over the ceiling cannot be served at
        # all under `max_price` and the request would fail rather than
        # overspend. The headline IS one of the slug's endpoints, so
        # `cost_in <= ceiling` is a witness that a servable endpoint survives
        # the filter. `openai/o4-mini` has exactly one endpoint at $1.10 and is
        # refused here; `openai/gpt-5.2` has a $0.88 flex endpoint but a $1.75
        # headline and is refused here too, which is the answer the roster wants.
        if model.cost_in > ceiling:
            raise ValueError(
                f"{model.id}: ${model.cost_in}/M input is over the ${ceiling}/M ceiling"
            )
        if model.cost_in_max_endpoint < model.cost_in:
            raise ValueError(
                f"{model.id}: cost_in_max_endpoint ${model.cost_in_max_endpoint} is below the "
                f"headline ${model.cost_in}, so the headline is not one of this slug's endpoints"
            )
        models.append(model)

    by_id = {model.id: model for model in models}
    presets = {str(key): str(value) for key, value in payload["presets"].items()}
    for tier, spelling in presets.items():
        base = spelling.removeprefix(_OPENROUTER_PREFIX).split(":", 1)[0]
        if base not in by_id:
            raise ValueError(f"preset {tier!r} names {spelling!r}, which is not a registry row")

    return {
        "ceiling_usd_per_m_input": ceiling,
        "generated_at": payload.get("generated_at", ""),
        "source": payload.get("source", ""),
        "presets": presets,
        "models": tuple(models),
        "raw": payload,
    }


_REGISTRY = load_model_registry()

#: Every model an author may pick, in the order `data/models.json` lists them -
#: which is the roster's own ranking, not alphabetical.
MODEL_REGISTRY: tuple[RegistryModel, ...] = _REGISTRY["models"]  # type: ignore[assignment]
MODEL_BY_ID: dict[str, RegistryModel] = {model.id: model for model in MODEL_REGISTRY}
MODEL_IDS: frozenset[str] = frozenset(MODEL_BY_ID)
#: The registry's own copy of the ceiling. Cross-checked against
#: MODEL_PRICE_CEILING_IN further down rather than duplicated: two numbers with
#: one meaning is how every count in this repository has gone stale.
MODEL_REGISTRY_CEILING_IN: float = float(_REGISTRY["ceiling_usd_per_m_input"])  # type: ignore[arg-type]
MODEL_PRESETS: dict[str, str] = dict(_REGISTRY["presets"])  # type: ignore[arg-type]
#: When the roster was measured, and against what. Served with it, because a
#: client holding a stale copy can then say HOW stale rather than only that its
#: prices disagree with somebody's.
MODEL_REGISTRY_GENERATED_AT: str = str(_REGISTRY["generated_at"])
MODEL_REGISTRY_SOURCE: str = str(_REGISTRY["source"])


def registry_model(model: str | None) -> "RegistryModel | None":
    """The registry row a model id names, in any of the four spellings.

    `openrouter/` prefix and a `:nitro` variant are both routing detail rather
    than identity, and every one of the four spellings reaches this project
    somewhere - `config.py` writes one, CrewAI reports another, a document
    carries a third.
    """

    name = str(model or "").strip().casefold()
    if not name:
        return None
    for candidate in _price_lookup_spellings(name):
        found = MODEL_BY_ID.get(candidate)
        if found is not None:
            return found
    return None


# USD per million tokens, (prompt, completion). Used to ESTIMATE cost, because
# CrewAI discards OpenRouter's per-generation cost before it reaches any event.
# Keys are written the way this project configures a model - with the
# `openrouter/` provider prefix - and `resolve_price_model` below accepts the
# de-prefixed spelling CrewAI actually reports.
#
# DERIVED from the registry as of 2026-09-04, and the derivation changed no
# value in this repository - it changed where the value comes from. The two
# presets measured IDENTICAL to the pair this dict held by hand ($0.30/$2.50 and
# $0.75/$3.75), which is the whole reason plan 05's own price table had to be
# corrected before it was implemented: the table it was written against quoted
# `:batch` variant prices as headlines, and a registry seeded from it would have
# replaced two correct prices with two wrong ones.
#
# THE TWO PRESETS ARE INSERTED FIRST, and the order is load-bearing.
# `_build_price_index` uses `setdefault`, so whichever key is registered first
# owns the variant-stripped spellings - and the answer
# `resolve_price_model("google/gemini-3.5-flash-lite")` gives has to stay
# CHEAP_MODEL, the key this project actually configures, rather than the bare
# registry row that happens to carry the same numbers.
PRICES: dict[str, tuple[float, float]] = {
    # Unchanged by the 2026-09-04 escalation swap, and CHECKED rather than
    # assumed: 3.8-flash is $0.75 / $3.75, the same as the 3.7-flash it
    # replaces. The dict is keyed by the constants, so a swap can never orphan
    # a key - but it can leave a stale VALUE, which is exactly the defect that
    # once priced a 128,069-token run at $0.00. The rule is that the number
    # moves in the same commit as the constant; here the number did not need
    # to move, and that is a measurement, not an omission.
    CHEAP_MODEL: (
        MODEL_BY_ID[CHEAP_MODEL.removeprefix(_OPENROUTER_PREFIX).split(":", 1)[0]].cost_in,
        MODEL_BY_ID[CHEAP_MODEL.removeprefix(_OPENROUTER_PREFIX).split(":", 1)[0]].cost_out,
    ),
    ESCALATION_MODEL: (
        MODEL_BY_ID[ESCALATION_MODEL.removeprefix(_OPENROUTER_PREFIX).split(":", 1)[0]].cost_in,
        MODEL_BY_ID[ESCALATION_MODEL.removeprefix(_OPENROUTER_PREFIX).split(":", 1)[0]].cost_out,
    ),
}
for _model in MODEL_REGISTRY:
    # `setdefault`, so a preset's own spelling is never displaced by the bare
    # row underneath it. Both carry the same pair by construction - the presets
    # above are READ from these rows - so this can only ever add keys.
    PRICES.setdefault(f"{_OPENROUTER_PREFIX}{_model.id}", (_model.cost_in, _model.cost_out))
del _model

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
#
# `_OPENROUTER_PREFIX` is DECLARED ABOVE, beside the model registry, because
# `load_model_registry` runs at import and needs it before this point in the
# file. It is documented here, where its reason lives.


def _build_price_index() -> dict[str, str]:
    """Every spelling a reported model name might arrive in, mapped to its key.

    Four per key: with and without the `openrouter/` prefix, each with and
    without a trailing routing variant such as `:nitro`. Registering the
    variant-stripped forms HERE rather than only stripping the incoming name is
    what makes `google/gemini-3.5-flash-lite` resolve when the configured model
    is `openrouter/google/gemini-3.5-flash-lite:nitro` - the provider that
    serves a nitro-routed request can report the base model back, and without
    this the run's whole cost display would quietly return to zero.

    `setdefault` so a key that is spelled explicitly always wins over a base
    form derived from some other key.
    """

    index: dict[str, str] = {}
    for key in PRICES:
        folded = key.casefold()
        spellings = [folded]
        if folded.startswith(_OPENROUTER_PREFIX):
            spellings.append(folded[len(_OPENROUTER_PREFIX) :])
        for spelling in list(spellings):
            base, separator, _ = spelling.rpartition(":")
            if separator and base:
                spellings.append(base)
        for spelling in spellings:
            index.setdefault(spelling, key)
    return index


PRICE_MODEL_INDEX: dict[str, str] = _build_price_index()


def resolve_price_model(model: str | None) -> str | None:
    """The PRICES key a reported model name refers to, or None if it has none.

    Three spellings have to land on one key, and each was a real failure mode:

    1. `openrouter/google/gemini-3.5-flash-lite:nitro` - what config.py declares.
    2. `google/gemini-3.5-flash-lite:nitro` - what CrewAI reports, because
       `LLM.__new__` strips the provider prefix for native providers. This one
       already cost this project a run priced at $0.00 over 128,069 real tokens.
    3. `google/gemini-3.5-flash-lite` - the VARIANT-STRIPPED name, because
       `:nitro` is a routing instruction rather than a distinct model, and the
       provider that serves the request may report the base model back.

    Only (3) is new. It matters because an unresolved name contributes NOTHING
    to the run's cost - deliberately `None` rather than 0.0, so "no price on
    file" can never masquerade as "this call was free" - which would silently
    return the whole cost display to the zero it used to show.
    """

    name = str(model or "").strip().casefold()
    if not name:
        return None
    for candidate in _price_lookup_spellings(name):
        resolved = PRICE_MODEL_INDEX.get(candidate)
        if resolved is not None:
            return resolved
    return None


def _price_lookup_spellings(name: str) -> tuple[str, ...]:
    """`name`, then without the provider prefix, then without a `:variant`."""
    spellings = [name]
    if name.startswith(_OPENROUTER_PREFIX):
        spellings.append(name[len(_OPENROUTER_PREFIX) :])
    # Strip a trailing routing variant (`:nitro`, `:floor`, `:free`, `:batch`).
    # Split on the LAST colon only: an id may legitimately contain others.
    for spelling in list(spellings):
        base, separator, _ = spelling.rpartition(":")
        if separator and base:
            spellings.append(base)
    return tuple(spellings)


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
#   vendor owned         - Competitor.vendor_owned: delivered as part of a
#                          larger platform vendor's product or subscription -
#                          something the buyer already has rather than buys.
#                          Corporate ownership alone is NOT enough: a product a
#                          larger vendor acquired but still sells as its own
#                          standalone subscription is not vendor owned. Null
#                          means no source settled it; null is not false.
#                          (RATIFICATION C5. The old wording split on ownership
#                          OR bundling and gave opposite answers for an
#                          acquired-but-standalone product - Slack under
#                          Salesforce - leaving 0.4 of the composite to which
#                          half of a sentence a cheap-tier model weighted.
#                          Bundling is readable off a pricing page, which is
#                          what Firecrawl retrieves; ownership lives in footers
#                          and press releases, which it does not.)
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
# RATIFICATION C7 (2026-09-01): 5, not 3. Set WITH MARGIN against
# VALIDATOR_SENTIMENT_STORY_LIMIT rather than at the ladder's own smallest
# count.
#
# At 3 of a possible 5 the floor fired one OFF_TOPIC/OPINION flip away from not
# firing, and that pair of labels is the softest judgement in the pipeline - it
# was undefined anywhere the Sentiment Analyst could read it until C7(a). One
# fixed retrieval of five threads measured 3 OPINION + 2 OFF_TOPIC as
# REJECT / FLOOR_NO_DEMAND, and flipping ONE label to OFF_TOPIC as NEEDS_WORK.
# Same evidence, opposite verdict, zero margin.
#
# At 5 the floor requires the branch to have retrieved a full page of on-topic
# discussion and found no problem in any of it. It bounds a FLOOR only: it never
# raises a score, and D=1 absorbs every state it excludes.
RUBRIC_FLOOR_MIN_USABLE_THREADS = 5

# D at 4, deliberately.
DEMAND_ANCHORS: dict[int, str] = {
    # ⚠️ INTERPOLATED from RUBRIC_FLOOR_MIN_USABLE_THREADS, not written out.
    #
    # These said "3" while the constant said 5 for about an hour on 2026-09-01 -
    # RATIFICATION C7 raised the floor and left the prose behind. The result was
    # a DEAD ZONE, not a cosmetic mismatch: at 3 or 4 usable threads with no
    # problem thread, `zero_ok` is false and `one_ok` is true, so score 1 is the
    # only legal answer - and its anchor asserted "fewer than 3", which is false
    # of that evidence, while D=0's anchor was true of it and rejected.
    #
    # A careful model picks 0, is rejected with SCORE_FLOOR_D, and re-runs the
    # entire escalation-tier task. Worse, level 1 is matched by EXACT string
    # equality, so the model had to reproduce a false sentence character-perfect
    # to proceed.
    #
    # Not a corner case: VALIDATOR_SENTIMENT_STORY_LIMIT is 5, and C7's own
    # justification names the retrieval that lands here - "3 OPINION + 2
    # OFF_TOPIC" is usable=3, problems=0, dead centre of the zone it created.
    #
    # Interpolating makes the drift impossible to reintroduce silently: change
    # the constant and these move with it, and the verbatim-quote test then
    # fails until `tasks.yaml` is resynced. Loud, not silent.
    0: (
        f"At least {RUBRIC_FLOOR_MIN_USABLE_THREADS} usable threads, and none of them is "
        "a problem thread: nobody in the evidence describes having this problem."
    ),
    1: (
        f"{LEVEL_ONE_ANCHOR} — the sentiment branch returned fewer than "
        f"{RUBRIC_FLOOR_MIN_USABLE_THREADS} usable threads and no problem thread."
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
# M=0 with D<=2 is a hard floor (REJECT).
#
# ⚠️ CORRECTED 2026-09-01. This comment claimed 'The PRD floor is "no money, no
# nameable buyer"'. There is no such floor: PRD.md states no Market ladder, and
# the word "buyer" does not occur in it at all (verified, 0 occurrences). An
# invented provenance for a REJECT is worse than none, because the next reader
# treats it as settled.
#
# What the PRD actually supplies is the dimension QUESTION - "Is there money,
# and can you name whose?" - which is a conjunction, so level 0 is the negation
# of BOTH halves. Firing on the buyer half alone rejects the commonest
# market-research result there is: a page giving category revenue and naming no
# segment. Measured, that scored REJECT at confidence 1.0. "That is not an
# answer to the question" is an argument for a LOW score - which rungs 2-5 and
# the ceiling already deliver - not for a REJECT.
# ⚠️ "None of them names a buyer segment" cannot be settled without reading
# the sources, so M=0 remains the one floor of the four that is not fully
# countable (`docs/rubric-review.md` F3). One necessary condition IS
# countable and is now enforced: a branch that recorded a paying segment has,
# by `market_task`'s own definition of that field, an attributed source
# naming a buyer segment, so `market_paying_segments >= 1` contradicts this
# anchor. That bound needs no change to the anchor text, which is why it is
# taken here. The review's second conjunct - "at least 3 sources" - is now
# taken as well (RATIFICATION C2).
#
# ⚠️ CORRECTED 2026-09-01. This said raising the count "would orphan the 1-2
# source states the way D=0 orphaned the 1-2 thread states". That is checkably
# false and was the sole stated reason for refusing the conjunct: the M
# ceiling's `else` branch is `money = 3` (validator_guardrails.py), so 1-2
# sources keep legal scores [2,3] and never lost a ceiling. D's problem was a
# genuine deadlock; this was a dead band, and the paired widening of M=1 closes
# it the same way D's did.
MARKET_ANCHORS: dict[int, str] = {
    0: (
        "At least 3 market sources, and none of them names a buyer segment for this "
        "problem, and none states a price or a budget anyone spends on it."
    ),
    1: f"{LEVEL_ONE_ANCHOR} — the market branch returned fewer than 3 sources, and none of them names a buyer segment for this problem.",
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
    1: f"{LEVEL_ONE_ANCHOR} — the market branch returned no source, so no competitor could be named.",
    2: (
        "No source states an axis of beatability, and either no competitor is named or "
        "at least 1 named competitor is not shown to be vendor owned."
    ),
    3: "At least 1 source states an axis on which a named competitor is beatable.",
    4: (
        "Anchor 3, and at least 2 competitors are named, and at least 1 source dated within "
        "24 months describes a need the named incumbents do not serve."
    ),
    5: (
        "Anchor 4, and at least 2 sources dated within 24 months describe the same unserved "
        "need, and every named competitor is shown not to be vendor owned."
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
    1: f"{LEVEL_ONE_ANCHOR} — the feasibility branch returned no repository.",
    2: (
        "At least 1 repository was returned, and none of them is reusable: none is marked "
        "SOLVES_ENTIRELY or PARTIAL, or those that are lack a commercial licence or a push "
        "within 12 months."
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
        "and was pushed within 12 months, or at least 1 free product with an attributed URL covers the whole core job."
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
        "No free substitute repository exists, and free coverage is unsettled or "
        "settled at no more than a separable part of the core job."
    ),
    4: (
        "No free substitute, no free product, and free coverage settled, but a "
        "repository marked PARTIAL covers most of the core job."
    ),
    5: (
        "No free substitute, no free product, and free coverage settled, and every "
        "repository marked PARTIAL covers only a separable part of the core job, with "
        "at least 1 such repository in the evidence."
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


# RATIFICATION C2 (2026-09-01). The same precondition, for the same reason, on
# the market floor.
#
# `zero_ok = sources >= 1 and segments == 0` fired a FINAL, non-provisional
# REJECT on ONE web page - measured at composite 4.6, confidence 0.68, zero
# guardrail complaints. "The branch returned sources and none names a buyer" is
# only a finding about the world if the branch actually looked.
#
# 3 is the unit the M ladder already counts in (M=5 asks for "at least 3 sources
# dated within 24 months"). It bounds a FLOOR only: it never raises a score.
# M=1's lower bound widens in the same edit - separated, they leave a state with
# a true anchor and no legal score, which is the deadlock D's repair hit.
RUBRIC_FLOOR_MIN_MARKET_SOURCES = 3

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
# than the provider default, so the setting is a decision rather than an
# accident.
#
# "low", not "high", since 2026-09-01, and the reason is measured. On the first
# successful paid run the Synthesist took **61 SECONDS** for a single call with
# no retries - 40% of a 150s pipeline - and `internal_reasoning` bills at
# $3.75/M, the SAME rate as completion, so the thinking was paid for twice over
# in latency and in money.
#
# The live catalogue is the authority on what is available here:
#
#     "reasoning": {"mandatory": true, "default_enabled": true,
#                   "supported_efforts": ["high", "medium", "low"],
#                   "default_effort": "medium"}
#
# Three things follow, and each has been got wrong in this file before:
#   * Reasoning CANNOT be disabled on this model. `mandatory: true` means there
#     is no zero-thinking option to fall back to.
#   * There is no "minimal" tier. The Evaluator's "minimal" belongs to a
#     DIFFERENT model; naming it here would silently fall through.
#   * "low" is the floor, not a middle setting - so this is as far down as the
#     dial goes without changing models.
#
# What justifies going to the floor rather than to "medium": the Synthesist is
# not reasoning FREELY. It picks five integers from a 30-anchor ladder whose
# text it must reproduce at 0.85 token overlap, over evidence it is handed, and
# every arithmetic conclusion it might reach is recomputed and overwritten by
# `Verdict`. The judgement is bounded and checked. If low degrades the choice,
# `anchor_problems` and `score_support_problems` catch it - at the cost of a
# retry, which is the risk this trade accepts.
# --------------------------------------------------------------------------
VALIDATOR_SYNTHESIST_REASONING_EFFORT = "low"

# The Reporter's effort, and it was the PROVIDER DEFAULT until 2026-09-01 -
# `LLM(model=ESCALATION_MODEL)` with no reasoning params, so "medium" by
# omission rather than by decision. It took 60 seconds on the first paid run,
# the same order as the Synthesist.
#
# "low" is defensible here on stronger grounds than for the Synthesist: the
# Reporter makes NO scoring judgement. Every number it prints was decided and
# overwritten by `Verdict` before this step began, every URL it may cite was
# returned by a tool, and its output is checked by a mechanical guardrail for
# source closure and by a citation judge for attribution. It is writing prose
# over settled facts, which is the cheapest thing a reasoning model does.
VALIDATOR_REPORTER_REASONING_EFFORT = "low"



# Route the escalation tier by THROUGHPUT rather than by OpenRouter's default
# load balance. MEASURED 2026-09-01 via `list-model-endpoints` for
# google/gemini-3.7-flash - tokens/second p50 over the trailing 30 minutes:
#
#   google-ai-studio/flex          $0.375/$1.875   216 tok/s    6,258 reqs
#   google-ai-studio               $0.75 /$3.75     95 tok/s   27,783 reqs
#   google-ai-studio/priority      $1.35 /$6.75     94 tok/s      750 reqs
#   google-vertex/global/priority  $1.35 /$6.75     89 tok/s      421 reqs
#   google-vertex/global           $0.75 /$3.75     60 tok/s  241,318 reqs
#   google-vertex/global/flex      $0.375/$1.875    21 tok/s      862 reqs (degraded)
#
# Both escalation calls of a real paid run landed on `google-vertex/global` and
# ran at 90.7 and 82.9 tok/s. Both steps are THROUGHPUT-bound: time-to-first-
# token is 2.7-3.0s on every healthy endpoint, so `priority` buys nothing, and
# the fastest endpoint here is also the cheapest.
#
# This is a ROUTING instruction, not a model change - same weights, same prompt,
# same temperature, same reasoning effort. It cannot alter a single output
# token, which makes it the one latency change with no exposure to the retry
# trap: it cannot make a guardrail attempt fail more often.
#
# Deliberately NOT `:nitro` in the model string. That spelling moves the
# `PRICES` key and its failure mode is a 404 that aborts a paid run; an ignored
# `provider` block merely runs at today's speed. There is no outcome here worse
# than the status quo.
#
# ⚠️ `PRICES` is NOT adjusted for the cheaper endpoint. It stays keyed on
# ESCALATION_MODEL, which has not changed, and an over-estimate is the safe
# direction for MAX_RUN_COST_USD - the recorded rate is now a CEILING rather
# than a floor. Reconcile against `get-generation` using the `response_id` the
# serializer records on every model-call frame.
VALIDATOR_ESCALATION_PROVIDER_SORT = "throughput"

# --------------------------------------------------------------------------
# The price ceiling, ENFORCED rather than asserted - owner's ruling 2026-09-04
# --------------------------------------------------------------------------
#
# The gauntlet's rule is "no model above $1.00 per 1M INPUT tokens reachable
# anywhere in the product", and the owner ruled that the ceiling is measured
# against the MAX endpoint price, not the headline. That ruling has teeth,
# because a slug's headline is only one of its endpoint prices. Measured
# 2026-09-04 with `list-model-endpoints`, `google/gemini-3.8-flash` has six:
#
#   google-ai-studio/flex           $0.375 / $1.875
#   google-vertex/global/flex       $0.375 / $1.875
#   google-ai-studio                $0.75  / $3.75     <- the headline
#   google-vertex/global            $0.75  / $3.75
#   google-ai-studio/priority       $1.35  / $6.75     <- OVER THE CEILING
#   google-vertex/global/priority   $1.35  / $6.75     <- OVER THE CEILING
#
# So the escalation tier's max endpoint is $1.35 and the literal ruling
# excludes it.
#
# WHY IT IS NEVERTHELESS ADMISSIBLE, and why that is a fact about routing
# rather than a reinterpretation of the ruling. OpenRouter's service-tier
# documentation is explicit: "Non-default tier endpoints (flex, priority) are
# only considered when your request asks for them", and there are exactly three
# ways to ask - a `:nitro` / `:floor` model variant, the `service_tier`
# parameter, or naming a tier endpoint slug in `provider.order` / `provider.only`.
#
# `ESCALATION_MODEL` is a plain slug and this file sends `provider: {"sort":
# "throughput"}`. `sort` is NOT one of the three. The two $1.35 endpoints are
# therefore not candidates, which is exactly what the one paid run observed:
# both escalation calls landed on `google-vertex/global` at $0.75.
#
# `CHEAP_MODEL` DOES carry `:nitro`, so for the cheap tier priority endpoints
# ARE admissible - and that is fine, because flash-lite's priority tier is
# $0.54, comfortably under.
#
# THE PROBLEM WITH LEAVING IT THERE is that all of the above is a property of
# today's configuration. Add `:nitro` to the escalation model, set a
# `service_tier`, or let a future author name an endpoint slug, and the $1.35
# endpoint becomes reachable with nothing failing. A ceiling that holds because
# of what we happen not to have set is not a ceiling.
#
# `provider.max_price` makes it one. OpenRouter filters endpoints by price
# BEFORE routing, so an over-ceiling endpoint cannot be selected regardless of
# variant, sort, tier or a catalogue change we have not noticed. The bound
# moves from a test in this repository to the API that does the billing.
#
# Failure mode, stated because it is the cost of the guarantee: if a model's
# CHEAPEST endpoint is over the ceiling, `max_price` filters every candidate
# and the request fails rather than silently overspending. That is the right
# direction, and it is also why the registry refuses such a model up front -
# `openai/o4-mini` has exactly one endpoint at $1.10 and is refused at both
# doors. Verified 2026-09-04: one endpoint, `openai`, $1.1 / $4.4.
MODEL_PRICE_CEILING_IN = 1.00

# The registry carries the ceiling too - C3's `ceiling_usd_per_m_input`, because
# `data/models.json` has to be readable on its own by `refresh_models.py` and by
# the client mirror, neither of which imports this module. Two numbers with one
# meaning is exactly how every count in this repository has gone stale, so they
# are CROSS-CHECKED at import rather than trusted to stay equal. A mismatch is
# fatal here, where the traceback names both files, rather than at the first
# publish that admits a model the ceiling forbids.
if MODEL_REGISTRY_CEILING_IN != MODEL_PRICE_CEILING_IN:
    raise RuntimeError(
        f"{MODEL_REGISTRY_PATH} declares a ${MODEL_REGISTRY_CEILING_IN}/M input ceiling and "
        f"config.py declares ${MODEL_PRICE_CEILING_IN}/M. They are one rule; change both."
    )

# ⚠️ There is deliberately NO completion ceiling, and the omission is the
# honest reading rather than an oversight. The gauntlet's rule is stated in one
# dimension - "$1.00 per 1M INPUT tokens" - and inventing a second bound would
# be inventing a number, which is the exact failure this whole 2026-09-04 pass
# exists to correct.
#
# It costs nothing in practice, and that is measured rather than assumed: every
# roster endpoint whose completion price is over $3.75 is a `priority` endpoint
# whose PROMPT price is $1.35, so the input bound already excludes it. The
# dearest completion price that survives the input bound is $3.75, the
# escalation tier's own headline. If a model ever appears with a cheap prompt
# and a wild completion price, this is where the second bound goes - and it
# should be added with its own measurement, not by symmetry.
def openrouter_price_ceiling_params() -> dict[str, float]:
    """The `provider.max_price` block that enforces the ceiling at the API.

    Returned as the inner mapping rather than a whole `extra_body`, because it
    has to MERGE with the `sort` this file already sends - two callers each
    writing their own `provider` key would have one silently overwrite the
    other, and the one that lost would be whichever ran second.
    """

    return {"prompt": MODEL_PRICE_CEILING_IN}


def openrouter_escalation_params(effort: str | None) -> dict[str, object]:
    """Reasoning effort AND throughput routing, in one ``extra_body``.

    Both travel the same way and for the same reason - see
    ``openrouter_reasoning_params`` for why CrewAI's own fields do not reach
    OpenRouter - so they are assembled once rather than merged at three call
    sites that could each forget one.
    """

    body: dict[str, object] = {}
    if effort is not None:
        body["reasoning"] = {"effort": effort}
    # ONE `provider` block, assembled here, because JSON has no merge and two
    # writers of the same key means the second wins silently.
    provider: dict[str, object] = {"max_price": openrouter_price_ceiling_params()}
    if VALIDATOR_ESCALATION_PROVIDER_SORT:
        provider["sort"] = VALIDATOR_ESCALATION_PROVIDER_SORT
    body["provider"] = provider
    return {"extra_body": body} if body else {}


def openrouter_authored_params(effort: str | None) -> dict[str, object]:
    """The `extra_body` an AUTHORED node's `LLM` carries - 10 D1.

    Two things travel together for the same reason ``openrouter_escalation_params``
    assembles its two: JSON has no merge, so one ``provider`` object is written
    once here rather than by two callers of whom the second silently wins.

    What is DELIBERATELY absent is ``provider.sort``. The escalation preset
    routes on throughput because three research analysts run behind a human
    waiting at a gate; an authored node's model is the author's own choice out
    of the registry, and imposing a routing preference on it would be this
    module choosing an endpoint the author did not.

    The price ceiling is NOT optional and is not a property of the tier. §6a's
    ruling is measured against the max ENDPOINT price, and an authored node can
    name any roster model, so without this an author's own slug could route to
    a priority endpoint over the ceiling exactly as the escalation preset could
    before ``max_price`` was added.
    """

    body: dict[str, object] = {"provider": {"max_price": openrouter_price_ceiling_params()}}
    if effort is not None:
        body["reasoning"] = {"effort": effort}
    return {"extra_body": body}


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


def _env_non_negative_float(name: str, default: float) -> float:
    """Read a float knob where 0 is a meaningful value, not a mistake.

    Separate from `_env_positive_float` because a knob whose zero means
    "disabled" cannot share a reader that refuses zero. A NEGATIVE value is
    still refused: it would be an operator asking for something the code cannot
    express, and silently clamping it to "disabled" is how a spend cap goes
    missing without anyone being told.
    """
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number >= 0") from exc
    if value < 0:
        raise ValueError(f"{name} must be a number >= 0")
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
# The per-run spend ceiling - the only limit here denominated in DOLLARS
#
# Every other admission limit above bounds a COUNT: bytes, characters, keys,
# queued runs, runs per minute. None of them bounds what one admitted run may
# spend once it is executing, and until this constant existed nothing did:
# `compute_cost_usd` priced each call and `RunRecord._record_usage` added it to
# a running total that was never compared to anything. A single run that loops
# inside an agent's `max_iter`, or a revise cycle nobody is watching, was
# bounded only by the agents' own patience.
#
# THE DEFAULT, AND WHY IT IS THIS NUMBER. Measured on run `8b5a0a78` recovered
# from the deployed API - 11 calls, 128,069 tokens, $0.1309 total:
#
#   escalation call (google/gemini-3.7-flash)   $0.024488 average
#   cheap call      (z-ai/glm-5.3-flash)        $0.001417 average  - 17.3:1
#   typical clean run                           $0.13 - $0.18
#   observed worst case                         $2 - $4
#   observed tail                               $7
#
# A ceiling has to sit ABOVE the most expensive legitimate run and BELOW an
# unbounded one, and the only honest anchor for "legitimate" is that observed
# $7 tail. $10 clears it by 1.4x, which is the margin that matters: a ceiling
# that fires on an honest run gets raised or turned off, and then it protects
# nothing. Against the runs anyone actually sees it is enormous - ~55x the
# $0.18 clean run, and ~2.5x the $4 worst case - and that asymmetry is the
# point. This is a RUNAWAY brake, not a budget: it converts "unbounded" into
# "at most about ten dollars", and it is not the knob for holding a demo to a
# few cents. An operator who wants that sets MAX_RUN_COST_USD lower and accepts
# that some real runs will be cut short.
#
# What the worst legitimate run is made of, so the number can be re-derived
# rather than re-guessed: VALIDATOR_MAX_GATE_TURNS (5) revises at each of two
# gates is 10 extra escalation-tier calls on top of the 11 a clean run makes,
# and the verdict-gate ones re-run the Synthesist at reasoning_effort=high.
# Raise VALIDATOR_MAX_GATE_TURNS and this ceiling has to be re-checked with it.
#
# 0 DISABLES THE CEILING; UNSET DOES NOT. Leaving the variable out gives the
# default above, so a deployment that does nothing still gets a brake; turning
# it off takes a deliberate `MAX_RUN_COST_USD=0`. That is the same escape-hatch
# spelling RUN_RATE_LIMIT_MAX_RUNS already uses, and it is the right way round
# for a cost control: the failure mode of an over-tight ceiling is a cut-short
# run, and the failure mode of a missing one is a bill.
#
# ⚠️ THREE THINGS THIS CEILING DOES NOT DO. None is a defect to be fixed later
# by tuning the number; each is structural, and enforcement in
# `registry.RunRecord._record_usage` repeats all three where it acts on them.
#
#   1. IT ENFORCES AN ESTIMATE, NOT AN INVOICE. `compute_cost_usd`'s own
#      docstring says so: CrewAI never asks OpenRouter for its per-generation
#      cost, so every figure here is recomputed from the PRICES table. Cached
#      prompt discounts, BYOK fees, per-request rounding and any price change
#      made after that table was written all move the billed number away from
#      the enforced one, in either direction.
#   2. IT CANNOT STOP A CALL ALREADY IN FLIGHT. The total only moves when a
#      call COMPLETES, and the stop then takes effect at the next CrewAI
#      PRE_STEP boundary. Granularity is therefore one LLM call plus the tail
#      of the current step: expect to overshoot by roughly one escalation call,
#      ~$0.05 at the measured average, and more if that call is unusually long.
#      The ceiling bounds the order of magnitude, never the cent.
#   3. IT IS BLIND TO EVERYTHING THAT IS NOT AN LLM CALL. Embeddings, Cohere
#      rerank and Firecrawl never raise an `LLMCallCompletedEvent`, so they
#      never reach `_record_usage` and are absent from the total this ceiling
#      reads. That is roughly $0.006-$0.02 per run of real money the reported
#      figure structurally UNDERCOUNTS - so the enforced total is always a
#      lower bound on the true spend, and the true stop is always a little
#      later than the number here suggests.
# --------------------------------------------------------------------------
MAX_RUN_COST_USD = _env_non_negative_float("MAX_RUN_COST_USD", 10.0)

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

# --------------------------------------------------------------------------
# C6's three frame ceilings - .agent/plans/10-runtime.md D6
#
# Separate constants rather than one, because each bounds a different thing and
# the contract fixes each number independently. They are all far under
# `SerializerLimits.max_string` on purpose: the ring holds 2,000 frames and a
# subscriber queue 512, and a run whose narration evicts its own history is a
# run that cannot be replayed - which is the failure the ring is bounded to
# prevent in the first place.
# --------------------------------------------------------------------------
#: A completed model response, on the `utterance` frame. The whole point of the
#: frame is that a run view can show what the agent SAID, so this is the one
#: that has to be generous; `truncated: true` says when it was not enough.
MAX_UTTERANCE_CHARS = 4096
#: A tool's arguments, a tool's result, and a node's output, on the
#: `input_preview` / `output_preview` keys. A preview, not the value: the value
#: is in the run result and in `flow_states`.
MAX_FRAME_PREVIEW_CHARS = 2048
#: One failure's sentence on a `node_error` frame. Shorter than the other two
#: because a traceback-shaped message is a thing to point at, not to read in a
#: stream.
MAX_NODE_ERROR_CHARS = 1024
#: How long stream chunks for one `call_id` are gathered before one frame is
#: emitted for them (decision 15, owner, 2026-09-04). The alternative was a
#: bigger ring, which trades a known bound for an unknown one.
STREAM_CHUNK_COALESCE_MS = 250

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

# --------------------------------------------------------------------------
# Revise turns per human gate
# --------------------------------------------------------------------------
# How many times an operator may answer ONE gate with `decision: "revise"`
# before the next revise is honoured as an approval instead.
#
# What a turn costs, which is why this is bounded at all. A revise at
# `confirm_scope` re-runs the Scoper; a revise at `review_verdict` re-runs the
# Synthesist. Both are ESCALATION_MODEL agents - the two most expensive calls
# in the pipeline, and the Synthesist runs at reasoning_effort=high. Nothing
# else about a revise is cheap either: it is unauthenticated (the gate reply
# endpoint deliberately bypasses admission control so a flood can never strand
# a human mid-run), it is unlimited in wall-clock (a WAITING run holds no
# admission slot, so a revise loop occupies no queue an operator would notice),
# and it never terminates on its own - `route_scope` -> `revise_scope` ->
# `confirm_scope` is a genuine cycle in the flow graph. So the only thing
# standing between one run and unbounded escalation-tier spend was an
# operator's patience.
#
# CrewAI's own loop guard cannot serve here, and this is the whole reason the
# bound lives on the state. `Flow.max_method_calls` (crewai/flow/runtime/
# __init__.py:614, enforced at :3333) counts calls in `_method_call_counts`,
# which is a `PrivateAttr` (:756) - never serialized, never restored. Every
# shipped gate reply travels `ValidatorFlow.from_pending()` -> `resume()`,
# which builds a BRAND NEW flow object per reply, so that counter reads 1 on
# every single revise no matter how many came before it. A durable bound has to
# live somewhere `from_pending()` reloads, and `ValidatorState`'s declared
# fields are the only such place. `max_method_calls` is still set below, as the
# in-process backstop it can actually be.
#
# 5 is a working default rather than a principled one: enough that a real
# scoping conversation ("narrow it to dental clinics", "no, outpatient only")
# is not cut short, few enough that six escalation-tier calls is the worst a
# single anonymous run can do at one gate. Set 0 for a deployment where the
# only offered replies are approve and cancel - `minimum=0` is deliberate, and
# the gate stops offering Revise at all in that mode.
VALIDATOR_MAX_GATE_TURNS = _env_positive_int("VALIDATOR_MAX_GATE_TURNS", 5, minimum=0)

# The in-process backstop, and NOT a substitute for the durable bound above.
#
# CrewAI ships `max_method_calls=100` for a flow of any size. This one has 14
# nodes, so 100 is not a loop guard, it is a rounding error: at the measured
# ceiling below it would allow 99 revises at one gate before complaining.
#
# The ceiling is exact and was measured, not reasoned. `_method_call_counts` is
# keyed by METHOD NAME, so what matters is the most-called single method in one
# flow object. Running the in-process revise loop with T revises at each gate
# gives `confirm_scope: T+1`, `route_scope: T+1`, `revise_scope: T` and 1 for
# every other method - the gate method is entered once to ask, then once more
# after each revise. So T+1 is the highest legitimate count, and T+2 leaves
# exactly one call of headroom for a CrewAI re-entry this derivation has not
# modelled. `tests/validator/test_gate_turns.py` pins the derivation and the
# measurement together, so a raised VALIDATOR_MAX_GATE_TURNS cannot silently
# start tripping the backstop.
#
# On the durable service path no method reaches even 2, because each resume is
# a fresh object. This value only ever binds an in-process caller: `no_gates`,
# a scripted `HumanFeedbackProvider`, a test, or a future auto mode.
VALIDATOR_MAX_METHOD_CALLS = VALIDATOR_MAX_GATE_TURNS + 2

# --------------------------------------------------------------------------
# Research breadth - one tool call per branch, and how wide that one call goes
#
# Measured on the second paid run: the market branch ran for OVER 13 MINUTES
# while sentiment and feasibility finished in seconds. The cause is not the
# agent looping. `MarketResearchTool._run` passes `scrape_options` to
# Firecrawl's `search`, which makes it scrape EVERY result to markdown - so one
# obedient tool call is one search plus `limit` full page scrapes, at the PRD's
# own 10-30s per scrape. The agent could also ask for `limit=10`.
#
# So "call the tool once" does not bound this on its own, and the two numbers
# below are the ones that actually do. Each is a floor imposed by the rubric,
# not a preference - cutting further silently caps a dimension:
#
#   MARKET 3, not 1. Coverage is `min(1, sources / VALIDATOR_COVERAGE_TARGET_
#   SOURCES)`, M=4 needs 2 recent sources and M=5 needs 3 (`tasks.yaml`). At
#   `limit=1` the market dimension can never exceed 3 and no guardrail would
#   ever say so - the run would just quietly stop being able to score well.
#
#   SENTIMENT 5, not 3. Every row from one story shares one URL and the task
#   keeps at most one Thread per URL, so DISTINCT THREADS == story_limit. The
#   REJECT floor needs `>= RUBRIC_FLOOR_MIN_USABLE_THREADS` (3) usable threads,
#   so the old default of 3 sat exactly ON the floor with zero margin: one
#   thread classified OFF_TOPIC dropped it to 2 and fired `FLOOR_NO_DEMAND` -
#   a final REJECT for "no demand" caused by arithmetic, not by the world.
#   That margin used to come from the broadening retries. With one call it has
#   to come from the call. HN is fast and unthrottled, so this is nearly free.
#
# The `le=` bound on each tool's pydantic Field is set to the SAME value, which
# is what stops an agent asking for more than the budget: a default the model
# can override is a suggestion, not a cap.
VALIDATOR_MARKET_SEARCH_LIMIT = _env_positive_int("VALIDATOR_MARKET_SEARCH_LIMIT", 3)
VALIDATOR_SENTIMENT_STORY_LIMIT = _env_positive_int("VALIDATOR_SENTIMENT_STORY_LIMIT", 5)

# How many queries a branch may be handed. Belt-and-braces behind the YAML:
# `community_queries` and `tech_queries` are `min_length=1` with NO upper bound
# (`schemas/validator.py`), and the task prompts used to say "call the tool for
# each query below". Prompts are advisory and drift; a schema bound does not.
# Applied as `max_length`, so even on prompt drift the block holds one query.
#
# An over-long operator edit at the scope gate degrades safely rather than
# failing the run: `route_scope` already swallows `ValidationError` into
# `scope_edit_error`. See the UI work that finally surfaces that field - until
# it did, this was a silent discard of every edit the operator made.
VALIDATOR_MAX_BRANCH_QUERIES = _env_positive_int("VALIDATOR_MAX_BRANCH_QUERIES", 1)

# `max_iter` is the number of tool-calling passes an agent may take before
# CrewAI forces a final answer. It was 12 / 8 / 8.
#
# 2 rather than 1, and the difference is not caution. At 1, CrewAI's
# `handle_max_iterations_exceeded` still makes one more LLM call demanding an
# answer - so if the agent spends its single pass on anything except the tool
# call, it is forced to answer with ZERO captured URLs, the dynamic guardrail
# rejects it against `tool.captured_urls`, and the WHOLE TASK re-runs. One
# spare pass is cheaper than one guardrail retry.
VALIDATOR_BRANCH_MAX_ITER = _env_positive_int("VALIDATOR_BRANCH_MAX_ITER", 2)

# --------------------------------------------------------------------------
# Branch sampling - correctness first, and it was never being set at all
#
# A bare `LLM(model=...)` sends NO temperature, so the PROVIDER's default
# applies. Measured: glm-5.3-flash defaults to temperature 1.0, top_p 0.95.
# The three branch tasks are verbatim extraction - copy this claim, copy this
# URL, copy this date - and sampling at 1.0 is simply the wrong tool for that.
#
# The cost of a wobble is not a slightly different sentence. Every branch has a
# dynamic guardrail binding its output to URLs the tool actually returned, and
# `guardrail_max_retries: 2` re-runs the WHOLE task on a rejection. A sampled
# hallucinated URL therefore costs a full extra execution - which is exactly
# what happened to the sentiment branch on the last live run, twice, before it
# gave up. This is a correctness setting that happens to save time, not a
# latency knob: temperature measured flat (1.25s vs 1.31s at T=0).
VALIDATOR_BRANCH_TEMPERATURE = _env_non_negative_float("VALIDATOR_BRANCH_TEMPERATURE", 0.0)

# A hard ceiling on generated tokens - the slow half of every call.
#
# 2048 is sized against the schema, not guessed: a full-evidence MarketFindings
# (5 sources at the 500-char claim ceiling plus 3 competitors) is ~1,040 tokens
# and the worst realistic case ~1,745. Below ~1,800 a rich branch would be
# truncated mid-JSON, which fails validation and costs a whole task re-run.
#
# ⚠️ This is only safe because the branch model does not do mandatory reasoning.
# Measured on glm-5.3-flash, which does: `max_tokens=200` was consumed ENTIRELY
# by thinking and the call returned an empty string with `finish_reason=length`
# and no exception. If the branch model is ever changed back to a
# reasoning-by-default model, this bound becomes a silent output-eraser.
VALIDATOR_BRANCH_MAX_TOKENS = _env_positive_int("VALIDATOR_BRANCH_MAX_TOKENS", 2048)

# NO max_tokens ON THE ESCALATION TIER. Deliberate, and reversed on 2026-09-01
# the same day it was added.
#
# An 8192 ceiling was introduced here to bound generation, and it was the one
# change in this optimisation that could CAUSE the failure the whole exercise is
# trying to avoid. Truncation is not a quality regression that degrades
# gracefully - it is a HARD failure: a clipped `Verdict` or `ValidationReport` is
# invalid JSON, the guardrail rejects it, and CrewAI re-runs the ENTIRE task.
# So a cap that fires costs a full extra escalation call, guaranteed, which is
# larger than every saving on the list.
#
# The asymmetry decides it. Too high a ceiling costs nothing when unused; too low
# costs a whole call every time it bites, and the bite is invisible until it
# happens on the one run that mattered. The branches are bounded
# (VALIDATOR_BRANCH_MAX_TOKENS) because they emit small fixed-shape findings and
# a runaway there is a real cost; the escalation tier emits the deliverable, and
# clipping the deliverable is the defect this repository has already fixed twice
# (the 4096-character report, and the frame serializer's max_string).
#
# Latency here is bought with `reasoning.effort`, which shortens the THINKING -
# billed at $3.75/M, the same as completion - rather than by cutting the answer
# off mid-sentence.

# --------------------------------------------------------------------------
# Why the market branch timed out, and the three numbers that fix it
#
# MEASURED, not reasoned. The suspects were all wrong:
#
#   Firecrawl search+scrape, limit=3        1.83s   not the bottleneck
#   the whole tool, end to end              1.84s   not the bottleneck
#   its envelope handed to the model     ~1,310 tokens   not the bottleneck
#
# The bottleneck is the model's OUTPUT. The same cheap model, same input,
# asked for two different answer lengths:
#
#   claims capped at 150 chars     18.40s     817 output chars
#   claims copied verbatim (4k)   196.93s  15,908 output chars
#
# 196.93s for ONE call, against a 180s task ceiling. Output generation is the
# slow half of an LLM call, and MAX_CLAIM_CHARS was setting how much prose the
# Market Analyst had to re-emit into its JSON: up to 4,000 characters per
# source, three sources, plus the competitor objects.
#
# 500 is a citable claim - two or three sentences, which is what the Reporter's
# faithfulness check actually reads. Nothing else reads `claim` at all: no
# guardrail touches it, and `market_task` never even says what to put in it, so
# 4,000 was an unexamined default rather than a requirement. The clip is also a
# plain head-clip of whitespace-flattened text, so the extra 3,500 characters
# were the top of a page, not the pricing table further down.
VALIDATOR_MAX_CLAIM_CHARS = _env_positive_int("VALIDATOR_MAX_CLAIM_CHARS", 500)

# The bound above applies to the TOOL. This one applies to the MODEL, and the
# distinction is the whole point: nothing stopped the Market Analyst expanding
# a 500-char row into 4,000 characters of its own prose, or the Reporter
# emitting one at escalation-tier COMPLETION price. This repo already made
# exactly this argument for `community_queries` - prompts are advisory and
# drift, a schema bound does not.
#
# The floor is NOT free, and 1,200 is chosen against it rather than picked.
# `reporting_task` turns Hacker News quotes into `Evidence.claim`, and those
# are bounded at `hn_sentiment.MAX_QUOTE_CHARS` (1,000). Any bound below 1,000
# would reject legitimate Reporter output. 1,200 leaves headroom for the
# surrounding attribution and can only fire on genuinely runaway generation.
VALIDATOR_MAX_EVIDENCE_CLAIM_CHARS = _env_positive_int(
    "VALIDATOR_MAX_EVIDENCE_CLAIM_CHARS", 1_200
)

# Firecrawl's client defaults to `timeout=None` - an UNBOUNDED socket wait -
# and retries 3 times against a 300s server ceiling. 3 x 300s is where a
# 600s branch timeout comes from. Neither bound is the tool's own `try`, which
# only wraps the call and never sees a deadline that never arrives.
# 90, and the first draft said 30 - which FIRED on a real run at 31.1s and cost
# that run its whole market branch.
#
# Two things were wrong with 30. It was fitted to a 10.36s cold measurement with
# no allowance for a slow page or a cold Firecrawl cache, and the SDK degrades
# horribly when it trips: `handle_response_error(response, ...)` reads
# `response.status_code`, and a timeout has NO response, so the operator got
# `AttributeError: 'NoneType' object has no attribute 'status_code'` rather than
# "it timed out". `_error_status` now recognises that shape, but the real repair
# is a bound that only fires on a genuine hang.
#
# Still far below the branch's own 240s ceiling, so a wedged Firecrawl call
# fails the TOOL - honestly, through its envelope - rather than the task.
VALIDATOR_FIRECRAWL_TIMEOUT_SECONDS = _env_positive_int(
    "VALIDATOR_FIRECRAWL_TIMEOUT_SECONDS", 90
)
VALIDATOR_FIRECRAWL_MAX_RETRIES = _env_positive_int(
    "VALIDATOR_FIRECRAWL_MAX_RETRIES", 1, minimum=1
)

# Per-PAGE scrape ceiling in milliseconds, which the SDK leaves unset so the
# server's own 5-minute default applies. Distinct from the whole-call bound
# above: one pathological page must not consume the entire call's budget.
VALIDATOR_FIRECRAWL_SCRAPE_TIMEOUT_MS = _env_positive_int(
    "VALIDATOR_FIRECRAWL_SCRAPE_TIMEOUT_MS", 8_000
)

# Firecrawl reuses a cached page rather than refetching it, and the measured
# difference is 10.36s cold against 2.26s warm for the same query. The SDK
# already sends 4 hours; a week is right for market evidence, which does not
# move that fast, and the `dated` field records what the page said rather than
# when we fetched it.
VALIDATOR_FIRECRAWL_MAX_AGE_MS = _env_positive_int(
    "VALIDATOR_FIRECRAWL_MAX_AGE_MS", 604_800_000
)

# The `PendingFeedbackContext.metadata` key carrying how many revise turns this
# gate has already spent. It lives here because it is the one string two
# modules that CANNOT import each other have to agree on: `validator_flow`
# writes it (the feedback provider is the only code holding both the flow state
# and the context), and `service/registry` reads it to decide whether this
# gate still offers a Revise button. The service deliberately does not import
# `validator_flow` - `service/runner.py` defers that import so the FastAPI app
# does not drag in six crews - so a shared constant here is the seam.
#
# CrewAI persists `metadata` verbatim through `PendingFeedbackContext.to_dict`
# / `from_dict`, so the count survives a process restart the same way the gate
# row does.
GATE_REVISE_TURNS_METADATA_KEY = "revise_turns_used"

# The four `PendingFeedbackContext.metadata` keys a BUILDER gate declares about
# itself, for the same reason as the key above: `builder/compiler.py` writes
# them into the compiled `human_feedback` block and `service/registry.py` reads
# them back out, and neither may import the other - the compiler must not drag
# the service in, and the service must not learn the document schema.
#
# Everything the service used to assume about a gate is one of these. Without
# them a builder gate is titled "Review verdict", offers every key of its
# payload as editable whatever its author declared, counts its revise budget
# against VALIDATOR_MAX_GATE_TURNS instead of its own `max_turns`, and expires
# on the global clock. A validator gate declares NONE of them - its
# `@human_feedback` decorators carry no `metadata=` at all - so the absence of
# these keys is what tells the two apart, rather than a flag somebody has to
# remember to set.
GATE_LABEL_METADATA_KEY = "label"
GATE_EDITABLE_FIELDS_METADATA_KEY = "editable_fields"
GATE_MAX_TURNS_METADATA_KEY = "max_turns"
GATE_EXPIRY_METADATA_KEY = "expiry_seconds"

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
        # Gate turn accounting. Reserved for the most direct reason on this
        # list: these four ARE the bound. A caller who could post
        # `{"scope_revise_turns": -1000}` would not be tweaking a preference,
        # they would be handing themselves an unbounded number of
        # escalation-tier Scoper calls on an unauthenticated endpoint - the
        # exact spend VALIDATOR_MAX_GATE_TURNS exists to cap. The `_capped`
        # flags are reserved too, because a pre-set True is a lie about what
        # the operator was told at the gate.
        "scope_revise_turns",
        "verdict_revise_turns",
        "scope_revise_capped",
        "verdict_revise_capped",
        # Why an operator edit was dropped. Server-written explanations; a
        # caller seeding them would be forging the system's own account of
        # what happened.
        "scope_edit_error",
        "verdict_edit_error",
    }
)

# --------------------------------------------------------------------------
# Reserved input keys, PER WORKFLOW
#
# The set above is the VALIDATOR's, and until the builder existed it was also
# the only set, applied to every workflow by one `field_validator` on
# `CreateRunRequest.inputs`. That was correct while two flows shipped and both
# were written here. A user-authored graph declares its own state names, so
# "reserved" stops being one global fact: `verdict` is a control key on the
# validator and an ordinary word on somebody's competitor-sweep graph.
#
# Three sets rather than one, because the failure modes differ:
#
#   GLOBAL_RESERVED_RUN_INPUT_KEYS - names CrewAI's own runtime reads on ANY
#     flow, so they are refused whatever the workflow is.
#   WORKFLOW_RESERVED_RUN_INPUT_KEYS - what each registered workflow's state
#     declares beyond the one public prompt it reads.
#   the UNION - the answer for a workflow id nobody recognises. Fail CLOSED:
#     inventing a workflow id must never be the cheapest way to get a control
#     key past the check, and an id that failed its OWN validation arrives
#     here as None.
#
# The check stays ON the pydantic model, which is what keeps the existing
# 403-vs-422 distinction meaningful: pydantic validates fields in DECLARATION
# order and `workflow_id` is declared before `inputs` (`service/models.py`), so
# `info.data` already carries a validated workflow id when `inputs` is checked.
#
# But the model holds an id and no registry, so it cannot ask the union without
# refusing a registered third workflow's own public prompt - `brief` is a Brief
# Crew result slot AND somebody else's legitimate prompt field. So the two
# questions have two functions: the SCHEMA asks
# `declared_reserved_run_input_keys`, which answers the two built-ins' declared
# names and only the global keys for EVERY other id - registered or invented,
# because a registered graph has an owner and the schema layer runs before
# ownership is checked (D-01-1) - and `create_run` asks
# `reserved_run_input_keys` for the fail-closed union once it has resolved the
# workflow, checked who may see it, and knows which single key is its prompt.
# --------------------------------------------------------------------------

# `id` is here rather than in the validator's list because it is not this
# project's control key at all - it is CrewAI's. `kickoff(inputs={"id": ...})`
# restores a persisted flow STATE with an empty completed-method set, which
# re-runs the flow from @start rather than resuming it (the same mechanism
# VALIDATOR_ORPHAN_RUN_RECOVERY's note below spells out). A caller who could
# set it would be choosing which stored state their run starts from.
#
# `no_gates` and `sequential_branches` are global for a weaker but sufficient
# reason: they are execution-mode words any flow here would spell the same way,
# and refusing them everywhere costs a legitimate caller nothing.
GLOBAL_RESERVED_RUN_INPUT_KEYS: frozenset[str] = frozenset(
    {"id", "no_gates", "sequential_branches"}
)

# Keyed by workflow id. The two literals MUST equal `service/graph.py`'s
# BRIEF_WORKFLOW_ID and VALIDATOR_WORKFLOW_ID; they are spelled out because
# that module imports this one and the dependency cannot run both ways.
# `tests/builder/test_document.py::ReservedRunInputKeyTests` pins both spellings
# and the Brief Crew field list against `BriefState`, so a renamed state field
# fails a test instead of quietly opening a control key.
#
# Brief Crew's entry is everything `main.BriefState` declares except `topic`,
# which is its one public prompt. `run_id` is on the list for the same reason
# the validator reserves `source_run_id`: it stamps attribution on indexed
# cache evidence.
#: The two workflows whose state names are DECLARED in this file, as opposed to
#: registered into the dict below by a publish. `declared_reserved_run_input_keys`
#: answers the dict only for these two - see its docstring for why the schema
#: layer may never read a registered graph's entry.
BUILT_IN_WORKFLOW_IDS: frozenset[str] = frozenset({"brief-flow", "idea-validator"})

WORKFLOW_RESERVED_RUN_INPUT_KEYS: dict[str, frozenset[str]] = {
    "brief-flow": frozenset(
        {
            "run_id",
            "retrieved",
            "route",
            "research_notes",
            "scraped_sources",
            "brief",
            "usage",
        }
    ),
    "idea-validator": RESERVED_RUN_INPUT_KEYS,
}


def register_workflow_reserved_run_input_keys(
    workflow_id: str, keys: Iterable[str]
) -> None:
    """Declare a compiled builder graph's own state names as reserved.

    The seam a builder registration uses, and deliberately a mutation rather
    than a literal: a builder graph's state names are not knowable when this
    file is written. It mirrors `RunRegistry.workflows`, which is likewise a
    plain mutable dict a builder workflow is registered into.

    The union `reserved_run_input_keys` falls back to is RECOMPUTED on every
    call rather than snapshotted at import, so a graph registered afterwards
    still fails closed for an unknown id.
    """

    WORKFLOW_RESERVED_RUN_INPUT_KEYS[workflow_id] = (
        GLOBAL_RESERVED_RUN_INPUT_KEYS | frozenset(keys)
    )


def forget_workflow_reserved_run_input_keys(workflow_id: str) -> None:
    """Undo the declaration above, and refuse to disarm a built-in.

    The mirror image of `register_workflow_reserved_run_input_keys`, and it
    exists because for a while there was no mirror: `unregister_builder_workflow`
    cleared four maps while registration wrote five, so a publish rollback, a
    rehydration rollback or a delete left this dict declaring state names for a
    workflow the service no longer has. That stale entry is not inert. It is
    the answer `reserved_run_input_keys` gives for that id, and
    `all_reserved_run_input_keys` unions it into the answer for EVERY unknown
    id - so a deleted graph goes on refusing its own state names as control
    keys in some later author's perfectly ordinary `inputs`, and the only way
    back is a process restart.

    The two built-in ids are literals here for the same reason they are
    literals in `WORKFLOW_RESERVED_RUN_INPUT_KEYS` above - `service/graph.py`
    imports this module and the dependency cannot run both ways - and the guard
    is the same one `unregister_builder_workflow` makes: a pop keyed on a
    bug-supplied id would silently open every control key on `idea-validator`,
    which is the single check standing between a request body and `no_gates`.
    """

    if workflow_id in BUILT_IN_WORKFLOW_IDS:
        raise ValueError(f"{workflow_id} is a built-in workflow and is not removable")
    WORKFLOW_RESERVED_RUN_INPUT_KEYS.pop(workflow_id, None)


def all_reserved_run_input_keys() -> frozenset[str]:
    """Every reserved key of every registered workflow, plus the global set."""

    union = GLOBAL_RESERVED_RUN_INPUT_KEYS
    for declared in WORKFLOW_RESERVED_RUN_INPUT_KEYS.values():
        union = union | declared
    return union


def reserved_run_input_keys(workflow_id: str | None) -> frozenset[str]:
    """The `inputs` keys this workflow refuses, failing CLOSED on an unknown id.

    `None` reaches here when nobody could name a workflow at all; an
    unregistered id reaches here when a caller invents one, or when a workflow
    is registered on the service without declaring its state names here. All of
    them answer the UNION, so no control key is ever free by accident.

    The caller is `create_run`, which subtracts the workflow's own public
    prompt before intersecting - see `declared_reserved_run_input_keys` below
    for why that subtraction cannot be made here, and why the request SCHEMA
    asks that function instead of this one.
    """

    if workflow_id is not None:
        declared = WORKFLOW_RESERVED_RUN_INPUT_KEYS.get(workflow_id)
        if declared is not None:
            return GLOBAL_RESERVED_RUN_INPUT_KEYS | declared
    return all_reserved_run_input_keys()


def declared_reserved_run_input_keys(workflow_id: str | None) -> frozenset[str]:
    """The same question, asked by a layer that cannot resolve a workflow.

    Identical to `reserved_run_input_keys` for a workflow declared above, and
    only the GLOBAL keys for one that is not - because the pydantic model that
    calls this holds a workflow id and nothing else. It cannot tell "registered
    on this service but undeclared here" from "invented", and failing closed to
    the union at that layer refused a third workflow's own public prompt: a
    graph whose input field is `brief` collides with Brief Crew's result slot,
    and its author was told their prompt was a reserved control key by a
    workflow that has never heard of their graph.

    The union has not been abandoned; it has moved one layer down, to
    `create_run` - the only code that has resolved the workflow far enough to
    know which single key is its public prompt, and which can therefore refuse
    every other workflow's control keys without refusing this one's. Inventing
    an id buys nothing there either: an id in no map at all is a 404 before
    that check is reached, and the three keys CrewAI's own runtime reads on ANY
    flow are refused here for every id, invented ones included - which is what
    keeps `no_gates` unsettable from a request body, and therefore keeps the
    403-versus-422 distinction in `create_run` meaningful.

    **"Declared above" means the two literals, and NEVER an entry a publish
    registered** (D-01-1, 2026-09-03). This function used to read the whole
    dict, so for a PUBLISHED graph it answered that graph's own `__builder__`
    and `out__<node>` names to anybody who named its id - and pydantic runs
    before `create_run`'s rate limiter and its ownership 404. A stranger, or
    nobody at all, could therefore post `{"inputs": {"idea": "p",
    "out__scoper": "x"}}` and read off the 422-versus-404 whether the id
    existed and what its nodes were called, unthrottled, for a graph the same
    request with a clean body was told did not exist. That is the oracle
    `graph.py::workflow_visible_to` says it must not become, one layer up.

    So the schema layer consults a workflow's registered keys ONLY through
    `create_run`, after the caller has been allowed to see that workflow; here
    a registered id and an invented one get the same answer, which is the
    global set. The two built-ins are public to everyone, so their declared
    names leak nothing - and they are the only ids this function has ever been
    entitled to call "declared".
    """

    if workflow_id in BUILT_IN_WORKFLOW_IDS:
        return GLOBAL_RESERVED_RUN_INPUT_KEYS | WORKFLOW_RESERVED_RUN_INPUT_KEYS[workflow_id]
    return GLOBAL_RESERVED_RUN_INPUT_KEYS


# --------------------------------------------------------------------------
# Builder graphs - the bounds a user-authored flow is compiled against
#
# A canvas lets somebody who has never read this file draw a graph that spends
# money. Every constant below is one of two things: a COUNT that bounds what
# can be drawn, or a term in the static price of what was drawn. They are
# grouped because they are read together - `builder/bounds.py` enforces the
# counts and `builder/budget.py` prices the result, and both refuse at COMPILE
# time, before a graph can ever take an admission slot.
#
# Enforcement stays three-layered, and the layers bound different things.
# Compile time refuses an unpriceable graph. Admission compares the stored
# estimate against MAX_QUEUED_RUNS. Runtime is MAX_RUN_COST_USD, the only one
# of the three that ever sees a real token count.
#
# THE PREMISE THIS REPLACES. "Human inaction is the de facto spend cap" - the
# argument VALIDATOR_ALLOW_AUTO_GATES is still built on - was already obsolete
# when MAX_RUN_COST_USD landed: spend is arithmetic now. A builder graph has to
# make that arithmetic possible BEFORE the run, which is what "statically
# priceable" means, and why a graph that cannot be priced is refused rather
# than admitted optimistically.
# --------------------------------------------------------------------------

# The whole graph, every kind of node, including the ones that cost nothing.
#
# 24 is the validator's 14 x 1.7, and the multiplier is checked against the
# frame ring rather than chosen: at the production rate of 102 frames per run
# over 14 nodes, 24 nodes is ~175 frames, so DEFAULT_RING_CAPACITY (2,000,
# `events/buffer.py`) still holds 11 complete passes of the graph. A bound that
# let a single pass overflow the ring would make the replay a reconnecting
# client receives structurally incomplete, and nothing would say so.
MAX_GRAPH_NODES = 24

# Nodes that call a model: `agent` and `crew`.
#
# THIS BOUND IS NOT THE MONEY BOUND, and reading it as one is what set it at 8.
# The sweep behind that number reported a pure chain - every node tooled, every
# node on a cycle, escalation deepest where the accumulated context is largest
# - pricing at $7.36 over 8 nodes and $10.14 over 10, against a $10 ceiling. It
# looked like a frontier. It was not: those are FLOOR prices, and the figure
# `budget_problems` actually enforces is the nitro-inflated one times
# GRAPH_STATIC_BUDGET_MARGIN, which puts that same 8-node corner at **$10.55 -
# already over.** `tests/builder/test_budget.py` has said so in its own
# docstring since it was written, and one of its tests is literally named
# `test_the_worst_graph_the_counts_permit_is_still_refused_on_price`.
#
# So the count never bounded the expensive graph. What it bounded was the
# CHEAP one: a 9-node chain with no tools, no cycle and no escalation node
# prices at $0.99 with the margin applied, and was refused anyway - by a
# sentence quoting two dollar figures that had nothing to do with it. The
# validator's own topology is exactly 8 billable, so the gallery hero errored
# on the first node a user added, and the error blamed a price the graph did
# not have.
#
# 13 is the validator's measured 8 x 1.7, the same headroom multiplier
# MAX_GRAPH_NODES already applies to the validator's 14 drawn nodes. Measured
# at 13, with `builder/budget.py`: the pathological shape prices at $21.62 with
# the margin and is refused ON PRICE, where that refusal belongs and where it
# names something an author can act on; an ordinary tooled chain prices at
# $5.41 and is allowed; a chain with no tools prices at $1.66.
#
# What this bound does now is bound SHAPE, not spend - 24 drawn nodes may not
# all be agents - and the layer that can measure money is left to do it.
MAX_BILLABLE_NODES = 13

# Of those 13, how many may sit on the escalation tier. 8 is the validator's
# measured split (5 of its 8 agent nodes) carried up by the same 1.7, which
# keeps the ratio it was derived from: 8/13 against the validator's 5/8. It
# moves for the same reason the count above does - the validator sat exactly on
# 5, so the template could not gain a single escalation node - and it is safe
# for the same reason: escalation is the priced tier, and thirteen escalation
# nodes on a cycle is a graph `budget_problems` refuses long before this does.
MAX_ESCALATION_NODES = 8

# Maximum out-degree of any node, and so the maximum number of branches a
# router may declare. 4 is the validator's measured maximum, at `route_scope`
# (market, sentiment, feasibility, revise_scope). It is cost-neutral - the node
# count already bounds spend - and what it really bounds is THREADS: three
# concurrent branches is what the fan-out was measured at, and GitHub's 10
# requests/minute per IP is the real constraint on widening it.
#
# THIS ONE DELIBERATELY DID NOT MOVE when the node counts did. The validator
# also sits exactly on it - `route_scope` fans out four ways - so the same
# "no headroom" complaint applies, and the answer is different because the
# bound is different in kind: the counts above were proxies for money and money
# has a layer that measures it, while this is a bound on CONCURRENT THREADS and
# on an external rate limit nobody here has re-measured. Widening it on
# judgement alone would be inventing a number, which is the mistake the counts
# above are being corrected for. The visible consequence is precise and worth
# stating: a template graph may gain nodes freely, but not a fifth branch off
# that one gate until somebody measures a four-branch fan-out for real.
MAX_FANOUT_WIDTH = 4

# A router may not declare fewer than two branches, because a one-branch router
# is a node with a decision that cannot go either way: it compiles, it runs and
# it means nothing. Exactly one branch must additionally be the `otherwise`, so
# an unmatched value goes FORWARD rather than wedging the run at a router whose
# declared comparisons all missed.
MIN_ROUTER_BRANCHES = 2

# Back edges in the drawn graph. The validator's measured count is 2
# (revise_scope -> confirm_scope, revise_verdict -> review_verdict), and the
# bound was that count with no headroom over it - so the template that ships in
# the gallery could not be given a third revise loop. 3 is the same 1.7 applied
# to the same measurement, and a cycle is the one shape here that is already
# priced exactly: every node on one is billed (1 + MAX_CYCLE_ITERATIONS) times
# by `builder/budget.py`, so a third loop that costs too much is refused with a
# dollar figure rather than with a count.
MAX_CYCLES = 3

# How many times a cycle may re-enter, worst case, and the multiplier the
# static price applies to every node on one.
#
# Deliberately NOT VALIDATOR_MAX_GATE_TURNS (5). That number is sized so a real
# scoping conversation is not cut short - it prices a HUMAN in the loop, who is
# both the cause of the delay and the brake on it. A builder cycle need not
# have one, and the arithmetic agrees: at 8 billable nodes, loop=5 costs $11.04
# and loop=3 costs $7.36. Both are FLOOR prices, and the note above
# MAX_BILLABLE_NODES is where that distinction was found to matter: the figure
# `budget_problems` enforces puts loop=3 at that shape at $10.55, so loop=3 is
# chosen because loop=5 is very much worse, not because loop=3 fits under the
# ceiling. It does not, and it is refused there.
#
# It is also the ceiling on a builder gate's own `max_turns`, for the same
# reason and by the same arithmetic - a revise loop through a gate IS a cycle,
# and giving it a second, larger bound would be two numbers for one fact.
MAX_CYCLE_ITERATIONS = 3

# --------------------------------------------------------------------------
# The ATTACHMENT family's own bounds - 03-node-library.md D2.
#
# None of the three is a money bound, and that is the whole reason they are
# separate numbers rather than a share of the ones above. An attachment is not
# a step: it never runs, never bills, never appears in a cycle and emits no
# frame, so neither the frame-ring arithmetic behind MAX_GRAPH_NODES nor the
# token model behind MAX_BILLABLE_NODES has anything to say about it. What each
# of these bounds is a PROMPT and a DOCUMENT, and the honest thing to record is
# which of the three rests on a measurement and which does not.
# --------------------------------------------------------------------------

# Attachment nodes on one canvas. 24 is MAX_GRAPH_NODES, the same ceiling
# applied to the other family, on the argument that a document may hold as many
# possessions as it holds steps. It is deliberately NOT derived from the frame
# ring, because an attachment emits no frames - the reason MAX_GRAPH_NODES is
# 24 does not transfer, and only the figure does.
#
# What actually bounds this in practice is the product below it:
# MAX_ATTACHMENTS_PER_NODE x the billable nodes that can carry them. This is
# the outer guard, so that a canvas full of unattached pills is refused by a
# count rather than by MAX_BUILDER_DOCUMENT_BYTES, which would name a byte
# figure no author can act on.
MAX_ATTACHMENT_NODES = 24

# Tools, MCP servers and skills hanging off ONE agent or crew.
#
# **This is the one figure here that nobody has measured**, and it is recorded
# as 03-node-library.md's C2 declares it rather than dressed up as arithmetic.
# What it bounds is the agent's system prompt: every attachment contributes a
# tool schema or a skill preamble, and past some width the agent stops choosing
# well - a claim about model behaviour that this repository has not tested.
# 8 is the plan's number and the shipped validator's most-tooled agent binds 1,
# so there is a great deal of headroom and no evidence about where it ends.
#
# It is treated the same way MAX_FANOUT_WIDTH is: left where the plan put it
# until somebody measures a wide attachment set for real, rather than widened
# or narrowed on judgement, which would be inventing a number.
MAX_ATTACHMENTS_PER_NODE = 8

# Agents inside one authored crew, along `member` edges.
#
# 6 is a measurement: it is the shipped six-agent validator's own crew count -
# Scoper, Market, Sentiment, Feasibility, Synthesist, Reporter - which is
# `grep -c '^@CrewBase' src/brief_crew/crews/validator_crew/validator_crew.py`.
# No headroom multiplier is applied, and that is the difference from
# MAX_BILLABLE_NODES: the counts above were widened by 1.7 because the
# validator sat exactly on them and the gallery template could not gain a node,
# where a crew's membership is not a shape an author grows into - a seventh
# member is a different crew. The lower end is 1 rather than 0, because a crew
# with no members compiles to a Crew with no tasks and returns nothing.
MAX_CREW_MEMBERS = 6

# Headroom over the static estimate, applied when the estimate is compared to
# MAX_RUN_COST_USD. The estimate is a token model calibrated on ONE paid run;
# 1.25 is the margin that stops a graph priced at the very edge of the ceiling
# being admitted on the strength of that one calibration.
GRAPH_STATIC_BUDGET_MARGIN = 1.25

# `:nitro` routes to the FASTEST provider, not the cheapest, so the cheap
# tier's entry in PRICES is a floor rather than a bound - the note above
# CHEAP_MODEL says exactly that. Measured against the live catalogue: eight
# endpoints serve `gemini-3.5-flash-lite`, from $0.15/$1.25 to $0.54/$4.50,
# with the configured $0.30/$2.50 sitting in the middle. 1.8 is that spread's
# top over the recorded price, applied to every cheap-tier node in the STATIC
# estimate only.
#
# Interim, and it says so: drop the factor once a provider is pinned. It is
# deliberately NOT applied inside `compute_cost_usd`, which reports what a call
# is believed to have actually cost and must not inflate a figure an operator
# reads as a measurement.
NITRO_PRICE_FACTOR = 1.8

# The two token terms in the static estimate, both taken from the first paid
# run (`8b5a0a78`: 11 calls, 128,069 tokens, 46,787 of them completion).
#
# 46,787 / 11 = 4,253 completion tokens per call, and that same figure is the
# per-call CONTEXT growth term: a node's prompt is modelled as the seed plus
# every upstream billable node's output. That is why the estimate prices each
# node at its own DEPTH rather than at an average - a 20-deep chain costs 3.9x
# per call what a 1-deep one does, and an average would under-price precisely
# the shape that gets expensive.
GRAPH_BUDGET_SEED_PROMPT_TOKENS = 2000
GRAPH_BUDGET_CALL_COMPLETION_TOKENS = 4253

# Whether a graph with no human gate may be launched ANONYMOUSLY. Read the way
# `service/app.py` already reads VALIDATOR_ALLOW_AUTO_GATES:
# `if not (user or BUILDER_ALLOW_GATELESS_GRAPHS): 403`.
#
# Default OFF, and - exactly like VALIDATOR_ALLOW_AUTO_GATES - that is a cost
# decision rather than a security one, which is why it is a flat False and not
# a value derived from AUTH_BASE_URL the way VALIDATOR_REQUIRE_AUTH's is. The
# difference is what the wrong answer costs. Getting VALIDATOR_REQUIRE_AUTH
# wrong serves every paid endpoint anonymously with nothing on screen to say
# so, so its default has to fail closed by derivation. This flag is already
# irrelevant wherever auth is on, because `user` is then always truthy: it
# binds only the anonymous case, which is the one it was written for.
#
# What it costs when it is on: a gateless graph runs every billable node it
# declares with nobody watching, up to the static estimate bounded above. With
# it off, an anonymous author must keep one gate reachable before the first
# billable node, so an unanswered run stops after at most one model call - the
# same brake, and the same reasoning, as the validator's.
BUILDER_ALLOW_GATELESS_GRAPHS = _env_flag("BUILDER_ALLOW_GATELESS_GRAPHS", False)

# Whether a booting process re-registers every PUBLISHED builder graph from the
# document store. Default ON, and the default is the whole point.
#
# All six registration sites a publish writes to - GRAPHS, NODE_REGISTRIES,
# WORKFLOWS, BUILDER_WORKFLOWS, the reserved-key map, and the registry's own
# runtime dict - are process-local. The documents are not. Both Render services
# carry `autoDeploy: yes`, so before this pass existed every push to `main`
# silently unpublished every user graph: the row still said `published`, the
# canvas still said `published`, and `POST /api/sessions/{id}/runs` answered 404
# for a workflow the author had published an hour earlier. That is the same
# shape as the orphaned runs of remaining-work item 32 - durable state and
# process state disagreeing across a restart, with only the process state
# consulted - and it gets the same answer: reconcile at boot, loudly.
#
# The switch exists for the one case where re-registering is the wrong move: a
# graph that compiles and then wedges or bankrupts this deployment. Turning it
# off is a deploy-time flip that boots with no user graph registered at all,
# rather than an edit to code or a DELETE against somebody's document. It is
# NOT a test lever - a test that wants no rehydration builds an app with no
# persistence, and the sweep is then a no-op with nowhere to read from.
BUILDER_REHYDRATE_PUBLISHED = _env_flag("BUILDER_REHYDRATE_PUBLISHED", True)

# The saved document, in bytes. MAX_REQUEST_BODY_BYTES (64 KiB) is the bound on
# every other request into this service and it is far too small here: 24 nodes
# with positions, labels, prompts and router rules is legitimately larger than
# any gate reply will ever be. 256 KiB is ~10 KiB a node at the node ceiling,
# generous for a document whose largest field is a gate message. The save
# endpoint therefore needs its own exemption from the ASGI-edge check rather
# than a raised global bound: a megabyte of `inputs` on the RUN endpoint would
# still be a cost, and this is not that endpoint.
MAX_BUILDER_DOCUMENT_BYTES = 256 * 1024

# --------------------------------------------------------------------------
# Builder documents - the author-facing vocabulary
#
# Every pattern and allowlist the document schema and the compiler both read.
# They live here for the usual reason and one extra one: `builder/document.py`
# validates what an author may write and `builder/compiler.py` asserts what it
# emitted, and those two agreeing is the whole of the compiled-namespace
# guarantee.
# --------------------------------------------------------------------------
BUILDER_DOCUMENT_SCHEMA = "builder.flow/v1"

# Server-assigned, never author-chosen, so the shape is exact.
BUILDER_DOCUMENT_ID_PATTERN = r"^ug_[0-9a-f]{8}$"

# Author-facing node and edge ids. Lowercase, identifier-shaped and at most 40
# characters, which is what keeps the compiled `n{index}_{node_id}` well under
# MAX_IDENTIFIER_LENGTH (128, `events/models.py`) - a limit that TRUNCATES
# silently rather than raising, and a truncation there merges two nodes into
# one in every frame the run emits.
BUILDER_ID_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
BUILDER_MAX_ID_CHARS = 40

# The compiled flow method idents and router event labels. Every method starts
# `n`, every label starts `e`, so the two namespaces cannot collide - and
# `builder/bounds.py` asserts the disjointness rather than trusting the prefix,
# because the guarantee is only ever worth what the generator does.
#
# The `{1,40}` body is a real bound, not decoration: a GATE compiles to two
# methods and the second is `n{index}_route_{node_id}`, so a gate's node id has
# BUILDER_GATE_ROUTER_PREFIX's six characters less room than any other node's.
BUILDER_METHOD_IDENT_PATTERN = r"^n[0-9]{1,2}_[a-z0-9_]{1,40}$"
BUILDER_EVENT_LABEL_PATTERN = r"^e[0-9]{1,2}_[a-z0-9_]{1,40}$"
BUILDER_MAX_IDENT_BODY_CHARS = 40
BUILDER_GATE_ROUTER_PREFIX = "route_"
# The same trick a second time, for the second thing that needs a router it did
# not draw. A billable node whose `on_error` is `route` compiles to TWO methods
# - the step, and a paired deterministic router that reads `err__<node>` and
# chooses the `out` or the `error` port - because only a `@router` can choose an
# event, and a step that raised past its own listener would end the run instead
# of taking the recovery path the author drew (09 D3).
BUILDER_ERROR_ROUTER_PREFIX = "route_err_"
# Where a step records the reason it failed, so its paired router can read it.
# A separate namespace from `out__` deliberately: a failed node's OUTPUT is
# still null, and folding the two would make "this node produced nothing" and
# "this node exploded" the same state.
BUILDER_STATE_ERROR_PREFIX = "err__"

# The ONE expression shape a `with:` value may take besides a JSON literal.
# Single-key by construction: only `${state.a_value}` was ever measured
# resolving, and nested dotted access into a sub-dict was not - which is why
# the compiler writes every node's return to a flat `out__<node_id>` key rather
# than nesting it.
BUILDER_STATE_REF_PATTERN = r"^\$\{state\.[a-z0-9_]{1,64}\}$"
BUILDER_STATE_OUTPUT_PREFIX = "out__"

# Display text. The label is what the canvas draws on a node; the name is what
# the author calls the whole graph.
BUILDER_MAX_LABEL_CHARS = 40
BUILDER_MAX_NAME_CHARS = 80

# A gate's message is the only long free text in the document, and it is shown
# to the operator who has to answer it.
BUILDER_MAX_GATE_MESSAGE_CHARS = 2000

# Per-node agent limits. Both are ceilings on RETRY, which is where one node's
# cost multiplies: CrewAI counts guardrail retries PER GUARDRAIL, so the unset
# default of 3 permits eight full regenerations of a two-guardrail task.
# `max_iter` is the agent's own tool loop; 8 is CrewAI-generous, and the
# research branches in this repo run at VALIDATOR_BRANCH_MAX_ITER = 2.
BUILDER_MAX_AGENT_ITER = 8
BUILDER_MAX_GUARDRAIL_RETRIES = 2

# --------------------------------------------------------------------------
# What an AUTHORED agent or crew may write - 03-node-library.md D3, FD5.
#
# A library node names a YAML agent and carries no prose; an authored one
# carries its own role, goal, backstory and task text, so these four ceilings
# exist for the first time here. They live in this file rather than as literals
# in `builder/document.py` for the platform rule's reason - a runtime limit
# inlined at its use site is a limit nobody can find - and each says what it is
# derived from, because a bound with no derivation is a number somebody will
# move on a whim.
# --------------------------------------------------------------------------

# One free-text prompt field: `role`, `goal`, `backstory`, or a task's
# `description` / `expected_output`. 4000 is 03-node-library.md's C2
# (`max_prompt_chars`), and it is twice BUILDER_MAX_GATE_MESSAGE_CHARS on the
# argument that a gate message is one question to a human while a backstory is
# the whole of what an agent knows about itself. It is a DOCUMENT bound and not
# a token bound: what the prompt costs is priced by `builder/budget.py` and
# capped by MAX_RUN_COST_USD, which is the layer that can measure money.
BUILDER_MAX_PROMPT_CHARS = 4000

# Whole-node retries - `retry.max_retries`, the builder's own loop inside
# `run_agent`, and NOT CrewAI's deprecated `Task.max_retries`, which counts
# guardrail retries and is a different concept sharing a name. 3 is
# 03-node-library.md's C2 (`max_retries`), and it is the same figure as
# MAX_CYCLE_ITERATIONS for the same reason: a retry multiplies a node's price
# exactly the way a cycle does, so the two ceilings that multiply spend are
# deliberately equal rather than independently chosen.
BUILDER_MAX_NODE_RETRIES = 3

# The pause between those retries. 60 s x BUILDER_MAX_NODE_RETRIES is three
# minutes of a worker thread sleeping inside one node, which is well under
# VALIDATOR_GATE_TIMEOUT_SECONDS - so a retrying node can never outlive the
# gate an operator is waiting at, which is the one interaction that would be
# invisible from either side.
BUILDER_MAX_RETRY_BACKOFF_SECONDS = 60

# `planning_config.max_steps`, one of the FOUR of its eleven fields the S9
# deprecation ruling admits. 20 is CrewAI 1.15.18's own default for that field
# (`crewai/agent/planning_config.py`), taken rather than invented: the package
# owns what a planner does and this repository owns only whether an author may
# raise it.
BUILDER_MAX_PLANNING_STEPS = 20

# The three registered research tools an `agent` node may bind, by the name
# each tool declares. Restated here because `tools/` imports this module and
# the dependency cannot run both ways; `tests/builder/test_document.py` asserts
# this set equals the three modules' own TOOL_NAME constants, so a renamed tool
# fails a test rather than silently becoming unbindable.
BUILDER_RESEARCH_TOOLS: frozenset[str] = frozenset(
    {
        "research_market_landscape",
        "analyze_community_sentiment",
        "assess_technical_feasibility",
    }
)

# The six transform operations, and the whole of the "no user Python" position.
# A transform node picks, merges, joins, serialises, defaults or formats - each
# with a declared argument shape - and there is no seventh escape hatch.
BUILDER_TRANSFORM_OPS: frozenset[str] = frozenset(
    {"pick", "merge", "join_text", "to_json", "default", "format"}
)

# The comparisons a router branch may declare over ONE state key. No user
# expressions, because an expression surface is an evaluation surface.
# `otherwise` is not a comparison and is named separately: exactly one branch
# must carry it, and it takes no key and no value.
BUILDER_ROUTER_COMPARISONS: frozenset[str] = frozenset(
    {"eq", "ne", "gt", "gte", "lt", "lte", "contains"}
)
BUILDER_ROUTER_OTHERWISE = "otherwise"

# The ten compiler-owned entrypoints, and the ONLY values a compiled `do.ref`
# may take. The document carries no ref of its own - that is the whole answer
# to the code-execution surface a canvas would otherwise open, and author data
# travels in `with:` as data instead.
#
# `call: "script"` is never emitted: CrewAI's own `_actions.py` records that
# inline script execution is not sandboxed, and it is gated behind an env var
# this service refuses to boot with.
BUILDER_ACTION_REFS: frozenset[str] = frozenset(
    {
        "brief_crew.builder.runtime:seed_input",
        "brief_crew.builder.runtime:run_agent",
        "brief_crew.builder.runtime:run_crew",
        "brief_crew.builder.runtime:render_gate",
        "brief_crew.builder.gates:GATE_PROVIDER",
        "brief_crew.builder.runtime:route_gate",
        "brief_crew.builder.runtime:route_branch",
        "brief_crew.builder.runtime:transform",
        "brief_crew.builder.runtime:rejoin",
        "brief_crew.builder.runtime:emit_output",
        # The ELEVENTH, added by 09 D7. A derived replay plan compiles every
        # node upstream of a resume or a node test to this ref instead of to
        # the entrypoint that would have billed, so the downstream listeners
        # fire exactly as they would after a real run and nothing calls a
        # model. It widens what the entrypoints ACCEPT and not what the set is
        # for: `node_id` and a `source` word, both values, neither a name.
        "brief_crew.builder.runtime:replay_output",
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
# Authorization joined the list when Better Auth landed, and it is load-bearing
# rather than tidy: `Authorization` is NOT on the CORS safelist, so a browser
# preflights every authenticated call and drops the real request unless this
# names it. Omitting it does not produce a 401 - it produces a CORS failure in
# the console and a request the API never sees, which reads like the API is
# down.
#
# Note this does NOT flip CORS_ALLOW_CREDENTIALS. That switch governs cookies
# and TLS client certs, which the browser attaches on its own; an Authorization
# header set explicitly by our own JavaScript is an ordinary header. The
# warning above still binds if COOKIE auth is ever added here.
CORS_ALLOW_HEADERS = ("Accept", "Authorization", "Content-Type")

# ETag is NOT on the CORS-safelist for response headers, so a cross-origin
# reader of /api/workflows/{id}/graph cannot see the graph version unless it is
# named here. Content-Disposition is deliberately absent: downloadLogs names
# the file itself from the run id.
# Retry-After joins it for the same reason: run creation answers 429 with
# one, and a cross-origin client cannot read it unless it is named here.
CORS_EXPOSE_HEADERS = ("ETag", "Retry-After")

# --------------------------------------------------------------------------
# Authentication - Better Auth (frontend/server/auth.ts)
#
# The SPA and this API are separate ORIGINS, and `onrender.com` sits on the
# Public Suffix List, so the browser will not let them share a session cookie.
# The SPA therefore fetches a SHORT-LIVED JWT from its own origin (where the
# httpOnly session cookie does work) and sends it here as a Bearer token. This
# service verifies that token offline against the auth server's JWKS: no shared
# secret, no database round trip on the hot path, and no call back into the
# auth service while serving a request.
# --------------------------------------------------------------------------

# The ORIGIN of the Better Auth service - scheme and host, no trailing slash.
# It is three things at once, which is why one value drives all of them: the
# JWKS location, the expected `iss`, and the expected `aud`. Empty means no
# auth server is configured.
AUTH_BASE_URL = os.getenv("AUTH_BASE_URL", "").strip().rstrip("/")

# Auth is required whenever an auth server is configured, and the default is
# deliberately derived rather than a flat False.
#
# A flat False fails OPEN: a deployment that sets AUTH_BASE_URL, wires the
# login screen and forgets one boolean would serve every paid endpoint
# unauthenticated, and nothing on screen would say so. Deriving it means the
# half-configured state does not exist - configuring an auth server IS turning
# auth on. This is the same reasoning as CORS_ALLOW_ORIGINS' empty default
# above: when a mistake is possible, make the mistake the loud one.
#
# The unset case stays off so the test suite, the SYNTHETIC runners and a bare
# local checkout keep working with no auth server running at all.
VALIDATOR_REQUIRE_AUTH = _env_flag("VALIDATOR_REQUIRE_AUTH", bool(AUTH_BASE_URL))

# How long a fetched JWKS is trusted before it is re-fetched. An unknown `kid`
# forces an immediate refresh regardless, so this bounds staleness after a key
# ROTATION, not after a key addition.
AUTH_JWKS_CACHE_SECONDS = _env_positive_int("AUTH_JWKS_CACHE_SECONDS", 3600)

# How long to wait for the JWKS document itself.
#
# 45s, not the 10s this was hardcoded at, and the reason is measured rather than
# cautious: `AUTH_BASE_URL` is the studio's own Node service, which `render.yaml`
# puts on Render's FREE plan - so it SLEEPS. Timed on 2026-09-01, that origin
# answered in 2.12s warm and **40s cold**.
#
# A JWKS fetch that times out does not degrade gracefully. `_refresh` keeps the
# keys it already has, but a process that has never fetched any has none, so
# every bearer token is rejected - and the operator, who is correctly signed in,
# is told to sign in. The failure looks like a credential problem and is
# actually a cold start.
#
# It is bounded rather than removed because this runs on the request path, and
# an unbounded fetch there would hold a worker open indefinitely.
AUTH_JWKS_TIMEOUT_SECONDS = _env_positive_int("AUTH_JWKS_TIMEOUT_SECONDS", 45)

# Clock skew allowance when checking `exp`/`iat`. Two independent Render
# instances are not perfectly synchronised, and a token minted one second in
# the future must not be rejected as invalid.
AUTH_JWT_LEEWAY_SECONDS = _env_positive_int("AUTH_JWT_LEEWAY_SECONDS", 60)

# Ed25519. Declared here AND in frontend/server/auth.ts's `keyPairConfig`,
# because a verifier that accepts whatever the token's own header claims is a
# verifier that can be talked into accepting `alg: none` or an HMAC forged with
# the public key. The list is the allowlist passed to PyJWT, and the two files
# name the same value on purpose - if one changes, the other must change in the
# same commit or every login breaks at the API boundary.
AUTH_JWT_ALGORITHMS = ("EdDSA",)

# --------------------------------------------------------------------------
# The credential vault - contract C4, .agent/plans/01-auth-and-workspaces.md
#
# CREDENTIALS_MASTER_KEY is base64 of 32 bytes. It is read HERE and nowhere
# else, through os.getenv like every other knob, so the section 6 scan in
# docs/tech-stack.md finds it. The boot check that refuses to start with auth
# on and no key lives in service/app.py beside the auth checks (01 D3), and
# is the same shape as the VALIDATOR_REQUIRE_AUTH rule above: configuring the
# vault half-way is the loud failure, not the quiet one. Empty with auth OFF
# means "no vault" - the credential routes answer 503 and nothing else
# changes, so tests, SYNTHETIC mode and a bare checkout keep working.
# --------------------------------------------------------------------------
CREDENTIALS_MASTER_KEY = os.getenv("CREDENTIALS_MASTER_KEY", "").strip()

# One credential is one encrypted JSON object of its fields. 4 KiB is a
# PostgreSQL DSN with room to spare and refuses a pasted PEM by an order of
# magnitude; the POST answers 413 over it.
MAX_CREDENTIAL_BYTES = 4096

# `cr_` + 8 hex, minted like `ug_` document ids (BUILDER_DOCUMENT_ID_PATTERN).
# The Integrator's S1 ruling: 15 D6 wrote `cred_` + 16 hex and 01 C4 wrote
# this; C4 owns the id shape, and every consumer - the document field, the
# export strip, the store - reads the pattern from here rather than restating
# it. The column is String(128) regardless, like every other id.
CREDENTIAL_ID_PATTERN = r"^cr_[0-9a-f]{8}$"

# The kinds 01 D4 tables, and the fields the vault requires for each. A POST
# naming a kind outside this set, or missing one of its fields, is a 422 with
# the field named. `e2b` is listed so a row can exist; nothing constructs from
# it in v1 (PLANS.md decision 3).
CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    "openrouter": ("api_key",),
    "firecrawl": ("api_key",),
    "serper": ("api_key",),
    "tavily": ("api_key",),
    "exa": ("api_key",),
    "brave": ("api_key",),
    "github": ("token",),
    "postgres": ("dsn",),
    "http_header": ("name", "value"),
    "mcp_header": ("name", "value"),
    "e2b": ("api_key",),
}
CREDENTIAL_KINDS: frozenset[str] = frozenset(CREDENTIAL_FIELDS)

# The vault's route-level constants (01 D3, D4), moved here at Stage 1
# integration from service/credentials.py under S1 ruling 3. That module
# re-exports them under the same names.
#: What every credential route answers (503) while auth is OFF and no master
#: key is set: "no vault", and nothing else about the service changes.
VAULT_NOT_CONFIGURED_DETAIL = "credential vault is not configured"
#: A probe is a user-initiated call to the provider's cheapest authenticated
#: read, and it is rate-limited with the run limiter's key. Five seconds is
#: the same budget 01 D4 gives the postgres `SELECT 1`.
CREDENTIAL_PROBE_TIMEOUT_SECONDS = 5.0
#: The two free authenticated reads 01 D4 names. Firecrawl has none, so its
#: probe is a format check that says so.
OPENROUTER_KEY_PROBE_URL = "https://openrouter.ai/api/v1/auth/key"
GITHUB_RATE_LIMIT_PROBE_URL = "https://api.github.com/rate_limit"
#: `user_credentials.label` is String(80) (15 D6, C10); the POST answers 422
#: over it rather than letting the database truncate or refuse.
MAX_CREDENTIAL_LABEL_CHARS = 80
#: The kind an authored agent's `credential_id` must name. The agent's model
#: is always OpenRouter here (S1 ruling 8: `credential_id` on AgentConfig is
#: the stand-in for C1 v2's `llm.credential_id`), so a `github` token on an
#: agent node is refused by name at resolution rather than failing inside
#: `LLM(api_key=...)` after the run has started.
AGENT_CREDENTIAL_KIND = "openrouter"
if AGENT_CREDENTIAL_KIND not in CREDENTIAL_KINDS:
    raise RuntimeError(
        f"AGENT_CREDENTIAL_KIND {AGENT_CREDENTIAL_KIND!r} is not one of CREDENTIAL_KINDS"
    )

# The synthetic identity (01 D8): the header a zero-cost test sets to BE
# somebody. `current_user` honours it only when the app was built
# `synthetic=True` AND AUTH_BASE_URL is unset - the same fail-closed shape as
# EXPOSE_API_DOCS - and ignores it everywhere else. The pattern is also the
# bound the E2E harness checks a cookie against before forwarding it
# (frontend/e2e/syntheticUser.ts), so the two must move together.
SYNTHETIC_USER_HEADER = "X-Synthetic-User"
SYNTHETIC_USER_PATTERN = r"^[a-z0-9_-]{1,64}$"

# Two document-lifecycle constants (15 D3, S1 ruling 7), moved here from
# service/builder_api.py under S1 ruling 3.
#: What a duplicate is called. Appended, and the base is trimmed to make room
#: rather than the suffix dropped, because a copy that cannot be told from its
#: source in the sidebar is the one thing a duplicate must not be.
COPY_SUFFIX = " copy"
#: What an import is called when the caller already has a document by the
#: file's name (round 2, D-15-4). Applied only on a collision: a colleague's
#: file imported into an empty library keeps its own name, and the author's
#: own export imported back reads "<name> imported" - then "<name> imported 2"
#: - rather than a second row identical to the first down to the letter.
IMPORT_SUFFIX = " imported"
#: How many `needs_credentials` entries an import envelope may name. A node id
#: per graph node is the most a strip can produce; anything beyond that is a
#: file that was not written by an export. The server re-derives the list
#: anyway; this only bounds what it is willing to parse.
MAX_IMPORT_NEEDS_CREDENTIALS = MAX_GRAPH_NODES

# How a stored version came to be, for the version browser (round 2, D-15-3).
#: What a CLIENT may declare on a save. The server composes the stored string
#: from it - `saved`, `autosaved`, `restored from v3` - and writes `created`,
#: `imported` and `duplicated` itself on the routes that mint a row. Round 1
#: found two rows that read "3 Sept, 00:19 · DRAFT" apart from 0.2 KB, so
#: choosing which to restore was guesswork; the source is one of the three
#: facts that tell them apart, beside the name-and-node-count label and a
#: relative time with seconds.
BUILDER_VERSION_SAVE_SOURCES: tuple[str, ...] = ("save", "autosave", "restore")
#: `builder_document_versions.source` is VARCHAR(64), added through
#: `persistence._ADDITIVE_COLUMNS` because that table shipped before it
#: (plan 15 D6, C10, amended 2026-09-03). NULL on older rows reads as `stored`.
BUILDER_VERSION_SOURCE_MAX_CHARS = 64

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
# Durable run retention - .agent/plans/15-persistence.md D7
#
# The in-memory eviction above (VALIDATOR_RUN_RETENTION_SECONDS) never touched
# a row, so terminal runs, their frames, metrics and gates accumulated forever
# (CLAUDE.md closed item 32). This is the durable half: terminal runs older
# than this many DAYS are deleted by the same periodic sweep the orphan
# recovery uses, and `run_frames` / `run_node_metrics` / `run_gates` follow by
# ON DELETE CASCADE. Documents, versions, credentials, skills and tools are
# never purged by it.
#
# 0 means keep everything, which is the deployed behaviour today and stays the
# default until PLANS.md decision 23 is answered. `minimum=0` because zero is
# the meaningful "off" value here, not a mistake.
# --------------------------------------------------------------------------
VALIDATOR_RUN_RETENTION_DAYS = _env_positive_int("VALIDATOR_RUN_RETENTION_DAYS", 0, minimum=0)

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


# --------------------------------------------------------------------------
# Plan 06 - the tool registry
#
# "Tools = hands." A `tool` attachment node names a CATALOGUE ID and nothing
# else: the server maps that id to a factory, exactly as BUILDER_ACTION_REFS
# maps a compiled `do.ref` to one of ten entrypoints. No module path, no class
# name and no callable reaches a document, which is the same closed-set answer
# to code execution the compiler already gives.
#
# The catalogue itself lives in `builder/tools.py` - a tuple of entries with a
# factory each - because an entry carries a param schema and a class reference,
# neither of which belongs in a constants module. What lives here is what the
# platform rule says lives here: the bounds and the flags.
# --------------------------------------------------------------------------
#: `research`, `web`, `data`, `custom` - the four headings the palette groups
#: catalogue tiles under. Declared here so the vocabulary can serve the order
#: and the client never holds a copy (cut-list 17: no client fallback list).
BUILDER_TOOL_CATEGORIES: tuple[str, ...] = ("research", "web", "data", "custom")

#: `ToolFailurePolicy` (`crewai/tools/tool_failure.py`) as this product spells
#: it. `warn` is CrewAI's own default and stays this product's; `raise` is the
#: setting that makes plan 12's error edge fire on a tool failure, because only
#: a raised `ToolExecutionFailedError` leaves the step.
BUILDER_TOOL_FAILURE_POLICIES: tuple[str, ...] = ("ignore", "warn", "raise")
BUILDER_DEFAULT_TOOL_FAILURE_POLICY = "warn"

#: A user's declarative HTTP tool. `ut_` + 12 hex, minted the way `cr_` + 8 hex
#: is (CREDENTIAL_ID_PATTERN) - and deliberately inside BUILDER_ID_PATTERN's
#: own shape, because `ToolConfig.tool_id` is a `NodeId` and a document that
#: could not spell its own tool's id would be a catalogue nobody can reference.
CUSTOM_TOOL_ID_PATTERN = r"^ut_[0-9a-f]{12}$"
#: The tool NAME an agent sees in its prompt. The same shape as a node id, and
#: bounded at 40 for the same reason: it is interpolated into a tool list.
CUSTOM_TOOL_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
#: 16 rows per user against MAX_ATTACHMENTS_PER_NODE = 8: two full agents' worth
#: of bespoke tools, which is past the point where a second graph is the better
#: answer. The POST answers 422 over it.
MAX_CUSTOM_TOOLS_PER_USER = 16
#: One typed argument per property. 12 is MAX_RUN_INPUT_KEYS (16) minus room for
#: the envelope keys the tool adds; past a dozen arguments a cheap-tier model
#: stops filling the schema reliably, which is a tool that fails silently.
MAX_CUSTOM_TOOL_PROPERTIES = 12
#: Same ceiling as `user_tools.description` (String(1024), 15 C10).
MAX_CUSTOM_TOOL_DESCRIPTION_CHARS = 1024
#: The request template's own bounds. 30 s is `URLReadTool`'s own ceiling; 1 MiB
#: is the body a tool result may return before it is refused, an order of
#: magnitude under MAX_RUN_RESULT_BODY_CHARS so a single tool call can never be
#: the thing that loses a run row at write time.
CUSTOM_TOOL_MAX_TIMEOUT_SECONDS = 30
CUSTOM_TOOL_MAX_RESPONSE_BYTES = 1048576
#: The methods a request template may name. No PUT and no DELETE: a tool an
#: author drew on a canvas should not be able to destroy anything, and the two
#: that remain cover every read and every "ask the API a question" shape.
CUSTOM_TOOL_METHODS: tuple[str, ...] = ("GET", "POST")

# PLANS.md decision 3 - PROVISIONAL, owner to confirm. The code interpreter is
# BYO E2B key behind this flag and the flag is OFF. Two independent reasons,
# and the second arrived after the decision was taken: it runs somebody else's
# code on a paid third-party sandbox, AND CrewAI's own `Agent.allow_code_execution`
# / `code_execution_mode` are `Field(deprecated=True)` at 1.15.18, so the native
# path is going away regardless of what is decided here.
BUILDER_CODE_INTERPRETER_ENABLED = _env_flag("BUILDER_CODE_INTERPRETER_ENABLED", False)
#: E2B's own ceiling for one sandbox, passed as `sandbox_timeout`. Named here so
#: the entry exists and is priced the day the flag is turned on.
E2B_SANDBOX_TIMEOUT_SECONDS = 300

# PLANS.md decision 9 - PROVISIONAL, owner to confirm. The per-user override and
# the daily cap are BUILT; the platform key backing every user's research is
# OFF. With it off, `research_market_landscape` and the three Firecrawl entries
# require the author's own `firecrawl` credential and say so on the card.
BUILDER_PLATFORM_FIRECRAWL_DEFAULT = _env_flag("BUILDER_PLATFORM_FIRECRAWL_DEFAULT", False)
#: Calls per user per UTC day against the platform key, counted only when the
#: flag above is on and the author supplied no credential of their own. 50 is
#: two full idea-validator runs worth of market research with room over.
BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP = _env_positive_int(
    "BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP", 50
)


# --------------------------------------------------------------------------
# Plan 07 - the MCP client
#
# A bare string in `Agent.mcps` is a CrewAI AMP marketplace lookup unless it
# starts with `https://` (`crewai/mcp/tool_resolver.py`), so user input is NEVER
# passed as a string here: the runtime always builds an `MCPServerHTTP`,
# `MCPServerSSE` or `MCPServerStdio`. Everything below bounds what may go into
# one of those, and what a server is allowed to say back.
# --------------------------------------------------------------------------
#: `ms_` + 12 hex, inside BUILDER_ID_PATTERN's shape for the same reason
#: CUSTOM_TOOL_ID_PATTERN is: `McpConfig.server_id` is a `NodeId`.
MCP_SERVER_ID_PATTERN = r"^ms_[0-9a-f]{12}$"
#: The three transports `crewai/mcp/config.py` models. Order is the order the
#: panel offers them: remote first, because remote is what production allows.
MCP_TRANSPORTS: tuple[str, ...] = ("http", "sse", "stdio")
#: A discovery is one connect, one tool listing and a cleanup. 20 s is generous
#: for a healthy server and short enough that the FastAPI threadpool slot it
#: occupies is not a denial of service; the route answers 200 `status: error`
#: over it rather than 504, because the author needs the sentence in the panel.
MCP_DISCOVERY_TIMEOUT_SECONDS = 20
#: A day. Past it the panel offers "re-discover" rather than silently serving a
#: stale tool list, because a server that renamed a tool between discovery and
#: run simply fails to match `tool_filter` and the agent runs without it.
MCP_DISCOVERY_STALE_SECONDS = 86400
#: A tool name reaches the agent's tool list, which is a prompt. Sanitised to
#: non-alphanumerics as underscores and truncated here.
MCP_TOOL_NAME_MAX_CHARS = 128
#: A tool description reaches the same prompt, and is the injection surface
#: Flowise's `core.ts` treats it as. 1024 matches SkillFrontmatter.description's
#: own ceiling, so the two untrusted-text bounds in this product agree.
MCP_TOOL_DESCRIPTION_MAX_CHARS = 1024
#: 64 tools is past the point where a cheap-tier model can choose between them;
#: discovery stores the first 64 and says which server overflowed.
MCP_MAX_TOOLS_PER_SERVER = 64
#: 16 servers per user, matching MAX_CUSTOM_TOOLS_PER_USER for the same reason.
MCP_MAX_SERVERS_PER_USER = 16

# PLANS.md decision 7 - PROVISIONAL, owner to confirm. Production is remote-only
# and stdio is behind this flag, which is OFF. An arbitrary stdio command would
# let an author's document name a process to run on the server, which is the one
# thing BUILDER_ACTION_REFS' closed set exists to prevent. With the flag off
# every stdio server is refused at create, whatever MCP_ALLOWED_COMMANDS says.
MCP_STDIO_ENABLED = _env_flag("MCP_STDIO_ENABLED", False)
#: The allow-list a stdio command must be on even once the flag is lifted.
#: EMPTY by default, so the flag alone opens nothing. Flowise arrived at the
#: same shape (`CUSTOM_MCP_ALLOWED_COMMANDS`); a local developer may set
#: `npx,uvx`, and `render.yaml` sets neither this nor the flag.
MCP_ALLOWED_COMMANDS: tuple[str, ...] = tuple(
    part.strip()
    for part in os.getenv("MCP_ALLOWED_COMMANDS", "").split(",")
    if part.strip()
)
#: The environment keys a stdio server may be handed. Empty by default; a key
#: outside this set is refused rather than dropped, so an author is told.
MCP_ALLOWED_ENV_VARS: tuple[str, ...] = tuple(
    part.strip()
    for part in os.getenv("MCP_ALLOWED_ENV_VARS", "").split(",")
    if part.strip()
)
#: `https://` is required of every remote server. This flag admits
#: `http://127.0.0.1` and `http://localhost` for local development and for the
#: E2E loopback fixture, and nothing else - the SSRF rule still refuses every
#: other private, loopback and link-local address.
MCP_ALLOW_INSECURE_LOCAL = _env_flag("MCP_ALLOW_INSECURE_LOCAL", False)

#: The thirteen patterns a discovered tool description is tested against, from
#: Flowise's `MCP/core.ts` sanitiser. A match marks the tool `suspicious` and
#: names the pattern; it does NOT hide the tool (PLANS.md decision 8), because
#: "act as" is ordinary English and a picker that quietly drops rows is the
#: quietly-divergent double this repository keeps warning about.
MCP_INJECTION_PATTERNS: tuple[str, ...] = (
    r"\bYOU\s+MUST\b",
    r"ignore\s+(previous|all|above|prior)\s+instructions?",
    r"disregard",
    r"system\s*prompt",
    r"new\s+instructions",
    r"act\s+as",
    r"you\s+are\s+now",
    r"override",
    r"jailbreak",
    r"\bDAN\b",
    r"do\s+anything\s+now",
    r"pretend",
    r"roleplay",
)


# --------------------------------------------------------------------------
# Plan 08 - skills
#
# "Skills = knowledge." CrewAI implements the whole mechanism natively - a
# SKILL.md's frontmatter loads at run start and its body loads only when the
# agent activates it - so this product's job is to store a pack, materialise it
# and hand `Agent(skills=[Path, ...])` a PATH. Never a `str`: a bare string in
# `Agent.skills` is an AMP registry lookup, the same trap as `mcps`.
# --------------------------------------------------------------------------
#: `sk_` + 12 hex, inside BUILDER_ID_PATTERN's shape: `SkillConfig.skill_id` is
#: a `NodeId`.
SKILL_ID_PATTERN = r"^sk_[0-9a-f]{12}$"
#: Where packs live. `builtin/<name>/SKILL.md` is committed and this
#: repository's; `users/<user_id>/<name>/SKILL.md` is a user's own and is
#: git-ignored. Env-overridable so a deployment can point it at a mounted disk.
SKILLS_ROOT = os.getenv("SKILLS_ROOT", "data/skills").strip() or "data/skills"
#: 64 KiB, and the figure is not a guess: it is exactly
#: `persistence.MAX_STRING_LENGTH`, whose `_sanitize_json` RAISES rather than
#: truncates. A larger cap would lose the whole row at write time - the same
#: trap MAX_RUN_RESULT_BODY_CHARS records from the other side.
MAX_SKILL_BYTES = 65536
#: 32 packs per user: this is a STORE bound, not an attach bound -
#: MAX_ATTACHMENTS_PER_NODE (8) is what bounds one agent's context.
MAX_SKILLS_PER_USER = 32
#: A zip import holding one SKILL.md. 256 KiB is four times MAX_SKILL_BYTES,
#: which leaves room for the archive's own overhead and refuses a zip bomb by
#: refusing the compressed size before anything is expanded.
MAX_SKILL_IMPORT_BYTES = 262144
#: The four packs this repository owns, distilled from prompts it already owns
#: (`crews/validator_crew/config/tasks.yaml` and the ratified rubric). Seeded
#: for every user so a fresh account's palette is not empty.
#:
#: They ship with NO licence header. PLANS.md decision 11 asks which header, and
#: it is NOT ANSWERABLE: this repository has no LICENSE file, which for a public
#: repo means all rights reserved (CLAUDE.md remaining-work item 17). Inventing
#: one would be inventing provenance. The dependency is recorded and the field
#: is left unset - `SkillFrontmatter.license` is optional.
BUILTIN_SKILL_NAMES: tuple[str, ...] = (
    "market-research-method",
    "hn-signal-reading",
    "evidence-citation",
    "report-writing",
)
