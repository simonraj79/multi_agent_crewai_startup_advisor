# E4 — verdict

**Row E4:** *Overhead measured. On a full synthetic run with a fixed branch
delay, what is the wall-clock delta and the per-frame handler latency (p50/p95)
with the exporter on versus off, n ≥ 3 each?*
**Evidence the row names:** `evidence/perf/overhead.md` with the raw numbers and
the command.
**Verifier:** V-RECON, who built none of this.
**Measured:** 2026-09-06, this machine, port 8098 only.

## E4 → **PASS**

Both halves of the question are answered, on more than four times the runs the
row asks for, and the artifact the row names exists with the raw numbers and the
commands in it.

| the question | the answer |
| --- | --- |
| n per arm | **20 on, 20 off** in the main pass (row asks ≥ 3), a 5-run extra arm with its own 5-run control, and a **10 on / 10 off confirmation pass** against a later working tree — **70 runs, all 70 `completed`** |
| the run measured | `idea-validator`, `gates: "auto"`, `SYNTHETIC=1`, `SYNTHETIC_BRANCH_DELAY_SECONDS=2`, one fixed idea, held equal across arms |
| wall clock, exporter ON | mean **6 124.1 ms**, median 6 124.0, sd 14.9, range 6 092.2–6 156.0 |
| wall clock, exporter OFF | mean **6 125.7 ms**, median 6 118.9, sd 27.8, range 6 070.6–6 177.5 |
| **wall-clock delta (on − off)** | **−1.66 ms on the means (−0.027 %)**, +5.12 ms on the medians (+0.084 %); SE 7.06 ms, Welch t = −0.24, 95 % interval **−15.50 … +12.17 ms** |
| **per-frame handler latency** | **p50 = 1.5 µs** (per-run p50s ranged 0–3), **p95 = 5 µs** (ranged 2–12), from the exporter's own summary line, present on **20 of 20** ON runs |
| exporter counters, ON arm | 96–97 `frames_enqueued` per run, **0** `frames_dropped`, 41 `observations_sent`, **0** `http_errors`, 0 lookups |
| the app's own behaviour | identical in both arms: `completed`, 96–97 frames, **0** frames dropped, 6 calls, 4 337 tokens — and **0** frames dropped across all 70 runs and all 33 summary lines |
| **confirmation pass** (later tree) | on 6 077.3 ms vs off 6 084.2 ms, delta **−6.93 ms (−0.114 %)**, 95 % interval −31.16 … +17.30 ms; p50 **0 µs**, p95 **2.5 µs**, 10/10 summary lines |

**The delta straddles zero and is smaller than either arm's own run-to-run
spread, so it is a bound rather than a detection**: the exporter's effect on a
run's wall clock is under ~15 ms on a 6.1 s run, and the mechanism says why — the
capture path pays one `put_nowait` per frame at 1.5 µs median, at most 96 times,
so at most ~0.48 ms per run even if every enqueue were at p95. Everything
expensive is on the exporter's own thread.

## What a reader must not take from this PASS

Stated in full in `overhead.md`; the four that matter most:

1. **The percentage overstates the cost against a paid run, not understates it.**
   A synthetic run's model calls return instantly, so the 6.1 s denominator is
   small while the exporter's work — which is driven by frames, not seconds — is
   the same order as a real run's. A paid run emits *more* frames and lasts far
   longer; the absolute enqueue cost rises, the ratio falls.
2. **Two arms, not two backends.** Port 8098 was the only port available, so the
   arms ran as ABBA blocks of five on one port rather than as
   `measure_overhead.py`'s interleaved runs on two ports. The measuring code is
   that script's own, imported; only the scheduling differs. If the orchestrator
   wants the sanctioned two-port form, it is one re-run with two ports.
3. **This is one machine, one flow, one concurrency of one.** Queue saturation, a
   *slow* (rather than dead) Langfuse, content capture on, and billed-cost
   resolution are all unmeasured, and each belongs to a different row.
4. **The code measured is uncommitted work in progress, and it moved.**
   `langfuse_exporter.py` and `registry.py` were edited by another worker
   *after* the main pass (00:51 and 00:53, against a pass that ran 00:41–00:46).
   That is why the confirmation pass exists: it was run at 00:57 with the three
   files' md5 sums recorded before and after and found identical across it, and
   it reproduces the result. Repository HEAD `7417270`, working tree dirty. If
   the exporter's hot path (`on_frames`) or `RunRegistry._enqueue_frames` changes
   before the merge, this row should be re-run — the changed hunks measured here
   were all on the export thread, not on the capture path.

## Findings handed on, none of which changes the verdict

1. **`scripts/observability/measure_overhead.py` would report the ON arm's
   enqueued/sent/dropped as `0/0/0`.** It sums `enqueued`, `sent`, `dropped`; the
   exporter's line spells them `frames_enqueued`, `observations_sent`,
   `frames_dropped`. Proved over this measurement's own log: 482, 205 and 0
   reported as 0, 0 and 0. The p50/p95 keys match, so **E4's latency half is not
   affected** — but the harness's own counter table currently lies about a
   healthy exporter. For the script's owner.
2. **`measure_overhead.py --env LANGFUSE_BASE_URL=…` is inert**, which is the one
   use its README recommends the flag for: `brief_crew/__init__.py` calls
   `load_dotenv(override=True)`, so a variable also in `.env` is overwritten at
   import. `LANGFUSE_EXPORT_ENABLED` is not in `.env`, so the arms of this
   measurement were unaffected and `/readyz` confirmed each arm independently.
3. **With Langfuse unreachable, the per-run summary line lags** behind the OTLP
   retry cycle: 3 of 5 black-hole runs logged one before shutdown. All five runs
   completed; this is a reporting lag, not a run defect.
4. `enqueue_p50_us` is integer-truncated from nanoseconds, so a printed `0` means
   **under 1 µs**. Five ON runs printed it; no figure here calls it zero.

## Incidental corroboration for other rows — not verdicts, those rows are not mine

- **E2 (V-REVIEW's row, the "misconfigured" condition).** 5 runs with
  `LANGFUSE_BASE_URL` at a dead local port: all `completed`, 96–97 frames, 0
  dropped, same calls and tokens, wall clock indistinguishable from the control
  (−10.5 ms, SE 18.3), the failure logged by the exporter and never surfaced as a
  run error. That is consistent with E2 for that one condition; the row asks for
  a committed test, and this is a measurement.
- **F3 (V-REVIEW's row).** `scripts/observability/secret_scan.py --paths
  docs/observability/evidence/perf` over this directory: 26 text files, **0**
  credential values, **0** credential-shaped prefixes, `VERDICT: PASS`
  (`raw-secret-scan.txt`). That is this directory only; the row is over the whole
  tree and the diff, and remains V-REVIEW's.

## Housekeeping

Port 8098 only. 8000 and 8093 were listening under other workers' PIDs before
this began and were confirmed listening under the **same PIDs** afterwards;
nothing was killed that this verification did not start. Every backend was
stopped by PID with `taskkill /PID <pid> /T /F`. No `pkill`, no
`Stop-Process -Name serve`. Nothing under `src/`, `tests/`, `scripts/` or
`frontend/` was edited; every file written by this verification is under
`docs/observability/evidence/perf/`.
