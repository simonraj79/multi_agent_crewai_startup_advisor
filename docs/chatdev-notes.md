# ChatDev notes — what the run-time reference actually does

Extracted on **2026-09-02** from `D:\ChatDev-main` by reading its source, not
from memory. Every path below is relative to that directory.

## 0. The headline: this is ChatDev 2.0, and it is Vue

`D:\ChatDev-main` is **ChatDev 2.0 (DevAll)**, not the 1.0 Flask visualizer.
`README.md:1` reads `# ChatDev 2.0 - DevAll`; `README.md:19` says v1.x moved
to the `chatdev1.0` branch, and the directory has no `.git`, so 1.0 cannot be
checked out from it. There is no `visualizer/`, no `online_log/`, no
`CompanyConfig/Default/*.json`, no log-replay parser.

What exists instead is a **Vue 3 + Vue Flow single-page app** (`frontend/`)
driven by a **FastAPI WebSocket** (`server/`). That is the same stack as this
repository, which makes it a much closer reference than 1.0 would have been:
the choreography below is expressed in Vue Flow custom nodes and CSS, and
transfers almost verbatim.

Licence: **Apache-2.0**, plain (`LICENSE:1-3`, `pyproject.toml:6-9`). The 1.0
non-commercial addendum is not present.

## 1. Where the visualizer lives

| Piece | Path |
| --- | --- |
| Run view (the visualizer) | `frontend/src/pages/LaunchView.vue` (3,705 lines) |
| Agent node | `frontend/src/components/WorkflowNode.vue` |
| Edge | `frontend/src/components/WorkflowEdge.vue` |
| Node/edge CSS | `frontend/src/utils/vueflow.css` |
| Sprite assignment | `frontend/src/utils/spriteFetcher.js` |
| Palette | `frontend/src/utils/colorUtils.js` |
| Sprites | `frontend/public/sprites/` — 144 PNGs, `{character 1-12}-{stance D/L/R/U}-{frame 1/2/3}.png`, varying sizes (508×847 … 856×958), ~14 MB total, drawn at **32×40 px** |
| WebSocket route / session manager | `server/routes/websocket.py`, `server/services/websocket_manager.py` |
| Log entry schema | `utils/logger.py:40-62` |
| Event enum | `entity/enums.py:61-79` |

Sprites are assigned **randomly per node id**, not by role
(`spriteFetcher.js:22-53`): a character is drawn from an unassigned pool and
bound to the node for the session. This repository already sourced these 144
files, downscaled them, rendered them, and **removed them** — the art is the
competitor's, and nothing writes a design-time run state (CLAUDE.md §14,
"Sprites", and remaining-work item 6). The motion, not the art, is what to
take.

## 2. The motion spec — what actually moves

| Effect | Trigger | Timing | Easing | Source |
| --- | --- | --- | --- | --- |
| Idle agent | default | static frame `1`, stance `D` | — | `WorkflowNode.vue:32-84` |
| Active agent gait | `NODE_START` | `setInterval` **500 ms**, frames 2↔3 (2 Hz), still facing down | step | `WorkflowNode.vue:32-84` |
| Active node card | `.workflow-node-active` | `node-glowing 4s` **and** `node-pulse 2s`, both infinite, different periods so the shimmer never repeats | `linear` + `ease-out` | `vueflow.css:81-125` |
| Active node scale | ditto | `scale(1) → 1.02 → 1` | — | `vueflow.css:81-125` |
| **Idle recede** | **none** | — | — | absent everywhere |
| **Agent→agent handoff** | log line `Edge condition met for A -> B` | sprite walks the real edge path: `clamp(pathLength × 0.02, 2000, 4000)` ms | **linear**, `requestAnimationFrame` | `LaunchView.vue:1995-2093` |
| Handoff gait | ditto | 250 ms/frame, 4-beat contact cycle `1→2→1→3` | step | `LaunchView.vue:2066-2075` |
| Handoff facing | ditto | `endPoint.x >= startPoint.x ? 'R' : 'L'` | — | `LaunchView.vue:2044` |
| Node hover | mouseenter | `all 0.3s cubic-bezier(0.4, 0, 0.2, 1)`, `translateY(-2px)` | Material standard — the only custom curve in the repo | `vueflow.css:20-31` |
| Edge hover recolour | mouseenter | `stroke 120ms ease, stroke-width 120ms ease` | `ease` | `WorkflowEdge.vue:110-128` |
| Edge dash march | hover | dash 12 / gap 30, period `8000 × L/150` ms | `linear` | `WorkflowEdge.vue:182-214` |
| Notification in | any log | `slideIn 0.3s ease-out`: opacity 0→1, `translateY(-10px→0)` | `ease-out` | `LaunchView.vue:2734-2743` |
| Dialogue bubble | `NODE_END` | **instant** (`transition: all 0.2s ease` only) — no typewriter, no per-message fade | — | `LaunchView.vue:948-976`, `:2807` |
| Thinking bubble | `MODEL_CALL` / `TOOL_CALL` `before` | `bubbleGlow 3s ease-in-out infinite alternate` | `ease-in-out` | `LaunchView.vue:2817-2832` |
| Tool chip in/out | ditto | `all 0.22s ease-out`, opacity 0→1, `translateY(4px→0)` | `ease-out` | `LaunchView.vue:2872-2913` |
| Tool chip running / done | ditto / `after` | `loadingEntryPulse 2.6s ease-in-out infinite` / `opacity: 0.8` | `ease-in-out` | same |
| Elapsed timer | run active | `setInterval` 1000 ms | — | `LaunchView.vue:696-701` |
| Launch button idle | connected | `gradientShift 6s ease-in-out infinite` on a 3-stop gradient | `ease-in-out` | `LaunchView.vue:3588-3603` |
| Launch button ready | `shouldGlow` | `+ glowPulse 3s ease-in-out infinite` (`box-shadow 0 0 0 0 → 0 0 0 5px` fading) | `ease-in-out` | `LaunchView.vue:3021-3056` |
| Input awaiting you | `waiting_for_input` | `borderPulse 4s ease-in-out infinite alternate`, colour cycles `#aaffcd → #99eaf9 → #a0c4ff` | `ease-in-out` | `LaunchView.vue:2143-2166` |
| Entrance / stagger on the graph | **none** | fixed 5-column grid, one `setNodes` + `fitView({padding: 0.1})` | — | `LaunchView.vue:1712-1746` |
| Landing background | page load | 80 cubes, 40–70 s each, **negative delays `-0…60s`** so everything is mid-cycle on arrival | `linear` | `HomeView.vue:11-22, 138-181` |

