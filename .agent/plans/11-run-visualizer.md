# 11 — Run Visualizer (ChatDev choreography)

Written 2026-09-02 against `25634c0`. Owner: S6. Consumes C6 (frames, owned
by 10), C1 (document, owned by 03), C9 (templates, owned by 14). This file
adds motion to the run console that already exists; it does not build a
second run view.

## References — the motion spec comes first

Everything below is measured from `D:\ChatDev-main` (ChatDev **2.0**, Vue 3 +
Vue Flow — `docs/chatdev-notes.md` §0) and is the reference a critic scores
against for rubric dimensions 7–10. Paths relative to `D:\ChatDev-main`.

| Effect | Trigger | Timing | Easing | Source |
| --- | --- | --- | --- | --- |
| Idle agent | default | static frame `1`, stance `D` | — | `frontend/src/components/WorkflowNode.vue:32-84` |
| Active agent gait | `NODE_START` | `setInterval` 500 ms, frames 2↔3 | step | `WorkflowNode.vue:32-84` |
| Active node card | `.workflow-node-active` | `node-glowing 4s` + `node-pulse 2s`, both infinite, different periods | `linear` + `ease-out` | `frontend/src/utils/vueflow.css:81-125` |
| Active node scale | ditto | `scale(1) → 1.02 → 1` | — | `vueflow.css:81-125` |
| **Idle recede** | **none in the reference** | — | — | absent |
| **Agent→agent handoff** | log line `Edge condition met for A -> B` | sprite walks the real path, `clamp(pathLength × 0.02, 2000, 4000)` ms | linear, `requestAnimationFrame` | `frontend/src/pages/LaunchView.vue:1995-2093` |
| Handoff gait | ditto | 250 ms/frame, `1→2→1→3` | step | `LaunchView.vue:2066-2075` |
| Handoff facing | ditto | `endPoint.x >= startPoint.x ? 'R' : 'L'` | — | `LaunchView.vue:2044` |
| Node hover | mouseenter | `all 0.3s cubic-bezier(0.4, 0, 0.2, 1)`, `translateY(-2px)` | Material standard | `vueflow.css:20-31` |
| Edge hover recolour | mouseenter | `stroke 120ms ease` | `ease` | `frontend/src/components/WorkflowEdge.vue:110-128` |
| Notification in | any log | `slideIn 0.3s ease-out`, `translateY(-10px→0)` | `ease-out` | `LaunchView.vue:2734-2743` |
| Dialogue bubble | `NODE_END` | **instant** — no reveal | — | `LaunchView.vue:948-976` |
| Thinking bubble | `MODEL_CALL`/`TOOL_CALL` `before` | `bubbleGlow 3s ease-in-out infinite alternate` | `ease-in-out` | `LaunchView.vue:2817-2832` |
| Tool chip in/out | ditto | `all 0.22s ease-out`, `translateY(4px→0)` | `ease-out` | `LaunchView.vue:2872-2913` |
| Elapsed timer | run active | `setInterval` 1000 ms | — | `LaunchView.vue:696-701` |
| Launch button ready | `shouldGlow` | `glowPulse 3s` + `gradientShift 6s` | `ease-in-out` | `LaunchView.vue:3021-3056, 3588-3603` |
| Input awaiting you | `waiting_for_input` | `borderPulse 4s ease-in-out infinite alternate` | `ease-in-out` | `LaunchView.vue:2143-2166` |
| Entrance / stagger | **none on the graph** | fixed grid, one `fitView` | — | `LaunchView.vue:1712-1746` |
| Landing background | page load | 80 cubes, **negative delays `-0…60s`** | linear | `frontend/src/pages/HomeView.vue:11-22` |

Reference captures: `assets/launch.gif` (4.1 MB, primary),
`frontend/public/media/run.gif`, `complex_run.gif`. They stay in
`D:\ChatDev-main`; `benchmarks/reference/chatdev/` holds our own captures of
them at the gauntlet's crops.

## Problem

The run console narrates the fixed validator and cannot narrate a graph a
user drew:

