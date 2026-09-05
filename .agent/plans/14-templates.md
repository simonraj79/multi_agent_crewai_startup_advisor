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

### News template — 2026-09-05

A **fifth** pattern template, `news-to-social`, added on the owner's request:
an agent that searches the week's discussion of a subject and writes the social
post from it. The gallery's first row is **seven** cards now and
`ALL_BUILDER_TEMPLATES` is nine; the ordering rule and the demoted "more" row
are unchanged.

It is the smallest graph in the gallery that still does a whole job - five
nodes, two of them billable - and it is the cheapest: **$0.3205 floor,
$0.4284 static, $0.5355 with the 1.25x margin** against the $10.00 ceiling, all
regenerated from the committed fixture rather than typed. `validate_document`
answers `[]`.

| | |
| --- | --- |
| `subject` | input, `What should the post be about?` |
| `research` | authored agent, **cheap** tier (`{{workhorse}}`), `max_iter: 3` |
| `search` | tool, `analyze_community_sentiment`, attached to `research` |
| `write` | authored agent, **escalation** tier (`{{escalation}}`), no tools, `markdown: true` |
| `post` | output, `markdown_body` |

Four departures from what this plan's earlier sections assume, each measured
rather than reasoned:

1. **It has NO gate, and it is the first template that chose that.** Assumption
   1 above says every template carries a human gate above its first billable
   node, and that is right for the four that came before: it is what makes them
   launchable by a signed-OUT visitor. This one is written to run
   **unattended**, and a gate is the one thing that makes that impossible. The
   price is exactly one thing - `create_run` answers **403** for a signed-out
   caller unless `BUILDER_ALLOW_GATELESS_GRAPHS` is set - and it is paid in the
   open: the card carries a `caveat` saying so, and `PublishDialog` already
   renders the refusal sentence verbatim before anybody shares a link.
   `UNGATED_BY_DESIGN` in `test_templates.py` is now two, and the test that
   names them fails if a third appears.
2. **The tool is NOT `firecrawl_search`, and `BUILDER_PLATFORM_FIRECRAWL_DEFAULT`
   cannot make it one.** That flag is read at exactly one site -
   `research_market_landscape`'s `credential_optional`, `builder/tools.py:578` -
   whose factory falls back to the process `FIRECRAWL_API_KEY`. The three
   `firecrawl_*` entries are `credential_optional=False` unconditionally and
   `_firecrawl` **raises** without a credential, so no flag reaches them. A
   template naming one would open with `tool-credential-required` on a graph
   nobody had touched and could not run from a cold sign-in. Same conclusion as
   assumption 2 above, reached from a different entry.
3. **Its input field is `subject`, not `topic`.** `sequential-pipeline` already
   declares `topic`, and `testInputs.ts` resolves a saved sample **by field** -
   a cloned document carries no provenance, so the field is all there is to key
   on. Two templates sharing a field share a sample, and `AI agents` is not the
   prompt somebody opening the research pipeline should be handed. The prompt
   VARIABLE is still `{topic}`; only the state key differs, which is the one
   place in the gallery that distinction is visible.
4. **The `@launch` E2E's green line does not prove an anonymous launch works,
   and the file now says so.** Every request in `e2e/templates.spec.ts` goes
   through the e2e Vite proxy, which forwards `X-Synthetic-User: e2e-user`, so
   the API sees a **signed-in** caller - which is the case this template was
   written for, and the reason it completes with no flag set. The anonymous 403
   is proved where it can actually be reached, in
   `test_workflow_ownership.py::test_an_anonymous_launch_of_a_gateless_graph_is_still_403`.
   A first draft of this test skipped on a 403 that never arrives; that dead
   branch was removed once the header was found.

Criteria 1-8 hold for the fifth template as they do for the other four, by the
same tests extended rather than by new ones: `templates.spec.ts` (client and
server), `test_client_fixtures.py`, `test_templates.py`, `builder-layout.spec.ts`
and `e2e/templates.spec.ts`. It is in `capture-templates.spec.ts` too, so
criterion 10's capture run covers it. **Criterion 9 is still the owner's money**
and this session spent **$0.00**.

