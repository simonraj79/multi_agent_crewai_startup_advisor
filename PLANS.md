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
| 00 | [Architecture](.agent/plans/00-architecture.md) | S1 / S9 | — | 7 | 7 | — | 0 | In build | 2026-09-04 |
| 01 | [Auth and workspaces](.agent/plans/01-auth-and-workspaces.md) | S1 | 00 | 13 | 13 | 2 | 1 | In build (round 3) | 2026-09-03 |
| 02 | [Canvas](.agent/plans/02-canvas.md) | S2 | 00 | 14 | 14 | — | 0 | In build | 2026-09-04 |
| 03 | [Node library](.agent/plans/03-node-library.md) | S2 | 00 | 11 | 6 | — | 0 | In build | 2026-09-04 |
| 04 | [Inspector and params](.agent/plans/04-inspector-and-params.md) | S3 | 03, 05 | 11 | 0 | — | 0 | Planned | 2026-09-02 |
| 05 | [Model registry](.agent/plans/05-model-registry.md) | S3 | 00 | 11 | 0 | — | 0 | Planned | 2026-09-02 |
| 06 | [Tool registry](.agent/plans/06-tool-registry.md) | S4 | 01, 03 | 11 | 0 | — | 0 | Planned | 2026-09-02 |
| 07 | [MCP client](.agent/plans/07-mcp-client.md) | S4 | 01, 03 | 10 | 0 | — | 0 | Planned | 2026-09-02 |
| 08 | [Skills](.agent/plans/08-skills.md) | S4 | 01, 03 | 10 | 0 | — | 0 | Planned | 2026-09-02 |
| 09 | [Compiler](.agent/plans/09-compiler.md) | S5 | 03, 05, 06, 07, 08 | 12 | 0 | — | 0 | Planned | 2026-09-02 |
| 10 | [Runtime](.agent/plans/10-runtime.md) | S5 | 09 | 12 | 0 | — | 0 | Planned | 2026-09-02 |
| 11 | [Run visualizer](.agent/plans/11-run-visualizer.md) | S6 | 10 | 15 | 0 | — | 0 | Planned | 2026-09-02 |
| 12 | [Error handling](.agent/plans/12-error-handling.md) | S7 | 10 | 10 | 0 | — | 0 | Planned | 2026-09-02 |
| 13 | [Flow testing](.agent/plans/13-flow-testing.md) | S7 | 10 | 11 | 0 | — | 0 | Planned | 2026-09-02 |
| 14 | [Templates](.agent/plans/14-templates.md) | S8 | 09 | 10 | 0 | — | 0 | Planned | 2026-09-02 |
| 15 | [Persistence](.agent/plans/15-persistence.md) | S1 | 01 | 11 | 11 | 2 | 12 | In build (round 3) | 2026-09-03 |
| | **Total** | | | **179** | **51** | | **13** | | |

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
| **J** judge | Scaffolded, no round run | `benchmarks/README.md`, `benchmarks/DEFECTS.md` |

## Decisions for the owner

Consolidated from every plan's `Status` section. A decision moves from
*open* to a dated answer here **and** in the plan that raised it.

