# 09 — Compiler

Flow JSON → CrewAI, cycle detection, preview. Written 2026-09-02 against
`25634c0`. Owns contract **C5**. Consumes C1, C3, C4, C11, C12.

## Problem

The compiler that exists is the strongest part of the builder and it cannot
compile the thing the gauntlet is about. `compile_document` turns a
`BuilderDocument` into a `crewai.flow/v1` dict — `schema`, `name =
builder_<id>_v<version>`, a `dict` state seeded by `_Plan.state_default()`,
`config.max_method_calls = (1 + MAX_CYCLE_ITERATIONS) ** cycles`, and one
method per node, two per gate (`compiler.py:234-244`, `:726-774`, `:786-797`,
`:436-440`). Every method's `do.ref` is one of exactly ten compiler-owned
entrypoints (`config.py:2046-2059`), re-asserted on the emitted definition
(`assert_action_refs`, `compiler.py:319-350`); `call: "script"` is refused
outright (`:334-338`); `lint_gates` (`:270-316`) refuses the one gate shape
CrewAI runs while logging `severity="error"`; namespaces are proved disjoint
(`:353-369`) and every router is proved to declare what it emits
(`:372-396`).

What it cannot express:

- An agent the author wrote. `run_agent` receives an `agent_key` into `agents.yaml` and nothing else (`runtime.py:406-439`); the `with:` block for an agent node carries `agent_id`, `tier`, `tools`, `max_iter`, `guardrail_max_retries`, `prompt_inputs` — no text.
- A crew the author composed. `run_crew` calls `<Class>().crew()` with zero arguments (`runtime.py:468`) and **ignores** the `tier` / `max_iter` it was passed (`:441-468`).
- A model. `LLM(model=_model_for(tier))` and nothing else (`runtime.py:414`).
- A tool that is not one of three names, an MCP server, a skill, a credential.
- A step that can fail without failing the run, a retry, an `or_` join (`'any'` is refused at parse, `document.py:533-559`), an authored state schema, a re-run from a node.
- A human-readable rendering of what the canvas became.

## Scope

Compile authored `agent` and `crew` nodes, attachment nodes folded into their
agent, per-node `llm`, `retry`, `on_error`, `or_` joins, `json_schema` state,
the derived replay plan for `resume_from` and `node_test`, the eleventh action
ref, the code preview, and the determinism harness that answers rubric 11.

## Out of scope

- Executing anything. The compiler emits a definition; `10-runtime.md` runs it.
- Resolving a credential. The compiler carries `credential_id`s and never sees a secret (C4).
- Deriving a topology from a decorated `Flow` class. `descriptor.py` never calls `build_graph_descriptor`, and the measured cost of that mistake — the validator suite going from **809 OK to 480 run / 77 errors across 28 modules** because the overlay assertion raises inside a module-level constant — is in the module's own docstring (`descriptor.py:3`, CLAUDE.md §14).
- A `script` action, a `code` action with author text, or any `do.ref` outside `BUILDER_ACTION_REFS`.

## Design

### D1 — Authored nodes compile through the same two entrypoints, with the text in `with:`

`runtime:run_agent` and `runtime:run_crew` keep their names and gain
arguments. For a library node the `with:` block is unchanged. For an authored
node the compiler emits the authored fields, the `llm` dict, the folded
attachment lists and the credential ids as `with:` values — **values, never
names** — so `assert_action_refs` still sees one of eleven refs and the
canvas still carries no Python (`AGENTS.md:67`, kept by
`00-architecture.md` D2). The entrypoint decides which branch it is in by the
presence of `agent_id` / `crew_id` versus `role` / `members`, mirroring the
parser's exactly-one rule (C1). Rationale: one entrypoint per kind is what
`assert_action_refs` and `BUILDER_ACTION_REFS` were designed to bound; two
refs per kind would double the allowlist for no security gain.

### D2 — Attachments are folded, never emitted

