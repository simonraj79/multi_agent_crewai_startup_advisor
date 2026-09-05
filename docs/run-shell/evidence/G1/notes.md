# G1 — a flow the cast and the interpretation layer have never seen

Written by verification worker **RV2** on branch `run-shell/cast`, 2026-09-05.
RV2 authored the flow; it did not read `frontend/src/characters/`,
`frontend/src/trace/`, `AgentCharacter.vue` or `useRunChoreography.ts`, which is
the whole point of the criterion — the roles below were invented by somebody who
has not seen how a role string becomes a figure or a sentence.

## Provenance

| | |
| --- | --- |
| Freeze commit | **`683308950e823a896a8fa4a61739dde2709bd542`** (`6833089`) — *"feat(run-shell): the cast, the interpretation layer, the decided-by block - FREEZE for G1"*, Sat 5 Sep 2026 14:33:59 +0800 |
| Flow authored | 2026-09-05, **after** that commit. `invented-flow.json` did not exist at `6833089`: `git ls-tree -r --name-only 6833089 -- docs/run-shell/evidence/G1` prints nothing, and `git log --diff-filter=A -- docs/run-shell/evidence/G1/invented-flow.json` names no commit at all. At the freeze `docs/run-shell/evidence/G4/roles-sheet.png` carried its fourth section as a deliberate EMPTY placeholder reading *"The G1 flow does not exist yet"* |
| Verifier | **RV2**, branch `run-shell/cast`, working tree `D:\MultiAgentSystem` |
| Backend | `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8098 CREDENTIALS_MASTER_KEY=<placeholder> BUILDER_ALLOW_GATELESS_GRAPHS=1 .\.venv\Scripts\serve.exe` — no money spent |
| Console | Vite `e2e/vite.e2e.config.ts` on `E2E_UI_PORT=5274`, `E2E_API_TARGET=http://127.0.0.1:8098`, identity `e2e-user`, 1440×900, dark |

## The flow — "Clinic Rota Planner"

A domain with nothing to do with startup validation: staffing a week at a GP
practice. Five authored agent nodes, and **none of the five roles appears in any
existing template** (checked against `frontend/src/data/templates/*.ts` and
`frontend/src/data/builderTemplates.ts`, whose roles are Analyst, Billing
Specialist, Risk Specialist, Social Editor, Writer, Support Engineer, Account
Manager, Triage, Research Analyst, Drafter, News Researcher, Market Specialist,
Critic, Product Specialist) nor in the Idea Validator, the Brief Crew or the
character sheet's stock "Copy Desk".

| Node | Kind | Role invented | Tier |
| --- | --- | --- | --- |
| `brief` | input (`input_field: brief`) | — | — |
| `forecast` | agent | **Shift Demand Forecaster** | cheap |
| `confirm` | **gate** (in the middle, between forecast and draft) | — | — |
| `draft` | agent | **Roster Architect** | cheap |
| `guidance` | **tool** (`scrape_website` — the keyless one) attached to `audit` | — | — |
| `audit` | agent, `output_schema {breaches:int, notes:str}` | **Rest Rules Auditor** | cheap |
| `breaches` / `notes` | transform (`pick`) | — | — |
| `judge` | **router**, `joins: all` | — | — |
| `cover` | agent | **Locum Cover Planner** | cheap |
| `handover` | agent, markdown | **Handover Briefer** | escalation |
| `notice` | output (`markdown_body`) | — | — |

12 nodes, 13 edges, one revise loop closed through the router
(`judge --again--> draft`, tested `gt breaches 0`, exiting on `otherwise` so an
unparseable count fails *towards stopping*), one cycle.

**Validation: zero problems.** `POST /api/builder/validate` →
`{"valid": true, "problems": [], "identity_checked": true}`; budget
`static_cost_usd $2.4016`, floor `$1.4550`, 99 modelled calls, 5 billable, 1
escalation, 1 cycle, `over_ceiling: false` against the $10 ceiling.

## The run