**What a paid run of it needs**, exactly: a signed-in caller (or
`BUILDER_ALLOW_GATELESS_GRAPHS=1`), `OPENROUTER_API_KEY`, and nothing else - the
attached search is keyless. `POST /api/sessions/{id}/runs` with
`{"workflow_id": "<published id>", "inputs": {"subject": "AI agents"}}`. No
gate reply is needed. Projecting the paid acceptance run's measured 2.8% of
static onto $0.4284 gives roughly **$0.012**; the figure to authorise against is
the static $0.4284.

### Measured, 2026-09-05

```text
Python           2441 run - 0 failures, 6 skipped, 149.9 s
Frontend unit    1705 passed in 84 files
vue-tsc -b --force    exit 0
npm run build         677 ms
E2E              131 collected - 122 passed, 8 skipped, 1 failed
```

**The one E2E failure is PRE-EXISTING and that was measured rather than
argued.** `builder.spec.ts:1227` - "paints the target handle green when it will
take the edge" - fails only inside a full-suite run and passes in 5 s on its
own. This branch does not touch that file, so the base commit `5a97b26` was
checked out and the whole suite run again on the same machine under the same
backend: **130 collected, 121 passed, 8 skipped, and the same one test failed.**
The delta from this work is therefore exactly +1 test and +1 pass.

The eight skips are environment knobs this session did not set - `E2E_MCP_URL`,
and `SYNTHETIC_FAILURE` for `failure-modes.spec.ts` and `test-panel.spec.ts` -
and each skip names the knob it wants; the base run skipped the same eight.
The two `gallery-*.png` visual baselines WERE re-recorded, because the gallery
is this change's own surface and it gained a card by design; nothing else was
re-baselined, and the two `[mobile]` gallery captures did not move because a
390px column puts the seventh card below the fold.
`benchmarks/perf/canvas.json` is rewritten by every perf run and was reverted
rather than committed.

### The four, as built — 2026-09-04

**Built · 2026-09-04.** Eight of the ten criteria are met. Criterion 9 is the
owner's money and criterion 10 is a capture run rather than a code change.

The gallery led with **six** templates and kept the two library-agent ones in a
demoted second row. (Seven and two since 2026-09-05 — the section above.) The
four new ones are authored end to end - every prompt
on the canvas is a prompt an author may edit - name their models by role rather
than by slug, validate with **zero problems**, publish, and reach a completed
run with a non-empty body from a cold sign-in with nothing configured.

| # | Criterion | State | Shown by |
| ---: | --- | --- | --- |
| 1 | four modules, `BUILDER_TEMPLATES.length === 6`, each id named | **met** | `templates.spec.ts` "offers them in the order plan 14 D7 declares" and "keeps the two library-agent templates in a second row"; `test_templates.py::GalleryTests` |
| 2 | fixture `valid`, `problems: []`, `unpriced_models: []`, static x margin < ceiling, both sides | **met** | `test_templates.py::ValidationTests` (5) and `test_client_fixtures.py::TemplateFixtureTests` (3) server-side; `templates.spec.ts` asserts the same three per template client-side |
| 3 | `unittest tests.builder.test_client_fixtures` passes, and a one-character template edit fails it naming the regeneration command | **met, in two halves** | proved by breaking it - see *The bridge* below |
| 4 | no literal model slug under `frontend/src/data/templates` | **met** | the criterion's own grep exits 1; `test_templates.py::ModelRoleTests::test_no_template_source_file_carries_a_model_slug` runs it as a test and caught a slug in a docstring on its first run |
| 5 | `reflection-loop` 1 cycle / `max_method_calls == 4`; `conditional-router` `joins.merge === 'any'`; `hierarchical-delegation` three member edges and no flow edge into a member | **met** | `test_templates.py::PatternTests` (7) |
| 6 | every node of each template inside the canvas pane after fit | **met** | `e2e/builder-layout.spec.ts` "lands every node of every pattern template inside the canvas pane" |
| 7 | cold sign-in, zero configuration: open, publish, launch, `completed` with a non-empty body, under four minutes | **met** | `e2e/templates.spec.ts`, four `@launch` tests, **1.6-1.7 s each** |
| 8 | each card renders `teaches`, `modifyFirst`, node/edge counts and a price from `validation.budget` | **met** | `templates.spec.ts` "renders teaches, modifyFirst and both counts on every card", "prices every card from the server answer rather than from a literal" |
| 9 | one **paid** run per template in `benchmarks/paid-runs.md` | **not done - the owner's money** | decision 22. Costed below. **This session spent $0.00** |
| 10 | blind captures under `benchmarks/ours/templates/` | **met** | `e2e/capture-templates.spec.ts` wrote **28 PNGs** - gallery + six templates x 1440x900 and 390x844 x dark and light |

