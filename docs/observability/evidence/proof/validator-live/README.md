# `validator-live` — the hand-written six-agent validator, PAID

Run 2026-09-05 by V-PROOF. Code at `e68dac4`. Backend: local paid backend on
`127.0.0.1:8000`, non-synthetic, `AUTH_BASE_URL=http://127.0.0.1:8093`,
`RUN_CONCURRENCY=2`, exporter defaults (content capture OFF, billed-cost
resolution ON). Launched as the signed-in user `proof-runner`.

| | |
| --- | --- |
| app run id | `f4c8c779-52f2-40e1-9351-2668ea276ae4` |
| Langfuse trace id | `f4c8c77952f240e193512668ea276ae4` (= `UUID(run_id).hex`) |
| Langfuse session URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/f4c8c779-52f2-40e1-9351-2668ea276ae4 |
| Langfuse trace URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/f4c8c77952f240e193512668ea276ae4 |
| workflow / gates / env | `idea-validator` / `auto` / `live` |
| terminal status | `completed`, 50.31 s |
| frames | 155 |
| observations | 76 — SPAN 18, EVENT 38, AGENT 7, GENERATION 10, TOOL 3 |
| scores | 14 (`run_succeeded`, `run_status`, 6x `task_attempts`, 6x `guardrail_passed`) |
| app usage | 10 calls, 29,816 / 6,371 / 36,187 tokens, app estimate **$0.03823525** |
| OpenRouter billed | 10 generations, **$0.03823525** (`openrouter.md`) |

Idea (33 words, in `request.json`): a retrofit vibration-sensor subscription
warning facilities managers of lift bearing wear before a breakdown.

## Screenshots and the observation ids each shows

| file | URL | shows |
| --- | --- | --- |
| `A1-sessions-list.png` | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions (filtered to `environment = live`) | the four PAID proof sessions, each id equal to its app run id, all `live`, all `proof-runner` |
| `A3-run-level.png` | the trace URL above | the `run` SPAN `5525de0c3601355d`: session id, `User ID: proof-runner`, `Env: live`, tags `idea-validator` / `gates:auto` / `mode:run`, start `00:33:04.230`, latency 50.31 s, `output.status = "completed"`, input as keys+chars+fingerprint with no idea text |
| `B1-tree-per-agent.png` | the trace URL above | `market_task` `24a7e1d59a77be61` → AGENT `Market evidence analyst` `5110f385afb7793c` → GENERATION `29d9745e799a00bf` (attempt 1), TOOL `research_market_landscape` `a6c68222501bc21d`, GENERATION `6887832fcf5eaaa6` (attempt 2), each with its own tokens and cost |
| `B4-timeline.png` | `?view=timeline` | per-observation durations, labels on |
| `B6-scores.png` | `?traceTab=scores` | this run's 14 scores with names, values and timestamps |
| `B6-scores-project-surface.png` | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/scores | the project Scores surface non-empty, with the count-over-time chart |

## What this run settles

- **A1 / A3.** `langfuse-session.json.id` == the app run id; the trace names the
  flow, the user, the gates mode, the environment and the terminal status.
- **B5, default half.** All 10 generations carry
  `prompt_fingerprint_basis = "messages"`, `message_count`, `prompt_chars`,
  `completion_chars`, `attempt` and `finish_reason`; 10 **distinct**
  fingerprints; `input` and `output` are null on all ten. (The smoke-live
  defect D3 — a fingerprint of the identity rather than of the prompt — is
  fixed.)
- **B6.** `guardrail_passed` scores exist here for the first time: this path
  emits guardrail frames, which the synthetic double never did.
- **Defect.** `metadata.cost_source` reads `app-estimate (lookup failed)` on
  all ten. See `../DEFECT-billed-cost-lookup.md`.
