# 04 — Inspector and parameters

Parameter forms, three-tier disclosure, capability gating, credential picking,
live cost, and validation feedback. Build-time; compared against Flowise.

## Problem

The inspector is docked, keyboard-first and flat. Dispatch is a total
`Record<NodeKind, Component>` (`InspectorRail.vue:67-75`); the agent/crew form
exposes six controls at once — tier, `agent_id`, tools checklist, `max_iter`,
`guardrail_max_retries`, `prompt_inputs` (`BillableForm.vue:75-91, 111-148,
351-452`) — and argues against disclosure in its own comment
(`BillableForm.vue:29-35`). That was right for six controls. An authored agent
has **thirty-four** (FD5), a crew fifteen, and a flat rail would bury the
five that matter under the twenty-nine that rarely do.

Nothing gates a control on what the chosen model can do, because a document
cannot name a model. There is no credential picker, no schema editor, no
prompt field with a counter, and the per-node cost is invisible: `BudgetMeter`
shows two whole-flow figures and four pip rows (`BudgetMeter.vue:28-59`).
Field-anchored problems cover eleven codes (`types/builder.ts:425-454`).

Flowise v2 configures a node in a **modal** on double-click
(`docs/flowise-notes.md` §0); R15 forbids that and stands. Flowise silently
accepts a parameter the model cannot honour; the gauntlet names that as a
deliberate win condition.

## Scope

Every inspector form for the ten kinds, the tier mechanism, the new widgets
(prompt, model picker, credential picker, schema editor), capability gating,
per-node cost, field-anchored problems for the new codes, multi-select, and
keyboard reachability. Files: `InspectorRail.vue`, `inspectors/**`, `fields/**`,
`BudgetMeter.vue`, `useBuilderValidation.ts`, `types/builder.ts` (`FIELD_CODES`).

## Out of scope

The registry's contents (05). Tool param schemas' contents (06). MCP discovery
UI (07 owns the server panel; this plan owns the `mcp` node inspector that
picks from discovered tools). Skill authoring (08). Validation rules
themselves (12 — this plan only anchors them).

## Design

**D1 — Three tiers, nothing hidden.** Each form renders three regions:
*Essentials* (always open), *Advanced* (a `<details>` with a `<summary>`
button, closed by default, state remembered per node kind in
`sessionStorage`), *Expert* (rendered only while the rail's "Expert settings"
switch is on; the switch is in the rail header, persisted in
`localStorage['builder-inspector-expert']`, and its off-state shows a one-line
"N expert settings hidden — show" link so nothing is ever *absent*). A field
carrying a problem forces its region open and scrolls into view — an error
behind a closed disclosure is the modal-stack failure R15 exists to prevent.

**D2 — Field placement.** Every FD5 field, its widget, bound and source of
truth. Bounds come from `vocabulary.bounds` (R6), never constants.

*Authored agent*