- **No dialogue.** `ChatRail.vue` (203 lines) is a `role="log"` list whose `message` is the backend's one-line frame text verbatim (`useValidatorRun.ts:987-997`); a `CallChip` carries only a model or tool name and a duration (`:1004-1015`). Stream chunk frames are dropped outright (`useValidatorRun.ts:973`). No prompt, no response, no tool argument is rendered anywhere except `details.query` on the running card (`:978-985`).
- **No handoff.** `WorkflowEdge.vue:21-51` marches a dashed overlay while an edge is `active`; nothing travels from one agent to the next, and no frame says a handoff happened.
- **No phase for a builder graph.** `CREW_STAGES` hardcodes seven stages over thirteen validator node ids (`crewStages.ts:60-114`); `assertStageCoverage` (`:124-168`) fails for any graph that shares none of them, and `CrewProgress` then hides itself entirely (`CrewProgress.vue:44-56`). A published graph runs with no progress strip.
- **Emphasis without recession.** The running card gets `node-glowing` + `node-pulse` (`node-card.css`, asserted by `e2e/visual/run-canvas.spec.ts:198`); idle cards do not recede, so in a 16-node run the active speaker is one glow among fifteen identical cards.
- **No launch sequence.** Launch flips `status` and the first frame repaints a node; nothing announces that a run began.
- **Characters are not stable.** Every card is the same brand gradient at rest (`node-card.css:53-84`); identity is the label at ~7 px at the default fit (`CrewProgress.vue:2-19`).

## Scope

Motion and narration for both the validator and any published builder
graph, in `StudioView.vue`, `WorkflowNode.vue`, `WorkflowEdge.vue`,
`CrewProgress.vue`, `ChatRail.vue`, `useValidatorRun.ts`, plus three new
files: `DialogueRail.vue`, `HandoffToken.vue`, `useRunChoreography.ts`, and
`assets/styles/motion.css`. Light and dark. Reduced motion. The capture
recipe and the rubric 7–10 gate.

## Out of scope

- A second run view, a run mode inside the builder canvas, or any change to `BuilderCanvas.vue` (S2 / S7 own those; the test panel in 13 hands off to this console the way publish does — `data/builderRunHandoff.ts:31-66`).
- Third-party sprites or characters. `frontend/tests/builderCardDesign.spec.ts` asserts no `/sprites/` and stays. CLAUDE.md §14 records the adoption and reversal; the design commission for owned characters is an open decision (Status).
- Replay pacing of a finished run (frames replay as fast as the socket allows, as the reference does — `docs/chatdev-notes.md` §3). A settled-state render is the target for replay; live pacing applies to live runs only.
- Changing what the backend emits. C6 is owned by 10; this file consumes it.

## Design

### D1 — Persistent characters: identity is kind + a stable colour, and it is ours

A node's character is its per-kind lucide icon (already on the card,
`WorkflowNode.vue:69-75`) inside a 34 px medallion coloured from a
twelve-entry palette declared in `motion.css` as
`--character-1 … --character-12`, chosen by a deterministic hash of the node
id (`useRunChoreography.ts::characterIndex(nodeId)`, FNV-1a mod 12 — no
`Math.random`, no session state). The same index colours the node's
medallion on the card, its avatar in `DialogueRail`, its `HandoffToken`, and
its stage chip, so one agent is one colour everywhere. The reference assigns
characters randomly without replacement and its chat avatars never match the
graph because the chat path omits the node id (`LaunchView.vue:960`,
`spriteFetcher.js:22-53`); this is the first of the two reference defects we
fix rather than copy.

The medallion mounts into `.node-crew-slot`, the empty 34 px box the design
canvas already reserves (`docs/flow-builder-spec.md` §5.7), so the run
console adds no reflow to a card the author was just looking at.

### D2 — Active-speaker emphasis, and idle recede

Active = the reference's dual-period pair, already in `node-card.css` and
pinned by the visual baseline: `node-glowing 4s linear infinite` +
`node-pulse 2s ease-out infinite`, `scale(1.02)`. Unchanged.

Idle recede is new and is the second reference defect fixed: while a run is
live (`status ∈ {running, waiting}`), every card that is not `running`,
`waiting` or `error` takes `.is-receded` — `opacity: .55; filter:
saturate(.6)` with `transition: opacity var(--motion-medium) var(--ease-out),
filter var(--motion-medium)`. A completed card recedes too; its `✓` state
chip stays at full opacity so completion still reads. The recede lifts on the
terminal `RUN_STATE` frame. Reduced motion keeps the recede (it is a static
style, not an animation) — legibility is not motion.

The `error` card never recedes and never glows: it takes `--gradient-danger`
and a static red ring, because a pulsing error is noise.

### D3 — Message passing: a token walks the real edge on an `edge_traversal` frame

