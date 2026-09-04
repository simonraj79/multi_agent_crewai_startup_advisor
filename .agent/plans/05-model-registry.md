# 05 — Model registry

## Problem

The product's model choice is two constants and two prices in `config.py`.
**Both prices are exactly right, and this section asserted the opposite until
2026-09-04.** The correction is below, and it is load-bearing: acceptance
criterion 3 binds `PRICES` to the registry, so a registry seeded from the old
table would have *replaced* two correct prices with two wrong ones.

Measured 2026-09-04 with `mcp__openrouter__get-model`, one call per row:

| Constant | Value (`config.py:49`, `:72`) | `PRICES` (`config.py:79-89`) | Live headline 2026-09-04 | `:batch` variant |
| --- | --- | --- | --- | --- |
| `CHEAP_MODEL` | `openrouter/google/gemini-3.5-flash-lite:nitro` | $0.30 / $2.50 | **$0.30 / $2.50** — identical | $0.15 / $1.25 |
| `ESCALATION_MODEL` | `openrouter/google/gemini-3.8-flash` | $0.75 / $3.75 | **$0.75 / $3.75** — identical | $0.375 / $1.875 |

> **CORRECTION — 2026-09-04. What this table said, and why it was wrong.**
> Its fourth column was headed *"Live headline 2026-09-02"* and carried
> **$0.15 / $1.25** and **$0.38 / $1.88**, under the sentence *"both prices are
> already wrong against the live catalogue"*. Those are the **`:batch` variant**
> prices, confirmed by asking for the variant slugs directly:
> `google/gemini-3.5-flash-lite:batch` answers $0.15 / $1.25, and
> `google/gemini-3.8-flash:batch` answers $0.375 / $1.875 — which is the
> $0.38 / $1.88 the old row rounded to. The headline price of each plain slug is
> what `PRICES` already held.
>
> It is worse than merely wrong. Batch is a queued lane, and a run with
> streaming frames and a human waiting at a gate cannot be queued
> (MISSION.md §6), so the old column quoted a price this system **can never
> pay** as evidence that the price it does pay was stale. The identical error
> was found and corrected in [`00-architecture.md`](00-architecture.md) D4
> (`52acb02`); this is that same mistake sitting in the plan that would have
> shipped it into `data/models.json` and out through `PRICES`.
>
> The escalation row also names a different model than it did: the tier moved
> `gemini-3.7-flash` → `gemini-3.8-flash` in `f19a2c6` on 2026-09-04.
> `gemini-3.7-flash` still resolves and is also $0.75 / $3.75 — measured, not
> assumed — which is why `PRICES` did not move with the constant.

**The argument this section was making survives its own correction, and is
strengthened by it.** One slug has many endpoint prices, and a hand-typed pair
of numbers cannot express that. Measured 2026-09-04,
`mcp__openrouter__list-model-endpoints` shows `gemini-3.5-flash-lite` served by
**eight** endpoints from $0.15 to $0.54 per million input — a 3.6× spread with
the $0.30 headline sitting in the middle — and `:nitro` routes on **speed, not
price**, so a recorded rate is a **floor** and a real run can bill above it.
Asking for the `:nitro` variant slug returns those same eight endpoints, so
nitro narrows nothing: $0.54 is what the cheap preset can cost, which is
`NITRO_PRICE_FACTOR = 1.8` × $0.30 to the cent. The budget model prices every
builder graph off that single hand-typed pair (`budget.py:105-125`).

That this table misread its own column and then reasoned from the misreading is
the demonstration: a two-row hand-maintained table is not a model registry.

A user building their own team needs to pick a model per agent — the
gauntlet's fourth template puts the cheapest model on a classifier to show
mixed-model economics — and today a document can only say `cheap` or
`escalation` (`document.py:160-179`, `AGENTS.md:64` forbids naming a model).
There is no capability information anywhere: nothing tells the inspector
that a model cannot do JSON mode, so a parameter would be rendered and
silently dropped, which the gauntlet names as the single most infuriating
competitor behaviour.

The gauntlet's hard rule — **$1.00 per million input tokens, never a
frontier model, anywhere** — is asserted by nothing in this repository. The
only enforced money rule is the per-run `MAX_RUN_COST_USD` ceiling
(`config.py:1107`). All ten roster models pass that rule on their headline
input price; **`google/gemini-3.8-flash`'s priority endpoints bill $1.35 per
million input**, over the ceiling, which is a question D3 raises and does not
settle.

## Scope

- A committed, data-driven registry `data/models.json` of at most ten models plus the two tier presets, regenerated from OpenRouter's public catalogue by a script that refuses to overwrite silently.
- `PRICES` derived from the registry at import; `PRICE_MODEL_INDEX`, `resolve_price_model`, `compute_cost_usd` unchanged in behaviour.
- Per-model pricing in `budget.py`, replacing per-tier pricing.
- `GET /api/builder/models` and a client mirror pinned by a Python-generated fixture.
- Capability gating in the inspector: an unsupported parameter is disabled with a tooltip, never dropped, and the compiler refuses it too.
- `tests/test_model_ceiling.py`: every model literal in the codebase is in the registry and under the ceiling (rubric 13).

## Out of scope

