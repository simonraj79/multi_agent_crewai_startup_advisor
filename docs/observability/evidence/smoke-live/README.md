# smoke-live — the app-side exporter against the live Langfuse project

Run **2026-09-05** by **V-PROOF-PREP**, an Opus 5 verifier who built none of
this code and edited nothing under `src/`, `tests/` or `scripts/`. Subject: does
the exporter in `src/brief_crew/observability/` actually write to the real
Langfuse project `cmto3mj7t06ykad0ipon3ksbw` at `https://us.cloud.langfuse.com`,
end to end, on a **no-cost synthetic** run.

This is **not** proof-run evidence for any DoD row. Every run here is synthetic:
no money was spent, there are no OpenRouter generation ids, no billed cost, no
failing agent, no raising tool and no human gate. It is the predecessor of
`evidence/proof/**` and its job is to find, before a paid run, everything that
would waste one.

Companion: `evidence/tooling-smoke/` ran the same tooling against a backend with
**no** exporter and correctly found no session. This directory is the same shape
**with** the exporter, and it finds one.

---

## 1. What was run

| | |
| --- | --- |
| Backend | `.venv\Scripts\serve.exe`, **bare**, `127.0.0.1:8097` |
| Environment | `SYNTHETIC=1  SYNTHETIC_BRANCH_DELAY_SECONDS=2  PORT=8097  HOST=127.0.0.1  VALIDATOR_ALLOW_AUTO_GATES=1  CREDENTIALS_MASTER_KEY=<the base64 placeholder `tests/__init__.py` uses; authenticates against nothing>` |
| Langfuse knobs | **none set** — every one is at its default. `LANGFUSE_EXPORT_ENABLED` therefore defaults to on because both keys are present in `.env`; `LANGFUSE_CAPTURE_CONTENT` is off; `LANGFUSE_RESOLVE_BILLED_COST` is on but inert on a synthetic run |
| Credentials | read by the process from `.env` via `import brief_crew`'s `load_dotenv(override=True)`. No key was passed on a command line, printed, or written to any file here |
| Workflow | `idea-validator`, `gates: "auto"`, one idea per run |
| Killed with | `taskkill /PID 15956 /T /F` on the PID `netstat -ano` gave for `:8097`. **Never** `pkill`, never `Stop-Process -Name serve`. Port confirmed free afterwards |

Three runs, all `completed`:

| # | app session | run id | Langfuse trace id | app usage | dir |
| --- | --- | --- | --- | --- | --- |
| 1 | `smoke-live-1` | `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7` | `4548c8846e5c404ca28abbf5a8ce8cf7` | 6 calls, 3840/449/4289 tok, $0.0022745 | `./` |
| 2 | `smoke-live-2` | `036ace4e-8b58-4a9b-9d46-0b78448684f9` | `036ace4e8b584a9b9d460b78448684f9` | 6 calls, 3840/437/4277 tok, $0.0022445 | `run-2/` |
| 3 | `smoke-live-3` | `9d356fcb-aadd-4d41-ab06-7ffcd50c78ea` | `9d356fcbaadd4d41ab067ffcd50c78ea` | 6 calls | `run-3/` |

Run 3 was added to **time** the Langfuse flush; it is otherwise identical.
Console URL shape: `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/<trace id>`
(the `htmlPath` the trace-detail endpoint returns).

`trace id == UUID(run_id).hex` for all three — the DoD §7 revision of §5.1,
verified in code above and reproducible with `uuid.UUID(run_id).hex`.

---

## 2. Files

