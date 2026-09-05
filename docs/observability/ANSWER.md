# What a person can now learn from this data, and what still cannot be answered

Task 3's closing answer, written 2026-09-06 by the orchestrator against the
evidence tree. Every claim below names the file that shows it; the audit's
own table (`AUDIT.md` §3) is the "before" column. Where a figure comes from a
paid run it is one of the six proof runs in `evidence/proof/RUNS.md`,
made against real OpenRouter, Firecrawl, HN and GitHub for **$0.19** across
two passes (four paid runs, then three re-proofs after fixes).

## 1. The questions, before and after

| Question | Before (audit, 2026-09-05) | After (proof runs, 2026-09-06) | Evidence |
| --- | --- | --- | --- |
| **Which run is this?** | NO — one trace per OpenRouter request, no run id, runs reconstructed by a 120 s timestamp gap that merges concurrent runs | **YES** — one Langfuse session per run, `sessionId == run_id` verbatim, for the validator, the brief flow and two builder-authored graphs; the console URL's run id is the Langfuse session id | `proof/*/langfuse-session.json`; `proof/validator-live/A1-sessions-list.png` |
| **Are two concurrent runs separable?** | NO — reasoned from field availability; would silently merge | **YES** — two runs launched 5 ms apart with `RUN_CONCURRENCY=2`, 43 of 43 frames of one inside the other's window, 0 cross-membership over 97 observations | `proof/concurrent/overlap.txt`, `membership-check.txt` |
| **Who launched it, which flow, what mode, when, how did it end?** | NO — `userId`, `sessionId`, tags all empty on 40/40 | **YES** — `trace.name` = workflow id, `userId` = the signed-in user, `environment` live/synthetic, `tags` = gates and mode, run span start/end, `output.status` ∈ completed/failed/cancelled with a reason | `proof/*/langfuse-trace.json`; A3 in `proof/VERDICTS.md` |
| **Cost per agent** | PARTIAL — a regex over prompt text on a run identified by hand | **YES** — GENERATIONs carry `agent_role`; grouped from the API they sum to the trace total, the app snapshot and (validator-live) OpenRouter's bill to the cent | `proof/validator-live/per-agent.md`, `B1-tree-per-agent.png` |
| **Cost per task** | NO | **YES** — same, by `task_name`; the guardrail calls the app's own table could not place resolve to their task in Langfuse | `proof/*/per-task.md` |
| **Cost per run / per flow** | PARTIAL — by clustering, breaks under concurrency | **YES** — `trace.metadata.run_metrics` is the app's final snapshot (or the exporter's own tally when a run never got one), and the generations sum to it | `RECONCILIATION.md` §1 |
| **Which step failed, and why** | NO — 80/80 observations `level: DEFAULT`; a refused request produced no trace at all | **YES** — a refused call is an ERROR generation under its agent, task and node; the run ends `failed` with the reason; after pass 2 the exception class is named on each of them | `proof/builder-agentfail*/failure.png`, B3/D1 in `proof/VERDICTS.md` |
| **What did the tool do, and did it fail?** | NO — tools never reach OpenRouter; a tool-call turn showed an empty completion | **YES** — a TOOL observation named after the tool, `level: ERROR` with `ValueError("Could not resolve hostname …")`, nested under the agent, and the agent's next move (gave up) visible after it | `proof/builder-toolfail/D2-tool-error.png` |
| **Why was the run slow?** | PARTIAL — per-call latency only; nothing between calls | **YES** — agent, task and tool spans with durations that agree with the app's frames on 56 of 56 paired rows (worst 0.256 s); slowest agent/task/tool ranked | `proof/*/durations.md`, `B4-timeline.png` |
| **Which prompt produced a bad output?** | YES for content, NO for attribution | **YES for attribution** — every generation carries task, agent, model, `prompt_fingerprint` (a hash of the rendered messages; 10 distinct on 10 calls), `message_count`, `prompt_chars`, `completion_chars`. **Content is off by default** and, when switched on, the completion is present with keys scrubbed; the prompt itself is never stored (§3) | B5 in `proof/VERDICTS.md`; `proof/capture-on/` |
| **Is quality drifting?** | NO — 0 scores, 0 evaluators, 0 datasets | **A baseline now exists** — `guardrail_passed` per task, `task_attempts` per task, `run_succeeded` / `run_status` per run, chartable over time on the Scores surface | `proof/validator-live/B6-scores.png`, `langfuse-scores.json` |
| **Was a call reported twice?** | Unknowable | **NO** — generations = call attempts on every run; 0 traces in any window carry the broadcast's `openrouter.api_key_name` after this app's key was excluded (a detector that saw 45 such traces before) | `RECONCILIATION.md` §4 |
| **Does the app agree with Langfuse and with OpenRouter?** | Never checked | **YES, and the difference is now visible in Langfuse itself.** Pass 1: to the cent on three of four paid runs; `brief-live` 9.95 % high in the app's estimate because OpenRouter applied a prompt-cache discount on 32,703 cached tokens (attributed exactly). Passes 2 and 3: every generation carries OpenRouter's billed cost, provider, cached and reasoning tokens; Langfuse's sum equals OpenRouter's to the last decimal, and the app's price-table estimate reads 12.7 % and 7.5 % low on those runs because the `:nitro` route lands some calls on a `priority` endpoint at exactly 1.8× list price, per call, so a reader sees estimate and bill side by side and no fixed multiplier could have corrected it | `RECONCILIATION.md` §3 and the pass-2 section; `proof/validator-live-2/` |
| **A flow that does not exist yet** | — | **Traced completely with no code change** — a graph authored during Task 3 with a role, task and tool name that appear nowhere in the repository before it shows all three verbatim as observation names; the instrumentation path contains no identifier of any flow in the repo (a test that can fail proves it) | C1/C2 in `proof/VERDICTS.md`, `evidence/tests/C1.txt`, `proof/builder-toolfail/absent-before.txt` |

