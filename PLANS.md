# PLANS.md — the gauntlet build tracker

The one place the **status** of each feature plan is recorded. The plans
themselves are one file per feature under `.agent/plans/`; the method for
finishing one is `benchmarks/README.md`; the judge's ledger is
`benchmarks/DEFECTS.md`. `CLAUDE.md` stays the session file and is not
restated here. Update this table when a plan's `Status` line changes, and
nowhere else.

Spec: `C:\Users\Simon\Downloads\gauntlet-crewai-visual-builder.md`.
Baseline: `main` = `25634c0`, 2026-09-02.

## Status legend

`Planned` → `In build` → `In judge (round n)` → `Built` · `Blocked (why)`

A plan is `Built` only when every numbered acceptance criterion is ticked
in its own file, three judge rounds have run, every dimension scored ≥ 8,
and it has no open row in `benchmarks/DEFECTS.md`.

## The plans

| # | Plan | Owner | Gates on | Criteria | Ticked | Round | Open defects | Status | Updated |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 00 | [Architecture](.agent/plans/00-architecture.md) | S1 / S9 | — | 7 | 7 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 01 | [Auth and workspaces](.agent/plans/01-auth-and-workspaces.md) | S1 | 00 | 13 | 13 | 3 + product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 02 | [Canvas](.agent/plans/02-canvas.md) | S2 | 00 | 14 | 13 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 03 | [Node library](.agent/plans/03-node-library.md) | S2 | 00 | 11 | 11 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 04 | [Inspector and params](.agent/plans/04-inspector-and-params.md) | S3 | 03, 05 | 11 | 11 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 05 | [Model registry](.agent/plans/05-model-registry.md) | S3 | 00 | 11 | 11 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 06 | [Tool registry](.agent/plans/06-tool-registry.md) | S4 | 01, 03 | 11 | 11 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 07 | [MCP client](.agent/plans/07-mcp-client.md) | S4 | 01, 03 | 10 | 10 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 08 | [Skills](.agent/plans/08-skills.md) | S4 | 01, 03 | 10 | 10 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 09 | [Compiler](.agent/plans/09-compiler.md) | S5 | 03, 05, 06, 07, 08 | 12 | 12 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 10 | [Runtime](.agent/plans/10-runtime.md) | S5 | 09 | 12 | 12 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 11 | [Run visualizer](.agent/plans/11-run-visualizer.md) | S6 | 10 | 15 | 14 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 12 | [Error handling](.agent/plans/12-error-handling.md) | S7 | 10 | 10 | 9 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 13 | [Flow testing](.agent/plans/13-flow-testing.md) | S7 | 10 | 11 | 11 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 14 | [Templates](.agent/plans/14-templates.md) | S8 | 09 | 10 | 9 | product-1 | 0 | In judge (product-1) | 2026-09-04 |
| 15 | [Persistence](.agent/plans/15-persistence.md) | S1 | 01 | 11 | 11 | 3 + product-1 | 1 | In judge (product-1) | 2026-09-04 |
| | **Total** | | | **179** | ~~123~~ **175** | | ~~18~~ **1** | | |

**Regenerated 2026-09-04 from the sixteen plan files themselves**, criterion by
criterion, which is defect **P-11**'s fix. `benchmarks/rounds/product-1.md`
measured this table **85 commits stale** (`git log -1 --format=%H -- PLANS.md`
→ `5562bd6`; `git log --oneline 5562bd6..HEAD | wc -l` → 85) while twelve plan
files had changed in that window, and scored dimension 16 at **4/10** for it.
Method: `Criteria` is the count of numbered items under each plan's
`## Acceptance criteria`; `Ticked` is that plan's own `## Status` per-criterion
table with the **latest dated section winning per criterion**, `met` / `met (…)`
/ `done` / `holds` counting and `partial` / `not reached` / `not done` /
`not this session's` not.

The four criteria still unticked, named so nobody has to diff for them:

| plan | # | state in its own Status |
| ---: | ---: | --- |
| 02 | 8 | **partial** — the 48/60-node frame budget: p95 met with 3.2 ms of headroom, the **mean** missed by 0.01–0.15 ms across five runs, and both assertions are left red rather than the budget widened |
| 11 | 14 | **not this session's** — the blind reference comparison, which is the Integrator's judge round. Product-1 ran it and **disclosed that it was not blind**, so this does not tick |
| 12 | 10 | **partial** — every trigger exists and the cause is on the node; the four-screenshot review at 1440×900 is not done |
| 14 | 9 | **not done — the owner's money** — one paid run per template, MISSION §12 item 2 and decision 22 |

