# Flow Builder — Definitive Implementation Spec

> **Superseded in part by the gauntlet plan set, 2026-09-02.** This document
> is still the contract for everything it rules on, but four of its rulings
> have expired and are overturned **by number** in
> [`.agent/plans/00-architecture.md`](../.agent/plans/00-architecture.md) D2:
> R4 with cut-list items 1–2 (a run mode inside the builder now exists),
> cut-list item 14 (light mode is required), cut-list item 9 (narrowed: the
> generated-code preview is read-only), and the rule that `BuilderView`
> receives no `user` prop. Everything else — R1–R3, R5–R13, R15, cut-list
> items 3–8, 10–13, 15–17 — stands unchanged. Where this file and a plan file
> disagree, the plan file's D2 list is the authority on which is current;
> report the disagreement against a ruling number rather than improvising
> around either. Status per feature is tracked in [`PLANS.md`](../PLANS.md).

**Target:** `D:/MultiAgentSystem/frontend`
**Status:** contract. Every decision below is closed. Do not re-litigate; if reality contradicts this document, report it, do not improvise.

---

## 0. Rulings (where the judges disagreed)

| # | Question | Ruling | Why (one line) |
|---|---|---|---|
| R1 | Which proposal is the spine? | **Forge.** Typed contract + three-tier enforcement boundary + snapshot undo. | 2 of 3 judges; it is the only one whose novel machinery is small enough to actually ship. |
| R2 | Own the pointer layer (Drydock) or ride Vue Flow? | **Ride Vue Flow.** `nodes-draggable`, `elements-selectable`, marquee, pan, zoom, `snap-to-grid` are the library's job. | Reimplementing the library's core competency across a 7-state machine is the single largest ship risk in the set. |
| R3 | Command algebra with `invert()` or snapshot ring? | **Snapshot ring, 200 deep, with `coalesceKey`.** | Document is capped at 256 KiB and frozen server-side; an algebra buys nothing and invites inversion bugs. |
| R4 | Is Run mode in scope? | **No.** No Launch control is rendered at all. | No `builder_runner` is passed anywhere; a disabled button is the stub the brief forbids. |
| R5 | Extract `node-card.css` out of the shipping `WorkflowNode.vue`? | **Yes — as WP-A, its own commit, gated on a committed Playwright screenshot baseline taken BEFORE the move.** | The payoff (build card === run card, byte-identical) is the "one product" screenshot; the risk is real and the gate neutralises it. |
| R6 | Does the client enforce `max_fanout_width` at the mouse? | **No.** Client enforces *parse* refusals only; every `bounds.py` count is server-owned and advisory-only on the client. | A client-side bound is a second opinion that silently disagrees with the compiler after any server change. |
| R7 | Client mirror of `_back_edges_with_index`? | **Yes, for edge STYLING only, pinned by a Python-generated fixture whose freshness is asserted by a Python test in CI.** | Cycles must be legible; a mirror that can rot un-noticed is how this repo's counts went wrong five times. |
| R8 | `GateConfig.expiry_seconds` control? | **Cut.** Field round-trips at its stored value; no control. | It is authored, range-validated, and read by nothing in `src/`. A control for it is a lie. |
| R9 | `GateConfig.editable_fields` control? | **Ship it,** with one inline sentence: it seeds the gate payload; the service does not currently render the rest read-only. | The compiler *does* seed those keys; the field is half-honoured, not dead. Named in Backend Gaps. |
| R10 | `crew_id: synthesis` / `report`? | **Marked unavailable in the picker with the reason, AND filed as a backend fix (`library_problems` must error on a non-zero-arg factory).** | Client-side hiding alone is exactly the quietly-divergent double this repo warns about. |
| R11 | Minimap | **Hand-rolled, problem-coloured. No `@vue-flow/minimap` dependency.** | Stock chrome in a product whose argument is that it is not stock; ChatDev ships that exact package unimported. |
| R12 | Snap grid | **`[20, 20]`, matching `<Background :gap="20">`.** Alt disables. `Math.round` on every write regardless. | Nodes land on visible dots. Rounding is a *schema requirement* — `position.x` is declared `int`; `120.5` is a hard 422. |
| R13 | Router | **60-line hash router.** No `vue-router`. | Hono serves the SPA; history mode needs a catch-all rewrite in two places. |
| R14 | Idea-validator template | **Ships, agent-only, with its `caveat` rendered verbatim on the gallery card.** | It is topology, not judgement; saying so is the difference between a template and a booby trap. |
| R15 | Modal policy | **Zero modals in the editing path.** Two dialogs total: `PublishDialog`, `ConflictDialog`. `ShortcutSheet` is an overlay. | ChatDev's defining failure is a stack of overlays hiding the graph you are editing. |

---

## 1. Architecture

### 1.1 The one-way loop

```
                  ┌──────────────────────────────────────────────┐
                  │  useBuilderDocument                          │
   user gesture   │    doc: Ref<BuilderDocument>   (immutable)   │
  ───────────────▶│    history: Snapshot[200]                    │
   (canvas /      │    commit(label, next, coalesceKey?)  ◀─ ONLY WRITE PATH
    inspector /   └──────┬───────────────────────┬───────────────┘
    hotkey)              │                       │
                         │ fingerprint()         │ toWire()
                         ▼                       ▼
             ┌───────────────────────┐   ┌───────────────────────┐
             │ useBuilderValidation  │   │ useBuilderPersistence │
             │  400ms debounce       │   │  Ctrl+S + 2.5s idle   │
             │  AbortController      │   │  expected_version CAS │
             └──────────┬────────────┘   └──────────┬────────────┘
                        │ POST /validate            │ PUT /workflows/{id}
                        ▼                           ▼
             ┌───────────────────────┐        409 ─▶ ConflictDialog
             │ useBuilderProblems    │
             │  byNode / byEdge /    │──▶ node rims, FieldProblem,
             │  documentProblems     │    ProblemsPanel, BudgetMeter
             └───────────────────────┘
```

**Invariants. These are not guidelines.**

1. **`commit()` is the only function that assigns to `doc.value`.** Nothing else, anywhere, mutates the document. Not the canvas, not an inspector, not Vue Flow.
2. **The document is replaced, never mutated.** `commit` receives a *new* object. Deep-freeze it in dev (`import.meta.env.DEV`).
3. **The client never COMPUTES a Problem.** It renders the ones the server returned. The only client-side legality is the parse-refusal table in §6.1.
4. **Vue Flow's node/edge arrays are `computed` projections of `doc`.** Position changes flow back through `@node-drag-stop` → one `commit`. Never through `@nodes-change`.
5. **`expected_version` comes only from a server response.** Never from `doc.version` — the server overwrites both `id` and `version` on every write.

### 1.2 State ownership

| Concern | Owner | Persisted? |
|---|---|---|
| The document | `useBuilderDocument.doc` | server (PUT) + `localStorage['builder-draft:<id>']` |
| Undo/redo | `useBuilderDocument.history` / `future` | no — session only |
| Save state, version, head version | `useBuilderPersistence` | server |
| Selection | `useBuilderCanvas.selection` | no |
| Problems / budget / phase | `useBuilderValidation` + `useBuilderProblems` | no |
| Vocabulary + bounds | `builderVocabulary` module singleton | `sessionStorage` |
| Clipboard | `useBuilderClipboard` (ref + `navigator.clipboard`) | no |
| Route | `useWorkspaceRoute` (hash) | URL |

### 1.3 Shell

`App.vue` keeps its three-phase auth gate verbatim, then switches on `useWorkspaceRoute()`:

- `#/` → `StudioView.vue` (the current console, moved out of `App.vue` unchanged)
- `#/build` → `BuilderView.vue` with `TemplateGallery` as the empty state
- `#/build/:documentId` → `BuilderView.vue` with a loaded document

`StudioView` and `BuilderView` each mount their own `<VueFlow>` with a **distinct `id`** (`'studio-flow'` / `'builder-flow'`), because `useVueFlow` keys per-instance state by id and viewport/selection would otherwise leak between views.

---

## 2. File manifest & work packages

Sizes are targets, not budgets. **Dependencies are on the *contract* of the named file, not its implementation** — WP-B..WP-F may begin against WP-0's exported signatures the moment those files exist as typed stubs with real signatures (WP-0 lands first and fast).

### WP-A — CSS extraction (1 agent, lands FIRST, standalone commit)

Blocking gate: capture and commit a Playwright screenshot baseline of the run canvas (`e2e/visual/run-canvas.spec.ts`, idle + running + gate-waiting states) **before** touching a line. The commit is rejected if the after-screenshots differ.

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `src/assets/styles/node-card.css` | The node card's visual shell, cut **verbatim** from `WorkflowNode.vue`'s scoped block: the `background-image: linear-gradient(var(--bg-node),var(--bg-node)), var(--node-gradient)` + `background-origin:border-box` + `background-clip:padding-box,border-box` + `border:2px solid transparent` double-clip, `.node-icon`, `.node-eyebrow-row`, `.node-copy`, `.node-state`, `.node-meta`, `.node-usage`, the crew SVG rules, every `@keyframes` and the reduced-motion block. Adds nothing. | 250 | — |
| `src/components/WorkflowNode.vue` | **MODIFY.** Delete the extracted rules. Template and script untouched. | −200 | node-card.css |
| `src/studio.css` | **MODIFY.** `@import './assets/styles/node-card.css';` after tokens, with a comment stating why it is global (two components in two views must be guaranteed identical; a scoped selector cannot span them — the same reasoning `studio.css` already records for `.markdown-body`). | +4 | — |
| `e2e/visual/run-canvas.spec.ts` | The baseline gate. Retained afterwards. | 90 | — |