### Measured, 2026-09-04, in this worktree

```text
Python           2243 run · 0 failures · 6 skipped · 131.7 s   (baseline 2119)
Frontend unit    1468 passed in 74 files                        (baseline 1426 in 73)
vue-tsc -b --force    exit 0
npm run build         2042 modules · 677 ms
E2E              68 passed · 2 failed · 5 skipped · 4.4 min    (baseline 69 listed)
```

Every row was RUN, not inherited. Three notes on the E2E line, because a count
with no explanation is the thing this repository keeps having to correct:

* **The two failures are not this plan's, and that was proved rather than
  argued.** `visual/builder-canvas.spec.ts` "problem state — dark / light" is a
  pixel baseline whose diff lies ENTIRELY inside the inspector rail - the model
  picker, the tier control, the tools list - which plan 04's `4d8a054` rewrote
  after the baseline was taken by `f7f2e95`. Re-run with this plan's four
  changed `src/` files reverted to HEAD: **the same 12,442 pixels differ**. They
  are left un-baselined deliberately; re-recording somebody else's pixels would
  ratify a change nobody reviewed.
* **The four GALLERY baselines WERE re-recorded**, because the gallery is this
  plan's surface and it changed by design.
* **The five skips are the harness, not the product.** `isolation.spec.ts`
  carries `test.skip(Boolean(process.env.E2E_BASE_URL))`, and this run set
  `E2E_BASE_URL` to reach a private Vite server on 5283: ports 8099-8101 and
  5273 were already held by other sessions in this shared worktree, so this plan
  ran its own stack on **8102 / 5283**. Run the suite the MISSION way, on 8099
  with no `E2E_BASE_URL`, and those five run.

### The four, priced at head

Every figure regenerated on 2026-09-04 from the committed fixtures, which are
themselves generated from the real `validate_document` and `estimate_budget`.
`floor` is the published prices; `static` is what admission enforces, with the
measured nitro inflation on every cheap-tier node; the ceiling is $10.00 and the
margin 1.25×, applied to `static` and never to `floor`.

| template | nodes | edges | billable | esc | cycles | calls | floor | static | × 1.25 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `sequential-pipeline` | 7 | 6 | 3 | 1 | 0 | 30 | $0.4618 | $0.6597 | $0.8246 |
| `conditional-router` | 10 | 11 | 4 | 0 | 0 | 33 | $0.3414 | $0.6116 | $0.7645 |
| `reflection-loop` | 8 | 9 | 2 | 0 | **1** | 72 | $0.8547 | $1.5384 | $1.9230 |
| `hierarchical-delegation` | 7 | 6 | 1 | 1 | 0 | 30 | $0.5235 | $0.5235 | $0.6543 |
| **four, summed** | | | | | | | **$2.1814** | **$3.3332** | **$4.1665** |

Three prices are worth a sentence each, because each is a fact about the model
rather than about the graph. `reflection-loop` is the dearest with the fewest
billable nodes: both agents sit on the cycle, so each is priced
`1 + MAX_CYCLE_ITERATIONS` = four times over. `hierarchical-delegation` prices
its three members INSIDE the crew node, so it reports one billable node and
thirty calls. And `conditional-router` is a worst case in the strictest sense -
every one of its three desks is priced although exactly one ever runs, which is
the arithmetic the card exists to make visible.

### Criterion 9's costed estimate - not run, and the owner's to authorise

**$3.33** is the worst case for all four, and it is a worst case in which every
guardrail retries, every tool loop runs to `max_iter`, every cycle goes round
three times, and the cheap tier bills at its dearest endpoint. The only
measurement this repository has of that model against reality is the paid
acceptance run: `$0.0417` measured against a `$1.5137` static estimate for the
same graph, **2.8%**. Projecting that ratio onto these four gives roughly
**$0.09** for the set. That is a projection from ONE data point and is labelled
as one; the number to authorise against is $3.33.

