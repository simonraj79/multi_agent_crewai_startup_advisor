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
| `assets/styles/character.css` | the cast: the character parts, their five states, and their own reduced-motion block (§5). Imported **last** | |
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

### On-surface text and boundaries (run shell, `docs/run-shell/SHELL-SCOPE.md` §2c)

Every one of these is **additive**: its dark value is identical to the shipped
token it stands beside, so no dark pixel moves, and the light value is the
correction. They exist as second tokens rather than as edits because the
originals are read by `builder.css`, `node-card.css` and sixteen committed
pixel baselines. Ratios are `frontend/scripts/contrast-audit.mjs`'s, composited
over the real surface stack. SHELL-SCOPE.md §6 is the commit that merges each
pair back into the token it shadows.

| Token | dark | light | Replaces, and why |
| --- | --- | --- | --- |
| `--text-meta` | `= --text-40` | `rgba(11,13,15,.6)` | `--text-40` as small text measures 4.07–4.26 in light |
| `--border-control` | `rgba(255,255,255,.34)` | `rgba(15,20,25,.49)` | a control's own boundary needs 3.0 (1.4.11); `--border-default` is 1.31–1.37 |
| `--border-hover-strong` | `rgba(255,255,255,.42)` | `rgba(15,20,25,.56)` | `--border-hover` is 2.71 / 2.18. Hover only — no screenshot captures it |
| `--on-accent-cyan` / `-mint` / `-blue` | `= --accent-*` | `#0e6b7d` / `#0f6b42` / `#2f5fa8` | the accent stays IDENTITY (§7, plan 02 D6); this carries the same colour as *text*, 1.01–1.69 → ≥ 5.15 |
| `--link-strong` | `= --link-cyan` | `#1a6099` | `--link-cyan` is 4.38–4.41 against its own stated contract of 4.5 |
| `--warn-text-strong` | `= --warn-text` | `#865700` | `--warn-text` on its tint over the canvas is 4.30 |
| `--warn-border-strong` / `--err-border-strong` | `rgba(255,204,0,.46)` / `rgba(255,82,82,.7)` | `rgba(150,100,0,.95)` / `rgba(190,40,40,.7)` | the two status boundaries at 2.70 / 1.85 |
| `--brand-wash` / `--brand-rim` | `rgba(153,234,249,.08)` / `.28` | same | the brand mark's fill and rim, written out at three sites |
| `--ink-on-brand` | `#10201c` | same | three near-identical inks on one shared gradient |
| `--ink-on-warn` / `--ink-on-err` | `= --ink-on-brand` | `#fff8e7` / `#fff5f5` | the verdict badge fills itself with `--warn-text` / `--err-text`, which are TEXT colours and flip DARK in light; the near-black ink then measured 2.84 and **2.24** → 5.60 / 7.05. Two tokens, not one: an ink on amber and an ink on red are independent decisions |
| `--ring-pressed` | `inset 0 0 0 1px color-mix(in srgb, var(--accent-cyan) 20%, transparent)` | same | the pressed segment's ring literal |

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

### Roles

A role says what a piece of text **is**; the step is only how big it happens
to be. Seven roles over the six steps and the three families — no seventh
step, and adding one is still refused here. Each is a whole `font` shorthand,
because `var()` substitution into `font:` is textual, because the shorthand
resets `line-height` and `font-variant` (so one role cannot inherit half of
another), and because the shell already writes every one of them out as a
shorthand — which is what makes adopting a role a one-for-one substitution
provable against a pixel baseline. `letter-spacing` is not part of `font`, so
tracking is its own token; that is why the four tracking values in use collapse
to one rather than disappearing into the roles.

