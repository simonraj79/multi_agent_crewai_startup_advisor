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

### Owner decisions answered — 2026-09-04

**Decision 4 — icon medallions.** ChatDev's own sprites were already sourced,
downscaled, rendered on every node and then deleted: 132 of the 144 frames could
never paint because nothing writes a design-time run state, and the art belongs
to the competitor this product argues against (CLAUDE.md remaining-work item 6).
`.node-crew-slot` already reserves the box.

**Decision 20 — re-baseline the validator's three screenshots once.** Two code
paths for one card is the quietly-divergent double this repository keeps warning
about.

### Built - 2026-09-04

Fourteen of the fifteen criteria met; criterion 14 is the Integrator's judge
round and was not attempted. The run console now says who is speaking, what
walked which edge, what phase the run is in and what failed - for the validator
and, for the first time, for a graph somebody drew.

| n | state | evidence |
| ---: | --- | --- |
| 1 | **met** | `frontend/tests/runChoreography.spec.ts` (38) - pure across 1,000 calls; the 16 template ids spread over **11** distinct colours, measured against `builderValidatorTemplate.json` |
| 2 | **met** | `e2e/visual/choreography.spec.ts` "one agent is one colour on the card, in the rail and on the token" - resolved `background-color`, medallion == dialogue avatar |
| 3 | **met** | same file, "steps every other card back mid-run and lifts on the terminal frame" - idle 0.55, waiting 1.0, every card 1.0 after the terminal frame |
| 4 | **met** | same file, "a token walks the edge and is gone inside its own bound" - monotone in x AND y over three samples, removed inside 4,100 ms. Recording: `e2e/capture-handoff.spec.ts`, `test-results/capture-handoff-*/video.webm` |
| 5 | **met** | `grep -rn "Edge condition met" frontend/src` -> exit 1, nothing. The phrase is deliberately not written anywhere under `src/`, including in the comment that explains the refusal |
| 6 | **met** | `e2e/published-run.spec.ts` (2) - `sequential-pipeline` published through the dialog and run through the console: the lane is absent before launch, paints from the plan frames, shows at least 3 chips, the current index never falls and does leave the first stage, and it stays visible for the whole run |
| 7 | **met** | `e2e/visual/run-canvas.spec.ts` 3/3 after its one re-baseline commit (`7060af5`); `frontend/tests/stageLane.spec.ts` "the validator is unchanged" keeps the boat, the three named oars and the lap banner |
| 8 | **met** | `runChoreography.spec.ts` - 1,200 chars reveals at 120 +/- 10 per second, driven through `advanceReveal` at exact ms boundaries; three at once dumps the first two whole |
| 9 | **met** | same file - five chunks for one `call_id` concatenate to one entry; `runConsoleChoreography.spec.ts` proves the frame reaches it through the real composable |
| 10 | **met** | `e2e/visual/choreography.spec.ts` "the control glows from the press, and the cards land staggered" - `animation-delay` 0s / -0.04s / -0.08s / -0.12s by `getComputedStyle` |
| 11 | **met** | `runChoreography.spec.ts` "never exceeds twelve across a thirty-frame fan-out" and "is zero once the run is terminal"; `e2e` "no card animation runs on a canvas whose run is over" |
| 12 | **met** | `e2e/visual/choreography.spec.ts` "keeps the recede, drops the movement"; `run-canvas.spec.ts`'s own reduced-motion leg still passes |
| 13 | **met** | `e2e/capture-run.spec.ts` - **20 PNGs** written to `benchmarks/ours/11/`, `<state>-<theme>-<w>x<h>.png` over empty, one-node, largest, running and errored, times light/dark, times 1440x900/390x844, plus the webm above. Gitignored by the global `*.png` rule, as `benchmarks/README.md` intends |
| 14 | **not this session's** | the blind reference comparison is the Integrator's judge round |
| 15 | **met** | `frontend/tests/nodeChoreography.spec.ts` (16) - the message on the card, `data-testid="node-error-message"`, clipped at 120 chars with the whole of it in `title` and in the aria label; `e2e` proves the card neither glows nor recedes and takes a static red ring |

Plus the two other plan-12 surfaces that live in this plan's files:

| plan 12 | state | evidence |
| --- | --- | --- |
| D6 | **met** | `runConsoleChoreography.spec.ts` - `data-testid="rerun-from-here"` on the failed node of a TERMINAL run only, POSTs `resume_from {run_id, node_id}` through `studioApi.resumeRun`, follows the new run, and surfaces the server's refusal; a `replayed: true` node draws dimmed and says REPLAYED |
| D7 | **met** | `data-testid="stream-reconnecting"` reads exactly `reconnecting - N steps kept`, N being the frames APPLIED; the existing recovery path is untouched and `e2e/studio.spec.ts`'s reload test still passes |