| # | Decision | Raised in | Recommendation | Answer |
| ---: | --- | --- | --- | --- |
| 1 | Replace `CLAUDE.md` with `@AGENTS.md` and move it to `docs/handoff.md` | 00 D10 | — | **Declined, 2026-09-02** |
| 2 | Prepend the rules block (`.agent/RULES.draft.md`) to `CLAUDE.md` and smoke-test it | 00 D10 | yes, one paste | **Taken, 2026-09-04** — applied in `c9e8521` |
| 3 | Code interpreter: BYO E2B key behind a flag, or cut | 06 D8, 01 | BYO E2B, not started until decided | BYO E2B behind a flag, default OFF — **PROVISIONAL, owner to confirm before enabling**, 2026-09-04 |
| 4 | Commission character art, or ship icon medallions through the gauntlet | 11 | medallions first | **Icon medallions**, 2026-09-04 |
| 5 | Roster: keep `deepseek/deepseek-r1` ($2.50 out) or swap for `deepseek-v3.2` | 05 | keep, show the output price | **Keep `deepseek-r1` and show its output price on the card**, 2026-09-04 |
| 6 | Measure `cost_in_max_endpoint` per model, or accept the 1.8 factor | 05 | measure once at build time | **Measure once at build time**, 2026-09-04 |
| 7 | Allow any stdio MCP command in production | 07 | none — remote only | Remote servers only in production; stdio behind a flag that is OFF — **PROVISIONAL, owner to confirm**, 2026-09-04 |
| 8 | A suspicious MCP tool: selectable with a warning, or shown only | 07 | selectable | Selectable with a warning — **PROVISIONAL, owner to confirm**, 2026-09-04 |
| 9 | Platform Firecrawl key as the default for every user, with a daily cap | 06 | yes, per-user override | Per-user override built and the daily cap built; the platform default stays OFF — **PROVISIONAL, owner to confirm**, 2026-09-04 |
| 10 | Skills attachable to library agents, or authored only | 08 | authored only | **Authored only**, 2026-09-04 |
| 11 | Licence header on the built-in skills; the repo has no `LICENSE` | 08, CLAUDE.md item 17 | settle the repo licence first | **Not answerable** — depends on the repository having no `LICENSE`, 2026-09-04 |
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
| 2026-09-04 | All 25 open owner decisions answered. Each answer is in the decision table above and in the `## Status` section of every plan that raised it — 00, 01, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14 and 15. Four are **provisional** and say so in both places: 3, 7, 8 and 9 are built up to the surface, left off, and wait for the owner. Decision 11 is **not answerable** while the repository has no `LICENSE`, so the built-in skills ship with no licence header and the dependency is recorded. Decision 2 was taken in `c9e8521`, which put the rules block at the head of `CLAUDE.md` with two clauses amended — parallel subagents authorized, and a money bound the draft did not carry. No code changed and no criterion moved. |
| 2026-09-03 | Plan 15 round 3 built on `gauntlet/plans`, `f2a3bb8` → `38d7635`. Twelve open rows built in eleven fixing commits (D-15-19 and D-15-20 share one - they are one defect the critic scored on two dimensions), preceded by two docs commits that fix no defect: `8231966` moves the ten misplaced round-2 rows into the ledger table, and `ca3d4f8` is the OWNER'S RULING closing D-15-8 … D-15-12 on the round-2 verifier's output, which is why 15's open count moved 17 → 12. Every built row is left `open` for the round-3 critic. That ruling also retires this plan's keep-the-earlier-wording convention: criteria 7 and 8 now strike the wrong figure inline, because the critic has scored a ticked criterion whose first sentence is false three times. The plan's per-module counts were regenerated by running each module alone - the verifier had found `test_isolation_matrix` at 32 where the table said 16. Python 1655 / PostgreSQL 18 5/5 / frontend 1195 in 65 files / E2E 37 in 5 files, all green. |
| 2026-09-03 | Plan 01 round 3 built on `gauntlet/plans`, `f2a3bb8` → `e22a32f`. One commit for the one open row: D-01-5 `e22a32f` - browser residue (the builder draft holding a `credential_id`, the run handoff, the run pointer) is keyed to the signed-in user's id, so the next person on the same browser reads none of it even when the previous one never signed out, and a sign-out sweeps what that identity wrote. The row is left `open` for the round-3 critic. Preceded by `20d51a4`, the OWNER'S RULING closing D-01-1 and D-01-2 on the round-2 verifier's output, which is why 01's open count moved 3 → 1; it is docs-only and separate so the log cannot read as a builder closing its own work. Plan 01's Status now names every fixing commit per id, **including round 2's four**, which it had never listed. Python 1642 / frontend 1180 / E2E 35, all green. |
| 2026-09-02 | Audit against `25634c0`; sixteen plans, three reference notes, design system, judge scaffolding written. Nothing committed. Decision 1 declined by the owner. |
| 2026-09-03 | Plan 15 round 2 built on `gauntlet/plans`: twelve fixing commits, one per ledger id (`95dfd70` … see the plan's Status), every row left open for the critic. Decision 24 is now built rather than assumed — `POST …/unpublish` exists and delete refuses while any version is registered. A second additive column, `builder_document_versions.source`, recorded against C10. |
| 2026-09-03 | 01 and 15 criteria complete and integrated on `gauntlet/plans` at `18a7944`: four builder branches merged (`bc6eab6`, `a44fa3d`, `9f6e63b`, `831ae6b`), three defects found only by the merged tree fixed (`348af34`, `e62235a`), the two-writer test run 5/5 against PostgreSQL 18.6, the 33-test E2E suite green with `CREDENTIALS_MASTER_KEY` set, ten builder constants moved into `config.py`, §6 regenerated at 41. Python 1548 / frontend 1131. **No judge round has run** — `In judge (round 1 pending)` means the criteria are ticked and the critic has not been invoked; the round file does not exist yet. Console mock-mode defect recorded as CLAUDE.md item 43. |
| 2026-09-02 | Plan set committed on `gauntlet/plans`. S1 starts on 01 and 15: the Integrator lands C10's six tables, `runs.mode`, the six config knobs and ten S1 rulings (`00-architecture.md`, Status) first, then four agents build 01 API, 01 UI, 15 API and 15 UI on their own branches. Decisions 23–26 are built on their recommendation and stay open. |
