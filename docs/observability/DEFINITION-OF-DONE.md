# Observability programme — Definition of Done

Written 2026-09-05 by the orchestrator (Fable 5.1) BEFORE any implementation,
as the brief requires. **This document is binding.** A criterion is met only
when the artifact named in its Evidence column exists on disk under
`docs/observability/` and the named verifier has marked it. A builder never
marks their own row. Revisions after Task 1 are logged in §7 with the reason.

Repository note: every `*.md`/`*.png` outside `README.md` is gitignored in
this repository since 2026-09-05. `.gitignore` carries an explicit exception
for `docs/observability/**` because the brief requires these artifacts to be
committed, not local-only. **No file under this tree may contain a credential
value** (row F3 checks it mechanically).

## 1. What this is judged on

Not "fields are populated". The bar is: **a person reading Langfuse can answer
the questions below about a run they did not watch**, for a flow whose agents,
tasks and tools they have never seen, including on the paths where something
went wrong. Each row below is a question and the artifact that shows the
answer coming out of Langfuse (or out of the app, for the rows about the app
not being harmed).

## 2. Roles

| Role | Who | Builds | Verifies |
| --- | --- | --- | --- |
| ORCH | Fable 5.1 orchestrator | nothing | final acceptance; rows F1, F4 |
| B-EXP | Opus 5 builder, exporter | `src/brief_crew/observability/**`, its tests, its config knobs | nothing it built |
| B-CFG | Opus 5 builder, config + reconciliation tooling | OpenRouter-side change, `scripts/observability/**`, app-side figure export | nothing it built |
| V-PROOF | Opus 5 verifier (built nothing) | — | the real-run rows: A*, B*, C2, D1–D3 |
| V-RECON | Opus 5 verifier (built nothing) | — | the counting rows: A2, B1, B2, B4, E1, E4, E5 |
| V-REVIEW | Opus 5 verifier (built nothing) | — | the code/test/policy rows: C1, C3, D4, D6, E2, E3, F2, F3 |

Two workers will additionally argue the keep/supplement/replace question
independently in Task 1; neither builds.

## 3. Evidence layout

```text
docs/observability/
  DEFINITION-OF-DONE.md        this file
  AUDIT.md                     Task 1 synthesis and the layer decision
  audit/                       the three Task 1 inventories
  RECONCILIATION.md            Task 3 side-by-side, every discrepancy diagnosed
  ANSWER.md                    Task 3 closing answer: what can now be learned, what still cannot
  evidence/audit/**            Task 1 exports and screenshots
  evidence/proof/<run-slug>/   per proof run: request, app snapshot JSON, Langfuse session/trace JSON, PNGs
  evidence/tests/              pasted test output with the command that produced it
  evidence/perf/               overhead measurement raw numbers and the table
```

A screenshot is a PNG taken from the Langfuse console showing the thing the row
names, with the URL visible or recorded beside it. A JSON export is the public
API response saved verbatim. "App snapshot" is `GET /api/runs/{id}` plus the
NDJSON frame log for that run.

## 4. Criteria

Status column is filled at the end: PASS / PARTIAL / FAIL / NOT RUN, never
blank. Every non-PASS gets a sentence in §6.

### A. A run reads as one unit

| # | Question the data must answer | Evidence (on disk) | Verifier | Status |
| --- | --- | --- | --- | --- |
| A1 | Does one app run appear as exactly one Langfuse **session**, whose id is the app's own run id, for every flow kind the app can launch (hand-written validator, hand-written brief, builder-authored graph)? | `evidence/proof/<run>/langfuse-session.json` for each proof run with `id == run_id`; console screenshot of the Sessions list showing them. | V-PROOF | |
| A2 | Do two runs launched **concurrently** produce two sessions with **zero** cross-membership — every observation's run-id metadata equals the session it sits in? | Two proof runs overlapping in time; both session exports; `evidence/proof/concurrent/membership-check.txt` from a script that walks every observation and reports mismatches (must be 0). | V-RECON | |
| A3 | From the session alone, can a reader tell WHICH flow ran, WHO launched it, in WHAT mode (gates human/auto; synthetic/live), and WHEN it started and ended with WHAT terminal status? | Trace JSON showing workflow id, flow kind, user id (or `anonymous`), gates mode, Langfuse `environment`, run start/end, terminal status in a run-level observation. | V-PROOF | |

### B. Attribution — the questions the audit says fail today

