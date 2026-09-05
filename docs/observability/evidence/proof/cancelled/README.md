# `cancelled` — D3, a run cancelled mid-branch (SYNTHETIC, and this file says so)

Run 2026-09-05 by V-PROOF on the **free** synthetic backend, `127.0.0.1:8099`,
`SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=8`, exporter on
(`readyz-8099.json`: `exporter: enabled`, `environment: synthetic`).
D3 permits synthetic and asks the report to say which. **This is synthetic.**
No money was spent.

| | |
| --- | --- |
| app run id | `073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba` |
| Langfuse trace id | `073c021f4ff743e184d5d9e8dd7fa0ba` |
| Langfuse session URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba |
| Langfuse trace URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/073c021f4ff743e184d5d9e8dd7fa0ba |
| launched | 16:41:08.395Z |
| cancel POST | 16:41:14.437Z — **6.0 s in**, with the research branches in flight (8 s branch delay) |
| terminal | 16:41:14.609Z, status `cancelled` |
| frames | 82 |
| observations | 28 — SPAN 15, AGENT 5, GENERATION 5, TOOL 3. **No EVENT observations** |
| scores | 7 (`run_status` `cancelled`, `run_succeeded` 0, 5x `task_attempts`) |

`cancel-response.json`: `{"status":"cancelled","effect":"stops at the next step
boundary"}`. Timing in `cancel-timing.txt`.

## D3, measured

| what D3 asks | answer | where |
| --- | --- | --- |
| the trace ends with a run-level observation whose status is `cancelled` | **yes** — run SPAN, `level: WARNING`, `statusMessage: "cancelled by operator"`, ended `16:41:14.474Z`; `trace.output = {"status":"cancelled","reason":"cancelled by operator"}` | `langfuse-observations.json`, `langfuse-traces.json` |
| **no observation left without an end time** | **0** | `open-spans.txt`: `open observations (endTime is null): 0 … observations examined: 28` |

Independently recomputed here: `sum(1 for o in obs if not o["endTime"])` = **0**,
and **0** observations have a negative duration.

`D3-cancelled-run-span.png` is the console at the trace URL above: run span
`WARNING`, `run_status: cancelled`, `run_succeeded: 0.00`, `Env: synthetic`,
output status and reason.

## A caveat that matters for reading `open-spans.txt` on OTHER runs

This run produced **no EVENT observations**, so the count is a clean 0. The
four **paid** runs each carry EVENT observations whose `endTime` is null by
construction — a Langfuse EVENT is a point in time, not a span — and
`open-spans.txt` counts them, so it reads 38 / 10 / 19 / 22 there. On those
runs every SPAN, AGENT, GENERATION and TOOL is closed; only EVENTs are
"open". `open-spans-by-type.txt` beside this file records the split for all
six runs, so nobody reads a point-in-time event as a leaked span.
