# The gauntlet plan set

Sixteen plan files for the visual CrewAI agent builder described in
`C:\Users\Simon\Downloads\gauntlet-crewai-visual-builder.md` (the gauntlet).
Written 2026-09-02 against `main` = `25634c0`. **Order is dependency order,
not priority order.** `00` and `01` gate everything.

| # | File | Gates on | Owner (Stage 1) |
| --- | --- | --- | --- |
| 00 | `00-architecture.md` — stack, boundaries, data flow, the contracts index C1–C12, supersession of `docs/flow-builder-spec.md` by number | — | S1 / S9 |
| 01 | `01-auth-and-workspaces.md` — workflow ownership, the credential vault (C4), the three isolation rules, synthetic identity | 00 | S1 |
| 02 | `02-canvas.md` — the Vue Flow surface, ports, edges, light theme, 60 fps at 50 nodes | 00 | S2 |
| 03 | `03-node-library.md` — ten kinds, two families, attachment ports, vocabulary v2 (C2), the v1→v2 upgrade | 00 | S2 |
| 04 | `04-inspector-and-params.md` — Essentials / Advanced / Expert, capability gating, credential picker | 03, 05 | S3 |
| 05 | `05-model-registry.md` — the ten-model roster under $1.00/M input (C3), `PRICES` derived, the ceiling test | 00 | S3 |
| 06 | `06-tool-registry.md` — the tool catalogue, the declarative custom HTTP tool, the code-interpreter decision | 01, 03 | S4 |
| 07 | `07-mcp-client.md` — per-user MCP servers (C12), discovery, native `Agent.mcps` | 01, 03 | S4 |
| 08 | `08-skills.md` — SKILL.md packs on disk (C11), progressive disclosure, built-in library | 01, 03 | S4 |
| 09 | `09-compiler.md` — authored nodes → `Agent`/`Task`/`Crew`, error routers, `or_` joins, replay plans, code preview (C5) | 03, 05, 06, 07, 08 | S5 |
| 10 | `10-runtime.md` — run modes (C7), new frames (C6), retry/fallback, `replay_output`, cost | 09 | S5 |
| 11 | `11-run-visualizer.md` — ChatDev motion on our art: handoff walk, idle recede, dialogue rail, launch, stage lane | 10 | S6 |
| 12 | `12-error-handling.md` — problem codes (C8), the six failure modes, node-level error state, execution log, resume | 10 | S7 |
| 13 | `13-flow-testing.md` — the docked test panel: run, node test, dry run, code, state | 10 | S7 |
| 14 | `14-templates.md` — sequential, hierarchical, reflection, router (+ idea validator), fixtures (C9) | 09 | S8 |
| 15 | `15-persistence.md` — tables (C10), export/import/duplicate/history, the two-writer PostgreSQL test | 01 | S1 |

## Stage 0 — RAMP

| | State |
| --- | --- |
| **R** rules | **Declined 2026-09-02**: `CLAUDE.md` stays; status is tracked in `PLANS.md` at the root. A rules block may still be prepended to `CLAUDE.md` — paste-ready text in `.agent/RULES.draft.md` |
| **A** augment | Done: `docs/crewai-notes.md`, `docs/flowise-notes.md`, `docs/chatdev-notes.md`, `docs/design.md`, `.agent/mcp.json` |
| **J** judge | Scaffolded: `benchmarks/README.md` (method, rubric, capture recipe, critic protocol), `benchmarks/DEFECTS.md` (empty ledger) |
| **M** map | This directory |
| **P** prove | Playwright MCP is live in this environment; `npx playwright test` against `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099` is the second rung (recipe in `CLAUDE.md`, "Verified Baseline") |

## The loop, per feature

```text
clear context → AGENTS.md (auto) + ONE plan file (manual)
→ build against its numbered acceptance criteria
→ verify item by item (Playwright → integration tests → CLI → screenshots)
→ capture 1440×900 and 390×844, light and dark, every state
→ a fresh critic scores against benchmarks/reference/ (order randomised, labels stripped)
→ all dimensions ≥ 8 and no open defect in benchmarks/DEFECTS.md, three rounds minimum
→ commit, set the plan's Status
```

Build-time surfaces compare against Flowise (`D:\Flowise-main\Flowise-main`);
run-time surfaces against ChatDev 2.0 (`D:\ChatDev-main`). Do not cross
them.

## Three rules that keep this set honest

1. **A contract lives in one file.** The index in `00` names the owner of C1–C12; a plan that needs a contract it does not own consumes it by number and never restates it.
2. **A number is measured or it says it is inherited.** Where a figure below was carried from an audit rather than re-run, the plan says so beside it.
3. **Where the gauntlet and the installed package disagree, the package wins.** `docs/crewai-notes.md` §11 is the list.