- Per-user model roster or per-user ceiling. The registry is global; BYO OpenRouter keys (01, C4) change who pays, not what may be picked.
- Provider routing preferences (`provider.sort`, allow/deny lists) beyond the two presets' existing `:nitro` and `throughput` settings (`config.py:801-829`).
- Reconciling estimates against OpenRouter's actual per-generation cost — that needs generation-id capture, which nothing does yet (CLAUDE.md, "OpenRouter MCP"; remaining-work item 41).
- Embedding and rerank models. They raise no LLM event and are outside every figure here (`budget.py` docstring).

## Design

### D1 — The registry is a committed JSON file, and the refresh is a diff

`data/models.json` is regenerated by `scripts/refresh_models.py` from the
public `GET https://openrouter.ai/api/v1/models` (no key required) with the
filter `cost_in ≤ 1.00 and 'tools' in supported_parameters and id not
ending :free or :batch and provider != anthropic`. The script **writes to a
temp file and prints a unified diff**; it overwrites `data/models.json`
only with `--write`, and exits non-zero when a model in the current
registry has left the filtered catalogue. A price that moves is therefore
a visible diff in a commit, never a silent drift — the failure CLAUDE.md
records six times for its own counts.

Rationale for a committed file over a live fetch at startup: `config.py` is
imported by every test and by the service at boot, the suite must run with
no network (`tests/__init__.py`, CI has no credentials), and a boot that
depends on a third-party catalogue is a boot that fails at 3 a.m.

> **The `:batch` exclusion in that filter is not housekeeping — it is the
> guard against the exact defect this plan shipped with.** The Problem
> section's original table quoted two `:batch` prices as headlines. The
> filter drops ids *ending* `:batch`, which stops a batch row entering the
> registry as its own model; it does **not** by itself stop a human reading a
> batch price into a plain row, which is what happened. `refresh_models.py`
> must therefore take `cost_in` / `cost_out` from the **plain slug's own**
> `pricing.prompt` / `pricing.completion`, and `tests/test_refresh_models.py`
> should carry a fixture in which the plain and `:batch` rows of one model
> both appear, asserting the plain price wins. Measured 2026-09-04:
> `google/gemini-3.5-flash-lite` is $0.30 / $2.50 and its `:batch` variant is
> $0.15 / $1.25 — half, exactly, on both figures, which is why the wrong pair
> looks plausible.

### D2 — Ten models, two presets, chosen from the live ranking, each with a reason

The roster was seeded 2026-09-02 from the live ranking (339 tool-capable
models; 182 under the ceiling after the filter; ranked by OpenRouter's weekly
token volume where the model appeared in the top 40). **Every price, context
window and capability flag below was RE-MEASURED on 2026-09-04** —
`mcp__openrouter__get-model` once per model for the headline columns, and
`mcp__openrouter__list-model-endpoints` once per model for the `max in`
column. Where a 2026-09-02 figure and the 2026-09-04 measurement disagree, the
table carries the measurement and the difference is named underneath. All ten
slugs still resolve.

| # | id | in $/M | out $/M | max in $/M | ×head | context | tools | json | reason | vision | speed | `recommended_for` |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | :-: | :-: | :-: | :-: | --- | --- |
| P1 | `google/gemini-3.5-flash-lite` — **cheap preset** | 0.30 | 2.50 | 0.54 | 1.8× | 1,048,576 | ✓ | ✓ | ✓ | ✓ | fast | `research`, `tool-calling`, `default-cheap` |
| P2 | `google/gemini-3.8-flash` — **escalation preset** | 0.75 | 3.75 | **1.35** | 1.8× | 1,048,576 | ✓ | ✓ | ✓ | ✓ | balanced | `synthesis`, `reporting`, `manager` |
| 3 | `deepseek/deepseek-v4-flash` | 0.0886 | 0.1772 | 0.21 | 2.4× | 1,048,576 | ✓ | ✓ | ✓ | – | fast | `default`, `tool-calling`, `summarising` |
| 4 | `z-ai/glm-5.3-flash` | 0.075 | 0.25 | 0.15 | 2.0× | 1,310,720 | ✓ | ✓ | ✓ | ✓ | fast | `tool-calling`, `vision`, `fast-agents` |
| 5 | `qwen/qwen3.7-flash` | 0.03 | 0.13 | 0.03 | 1.0× | 1,000,000 | ✓ | ✓ | ✓ † | ✓ | fast | `router`, `classifier`, `extraction` |
| 6 | `openai/gpt-5-mini` | **0.25** | **2.00** | 0.275 | 1.1× | 400,000 | ✓ | ✓ | ✓ | ✓ | balanced | `general`, `json-mode`, `instruction-following` |
| 7 | `openai/gpt-4.1-nano` | 0.10 | 0.40 | 0.11 | 1.1× | 1,047,576 | ✓ | ✓ | – | ✓ | fast | `router`, `classifier`, `cheapest-openai` |
| 8 | `openai/gpt-oss-120b` | 0.037 | 0.17 | **0.35** | **9.5×** | 131,072 | ✓ | ✓ | ✓ | – | balanced | `reasoning-cheap`, `coding` |
| 9 | `deepseek/deepseek-r1` | 0.70 | **2.50** | 0.70 | 1.0× | **64,000** | ✓ | ✓ | ✓ † | – | deep | `critic`, `deep-reasoning` |
| 10 | `openai/gpt-4o-mini` | 0.15 | 0.60 | 0.165 | 1.1× | 128,000 | ✓ | ✓ | – | ✓ | fast | `tool-calling-baseline` |