| | |
| --- | --- |
| Workflow id | **`ug_42c65656`** (published, v1, graph version `58e65eb432e12adf`) |
| Run id | **`171fc2fc-5495-4032-9d43-7226ad13557b`** — the run in `graph.png` and `trace.png`, and the one `run.ndjson` holds |
| Session | driven from the console (handoff → Review → Launch → Approve) |
| Frames | **81**, `seq` 1→81 gapless, terminal `WORKFLOW_END`, status `completed` |
| Console errors | **0** (`pageerror` and `console.error` both empty; see `capture-notes.json`) |

Five earlier runs of the same graph exist on that backend from the same session
(`2e57c8c4…`, `20b8b7b5…`, `bc1dba01…`, `7c5ffc08…`, `ab48f295…`); all completed,
all identical in shape. `run.ndjson` is the last one, so log and captures are one
run.

### `details.agent_role` — exactly the five invented roles, and nothing else

```
Handover Briefer          5 frames
Locum Cover Planner       5 frames
Rest Rules Auditor        5 frames
Roster Architect          5 frames
Shift Demand Forecaster   5 frames
```

No other value of `details.agent_role` occurs anywhere in the log — no Scoper,
no Market Analyst, no validator vocabulary of any kind.

### "every frame on an agent node carries `agent_role`" — **NO, and the graph is why that is fine**

Measured, not assumed. Of the **40** frames whose `node_id` is one of the five
agent nodes, **25 carry `details.agent_role` and 15 do not**:

| frame kind | event type | carries `agent_role` |
| --- | --- | --- |
| `llm` | `MODEL_CALL` | **yes** (20) |
| `token` | `MODEL_CALL` | **yes** (5) |
| `node_state` | `NODE_START` / `NODE_END` | no |
| `edge_taken` | `EDGE_PROCESS` | no |

So per agent node it is: `EDGE_PROCESS`, `NODE_START` (no role), then three
stream chunks + one completion + one token frame (role), then `NODE_END` (no
role).

This is **not** a gap the cast falls into, and the DoD's own R2 amendment is the
reason: the **graph descriptor** carries the role for every agent node —
`GET /api/builder/workflows/ug_42c65656` returns
`agent_role: "Shift Demand Forecaster"`, `"Roster Architect"`,
`"Rest Rules Auditor"`, `"Locum Cover Planner"`, `"Handover Briefer"` on the five
agent nodes and `null` on the input, gate, transform, router, output and
quarantine nodes. The console therefore has the identity before the first frame
arrives, which is exactly what the amendment says it is for. Confirmed in the
browser: at the moment the gate opened — before any `llm` frame for `draft`,
`audit`, `cover` or `handover` had ever been sent — all five node cards already
carried their character (`capture-notes.json → nodeSeeds`).

Recording it here because "every frame carries it" is the sentence in the brief,
and it is false as written; the thing it was protecting is true by another route.

### Node ↔ trace tie-in

Same seeds on both sides, from `capture-notes.json`:

```
node cards : shift demand forecaster, roster architect, rest rules auditor,
             locum cover planner, handover briefer
trace rows : the same five, plus "confirm the demand" (the gate's own row,
             seeded on the gate node's label rather than on an agent role)
```

12 of the 15 trace rows carry a `[data-testid="trace-avatar"]` with a Pip inside
it. The three that do not are the workflow-level rows (`Run started` ×2,
`Run finished`), which have no `data-identity` — a system line, correctly
characterless.

### The five states are reached for every invented role

A `MutationObserver` on `data-state` recorded **53 transitions** across the run
(`capture-notes.json → transitions`). Every one of the five roles goes
`working → speaking → done`, and `shift demand forecaster` additionally goes
`blocked` while the gate below it is open:

```
working 9   speaking 15   done 24   blocked 5
```

## Captures

- **`graph.png`** — 1440×900, dark, mid-run with `Draft the rota` **working**
  (`midRunState: "working-after-gate"`). Characters on every agent node card, the
  phase lane at 3/10 with the Roster Architect's figure on it, and the trace rail
  down the left with per-role Pips.
