# The exporter's own account of the first production run

**2026-09-05 (UTC) / 2026-09-06 local.** Read from the **server side only**:
Render's log API for what the process said, the unauthenticated health probes
for what it thinks it is configured as, and OpenRouter for what was actually
billed. No code was changed and no run was launched from here.

The run is the owner's: `40a9c597-0613-4a4f-9ce1-3d9252410445`, launched on
`agentic-crew-ai-api` (`srv-da9qe7p42hec738l26og`) roughly six minutes after the
deploy that turned the exporter on
([`../../deploy/README.md`](../../deploy/README.md)). It is the only run in the
service's logs today, and the only one the exporter has ever reported.

## The summary line, verbatim

`exporter-lines.txt`, one line, `2026-09-05T22:37:45.896209654Z`:

```text
WARNING:brief_crew.observability.summary:langfuse-exporter
run=40a9c597-0613-4a4f-9ce1-3d9252410445 frames_enqueued=181 frames_dropped=0
observations_sent=104 http_errors=0 lookup_ok=12 lookup_failed=0
enqueue_p50_us=11 enqueue_p95_us=30
```

(Wrapped for width. It is a single line in the log and a single line in
`exporter-lines.txt`.)

| counter | value | what it is evidence of |
|---|---:|---|
| `frames_enqueued` | **181** | distinct frames the exporter accepted, replays already discarded (`frame.seq <= last_seq` is skipped before this counts) |
| `frames_dropped` | **0** | nothing was evicted from the export queue |
| `observations_sent` | **104** | successful `open_run` / `open_child` / `event` / `score` calls |
| `http_errors` | **0** | no exception from any backend call, and no flush that failed to finish |
| `lookup_ok` | **12** | generations whose **billed** cost was resolved from OpenRouter |
| `lookup_failed` | **0** | none fell back to the app estimate |
| `enqueue_p50_us` | **11** | median time the app's own thread spent handing a frame over: 11 microseconds |
| `enqueue_p95_us` | **30** | p95 of the same |

## What those numbers prove, one at a time

**`frames_enqueued=181` is the exporter's count, so it is checked against the
app's.** The run span in Langfuse carries the app's own snapshot
(`metadata.run_metrics.frames`, `source: app-snapshot`):

```text
captured 180   dropped 0   gaps 0   emit_errors 0   subscriber_dropped 0   unattributed 0
```

180 against 181, and the highest `frame_seq` on any observation is 177. The
one-frame difference is what the ordering predicts rather than a discrepancy:
the app builds its metrics snapshot inside a frame, and the exporter goes on to
enqueue that frame and the terminal one after it. What matters for delivery is
that **both sides independently report zero loss** — `dropped 0` and `gaps 0`
from the app, `frames_dropped=0` from the exporter.

**`http_errors=0` is worth more here than in a local run.** The deploy record
named the one failure mode `/readyz` cannot see: *a wrong or unreachable base
URL would look exactly like this from the outside — the exporter reports
enabled, the queue fills, the flush fails.* This counter is the answer to that.
It counts a flush that did not **finish** as an error too, and it is logged
**after** the flush precisely so it cannot report zero for a backend that was
never reachable. Egress from Render's singapore region to
`us.cloud.langfuse.com` works.

**`lookup_ok=12` equals the number of calls the app made**, which is the healthy
shape [`../../proof/validator-live-3/`](../../proof/validator-live-3/) records.
Four sources agree on 12, and only one of them is the exporter:

| source | figure |
|---|---|
| the app's own run metrics on the run span | `successful_requests: 12`, `call_count: 12` |
| the exporter's summary line | `lookup_ok=12`, `lookup_failed=0` |
| the trace, re-read after the summary landed | **12** GENERATION observations, `cost_source: openrouter-billed` on **12 of 12** |
| OpenRouter, asked per generation | **12** `GET /api/v1/generation` lookups, all HTTP 200 |

**`observations_sent=104` reconciles exactly**: 87 observations on the trace
plus 17 scores. The arithmetic is the same one `validator-live-3` shows
(96 = 81 + 15).

## One thing this pass found, and it is the reason to re-read a trace late

The sibling pull in
[`../40a9c597-0613-4a4f-9ce1-3d9252410445/`](../40a9c597-0613-4a4f-9ce1-3d9252410445/)
was generated at **22:36:58Z**, forty-seven seconds **before** the exporter
logged its summary, and it records **81 observations and 6 generations**. Read
again at 22:41Z the same trace carries **87 observations and 12 generations**,
all twelve `openrouter-billed`. Nothing was lost and nothing is contradictory:
a generation is **held open until its billed price is known**, and the billed
lookup retries on a 20 s / 60 s / 180 s schedule inside a 240 s deadline
(`_LOOKUP_ATTEMPT_DELAYS`, `LANGFUSE_BILLED_LOOKUP_DEADLINE_SECONDS`). Six of
the twelve had not been priced yet at 22:36:58.

`observations_sent=104` is what makes that legible from the log alone: 81 + 17
scores is 98, not 104, so the summary line already said six observations were
missing from that pull. **The summary line is emitted after the last lookup
settles, so it — not a clock — is the signal that a trace is finished.**
Anything that reads a trace before it appears is reading a partial one.

## `/readyz` and `/healthz`, now

`readyz-now.json`, probed `2026-09-05T22:45Z`, both HTTP 200. All four required
answers hold, unchanged from the deploy record and now with a run behind them:

```json
{"exporter": "enabled", "reason": null, "environment": "live",
 "capture_content": false, "resolve_billed_cost": true}
```

