# R1 — the visual baselines, and the one that could not be regenerated

Written by RV3 (verification worker) on branch `run-shell/cast` at `27b256e`,
2026-09-05, against the free backend on :8099 started with the recipe in
`evidence/R/playwright.txt`. Playwright drove its own Vite on :5273.

RV3 built none of this work. The only product-tree edit RV3 is permitted is
regenerating the three PNGs under
`frontend/e2e/visual/run-canvas.spec.ts-snapshots/`, and only after first
recording the failing diff. That is what this file records.

---

## Step 1 — run first, record the diff

```
$ cd frontend
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1
```

```
Running 3 tests using 1 worker

  ✘  1 [chromium] › run-canvas.spec.ts:181 › looks the same idle, and the card shell resolves as authored (2.6s)
  ✘  2 [chromium] › run-canvas.spec.ts:249 › looks the same with a branch in flight, and still animates @launch (16.6s)
  ✘  3 [chromium] › run-canvas.spec.ts:338 › looks the same paused at a gate @launch (1.5s)

  3 failed
```

**The three failures are not the same kind of failure**, and that is the whole
finding:

| # | test | failure | pixels different |
| ---: | --- | --- | ---: |
| 1 | `looks the same idle` | `toHaveScreenshot(run-canvas-idle.png)` | **768** (ratio 0.01) |
| 2 | `…with a branch in flight, and still animates` | **`TimeoutError: locator.evaluate` — `.workflow-node.is-running >> .node-crew-oar` never appeared** | — (no screenshot was ever taken) |
| 3 | `looks the same paused at a gate` | `toHaveScreenshot(run-canvas-gate-waiting.png)` | **570** (ratio 0.01) |

1 and 3 are the intended change: the node medallion now holds the character
and the two-rower crew is gone (DoD T2.9). 0.01 of the image is the medallion
and the retired boat, which is the right order of magnitude for a card-sized
change on a 14-node canvas.

**2 is not a pixel diff and `--update-snapshots` cannot fix it.** The spec
still asserts the rowers exist, at `run-canvas.spec.ts:305-310`:

```ts
expect(await animationsOn(running.locator('.node-crew-oar').first()))
  .toEqual(['node-oar-stroke'])
expect(await animationsOn(running.locator('.node-crew-hull'))).toEqual(['node-hull-bob'])
expect(await animationsOn(running.locator('.node-crew-rower').first()))
  .toEqual(['node-rower-pull'])
```

and again under reduced motion at `:328`. Those three elements are exactly what
T2.9 required be removed, and they were: a grep for `node-rower|node-oar` over
`frontend/src` finds one hit, a comment in `assets/styles/node-card.css:210`
recording the retirement. So the test hangs on a locator for an element the
product no longer draws, times out after 15 s, and **never reaches its
`toHaveScreenshot('run-canvas-running.png')` call**.

RV3 may not edit a spec, and weakening this one would be worse than the red it
reports. Recorded as a FAIL against R1 and left standing.

---

## Step 2 — regenerate, for the two that are pixels

```
$ npx playwright test e2e/visual/run-canvas.spec.ts --update-snapshots
# exit 1  ·  1 failed, 2 passed (25.0s)
```

**Two PNGs were regenerated. Named, with why:**

| PNG | md5 before | md5 after | why it changed |
| --- | --- | --- | --- |
| `run-canvas-idle-chromium-win32.png` | `c1cbb91f0a5d6b606ecb3d0d0c2238ba` | `13f8208107470c54054cab689672e3ef` | every idle node card now carries its agent's character in the medallion where a per-kind lucide icon used to sit (T2.9: replaced, not duplicated) |
| `run-canvas-gate-waiting-chromium-win32.png` | `0d85fde51a1996365f88dd2fcb2723ce` | `5d2357ce8829b0c78a9b1f3493222f40` | same medallion change, plus the gate node's character showing the blocked/waiting state |

**One PNG was NOT regenerated and is now stale:**

| PNG | md5 | state |
| --- | --- | --- |
| `run-canvas-running-chromium-win32.png` | `dcb4eba955fc47394e03d20104937c39` — unchanged from the committed baseline | its test aborts on the `.node-crew-oar` locator before the screenshot is taken, so no new image was ever produced. The committed file still shows the two-rower boat. |

---

## Step 3 — re-run to confirm

```
$ npx playwright test e2e/visual/run-canvas.spec.ts
# exit 1

  1 failed
    [chromium] › run-canvas.spec.ts:249 › looks the same with a branch in flight, and still animates @launch
  2 passed (23.2s)
```

The two regenerated baselines are green and stay green. The third test fails
identically to step 1 — same locator, same 15 s timeout — which is the proof
that its red is about the retired rowers and not about a flaky capture.

---

## What this means for R1

R1 asks for a green full Playwright run with "visual baselines regenerated only
where this work intentionally changed the pixels, each named". Two are named
above and are legitimate. The third is **not a baseline problem**: it is a spec
that the cast work (W4, T2.9) contradicted and did not update. Someone who owns
`e2e/visual/run-canvas.spec.ts` has to decide between deleting the three rower
assertions and asserting the character parts that replaced them — and then a
`run-canvas-running.png` can be regenerated honestly. RV3 records the red.