`in` / `out` are the plain slug's headline price per million tokens. `max in`
is the dearest endpoint serving that slug, and `×head` is `max in ÷ in`.

**†** — rows 5 and 9 support reasoning (`reasoning` and `include_reasoning` are
in `supported_parameters`) but the catalogue publishes **no
`reasoning.supported_efforts`** for either: `qwen3.7-flash` answers
`{mandatory: false, default_enabled: true, supports_max_tokens: true}` and
`deepseek-r1` answers `{mandatory: true}`. C3's derivation rule
(*"`supports_reasoning` is `reasoning.supported_efforts` non-empty"*) therefore
computes **false** for both — including for `deepseek-r1`, whose reasoning is
mandatory and is the entire reason it is on the roster. The table above carries
the measured truth; the rule that contradicts it is a contract question raised
in Status, not something this pass changed.

#### What the 2026-09-04 re-measurement moved

| Row | Field | This plan said (2026-09-02) | Measured 2026-09-04 |
| --- | --- | --- | --- |
| P1 | in / out | 0.15 / 1.25 | **0.30 / 2.50** — the old pair was the `:batch` variant |
| P2 | id | `google/gemini-3.7-flash` | **`google/gemini-3.8-flash`** (`f19a2c6`) |
| P2 | in / out | 0.38 / 1.88 | **0.75 / 3.75** — the old pair was the `:batch` variant; `gemini-3.7-flash` measures $0.75 / $3.75 as well, so the swap did not move the price |
| 3 | in / out | 0.09 / 0.17 | 0.088606 / 0.177212 — the old figures were rounded, not wrong |
| 4 | in | 0.07 | 0.075 — rounding |
| 4 | context | 1,048,576 | **1,310,720** catalogue-wide. Only Cloudflare serves it; `top_provider.context_length` is 1,048,576 |
| 6 | in / out | 0.12 / 1.00 | **0.25 / 2.00** — a real move, 2.1× on input and 2.0× on output, not a rounding |
| 8 | in | 0.04 | 0.037 — rounding |
| 9 | context | 163,840 | **64,000**. 163,840 is `deepseek-chat`'s context window, not this model's |
| 5, 9 | reasoning | ✓ | supported, but no `supported_efforts` — see † above |

Nothing else moved. Rows 7 and 10 measured exactly as recorded.

#### What the endpoint spread says about `NITRO_PRICE_FACTOR`

Decision 6 asked for this measurement rather than a blanket 1.8, and the ten
calls say the blanket would have been wrong in both directions:

- **1.8× is exactly right for the two Google presets and for nothing else.**
  Both measure 0.54 ÷ 0.30 and 1.35 ÷ 0.75 to the cent. That is where the
  constant came from, and it is the only place it is a measurement.
- **`openai/gpt-oss-120b` spreads 9.5×**, $0.037 to $0.35 across 21 providers —
  the price of being open-weight. A 1.8 factor understates its worst case by
  more than five times.
- `deepseek/deepseek-v4-flash` (2.4×, 16 endpoints) and `z-ai/glm-5.3-flash`
  (2.0×, 23 endpoints) also exceed 1.8.
- The three OpenAI first-party rows are **1.1×** — one Azure region a shade
  dearer, nothing more. Applying 1.8 to them overstates by 60%.
- `qwen/qwen3.7-flash` and `deepseek/deepseek-r1` have **one endpoint each**, so
  their measured spread is 1.0× — but for qwen that is misleading, see next.
- **`qwen/qwen3.7-flash` is priced in tiers that no endpoint price column
  exposes.** Its `pricing.overrides` charge **$0.10/M above 32,000 prompt
  tokens** and **$0.20/M above 256,000** — a 6.7× effective ceiling on the
  cheapest model in the roster. Its stated roles are `router` / `classifier`
  work, which is short-prompt work, so the headline is usually the right
  number and occasionally is not. C3 has no field for this; contract request in
  Status.

Roles covered: default workhorse (3), cheapest classifier (5, 7),
reasoning (8, 9, and both presets, whose reasoning is `mandatory` — P1 at
`default_effort: minimal`, P2 at `medium`), vision (4, 5, 6, 7, 10, P1, P2),
long context (every 1M-context row), cheap OpenAI (6, 7, 8, 10), Chinese flash
(3, 4, 5). `speed_tier` is hand-assigned from the MCP
`sort: throughput-high-to-low` ordering and stays a curated field; the public
endpoint carries no throughput figure.

Disposition of the gauntlet's ten candidates, **re-measured 2026-09-04** over
the live endpoint list (ranges are min–max across endpoints):

