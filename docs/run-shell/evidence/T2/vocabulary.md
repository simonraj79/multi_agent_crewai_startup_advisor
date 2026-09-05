# T2.2 — the trace vocabulary, as built

Written by W3 on `run-shell/cast`. This is the table RV checks against the
ladder in `src/brief_crew/events/serializer.py` (`_event_drafts`, roughly lines
424–650) and against `src/brief_crew/service/registry.py`'s own gate frames.

The implementation is `frontend/src/trace/interpret.ts`; the assertions are
`frontend/tests/traceInterpretation.spec.ts`, run over two real frame logs
(`frontend/tests/fixtures/serializerFrames.ndjson`, produced by the real Python
serializer over real CrewAI events, and `frontend/tests/fixtures/syntheticRun.ndjson`,
what the synthetic backend actually serves).

## The two rules the table obeys

1. **The verb comes from the frame kind and its stage.** Nothing in
   `src/trace/` knows which flow is running. The single table that is not keyed
   on a frame field is the tool-verb table, and every key in it is a word the
   framework itself puts inside a tool id (`search`, `scrape`, `write`, `run`,
   `check`) — never a role, task, crew or node name. A tool nobody here has
   heard of falls through to "using", so a flow invented after this was written
   narrates itself with no edit. G2's grep over `frontend/src/trace/` returns
   zero product hits.
2. **The subject is the agent's identity**, resolved in one ladder:
   `details.agent_role` (CrewAI stamps it on every agent, task, tool and LLM
   event via `serializer._carry_identity`) → the descriptor node's declared
   `agent_role` (`service/models.py::GraphNode.agent_role`) → the node's label →
   nothing, which makes it a run-level line with no avatar. A node id reaching
   the last rung is humanised, never printed raw.

`{Who}` below is that resolved identity. `{Task}` is `humaniseTask()` of
`details.task` or `details.task_name`. `{Tool}` is `humaniseTool()` of
`details.tool`. All three come from `frontend/src/utils/humanise.ts`.

## The table