On `edge_traversal {from, to, port}` (C6), `HandoffToken.vue` injects an SVG
`<g>` into the traversed edge's own `<svg>`, positioned by
`path.getPointAtLength(t × length)` over `clamp(pathLength × 0.02, 2000,
4000)` ms, **linear**, driven by `requestAnimationFrame` — the reference's
mechanism verbatim (`LaunchView.vue:2044-2075`), minus the sprite: the token
is the **source** node's medallion (icon + character colour) at 24 px, with a
4 px trailing dash in the same colour so direction reads even at 50 % zoom.
Facing is irrelevant without a sprite and is dropped. The token is removed
from the DOM on arrival, and the target card's medallion takes a single
120 ms `scale(1) → 1.15 → 1` receipt pulse.

What the reference does that we refuse: it triggers the walk by regex-matching
a human-readable log line (`LaunchView.vue:1974`), which PRD §8.5 already
named the most fragile thing in DevAll. Ours consumes a structured frame; if
no `edge_traversal` frame arrives the edge falls back to today's dashed march
(`WorkflowEdge.vue:42-51`) and nothing regresses.

Concurrency bound: at most **one** token in flight per edge; a second
`edge_traversal` on an edge whose token is still walking completes the first
instantly. Across the graph the bound is `MAX_FANOUT_WIDTH = 4`
(`config.py:1828`) simultaneous tokens, which is the most the topology can
emit at once.

### D4 — Phase progression: a stage lane from `stage` frames, the boat for the validator

`useValidatorRun.ts` gains a `stages` ref filled from the `stage` frames
(C6: `{index, of, label, node_ids[]}`, one per topological layer, all emitted
at kickoff so the lane paints before the first node runs). `CrewProgress.vue`
takes its stage list from `stages` when non-empty and from `CREW_STAGES`
otherwise — `assertStageCoverage` runs only on the `crewStages.ts` path, so
the strip no longer hides itself for a published graph (`CrewProgress.vue:44-56`).

The validator keeps the rowing boat, the three named oars and the lap banner
(`CrewProgress.vue:66-174`) unchanged; the visual baseline covers it. A
builder graph gets the same lane with the hull replaced by the active stage's
character medallions (one per running node, max 4) sliding along the track —
same `boatPercent` maths (`:66-73`), same `stageProgress` severity order
(error > waiting > running > completed, `crewStages.ts`), same `×N` lap chip.
Phase labels are the stage `label` from the frame; node ids in the stage
drive the per-node pips exactly as the validator's `branchLabels` do today.

### D5 — Dialogue: progressive reveal, bounded, in a rail that stays legible at step 20

`DialogueRail.vue` replaces the trace list's role for model output while
`ChatRail.vue` keeps the trace (kicker, tool chips, warnings). One
`DialogueEntry` per `utterance` frame (C6): avatar medallion, `agent_role`,
`task_name`, the text, token counts, timestamp.

Reveal rule, in `useRunChoreography.ts`:

1. When `details.stage='chunk'` frames arrive for a `call_id`, they append to a pending entry as they come — real streaming, no artificial pacing. Today these frames are dropped at `useValidatorRun.ts:973`; that branch is removed.
2. When only the `utterance` arrives (no chunks), the text is revealed at **120 characters per second** in `requestAnimationFrame` batches — a 4,096-character utterance takes 34 s, which is the bound on how far the rail can lag the graph.
3. Catch-up: if more than **two** utterances are pending, every pending entry except the newest is dumped whole. The rail never falls more than two speakers behind the canvas.
4. Entries older than the last **three** collapse to a one-line header (avatar, role, first 80 characters) with a disclosure — the reference's `CollapsibleMessage.vue` pattern, ours keyed on recency rather than length.
5. `truncated: true` renders a *"trimmed to 4,096 characters"* note; the full text is in the run's NDJSON log export, which already exists.

The reference reveals nothing — a bubble lands whole at `NODE_END`
(`docs/chatdev-notes.md` §2). Rule 2 is the difference the critic will see in
a recording.

### D6 — Launch sequence

On `launch()`:

