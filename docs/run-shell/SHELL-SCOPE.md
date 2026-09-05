# The run shell — scope, proposed before it is built

Written 2026-09-05 on `run-shell/cast` at `5bb1612`, by W5, **before the first
`studio.css` change**. It is the artifact
[`DEFINITION-OF-DONE.md`](DEFINITION-OF-DONE.md) T3.1 asks for, and its evidence
is `git log` order rather than its own content: this file's first commit
precedes the first commit touching `frontend/src/studio.css`
(`evidence/T3/scope-order.txt`).

It builds on the measured audit written the same morning (spacing, type,
elevation, contrast and motion, five scripts, `262`/`316` pairings). Where this
document and that audit disagree, **this one is the later measurement** and the
disagreement is named where it sits — there is one, and it is §0.B.

---

## 0. The two constraints that decide almost everything

### A. Ownership

`DEFINITION-OF-DONE.md` §0 gives W5 `tokens.css`, `studio.css`,
`StatusPanel.vue`, the header in `StudioView.vue`, this file,
`frontend/scripts/contrast-audit.mjs` and `frontend/tests/designTokens.spec.ts`.
W1–W4 and W6 are building **in parallel** (§7.1) in the files this shell
renders: `ChatRail.vue` and `DialogueRail.vue` are W3's, `ReportPanel.vue` and
`GateCard.vue` are W1's, `CrewProgress.vue` / `motion.css` / `WorkflowNode.vue`
are W4's.

**So the shell polish cannot be delivered by editing the rails.** It arrives as
tokens and as global classes in `studio.css` that those components already use
or can adopt in one attribute — §4 is that contract, written so the orchestrator
can hand it on. Every LEAVE in §1 that reads "another worker owns it" is this
rule and not timidity.

### B. Nineteen committed pixel baselines — and the builder's are FULL-PAGE

`frontend/e2e/visual/builder-canvas.spec.ts-snapshots/` holds **16** PNGs and
`run-canvas.spec.ts-snapshots/` holds **3**. All 19 are tracked
(`.gitignore` rescues them from the global `*.png` rule) and no
`toHaveScreenshot` call passes `maxDiffPixels`. T3.5 requires the builder's 16
to pass **unchanged**.

> **The correction to the morning audit, and it is the single most
> consequential fact in this document.** The audit reasoned about the
> `.validator-flow` clip that bounds the three run-canvas baselines and
> concluded that the shell's chrome was free. It is not.
> `builder-canvas.spec.ts` calls `await expect(page).toHaveScreenshot(...)` —
> **the whole page**, four states × two themes × two viewports, and the two
> viewports are **1440×900 and 390×844** (`playwright.config.ts`, projects
> `chromium` and `mobile`). So the builder baselines contain the application
> header, the brand lockup, the account chip, every `.button`, and the 390px
> narrow layout.
>
> Therefore: **any rule in `studio.css` that the builder also renders must keep
> byte-identical computed values.** A literal→token extraction at the same value
> is safe; a type, spacing or colour *change* on a shared selector is not.

Measured, by grepping `frontend/src/components/builder/**` for each class this
sheet declares:

| Shared with the builder — **frozen** | Run-shell only — **free** |
| --- | --- |
| `.app-header`, `.brand-lockup`, `.brand-mark`, `.header-context`, `.account-chip`/`-avatar`/`-name`/`-signout`, `.icon-button`, `.button`/`-primary`/`-secondary`/`-quiet`, `.skip-link`, `.sr-only`, `.markdown-body`, `.studio-shell`, `.studio-main`, `.graph-workspace`, `.vue-flow__controls*`, `html`/`body`/`#app`, `:focus-visible`, the global reduced-motion block, the `is-builder` breakpoint blocks | `.canvas-heading`, `.canvas-kicker`, `.canvas-meta`, `.stream-reconnecting`, `.control-rail`, `.control-scroll`, `.control-toggle`, `.report-reopen`, `.auth-splash*`, `.workflow-name`, `.live-status`, every class in `StatusPanel.vue`, the `.chat-rail` / `.control-rail` breakpoint rules |

`.canvas-heading`, `.canvas-kicker` and `.canvas-meta` are **not** builder
surfaces — the audit listed `.canvas-heading` as one and the grep answers zero
files. That is what makes the one real type change in this sheet (§3) possible
at all.

Two mechanisms let a frozen surface still be improved, and both are used below:

1. **A hover state is never captured.** `.icon-button:hover` and
   `.button:hover` may take a stronger border token at zero baseline cost.
2. **`:where()` costs no specificity.** A rule written
   `:where(.studio-shell:not(.is-builder)) .segmented { … }` is specificity
   `(0,1,0)` — it reaches the run console, never the builder, and every existing
   modifier still outranks it.