| Tier | Field | Widget | Bound / validation |
| --- | --- | --- | --- |
| E | `role`, `goal`, `backstory` | `PromptField` (textarea, counter, amber inside last 200) | 1..`max_prompt_chars`; `prompt-too-long` |
| E | `task.description`, `task.expected_output` | `PromptField` | same |
| E | `llm.model` | `ModelPicker` | registry id; `model-unknown`, `model-over-ceiling` |
| E | tier preset | two chips (cheap / escalation) that **set** `llm.model`; shows "custom" when the model is neither | — |
| E | attachments | read-only avatar list with "jump to node" — attachments are edges, never a dropdown (Flowise v2 `agentTools` array is the anti-pattern) | — |
| A | `task.output_schema` | `SchemaEditor` (grid: property, type ∈ string/number/boolean/array/object, description, required; "Paste JSON") | valid JSON Schema; `state-schema-invalid` reused with `field` |
| A | `task.markdown`, `task.async_execution` | switches | — |
| A | `llm.temperature`, `top_p` | slider + number | 0..2 / 0..1 |
| A | `llm.max_tokens`, `timeout` | number | ≥ 1 |
| A | `llm.response_format` | segmented text / json | gated by `supports_json_mode` |
| A | `max_iter`, `max_rpm`, `max_execution_time` | number | 1..`max_agent_iter`; ≥ 1; seconds |
| A | `allow_delegation`, `memory`, `cache`, `respect_context_window` | switches | — |
| A | `retry.max_retries`, `retry.backoff_seconds`, `retry.fallback_model` | number, number, `ModelPicker` (nullable) | 0..`max_retries`; 0..30; `retry-over-max` |
| A | `on_error` | segmented fail / route; switching to route adds the `error` port | `error-port-unconnected` (warning) |
| A | `guardrail_max_retries`, `prompt_inputs` | today's widgets (`BillableForm.vue:376-452`) | unchanged |
| X | `llm.frequency_penalty`, `presence_penalty` | slider | −2..2 |
| X | `llm.stop[]`, `seed` | `TokenListInput`, number | — |
| X | `llm.reasoning_effort` | segmented none/low/medium/high | gated by `supports_reasoning`; help text says OpenRouter drops it for non-`o1` models (`config.py:707-712`) unless routed through `extra_body` — 09 decides |
| X | `reasoning`, `max_reasoning_attempts` | switch, number | gated by `supports_reasoning` |
| X | `multimodal` | switch | gated by `supports_vision` |
| X | `system_template`, `prompt_template`, `response_template` | `PromptField` | `max_prompt_chars` |
| X | `function_calling_llm` | `ModelPicker` (nullable) | must `supports_tools` |
| X | `tool_failure_policy` | segmented ignore / warn / raise | default warn (`tool_failure.py:57-69`) |

*Library agent* — today's six controls, unchanged, plus a "convert to
authored" action that copies the YAML role/goal/backstory into a new authored
node (one commit) so a user can start from the repo's Scoper and edit it.

*Authored crew* — E: `process` (segmented), members (read-only list with
drag-to-reorder = `task_order`), `manager_llm` / `manager_agent` (one or the
other; required when hierarchical; `crew-hierarchical-needs-manager`); A:
`memory`, `cache`, `max_rpm`, `planning`, `planning_llm`, `retry`, `on_error`,
`prompt_inputs`; X: none. *Library crew* — today's controls with the
"accepted and ignored" help text (`BillableForm.vue:356-359`) **removed**,
because 09 makes the factory honour `tier` / `max_iter` or the schema stops
accepting them.

*Tool* — E: catalogue label (read-only), `credential_id` (`CredentialPicker`,
shown only when `credential_kind` is set; `credential-missing`), each
`params[]` entry rendered from its `type` (string → text, number → number with
min/max, boolean → switch, json → `ScalarInput`/JSON textarea, `enum` →
select). *Mcp* — E: server (from C12 list), `tool_names[]` as a checklist of
discovered tools with a refresh button (`mcp-server-unavailable`,
`mcp-tool-unknown`). *Skill* — E: `skill_id` from C11 list with the skill's
description read-only (`skill-unknown`).

*Gate, router, transform, input, output* — unchanged
(`GateForm.vue`, `RouterForm.vue:116-200`, `TransformForm.vue`,
`InputForm.vue`, `OutputForm.vue`). *Graph settings* (nothing selected,
`GraphSettings.vue:143-184`) gains the `state` schema editor and the joins
`all` / `any` segmented control now that `any` is legal.

**D3 — Capability gating: disabled with a reason, never dropped.** The
`ModelPicker` publishes the selected registry entry; each gated control reads
one flag and, when false, renders `disabled` with `aria-disabled`, a tooltip
*"{model name} does not support {capability}"*, and keeps its **stored value**
visible. Because the value stays in the document, validation reports
`model-lacks-capability` with `field` naming the control, so an author who
switches model sees exactly what stopped working and can clear it or switch
back. Flowise drops silently; the gauntlet scores this.

