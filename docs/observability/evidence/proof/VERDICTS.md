# V-PROOF's verdicts — the ten DoD rows this verifier owns

Signed **2026-09-06** by **V-PROOF**, an Opus 5 verifier who built none of this
code and edited none of it. Every row is settled by a file under
`docs/observability/evidence/proof/`, named in its sentence. Nothing here rests
on a screenshot alone; every screenshot has the JSON beside it.

### Which pass each row rests on

Three passes of paid runs were made, against three commits. A row is scored on
the **latest pass that measured it**, and its verdict cell says which.

| pass | commit | directories | what it settled |
| --- | --- | --- | --- |
| 1 | `e68dac4` | `validator-live`, `brief-live`, `builder-toolfail`, `builder-agentfail`, `cancelled`, `capture-on`, `concurrent` | A1 (all three flow kinds), A3, B5's capture half, B6, C2, D3 — and it found the billed-cost defect |
| 2 | `c608953` | `*-2`, `concurrent`(unchanged) | billed cost fixed; B3/D1 re-proved and still short; found the `fc-` scrub |
| 3 | `58a1c0b` | `*-3`, `concurrent-3` | B3/D1 met, D2 re-proved with classes, A2/D5 re-measured clean, the `fc-` scrub closed |

> **Pass-1 qualifications, still true of the pass-1 directories.** The synthetic
> runner carried `7417270`'s then-uncommitted change (so it is in `cancelled` and
> `capture-on` only), and `ad6a696` landed 18 minutes after the last pass-1 run
> and was measured by nothing in it. `RUNS.md` carries both.

Rows A2, B1, B2, B4, E1 and E5 are **V-RECON's**; A2/D5 is scored below only
because the orchestrator asked for a clean concurrent pair after the `fc-` fix,
and the number quoted is `membership_check.py`'s own. The raw pulls V-RECON needs
are in place for every run: `app-run.json`, `app-frames.ndjson`, `app-figures.*`,
`langfuse-{session,traces,observations,scores}.json`, `langfuse-figures.*`,
`per-agent.md`, `per-task.md`, `durations.md`, `hierarchy.txt`, `open-spans.txt`
and `openrouter-{generations,figures}.json`, plus
`concurrent/` and `concurrent-3/membership-check.{txt,json}`.