`tool`, `mcp` and `skill` nodes are not Flow methods. `_Plan` collects the
attachment edges (target port `attach`) per agent and emits them into that
agent's `with:` as `tools: [{tool_id, credential_id, config}]`,
`mcps: [{server_id, tool_names}]`, `skills: [skill_id]`. A `member` agent
(target port `member` on a crew) is likewise folded into the crew's
`members: [...]` and is **not** a method. `bounds.py` already refuses the
shapes that would make this ambiguous (`attach-target-not-agent`,
`member-agent-has-flow-edges`, C8); the compiler asserts them again on the
plan because two independent checks agreeing is the whole guarantee
(`compiler.py:446-452` already does this for identifiers).

### D3 — `on_error: 'route'` is the gate shape, reused

Only a `@router` can choose an event. A step whose `on_error` is `'route'`
therefore compiles to **two** methods — the step, and a paired deterministic
router `n{i}_route_err_{id}` that reads `err__<node>` from state and emits
`e{i}_ok` or `e{i}_error` — exactly the pause-plus-router shape gates already
use (`compiler.py:436-440`). Downstream listeners on the node's `out` port
listen to `e{i}_ok`; listeners on its `error` port listen to `e{i}_error`.
The step method itself catches, records `err__<node>` and returns normally;
it never raises past the router. `_assert_routers_declare_what_they_emit`
covers the new router with no change. A node with `on_error: 'fail'` (the
default) compiles as today and an exception fails the run.

### D4 — Retry is inside the entrypoint, and the compiler's job is to price it

`retry: {max_retries, backoff_seconds, fallback_model}` travels in `with:`.
The loop runs inside `run_agent` / `run_crew` (`10-runtime.md` D3) because a
retry that re-enters a Flow method would need CrewAI to re-fire a listener,
which is the mechanism closed item 35 had to work around. The compiler's
contribution is `modelled_calls` (FD6): calls multiply by `max_retries + 1`,
and a fallback model is priced at the **dearer** of the two so the static
estimate stays a worst case (`budget.py:105-125` shape, extended).

### D5 — `or_` joins are allowed where they are safe, and the compiler says where that is

`joins[node] = 'any'` compiles to `or_(...)`. CrewAI adds a multi-event
`or_()` listener to `_fired_or_listeners` on first fire and skips it after
(`crewai/flow/runtime/__init__.py:3288-3297`, verified at 1.15.18 — closed
item 35). Two consequences the compiler enforces: an `or_` join may not be a
loop closer (the loop closer must be a router, `bounds.py:611-631`, and a
router is exempt via `and not is_router`), and an `or_` join inside a cycle
compiles with the `_discard_or_listener` re-arm the validator already uses
(`validator_flow.py`, item 35) emitted as a `with:` flag the entrypoint
honours. The `document.py:533-559` refusal of `'any'` is lifted; the reason
it recorded is now a compiled rule rather than a parse refusal.

### D6 — Authored state is `json_schema`, reserved keys are refused

`document.state` (C1) is a JSON Schema object. The compiler emits
`FlowDefinition.state = {type: "json_schema", schema, default}`
(`crewai/flow/flow_definition.py:133`). Reserved keys — every `out__*`,
`err__*`, `turns__*`, `__builder__`, and the input field — are refused with
`state-key-reserved` (C8) because `_Plan.state_default()` owns them
(`compiler.py:726-774`). A `pydantic` state is not offered: it needs a Python
class the author cannot write (`docs/crewai-notes.md` §11.8).

### D7 — The eleventh ref: `runtime:replay_output`

`resume_from {run_id, node_id}` and `node_test {node_id}` compile a
**derived plan**: the same document, in which every node upstream of the
target — `ancestorsOf` on the flow edges, attachment and member edges
excluded — is emitted with `do.ref = runtime:replay_output` and
`with: {node_id, source: 'run' | 'test_input'}`. The entrypoint writes
`out__<node>` from the source run's last `flow_states` row
(`persistence.load_state`, `persistence.py:623`) or from the saved test
input's mocked values (C7) and returns, so downstream listeners fire exactly
as they would after a real run. Nothing about this touches CrewAI's own
resume; `Flow.from_pending` stays what it is for gates
(`builder_runner.py:109-119`). The derived plan is compiled fresh per
request and is never published or rehydrated.