| file | what it is |
| --- | --- |
| `serve.log` | the backend's stderr followed by its stdout, verbatim (`serve-exe-probe.err.log` + `serve-exe-probe.out.log`, both kept). Grepped for `sk-`, `pk-`, `fc-`, `ghp_`, `github_pat_`, `pcsk_`, `AIza`: **no hit, nothing deleted** |
| `request-1.json`, `create-1.json` (and `-2`) | the POST body and the 202 response |
| `app-run.json`, `frames.ndjson` | `GET /api/runs/{id}` and `…/logs?format=ndjson`. `frames.ndjson` is a copy of `app-frames.ndjson`, which is the name `pull_app_run.py` writes |
| `app-figures.json`, `app-figures.md` | the app's own per-agent/per-task/per-node figures, derived from the frames |
| `langfuse-session.json`, `langfuse-trace.json`, `langfuse-traces.json`, `langfuse-observations.json`, `langfuse-scores.json` | the public-API responses. `langfuse-trace.json` is the single trace object lifted out of the list, for the filename the brief asks for |
| `langfuse-figures.{json,md}`, `per-agent.md`, `per-task.md`, `durations.md`, `open-spans.txt`, `hierarchy.txt` | derived by `pull_langfuse_run.py` |
| `RECONCILIATION-smoke-live.md`, `durations-app-vs-langfuse.md` | `reconcile.py`, app vs Langfuse |
| `membership/` | `membership_check.py` over all three runs |
| `flush-latency.json` | the run-3 timing measurement |
| `secret-scan-BEFORE.txt` / `secret-scan-AFTER.txt` | `secret_scan.py` before and after the redaction in §6 |

**Tooling used, and it all worked.** `pull_app_run.py` exit 0, `pull_langfuse_run.py`
exit 0 (**not** the exit 3 the tooling smoke got — there is a session now),
`membership_check.py` exit 0, `reconcile.py` exit 0, `secret_scan.py` exit 0.
`pull_openrouter.py` was not run: a synthetic run carries no generation ids, and
`evidence/tooling-smoke/` already records that empty case.

---

## 3. The observation tree that actually arrived

Run 1, drawn from `langfuse-observations.json` by walking `parentObservationId`.
Names and types are verbatim. `hierarchy.txt` could **not** draw this — see
defect D2.

```text
TRACE 4548c8846e5c404ca28abbf5a8ce8cf7  name=idea-validator
      sessionId=4548c884-6e5c-404c-a28a-bbf5a8ce8cf7  userId=anonymous
      environment=synthetic  tags=[gates:auto, idea-validator, mode:run]
      output={"status":"completed","reason":null}
 |
 +- SPAN      "run"                              role=run     parent=6d5d6cc0b2b5c678  <- NOT PRESENT (D2)
     +- SPAN  "scope_idea"                       role=node
     |   +- SPAN   "scoping_task"                role=task
     |       +- AGENT "Startup validation scoper"          role=agent
     |           +- GENERATION "google/gemini-3.5-flash-lite:nitro"
     +- SPAN  "confirm_scope"                    role=node
     +- SPAN  "route_scope"                      role=node
     +- SPAN  "research_market"                  role=node
     |   +- SPAN   "market_task"                 role=task
     |       +- AGENT "Market evidence analyst"            role=agent
     |           +- TOOL       "research_market_landscape"   tool_status=ok
     |           +- GENERATION "google/gemini-3.5-flash-lite:nitro"
     +- SPAN  "research_sentiment"               role=node
     |   +- SPAN   "sentiment_task"              role=task
     |       +- AGENT "Community demand analyst"           role=agent
     |           +- TOOL       "analyze_community_sentiment" tool_status=ok
     |           +- GENERATION "google/gemini-3.5-flash-lite:nitro"
     +- SPAN  "research_feasibility"             role=node
     |   +- SPAN   "feasibility_task"            role=task
     |       +- AGENT "Technical feasibility analyst"      role=agent
     |           +- TOOL       "assess_technical_feasibility" tool_status=ok
     |           +- GENERATION "google/gemini-3.5-flash-lite:nitro"
     +- SPAN  "synthesize"                       role=node
     |   +- SPAN   "synthesis_task"              role=task
     |       +- AGENT "Startup validation synthesist"      role=agent
     |           +- GENERATION "google/gemini-3.5-flash-lite:nitro"
     +- SPAN  "review_verdict"                   role=node
     +- SPAN  "route_verdict"                    role=node
     +- SPAN  "write_report"                     role=node
     |   +- SPAN   "reporting_task"              role=task
     |       +- AGENT "Validation report writer"           role=agent
     |           +- GENERATION "google/gemini-3.5-flash-lite:nitro"
     +- SPAN  "persist"                          role=node
```

33 observations: `SPAN 18` (1 run + 11 node + 6 task), `AGENT 6`,
`GENERATION 6`, `TOOL 3`. Identical counts on all three runs.