| row | verdict | the one sentence, naming the file and field |
| --- | --- | --- |
| **A1** | **PASS** *(pass 1 for the three flow kinds; re-confirmed pass 3)* | `langfuse-session.json.id` equals the app run id verbatim for all **three** flow kinds — `idea-validator` (`validator-live`, `f4c8c779-…`), `brief-flow` (`brief-live`, `6586c854-…`) and a builder-authored graph (`builder-toolfail`, `9becf713-…`, plus `builder-agentfail`, `ca13fc73-…`) — one session per run, each trace id equal to `UUID(run_id).hex`. `validator-live-3/A1-sessions-list.png` shows **all ten** paid sessions across the three passes, every id equal to its run id, every one `proof-runner`, one trace each. |
| **A2 / D5** | **PASS** *(pass 3; V-RECON's row, scored here only because a clean pair was asked for)* | `concurrent-3/membership-check.txt`: `sessions=2 traces=2 observations=102 mismatches=0 cross-membership=0 no-run_id=0 VERDICT=PASS`, over `validator-live-3` and `builder-toolfail-3` launched **5 ms** apart (`concurrent-3/launch-times.txt`) on a backend with `executor.workers: 2`. Re-measured on `58a1c0b` because pass 2 found the exporter scrubbing a run id containing `fc-` to `…-b5***` — the exact field this check compares. The pass-1 pair also read 0/0/0 over 97 observations (`concurrent/`). |
| **A3** | **PASS** *(pass 1, unchanged)* | From `langfuse-traces.json` alone: `name` says WHICH flow (`idea-validator` / `brief-flow` / `ug_4e7e952f` / `ug_fd12e0a6`), `userId` says WHO (`proof-runner` on all ten paid runs), `environment` = `live` and `metadata.gates` = `auto` say in WHAT mode, and the run SPAN's `startTime`/`endTime` plus `output = {"status": …, "reason": …}` say WHEN and with WHAT terminal status — `completed`, `failed` and `cancelled` all exercised; screenshot `validator-live/A3-run-level.png`. Pass 3 adds `error_class` to that `output`. |
| **B3** | **PASS** *(pass 3 at `58a1c0b`; PARTIAL in passes 1 and 2)* | On `builder-agentfail-3` the failure is on the specific agent's and task's observations at `level=ERROR` — AGENT `Channel Sounder` `a9ba1f503291bff6`, task SPAN `e7f16220a4378c14` — **each carrying `metadata.error_class: "BadRequestError"` and a `statusMessage` beginning `BadRequestError: Error code: 400 …`**, as do the node SPAN `58373c3b1d66f048` and the run SPAN `7ffeb0323f815b05`; `trace.output.error_class` is `"BadRequestError"`, and the run-level observation ends `failed` rather than the trace merely stopping (`builder-agentfail-3/B3-failure.png`). Every span still ends on its own closing frame — agent/task `18:16:04.701Z` (`AGENT_CALL`), node `.718Z` (`NODE_END`), run `.721Z` (`WORKFLOW_END`) — so the held-close mechanism did not flatten the timeline. |
| **B5** | **PASS** *(re-judged against the revised §4)* | Default policy on `validator-live`: all 10 generations carry `prompt_fingerprint_basis = "messages"` with **10 distinct** fingerprints, `message_count`, `prompt_chars`, `completion_chars`, `attempt`, `finish_reason`, `model`, `agent_role` (0 missing) and `task_name` (the one null is a `Guardrail Agent` call, declared in `null_fields`), with `input` and `output` **null on all ten**; and under `LANGFUSE_CAPTURE_CONTENT=1` the planted `MARKER-QUILTED-SEXTANT` appears 18 times across `capture-on/langfuse-observations.json` while the planted `sk-or-v1-0…0` appears **0** times (rendered `***`), with `output` non-null on all six generations, the trace input captured and every tool payload captured. §4 now states that a generation's `input` is **absent under every policy by decision** — prompt content never enters the frame pipeline — so the one thing pass 1 marked short is no longer a shortfall, and the capture half is judged on `output`, tool payloads and the trace input, all of which are present and redacted. `validator-live-2` additionally shows the same fields on 12 of 12 generations. |
| **B6** | **PASS** | `validator-live/langfuse-scores.json` carries 14 generic scores — `run_succeeded` 1 and `run_status` `completed` on the trace, `task_attempts` and **`guardrail_passed`** on each of the six task SPANs — with `run_succeeded` 0 / `run_status` `failed` on both builder runs and `cancelled` on the cancelled one, and the Scores surface is non-empty with a count-over-time chart (`validator-live/B6-scores.png`, `B6-scores-project-surface.png`). This is the first evidence of `guardrail_passed` anywhere: the synthetic double emits no guardrail frames. |
| **C2** | **PASS** | All three strings invented for Task 3 appear **verbatim as observation names** in `builder-toolfail/langfuse-observations.json` — AGENT `Tidewater Cartographer` (`a6280bb92209fb0a`), node SPAN `chart_the_shoals` (`789867469c2df048`) and TOOL `sounding_line_lookup` (`ac336998a8cb5c64`, the author-named custom HTTP tool) — the raising library tool's own id `read_website_content` appears verbatim too (`0eb0d52dff1e8883`), and `builder-toolfail/absent-before.txt` records `git grep` answering **no match** for every one of them over the whole tree at the pre-Task-3 commit `b65bd65`; screenshot `C2-invented-names.png`. |
| **D1** | **PASS** *(pass 3 at `58a1c0b`; PARTIAL in passes 1 and 2)* | Same artifact and same reading as B3, on `builder-agentfail-3`: the failing agent, task, node and run observations are all `level=ERROR`, all four name `BadRequestError` in both `metadata.error_class` and the `statusMessage`, and the run ends `failed`. `builder-agentfail-3/README.md` carries the endTime-to-frame table. |
| **D2** | **PASS** *(pass 1; re-proved and strengthened pass 3)* | On `builder-toolfail-3`, TOOL `read_website_content` `ab6378130d772e46` carries `level=ERROR`, `statusMessage` naming `ValueError` and **`metadata.error_class: "ValueError"`**, nested under AGENT `Tidewater Cartographer` `7c527ecb44053432`, and the agent's subsequent behaviour is legible after it — `AGENT_CALL` at ERROR then `NODE_END` at ERROR, i.e. it **gave up**, matching `retry.max_retries = 0` / `on_error: "fail"`. The chain above it names `ToolExecutionFailedError` — the class that escaped the step, correctly distinguished from the one the tool raised — while **both successful generations stay `level: DEFAULT` with `cost_source: openrouter-billed`** on a run whose own span is ERROR (regression #12 closed). `builder-toolfail-3/D2-tool-error.png`; pass 1's `builder-toolfail/D2-tool-error{,-detail}.png` show the same shape without the classes. |
| **D3** | **PASS** *(pass 1; instrument re-run at `58a1c0b`)* | `cancelled/open-spans.txt` reads `open observations (endTime is null): 0 … observations examined: 28`, and `langfuse-traces.json.output` is `{"status":"cancelled","reason":"cancelled by operator"}` with the run SPAN at `level: WARNING` and the same `statusMessage`, on a run cancelled 6.0 s in with its research branches in flight (`cancel-timing.txt`); the run is **synthetic** and this row says so, as D3 permits. The instrument now leads with `unfinished spans (non-EVENT observations with endTime null)` and prints the three-way split, and reads **0** on all three pass-3 runs as well. |

## Rows that are not a plain PASS

**None.** All ten rows this verifier owns are PASS as of pass 3. The two that
were short are recorded here with what moved them, because a row that changed
verdict is worth being able to audit:

- **B3 / D1** — PARTIAL in pass 1 (`e68dac4`) and again in pass 2 (`c608953`):
  agent, task, node and run all at `level=ERROR` with the provider's full 400
  message and a run ending `failed`, but nothing naming the exception class,
  because in both runs **exactly one frame carried `error_class` and it closed
  no span**. **PASS at `58a1c0b`** — the class now reaches all four
  observations and the trace output, in both `metadata.error_class` and the
  `statusMessage`, without collapsing the three distinct span end times.
- **B5** — PARTIAL in pass 1 on the ground that a generation's `input` stayed
  null under `LANGFUSE_CAPTURE_CONTENT=1`. **PASS** since the contract's §4 was
  revised: `input` is absent under every policy by decision, because prompt
  content never enters the frame pipeline, so the capture half is judged on
  `output`, tool payloads and the trace input — all present and redacted, with
  the planted marker visible and the planted key scrubbed. No code changed for
  this row; the standard did.

Two things this verifier could not measure and does not claim: whether
`ad6a696`, `c608953` or `58a1c0b` changed anything in a pass-1 or pass-2
directory's favour beyond what pass 3 re-ran (only the rows re-run are
re-scored), and V-RECON's counting rows B1, B2, B4, E1 and E5.