### D8 — The code preview is a renderer, not an executor

`GET /api/builder/workflows/{id}/compiled` (C7) returns the compiled
`crewai.flow/v1` document as YAML — the literal thing the runtime loads
(`Flow.from_declaration(contents=…)`, `builder_runner.py:92-107`) — and a
Python rendering: for each method, the `Agent(...)`, `Task(...)`,
`Crew(...)`, `LLM(...)` constructors the entrypoint will build, with
`credential_id` values rendered as `<credential: label>` and never the
secret. The rendering is produced by walking the definition; no Python is
evaluated, and the file ends with a banner saying it is a reading aid. A
power user who pastes it into a script gets a working program minus the
credentials, which is the point.

### D9 — Rubric 11: identical result, 20 of 20

A fixture set of twenty documents under `tests/builder/fixtures/rubric11/`
— the four templates, the idea validator, and fifteen generated shapes
covering every kind, both families, both join types, an error router, a
retry with fallback, a hierarchical crew, a replay plan — is run through the
synthetic factories (`use_crew_factories`, `runtime.py:476-484`) with fixed
test inputs and `SYNTHETIC_BRANCH_DELAY_SECONDS=0`. The synthetic double
returns deterministic text keyed on `(node_id, input hash)`, so **the
compiled definition, the frame sequence (`node_id`, `event_type`, `stage`)
and the final result body** are all byte-comparable to committed goldens. A
determinism harness runs each fixture twice in one process and once in a
fresh process and asserts equality all three ways. A double that diverges
from its subject certifies nothing (gotchas 22), so the double's output
shape is the same `ValidationReport`-shaped body the real runner produces.

## Interfaces

### C5 — compiled definition and action refs (owned)

`BUILDER_ACTION_REFS` (`config.py:2046-2059`) becomes eleven:

| ref | change |
| --- | --- |
| `runtime:seed_input` | unchanged |
| `runtime:run_agent` | gains authored `with:` (below) |
| `runtime:run_crew` | gains authored `with:`; the library branch now honours `max_iter` and refuses `tier` with a problem rather than ignoring it |
| `runtime:render_gate`, `gates:GATE_PROVIDER`, `runtime:route_gate` | unchanged |
| `runtime:route_branch`, `runtime:transform`, `runtime:emit_output` | unchanged |
| `runtime:rejoin` | still reserved, still never emitted |
| **`runtime:replay_output`** | new (D7) |

The budget response (`BuilderBudget`, `budget.py:69-102` — `static_cost_usd`,
`floor_cost_usd`, `modelled_calls`, `billable_nodes`, `escalation_nodes`,
`cycles`, `unpriced_models`) gains `per_node: {node_id: {calls: int, usd:
float}}`, requested by 04 for the inspector's per-node cost line and
integrated here by the Integrator. It is the same per-node figure the total
already sums, exposed rather than recomputed on the client (R6 stands: the
client renders it and never derives it).

Authored agent `with:` block (all values from C1; `credential_id`s from C4;
model ids from C3; `server_id` / `tool_names` from C12; `skill_id` from C11):

```yaml
with:
  node_id: draft
  role: "…"            # ≤ BUILDER_MAX_PROMPT_CHARS (C1)
  goal: "…"
  backstory: "…"
  task: {description: "…", expected_output: "…", output_schema: {…} | null, markdown: false, async_execution: false}
  llm: {model: "openrouter/deepseek/deepseek-v4-flash", credential_id: null, temperature: 0.2, max_tokens: 4096,
        top_p: null, frequency_penalty: null, presence_penalty: null, stop: [], seed: null, timeout: null,
        response_format: null, reasoning_effort: null}
  advanced: {max_iter: 4, max_rpm: null, max_execution_time: null, allow_delegation: false, memory: false,
             cache: true, respect_context_window: true}
  expert: {reasoning: false, max_reasoning_attempts: null, multimodal: false,
           system_template: null, prompt_template: null, response_template: null, function_calling_llm: null}
  tools: [{tool_id: "serper_search", credential_id: "cr_…", config: {n_results: 5}}]
  mcps: [{server_id: "mcp_…", tool_names: ["search", "fetch"]}]
  skills: ["sk_…"]
  retry: {max_retries: 1, backoff_seconds: 2.0, fallback_model: "openrouter/z-ai/glm-5.3-flash"}
  on_error: fail | route
  guardrail_max_retries: 2
  tool_failure_policy: warn
  prompt_inputs: {topic: "${state.out__idea}"}
```

