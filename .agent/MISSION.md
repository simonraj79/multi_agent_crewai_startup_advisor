# MISSION.md — the gauntlet build

**Read this first, and read it whole.** It is written for somebody who has
never seen the conversation that started this, and who may be opening it cold
after a compaction. Everything a build session needs to know that is *not*
discoverable from the code is here. Everything that *is* discoverable from the
code is deliberately not here, because this file is about to become the most
copied document in a repository that has published a wrong count six times by
copying one document into another.

Written 2026-09-04 by the Integrator, against `gauntlet/plans` = `f19a2c6`.

> **If this file and a prompt disagree, this file wins.**
> If this file and the *code* disagree, the code wins and this file is stale —
> fix it in the same commit as whatever you were doing.

---

## 1. What is being built, and what winning means

A **visual CrewAI agent builder**: a canvas where a signed-in person composes
agents, tools, MCP servers and skills into a graph, which the server compiles
into a real `crewai.flow/v1` definition — real `Agent`, `Task`, `Crew`, `Flow` —
and runs through the same registry, gates, frames and console as the two
hand-written flows this repository already ships.

It is **not** a diagram tool and it is **not** a wrapper. If a node cannot map
to a real CrewAI primitive, the node design is wrong; fix the design, never fake
the runtime.

**Winning is defined adversarially, not by self-assessment.** A hostile critic
with a fresh context scores the result against two shipped competitors —
Flowise Agentflow v2 for everything you build *with*, ChatDev 2.0 for everything
you watch *run* — across sixteen rubric dimensions, and the feature is finished
when the critic can no longer land a hit. The method is
[`benchmarks/README.md`](../benchmarks/README.md) and it is not optional
reading before a judge round.

