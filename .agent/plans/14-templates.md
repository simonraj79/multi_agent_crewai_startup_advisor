# 14 — Templates (the four patterns)

Written 2026-09-02 against `25634c0`. Owner: S8. Owns C9. Consumes C1 (03),
C3 (05), C6 (10), C7 (10). Every template here is code, pinned by a fixture,
and runnable from a cold sign-in with zero configuration.

## Problem

The gallery ships four templates (`frontend/src/data/builderTemplates.ts:351-365`):
`blank` (0 nodes, deliberately invalid, `:240-265`), `minimal-gated-agent`
(4 nodes, `:267-301`), `fan-out-join` (8 nodes, `:303-341`) and
`idea-validator` (16 nodes, `src/data/templates/ideaValidator.ts`). All four
are built from **library** agent ids over prompts this repository owns; none
teaches the four patterns the gauntlet names, and none can, because a library
agent's role and task are fixed in `crews/validator_crew/config/*.yaml`
(`runtime.py:178-185`). A new user opening any of them sees six dropdown
choices, not a team they could have written.

The fixture pipeline that keeps a template honest already exists for one of
them: `frontend/tests/fixtures/builderValidatorTemplate.json` carries
`{document, vocabulary, validation}`, `frontend/tests/validatorTemplate.spec.ts:62`
asserts the TypeScript document equals the fixture's, `:66-67` asserts
`validation.valid` and an empty problem list, and `:160` asserts the gallery
ships exactly four. That pipeline scales to five.

## Scope

Four new templates — `sequential-pipeline`, `hierarchical-delegation`,
`reflection-loop`, `conditional-router` — as TypeScript documents under
`frontend/src/data/templates/`, each with a Python-generated fixture, gallery
copy, a "what it teaches" and "what to modify first" line, a target price,
and a `@launch` E2E test. `blank` and `idea-validator` stay. The gallery
ordering rule stays. Rubric 15.

## Out of scope

- Template authoring or save-as-template by users (`docs/flow-builder-spec.md` cut-list 12 stands; `builderTemplates.ts:5-13`).
- Retiring `minimal-gated-agent` and `fan-out-join`. They are demoted from the gallery's first row to a "more" row and kept because `e2e/builder.spec.ts` drives them; the owner may delete them later (Status).
- Changing the schema, the bounds, the budget model or the compiler. When a template needs a capability, the plan that owns it is named; this file waits on it.
- Localisation of template copy.

## Design

### D1 — Templates are authored documents, referencing models by role

Every agent in the four templates is an **authored** agent (`role`, `goal`,
`backstory`, `task.description`, `task.expected_output` — C1), and every
model is named by role, not by slug: `{{cheapest}}`, `{{workhorse}}`,
`{{escalation}}`, resolved at load time by `data/models.ts` (C3) into the
registry's current id for that role. A roster refresh therefore cannot break
a template, and the fixture pipeline (D6) re-resolves before comparing.
`documentFromTemplate` continues to `structuredClone` (`builderTemplates.ts:367-380`);
resolution happens inside it.

### D2 — Sequential pipeline: research → analyse → write

"Hello world." Teaches ports, context passing and one attached tool.

