# R1 — the visual baselines, across four RV3 passes

Written by RV3 (verification worker) on branch `run-shell/cast`. RV3 built none
of this work. The only product-tree edit RV3 is permitted is regenerating the
three PNGs under `frontend/e2e/visual/run-canvas.spec.ts-snapshots/`, and only
after first recording the failing diff. That is what this file records, pass by
pass.

Backend for every run below: the free `SYNTHETIC=1` one on :8099, full line in
`evidence/R/playwright.txt`. Playwright drove its own Vite on :5273 — and in
this pass that was **verified rather than assumed**, because
`playwright.config.ts` sets `reuseExistingServer: true` and a stale Vite would
have made every capture below a picture of an older bundle. Before anything ran:
`netstat -ano | findstr :527` showed no listener on 5273/5274/5275, no
node/serve/python process was listening on any port, `Stop-Process -Name serve`
found nothing to stop, and all three ports answered nothing.

---

# FOURTH PASS — `8ae40ec`, 2026-09-05

## Step 1 — run first, record the diff

```
$ cd frontend
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1  ·  3 failed
```

All three failed on **pixels alone** — no timeout, no assertion, nothing but a
changed picture, and the diffs are the smallest of any pass:

| # | test | snapshot | pixels different |
| ---: | --- | --- | ---: |
| 1 | `:204` looks the same idle, and the card shell resolves as authored | `run-canvas-idle.png` | **22** (ratio 0.01) |
| 2 | `:272` with a branch in flight, and still animates | `run-canvas-running.png` | **8** (ratio 0.01) |
| 3 | `:390` paused at a gate | `run-canvas-gate-waiting.png` | **10** (ratio 0.01) |

22, 8 and 10 pixels on a 14-node canvas is a change to one small drawn shape.
That is what round five did: the **bun crest replaces the halo** on the
character, and the crest is a few pixels across at canvas zoom. Nothing in
rounds four or five touched the cards otherwise, and the numbers say so.

## Step 2 — regenerate

```
$ npx playwright test e2e/visual/run-canvas.spec.ts --update-snapshots
# exit 0  ·  3 passed (19.4s)
```

**All three PNGs were regenerated. Named, with why:**

| PNG | md5 before | md5 after | why it changed |
| --- | --- | --- | --- |
| `run-canvas-idle-chromium-win32.png` | `685560518ca4976383af6620b3d0bca9` | `c0372c68b79f5862cf423d8f59bbaef1` | the bun crest replaces the halo on every idle card's character (round five) |
| `run-canvas-running-chromium-win32.png` | `2306ea460978915b649bfaefbe098a28` | `68995bbcb458e3df2ce9f7bbd0789baf` | the same crest on the running card's medallion |
| `run-canvas-gate-waiting-chromium-win32.png` | `67148155a14cd056a2fe60237d134207` | `2833bddbbbe40cbd554d9121838366e3` | the same crest, on the gate node's waiting character |

**The opaque report sheet and control rail are NOT why these moved**, and that
is worth saying because it was the leading hypothesis for the third pass's
see-through capture: those three crops are the `.validator-flow` canvas element
and neither the sheet nor the rail is inside them. Round four (`fec004d`), which
made both opaque, moved these baselines by nothing at all — a run at `fec004d`
was green with no regeneration.

## Step 3 — re-run to confirm

```
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 0  ·  3 passed (19.1s)
```

## The four-pass history of these three files

| PNG | at branch start | pass 1 | pass 2 | pass 3 | pass 4 |
| --- | --- | --- | --- | --- | --- |
| `run-canvas-idle` | `c1cbb91f…` | `13f82081…` | — | `68556051…` | `c0372c68…` |
| `run-canvas-gate-waiting` | `0d85fde5…` | `5d2357ce…` | — | `67148155…` | `2833bddb…` |
| `run-canvas-running` | `dcb4eba9…` | unreachable | `0c11150e…` | `2306ea46…` | `68995bbc…` |