**D4 — `ModelPicker`.** A listbox over `vocabulary.models` (≤ 10): name,
provider glyph, `cost_in / cost_out` per M, context window, four capability
glyphs, `speed_tier`, `recommended_for` tags; sorted by `cost_in`; a search
box; the two tier presets pinned at the top. Selecting writes `llm.model`
and, on an authored agent, updates the card's model pill. A model absent from
the registry (a stale document) renders as "not in this roster" with the
problem `model-unknown` — the same treatment `agent_id` gets today
(`BillableForm.vue:111-131`).

**D5 — `CredentialPicker`.** Lists `{id, kind, label}` from C4 filtered by
`credential_kind`, plus *Create new…* which opens the credential form as a
**docked sub-panel** in the rail (R15), returns the new id, and selects it.
Never shows a secret; a deleted credential shows "credential no longer
exists" and `credential-missing`.

**D6 — Live cost, per node.** `BudgetMeter` keeps its two figures and pips.
The LLM sub-form adds one line, *"this node ≈ $0.12 of $1.51 (static)"*, from
the budget response's per-node breakdown, recomputed on the same 400 ms
validation debounce (`useBuilderValidation.ts:39, 111`). Changing the model
therefore reprices within half a second without leaving the field.

**D7 — Field-anchored problems.** `FIELD_CODES` (`types/builder.ts:425-454`)
grows from eleven to cover every FD14 code with a fixed field; codes whose
field varies (`model-lacks-capability`, `state-schema-invalid`,
`prompt-too-long`) carry `field` in the problem payload and the client anchors
to it. Clicking a problem row, or `F8`, focuses the control, opens its tier,
and flashes the card (`useBuilderCanvas.ts:1174-1218`).

**D8 — Multi-select.** Today three shared fields with `MIXED`
(`InspectorRail.vue:306-357, 639-704`). Add the shared authored fields:
`llm.model`, `retry.*`, `on_error`, `tool_failure_policy`, `memory`, `cache`.
One commit per change (one undo), unchanged.

**D9 — Keyboard.** Every widget is a native control or has `role`, `tabindex`
and arrow handling; tier summaries are `<button aria-expanded>`; `Tab` order
is E → A → X → problems. No new global hotkeys; `useBuilderHotkeys` is data
and `ShortcutSheet` would otherwise drift (`useBuilderHotkeys.ts:5-27`).

**D10 — Click budget (rubric 4).** From an empty document to a valid,
runnable `input → authored agent → output` with one tool and a chosen model:
template card (1) · palette `2` key or tile (1) · wire input→agent (1 drag) ·
model picker open + choose (2) · tool tile dropped on agent (1 drag) · palette
`7` (1) · wire agent→output (1 drag) = **8 pointer actions plus typing five
prompt fields**. Flowise v2: open dialog, model dropdown, tools array add,
tool dropdown, close — measured by the critic, not here.

## Interfaces

Consumes **C1** (fields, FD5), **C2** (`models`, `tools[].params`, `bounds`),
**C3**, **C4** (`GET /api/builder/credentials` → `[{id, kind, label}]`;
`POST` → `{id}`), **C8** (codes with `field`), **C11** (`GET
/api/builder/skills` → `[{skill_id, name, description}]`), **C12** (`GET
/api/builder/mcp/servers` → `[{server_id, label, status, discovered_tools:
[{name, description}]}]`).

Owned:

- `INSPECTOR_FIELDS` (`InspectorRail.vue:86-94`) extended with every FD5 path; `FIELD_CODES` extended per D7.
- Widgets: `fields/PromptField.vue`, `fields/ModelPicker.vue`, `fields/CredentialPicker.vue`, `fields/SchemaEditor.vue`, `fields/TierRegion.vue` (E/A/X container).
- Props contract: every inspector form takes `(node, vocabulary, problems, capabilities)` and emits `InspectorCommit` (`commit.ts:3-16`) — unchanged shape.

## Acceptance criteria