| id | kind | family | key config |
| --- | --- | --- | --- |
| `topic` | input | — | `field: topic`, `label: "What should the team write about?"`, `max_chars: 2000` |
| `research` | agent | authored | role *Research Analyst*; task *"Find the five most load-bearing facts about {topic} with a source URL for each"*; `llm: {{workhorse}}`; `max_iter: 3` |
| `search` | tool | attachment | `tool_id: web_search` (06's one-interface search; platform key) — edge `search.attach → research.attach` |
| `analyse` | agent | authored | role *Analyst*; task *"From the research, name the three tensions a reader must understand, each with its evidence"*; `llm: {{workhorse}}`; `prompt_inputs: {research: "${state.out__research}"}` |
| `write` | agent | authored | role *Writer*; task *"Write a 600-word brief with a headline, three sections, and a sources list"*; `task.markdown: true`; `llm: {{escalation}}`; `prompt_inputs: {analysis: "${state.out__analyse}"}` |
| `brief` | output | — | `body_key: markdown_body`, `source: "${state.out__write}"` |

Edges: `topic.out → research.in`, `research.out → analyse.in`,
`analyse.out → write.in`, `write.out → brief.in`, `search.attach →
research.attach`. Joins `{}`. 5 flow nodes + 1 attachment, 5 edges, 0
cycles, 3 billable, 1 escalation.

Modify first: the writer's `expected_output`. Teaches: an edge is a
`@listen`, `${state.out__x}` is how the previous step's text reaches the
next prompt, and a tool is something you drop onto an agent.

Target price under the current budget model (`budget.py:105-125`, PRICES at
`config.py:57-60`, `NITRO_PRICE_FACTOR` 1.8, defaults `guardrail_max_retries
2`): research 9 calls (tools) ≈ $0.18, analyse 3 calls at depth 1 ≈ $0.07,
write 3 escalation calls at depth 2 ≈ $0.07 — **≈ $0.32 static, ≈ $0.40 with
the 1.25 margin.** To be measured at build time.

### D3 — Hierarchical delegation: a manager, three specialists, a synthesis

Teaches fan-out/fan-in inside one crew and `manager_llm`.

| id | kind | family | key config |
| --- | --- | --- | --- |
| `brief` | input | — | `field: brief`, `label: "Describe the deliverable"` |
| `team` | crew | authored | `process: hierarchical`; `manager_llm: {{escalation}}`; `prompt_inputs: {brief: "${state.out__brief}"}`; task order `[market, product, risk]` |
| `market` | agent | authored | member; role *Market Specialist*; task *"Size the market and name the buyer"*; `llm: {{workhorse}}` |
| `product` | agent | authored | member; role *Product Specialist*; task *"Define the v1 scope in five bullets"*; `llm: {{workhorse}}` |
| `risk` | agent | authored | member; role *Risk Specialist*; task *"List the three ways this fails and the early signal for each"*; `llm: {{workhorse}}` |
| `plan` | output | — | `body_key: markdown_body`, `source: "${state.out__team}"` |

Edges: `brief.out → team.in`, `team.out → plan.in`, and three membership
edges `market.out → team.member`, `product.out → team.member`, `risk.out →
team.member`. The three member agents have no flow edges — 03's bound
`member-agent-has-flow-edges` refuses one that does. 3 flow nodes + 3
members, 5 edges, 0 cycles.

Modify first: `process` — flip it to `sequential` and watch the manager
disappear from the inspector and the price. Teaches: a crew node is a
`Crew`, members are `Agent`s the crew owns, and `hierarchical` without a
manager is refused — by CrewAI itself (`crew.py:729`) and by 03's
`crew-hierarchical-needs-manager` before publish.

Target price: this needs 09's per-member pricing (today a crew node is priced
as one tool-using billable node, `budget.py:121`). Under the assumption
"members priced as tool-less agents at the crew's depth, manager priced at
`members + 1` escalation calls": ≈ $0.18 + $0.07 = **≈ $0.25 static**. To be
measured at build time once 09 lands.

### D4 — Reflection loop: generator ↔ critic until a score or the cap

Teaches loops, routers, structured output and exit conditions. It is this
document as a template.

| id | kind | family | key config |
| --- | --- | --- | --- |
| `ask` | input | — | `field: ask`, `label: "What should be drafted?"` |
| `generate` | agent | authored | role *Drafter*; task *"Draft the piece; if feedback is present, revise to address every point"*; `prompt_inputs: {ask: "${state.out__ask}", feedback: "${state.out__feedback}"}`; `llm: {{workhorse}}` |
| `critique` | agent | authored | role *Critic*; task *"Score the draft 0–10 and give the three most important fixes"*; `task.output_schema: {score: integer, feedback: string}` (C1); `prompt_inputs: {draft: "${state.out__generate}"}`; `llm: {{workhorse}}` |
| `score` | transform | — | `op: pick`, `args: {from: "${state.out__critique}", key: "score"}` |
| `feedback` | transform | — | `op: pick`, `args: {from: "${state.out__critique}", key: "feedback"}` |
| `judge` | router | — | branches `[{label: done, op: gte, key: out__score, value: 8}, {label: again, op: otherwise}]` |
| `final` | output | — | `body_key: markdown_body`, `source: "${state.out__generate}"` |

Edges: `ask.out → generate.in`, `generate.out → critique.in`,
`critique.out → score.in`, `critique.out → feedback.in`, `score.out →
judge.in`, `feedback.out → judge.in`, `judge.done → final.in`, `judge.again
→ generate.in` (the back edge, closed by a router as `bounds.py:611-631`
requires). Joins `{judge: 'all'}`. 7 nodes, 8 edges, **1 cycle**.

The loop is bounded by the compiler, not the prompt: `max_method_calls =
(1 + MAX_CYCLE_ITERATIONS) ** cycles` (`compiler.py:786-797`,
`MAX_CYCLE_ITERATIONS = 3`, `config.py:1863`), so at most four drafts. The
card says so: *"stops at a score of 8 or after three revisions."*

Modify first: the threshold `8`. Teaches: a router is the only thing that
may close a loop, `output_schema` turns prose into a number a router can
read, and `pick` is how one field leaves a structured answer.

Target price: both agents sit on the cycle (× 4): generate 12 calls ≈ $0.24,
critique 12 calls at depth 1 ≈ $0.27 — **≈ $0.51 static, ≈ $0.64 with
margin.** To be measured at build time.