| Frame kind | `details.stage` | Line | Tone | Coalesce |
| --- | --- | --- | --- | --- |
| `run_state` | `plan` | *(no row — the stage lane owns it)* | — | — |
| `run_state` | `status: running` / `WORKFLOW_START` | `Run started` | info | — |
| `run_state` | `status: completed` | `Run finished` | info | — |
| `run_state` | `status: cancelled` / `cancelling` | `Run cancelled` | warn | — |
| `run_state` | `status: failed` | `Run failed: {first sentence}` | error | — |
| `node_state` | `before` | `{Who} started` | info | `open:{node}`, precedence 0, clears `close:{node}` |
| `node_state` | `after` | `{Who} finished` | info | `close:{node}`, precedence 0, clears `open:{node}` |
| `node_state` | `error` (or level `ERROR`) | `{Who} could not finish: {first sentence}` | error | none — a failure is never coalesced away |
| `node_state` | `paused` | *(no row — the gate frame that follows says what it is parked on)* | — | — |
| `agent` | `before` | `{Who} started on {Task}` / `{Who} started` | info | `open:{node}`, precedence 1–4, clears `close:{node}` |
| `agent` | `after` | `{Who} finished {Task}` / `{Who} finished` | info | `close:{node}`, precedence 1–4, clears `open:{node}` |
| `agent` | `error` | `{Who} could not finish {Task}: {first sentence}` | error | none |
| `agent` | `skill` | `{Who} {skill_event} the {Skill} skill` | info | none |
| `agent` | *(anything else)* | `{Who} is working` | info/error | none |
| `tool` | `before` | `{Who} is {gerund} “{query}” with {Tool}`; with no query, `{Who} is {gerund} with {Tool}`, or `{Who} is using {Tool}` for the neutral verb | info | call key, precedence 0 |
| `tool` | `after` | `{Who} {past} “{query}” — {outcome}` | info/warn | call key, precedence 100 |
| `tool` | `error` | `{Who}'s {Tool} call failed` | error | call key, precedence 100 |
| `llm` | `before` | `{Who} is thinking` | info | call key, precedence 0 |
| `llm` | `after` | `{Who} thought for {duration}` / `{Who} finished thinking` | info | call key, precedence 100 |
| `llm` | `error` | `{Who}'s model call failed` | error | call key, precedence 100 |
| `llm` | `chunk` | *(no row — it streams to the dialogue rail)* | — | — |
| `llm` | `utterance` | *(no row — the dialogue rail's whole subject)* | — | — |
| `guardrail` | `before` | `{Who}'s work is being checked` | info | call key, precedence 0 |
| `guardrail` | `after`, `success: true` | `{Who}'s work passed the check` | info | call key, precedence 100 |
| `guardrail` | `after`, `success: false` | `{Who}'s work failed the check — trying again (attempt N)` | warn | call key, precedence 100 |
| `reasoning` | `thinking` | `{Who} is reasoning` | info | `think:{node}`, scope `tail` |
| `gate_open` | `before` | `Waiting for you: {title}` | you | `gate:{gate_id}` |
| `gate_closed` | `after` | `You approved` / `You asked for changes` / `You answered: {decision}` | you | none |
| `gate_expired` | — | `The review window for {title} expired` | warn | none |
| `gate_alert` | — | `{title} is still waiting for you — {duration} past the deadline` | warn | none |
| `verdict` | — | `Scored {n}/10 — {label}` | info | none |
| `edge_taken` | — | *(no row — the canvas draws the traversal)* | — | — |
| `token` | — | *(no row — the spend panel owns it)* | — | — |
| `metrics` | — | *(no row — the spend panel owns it)* | — | — |
| `error` | run-level (`WORKFLOW` event, or no node) | `Run failed: {first sentence}` | error | none |
| `error` | node-level | `{Who} hit an error: {first sentence}` | error | none |
| *unknown kind* | — | *(no row)*, unless level `ERROR`, which takes the `error` row above | — | — |

### The tool verb table

Chosen from the words inside the emitted tool name, first match winning. The
name is split on non-alphanumerics and on camel boundaries first, so
`FirecrawlScrapeWebsiteTool`, `scrape_website` and `scrape-website` all reach
the same row.

| Words in the tool name | Gerund | Past |
| --- | --- | --- |
| `search` `query` `lookup` `find` `research` `retrieve` | searching | searched |
| `scrape` `read` `fetch` `crawl` `browse` `load` `open` | reading | read |
| `write` `save` `store` `export` `record` `upload` | saving | saved |
| `run` `exec` `execute` `eval` `compute` `calculate` | running | ran |
| `analyse` `analyze` `assess` `check` `inspect` `review` `audit` `classify` | checking | checked |
| *(anything else)* | using | used |

### What a finished tool call reports

Read from the envelope the serializer merges into `details` at
`stage: "after"` (`serializer.py::tool_envelope`), in this order:

| Condition | Suffix |
| --- | --- |
| `failure` non-empty | `— it failed` |
| `tool_status` present and not `ok` | `— {humanised status}`, e.g. `— rate limited` |
| `result_count: 0` | `— nothing found` (or `— nothing in the cache`) |
| `result_count: n` | `— n results` / `— 1 result`, plus ` from the cache` when `from_cache` |
| `from_cache` alone | `— from the cache` |
| nothing of the above | no suffix |

## Coalescing — why some frames rewrite a row instead of adding one

- **A call is one row.** `before` writes the row, `after`/`error` rewrites it in
  place. Two rows for one call is how a nine-call run read as eighteen events.
  The key is `traceCallKey()`: `{kind}:{call_id}` when the event carries one,
  else `{kind}:{node}:{tool|guardrail|model}` — plus `#{retry_count}` for a
  guardrail, so a rejected check and its retry are two rounds and not one row.
- **The most specific view of one moment wins.** A node starting, a crew
  starting, a task starting and an agent starting are four frames about one
  event. They share `open:{node}`, and `precedence` (role +2, task +1, base 1;
  a `node_state` scores 0) decides which sentence survives, whichever order they
  arrive in. A coarser frame arriving later is dropped, not appended.
- **A finished thing retires its key** (`precedence >= 100`), so the same agent
  calling the same tool three times gets three rows. Collapsing them would hide
  two thirds of a branch's spend — which is exactly the figure the first paid
  run went looking for.
- **A visit retires the other half of the previous one** (`clears`): an `open`
  row clears `close:{node}` and a `close` row clears `open:{node}`, so a node
  the flow revises through gets one pair of rows per visit rather than silently
  rewriting the first visit's.
- **Reasoning merges only while it is still the newest row** (`scope: 'tail'`).
  It is the highest-volume kind there is; a run-scoped key would rewrite a row
  the reader scrolled past ten rows ago.

## What is banned from a line, and where the payload went

Asserted for every row produced over both fixtures:

- at most **140** characters (`MAX_TRACE_LINE_CHARS`);
- no literal `\n` / `\r` / `\t` escape — the serializer `json.dumps`es a
  non-string response, so these arrive as two characters and used to render as
  `\n` on screen;
- no real newline, and no run of whitespace;
- no `{"` — a serialised structure is never quoted as though it were a sentence;
- no `N in · N out` token counts;
- no SNAKE_CASE or snake_case identifier.

Nothing is dropped. Every row carries `raw` — the framework's own sentence, the
whole `details` payload pretty-printed, the model, the tool, the token counts,
the duration, the sequence number and the timestamp — behind a `<details>`
disclosure that is collapsed by default.

## Two departures from the brief, and why

1. **A crew kickoff does not get its own sentence.** The brief suggested
   "The {crew} crew is up". `CrewKickoffStartedEvent` puts the crew name in
   `frame.message` and nothing in `details` (`serializer.py:549`), so building
   that line means parsing framework prose — and the frame coalesces onto the
   same node as the agent frame that follows it anyway. It reads as
   `{Who} started` and is then replaced by the more specific line.
2. **`frame.message` is admitted in exactly one place: `gate_open`.** CrewAI's
   own gate frame carries the operator's question as the message and nothing in
   `details` (`serializer.py:466`), and unlike every other message on this
   ladder that one is authored text addressed to a person. The service's own
   `gate_open` carries `title` in `details` and is preferred when present.