Authored crew `with:` block: `node_id`, `members: [<agent with-blocks as above, minus retry/on_error>]`,
`task_order: [member node ids]`, `process: sequential | hierarchical`,
`manager_llm: {…} | null`, `manager_agent: <member id> | null`,
`memory`, `cache`, `max_rpm`, `planning`, `planning_llm`, `retry`, `on_error`.

Error router (D3): method `n{i}_route_err_{id}`, `listen: [n{i}_{id}]`,
`do: {ref: runtime:route_branch, with: {node_id, key: err__{id}, branches: [{label: ok, op: eq, value: null}, {label: error, op: otherwise}]}}`,
`emits: [e{i}_ok, e{i}_error]`. Out-ports on an `on_error: route` node are
`['out', 'error']`; `out` maps to `e{i}_ok`, `error` to `e{i}_error`.

Join (D5): `listen: {and: [...]}` for `'all'`, `listen: {or: [...]}` for `'any'`.

State (D6): `state: {type: json_schema, schema: <document.state>, default: <plan.state_default() merged with schema defaults>}`.

Derived plan (D7): `name = builder_<id>_v<version>_replay_<node>`; upstream
methods `do: {ref: runtime:replay_output, with: {node_id, source}}`;
`config.max_method_calls` recomputed on the derived graph.

Preview (D8): `{yaml: str, python: str, definition: dict, generated_at, document_version}`.

### Consumed

C1 (document v2, from 03), C3 (registry — `compile_document` refuses a
model not in the snapshot with `model-unknown`, over the ceiling with
`model-over-ceiling`, lacking `supports_tools` when tools are attached with
`model-lacks-capability`), C4 (`credential_id` opaque), C11, C12.

## Acceptance criteria

1. `python -c "from brief_crew.config import BUILDER_ACTION_REFS; print(len(BUILDER_ACTION_REFS))"` prints `11`, and `tests/builder/test_compiler.py` asserts every emitted `do.ref` is in it, including the derived plan.
2. `tests/builder/test_compiler.py::AuthoredAgentTests`: an authored agent node compiles to one `run_agent` method whose `with:` carries every field in C5 and **no** `agent_id`; a library node carries `agent_id` and no `role`; a node with both is refused at parse (C1), never reaching the compiler.
3. `tests/builder/test_compiler.py::AttachmentFoldTests`: `tool`, `mcp`, `skill` nodes never appear in `methods`; their data appears in the target agent's `with:`; a `member` agent never appears in `methods` and appears in the crew's `members` in `task_order`.
4. `tests/builder/test_compiler.py::ErrorRouterTests`: `on_error: route` emits exactly two methods and `_assert_routers_declare_what_they_emit` passes; `on_error: fail` emits one; an edge from `error` on a `fail` node is refused by bounds (`error-port-unconnected` is a warning on a `route` node with no error edge).
5. `tests/builder/test_compiler.py::OrJoinTests`: `'any'` compiles to `listen.or`; an `'any'` join that closes a loop is refused; a compiled `or_` inside a cycle carries the re-arm flag; a real `Flow.from_declaration` of that definition runs the join twice in a two-lap synthetic loop (the closed-item-35 reproduction, run against the compiled shape).
6. `tests/builder/test_compiler.py::StateSchemaTests`: `document.state` becomes `json_schema` state; every reserved key is refused with `state-key-reserved`; an invalid schema with `state-schema-invalid`.
7. `tests/builder/test_compiler.py::ReplayPlanTests`: for a fixture with a chain `a → b → c`, `resume_from c` emits `a`, `b` as `replay_output` and `c` unchanged; a `node_test b` emits `a` as `replay_output`, `b` unchanged, and **no** `c`; the derived plan passes all four post-emission assertions.
8. `tests/builder/test_budget.py`: a node with `retry.max_retries = 2` prices `3×` calls; a hierarchical crew of 3 prices `3` manager calls per task; a `:nitro` model applies `NITRO_PRICE_FACTOR`, a non-nitro model does not; the frontier document from `test_budget.frontier_document` is still refused at `$10` with the 1.25 margin.
9. `tests/builder/test_preview.py`: the YAML preview round-trips through `FlowDefinition.model_validate`; the Python preview contains one `Agent(` per authored agent, one `Crew(` per crew, `<credential: …>` for every credential id and **no** secret material, verified by seeding a credential whose value is a sentinel string and asserting the sentinel is absent.
10. `tests/builder/test_rubric11.py`: twenty fixtures, each compiled and run through the synthetic factories twice in-process and once in a subprocess; definition, frame sequence and result body byte-equal to committed goldens all three ways. **Rubric 11: 20/20.**
11. `tests/builder/test_from_document.py` still never imports `build_graph_descriptor`, and the validator suite count is unchanged by this plan (re-run `unittest discover`; the 809→480 failure shape is the regression to watch).
12. `tests/builder/test_client_fixtures.py` passes after the problem-code union grows (C8, owned by 12).