#### Measured, 2026-09-04, in this worktree

```text
Python          2257 run - 0 failures - 6 skipped - 147.5 s   (baseline 2243)
Frontend unit   1567 passed in 80 files                       (baseline 1468 in 74)
vue-tsc -b --force   exit 0
npm run build        1981 modules, 730 ms
E2E             88 passed in 7.0 min, ALL files, both projects
                (E2E_API_TARGET=http://127.0.0.1:8098, E2E_UI_PORT=5274,
                 SYNTHETIC=1, SYNTHETIC_BRANCH_DELAY_SECONDS=5)
```

**This plan spent $0.00.** Every launch is against `SYNTHETIC=1`, which replaces
the crew factories and nothing else.

New specs: `runChoreography` 38, `nodeChoreography` 16, `stageLane` 13,
`dialogueRail` 12, `runConsoleChoreography` 11, `handoffToken` 9;
`tests/service/test_synthetic_choreography.py` 14; four E2E files
(`visual/choreography` 9, `published-run` 2, `capture-run` 1, `capture-handoff` 1).

#### The backend change this needed, and why it was allowed

`SYNTHETIC=1` replaces only the crew factories, so three of the five C6 shapes
already reached a published builder graph on the free path. **Two did not, and
both were the same defect this repository has now recorded four times: a double
that cannot produce the thing under test certifies nothing.**

* `SyntheticValidatorRunner` emitted no `edge_taken` and no `llm` frame of any
  kind, so the console's edge march and its whole dialogue surface were
  unobservable on the only path a test, an E2E run or a local session can use.
* `_SyntheticCrew` calls no model, so a published graph said nothing either.

Both now emit, every field mirrored from its production emitter and named in
`tests/service/test_synthetic_choreography.py`. **No paid path was touched.**
The predecessor of a traversal is NAMED at each call site rather than inferred
from whichever node finished last, because that rule reports
`research_market -> research_sentiment` at the fan-out - an edge the graph does
not draw, and the exact pair `events/adapter.py::_traversal_for` refuses by
consulting `NodeRegistry.edges`.

Consequence, recorded rather than smoothed over: **21 rubric-11 goldens changed**
(`cea4cbd`). 520 insertions, **zero deletions**, every added line a
`FrameKind.LLM` / `MODEL_CALL` frame on the author's own node id. The definition
and the result body are byte-identical, which is what says this changed the
narration and not the compile.

#### Departures from the plan, each stated rather than smoothed over

1. **`useRunChoreography` is a STORE frames are pushed into**, not
   `useRunChoreography(run: ValidatorRun)`. Taking the run would mean exposing a
   frame stream off `useValidatorRun` for one consumer to subscribe to - a
   second path through the same frames with its own ordering and replay
   semantics. There is exactly one place a frame is applied and that property is
   worth more than the signature.
2. **D4's precedence is inverted: `CREW_STAGES` wins over the frame stages**,
   not the other way round. Criterion 7 is the reason. A topological plan cannot
   know that the three research branches are one stage called Research with oars
   called Market, Signal and Build; it would emit them as one anonymous layer,
   which is true about the graph and a worse picture of the crew. In practice
   the two readings never disagree - `_emit_plan` lives on the BUILDER runner,
   so neither hand-written flow emits a plan at all - and the precedence is
   written down for the day one does.
3. **The dialogue rail is in the ACTIVITY column, not under the canvas.** It
   shipped as a fifth row of `.graph-workspace` first, and the measurement is
   why it is not one: opening on the first utterance took the Vue Flow container
   from 626px to 462px, mid-run, on the exact canvas the gauntlet captures. A
   surface whose job is narrating a run cannot pay for itself out of the run.
4. **The landing settle is on Vue Flow's node WRAPPER, not on the card.** Two
   reasons and either decides it: `.workflow-node.is-running` sets the
   `animation` shorthand, so an equal-specificity landing rule on the card would
   replace the whole list and cancel a running node's glow; and Vue Flow
   positions a node by writing `transform` onto that wrapper, so the keyframe is
   opacity-only rather than D6's translate.
5. **A dialogue entry's `role` comes from the node's AGENT frames, or falls back
   to its label.** The `utterance` frame carries neither role nor task - the
   real serializer writes seven keys and none of them is one - and adding them
   to the synthetic double would have taught the client to read a field
   production never sends.