**No `EVENT` observation exists in any of the three traces.** Nothing in these
runs produced one: `gates: "auto"` opens no gate, and no frame kind was unknown
to the exporter. Contract §2's gate-EVENT and unknown-frame-EVENT branches are
therefore **untested here**, not absent.

---

## 4. Contract check — `TRACE-CONTRACT.md`

| § | What it asks | Verdict | The evidence field |
| --- | --- | --- | --- |
| **1** ids and grouping | trace id deterministic from run id | **MET** | `langfuse-trace.json.id` = `4548c8846e5c404ca28abbf5a8ce8cf7` = `UUID(run_id).hex`; same on all 3 |
| 1 | `sessionId` = app run id verbatim | **MET** | `langfuse-session.json.id` and `langfuse-trace.json.sessionId` both `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7` |
| 1 | `name` = workflow id | **MET** | `langfuse-trace.json.name` = `idea-validator` |
| 1 | `userId` = owner else `anonymous` | **MET** | `langfuse-trace.json.userId` = `anonymous` (backend has no `AUTH_BASE_URL`) |
| 1 | `environment` = `synthetic` on a doubles run | **MET** | `langfuse-trace.json.environment` = `synthetic`, and on every observation |
| 1 | `tags` = `[flow_kind, "gates:"+mode]` | **PARTIAL** | `langfuse-trace.json.tags` = `["gates:auto","idea-validator","mode:run"]` — a **superset**: both required tags are there plus an undocumented `mode:run`. Harmless for filtering; the contract table does not list it |
| 1 | `metadata` carries run_id, workflow_id, app_session_id, gates, synthetic, user_id, graph_version | **MET** | all seven present in `langfuse-trace.json.metadata` (`graph_version` = `9c6ca8a6fefbfffd`). Two undocumented extras: `computed_result` and `run_metrics` — see defect D4 |
| 1 | `input` = keys + chars + fingerprint under default policy | **MET** | `langfuse-trace.json.input` = `{"input_keys":["idea","no_gates"],"input_chars":69,"input_fingerprint":"3857c57e…"}`. **The idea text is absent.** Verified by grep: the literal idea string occurs 20x in `frames.ndjson` and in `app-run.json` / `request-1.json` (all app-side), and in **none** of the 15 `langfuse-*.json` files across the three runs |
| 1 | `output` = terminal status + reason | **MET** | `{"status":"completed","reason":null}` |
| 1 | start/end from **frame** timestamps, never the exporter clock | **PARTIAL** | Agent/task/node/tool spans track frame timestamps to ±3 ms. The six GENERATIONs do **not**: `endTime` runs 0–12 ms past the after-frame's `ts` (e.g. `write_report` after-frame `…25.740`, `endTime` `…25.752`). Within B4's 1 s tolerance; contrary to the sentence. DoD §7 already amended *start* for this reason and did not amend *end* |
| **2** hierarchy | run SPAN → node SPAN → task SPAN → agent → GENERATION / TOOL | **MET** | the tree in §3. Every level present and correctly nested on all 6 agent executions and all 3 tool calls |
| 2 | agent level is a SPAN | **PARTIAL** | it is Langfuse's native **`AGENT`** type, not `SPAN`, carrying `metadata.observation_role = "agent"`. A deviation from the letter that reads better in the console; the tooling groups on `observation_role`/`agent_role`, so nothing downstream cares |
| 2 | TOOL type, or a SPAN with `observation_role="tool"` | **MET** | real `TOOL` observations; the fallback was not needed |
| 2 | unknown frame → EVENT, never dropped | **NOT TESTED** | zero EVENT observations; no unknown frame kind occurred. C3's committed test is the instrument for this, not this run |
| 2 | gate EVENT | **NOT TESTED** | `gates: "auto"`; no gate opened |
| **3** metadata on **every** observation | run_id, node_id, agent_role, task_name, frame_seq, frame_kind, event_type | **PARTIAL** | 22 of 33 carry all seven. The 10 node SPANs entered by an edge omit the **keys** `agent_role` and `task_name` (contract says present-or-null). The `run` SPAN omits six of the seven, carrying only `run_id`. `run_id` itself is on **100%** of observations in all three runs — `membership/membership-check.txt`: `observations with no run_id: 0` |
| 3 | `frame_seq` = the **first** frame's sequence number | **PARTIAL** | true for GENERATION (`write_report` → seq 84, the `before` frame) and for AGENT/task. **False for TOOL**: `research_market_landscape` carries `frame_seq: 23` / `frame_ts: …21.728`, which is the `after` frame; its `before` frame is seq 22 at `…19.727`, and the span's own `startTime` is `…19.729`. So on a TOOL, `frame_ts` contradicts `startTime` by the tool's whole duration |
| **4** GENERATION | `model` | **MET** | `model` = `google/gemini-3.5-flash-lite:nitro` on all 6, provider prefix as the app sees it |
| 4 | `usageDetails` input/output/total | **MET** | e.g. `{"input":640,"output":68,"total":708}`; the six sum to 3840/449/4289, equal to the app snapshot |
| 4 | `costDetails.total` from the app estimate | **MET** | six values summing to `$0.002275`, equal to `app-run.json.usage.cost_usd` `0.0022745` |
| 4 | `metadata.cost_source` | **MET** | `app-estimate` on all six |
| 4 | `metadata.response_id` | **ABSENT, EXPECTED** | key absent on all six. `service/runner.py` writes `response_id: None` on the synthetic after-frame. **On a paid run all-ids-absent is a defect** |
| 4 | `metadata.openrouter_cost_usd` | **ABSENT, EXPECTED** | set only by the billed-cost resolution, which has nothing to resolve here (`lookup_ok=0 lookup_failed=0`) |
| 4 | `metadata.prompt_fingerprint` = sha256 over the **rendered messages** | **NOT MET** | the field is present and distinct per call, but `metadata.prompt_fingerprint_basis` says `node\|agent_role\|task_name\|model` — it is a hash of the **identity**, not of the prompt. Two different prompts from one agent/task/model hash identically. This is the field B5 exists for. See defect D3 |
| 4 | `metadata.message_count` — "always" | **NOT MET** | key absent on all 6 generations, all 3 runs |
| 4 | `metadata.prompt_chars` — "always" | **NOT MET** | key absent on all 6 generations, all 3 runs |
| 4 | `metadata.completion_chars` — "always" | **MET** | `[275, 309, 318, 316, 313, 273]` |
| 4 | `input`/`output` ABSENT under default policy | **MET** | both `null` on all six |
| 4 | `level`/`statusMessage` | **PARTIAL** | `DEFAULT` / `null` on all six, which is right for six successful calls. The `ERROR` half is untested — no call failed |
| 4 | `metadata.finish_reason` | **MET** | `stop` on all six |
| 4 | `metadata.attempt` 1-based | **MET** | `1` on all six; nothing retried, so 2+ is untested |
| **5** TOOL | name, `input` policy, `tool_status`, `result_count`, `query` | **MET** | name verbatim; `input` = `{"arg_keys":["query"],"arg_chars":57,"arg_fingerprint":…}`; `tool_status:"ok"`, `result_count:3`, `query` as `{chars, sha256}`, `from_cache:false`, `notes` as `{chars, sha256}`. `output` reads `{"output_chars":0,…}` because **the app's tool after-frame carries no result payload** (verified in `frames.ndjson` seq 23) — faithful to the frame, not a loss by the exporter |
| 5 | `level=ERROR` + `statusMessage` on a tool error | **NOT TESTED** | no tool raised |
| **6** terminal | trace `output.status` | **MET** | `completed` on all three |
| 6 | run span ended at the terminal frame ts | **MET** | run span `…19.727 → …25.747`; the app's `WORKFLOW_END` frame (seq 96) is at `…25.747`. Exact |
| 6 | **no observation left without an end time** | **MET** | `open-spans.txt`: `observations examined: 33`, **0** with `endTime` null. Computed independently here: `sum(1 for o in obs if not o["endTime"])` = **0**, all three runs |
| 6 | failed / cancelled / budget-stopped rows | **NOT TESTED** | every run completed |
| **7** scores | `run_succeeded` on the trace | **MET** | `langfuse-scores.json`: NUMERIC `1`, `traceId` set, `observationId` null |
| 7 | `run_status` categorical on the trace | **MET** | CATEGORICAL, `stringValue: "completed"` |
| 7 | `task_attempts` on the task SPAN | **MET** | 6 scores, one per task SPAN, each value `1`, each `observationId` a task span id |
| 7 | `guardrail_passed` on the task SPAN | **NOT TESTED** | **zero** such scores — and the app emitted **zero** guardrail frames on this path (`frames.ndjson` event types: `MODEL_CALL 42, AGENT_CALL 12, NODE_START 11, NODE_END 11, EDGE_PROCESS 10, TOOL_CALL 6, METRICS_UPDATED 2, WORKFLOW_START 1, VERDICT_COMPUTED 1, WORKFLOW_END 1` — no guardrail event exists). Nothing was dropped; there was nothing to score |
| **8** content policy | no message content, no user text, no key-shaped string | **MET on the exporter's own output** | the idea string is in `frames.ndjson` and in no `langfuse-*.json`; every free-text value arrives as `{chars, sha256}`; all six generations have `input`/`output` null. **But see defect D1** — Langfuse's own API *response* echoes a credential back |
| **10** self-report | one summary line per run with the counters | **MET** | three lines in `serve.log`, quoted in §5 |