| Token | Value | Is |
| --- | --- | --- |
| `--type-display` | `700 var(--fs-18)/1 var(--font-display)` | the app title, a report's own h2 |
| `--type-title` | `600 var(--fs-15)/1.25 var(--font-display)` | every panel header's h2 |
| `--type-body` | `400 var(--fs-13)/1.5 var(--font-body)` | prose in a rail |
| `--type-label` | `500 var(--fs-12)/1.4 var(--font-body)` | field labels, list rows, banners |
| `--type-kicker` | `700 var(--fs-11)/1 var(--font-mono)` | the uppercase mono eyebrow — twelve independent declarations before this |
| `--type-meta` | `500 var(--fs-11)/1.2 var(--font-mono)` | timestamps, sequence numbers, ids; the fourteen raw 10 px sites |
| `--type-metric` | `600 var(--fs-15)/1.1 var(--font-mono)` | a number a human is watching |
| `--track-kicker` | `0.06em` | the one tracking value for uppercase mono |

`--type-title` is *smaller in px* than the 16 and 17 px panel titles it
replaces and *stronger in hierarchy*, because Space Grotesk at 600 against
Archivo at 400 is a family contrast rather than a size one. That matters here
specifically: three panel headers are pinned at 64 px by a pixel baseline, so
the hierarchy could not be bought with height.

## 3. Space, radius, elevation

The eight house values are 4, 6, 8, 10, 12, 16, 20 and 24 px, and since
`docs/run-shell/SHELL-SCOPE.md` §2a **they are tokens**: `--space-1` … `--space-8`
in that order. Nothing outside the list exists; a literal px in `padding`,
`margin` or `gap` is a bug, with four documented exceptions that each carry
their own comment at the site — `40px` (`.canvas-heading`'s inset, load-bearing
against the two rail toggles), `46px` (the crew lane), `64px` (the panel-header
height and grid row 1) and `-34px` (the boat's half width). The snap grid is
`GRID = 20` (`useBuilderCanvas.ts:51`) matching `--dot-gap: 20px`; every node
position is an integer on it.

Eight steps and not a tighter 4/8/12/16/24 set: 6 and 10 px carry 48 of the run
shell's 234 spacing declarations between them, and collapsing them changes the
height of the segmented control, the status badge and the account chip — three
surfaces the builder shares and two baselines capture.

| Token | Value |
| --- | --- |
| `--r-xs` / `-sm` / `-md` / `-lg` | 3 / 4 / 6 / 8 px |
| `--r-2xl` | 12 px — the house radius, lifted from DevAll |
| `--r-fab` / `-pill` / `-full` | 16 px / 20 px / 50 % |
| `--glow-input`, `--glow-bubble` | the two glows |
| `--blur-panel` / `--blur-rail` | `blur(5px)` / `blur(12px)` |
| `--z-base` / `-rail` / `-control` / `-toast` | 0 / 20 / 30 / 50 |

### Elevation

Before SHELL-SCOPE.md §2d there was no elevation system, only five background
tints and **21 distinct shadow literals across 26 sites** — seven depths for
three jobs. Three levels and a recess, and no fourth: a fourth would be a level
with two occupants.

| Token | Level | Where |
| --- | --- | --- |
| — (`--surface-panel` + `--border-default`, no shadow) | 0, the ground | a rail, the canvas ground. A ground does not float |
| `--shadow-panel` | +1 | something *on* the panel: a bubble, a chip, a raised button |
| `--shadow-overlay` | +2 | the report sheet, the zoom controls, the report FAB, a rail while it is an overlay |
| `--shadow-inset-well` | −1 | a field, a code chip, the segmented track — with `--surface-well` + `--border-control` |
| `--shadow-raised` | +1 strong | a card lifted off its panel |

Four further shadow tokens are **pure extractions with no light value at all** —
`--shadow-controls`, `--shadow-rail-start`, `--shadow-rail-end`,
`--shadow-sheet`. Their sites are inside the builder's sixteen baselines, and a
shadow that changes with the theme is exactly what those baselines exist to
catch. SHELL-SCOPE.md §6.4 is the commit that folds them into the three levels.

One elevation defect is **recorded and not fixed**: in the light theme
`--surface-raised` and `--surface-well` are the same value, so the three-level
system is two levels there; in dark a well sits 1.055:1 below its rail, which is
5 % of a step. Both tokens are read by `node-card.css` inside the run-canvas
clip, so correcting them moves all 19 baselines (SHELL-SCOPE.md §6.1).

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

Reduced motion is honoured in **four** sheets now and every new animation joins
one of them: the global block (`studio.css`), the card's named keyframes
(`node-card.css`), the builder's (`builder.css`, which also clears
`stroke-dasharray` so a frozen dashed line does not read as a rendering fault),
and **`character.css`**, whose own `@media (prefers-reduced-motion: reduce)`
block sets `animation: none` on every character loop — a cast that keeps its
pose is the whole requirement, and the pose is what carries the state.

