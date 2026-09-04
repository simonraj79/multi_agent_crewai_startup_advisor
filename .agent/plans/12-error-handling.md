# 12 — Error handling

The Flowise-parity feature. Written 2026-09-02 against `25634c0`. Owns
contract **C8** (problem-code union). Consumes C1, C6, C7.

## Problem

Flowise's error surfaces, read from source (`docs/flowise-notes.md` §6),
are: a **server-side, manual, stale** pre-run checklist that validates the
last *saved* flow on a button press; a **persistent snackbar** whose
dismiss block is copy-pasted forty times; a red status badge with the error
in a tooltip; a trace entry; and **no retry, no backoff, no error branch, no
fallback** — one node throw aborts the run
(`packages/server/src/utils/buildAgentflow.ts:2207`).

This repository is ahead on the build side and behind on the run side.
Ahead: validation is client-triggered, live, and against the canvas — a
400 ms debounced `POST /validate` (`useBuilderValidation.ts:39`) whose
problems render all at once, errors first, document-level group first,
publish-422 rows merged with a `from publish` tag (`ProblemsPanel.vue:90-131`),
eleven codes anchored to the exact inspector control (`FIELD_CODES`,
`types/builder.ts:425-454`), and `F8` walks them. Behind: the run console
has node-level `error` state but the builder's run styling is dormant —
`builder.css:74-77` declares `[data-mode='run'] .is-error` and nothing
writes it (`BuilderCanvas.vue:509` hardcodes `design`) — there is no
inline error message on a node, no error edge, no retry, no per-step
input/output in the log, and no way to resume.

## Scope

The eight gauntlet bullets: pre-run validation, node-level error state,
error edges, retry config, execution log, partial-run resume, graceful
stream failure, and the six failure modes failing legibly and recoverably.
The problem-code union and its fixture. The synthetic failure triggers that
make every mode testable at zero cost.

## Out of scope

- The retry loop, error router and replay mechanics themselves — owned by 09 and 10; this plan owns their **surfaces** and their **tests**.
- Toast infrastructure. The console already has one status strip; this plan adds no notistack-style layer.

## Design

### D1 — Pre-run validation blocks the run, names the node, states the fix

Already true for the seventeen structural checks and the price
(`bounds.py`, `budget.py:197-248`). It becomes true for the new shapes by
growing the union (Interfaces) and by extending `FIELD_CODES` so each new
code lands on a control, not a strip. The four Flowise checks are all
subsumed: unconnected node → `orphan-node` (exists); missing required
param → the per-field codes; missing credential → `credential-missing`
(new, anchored to the credential picker); hanging edge → refused at parse.
Hierarchical without a manager → `crew-hierarchical-needs-manager`, refused
before CrewAI's own `crew.py:729` can raise mid-run. Cycles where cycles are
illegal → `back-edge-not-router` (exists). **Every error blocks publish and
launch; warnings do not** (`WARNING_CODES`, `types/builder.ts:396-398`).

### D2 — Node-level error state is on the canvas, in red, with the message inline