### C. Option A, taken

The audit offered Option A (purely additive tokens; defer the four value
changes) and Option B (take them now and regenerate all 19 baselines). **The
orchestrator took A.** No existing token changes value in this branch. The four
deferred changes are §6's follow-ups.

---

## 1. Surface inventory — 41 surfaces, 25 TOUCH, 16 LEAVE

Every TOUCH is in a file W5 owns. There is no exception, and that is the test
this inventory had to pass.

### 1a. `studio.css` — the application chrome

| # | Surface | Verdict | Reason |
| ---: | --- | --- | --- |
| 1 | `.studio-shell` + its brand hairline | **TOUCH** | The `::before` glow is an `rgba(153,234,249,.08)` literal — T3.2. Becomes `--brand-wash`, same value, zero pixels. |
| 2 | `.app-header` bar | **TOUCH, geometry frozen** | 52px stays (orchestrator's decision 2, and `studio.css` states it twice: `height: 52px` and `calc(100dvh - 52px)`). Token adoption only; the 52-vs-64 rhythm break is §6. |
| 3 | `.brand-lockup` / `.brand-mark` | **TOUCH** | `rgba(153,234,249,.08/.28)` twice over, duplicated verbatim at `.auth-splash-mark`. One pair of tokens, three sites, identical values. |
| 4 | `.workflow-name`, `.live-status` | **TOUCH** | `--text-40` is **4.26:1** on the header in light — an AA failure on the first line a visitor reads. Takes `--text-meta`. |
| 5 | `.account-chip` family | **TOUCH** | Spacing tokens at identical values. No visual change (frozen, §0.B). |
| 6 | `.segmented` **base — MISSING** | **TOUCH (defect)** | The base rule is declared **only** inside `StatusPanel.vue`'s scoped block, so it compiles to `.segmented[data-v-…]` and the header's `class="segmented workspace-switch"` inherits **nothing**: the Build/Run pair renders as two *native* buttons — light grey `ButtonFace` boxes in a dark header. Visible in `evidence/T3/before-1440.png` and in the committed `gallery-dark` baseline. Promoted to one global declaration, run-console-scoped (§0.B.2). |
| 7 | `.button` family | **TOUCH** | Shared with 21 builder files. `#10201c` literal → `--ink-on-brand`, same value. Hover takes `--border-hover-strong`. |
| 8 | `.icon-button` | **TOUCH** | Same. Its `:hover` border measures **2.71:1** dark / **2.18:1** light against a needed 3.0. |
| 9 | `.skip-link`, `:focus-visible`, `.sr-only` | **TOUCH (one literal)** | `#0d1715` → `--ink-on-brand`. The link is `translateY(-150%)` until focused, so it is in no capture. |
| 10 | `.control-rail`, `.control-scroll`, `.control-toggle` | **TOUCH** | The right rail's own chrome, and the 390px toggle target (§5). |
| 11 | `.canvas-heading` and its fade | **TOUCH, height frozen** | `h2` is a raw `17px` — a seventh step design.md §2 refuses; `.canvas-meta code` is a raw `10px`. Type only. `min-height: 64px` and `padding: 0 40px` do not move (the 40px is load-bearing against the two rail toggles; the comment at the site records the "XED VALIDATOR GRAPH" defect). |
| 12 | `.graph-workspace` grid | **LEAVE (one narrow-viewport addition)** | Its row template is the run-canvas baseline's height. The only change is a `grid-template-columns: minmax(0, 1fr)` at ≤640, which the builder already has for itself and which the run console needs for the same measured reason. |
| 13 | `.stream-reconnecting` | **TOUCH** | `--warn-text` on `--warn-bg` over the canvas is **4.30:1** in light — the only status-colour AA failure. |
| 14 | Vue Flow `.vue-flow__controls*` | **TOUCH** | `0 8px 24px rgba(0,0,0,.3)` literal → `--shadow-controls`, a **theme-invariant** token at exactly that value, because this element is in all 16 builder baselines. |
| 15 | `.markdown-body` | **TOUCH (one line)** | Flow-specific output rendering, excluded by the brief — except `a { color: var(--link-cyan) }`, which is **4.38:1** in light. Takes `--link-strong`. The document scale (22/18/15px) stays; §6.8 says why. |
| 16 | `.report-reopen` FAB | **TOUCH** | `0 8px 24px rgba(0,0,0,.4)` → `--shadow-overlay`; `#101a18` → `--ink-on-brand`. |
| 17 | `.auth-splash*` | **TOUCH (one literal pair)** | Not the run shell, but it carries the same two brand literals as #3 and T3.2 counts every literal in a touched file. |
| 18 | Breakpoint blocks 1180 / 860 / 640 | **TOUCH (add, never alter)** | design.md §6 fixes the two breakpoints and both workspaces obey them. Nothing existing moves; §5 adds run-console-only rules at ≤640. |
| 19 | Global `prefers-reduced-motion` block | **LEAVE** | Keeps its blanket. §5 adds one *named* rule it currently papers over, in `StatusPanel.vue` where the animation is. |

### 1b. `StatusPanel.vue` — the right rail

| # | Surface | Verdict | Reason |
| ---: | --- | --- | --- |
| 20 | `.control-section` / `.compact-section` | **TOUCH** | `padding: 16px` against `padding-block: 13px`; 13 is not a house value. |
| 21 | `.control-label` | **TOUCH** | One of **twelve** independent declarations of one type role. |
| 22 | Idea `textarea` + `.field-meta` | **TOUCH** | The border is `--border-default` at **1.31:1** — a form control's boundary, WCAG 1.4.11, needs 3.0. `.field-meta` is a raw `10px`. |
| 23 | `.read-only-well` | **TOUCH** | A "well" measuring 1.055:1 against its rail reads flat. |
| 24 | `.segmented` (GATES, VIEW, format picker) | **TOUCH** | Base moves to `studio.css`; the `rgba(153,234,249,.2)` ring becomes a token. |
| 25 | `.status-line` / `.status-badge` | **TOUCH** | The panel's most-read line. Takes its words from `data/runStatusDisplay.ts` (W1's), so the rail and the history list stop contradicting each other. |
| 26 | **`.metrics-grid`** | **TOUCH — the headline fix** | §3d. A 10px label at 4.11:1 in light, a 13px value, 5px between them, 9px cell padding, and a divider painted at **1.34:1**. |
| 27 | `.stream-line`, `.run-id` | **TOUCH** | Three raw 10px mono sizes. |
| 28 | `.control-actions`, the download row | **TOUCH** | Spacing tokens; the primary button's verb (§3e). |
| 29 | `.error-banner` / `.transport-banner` / `.graph-banner` | **TOUCH (chrome only)** | Three near-identical rules differing only in colour family. One `.panel-banner` + `is-warn`/`is-error`. **The wording is W1's** and does not change; the three class names stay on the elements because four E2E specs select them. |
| 30 | `.download-spinner` | **TOUCH** | The one animation in the shell with no named reduced-motion rule. The global blanket freezes it at a pseudo-random rotation rather than stopping it — a permanently crooked loader. |