| Candidate | Live 2026-09-04 | Decision |
| --- | --- | --- |
| `openai/gpt-4o-mini` | $0.15–0.165 / $0.60–0.66, 128,000 | kept (10) |
| `openai/gpt-4.1-mini` | $0.40–0.44 / $1.60–1.76, 1,047,576 | dropped — **but its stated reason has half expired.** It read *"`gpt-5-mini` is cheaper, newer, same family"*; `gpt-5-mini` now measures $0.25 / $2.00, so it is cheaper on input and **dearer on output** ($2.00 against $1.60). Newer and same family still hold. The decision stands as written and the changed premise is named rather than re-argued |
| `openai/gpt-4.1-nano` | $0.10–0.11 / $0.40–0.44 | kept (7) |
| `openai/gpt-5-mini` | **$0.25–0.275 / $2.00–2.20**, 400,000 | kept (6). Was recorded here as $0.12 / $1.00 |
| `openai/o4-mini` | **$1.10** / $4.40, 200,000, one endpoint | **over the ceiling — excluded automatically.** Re-confirmed |
| `deepseek/deepseek-chat` | $0.2574–0.32 / $0.89–1.03, 163,840 | superseded by `deepseek-v4-flash` (cheaper, 1M) |
| `deepseek/deepseek-r1` | $0.70 / $2.50, **64,000**, one endpoint | kept (9), output price warned. Its context is 64K, not the 163,840 recorded here |
| `qwen/qwen3-30b-a3b` | $0.12–0.13 / $0.50–0.52, 131,072 | superseded by `qwen3.7-flash` ($0.03, 1M) |
| `z-ai/glm-4.5-air` | $0.13–0.20 / $0.85–1.10, 131,072 | superseded by `glm-5.3-flash` ($0.075, 1M+) |
| `moonshotai/kimi-k2` | $0.57 / $2.30, **131,072**, one endpoint | dropped — its live context is not long; every 1M row covers the role |

`openai/gpt-oss-120b` is the backfill from the cheap-OpenAI tier.

### D3 — The ceiling is on input price; output price is shown and warned on

The gauntlet's rule is "$1.00 / 1M input tokens", and **every roster row passes
it on the headline input price.** Two consequences of the 2026-09-04
measurement change what this section used to say, and neither is settled here:

**Four rows bill over $1.00 per million output, not two.** The old text named
*"`deepseek-r1` $2.50, and `gpt-5-mini` at exactly $1.00"*. Measured: P1 $2.50,
P2 $3.75, `gpt-5-mini` **$2.00** — not $1.00, and not "exactly" anything —
and `deepseek-r1` $2.50. So the `cost_out > 1.00` amber note lands on **both
tier presets** as well as on two roster rows, which makes it a badge on the
default rather than a warning about an unusual pick. Whether the note should
key on something else is a question for 04's picker design; this plan records
the measurement and does not decide it.

**One row's dearest endpoint is over the input ceiling.**
`google/gemini-3.8-flash` bills **$1.35 per million input** on its two
`priority` endpoints (`google-ai-studio/priority` and
`google-vertex/global/priority`). The ceiling as specified in D9 tests
`cost_in ≤ 1.00` — the headline — which this row passes at $0.75. So the
escalation preset is compliant as measured, and could still bill over the
ceiling on a routing decision nobody in this repository makes. Recording
`cost_in_max_endpoint: 1.35` is what makes that visible; **whether the ceiling
test should read the headline or the maximum is an owner decision, raised in
Status.** `gemini-3.7-flash`, the model P2 replaced, measures identically, so
this is not something the swap introduced.

The registry carries both figures; the picker renders both; a model whose
`cost_out > 1.00` carries an amber note. The budget model prices completion
tokens at 4,253 per call (`GRAPH_BUDGET_CALL_COMPLETION_TOKENS`,
`config.py:1949`), so the output price is the larger
half of every estimate and hiding it would make the meter lie.

### D4 — `PRICES` is derived, and the four spellings survive

`config.py` gains `MODEL_REGISTRY_PATH = data/models.json` and loads it
with the standard library at import. `PRICES` becomes
`{f"openrouter/{m.id}": (m.cost_in, m.cost_out)} ∪ {CHEAP_MODEL: …,
ESCALATION_MODEL: …}` — the two presets keep their `:nitro` / plain
spellings so `PRICE_MODEL_INDEX` (`config.py:180`) registers the same
four variants per key it does today, `resolve_price_model` (`:183`) is
untouched, and `compute_cost_usd` (`:226`) still returns **`None`, never
`0.0`**, for an unknown model. Because the two preset prices measured
**identical** to the `PRICES` already in `config.py` (Problem), deriving `PRICES`
from the registry changes no value in this repository — it changes where the
value comes from. If a build finds it changing a preset price, the registry is
wrong, not `config.py`. The platform rule "constants stay in
`config.py`" holds: the file names the path; the data is data.

### D5 — The nitro factor applies to `:nitro` ids, and the measurement is now in

`NITRO_PRICE_FACTOR = 1.8` (`config.py:1937`) is applied today to every
cheap-tier node in the static estimate (`budget.py:177-178`) because the
cheap preset is a `:nitro` id. With per-model pricing the rule is: a model
id carrying `:nitro` is priced at `max(cost_in_max_endpoint, cost_in ×
NITRO_PRICE_FACTOR)` when `cost_in_max_endpoint` is recorded, and `cost_in ×
NITRO_PRICE_FACTOR` otherwise; a plain id is priced at `cost_in`.