The run console's `WorkflowNode.vue` already has the five states and the
`error` class. It gains an inline message line (≤ 120 characters, full text
on focus) fed by the `node_error` frame's `message` (C6), and the builder's
dormant `[data-mode='run']` block is finally written by the test panel (13)
when a test run is inline. Not only in a log drawer: the node, the problems
dock (run-phase group, C8's `run-*` codes) and the log all say it.

### D3 — Error edges are a port, and the port is a warning until it is wired

An `on_error: route` node shows an `error` out-port drawn in the error
colour beside `out`. An unwired error port is `error-port-unconnected`, a
**warning** — the flow will still complete with `err__<node>` recorded —
so an author can flip the switch first and wire the fallback second. An
edge leaving `error` renders dashed-red (a third stroke class beside the
back-edge dash; `docs/flow-builder-spec.md` §5.4).

### D4 — Retry config is per node, tiered under Advanced, and priced

`retry {max_retries ∈ 0..RETRY_MAX (3), backoff_seconds ∈ 0..30,
fallback_model: registry id | null}` on agent and crew nodes (C1). The
budget meter shows the multiplier so the cost of resilience is visible
before it is spent (09 D4). `retry-over-max` refuses a value above the
bound with the bound in the sentence.

### D5 — The execution log is the frame log, with per-step inputs, outputs, timestamps and cost

`run_frames` already stores every frame with `ts`, `duration_ms`, `node_id`
and `details` (`persistence.py:185-200`) and the NDJSON export already
exists. The log surface (in the run console's rail and the test panel's
Run tab) groups frames by node, shows `input_preview` / `output_preview`
(C6), the per-node cost from `run_node_metrics`, and expands a
`node_error` into its `error_class`, attempt number and — for a
`crewai` exception — the bounded traceback tail the serializer already
captures for `ERROR` frames. Flowise has no per-node duration
(`docs/flowise-notes.md` §5); every row here has one.

### D6 — Partial-run resume is a button on the failed node

A terminal run with a `node_error` shows **Re-run from here** on that node;
it posts `resume_from {run_id, node_id}` (C7). Upstream nodes replay from
the failed run's state and draw dimmed with `replayed: true`. The button is
absent when the failed run belongs to someone else or its state is gone.

### D7 — Graceful stream failure

Already true by construction: `seq` is gapless, `/ws?after=` replays from
the cursor, the client dedupes (CLAUDE.md §9), and `GET /api/runs/{id}`
restores a run across a reload (`e2e/studio.spec.ts:433`). What this plan
adds is the **statement** on screen: a dropped socket shows *reconnecting —
N steps kept* rather than the header's connection badge silently changing
word, and a reload mid-run lands on the same node history. No completed
step is ever re-rendered as pending.

### D8 — The six failure modes, each with a trigger, a surface and a recovery

| Mode | Trigger (real / synthetic) | Canvas | Log / dock | Recovery | Test |
| --- | --- | --- | --- | --- | --- |
| Bad API key | 401 from OpenRouter or a tool / `SYNTHETIC_FAILURE=bad_key` | node red, *"credential rejected by openrouter"* | `node_error error_class=auth`, credential label, never the key | fix the credential in the picker → **Re-run from here** | `test_failure_modes.py::test_bad_api_key` |
| Tool timeout | `URLReadTool` / MCP call past `timeout` / `=tool_timeout` | node red with the tool name and seconds | `node_error error_class=tool_timeout`, `input_preview` shows the arguments | retry (D4) or error edge (D3) | `::test_tool_timeout` |
| Model refusal | `finish_reason = content_filter` or an empty completion / `=refusal` | node red, *"the model declined"* | `utterance` frame with the refusal text, `node_error error_class=refusal` | edit the prompt → re-run from here; **not** retried (10 D3) | `::test_model_refusal` |
| Malformed structured output | `output_schema` set and the response fails validation after `guardrail_max_retries` / `=malformed_output` | node red, *"output did not match the schema (2 retries)"* | `guardrail` frames per attempt, then `node_error error_class=schema` with the validation message | loosen the schema or raise retries → re-run | `::test_malformed_output` |
| Rate limit | 429 from OpenRouter / a tool / `=rate_limit` | node amber while retrying, red if exhausted, *"rate limited — retry 2 of 3 in 4 s"* | `retry` frames with `backoff_ms`, then success or `node_error error_class=rate_limit` | automatic (D4); fallback model on the last attempt | `::test_rate_limit` |
| Cyclic graph | a loop closed by a non-router | **never runs** — `back-edge-not-router` blocks publish and launch, highlights the closing edge, says *"close this loop with a router"* | problems dock | wire a router | `::test_cyclic_graph` + `test_bounds.py` |

Every synthetic mode is a value of one knob, `SYNTHETIC_FAILURE`, read by
the synthetic factories (`runtime.py:476-484`, `builder_runner.py:177-206`)
and applied to the node named by `SYNTHETIC_FAILURE_NODE` (default: the
first authored agent). Both knobs join the canonical list in
`docs/tech-stack.md` §6 the day they land — the scan is the contract.

### D9 — What Flowise does that we do not copy

The whole-flow paste sniffer, the stale server checklist, the forty
snackbar blocks, and cycle rejection that fails silently on drop
(`docs/flowise-notes.md` §1, §2, §6). A refused connection here already
commits nothing and flashes the reason (`e2e/builder.spec.ts:321`).

## Interfaces

### C8 — problem-code union (owned)

`PROBLEM_CODES` (`types/builder.ts:374-388`, 30 today, mirrored from three
Python files and byte-compared by `tests/builder/test_client_fixtures.py`)
grows by twenty-seven, ordered as an author meets them (the ten marked ◆
were requested by 02, 03, 04, 06, 07 and 08 while this file was being
written and are integrated here by the Integrator):

| code | severity | anchors to | emitted by |
| --- | --- | --- | --- |
| `attach-target-not-agent` | error | edge | `bounds.py` |
| `member-target-not-crew` ◆ | error | edge | `bounds.py` |
| `attachment-unattached` ◆ | **warning** | the attachment node | `bounds.py` |
| `attachments-over-max` ◆ | error | the agent or crew node (`MAX_ATTACHMENTS_PER_NODE`) | `bounds.py` |
| `attachment-nodes-over-max` ◆ | error | document (`MAX_ATTACHMENT_NODES`) | `bounds.py` |
| `crew-members-out-of-range` ◆ | error | the crew node (1..`MAX_CREW_MEMBERS`) | `bounds.py` |
| `member-agent-has-flow-edges` | error | the agent node | `bounds.py` |
| `crew-hierarchical-needs-manager` | error | crew `process` | `bounds.py` |
| `crew-task-order-mismatch` | error | crew `task_order` | `bounds.py` |
| `credential-missing` | error | the credential picker | `compiler.library_problems` |
| `credential-not-yours` | error | node | server-only, at publish/launch |
| `model-unknown` | error | `llm.model` | `compiler` against C3 |
| `model-over-ceiling` | error | `llm.model` | `compiler` against C3 |
| `model-lacks-capability` | error | `llm.model` | `compiler` — tools attached and `supports_tools` false, `output_schema` and `supports_json_mode` false |
| `mcp-server-unavailable` | error | the mcp node | server, from the stored discovery status (C12) |
| `mcp-tool-unknown` | error | mcp `tool_names` | `compiler` against C12 |
| `skill-unknown` | error | skill node | `compiler` against C11 |
| `skill-contains-scripts` ◆ | error | skill node, at import time | `builder/skills.py` (08: `scripts/` refused in v1) |
| `tool-param-invalid` ◆ | error | the tool node's offending param | `document.py` against the catalogue's `param_schema` (06) |
| `mcp-transport-disallowed` ◆ | error | the mcp node | server, `MCP_ALLOWED_COMMANDS` empty → stdio refused (07) |
| `mcp-no-tools-selected` ◆ | error | mcp `tool_names` | `bounds.py` |
| `mcp-tool-description-suspicious` ◆ | **warning** | mcp `tool_names` | server, the thirteen injection patterns (07) |
| `prompt-too-long` | error | the field | `document.py` (`BUILDER_MAX_PROMPT_CHARS`, C1) |
| `retry-over-max` | error | `retry.max_retries` | `document.py` |
| `error-port-unconnected` | **warning** | the node | `bounds.py` |
| `state-key-reserved` | error | graph settings → state | `compiler` |
| `state-schema-invalid` | error | graph settings → state | `document.py` |

Run-phase codes surface through `node_error.error_class` (C6), not the
union: `auth`, `tool_timeout`, `refusal`, `schema`, `rate_limit`,
`credential-not-yours`, `replay-missing-output`, `cancelled`, `ceiling`.

`WARNING_CODES` becomes six. `FIELD_CODES` gains the anchored rows.
`tests/builder/test_problem_code_declarations.py` still forbids an inline
literal the frontend's grep cannot see.

The problem payload gains one optional key, requested by 04: `field: string`
— the inspector control a problem anchors to when the code alone cannot say
(a `prompt-too-long` on `role` versus `backstory`). Absent, the client falls
back to `FIELD_CODES` as it does today (`types/builder.ts:425-454`); the
server emits it only for codes whose anchor varies.

### Consumed

C1 (`retry`, `on_error`), C6 (`node_error`, `retry`, previews), C7
(`resume_from`).

## Acceptance criteria

1. `tests/builder/test_client_fixtures.py` passes with `PROBLEM_CODES` at **57** on both sides (`python -c` over the three Python declarations and `grep -c` over `types/builder.ts` agree), and `test_problem_code_declarations.py` passes.
2. `tests/builder/test_bounds.py`: each new structural code fires on a one-node reproduction and on nothing else; `error-port-unconnected` is `severity="warning"`.
3. `tests/builder/test_failure_modes.py`: six tests, each setting `SYNTHETIC_FAILURE`, running a three-node authored fixture under `SYNTHETIC=1`, and asserting the exact frame sequence in D8's table, the run's terminal status, and — for the five that run — that `resume_from` the failed node completes.
4. `tests/builder/test_failure_modes.py::test_no_secret_in_any_failure`: with a sentinel credential value, every failure mode's frames, run row, NDJSON and ZIP export contain no sentinel.
5. Playwright `e2e/failure-modes.spec.ts` (`@launch`, synthetic): for each of the five running modes the failing node turns red **with its message visible without hover**, the problems dock lists it under a run-phase heading, the log row expands to inputs/outputs/attempt, and **Re-run from here** completes the run; for the cyclic mode the publish button is disabled and the closing edge is highlighted with the sentence.
6. Playwright `e2e/stream-failure.spec.ts`: kill the WebSocket mid-run (route abort), assert the strip reads *reconnecting — N steps kept*, reload, assert every completed node is still `completed` and the run finishes.
7. `frontend/tests/errorEdge.spec.ts`: an `on_error: route` node renders two out-ports, the error port's edge has the error stroke class, and toggling `on_error` back to `fail` removes the port and its edges in one undo step (the router-branch pattern, `RouterForm.vue:116-200`).
8. `frontend/tests/retryField.spec.ts`: the retry group sits under Advanced, `max_retries` above `RETRY_MAX` renders `retry-over-max` on the field, and the budget meter's multiplier updates on change.
9. `docs/tech-stack.md` §6's scan lists `SYNTHETIC_FAILURE` and `SYNTHETIC_FAILURE_NODE`.
10. Rubric 12: a critic can trigger all six modes from the UI using only `SYNTHETIC_FAILURE`, screenshot each at 1440×900 and 390×844, light and dark, and find each *legible* (the cause is on the node) and *recoverable* (a path forward is one click away).

## References

- `frontend/src/{components/builder/ProblemsPanel.vue:90-136, composables/useBuilderValidation.ts:25-39, 100, types/builder.ts:374-454, assets/styles/builder.css:74-77, components/builder/BuilderCanvas.vue:509, components/WorkflowNode.vue:69-75, components/builder/inspectors/RouterForm.vue:116-200}`
- `src/brief_crew/builder/{bounds.py:62-86, 611-631, budget.py:197-248}`, `src/brief_crew/service/{persistence.py:185-200, runner.py:65}`, `tests/builder/{test_client_fixtures.py, test_problem_code_declarations.py}`
- `docs/flowise-notes.md` §1, §2, §5, §6 — `packages/server/src/services/validation/index.ts:29-310`, `packages/ui/src/views/chatmessage/ValidationPopUp.jsx`, `packages/server/src/utils/buildAgentflow.ts:2163-2226`
- `crewai/crew.py:729`; `crewai/tools/tool_failure.py:57-69`; `docs/crewai-notes.md` §2, §8
- CLAUDE.md §9 (reconnect cursor), closed items 19, 20, 33; `docs/gotchas-and-insights.md` 22
- Gauntlet: "Error handling — Flowise parity or better", rubric 12, "Forbidden — TODO/FIXME in shipped paths"

## Status

**Planned · 2026-09-02.** No code.

Contract requests for 00: none. C8 is spelled out above.

Open decisions for the owner:

- `RETRY_MAX = 3` and `backoff ≤ 30 s` are judgements; the budget multiplier is what keeps them from being a money hole, and a critic may argue for higher.
- Whether a model refusal should be retryable with the fallback model (this plan: no — a refusal is a prompt problem, and re-asking a cheaper model is how a refusal becomes a hallucination).

### Owner decisions answered — 2026-09-04

**Decision 16 — no.** A refusal is a decision, and retrying it with a different
model is asking a second judge until one agrees.

### Built — 2026-09-04

Eight of ten met, one partial, one not reached. What shipped: two crew fields
the runtime was discarding in silence, five failure modes that now say which
kind of failure they were, an error port that takes its edges with it, an error
edge that is a class rather than a tint, a run-phase group in the problems dock,
and the two E2E files that are the only place three of these questions have an
answer.

| n | state | evidence |
| ---: | --- | --- |
| 1 | **met**, at **57** and not at the criterion's 57 | `test_client_fixtures.py` (14) and `test_problem_code_declarations.py` (4) green; `builderTypes.spec.ts` asserts 57 on both sides. Arithmetic below. |
| 2 | **met** | `test_bounds.py` 69 (was 57): `CrewTaskOrderTests` (5), `CrewManagerTests` (4), `CrewFieldPartitionTests` (3) — each code on a one-node reproduction, on nothing else, and `error-port-unconnected` asserted `severity="warning"` |
| 3 | **met** | `test_failure_modes.py::RunningModeTests` (6) and `RecoveryTests` (3): each mode sets `SYNTHETIC_FAILURE`, runs a two-step authored fixture under `SYNTHETIC=1`, asserts D8's `error_class`, the attempt, `will_retry`, a terminal `failed`, and that `resume_from` the failed node completes — plus a clean-run control |
| 4 | **met** | `SentinelTests::test_no_secret_in_any_failure`: five modes × frames, run row, status payload, NDJSON, ZIP, each preceded by the control that the run really held the key |
| 5 | **met, with three guarded assertions** | `e2e/failure-modes.spec.ts`, **7 passed**. The five running modes fail with the right class and re-run to completion; one drives the whole person's journey and watches the card turn red; the cyclic mode is refused in the dock with its edge tinted, publish disabled and a second refusal from the server |
| 6 | **met, with one guarded assertion** | `e2e/stream-failure.spec.ts`, **2 passed**: `page.route` aborts the ws handshake mid-run, the reload keeps every completed node, `seq` does not go backwards, `0 dropped`, and both gates are answered to completion — with a no-drop control |
| 7 | **met** | `frontend/tests/errorEdge.spec.ts`, **12 passed** |
| 8 | **met, and one clause is a contradiction** | `frontend/tests/retryField.spec.ts`, **11 passed**. `retry-over-max` cannot arise — see contradiction 2 |
| 9 | **met** | `docs/tech-stack.md` §6's wider scan lists both, with the regeneration command beside it; the list moved five → seven |
| 10 | **partial** | Every trigger exists and is one knob; the cause is on the node (`.workflow-node.is-error`, asserted in a browser). NOT DONE: the four-screenshot review at 1440×900 and 390×844 in both themes, and "a path forward one click away" is plan 11's **Re-run from here**, which does not exist in this worktree |

### Criterion 1's arithmetic, which is not the criterion's

The criterion says 57 and was written when the union was 30 and C8's table had
27 rows. It is 57 now by a different route, and the difference matters because
two of those 27 rows are deliberately not union members:

```text
  55   the union at 9b06e40   (scripts/emit_builder_fixtures.py::_declared_codes)
+  2   crew-task-order-mismatch, crew-hierarchical-needs-manager
----
  57
```

Of C8's 27 rows, **21 had already landed** with plans 03, 05, 06, 07, 08 and 09;
**2 are not union codes and never were** — `credential-not-yours` is a run-phase
`error_class` (`service/credentials.py:165`), and this plan's own Interfaces
section lists it in the run-phase set as well as in the table;
`skill-contains-scripts` is an import-time refusal declared in
`service/builder_api.py:731`, outside the seven files the mirror greps, and
three separate files say so deliberately. **2 are blocked** (contradiction 2).
That leaves 2, and four other plans contributed 4 codes the table never listed
(`tool-unknown`, `tool-credential-required`, `attachment-reference-missing`,
`crew-tier-not-honoured`). 30 + 21 + 4 + 2 = 57.

**`WARNING_CODES` is SEVEN, not the six this plan asks for.** Plan 09 took it to
7 with `crew-tier-not-honoured`, which this plan never knew about; neither new
code is a warning.

### Measured, 2026-09-04, in this worktree

```text
Python          2280 run · 0 failures · 9 skipped · 155.0 s   (baseline 2243/6)
Frontend unit   1505 passed in 77 files                        (baseline 1468 in 74)
vue-tsc -b --force   exit 0
npm run build        992 ms, green
E2E             84 passed in 5.2 min, every file, both projects,
                zero console errors tolerated                  (baseline 75)
                E2E_API_TARGET=127.0.0.1:8097, E2E_UI_PORT=5275
```

The six skips added since baseline are the three MCP-arm tests in the merged
`test_failure_modes.py` (plan 07's, absent here) counted twice by the two
discovery paths. **This plan spent $0.00**: every billable node is built by the
double `SYNTHETIC=1` installs, and the two places a real `Agent` is constructed
call no model.

**The E2E backend needs two extra knobs**, and both are in
`e2e/failure-modes.spec.ts`'s own docstring:

```text
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8097 \
BUILDER_ALLOW_GATELESS_GRAPHS=1 \
SYNTHETIC_FAILURE="fm_bad_key:bad_key:1,fm_tool_timeout:tool_timeout:1,\
fm_refusal:refusal:1,fm_malformed:malformed_output:1,fm_rate_limit:rate_limit:1"
```

Every entry names a node only that file authors, so the same backend serves
`builder.spec.ts`, `studio.spec.ts` and `templates.spec.ts` unchanged — measured:
84/84 on one backend. **Without the line those seven tests SKIP and say so**,
rather than failing on an environment gap that reads like a product defect,
which is `SYNTHETIC_BRANCH_DELAY_SECONDS`'s lesson applied before it costs
anybody an afternoon.

### Three contradictions, each stopped rather than improvised around

**1. C8's `crew-hierarchical-needs-manager` is `document.py`'s raise, not a
reported problem.** The table gives it to `bounds.py` anchored to crew
`process`; `AuthoredCrewConfig._validate_manager` already RAISES on a
hierarchical crew with neither manager set, with a comment saying it is a
cross-field rule about one object. Both are right, about different states. What
`document.py` cannot see is whether `manager_agent` names one of THIS crew's
members, because only the `member` edges answer that — and `runtime.py:730`
resolves it against the crew's own agents, falls through to `manager_llm`, and
with neither resolving `Crew.__init__` raises at `crew.py:729` MID-RUN. So the
code is `bounds.py`'s and it fires on the reachable half: pick a manager, then
delete that agent's member edge. The raise stays.

**2. `prompt-too-long` and `retry-over-max` are BLOCKED on a C1 change and are
NOT in the union.** C8 assigns both to `document.py`. At head both are
parse-time constraints — `Prompt` is
`StringConstraints(max_length=BUILDER_MAX_PROMPT_CHARS)` and `max_retries` is
`Field(le=BUILDER_MAX_NODE_RETRIES)` — which refuse the whole document rather
than reporting a fixable position, and `NumberRow` CLAMPS above the served
bound so the value cannot be typed either (asserted in `retryField.spec.ts`).
Reporting them means relaxing the schema so an over-limit document can be
STORED, which is C1 and the Integrator's, and it weakens `budget.py`'s premise
that a prompt is bounded before it is priced. `build_problem_codes` refuses to
emit a fixture for a code with no reachable instance, so this is not a choice
about tidiness. **Contract need: a ruling on whether C1 relaxes.** What is built
in the meantime is the half that carries the code the day it exists — the bound
is served rather than hardcoded, and a problem naming `retry.max_retries`
reaches that control through C8's `field` key.

**3. `WARNING_CODES` is seven where this plan says six.** Recorded above; no
action, the plan's figure predates plan 09.

### One defect found, and it is plan 10's

**`compile_replay_plan` cannot replay a GATE.** Resuming past one compiles to a
flow whose next node listens for a trigger nothing emits — measured verbatim:

```text
n3_safe listens for 'e2_approve', which no method emits and no method is
called. A trigger nothing produces is a node that never runs
```

That collides with the launch rule. A gate above the first billable node is the
only shape an anonymous caller may launch (`BUILDER_ALLOW_GATELESS_GRAPHS` off,
measured 403), so **every graph an anonymous author can launch is a graph
`resume_from` cannot resume past its gate.** The E2E works around it with the
flag and says so; the fix belongs to plan 10 D5. `tests/service/test_replay.py`
does not see it because its `abc()` fixture has no gate.

### Contract needs, and what the Integrator does at integration

- **C8 is at 57 and `WARNING_CODES` at 7.** Both new codes carry the optional
  `field` (`members`, `manager_agent`) and both also have `FIELD_CODES` entries
  as the fallback for a server that predates the key, which is `model-unknown`'s
  own pattern.
- **Un-guard three assertions once plan 11 merges**, each named in a Playwright
  annotation at its site: `e2e/failure-modes.spec.ts` — `node-error-message`
  (≤ 120 chars, on the failed card) and `rerun-from-here`;
  `e2e/stream-failure.spec.ts` — `stream-reconnecting` reading
  *reconnecting — N steps kept*.
- **Un-guard one more once plan 13 merges**: `e2e/failure-modes.spec.ts`'s
  run-phase group step. `ProblemsPanel` is not on the run console today; the
  group itself is proved by `frontend/tests/runProblems.spec.ts` (14).
- **`tests/builder/test_failure_modes.py` is now THREE plans' file.**
  `wd/ab-backend`'s two classes are byte-unchanged; the only edit to their half
  folds `MCP_CONNECTION_ERROR_CLASS` and `tests/service/mcp_fixture_server` into
  the `MCP_AVAILABLE` block their own file already used, because at module scope
  they made the whole file unimportable in a tree that had one branch and not
  another. **Delete that guard once the branches have met.**
- **Two files outside the ownership map were touched, and both were required by
  it:** `tests/service/test_error_routing.py` (two assertions pinned the base
  class's `"synthetic-failure"` placeholder that D8 replaces) and
  `scripts/emit_builder_fixtures.py` (every new code needs a scenario, and
  `test_client_fixtures.py` names that script as the way to regenerate).
  `frontend/src/assets/styles/builder.css` gained the error-edge dash — the
  brief grants the stroke class and that is where it lives.
- **`frontend/tests/runProblems.spec.ts` is a third new spec** beyond the two
  the map lists, because the brief asks for the run-phase group as a component
  with a unit test.

### Follow-ups this plan did not take

1. **The gate/replay collision above** — plan 10 D5, and it is the sharpest
   thing found this session.
2. **Criterion 10's screenshot review** is not done: four captures per mode at
   two viewports in two themes, and half of what it would judge is plan 11's.
   Worth running after plans 11 and 13 merge, not before.
3. **`benchmarks/perf/canvas.json` is rewritten by every full E2E run**, so a
   pass on one machine overwrites another's measurement. Restored here; it wants
   a `.gitignore` entry or a `--record` flag.
4. **`e2e/failure-modes.spec.ts` is the first file to meet
   `RUN_RATE_LIMIT_MAX_RUNS`.** It waits out the limiter on the server's own
   `Retry-After` rather than raising the limit, which would be turning off what
   makes an unauthenticated Launch survivable. If the suite grows more launching
   files, the limiter — not the runner — becomes the bottleneck.