One line each: pass 1 moved idle and gate-waiting because the medallion took the
character from the lucide icon; pass 2 finally moved running, because RV1
replaced the assertions that pinned the retired rowers so the test could reach
its shutter for the first time; pass 3 moved all three, because four
`backdrop-filter`s went and the crests grew; pass 4 moved all three by 8–22
pixels, because the halo became a bun.

---

# THIRD PASS — `601baef`, 2026-09-05

## Step 1 — run first, record the diff

```
$ cd frontend
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1  ·  3 failed
```

**All three failed, and for the first time all three failed on PIXELS ALONE** —
no timeout, no colour assertion, nothing but a changed picture:

| # | test | snapshot | pixels different |
| ---: | --- | --- | ---: |
| 1 | `:204` looks the same idle, and the card shell resolves as authored | `run-canvas-idle.png` | **202** (ratio 0.01) |
| 2 | `:272` with a branch in flight, and still animates | `run-canvas-running.png` | **113** (ratio 0.01) |
| 3 | `:390` paused at a gate | `run-canvas-gate-waiting.png` | **97** (ratio 0.01) |

That is the shape a clean visual change makes. In particular `:204` no longer
fails at `:243` on the quarantine chip's colour — the second pass's finding
(`.studio-shell:not(.is-builder) .quarantine-count` outranking `.node-state`)
is repaired, and the contrast sheet now carries a row asserting the same fact
from the other side.

## Step 2 — regenerate

```
$ npx playwright test e2e/visual/run-canvas.spec.ts --update-snapshots
# exit 0  ·  3 passed (19.7s)
```

**All three PNGs were regenerated. Named, with why:**

| PNG | md5 before | md5 after | why it changed |
| --- | --- | --- | --- |
| `run-canvas-idle-chromium-win32.png` | `13f8208107470c54054cab689672e3ef` | `685560518ca4976383af6620b3d0bca9` | round three removed the run console's four `backdrop-filter`s (the bisect is in `evidence/T2/perf-notes.md`) and grew the small crests so a character carries identity at 32 px; both repaint every idle card |
| `run-canvas-running-chromium-win32.png` | `0c11150e764462f83da1d3d452848922` | `2306ea460978915b649bfaefbe098a28` | the same two changes on the running card, whose medallion is the largest character on the canvas |
| `run-canvas-gate-waiting-chromium-win32.png` | `5d2357ce8829b0c78a9b1f3493222f40` | `67148155a14cd056a2fe60237d134207` | the same, plus the gate node's state chip, which is the element the contrast sheet's new `node state chip` row now measures |

97–202 px on a 14-node canvas is the right order of magnitude for a blur
removal and a crest: a change to how a small element is drawn, not to what is
drawn.

## Step 3 — re-run to confirm

```
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 0  ·  3 passed (18.9s)

  ✓ :204  looks the same idle, and the card shell resolves as authored
  ✓ :272  with a branch in flight, and still animates
  ✓ :390  paused at a gate
```

**First pass in which this spec is entirely green**, and the first in which
every one of its three baselines was regenerated in the same pass and stayed
regenerated.

## The three-pass history of these three files

| PNG | committed at branch start | after pass 1 | after pass 2 | after pass 3 |
| --- | --- | --- | --- | --- |
| `run-canvas-idle` | `c1cbb91f…` | `13f82081…` | (unchanged) | `68556051…` |
| `run-canvas-gate-waiting` | `0d85fde5…` | `5d2357ce…` | (unchanged) | `67148155…` |
| `run-canvas-running` | `dcb4eba9…` | (unreachable) | `0c11150e…` | `2306ea46…` |

Reasons, one line each: pass 1 moved idle and gate-waiting because the medallion
took the character from the lucide icon; pass 2 finally moved running, because
RV1 replaced the assertions that pinned the retired rowers and the test could
reach its shutter for the first time; pass 3 moved all three, because the four
backdrop blurs went and the crests grew.

---

# SECOND PASS — `16f3be5`, 2026-09-05

## Step 1 — run first, record the diff