**Audience note, and it changes no criteria.** The owner's purpose for this
build is educational — it is a teaching artefact for CrewAI. That is background
for judgement calls, not a licence to add scope. The 179 acceptance criteria
stand exactly as written (owner's ruling, 2026-09-04).

## 2. The gate a plan passes to be `Built`

Copied from `benchmarks/README.md` because a build session needs it without a
second hop, and it is short enough that restating it cannot drift:

```text
every applicable dimension >= 8
AND no open row for this plan in benchmarks/DEFECTS.md
AND at least three judge rounds have run
AND every numbered criterion ticked in the plan's own Status table
```

Two distinctions that cost round 2 an entire extra round. Keep them apart:

- **A ledger row closes when its own defect is absent** — the verifier's output
  shows it gone, the critic did not land it again, and the fixing commit is
  named in "closed by". That is the *only* test for closing a row.
- **A dimension scoring below the reference is an open defect in its own
  right**, and it does gate. But it does **not**, by itself, hold some *other*
  row open. Round 2 conflated these and held seven rows that had genuinely been
  fixed.

"Close enough" is a failure state. A first-round pass means the critic was too
soft: replace it and restart the round count.

## 3. Where the work happens — and which tree is not yours

| | |
| --- | --- |
| **Build here** | `D:\MultiAgentSystem-wt\integration`, branch `gauntlet/plans` |
| **Not yours** | `D:\MultiAgentSystem` — a separate worktree on `main`. Leave it alone. |
| Other worktrees | `D:\MultiAgentSystem-wt\s1-01-api`, `s1-01-ui`, `s1-15-api`, `s1-15-ui` — spent Stage 1 branches, already integrated. Read-only history. |

The main tree was cleaned on 2026-09-04: an abandoned uncommitted frontend
session from 2026-09-02 is parked on `wip/frontend-gate-card-visits`, and stale
untracked copies of six paths that are *tracked* on this branch were deleted.
Both trees are clean. **Do not recreate that state** — an untracked copy of a
tracked file in the main tree makes git refuse the final merge, and it refuses
at the end, after everything is built.

Nothing is pushed and nothing goes near `main` until plan P5. Ask before
pushing.

## 4. The plans, the order, and who gates whom

Sixteen files under [`.agent/plans/`](plans/), `00` the contracts index,
**179 numbered acceptance criteria** total.
[`PLANS.md`](../PLANS.md) at the repository root is the one place a plan's
*status* is recorded. The plan file itself is the one place its *criteria* are
ticked. Neither restates the other.

```
S1  00 architecture · 01 auth+workspaces · 15 persistence        [BUILT, judging]
     |
     +-- Wave A  03 node library  (KEYSTONE, first and alone)
     |           02 canvas · 05 model registry   (parallel, after 03)
     |
     +-- Wave B  04 inspector · 06 tools · 07 MCP · 08 skills    (four parallel)
     |
     +-- Wave C  09 compiler  ->  10 runtime                     (strictly ordered)
     |
     +-- Wave D  11 visualizer · 12 errors · 13 flow testing · 14 templates
     |
     +-- P5      integration, whole-product gauntlet, PR to main
```

**Plan 03 is the keystone and runs alone.** Plans 02, 04, 05, 06, 07 and 08 all
read the ten-kind node vocabulary it defines. Two agents editing that schema at
once produce a merge nobody can review.

**Contracts C1–C12 are indexed in `00-architecture.md` and the Integrator owns
every change to one.** A subagent that needs a contract changed reports the
need; it does not make the change.

## 5. The rulings — decisions already taken, do not relitigate

All 26 owner decisions are answered in [`PLANS.md`](../PLANS.md)'s decision
table **and** in the plan that raised each one. That table is authoritative;
this is the summary a builder needs at the moment of building.

Four are marked **provisional — owner to confirm**, because they spend the
owner's money or open a surface. For each: build up to it, leave it off, and
**ask**.

| # | Ruling | |
| ---: | --- | --- |
| 3 | Code interpreter: BYO E2B key behind a flag, default off | **provisional** |
| 7 | Production MCP: remote servers only; stdio behind a flag that is off | **provisional** |
| 8 | A suspicious MCP tool stays selectable with a warning, not hidden | **provisional** |
| 9 | Platform Firecrawl key as everyone's default, with a daily cap and per-user override | **provisional** |

The rest are settled. The ones whose *reason* a builder needs:

- **12** — a library crew's `tier` is **refused**, not honoured. Honouring it
  means rebuilding the crew's LLMs from outside the crew, and the crew library
  is the one place in the builder where the code is ours and not the author's.
- **13** — depending on the private `_discard_or_listener` for `or_` inside a
  cycle is **accepted**, exactly as CLAUDE.md's closed item 35 accepted it. Pin
  it with a guard test whose failure message names the router variant as the
  replacement. The alternative costs two pass-through nodes carrying no agent,
  no model and no decision, plus lockstep edits to seven files.
- **14** — a caller's own OpenRouter key does **not** exempt a run from the $10
  ceiling. The ceiling bounds a topology somebody else drew, not whose card is
  charged.
- **16** — a model refusal is **not** retried with the fallback model. A refusal
  is a decision; retrying it with a different model is asking a second judge
  until one agrees.
- **18** — palette hotkeys are **letters** `T` / `M` / `K`. Digits `1`–`7`
  already select node kinds, and a second digit row on one surface is a
  collision an author discovers by pressing one.
- **19** — the expert switch is **global**, not per node kind. Per-kind means an
  author learns the same control four times and it remembers a different answer
  each time.
- **24** — deleting a *published* document is **refused**, not silently
  unpublished.
- **11** is **not answerable**: it asks for a licence header on the built-in
  skills, and this repository has no `LICENSE`. Record the dependency; do not
  invent an answer.

## 6. The model ruling

```
CHEAP_MODEL      openrouter/google/gemini-3.5-flash-lite:nitro   $0.30 / $2.50
ESCALATION_MODEL openrouter/google/gemini-3.8-flash              $0.75 / $3.75
```

The escalation tier moved 3.7-flash → **3.8-flash** on 2026-09-04 (`f19a2c6`).
Measured against the live OpenRouter catalogue that day, not copied: identical
price, higher on all three Artificial Analysis indices (58.7 / 76.3 / 50.0
against 56.0 / 76.1 / 45.1). A same-price strictly-better swap needs no
argument.

- **The cheap tier deliberately did not move.** 3.8-flash would cost it 2.5×
  on prompt, and three tool-using research analysts run there.
- **`:batch` is half price and unusable here.** Batch is a queued lane; a run
  with streaming frames and a human waiting at a gate cannot be queued.
- **`gemini-3.8-flash` is the builder's default authored model** and the model
  the E2E and test paths use.
- `PRICES` moves in the same commit as the constant — the platform rule. Here
  the value did not need to move, and that was *checked*, not assumed. The
  failure this rule exists to prevent already happened once: a run priced at
  `$0.00` over 128,069 real tokens.
- **A price written in prose is stale. Look it up** with
  `mcp__openrouter__get-model`. That MCP server's OAuth credential lasts seven
  days and carries no refresh token; if its tools are missing, the token
  expired — call `mcp__openrouter__authenticate`, which swaps the real tools in
  mid-session with no restart.

## 6a. The price ceiling — owner's ruling, 2026-09-04

**No model above $1.00 per 1M input tokens is reachable anywhere in the
product, and the ceiling is measured against the MAX ENDPOINT price, not the
headline.** That is the owner's ruling and it is not open.

It has teeth, because a slug's headline is one of several endpoint prices.
`google/gemini-3.8-flash` has six endpoints and its two `priority` ones bill
**$1.35 / $6.75** — over the ceiling. Measured 2026-09-04.

**Why the escalation preset is nevertheless admissible**, and why that is a
fact rather than a reinterpretation: OpenRouter only considers `flex` and
`priority` endpoints *when the request asks for them*, by a `:nitro` / `:floor`
variant, a `service_tier` parameter, or a tier slug named in `provider.order` /
`provider.only`. `ESCALATION_MODEL` is a plain slug sent with
`provider: {"sort": "throughput"}`, and **`sort` is not one of those three** —
which is what the one paid run observed, both escalation calls landing on
`google-vertex/global` at $0.75. `CHEAP_MODEL` *does* carry `:nitro`, so
priority endpoints are admissible for it; flash-lite's priority tier is $0.54,
under the ceiling.

**But that is a property of today's configuration, not a guarantee**, and a
ceiling that holds because of what nobody happens to have set is not a ceiling.
So it is now **enforced at the API**: every escalation request carries
`provider.max_price`, which filters endpoints *before* routing. An over-ceiling
endpoint cannot be selected regardless of variant, sort, tier, or a catalogue
change nobody noticed. `config.py::openrouter_price_ceiling_params`.

Three things a later wave must not get wrong:

- **`max_price` and `sort` are one `provider` object.** JSON has no merge, so a
  second caller writing its own `provider` key silently overwrites the first
  and nothing raises — the call simply becomes eligible for $1.35 again.
  `openrouter_escalation_params` assembles it once;
  `test_crews.py::test_the_price_ceiling_survives_sharing_a_provider_block_with_sort`
  pins it at every effort including `None`.
- **There is deliberately no completion ceiling.** The rule is stated in one
  dimension and inventing a second bound would be inventing a number. It costs
  nothing, measured: every roster endpoint over $3.75 completion is a priority
  endpoint whose prompt price the input bound already excludes.
- **The registry still records `cost_in_max_endpoint`** and the plan 05 ceiling
  test still reads it. A model whose *cheapest* endpoint is over the ceiling is
  unusable under this policy and is refused up front — `openai/o4-mini` has
  exactly one endpoint, at $1.10, and is refused at both doors.

## 7. The money rule

**Balance: $27.55** — `total_credits` 120, `total_usage` 92.446, measured
2026-09-04 with `mcp__openrouter__get-credits`. (An earlier note recorded
$7.55; the owner has since topped up. Re-measure rather than quote this.)

Owner's ruling, 2026-09-04:

- **Authorized without asking:** live `gemini-3.8-flash` runs for E2E and smoke
  testing, **up to $5.00 cumulative across the whole programme**. Record what
  you spend in your report so the next session can subtract it.
- **Stop and ask, with a costed estimate first:** plan 14's four paid template
  runs, the paid acceptance run (CLAUDE.md remaining-work item 1), and the live
  fan-out benchmark (item 2).
- **Never press Launch against `127.0.0.1:8000`.** That is the *paid* backend
  and the default Vite proxy points at it. The free one is on **8099**.

## 8. The commands — copy these exactly

### The free backend

The editable install resolves `brief_crew` to the **main tree's** source unless
told otherwise, so every Python command and the backend itself carry
`PYTHONPATH`. Get this wrong and you inspect the wrong code and are not told.

```powershell
$env:SYNTHETIC = "1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS = "5"; $env:PORT = "8099"
$env:CREDENTIALS_MASTER_KEY = "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
$env:PYTHONPATH = "D:\MultiAgentSystem-wt\integration\src"
D:\MultiAgentSystem\.venv\Scripts\serve.exe
```

`CREDENTIALS_MASTER_KEY` is the placeholder `tests/__init__.py` sets; without it
the credential path answers **503**, which reads like a broken feature.
`SYNTHETIC_BRANCH_DELAY_SECONDS=5` is not optional either — the visual specs
screenshot a branch *while it is running*, and the synthetic runner finishes one
instantly, so without it the suite fails with `No branch stayed in flight`,
which reads exactly like a CSS regression.

Playwright starts its own second Vite server on **5273** which proxies to 8099.

**Stopping it:** `Stop-Process -Name serve -Force`. Then confirm from the serve
log *and* a refused `/healthz`. `pkill` reports success on Windows while doing
nothing, and a stale process keeps answering from old code — this has cost two
sessions, once presenting as a mysterious 401.

### The suites

```powershell
# Python  (PYTHONPATH, always)
$env:PYTHONPATH = "D:\MultiAgentSystem-wt\integration\src"
D:\MultiAgentSystem\.venv\Scripts\python.exe -m unittest discover -s tests -t .

# Frontend
Push-Location frontend; npm test; npx vue-tsc -b --force; npm run build; Pop-Location

# E2E  (needs the backend above already running)
Push-Location frontend; npx playwright test; Pop-Location
```

PostgreSQL 18 runs in container `pg18-test` on **5433**, password `test`:
`TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres`.

> **Docker Desktop must be running, and on 2026-09-04 it was not** — the daemon
> answered `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the
> file specified`. Nothing before plan 15's two-writer test needs it, so this is
> a precondition to check rather than a blocker to clear now. It is the *only*
> way to exercise the five compare-and-set paths in this codebase that have
> never met a concurrent writer; SQLite's single-writer model cannot stress any
> of them.

## 9. The traps — each of these has already cost somebody a session

0. **The `CLAUDE.md` auto-loaded into your context is the MAIN TREE's copy, and
   it is a generation stale.** Measured 2026-09-04: a fresh subagent was asked
   what its context held and answered that it had loaded `CLAUDE.md` and
   `MEMORY.md`, and that no "Rules for the gauntlet build" section was present —
   because that section is committed to
   `D:\MultiAgentSystem-wt\integration\CLAUDE.md` on `gauntlet/plans`, and
   auto-loading follows the *session's* working directory, which is
   `D:\MultiAgentSystem` on `main`. Two different files with one name.

   The stale copy predates plans 01 and 15, the credential vault, and ~31,000
   lines. **The authoritative copy is this worktree's**, and *this* file governs
   over both. There is no clean file-edit fix: putting the block in the main
   tree means either an uncommitted change there — which recreates the merge
   blocker cleared on 2026-09-04 — or a commit to `main`, which is out of
   scope. So **every subagent brief must say this in its own words.** That is
   not belt and braces; it is the only mechanism there is.

   This was found by the rules block's own ORRERY smoke test, which exists for
   exactly this and is the only check in the repository that instructions
   *arrive* rather than merely exist.

1. **`PYTHONPATH`.** Without it you are testing the main tree's source. Silent.
2. **`OSError: [Errno 22]` from `test_gates`, `test_builder_runner` or
   `test_credential_resolution`** means `%TEMP%\crewai` must be deleted and the
   run repeated. It accumulates leaked NTFS streams — 2,520 of them once.
3. **`pkill` does nothing on Windows** and reports success. See above.
4. **Git Bash mangles `git show rev:path`.** MSYS rewrites anything that looks
   like a Unix path list, so `gauntlet/plans:.agent/x` becomes
   `gauntlet\plans;.agent\x` and fails. Export `MSYS2_ARG_CONV_EXCL='*'`. Worse
   than the error: a redirected `git show` writes an **empty** file, so a
   comparison silently reports "differs" for everything.
5. **PowerShell mangles `npx playwright test -g "some words"`** into an invalid
   regex. Use the `file.spec.ts:<line>` form.
6. **The builder canvas pans on middle-drag, right-drag or Space+left only.** A
   Playwright pan must hold Space.
7. **`.NET` APIs ignore PowerShell's `Set-Location`.** Pass absolute paths.
8. **A comment inside a Vue tag breaks the view.**
9. **Fake timers hang a component mount.**
10. **`create_all()` never alters a table that already shipped.** A new column
    on an existing table is silently absent on the deployed PostgreSQL database
    and fails at the first INSERT. Use `persistence._add_missing_columns()`.
11. **`unittest discover` walks past a test directory with no `__init__.py`**
    in silence and reports a green `OK` over tests it never ran. Add the
    `__init__.py` in the same commit as the directory.
12. **`core.autocrlf` is `true` here.** A byte comparison against a committed
    fixture reports the platform, not the drift. Normalise line endings first.
13. **A jsdom mount asserts structure and never asks how wide anything ended
    up.** Two layout defects reached a 988-green suite this way. Layout
    questions have an answer only in a real browser.
14. **`git checkout <rev> -- path` wipes uncommitted edits** to that path.
15. **Rebasing after committing** re-hashes commits whose ids are named inside
    committed files.

## 10. The baseline — what is measured, and what is inherited

**Say which is which, every time.** This repository has published a wrong count
six times, never twice for the same reason, and every one of them was a figure
copied from a neighbouring document rather than regenerated. The command is the
contract; the number never is.

Measured on **2026-09-04** at `f19a2c6` in this worktree:

<!-- BASELINE-START -->
| Suite | Result | How |
| --- | --- | --- |
| Python | **1655 run · 0 failures · 6 skipped · 65.6 s** | `unittest discover -s tests -t .` with `PYTHONPATH` set |
| Frontend unit | **1195 passed in 65 files** | `npm test` |
| Type check | **exit 0** | `npx vue-tsc -b --force` |
| Production build | **1981 modules · 646 ms** | `npm run build` |
| E2E | **37 passed in 1.7 min**, all 5 files, zero console errors tolerated | `npx playwright test` against `SYNTHETIC=1` on 8099 |
<!-- BASELINE-END -->

Every row above was **run in this worktree on 2026-09-04 at `f19a2c6`**, not
copied — the E2E included: 37 executed, not merely listed. **Nine of the 37 are
`@launch`** (`--grep-invert @launch` lists 28). Against `SYNTHETIC=1` on 8099
all 37 are free and this run cost nothing; point them at a paid origin with
`E2E_BASE_URL` and those nine spend money.

So the harness is known-good as of this baseline. A later wave that finds it
red broke it — that is the whole reason for measuring it before building
anything.

Inherited from plan 15's round-3 report and **not** re-measured there:
frontend 1195 in 65 files, E2E 37 in 5 files, PostgreSQL two-writer 5/5.
Treat a different number as either the main tree's source on your `PYTHONPATH`
or a real regression — and report the number *and* the tail either way.

## 11. Working method

- **Subagents are authorized and encouraged** (owner, 2026-09-04). A subagent
  sees none of the conversation that launched it, so every brief is
  self-contained: the worktree path, the `PYTHONPATH` rule, the backend recipe,
  the plan file, and what it may not touch.
- **The Integrator keeps** every contract change, every merge, every plan
  `Status` table, every ledger row, and the commits.
- **A build session does not open or close ledger rows.** That is a judge
  round's job.
- **A pre-existing bug outside a plan's surfaces is a follow-up in the report,
  not a fix.**
- **Where a criterion is ambiguous**, implement the reading its wording and the
  surrounding code most directly support, and state the assumption in the
  plan's `Status`.
- **Edit surgically rather than rewriting** when it will not change the result.
- **Before reporting, audit every claim against a tool result from that
  session.** Report only what you can point at. Say explicitly where something
  is not verified. A verdict reasoned to rather than measured must be labelled
  as such.

## 12. What cannot be closed here

Three things are money and one is a judgement the owner owes:

1. The paid live acceptance run (CLAUDE.md item 1).
2. Plan 14's four paid template runs (decision 22).
3. The live fan-out benchmark (CLAUDE.md item 2).
4. **The repository has no `LICENSE`**, which for a public repo means all rights
   reserved. Decision 11 depends on it.

Say so plainly in any report that claims the programme is finished.