### WP-0 — Foundation (1 agent, everyone blocks on it)

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `src/types/builder.ts` | The wire mirror, literally as written in §3. Branded `NodeId`/`EdgeId`/`DocumentId`, discriminated `BuilderNode` on `kind`, all seven configs, problems, budget, vocabulary, document model, publish. `PROBLEM_CODES` const tuple. `FIELD_CODES`. | 340 | — |
| `src/data/builderVocabulary.ts` | Fetch `GET /api/builder/vocabulary` once per session (no auth — runs before the auth gate resolves). `Math.trunc` every `bounds` value (they arrive as JSON floats: `24.0`). Module singleton + `sessionStorage` (try/catch). On failure sets `vocabularyUnavailable` and the palette disables with a stated reason — **no hardcoded fallback enum**, ever. | 130 | types |
| `src/data/nodeKinds.ts` | **One record per `NodeKind`, the single source of truth for kind.** `{ icon, className, blurb, paletteOrder, defaultLabel, defaultConfig, outPorts(node), acceptsIncoming, accent }`. `outPorts` mirrors `_OUT_PORTS_BY_KIND` exactly with the source file named in a comment: `['out']`; gate → `['approve','revise']` in that canvas order; router → `config.branches.map(b => b.label)`; output → `[]`. The palette, the card, the port footer, the hotkeys and the PortMenu all read this — a drawn port cannot disagree with an accepted port. | 230 | types |
| `src/data/builderDefaults.ts` | `newNode(kind, position, existingIds)` → a schema-valid node. Ids `agent_1`/`gate_2` (first free suffix), labels `Agent 1`. Defaults mirror the Python exactly: `max_iter 2`, `guardrail_max_retries 2`, `max_chars 2000`, `required true`, `max_turns 1`, `expiry_seconds 1800`, `body_key = vocabulary.result_body_keys[0]`. A new `router` is born with two branches (one comparison + one `otherwise`) so it satisfies `router-branch-count` and `router-otherwise` on arrival. `mintNodeId(label, taken)` slugifies against `^[a-z][a-z0-9_]{0,39}$`. | 200 | types, nodeKinds, vocabulary |
| `src/utils/builderSerialize.ts` | `toWire(doc)` (aliases `documentSchema`→`schema`, sends `budget: null`), `forValidate(doc)` (**deletes `id`**, **forces `version` to a number**), `fingerprint(doc)` (stable stringify with `position` OMITTED), `wireBytes(doc)` via `TextEncoder`, `roundPositions(doc)`. | 100 | types |
| `src/utils/builderGraph.ts` | Pure, tested graph helpers. `ancestorsOf(doc, id)`, `descendantsOf`, `topoOrder(doc)`, `renameCascade(doc, from, to)` (rewrites `edges[].source/target`, `joins` keys, `input_field`, and every `${state.out__<from>}` inside `prompt_inputs` / `transform.args` / `output.source` / `router.branches[].key` — returns ONE new document), `remapIds(subgraph, mint)` for paste, `backEdges(doc)` (line-for-line mirror of `bounds._back_edges_with_index`, styling-only, see R7). | 220 | types |
| `src/services/builderApi.ts` | `class BuilderApi` + `export const builderApi` + `export type BuilderApiLike = Pick<BuilderApi, …>`. Methods: `vocabulary, list, create, get, save, remove, validate, publish`. | 340 | types, serialize, httpCore |
| `src/services/httpCore.ts` | **MODIFY-BY-EXTRACT** from `studioApi.ts`: `authedFetch(path, init?, allowRetry?, forceToken?, presetToken?)` (one 401 retry with a forced fresh mint), `fetchJson`, base-URL resolution. `studioApi.ts` imports it instead of holding it. | 140 | — |
| `src/services/studioApi.ts` | **MODIFY.** Import from `httpCore`. No behaviour change. | −80 | httpCore |
| `src/composables/useWorkspaceRoute.ts` | Hash router: `#/`, `#/build`, `#/build/:documentId`. `route: Ref<Route>` + `navigate(r)` on `hashchange`. | 60 | — |

**`builderApi.ts` — four contract behaviours that live here and nowhere else:**

1. `create` reads **`body.id`**, never the `Location` header. `Location` is absent from `CORS_EXPOSE_HEADERS`, so cross-origin it is unreadable.
2. `validate` sends `forValidate(doc)` — `id` omitted, `version` a number. A non-numeric version reaches a bare `int()` and returns **500**; a malformed `id` returns 422.
3. `publish`'s 422 is the **one** error on this router whose `detail` is an **object** `{message, problems[]}`. `readPublishRefusal` unwraps it; everything else goes through `readErrorDetail` from `data/serverLimits.ts`.
4. `save` requires `expectedVersion` (`int ≥ 0`); on 409 it throws a typed `BuilderConflictError` carrying the stored version parsed out of the server's sentence **and** the raw detail.