1. `frontend/tests/builderInspector.spec.ts`: mounting an authored agent renders every FD5 field exactly once across the three regions; Advanced is closed by default; Expert is absent from the DOM with the switch off and the "N expert settings hidden" link present with `N` correct.
2. A problem on an Expert field with the switch off turns the switch on, opens the region, and focuses the control (`builderInspector.spec.ts`, `e2e/builder.spec.ts` "walk to a hidden problem").
3. With a model whose `supports_json_mode` is false, `response_format` is `disabled`, has `aria-disabled="true"`, a tooltip naming the model, and its stored value still renders; the problems dock shows `model-lacks-capability` anchored to that field. Same for `reasoning_effort` / `supports_reasoning` and `multimodal` / `supports_vision`.
4. `ModelPicker` lists exactly `vocabulary.models`, sorted by `cost_in`, presets pinned; choosing one updates the card's model pill in the same tick (`builderNode.spec.ts`).
5. `CredentialPicker` never renders a secret string; "Create new" opens a docked sub-panel, not a dialog (`document.querySelector('[role=dialog]')` is null — R15).
6. The per-node cost line changes within 500 ms of a model change (`e2e/builder.spec.ts`, fake budget response with per-node breakdown).
7. `FIELD_CODES` covers every FD14 code that has a fixed field; `frontend/tests/clientMirrors.spec.ts` asserts every code in `vocabulary.problem_codes` is either in `FIELD_CODES` or in the documented node-level list.
8. Multi-selecting two authored agents with different models shows `MIXED` on `llm.model`; choosing one applies to both in one undo step.
9. Axe (`@axe-core/playwright` is **not** added — zero new deps): a Playwright keyboard walk tabs through every control of an authored agent inspector and reaches the problems dock; no control is skipped (`e2e/builder.spec.ts` "inspector is fully keyboard reachable").
10. **Rubric 4:** `e2e/builder.spec.ts` "configure an agent in eight pointer actions" performs D10 and ends with `valid: true` from the validation response.
11. `npx vitest run` and `npx vue-tsc -b --force` exit 0; adding a kind without an inspector fails `vue-tsc` (`InspectorRail.vue:67-75`).

## References

- Flowise: `views/agentflowsv2/EditNodeDialog.jsx` (the modal to avoid), `views/tools/ToolDialog.jsx:144-167` (schema grid: property / type / description / required, "Paste JSON"), `views/canvas/CredentialInputHandler.jsx` (credential dropdown + create/edit), `packages/components/nodes/agentflow/Agent/Agent.ts:251-271` (`agentTools` array — the dropdown-of-tools anti-pattern) — `docs/flowise-notes.md` §2, §4.
- CrewAI: field tables in `docs/crewai-notes.md` §1–§4; `crewai/agent/core.py:279-282, 305-308` (deprecated code execution, not rendered); `crewai/tools/tool_failure.py:57-69`; `crewai/llm.py:372-388`.
- Repo: `frontend/src/components/builder/InspectorRail.vue:32-43, 67-94, 306-357, 405-411, 516-625, 639-704`; `inspectors/BillableForm.vue:29-44, 75-91, 111-148, 351-452`; `inspectors/{GateForm.vue:21-27, 74-83, RouterForm.vue:116-200, RouterBranchEditor.vue:144-221, GraphSettings.vue:143-184}`; `fields/{FieldRow,FieldProblem,NodeIdField,ScalarInput,StateRefInput,TokenListInput}.vue`; `BudgetMeter.vue:28-59`; `commit.ts:3-16`; `composables/useBuilderValidation.ts:39, 111`; `useBuilderCanvas.ts:1174-1218`; `types/builder.ts:400-454`; `src/brief_crew/config.py:707-712`.
- `docs/flow-builder-spec.md` R15, §4.4, WP-E.
- Gauntlet: Stage 2 "Node parameters" (three tiers), "Models" (capability flags drive the UI; disabled with tooltip, never silently dropped), rubric 4.

## Status

Planned · 2026-09-02.

CONTRACT REQUESTS: (a) for 09/10 — the budget response gains
`per_node: { [node_id]: { calls, usd } }` (D6); (b) for 12 / C8 — the
problem payload gains optional `field: string` (D7). Proceeding as if both
are granted.

