# 02 — Canvas

The Vue Flow surface: pan, zoom, select, connect, undo, and the pixels of
ports and edges. Build-time surface; the critic compares it against Flowise.

## Problem

The canvas exists and is good. `BuilderCanvas.vue` (703 lines) hosts
`<VueFlow id="builder-flow">` with snap `[20,20]`, `ConnectionMode.Strict`,
`min-zoom 0.2`, `max-zoom 1.4`, fit padding `0.16` (`BuilderCanvas.vue:528-543`).
`useBuilderCanvas.ts` (1,537 lines) owns selection, mouse *and* keyboard
connect gestures (`:743`, `:776-935`), drop and click-to-place (`:937-1012`),
drag committed only on `DragStop` (`:1043-1077`), edge retarget (`:1093-1135`),
fit / zoom / centre (`:1262-1329`), six align modes and two distribute axes
(`:116-119`, `:1364-1446`). Undo is a 200-deep snapshot ring with labelled,
coalescable commits (`useBuilderDocument.ts:57`, `:237-285`). Clipboard is the
system clipboard with a schema-tagged envelope (`useBuilderClipboard.ts:17-41`).
Thirty-one hotkeys are declared as data and rendered into the shortcut sheet
from the same table (`useBuilderHotkeys.ts:5-27`). Alignment guides are SVG
(`BuilderCanvas.vue:219-349`, `:609-616`). The minimap is hand-rolled and
problem-coloured (`BuilderMinimap.vue:6-19`). Flowise has **no undo at all** and
a paste handler that replaces the whole flow (`docs/flowise-notes.md` §1).

What the rubric will still score against Flowise, and lose on today:

| Rubric | Today | Flowise |
| --- | --- | --- |
| 3 — drag precision | ports **9 px** at rest, `×1.33` on hover = 12 px; hit target equals the visual (`builder.css:378-395`) | 10 px / 10 px (v1); v2 output port 20 px, hover-revealed |
| 3 — connection feedback | candidate ports pulse and non-candidates mute to `.25` (`builder.css:438-442`); no red on an invalid target | `handle-connecting` red / `handle-valid` green (`views/canvas/index.css:41-49`) |
| 5 — edge legibility | one `--edge-inactive` grey at 1.2 px, dashed cyan back edges, 16 px hit path (`builder.css:460-496`) | v2 gradient source→target colour, 15 px hit path, hover-only delete, branch label on the dangling line |
| 1 — new-flow creation | `BLANK` opens with 0 nodes and 2 problems (`builderTemplates.ts:240-265`) | new flow seeded with a Start node (`Canvas.jsx:656-677`) |
| 6 — graph scale | never measured; `min-zoom 0.2` unexplained | v2 `minZoom 0.5`, unmeasured |
| capture | dark only; one unconditional `:root` (`tokens.css:1`) | light and dark |

Three new port classes (`attach`, `member`, `error`, FD4) and three new node
kinds (FD3) land on this surface and must be distinguishable at 50 % zoom.

## Scope

Ports, connection feedback, edge rendering, the dangling connection line,
zoom limits, a light theme, the 390×844 viewport, the new-flow seed, the
perf fixture and its measurement, and the attach-by-drop gesture's canvas
half. Everything is a change to `BuilderCanvas.vue`, `BuilderNode.vue`'s port
footer, `BuilderEdge.vue`, `useBuilderCanvas.ts`, `assets/styles/{builder,tokens}.css`
and `playwright.config.ts`.

## Out of scope

Node identity and the palette (03). Inspector (04). Auto-layout, groups, node
resize, presence (cut-list 8, 10, 11 stand). A pointer layer of our own — R2
stands, Vue Flow owns drag, marquee, pan and zoom.

## Design

**D1 — Ports grow to 12 px visual inside a 24 px hit target, and colour by class.**
The rest size moves from 9 px to 12 px and the hover scale stays `×1.33`
(16 px) because scaling by transform is what stops a port "running away"
(`builder.css:375-395`). The hit target is the handle element itself at
`24×24` transparent, with the visible disc drawn by `::after`; Vue Flow's
`translate(-50%, ±50%)` offset is restated in the hover rule as today
(`builder.css:389-395`). Flowise's 10 px/10 px is the reference floor and the
rubric names "port hit-target is 4px; Flowise's is 12px" as the shape of a
defect. Colour by **port class**, not by selection (Flowise colours by
selection and hides type in a tooltip — `docs/flowise-notes.md` §2):