### D5 — Conditional router: classify, route to one of three, converge

Teaches `@router`, labelled edges, branch merging and mixed-model economics.

| id | kind | family | key config |
| --- | --- | --- | --- |
| `request` | input | — | `field: request`, `label: "Paste the customer message"` |
| `classify` | agent | authored | role *Triage*; task *"Classify as billing, technical or account"*; `task.output_schema: {category: string}`; **`llm: {{cheapest}}`**; `max_iter: 1` |
| `category` | transform | — | `op: pick`, `args: {from: "${state.out__classify}", key: "category"}` |
| `route` | router | — | branches `[{label: billing, op: eq, key: out__category, value: "billing"}, {label: technical, op: eq, …, "technical"}, {label: account, op: otherwise}]` |
| `billing` | agent | authored | role *Billing Specialist*; `llm: {{workhorse}}` |
| `technical` | agent | authored | role *Support Engineer*; `llm: {{workhorse}}` |
| `account` | agent | authored | role *Account Manager*; `llm: {{workhorse}}` |
| `reply` | output | — | `body_key: markdown_body`, `source: "${state.out__reply_text}"` — see note |

Edges: `request.out → classify.in`, `classify.out → category.in`,
`category.out → route.in`, `route.billing → billing.in`, `route.technical →
technical.in`, `route.account → account.in`, and the three specialists into
one `merge` transform (`op: default`, first non-empty of the three
`out__` keys) → `reply`. Joins `{merge: 'any'}` — exactly one branch fires,
which is why FD5 admits `'any'`; with `'all'` the join would wait forever
for two branches that never run. 9 nodes, 9 edges, 0 cycles, 4 billable.

Modify first: the classifier's model — swap `{{cheapest}}` for
`{{escalation}}` and watch the budget meter move for a node that only ever
says one word. Teaches: put the cheap model where the decision is small.

Target price (static, worst case — every branch priced although one runs):
classify 3 calls ≈ $0.06 at the cheap tier, three specialists 3 calls each at
depth 1 ≈ $0.20 — **≈ $0.26 static.** To be measured at build time; with 05's
per-model prices the classifier line falls further.

### D6 — The fixture pipeline

`scripts/emit_builder_fixtures.py` (exists; today emits
`builderBackEdges.json` and `builderProblemCodes.json`) gains a `templates`
target that, for each template id, loads the TypeScript document **as the
frontend serialises it** (`npx tsx scripts/dump-template.ts <id>` writes
`build/templates/<id>.json`; the Python script reads it), resolves `{{role}}`
models against `data/models.json`, runs `validate_document(doc,
ceiling_usd=MAX_RUN_COST_USD)` and `estimate_budget`, and writes
`frontend/tests/fixtures/templates/<id>.json` as
`{document, vocabulary, validation}` — the shape `builderValidatorTemplate.json`
already has.

Two tests guard it from both ends:

- `tests/builder/test_client_fixtures.py` regenerates every template fixture in memory and byte-compares it with the committed file, line endings normalised (`core.autocrlf` is true here — the existing test does the same at `:17-21`). A stale fixture fails with the regeneration command in the message (`:58`).
- `frontend/tests/templates.spec.ts` (replacing the four-template assertion at `validatorTemplate.spec.ts:160`) asserts, for each of the six gallery entries, `forValidate(document)` deep-equals the fixture's `document`, `validation.valid === true`, `problems` empty, `budget.unpriced_models` empty, and `static_cost_usd × 1.25 < 10`.

### D7 — Gallery card copy and order

Each card carries, verbatim from the template module: `name`, a one-sentence
`teaches`, a one-sentence `modifyFirst`, the measured price (from the
fixture's `validation.budget`, never typed — `TemplateGallery.vue:11-24`
already prices each card with a real `POST /validate` on mount), node and
edge counts, and for `idea-validator` its existing `caveat`
(`ideaValidator.ts:401-414`).

Order stays "by conceptual load, flagship last" (`builderTemplates.ts:351-365`):
`blank`, `sequential-pipeline`, `conditional-router`, `reflection-loop`,
`hierarchical-delegation`, `idea-validator`; `minimal-gated-agent` and
`fan-out-join` move to a collapsed "more" row.

### D8 — Zero configuration means the platform key

A cold sign-in has no credentials. Every template resolves to the platform
`OPENROUTER_API_KEY` (`llm.credential_id: null`) and the one attached tool
in D2 is a platform-keyed search (06). No template references a user
credential, a skill or an MCP server; those are things the user adds
afterwards, and the gallery card says which control to open first.

## Interfaces

**Owned — C9, template fixtures:**