Open decision for the owner: whether the Expert switch is global (this plan)
or per node kind.

### Owner decisions answered — 2026-09-04

**Decision 19 — global.** Per node kind means an author learns the same control
four times and it remembers a different answer each time.

### Built — 2026-09-04

Built against **`00-architecture.md`'s `FD5` table and its S9 deprecation
ruling**, not against this file's older prose, per the instruction in `FD5`
itself: *"where this document and the package disagree, the package wins."*
Every departure is listed below with its reason.

| # | Criterion | State | Shown by |
| ---: | --- | --- | --- |
| 1 | every FD5 field once across three regions; Advanced closed; Expert absent with the switch off and `N` correct | **met** | `frontend/tests/authoredInspector.spec.ts` — the field list is parsed out of `document.py` at run time, not written here |
| 2 | a problem on an Expert field opens the switch, the region, and focuses the control | **met (unit)** | same file, *"forces the region open"* and *"focusField turns the switch on"*. The `e2e/builder.spec.ts` half is **not written** — see criterion 9 |
| 3 | `response_format` / `reasoning_effort` disabled, `aria-disabled`, a tooltip naming the model, stored value still rendered, `model-lacks-capability` anchored | **met** | same file, *"a parameter the model cannot honour"*; server half `tests/builder/test_model_gating.py::ProblemFieldTests` |
| 4 | `ModelPicker` lists exactly the roster, sorted by `cost_in`, presets pinned; the card pill moves in the same tick | **met** | same file, *"the model picker, and what the card says"* |
| 5 | `CredentialPicker` never renders a secret; *Create new* is docked, not a dialog | **met (pre-existing)** | `frontend/tests/credentialPicker.spec.ts` — *"renders no field value from a list that carries them, in any shape"* and *"opens an inline form with no dialog"*, both landed with plan 01 |
| 6 | the per-node cost line changes within 500 ms of a model change | **partial** | the reader is built and tested (`authoredInspector.spec.ts`, *"the per-node cost line"*); the server serves no `per_node` yet — it is **C5, owned by plan 09**. The line renders when the key arrives and is absent until then |
| 7 | `FIELD_CODES` covers every FD14 code with a fixed field | **met** | `authoredInspector.spec.ts`, *"anchors every code with a fixed field"* — a total partition over `PROBLEM_CODES` |
| 8 | multi-select two authored agents: `MIXED` on `llm.model`, one undo | **met** | same file, *"multi-selection over authored nodes"* |
| 9 | a Playwright keyboard walk reaches every control | **not reached** | `frontend/e2e/**` is S9's under the 00 ownership map, and the run needs a live backend. Every widget is a native control or carries `role` / `aria`, which is the precondition; nothing has walked it |
| 10 | *"configure an agent in eight pointer actions"*, ending `valid: true` | **not reached as a test; counted as 7** | see the click budget below |
| 11 | `vitest` and `vue-tsc -b --force` exit 0; a kind with no inspector fails `vue-tsc` | **met** | `vue-tsc` exit 0; `INSPECTORS` is still `Record<NodeKind, Component>` |

**Click budget, counted against what is built rather than against D10's list.**
From the gallery to a valid `input → authored agent → output` with one tool and
a chosen model: Blank canvas card (1) · palette `2` (1) · **Convert to an
authored agent (1)** · wire input→agent (1 drag) · a tier chip (1) · tool tile
dropped on the agent (1 drag) · wire agent→output (1 drag) = **7**. Two things
moved in opposite directions and they nearly cancel: the Blank template already
seeds an `output`, so D10's `palette 7` press is gone, and the authored arm is
reachable only by converting a library agent, which adds one. Choosing from the
picker instead of pressing a tier chip makes it **8**. This is a count, not a
browser measurement — criterion 10's test does not exist.

**Departures from this plan's prose, each because the package or the schema
says otherwise.**

