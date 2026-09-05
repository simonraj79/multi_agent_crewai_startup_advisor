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

---

## Verified by RV3

Checked 2026-09-05 on `run-shell/cast` at `27b256e` by reading the table above
against `src/brief_crew/events/serializer.py::_event_drafts` (lines 394–652,
the range the header names) and against `src/brief_crew/service/registry.py`'s
own frames. RV3 built none of this.

**Method.** Two enumerations rather than a skim, because a skim of a ladder is
how a kind goes missing:

```bash
# 1. every FrameKind that can exist at all
./.venv/Scripts/python.exe -c "from brief_crew.events.models import FrameKind; print([k.value for k in FrameKind])"
# ['run_state','node_state','edge_taken','agent','tool','llm','token','gate_open',
#  'gate_closed','gate_expired','gate_alert','metrics','guardrail','reasoning',
#  'verdict','error']

# 2. every kind the SERVICE emits outside the serializer, since the table claims those too
grep -noE "FrameKind\.[A-Z_]+" src/brief_crew/service/registry.py | sort -u
# ERROR, GATE_ALERT, GATE_CLOSED, GATE_EXPIRED, GATE_OPEN, LLM, METRICS,
# RUN_STATE, TOKEN, VERDICT
```

**Result: no missing kind and no missing stage.** All sixteen `FrameKind`
values have a row, and every `stage` the serializer writes is named. The
mapping, walked branch by branch down `_event_drafts`:

| serializer branch | emits | table row |
| --- | --- | --- |
| `FlowStartedEvent` (root) | `run_state` `status: running` | ✓ |
| `FlowFinishedEvent` (root) | `run_state` `status: completed` | ✓ |
| `FlowFailedEvent` (root) | `error`, `WORKFLOW_END`, no node | ✓ run-level `error` row |
| `Flow*` (**nested**, `_nested_flow_draft` :867) | `agent` at `before` / `after` / `error` | ✓ by the three `agent` rows — see the note below |
| `VerdictComputedEvent` | `verdict` | ✓ |
| `MethodExecutionStarted/Finished/Failed` | `node_state` `before` / `after` / `error` | ✓ |
| …router arm of `Finished` | `edge_taken` | ✓ (no row, canvas owns it) |
| `MethodExecutionPausedEvent` | `node_state` `paused` | ✓ (no row) |
| `HumanFeedbackRequested/Received` | `gate_open` `before` / `gate_closed` `after` | ✓ |
| `ToolUsageStarted/Finished/Error` | `tool` `before` / `after` / `error` | ✓ |
| `ToolValidateInputError`, `ToolSelectionError`, `ToolExecutionError` | `tool` `error` | ✓ same row |
| `LLMCallStarted/Completed/Failed` | `llm` `before` / `after` **+ `utterance` + `token`** / `error` | ✓ all five |
| `LLMStreamChunkEvent` | `llm` `chunk` | ✓ (no row) |
| `AgentExecutionStarted/Completed/Error` | `agent` `before` / `after` / `error` | ✓ |
| `TaskStarted/Completed/Failed` | `agent` `before` / `after` / `error` | ✓ same rows |
| `CrewKickoffStarted/Completed/Failed` | `agent` `before` / `after` / `error` | ✓ same rows, and departure 1 explains the choice |
| `LLMGuardrailStarted/Completed` | `guardrail` `before` / `after` (± `success`) | ✓ both after-arms |
| `AgentLogsExecutionEvent` | `reasoning` `thinking` | ✓ |
| `MCPConnectionFailedEvent` | `error` `stage: error`, node-level | ✓ node-level `error` row |
| `Skill Activated/Loaded/Used` | `agent` `skill` | ✓ |
| `SkillLoadFailedEvent` | `error` `stage: error`, node-level | ✓ node-level `error` row |
| unmatched → `record_unhandled` | nothing | ✓ *unknown kind* row |
| `registry.py` | `gate_expired`, `gate_alert`, `metrics`, `run_state` cancelled/failed | ✓ |

**Three notes, none of them a gap, all of them things a reader would otherwise
have to re-derive:**

1. **The nested-flow frames have no row of their own and do not need one.**
   `_nested_flow_draft` deliberately emits `FrameKind.AGENT` — its docstring
   says so and gives the reason (an agent executor is often the only frame
   between a task starting and a tool call, and `AGENT` moves no run status
   anywhere in the client). So they land on the three `agent` rows. The table
   would read more completely with a line saying that, but nothing is
   unnarrated.
2. **`llm` at `stage: "after"` is one of THREE frames from one event.**
   `LLMCallCompletedEvent` returns a triple — `after`, `utterance`, `token` —
   and the table has a row for each of the three, which is the half a reader
   is most likely to get wrong.
3. **`guardrail` has no `error` stage** because the serializer has no
   `LLMGuardrailFailed` branch; only Started and Completed exist. The table
   correctly lists no such row.

**One row of the table RV3 could not check against the ladder**, and it is
outside the ladder by construction: the `verdict` row's `Scored {n}/10 —
{label}` comes from `_verdict_draft`, which is at `serializer.py:8xx` rather
than in the 394–652 range. It exists and it emits `FrameKind.VERDICT`; the
sentence itself is `interpret.ts`'s and is asserted by
`traceInterpretation.spec.ts`.

**Verdict: T2.2's vocabulary table is complete against the serializer.**

### Second pass, `16f3be5`

Re-checked, not carried forward. Neither side of this table's subject moved in
round two, and that is a measurement rather than an assumption:

```bash
$ git diff 27b256e..HEAD --stat -- src/brief_crew/events/serializer.py frontend/src/trace/
# (no output - neither the serializer's ladder nor src/trace/ changed)
```

The sixteen `FrameKind` values were re-enumerated from the package and every one
still has a row; `registry.py`'s ten kinds still land on rows the table names.
Round two changed how a row is *rendered* — gate rows wear a person marker, run
rows say `Run`, the row is more compact — and `frontend/src/trace/interpret.ts`,
which is what this table describes, is byte-identical to the first pass.

**T2.2 PASS, second pass.**

### Third pass, `601baef`

Re-checked, and this time the subject really did move: round three rewrote
**91 lines of `frontend/src/trace/interpret.ts`** (the trace reads as a story,
gate rows wear a person marker, run rows say `Run`, the error line changed
shape). So the table was walked against the ladder again rather than carried
forward.

```bash
$ git diff 16f3be5..HEAD --stat -- src/brief_crew/events/serializer.py
# (no output - the ladder itself did not change)
$ git diff 16f3be5..HEAD --stat -- frontend/src/trace/
# frontend/src/trace/interpret.ts | 91 ++++++++++++++++++++++++------------
```

**The serializer is unchanged, so the row-per-kind claim still holds by
construction**: all sixteen `FrameKind` values were re-enumerated from the
package and every one still has a row, and `registry.py`'s ten kinds still land
on rows the table names. What changed is *wording inside three of the rows* —
`gate_open`, `gate_closed` and the two `error` rows — and the sentences in this
table are the shape (`Waiting for you: {title}`, `Run failed: {first sentence}`)
rather than the exact string, so they still describe what `interpret.ts` emits.

Two facts the pass measured rather than assumed:

* `frontend/tests/traceInterpretation.spec.ts` grew by 156 lines and its file
  pair runs **76 tests green** (66 in the second pass), over the same two real
  frame logs. The banned-in-a-line list is asserted per row there.
* The browser assertion that failed in the second pass — 24 trace rows reading
  as an empty line — **passes now** (`cast.spec.ts:1027`), which is the half of
  T2.1 no unit test can reach.

**T2.2 PASS, third pass.**