### 1c. Everything else — LEAVE

| # | Surface | Verdict | Reason |
| ---: | --- | --- | --- |
| 31 | `ChatRail.vue` | **LEAVE** | **W3's**, and the file the interpretation layer is rewriting. Inherits §2's tokens and §4's classes. |
| 32 | `DialogueRail.vue` | **LEAVE** | W3's. |
| 33 | `CrewProgress.vue` | **LEAVE** | **W4's**, and the boat is being replaced by the cast (T2.9). Its `background: rgba(26,26,26,.86)` literal keeps the crew strip **black in the light theme** — `--text-title` on it is **1.64:1**, the worst contrast defect in the shell, and it is one line in W4's file. §7 hands it over. |
| 34 | `ReportPanel.vue` | **LEAVE** | **W1's**, and flow-specific output rendering is out of the brief. `.score-track`'s `rgba(255,255,255,.08)` is 1.014:1 in light — handed over. |
| 35 | `GateCard.vue` | **LEAVE** | W1's. |
| 36 | `RunHistory.vue` | **LEAVE** | Unassigned, and already token-clean. Gains §2 and §4 for free. |
| 37 | `WorkflowNode.vue` + `node-card.css` | **LEAVE** | W4's, and inside both baseline sets. |
| 38 | `WorkflowEdge.vue`, `HandoffToken.vue` | **LEAVE** | W4's. |
| 39 | `motion.css` | **LEAVE** | W4's/W2's. The character palette's light-theme misses are handed over. |
| 40 | The Vue Flow canvas markup | **LEAVE** | W4 wires `StudioView.vue`; the `#777777` props there are props, not CSS, and match `--dot-color`. |
| 41 | **The builder workspace** | **LEAVE** | T3.5. §0.B is the whole reason this document is shaped the way it is. |

---

## 2. The token additions

All additive. **No existing token changes value.** Each is named in
`docs/design.md`'s tables in the same commit, because design.md §8 rules that a
new colour is a pull request against that document first.

### 2a. Spacing — eight steps, the house values named