---

## 5. The exporter's self-report, and the flush

All three lines from `serve.log`, verbatim:

```text
langfuse-exporter run=4548c884-6e5c-404c-a28a-bbf5a8ce8cf7 frames_enqueued=97 frames_dropped=0 observations_sent=41 http_errors=0 lookup_ok=0 lookup_failed=0 enqueue_p50_us=2 enqueue_p95_us=7
langfuse-exporter run=036ace4e-8b58-4a9b-9d46-0b78448684f9 frames_enqueued=96 frames_dropped=0 observations_sent=41 http_errors=0 lookup_ok=0 lookup_failed=0 enqueue_p50_us=0 enqueue_p95_us=3
langfuse-exporter run=9d356fcb-aadd-4d41-ab06-7ffcd50c78ea frames_enqueued=96 frames_dropped=0 observations_sent=41 http_errors=0 lookup_ok=0 lookup_failed=0 enqueue_p50_us=0 enqueue_p95_us=2
```

- `frames_enqueued` **97 / 96 / 96** equals the frame count `pull_app_run.py`
  read from the app for each run. Nothing was skipped at the door.
- `frames_dropped=0`, `http_errors=0`.
- `enqueue_p95_us` ≤ **7 µs** — the on-thread cost the exporter adds under the
  capture lock.
