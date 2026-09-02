# Design system

The rule this file exists to serve, from `AGENTS.md`: **no new colours,
spacing or type scales.** A value is a token in
`frontend/src/assets/styles/tokens.css` or it does not exist. Written
2026-09-02 from the sheet as it is on disk (65 lines, one unconditional
`:root`), plus the additions plans 02, 03 and 11 committed to. Where a value
is planned rather than shipped it says so.

## 0. Where things live, and why the order matters

| Sheet | Owns | Lines |
| --- | --- | --- |
| `assets/styles/tokens.css` | every custom property | 65 |
| `assets/styles/node-card.css` | the node card shared by the run console and the builder | ~250 |
| `assets/styles/builder.css` | the builder's tenancy of the card, ports, edges, palette, rails | |
| `assets/styles/motion.css` (planned, 11) | run-time choreography and the character palette | |
| `studio.css` | layout, import order, breakpoints, the global reduced-motion block | 551 |

`studio.css:1-21` imports Google Fonts → `tokens.css` → `node-card.css` →
`builder.css`. **The last two are at identical specificity on the same
element**; swap them and every builder card loses its kind colour. Add a
sheet at the end of that list, never in the middle.

`src/style.css` is the leftover Vite scaffold, imported by nothing
(`main.ts:5` imports only `./studio.css`). It carries a light palette that
is dead. Do not resurrect it; the light theme goes in `tokens.css` (§7).

## 1. Colour

### Surfaces, borders, text

| Token | Value |
| --- | --- |
| `--bg-app` | `#1a1a1a` |
| `--bg-node` | `#2a2a2a` |
| `--surface-panel` / `-raised` / `-well` | `rgba(255,255,255,.03)` / `.055` / `rgba(0,0,0,.22)` |
| `--surface-overlay` / `-strong` | `rgba(26,26,26,.94)` / `#222426` |
| `--border-default` / `-avatar` / `-hover` | `rgba(255,255,255,.1)` / `.2` / `.3` |
| `--text-primary` / `-body` / `-title` / `-muted` | `#f2f2f2` / `#e0e0e0` / `#ffffff` / `#b3b3b3` |
| `--text-40` | `rgba(255,255,255,.52)` |

### Accents

| Token | Value | Use |
| --- | --- | --- |
| `--accent-mint` | `#aaffcd` | input kind, `member` port, success |
| `--accent-cyan` | `#99eaf9` | agent kind, running |
| `--accent-blue` | `#a0c4ff` | crew kind |
| `--link-cyan` | `#7dc6ff` | router kind, links |
| `--accent-attach` (planned, 02) | `#c3a6ff` | the attachment family and the `attach` port |
| `--gradient-brand` | `linear-gradient(135deg, #aaffcd, #99eaf9, #a0c4ff)` | the running card, the launch control |
| `--gradient-danger` | | error |

The three accents and the brand gradient were hand-extracted from DevAll's
scoped styles (PRD §8.2) because DevAll defines almost no custom properties
of its own. They are the one thing lifted from the run-time reference. The
fifteen-gradient node palette that DevAll assigns by string hash (`utils/colorUtils.js:15-60`)
was **refused** (PRD §8.3): its hash can index past the array and its colours
are unstable across reloads. Kind colours here are declared, not derived.

### Semantic

| Token | Value |
| --- | --- |
| `--warn-bg` / `-border` / `-text` | on `#ffe082` (also the gate kind) |
| `--err-bg` / `-border` / `-text` | on `#ffcccc` |

### Node kinds — one colour, one shape, one icon each (03)

| Kind | Shape | Icon (lucide) | Accent |
| --- | --- | --- | --- |
| input | card, no top port | `text-cursor-input` | `#aaffcd` |
| agent | card, 240 px | `user-round` authored / `book-user` library | `#99eaf9` |
| crew | card, 240 px, double left border | `users-round` | `#a0c4ff` |
| gate | card, two labelled bottom ports | `hand` | `#ffe082` |
| router | card, notched right edge, labelled ports | `git-fork` | `#7dc6ff` |
| transform | slim card | `wand-2` | `#b3b3b3` |
| output | card, no bottom port | `flag` | `#7bdff2` |
| tool | **pill**, 160 px | `wrench` | `#c3a6ff` |
| mcp | pill, 160 px | `plug-zap` | `#d5b8ff` |
| skill | pill, 160 px | `book-open` | `#e0ccff` |

The first seven are shipped and declared in **three reconciled places**:
`data/nodeKinds.ts` `accent` (minimap dot, palette tile, inspector kicker),
`builder.css:47-53` (`--node-gradient` two-stop 135° gradient and
`--node-shadow-color` per kind), and `node-card.css:53-84` (the run console's
tenancy of the same variable). A new kind adds a row to all three or the
`is-kind-*` class resolves to the default. The three attachment kinds are
planned by 03; their three violets are deliberately one family, because
"tool, mcp, skill" is one idea with three faces.

### Characters (planned, 11)