## 2. What it costs

Nothing measurable on a run. With the exporter on versus off, 20 synthetic runs
each: −1.7 ms on a 6.1 s run, a 95 % interval of −15.5 … +12.2 ms, enqueue
p50 1.5 µs and p95 5 µs on the capture path, 0 dropped frames in 70 runs, and
an unreachable Langfuse changes nothing but the exporter's own counters
(`evidence/perf/overhead.md`). Process boot is about 0.5 s slower for the SDK
import. Langfuse itself shows a run about 15 s after it ends; its cost fields
keep settling for up to about eight minutes while the deferred billed-cost
lookups land, and the pull tooling waits for that.

## 3. What still cannot be answered

- **The prompt text is not in Langfuse under any policy.** That is a
  decision, not a gap in the plumbing: prompt content never enters the app's
  frame pipeline, and putting it there would persist every prompt into the
  app's own run store, which is a wider disclosure than a Langfuse project.
  A bad output is traced to a task, agent, model and prompt fingerprint; to
  read the prompt itself you go to the code that rendered it. The completion
  and tool payloads are available under `LANGFUSE_CAPTURE_CONTENT=1`, scrubbed.
- **Spend that raises no LLM event is in no figure.** Embeddings, Cohere
  rerank and Firecrawl are invisible to the frame pipeline and therefore to
  the exporter, as they were to the OpenRouter broadcast; CrewAI's Memory and
  Knowledge events (17 classes) are deliberately unmapped, with the reason
  recorded per class in `mapping.py`, and their per-class count reaches the
  trace as `unhandled_event_counts` so a reader at least knows they happened.
- **The OpenAI client's own transport retries are invisible everywhere** — a
  429 retried twice inside the HTTP layer looks like one slow call. No CrewAI
  event, no frame, no second OpenRouter record.
- **A CLI run (`validate --idea`) is not traced.** It never enters the
  service's capture scope, has no run id, and so has no session. Follow-up.
- **Quality itself is not judged.** The scores are mechanical (guardrail
  outcome, attempts, terminal status). No LLM-as-judge evaluator runs — the
  Langfuse Playground has no model configured — and no flow-specific metric
  (the validator's composite score) is exported, by the definition of done's
  own rule that the instrumentation path knows no flow. A generic scoring
  hook is the next step.
- **An agent's span starts at its first model call, not at the agent frame,
  and a retried agent is one observation, not two.** CrewAI's agent-started
  event carries no role, so the exporter cannot name the agent until the first
  LLM frame; the span opens up to 0.26 s late, and when an agent is executed
  twice both attempts sit under one agent observation (legible as `attempt`
  1 and 2 on the generations, but the slowest-agent figure is inflated).
  A serializer follow-up rather than an exporter one.
- **A refused model call's generation names no exception class.** The class
  is on the agent, task, node and run observations and on the trace output;
  the ERROR generation itself carries the provider's message only, because
  CrewAI stringifies the error before the event. Follow-up.
- **The bill is exact only after OpenRouter indexes the generation** —
  tens of seconds after the call. Until the deferred lookup lands (20, 60,
  then 180 s after the call), a generation carries the app's price-table
  estimate and says so in `cost_source`; the estimate knows nothing of
  prompt-cache discounts, reasoning tokens or provider price spread, which is
  why it read 9.95 % high on one run and 12.7 % low on another. The app's own
  `cost_usd` in the console is that estimate; the true figure lives in Langfuse.

## 4. Follow-ups outside this brief

Recorded rather than fixed, per the scope rule:

- `tests/service` crashes with a Windows access violation in roughly a quarter
  of full-suite runs **at the pre-observability baseline too**
  (`evidence/tests/stability/REPORT.md`): 1,050 leaked `validator*` threads
  from registries tests never close. Same census on both arms.
- The agent-started frame carries `agent_role: None` (above).
- `Guardrail Agent` calls are labelled `AgentExecutor` by the app's own agent
  frames; Langfuse names them from the LLM frame's role.
- The `/api/public/metrics/daily` endpoint the audit's cost figures came from
  is deprecated with a sunset of 2026-11-16.
- Five `obs-probe-*` traces from the audit's probes remain in the Langfuse
  project and are cheap to delete.