- `observations_sent=41` is **33 observations + 8 scores**. The counter is
  incremented for `open_run`, `open_child`, `event` **and `score`**
  (`langfuse_exporter.py:635-637`), so it is not an observation count despite
  the name. 41 − 8 = 33 = the observation count. Cosmetic; recorded so nobody
  reconciles 41 against 33 and reports a loss.

**Wall clock to visibility** (`flush-latency.json`, run 3, measured by polling
the public API from the moment of launch):

| | seconds |
| --- | ---: |
| launch → run terminal | 6.20 |
| launch → first observation visible in Langfuse | 20.32 |
| **run terminal → first observation visible** | **14.11** |
| launch → observation count stable at 33 | 23.82 |
| run terminal → count stable | 17.62 |

The trace appeared **all at once**: the first successful poll already returned
all 33 observations, so 14.11 s is the ingestion latency, not a fill rate. The
stable-at figure is imprecise by up to ~5 s because five consecutive polls came
back **HTTP 429** from the Langfuse public API (it rate-limits at roughly one
request per second).

**Consequence for the paid proof run: a 15-second wait is not enough.** Poll
until the count is non-zero and stops moving, at ≥ 2 s between requests.

---

## 6. The redaction that had to be made, and it is a defect not a courtesy

`secret-scan-BEFORE.txt`, `secret_scan.py` over this directory as the tooling
first wrote it:

```text
FAIL - actual credential values found: 36
VERDICT: FAIL
  …langfuse-observations.json:42  the value of LANGFUSE_PUBLIC_KEY appears verbatim
  …  (× 33, one per observation, plus langfuse-session.json, langfuse-traces.json,
      langfuse-figures.json)
```