| # | Question | Evidence | Verifier | Status |
| --- | --- | --- | --- | --- |
| B1 | **Cost and tokens per agent.** For one proof run, can a per-agent table (role → calls, input tokens, output tokens, cost) be produced FROM LANGFUSE, and does it sum to the run total? | `evidence/proof/<run>/per-agent.md` computed from the Langfuse API grouping generations by their agent-role attribute, plus a console screenshot of the observation tree where each generation sits under its agent. | V-RECON | |
| B2 | **Cost and tokens per task.** Same, grouped by task name. | `evidence/proof/<run>/per-task.md` + screenshot. | V-RECON | |
| B3 | **Which step failed, and why.** For the run containing a failing agent: is the failure on the specific agent's and task's observation, at `level=ERROR`, with a `statusMessage` naming the exception class and a redacted message, and does the run-level observation end with status `failed` rather than the trace just stopping? | `evidence/proof/<failing-run>/failure.png` and the trace JSON; the observation ids named in the caption. | V-PROOF | |
| B4 | **Why was the run slow.** Can the slowest agent, task and tool call be ranked from span durations, and do those durations agree with the app's own frame timestamps within 1 s? | `evidence/proof/<run>/durations.md` (Langfuse spans vs app frames side by side) + timeline screenshot. | V-RECON | |
| B5 | **Which prompt produced a bad output.** Under the default content policy (§5), does every generation carry the task name, agent role, model, a stable prompt fingerprint and the completion length, so that a bad output can be traced to a specific task+agent+model+prompt-version WITHOUT the content being stored? And with `LANGFUSE_CAPTURE_CONTENT=1`, is the redacted content present? | Trace JSON from a default-policy run showing the fingerprint fields and no content; trace JSON from one synthetic run with capture on showing content, with the redaction visible on a planted marker. | V-PROOF | |
| B6 | **Is quality drifting.** Are generic quality signals recorded as Langfuse **scores** — per task: guardrail passed/failed and retry count; per run: terminal outcome — such that a rate over time is chartable in Langfuse? (Flow-specific scores like the validator's composite are OUT of scope for the instrumentation path; see C1.) | Scores JSON export for the proof runs; console screenshot of the Scores surface non-empty. | V-PROOF | |

### C. Generalisation — a flow built later is traced completely

| # | Question | Evidence | Verifier | Status |
| --- | --- | --- | --- | --- |
| C1 | Does the instrumentation path contain **no** agent role, task name, tool name, crew name or flow name from any flow in this repository? | A committed test that greps `src/brief_crew/observability/**` for every role/task/tool/crew identifier in `agents.yaml`/`tasks.yaml` of both hand-written crews and the four built-in skill packs, asserting zero hits; its output in `evidence/tests/`. | V-REVIEW | |
| C2 | Is a **builder-authored graph with an agent role, a task name and an author-named tool invented during Task 3** (strings that appear nowhere in the repo before that day) traced with those strings appearing verbatim as the agent, task and tool observation names? The one tool an author can NAME in this product is the custom HTTP tool (a library tool carries a server-owned id); the raising tool of D2 is therefore a library tool and its own id must appear verbatim. | The graph's document JSON, the proof run's trace JSON, a screenshot; `git grep` output proving the strings were absent at the pre-Task-3 commit (`evidence/proof/builder-toolfail/absent-before.txt`). | V-PROOF | |
| C3 | Is every CrewAI 1.15.18 event type either mapped to an observation or listed as deliberately unmapped with a reason, and does an event type the exporter has never seen become a generic EVENT observation instead of being dropped? | A committed test that enumerates `crewai.events.types` classes against the exporter's mapping; a test feeding a synthetic unknown event; both outputs in `evidence/tests/`. | V-REVIEW | |

### D. The paths that are easy to skip

| # | Question | Evidence | Verifier | Status |
| --- | --- | --- | --- | --- |
| D1 | **Failed agent** (real run): as B3. | Same artifact as B3. | V-PROOF | |
| D2 | **Raising tool** (real run): does the tool observation carry `level=ERROR` and the error text, nested under the agent that called it, and does the agent's subsequent behaviour (retry or give up) remain visible after it? | `evidence/proof/<run>/tool-error.png` + trace JSON with the tool observation id. | V-PROOF | |
| D3 | **Cancelled run**: after `POST /api/runs/{id}/cancel`, does the trace end with a run-level observation whose status is `cancelled`, with **no observation left without an end time**? | Trace JSON for a cancelled run (synthetic is acceptable here, and the report says which) + `evidence/proof/cancelled/open-spans.txt` = 0. | V-PROOF | |
| D4 | **Retried call**: when a guardrail fails and CrewAI re-runs the task, are both generations present under the same task with the guardrail result and the retry index legible, and when CrewAI retries a transport failure is that visible as a failed generation followed by a successful one? | A committed test replaying a recorded event sequence containing a guardrail retry and a transport retry, asserting the observation shape; output in `evidence/tests/`. If a proof run happens to retry, its screenshot too. | V-REVIEW | |
| D5 | **Concurrent runs**: as A2. | Same artifact as A2. | V-RECON | |
| D6 | **Cost-ceiling abort** (`MAX_RUN_COST_USD` → `HookAborted`): does the trace end with status `failed` and the ceiling named as the reason? | A committed test driving the abort path through the exporter; output in `evidence/tests/`. | V-REVIEW | |

### E. Observability must not change what the app does, and must not lie

| # | Question | Evidence | Verifier | Status |
| --- | --- | --- | --- | --- |
| E1 | **Nothing reaches Langfuse twice.** For each proof run, is the count of GENERATION observations in its session equal to the app's LLM-call count for the run, with no second copy of any call arriving from the OpenRouter-side integration? | `RECONCILIATION.md` row per run: Langfuse generations, app `LLM` frames, OpenRouter activity rows for the window; and the recorded OpenRouter-side configuration change (or non-change) that makes this hold. | V-RECON | |
| E2 | **Langfuse down, misconfigured or slow → runs unaffected.** With `LANGFUSE_BASE_URL` pointed at a black-hole port, at a host that answers slowly, and with the keys missing, does a synthetic run complete with the same status, result and frame count as with Langfuse healthy, with the exporter failure logged once and never surfaced as a run error? | A committed test for each of the three conditions; output in `evidence/tests/`. | V-REVIEW | |
| E3 | **Content policy enforced.** Under defaults, does the exported payload contain no message content, no user-entered idea text, and no string matching the credential shapes the app already knows (`events/redaction.py` rules plus OpenRouter/Langfuse/Firecrawl/GitHub key prefixes), even when a tool argument or prompt contains a planted fake key? | A committed test that plants markers and asserts absence from the captured exporter payload; output in `evidence/tests/`. | V-REVIEW | |
| E4 | **Overhead measured.** On a full synthetic run with a fixed branch delay, what is the wall-clock delta and the per-frame handler latency (p50/p95) with the exporter on versus off, n ≥ 3 each? | `evidence/perf/overhead.md` with the raw numbers and the command. | V-RECON | |
| E5 | **The app's figures and Langfuse's agree, or the difference is diagnosed.** For each proof run: call count, input/output tokens, cost — app snapshot vs Langfuse session vs OpenRouter's own activity/generation records, side by side. Every difference has a named cause; "close enough" is not a status. | `RECONCILIATION.md`. | V-RECON | |

### F. Process

| # | Question | Evidence | Verifier | Status |
| --- | --- | --- | --- | --- |
| F1 | Was the OpenRouter-side configuration's **exact prior state** recorded before anything touched it, and is every change to it stated with its reason? | `audit/openrouter-forwarding.md` §1 (prior state) and `AUDIT.md` (change + reason). | ORCH | |
| F2 | Are the committed tests only those the rows above require? | V-REVIEW's list of test files against the rows they serve, in `evidence/tests/INDEX.md`. | V-REVIEW | |
| F3 | Does no committed artifact contain a credential value? | `evidence/tests/secret-scan.txt`: a grep over `docs/observability/` and the diff for `sk-or-`, `sk-lf-`, `pk-lf-`, `fc-`, `ghp_`, `github_pat_`, `pcsk_`, and the actual key values read from `.env` at check time (compared, never printed) — zero hits. | V-REVIEW | |
| F4 | Were the three real proof runs (≥ 2 flows, one with tools, one with a failing agent) run against paid models, and is the money spent recorded? | `evidence/proof/RUNS.md`: run ids, flow, model tier, OpenRouter cost per run, total. | ORCH | |

## 5. Decisions taken in advance (the instrumentation is built to these)

These are the orchestrator's calls. Task 1 may overturn any of them; if it
does, §7 says so.

1. **Session = app run id.** Langfuse `sessionId` is the app's `run_id`
   verbatim, so a reader can go from the console's URL to Langfuse without a
   lookup table. `userId` is the app's owner id or `anonymous`. `environment`
   is `synthetic` or `live`.
2. **Identity comes from CrewAI's own event payloads**, never from a table:
   agent role from the agent object on the event, task name/description from
   the task object, tool name from the tool event, model from the LLM event.
   That is the same source the app's existing frame pipeline already uses.
3. **Content policy, default OFF.** Prompt and completion text are not sent;
   each generation carries a SHA-256 fingerprint of the rendered prompt, the
   message count, and character lengths. User-entered text is treated as
   content. `LANGFUSE_CAPTURE_CONTENT=1` turns capture on, and even then every
   string passes the existing redaction rules plus key-prefix scrubbing.
   Rationale: a public console URL is one paste away from leaking a user's
   idea or a pasted key; a fingerprint still answers "which prompt".
4. **Fail open, log once.** The exporter runs off the same bounded, dropping
   queue pattern the frame pipeline uses; any exception inside it is caught,
   counted and logged at most once per run. It never raises into CrewAI.
5. **One reporter per call.** Whichever layer is chosen in Task 1, exactly one
   of them emits the GENERATION observation. If both must exist, the
   OpenRouter-side copy is either turned off or demoted to a linked reference,
   and E1 measures the outcome.
6. **No flow-specific scores in the instrumentation path.** Generic scores
   only (guardrail result, retry count, terminal outcome). A flow that wants
   its own metric scored can do so through a declared, generic hook later; that
   is a follow-up, not this programme.

## 6. Rows that are not a plain PASS

Filled at the end. One sentence each: what was measured, what was short.

## 7. Revision log

| Date | Row | Change | Why |
| --- | --- | --- | --- |
| 2026-09-05 | — | Initial version, before Task 1. | — |
| 2026-09-05 | §5.1 | Trace id = `UUID(run_id).hex` when the run id parses as a UUID, else the SDK's seeded derivation. | Both position papers: keep an undocumented hash out of the critical path; the id stays computable from a console URL. |
| 2026-09-05 | §5.5 | Settled as REPLACE: the app emits every observation; the OpenRouter destination excludes this app's key. | `AUDIT.md` §7. |
| 2026-09-05 | B4 | Span start = exporter clock behind a ≤ 0.25 s drain, end = frame timestamp, `metadata.frame_ts` = true start; tolerance unchanged at 1 s. | The langfuse 4.15.1 SDK has no `start_time` on `start_observation()`; `end(end_time=)` is explicit (position B). |
| 2026-09-05 | B1/B2 | Cached/reasoning token split comes from the OpenRouter generation lookup, not from the app's frames. | The frame serializer drops those fields; changing it is outside this brief. |
| 2026-09-05 | §2 roles | The OpenRouter exclusion is made by a dedicated config worker, not B-CFG. | B-CFG was already building the tooling; one owner per surface. |
| 2026-09-05 | contract §2 | The agent observation is Langfuse's native AGENT type, not a SPAN; the `run` span is the parentless root. | Live smoke (`evidence/smoke-live/`): the exporter already emits AGENT, and the run span carried a parent id that exists nowhere, leaving the tree rootless in the API export. |
| 2026-09-05 | contract §3 | `frame_seq`/`frame_ts` are the OPENING frame's for every type, and all seven metadata keys are present (null-valued) on every observation. | Smoke: TOOL carried the `after` frame's seq; 11 of 33 observations lacked keys. |
| 2026-09-05 | B5 / contract §4 | The prompt fingerprint is computed in the frame serializer from `LLMCallStartedEvent.messages` and carried on the LLM `before` frame; the exporter copies it. Additive frame fields only; no content enters a frame. | Smoke: the frame pipeline recorded no prompt, so the exporter fingerprinted the identity, which is constant across every call of a task and cannot answer "which prompt". The serializer is instrumentation, not flow semantics, so this is inside the brief. |
| 2026-09-05 | contract §1 | Tags carry `mode:`; trace metadata carries the LAST `run_metrics` snapshot. | Smoke: `mode:run` was emitted undocumented; the run span held the interval snapshot (3 calls) rather than the final one (6 calls), because the final snapshot arrives after the terminal frame. |
| 2026-09-05 | F3 | Langfuse's API echoes the project public key (`metadata.scope.attributes.public_key`) on every object; the pull tooling redacts it at write time. | Smoke: 36 occurrences per run in the raw export; the F3 scan failed until redacted by hand. |
| 2026-09-05 | C2 | The invented strings are the agent role, the task name and an author-named custom HTTP tool; the raising tool is a library tool whose own id must appear verbatim. | Proof-doc preparation: a builder `tool` node carries only a server-owned `tool_id`, and the only author-named tool (custom HTTP) reports rather than raises by design (`builder/tools.py`), so "invented name" and "throws" cannot be one tool. The generalisation claim is unchanged: whatever name the frame carries is what Langfuse shows. |
| 2026-09-05 | proof plan | Tool failure = library `scrape_website` with `tool_failure_policy: raise` against an unresolvable host (a real `ValueError`); agent failure = `llm.max_tokens` far above the model's context, refused by OpenRouter with HTTP 400 at zero cost. | The plan's credential injection is impossible for an anonymous launch on an auth-off backend (401 on the credential route; `CredentialNotYours` on an unowned run), and an unserved model id is refused at validate/publish (`model-unknown`). Recorded in `evidence/proof/*/inject.md`. |