```
--space-1 4  --space-2 6  --space-3 8  --space-4 10
--space-5 12 --space-6 16 --space-7 20 --space-8 24
```

design.md §3's eight house values, made enforceable. **Eight and not a tighter
4/8/12/16/24 set**: 6 and 10 carry 48 of the 234 spacing declarations in the run
shell between them, and collapsing them changes the height of the segmented
controls, the status badge and the account chip — three surfaces the builder
shares. Eight steps is the set that tokenises the whole shell without moving a
builder pixel.

Four literals survive as documented exceptions, each already carrying its own
comment: `40px` (`.canvas-heading` inset), `46px` (the crew lane), `64px`
(the three panel-header heights and grid row 1), `-34px` (the boat's half
width). Two more are frozen rather than exceptional: `14px` on `.header-context`
and `13px` on `.control-toggle`'s top, both inside builder baselines.

### 2b. Type — roles over the existing six steps, no seventh

```
--type-display  700 var(--fs-18)/1    var(--font-display)
--type-title    600 var(--fs-15)/1.25 var(--font-display)
--type-body     400 var(--fs-13)/1.5  var(--font-body)
--type-label    500 var(--fs-12)/1.4  var(--font-body)
--type-kicker   700 var(--fs-11)/1    var(--font-mono)
--type-meta     500 var(--fs-11)/1.2  var(--font-mono)
--type-metric   600 var(--fs-15)/1.1  var(--font-mono)
--track-kicker  0.06em
```

**A whole `font` shorthand per role, not a five-token set per role, and not
utility classes alone.** The brief allowed either; the reasons for this one are
measurable:

- `var()` substitution into the `font` shorthand is textual, so
  `font: var(--type-kicker)` resolves through the nested `var(--fs-11)` and
  `var(--font-mono)` exactly as if it were written out — and **the shell already
  writes every one of these as a `font` shorthand today** (`font: 700
  var(--fs-11)/1 var(--font-mono)` appears verbatim at nine sites). A role token
  is therefore a one-for-one substitution at every site, which is what makes it
  provable that no pixel moved on a frozen surface.
- The shorthand *resets* `font-variant`, `font-stretch` and `line-height`, which
  is the property that stops a role from inheriting half of another one. The one
  site that needs `font-variant-numeric: tabular-nums` declares it after the
  shorthand, as it already does.
- `letter-spacing` is not part of `font`, so tracking is its own token. That is
  a fact about CSS, not a design choice, and it is why the four tracking values
  in use collapse to one named token rather than disappearing into the role.
- The utility classes exist too — §4 — and they *read these tokens*. The token
  is the primitive and the class is the composed role, so a component can adopt
  either without the two being able to disagree.

`--type-display`'s `/1` is not the audit's proposed `/1.15`: the header's `h1`
is a **frozen** surface and `1.15` moves it. The value written here is exactly
what that element computes today.

### 2c. Colour — new tokens, adopted at run-shell sites only

Every one has a **dark value identical to the token it stands beside**, so no
dark pixel moves anywhere, and a corrected light value adopted only where §0.B
says it is free.

| Token | dark | light | Fixes |
| --- | --- | --- | --- |
| `--text-meta` | `rgba(255,255,255,.52)` (= `--text-40`) | `rgba(11,13,15,.60)` | 4.26 / 4.25 / 4.11 / 4.07 → ≥ 4.78 |
| `--border-control` | `rgba(255,255,255,.34)` | `rgba(15,20,25,.49)` | 1.31–1.37 → 3.11 / 3.16 |
| `--border-hover-strong` | `rgba(255,255,255,.42)` | `rgba(15,20,25,.56)` | 2.71 / 2.18 → 3.81 / 4.02 (hover only) |
| `--on-accent-cyan` | `var(--accent-cyan)` | `#0e6b7d` | 1.14–1.36 → ≥ 5.15 |
| `--on-accent-mint` | `var(--accent-mint)` | `#0f6b42` | 1.01–1.12 → ≥ 5.50 |
| `--on-accent-blue` | `var(--accent-blue)` | `#2f5fa8` | 1.69 → 5.30 |
| `--link-strong` | `#7dc6ff` (= `--link-cyan`) | `#1a6099` | 4.38–4.41 → 5.54 |
| `--warn-text-strong` | `#ffe082` (= `--warn-text`) | `#865700` | 4.30 → 4.51 |
| `--warn-border-strong` | `rgba(255,204,0,.46)` | `rgba(150,100,0,.95)` | 2.70 / 1.69 → 3.07 / 3.44 |
| `--err-border-strong` | `rgba(255,82,82,.70)` | `rgba(190,40,40,.70)` | 1.85 / 2.04 → 3.03 / 3.12 |
| `--brand-wash` / `--brand-rim` | `rgba(153,234,249,.08)` / `.28` | same | the two literals at three sites |
| `--ink-on-brand` | `#10201c` | same | the three near-identical inks on one gradient |
| `--ink-on-warn` / `--ink-on-err` | `= --ink-on-brand` | `#fff8e7` / `#fff5f5` | 2.84 / **2.24** → 5.60 / 7.05 — added 2026-09-05 after W1's sweep |
| `--ring-pressed` | `inset 0 0 0 1px color-mix(in srgb, var(--accent-cyan) 20%, transparent)` | same | the pressed segment's ring literal |