1. **`SchemaEditor` has two columns, not four, and four types, not five.**
   `TaskConfig.output_schema` is `dict[NodeId, ScalarType] | None` — a flat map
   of name to `string | number | integer | boolean`. There is nowhere to put a
   description or `required`, and no `array` or `object` to offer. Rendering
   them would be rendering controls whose values are dropped on save, which is
   the competitor behaviour this plan names as the win condition. *Paste JSON*
   survives and accepts both a bare map and a JSON Schema's `properties`; a
   property it cannot express is reported rather than dropped, and nothing is
   partially applied.
2. **The crew's members reorder with buttons, not drag.** D9 needs every control
   keyboard-reachable, so a drag would have needed this fallback anyway, and the
   fallback alone is the whole feature at a fifth of the surface. The order is
   what matters; the gesture is not.
3. **`verbose` is the crew's fifteenth field (ruled) and is rendered in
   *Advanced*, not Essentials.** D2's crew Essentials list is explicit and
   complete, and `00`'s own "fields the gauntlet names that no plan places"
   table gives the reason it was dropped in the first place: console noise, and
   the run console reads frames. Rendering it honours the ruling; rendering it
   in Advanced honours this plan's own tiering.
4. **`max_iter` and `guardrail_max_retries` are rendered on the authored crew**
   though its paragraph names neither. `AuthoredCrewConfig` inherits both from
   `_BillableConfig`, and a stored field with no control round-trips a value the
   author cannot see and cannot change.
5. **The library crew keeps its "accepted and ignored" help text**, which D2
   asks to remove. The removal is conditional on plan 09 making the factory
   honour `tier` / `max_iter`; 09 has not landed, so removing it now would
   replace a true sentence with a false one. It comes out in the commit that
   makes it false.
6. **`ModelPicker` stays a `<select>`** rather than becoming D4's listbox with
   glyph columns and a search box. It is plan 05's component, already
   unit-tested, and a hand-rolled listbox is a keyboard implementation this plan
   would have to get right for no gain over ten options. What criterion 4 asks
   for — exactly the roster, sorted by `cost_in`, presets pinned — is built; the
   glyph row, both price columns and the speed tier render beneath it, as 05
   shipped them.
7. **`ModelPicker` and `CredentialPicker` stay where they are**
   (`inspectors/ModelPicker.vue`, `builder/CredentialPicker.vue`) rather than
   moving under `fields/` as the Interfaces section lists them. Both already
   existed and both are imported by other plans' surfaces; the move is churn
   with a merge cost and no reader benefit.
8. **D8's `tool_failure_policy`, `memory` and `cache` are not in the shared
   multi-selection pane.** An authored crew has `memory` and `cache` and no
   `tool_failure_policy`, so the three do not share one predicate and a control
   offered over "authored nodes" would be wrong for one of the two kinds.
   `llm.model`, `retry.max_retries`, `retry.backoff_seconds` and `on_error` are
   there, gated on every selected node being authored — a library agent has no
   `llm` at all, and `extra="forbid"` makes writing one a 422 rather than a
   dropped key.
9. **The authored arm is reachable only by converting a library agent.** D2
   specifies that action and nothing in the plan set specifies a palette route
   to a fresh authored node; `nodeKinds.defaultConfig` still builds the library
   arm, which is 02/03's surface rather than this one's.

**One contract implemented rather than requested: C8's optional `field`.**
`bounds.Problem` and `BuilderProblemModel` gained `field: str | None = None`,
`registry.py` sets it on all three model codes, and
`useBuilderProblems.fieldFor` prefers it over `FIELD_CODES`. C8 already
specifies the key — *"an optional `field` on the payload"* — so this is
implementing a frozen contract rather than changing one, but it touches
`bounds.py` (S2's file) and `service/builder_api.py` (the Integrator's) and
should be ratified as such. **Criterion 3 is not reachable without it**: the
code blames `llm.response_format` on one node and `llm.reasoning_effort` on the
next, and one string per code cannot say both.