## References

- `src/brief_crew/builder/compiler.py:234-244, 270-316, 319-350, 334-338, 353-369, 372-396, 436-452, 611, 626-633, 648-653, 726-774, 786-797, 823-840, 928-973`
- `src/brief_crew/builder/runtime.py:170-185, 297-328, 406-468, 476-488, 588-952`
- `src/brief_crew/builder/{bounds.py:611-631, budget.py:105-125, 197-248, document.py:533-559, descriptor.py:3, 282-321}`
- `src/brief_crew/config.py:1863, 1869, 1883, 1894-1895, 2046-2059`
- `src/brief_crew/service/{builder_runner.py:92-136, persistence.py:101-110, 623}`
- `crewai/flow/flow_definition.py:81, 133, 277, 348, 399, 465, 710`; `crewai/flow/runtime/__init__.py:3288-3297`; `docs/crewai-notes.md` §5, §11
- `docs/flow-builder-spec.md` R6, R7; CLAUDE.md §14 (the four measured rules), closed item 35; `docs/gotchas-and-insights.md` 22
- Gauntlet: "Flow control", "Compiler correctness" (rubric 11), "Forbidden — a parameter rendered in the UI that the compiler ignores"

## Status

**Planned · 2026-09-02.** No code.

Contract notes for 00: none new. C5 is spelled out above; C7's `compiled`
endpoint is named in 10 and consumed here.

Open decisions for the owner:

- Whether a crew node's **library** branch should refuse `tier` (this plan) or start honouring it by rebuilding the library crew's LLMs — the latter reaches into `validator_crew.py:155-159, 194` and changes a hand-written crew's behaviour from a canvas.
- The `or_`-inside-a-cycle re-arm depends on a private CrewAI method (`_discard_or_listener`), the accepted cost recorded at closed item 35. If that is unacceptable, `'any'` joins are refused inside cycles and allowed elsewhere.

### Owner decisions answered — 2026-09-04

**Decision 12 — refuse.** Honouring `tier` means rebuilding the crew's LLMs from
outside the crew, and the crew library is the one place in the builder where the
code is ours and not the author's.

**Decision 13 — accept, with a guard test.** CLAUDE.md's closed item 35 already
accepted exactly this dependency after prototyping the alternative: the router
variant costs two pass-through nodes carrying no agent, no model and no
decision, plus lockstep edits to seven files. The guard test's failure message
must name the router variant as the replacement, as item 35's does.