Two of those figures are worth stating plainly because they are the sort this
repository keeps getting wrong. **The published `123` understated by 52, not by
the round's estimated 33** — P-11 said "≥ 156 / 179" from the three plans whose
prose it read, and counting all sixteen answers **175**. And **`Round` is not a
count of judge rounds for most plans**: only 01 and 15 have had three per-plan
rounds; every other plan's first judging of any kind was product-1, which is why
no plan can reach `Built` on the round-count clause alone regardless of its
score.

**Plan 12's own prose and its own table disagree, and the table was used.** The
`### Built — 2026-09-04` paragraph opens *"Eight of ten met, one partial, one
not reached"* over a table whose ten rows are nine `met` and one `partial`. The
table is the per-criterion record this column is defined against, so 12 reads
**9**; the sentence above it needs a correction in that plan, which is not this
file's to make.

**Plan 03 is the one row resting on prose rather than on a table.** Its Wave A/B
closers table covers criteria 7–10; criteria 1–6 and 11 are recorded only as
sentences (*"Criteria 1 (TS half), 6 and 11 were already met by the client
half"*, and *"Criteria 2, 3, 4 and 5"* as the server half's subject). Counted as
ticked on that prose. It is exactly the shape P-11's second half asks to be
fixed — one state token per criterion row — and it is recorded here rather than
invented into the plan.

Build order: S1 (00, 01, 15) → S2 / S3 / S4 in parallel → S5 (09, 10) →
S6 / S7 / S8 in parallel → S9 integrates, runs the E2E and the final
gauntlet. Contracts C1–C12 are indexed in `00-architecture.md`; the
Integrator owns every change to one.

## Stage 0 — RAMP

| | State | Where |
| --- | --- | --- |
| **R** rules | **Declined 2026-09-02**: `CLAUDE.md` stays the session file and is not replaced by `@AGENTS.md`. A rules block may still be prepended to `CLAUDE.md`; the paste-ready text is `.agent/RULES.draft.md`. Not applied. | `00-architecture.md` D10 |
| **A** augment | Done | `docs/crewai-notes.md`, `docs/flowise-notes.md`, `docs/chatdev-notes.md`, `docs/design.md`, `.agent/mcp.json` |
| **M** map | Done — sixteen plan files, 179 numbered criteria | `.agent/plans/` |
| **P** prove | Ladder in place: Playwright MCP → `npx playwright test` against the synthetic backend → CLI → screenshots | `benchmarks/README.md` |
| **J** judge | **Seven rounds run**, 2026-09-03/04: plans 01 and 15 three each (`rounds/01-1..3`, `rounds/15-1..3`) plus the first whole-product round (`rounds/product-1.md`). 44 ledger rows opened, **43 closed, 1 open** (D-15-2) | `benchmarks/README.md`, `benchmarks/DEFECTS.md` |

## Decisions for the owner

Consolidated from every plan's `Status` section. A decision moves from
*open* to a dated answer here **and** in the plan that raised it.

| # | Decision | Raised in | Recommendation | Answer |
| ---: | --- | --- | --- | --- |
| 1 | Replace `CLAUDE.md` with `@AGENTS.md` and move it to `docs/handoff.md` | 00 D10 | — | **Declined, 2026-09-02** |
| 2 | Prepend the rules block (`.agent/RULES.draft.md`) to `CLAUDE.md` and smoke-test it | 00 D10 | yes, one paste | **Taken, 2026-09-04** — applied in `c9e8521` |
| 3 | Code interpreter: BYO E2B key behind a flag, or cut | 06 D8, 01 | BYO E2B, not started until decided | **OFF — ruled 2026-09-05** (owner delegated the four provisional decisions to the Integrator): a code interpreter runs a stranger's code under a key the platform does not hold; `BUILDER_CODE_INTERPRETER_ENABLED` stays unset in production |
| 4 | Commission character art, or ship icon medallions through the gauntlet | 11 | medallions first | **Icon medallions**, 2026-09-04 |
| 5 | Roster: keep `deepseek/deepseek-r1` ($2.50 out) or swap for `deepseek-v3.2` | 05 | keep, show the output price | **Keep `deepseek-r1` and show its output price on the card**, 2026-09-04 |
| 6 | Measure `cost_in_max_endpoint` per model, or accept the 1.8 factor | 05 | measure once at build time | **Measure once at build time**, 2026-09-04 |
| 7 | Allow any stdio MCP command in production | 07 | none — remote only | **Remote servers only — ruled 2026-09-05.** `MCP_STDIO_ENABLED` stays unset in production; a document must never be able to name a server-side process, which is the same reason the compiler's action refs are a closed set |
| 8 | A suspicious MCP tool: selectable with a warning, or shown only | 07 | selectable | **Selectable with a warning — ruled 2026-09-05.** The warning is information the author needs and hiding the tool would be the quietly-divergent picker R10 refused; no knob, it is the built behaviour |
| 9 | Platform Firecrawl key as the default for every user, with a daily cap | 06 | yes, per-user override | **ON — ruled 2026-09-05.** `BUILDER_PLATFORM_FIRECRAWL_DEFAULT=1` set on the Render API service through the Render API that day, with `BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` at its default 50 per user per UTC day and the per-user override still honoured. Without it a cold sign-in cannot run any research template, which rubric 15 requires; the cap bounds the owner's exposure |
| 10 | Skills attachable to library agents, or authored only | 08 | authored only | **Authored only**, 2026-09-04 |
| 11 | Licence header on the built-in skills; the repo has no `LICENSE` | 08, CLAUDE.md item 17 | settle the repo licence first | **MIT, 2026-09-04** — ~~Not answerable~~. `LICENSE` at the root and `license = "MIT"` in `pyproject.toml` (`e7dfb86`); the four built-in packs carry `license: MIT` in their frontmatter (`f122322`). `docs/licensing.md` records the decision |
| 12 | Library crew `tier`: refuse it, or honour it by rebuilding the crew's LLMs | 09 | refuse | **Refuse**, 2026-09-04 |
| 13 | `or_` inside a cycle depends on private `_discard_or_listener` | 09 | accept, as closed item 35 did | **Accept, with a guard test**, 2026-09-04 |
| 14 | A BYO OpenRouter key exempts a run from the $10 ceiling | 10 | no | **No**, 2026-09-04 |
| 15 | Stream-chunk coalescing at 250 ms, or a larger frame ring | 10 | 250 ms | **Coalesce at 250 ms**, 2026-09-04 |
| 16 | Retry a model refusal with the fallback model | 12 | no | **No**, 2026-09-04 |
| 17 | Test runs appear in run history, labelled `test` | 13 | yes | **Yes, labelled `test`**, 2026-09-04 |
| 18 | Attachment palette hotkeys `T`/`M`/`K` or `8`/`9`/`0` | 03 | letters | **Letters `T`, `M`, `K`**, 2026-09-04 |
| 19 | Expert switch global or per node kind | 04 | global | **Global**, 2026-09-04 |
| 20 | Re-baseline the validator's three screenshots, or gate the new styling to builder graphs | 11 | re-baseline once | **Re-baseline once**, 2026-09-04 |
| 21 | Delete `minimal-gated-agent` and `fan-out-join` once the E2E is re-pointed | 14 | keep in a "more" row | **Keep both in a "more" row**, 2026-09-04 |
| 22 | The four paid template runs before or after the rubric gate | 14 | after | **After the rubric gate, and after asking** — the owner must approve the spend, 2026-09-04 |
| 23 | `VALIDATOR_RUN_RETENTION_DAYS` default | 15 | `0`, keep everything | **`0` — keep everything**, 2026-09-04 |
| 24 | Deleting a published document: unpublish automatically or refuse | 15 | refuse | **Refuse**, 2026-09-04 |
| 25 | PostgreSQL two-writer job on every push or only on `main` | 15 | `main` | **On `main` only**, 2026-09-04 |
| 26 | Unowned published workflows stay launchable by anyone | 01 D1 | yes, for legacy rows | **Yes, for legacy rows**, 2026-09-04 — already built on this recommendation |
| 27 | The $1.00 model ceiling: measure it against the headline price or the max endpoint price | 05 D9 | max endpoint | **Max endpoint, 2026-09-04** — and enforced at the API with `provider.max_price`, not only asserted in a test |

## Log

| Date | What |
| --- | --- |
| 2026-09-04 | **Waves C and D, the round-3 build, the product gauntlet and a licence** — `9b06e40..HEAD` (`a3c9a31`), **88 commits**. Plans **11**, **12** and **13** built and merged (`4020d5d`, `69f7f22`, `34a3918`): the run console now says who is speaking, which edge was walked and what phase a run is in for a graph somebody *drew*; five failure modes carry a real error class; and a docked test panel runs a graph in `dry_run` / `test` / `node_test` with saved inputs. The **six wave A/B backend closers** landed in `47dc548` (04-6, 06-3, 06-8, 07-1, 07-8, 08-7) and the E2E half in `12d5030`; six further **integration closers** the merged tree exposed in `5cb7092`. The **18-row round-3 build** merged as `238c967`, one commit per ledger id. Then **judge round product-1** (`a38ef09` / `a3c9a31`, persona design director, the first WHOLE-PRODUCT round): a verifier re-ran all eighteen open rows and found **seventeen ABSENT, one PRESENT** — D-15-2, for the fourth round running and this time with nothing docked. The seventeen are closed in `benchmarks/DEFECTS.md`; **one row is open**. All sixteen dimensions scored in one pass: **6 = 7, 12 = 7, 15 = 6, 16 = 4 are under the gate of 8**, and every engineering dimension is under its reference. The round ranked **P-01 … P-11** rather than filing ledger rows, so they live in `benchmarks/rounds/product-1.md` and in this line — chief among them **P-01** (a user's `SKILL.md` body silently discarded by a double-prefixed relative `SKILLS_ROOT`, invisible to 2,420 green tests because every skill test patches the root to an *absolute* tempdir), **P-02** (the E2E suite red at the round's HEAD) and **P-11** (this table). Measured by the round at `5cb7092`, per product-1: **Python 2420 run · 0 failures · 6 skipped · 152.1 s**; **frontend 1682 passed in 84 files**; `vue-tsc` exit 0; build 772 ms; **E2E 121 passed · 7 failed · 9.0 min** over 128 tests in 23 files. Six of those seven failures are the visual baselines P-02 names and `ea4202f` re-baselined three minutes after the round's HEAD — the suite WAS re-run on the final integrated tree at `953ccbd` on 2026-09-05, after `ea4202f`, the seven product-1 fixes (`5e757be`, P-01 … P-09) and the limiter knob, and it is **GREEN: 130 passed · 0 failed · 0 skipped · 8.1 min** — with unit suites at **Python 2439 / 0 / 6** and **frontend 1696 in 84 files**. The repository now has a **licence**: MIT, `LICENSE` at the root with `license = "MIT"` in `pyproject.toml` and `"license": "MIT"` in `frontend/package.json` (`e7dfb86`), and the four built-in skill packs carry `license: MIT` (`f122322`) — which answers decision **11**, open since it was raised because it could not be answered. Spend this wave, per the round file and MISSION §11a: **$0.00** in the judge round; the programme total stands at $0.0417 of the $5.00 allowance. |
| 2026-09-04 | Plan 09 built on `gauntlet/plans`. The compiler compiles the thing the gauntlet is about: an **authored** agent and crew through the same two entrypoints, attachments and crew members folded into their `with:` block, `on_error: route` as a paired router, `or_` joins with the cycle re-arm decision 13 accepted, a `json_schema` state, the eleventh action ref `runtime:replay_output` and the derived plans it serves, a YAML+Python code preview that cannot read a key, and twenty determinism goldens compared three ways. All 12 criteria met. `BUILDER_ACTION_REFS` is **eleven**; C8 grew 50 → 55 codes and `WARNING_CODES` 5 → 7; the budget RESPONSE gained `per_node`. Two things were measured on a flow that ran and are in the plan's Status rather than reasoned from a schema: a compiled `{or: [a, b]}` over two plain method names is a CrewAI **racing group** that cancels the loser and the join with it, so an undeclared diamond now compiles to `and`; and the D5 re-arm is defence in depth, because `_clear_or_listeners()` already covers the topology it was written for. Python 2115 (from 2023) / frontend 1426 in 73 files / `vue-tsc` exit 0 / build 603 ms. E2E not run - nothing here reached a route. $0.00 spent. |
| 2026-09-04 | All 25 open owner decisions answered. Each answer is in the decision table above and in the `## Status` section of every plan that raised it — 00, 01, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14 and 15. Four are **provisional** and say so in both places: 3, 7, 8 and 9 are built up to the surface, left off, and wait for the owner. Decision 11 is **not answerable** while the repository has no `LICENSE`, so the built-in skills ship with no licence header and the dependency is recorded. Decision 2 was taken in `c9e8521`, which put the rules block at the head of `CLAUDE.md` with two clauses amended — parallel subagents authorized, and a money bound the draft did not carry. No code changed and no criterion moved. |
| 2026-09-03 | Plan 15 round 3 built on `gauntlet/plans`, `f2a3bb8` → `38d7635`. Twelve open rows built in eleven fixing commits (D-15-19 and D-15-20 share one - they are one defect the critic scored on two dimensions), preceded by two docs commits that fix no defect: `8231966` moves the ten misplaced round-2 rows into the ledger table, and `ca3d4f8` is the OWNER'S RULING closing D-15-8 … D-15-12 on the round-2 verifier's output, which is why 15's open count moved 17 → 12. Every built row is left `open` for the round-3 critic. That ruling also retires this plan's keep-the-earlier-wording convention: criteria 7 and 8 now strike the wrong figure inline, because the critic has scored a ticked criterion whose first sentence is false three times. The plan's per-module counts were regenerated by running each module alone - the verifier had found `test_isolation_matrix` at 32 where the table said 16. Python 1655 / PostgreSQL 18 5/5 / frontend 1195 in 65 files / E2E 37 in 5 files, all green. |
| 2026-09-03 | Plan 01 round 3 built on `gauntlet/plans`, `f2a3bb8` → `e22a32f`. One commit for the one open row: D-01-5 `e22a32f` - browser residue (the builder draft holding a `credential_id`, the run handoff, the run pointer) is keyed to the signed-in user's id, so the next person on the same browser reads none of it even when the previous one never signed out, and a sign-out sweeps what that identity wrote. The row is left `open` for the round-3 critic. Preceded by `20d51a4`, the OWNER'S RULING closing D-01-1 and D-01-2 on the round-2 verifier's output, which is why 01's open count moved 3 → 1; it is docs-only and separate so the log cannot read as a builder closing its own work. Plan 01's Status now names every fixing commit per id, **including round 2's four**, which it had never listed. Python 1642 / frontend 1180 / E2E 35, all green. |
| 2026-09-02 | Audit against `25634c0`; sixteen plans, three reference notes, design system, judge scaffolding written. Nothing committed. Decision 1 declined by the owner. |
| 2026-09-03 | Plan 15 round 2 built on `gauntlet/plans`: twelve fixing commits, one per ledger id (`95dfd70` … see the plan's Status), every row left open for the critic. Decision 24 is now built rather than assumed — `POST …/unpublish` exists and delete refuses while any version is registered. A second additive column, `builder_document_versions.source`, recorded against C10. |
| 2026-09-03 | 01 and 15 criteria complete and integrated on `gauntlet/plans` at `18a7944`: four builder branches merged (`bc6eab6`, `a44fa3d`, `9f6e63b`, `831ae6b`), three defects found only by the merged tree fixed (`348af34`, `e62235a`), the two-writer test run 5/5 against PostgreSQL 18.6, the 33-test E2E suite green with `CREDENTIALS_MASTER_KEY` set, ten builder constants moved into `config.py`, §6 regenerated at 41. Python 1548 / frontend 1131. **No judge round has run** — `In judge (round 1 pending)` means the criteria are ticked and the critic has not been invoked; the round file does not exist yet. Console mock-mode defect recorded as CLAUDE.md item 43. |
| 2026-09-02 | Plan set committed on `gauntlet/plans`. S1 starts on 01 and 15: the Integrator lands C10's six tables, `runs.mode`, the six config knobs and ten S1 rulings (`00-architecture.md`, Status) first, then four agents build 01 API, 01 UI, 15 API and 15 UI on their own branches. Decisions 23–26 are built on their recommendation and stay open. |
