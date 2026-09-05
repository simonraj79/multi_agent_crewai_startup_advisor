# Task 3 proof runs — what was run, what it cost, and where it differs from the plan

Executed **2026-09-05/06** by **V-PROOF**, an Opus 5 verifier who built none of
this code and edited nothing under `src/`, `tests/`, `scripts/` or `frontend/`.
Everything this session wrote is under `docs/observability/evidence/proof/`.

**Code commit: `e68dac4`** (`feat(observability): app-side Langfuse exporter,
the audit, the definition of done and the reconciliation tooling`) — with the
two qualifications below, both of which are about other agents committing while
these runs were in flight, and both of which are measured rather than assumed.

> **1. The working tree was NOT clean at `e68dac4`.** `git status --short` at
> the start of this session showed three files modified by another agent:
> `src/brief_crew/service/runner.py` (+57/-0), `tests/events/test_trace_fixture.py`
> and `frontend/tests/fixtures/serializerFrames.ndjson`. Those edits were
> committed **during** this session as `7417270` (00:47:41 +08:00, "the
> synthetic double carries a prompt digest"). `runner.py` is the **synthetic**
> runner, so it is in the two free runs (`cancelled` at 00:41, `capture-on` at
> 00:42) and in none of the four paid ones. Nothing was stashed: stashing would
> have destroyed another agent's work in progress.
>
> **2. `ad6a696` landed 18 minutes AFTER the last run** (01:00:20 +08:00,
> "every outbound string goes through the scrub…") and it touches
> `src/brief_crew/observability/langfuse_exporter.py` (+62) and
> `src/brief_crew/events/serializer.py` (+21). **Nothing here was measured
> against it.** Checked before signing: its diff contains no line matching
> `lookup`, `deadline`, `messages`, `error_class`, `statusMessage` or `input`,
> so none of the five defects below is addressed by it — but a re-measurement
> at HEAD is the only thing that can say so authoritatively, and this session
> did not do one.
>
> Run times, for the record: the paid runs were launched 00:33:04–00:34:41
> (+08:00), i.e. **after** `e68dac4` and **before** both later commits.

## The runs

| slug | run id | trace id | flow | gates | env | terminal | frames | LLM calls (app) | GENERATIONs | app estimate | OpenRouter BILLED | attempts |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `validator-live` | `f4c8c779-52f2-40e1-9351-2668ea276ae4` | `f4c8c77952f240e193512668ea276ae4` | `idea-validator` | auto | live | completed | 155 | 10 | 10 | $0.03823525 | **$0.03823525** | 1 |
| `builder-toolfail` | `9becf713-e984-45a9-b9c0-5b229a15cb60` | `9becf713e98445a9b9c05b229a15cb60` | `ug_4e7e952f` (builder) | auto | live | **failed** | 43 | 2 | 2 | $0.0003689 | **$0.0003689** | 1 |
| `builder-agentfail` | `ca13fc73-0ca9-4a31-bc8c-6e53ed1d562d` | `ca13fc730ca94a31bc8c6e53ed1d562d` | `ug_fd12e0a6` (builder) | auto | live | **failed** | 50 | 0 | 6 (all ERROR) | $0.00 | **$0.00** — no generation record exists | 1 |
| `brief-live` | `6586c854-3ca3-44c4-a587-eb6a3ef01962` | `6586c8543ca344c4a587eb6a3ef01962` | `brief-flow` | human | live | completed | 116 | 10 | 10 | $0.09759125 | **$0.08876144** | 1 |
| `cancelled` | `073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba` | `073c021f4ff743e184d5d9e8dd7fa0ba` | `idea-validator` | auto | **synthetic** | **cancelled** | 82 | 5 | 5 | $0.00209 (fabricated) | free | 1 |
| `capture-on` | `c5d1dde9-c22d-4621-a171-9a7e85803105` | `c5d1dde9c22d4621a1719a7e85803105` | `idea-validator` | auto | **synthetic** | completed | 98 | 6 | 6 | $0.002722 (fabricated) | free | 1 |

### Pass 2 — the re-proof at `c608953`

Run 2026-09-06 against **`c608953`** (`fix(observability): the billed-cost lookup
is deferred and retried, every error observation names its exception class, and
run_metrics falls back to the exporter's tally`), same rules and same backend
recipe. New directories so pass 1 stays intact.

| slug | commit | run id | trace id | flow | gates | env | terminal | frames | LLM calls (app) | GENERATIONs | app estimate | OpenRouter BILLED | `lookup_ok` / `lookup_failed` |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `builder-agentfail-2` | `c608953` | `45cc3736-ed0b-466a-9dc6-e7f69ff0eea0` | `45cc3736ed0b466a9dc6e7f69ff0eea0` | `ug_fd12e0a6` | auto | live | **failed** | 50 | 0 | 6 (all ERROR) | $0.00 | **$0.00** | 0 / 0 |
| `builder-toolfail-2` | `c608953` | `6342e33f-268e-4b67-87ae-1574a2fffbeb` | `6342e33f268e4b6787ae1574a2fffbeb` | `ug_4e7e952f` | auto | live | **failed** | 43 | 2 | 2 | $0.0003689 | **$0.000369** | **2 / 0** |
| `validator-live-2` | `c608953` | `1a0bea14-ffb3-459d-b5fc-f714a76e5f71` | `1a0bea14ffb3459db5fcf714a76e5f71` | `idea-validator` | auto | live | completed | 178 | 12 | 12 | $0.05625510 | **$0.06441798** | **12 / 0** |

Pass 2 exporter summary lines, verbatim from `backend-8000-pass2.log`:

```text
langfuse-exporter run=45cc3736-... frames_enqueued=50  frames_dropped=0 observations_sent=35  http_errors=0 lookup_ok=0  lookup_failed=0 enqueue_p50_us=4 enqueue_p95_us=12
langfuse-exporter run=1a0bea14-... frames_enqueued=178 frames_dropped=0 observations_sent=102 http_errors=0 lookup_ok=12 lookup_failed=0 enqueue_p50_us=4 enqueue_p95_us=13
langfuse-exporter run=6342e33f-... frames_enqueued=43  frames_dropped=0 observations_sent=24  http_errors=0 lookup_ok=2  lookup_failed=0 enqueue_p50_us=4 enqueue_p95_us=14
```

**14 of 14 billed-cost lookups resolved, none failed** — against 0 of 22 in
pass 1. `frames_enqueued` again equals the app's own frame count on every run;
`frames_dropped=0` and `http_errors=0` throughout.

### Pass 3 — the final re-proof at `58a1c0b`

Run 2026-09-06 against **`58a1c0b`** (`fix(observability): the exception class
reaches every error observation, a generation held for its price is never marked
failed, and identity fields are scrubbed by value only`). `validator-live-3` and
`builder-toolfail-3` are the **concurrent pair** (5 ms apart); `builder-agentfail-3`
followed once both had settled.

| slug | commit | run id | trace id | flow | gates | env | terminal | frames | LLM calls | GENERATIONs | app estimate | OpenRouter BILLED | `lookup_ok` / `failed` |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `validator-live-3` | `58a1c0b` | `f146e846-7e32-4276-9c9d-d79909a02eec` | `f146e8467e3242769c9dd79909a02eec` | `idea-validator` | auto | live | completed | 167 | 11 | 11 | $0.05268975 | **$0.05697687** | **11 / 0** |
| `builder-toolfail-3` | `58a1c0b` | `f0297951-e1ff-49a1-90f6-725d06d9b112` | `f0297951e1ff49a190f6725d06d9b112` | `ug_4e7e952f` | auto | live | **failed** | 44 | 2 | 2 | $0.0003689 | **$0.000369** | **2 / 0** |
| `builder-agentfail-3` | `58a1c0b` | `f371b3b9-6ca5-4b8b-9f63-9c34249ef440` | `f371b3b96ca54b8b9f639c34249ef440` | `ug_fd12e0a6` | auto | live | **failed** | 50 | 0 | 6 (all ERROR) | $0.00 | **$0.00** | 0 / 0 |

Pass 3 exporter summary lines, verbatim from `backend-8000-pass3.log`:

```text
langfuse-exporter run=f0297951-... frames_enqueued=44  frames_dropped=0 observations_sent=24 http_errors=0 lookup_ok=2  lookup_failed=0 enqueue_p50_us=3 enqueue_p95_us=16
langfuse-exporter run=f146e846-... frames_enqueued=167 frames_dropped=0 observations_sent=96 http_errors=0 lookup_ok=11 lookup_failed=0 enqueue_p50_us=3 enqueue_p95_us=11
langfuse-exporter run=f371b3b9-... frames_enqueued=50  frames_dropped=0 observations_sent=35 http_errors=0 lookup_ok=0  lookup_failed=0 enqueue_p50_us=4 enqueue_p95_us=13
```

`lookup_ok` equals the app's own call count on both priced runs (11 and 2);
`frames_enqueued` equals the frame count on all three; nothing dropped, no HTTP
error, `enqueue_p95` at most 16 microseconds.

**`validator-live-2` was also re-pulled** with the `58a1c0b` tooling, in place,
overwriting the eleven files the old redactor had damaged. See its README: the
tooling now writes the run id whole, and the one value that cannot be repaired by
re-pulling — `trace.metadata.run_id` on that run's **stored** trace — still reads
`1a0bea14-ffb3-459d-b5***`, because the exporter wrote it that way at `c608953`.

Every trace id is `UUID(run_id).hex`. Every `sessionId` is the app run id
verbatim. Every paid trace carries `userId = proof-runner` and
`environment = live`; both synthetic traces carry `userId = anonymous` and
`environment = synthetic`.

**No run needed a second attempt.** In particular `builder-toolfail` called both
of its tools on the first try, so the relaunch the brief authorises was not used.

Langfuse project `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw`
— a session is `/sessions/<run id>`, a trace `/traces/<trace id>`. Each run's own
`README.md` carries its URLs and the observation ids its screenshots show.

## Money

| | |
| --- | --- |
| `validator-live` | **$0.03823525** |
| `builder-toolfail` | **$0.0003689** |
| `builder-agentfail` | **$0.00** — the one request was refused at HTTP 400 before generation |
| `brief-live` | **$0.08876144** |
| one diagnostic call (defect 1 below) | 1 completion token, `google/gemini-3.5-flash-lite`. **Unpriceable, and that is the finding**: OpenRouter never indexed its generation id. Bounded above by about $0.000002 at that model's published rate |
| **PASS 1 TOTAL, from OpenRouter's own billed figures** | **$0.1274** |
| `builder-agentfail-2` | **$0.00** |
| `builder-toolfail-2` | **$0.000369** |
| `validator-live-2` | **$0.06441798** |
| **PASS 2 TOTAL** | **$0.0648** — against the pass-2 authorisation of **$0.15**, **43 % used** |
| `builder-agentfail-3` | **$0.00** |
| `builder-toolfail-3` | **$0.000369** |
| `validator-live-3` | **$0.05697687** |
| **PASS 3 TOTAL** | **$0.0573** — against the pass-3 authorisation of **$0.15**, **38 % used** |
| **ALL THREE PASSES** | **$0.2495** |

Against the **$1.00** pass-1 authorisation: **12.7 % used**. Every figure comes from
`GET /api/v1/generation?id=` through `scripts/observability/pull_openrouter.py`
(`openrouter-generations.json` and `openrouter.md` in each run's directory), not
from the app's estimate. The two synthetic runs cost nothing and their usage is
fabricated by the doubles — it must never enter a cost view, which is what
`environment=synthetic` exists for.

The account balance was read with the OpenRouter MCP before starting and is
deliberately recorded in no file.

## The backends

**Paid, `127.0.0.1:8000`** — log `backend-8000.log`; readiness
`readyz-before.json`, captured **before any launch**:

```text
observability: {"exporter":"enabled","reason":null,"environment":"live",
                "capture_content":false,"resolve_billed_cost":true}
executor:      {"status":"ok","workers":2}      storage: sqlite
```

`GET /docs` answered **404**, which is the proof the instance is not synthetic
(`expose_docs` is `EXPOSE_API_DOCS or synthetic`).

Environment, all exported. `.env` declares none of these five names, and `.env`
wins by `override=True` for everything it does declare:

```text
AUTH_BASE_URL=http://127.0.0.1:8093    CREDENTIALS_MASTER_KEY=<the tests/__init__.py base64 placeholder>
RUN_CONCURRENCY=2                      PORT=8000    HOST=127.0.0.1
```

Launched as `python -c "logging.basicConfig(level=INFO); serve()"`, because
under a bare `serve.exe` the exporter's INFO records reach `logging.lastResort`
(WARNING and above) and only the per-run summary would be visible.

**JWKS stand-in, `127.0.0.1:8093`** — `scripts/observability/mint_identity.py serve`,
log `jwks.log`. Started **before** the backend and killed **after** it. Every
request carried a bearer minted with `--ttl 7200` for subject `proof-runner`;
the token was written to a scratch file outside the repository and was never
echoed, logged or committed. The private key lives outside the repository at
`%TEMP%\brief-crew-proof-identity\ed25519.pem` and was deleted at the end.

**Free, `127.0.0.1:8099`** — `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=8`,
`VALIDATOR_ALLOW_AUTO_GATES=1`, no `AUTH_BASE_URL`. Started twice: once for
`cancelled` (`backend-8099.log`, copied to `cancelled/backend-8099-cancelled.log`)
and again with `LANGFUSE_CAPTURE_CONTENT=1` for `capture-on`
(`backend-8099-capture.log`).

All three processes were killed **by PID** (`netstat -ano`, then
`taskkill /PID <pid> /T /F`), the backends first and the JWKS server last.
Never `pkill`; never `Stop-Process -Name serve`.

## The exporter's own self-report, verbatim from `backend-8000.log`

```text
langfuse-exporter run=9becf713-... frames_enqueued=43  frames_dropped=0 observations_sent=24 http_errors=0 lookup_ok=0 lookup_failed=2  enqueue_p50_us=4 enqueue_p95_us=10
langfuse-exporter run=f4c8c779-... frames_enqueued=155 frames_dropped=0 observations_sent=90 http_errors=0 lookup_ok=0 lookup_failed=10 enqueue_p50_us=4 enqueue_p95_us=12
langfuse-exporter run=ca13fc73-... frames_enqueued=50  frames_dropped=0 observations_sent=35 http_errors=0 lookup_ok=0 lookup_failed=0  enqueue_p50_us=4 enqueue_p95_us=13
langfuse-exporter run=6586c854-... frames_enqueued=116 frames_dropped=0 observations_sent=60 http_errors=0 lookup_ok=0 lookup_failed=10 enqueue_p50_us=4 enqueue_p95_us=20
```

`frames_enqueued` equals the frame count the app itself served for every run
(155 / 43 / 50 / 116): nothing was skipped at the door. **Nothing was dropped and
no HTTP error occurred on any run.** `enqueue_p95` is at most 20 microseconds on
the capture thread. `observations_sent` counts scores as well as observations
(smoke-live defect D8), so it does not equal the observation count.
`lookup_failed` is defect 1 below.

## Where this diverged from `PLAN.md`, and why

1. **Every paid run was launched as a SIGNED-IN user, not anonymously.**
   `PLAN.md` describes an `.env`-only backend with no `AUTH_BASE_URL`. That
   backend cannot run `builder-toolfail`'s document at all:
   `builder-toolfail/inject.md` section 7 measured that a custom tool is
   per-user by construction (401 to create one), and that
   `builder/runtime.py::_custom_tool_spec` raises for an unowned run — losing C2
   and D2 together. `identity/README.md` is the way through and is what was used.
   Consequence worth stating plainly: every paid trace here reads
   `userId: proof-runner` rather than `anonymous`, which is a **stronger** A3
   result, not a weaker one.
2. **`brief-live` was added.** A1 names three flow kinds — hand-written
   validator, hand-written brief, builder-authored graph — and `PLAN.md`
   scheduled two. Budget allowed the third, so A1 is complete rather than
   PARTIAL.
3. **The tool that raises is not the tool the author named, and cannot be.**
   `inject.md` sections 2 and 7 predicted this and the run confirms it: the only
   tool an author can NAME is a custom HTTP tool, and that tool **reports**
   rather than raises, by design. So `sounding_line_lookup` (author-named,
   appears verbatim as a TOOL observation, reports `failed`) satisfies C2, and
   `read_website_content` (library tool, raises `ValueError`) satisfies D2.
   **This is a fact about the builder, not a shortfall of the tracing** —
   whatever name the frame carries is the name Langfuse shows. Related:
   `inject.md` predicted the library tool's runtime name would be
   `Read website content`; it is `read_website_content`.
4. **The agent-failure injection is `inject.md`'s substitute, not `PLAN.md`'s.**
   An unserved model id is refused at validate **and** at publish with two
   error-severity problems, so `llm.max_tokens: 2000000000` on a real roster
   model was used instead: the same failure class (a provider refusal, zero
   tokens) through a field the schema deliberately leaves unbounded. The
   provider's refusal is quoted verbatim in `builder-agentfail/README.md`.
5. **The credential injection was not attempted**, for the reason `inject.md`
   section 1 records: a wrong-key credential needs a vault row, and a keyless
   library tool aimed at an RFC 2606 `.invalid` host raises just as hard and
   costs nothing.
6. **The cancelled run is synthetic, and this file says so** — D3 permits it and
   asks the report to name it.

## Defects seen in the exporter's output on a PAID run

Full detail in `DEFECT-billed-cost-lookup.md` and in each run's README. With the
field:

1. **`metadata.cost_source` reads `app-estimate (lookup failed)` on 22 of 22
   paid generations**, and `metadata.openrouter_cost_usd`, `metadata.provider`,
   `usageDetails.reasoning` and `usageDetails.cached` are absent. Cause
   **measured**: the exporter's lookup code is *correct* — driven by hand against
   a real id it returns
   `BilledCost(total_usd=0.00658725, provider='Google', reasoning_tokens=1115, cached_tokens=0)`
   — but it fires within `LANGFUSE_BILLED_LOOKUP_DEADLINE_SECONDS = 3.0` with one
   attempt and no retry, while OpenRouter answered **404 for a fresh generation
   id from +0.71 s through +60.06 s**, and still 404 twenty minutes later
   (`openrouter-index-latency.json`). The feature therefore ships permanently off
   while `/readyz` reports `resolve_billed_cost: true`.
2. **No exception class on any error observation except TOOL.** The
   `statusMessage` on the failing agent, task, node and run spans is the message
   alone, and `metadata.error_class` is absent — while the app's own `NODE_END`
   frame carries `error_class: "BadRequestError"` (agentfail) and
   `"ToolExecutionFailedError"` (toolfail). `TRACE-CONTRACT.md` section 6 asks
   for "error class + redacted message". A mapping gap, not information the app
   never had.
3. **A GENERATION's `input` is null even under `LANGFUSE_CAPTURE_CONTENT=1`**,
   because the LLM `before` frame carries no messages at all — measured on the
   PAID run, its detail keys are exactly `agent_id, agent_role, call_id,
   message_count, model, prompt_chars, prompt_fingerprint, stage, task_id,
   task_name`. `output`, `trace.input` and tool arguments and results **are**
   captured and redacted. Contract section 4's `input` row is unsatisfiable as
   written: the contract and the frame pipeline disagree, and the exporter is
   faithful to the frame.
4. **`trace.metadata.run_metrics` is `null` on `builder-agentfail`** — that run
   emitted no `METRICS_UPDATED` frame at all. Faithful, but a reader treating
   trace metadata as the run's cost source gets nothing from a run that failed
   early. (On the other three paid runs it is the FINAL snapshot,
   `reason: run_completed` / `run_failed` — smoke-live defect D4 is fixed.)
5. **`open-spans.txt` counts EVENT observations**, which carry no `endTime` by
   construction, so it reads 38 / 10 / 19 / 22 on the paid runs.
   `cancelled/open-spans-by-type.txt` splits it: **0** non-EVENT observations are
   open on any of the six runs. A tooling artifact rather than an exporter
   defect — but D3's stated instrument is that file, so it is recorded here.

Two smoke-live defects are **fixed**, and this session confirms it on paid runs:
the trace has exactly **one parentless root** (`hierarchy.txt` draws the whole
tree, where smoke-live's was empty), and `prompt_fingerprint_basis` is `messages`
with 10 distinct fingerprints on `validator-live` rather than a hash of the
identity.

## What pass 2 settled, at `c608953`

| pass-1 defect | pass-2 result |
| --- | --- |
| 1. billed-cost lookup never succeeds | **FIXED.** `lookup_ok=12/12` and `2/2`; `cost_source = openrouter-billed` everywhere; `openrouter_cost_usd`, `provider`, `usageDetails.reasoning`, `usageDetails.cached` all present; `costDetails.total` equals OpenRouter's `total_cost` per generation, and both sums are `$0.06441798`. The run span still ends at the terminal frame's own timestamp (`17:26:55.255Z` on both sides) although the lookups ran for another three minutes |
| 2. no exception class on any error observation | **NOT FIXED.** `metadata.error_class` is `None` on every error observation of both failure runs, and `trace.output.error_class` is `null` — the key is new, the value is not set. Measured cause in `builder-agentfail-2/README.md` and `builder-toolfail-2/README.md`: **exactly one frame per run carries `error_class`, and it closes no span** |
| 3. generation `input` null under capture | **RESOLVED BY DECISION, not by code.** Contract §4 now says `input` is absent under every policy because prompt content never enters the frame pipeline; B5's capture half is judged on `output`, tool payloads and the trace input, all of which are present and redacted. Row B5 is re-judged **PASS** |
| 4. `run_metrics` null on a run with no metrics frame | **FIXED.** `builder-agentfail-2` reads `run_metrics.source = "exporter-tally"` with `call_count: 6`; the other two read `source: "app-snapshot"` |
| 5. `open-spans.txt` counted EVENTs | **FIXED.** The instrument now leads with `unfinished spans (non-EVENT observations with endTime null): 0` and prints the three-way split beneath it. 0 on all three pass-2 runs |

## What pass 3 settled, at `58a1c0b`

| carried into pass 3 | pass-3 result |
| --- | --- |
| **no exception class on any error observation** (the one row two passes could not close) | **FIXED.** `builder-agentfail-3`: `metadata.error_class = "BadRequestError"` and `statusMessage` beginning `BadRequestError: …` on the **agent, task, node AND run** observations, and `trace.output.error_class = "BadRequestError"`. `builder-toolfail-3` distinguishes two classes correctly — `ValueError` on the TOOL, `ToolExecutionFailedError` on the agent/task/node/run and the trace |
| the held-close risk that came with it | **not realised.** Every span still ends on its own closing frame: agent and task at `18:16:04.701Z` (the `AGENT_CALL` frames), node at `.718Z` (`NODE_END`), run at `.721Z` (`WORKFLOW_END`) — three distinct timestamps |
| a successful generation swept to ERROR by a failed run's terminal (regression #12) | **FIXED.** `builder-toolfail-3`'s two generations are `level: DEFAULT` with `cost_source: openrouter-billed`, on a run whose own span is `ERROR` |
| the `fc-` scrub mangling a run id | **FIXED on both sides.** `validator-live-3`'s `trace.metadata.run_id` reads in full; the re-pulled `validator-live-2` now writes the id whole in every file, and the one residue is that run's stored trace, which no re-pull can change |
| A2 / D5 on the new code | **PASS.** `concurrent-3/membership-check.txt`: `sessions=2 traces=2 observations=102 mismatches=0 cross-membership=0 no-run_id=0 VERDICT=PASS`, over a pair launched **5 ms** apart |
| billed-cost resolution | **still fixed**, `lookup_ok` = the app's call count on both priced runs (11 and 2), 0 failed, `costDetails.total` equal to OpenRouter's `total_cost` on every generation |

### One NEW defect, in the tooling, found by pass 2 — FIXED at `58a1c0b`

`scripts/observability/_common.py::redact_for_disk` scrubs the Firecrawl prefix
`fc-`, and a hex UUID can contain it. `validator-live-2`'s run id
`1a0bea14-ffb3-459d-b5fc-f714a76e5f71` is written to disk as
`1a0bea14-ffb3-459d-b5<redacted>` in **11** of that directory's files, including
`langfuse-session.json.id` — the exact field row A1 is verified on. The true id
survives in the app-side files, in the live API and in the console header of
`validator-live-2/B5-billed-cost-resolved.png`, so nothing is lost here; but a
UUID group ends in `fc` about 1.5 % of the time, so this will recur silently and
it damages the evidence rather than protecting anything.

**Closed at `58a1c0b`, and it had a second half nobody had seen.** The tooling's
shape rule gained a UUID boundary, and `validator-live-2` was re-pulled: every
file it writes now carries `1a0bea14-ffb3-459d-b5fc-f714a76e5f71` whole. The
second half is that **the exporter was scrubbing it too** — `trace.metadata.run_id`
on that run's stored trace reads `1a0bea14-ffb3-459d-b5***` and always will,
because that is what was sent to Langfuse. `58a1c0b` scrubs identity fields by
exact value only, and `validator-live-3`'s stored `run_id` is whole. Had the
damaged run been half of a concurrent pair, `membership_check.py` would have
reported one mismatch on its `run` span — which is why A2 was re-measured on a
fresh pair (`concurrent-3/`) rather than left resting on pass 1.

One number for E5, not diagnosed here because E5 is V-RECON's row: on
`brief-live` the app's estimate is **9.9 % HIGH** ($0.09759125 against
$0.08876144 billed). The other two priced runs agree to the cent. `brief-live` is
the only run that leaned on the escalation tier, which is where cached and
reasoning tokens live — and, by defect 1, exactly the split the trace does not
carry.

## 8. Commit-hash map after the planted-key rewrite (2026-09-06)

GitHub push protection refused the first push because the E3 proof's PLANTED
FAKE key (`sk-or-v1-` + 64 zeros, never a real credential - F3 scanned 0 values)
matches its OpenRouter key pattern. The tail was rewritten to
`sk-or-v1-0000000000000000-planted-fake-key` in the five files that carried it
(the E3 test constant and the four `capture-on` app-side files), through every
unpushed commit, so the hashes the evidence prose cites are the PRE-rewrite
ones. Map:

| cited in the evidence | pushed |
| --- | --- |
| `e68dac4` | `9df7ee2` |
| `7417270` | `77a5634` |
| `ad6a696` | `77a8222` |
| `c608953` | `38ed0c4` |
| `58a1c0b` | `ba5a613` |
| `1130f32` | `a20a3bc` |

Nothing else in any commit changed; the exporter's scrub still blanks the new
shape (E3 test and both probes re-run after the rewrite).