**This session spent $0.00.** Nothing here called a model.

### The bridge, and what each half catches

A template's document is authored in TypeScript and the thing that proves it is
a template - `validate_document` and `estimate_budget` - is Python. Something
has to carry a document across that line, and the two obvious answers are worse
than the one taken: writing the documents twice makes a template a thing that
can disagree with itself, and having Python shell out to `node` inside a unit
test makes the Python CI job depend on `frontend/node_modules`, which
`.github/workflows/ci.yml` does not install.

So `scripts/dump-templates.mjs` is the bridge and its output is committed:

```
frontend/src/data/templates/*.ts            authored
  -> node scripts/dump-templates.mjs
frontend/tests/fixtures/templates/documents.json     committed
  -> ./.venv/Scripts/python.exe scripts/emit_builder_fixtures.py
frontend/tests/fixtures/templates/<id>.json          committed
```

and BOTH ends are gated, which is the only thing that makes a committed
intermediate honest:

| gate | goes red when |
| --- | --- |
| `frontend/tests/templates.spec.ts` | the TypeScript no longer equals `documents.json` |
| `tests/builder/test_client_fixtures.py::TemplateFixtureTests` | a fixture is not what the emitter produces from `documents.json` today |

**Proved by breaking it**, 2026-09-04, rather than argued. One character was
changed in `sequentialPipeline.ts` - `max_iter` 3 to 2:

```text
npx vitest run tests/templates.spec.ts
  x sequential-pipeline matches its fixture byte for byte
    sequential-pipeline has drifted from its fixture. Regenerate with:
        node scripts/dump-templates.mjs && ./.venv/Scripts/python.exe scripts/emit_builder_fixtures.py

node scripts/dump-templates.mjs      # the author remembers half the recipe
python -m unittest tests.builder.test_client_fixtures
  FAIL: test_every_committed_template_fixture_is_current (sequential-pipeline.json)
    frontend/tests/fixtures/templates/sequential-pipeline.json is stale ...
```

Reverted; both green. **Criterion 3's letter says the Python test fails on a
one-character TypeScript edit, and what is true is that it fails on the second
step of that edit while the Vitest half fails on the first.** Stated rather than
smoothed over: an edit cannot land silently either way, and closing the letter
would mean running `node` from a Python unit test in a CI job that has neither
`node_modules` nor a reason to.

### Nine assumptions and departures, each where the plan and the code disagreed

Stated rather than smoothed over. In every case the reading taken is the one the
surrounding code most directly supports.

1. **Every template carries a human GATE above its first billable node, and the
   plan's node tables have none.** `create_run` answers **403** for a published
   graph that reaches a billable node before any human gate unless
   `BUILDER_ALLOW_GATELESS_GRAPHS` is set, and a `SYNTHETIC=1` backend with no
   `AUTH_BASE_URL` resolves every caller to nobody - so a gateless template is
   one the E2E suite cannot launch and a signed-out visitor cannot either.
   Measured: `idea-validator`, which scopes before it gates, publishes
   `gated_before_spend: false` and answers 403 on an anonymous launch. One node
   and one edge per template, and it is the shape `MINIMAL_GATED_AGENT` has
   shipped with since 2026-09-02.
2. **The attached tool is `analyze_community_sentiment`, not `web_search`.** D8
   calls `web_search` "platform-keyed"; it is not. Every one of its four
   providers maps to a credential kind through `credential_kind_by_param`, and
   PLANS.md decision 9 (a platform Firecrawl key) is provisional and off - so a
   template shipping it opens with `tool-credential-required` on a graph nobody
   has touched. Measured against a live `/api/builder/validate` before the swap.
   The chosen tool is keyless, is a real search rather than a stand-in, and
   returns URLs the writer can cite.
3. **`reflection-loop`'s router loops on `lt` and exits on `otherwise`**, which
   is the opposite polarity to D4's `[done: gte 8, again: otherwise]`.
   `_compare` returns false for a null on every ordering comparison, so with
   `done` as the tested branch a critic whose answer could not be parsed scores
   null, fails `gte`, falls to `again`, and goes round until CrewAI's
   `max_method_calls` raises `RecursionError` - a run that fails having paid for
   four drafts because one answer came back unreadable. Written this way the
   same null falls to `done` and the run ends with the draft it has. A loop
   should fail towards stopping.