```
$ cd frontend
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1  ·  2 failed, 1 passed (21.8s)
```

| # | test | outcome | detail |
| ---: | --- | --- | --- |
| 1 | `:204` looks the same idle, and the card shell resolves as authored | **FAIL, and not on a pixel** | its `toHaveScreenshot('run-canvas-idle.png')` at `:207` **passed**; it then failed at `:243` on `expect(await styleOf(quarantine, 'color')).toBe(TEXT_MUTED)` — `Expected "rgb(179, 179, 179)"`, `Received "rgba(255, 255, 255, 0.52)"` |
| 2 | `:272` with a branch in flight, and still animates | FAIL, pixels | **661 pixels** (ratio 0.01) different against `run-canvas-running.png` |
| 3 | `:390` paused at a gate | **PASS** | the first pass's regenerated `run-canvas-gate-waiting.png` still matches; the coordinator expected it to move and it did not |

## Step 2 — regenerate

```
$ npx playwright test e2e/visual/run-canvas.spec.ts --update-snapshots
# exit 1  ·  1 failed, 2 passed (23.1s)
```

**One PNG was regenerated this pass. Named, with why:**

| PNG | md5 before | md5 after | why it changed |
| --- | --- | --- | --- |
| `run-canvas-running-chromium-win32.png` | `dcb4eba955fc47394e03d20104937c39` — the original committed baseline, untouched since the branch began | `0c11150e764462f83da1d3d452848922` | This is the baseline the first pass **could not** reach: at `27b256e` the spec still asserted `.node-crew-oar` / `-rower` / `-hull` and timed out before the shutter. RV1 rewrote those assertions to the cast, so the test now reaches its screenshot — and the picture is different because the running card's medallion carries the agent's character where the two-rower boat used to be (T2.9), 661 px of a 14-node canvas. |

**Two were NOT regenerated this pass, and both are correct as they stand:**

| PNG | md5 | state |
| --- | --- | --- |
| `run-canvas-idle-chromium-win32.png` | `13f8208107470c54054cab689672e3ef` | regenerated in the FIRST pass; still matches at `16f3be5`, so `--update-snapshots` wrote the same bytes back |
| `run-canvas-gate-waiting-chromium-win32.png` | `5d2357ce8829b0c78a9b1f3493222f40` | regenerated in the FIRST pass; its test passes outright |

**So all three baselines have now moved from their committed values**, and each
is named with a reason:

| PNG | committed at `16f3be5` | now | pass that moved it |
| --- | --- | --- | --- |
| `run-canvas-idle` | `c1cbb91f0a5d6b606ecb3d0d0c2238ba` | `13f8208107470c54054cab689672e3ef` | first — every idle card's medallion holds its agent's character where a per-kind lucide icon sat |
| `run-canvas-gate-waiting` | `0d85fde51a1996365f88dd2fcb2723ce` | `5d2357ce8829b0c78a9b1f3493222f40` | first — the same medallion change, plus the gate node's character in its waiting pose |
| `run-canvas-running` | `dcb4eba955fc47394e03d20104937c39` | `0c11150e764462f83da1d3d452848922` | second — the running card's character replaces the two-rower boat |

## Step 3 — re-run to confirm

```
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1  ·  1 failed, 2 passed (21.6s)

  ✘ :204  looks the same idle, and the card shell resolves as authored
  ✓ :272  with a branch in flight, and still animates
  ✓ :390  paused at a gate
```

Both regenerated baselines are green and stay green. The idle test fails
identically to step 1 — same line, same two colour strings — which is the proof
that its red is a real restyle and not a flaky capture.

## The one red, and why it is a finding rather than a stale test

`run-canvas.spec.ts:243` is not an incidental assertion. Its own comment says
what it is for:

> `.quarantine-count` and `.node-state` are on the **SAME element** and set the
> same two properties at the same specificity; `.node-state` wins **only because
> it is written later**. Extract `.node-state` alone and the scoped
> `.quarantine-count` … outranks it, and the chip silently restyles. Both rules
> move together for this reason.

