# Exporter overhead - DoD E4

Measured 2026-09-05T13:41:06Z on this machine.
Runs per arm: 1. Arms alternated on/off, not run in two blocks.
Workflow `idea-validator`, `gates: "auto"`, `SYNTHETIC=1`, `SYNTHETIC_BRANCH_DELAY_SECONDS=1`.

## Wall clock per run (launch to terminal status, client side)

| arm | n | mean s | median s | min s | max s | stdev s |
| --- | --- | --- | --- | --- | --- | --- |
| on | 1 | 3.079 | 3.079 | 3.079 | 3.079 | 0.000 |
| off | 1 | 3.327 | 3.327 | 3.327 | 3.327 | 0.000 |

**Delta (on - off), on the means: -0.248 s (-7.5%).**

A synthetic run's duration is dominated by `SYNTHETIC_BRANCH_DELAY_SECONDS`, which is held equal, so the delta is
the exporter's contribution plus this machine's noise. Read it against
the `stdev` column: a delta inside one standard deviation is not a
measurement of the exporter.

## The exporter's own counters

Parsed from the captured server log, one summary line per run (`TRACE-CONTRACT.md` section 10).

| arm | summary lines | enqueued | sent | dropped | enqueue p50 us (mean) | enqueue p95 us (mean) |
| --- | --- | --- | --- | --- | --- | --- |
| on | 1 | 95 | 108 | 0 | 0.0 | 2.0 |
| off | not found | - | - | - | - | - |

## Per run

| arm | # | run_id | status | wall s | frames | dropped | calls | tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| on | 1 | 43218417-1e55-484d-ad41-745378fbe32c | completed | 3.079 | 96 | 0 | 6 | 4337 |
| off | 1 | a6df5901-712a-40c6-a73c-2eea225d36da | completed | 3.327 | 96 | 0 | 6 | 4337 |

## The exact commands

```text
# on arm
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=1 PORT=8110 LANGFUSE_EXPORT_ENABLED=(unset) VALIDATOR_ALLOW_AUTO_GATES=1 LANGFUSE_BASE_URL=http://127.0.0.1:9 LANGFUSE_HTTP_TIMEOUT_SECONDS=2 CREDENTIALS_MASTER_KEY=<placeholder> D:\MultiAgentSystem\.venv\Scripts\python.exe -c "logging.basicConfig(level=INFO); serve()"
# off arm
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=1 PORT=8111 LANGFUSE_EXPORT_ENABLED=0 VALIDATOR_ALLOW_AUTO_GATES=1 LANGFUSE_BASE_URL=http://127.0.0.1:9 LANGFUSE_HTTP_TIMEOUT_SECONDS=2 CREDENTIALS_MASTER_KEY=<placeholder> D:\MultiAgentSystem\.venv\Scripts\python.exe -c "logging.basicConfig(level=INFO); serve()"
```

Servers were killed with `taskkill /PID <pid> /T /F`, never `pkill`:
on Windows `pkill` reports success while the old process keeps serving
(`docs/gotchas-and-insights.md` 25).