- **`graph-at-gate.png`** — the same run paused at `Confirm the demand`: the
  forecaster **blocked**, the other four **idle**, all five drawn. Kept because it
  is the state in which the descriptor-supplied identity is proved (no `llm`
  frame has been sent for four of the five nodes yet).
- **`trace.png`** — the `.chat-rail` at completion: the "WHAT THE CREW SAID"
  block naming all five roles with their avatars, then the trace entries, ending
  on `Run finished`.
- **`capture-notes.json`** — the machine-readable backing for everything above.

> **How the mid-run still was obtained, because it matters for reproducing it.**
> The synthetic *builder* runner has **no per-node delay** —
> `SYNTHETIC_BRANCH_DELAY_SECONDS` is read only by `runner.py::_BRANCH_TOOLS`,
> which is the validator's three research branches — so all 81 frames arrive in
> one burst and the whole post-gate half completes in under a second. Two
> attempts to catch a `working` pose failed outright (plain, and again under
> `Emulation.setCPUThrottlingRate: 20`); the third succeeded by throttling the
> **socket** (`Network.emulateNetworkConditions`, 3000 B/s, 200 ms latency),
> which spreads the burst without touching a line of product code. Nothing about
> the cast was changed to get this picture. If a future verifier needs a mid-run
> still of a builder graph, that is the lever — or give the synthetic builder
> crew a delay knob of its own.

## Two defects found by authoring this flow

