# Exporter overhead — DoD row E4

**Measured 2026-09-06 by V-RECON, who built none of this.** The question row E4
asks: *on a full synthetic run with a fixed branch delay, what is the wall-clock
delta and the per-frame handler latency (p50/p95) with the exporter on versus
off, n ≥ 3 each?*

**The answer, in one line: the exporter is not measurable in a run's wall clock
(mean delta −1.7 ms on 6.12 s runs, 95 % interval −15.5 … +12.2 ms, which
straddles zero and is smaller than either arm's own spread), and the cost it
does have is 1.5 µs at the median enqueue and 5 µs at p95, paid ~96 times per
run — bounded above by half a millisecond per run in total.** Everything the app
returned was identical across the arms: same status, same frame count, same call
count, same token total, zero drops.

n = **20 per arm** in the main pass, four times the row's minimum, plus a 5-run
extra arm with its own control, plus a **10-per-arm confirmation pass** against a
later working tree — 70 runs in all, every one `completed`.

## The tree moved while this ran, and the confirmation pass is the answer

`src/brief_crew/observability/langfuse_exporter.py` and
`src/brief_crew/service/registry.py` are **uncommitted work in progress** by
another worker, and both were edited *after* the main pass finished — the
exporter at 00:51:47 and the registry at 00:53:06, against a main pass that ran
00:41–00:46. So the main pass measured the tree as it stood at ~00:40, not the
tree as it stands now. That is stated rather than hidden, and it was answered by
measuring again: a **confirmation pass** of `on,off,off,on` × 5 was run at 00:57
against the later tree, with the three files' md5 sums recorded **before and
after** and found identical across it
(`langfuse_exporter.py 9be6db2f…`, `registry.py 3d854749…`,
`serializer.py a3dfd9e7…`; repository HEAD `7417270`, working tree dirty).

The changed hunks are all at `langfuse_exporter.py:901` and beyond — the
observation-building code on the **export thread**. `on_frames` (`:479-498`),
`SUMMARY_FORMAT` (`:188-193`) and `RunRegistry._enqueue_frames` were not in any
hunk, which is consistent with the confirmation pass reproducing the result: a
delta of −6.9 ms (95 % interval −31.2 … +17.3 ms) and p50/p95 of 0 µs / 2.5 µs.
Note that the machine itself was ~45 ms faster per run by then, in **both** arms
— which is exactly why arms are compared within a pass and never across two.

## What was run, and where it departs from the sanctioned harness

`scripts/observability/measure_overhead.py` is the E4 harness and it starts
**both** arms at once, on `--port-on` and `--port-off`, alternating runs between
them. This verification was constrained to **port 8098 only** — 8000 and 8099
were carrying another worker's paid proof runs and no second port was assigned —
so two simultaneous backends were not available. The brief allows the fallback
("restarting the backend per arm otherwise").

`e4-driver.py`, beside this file, is that fallback. **Everything that measures is
`measure_overhead.py`'s own code, imported rather than copied** —
`start_backend`, `wait_for_health`, `launch_and_wait`, `parse_exporter_lines`.
What the driver adds is scheduling: one backend at a time on 8098, arms in an
**ABBA block order** — `on, off, off, on, on, off, off, on`, five runs per block.
The on blocks sit at positions {1, 4, 5, 8} and the off blocks at {2, 3, 6, 7},
mean position 4.5 for each, so a machine that warms up or throttles across the
measurement contributes to both arms equally. That is the control the script's
run-level alternation buys, taken at block granularity, and it is the only
substantive difference.

Two consequences of the fallback, stated rather than hidden: the arms never ran
concurrently, so a transient on the machine lands in whichever block was live
rather than in both at once; and each arm paid four process starts, which is why
the boot table below is reported separately and is **not** in the per-run
figures.

## The environment, per arm

Held equal across arms: `SYNTHETIC=1` (free and deterministic),
`SYNTHETIC_BRANCH_DELAY_SECONDS=2`, `VALIDATOR_ALLOW_AUTO_GATES=1`,
`CREDENTIALS_MASTER_KEY` (the placeholder from `tests/__init__.py`, which
authenticates against nothing), `HOST=127.0.0.1`, `PORT=8098`, workflow
`idea-validator`, `gates: "auto"`, and one fixed idea string. The **only**
variable that differs between the on and off arms is
`LANGFUSE_EXPORT_ENABLED`.

| arm | `LANGFUSE_EXPORT_ENABLED` | `LANGFUSE_BASE_URL` | `/readyz` `observability` |
| --- | --- | --- | --- |
| `on` | `1` | the real project, from `.env` | `exporter: enabled`, `reason: null`, `environment: synthetic`, `capture_content: false`, `resolve_billed_cost: false` |
| `off` | `0` | same (unused) | `exporter: disabled`, `reason: "LANGFUSE_EXPORT_ENABLED is off"`, same otherwise |
| `bh` (extra) | `1` | `http://127.0.0.1:9`, a dead local port | `exporter: enabled`, `reason: null`, same otherwise |

`/readyz` was read on every block before any run of that block, so each arm's
state is **recorded, not assumed**; the per-block table at the end carries all
ten readings. The on arm exported to the real Langfuse project with
`environment=synthetic`, which the brief authorises.

## The exact commands

```text
# the measurement (40 runs: on/off, ABBA blocks of five)
.venv/Scripts/python.exe docs/observability/evidence/perf/e4-driver.py \
    --out docs/observability/evidence/perf/main \
    --port 8098 --branch-delay 2 --runs-per-block 5 \
    --blocks on,off,off,on,on,off,off,on

# the extra black-hole arm and its own off control (10 runs)
.venv/Scripts/python.exe docs/observability/evidence/perf/e4-driver.py \
    --out docs/observability/evidence/perf/blackhole \
    --port 8098 --branch-delay 2 --runs-per-block 5 \
    --blocks bh,off --bh-url http://127.0.0.1:9

# the confirmation pass against the later working tree (20 runs)
.venv/Scripts/python.exe docs/observability/evidence/perf/e4-driver.py     --out docs/observability/evidence/perf/confirm     --port 8098 --branch-delay 2 --runs-per-block 5     --blocks on,off,off,on

# every table below, regenerated from the three e4-raw.json files
.venv/Scripts/python.exe docs/observability/evidence/perf/analyse.py
```

Each block's backend, as the driver recorded it (`e4-raw.json` → `commands`):

```text
# on
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=2 PORT=8098 LANGFUSE_EXPORT_ENABLED=1 \
VALIDATOR_ALLOW_AUTO_GATES=1 CREDENTIALS_MASTER_KEY=<placeholder> \
D:\MultiAgentSystem\.venv\Scripts\python.exe -c "logging.basicConfig(level=INFO); serve()"

# off
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=2 PORT=8098 LANGFUSE_EXPORT_ENABLED=0 \
VALIDATOR_ALLOW_AUTO_GATES=1 CREDENTIALS_MASTER_KEY=<placeholder> \
D:\MultiAgentSystem\.venv\Scripts\python.exe -c "logging.basicConfig(level=INFO); serve()"

# bh (extra) — the bootstrap differs; see finding 2 near the end of this file
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=2 PORT=8098 LANGFUSE_EXPORT_ENABLED=1 \
VALIDATOR_ALLOW_AUTO_GATES=1 CREDENTIALS_MASTER_KEY=<placeholder> \
D:\MultiAgentSystem\.venv\Scripts\python.exe -c "basicConfig(INFO); import brief_crew; \
os.environ['LANGFUSE_BASE_URL']='http://127.0.0.1:9'; from brief_crew.service.app import serve; serve()"
```

The `python -c "logging.basicConfig(level=INFO); serve()"` launcher is the
harness's own, and it is load-bearing: nothing in `src/brief_crew/` configures
logging, so under a bare `serve.exe` a `brief_crew.*` record reaches a root
logger with no handler. Every backend was killed by PID with
`taskkill /PID <pid> /T /F`, never `pkill` and never `Stop-Process -Name serve`.
Port 8098 was the only port bound; 8000 and 8093 were listening throughout under
other workers' PIDs and were confirmed unchanged, by PID, before and after.

---

## Per arm, wall clock launch -> terminal status (client side, ms)

| arm | n | mean | median | min | max | stdev |
| --- | --- | --- | --- | --- | --- | --- |
| on | 20 | 6124.1 | 6124.0 | 6092.2 | 6156.0 | 14.9 |
| off | 20 | 6125.7 | 6118.9 | 6070.6 | 6177.5 | 27.8 |
| bh (extra) | 5 | 6106.5 | 6116.5 | 6078.0 | 6123.5 | 19.5 |
| off, bh session control | 5 | 6117.0 | 6118.9 | 6062.4 | 6150.5 | 35.8 |

## The delta

| quantity | value |
| --- | --- |
| mean(on) - mean(off) | -1.66 ms (-0.027 % of the off mean) |
| median(on) - median(off) | +5.12 ms (+0.084 %) |
| standard error of that delta | 7.06 ms |
| Welch t / df | -0.24 / 29.1 |
| 95 % interval on the mean delta | -15.50 .. +12.17 ms |
| stdev of the on arm / the off arm | 14.9 ms / 27.8 ms |

Extra arm: mean(bh) - mean(off control) = -10.48 ms (SE 18.25 ms, Welch t = -0.57).

## The exporter's own counters, per run (from the summary line)

| arm | summary lines | frames_enqueued | frames_dropped | observations_sent | http_errors | enqueue p50 us, median (range) | enqueue p95 us, median (range) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| on | 20/20 | 96-97 | 0 | 41-41 | 0 | 1.5 (0-3) | 5 (2-12) |
| bh (extra) | 3/5 | 96-97 | 0 | 41-41 | 20 | 2 (1-2) | 7 (3-10) |

## What the app did, per arm - the E2 half of this measurement

| arm | runs | status | app frames | app frames dropped | calls | tokens |
| --- | --- | --- | --- | --- | --- | --- |
| on | 20 | completed | 96-97 | 0 | 6 | 4337 |
| off | 20 | completed | 96-97 | 0 | 6 | 4337 |
| bh (extra) | 5 | completed | 96-97 | 0 | 6 | 4337 |
| off control | 5 | completed | 96-97 | 0 | 6 | 4337 |

## Every run

| set | arm | block | # | run_id | status | wall ms | app frames | enqueued | dropped | sent | http_err | p50 us | p95 us |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| main | on | 1 | 1 | 347ffecc-96cc-4bca-b979-bb28977f4c68 | completed | 6138.4 | 96 | 96 | 0 | 41 | 0 | 2 | 7 |
| main | on | 1 | 2 | 798c4f4b-8a4e-4c9d-8fb9-f1d33ae60741 | completed | 6126.8 | 96 | 96 | 0 | 41 | 0 | 0 | 4 |
| main | on | 1 | 3 | b3a3036b-d9a7-4902-9d90-132ec55c2ebc | completed | 6121.1 | 97 | 97 | 0 | 41 | 0 | 0 | 5 |
| main | on | 1 | 4 | 2925dbec-f4cf-4906-8184-a52242c7206d | completed | 6092.2 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 1 | 5 | 6dd5692f-79f8-48e9-9ac5-72f5eec3e66f | completed | 6133.6 | 97 | 97 | 0 | 41 | 0 | 2 | 5 |
| main | off | 2 | 1 | ba5fa675-6e24-4573-8b57-04edf3bfad62 | completed | 6171.1 | 96 | - | - | - | - | not found | not found |
| main | off | 2 | 2 | 9c18f493-4180-4273-b339-600e9f922285 | completed | 6114.9 | 96 | - | - | - | - | not found | not found |
| main | off | 2 | 3 | fa4e28ac-3070-4a17-a5a5-d87015fc48b3 | completed | 6137.9 | 97 | - | - | - | - | not found | not found |
| main | off | 2 | 4 | 72aa470e-2c50-4ca7-9004-f4580429619f | completed | 6108.5 | 96 | - | - | - | - | not found | not found |
| main | off | 2 | 5 | 028dcd2e-071a-490c-8a90-01754eb0d592 | completed | 6088.9 | 97 | - | - | - | - | not found | not found |
| main | off | 3 | 1 | 61828dc4-d428-4f8c-b732-34f97f11f3ca | completed | 6177.5 | 96 | - | - | - | - | not found | not found |
| main | off | 3 | 2 | 0a1c339f-debe-4bc2-a864-422268ba1690 | completed | 6116.9 | 96 | - | - | - | - | not found | not found |
| main | off | 3 | 3 | 144c491a-937a-4de9-9d59-c17ca1a8d7e5 | completed | 6070.6 | 97 | - | - | - | - | not found | not found |
| main | off | 3 | 4 | 59eaf720-40c9-4c18-b565-b44158aaa2fa | completed | 6130.6 | 96 | - | - | - | - | not found | not found |
| main | off | 3 | 5 | f1bc6fa1-fc5a-4222-9947-4255f56ed4e0 | completed | 6140.7 | 97 | - | - | - | - | not found | not found |
| main | on | 4 | 1 | f0a295f0-0342-4c46-8221-f855886f23b0 | completed | 6156.0 | 96 | 96 | 0 | 41 | 0 | 1 | 6 |
| main | on | 4 | 2 | 0e81928d-5b6a-479b-b3b0-c12e55989702 | completed | 6118.0 | 96 | 96 | 0 | 41 | 0 | 2 | 5 |
| main | on | 4 | 3 | 064d0420-9cb3-41ce-a90a-9e19a7ea44ea | completed | 6137.0 | 97 | 97 | 0 | 41 | 0 | 2 | 5 |
| main | on | 4 | 4 | 6fb3413c-99c0-4473-b070-968751b62431 | completed | 6134.9 | 96 | 96 | 0 | 41 | 0 | 3 | 8 |
| main | on | 4 | 5 | 592afd43-6dd8-4496-8fc2-6ad2cc3ff9dd | completed | 6117.2 | 97 | 97 | 0 | 41 | 0 | 2 | 7 |
| main | on | 5 | 1 | 6ff0ddff-61fb-4ef6-af61-228c69c2bb8f | completed | 6097.9 | 96 | 96 | 0 | 41 | 0 | 1 | 2 |
| main | on | 5 | 2 | f51ba6c1-f82e-4bb8-b191-a1fe4bc28cc3 | completed | 6139.4 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 5 | 3 | cf045557-3113-41c1-a17d-f1f17750d7de | completed | 6116.3 | 97 | 97 | 0 | 41 | 0 | 1 | 5 |
| main | on | 5 | 4 | 83513496-e4c6-4765-8bd1-71184d8be747 | completed | 6115.3 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 5 | 5 | 3fb44755-f608-4210-8400-e518887edb84 | completed | 6121.8 | 97 | 97 | 0 | 41 | 0 | 0 | 2 |
| main | off | 6 | 1 | 06adb60c-3fa4-4726-a69c-7110fa4dbb2d | completed | 6163.3 | 96 | - | - | - | - | not found | not found |
| main | off | 6 | 2 | 7b55e756-02d7-44d4-8970-aa29431ff798 | completed | 6115.3 | 96 | - | - | - | - | not found | not found |
| main | off | 6 | 3 | cbc39284-14ac-4d30-8a12-8a20a83cc412 | completed | 6131.8 | 97 | - | - | - | - | not found | not found |
| main | off | 6 | 4 | 6e0ab1fd-7e62-4600-b7b7-1dc4218daf7a | completed | 6137.1 | 96 | - | - | - | - | not found | not found |
| main | off | 6 | 5 | a5a735e1-122f-41fd-bb59-b0f10fe5b607 | completed | 6108.4 | 97 | - | - | - | - | not found | not found |
| main | off | 7 | 1 | c034d8c4-ffb5-475b-943e-be2fc962b65f | completed | 6161.7 | 96 | - | - | - | - | not found | not found |
| main | off | 7 | 2 | 096434fe-5367-4893-bac4-9ee50018533b | completed | 6118.3 | 96 | - | - | - | - | not found | not found |
| main | off | 7 | 3 | af38e9ca-553d-40fd-9c04-d5495a94c47b | completed | 6095.9 | 97 | - | - | - | - | not found | not found |
| main | off | 7 | 4 | bb268de9-9dac-4b7a-83e1-16bf5cd36ed2 | completed | 6119.5 | 96 | - | - | - | - | not found | not found |
| main | off | 7 | 5 | e1aa348f-5e75-4ceb-bfbc-728df3f2a571 | completed | 6105.8 | 97 | - | - | - | - | not found | not found |
| main | on | 8 | 1 | 7ce96766-0f03-460f-bc79-7e51c91fb8a9 | completed | 6134.8 | 96 | 96 | 0 | 41 | 0 | 1 | 5 |
| main | on | 8 | 2 | 456a84bc-75c7-4d67-a73b-b25cd13fb3e3 | completed | 6126.2 | 96 | 96 | 0 | 41 | 0 | 2 | 5 |
| main | on | 8 | 3 | b2686d21-5674-405d-bef8-31737c60ce8e | completed | 6130.6 | 97 | 97 | 0 | 41 | 0 | 3 | 12 |
| main | on | 8 | 4 | 31c339b4-d887-4399-80db-13e8207f463b | completed | 6115.5 | 96 | 96 | 0 | 41 | 0 | 2 | 7 |
| main | on | 8 | 5 | 2b22e3e0-eb5c-4997-a6ab-092d32b8c30f | completed | 6108.8 | 97 | 97 | 0 | 41 | 0 | 2 | 7 |
| blackhole | bh | 1 | 1 | 8a28d64c-c216-40a5-9b91-0789a279183e | completed | 6123.5 | 96 | 96 | 0 | 41 | 6 | 2 | 7 |
| blackhole | bh | 1 | 2 | 1f84825e-6bcd-46b2-8271-75ff01198a14 | completed | 6094.7 | 96 | 96 | 0 | 41 | 8 | 1 | 10 |
| blackhole | bh | 1 | 3 | 10274c2f-0fbf-4dc2-bc09-0d9c0806ad4a | completed | 6116.5 | 97 | 97 | 0 | 41 | 6 | 2 | 3 |
| blackhole | bh | 1 | 4 | 196bcad5-2331-4ecb-8251-736038b65745 | completed | 6119.9 | 96 | - | - | - | - | not found | not found |
| blackhole | bh | 1 | 5 | 4476d6cb-b4bf-40e9-a77d-8ebbf15df9ac | completed | 6078.0 | 97 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 1 | 4781791e-3c8a-4440-a4a2-18e88c0d8bfe | completed | 6147.1 | 96 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 2 | 6d51aa74-cfe0-4ae7-8ecd-96a4584fee7f | completed | 6062.4 | 96 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 3 | fec7ae54-9a85-4bc9-99ab-167c346e4d13 | completed | 6106.1 | 97 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 4 | 7d7bcdf9-77a3-4edc-9a87-70553d900d21 | completed | 6150.5 | 96 | - | - | - | - | not found | not found |
| blackhole | off | 2 | 5 | 08573c9a-b7df-4dec-8e5c-247647ca3dba | completed | 6118.9 | 97 | - | - | - | - | not found | not found |

## Confirmation pass, re-run against a later working tree

| arm | n | mean | median | min | max | stdev |
| --- | --- | --- | --- | --- | --- | --- |
| on | 10 | 6077.3 | 6069.1 | 6052.4 | 6133.3 | 25.1 |
| off | 10 | 6084.2 | 6077.8 | 6052.0 | 6153.3 | 30.0 |

mean(on) - mean(off) = -6.93 ms (-0.114 %), SE 12.36 ms, Welch t = -0.56, 95 % interval -31.16 .. +17.30 ms.

Enqueue latency, on arm: p50 median 0 us (range 0-1), p95 median 2.5 us (range 1-6), from 10/10 summary lines. Statuses: completed; app frames dropped 0.

## Process boot, per block (not per run - a one-off cost)

| block | arm | boot s | /readyz exporter | reason | environment | capture_content |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | on | 3.63 | enabled | - | synthetic | False |
| 2 | off | 3.08 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 3 | off | 3.08 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 4 | on | 3.61 | enabled | - | synthetic | False |
| 5 | on | 3.62 | enabled | - | synthetic | False |
| 6 | off | 3.10 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 7 | off | 3.12 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 8 | on | 3.63 | enabled | - | synthetic | False |
| 1 | bh | 3.66 | enabled | - | synthetic | False |
| 2 | off | 3.09 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 1 | on (confirm) | 3.67 | enabled | - | synthetic | False |
| 2 | off (confirm) | 3.11 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 3 | off (confirm) | 3.09 | disabled | LANGFUSE_EXPORT_ENABLED is off | synthetic | False |
| 4 | on (confirm) | 3.59 | enabled | - | synthetic | False |

Boot, on arm mean 3.62 s; off arm mean 3.10 s; difference +526 ms, paid once per process.
---

## Reading it: where the cost actually sits

**The exporter's cost is on the capture path only as a queue put, and everything
expensive is on its own thread.** That is not an inference from the numbers; it
is what the code does, and the numbers agree with it.

`RunRegistry._enqueue_frames` calls `frame_observer.on_frames(...)`
**synchronously, on the capture thread, while the adapter's non-reentrant
`_capture_lock` is held** (`service/registry.py:3114-3129`, and the attribute's
own comment at `:1469` — *"an observer that does anything but enqueue is a defect
in the observer"*). The capture thread is whichever thread raised the CrewAI
event, i.e. the run's own worker thread. **So the enqueue is genuinely on the
run's critical path**, and it is inside a lock that the three concurrent research
branches contend for. That is the pessimistic reading, and it is the right one.

What is on that path is small by construction: `on_frames`
(`observability/langfuse_exporter.py:479-498`) is two `perf_counter_ns` calls, a
`put_nowait` on a 4096-slot bounded queue, and a deque append. No lock of its
own, no I/O. **Measured: 1.5 µs median, 5 µs p95** (medians across the 20 ON
runs' own per-run percentiles). A run emits 96–97 frames, and the adapter calls
`on_frames` at most once per frame, so the whole capture-path cost of the
exporter is bounded above by **96 × 5 µs ≈ 0.48 ms per run**, and sits nearer
**0.14 ms** at the median — against a 6 124 ms run, 0.002 % to 0.008 %. It is
three orders of magnitude below the run-to-run noise, which is why the wall-clock
delta comes back as −1.7 ms with an interval straddling zero: **the wall clock
cannot see the exporter, and this measurement is a bound on how large its effect
could have been, not a detection of it.**

Everything else — turning frames into observations, the OTLP HTTP, the batch
processor — runs on the exporter's own daemon thread, fed by that queue. **The
extra `bh` arm is the direct evidence that the export half is off the run's
path**: with `LANGFUSE_BASE_URL` at a dead local port, every export attempt fails
through a retry cycle taking seconds (the log carries `WinError 10061 … actively
refused it`, `Failed to export span batch`, 6–8 `http_errors` per run), and the
runs are **the same length as their off control** (−10.5 ms, SE 18.3 ms) with
every one completing at 96–97 frames, 0 dropped and identical calls and tokens.
A busy, failing export thread does not lengthen a run.

**One cost that is real and is not per run: process boot.** The ON arm's backend
took 3.62 s to answer `/healthz` against the OFF arm's 3.10 s — **+526 ms, four
starts each, consistently** — which is the Langfuse SDK import plus client
construction. It is paid once per process, so it is invisible in a per-run
figure and would be visible on a cold Render start.

## What this measurement can and cannot show

**It cannot be read as "the exporter costs 0.008 % of a run", and the direction
of the error is worth being precise about.** These are `SYNTHETIC=1` runs: the
six "model calls" and 4 337 tokens are fabricated by the double and return
instantly, so a run's 6.12 s is essentially `SYNTHETIC_BRANCH_DELAY_SECONDS=2`
plus orchestration. The exporter's work, by contrast, is driven by **frames**,
not by seconds. So:

- **The ratio overstates the relative cost against a real run.** A paid run of
  this flow has a wall clock measured in minutes rather than six seconds, and the
  same handful of microseconds per frame lands against a denominator tens of
  times larger. Whatever percentage a paid run pays, it is smaller than this one.
- **The absolute cost would rise, and the ratio still would not.** A paid run
  emits *more* frames than a synthetic one — streaming chunk frames, real tool
  calls, real guardrail retries — so the number of enqueues goes up. It would
  take **a thousand frames in one run** for the capture-path total to reach 5 ms
  at the measured p95 (5 ms / 5 us), and the app's own frame ring holds 2 000.
- **What is genuinely unmeasured on a paid run is the export thread's
  competition for CPU and the GIL** while a run is doing real work. Nothing here
  can see that; the `bh` arm is the closest available proxy and shows no effect,
  but it is a proxy.

Four things this deliberately does not answer, each belonging to a row that is
not E4:

1. **Queue saturation.** `LANGFUSE_QUEUE_CAPACITY` is 4 096 and a run enqueued
   96 frames, one run at a time. `frames_dropped` was **0 on all 33 summary
   lines**, and the app's own `frames.dropped` was 0 on all **70** runs; the
   drop-oldest path was never approached. A concurrent or high-frame-rate load is
   untested here (rows A2/D5).
2. **A slow host.** A dead local port refuses the connection **immediately**;
   a host that accepts and then stalls is a different failure mode with a
   different cost, and it is E2's second condition, which is V-REVIEW's row and a
   test rather than a measurement. This arm is labelled *extra* for that reason.
3. **Content capture on.** `capture_content` was `false` in every arm, the
   documented default. With `LANGFUSE_CAPTURE_CONTENT=1` the payloads and the
   redaction work are larger; unmeasured.
4. **Billed-cost resolution.** `resolve_billed_cost` was `false` throughout —
   `lookup_ok` and `lookup_failed` are 0 on every line — so the generation-lookup
   path contributed nothing to any figure above.

## Three things found in the harness while running it

All three are proved in `raw-harness-findings.txt` rather than asserted, and none
of them changes the result above. They belong to whoever owns
`scripts/observability/`.

1. **`measure_overhead.py`'s own counter table would print zeros over a healthy
   log.** Its `main()` sums the keys `enqueued`, `sent` and `dropped`; the
   exporter's line spells them `frames_enqueued`, `observations_sent` and
   `frames_dropped` (`langfuse_exporter.py:188-193`, whose comment records the
   rename and why). Run over this measurement's own `server-on-b1.log`, the
   script's summariser answers `enqueued=0 sent=0 dropped=0` for five lines
   carrying **482, 205 and 0**. `enqueue_p50_us` / `enqueue_p95_us` match and are
   unaffected, so the E4 latency half is safe — but a reader of that table would
   be told the exporter enqueued nothing. The tables here parse the field names
   the exporter actually emits.
2. **`--env LANGFUSE_BASE_URL=…` does not reach the app**, which is exactly the
   use the harness README recommends it for ("point `LANGFUSE_BASE_URL` at a
   black-hole port"). `brief_crew/__init__.py:56` calls
   `load_dotenv(_ENV_PATH, override=True)`, so any variable also present in
   `.env` is overwritten at import, after the child inherits it. Proved:
   inject `http://127.0.0.1:9`, and `config.LANGFUSE_BASE_URL == injected` is
   `False`. **This does not touch the main result** — `LANGFUSE_EXPORT_ENABLED`
   is not in `.env`, so the arms' own switch survives, and `/readyz` confirmed
   each arm's state independently. `e4-driver.py`'s `bh` arm works around it by
   importing `brief_crew` first and setting the variable second, and asserts the
   outcome by reading `/readyz` and the connection-refused errors in the log.
3. **With Langfuse unreachable the summary line lags the run.** Three of the five
   `bh` runs logged one before the process was killed three seconds after the
   last run; the trace close queues behind the OTLP retry cycle. All five runs
   **completed** — this is a reporting lag, not a run defect — but a `bh` log is
   expected to be short of summary lines, and a harness that killed faster would
   see fewer still.

A fourth, smaller: `enqueue_p50_us` is integer-truncated from nanoseconds
(`_percentile(...) // 1000`), so the `0` printed by five of the twenty ON runs
means **under one microsecond**, not zero. No figure here reports it as zero.

## The files

| file | what it is |
| --- | --- |
| `overhead.md` | this document — the E4 artifact |
| `VERDICT.md` | the row's verdict |
| `e4-driver.py` | the scheduler; imports `measure_overhead.py`'s measuring code |
| `analyse.py` | regenerates every table above from the three raw JSON files |
| `tables.md` | `analyse.py`'s output, verbatim; identical to the tables above |
| `raw-stats.txt` | the same, as captured from the command |
| `raw-summary-lines.txt` | all 33 `langfuse-exporter` summary lines, verbatim |
| `raw-harness-findings.txt` | the harness findings, with the commands that proved them |
| `raw-secret-scan.txt` | `scripts/observability/secret_scan.py` over this directory: 26 text files, 0 values, 0 prefixes, PASS |
| `main/e4-raw.json` | every run of the 40, with its exporter line attached |
| `confirm/e4-raw.json`, `confirm/server-*.log` | the 20-run confirmation pass against the later working tree |
| `main/server-{on,off}-b*.log` | the eight backends' captured stdout/stderr |
| `blackhole/e4-raw.json`, `blackhole/server-*.log` | the extra arm and its control |

No file in this directory contains a credential value. That is not an assertion:
`scripts/observability/secret_scan.py --paths docs/observability/evidence/perf`
loaded 11 credential values from `.env` into memory, scanned all 26 text files
for them and for the DoD's key prefixes, and answered **0 and 0, VERDICT: PASS**
(`raw-secret-scan.txt`). No proof above prints a `.env` value either - finding 2
reports a boolean rather than the URL it compared.