## Two things a reader of these rows should not be misled by

1. **`open-spans.txt` is not 0 on the paid runs, and D3 still passes.** It reads
   38 / 10 / 19 / 22 there because a Langfuse **EVENT** observation is a point in
   time and carries no `endTime` by construction. `cancelled/open-spans-by-type.txt`
   splits every run: **0** non-EVENT observations are open on any of the six,
   terminal states included. D3's own run produced no EVENTs, so its file reads a
   clean 0.
2. **Every paid run here is signed in as `proof-runner`, which `PLAN.md` did not
   anticipate.** That was forced — the two-tool document is not launchable
   anonymously — and it makes A3 stronger, not weaker. `RUNS.md` records it as
   divergence 1.

## The defect that a PAID run was needed to see — FIXED, and re-proved fixed

Pass 1: `metadata.cost_source` read `app-estimate (lookup failed)` on **22 of 22**
paid generations, `lookup_ok=0` across four runs, because a 3.0 s single attempt
cannot catch a record OpenRouter does not index for 60 s+
(`DEFECT-billed-cost-lookup.md`, `openrouter-index-latency.json`).

Pass 2 at **`c608953`** (deferred, retried at +20/+60/+180 s inside a 240 s
window): `validator-live-2` reads **`lookup_ok=12 lookup_failed=0`**,
`cost_source = openrouter-billed` on **12 of 12**, `openrouter_cost_usd` and
`provider` on 12 of 12, `usageDetails` carrying `reasoning`/`cached` on 12 of 12,
and `costDetails.total` equal to OpenRouter's `total_cost` on every call —
Langfuse's sum and OpenRouter's sum are both **$0.06441798**, against an app
estimate of $0.05625510. `builder-toolfail-2` reads `lookup_ok=2 lookup_failed=0`.
The run span still ends at the terminal frame's own timestamp,
`2026-09-05T17:26:55.255Z` on both sides, exactly.

Pass 3 at **`58a1c0b`** holds it: `validator-live-3` reads
**`lookup_ok=11 lookup_failed=0`** against **11** app calls — one resolution per
call — with `openrouter-billed` and `level: DEFAULT` on 11 of 11, `costDetails.total`
matching OpenRouter on 11 of 11, both sums **$0.05697687**, and the run span
closing at its own `WORKFLOW_END` timestamp `2026-09-05T18:08:36.630Z`.
`builder-toolfail-3` reads `lookup_ok=2 lookup_failed=0` on a run that FAILED,
with both generations still `DEFAULT`.

## A tooling defect pass 2 exposed — FIXED at `58a1c0b`, with a second half

`scripts/observability/_common.py::redact_for_disk` scrubbed any string carrying
the Firecrawl prefix `fc-`, and a hex UUID satisfies that: the run id
`1a0bea14-ffb3-459d-b5fc-f714a76e5f71` was written to disk as
`1a0bea14-ffb3-459d-b5<redacted>` in **11 files** of `validator-live-2/`,
`langfuse-session.json.id` — the field A1 is verified on — among them.

Both halves are closed at `58a1c0b`. The shape rule gained a UUID boundary, and
`validator-live-2` was **re-pulled in place**: every file the tooling writes now
carries the id whole, and `metadata.run_id` reads in full on 85 of its 86
observations. The second half is the one nobody had seen — **the exporter was
scrubbing it too**, so `trace.metadata.run_id` on that run's *stored* trace reads
`1a0bea14-ffb3-459d-b5***` and no re-pull can change it. Identity fields are now
scrubbed by exact value only, and `validator-live-3`'s stored `run_id` is whole.

That is why A2 was re-measured on a fresh pair rather than left on pass 1: the
scrubbed field is exactly the one `membership_check.py` compares, and a damaged
run would have reported a mismatch indistinguishable from a real concurrency bug.

No code was changed by this verifier in any of the three passes.