| Port | Colour token | Shape |
| --- | --- | --- |
| `in` | `--accent-cyan` (today's default) | disc, top edge |
| `out` | `--accent-cyan` | disc, bottom edge |
| `approve` / `revise` | `--accent-mint` / `--warn-text` (unchanged, `builder.css:397-398`) | disc with permanent label |
| router branch / `otherwise` | `--link-cyan` / dashed `--text-40` (unchanged, `:399-403`) | disc with permanent label |
| `attach` (target on agent, crew) | new `--accent-attach` (violet, `#c3a6ff`) | **square**, left edge |
| `attach` (source on tool, mcp, skill) | `--accent-attach` | square, right edge |
| `member` (target on crew) | `--accent-mint` | **diamond**, left edge, below `attach` |
| `error` (source) | `--err-text` | disc with permanent `error` label, bottom-right |

Shape carries class where colour is lost — at 50 % zoom, print, or
deuteranopia. `attach` and `member` sit on the left edge so attachment edges
run horizontally and flow edges vertically, which is what keeps a wired agent
readable (rubric 5).

**D2 — Red and green during a connection drag.** Vue Flow sets
`.vue-flow__handle-connecting` and `.vue-flow__handle-valid` exactly as React
Flow does. Two rules join the existing `is-connecting` muting:
`.vue-flow__handle-valid` fills `--accent-mint` with `cursor: crosshair`;
`.vue-flow__handle-connecting:not(.vue-flow__handle-valid)` fills
`--err-text` with `cursor: not-allowed`. `isValidConnection`
(`useBuilderCanvas.ts:743`) stays the single predicate; it gains the FD4
class rules: `attach` accepts only tool/mcp/skill sources, `member` only
agent sources, `in` refuses attachment kinds and member agents. Flowise v2's
silent cycle rejection (`docs/flowise-notes.md` §2, "the drop just does
nothing") is the failure to avoid: a refused drop flashes the target red for
`--motion-medium` and the port menu is not opened.

**D3 — The dangling connection line previews class and label.** Vue Flow's
`#connection-line` slot renders a path tinted by the source port's class and,
for gate and router sources, the port label (`approve`, `revise`, a branch
name) travelling with the cursor — Flowise's `ConnectionLine.jsx` does this
for `proceed` / `reject` and it is the reason a drag from a gate never lands
on the wrong branch.

**D4 — Edges are tinted by class; flow edges run a source→target gradient.**
`BuilderEdge.vue` keeps `getBezierPath` (`:45`) and the 16 px hit path
(`:160`, already wider than Flowise's 15). Per-edge `<linearGradient
id="edge-gradient-{id}">` from the source kind's accent to the target kind's
accent (`nodeKinds.ts:147-336` `accent`), `stroke-width 1.5`, opacity `.75`
unselected, `1` selected — Flowise v2 measurements (`docs/flowise-notes.md` §2).
Class styles:

| Class (from `target_port`) | Stroke | Marker |
| --- | --- | --- |
| flow (`in`) | gradient, 1.5 px | arrowhead |
| attach | `--accent-attach`, 1 px, `stroke-dasharray 2 3` | none |
| member | `--accent-mint`, 1 px, `stroke-dasharray 6 3` | none |
| error (source port `error`) | `--err-text`, 1.5 px | arrowhead + `!` chip at midpoint |
| back edge | as flow, plus `stroke-dasharray 5 4` (unchanged, `builder.css:484`) | arrowhead |

Warning and error problem tints (`builder.css:477-478`), `is-lit-in/out`,
`is-dim` and the selected dash (`:486-496`) are unchanged. A hover-only
delete affordance (20 px, `EdgeLabelRenderer`, midpoint) is added for pointer
users; keyboard deletion stays select + `Delete` (`useBuilderHotkeys`).

**D5 — Zoom limits 0.2 … 2.0.** Today `0.2 / 1.4` (`BuilderCanvas.vue:538-539`).
The floor stays: the 16-node validator template fits at scale `0.466` in the
settled container (CLAUDE.md §14 defect 4), so a 48-node document needs
roughly `0.3`. The ceiling rises to Vue Flow's default `2.0`, matching
Flowise, so a 390 px viewport can read an 11 px port label at 22 px. Fit
options stay `padding 0.16, maxZoom 1`.

**D6 — A light theme, as tokens.** `tokens.css` has one `:root`
(`tokens.css:1`). Add `:root[data-theme="light"]` overriding surfaces, text,
borders, canvas, edge and glow tokens only; accents and kind gradients are
shared. Default follows `prefers-color-scheme`; a toggle in `DocumentBar`
writes `localStorage['studio-theme']` and is **not** a document commit. The
node-card gradient trick (`node-card.css:53-84`) is verified in both themes by
the visual spec. Cut-list 14 is overturned by 00 D2.

**D7 — The new-flow seed.** "New graph" creates a document with one `input`
node at `(100, 100)`, `field: 'input'`, `input_field` set, so the canvas
opens with **zero** problems (today two, `builderTemplates.ts:240-265`). A
second `input` remains legal and remains flagged by `input-field-ambiguous`
as today (`nodeKinds.ts:124-133`). Landing → first node placed is then one
click (the template card) — rubric 1.

**D8 — Attach-by-drop on the canvas.** `dropKind` (`useBuilderCanvas.ts:937`)
gains a hit test against node bounds: a tool/mcp/skill kind dropped inside an
agent or crew card creates node + attach edge in **one** commit labelled
`Attach {kind}`; the target card gets `is-attach-target` while the drag is
over it. A drop on empty canvas creates an unattached node that validation
flags (`attach-target-not-agent` is for edges; the unattached case is the
warning `attachment-unattached` — CONTRACT REQUEST below). `placeAtCentre`
(`:942-964`, in the working tree) is untouched.

**D9 — 390×844 is a capture and inspect viewport, not an authoring one.**
Rails already become overlays at 1180 px and 860 px (`studio.css:287-293`).
At 390 px the palette is a bottom sheet, the inspector an overlay, and the
canvas is pan/zoom/select only; drop is disabled (touch drag from a sheet is
a separate gesture the gauntlet does not require). A second Playwright
project `mobile` at 390×844 runs the visual specs and the gallery/open
journey.

**D10 — Undo semantics are unchanged (R3).** Every new gesture is one
`commit(label, next, coalesceKey)`: attach-drop, edge delete by hover button,
theme toggle excluded. `HISTORY_LIMIT` stays 200.

## Interfaces

Consumes **C1** (port names per kind, FD4), **C2** (the port table arrives in
`vocabulary.target_ports`, 03), **C8** (problem codes for refused edges, 12).

Owned:

- CSS tokens: `--accent-attach: #c3a6ff` and the `[data-theme="light"]` block (`assets/styles/tokens.css`).
- Port classes on `.builder-port`: `is-port-in | is-port-out | is-port-attach | is-port-member | is-port-error | is-approve | is-revise | is-branch | is-otherwise`.
- Edge classes on `.builder-edge`: `is-class-flow | is-class-attach | is-class-member | is-class-error`, plus the existing `is-back-edge`, `has-warning`, `has-error`, `is-selected`, `is-dim`.
- `useBuilderCanvas` additions: `edgeClassOf(edge): 'flow'|'attach'|'member'|'error'`, `dropKind(kind, screenPoint) → { nodeId, attachedTo: NodeId | null }`, `hitTestNode(flowPoint) → NodeId | null`.
- `playwright.config.ts` projects: `chromium` (1440×900, unchanged) and `mobile` (390×844).

## Acceptance criteria

1. `builder.css`: `.builder-port.vue-flow__handle` is `24×24` with a 12 px `::after` disc; `frontend/tests/builderPorts.spec.ts` asserts the computed sizes. **Rubric 3.**
2. `e2e/builder.spec.ts` "connects at 50 / 100 / 150 % zoom": at each zoom a port-to-port drag succeeds on the first attempt, 10 of 10 repetitions. **Rubric 3.**
3. During a connection drag, a valid target handle has class `vue-flow__handle-valid` and computed background `--accent-mint`; an invalid one has `vue-flow__handle-connecting` and `--err-text`; `e2e/builder.spec.ts` asserts both. A refused drop leaves `useBuilderDocument.depth` unchanged.
4. Dragging from a gate's `revise` port shows `revise` on the dangling line (`#connection-line` slot rendered; Playwright reads the label text).
5. Every edge element carries exactly one `is-class-*`; `frontend/tests/builderEdge.spec.ts` mounts one edge per class and asserts stroke token and marker presence per the D4 table. **Rubric 5.**
6. Flow edges render a `<linearGradient>` whose stops equal the source and target kind accents from `nodeKinds.ts`; back edges additionally carry `stroke-dasharray`.
7. `min-zoom` is `0.2` and `max-zoom` is `2` (`BuilderCanvas.vue`), and the 48-node perf fixture fits inside the canvas pane at `fit-view` — `e2e/builder-layout.spec.ts` extends its existing "every node inside the pane" test (`:212`).
8. **Rubric 6:** `e2e/builder-perf.spec.ts` loads `frontend/tests/fixtures/perf48.json` (24 flow + 24 attachment nodes, the bound maximum), scripts 3 s of wheel zoom and 3 s of drag pan, samples `requestAnimationFrame` deltas, and asserts **mean ≤ 16.7 ms and p95 ≤ 20 ms** on the `chromium` project; the numbers are written to `benchmarks/perf/canvas.json`. A client-only 60-node render (no server) passes the same budget.
9. `tokens.css` contains `[data-theme="light"]`; `e2e/visual/builder-canvas.spec.ts` captures the gallery, a one-node canvas, the 16-node template, and a problem state at 1440×900 **and** 390×844, light **and** dark — 16 baselines — with zero console errors.
10. A new document opens with one `input` node and **zero** problems (`frontend/tests/builderTemplates.spec.ts`); landing → first node placed ≤ 1 click in `e2e/builder.spec.ts`. **Rubric 1.**
11. Dropping a `tool` tile onto an agent card creates two document entries (node + edge with `target_port: 'attach'`) in one undo step; `undo()` removes both (`frontend/tests/builderCanvas.spec.ts`).
12. `useBuilderHotkeys` still declares every binding as data and `ShortcutSheet` renders the same table; adding the theme toggle key fails `shortcutSheet.spec.ts` unless declared.
13. `npx playwright test --project=mobile` runs and is green; the palette bottom sheet and inspector overlay are present at 390 px.
14. `npx vitest run` and `npx vue-tsc -b --force` exit 0.

## References

- Flowise: `packages/ui/src/views/agentflowsv2/{Canvas.jsx:720-821, AgentFlowNode.jsx:331-357, 659-699, AgentFlowEdge.jsx, ConnectionLine.jsx}`, `views/canvas/index.css:41-49`, `views/canvas/index.jsx:586-660` — via `docs/flowise-notes.md` §1, §2, §9.
- ChatDev: `frontend/src/utils/vueflow.css:20-31` (the one custom easing, `cubic-bezier(0.4,0,0.2,1)` 300 ms) — `docs/chatdev-notes.md` §2.
- Repo: `frontend/src/components/builder/BuilderCanvas.vue:219-349, 509, 528-543, 609-616`; `BuilderNode.vue:191-216`; `BuilderEdge.vue:34-52, 152-180`; `composables/useBuilderCanvas.ts:51, 116-119, 204, 229-242, 364, 544-552, 743-935, 937-1012, 1043-1135, 1150, 1262-1446`; `useBuilderDocument.ts:57, 153, 207-285`; `useBuilderClipboard.ts:17-59`; `useBuilderHotkeys.ts:5-27`; `assets/styles/builder.css:372-442, 460-496`; `assets/styles/tokens.css:1-65`; `studio.css:287-293`; `data/builderTemplates.ts:240-265`; `playwright.config.ts:54-59`; `e2e/builder-layout.spec.ts:212`.
- `docs/flow-builder-spec.md` R2, R3, R11, R12, §4.2, §4.3, §5.3, §5.4.
- Gauntlet: rubric 1, 3, 5, 6; JUDGE §Capture (1440×900, 390×844, light, dark).

## Status

Built · 2026-09-04, on `gauntlet/plans`. Twelve of the fourteen criteria are
met, one is partial and one is met with a stated reading. Every figure below was
run in this worktree on the day; nothing is inherited.

| # | Criterion | | Shown by |
| ---: | --- | --- | --- |
| 1 | 24px hit target, 12px disc | **met** | `tests/builderPorts.spec.ts` (38), `e2e/builder.spec.ts` |
| 2 | connects at 50 / 100 / 150 %, 10 of 10 | **met** | `e2e/builder.spec.ts` — 30 drags, every one first time |
| 3 | green / red handles; a refused drop commits nothing | **met** | `tests/builderPorts.spec.ts`, `e2e/builder.spec.ts` |
| 4 | the dangling line previews class and label | **met** | `e2e/builder.spec.ts` |
| 5 | exactly one `is-class-*`, per the D4 table | **met** | `tests/builderEdge.spec.ts` (25) |
| 6 | flow edges gradient source → target accent | **met** | `tests/builderEdge.spec.ts` |
| 7 | zoom 0.2 … 2, the 48-node fixture fits | **met** | `e2e/builder.spec.ts`, `e2e/builder-layout.spec.ts` |
| 8 | frame budget on 48 and 60 nodes | **partial** | `e2e/builder-perf.spec.ts`, `benchmarks/perf/canvas.json` |
| 9 | `[data-theme="light"]`, 16 baselines | **met** | `tests/studioTheme.spec.ts` (13), `e2e/visual/builder-canvas.spec.ts` |
| 10 | a new document opens clean | **met, one reading** | `tests/builderTemplates.spec.ts` (10), `e2e/builder.spec.ts` |
| 11 | attach by drop, one undo step | **met** | `tests/builderCanvas.spec.ts` (76) |
| 12 | every binding declared as data | **met** | `tests/shortcutSheet.spec.ts` (9) |
| 13 | `--project=mobile` green | **met** | `e2e/mobile.spec.ts` (4) |
| 14 | `vitest` and `vue-tsc` exit 0 | **met** | 1318 passed in 70 files; `vue-tsc -b --force` exit 0 |

### Criterion 8 is a measurement, and the budget is missed

Measured on this machine, 2026-09-04, written by the spec itself to
[`benchmarks/perf/canvas.json`](../../benchmarks/perf/canvas.json). Four cases,
two of which are controls:

| case | mean | p95 | max | frames |
| --- | ---: | ---: | ---: | ---: |
| `idle48` — 48 nodes, no gesture | 16.666 | 16.70 | 16.80 | 361 |
| `gesture1` — ONE node, same gesture | 16.849 | 16.80 | 33.40 | 365 |
| `fixture48` — 48 nodes, the gesture | **16.846** | **16.80** | 33.40 | 370 |
| `client60` — 60 nodes, the gesture | **16.846** | **16.70** | 33.40 | 370 |
| budget | ≤ 16.70 | ≤ 20 | | |

**p95 is met on both cases with 3.2ms of headroom. The mean is missed, by
0.15ms on this run and by 0.01ms to 0.15ms across five**, and the budget is NOT
widened and the test is NOT tuned: both mean assertions are red.

Read the three middle rows together, because they are the finding. An IDLE
48-node canvas sits on the floor exactly - 16.666, max 16.80, not one late
frame. The same gesture over ONE node reports 16.849. The same gesture over 48
reports 16.846 and over 60 reports 16.846. **Graph size contributes nothing
measurable**; the whole of the overrun is the scripted input.

Where the time goes, which is the part worth having. A 60Hz display makes the
floor 1000/60 = **16.667ms**, so a 16.7 budget allows 0.033ms per frame — over
370 frames that is less than one late frame. The measured miss is two or three
frames per 370 taking two vsync intervals (max 33.3-33.4ms, exactly double).

`gesture1` is what identifies them. It is the identical scripted gesture at the
identical cadence over a canvas with ONE node — the same number of CDP round
trips, roughly a fiftieth of the canvas work — and it is just as late as the
48-node case. The late frames belong to the harness driving the input, not to
the graph. The canvas's own cost at 48 and at 60 nodes is not measurable above
that floor on this machine.

`instrumentCheck` is what makes any of this mean anything: a deliberate 300ms
block on the main thread reports as a single ~350ms frame against a 16.8ms
maximum everywhere else. An instrument that read the same number whatever
happened would make every other row here furniture.

### Two readings, stated

**Criterion 10, "one `input` node AND zero problems".** Only one shape satisfies
both. Measured against this build's own `/api/builder/validate`:

```text
one input alone           -> 1 problem, `no-output-node` (warning)
input + output + the edge -> 0 problems
```

So "one input node" is read as *exactly one node of kind `input`* — true of both
shapes — and the zero is taken literally. `BLANK` seeds the run's two ends,
wired, at (100, 100) and (100, 300). `no-output-node` is the server saying a
completed run hands back no body, and seeding the output invents no more of a
decision than seeding the input did: `document.py` gives `input` no target port
and `output` no source port precisely because they are the two ends every
compiled graph has.

**Criterion 5's fourth class.** `types/builder.ts` says `target_port` decides an
edge's class *alone*, and D4's own table marks `error` as the exception —
`(source port `error`)`. `edgeClassOf` reads both fields OF THE EDGE and never
looks up what kind the source node was, which is what the settled contract is
protecting. Four classes, mutually exclusive by construction.

### What was changed outside this plan's own files, and why

- `data/builderTemplates.ts` — D7's seed. Named by criterion 10.
- `composables/useBuilderDocument.ts` — `EdgeEnds.target_port` is optional, and
  `edgeOptionsFor` moved here out of `BuilderView`'s setup so criterion 11 can
  drive the real store through the real adapter. An adapter that exists only
  inside a component is an adapter no test can exercise.
- `composables/useBuilderHotkeys.ts` — the `theme` binding, which criterion 12
  names.
- `components/builder/DocumentBar.vue` — D6's toggle.
- `components/builder/BuilderView.vue` — the theme wiring, the edge-delete
  handler, and `NARROW_VIEWPORT_PX`: below 640px both rails start CLOSED,
  because open-by-default at 390 means the first thing a reader sees is the
  inspector covering the whole graph (measured at 390x792 over an invisible
  canvas).
- `src/studio.css` — D9's 640px block, and four literals that became tokens.
- `benchmarks/perf/canvas.json` — criterion 8 names the path.
- `frontend/tests/fixtures/perf48.json` — criterion 8 names the path.

### Three defects a browser found that no unit test could

1. **Playwright's default colour scheme is `light`.** The moment D6 landed the
   whole suite silently began asserting against the light palette. Found by an
   assertion reading `rgb(138, 90, 0)` where it expected `rgb(255, 224, 130)` -
   the same token, the other palette. `colorScheme: 'dark'` is now stated in
   `playwright.config.ts`.
2. **`.graph-workspace` leaves its single column implicit, and an implicit
   column is `auto`** - which resolves to its content's MIN-CONTENT width. At
   390px the canvas rendered **802px** inside a 390px workspace, clipped rather
   than scrolled, so nothing said so and every fit was computed against a box
   twice the width of the phone. This is `.studio-main`'s own `min-height: 0`
   lesson, one axis over.
3. **The application chrome was four hardcoded darks** - `.studio-shell`,
   `.app-header`, the two canvas-heading fades and Vue Flow's controls bar. The
   light theme found all four at once: cards went white, text went dark, and
   those four surfaces stayed black, so the palette rendered dark text on a dark
   tile. All four are tokens now.

### Known limitation, recorded rather than hidden

D6 rules that accents and kind gradients are SHARED between themes, and
`tokens.css` obeys it. The accents were chosen against a `#1a1a1a` ground and
are pale pastels, so wherever one is used as SMALL TEXT on a light surface —
`.canvas-kicker`, the palette's `PALETTE` heading, `Ready to publish`, the
inspector's `GRAPH` kicker — it is thin. Nothing is unreadable and nothing
moves.

Fixing it properly means a second token per accent (identity, and on-surface
text) and swapping the text sites over. Measured 2026-09-04:
`color: var(--accent-cyan|mint|blue)` and `--link-cyan` appear at **109 sites
across 32 files**, most owned by other plans. That is a change to make
deliberately in one pass, not as a side effect of a canvas plan.

`--link-cyan` itself DID move, and the line is what a token is for rather than
what it looks like: it is a link colour in the same family as `--warn-text` and
`--err-text`, which also moved. It is read, so it has to be readable.

### Not done

- **D4's `!` chip at an error edge's midpoint.** The class, the stroke and the
  arrowhead are all there and pinned; the chip is not. No criterion names it.
- **D9's "drop is disabled at 390px".** HTML5 drag-and-drop does not fire from a
  touch drag anyway, so the gesture is already unavailable rather than
  explicitly refused. Criterion 13 does not name it.

CONTRACT REQUEST for 12 / 00 C8: warning code `attachment-unattached` (an
attachment node with no attach edge). Proceeding as if granted — a drop that
misses every card creates an unattached node deliberately, because an author may
be laying out before wiring, and a sentence they can read beats a refused drop.

CONTRACT REQUEST for 03 / 00 C2: `vocabulary.target_ports`. Until it is served,
`useBuilderCanvas.TARGET_PORTS_BY_KIND` is a client-side mirror of a server
table that does not exist - `document.py` has `TARGET_PORTS`, the three legal
strings, and does not say which kind offers which. It is written beside
`isValidConnection`, the one function that consumes it, rather than in
`nodeKinds.ts`, whose mirror `nodeKinds.spec.ts` proves against the Python at run
time: putting an unprovable table in the provable file is how a mirror stops
being a mirror. Delete it when the vocabulary carries the real one.

Open decision for the owner: none.