**Why `--on-accent-*` and not a repaint of the accents.** design.md §7 and plan
02 D6 rule that accents are *identity* and shared across themes — "a kind that
is one colour in the dark and another in the light is a kind an author has to
learn twice". `tokens.css` already records this exact gap as a follow-up and
counts the sites: 109 across 32 files. This is the fix that comment proposes,
applied to the run shell's sites only.

**Why `--link-cyan` is not simply darkened**, which the audit recommended: it is
consumed by `builder.css` at six sites, so changing it moves the eight light
builder baselines. `--link-strong` is the same correction with a different
carrier, and §6 schedules the merge.

### 2d. Elevation — three levels, and four frozen extractions

```
--shadow-panel    (light: shorter, cooler)
--shadow-raised   (light: shorter, cooler)
--shadow-overlay  0 8px 24px rgba(0,0,0,.4) dark — exactly today's FAB shadow
--shadow-inset-well
```

Those four are theme-aware and are adopted at run-shell-only sites. The four
below are **pure extractions with no light-theme value at all**, because their
sites are in the builder's baselines and a themed shadow would move them:

```
--shadow-controls    0 8px 24px  rgba(0,0,0,.30)
--shadow-rail-start  18px 0 38px rgba(0,0,0,.34)
--shadow-rail-end   -18px 0 38px rgba(0,0,0,.34)
--shadow-sheet       0 -18px 38px rgba(0,0,0,.34)
```

That asymmetry is deliberate and is the honest shape of Option A: the shell
gains an elevation *system*, and four shadows that the builder is standing on
are named without being changed. §6.4 is the commit that unifies them.

The audit's other elevation finding — that in the light theme
`--surface-raised` and `--surface-well` are **the same value**, so the
three-level system is two levels — is **not fixed here**. Both tokens are read
by `node-card.css` inside the `.validator-flow` clip, so correcting them moves
all 19 baselines. §6.1.

---

## 3. What changes on screen

### 3a. The header