`capture_content: false` is the one to keep looking at: the exported trace of a
real user's idea carries structure, identity and money, and **no prompt or
completion text**. `/healthz` reports `storage.backend: "postgresql"`, one
worker.

## OpenRouter, from outside

`openrouter-activity.json`. Two things did not go as the brief assumed, and both
are recorded there rather than worked around:

- **`GET /api/v1/activity` cannot answer for this window.** It is one row per
  (UTC day, model, endpoint) — there is no hour-level endpoint — and the current
  UTC day is refused outright: *"Date must be within the last 30 (completed) UTC
  days"* (HTTP 400). So no activity row for 2026-09-05 exists to be read.
- **`GET /api/v1/auth/key` answers for the key, not the window.** It reports
  `usage_daily` for the whole UTC day, which also contains the four local proof
  runs from earlier today, and `limit: null` (no cap on this key).

So the window figure was taken the strict way instead, one generation at a time:
every GENERATION observation on the production trace carries
`metadata.response_id`, and each was resolved with
`GET /api/v1/generation?id=…`.

| | |
|---|---|
| generations in the window | **12**, all HTTP 200 |
| first / last `created_at` | `2026-09-05T22:33:09.882Z` / `2026-09-05T22:33:50.900Z` |
| OpenRouter's own `total_cost`, summed | **$0.08794491** |
| the same figure carried on the Langfuse trace | **$0.08794491** — 0 of 12 differ |
| the app's own estimate on the run span | $0.07775795, i.e. **11.6 % low** |
| tokens (Langfuse `usageDetails` sum) | 48,908 in / 14,124 out / 63,032 total, 533 reasoning — identical to the app's `run_metrics.usage` |

Every generation is inside the run, inside the window, and priced. The app's
estimate being ~12 % low is the gap the billed-cost lookup exists to close, and
on this run it closed it.

**Credits.** `mcp__openrouter__get-credits` was called; the balance is
deliberately not written here (repo rule — re-measure, never quote). In delta
form against the 2026-09-04 figure recorded in `CLAUDE.md`: **−$0.9157** across
the whole programme since that figure was taken. This run is $0.088 of it.

## What else is in the log, and what is not

`exporter-lines.txt` carries every match, with timestamps, for
`langfuse-exporter`, `langfuse`, `observability`, `WARNING`, `ERROR` and
`Traceback` over the last three hours, and for `langfuse-exporter`,
`langfuse export failed`, `the langfuse` and `Traceback` over twelve.

- **One** `langfuse-exporter` line in twelve hours — the summary above.
- **Zero** `langfuse export failed …` lines (the exporter's own at-most-once
  per-run failure warning).
- **Zero** matches for `the langfuse …` — no *"queue stayed full"*, no *"did not
  flush within"*, no *"backend did not … within"*, no *"export thread stopped"*.
  Those are every remaining WARNING the observability package can emit; the
  greps that enumerate them are in the file header.
- **Zero** tracebacks.
- The other WARNING and the ten ERROR lines in the window are **the crew, not
  the exporter**: a `research_market` guardrail retry on `MarketFindings`
  source-URL ordering, and the Reporter failing `REPORT_URL_CLOSURE` twice
  before the flow assembled the report mechanically. They are reproduced in full
  because they are what a reader will otherwise mistake for exporter noise.

**There is no per-run startup line, and its absence proves nothing.** The
package logs *"langfuse export is on: environment=… content=… billed-cost=…"* at
**INFO** (`observability/__init__.py:159`), and this service configures no
handler for it, so the root logger's default WARNING level discards it — which
is also why every line that does appear is formatted `LEVEL:logger:message` by
logging's last-resort handler. By design the exporter emits **exactly one
WARNING per run** (the summary), plus at most one more if something failed.
Nothing was missing; there was never anything to find.

## Verdict

**From the server's point of view, the exporter delivered this run cleanly.**

Every counter on the line is the healthy value: nothing dropped, nothing
errored, every generation priced from the provider rather than estimated, and
the enqueue cost to the application's own thread was 11 µs at the median and
30 µs at p95. The app and the exporter agree independently that no frame was
lost; the trace, re-read after the summary landed, carries every observation the
summary says was sent; and OpenRouter's own per-generation records agree with
the trace's costs to the cent and beyond.

The claim the deploy record could not make — *"that egress to
`us.cloud.langfuse.com` is reachable from Render's singapore region at all"* —
is now made, and by the counter that would have caught its opposite.

**One caveat, and it is about method rather than result.** `frames_enqueued` and
the p50/p95 come from the exporter's own instrumentation; the independent
corroboration here is the app's run-metrics snapshot, which travels *inside* the
same trace. The app's `GET /api/runs/{id}` figure — the fully independent one —
needs the owner's signed-in session and was not fetched. It would be worth one
authenticated GET to close.

## Files

| File | What it is |
|---|---|
| `exporter-lines.txt` | every matching Render log line, with timestamps, the queries that produced them, and the redaction note |
| `readyz-now.json` | live `/readyz` and `/healthz`, with the four required checks evaluated |
| `openrouter-activity.json` | `auth/key`, the `activity` refusal, the 12 per-generation lookups, and the credits delta |
| `secret-scan.txt` | `scripts/observability/secret_scan.py` over this directory |

No credential value was printed, echoed or written at any point. Every key was
read with `os.environ` and handed straight to an `Authorization` header. The one
log line in this run's window that *does* carry a credential — uvicorn's access
log for the WebSocket handshake, which echoes the 15-minute bearer JWT in the
query string — appeared only in the unfiltered pull and is deliberately not
reproduced. `secret-scan.txt` is the check on that claim rather than the claim
itself.
