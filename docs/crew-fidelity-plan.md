# Crew fidelity + UX plan

Audited 2026-08-30 by four parallel agents against HEAD `1b79197`.

## The diagnosis

The console does not lack information. It **discards the same information three
times**:

1. CrewAI puts `agent_role`, `task_name`, `run_attempts`, `event_id`/`parent_event_id`
   on **every** event (`BaseEvent`). The serializer reads two of them only to hit
   two lookup tables that are empty in production, then throws all of them away.
2. What does survive — `query`, `tool_status`, `result_count`, `notes`,
   `from_cache`, `route`, `condition_type`, `nodes[]` — reaches the browser and
   the client never reads it. Zero references in `frontend/src`.
3. What the client does read, it renders at **4.7-7.8px**.

So "which agent is running, on which task, calling which tool, with which query,
and what came back" is answerable at the CrewAI layer and unanswerable on screen.

## Workstreams

### W1 - the event spine carries agent truth
- Frames carry `agent_role` / `task_name` as structured fields, not English prose.
- `duration_ms` on LLM frames (the number is already computed and discarded).
- New branches: `LLMGuardrail*` (retry visibility - the biggest cost blind spot),
  `AgentLogsExecutionEvent` (reasoning), `MethodExecutionPausedEvent` (native pause),
  `Tool*Error` (3 variants).
- A counter for unhandled event types, so the gap stops being invisible.

### W2 - the graph asserts only what it can prove
- `kind: "gate"` derived from `flow_definition().methods[...].human_feedback`,
  guarded against overlay drift.
- Overlay `model`/`tool` bound to the real crews by test.
- AND/OR and trigger conditions surfaced to the client.
- DONE: the two Brief-graph falsehoods corrected (`scrape_web` ran 3 agents, 2 of
  them escalation tier, behind a badge reading "Cheap tier").

### W3 - the double is as rich as its subject
`SyntheticValidatorRunner` emits 17 frames and not one tool, llm, token, agent or
metrics frame. Every W4 surface would be untestable on the free path. This is the
same trap as closed items 20 and 33.

### W4 - the UI
- Legible graph: tighter layout, zoom-aware detail, minimap.
- Node cards show live CrewAI state.
- Agent-first trace with tool query/status/results and per-node filtering.
- A real elapsed clock; honest cost (`null` is not `$0.0000`).
- The gate announces itself.
- Router decisions and the AND-join are drawn.
- CrewAI vocabulary throughout.
