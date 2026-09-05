# `builder-toolfail` — a builder-authored graph with an invented tool that reports and a library tool that RAISES, PAID

Run 2026-09-05 by V-PROOF. Code at `e68dac4`. Same paid backend as
`../validator-live`, same signed-in user `proof-runner`. Launched **within
5 ms** of `validator-live` — see `../concurrent/launch-times.txt`.

| | |
| --- | --- |
| app run id | `9becf713-e984-45a9-b9c0-5b229a15cb60` |
| Langfuse trace id | `9becf713e98445a9b9c05b229a15cb60` |
| Langfuse session URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/9becf713-e984-45a9-b9c0-5b229a15cb60 |
| Langfuse trace URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/9becf713e98445a9b9c05b229a15cb60 |
| workflow / gates / env | `ug_4e7e952f` (*Tidewater survey*, graph_version `c3b393e1a89362dd`) / `auto` / `live` |
| terminal status | `failed`, 2.67 s |
| frames | 43 |
| observations | 21 — SPAN 6, EVENT 10, AGENT 1, GENERATION 2, TOOL 2 |
| scores | 3 (`run_succeeded` 0, `run_status` `failed`, `task_attempts` 2) |
| app usage | 2 calls, 788 / 53 / 841 tokens, app estimate **$0.0003689** |
| OpenRouter billed | 2 generations, **$0.0003689** |
| attempts | **one**. The model called both tools on the first try; no relaunch was needed |

The document was created and published by `V-PROOF-IDENTITY` before this
session (`../identity/README.md`) and was still registered after the backend's
boot rehydration (`rehydrated 1 published builder graph(s): ug_4e7e952f` in
`../backend-8000.log`), so it was launched directly.

## The two tools, and why there had to be two

`inject.md` §2 and §7 explain it and this run confirms both halves:

- **`sounding_line_lookup`** is the **author's own name** for a custom HTTP
  tool. It appears verbatim as the TOOL observation name. It **reports** rather
  than raises, by design (`builder/tools.py` — "a tool reports, never raises"),
  so it cannot satisfy D2.
- **`read_website_content`** is the library tool (`scrape_website` in the
  document; `ScrapeWebsiteTool.name` at runtime) pointed at
  `https://sounding-line.invalid/shoals`, with
  `tool_failure_policy: "raise"`. It raises `ValueError`, which is D2.

  Note for the record: `inject.md` predicted the runtime name would be
  `Read website content`; it is `read_website_content`. Either way it is the
  **server's** name, never the author's.

## Screenshots and the observation ids each shows

| file | URL | shows |
| --- | --- | --- |
| `C2-invented-names.png` | the trace URL above | all three invented strings verbatim in one view: node SPAN **`chart_the_shoals`** `789867469c2df048` (ERROR), AGENT **`Tidewater Cartographer`** `a6280bb92209fb0a` (ERROR), TOOL **`sounding_line_lookup`** `ac336998a8cb5c64` |
| `D2-tool-error.png` | the same view | TOOL **`read_website_content`** `0eb0d52dff1e8883` at ERROR nested under the AGENT, and what the agent did next: `AGENT_CALL` ERROR then `NODE_END` ERROR — it gave up, it did not retry (`retry.max_retries = 0`, `on_error: "fail"`) |
| `D2-tool-error-detail.png` | `?observation=0eb0d52dff1e8883` | that TOOL observation open: `Error: ValueError("Could not resolve hostname: 'sounding-line.invalid'")`, `input` as `arg_keys`/`arg_chars`/`arg_fingerprint` under the default content policy, and metadata `observation_role: "tool"`, `event_type: "TOOL_CALL"`, `frame_kind: "tool"`, `null_fields: ""` |

## Other ids

task SPAN `bfd8a2ef290c826c` (its name is the task **description** — an
authored node's task has no separate name), node SPAN `789867469c2df048`,
run SPAN `6294c8c6a2958199`, GENERATIONs `…` (2, one per agent turn).

## C2's absence proof

`absent-before.txt` — `git grep` at the pre-Task-3 commit `b65bd65` answers
**no match** over the whole tree for `Tidewater Cartographer`,
`chart_the_shoals`, `sounding_line_lookup` and `sounding line`; re-run at
`e68dac4` over `src frontend/src data tests agents` it still answers no match.