1. The Launch control takes `.is-armed` — the reference's `gradientShift 6s ease-in-out infinite` gradient plus `glowPulse 3s` ring, lifted verbatim (`LaunchView.vue:3021-3056`); it is the one glow vocabulary, and the gate card's textarea takes `borderPulse 4s alternate` on `WAITING` for the same reason (`:2143-2166`).
2. On the first `RUN_STATE` frame every card takes `.is-landing` once (already declared in `node-card.css`, asserted in reduced-motion by `builder.css:871-880`) with a **negative animation delay** per card of `-(index × 40) ms` over a 480 ms `ease-out` settle, so a 16-node graph reads as already-in-motion on the first paint rather than popping in — the `HomeView.vue:11-22` technique applied once, not forever.
3. The stage lane paints from the `stage` frames (D4) before any node runs.
4. The first `utterance` opens the dialogue rail if collapsed, the way `ReportPanel` opens itself for the first body (CLAUDE.md closed item 33) — keyed on run id so a relaunch re-arms.

### D7 — Alive, not noisy: the measurable bound

The design canvas is still (`docs/flow-builder-spec.md` §5.5), and the run
canvas is bounded:

| Surface | At rest | Live run | Bound |
| --- | --- | --- | --- |
| Node glow | none | running nodes only | ≤ `MAX_FANOUT_WIDTH` = 4 |
| Edge march | none | active edges only | ≤ out-degree of running nodes |
| Handoff token | none | one per traversed edge | ≤ 4 in flight |
| Dialogue reveal | none | one pending reveal | catch-up beyond 2 |
| Elapsed clocks | none | running nodes | 1 Hz, ≤ 4 |
| Lane medallions | none | active stage | ≤ 4 |
| Launch glow | none | until first frame | 1 |
| Error ring | static | static | — |

`useRunChoreography.ts` exposes `liveAnimationCount` and a Vitest spec
asserts it never exceeds **12** across a replayed 30-frame fan-out fixture.
No infinite animation runs on a canvas whose run is terminal; the terminal
`RUN_STATE` frame lifts the recede, stops the clocks, and leaves the lane and
the rail as a settled record.

### D8 — Light theme and reduced motion

`[data-theme=light]` overrides land in `tokens.css` (S2, plan 02); this file
adds only the motion-specific tokens — `--character-1…12`, `--recede-opacity`,
`--handoff-trail` — in `motion.css` with light values beside dark. Every
keyframe here is named in `motion.css`'s reduced-motion block the way
`node-card.css:268` and `builder.css:871-880` already name theirs; the global
sledgehammer in `studio.css:306-314` covers the rest. Under reduced motion the
handoff token is placed at the target instantly and the dialogue dumps whole.

### D9 — The visual baseline is a contract, not a nuisance

`e2e/visual/run-canvas.spec.ts` screenshots the validator idle, mid-branch
and paused, and asserts the running animation names
(`['node-glowing','node-pulse']` etc., `:198`). This file changes the
validator's appearance in exactly two ways — the receded idle cards and the
medallion in the crew slot — so the three baselines **will** change. They are
re-baselined in their own commit whose message names both reasons, and never
in the same commit as a behavioural change.

## Interfaces

**Consumed** (owned elsewhere; this file does not alter them):

- **C6** (10): `utterance`, `edge_traversal`, `node_error`, `retry`, `stage`, and forwarded `chunk` frames, shapes as in 00's index.
- **C1** (03): node kinds for the medallion icon map; `NODE_KINDS[kind].icon`.
- **C9** (14): the templates the captures are taken on.

**Owned** — component and composable surfaces inside S6's files:

```ts
// useRunChoreography.ts
export function characterIndex(nodeId: string): 1|2|…|12          // FNV-1a mod 12
export interface Handoff { edgeId: string; from: NodeId; to: NodeId; startedAt: number }
export interface DialogueEntry { callId: string; nodeId: NodeId; role: string; task: string;
  text: string; revealed: number; truncated: boolean; tokens: {prompt: number; completion: number};
  at: number; collapsed: boolean }
export function useRunChoreography(run: ValidatorRun): {
  handoffs: Ref<Handoff[]>; dialogue: Ref<DialogueEntry[]>; stages: Ref<Stage[]>;
  isReceded(nodeId): boolean; liveAnimationCount: ComputedRef<number>; armed: Ref<boolean> }
```

`WorkflowNode.vue` gains props `character: number` and `receded: boolean`;
`WorkflowEdge.vue` gains a `handoff?: Handoff` prop and renders
`HandoffToken` inside its `<svg>`; `CrewProgress.vue` gains `stages?: Stage[]`
and falls back to `CREW_STAGES` when absent.

## Acceptance criteria

