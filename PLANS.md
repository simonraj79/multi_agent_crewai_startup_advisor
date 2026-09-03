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
| 00 | [Architecture](.agent/plans/00-architecture.md) | S1 / S9 | — | 7 | 0 | — | 0 | In build | 2026-09-02 |
| 01 | [Auth and workspaces](.agent/plans/01-auth-and-workspaces.md) | S1 | 00 | 13 | 13 | 2 | 1 | In build (round 3) | 2026-09-03 |
| 02 | [Canvas](.agent/plans/02-canvas.md) | S2 | 00 | 14 | 0 | — | 0 | Planned | 2026-09-02 |
| 03 | [Node library](.agent/plans/03-node-library.md) | S2 | 00 | 11 | 0 | — | 0 | Planned | 2026-09-02 |
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
| 15 | [Persistence](.agent/plans/15-persistence.md) | S1 | 01 | 11 | 11 | 2 | 17 | In build (round 3) | 2026-09-03 |
| | **Total** | | | **179** | **24** | | **20** | | |

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
| 2 | Prepend the rules block (`.agent/RULES.draft.md`) to `CLAUDE.md` and smoke-test it | 00 D10 | yes, one paste | open |
| 3 | Code interpreter: BYO E2B key behind a flag, or cut | 06 D8, 01 | BYO E2B, not started until decided | open |
| 4 | Commission character art, or ship icon medallions through the gauntlet | 11 | medallions first | open |
| 5 | Roster: keep `deepseek/deepseek-r1` ($2.50 out) or swap for `deepseek-v3.2` | 05 | keep, show the output price | open |
| 6 | Measure `cost_in_max_endpoint` per model, or accept the 1.8 factor | 05 | measure once at build time | open |
| 7 | Allow any stdio MCP command in production | 07 | none — remote only | open |
| 8 | A suspicious MCP tool: selectable with a warning, or shown only | 07 | selectable | open |
| 9 | Platform Firecrawl key as the default for every user, with a daily cap | 06 | yes, per-user override | open |
| 10 | Skills attachable to library agents, or authored only | 08 | authored only | open |
| 11 | Licence header on the built-in skills; the repo has no `LICENSE` | 08, CLAUDE.md item 17 | settle the repo licence first | open |
| 12 | Library crew `tier`: refuse it, or honour it by rebuilding the crew's LLMs | 09 | refuse | open |
| 13 | `or_` inside a cycle depends on private `_discard_or_listener` | 09 | accept, as closed item 35 did | open |
| 14 | A BYO OpenRouter key exempts a run from the $10 ceiling | 10 | no | open |
| 15 | Stream-chunk coalescing at 250 ms, or a larger frame ring | 10 | 250 ms | open |
| 16 | Retry a model refusal with the fallback model | 12 | no | open |
| 17 | Test runs appear in run history, labelled `test` | 13 | yes | open |
| 18 | Attachment palette hotkeys `T`/`M`/`K` or `8`/`9`/`0` | 03 | letters | open |
| 19 | Expert switch global or per node kind | 04 | global | open |
| 20 | Re-baseline the validator's three screenshots, or gate the new styling to builder graphs | 11 | re-baseline once | open |
| 21 | Delete `minimal-gated-agent` and `fan-out-join` once the E2E is re-pointed | 14 | keep in a "more" row | open |
| 22 | The four paid template runs before or after the rubric gate | 14 | after | open |
| 23 | `VALIDATOR_RUN_RETENTION_DAYS` default | 15 | `0`, keep everything | open |
| 24 | Deleting a published document: unpublish automatically or refuse | 15 | refuse | open |
| 25 | PostgreSQL two-writer job on every push or only on `main` | 15 | `main` | open |
| 26 | Unowned published workflows stay launchable by anyone | 01 D1 | yes, for legacy rows | open |

## Log

| Date | What |
| --- | --- |
| 2026-09-02 | Audit against `25634c0`; sixteen plans, three reference notes, design system, judge scaffolding written. Nothing committed. Decision 1 declined by the owner. |
| 2026-09-03 | Plan 15 round 2 built on `gauntlet/plans`: twelve fixing commits, one per ledger id (`95dfd70` … see the plan's Status), every row left open for the critic. Decision 24 is now built rather than assumed — `POST …/unpublish` exists and delete refuses while any version is registered. A second additive column, `builder_document_versions.source`, recorded against C10. |
| 2026-09-03 | 01 and 15 criteria complete and integrated on `gauntlet/plans` at `18a7944`: four builder branches merged (`bc6eab6`, `a44fa3d`, `9f6e63b`, `831ae6b`), three defects found only by the merged tree fixed (`348af34`, `e62235a`), the two-writer test run 5/5 against PostgreSQL 18.6, the 33-test E2E suite green with `CREDENTIALS_MASTER_KEY` set, ten builder constants moved into `config.py`, §6 regenerated at 41. Python 1548 / frontend 1131. **No judge round has run** — `In judge (round 1 pending)` means the criteria are ticked and the critic has not been invoked; the round file does not exist yet. Console mock-mode defect recorded as CLAUDE.md item 43. |
| 2026-09-02 | Plan set committed on `gauntlet/plans`. S1 starts on 01 and 15: the Integrator lands C10's six tables, `runs.mode`, the six config knobs and ten S1 rulings (`00-architecture.md`, Status) first, then four agents build 01 API, 01 UI, 15 API and 15 UI on their own branches. Decisions 23–26 are built on their recommendation and stay open. |