The active-node keyframes, verbatim (`vueflow.css:81-125`):

```css
.workflow-node.workflow-node-active {
  animation: node-glowing 4s linear infinite, node-pulse 2s ease-out infinite;
}
@keyframes node-glowing {
  0%   { filter: hue-rotate(0deg) saturate(1) brightness(1); transform: translateZ(0) scale(1); box-shadow: 0 0 0 0 transparent; }
  50%  { filter: hue-rotate(180deg) saturate(1.6) brightness(1.25) drop-shadow(0 0 16px var(--node-shadow-color));
         transform: translateZ(0) scale(1.02); box-shadow: 0 0 20px 8px rgba(100,100,100,0.12); }
  100% { filter: hue-rotate(360deg) saturate(1) brightness(1); transform: translateZ(0) scale(1); box-shadow: 0 0 0 0 transparent; }
}
```

The handoff walk, verbatim (`LaunchView.vue:2044-2075`):

```js
const direction = endPoint.x >= startPoint.x ? 'R' : 'L'
const duration = Math.min(Math.max(pathLength * 0.02, 2000), 4000)
// … per frame:
const progress = Math.min(elapsed / duration, 1)
const point = pathElement.getPointAtLength(progress * pathLength)
spriteImage.setAttribute('transform', `translate(${point.x}, ${point.y})`)
const frameIndex = Math.floor(elapsed / 250) % 4        // 1 → 2 → 1 → 3
```

Palette (`colorUtils.js:15-60`): fifteen pastel three-stop gradients assigned
per node **type** by string hash with linear probing. Agent =
`linear-gradient(135deg, #a0c4ff, #99eaf9, #baf9b1)`; Human =
`#ff9b9b, #ffb876, #ffe59d`. Incoming edges warm (yellow→orange), outgoing
cool (cyan→turquoise), `strokeWidth: 1.4`; untriggered edges `#868686`
dashed `5,5`.

## 3. The wire format the visualizer consumes

Transport is a WebSocket (`ws(s)://<host>/ws`, reconnect with
`?session_id=<uuid>`, `LaunchView.vue:1503-1506`). No log polling. Envelope
`{ type, data }` with types `connection`, `session_resumed`,
`human_input_required`, `artifact_created`, `log`, `workflow_completed`,
`pong`, `error`.

A `log` payload (`utils/logger.py:40-62`):

```json
{ "timestamp": "…iso…", "level": "INFO", "node_id": "Programmer Coding",
  "event_type": "MODEL_CALL", "message": "…",
  "details": { "stage": "before" | "after", "model_name": "…", "tool_name": "…", "output": "…" },
  "execution_path": ["USER", "Chief Executive Officer", "…"], "duration": 1.23 }
```

`event_type` (`entity/enums.py:61-74`): `NODE_START`, `NODE_END`,
`EDGE_PROCESS`, `MODEL_CALL`, `TOOL_CALL`, `AGENT_CALL`, `HUMAN_INTERACTION`,
`THINKING_PROCESS`, `MEMORY_OPERATION`, `WORKFLOW_START`, `WORKFLOW_END`.
**There is no phase field**; `execution_path` is the nearest thing.

Client state machine (`LaunchView.vue:2237-2308`):