6. **Criterion 13's `empty`, `one-node` and `largest` states are produced by
   stubbing `GET /api/workflows/{id}/graph`**, and `capture-run.spec.ts` says so
   at the top. They are facts about a GRAPH and this console draws whatever that
   endpoint hands it. `running` and `errored` are facts about a RUN and are not
   stubbed.

#### Three things the visual gate could not survive unchanged

The re-baseline commit (`7060af5`) carries three edits to
`e2e/visual/run-canvas.spec.ts` that are repairs rather than loosenings, and each
is a measurement worth keeping:

1. The handoff tokens are **masked**, as the elapsed clock has been since that
   file was written and for the same reason. A token's centre is rewritten every
   frame, so two consecutive captures never agree, `toHaveScreenshot` retried
   until its 15 s budget was gone, and the animation audit twenty lines below
   then ran against a fan-out that had finished.
2. The audit runs **before** the screenshot. `toHaveScreenshot` cancels infinite
   CSS animations to capture and what it restores is not dependable: measured,
   the card's glow came back and the state dot's `dot-pulse` did not, so the
   audit read an empty list on an element whose rule was intact - the exact
   false negative that audit exists to avoid producing.
3. It waits for `.workflow-node.is-running` rather than for `Market Analyst` by
   name. The synthetic runner walks the three branches in sequence at five
   seconds each, so naming one bounded every assertion to that branch's window.

#### Contract needs

**None.** Every consumed shape is in C6 as landed. The one assumption this plan
raised for 10 - that the `stage` frames are emitted one per layer, all before
the first `NODE_START` - is **confirmed**: `builder_runner._emit_plan` emits the
whole plan at kickoff, so the lane paints before anything has happened.

#### For the Integrator

* **New `data-testid`s, for the plan-12 and plan-13 agents:**
  `node-error-message`, `rerun-from-here`, `node-replayed`,
  `stream-reconnecting`, `node-character`, `handoff-token` (which also carries
  `data-edge`), `dialogue-list`, `dialogue-text`, `dialogue-avatar`,
  `dialogue-fold`, `dialogue-trimmed`, `dialogue-toggle`, `crew-medallions`,
  `launch-button`.
* **The resume client call is `studioApi.resumeRun(sessionId, sourceRunId,
  nodeId, workflowId, inputs, gates)`**, which POSTs
  `resume_from: {run_id, node_id}` to `POST /api/sessions/{id}/runs`. It refuses
  outright in mock mode. `StudioApiLike` gained the method, so every double must
  too - `tests/helpers.ts::FakeStudioApi` has it with a `resumeError` hook,
  because the interesting half of that control is the refusal.
* **`StudioNodeData` gained nine fields** - `character`, `receded`,
  `errorMessage`, `replayed`, `receiving`, `index`, `landing`, `nodeId` and
  `rerunnable`. Four spec files build that object by hand and were updated.
* **Files touched outside S6's list:** `frontend/src/components/ChatRail.vue`
  (one slot named `above` and a `.rail-slot` rule, so the dialogue rail has a
  home in the activity column), `frontend/src/components/StatusPanel.vue` (an
  `armed` prop and `data-testid="launch-button"` on the Launch control),
  `frontend/src/data/serverLimits.ts` (`MAX_NODE_CARD_ERROR_CHARS`, a client
  bound with the Python one named beside it), `frontend/tests/helpers.ts`,
  `src/brief_crew/service/runner.py` and `service/builder_runner.py` (the
  SYNTHETIC paths only), and `tests/builder/fixtures/rubric11/*` (regenerated).
* **`MAX_FANOUT_WIDTH` is respected without being read:** the lane shows at most
  four medallions and at most four tokens can be in flight, because that is what
  the topology can emit at once.

#### Follow-ups - pre-existing, outside this plan's surfaces, not fixed

1. **A published `sequential-pipeline` descriptor names an edge whose endpoints
   are not in its own node list.** Vue Flow logs
   `[Vue Flow]: Edge source or target is missing - Edge: e6, Source: search,
   Target: research` repeatedly while that graph is on the run canvas. The
   descriptor comes from `builder/descriptor.py`, so this is plan 09/10's
   surface rather than this one's. It is a console WARNING and not an error, so
   it does not fail the E2E's zero-console-errors gate - which is arguably the
   problem.
2. **`benchmarks/perf/canvas.json` is rewritten by `e2e/builder-perf.spec.ts` on
   every full E2E run**, so a full suite always leaves the tree dirty with a new
   `measuredAt`. It was reverted rather than committed here. Either ignore the
   file or have that spec write outside the tree.