The chip really has restyled, and the mechanism is the one the comment predicts
arriving by a different door. Traced at `16f3be5`:

```
node-card.css:96    .quarantine-count { color: var(--text-40) }      (also on main)
node-card.css:181   .node-state       { color: var(--text-muted) }   (also on main)
```

Same specificity, `.node-state` later, so on `main` the chip is
`--text-muted` = `#b3b3b3` = `rgb(179, 179, 179)`, exactly what the spec expects.
Round two then added, in `motion.css:392-397`:

```
.studio-shell:not(.is-builder) .node-eyebrow,
.studio-shell:not(.is-builder) .quarantine-count,      <- this one
.studio-shell:not(.is-builder) .node-active-query,
.studio-shell:not(.is-builder) .node-active-hint,
.studio-shell:not(.is-builder) .node-usage { color: var(--text-meta) }
```

That selector carries a class and a `:not()`, so it **outranks both** and the
chip now resolves `--text-meta`, which in the dark palette is
`rgba(255, 255, 255, 0.52)` (`tokens.css:198`) — the received value, to the
character.

So the two rules the file insists must move together no longer do: the
quarantine chip took a contrast-driven colour that its twin `.node-state` did
not. Whether that is wanted is a judgement for whoever owns `motion.css`'s guard
(the audit needed `.node-eyebrow` in that list; `.quarantine-count` is four
selectors of convenience alongside it, and the comment above it says the five
were written as one rule so they "cannot drift apart"). RV3 does not edit
product code and does not weaken a test, so the red stands.

---

# FIRST PASS — `27b256e`, 2026-09-05

Kept because it is where two of the three baselines moved, and because it is the
record of a red that round two then fixed.

## Step 1 — run first, record the diff

```
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1  ·  3 failed
```

| # | test | failure | pixels different |
| ---: | --- | --- | ---: |
| 1 | `looks the same idle` | `toHaveScreenshot(run-canvas-idle.png)` | **768** (ratio 0.01) |
| 2 | `…with a branch in flight, and still animates` | **`TimeoutError` — `.workflow-node.is-running >> .node-crew-oar` never appeared** | — (no screenshot was ever taken) |
| 3 | `looks the same paused at a gate` | `toHaveScreenshot(run-canvas-gate-waiting.png)` | **570** (ratio 0.01) |

1 and 3 were the intended change: the node medallion now holds the character and
the two-rower crew is gone (T2.9). **2 was not a pixel diff and
`--update-snapshots` could not fix it** — the spec still asserted the rowers at
`:305-310` and `:328`, timed out on a locator for an element the product no
longer draws, and never reached its `toHaveScreenshot('run-canvas-running.png')`.

## Step 2 — regenerate, for the two that were pixels

```
$ npx playwright test e2e/visual/run-canvas.spec.ts --update-snapshots
# exit 1  ·  1 failed, 2 passed (25.0s)
```

| PNG | md5 before | md5 after | why it changed |
| --- | --- | --- | --- |
| `run-canvas-idle-chromium-win32.png` | `c1cbb91f0a5d6b606ecb3d0d0c2238ba` | `13f8208107470c54054cab689672e3ef` | every idle node card now carries its agent's character in the medallion where a per-kind lucide icon used to sit |
| `run-canvas-gate-waiting-chromium-win32.png` | `0d85fde51a1996365f88dd2fcb2723ce` | `5d2357ce8829b0c78a9b1f3493222f40` | same medallion change, plus the gate node's character showing the blocked/waiting state |

`run-canvas-running-chromium-win32.png` could not be produced and stayed at
`dcb4eba955fc47394e03d20104937c39`.

## Step 3 — re-run to confirm

```
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1  ·  1 failed, 2 passed (23.2s)
```

The third test failed identically, which was the proof its red was about the
retired rowers rather than a flaky capture. **RV1 fixed it in round two**, which
is how the second pass above could finally regenerate that third baseline.