4. **`reflection-loop`'s output names its source; the other three do not.** D4
   asks for `source: "${state.out__generate}"` and it is right, for a reason
   worth recording: an unset source follows the incoming edge, that edge comes
   from `judge`, and a router records what flowed THROUGH it - which at that
   point is the score it compared rather than the draft it was deciding about.
   Measured before the line existed: the run completed and answered
   `markdown_body: ""` with no problem reported anywhere. Every other output in
   the gallery leaves `source` null on purpose, so the `8e24e35` default stays
   exercised.
5. **`conditional-router`'s merge is `join_text`, not `default`.** `default`
   takes one value and one fallback, which is two branches; there are three.
   `join_text` skips a null and every branch that did not run IS null, because
   the compiler pre-seeds `out__*` - so joining all three yields exactly the one
   that ran, and a fourth desk costs one more argument.
6. **The three role tokens are C9's, not C3's.** The plan lists `{{cheapest}}`,
   `{{workhorse}}` and `{{escalation}}` as consumed from plan 05; no such thing
   exists in `data/models.ts`, and the served roster carries two presets named
   `cheap` and `escalation`. `frontend/src/data/templates/modelRoles.ts`
   resolves all three - the two presets, plus the roster's least expensive row
   that still supports tools and JSON mode, measured on `cost_in_max_endpoint`
   rather than on the headline. `test_templates.py::ModelRoleTests` asserts the
   Python and TypeScript answers agree, which is spec R7's condition for
   admitting a client mirror at all.
7. **The "more" row ships OPEN.** D7 says collapsed. The grid is
   `repeat(auto-fill, minmax(232px, 1fr))` inside `width: min(1080px, 100%)`,
   which resolves to four columns - so six cards occupy two rows and eight cards
   occupy the same two rows. Shutting it saves no vertical space at all, and it
   DOES hide the card six E2E specs click: measured, `builder.spec.ts` and
   `mobile.spec.ts` failed on a hidden-element timeout the first time it shipped
   shut. That is "a template change becomes a suite change", which is the thing
   owner's decision 21 was made to avoid. The demotion is the heading and the
   position.
8. **`BuilderJoins` in `types/builder.ts` was narrower than the server** -
   `Record<string, 'all'>` where `document.py::_validate_joins` has admitted
   `'any'` since 03 D3. `conditionalRouter.ts` is the first client code that
   needed it. Corrected, with the measurement that justified admitting `'any'`
   restated at the site. **The Integrator should confirm this is a mirror repair
   rather than a C1 change**; it widens the client to what the server already
   accepts and narrows nothing.
9. **`data/models.ts`'s `roster` ref moved to `data/modelRoster.ts`** and is
   re-exported, so every importer is unchanged. `models.ts` imports
   `services/httpCore`, which reads `import.meta.env` at module load and is
   therefore unimportable by anything that is not Vite - including the dump
   script, which needs the roster to resolve a role and needs no network at all.
   One ref, two doors.

### For the Integrator

- **`frontend/tests/builderApi.spec.ts` is red, and not from this plan.** It
  asserts `declared.size === 30` and `builder_api.py` now declares **31**: the
  extra is `GET /workflows/{document_id}/compiled`, added in this shared
  worktree by plan 10/11's uncommitted work (`git diff` names it). This plan
  added no route.
- **`benchmarks/paid-runs.md` does not exist**, so criterion 9 has no file to
  write into yet. Whoever authorises the spend creates it.
- Nothing in `PLANS.md` was touched. The row this plan implies is
  `| 14 | Templates | S8 | 09 | 10 | 8 | — | 0 | In build | 2026-09-04 |`.

### Owner decisions answered — 2026-09-04

**Decision 21 — keep both in a "more" row.** They are what the E2E suite drives,
and deleting them turns a template change into a suite change.

**Decision 22 — after the rubric gate, and after asking; the owner must approve
the spend.** The OpenRouter balance was $27.55 on 2026-09-04 and the standing
authorization is $5.00 cumulative for small live runs, so criterion 9's four
paid runs are outside it and need a costed estimate and a fresh yes.