**`BuilderBounds` grew two keys.** `max_prompt_chars` and `max_retries` were
already served and already enumerated in `clientMirrors.spec.ts` as "served and
not yet read"; every `PromptField` and every node-retry stepper reads them
rather than restating a constant, per R6. That list is now four rather than six.
`builderValidatorTemplate.json`'s recorded `vocabulary.bounds` was refreshed
from `_vocabulary()` at head — it was recorded on 2026-09-02 and was six bounds
behind, which made the client refuse it outright once `readBounds` required one
of the two.

### Wave A/B closers — 2026-09-04

Only row **6** moves. Everything else in the table above is untouched.

| # | Criterion | State | Shown by |
| ---: | --- | --- | --- |
| 6 | the per-node cost line changes within 500 ms of a model change | **met** | `tests/builder/test_per_node_cost.py` (7) · `frontend/tests/authoredInspector.spec.ts` → *"the per-node cost line, through the real validation loop"* (2), file total 28 |

**What was missing was never the reader.** The three tests under *"the
per-node cost line"* have proved since 2026-09-04 that a budget on
`BUILDER_BUDGET` renders the right figure and re-renders when the ref moves.
Two things were open, and they are different questions:

1. **Does the ROUTE serve `per_node`?** Plan 09 landed C5 on `BudgetEstimate`
   and `test_budget.py::PerNodeCostTests` proves the arithmetic, but
   `BuilderBudgetModel` is `extra="forbid"` and assembled field by field, so a
   breakdown dropped, renamed or re-keyed on the way out would look exactly like
   the *"not served yet"* state this row recorded — and no test would be red.
   `tests/builder/test_per_node_cost.py` asks it over the wire on
   `POST /api/builder/validate`: the key exists, it is keyed on **the author's
   own canvas node id** (`draft`, not a compiled `n2_draft`), each entry carries
   `calls` / `usd` / `model_id`, the served figures are the estimator's own
   rather than a second arithmetic, they still sum to `static_cost_usd`, and a
   library-agent graph is priced too so the line is not authored-only.

2. **Does pressing a chip get a new budget onto that ref inside 500 ms?** The
   chain has seven links — chip → commit → document → `fingerprint` watch →
   400 ms debounce → `validate` → `budget` → line — and a spec that provides a
   `ref` by hand jumps over all of them. The new describe block wires the
   **real** `useBuilderValidation` at its **real** default debounce on a **real**
   clock (no fake timers — MISSION.md trap 9 hangs a mount, and the criterion's
   number is a wall-clock one), with the server played by a double typed off
   `ValidateApi` whose per-node dollars are a function of the document's own
   model word. Measured: the line moves from `$0.12` to `$0.31` in **under
   500 ms** of the click, and exactly **two** requests are dispatched — so the
   debounce is doing its job and the second one asked about the model the author
   actually chose.

**The second test is what stops the first passing for the wrong reason.** A
client that recomputed the price beside the picker would move the line in nought
milliseconds and satisfy "within 500 ms" with an arithmetic nobody enforces the
ceiling with. Holding the validate response holds the line at the old figure
while the *model pill* has already moved — which is R6 rendered rather than
asserted in a comment.

**Two facts measured on the way, both recorded rather than smoothed over.**

- **`per_node[].model_id` carries the `openrouter/` prefix; the document's
  `llm.model` does not.** They are deliberately different strings for one model
  — one is the key `PRICES` is looked up on, the other is the registry id the
  author picked — and a reader expecting them to match would conclude the wrong
  node was priced. Asserted in both spellings.
- **A `:nitro` preset costs MORE than the dearer headline model.** Swapping the
  escalation model for the *cheaper* flash-lite `:nitro` preset takes the
  fixture's node from `$0.157` to `$0.182`, because `static_cost_usd` is the
  ENFORCED figure and applies `NITRO_PRICE_FACTOR` (1.8) to a variant that
  routes on speed. The cost line therefore reports the number the ceiling is
  enforced against, not a headline price — which is the whole reason D6 asks the
  server for it instead of computing it beside the picker.
  `test_a_nitro_variant_costs_MORE_than_the_dearer_headline` pins it.