**Cause, measured:** Langfuse's public API returns each observation with a
`metadata.scope.attributes.public_key` field containing the ingesting SDK's
public key — i.e. the exact value of `LANGFUSE_PUBLIC_KEY` from `.env`. It is
Langfuse's own OpenTelemetry scope attribute, not something the exporter puts
there. `pull_langfuse_run.py` saves the response verbatim, as it should, and
`langfuse-figures.json` copies metadata forward. **108 occurrences across the
three runs.**

I replaced that exact string, and nothing else, with
`<LANGFUSE_PUBLIC_KEY redacted by V-PROOF-PREP>` in the 12 files listed by the
run above. Every file still parses as JSON. `secret-scan-AFTER.txt`:
`FAIL - actual credential values found: 0`, `VERDICT: PASS`. The 36 remaining
`WARN`s are the scan's own `pk-lf-<36 chars>` renderings inside
`secret-scan-BEFORE.txt`, all `token-shaped: 0`.

`serve.log` was grepped for all seven prefixes and contains none. **No line was
deleted from it.**

---

## 7. Defects, ranked by how much each blocks a paid proof run

### D1 — BLOCKER for F3. Every Langfuse pull writes a credential value to disk.

36 occurrences per run, in `langfuse-observations.json`,
`langfuse-session.json`, `langfuse-traces.json` and `langfuse-figures.json`;
field `metadata.scope.attributes.public_key`. Row **F3** is "does no committed
artifact contain a credential value", checked by exactly the script that says
FAIL here. Every proof-run directory will fail it the moment
`pull_langfuse_run.py` runs, and the paid runs are the ones nobody wants to
repeat. Owner: whoever owns `scripts/observability/pull_langfuse_run.py`
(strip or mask that one field on the way to disk). Evidence:
`secret-scan-BEFORE.txt`.

### D2 — HIGH. The trace has no root: the `run` span's parent does not exist.

`langfuse-observations.json`: the `run` SPAN carries
`parentObservationId: "6d5d6cc0b2b5c678"`, and no observation with that id is
returned by `/api/public/observations?traceId=` **or** by
`/api/public/traces/{id}` (33 observations both ways, and **zero** with a null
parent). So the fetched tree has no root. Measured harm:
`pull_langfuse_run.py` wrote a `hierarchy.txt` containing only

```text
ORPHANED (parentObservationId not among the fetched observations):
  - SPAN run parent=6d5d6cc0b2b5c678
```

and no tree at all — the artifact B1/B2 cite for "each generation sits under its
agent" is empty. Whether the Langfuse **console** still renders the tree is
**NOT DETERMINED**: no browser was used. Verify that before the paid run, since
B1/B2/B3/D2 all want console screenshots of the tree.

### D3 — HIGH for B5. `prompt_fingerprint` does not fingerprint the prompt.

Contract §4: "sha256 over the rendered messages (role + content, in order)".
Actual: `metadata.prompt_fingerprint_basis = "node|agent_role|task_name|model"`.
The exporter is honest about it — the basis field is why this was findable — but
a hash of the identity cannot answer B5's question ("which prompt produced a bad
output"), because it is constant across every call an agent makes on a task, and
across prompt revisions. Whether the rendered messages are reachable from the
frames on a **paid** run is **NOT DETERMINED**; on this synthetic run the
`llm` before-frame carries no message list. Related and smaller:
`metadata.message_count` and `metadata.prompt_chars`, both specified "always",
are **absent** on all 18 generations across the three runs.

### D4 — MEDIUM. The run span reports HALF the run's cost and calls.

`langfuse-trace.json.metadata.run_metrics` and the `run` span's own metadata
carry:

```json
{"reason": "interval", "usage": {"call_count": 3, "cost_usd": 0.0011385, "total_tokens": 2145}}
```

The app emitted **two** `METRICS_UPDATED` frames: seq **51** (`reason:
"interval"`, 3 calls, $0.0011385) and seq **97** (`reason: "run_completed"`,
6 calls, $0.0022745). The exporter kept the **interval** one. Ordering fact:
the final metrics frame is seq 97 and the terminal `WORKFLOW_END` is seq **96**,
so the final figure arrives *after* the frame that ends the run span, and the
exporter's own docstring records that the SDK "cannot revise one after it ends".
**Cause beyond that ordering: NOT DETERMINED.** The trace is not *wrong* about
money — summing the six GENERATIONs gives the right $0.002275, and
`RECONCILIATION-smoke-live.md` shows app and Langfuse agreeing on all five
totals — but a reader who opens the run span and reads `run_metrics` sees half.