The Build/Run pair stops being two native buttons (#6). `.brand-lockup h1`,
`.brand-lockup span`, `.workflow-name` and `.live-status` take role tokens at
their current computed values; `.live-status` additionally takes `--text-meta`,
which is the light-theme AA fix, and the two accent marks take `--on-accent-*`
under a `:not(.is-builder)` guard so the builder's header is byte-identical.
**The 52px height does not move** and the 52-vs-64 rhythm break is §6.2.

### 3b. The canvas heading

`h2` 17px → `--type-title` (15px Space Grotesk 600). Smaller in px and stronger
in hierarchy, because the display face at 600 against the body face is a *family*
contrast rather than a size one — which is the fix for "flat typography" that
does not add a step and cannot push a 64px header taller. `.canvas-kicker` takes
`--type-kicker` + `--track-kicker` + `--on-accent-cyan`; `.canvas-meta code`'s
raw 10px goes to `--type-meta`.

### 3c. The right rail

Sections go to `--space-6` / `--space-5`; the kicker, the badge, the stream line
and the run id go to `--type-kicker` / `--type-meta`; the textarea, the workflow
well and the segmented track take the **well** treatment — `--surface-well` +
`--border-control` + `--shadow-inset-well` — so a recessed field is visibly
recessed and its boundary passes 1.4.11.

### 3d. The metrics grid, specifically

Measured at 310px of rail, so each cell is ≈137px:

| | now | after |
| --- | --- | --- |
| `dt` | `600 10px/1` mono, `--text-40`, no tracking | `--type-kicker` + `--track-kicker`, `--text-meta` |
| `dd` | `600 var(--fs-13)/1` mono | `--type-metric` (`600 var(--fs-15)/1.1`), tabular-nums kept |
| `dt`→`dd` gap | `5px` | `--space-2` |
| cell padding | `9px 10px` | `--space-5` |
| cell height | **46px** for two lines | **60px** |
| the rule between cells | `--border-default` at **1.34:1** | `--border-control` at 3.0 |
| columns | `1fr 1fr` | `repeat(auto-fit, minmax(120px, 1fr))` — two at 310px and pixel-identical, still two in the ≤860 overlay |

The `+28px` this adds to the panel is absorbed by `.control-scroll`, which is
`height: 100%; overflow: auto`. COST — the deliverable number of the entire
product — currently renders at 13px in the same weight as the word "Cost".

### 3e. Two words that were wrong

- **The status word comes from `data/runStatusDisplay.ts`** (W1's), so the rail
  and the history list stop calling one run two things. `error` reads *Failed*,
  `completed` reads *Finished*, `idle` reads *Ready*. Four E2E assertions encode
  the old vocabulary and move with it; they are named in the build report.
- **The primary button no longer reads `Send` mid-run.** `primaryLabel` in
  `useValidatorRun.ts` (W3's file, untouched) returns `Send` while a run is
  running or waiting — on a button that `canLaunch` has disabled, so it names an
  action nobody can take. The panel renders the state's own verb instead
  (`Queued…`, `Running…`, `Waiting for you`, `Stopping…`) and passes `Launch`,
  `Relaunch` and `Launching…` through untouched.

---

## 4. The class contract — how the rails inherit this without W5 editing them

Declared global in `studio.css`. W1/W3/W4 adopt by adding the class in their own
templates, or by reading the token in their own scoped block; either way there is
one definition. A component's existing scoped rule always outranks these (they
are specificity `(0,1,0)`), so **adopting is additive and nothing breaks on the
way**.

| Class | What it is | Composed of |
| --- | --- | --- |
| `.panel-section` | a bordered region inside a rail | `padding: var(--space-6)`, one bottom hairline |
| `.panel-header` | the 64px header strip every panel has five versions of | `min-height: 64px`, `padding: 0 var(--space-6)`, flex, one bottom hairline |
| `.panel-heading` | the title inside it | `--type-title`, no margin |
| `.panel-kicker` | the uppercase mono eyebrow — **twelve** declarations today | `--type-kicker` + `--track-kicker` + `--on-accent-cyan` |
| `.section-kicker` | alias of the above, because `ChatRail`, `DialogueRail` and `GateCard` already spell it this way | — |
| `.panel-meta` | timestamps, sequence numbers, ids | `--type-meta` + `--text-meta` |
| `.panel-scroll` | a scrolling list that does not simply stop at the edge | `flex: 1; min-height: 0; overflow: auto`, `--space-8` of bottom rest, a mask fade |
| `.panel-well` | something recessed *into* a panel | `--surface-well` + `--border-control` + `--shadow-inset-well` |
| `.panel-banner` + `.is-warn` / `.is-error` | the one rule replacing three near-identical banners | flex, `--space-4 --space-5`, `--type-label`, one bottom border in the family colour |
| `.chip` | a small bordered token — call chips, flags, counts, laps | `--space-1`/`--space-2`, `--type-meta`, `--surface-well` |
| `.metrics-grid` + `dt`/`dd` | the metric tile, promoted out of `StatusPanel` | §3d |
| `.segmented` + `button` + `[aria-pressed]` | the segmented pair, promoted out of `StatusPanel` | `--surface-well` track, `--border-control`, `--ring-pressed` |

Adoption is **opt-in per component and per element**; nothing in this list
renames anything or requires a coordinated commit.

---

## 5. Motion and the narrow viewport

**Motion: exactly one line is W5's.** Every animation in the shell has a named
`prefers-reduced-motion` rule except `.download-spinner`, which is covered only
by the global blanket — and that blanket sets
`animation-duration: .01ms; animation-iteration-count: 1`, which does not stop a
spinner, it **freezes it at a pseudo-random rotation**. `animation: none` in
`StatusPanel.vue`'s own block, matching what `RunHistory.vue` and
`SignInPanel.vue` already do for the identical icon.

**Narrow (S6, 390×844).** Measured in `evidence/T3/before-390.png`: the shell
does not reflow. The two rails are overlays at `52vw` and `48vw` — 202px and
187px — which covers the canvas completely, clips *Unattended* to "Unattende"
and wraps the header's `h1` out of its own 52px bar. What changes, all of it
under `@media (max-width: 640px)` and all of it on run-console-only selectors so
the builder's eight 390px baselines cannot move:

1. Both rails become near-full-width overlays — `min(360px, calc(100vw - 44px))`
   — leaving a 44px gutter for the toggle rather than a 32px one.
2. Both rail toggles become 44×44 in that gutter, which is the touch target size
   this viewport is for. The chat rail's toggle lives in W3's component, so it is
   reached by a `studio.css` descendant rule rather than by an edit.
3. `.graph-workspace` gains `grid-template-columns: minmax(0, 1fr)` in the run
   console. The builder already has exactly this line for itself, and its comment
   records the measurement that forced it: at 390px the canvas laid out **802px
   wide** inside a 390px workspace, clipped rather than scrolled, so nothing said
   so and every fit was computed against the wrong box.
4. The header's brand title stops wrapping out of the bar.

`document.scrollingElement.scrollWidth <= 390` then holds, and both the canvas
and the report are reachable by collapsing a rail with a thumb.

---

## 6. Follow-ups — recorded, not built

Each is a decision the orchestrator declined for this branch or a change whose
cost is a baseline regeneration. Together they are the "Option B" commit.

1. **Light `--surface-raised` and `--surface-well` are the same value**, so the
   three-level elevation system is two levels in light, and in dark a well is
   1.055:1 below its rail — 5% of a step. The fix is
   `--surface-raised → rgba(255,255,255,.75)` and
   `--surface-well → rgba(15,20,25,.07)` light, `rgba(0,0,0,.34)` dark
   (measured: raised/well separation 1.000 → 1.197). It moves **all 19**
   baselines, because `node-card.css`'s `.node-meta span` paints
   `--surface-well` inside the `.validator-flow` clip.
2. **The 52px header against five 64px panel headers.** The single worst rhythm
   break in the shell. `studio.css` states the 52 twice and `.studio-main`'s
   height is `calc(100dvh - 52px)`, so changing it changes `.validator-flow`'s
   height and fails all three run-canvas baselines.
3. **`--border-hover`, `--warn-border` and `--err-border` still fail at rest**
   (2.71 / 2.70 / 1.85 dark). This branch fixes the hover case, where nothing is
   captured, and the two status borders at run-shell sites via
   `*-strong` tokens. Raising the shipped tokens moves up to 16 builder
   baselines.
4. **Merge the four `*-strong` / `--on-accent-*` pairs back into the tokens they
   shadow**, and drop `--shadow-controls` / `--shadow-rail-*` / `--shadow-sheet`
   into `--shadow-panel` / `--shadow-raised`. One commit, 19 baselines, a message
   naming which pixels moved and why (R1 requires exactly that).
5. **Drop the `:where(.studio-shell:not(.is-builder))` guard on `.segmented`**
   and the two `:not(.is-builder)` guards in the header, so the builder's
   Build/Run pair stops being two native buttons too. Same commit as 4.
6. **`node-card.css`'s five `--text-40` sites** — the eyebrow, the quarantine
   count, the in-flight query, the duration hint and the usage row — measure
   **4.31:1** in light. **The RUN CONSOLE's copy of them is fixed** (round two):
   `motion.css` now overrides all five to `--text-meta` behind
   `.studio-shell:not(.is-builder)`, which is that sheet's own tenancy of the
   shared card, and the run console reads **5.13:1**. Nothing moved in dark —
   `--text-meta`'s dark value is `--text-40`'s — and the three run-canvas
   baselines are captured in dark only, so no pixel moved there either.

   **The BUILDER's copy still reads 4.31.** Closing it means editing
   `node-card.css`, which is inside the builder's sixteen full-page baselines,
   eight of them light — so it is one token swap plus a regeneration, and it is
   this follow-up. `contrast-audit.mjs` measures the builder's row and prints it
   under *out of scope* so nobody has to rediscover it; the run shell's row is
   in scope and passes.
7. **The 109 accent-as-text sites across 32 files** that `tokens.css` already
   counts. `--on-accent-*` makes the sweep mechanical.
8. **`.markdown-body`'s document scale** (22/18/15px + `0.88em`) is deliberately
   *not* reconciled with the shell's role tokens. A rendered report is a
   document, and whether a document inside a panel should obey the panel's type
   scale is a design question, not a cleanup.

---

## 7. Handed to a named owner, with the token to use

> **ROUND TWO, 2026-09-05: thirteen of these seventeen are CLOSED, and the
> exemption that let them stay open is gone.**
>
> Ownership moved from *plan* to *file* once every builder finished, so
> `CrewProgress.vue`, `motion.css`, `ReportPanel.vue` and `GateCard.vue` came to
> W5 and their rows were fixed with the tokens this table already named. The
> character palette's four short colours were darkened to 90 % of their own
> light values — the same hue, because the twelve have to stay tellable apart at
> 32 px and a ratio bought by collapsing two of them toward each other is not a
> fix. And `contrast-audit.mjs` no longer counts W5's rows only: RV's third pass
> was right that a script exiting 0 over seventeen failing pairings is a gate
> measuring the wrong thing. `owner` is a label on a failure now, never an
> exemption from one. **330 pairings, 328 in scope, 1 failing** — and that one is W4's.
>
> | Still open | Why |
> | --- | --- |
> | `ChatRail.vue:383` and `DialogueRail.vue:467` `.section-kicker` (1.29) | W4 owns both files this round; the token is `--on-accent-cyan`. The two `.text-button` rows are gone: `ChatRail` no longer has one, and the single remaining `--link-cyan` site sits on a rail rather than on a well, where it passes |
> | ~~`node-card.css` `.node-meta` (4.31)~~ | **CLOSED for the run console**: `motion.css` overrides the card's five quiet-text sites to `--text-meta` behind the run-console guard, 4.31 → **5.13**, with no pixel moved in dark and none in the builder. The builder's own card keeps 4.31 and is §6.6 |


These are the contrast failures the run shell renders in files W5 must not open.
`evidence/T3/contrast.md` lists each one with its measured ratio and marks it
`handed to Wn`; the audit script's exit code counts only W5's own rows.

| Site | Now | Should be | Owner |
| --- | --- | --- | --- |
| `CrewProgress.vue` `.crew-progress` | `background: rgba(26,26,26,.86)` — the strip stays **black in light**; `--text-title` on it is **1.64:1** | `var(--surface-overlay)` | **W4** |
| `CrewProgress.vue` `.crew-marker`, `.crew-label`, kind text | `--text-40`, `--accent-cyan`, `--accent-blue` on the canvas ground | `--text-meta`, `--on-accent-cyan`, `--on-accent-blue` | **W4** |
| `CrewProgress.vue` pips | accents as UI marks, 1.02–1.14:1 in light | `--on-accent-*` | **W4** |
| `motion.css` `--character-1/-2/-10/-12` | 3.89–4.47:1 as small text in light | darken in the light block only | **W4/W2** |
| `node-card.css` five `--text-40` sites | 4.11:1 light | `--text-meta` (needs a baseline regeneration) | **W4** |
| `ReportPanel.vue` `.score-track` | `rgba(255,255,255,.08)` — **1.014:1** against its own well in light | `var(--surface-well)` or `--border-control` | **W1** |
| `ReportPanel.vue` sources `a` | `--link-cyan`, 4.41:1 light | `--link-strong` | **W1** |
| `ReportPanel.vue` `.verdict-badge.is-warn` / `.is-fail` | `--ink-on-brand` on a fill that flips dark in light: **2.84 / 2.24** | **CLOSED 2026-09-05**: `--ink-on-warn` / `--ink-on-err`, 5.60 / 7.05. The token pair is W5's, because `tokens.css` is the only place that knows a theme exists; the two-line adoption was made in W1's file with the orchestrator's leave while W1 was idle | W1 → **W5** |
| `GateCard.vue` `.gate-card` | `linear-gradient(145deg, rgba(255,204,0,.09), rgba(255,255,255,.025))` — the white stop is invisible on paper; its border is 1.69:1 | `--warn-bg` / `--warn-border-strong` | **W1** |
| `ChatRail.vue` `.call-chip` | `rgba(0,0,0,.2)` — a dark chip on a light bubble; `--text-muted` on it drops to **3.40:1** | `var(--surface-well)`, or `.chip` | **W3** |
| `ChatRail.vue` `.section-kicker`, `.text-button` | `--accent-cyan` 1.29:1, `--link-cyan` 4.41:1 light | `--on-accent-cyan`, `--link-strong` | **W3** |
| `DialogueRail.vue` `.text-button`, avatar | `--link-cyan`, `--character-*` | `--link-strong`; see the character row | **W3/W2** |
| Seven `rgba(153,234,249,…)` / `rgba(170,255,205,…)` literals in `ChatRail`, `DialogueRail`, `ReportPanel` | literals | `color-mix(in srgb, var(--accent-*) N%, transparent)`, the form `FieldRow.vue` already uses | **W1/W3** |
| The 9px type sites (`CrewProgress` ×2) and the remaining 10px ones | below the six-step scale | `--type-meta` | **W4** |

---

## Appendix — how to re-run everything

```powershell
Push-Location frontend
node scripts\contrast-audit.mjs                 # exits 1 while a W5 row fails
node scripts\contrast-audit.mjs --markdown > ..\docs\run-shell\evidence\T3\contrast.md
npx vitest run designTokens                     # T3.2, the literal sweep
npx vue-tsc -b --force
npm run build
npx playwright test e2e/visual/builder-canvas.spec.ts   # T3.5, the 16 baselines
Pop-Location
git log --format='%h %ad %s' --date=iso -- docs/run-shell/SHELL-SCOPE.md frontend/src/studio.css
```