**No source file changed to close this row** beyond one stale docblock in
`inspectors/LlmFields.vue`, which said the key was "not served yet". The reader
was right; nothing had asked the server.

Criteria **9 and 10** close; **2** closes on its unit half and its browser half
is blocked on one function in another package's file. Measured at `369a8c4`:
frontend 1475 in 74 files, `vue-tsc -b --force` exit 0, every spec below RUN
against a local `SYNTHETIC=1` backend with zero console errors tolerated.

| # | Criterion | State | Shown by |
| ---: | --- | --- | --- |
| 2 | a problem on an Expert field opens the switch and the region and focuses the control | **partial — unit met, browser BLOCKED** | `frontend/e2e/builder.spec.ts` *"surfaces a problem that lives behind the Expert switch, and walks to its node"* is green; the focusing half is a `test.fixme` beside it naming the change |
| 9 | a Playwright keyboard walk reaches every control | **met** | `frontend/e2e/builder.spec.ts` *"is fully keyboard reachable…"* — every stamped control visited, then Shift+Tab out to the dock. The run that measured the stamp counted **73**; the spec asserts a floor of 30 rather than that figure, because pinning the total would fail for every future field |
| 10 | *"configure an agent in eight pointer actions"*, ending `valid: true` | **met, and the measured number is NINE** | same file, *"configures an agent in nine pointer actions, ending valid"* |

**Criterion 10's number is nine, measured, and the five differences from D10 are
each a fact about what shipped:**

```text
 8   D10's budget
-1   the Blank card seeds an `output`, so its `palette 7` press is gone
-1   `ModelPicker` is a native <select> (departure 6), so "open + choose" is one
+1   the authored arm is reachable ONLY by converting a library agent (departure 9)
+1   the Blank card also ships WIRED, so its own `idea -> result` edge must go
+1   a dropped tool lands on a placeholder `tool_id`, so WHICH tool is its own choice
═══
 9
```

The count is asserted rather than described, so a future gesture added to this
path fails a test instead of quietly making the product worse at the thing
rubric 4 scores. It ends on the app's OWN last `POST /api/builder/validate`
answer rather than on a request the test composed — "the headline says ready" is
the claim a canvas makes about itself.

**Criterion 9 asserts that nothing is SKIPPED, not that Tab works.** Every
focusable control the rail renders is stamped, the walk records what focus
actually visited, and the two sets are compared; a test that counted Tab presses
would pass straight over a `tabindex="-1"` in the middle of the form. 73
controls with Advanced open and Expert on. The dock is reached with **Shift+Tab**
and that is a fact about the layout rather than a convenience:
`.graph-workspace` puts the problems panel in grid row 5 and the rail is a
sibling after it, so from the top of the rail the dock is behind you.

**One product fix, in `InspectorRail.focusField`.** It took the first control in
the row, and a DISABLED control silently refuses `focus()` — so the one problem
that most needs walking to, `model-lacks-capability` on `llm.reasoning_effort`,
was the one that could not be walked to, because that control is disabled
precisely BECAUSE the model cannot honour it. It now takes the first enabled
control and falls back to focusing the row itself.

**Criterion 2's browser half is blocked, and the change is three lines.**
`focusField` does everything the criterion asks and is reached from exactly ONE
call site — the credential notice at `BuilderView.vue:829`. The problems dock's
row click goes to `onEdgeSelectFromPanel` → `canvas.focusProblem`, which selects
the node and flashes the card and never mentions a field:

```ts
// BuilderView.vue
async function onEdgeSelectFromPanel(problem: BuilderProblem): Promise<void> {
  canvas.focusProblem(problem)
  const field = problems.fieldFor(problem)
  if (field) await inspectorRef.value?.focusField(field)
}
```

`problems` (line 206) and `inspectorRef` (line 370) are already in scope.
`BuilderView.vue` belongs to another package this wave, so this is a report and
a `test.fixme`, not an edit. Note what it means today: a problem anchored to a
control behind the Expert switch leaves the author looking at a form that
appears clean.