```
frontend/src/data/templates/{sequentialPipeline,hierarchicalDelegation,reflectionLoop,conditionalRouter}.ts
  export const <NAME>: BuilderTemplate  // { id, name, teaches, modifyFirst, caveat?, document }
frontend/tests/fixtures/templates/<id>.json   // { document, vocabulary, validation }
scripts/emit_builder_fixtures.py --target templates
scripts/dump-template.ts <id>                  // frontend serialisation, run under tsx
```

`BuilderTemplate` gains `teaches: string` and `modifyFirst: string`; both
required, both rendered.

**Consumed:** C1 (authored agent / crew fields, `task.output_schema`,
`member` and `attach` ports, `joins: 'any'`), C3 (`{{cheapest}}`,
`{{workhorse}}`, `{{escalation}}` resolution), C6 / C7 (the `@launch` test
reads frames and the run result).

## Acceptance criteria

1. `ls frontend/src/data/templates` lists the four new modules; `BUILDER_TEMPLATES.length === 6` and `frontend/tests/templates.spec.ts` names each id. Rubric 15, 16.
2. For each of the four, the committed fixture has `validation.valid: true`, `problems: []`, `unpriced_models: []`, and `static_cost_usd × GRAPH_STATIC_BUDGET_MARGIN < MAX_RUN_COST_USD` — asserted on both sides (D6). Rubric 13, 15.
3. `./.venv/Scripts/python.exe -m unittest tests.builder.test_client_fixtures` passes, and editing one character of any template TypeScript makes it fail naming the regeneration command. Rubric 16.
4. No template document contains a literal model slug: `grep -rn "openrouter/\|google/\|openai/\|deepseek/\|qwen/\|z-ai/\|moonshotai/" frontend/src/data/templates` returns nothing; every `llm.model` is a `{{role}}` token. Rubric 13.
5. `reflection-loop` reports `cycles: 1` and compiles with `max_method_calls == 4`; `conditional-router` has `joins.merge === 'any'`; `hierarchical-delegation` has three `member` edges and no flow edge into a member. Asserted in `tests/builder/test_templates.py`. Rubric 11.
6. Opening each template shows every node inside the canvas pane after fit (extend `e2e/builder-layout.spec.ts:212` to loop over the six). Rubric 6.
7. **Cold sign-in, zero configuration:** `e2e/templates.spec.ts` (`@launch`, synthetic backend, stubbed signed-in session with no credentials) opens each of the four, publishes, launches, and reaches `completed` with a non-empty result body, in under **four minutes** wall clock per template. Rubric 15.
8. Each card renders `teaches`, `modifyFirst`, node/edge counts, and a price that came from `validation.budget` rather than a literal — asserted by the Vitest gallery spec. Rubric 1.
9. One **paid** run per template is recorded in `benchmarks/paid-runs.md` with run id, `cost_usd` from the run row, and `estimated` from the fixture; the estimate must exceed the measured cost. This costs money and is the owner's step. Rubric 11, 15.
10. Blind captures of the gallery and of each template's canvas at 1440×900 and 390×844, light and dark, exist under `benchmarks/ours/templates/`. Rubric 1, 2.

## References

- Gauntlet Stage 2 "Templates — four patterns, each fully working".
- `frontend/src/data/builderTemplates.ts:5-13, 240-341, 351-380`; `frontend/src/data/templates/ideaValidator.ts:380-428`.
- `frontend/tests/validatorTemplate.spec.ts:3, 43-44, 58-67, 104, 145, 160`; `frontend/tests/fixtures/builderValidatorTemplate.json`.
- `tests/builder/test_client_fixtures.py:3-21, 48-58`; `scripts/emit_builder_fixtures.py`.
- `src/brief_crew/builder/bounds.py:611-631` (loop closers are routers), `budget.py:105-125, 121` (pricing model, crew priced as tool-using), `compiler.py:786-797` (`max_method_calls`).
- `src/brief_crew/config.py:57-60, 1768, 1863, 1869, 1883`.
- `frontend/src/components/builder/TemplateGallery.vue:11-24`.
- `docs/flowise-notes.md` §3 (templates through the same load path as import and paste — the one-code-path rule this gallery already follows).

## Status

**Planned · 2026-09-02.**

Contract requests for 00: none. Dependencies this file waits on, by owner:
03 (`task.output_schema`, `member` / `attach` ports, `joins: 'any'`,
`member-agent-has-flow-edges`, `crew-hierarchical-needs-manager`), 05
(role tokens), 06 (`web_search` on the platform key), 09 (per-member crew
pricing, `'any'` join compilation).

Open decisions for the owner: (1) delete `minimal-gated-agent` and
`fan-out-join` once `e2e/builder.spec.ts` is re-pointed at
`sequential-pipeline`, or keep them in the "more" row; (2) whether criterion
9's four paid runs happen before or after the rubric gate.