**The global block is a blanket, not a stop, and the distinction has now cost
one real defect.** It sets `animation-duration: .01ms` and
`animation-iteration-count: 1`, which for a *spinner* does not stop the
rotation — it freezes it at whatever angle .01ms of a 0.8s cycle happens to
reach, so a reduced-motion reader got a permanently crooked loader for as long
as a log export takes to prepare. Every named block above exists because the
blanket cannot express "stop", only "hurry". `StatusPanel.vue`'s
`.download-spinner` was the last animation in the run shell with no named rule
and has one now, matching what `RunHistory.vue` and `SignInPanel.vue` already
do for the identical icon.

## 6. Breakpoints

Two, used consistently in both workspaces: **1180 px** (the control and
inspector rails become overlays) and **860 px** (the chat and palette rails
become overlays; the workspace switch hides) — `studio.css:287, 293, 459,
525, 539`. The 390 × 844 capture the gauntlet requires adds a third
behaviour (02): the palette is a bottom sheet and the inspector an overlay.

At **640 px** the run console answers the same question the builder already
answered there: both rails become near-full-width overlays
(`min(360px, calc(100vw - 44px))`), both rail toggles become 44 × 44 in the
gutter that leaves, `.graph-workspace` takes an explicit
`grid-template-columns: minmax(0, 1fr)` — without it the canvas lays out at its
content's min-content width, measured at **802 px inside a 390 px workspace**,
clipped rather than scrolled so nothing says so — and the brand title stops
wrapping out of the 52 px header. Every one of those rules is written against a
run-console-only selector, because the builder's eight 390 px baselines are in
the same sheet.

## 7. Light theme (planned, 02)

`tokens.css` gains `[data-theme="light"]` redefining the surface, border,
text, canvas, edge and glow tokens only. Accents, kind gradients and the
character palette do not change between themes; contrast is re-checked, not
re-coloured. Captures are taken in both.

## 8. Enforcement

`frontend/tests/designTokens.spec.ts` asserts that no `.vue` or `.css` file
outside the token sheets in §0 contains a hex, `rgba(` or `hsl(` literal. It is
**scoped to the files changed on the current branch** (`git diff --name-only
main...HEAD`, plus the working tree), which is the difference between a rule the
repository can adopt and one that would fail on 143 files the day it was
written. Every branch that touches a sheet therefore leaves it cleaner, and
`docs/run-shell/evidence/T3/literals.txt` is the run.

`frontend/scripts/contrast-audit.mjs` is the other half: it reads every colour
from `tokens.css` and `motion.css`, composites each translucent token over the
surface stack the shell actually paints, and exits non-zero while any pairing
the run shell **owns** is below the level it must meet — 4.5 for text, 3.0 for a
UI boundary, in both themes. A pairing whose site is in another worker's file is
listed with its owner and the token to use rather than silently counted.

A new colour is a pull request against this document first.

## References

- `frontend/src/assets/styles/tokens.css`, `node-card.css`, `builder.css`; `frontend/src/studio.css:1-21, 287-314, 459-539`; `frontend/src/data/nodeKinds.ts`; `useBuilderCanvas.ts:51`.
- `PRD.md` §8.2–8.3 (the token extraction from DevAll and the palette refusal); `docs/chatdev-notes.md` §2 (the motion table); `docs/flowise-notes.md` §2 (port and edge measurements).
- `.agent/plans/02-canvas.md` D1–D4, `03-node-library.md` D4 (identity table), `11-run-visualizer.md` D1–D2.