A twelve-entry palette in `motion.css`, indexed by FNV-1a of the node id
mod 12, gives every node one stable colour across its card medallion, its
dialogue avatar and its handoff token. The twelve values are **not yet
chosen**; they must sit inside the accent family above and pass 3:1 against
`--bg-node` in dark and against the light surface in light. No third-party
sprites, ever (`frontend/tests/builderCardDesign.spec.ts` asserts it).

## 2. Type

| Token | Value |
| --- | --- |
| `--font-body` | Archivo |
| `--font-display` | Space Grotesk |
| `--font-mono` | SFMono-Regular, Consolas, … |
| `--fs-11` … `--fs-18` | 11, 12, 13, 14, 15, 18 px — six steps, no seventh |

Node titles at the default fit of the validator graph (scale 0.457) render
near 7 px; that is why the run console has a stage lane and why 02 sets the
zoom floor where it does. Do not solve a legibility problem by adding a
5 px step.

## 3. Space, radius, elevation

There is **no spacing scale token**; padding and gap are literal pixels
throughout. The house values are 4, 6, 8, 10, 12, 16, 20 and 24 px. The
snap grid is `GRID = 20` (`useBuilderCanvas.ts:51`) matching
`--dot-gap: 20px`; every node position is an integer on it.

| Token | Value |
| --- | --- |
| `--r-xs` / `-sm` / `-md` / `-lg` | 3 / 4 / 6 / 8 px |
| `--r-2xl` | 12 px — the house radius, lifted from DevAll |
| `--r-fab` / `-pill` / `-full` | 16 px / 20 px / 50 % |
| `--glow-input`, `--glow-bubble` | the two glows; box-shadows otherwise inline |
| `--blur-panel` / `--blur-rail` | `blur(5px)` / `blur(12px)` |
| `--z-base` / `-rail` / `-control` / `-toast` | 0 / 20 / 30 / 50 |

## 4. Canvas, ports, edges

| Token | Value |
| --- | --- |
| `--canvas-bg`, `--dot-color #777`, `--dot-gap 20px`, `--dot-size 1px` | the dot grid |
| `--edge-stroke`, `--edge-width 1.2px`, `--edge-inactive #777a7c` | edges |
| `--edge-label-bg` / `-brd` | edge labels |

Ports (02): **12 px visual inside a 24 px hit target**, coloured by port
class — `in` a circle in the kind accent, `attach` a violet square,
`member` a mint diamond, `error` a labelled port; red while a drag is over
an invalid target, green over a valid one. Edges (02): flow edges a
source-accent → target-accent gradient at 1.5 px with an arrowhead;
attachment, membership, error and back edges each a distinct class; the
back edge stays dashed cyan.

## 5. States and motion

Node run states are five: `idle`, `running`, `waiting`, `completed`,
`error` (`WorkflowNode.vue:69-75`). Running and completed carry different
gradients (`node-card.css:53-84`). Active emphasis is DevAll's dual-period
pair, `node-glowing 4s linear` and `node-pulse 2s ease-out`, which the
visual baseline asserts (`e2e/visual/run-canvas.spec.ts:198`). Idle recede
(planned, 11): non-active nodes at opacity ≈ .55 and desaturated while a run
is live. **The design canvas is still** — no infinite animation at rest
(`docs/flow-builder-spec.md` §5.5).

| Token | Value |
| --- | --- |
| `--motion-fast` / `--motion-medium` | 160 ms / 260 ms |
| `--ease-out` | `cubic-bezier(.22, 1, .36, 1)` |

Reduced motion is honoured in three places and every new animation joins
one of them: the global block (`studio.css:306-314`), the card's named
keyframes (`node-card.css:268`), and the builder's (`builder.css:871-880`,
which also clears `stroke-dasharray` so a frozen dashed line does not read as
a rendering fault).

## 6. Breakpoints

Two, used consistently in both workspaces: **1180 px** (the control and
inspector rails become overlays) and **860 px** (the chat and palette rails
become overlays; the workspace switch hides) — `studio.css:287, 293, 459,
525, 539`. The 390 × 844 capture the gauntlet requires adds a third
behaviour (02): the palette is a bottom sheet and the inspector an overlay.

## 7. Light theme (planned, 02)

`tokens.css` gains `[data-theme="light"]` redefining the surface, border,
text, canvas, edge and glow tokens only. Accents, kind gradients and the
character palette do not change between themes; contrast is re-checked, not
re-coloured. Captures are taken in both.

## 8. Enforcement

`frontend/tests/designTokens.spec.ts` (planned, 02) asserts that no
`.vue` or `.css` file outside the four sheets in §0 contains a hex or
`rgba(` literal, and that `tokens.css` declares no token absent from this
file's tables. A new colour is a pull request against this document first.

## References

- `frontend/src/assets/styles/tokens.css`, `node-card.css`, `builder.css`; `frontend/src/studio.css:1-21, 287-314, 459-539`; `frontend/src/data/nodeKinds.ts`; `useBuilderCanvas.ts:51`.
- `PRD.md` §8.2–8.3 (the token extraction from DevAll and the palette refusal); `docs/chatdev-notes.md` §2 (the motion table); `docs/flowise-notes.md` §2 (port and edge measurements).
- `.agent/plans/02-canvas.md` D1–D4, `03-node-library.md` D4 (identity table), `11-run-visualizer.md` D1–D2.