**`cost_in_max_endpoint` is no longer `null`, and is no longer a guess.**
Decision 6 (*"measure once at build time"*, answered 2026-09-04) was carried
out the same day: one `mcp__openrouter__list-model-endpoints` call per roster
model, and the `max in` column of D2 is the result. The values to seed the
registry with are, per million input tokens:

```text
google/gemini-3.5-flash-lite   0.54     openai/gpt-5-mini      0.275
google/gemini-3.8-flash        1.35     openai/gpt-4.1-nano    0.11
deepseek/deepseek-v4-flash     0.21     openai/gpt-oss-120b    0.35
z-ai/glm-5.3-flash             0.15     deepseek/deepseek-r1   0.70
qwen/qwen3.7-flash             0.03     openai/gpt-4o-mini     0.165
```

Two things the measurement settles that the 1.8 factor could not:

- **Asking for the `:nitro` variant slug returns the same eight endpoints as
  the plain slug.** Nitro does not restrict the pool, it re-sorts it, so
  $0.54 is a real reachable price for the cheap preset and `max(0.54, 0.30 ×
  1.8)` is `0.54` either way. The factor and the measurement agree here to the
  cent, which is the only roster row where that is true by anything but
  coincidence — the other Google row agrees for the same reason and every
  other row disagrees (D2's spread list).
- **The factor is the wrong instrument for a plain id**, and applying it to
  one would be inventing a number in both directions: it would overstate the
  three OpenAI first-party rows by 60% and understate `gpt-oss-120b` by more
  than five times. Leaving plain ids at `cost_in` is what this plan specifies
  and what the measurement supports. Whether `budget.py` should use
  `cost_in_max_endpoint` for a plain id as a conservative worst case is a real
  question the measurement now makes answerable; it is raised in Status and
  not decided here.

`refresh_models.py` preserves a non-null `cost_in_max_endpoint` across
refreshes, so a re-measured value survives a price refresh and a stale one is
visible as an unchanged number beside a changed headline.

### D6 — Budget prices per model, not per tier

`budget.py:105-125` computes calls per node and multiplies by
`compute_cost_usd(tier_model, …)`. It changes to read the node's resolved
model id — `llm.model` on an authored node, the preset's id on a library
node — and apply D5. `static_cost_usd` and `floor_cost_usd` keep their
meanings (`budget.py:69-102`); `unpriced_models` keeps refusing a model the
registry does not price (`BUDGET_UNPRICED_MODEL`, `:215-227`), which is now
the same thing as "not in the registry".

### D7 — Capability flags gate controls, and the compiler agrees

The inspector (04) reads the selected model's flags:

| Flag false | Control | Behaviour |
| --- | --- | --- |
| `supports_json_mode` | `response_format: json` | disabled, tooltip *"<model> does not support JSON mode"* |
| `supports_reasoning` | `reasoning_effort`, `reasoning` | disabled, tooltip |
| `supports_vision` | `multimodal` | disabled, tooltip |
| `supports_tools` | the `attach` port for `tool` / `mcp` | connection refused with the tooltip; a stale document gets `model-lacks-capability` |

Every gate is enforced twice: the widget disables, and `bounds.py` reports
`model-lacks-capability` when a document carries the value anyway — a
stale client cannot smuggle a parameter the compiler would drop. `model-unknown`
and `model-over-ceiling` cover an id not in the registry and a registry
row whose price crossed the ceiling after publish. All three codes are
owned by 12 (C8).

### D8 — The picker shows the flow's live cost, per node and in total

`BudgetMeter.vue:28-59` already renders both dollar figures and the
ceiling bar, re-priced on every 400 ms-debounced validate
(`useBuilderValidation.ts:39`). The model picker in the inspector shows,
per row, `cost_in / cost_out`, context, the four flags as icons, and
`speed_tier`; the selected row shows *"≈ $N for this node"* from the
per-node breakdown (see Status — contract request). Changing the model on
a node re-validates and the meter moves; that is the whole "live cost
estimate for the current flow" requirement.

### D9 — The ceiling test scans the codebase, not the registry

`tests/test_model_ceiling.py` walks `src/`, `frontend/src/`,
`frontend/tests/`, `tests/`, `data/`, `scripts/`, `render.yaml` and
`.env.example` for the pattern
`(?:openrouter/)?(?:openai|google|deepseek|qwen|z-ai|moonshotai|anthropic|meta-llama|mistralai|x-ai|xiaomi|minimax|nvidia|tencent|stepfun|upstage)/[a-z0-9.\-]+(?::[a-z]+)?`
and asserts every match, stripped of `openrouter/` and `:variant`, is a
registry id whose `cost_in ≤ 1.00`. It separately asserts zero matches for
`anthropic/`, `openai/o1`, `openai/o3`, `openai/gpt-4o"` (the full model)
and `openai/gpt-5.2`. `docs/` is exempt so prose can name a forbidden model
when explaining the rule; this plan file is under `.agent/` and is likewise
exempt.

> **CORRECTION — 2026-09-04.** This paragraph described `openai/gpt-5.2` as
> *"the frontier row, $1.00+ on every endpoint"*. Measured, its endpoints span
> **$0.88 to $3.50** per million input: the `flex` endpoint at $0.88 is *under*
> the ceiling. The headline is **$1.75 / $14.00**, so the test as specified —
> which reads `cost_in`, the headline — still excludes it, and the exclusion
> list needs no change. Only the parenthetical was wrong, and it was wrong in
> the direction that matters: it claimed a stronger guarantee than the endpoint
> data supports. Measured the same day: `openai/o1` $15.00 / $60.00,
> `openai/gpt-4o` $2.50 / $10.00, `openai/o3` $2.00 / $8.00 — all three are
> over the ceiling on every endpoint they have, so their entries on the list
> are sound.

## Interfaces

### C3 — `data/models.json` (owned here)

```json
{
  "schema": "models/v1",
  "generated_at": "2026-09-04T00:00:00Z",
  "source": "https://openrouter.ai/api/v1/models",
  "ceiling_usd_per_m_input": 1.0,
  "presets": { "cheap": "google/gemini-3.5-flash-lite:nitro", "escalation": "google/gemini-3.8-flash" },
  "models": [
    {
      "id": "google/gemini-3.5-flash-lite",
      "name": "Gemini 3.5 Flash Lite",
      "provider": "google",
      "context_window": 1048576,
      "supports_tools": true,
      "supports_vision": true,
      "supports_json_mode": true,
      "supports_reasoning": true,
      "cost_in": 0.3,
      "cost_out": 2.5,
      "cost_in_max_endpoint": 0.54,
      "speed_tier": "fast",
      "recommended_for": ["research", "tool-calling", "default-cheap"]
    }
  ]
}
```

Rules: `models` has 1–10 entries; ids are base slugs without `openrouter/`
and without a variant; `presets` values may carry a variant and must
resolve, variant stripped, to a row; `cost_*` are USD per million tokens
as floats; `supports_json_mode` is `response_format ∈ supported_parameters
or structured_outputs ∈ supported_parameters`; `supports_reasoning` is
`reasoning.supported_efforts` non-empty; `supports_vision` is `image ∈
architecture.input_modalities`; `speed_tier ∈ {fast, balanced, deep}`;
`recommended_for` values are from a closed list the inspector uses for
grouping: `default`, `default-cheap`, `research`, `tool-calling`,
`tool-calling-baseline`, `router`, `classifier`, `extraction`,
`summarising`, `synthesis`, `reporting`, `manager`, `critic`,
`deep-reasoning`, `reasoning-cheap`, `coding`, `vision`, `fast-agents`,
`general`, `json-mode`, `instruction-following`, `cheapest-openai`.

> **Two of those derivation rules are falsified by the 2026-09-04 measurement,
> and neither is changed here.** C3 is a contract, and a contract change is the
> Integrator's to make (MISSION.md §4), so this is a request, not an edit:
>
> 1. **`supports_reasoning` = "`reasoning.supported_efforts` non-empty" computes
>    `false` for two roster rows that do support reasoning.**
>    `qwen/qwen3.7-flash` publishes `reasoning: {mandatory: false,
>    default_enabled: true, supports_max_tokens: true}` and
>    `deepseek/deepseek-r1` publishes `reasoning: {mandatory: true}` — neither
>    carries `supported_efforts`, and both carry `reasoning` and
>    `include_reasoning` in `supported_parameters`. Under the rule as written,
>    D7 would disable the reasoning controls on `deepseek-r1`, whose reasoning is
>    *mandatory* and which is on the roster for `deep-reasoning`. A rule that
>    matched the measurement would be `reasoning ∈ supported_parameters` (with
>    `supported_efforts` deciding whether the `reasoning_effort` *level* control
>    is offered, which is a genuinely separate capability — `qwen3.7-flash` and
>    `deepseek-r1` also lack `reasoning_effort` in `supported_parameters`, while
>    the other eight rows have it).
> 2. **There is no field for tiered prompt pricing.** `qwen/qwen3.7-flash` is
>    $0.03/M up to 32,000 prompt tokens, **$0.10/M above 32,000** and
>    **$0.20/M above 256,000** (`pricing.overrides` on its single Alibaba
>    endpoint). `cost_in`, `cost_out` and `cost_in_max_endpoint` cannot express
>    that, and the model most likely to be picked for a cheap classifier is the
>    one where it bites. A `cost_in_tiers` array, or a recorded worst-case in
>    `cost_in_max_endpoint`, would; both are contract shapes, not this pass's
>    call. Until one exists, the registry under-prices a long-prompt
>    `qwen3.7-flash` node by up to 6.7×.

### `GET /api/builder/models` (owned here)

Unauthenticated, like `/vocabulary` (`builder_api.py:415-420`), so it
resolves before the auth gate. Returns the registry verbatim with an
`ETag` equal to the file's SHA-256 and honours `If-None-Match` with the
same weak comparison `get_graph` uses (`tests/service/test_graph_etag.py`).
Client mirror: `frontend/src/data/models.ts` loads it into `sessionStorage`
under `builder-models` beside the vocabulary; `frontend/tests/fixtures/models.json`
is written by `scripts/emit_builder_fixtures.py` and byte-compared by
`tests/builder/test_client_fixtures.py` (R7 rule, line endings normalised).

### `scripts/refresh_models.py` (owned here)

```text
usage: refresh_models.py [--write] [--keep-ids ID ...] [--max 10]
  reads  https://openrouter.ai/api/v1/models
  filter cost_in <= ceiling, 'tools' in supported_parameters, no :free/:batch, provider != anthropic
  keeps  every id in the current registry that still passes; preserves cost_in_max_endpoint, speed_tier, recommended_for
  prints unified diff; exit 2 if a kept id no longer passes; writes only with --write
```

### `config.py` additions (Integrator-owned file; this plan specifies the constants)

`MODEL_REGISTRY_PATH`, `MODEL_CEILING_USD_PER_M_INPUT = 1.0`,
`MODEL_REGISTRY: tuple[RegistryModel, ...]`, `MODEL_IDS: frozenset[str]`,
`PRICES` (derived), `NITRO_PRICE_FACTOR` (unchanged value, narrowed rule).

### Consumed

- **C1** (03): `llm.model`, `retry.fallback_model`, `function_calling_llm`, `manager_llm`, `planning_llm` are registry ids; `tier` is a preset name.
- **C4** (01): `llm.credential_id` selects a BYO OpenRouter key; it does not change pricing.
- **C8** (12): `model-unknown`, `model-over-ceiling`, `model-lacks-capability`.

## Acceptance criteria

1. `data/models.json` exists, validates against the shape above, has ≤ 10 models, and both presets resolve to rows. Check: `python -c "from brief_crew.config import MODEL_REGISTRY, PRICES; print(len(MODEL_REGISTRY), len(PRICES))"`.
2. `python scripts/refresh_models.py` against the live endpoint prints a diff and leaves the file unchanged; with `--write` it changes the file; a run after a kept id is removed from the filter exits 2. Test: `tests/test_refresh_models.py` with a recorded catalogue fixture.
3. `PRICES[CHEAP_MODEL]` and `PRICES[ESCALATION_MODEL]` equal the registry's `(cost_in, cost_out)` for the preset rows, and `resolve_price_model` still answers all four spellings (`tests/service/test_run_result_and_cost.py` stays green). Measured 2026-09-04, those pairs are `(0.30, 2.50)` and `(0.75, 3.75)` — the values `PRICES` already holds, so this criterion is met by seeding the registry correctly and **not** by editing `PRICES`. An implementation that finds itself changing `PRICES` to pass this has copied the pre-correction table.
4. `compute_cost_usd("openrouter/anthropic/claude-haiku-4.5", 1, 1)` returns `None`. Test: `tests/test_model_ceiling.py::test_unknown_model_is_unpriced`.
5. `tests/test_model_ceiling.py` passes at head and **fails when a fixture file is temporarily given `openai/o4-mini`** (proved by breaking it once, the way the `./e2e` tsconfig reference was proved — CLAUDE.md item 38). Rubric 13.
6. The frontier document from `tests/builder/test_budget.py::frontier_document` priced with every billable node on `deepseek/deepseek-r1` is still refused over the $10 ceiling with the 1.25 margin; the same document on `qwen/qwen3.7-flash` is admitted. Test: `tests/builder/test_budget.py::test_per_model_pricing`.
7. A document naming `llm.model = "openai/o4-mini"` validates with `model-unknown`; a registry row edited to `cost_in: 1.5` in a test fixture yields `model-over-ceiling`; `response_format: json` on `openai/gpt-4.1-nano` is admitted and on a fixture row with `supports_json_mode: false` yields `model-lacks-capability`. Test: `tests/builder/test_model_gating.py`.
8. `GET /api/builder/models` answers 200 with an `ETag` and 304 on `If-None-Match`; unauthenticated. Test: `tests/service/test_models_endpoint.py`.
9. `frontend/tests/fixtures/models.json` is byte-identical to the Python-generated fixture (`tests/builder/test_client_fixtures.py`).
10. Playwright: open the fan-out template, select an agent, change its model from the cheap preset to `qwen/qwen3.7-flash`; the budget meter's enforced figure decreases within one validate cycle and the inspector shows the disabled-with-tooltip state for `reasoning_effort` on a `supports_reasoning: false` fixture row. Spec: `frontend/e2e/builder-models.spec.ts`. Rubric 4, 13.
11. No model literal in `src/`, `frontend/src/`, `tests/`, `data/`, `scripts/` is over the ceiling — the test in 5, run as part of `python -m unittest discover -s tests -t .`.

## References

- **Live re-measurement 2026-09-04** (the figures every table in this file now carries): `mcp__openrouter__get-model` once per roster model for headline price, `context_length`, `supported_parameters` and `reasoning`; `mcp__openrouter__list-model-endpoints` once per roster model for `cost_in_max_endpoint`; and the `:batch` variant slugs of both presets, which is what identified the mislabelled column. `pricing.prompt` from `get-model` is a display string (`"$0.3/M tokens"`); the same field from the public `/endpoints` resource is a raw per-token float and must be multiplied by 1e6. The two disagree in form, never in value.
- Live catalogue queries 2026-09-02: `mcp__openrouter__list-models` with `max_price: 1`, `supported_parameters: tools`, `sort: top-weekly`; full catalogue `supported_parameters: tools, limit: 1000`; `pricing.prompt` is a display string `"$0.065/M tokens"` and must be parsed.
- `src/brief_crew/config.py` — **line numbers re-checked 2026-09-04 at `f19a2c6`; the set this plan carried was written against a 2026-09-02 tree and every one of them had moved.** `:49` (`CHEAP_MODEL`), `:72` (`ESCALATION_MODEL`), `:79-89` (`PRICES`), `:180` (`PRICE_MODEL_INDEX`), `:183` (`resolve_price_model`), `:226` (`compute_cost_usd`), `:1107` (`MAX_RUN_COST_USD`), `:1923` (`GRAPH_STATIC_BUDGET_MARGIN`), `:1937` (`NITRO_PRICE_FACTOR`), `:1949` (`GRAPH_BUDGET_CALL_COMPLETION_TOKENS`). The `reasoning_effort`-dropped and `openrouter_*_params` references (`:707-712`, `:801-829`) were **not** re-checked this pass and should be treated as stale until they are.
- `src/brief_crew/builder/budget.py:69-102, 105-125, 177-178, 197-248`.
- `frontend/src/components/builder/BudgetMeter.vue:28-59`, `frontend/src/composables/useBuilderValidation.ts:39`.
- `docs/crewai-notes.md` §4 (LLM fields), §11 items 4–5 (`llm=None` on gates, `Agent.llm=None` resolves to OpenAI).
- CLAUDE.md "OpenRouter MCP — the live catalogue" (the 3.6× endpoint spread, `get-generation`), remaining-work item 41.
- Gauntlet: Stage 2 "Models — OpenRouter roster", rubric 13, "Forbidden: a model above the price ceiling anywhere in the codebase".

## Status

**Planned · 2026-09-02. Price and capability tables re-measured and corrected
· 2026-09-04.**

The 2026-09-04 pass changed no design and wrote no code. What it did was
replace every guessed figure in this file with one taken from
`mcp__openrouter__get-model` and `mcp__openrouter__list-model-endpoints` in
that session, and say out loud where the two disagreed. The headline
correction is in Problem: **`config.py`'s two prices were right and this plan
said they were wrong**, quoting `:batch` variant prices as headlines — the same
error `00-architecture.md` D4 corrected in `52acb02`, sitting in the plan that
would have shipped it into `data/models.json` and out through `PRICES`.

Contract requests for 00:

- **C1/C3 — per-node budget breakdown.** D8's *"≈ $N for this node"* needs `budget.per_node: {node_id: usd}` on the validate response and the stored `BuilderBudget` (`document.py:483-495`). Proceeding under the assumption 03 and 09 add it; until then the inspector shows the flow total only.
- **C3 — `supports_reasoning` derivation.** The rule as written computes `false` for `qwen/qwen3.7-flash` and `deepseek/deepseek-r1`, both of which support reasoning; on `deepseek-r1` it is *mandatory*. Measured 2026-09-04; full detail in the note under C3. Recommended shape: `reasoning ∈ supported_parameters` for the capability, `reasoning_effort ∈ supported_parameters` for the level control, which are separately true across the roster.
- **C3 — no field expresses tiered prompt pricing.** `qwen/qwen3.7-flash` charges $0.03/M, then $0.10/M above 32,000 prompt tokens, then $0.20/M above 256,000. `cost_in` under-prices a long-prompt node on the roster's cheapest model by up to 6.7×. Note under C3.

Open decisions for the owner:

- **Should the ceiling test read `cost_in` or `cost_in_max_endpoint`?** D9 tests the headline, and every roster row passes. `google/gemini-3.8-flash` — the escalation preset — bills **$1.35/M input** on its two `priority` endpoints, over the $1.00 ceiling, and `openai/gpt-oss-120b` reaches $0.35 against a $0.037 headline. Nothing in this repository selects a priority endpoint, so the exposure is theoretical today; the figures are recorded either way. Raised by D3 and not decided there.
- **Should `budget.py` price a plain (non-`:nitro`) id at `cost_in_max_endpoint` as a worst case?** Now answerable, because the value is measured for all ten. D5 specifies `cost_in` for a plain id, which is what the plan was written against.

### Owner decisions answered — 2026-09-04

**Decision 5 — keep `deepseek/deepseek-r1` and show its output price on the
card.** The $2.50 output price is a fact the author should see, not a reason to
remove the model from the roster. (Re-measured 2026-09-04: r1 is $0.70 / $2.50
on a **single** Novita endpoint at **64,000** context — this plan had recorded
163,840, which is `deepseek-chat`'s window. The alternative it was weighed
against, `deepseek/deepseek-v3.2`, measures $0.269 / $0.40 at 163,840 context
across 15 endpoints spanning $0.21–$3.00 input. The decision stands; the
figures behind it have moved and are named here rather than re-argued.)

**Decision 6 — measure once at build time. DONE, 2026-09-04.** Ten
`mcp__openrouter__list-model-endpoints` calls; the `max in` column of D2 and
the seed block in D5 are the result. What it turned up is that the 1.8 factor
is a measurement for exactly the two Google presets and a guess everywhere
else, wrong in **both** directions — 1.1× for the three OpenAI first-party
rows, **9.5×** for `openai/gpt-oss-120b`. That is the argument for measuring
rather than for the factor, and it is now a number.