1. **Characters.** `characterIndex` is pure and deterministic — `frontend/tests/runChoreography.spec.ts` asserts the same id yields the same index across 1,000 calls and that the 16 validator-template ids spread over ≥ 8 distinct colours. Rubric 9.
2. **Same colour everywhere.** A Playwright step on the synthetic backend reads the computed medallion colour on a running card, its dialogue avatar, and its handoff token, and asserts all three equal. Rubric 9.
3. **Idle recede.** In `e2e/visual/choreography.spec.ts`, mid-run, every non-running non-error card has `opacity` ≈ 0.55 and the running card has 1.0; after the terminal frame every card is 1.0. Rubric 10.
4. **Handoff.** With `SYNTHETIC_BRANCH_DELAY_SECONDS=5`, an `edge_traversal` frame produces a token whose bounding box moves monotonically along the edge and is removed within 4,100 ms; the target medallion's receipt pulse fires once. Recorded with Playwright `video: 'on'` for the critic. Rubric 7, 9.
5. **No regex trigger.** `grep -rn "Edge condition met" frontend/src` returns nothing. Rubric 9.
6. **Phase lane on a builder graph.** Launching the `sequential-pipeline` template (C9) shows a lane with three stage chips that advance in order; `CrewProgress` is visible for the whole run (today it is hidden — `CrewProgress.vue:44-56`). Rubric 10.
7. **Validator unchanged.** Launching the validator still shows the boat, three named oars and the lap banner; `e2e/visual/run-canvas.spec.ts` passes after its one re-baseline commit. Rubric 10.
8. **Progressive dialogue.** A Vitest spec feeds a 1,200-character `utterance` with no chunks and asserts `revealed` climbs at 120 ± 10 chars/s; feeding three utterances at once dumps the first two whole. Rubric 10.
9. **Chunks are no longer dropped.** `useValidatorRun.ts` has no branch discarding `stage === 'chunk'`; a spec feeds five chunks for one `call_id` and asserts one entry with the concatenated text. Rubric 10.
10. **Launch sequence.** On Launch the control carries `gradientShift` and `glowPulse`; on the first frame each card's `animation-delay` equals `-(index × 40) ms`; both assertions by `getComputedStyle` in Playwright. Rubric 7.
11. **Alive-not-noisy bound.** The `liveAnimationCount` spec never exceeds 12 on the 30-frame fan-out fixture, and equals 0 after the terminal frame. Rubric 10.
12. **Reduced motion.** Under `prefers-reduced-motion: reduce` the token appears at the target within one frame and the dialogue reveals whole; `e2e/visual/run-canvas.spec.ts:247` still passes. Rubric 10.
13. **Light and dark.** `benchmarks/ours/` contains, at 1440×900 and 390×844, light and dark: empty, one node, the largest admissible graph, running, errored — twenty PNGs named `<state>-<theme>-<w>x<h>.png` — plus `handoff.webm`. Rubric 7–10 capture.
14. **Reference comparison.** `benchmarks/reference/chatdev/` holds crops of `assets/launch.gif` at the same states; the critic scores blind; any dimension where the reference scores higher is logged in `benchmarks/DEFECTS.md` and the gate does not pass with one open. Rubric 7–10.
15. **Error is legible.** A `node_error` frame turns the card red with the message inline on the card (not only in the rail); the card does not glow or recede. Rubric 12 (shared with 12).

## Status

**Planned · 2026-09-02.**

Contract requests for 00: none — every consumed shape is in C6 as written.
One assumption to confirm with 10: the `stage` frames are emitted **one per
layer, all before the first `NODE_START`**; if 10 emits them lazily the lane
paints late and D4's "before the first node runs" moves to acceptance
criterion 6's failure list.

Open decisions for the owner:

1. **Character art.** D1 ships icon medallions. Real characters need art this project owns — a commission, not a download. Decide whether to commission before or after the gauntlet.
2. **The largest-graph capture.** The gauntlet asks for a 30-node state; `MAX_GRAPH_NODES = 24` (`config.py:1768`). The capture uses 24 flow nodes plus 6 attachment nodes on the assumption (03) that attachments are not counted by that bound. If 03 counts them, the state is 24 and the criterion says so.
3. **Re-baseline timing.** D9 re-baselines the validator's three screenshots once. If the owner prefers the validator pixel-identical, D2's recede and D1's medallion are gated behind a builder-graph-only class and the validator keeps its current look.