**1. A tool attachment makes the run canvas warn on every render, because the
descriptor emits a dangling edge.** `builder/descriptor.py` deliberately drops
attachment nodes from `nodes` (its comment says so at length: "ATTACHMENT nodes
are not steps and never appear in a descriptor") but builds `edges` from
`document.edges` **unfiltered**. My `guidance --attach--> audit` edge therefore
ships in the descriptor with a source that is not in the node list, and Vue Flow
answers, six times per render:

```
[Vue Flow]: Edge source or target is missing
Edge: e13   Source: guidance   Target: audit
```

It is a `console.warn`, not an error, so the zero-console-errors rule does not
catch it and my capture spec passed with `problems: []`. It is not a run-shell
defect and it is not in scope for this branch — it predates the freeze — but it
is reachable by any author who drops a tool on an agent and then runs the graph,
which is the ordinary case. The one-line shape of a fix is to filter `edges` to
`edge.target_port == "in"` in `descriptor.py`, the same predicate the same
function already applies when it builds `incoming`.

**2. `POST /api/runs/{id}/gates/{id}` takes `outcome`, and every reader of this
repo's own prose will send `decision`.** `CLAUDE.md`, `PLANS.md` and
`validator_flow.py` all describe the gate reply as `decision=approve` /
`decision=revise`, and the gate payload's own `summary` string — rendered to the
operator — says *"Reply with JSON: decision=approve, or decision=revise plus
feedback."* The model is `GateReplyRequest{outcome, fields}` with
`extra="forbid"`, so that sentence produces:

```
422 {"detail":"outcome: Field required; decision: Extra inputs are not
     permitted; feedback: Extra inputs are not permitted"}
```

The browser path is unaffected (the console sends the right key), so no suite
sees it; it costs an API caller who follows the on-screen instruction one
debugging round. Either the summary string should say `outcome`, or the model
should accept `decision` as an alias.

## G4, fourth section — the sheet re-rendered with these roles

`docs/run-shell/evidence/G4/g1-roles.json` carries four flows: the three the
generator already shipped with (Idea Validator, Brief Crew, Copy Desk), verbatim
and in their original order, plus **Clinic Rota Planner** as the fourth with the
note *"authored after freeze 6833089"*. All four are listed because
`scripts/character-sheet.mjs` REPLACES its `DEFAULT_FLOWS` with the file's
`flows` array wholesale — a file naming only my flow would have produced a
one-section sheet, not a fourth section — and because sheets 1 and 2 index into
`FLOWS[0]` and `FLOWS[2]`, which must keep meaning what they meant.

Re-rendered from `frontend/` with:

```
node scripts/character-sheet.mjs --roles ../docs/run-shell/evidence/G4/g1-roles.json
```

The fourth section is present in all four blocks of `roles-sheet.png` — A (dark,
96px), B (dark, 32px raster), C (light, 96px), D (light, 32px raster) — and it
has replaced the deliberate EMPTY placeholder that stood there at the freeze.

> The same command also rewrites `T2/characters-32px.*` and `T2/states-32px.*`,
> which are **W2's** evidence for T2.3. Adding a fourth flow adds a fourth card
> to the characters sheet, so those two files were backed up before the run and
> **restored afterwards**; `git status` shows only `G4/roles-sheet.{html,png}`
> modified. If the orchestrator would rather the T2 sheet also show the invented
> cast, re-run the command and keep the T2 output — it is the same generator and
> the same seeds.

### Do any two look alike at 32 px?

The generator prints each figure's five hash-selected parts, so this can be
answered by fingerprint as well as by eye:

```
Shift Demand Forecaster   bean / square / smile / antenna / c9   (lilac)
Roster Architect          bell / oval   / smile / ring    / c2   (pale mint)
Rest Rules Auditor        bell / lens   / oh    / antenna / c7   (teal)
Locum Cover Planner       bean / round  / oh    / curl    / c1   (cyan)
Handover Briefer          bean / square / oh    / curl    / c6   (pink)
```

**All five are distinguishable at a true 32 px**, on both themes. Two things are
worth flagging honestly:

1. **Within my flow, the closest pair is Locum Cover Planner and Handover
   Briefer** — same body, same mouth, same crest, differing only in eyes (round
   vs square) and colour. At 6× magnification the eyes separate them; at a true
   32 px it is the colour doing the work, cyan against pink, which is a wide gap.
   Told apart: yes, easily.
2. **The closest pair on the WHOLE sheet is cross-flow and is not mine alone:
   Roster Architect and Copy Desk's Localisation Lead share four of five parts
   including the colour** — `bell/oval/smile/ring/c2` against
   `bell/square/smile/ring/c2`. Only the eye shape differs, and at a true 32 px
   they read as the same pale-mint bell with a halo. They never appear in the
   same run, so it costs nothing operationally, but if the palette index is meant
   to be a disambiguator this is the case that shows it is not sufficient on its
   own. Worth a look by W2 rather than by me.

Nothing on the sheet resembles a character I recognise from anywhere else; they
read as one family of small hooded figures, which is what the system claims.


## Reproducing

```powershell
# 1. the free backend
$env:SYNTHETIC="1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS="5"; $env:PORT="8098"
$env:CREDENTIALS_MASTER_KEY="Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
$env:BUILDER_ALLOW_GATELESS_GRAPHS="1"
.\.venv\Scripts\serve.exe

# 2. validate / create / publish  (body is {"document": <invented-flow.json>})
curl -X POST http://127.0.0.1:8098/api/builder/validate   -H "Content-Type: application/json" -H "X-Synthetic-User: e2e-user" -d @body.json
curl -X POST http://127.0.0.1:8098/api/builder/workflows   -H "Content-Type: application/json" -H "X-Synthetic-User: e2e-user" -d @body.json
curl -X POST http://127.0.0.1:8098/api/builder/workflows/<id>/publish -H "Content-Type: application/json" -H "X-Synthetic-User: e2e-user" -d "{}"

# 3. launch, answer the gate with {"outcome":"approve","fields":{}}, then
curl "http://127.0.0.1:8098/api/runs/<run>/logs?format=ndjson" -H "X-Synthetic-User: e2e-user"
```

The console is reached by writing `sessionStorage["u:e2e-user:builder-run-handoff"]`
to `{"workflowId":"<id>","inputField":"brief","name":"Clinic Rota Planner"}` and
opening `#/` — the same record `PublishDialog`'s "Run it" writes.

---

## Re-captured at `16f3be5`

**`16f3be5c8d97bcc159c70f4435081930f6939f82`** — *"fix(run-shell): round two — the
frame budget, the last contrast rows, the compact trace row, and the specs that
pinned the rowers"*. The trace rows were restyled and the node card changed after
the first pass, so `graph.png`, `graph-at-gate.png` and `trace.png` were a
generation stale. Re-taken 2026-09-05 by RV2 with the **same method** — the same
:8098 `SYNTHETIC=1` backend, my own Vite on `E2E_UI_PORT=5274` /
`E2E_API_TARGET=http://127.0.0.1:8098` (8099 and 5273 left to RV3), the same CDP
socket throttle for the mid-run still, the same 1440×900 dark viewport — and the
three files plus `capture-notes.json` and `run.ndjson` overwritten.

The graph itself is byte-identical: `invented-flow.json` was re-posted unchanged
and re-validated **`{"valid": true, "problems": []}`**, same $2.4016 static price.
The backend was restarted, so it is a **new workflow id**; the published-graph
rehydration sweep found nothing because the previous process's store did not
survive it.

| | first pass | re-capture at `16f3be5` |
| --- | --- | --- |
| Workflow id | `ug_42c65656` (graph `58e65eb432e12adf`) | **`ug_b0126f9b`** (graph `1c0d417e22a0c992`) |
| Run id | `171fc2fc-5495-4032-9d43-7226ad13557b` | **`7e807a84-f9d2-4edc-a9e1-8411c702eda1`** |
| Frames | 81, gapless, completed | **81, `seq` 1→81 gapless, completed** |
| `midRunState` | `working-after-gate` | `working-after-gate` |
| Node cards drawn | 12 | 12 |
| Trace rows | 15 | 15 |
| Console errors | 0 | **0** |

`details.agent_role` is unchanged and still takes exactly five values — Shift
Demand Forecaster, Roster Architect, Rest Rules Auditor, Locum Cover Planner,
Handover Briefer, 5 frames each — and the 25-of-40 split (`llm`/`token` carry it,
`node_state`/`edge_taken` do not) is identical.

### Node ↔ trace seed check, repeated — and it is now an EXACT match

```
node cards : handover briefer, locum cover planner, rest rules auditor,
             roster architect, shift demand forecaster
trace rows : the same five, and nothing else
difference : none in either direction
```

Better than the first pass, which had `confirm the demand` as a trace-only seed.
The restyle **replaced the gate row's Pip with the amber person marker**, so the
gate no longer borrows a character it is not: 10 of the 15 rows carry a
`trace-avatar`, and the five that do not are the three run-level rows (now
labelled **"Run"**) and the two gate rows (person marker). Every character in the
trace is now an agent, which is the honest reading.

### State transitions, re-done

`44` transitions (was 53), `working 5 · speaking 15 · done 19 · blocked 5`. All
five invented roles still reach **`working`** and **`speaking`** and end **`done`**;
`shift demand forecaster` and the gate node both reach **`blocked`** while the gate
is open. The drop from 53 is the same restyle: the gate's trace row no longer
holds a figure that transitions with it.

### One new defect, and it is a generalisation defect

**The gate's read-only block is hard-coded with Idea Validator vocabulary, and it
renders that way on a clinic rota.** `graph-at-gate.png` shows the operator gate
for `Confirm the demand` carrying the heading **"COMPUTED BY THE VALIDATOR"** over
*"Recomputed by the server from the scores and the evidence behind them"*.
`frontend/src/components/GateCard.vue:264` and `:267` are literal strings. This
graph has no validator, no scores and no evidence — it has a demand table — so the
one panel that explains why a field cannot be edited is explaining it in the
vocabulary of a different product. It is W1's file (T1 owns `GateCard.vue` copy),
not the interpretation layer's, so G2's grep does not cover it; G1 is exactly the
instrument that finds it. Suggested wording is something derived rather than
named — "Computed by the run" / "Recomputed by the server from what produced it".

The gate message on the same capture also carries the first pass's defect 2 in
the operator's face: *"Reply with JSON: decision=approve, or decision=revise plus
feedback"*, where the route's model is `GateReplyRequest{outcome, fields}` with
`extra="forbid"`. Unchanged at this HEAD.

Everything else in this document was re-checked against the new run and still
holds as written.

