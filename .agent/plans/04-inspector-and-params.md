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