### D5 — MEDIUM. No exporter startup line under a bare `serve.exe`.

The brief said "it logs one line at startup about its state". It does not, under
the launcher the brief names. `build_exporter` logs
`"langfuse export is on: …"` at **INFO**; nothing in `src/brief_crew/` calls
`logging.basicConfig`, so that record reaches a root logger with no handler and
is served by `logging.lastResort`, which is fixed at WARNING. `serve.log` has
uvicorn's four lines and then nothing until the first per-run summary. The
per-run summary *does* appear because it uses a dedicated logger at WARNING —
that fix was applied to the summary and not to the startup line.
`GET /healthz` and `GET /readyz` say nothing about the exporter either: both
bodies were read during this run and their only keys are `status`,
`dependencies.executor`, `dependencies.storage` and `gates` — there is no
observability entry under `dependencies`. So on the paid run there is **no way to
confirm the exporter is on before spending money**, short of launching a run and
looking in Langfuse. `scripts/observability/measure_overhead.py` already carries
the workaround (`python -c "logging.basicConfig(level=INFO); serve()"`) and the
proof run should use it.

### D6 — MEDIUM, and it is in the tooling, not the exporter. B4's grouped
duration rows sum nested spans.

`RECONCILIATION-smoke-live.md` §4 reports **OVER 1 s** for
`Technical feasibility analyst` (app 2.006 s vs Langfuse 6.014 s),
`research_feasibility` (2.006 vs 8.019) and four more. Arithmetic:
6.014 = 2.005 (AGENT) + 2.005 (task SPAN) + 2.004 (TOOL), and
8.019 adds the node span. `reconcile.py` sums every Langfuse span carrying a
given `agent_role`/`node_id`, and the exporter's tree nests three or four of
them per agent execution, so the total is double- and triple-counted. The 1:1
**per-tool** table in the same file agrees to 1–2 ms, and the run span agrees
with the app's first→last frame span to 2 ms. Left uncorrected, B4 will read as
a failing exporter. Owner: `scripts/observability/`.

### D7 — LOW. `frame_ts` / `frame_seq` mean different things on different
observation types.

On a GENERATION and on an AGENT they are the **first** frame's, as §3 says. On a
TOOL they are the **last** frame's: `research_market_landscape` has
`frame_seq: 23`, `frame_ts: …21.728` (the `after` frame; the `before` is seq 22
at `…19.727`) while its own `startTime` is `…19.729`. A reader who trusts
`frame_ts` as the start is out by the tool's entire duration.

### D8 — LOW. Undocumented trace fields and a misnamed counter.

`tags` carries a third entry `mode:run` that §1's table does not list.
`trace.metadata` carries `computed_result` (verdict, composite score, the five
validator dimension names) and `run_metrics`, neither in §1's list — free-text
inside them *is* fingerprinted (`confidence_band` arrives as `{chars, sha256}`),
so this is a documentation gap, not a content-policy one. `observations_sent`
counts scores (§5 above).

---

## 8. What looked like a hang, a slow flush, or an error

- **No hang.** Runs 1/2/3 reached `completed` in 2.0 / 6.0 / 6.2 s wall clock.
  The backend answered `/healthz` 200 within ~1 s of launch and served every
  request. `taskkill /PID … /T /F` freed the port immediately.
- **No exporter error anywhere.** `http_errors=0`, `frames_dropped=0`,
  `lookup_failed=0` on all three runs. `serve.log` contains no traceback, no
  `langfuse` warning beyond the three summary lines, and no `WARNING`/`ERROR`
  record of any kind.
- **The flush is slow, and it is Langfuse's ingestion, not the exporter.** 14.1 s
  from terminal to first visibility (§5). Nothing in the app was waiting: the
  run had returned its result 14 s earlier.
- **The Langfuse public API rate-limits.** Five consecutive `HTTP 429` while
  polling at 1 s. The pull scripts did not hit it; a poller must back off.
