# `builder.spec.ts:1227` — is it this branch's fault?

Written by **RV3** (verification worker) on 2026-09-05, at branch head
`c054087` (the commit that landed RV3's third-pass evidence; the last commit to
touch product source is `601baef`). RV3 built none of this work, edited no
product code, and did not touch `builder.spec.ts`.

## Why this was measured

`the canvas, in a browser › paints the target handle green when it will take the
edge and red when it will not` failed in RV3's third-pass full suite **and then
failed again when re-run alone** — which the first two passes never saw, and
which `CLAUDE.md` remaining-work item 44 never recorded. Item 44 describes a
*timing* flake in the drag tests that passes when isolated. A test that fails
alone is not that, so the question is whether this branch caused it.

## Method

**One variable.** Both arms ran the same test file against the same backend on
the same machine, minutes apart:

* `frontend/e2e/builder.spec.ts` is **byte-identical** between `main` and this
  branch — `git diff main...HEAD -- frontend/e2e/builder.spec.ts` prints nothing,
  and both trees md5 to `202431502439f0fca9397a3e3cad1b6e`. The test is at line
  1227 in both.
* **One backend, shared by both arms**: `SYNTHETIC=1
  SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099` from the branch tree, with the
  usual `CREDENTIALS_MASTER_KEY`, `BUILDER_ALLOW_GATELESS_GRAPHS=1`,
  `RUN_RATE_LIMIT_MAX_RUNS=100`, `MCP_ALLOW_INSECURE_LOCAL=1` and `SKILLS_ROOT`.
  Legitimate because the builder API is unchanged on this branch: `R2`'s diff
  shows `git diff 16f3be5..HEAD -- src/` is empty and the only `src/brief_crew`
  files this branch touches at all are `builder/descriptor.py`,
  `service/runner.py` and `service/builder_runner.py`. So no `.env` copy and no
  `PYTHONPATH` were needed — no second backend was started.
* The only thing that differs between the arms is **which frontend source Vite
  serves**.

**The `main` arm, and how it was proved to be `main`.** A temporary worktree,
with the branch tree's `node_modules` junctioned in rather than reinstalled:

```powershell
git worktree add D:\wt-main main                       # -> 6291fee
New-Item -ItemType Junction -Path D:\wt-main\frontend\node_modules `
         -Target D:\MultiAgentSystem\frontend\node_modules
```

`E2E_UI_PORT=5275` for every worktree run, so Playwright's
`reuseExistingServer: true` had nothing on that port to reuse and had to start
the worktree's own Vite. That is the trap this arm exists to avoid, so it was
closed rather than assumed. Proof, taken against a worktree Vite left running on
:5275 afterwards:

```
$ curl -s http://127.0.0.1:5275/src/components/WorkflowNode.vue | grep -c AgentCharacter
0
$ grep -c AgentCharacter D:/MultiAgentSystem/frontend/src/components/WorkflowNode.vue
3          # the branch's copy imports the cast
$ grep -c AgentCharacter D:/wt-main/frontend/src/components/WorkflowNode.vue
0          # main's does not
```

(`/src/characters/pip.ts` answers `200` from that server, which looks alarming
and is not: the body is `<!doctype html>` — Vite's SPA fallback for a path it
cannot resolve. The `AgentCharacter` count is the probe that actually
discriminates.)

## The result

```
$ npx playwright test e2e/builder.spec.ts:1227      # five times per arm
```

| run | HEAD (`run-shell/cast`, `c054087`) | `main` (`6291fee`) |
| ---: | --- | --- |
| 1 | **FAIL** (15.9 s) | **FAIL** (15.9 s) |
| 2 | **FAIL** (16.0 s) | **FAIL** (15.9 s) |
| 3 | **FAIL** (16.0 s) | **FAIL** (16.0 s) |
| 4 | **FAIL** (15.9 s) | **FAIL** (16.0 s) |
| 5 | **FAIL** (16.0 s) | **PASS** (3.5 s) |
| | **0 / 5 pass** | **1 / 5 pass** |

## The failure shape — identical in both arms

Every failing run in both arms produced the same call log, to the sentence:

```
TimeoutError: locator.hover: Timeout 15000ms exceeded.
Call log:
  - waiting for locator('.vue-flow__handle.source[data-nodeid="tool_1"][data-handleid="attach"]')
    - locator resolved to <div data-nodeid="tool_1" data-handleid="attach" … class="… builder-port is-port-out is-port-attach">
  - attempting hover action
    2 × waiting for element to be visible and stable
      - element is not stable
    …
  27 × retrying hover action
       - waiting 500ms
       - waiting for element to be visible and stable
       - element is visible and stable
       - scrolling into view if needed
       - done scrolling
       - <span class="problem-message">tool_1 names the tool 'tool', which is not in thi…</span>
         from <section class="problems-panel">…</section> subtree intercepts pointer events
  - retrying hover action
    at builder.spec.ts:1260  ->  await port(page, tool.id, 'attach').hover()
```

Counted rather than eyeballed: the `problems-panel … intercepts pointer events`
line appears in **5 of 5** HEAD runs and **4 of 4** failing `main` runs, and in
the one passing run it does not appear at all.

**So this is not a timing flake and not a drag-gesture problem.** The handle
resolves, becomes visible and stable, and is then covered: the problems dock —
specifically the `problem-message` span reading *"tool_1 names the tool 'tool',
which is not in thi…"* — sits over the attach port the test needs to hover.
Playwright retries for the full 15 s because the element never stops being
occluded. The `element is not stable` lines at the start are the dock animating
in; the interception is what the retries then hit.

## Verdict

**Not this branch's fault, and worse than item 44 says.**

* The regression is **present on `main`** at a 4-in-5 failure rate, so nothing
  in `run-shell/cast` introduced it. The branch's contribution is at most the
  last 20 percentage points, and one extra run at each arm would be inside the
  noise of that difference — with n=5 per arm, 0/5 against 1/5 is not a
  distinguishable rate.
* **Item 44's description is wrong for this test.** It records these drag tests
  as flaky *and passing when run alone*; this one fails alone, 5 times out of 5
  on the branch and 4 out of 5 on `main`, with a deterministic-looking cause.
  Whoever owns item 44 should split this test out of it: the other drag test,
  `builder.spec.ts:1552`, still behaves the way item 44 describes — it failed in
  RV3's third-pass suite and passed alone in 2.4 s.
* The fix is a **layout** question for whoever owns the problems dock and
  `builder.spec.ts`, not a timing one: either the dock must not cover a port, or
  the test must dismiss or scroll past it before hovering. RV3 does not edit
  either.

## Teardown

The worktree and its junction were removed after the measurement
(`git worktree remove D:\wt-main --force`), and the probe Vite on :5275 was
stopped. Nothing outside `docs/run-shell/evidence/` was written.