- `NODE_START` → push to `activeNodes` → gait + glow start.
- `MODEL_CALL` / `TOOL_CALL` + `stage` → `addLoadingEntry` / `finishLoadingEntry`, keyed `model-<name>` / `tool-<name>`.
- `NODE_END` → remove from `activeNodes`, then `addDialogue(nodeId, details.output)` — **the utterance lands only when the agent finishes.**
- message matching `Edge condition met for A -> B` → the handoff walk.

Replay on reconnect (`websocket_manager.py:100-111`) resends the whole buffer
as fast as the socket allows — no pacing — so every walk fires at once.
Sessions expire after 24 h.

This repository's own frame model (`src/brief_crew/events/`) already carries
the equivalent of every one of these: `NODE_START` / `NODE_END` as node
frames, `MODEL_CALL` and `TOOL_CALL` with `stage: before | after`, gate frames
for `human_input_required`, and a gapless `seq` cursor for replay. The
mapping in `.agent/plans/11-run-visualizer.md` is therefore frame-kind →
choreography, with two additions this repo must make: a bounded utterance
(the completed LLM response) and an explicit **edge-traversal** frame for the
handoff walk.

## 4. Phase structure — how 1.0's hierarchy survives in 2.0

`ChatChainConfig.json` / `PhaseConfig.json` / `RoleConfig.json` do not
exist. The chain is one declarative graph, `yaml_instance/ChatDev_v1.yaml`
(1,021 lines), with a schema in `yaml_template/design.yaml`.

| ChatDev 1.0 | ChatDev 2.0 |
| --- | --- |
| `RoleConfig.json` | `type: agent`, `config.role` (full system prompt inlined) |
| `PhaseConfig.json` assistant/user prompts | `type: literal` — one node per prompt, the assistant/user pair kept explicitly (e.g. `Test Modification Phase Prompt for Assistant` `:401` / `… for User` `:415`) |
| `ChatChainConfig.json` ordering | `graph.edges` with `from` / `to` / `trigger` / `condition` / `carry_data` / `keep_message` / `clear_context` |
| `cycleNum` | `type: loop_counter`, `config.max_iterations` (`Code Review` 10, `Code Complete` 5, `Test Modification` 5, `Test` 3, `Manual` 1) |

Realised phase order: **Coding → CodeComplete → CodeReview (Comment ↔
Modification) → TestErrorSummary → TestModification → Manual → FINAL.**
`DemandAnalysis` and `LanguageChoose` are absent. The Programmer is **five
separate agent nodes**, one per phase — no single character traverses phases.

Mapping CrewAI onto this: Agent ≈ node, Task ≈ `literal` + `agent` pair,
Crew ≈ a sub-graph, and **there is no phase object** in the reference either.
A phase tier in our visualizer is a decision we make (Task boundaries are the
natural one), not a reference we copy.

## 5. Reference captures

Primary: `assets/launch.gif` (4.1 MB, the run-time visualizer in motion),
`assets/workflow.gif` (1.0 MB, editing). Tutorial captures under
`frontend/public/media/`: `run.gif`, `complex_run.gif` (run-time),
`create_node.gif`, `create_edge.gif`, `condition_edge_1.gif`,
`condition_edge_2.gif`, `human_node.gif`, `start_node.gif`,
`config_graph.gif`, `graph_create.gif`, `context_window.gif`. Case-study runs
under `assets/cases/*/`. These are the frames a critic compares against; they
stay in `D:\ChatDev-main` and are not copied into this repository
(`docs/comparison/` is ignored by the global `*.png` rule for the same
reason).

## 6. Carry, fix, and skip

**Carry over**

1. The handoff walk along the real edge path — the single effect that makes agent-to-agent message passing legible.
2. The negative-delay stagger for a populated-on-arrival canvas.
3. One glow vocabulary for "the system is waiting on you" (launch button, gate input).
4. Dual-period concurrent animations on the active node so emphasis never visibly loops.

**Fix (the reference gets these wrong)**

1. **Idle agents never recede.** Emphasis is purely additive at `scale(1.02)`. We recede idle nodes (opacity/desaturation) so the active speaker reads at a glance in a 20-step run.
2. Dialogue lands whole at `NODE_END`. We reveal progressively from stream chunks or the completed response, bounded.
3. Chat avatars are re-drawn randomly (`LaunchView.vue:960` omits the node id) so they never match the graph. Ours are keyed to the node.
4. `WorkflowEdge.vue:182-214` has a constant-8000 no-op clamp and an out-of-range `strokeOpacity: 2` that makes the glow inert — not worth copying.
5. Replay has no pacing; ours must reconstruct timing from frame timestamps or collapse walks into a single settled state.

**Skip**

- The sprite art. It is theirs, it is 14 MB, and this repo has already adopted and then removed it on the evidence (CLAUDE.md §14). Characters need art this project owns.
- Random character assignment. Identity must be stable per agent node and per run.
