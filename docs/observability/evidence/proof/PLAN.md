# Task 3 proof-run plan

Orchestrator's plan, written 2026-09-05 before any proof run. V-PROOF executes
it and records what actually happened in `RUNS.md` beside this file.

## Backend

One LOCAL paid backend, this machine, `.env` loaded (OpenRouter, Firecrawl,
GitHub, Langfuse keys), no `SYNTHETIC`. Settings that differ from the
defaults, all environment variables:

| Variable | Value | Why |
| --- | --- | --- |
| `PORT` | `8000` | the paid port; the console's default proxy target |
| `RUN_CONCURRENCY` | `2` | A2/D5 need two runs executing at once; the default is 1 and would queue them |
| `LANGFUSE_EXPORT_ENABLED` | `1` (default when keys present) | |
| `LANGFUSE_CAPTURE_CONTENT` | unset (default off) | B5's default-policy half |
| `VALIDATOR_ALLOW_AUTO_GATES` | already `1` in `.env` | unattended runs; no human at a gate |

Start it with logging visible (the exporter's summary line is WARNING on
`brief_crew.observability.summary`; tooling's `measure_overhead.py` shows the
`logging.basicConfig` wrapper). Kill with `Stop-Process -Name serve -Force`.

## Runs

| Slug | Flow | Purpose | Rows | Paid? |
| --- | --- | --- | --- | --- |
| `validator-live` | `idea-validator`, gates `auto`, one real idea | the tool-using hand-written flow: Firecrawl, HN, GitHub | A1, A3, B1, B2, B4, B5 (default half), B6, E1, E5 | yes (~$0.05 by the 12:11 precedent) |
| `builder-toolfail` | builder-authored graph, published via the API, gates none/auto | an INVENTED agent role and task name; a library tool given an invalid credential so the tool raises | C2, D2, A1, E1, E5 | yes (small) |
| `builder-agentfail` | builder-authored graph whose agent is given a model id OpenRouter does not serve (still `openrouter/`-prefixed, so startup checks pass) | the failing agent: LLM call refused → agent fails → run fails | B3, D1, A1, E1 | yes (near zero: the call is refused) |
| `concurrent-a` / `concurrent-b` | `validator-live` shape and `builder-toolfail` shape launched within 2 s of each other | A2/D5 | A2, D5 | yes (second validator run ≈ $0.05) — OR reuse `validator-live` and `builder-toolfail` themselves by launching them concurrently; preferred, saves a run |
| `cancelled` | synthetic backend on :8099, `SYNTHETIC_BRANCH_DELAY_SECONDS=8`, cancel mid-branch via `POST /api/runs/{id}/cancel` | D3 | D3 | no |
| `capture-on` | synthetic backend, `LANGFUSE_CAPTURE_CONTENT=1`, idea text containing a planted marker and a fake `sk-or-v1-…` key | B5's capture half, E3 live | B5 | no |

So the three paid runs are `validator-live`, `builder-toolfail`,
`builder-agentfail`, across two flows (hand-written validator, builder), one
with tools, one with a failing agent, and two of them launched concurrently.
Budget: authorised up to **$1.00** total for Task 3; record each run's OpenRouter
cost from the generation records.

## The invented identifiers (C2)

Chosen now, so `git grep` at the pre-Task-3 commit can prove their absence:

- agent role: `Tidewater Cartographer`
- task name / node label: `chart_the_shoals`
- goal/backstory: anything, but containing the phrase `sounding line`

Before running: `git grep -n "Tidewater Cartographer\|chart_the_shoals" $(git rev-parse HEAD)`
must print nothing; save that output as `evidence/proof/builder-toolfail/absent-before.txt`.
The tool name is a LIBRARY tool id (the builder does not let an author name a
tool); C2's "tool name appears verbatim" is satisfied by the library tool's own
name appearing as the TOOL observation name. If that is the only way, say so in
`RUNS.md` — it is a fact about the builder, not a shortfall of the tracing.

## Failure injection, engine-neutral (from `audit/app-surface.md` §9.2)

- **Raising tool**: on `builder-toolfail`, give the tool node a credential that
  is syntactically valid and wrong (create it through
  `POST /api/builder/credentials`, then reference it from the agent). The tool
  raises at first use; the agent then retries or gives up — both legible.
- **Failing agent**: on `builder-agentfail`, set the authored agent's model to
  `openrouter/nonexistent/model-that-is-not-served` (or whichever string the
  document schema accepts; it must keep the `openrouter/` prefix). OpenRouter
  answers 400/404; CrewAI raises; the frames carry `LLMCallFailed` → agent
  error → run failed.

If either injection is refused by the builder's validation before the run can
start, pick the next option from `app-surface.md` §9.2 and record which.

## What to save per run (`evidence/proof/<slug>/`)

`request.json`, `app-run.json` and `frames.ndjson` (via
`scripts/observability/pull_app_run.py`), the Langfuse session/trace/observation
exports and derived tables (via `pull_langfuse_run.py`), the OpenRouter
generation records (via `pull_openrouter.py`), the screenshots the rows name
(session list, observation tree, failure, tool error, scores, timeline), and a
`README.md` naming the run id, the Langfuse session URL, and the observation ids
each screenshot shows.
