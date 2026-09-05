# `brief-live` — the OTHER hand-written flow, PAID (added for A1)

Run 2026-09-05 by V-PROOF, after the three planned paid runs, because **A1
names three flow kinds** — hand-written validator, hand-written brief, and a
builder-authored graph — and `PLAN.md` scheduled only two of the three. Budget
allowed it, so A1 is complete rather than partial.

| | |
| --- | --- |
| app run id | `6586c854-3ca3-44c4-a587-eb6a3ef01962` |
| Langfuse trace id | `6586c8543ca344c4a587eb6a3ef01962` |
| Langfuse session URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/6586c854-3ca3-44c4-a587-eb6a3ef01962 |
| Langfuse trace URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/6586c8543ca344c4a587eb6a3ef01962 |
| workflow / gates / env | `brief-flow` / `human` (this flow has no gates) / `live` |
| terminal status | `completed`, 2 m 17 s |
| frames | 116 |
| observations | 52 — SPAN 10, EVENT 22, AGENT 6, GENERATION 10, TOOL 4 |
| scores | 8 |
| app usage | 10 calls, 96,787 / 17,606 / 114,393 tokens, app estimate **$0.09759125** |
| OpenRouter billed | 10 generations, **$0.08876144** |
| input | `{"topic": "predictive maintenance for commercial building lifts"}` |

## What it settles, and one number worth carrying to E5

- **A1's third flow kind.** `langfuse-session.json.id` ==
  `6586c854-3ca3-44c4-a587-eb6a3ef01962` == the app run id; trace `name` is
  `brief-flow`; `tags` carry `gates:human`, which is this flow's actual mode
  (it declares no gate, so nothing paused).
- **The app's estimate is 9.9 % HIGH here** — $0.09759125 against OpenRouter's
  billed $0.08876144, a gap of $0.0088. The other two priced runs agree to the
  cent. This run is the only one that used the escalation tier heavily
  (`google/gemini-3.8-flash`), which is where cached and reasoning tokens live
  and where `compute_cost_usd`'s local table can diverge. E5's diagnosis
  belongs to V-RECON; the figures are in `openrouter.md` and `app-figures.md`.

No screenshot was taken for this run: it exists to complete A1, whose console
evidence is `../validator-live/A1-sessions-list.png` — where this session is
the top row.