### WP-B — Document, history, persistence (1 agent)

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `src/composables/useBuilderDocument.ts` | `doc`, `commit(label, next, coalesceKey?)`, `undo/redo/canUndo/canRedo/undoLabel/redoLabel`, `dirty`. 200-entry snapshot ring; `coalesceKey` merges consecutive commits under the same key inside **600ms**; `sealHistory()` on blur, mode exit and save. Typed mutators: `addNode, deleteSelection, moveNodes, renameNode, setLabel, patchConfig, addEdge, deleteEdges, setEdgePort, retargetEdge, setJoin, setInputField, setName, applyTemplate, pasteSubgraph`. `deleteSelection` cascades to incident edges **and** orphaned `joins` keys **in one command**. | 380 | types, graph, defaults |
| `src/composables/useBuilderPersistence.ts` | `saveState: 'clean'|'dirty'|'saving'|'conflict'|'offline'`, `version`, `headVersion`, `status`, `publishedVersion`. Ctrl+S + idle autosave **2.5s** after the last commit (only when the doc has an id and no save is in flight; frozen entirely while `saveState === 'conflict'`). `beforeunload` guard while dirty. localStorage draft `builder-draft:<id>` written on every commit through try/catch; dropped with a visible chip if it would exceed `max_document_bytes`; restore bar offered on load **only when the draft's baseVersion still equals server head**, otherwise discarded — never silently merged. | 320 | builderApi, document, serialize |
| `src/composables/useBuilderClipboard.ts` | Copy/cut/paste/duplicate. Envelope `{__builder:'builder.flow/v1', nodes, edges, joins, bbox}` to `navigator.clipboard.writeText`, in-memory ref fallback (a denied clipboard reports a one-line notice, never nothing). Paste re-mints every id **and rewrites `${state.out__<oldId>}` in `prompt_inputs` values, `transform.args` values, `output.source`, and `router.branches[].key`**. Only edges with BOTH endpoints copied survive. One commit labelled `Paste 4 nodes`. | 220 | document, graph, defaults |
| `src/components/builder/SaveChip.vue` | `role="status"`. `saved · v7` / `saving…` / `unsaved changes · ⌘S` / `conflict — head is v8` / `offline — kept in this browser`. Never silent. | 120 | persistence |
| `src/components/builder/ConflictDialog.vue` | The 409 resolution. **Never auto-reloads.** Re-GETs head, shows a three-column diff (added / removed / changed, with per-field rows for a changed config). Actions: **Discard mine** (load head), **Keep mine** (adopt head's version as `expected_version`, re-PUT), **Open head in a new tab**. "Keep mine" pushes the incoming head onto the undo stack first so one Ctrl+Z is a recovery. | 220 | persistence, builderApi |

### WP-C — Validation, problems, budget (1 agent)

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `src/composables/useBuilderValidation.ts` | Watches `fingerprint(doc)` (position-free) with a **400ms** debounce; `AbortController` cancels in flight; every response stamped with the fingerprint it answered, stale responses dropped. `phase: 'idle'|'checking'|'stale'|'fresh'|'unreachable'`. `stale` is a **rendered** state. Exposes `problems`, `budget`, `valid`. | 200 | builderApi, serialize |
| `src/composables/useBuilderProblems.ts` | Indexes into `problemsByNode`, `problemsByEdge`, `documentProblems`, `worstByNode`, `errorCount`, `warningCount`, `problemsForField(nodeId, field)` via `FIELD_CODES`. Codes anchoring both a node and an edge (`edge-unknown-port`, `edge-target-refuses-incoming`, `back-edge-not-router`) are entered in **both** maps. | 130 | types, validation |
| `src/components/builder/ProblemsPanel.vue` | Collapsible dock at the canvas bottom. `role="log" aria-live="polite"`. Errors then warnings, **all at once**. Row = severity dot + mono `code` chip + the server's sentence verbatim + the anchor's label. Click → select + `fitView({nodes:[id], duration:260})` + focus the mapped inspector field + a finite `problem-anchor 1.1s ease-out 3` flash. Header: `3 errors · 1 warning` / `Ready to publish` / dimmed `checking…` when `phase === 'stale'`. `F8` / `Shift+F8` walk. Publish-refusal problems merge in tagged `from publish`. | 220 | problems, canvas |
| `src/components/builder/BudgetMeter.vue` | Both dollar figures: `floor_cost_usd` large as the honest comparable, `static_cost_usd` beside it labelled *enforced (nitro margin)*, `ceiling $10.00`. Track fills to `static_cost_usd × 1.25 / ceiling_usd` so it reaches full exactly where `over_ceiling` flips; amber at 80%, `--err-*` at 100%. **Four headroom PIP rows** (billable /8, escalation /5, cycles /2, nodes /24) as filled/empty pips. `unpriced_models` non-empty → amber naming the slug. **`ceiling_usd <= 0` hides the bar entirely** and reads *no ceiling configured*. | 200 | validation, vocabulary |
| `src/components/builder/fields/FieldProblem.vue` | Wraps any control; takes `nodeId` + `field`; renders the server's message **verbatim** beneath it with `aria-invalid` and `aria-describedby`. `--err-*` / `--warn-*`. | 110 | problems |

### WP-D — Canvas (1 agent, the largest package)

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `src/composables/useBuilderCanvas.ts` | Projects `doc` → Vue Flow nodes/edges. Owns `selection`, `isValidConnection` (§6.1 only), `onConnectStart` (computes the ancestor set once for the loop advisory; builds an O(1) `Set` of `source|port|target` triples for the duplicate check), palette drop (`screenToFlowCoordinate` → `Math.round` to 20), `@node-drag-stop` → one `moveNodes` commit, `focusNode(id)`, `focusProblem(p)`. | 320 | document, nodeKinds, graph |
| `src/composables/useBuilderHotkeys.ts` | One `window` keydown listener installed by `BuilderView`, removed on unmount. Ignores every binding while focus is in an input/textarea/`[contenteditable]` **except** `Escape` and `Ctrl/Cmd+S`. **Exports the binding table as data**, which `ShortcutSheet` renders — a binding cannot be documented-and-unbound or bound-and-undocumented. | 240 | canvas, document, clipboard |
| `src/components/builder/BuilderCanvas.vue` | The `<VueFlow id="builder-flow">` host. `nodes-draggable`, `elements-selectable`, `nodes-connectable`, `:snap-to-grid="true" :snap-grid="[20,20]"`, `:connection-mode="ConnectionMode.Strict"`, `:is-valid-connection`, `:delete-key-code="null"` (we own Delete so it is undoable), `:default-viewport` + `:fit-view-on-init`. **One node type `builder`, one edge type `builder`**, registered by named slot. `<Background :gap="20" :size="1" color="#777777">`, `<Controls position="bottom-left" :show-interactive="false">`, `<BuilderMinimap>`, `<PortMenu>`. `role="application"`, `tabindex="0"`, `aria-activedescendant`. `provide()`s `hoveredNodeId` + `selectedIds`. | 300 | canvas, node, edge, minimap, portmenu |
| `src/components/builder/BuilderNode.vue` | The design-time card. §5.2. | 320 | nodeKinds, problems |
| `src/components/builder/BuilderEdge.vue` | `getBezierPath` + `BaseEdge` + `EdgeLabelRenderer`. §5.4. | 200 | graph, problems |
| `src/components/builder/NodePalette.vue` | Seven kind tiles from `vocabulary.node_kinds` (server order, **not** sorted). Each tile is a miniature of the card it produces — icon in its own gradient-bordered 34px well, label, blurb. `draggable`, plus click-to-place at viewport centre, plus keys `1`–`7`. Billable/escalation tiles show their count against the bound and disable AT the ceiling with the bound's name in the tooltip. Below: the library list from `GET /api/builder/workflows`. | 200 | nodeKinds, vocabulary, validation |
| `src/components/builder/PortMenu.vue` | Drag from a port to empty canvas → typeahead node creator anchored at the drop point, over `vocabulary` (kinds, agent ids, crew ids, transform ops). Arrows move, Enter creates, Escape aborts with zero commits. Creation is **ONE commit** containing the node and the edge, labelled `Add market analyst` — one undo removes both. Also reachable keyboard-only: `E` on a focused node, then Enter over empty space. | 240 | vocabulary, document, nodeKinds |
| `src/components/builder/BuilderMinimap.vue` | Hand-rolled. Dots coloured by validation state — red = error, amber = warning, cyan = selected, otherwise the kind accent. Click to centre; drag the viewport rect to pan. Bottom-right, collapsible, remembered in `localStorage`. | 150 | problems, canvas |
| `src/assets/styles/builder.css` | Global builder chrome (the shell has no scoped block). Port geometry + the connect-drag affordance state machine, edge-field dimming, palette/inspector/bar surfaces, `is-loop-target` / `is-loop-illegal`, the builder grid. **Zero new custom properties** — washes are `color-mix(in srgb, var(--accent-cyan) 14%, transparent)`, the technique `WorkflowNode` already uses. Ships its own `prefers-reduced-motion` block naming what survives. | 360 | node-card.css |

### WP-E — Inspector (1 agent)

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `src/components/builder/InspectorRail.vue` | Docked, never a modal. Dispatches through `const INSPECTORS: Record<NodeKind, Component>` — an unhandled kind is a **compile error**, not a blank pane. Four states: nothing selected → `GraphSettings`; one node → the kind form; one edge → source/target/port pickers + the target's join toggle; multi-select → common fields with a *Mixed* indicator, one commit applied to all. The node's unplaceable problems are pinned at the top of every node form. | 230 | problems, document |
| `src/components/builder/inspectors/InputForm.vue` | `field` (NodeIdField), `label` (nullable, 40), `max_chars` (1..`bounds.max_input_chars`), `required`. Badge + one-click *make this the run input* when it is not the document's `input_field` — the fix for `input-field-undeclared`. | 150 | fields |
| `src/components/builder/inspectors/BillableForm.vue` | **Agent AND crew in one component** — they extend the same `_BillableConfig` in Python, so one form is the truthful modelling. `tier` segmented (escalation option carries an amber dot + live `n of 5 used`), `max_iter` 1..8, `guardrail_max_retries` 0..2, `prompt_inputs` inline key→`ScalarInput` rows. Agent-only: `agent_id` select + `tools` chip multi-select (**not** behind any disclosure). Crew-only: `crew_id` select with `synthesis`/`report` disabled and the reason inline; plus the note that `max_iter`/`guardrail_max_retries` are accepted and ignored at runtime while `tier` is still what you are priced on. **No `tools` control for crew** — the key is forbidden. | 260 | fields, vocabulary |
| `src/components/builder/inspectors/GateForm.vue` | `message` (2000, counter, amber in the last 100 — reuse `serverLimits.ts` idiom), `editable_fields` (`TokenListInput`, dupes refused in the widget, one honest sentence per R9), `max_turns` stepper showing the exact `cycle-iterations` sentence the moment it exceeds 3. **No `expiry_seconds` control** (R8). | 170 | fields |
| `src/components/builder/inspectors/RouterForm.vue` + `RouterBranchEditor.vue` | Inline, reorderable branch rows: `label` (NodeIdField — the label IS the out-port name), `op`, `key` (`StateRefInput`), `value` (`ScalarInput`). Cross-field rules enforced **in the widget**: `otherwise` clears and disables `key`/`value`; any other op requires `key`. Exactly-one-`otherwise` is structural — the option vanishes from the select once taken. Adding a branch grows the port on the card on the same tick. Deleting a branch that has an edge deletes the edge **in the same commit**, with a toast naming it. Live 2..4 count. | 300 | fields, document |
| `src/components/builder/inspectors/TransformForm.vue` + `TransformArgsEditor.vue` | `op` select; the args editor **changes shape per op** because the runtime reads different keys: `pick` → `source`+`key`; `default` → `value`+`default` (with the note that only `null`/`""` count as absent, so a legitimate `0` survives); `format` → `template` + a named-args table with a **two-way cross-check** (an arg with no `{name}`, and a `{name}` with no arg, both flagged) and the note that substitution is name-restricted and **not** `str.format`; `merge`/`to_json` → free named-args table; `join_text` → `separator` + ordered args, with the honest caveat that it joins the **args mapping's values**, not a list's elements. | 300 | fields |
| `src/components/builder/inspectors/OutputForm.vue` | `body_key` select over `vocabulary.result_body_keys` (one option today; a select anyway) with the server's own explanation as help text. `source` = `StateRefInput` defaulting to the sole upstream node's ref. | 130 | fields |
| `src/components/builder/inspectors/GraphSettings.vue` | `name` (80), `input_field` (a **picker over the declared input nodes' `config.field` values**, never free text), and the `joins` list — every node with ≥2 inbound edges gets an AND/OR toggle. AND writes `joins[id]='all'`; OR deletes the key. One line of consequence: AND waits for every branch, OR fires on the first, and two router branches converging under AND deadlock. | 160 | document |
| `src/components/builder/fields/NodeIdField.vue` | Per-keystroke `^[a-z][a-z0-9_]{0,39}$`, rejects a taken id, and on commit runs `renameCascade` as ONE commit. States *this rename updates N references* before you commit. | 150 | graph |
| `src/components/builder/fields/StateRefInput.vue` | A combobox over the **resolvable** keys only — `input_field` plus `out__<id>` per node, each shown with its node's label. Typing `${state.` opens it. Refuses a nested reference **in the field** with the server's own sentence (a 422 at parse time; it must never be sent). Explicit literal mode for plain strings. Warns (does not refuse) when the referenced node is not actually upstream — legal to the schema, always empty at runtime. | 190 | document, graph |
| `src/components/builder/fields/ScalarInput.vue` | `JsonScalar` with an explicit **string / number / boolean / null** toggle. Arrays and objects are not offered. Delegates to `StateRefInput` when a string contains `${`. | 160 | StateRefInput |
| `src/components/builder/fields/TokenListInput.vue` | Chip entry: type, Enter, chip; Backspace on empty removes the last; duplicates refused with the server's message. | 130 | — |

### WP-F — Shell, templates, publish (1 agent)

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `src/App.vue` | **MODIFY.** Auth gate unchanged; three-way switch on `useWorkspaceRoute()`. Body moves out. | 70 | route |
| `src/views/StudioView.vue` | **MODIFY-BY-MOVE.** The current `App.vue` template + script below the auth gate, verbatim. Gains one header control: a `Build` / `Run` segmented pair reusing `.segmented` + `aria-pressed`. | 320 | — |
| `src/components/builder/BuilderView.vue` | The builder shell. Reuses `.studio-shell` / `.studio-main` grid: `grid-template-columns: var(--palette-width) minmax(0,1fr) var(--inspector-width)`, `grid-template-rows: minmax(0,1fr)`, **`min-height: 0` on all three children** (the documented `studio.css:132-150` lesson). Installs `useBuilderHotkeys`; `provide()`s document/selection/validation. Hosts `DocumentBar`, `NodePalette`, `BuilderCanvas`, `BudgetMeter`, `ProblemsPanel`, `InspectorRail`, `TemplateGallery`, `ConflictDialog`, `PublishDialog`, `ShortcutSheet`. **The only place an inspector's emitted patch becomes a `commit`.** | 380 | all |
| `src/components/builder/DocumentBar.vue` | Canvas top strip in the 64px row `.graph-workspace` already reserves. Inline-editable name (80), `SaveChip`, undo/redo icon buttons with the last action's label in the tooltip, Publish/Republish. `Undid: delete node` for 2s after an undo. A mint dot + `v4 is live` when the published version differs from the open one. Renders the `status: 'published'` / `published: false` divergence honestly when they disagree. | 220 | persistence, document |
| `src/components/builder/TemplateGallery.vue` | The empty state and the screenshot. Four cards on the dot grid, each with a `GraphThumbnail` spine, title, blurb, node/billable counts, estimated cost. **The validator card renders its `caveat` verbatim.** Also the open-existing entry point from `GET /api/builder/workflows`, newest-first with status pills. Delete is an in-app typed confirmation, never `window.confirm`. | 230 | templates, thumbnail, builderApi |
| `src/components/builder/GraphThumbnail.vue` | Static SVG of a document's topology — 6px rounded rects tinted by kind, 1px edges, laid out from the document's own `position` normalised into 240×90. **Derived from the document**, so a preview cannot drift from the graph it advertises. | 90 | nodeKinds |
| `src/data/builderTemplates.ts` | `BLANK`, `MINIMAL_GATED_AGENT` (input → gate → agent → output — the smallest anonymously-launchable shape), `FAN_OUT_JOIN`, `IDEA_VALIDATOR`. Each `{ id, title, blurb, caveat?, document }`. | 130 | validatorTemplate |
| `src/data/templates/ideaValidator.ts` | The evaluator as a literal `BuilderDocument`: 17 nodes, 22 edges, `joins: {score:'all'}`, two back edges closed through **router** nodes (bounds refuses a back edge from a non-routing kind), `input_field: 'idea'`. **Agent nodes only** — no `crew_id`. Carries the caveat string. | 300 | types |
| `src/components/builder/PublishDialog.vue` | The only dialog in the publish path, justified: publish re-registers a runnable workflow in five maps and changes what `POST /runs` accepts. Precondition checklist, each met or naming its blocker. On success renders the `BuilderPublish` body as the contract the author now owns: `input_field`, `reserved_input_keys` (keys `POST /runs` will now **refuse**), `static_cost_usd`, `graph_version`, and `gated_before_spend` — when false, the full 403 sentence plus a jump to the first billable node on an ungated path. A 422's object detail merges into `ProblemsPanel`. | 250 | validation, persistence |
| `src/components/builder/ShortcutSheet.vue` | `?` overlay, `role="dialog"`, focus-trapped, Escape closes. Rendered **from `useBuilderHotkeys`'s exported binding table**. | 130 | hotkeys |
| `src/studio.css` | **MODIFY.** `@import './assets/styles/builder.css';` + the two `--palette-width` / `--inspector-width` values. | +6 | builder.css |

### WP-G — Test infrastructure & E2E (1 agent, starts with WP-0)

| File | Responsibility | ~Lines | Deps |
|---|---|---|---|
| `tests/helpers.ts` | **MODIFY.** Add `class FakeBuilderApi implements BuilderApiLike` — compiler-forced to match its subject — plus `emptyDocument()`, `docWithProblems()`, `vocabularyFixture()`. | +180 | builderApi |
| `scripts/emit_builder_fixtures.py` | Emits `frontend/tests/fixtures/builderBackEdges.json` (from the real `bounds.back_edge_indices` over order-permuted documents) and `builderProblemCodes.json` (one instance of all 27 codes). | 160 | — |
| `tests/builder/test_client_fixtures.py` (Python) | **Regenerates and byte-compares** both fixtures. CI fails when the client mirror rots. This is the anti-drift gate (R7). | 90 | script |
| `e2e/builder.spec.ts` | Playwright, chromium, `SYNTHETIC=1` backend, **zero console errors tolerated**. §7.4. | 320 | all |

Per-package specs are listed in §7 and are owned by the package's agent.

**Collision map.** Only three files are touched by more than one package: `src/studio.css` (WP-A adds one import, WP-D one, WP-F one — sequence A → D → F), `tests/helpers.ts` (WP-G only; other packages import from it), and `src/services/studioApi.ts` (WP-0 only). Everything else is single-owner.

---

## 3. The type layer

`src/types/builder.ts`, written literally. `GraphDescriptor` is imported from `types/studio.ts` — the builder's `graph` field is byte-identical to what `GET /api/workflows/{id}/graph` returns.

```ts
import type { GraphDescriptor } from './studio'

/* ─── branded ids ──────────────────────────────────────────────────────────
 * A label can never be assigned where an id belongs — that is a compile error,
 * not a 422. Mint through the guards; never cast. */
declare const NODE_ID: unique symbol
declare const EDGE_ID: unique symbol
declare const DOC_ID: unique symbol

export type NodeId = string & { readonly [NODE_ID]: true }
export type EdgeId = string & { readonly [EDGE_ID]: true }
export type DocumentId = string & { readonly [DOC_ID]: true }

/** config.py:BUILDER_ID_PATTERN — first char a-z, then 0..39 of [a-z0-9_]. */
export const NODE_ID_PATTERN = /^[a-z][a-z0-9_]{0,39}$/
/** config.py:BUILDER_DOCUMENT_ID_PATTERN — server-assigned, never client-chosen. */
export const DOCUMENT_ID_PATTERN = /^ug_[0-9a-f]{8}$/
/** config.py:BUILDER_STATE_REF_PATTERN — ONE flat lowercase key. No nesting. */
export const STATE_REF_PATTERN = /^\$\{state\.[a-z0-9_]{1,64}\}$/
/** config.py:BUILDER_STATE_OUTPUT_PREFIX */
export const STATE_OUTPUT_PREFIX = 'out__'
/** config.py:BUILDER_DOCUMENT_SCHEMA — the only legal value of `schema`. */
export const BUILDER_SCHEMA_ID = 'builder.flow/v1'

export const isNodeId = (v: string): v is NodeId => NODE_ID_PATTERN.test(v)
export const nodeId = (v: string): NodeId => {
  if (!isNodeId(v)) throw new Error(`not a NodeId: ${v}`)
  return v
}
export const edgeId = (v: string): EdgeId => {
  if (!NODE_ID_PATTERN.test(v)) throw new Error(`not an EdgeId: ${v}`)
  return v as EdgeId
}
export const documentId = (v: string): DocumentId => {
  if (!DOCUMENT_ID_PATTERN.test(v)) throw new Error(`not a DocumentId: ${v}`)
  return v as DocumentId
}

/* ─── scalars ─────────────────────────────────────────────────────────────
 * Arrays and objects are REFUSED by the server in prompt_inputs values,
 * transform.args values, output.source and RouterBranch.value. */
export type JsonScalar = string | number | boolean | null

export type NodeKind =
  | 'input' | 'agent' | 'crew' | 'gate' | 'router' | 'transform' | 'output'
export type Tier = 'cheap' | 'escalation'
export type Severity = 'error' | 'warning'
export type DocumentStatus = 'draft' | 'published'

/** _OUT_PORTS_BY_KIND (document.py:388-395). `in` is the ONLY target port. */
export type TargetPort = 'in'
export type GatePort = 'approve' | 'revise'

/* ─── per-kind configs ────────────────────────────────────────────────── */

export interface InputConfig {
  field: NodeId                 // REQUIRED. The `inputs` key on POST /runs.
  label: string | null          // 1..40 or null. The form prompt, distinct
                                // from the node's own canvas label.
  max_chars: number             // int, 1..2000. default 2000
  required: boolean             // default true
}

export interface AgentConfig {
  tier: Tier                    // REQUIRED, no default
  max_iter: number              // int, 1..8. default 2
  guardrail_max_retries: number // int, 0..2. default 2
  prompt_inputs: Record<string, JsonScalar>   // default {}
  agent_id: NodeId              // REQUIRED. One of vocabulary.agent_ids
  tools: string[]               // default []. Each in vocabulary.research_tools.
                                // Duplicates rejected server-side.
}

export interface CrewConfig {
  tier: Tier                    // REQUIRED. A DECLARATION, not derived — it is
                                // what MAX_ESCALATION_NODES counts and what the
                                // budget prices, even though run_crew ignores it.
  max_iter: number              // accepted, IGNORED at runtime
  guardrail_max_retries: number // accepted, IGNORED at runtime
  prompt_inputs: Record<string, JsonScalar>
  crew_id: NodeId               // REQUIRED. One of vocabulary.crew_ids
  // NO `tools` key. extra="forbid" — sending one is a 422.
}

export interface GateConfig {
  message: string               // 1..2000. REQUIRED.
  editable_fields: NodeId[]     // default []. Duplicates rejected.
  max_turns: number             // int >= 0, default 1. NO schema upper bound;
                                // > 3 is a CYCLE_ITERATIONS problem, not a 422.
  expiry_seconds: number        // int, 1..1800, default 1800.
                                // Round-trips only — NO UI control (R8).
}

export type RouterOp =
  | 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'otherwise'

export interface RouterBranch {
  label: NodeId                 // REQUIRED. This IS the out-port name.
  op: RouterOp                  // REQUIRED
  key: NodeId | null            // REQUIRED (non-null) for every op except
                                // 'otherwise'; MUST be null when 'otherwise'
  value: JsonScalar             // MUST be null when op === 'otherwise'
}

export interface RouterConfig {
  branches: RouterBranch[]      // 2..4 enforced as a PROBLEM, not a 422
}

export type TransformOp =
  | 'pick' | 'merge' | 'join_text' | 'to_json' | 'default' | 'format'

export interface TransformConfig {
  op: TransformOp                          // REQUIRED
  args: Record<string, JsonScalar>         // default {}. Arg NAMES are not
                                           // validated per op by the schema.
}

export interface OutputConfig {
  body_key: string              // REQUIRED. In vocabulary.result_body_keys.
                                // Today the only legal value is 'markdown_body'.
  source: JsonScalar            // default null
}

export type BuilderNodeConfig =
  | InputConfig | AgentConfig | CrewConfig
  | GateConfig | RouterConfig | TransformConfig | OutputConfig

/* ─── discriminated node ──────────────────────────────────────────────────
 * The union is what makes `node.config.branches` narrow only on 'router' and
 * every inspector switch exhaustiveness-checkable. A new kind becomes a
 * compile error, not a blank pane. */
export interface NodePosition { x: number; y: number }   // INTEGERS. 120.5 → 422.

interface BuilderNodeBase {
  id: NodeId
  label: string                 // 1..40, REQUIRED, no default
  position: NodePosition        // default {x:0,y:0}; never compiled, never
                                // read at runtime — but still int-typed.
}

export type BuilderNode =
  | (BuilderNodeBase & { kind: 'input';     config: InputConfig })
  | (BuilderNodeBase & { kind: 'agent';     config: AgentConfig })
  | (BuilderNodeBase & { kind: 'crew';      config: CrewConfig })
  | (BuilderNodeBase & { kind: 'gate';      config: GateConfig })
  | (BuilderNodeBase & { kind: 'router';    config: RouterConfig })
  | (BuilderNodeBase & { kind: 'transform'; config: TransformConfig })
  | (BuilderNodeBase & { kind: 'output';    config: OutputConfig })

export interface BuilderEdge {
  id: EdgeId
  source: NodeId
  source_port: string           // NodeId-shaped. default 'out'. See §5.3.
  target: NodeId
  target_port: TargetPort       // literal 'in' — the ONLY legal value
}

/** node_id -> 'all'. 'any' is REFUSED at parse time (or_() suppression). */
export type BuilderJoins = Record<string, 'all'>

/** Written by the compiler, not by you. Send `null`, or round-trip verbatim. */
export interface BuilderBudgetBlock {
  static_cost_usd: number
  billable_nodes: number
  escalation_nodes: number
  cycles: number
  compiled_at: string           // ISO datetime, REQUIRED if the object exists
}

export interface BuilderDocument {
  /** WIRE KEY IS `schema`. The python field is document_schema. */
  schema: typeof BUILDER_SCHEMA_ID
  id: DocumentId                // SERVER-ASSIGNED, always overwritten
  name: string                  // 1..80, whitespace-stripped server-side
  version: number               // SERVER-ASSIGNED, always overwritten
  input_field: NodeId           // must equal exactly one input node's config.field
  nodes: BuilderNode[]
  edges: BuilderEdge[]
  joins: BuilderJoins
  budget: BuilderBudgetBlock | null
}

/* ─── problems ────────────────────────────────────────────────────────── */

export const PROBLEM_CODES = [
  'node-count', 'billable-count', 'escalation-count',
  'duplicate-node-id', 'duplicate-edge-id',
  'edge-unknown-endpoint', 'edge-unknown-port', 'edge-target-refuses-incoming',
  'fanout-width',
  'router-branch-count', 'router-otherwise', 'router-duplicate-branch',
  'router-branch-unconnected',
  'cycle-count', 'back-edge-not-router', 'cycle-iterations',
  'no-input-node', 'input-field-undeclared', 'input-field-ambiguous',
  'node-unreachable', 'no-output-node',
  'join-unknown-node', 'join-single-predecessor',
  'ident-pattern', 'ident-collision',
  'budget-over-ceiling', 'budget-unpriced-model',
] as const
export type ProblemCode = (typeof PROBLEM_CODES)[number]

/** The ONLY three warnings. Everything else is an error and blocks publish. */
export const WARNING_CODES = [
  'router-branch-unconnected', 'no-output-node', 'join-single-predecessor',
] as const

export interface BuilderProblem {
  code: ProblemCode | string    // string fallback: a new server code must render
  severity: Severity
  message: string               // a full sentence for the author. RENDER VERBATIM.
  node_id: string | null
  edge_id: string | null
}

/** Which inspector control a problem anchors to. Anything absent falls to the
 *  node-level strip at the top of the inspector — no problem is ever dropped. */
export const FIELD_CODES: Partial<Record<ProblemCode, string>> = {
  'router-branch-count': 'branches',
  'router-otherwise': 'branches',
  'router-duplicate-branch': 'branches',
  'router-branch-unconnected': 'branches',
  'cycle-iterations': 'max_turns',
  'input-field-ambiguous': 'field',
  'escalation-count': 'tier',
  'billable-count': 'tier',
  'edge-unknown-port': 'source_port',
}

/* ─── budget ──────────────────────────────────────────────────────────── */

export interface BuilderBudget {
  static_cost_usd: number   // ENFORCED. NITRO_PRICE_FACTOR (1.8) on cheap nodes.
  floor_cost_usd: number    // published prices, no nitro — the comparable figure
  modelled_calls: number
  billable_nodes: number
  escalation_nodes: number
  cycles: number
  unpriced_models: string[] // non-empty => a budget-unpriced-model ERROR
  over_ceiling: boolean     // static * 1.25 > MAX_RUN_COST_USD;
                            // ALWAYS false when the ceiling is <= 0 (disabled)
  ceiling_usd: number       // MAX_RUN_COST_USD, default 10.0
}

/* ─── vocabulary ──────────────────────────────────────────────────────── */

/** EVERY value arrives as a JSON FLOAT (24.0, not 24). Math.trunc on ingest. */
export interface BuilderBounds {
  max_graph_nodes: number
  max_billable_nodes: number
  max_escalation_nodes: number
  max_fanout_width: number
  min_router_branches: number
  max_cycles: number
  max_cycle_iterations: number
  max_agent_iter: number
  max_guardrail_retries: number
  max_label_chars: number
  max_name_chars: number
  max_gate_message_chars: number
  max_input_chars: number
  max_document_bytes: number
  run_cost_ceiling_usd: number   // <= 0 means DISABLED
}

export interface BuilderVocabulary {
  schema_id: string
  node_kinds: NodeKind[]        // ORDERED literals in the handler, not sorted
  tiers: Tier[]                 // ordered
  agent_ids: string[]           // sorted
  crew_ids: string[]            // sorted
  research_tools: string[]      // sorted
  transform_ops: TransformOp[]  // sorted
  router_comparisons: string[]  // sorted, WITHOUT 'otherwise'
  router_otherwise: string      // 'otherwise'
  result_body_keys: string[]
  bounds: BuilderBounds
}

/* ─── responses ───────────────────────────────────────────────────────── */

export interface BuilderDocumentSummary {
  id: string
  name: string
  version: number
  status: DocumentStatus
  created_at: string
  updated_at: string
}

export interface BuilderDocumentModel {
  id: string
  document: BuilderDocument
  status: DocumentStatus        // STORED fact
  version: number               // the version you are looking at
  head_version: number          // is_head === version === head_version
  created_at: string
  updated_at: string
  problems: BuilderProblem[]    // recomputed on every response
  budget: BuilderBudget         // recomputed — NOT document.budget
  graph: GraphDescriptor        // ready to render, no second request
  published: boolean            // this exact version is registered ON THIS
                                // process. Can be false while status is
                                // 'published' (restart before re-registration).
}

export interface BuilderValidation {
  valid: boolean                // === problems.every(p => p.severity !== 'error')
  problems: BuilderProblem[]
  budget: BuilderBudget
}

export interface BuilderPublish {
  workflow_id: string           // === the document id
  graph_version: string         // 16 lowercase hex — the graph ETag body
  version: number
  input_field: string           // the key POST /runs must carry inside `inputs`
  static_cost_usd: number
  gated_before_spend: boolean   // false => anonymous launch refused 403
  reserved_input_keys: string[] // sorted; refused in `inputs` with 422
}

/** publish's 422 is the ONE error on this router whose detail is an OBJECT. */
export interface BuilderCompileRefusal {
  message: string
  problems: BuilderProblem[]
}

export interface BuilderDocumentRequest {
  document: unknown             // toWire(doc) — `schema`, not documentSchema
  expected_version: number | null   // MANDATORY on PUT; ignored on POST/validate
}
```

---

## 4. Interaction spec — the acceptance checklist

Every row is a test. `⌘` means `Ctrl` on Windows/Linux, `Cmd` on macOS.

### 4.1 Creating

| Interaction | Behaviour | Key |
|---|---|---|
| Drag a kind from the palette | `dragstart` sets `dataTransfer` to the kind. Canvas `@drop` → `screenToFlowCoordinate` → `Math.round` to the 20 grid → `newNode(kind, pos, ids)` → **one commit**. Card plays `node-land` 260ms `--ease-out` **once** and is auto-selected so the inspector is already on it. | — |
| Click a palette tile | Same, dropped at viewport centre. | — |
| Insert by number | Drops the kind at the pointer (or viewport centre if the pointer is off-canvas), grid-snapped. Auto-connects from the selection when **exactly one** node is selected — as one batch commit. | `1`–`7` |
| Drag a port to empty canvas | `@connect-end` with no target opens `PortMenu` at the drop point. Typeahead over `vocabulary`. Enter → **ONE commit** containing the node AND the edge, labelled `Add market analyst`. One undo removes both. | — |
| Keyboard node creation from a port | `E` on the focused node enters keyboard-link mode; candidate targets are numbered, Tab cycles, Enter connects, Enter over empty space opens `PortMenu`. | `E` |

### 4.2 Connecting

| Interaction | Behaviour | Key |
|---|---|---|
| Draw an edge | Drag port → port. `isValidConnection` has already refused at the mouse the four representational impossibilities of §6.1 and nothing else. On `@connect`, one commit mints `e<n>` and sets `target_port: 'in'`. | — |
| Connect-drag affordance | Container gains `.is-connecting`. Valid target ports animate `port-ready 1.2s ease-in-out infinite`; invalid ports drop to `opacity: .25`. | — |
| Loop advisory | `onConnectStart` computes `ancestorsOf(source)` **once**. Every ancestor gets `is-loop-target`. If the source kind is not `gate`/`router` they additionally get `is-loop-illegal` + the inline note *only a gate or router may close a loop*. **The connection is still permitted** — the server owns `back-edge-not-router`. | — |
| Two edges between one pair | **Allowed**, on different ports. A gate's `approve` and `revise` may both land on the same node. (ChatDev's edge identity is `${from}-${to}`; this is unrepresentable there.) | — |
| Re-route an edge endpoint | A selected or hovered edge grows an 8px grab dot at each end; a 16px invisible stroke sits under the 1.2px visible one so a hairline is clickable. Drag one end with the other pinned. Drop on a compatible port → `retargetEdge`. Drop on a **different port of the same node** → `setEdgePort` (this is how a gate edge moves approve↔revise). Drop on empty → `PortMenu` seeded with the fixed end. Escape reverts with zero commits. | — |
| Change port from the inspector | Edge selection shows source/target/port pickers. One commit. | — |
| Toggle AND / OR fan-in | A node with ≥2 inbound edges shows a `Σ` glyph; click toggles `joins[id]='all'` against deleting the key. Inbound edges redraw with the AND bracket. | — |

### 4.3 Selecting & moving

| Interaction | Behaviour | Key |
|---|---|---|
| Click a node | Selects (visibly — 2px `--accent-cyan` ring + `--glow-input`). Binds the docked inspector. **No modal, ever.** | — |
| Add / toggle selection | Shift adds; ⌘/Ctrl toggles. Last-clicked becomes `selection.anchor` with a brighter ring (align needs a defined winner). | `Shift` / `⌘` |
| **Grab a group** | `pointerdown` on an **already-selected** node does NOT collapse the selection — it arms `pendingCollapse`, and only a `pointerup` with **< 3px travel** collapses to that node. Without this you cannot drag a multi-selection. | — |
| Marquee | Drag on empty pane. **Intersection**, not containment (containment-only is what makes wide cards finicky). Shift = additive, Alt = subtractive, both against the baseline captured at pointerdown. | `Shift`/`Alt` |
| Drag nodes | Vue Flow drags; snap 20 unless `Alt`. **One commit on `@node-drag-stop` only.** A per-frame commit would destroy the undo history in one gesture — this is non-negotiable. | `Alt` = free |
| Nudge | One grid step; `Shift` = 1px. Consecutive nudges coalesce inside 600ms under key `move:<ids>`. | arrows |
| Align / distribute | Floating `SelectionToolbar` above a multi-selection: align L/CX/R/T/CY/B, distribute H/V. **One commit each**, one undo step each. Hidden during any drag. | — |
| Alignment guides | During a drag, at most 2 vertical + 2 horizontal guides from left/centerX/right and top/centerY/bottom candidates against unselected nodes. Threshold is **6 SCREEN px divided by `viewport.zoom`** — a raw-flow-unit threshold feels wrong zoomed out. Equal-spacing double-arrow badge when the dragged node lands between two nodes with gaps matching within 2px. | — |
| Select all / deselect | | `⌘A` / `Esc` |

### 4.4 Editing

| Interaction | Behaviour | Key |
|---|---|---|
| Edit any field | Docked inspector, live-bound. The inspector emits `update: [patch]`; `BuilderView` turns it into ONE commit with `coalesceKey = node:<id>:<field>`, so a typed word is one undo step. Text commits on blur or 300ms idle; selects and steppers commit immediately. | — |
| Rename a node label | Double-click the label on the card, or `R`. Contenteditable; Enter commits, Escape reverts. | `R` |
| Rename a node **id** | `NodeIdField` validates per keystroke, refuses a taken id, states *this rename updates N references*, and on commit runs `renameCascade` — edges, `joins`, `input_field`, and every `${state.out__<old>}` in prompt inputs / transform args / output source / router keys — as **one** commit. | — |
| Router branch add / reorder / delete | Inline rows. Adding grows the card's port on the same tick. `otherwise` clears and disables key/value and vanishes from the select once taken. Deleting a branch with an edge deletes the edge **in the same commit**, toast names it, one undo restores both. | — |
| State reference | `StateRefInput` combobox over resolvable keys only. A nested ref is refused **in the field** with the server's own sentence — it is a 422 and must never be sent. | — |
| Scalar values | Explicit string / number / boolean / null toggle. Kills ChatDev's `temperature: '0.7'` hazard. Arrays and objects are not offered. | — |
| Delete | Removes nodes, every incident edge, and orphaned `joins` in ONE commit. **No confirm dialog** — undo is the confirmation, which is exactly why enabling the key is safe here and is not in ChatDev. | `Del`/`Backspace` |
| Copy / cut / paste / duplicate | Envelope to the system clipboard so paste works across tabs and workflows; in-memory fallback with a one-line notice when clipboard access is denied. Paste re-mints ids **and rewrites internal `${state.out__…}` refs**, keeps only edges with both endpoints copied, lands at the cursor grid-snapped, and becomes the selection. `⌘D` offsets +24/+24. | `⌘C ⌘X ⌘V ⌘D` |
| Alt-drag duplicate | `pointerdown` with Alt on a node commits the duplicate first, then drags the copies. One undo removes the copy **and** its move. | `Alt`+drag |
| Undo / redo | 200-deep snapshot ring. Every commit carries a label; `DocumentBar` shows `Undid: delete node` for 2s. | `⌘Z` / `⌘⇧Z`, `Ctrl+Y` |

### 4.5 Navigating

| Interaction | Behaviour | Key |
|---|---|---|
| Topological traversal | Moves the focused node downstream / upstream in `topoOrder`; centres it; `aria-activedescendant` + a polite live region announce it. | `Tab` / `⇧Tab` |
| Cycle siblings | | `[` / `]` |
| Pan / zoom | Vue Flow defaults + Space-drag + middle-mouse. | — |
| Fit / 100% / zoom to selection | | `F` / `⇧1` / `Z` |
| Minimap | Click centres; drag the viewport rect pans. Dots coloured red/amber/cyan by problem severity and selection. | — |
| Filter nodes | Focuses the filter; matches highlight, non-matches dim to `.35`. | `/` |
| Walk problems | Next / previous problem: select + `fitView` + focus the mapped field + flash. Same code path as clicking a `ProblemsPanel` row. | `F8` / `⇧F8` |
| Shortcut sheet | Rendered from the same binding table the listener dispatches from. | `?` |
| Escape | If a gesture is live (connect, marquee, rename, PortMenu) abort it with **zero commits**; else clear the selection; else close the topmost sheet. | `Esc` |

### 4.6 Document lifecycle

| Interaction | Behaviour | Key |
|---|---|---|
| Validate | 400ms debounce on a position-free fingerprint. Never fires while a drag or connect is live. Aborts the in-flight request. Stale responses dropped by fingerprint. | `⌘↵` forces now |
| Save | PUT with `expected_version` from the last successful response. Idle autosave 2.5s after the last commit; frozen while `saveState === 'conflict'`. `SaveChip` reports every state including failure — **silence is never a state**. | `⌘S` |
| Conflict (409) | **Never auto-reloads.** `ConflictDialog` re-GETs head, diffs, offers Discard mine / Keep mine / Open head. | — |
| Restore after refresh | A localStorage draft whose baseVersion still equals head raises a restore bar with both timestamps. Otherwise discarded, never merged. | — |
| Publish | `PublishDialog` precondition checklist. Blocked by: any error problem, unsaved changes, not at head, `phase === 'stale'` or `'unreachable'`, `over_ceiling`. On success renders the publish contract (§6.4). A 422 refusal's problems merge into `ProblemsPanel` tagged `from publish`. | `⌘⇧P` |
| Start from a template | `TemplateGallery` seeds the document into the store as an ordinary unsaved draft. Same commands, same undo, same inspectors, **no special case anywhere in the code**. The validator card's `caveat` renders verbatim. | — |

---

## 5. Visual spec

### 5.1 The gradient system and the two tenancies

`--node-gradient` is a **single semantic channel with two tenancies**. At design time it encodes **kind**; when run mode eventually lands it encodes **state**, and the handover is CSS specificity with zero JS.

`src/assets/styles/node-card.css` carries the shell (WP-A, verbatim from `WorkflowNode.vue`). `builder.css` adds:

```css
/* Design tenancy: kind owns the channel. */
[data-mode='design'] .workflow-node.is-kind-input     { --node-gradient: linear-gradient(135deg,#aaffcd,#99eaf9); --node-shadow-color: rgba(170,255,205,.42); }
[data-mode='design'] .workflow-node.is-kind-agent     { --node-gradient: linear-gradient(135deg,#99eaf9,#a0c4ff); --node-shadow-color: rgba(153,234,249,.42); }
[data-mode='design'] .workflow-node.is-kind-crew      { --node-gradient: linear-gradient(135deg,#a0c4ff,#bdb2ff); --node-shadow-color: rgba(160,196,255,.42); }
[data-mode='design'] .workflow-node.is-kind-gate      { --node-gradient: linear-gradient(135deg,#ffe082,#ffb84d); --node-shadow-color: rgba(255,224,130,.42); }
[data-mode='design'] .workflow-node.is-kind-router    { --node-gradient: linear-gradient(135deg,#b3b3b3,#7dc6ff); --node-shadow-color: rgba(125,198,255,.34); }
[data-mode='design'] .workflow-node.is-kind-transform { --node-gradient: linear-gradient(135deg,#8892a0,#b3b3b3); --node-shadow-color: rgba(179,179,179,.30); }
[data-mode='design'] .workflow-node.is-kind-output    { --node-gradient: linear-gradient(135deg,#aaffcd,#7bdff2); --node-shadow-color: rgba(170,255,205,.42); }

/* Problem tenancy OUTRANKS kind — an invalid node is red before you read a word. */
[data-mode='design'] .workflow-node.has-warning { --node-gradient: linear-gradient(135deg, var(--warn-border), var(--warn-text)); --node-shadow-color: rgba(255,204,0,.34); }
[data-mode='design'] .workflow-node.has-error   { --node-gradient: linear-gradient(135deg, var(--err-border), var(--err-text));  --node-shadow-color: rgba(255,82,82,.40); }

/* Reserved. Run tenancy lands as-is when the runner exists; nothing else moves. */
[data-mode='run'] .workflow-node.is-running   { --node-gradient: var(--gradient-running); }
[data-mode='run'] .workflow-node.is-completed { --node-gradient: var(--gradient-complete); }
```

**Escalation tier** gets a second inset ring, so only spend shouts:
`.workflow-node.is-tier-escalation { box-shadow: inset 0 0 0 1px var(--warn-border), 0 4px 6px -1px rgba(0,0,0,.3); }`
Cheap tier gets nothing.

**Zero new custom properties.** Every wash is `color-mix(in srgb, var(--accent-cyan) 14%, transparent)` — the technique `WorkflowNode` already uses.

### 5.2 Node card anatomy

Card is `240px` wide (`NODE_W`), `--r-2xl` radius, `--bg-node` fill, 2px transparent border carrying the gradient via the double-clip. Vertical rhythm, top to bottom:

1. **Eyebrow row** — 20px. Left: kind icon (lucide, `:size="13"`, `aria-hidden`). Right: `03 · AGENT` in `font: 700 var(--fs-11)/1 var(--font-mono)`, `letter-spacing: .04em`, `--text-40`. The index is 1-based, zero-padded, from document order.
2. **Title** — the label, `font: 600 var(--fs-15)/1.2 var(--font-display)`, `--text-title`, 2-line clamp. Double-click enters inline rename.
3. **Config summary line** — one mono line, `font: 500 10px/1.2 var(--font-mono)`, `--text-muted`, ellipsised. Per kind:
   - input → `idea · 2000 chars · required`
   - agent → `escalation · scoper · 2 iter · 1 tool`
   - crew → `escalation · synthesis`
   - gate → `1 turn · 2 editable`
   - router → `4 branches`
   - transform → `pick · source, key`
   - output → `markdown_body`
4. **Badge row** — 18px, only when non-empty. Left: problem badge (count; `--err-*` fill for error, `--warn-*` for warning) whose hover panel prints `problem.message` verbatim. Centre: `Σ` join glyph when `joins[id] === 'all'`. Right: escalation dot.
5. **Port footer** — 14px. §5.3.

Per-kind deviations:
- **gate** — the whole card carries a 1px amber left rule (`border-left: 2px solid var(--warn-border)` inside the radius) because a human stop is categorically different from a machine step.
- **router** — no title font swap, but the card is 12px shorter (no summary line when branches are 2) and the footer grows to fit N ports.
- **output** — a 2px `--accent-mint` terminal underline inside the bottom radius, and **no source handle at all** (not an inert one).
- **transform** — muted greys; it is plumbing, and the palette says so.

**Selection:** 2px `--accent-cyan` ring + `var(--glow-input)`. The multi-selection **anchor** gets the same ring at full opacity while members get it at `.6`, so align has a visible winner.

**`×N` lap chip and the crew SVG are NOT rendered at design time.** The DOM slot exists and is empty. See §5.7.

### 5.3 Ports

- **Target port** — one `<Handle type="target" :position="Position.Top" id="in">`, centred, 9px. Rendered for every kind **except `input`** (which renders none at all — `accepts_incoming` is false only there, and an edge arriving is `edge-target-refuses-incoming`).
- **Source ports** — `<Handle type="source" :position="Position.Bottom">` per `nodeKinds[kind].outPorts(node)`, evenly spaced at `((i + 0.5) / n) * 100%`.
  - most kinds: one, `id="out"`, centred, unlabelled.
  - **gate**: exactly two, `approve` at 30% (mint fill) and `revise` at 70% (amber fill), each with a **permanently visible** 9px mono label beneath. Never hover-only. This is the interaction ChatDev buries ten clicks and three modals deep.
  - **router**: one per `config.branches[].label`, labelled, blue fill; the `otherwise` port is **dashed and muted**.
  - **output**: none.
- **Rest / hover / connecting:** 9px at rest; on node hover `transform: scale(1.33)` (transform, not width — no layout). During a connect drag the container carries `.is-connecting`; valid ports run `port-ready 1.2s ease-in-out infinite`, invalid ports drop to `opacity: .25`.

### 5.4 Edges

- Base: `getBezierPath` + `BaseEdge`, `--edge-stroke` at `--edge-width` (1.2px), with a **16px invisible stroke underneath** so a hairline is clickable.
- **Port label chip** at the midpoint via `EdgeLabelRenderer`, rendered only when the source is a `gate` or `router` (mirroring the descriptor's own rule). Uses `--edge-label-bg` / `--edge-label-brd`. Colour-coded: approve mint, revise amber, router branch blue, `otherwise` muted-dashed. Clicking the chip selects that branch row in the inspector.
- **Back edges** (from the mirrored `backEdges(doc)`, styling only): `stroke-dasharray: 5 4` with a `↺` prefix in the label, so the two-cycle bound is legible rather than inferred.
- **AND fan-in:** when `joins[target] === 'all'`, inbound edges are drawn into a small bracket glyph above the target port.
- **Problem strokes:** an edge carrying an error strokes `--err-border`; a warning strokes `--warn-border`.
- **Selected:** 2.5px `--accent-cyan` with `edge-march` at **1.2s** (the run canvas uses 0.75s), so marching dashes mean "this is the live one" in both modes at two legible tempos.
- **Hover dims the FIELD.** One class on the flow container:
  ```css
  .builder-flow.is-hovering .workflow-edge:not(.is-lit) { opacity: .22; }
  ```
  Inbound edges of the hovered node light `--accent-blue`, outbound light `--accent-mint`. Hover travels through `provide`/`inject`, **not props** — zero per-edge work, no edges-array churn on mousemove. ChatDev highlights two sets against a full-strength field, which visibly stops working past ~15 nodes.

### 5.5 Motion

**Rule: the design canvas is STILL.** No infinite animation at rest. Motion means a drag in flight, a one-shot acknowledgement, or (later) a live run. Quote the tokens; introduce no new curve.

| Thing | Declaration |
|---|---|
| colour / border / background state | `transition: color var(--motion-fast) ease, background var(--motion-fast) ease, border-color var(--motion-fast) ease;` |
| anything that MOVES (rail slide, budget bar width, panel entrance) | `var(--motion-medium) var(--ease-out)` |
| node arrival | `node-land 260ms var(--ease-out)` — one-shot: `scale(.94)→1`, `opacity 0→1` |
| problem anchor flash | `problem-anchor 1.1s ease-out 3` — **finite**, deliberately matching `CrewProgress`'s existing `lap-flash` tempo and iteration count so "look here" is one idiom app-wide |
| selected edge | `edge-march 1.2s linear infinite` (run canvas: 0.75s) |
| valid port during a connect drag | `port-ready 1.2s ease-in-out infinite` — **only while `.is-connecting`** |
| minimap / rail collapse | `width var(--motion-medium) var(--ease-out)` |

`builder.css` ships its own `@media (prefers-reduced-motion: reduce)` block naming what survives: `node-land`, `problem-anchor`, `edge-march` and `port-ready` all become `animation: none`; the **state they encode stays** — the problem rim, the selected stroke width, the valid/invalid port opacity are all static properties and are untouched.

### 5.6 Empty states

| Surface | Empty state |
|---|---|
| Canvas, no document | `TemplateGallery` centred on the dot grid: four cards with `GraphThumbnail` spines. |
| Canvas, empty document | Dot grid + a single centred mono line: `Drag a kind from the palette, or press 1–7`. No illustration. |
| Inspector, nothing selected | `GraphSettings` — never blank space. |
| ProblemsPanel, clean | Mint dot + `Ready to publish` + the rule stated once: *warnings never block; errors always do.* |
| Library, no workflows | `No saved graphs yet` + the New button. |
| Vocabulary unavailable | Palette disabled, one `role="alert"` line naming the failure. **No hardcoded fallback list.** |

### 5.7 The sprite / crew layer — reserved, not built

The run console's rowing-crew SVG and `×N` lap chip live in `WorkflowNode.vue` and are driven by `data.state` / `data.visits`. **`BuilderNode.vue` does not render them and does not duplicate their CSS.** After WP-A both cards share `node-card.css`, which already carries `.node-crew`, `node-oar-stroke`, `node-rower-pull` and `node-hull-bob`, so the run tenancy needs no new styles.

`BuilderNode` renders `<div class="node-crew-slot" />` — an empty, correctly-sized (34px) slot — so that when the runner lands, the crew mounts into an existing box and nothing reflows. That is the entire seam. Do not build a design-time animation into it; an idle canvas that rows is the ChatDev disco.

---

## 6. Validation UX

### 6.1 The enforcement boundary — the single most important table in this document

**Tier 1 — client enforces, at the widget or at the mouse.** These are the server's *parse* refusals: deterministic, tiny, and derived from `/vocabulary` rather than reimplemented. They are 422s, so they must never be sent.

| Rule | Where |
|---|---|
| target has an inbound port (`input` renders none) | `isValidConnection` + no handle |
| source port exists in `nodeKinds.outPorts(node)` | `isValidConnection` |
| `output` offers no source port | no handle rendered |
| duplicate `(source, source_port, target)` triple | `isValidConnection`, O(1) Set built at `onConnectStart` |
| `^[a-z][a-z0-9_]{0,39}$` on every id, router label, `field`, `key`, `editable_fields` entry | `NodeIdField`, `TokenListInput` |
| string length bounds (label 40, name 80, gate message 2000) | inputs, `maxlength` + counter |
| numeric ranges from `vocabulary.bounds` (`max_iter` 1..8, retries 0..2, `max_chars` 1..2000) | steppers |
| `otherwise` takes no key and no value; every other op requires a key | `RouterBranchEditor`, structurally |
| exactly one `otherwise` per router | option removed from the select once taken |
| duplicate tool / duplicate editable field | checklist / token widget, impossible by construction |
| `${state.…}` single flat key; no nesting | `StateRefInput` |
| `JsonScalar` only — no arrays, no objects | `ScalarInput` |
| `body_key` ∈ `result_body_keys` | select |
| `joins` value is `'all'` | `'any'` never offered |
| `position` integers | `Math.round` on every write |

**Tier 2 — server owns, client renders only.** Every `bounds.py` count and every judgement. The client **never** gates an interaction on any of these, and never computes them:

`node-count`, `billable-count`, `escalation-count`, `fanout-width`, `router-branch-count`, `router-otherwise`, `router-duplicate-branch`, `router-branch-unconnected`, `cycle-count`, `back-edge-not-router`, `cycle-iterations`, `no-input-node`, `input-field-undeclared`, `input-field-ambiguous`, `node-unreachable`, `no-output-node`, `join-*`, `ident-*`, `budget-*`.

The **only** client-side use of Tier 2 knowledge is **advisory presentation**: the loop rim during a connect drag (§4.2), the dashed back-edge stroke, the palette's disable-at-ceiling, and BudgetMeter's pips. All four still permit the action; the server's problem always wins on screen.

*Ruled explicitly (R6): `isValidConnection` must NOT check `max_fanout_width`. Drawing a fifth edge is permitted and reported.*

### 6.2 The loop, and the honest `stale`

```
edit → commit → fingerprint changes → 400ms debounce
     → phase 'stale'  (list dims, header reads "checking")
     → POST /api/builder/validate (AbortController cancels any in flight)
     → response stamped with the fingerprint it answered
     → if stamp !== current fingerprint: DROP IT
     → else phase 'fresh', reindex byNode/byEdge/document, budget updates
```

`stale` is rendered, not concealed. **A stale error list presented as current is ChatDev's defining failure** — a `ConfigError` about node 7 shown while you edit node 2. Shipping the same failure with a nicer font is the one loss that matters.

`phase === 'unreachable'` (network failure or any 5xx) **disables Publish with a stated reason**. It never silently permits.

A drag or connect gesture suppresses validation entirely; it coalesces to the gesture end. Position changes never trigger it at all — `fingerprint` omits `position`, because position is never compiled and never read at runtime.

### 6.3 Where a problem lands — three places at once

1. **On the node/edge.** `worstByNode` drives `has-error` / `has-warning`, which outranks the kind gradient. A count badge; its hover panel prints the message verbatim.
2. **At the offending control.** `FieldProblem` resolves through `FIELD_CODES` and renders the message beneath the control with `aria-invalid` and `aria-describedby`. Anything `FIELD_CODES` cannot place falls to a node-level strip pinned at the top of the inspector — **no problem is ever silently dropped.**
3. **In `ProblemsPanel`.** Errors then warnings, all at once, never one at a time. Click → select + `fitView({nodes:[id], duration: 260})` + focus the mapped field + `problem-anchor` flash. `F8`/`⇧F8` walk the same path.

Document-level problems (both anchors null) get their own group at the top of the panel and are never anchored anywhere.

### 6.4 Budget

`BudgetMeter` re-renders from the same validate response — no second request.

- **Both dollar figures, always.** `floor_cost_usd` large as the comparable; `static_cost_usd` beside it labelled *enforced (1.8× nitro margin)*. Showing the inflated one alone reads as an error.
- Bar fills to `static_cost_usd × 1.25 / ceiling_usd` so it reaches full **exactly** where `over_ceiling` flips. Amber at 80%, `--err-*` at 100%.
- **`ceiling_usd <= 0` hides the bar entirely** and reads *no ceiling configured*. A percentage of zero is either 0 or infinity, and both are lies.
- `unpriced_models` non-empty → amber row naming the slug (it is also a `budget-unpriced-model` error).
- **Four headroom pip rows** — `billable /8`, `escalation /5`, `cycles /2`, `nodes /24` — filled/empty pips, amber **at** the bound, not past it. The flagship template sits at exactly 8/8, 5/5, 2/2 and a 4/4 fan-out; an author must SEE a full row before placing the node that breaks it.
- All four counts read `vocabulary.bounds`, `Math.trunc`'d. **Never hardcoded.**

### 6.5 What blocks publish

| Blocker | Message |
|---|---|
| any problem with `severity === 'error'` | `3 errors must be fixed` (button title names the count) |
| `saveState !== 'clean'` | `save first — publish registers the stored version` |
| `version !== headVersion` | `you are viewing v3; publish works on head (v7)` |
| `phase === 'stale'` or `'unreachable'` | `validation is not current` |
| `budget.over_ceiling` | the server's own ceiling sentence |

Warnings never block. That rule is stated once, in `ProblemsPanel`'s empty state.

---

## 7. Test plan

House rules apply throughout: Vitest 4, `frontend/tests/*.spec.ts` **flat**, named after the behaviour not the module, each opening with a docblock saying what gap it closes, `describe` written as sentences, assertions against rendered structure and `data-testid` — **no snapshots**. Doubles implement their subject's structural type so the compiler forces agreement.

### WP-A must prove
- `e2e/visual/run-canvas.spec.ts` — three committed screenshots (idle, running, gate-waiting) match after the extraction. **This is the whole gate.**
- The existing `nodeCrew`, `crewLoop`, `nodeVisits`, `gateNodeWaiting`, `quarantineNode` specs stay green untouched.

### WP-0 — `builderTypes.spec.ts`, `builderApi.spec.ts`, `builderGraph.spec.ts`
- The id minters accept and reject the documented edge cases (leading digit, uppercase, hyphen, 41 chars, empty).
- `toWire` emits `schema`, not `documentSchema`; `budget` is `null`.
- `forValidate` **omits `id`** and coerces `version` to a number — with an explicit case proving a string version can never leave the client (the 500 trap).
- `fingerprint` is invariant under a position change and variant under a config change.
- `wireBytes` matches `TextEncoder` length for a multi-byte name.
- `builderApi.create` reads `body.id` and ignores a `Location` header that is present.
- `publish`'s 422 object detail is unwrapped to `{message, problems}`; every other 422 goes through `readErrorDetail`.
- `save`'s 409 throws `BuilderConflictError` carrying the parsed stored version.
- `vocabulary` truncates every `bounds` float; a failed fetch sets `vocabularyUnavailable` and returns no fallback list.
- `renameCascade` rewrites edges, joins, `input_field`, prompt input values, transform arg values, `output.source`, **and router branch keys** — one document, one pass.
- `backEdges` agrees with `tests/fixtures/builderBackEdges.json` over every order-permuted document in it.

### WP-B — `builderCommands.spec.ts`, `builderPersistence.spec.ts`, `builderClipboard.spec.ts`
- Delete-node cascades to incident edges **and** orphaned joins in ONE undo step.
- Rename is one step; `coalesceKey` merges inside 600ms and refuses across `sealHistory()`.
- The ring bounds at 200; a new commit clears redo.
- **A node drag produces exactly one commit** (fed `@node-drag-stop`, not per-frame changes).
- `expectedVersion` is only ever assigned from a response — a test that mutates `doc.version` and asserts the PUT body is unaffected.
- A 409 opens the conflict path and does not mutate the document; *Take theirs* leaves the author's version recoverable by one undo.
- A `localStorage` write that throws does not break a commit; a draft over `max_document_bytes` is dropped with the chip state set.
- A restore is offered only when the draft's baseVersion equals head.
- Paste rewrites `${state.out__x}` in all four positions; an edge with one endpoint outside the copied set is dropped; the clipboard falls back to the in-memory ref when `navigator.clipboard` rejects, and reports it.

### WP-C — `builderValidation.spec.ts`, `builderProblems.spec.ts`, `budgetMeter.spec.ts`
- A position-only edit issues **no** request.
- A rapid burst issues exactly one request; the earlier `AbortController` is aborted.
- An out-of-order response is dropped by fingerprint stamp.
- `phase` walks `idle → stale → fresh`; a 500 and a network failure both land in `unreachable` and Publish is disabled.
- Over `builderProblemCodes.json` (all 27): both-anchor codes appear in **both** maps; document-level codes reach `documentProblems`; `problemsForField` places each mapped code; **and no problem in the fixture is unrendered by any surface** (a coverage assertion over the three sinks).
- Publish stays enabled with any of the three warnings and disabled with any error.
- `BudgetMeter` renders both dollar figures; fills to full exactly at `over_ceiling`; **hides the bar when `ceiling_usd <= 0`**; pip rows read the truncated bounds.

### WP-D — `builderPorts.spec.ts`, `builderCanvas.spec.ts`, `builderNode.spec.ts`
- `nodeKinds.outPorts` agrees with `_OUT_PORTS_BY_KIND` for all seven kinds; a gate offers exactly `approve, revise` in that order; a router's ports track its branch labels reactively; `output` offers none; `input` renders no target handle.
- `isValidConnection` refuses the four Tier-1 cases and **permits** a fifth outgoing edge (the fan-out case) — the explicit anti-regression for R6.
- The duplicate check uses a Set built at `onConnectStart` (assert one build per drag, not per hover).
- Palette drop rounds to the 20 grid; a fractional drop position never reaches a commit.
- `pointerdown` on an already-selected node preserves the multi-selection; a `pointerup` with <3px travel collapses it; >3px does not.
- Marquee **intersects** rather than contains.
- `PortMenu` creation emits ONE commit containing node + edge; Escape emits zero.
- `BuilderNode` binds `has-error`/`has-warning` above `is-kind-*`, renders the escalation ring only on `tier: 'escalation'`, and renders **no** crew SVG and **no** lap chip.

### WP-E — `builderInspector.spec.ts`, `routerBranches.spec.ts`, `stateRef.spec.ts`
- `INSPECTORS` is exhaustive over `NodeKind` (a type-level assertion plus a runtime key check).
- Selecting `otherwise` clears and disables key/value; the option disappears once taken; a non-`otherwise` op with an empty key marks the row.
- Deleting a branch that has an edge removes both in one commit; one undo restores both.
- `StateRefInput` refuses a nested ref with the server's sentence and never emits it; the picker lists exactly `input_field` + `out__<id>` per node.
- `ScalarInput` round-trips number, boolean and null distinctly — `0` and `false` survive.
- `CrewInspector` disables `synthesis` and `report` with the reason, and renders no `tools` control.
- `GateForm` renders **no** `expiry_seconds` control and the value still round-trips through a commit.
- `NodeIdField` states the reference count before commit and refuses a taken id.
- `TransformArgsEditor` flags both an arg with no `{name}` and a `{name}` with no arg.

### WP-F — `builderShell.spec.ts`, `validatorTemplate.spec.ts`, `publishDialog.spec.ts`
- The hash router resolves all three routes and `BuilderView` mounts a VueFlow instance with an id distinct from the studio's.
- **`IDEA_VALIDATOR` validates clean against a recorded fixture of the real `/validate` response**, uses **no** `crew` node, sits at exactly 8 billable / 5 escalation / 2 cycles, and every `${state.…}` in it matches `STATE_REF_PATTERN`. Its bound assertions read live `vocabulary.bounds`, **not constants**, so a server bounds change fails this test rather than the gallery.
- `GraphThumbnail` renders one rect per node from the document's own positions.
- `PublishDialog` blocks on each of the five conditions independently and names each.
- On success it renders `input_field`, `reserved_input_keys`, `graph_version`, and the full 403 sentence when `gated_before_spend` is false.
- `ShortcutSheet` renders every entry in the exported binding table and nothing else (assert set equality both ways).

### WP-G — `e2e/builder.spec.ts`
Playwright, chromium, 1440×900, `SYNTHETIC=1` backend on 8099, **zero console errors tolerated**:

1. Open `#/build`, pick **Minimal gated agent** from the gallery.
2. Drag an `agent` from the palette; assert the problem count rises then falls as it is connected.
3. Attempt to connect INTO the input node; assert the connection does not complete and no commit occurred.
4. Drag from the gate's `approve` port to empty canvas; create a node from `PortMenu`; press `⌘Z` once and assert **both** the node and the edge are gone.
5. Delete a router branch that has an edge; assert both vanish; `⌘Z` restores both.
6. Marquee three nodes, align left, assert one undo step.
7. Save (`⌘S`); write a second version through the API directly; save again; assert `ConflictDialog` and that *Keep mine* succeeds.
8. Fix the last error the panel names by clicking its row (assert the viewport centres and the field focuses); publish; assert the publish contract renders `input_field` and `reserved_input_keys`.
9. Reload; assert the version chip and that no restore bar appears (draft baseVersion === head).

---

## 8. Backend gaps

Named precisely, in the order they must be closed. **None of this is in the frontend deliverable.** The builder ships without a Run path (R4) and says so in the UI only by omission — no disabled control, no "coming soon".

### 8.1 Blocking the Run path (ordered)

1. **§3a — `RunExecution` carries no `workflow_id`.** `registry._execute` resolves `runtime = self._runtime_for(record.workflow_id)` and then calls `runtime.runner(execution)`; the runner is never told which workflow it is, while `create_builder_router(..., runner=<single Runner>)` installs one runner for every builder workflow. **Take option A** (smaller diff, and the closure is the natural home for the `FlowDefinition` that `resume` must reuse): change `_register_runtime`'s third parameter to `runner_factory: Callable[[BuilderWorkflow], Runner]`, and thread that through `create_builder_router` and `create_app(builder_runner=…)`.
2. **§3b — `src/brief_crew/service/builder_runner.py`.** `BuilderFlowRunner` wrapping `Flow.from_declaration(contents=workflow.compiled.definition, persistence=execution.persistence)` and `Flow.from_pending(context.flow_id, execution.persistence, definition=self._definition)`. Four requirements, each of which fails **silently** if omitted:
   - both calls wrapped in `builder_cancellation(execution.cancel_requested)` — `runtime.checkpoint()` reads that ContextVar, and `HookAborted` is what makes a cancel reach CANCELLED instead of FAILED;
   - `FlowDefinition` built **once** and reused for `resume` — without `definition=`, `from_pending` builds `Flow()` with no methods and the resume produces nothing;
   - `persistence=` threaded on both paths;
   - a `SyntheticBuilderRunner` (a `use_crew_factories(StubFactories())` swap, not a second implementation) or `SYNTHETIC=1` cannot exercise a builder graph at all.
3. **§3c — three wiring sites:** `app.py:513`, `app.py:837`, `app.py:1656 app_from_env()`, plus `builder_api.py:299-306`.
4. **§3e — six gate fixes in `registry.py`**, without which a builder gate is unusable even once a runner exists:
   - `GATE_OPEN` / `GATE_CLOSED` / `_reopen_gate` (four emit sites) and `_gate_prompt` must resolve `node_id` via `record.node_registry.declared_node(context.method_name) or context.method_name` — today they emit the compiled ident `n2_confirm`, `StreamSinkAdapter.emit` uses it verbatim, and **the console can never set a builder gate node to `waiting`**;
   - `_gate_prompt` titles **every** builder gate `"Review verdict"` and reads validator-only summary keys;
   - `_gate_derived_keys` keys on `VERDICT_GATE_NODE`, so a builder gate returns `frozenset()` and **`GateConfig.editable_fields` is not enforced** (R9);
   - `_feedback` files a builder gate's operator edits under a `"verdict"` slot;
   - `remaining` uses `VALIDATOR_MAX_GATE_TURNS (5)` while `route_gate` honours `GateConfig.max_turns` (≤3) and silently downgrades the rest;
   - `GateConfig.expiry_seconds` is never read; `VALIDATOR_GATE_TIMEOUT_SECONDS` is used globally (R8).
5. **§3d — restart rehydration.** `BuilderDocumentStore.published()` exists, documents itself as this seam, and has **zero call sites**. All five registration maps are process-local and both Render services carry `autoDeploy: yes`, so **every push to `main` silently unpublishes every user graph**. Needs a startup pass in `create_app` after the registry exists and before the router mounts, with a `try/except BuilderCompileError: continue` per row — a graph published under laxer bounds must not stop the process booting.

### 8.2 Correctness, independent of the Run path

6. **`BUILDER_CREW_LIBRARY` advertises two uninstantiable crews.** `SynthesisCrew.__init__` requires `market, sentiment, feasibility`; `ReportCrew.__init__` requires `verdict, tool_urls`. A document naming `crew_id: "synthesis"` **compiles and publishes cleanly and then raises `TypeError` at the first PAID run** — after the scoper and all three research branches have billed. Fix: `library_problems` must return an **error** for a crew whose factory is not zero-arg constructible, or those ids must leave `vocabulary.crew_ids`. The client marks them unavailable (R10), but a document hand-edited past the widget still publishes.
7. **`POST /api/builder/validate` returns 500 on a non-numeric `version`** — a bare `int(...)` with no guard. The client can never provoke it, and treats any 5xx as `unreachable`, so a regression here presents as a mysteriously unpublishable document. Guard it.
8. **`/api/builder/validate` is unauthenticated and unrate-limited**, and an open editor tab polls it indefinitely on a 400ms debounce. No LLM work, no persistence — CPU only — but it is the only endpoint an idle tab drives forever. Worth a per-client bound before this is public.
9. **`list_my_runs` labels history with `inputs.get("idea") or inputs.get("topic")`** (`app.py:1080`), so a builder graph with any other `input_field` shows a blank row. One line.
10. **`MAX_BILLABLE_NODES = 8` and the validator template needs exactly 8.** Same for escalation (5/5), cycles (2/2) and the gate's fan-out (4/4). Shipping the template means shipping a hero graph that errors on the first node a user adds. Pips make it legible, not survivable. **Raise the billable and escalation bounds before the gallery ships**, or accept the surprise deliberately and say so.
11. **`scripts/emit_builder_fixtures.py` + `tests/builder/test_client_fixtures.py`** must land with WP-G. The Python test regenerates and byte-compares both fixtures, so CI fails when the TS mirrors rot. This is the only anti-drift mechanism in the plan that survives a contributor who does not read this document (R7).

---

## 9. Cut list — explicitly NOT in scope

Nothing below may be stubbed, disabled, hidden behind a flag, or rendered inert. If it is not built, it does not appear.

1. **Run mode. No Launch control, no Build/Run toggle inside the builder, no `data-mode="run"` code path beyond the reserved CSS block.** `StudioView` keeps its own Run header toggle back to `#/`; the builder never offers one. Reason: R4.
2. **Any run-view change beyond `useValidatorRun`'s `inputField` parameter.** Do not touch frames, gates, report, usage, recovery, or the 25 existing frontend specs.
3. **`GateConfig.expiry_seconds` control.** Round-trips only. R8.
4. **A crew node's `tools` control.** The key is `extra="forbid"`; there is nothing to render.
5. **A command algebra** — no `invert()`, no `Command` union, no `structural()` predicate. Snapshot ring only. R3.
6. **A hand-rolled pointer/selection/drag/pan/marquee layer.** Vue Flow owns all of it. R2. Alignment guides and the align/distribute toolbar sit *on top of* Vue Flow's drag; they do not replace it.
7. **`@vue-flow/minimap`, `@vue-flow/node-resizer`, `vue-router`, `marked`, `dompurify`, any form library, any state library.** Zero new npm dependencies in this deliverable.
8. **Node resize, groups/frames, lasso actions, node comments/notes.**
9. **A YAML or JSON source tab.** The document is edited through the canvas and the inspector; there is no second editing surface to keep in sync.
10. **Auto-layout / re-layout.** Positions are authored. (A layered pass is a good later addition as one undoable commit; it is not this milestone.)
11. **Real-time multi-user editing, presence, or locking.** Optimistic concurrency via `expected_version` and a conflict dialog is the whole story.
12. **Template authoring or saving a document as a template.** The four templates are code.
13. **Search across workflows, tags, folders, favourites.** The library is a flat list, newest-first.
14. **Light mode.** The product is dark-only and commits to it; `tokens.css` has no `[data-theme]` block and this deliverable adds none.
15. **i18n.** All strings are English literals in the components, matching the existing app.
16. **Any client-side reimplementation of a `bounds.py` count.** R6. The only exceptions are the four presentational advisories named in §6.1, none of which gates an action.
17. **A fallback vocabulary.** If `/vocabulary` fails, the palette disables and says so. A hardcoded enum is how a client starts drawing graphs the compiler rejects.

---

*Every decision in this document is closed. Where an implementation agent finds reality contradicting it — a wire field that differs, a bound that moved, a Vue Flow prop that does not behave as described — stop, report it against the section number, and do not improvise a second answer.*