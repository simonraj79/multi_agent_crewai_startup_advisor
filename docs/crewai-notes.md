# CrewAI notes — read from the installed package, not from memory

Pinned and verified on **2026-09-02** against the interpreter in `.venv`:

```text
crewai        1.15.18
crewai_tools  1.15.18
Python        3.13.5
```

Everything below was produced by introspecting that install (`model_fields`,
`inspect.signature`, and `grep` over `site-packages`). Where the gauntlet
document and the package disagree, **the package wins** — section 11 lists
every such disagreement. Regenerate the field tables with:

```powershell
.\.venv\Scripts\python.exe -c "from crewai import Agent, Task, Crew; [print(c.__name__, sorted(c.model_fields)) for c in (Agent, Task, Crew)]"
```

`docs/tech-stack.md` owns the version pins; this file owns what the API
actually looks like at those pins.

---

## 1. Agent — the gauntlet's three tiers, field by field

`crewai.Agent` is a pydantic model. Source: `crewai/agent/core.py`.

| Tier | Field | Exists | Type / default | Note |
| --- | --- | --- | --- | --- |
| Essentials | `role` | ✓ | `str`, required | |
| Essentials | `goal` | ✓ | `str`, required | |
| Essentials | `backstory` | ✓ | `str`, required | |
| Essentials | `llm` | ✓ | `str \| BaseLLM \| None = None` | **`None` resolves to the OpenAI env default.** Every compiled agent must carry an explicit `openrouter/…` LLM. |
| Essentials | `tools` | ✓ | `list[BaseTool] = []` | |
| Essentials | `skills` | ✓ | `list[Path \| Skill \| str] \| None` | Native SKILL.md support — see §7. |
| Advanced | `max_iter` | ✓ | `int = 25` | |
| Advanced | `max_rpm` | ✓ | `int \| None` | |
| Advanced | `max_execution_time` | ✓ | `int \| None` | seconds |
| Advanced | `allow_delegation` | ✓ | `bool = False` | |
| Advanced | `memory` | ✓ | `bool \| Memory \| MemoryScope \| MemorySlice \| None` | Unified memory. Not three toggles. |
| Advanced | `cache` | ✓ | `bool = True` | |
| Advanced | `verbose` | ✓ | `bool = False` | |
| Advanced | `respect_context_window` | ✓ | `bool = True` | |
| Expert | `reasoning` | ✓ | `bool = False` | |
| Expert | `max_reasoning_attempts` | ✓ | `int \| None` | |
| Expert | `multimodal` | ✓ | `bool = False` | |
| Expert | `allow_code_execution` | **✗ deprecated** | `bool \| None = False` | `core.py:279-282`: *"Deprecated. CodeInterpreterTool is no longer available. Use dedicated sandbox services instead."* Warns at `:407-410`. **Do not render it.** |
| Expert | `code_execution_mode` | **✗ deprecated** | `Literal['safe','unsafe']` | `core.py:305-308`, same reason. |
| Expert | `knowledge_sources` | ✓ | `list[BaseKnowledgeSource] \| None` | |
| Expert | `embedder` | ✓ | provider spec `\| None` | |
| Expert | `system_template` / `prompt_template` / `response_template` | ✓ | `str \| None` | |

Fields the gauntlet does not name but a builder needs:

| Field | Type / default | Why it matters |
| --- | --- | --- |
| `mcps` | `list[str \| MCPServerStdio \| MCPServerHTTP \| MCPServerSSE] \| None` | Native MCP — see §6. |
| `tool_failure_policy` | `ToolFailurePolicy \| None` | `ignore` / `warn` (default) / `raise` — see §8. |
| `max_retry_limit` | `int = 2` | Agent-level retry on execution error. |
| `guardrail` / `guardrail_max_retries` | `Callable \| str \| None` / `int = 3` | A `str` becomes an LLM guardrail **using the agent's own LLM**. |
| `function_calling_llm` | `str \| BaseLLM \| None` | Separate cheap model for tool-call formatting. |
| `use_system_prompt` | `bool = True` | |
| `inject_date` / `date_format` | `False` / `'%Y-%m-%d'` | |
| `planning` / `planning_config` | `False` / `None` | |
| `max_tokens` | `int \| None` | |
| `step_callback` / `callbacks` | callables | Event hooks; the repo uses the event bus instead. |
| `apps` | enterprise app list | CrewAI AMP only — not for this product. |

---

## 2. Task

`crewai.Task`, source `crewai/task.py`.

| Tier | Field | Exists | Type / default | Note |
| --- | --- | --- | --- | --- |
| Essentials | `description` | ✓ | `str`, required | |
| Essentials | `expected_output` | ✓ | `str`, required | |
| Essentials | `agent` | ✓ | `BaseAgent \| None` | Required for `sequential`; the manager assigns under `hierarchical`. |
| Advanced | `context` | ✓ | `list[Task] \| None \| NOT_SPECIFIED` | Renders as incoming edges on the canvas, never a dropdown. |
| Advanced | `tools` | ✓ | `list[BaseTool] = []` | Overrides the agent's tools for this task. |
| Advanced | `async_execution` | ✓ | `bool = False` | |
| Advanced | `human_input` | ✓ | `bool = False` | Console prompt — **not** the durable gate. Builder gates use Flow `@human_feedback`, §5. |
| Advanced | `markdown` | ✓ | `bool = False` | |
| Expert | `output_json` | ✓ | `type[BaseModel] \| None` | Needs a pydantic class; a canvas schema editor must generate one (json_schema → `create_model`). |
| Expert | `output_pydantic` | ✓ | `type[BaseModel] \| None` | |
| Expert | `response_model` | ✓ | `type[BaseModel] \| None` | Native structured-output path. |
| Expert | `output_file` | ✓ | `str \| None`, `create_directory=True` | Writes to container disk — ephemeral on Render. |
| Expert | `guardrail` / `guardrails` | ✓ | `Callable \| str \| None` / sequence | `str` = LLM guardrail on the agent's LLM; `guardrail_max_retries = 3`. |
| Expert | `callback` | ✓ | callable | |
| Expert | `retry_count` | **✗ not a setting** | `int = 0`, runtime counter | The *setting* is `max_retries: int \| None`. |

---

## 3. Crew

`crewai.Crew`, source `crewai/crew.py`.

| Tier | Field | Exists | Type / default | Note |
| --- | --- | --- | --- | --- |
| Essentials | `process` | ✓ | `Process.sequential` | `Process` values: `sequential`, `hierarchical`. |
| Essentials | `verbose` | ✓ | `bool = False` | |
| Advanced | `manager_llm` / `manager_agent` | ✓ | `str \| BaseLLM \| None` / `BaseAgent \| None` | **Validated:** `crew.py:729` raises *"Attribute `manager_llm` or `manager_agent` is required when using hierarchical process."* |
| Advanced | `memory` | ✓ | `bool \| Memory \| MemoryScope \| MemorySlice = False` | **Unified.** The legacy `short_term_memory` / `long_term_memory` / `entity_memory` fields are not on the model at 1.15.18. |
| Advanced | `cache` | ✓ | `bool = False` | |
| Advanced | `max_rpm` | ✓ | `int \| None` | |
| Advanced | `planning` / `planning_llm` | ✓ | `False` / `None` | |
| Expert | `embedder` | ✓ | provider spec | |
| Expert | `knowledge_sources` | ✓ | list | |
| Expert | `output_log_file` | ✓ | `bool \| str \| None` | |
| Expert | `step_callback` / `task_callback` | ✓ | callables | Also `before_kickoff_callbacks` / `after_kickoff_callbacks`. |

Also present: `skills` (crew-level SKILL.md packs), `stream: bool = False`,
`function_calling_llm`, `chat_llm`, `prompt_file`, `tracing`, `checkpoint`,
`tool_failure_policy`.

---

## 4. LLM

`crewai.LLM` (`crewai/llm.py`, fields at `:372-388`) over `BaseLLM`
(`crewai/llms/base_llm.py:172-186`). Constructor is `**data` — it is a
pydantic model.

| Gauntlet field | Exists | Type / default |
| --- | --- | --- |
| `model` | ✓ | `str`, required |
| `temperature` | ✓ | `float \| None` |
| `max_tokens` | ✓ | `int \| float \| None` (also `max_completion_tokens`) |
| `top_p` | ✓ | `float \| None` |
| `frequency_penalty` | ✓ | `float \| None` |
| `presence_penalty` | ✓ | `float \| None` |
| `stop` | ✓ | `list[str] = []` |
| `seed` | ✓ | `int \| None` |
| `timeout` | ✓ | `float \| int \| None` |
| `response_format` | ✓ | `JsonResponseFormat \| type[BaseModel] \| None` |
| `stream` | ✓ | `bool = False` |

Extra: `n`, `logprobs`, `reasoning_effort: Literal['none','low','medium','high'] | None`,
`api_key`, `base_url`, `provider = 'openai'`, `is_litellm = False`.

Repo-specific caveats, both already recorded in `config.py` and `CLAUDE.md`:
CrewAI strips the `openrouter/` prefix for native providers when it
constructs the client (`LLM.__new__`), so **price lookups must accept both
spellings**; and `reasoning_effort` is **silently dropped** for OpenRouter
models (`config.py:628`), so a UI must not claim it took effect.

---

## 5. Flow

`crewai.flow` exports (verified): `Flow`, `start`, `listen`, `router`, `or_`,
`and_`, `persist`, `human_feedback`, `HumanFeedbackPending`,
`HumanFeedbackResult`, `HumanFeedbackProvider`, `FlowDefinition` and the
declarative `crewai.flow/v1` loader.

```python
human_feedback(message: str, emit: Sequence[str] | None = None,
               llm: str | BaseLLM | None = 'gpt-5.4-mini',
               default_outcome: str | None = None, metadata=None,
               provider: HumanFeedbackProvider | None = None,
               learn=False, learn_source='hitl', learn_strict=False)
```

**The `llm` default is a bare OpenAI model string.** It is deserialized
before `emit` is checked, so it must be passed as `None` explicitly. This is
`CLAUDE.md` §11(a) and `docs/flow-builder-spec.md` rule 2 seen from the
package side.

The declarative schema (`crewai/flow/flow_definition.py`):

- `FlowDefinition(schema='crewai.flow/v1', name, description, state, config, persistence, methods…)` — `:710`.
- State kinds: `dict` (`:81`), `pydantic` (`:98`), `json_schema` (`:133`), `unknown` (`:160`). **`json_schema` is the one a canvas can author**; `pydantic` needs a Python class.
- Action kinds: `code` (`:348`), `tool` (`:375`), `crew` (`:399`), `agent` (`:465`), `expression` (`:498`), `script` (`:513`), `each` (`:583`), plus `FlowHumanFeedbackDefinition` (`:277`) and `FlowPersistenceDefinition` (`:236`).

Three rules that were **measured on a running flow**, not reasoned
(`docs/flow-builder-spec.md`, `CLAUDE.md` §14):

1. One canvas gate compiles to **two** methods — the `@human_feedback` pause and a deterministic `@router` that reads the answer. A single method doing both returns a `HumanFeedbackResult`, which is not an event name, and the flow ends silently.
2. `emit` must be null and `llm` must be **explicitly** null on every gate.
3. Every loop-closing node must be a `@router`; a plain `@listen` join fires once and the second arrival is dropped without an exception, warning or frame.

`Flow.resume()` has shown one unreproduced `RecursionError` (CLAUDE.md remaining-work item 9).

---

## 6. MCP — native on `Agent.mcps`

```python
Agent.mcps: list[str | MCPServerStdio | MCPServerHTTP | MCPServerSSE] | None
```

Config models (`crewai/mcp/config.py`):

| Class | Fields |
| --- | --- |
| `MCPServerStdio` | `command: str`, `args: list[str]`, `env: dict[str,str] \| None`, `tool_filter`, `cache_tools_list: bool` |
| `MCPServerHTTP` | `url: str`, `headers: dict[str,str] \| None`, `streamable: bool`, `tool_filter`, `cache_tools_list` |
| `MCPServerSSE` | `url: str`, `headers: dict[str,str] \| None`, `tool_filter`, `cache_tools_list` |

**How a bare string is interpreted** (`crewai/mcp/tool_resolver.py:81-120`):
a string starting with `https://` is an external HTTP server; **any other
string is a CrewAI AMP marketplace reference** (`_parse_amp_ref`, `:121`) and
goes to the network. A builder must therefore always construct a config
object from user input and never pass the raw string.

Resolution: `MCPToolResolver.resolve(mcps) -> list[BaseTool]` discovers tools
with retry (`_retry_mcp_discovery`, `:572`), and `cleanup()` disconnects the
clients. Tool schemas: `_get_mcp_tool_schemas` (`:534`). Events:
`crewai/events/types/mcp_events.py`.

The older adapter still exists —
`crewai_tools.MCPServerAdapter(serverparams, *tool_names, connect_timeout=30)`
— but native `mcps` is the primitive a canvas node should map to.

---

## 7. Skills — native SKILL.md packs

`Agent.skills` and `Crew.skills`: `list[Path | Skill | str] | None`.
`crewai/skills/models.py`:

- `SkillFrontmatter` (`:43-63`): `name` (1–64 chars, lowercase alphanumeric + hyphens), `description` (1–1024), `license`, `compatibility` (≤500), `metadata` (str→str; conventional key `version`), `allowed_tools` (space-delimited).
- `Skill`: `frontmatter`, `instructions: str | None`, `path: Path`, `disclosure_level`, `resource_files`.
- **Progressive disclosure is built in** (`:25-35`): `METADATA = 1` (frontmatter only), `INSTRUCTIONS = 2` (body loaded), `RESOURCES = 3` (`scripts/` / `references/` / `assets/` catalogued). This is exactly the gauntlet's "name and description at run start, body when a task matches".
- Loader (`crewai/skills/loader.py`): `discover_skills` (at METADATA, `:44`), `load_skill` / `load_skills` (`:154`, `:210`), `activate_skill` (→ INSTRUCTIONS, `:120`), `load_resources` (→ RESOURCES, `:281`), `build_skill_catalog` (`:245`), `format_skill_context` (`:293`).
- A `str` that is not a path is a **registry reference** (`is_registry_ref` / `resolve_registry_ref`) — same AMP caveat as MCP. Store user skills on disk and pass `Path`s.
- Events: `crewai/events/types/skill_events.py`.

---

## 8. Tools and tool failure

`ToolFailurePolicy` (`crewai/tools/tool_failure.py:57-69`): `ignore`, `warn`
(default), `raise` → `ToolExecutionFailedError`. A tool returns a
`ToolFailure(message=…)` instead of an error string so the framework knows the
call failed. Settable per agent and per task.

`crewai_tools` 1.15.18 exposes 107 classes. The ones the gauntlet names, with
what they need (env var names read from each module's source):

| Gauntlet item | Class | Credential | Notable constructor fields |
| --- | --- | --- | --- |
| Firecrawl scrape / crawl / search | `FirecrawlScrapeWebsiteTool`, `FirecrawlCrawlWebsiteTool`, `FirecrawlSearchTool` | `FIRECRAWL_API_KEY` (or `api_key=`) | `config` |
| Firecrawl map / extract | **absent** | — | Only the three above exist; the repo's own `tools/market_research.py` wraps v2 search+scrape. |
| Web search — Serper | `SerperDevTool` | `SERPER_API_KEY` | `n_results=10`, `search_type`, `country`, `locale` |
| Web search — Tavily | `TavilySearchTool` | `TAVILY_API_KEY` | `search_depth='basic'`, `max_results=5`, `include_domains` |
| Web search — Exa | `EXASearchTool` | `EXA_API_KEY` | `type='auto'`, `highlights=True` |
| Web search — Brave | `BraveSearchTool` | `BRAVE_API_KEY` | `n_results=10` |
| HTTP request | `URLReadTool` | none | `max_bytes=5 MiB`, `timeout=30`, `headers` |
| Scrape (no key) | `ScrapeWebsiteTool` | none | `website_url`, `cookies`, `headers` |
| File read | `FileReadTool` | none | `file_path`, `base_dir`, `encoding` |
| CSV / JSON | `CSVSearchTool`, `JSONSearchTool` | none — **but RAG-backed** | see warning |
| RAG retrieval | `RagTool`, `WebsiteSearchTool` | none — **RAG-backed** | `similarity_threshold=0.6`, `limit=5`, `collection_name` |
| GitHub | `GithubSearchTool` | `gh_token=` | RAG-backed; the repo's `tools/github_feasibility.py` is the non-RAG alternative |
| YouTube | `YoutubeVideoSearchTool` | none | RAG-backed |
| Postgres query | `NL2SQLTool` | `db_uri=` | `allow_dml=False`, `tables`, `columns` |
| Code interpreter | **`CodeInterpreterTool` removed** | — | Sandboxed alternatives: `E2BPythonTool` (`api_key`, `sandbox_timeout=300`) and `DaytonaPythonTool` (`api_key`, `api_url`). Both are paid third-party sandboxes. |
| MCP | `MCPServerAdapter` | per server | prefer native `Agent.mcps` |

> **RAG-backed tools default to OpenAI embeddings.** `CSVSearchTool`,
> `JSONSearchTool`, `GithubSearchTool`, `YoutubeVideoSearchTool`,
> `WebsiteSearchTool` and `RagTool` all share the `adapter` / `config` /
> `summarize` / `similarity_threshold` / `limit` / `collection_name` shape and
> embed through the default provider unless `config` says otherwise. The
> platform rule is *no direct OpenAI* and *embeddings through
> `brief_crew.embeddings`*, so each of these must be constructed with an
> explicit embedder config or left out of the catalogue.

---

## 9. Events a run visualizer can consume

`crewai/events/types/`: `agent_events`, `crew_events`, `flow_events`,
`task_events`, `tool_usage_events`, `llm_events`, `llm_guardrail_events`,
`mcp_events`, `skill_events`, `reasoning_events`, `memory_events`,
`knowledge_events`, `hook_events`, `checkpoint_events`, `a2a_events`.

The ones that carry **content** rather than lifecycle:

- `LLMCallCompletedEvent` (`llm_events.py:90`): `messages`, **`response: Any`**, `usage`, `finish_reason`, `response_id`, `call_id`, `model`.
- `LLMStreamChunkEvent` (`:136`): `chunk: str`, `tool_call`, `call_type`, `response_id`.
- `LLMThinkingChunkEvent` (`:146`).
- `ToolUsageStartedEvent` / `ToolUsageFinishedEvent` / `ToolUsageErrorEvent` carry the tool name, arguments and output.

The repo's serializer (`src/brief_crew/events/serializer.py`) already maps
all of the lifecycle events plus `LLMStreamChunkEvent`, but **drops the
completed response text** (`:472` emits only `finish_reason` / `response_id`)
and clips stream chunks (`:478`). A dialogue-reveal visualizer needs the
bounded response text captured at completion — that is a serializer change,
not a CrewAI limitation.

---

## 10. Process, memory, checkpoints — one line each

- `Process`: `sequential`, `hierarchical`. Hierarchical without a manager is refused at validation (`crew.py:729`).
- Memory is one `memory` field on Agent and Crew (`bool | Memory | MemoryScope | MemorySlice`); the three-store split is gone.
- `checkpoint: CheckpointConfig | bool | None` exists on Agent and Crew (1.15 checkpointing) — relevant to partial-run resume, untested here.
- `Crew.stream = True` turns on `LLMStreamChunkEvent` emission for the crew's calls.

---

## 11. Where the gauntlet and the package disagree — the package wins

1. **`allow_code_execution` / `code_execution_mode` are deprecated with no tool behind them.** The Expert tier must not render them. "Code interpreter, sandboxed, opt-in" maps to `E2BPythonTool` or `DaytonaPythonTool` behind a per-user key, or is cut.
2. **Task `retry_count` is a counter, not a setting.** ~~Render `max_retries`.~~
   **CORRECTED 2026-09-04: render `guardrail_max_retries`, NOT `max_retries`.**
   `Task.max_retries` is itself deprecated at 1.15.18 - `task.py:275-278` carries
   `[DEPRECATED] ... Use guardrail_max_retries instead. Will be removed in
   v1.0.0`, and `handle_max_retries_deprecation` (`:574-583`) warns and silently
   copies the value into `guardrail_max_retries`. So the old advice built a
   control that emits a `DeprecationWarning` and writes to a different field.
   Note the collision: the builder's own `retry.max_retries` is a NODE-level
   retry and is not this field.
3. **Crew memory is one unified field**, not "short/long/entity individually toggleable".
4. **`human_feedback`'s `llm` default is a live OpenAI string.** Every gate passes `llm=None`.
5. **`Agent.llm = None` resolves to OpenAI.** The compiler must always attach an explicit `openrouter/` LLM — the repo's startup assertion already refuses anything else.
6. **A bare string in `mcps` or `skills` is an AMP marketplace lookup**, not a URL or a path (except `https://`). User input is never passed as a raw string.
7. **Firecrawl `map` and `extract` have no `crewai_tools` class.** Either wrap the Firecrawl SDK (the repo already wraps v2 search/scrape in `tools/market_research.py`) or list only the three that exist.
8. **Flow state authored on a canvas is `json_schema`**, not a Pydantic editor; `pydantic` state needs a Python class the author cannot write.
9. **RAG-family tools embed with OpenAI by default**, which the platform rules forbid; they need `brief_crew.embeddings` wired in or must be excluded.

### Added 2026-09-04 — a full deprecation scan, all three mechanisms

10. **Four fields the plan set renders are DEPRECATED on `Agent`.** `reasoning`,
    `max_reasoning_attempts`, `multimodal` and `function_calling_llm` all appear
    in `03-node-library.md` D3's `AuthoredAgentConfig` and `04-inspector-and-params.md`
    D2's Expert tier. `Crew.function_calling_llm` is deprecated too. A form control
    bound to a deprecated field is a control that emits a warning today and breaks
    on the next major.
11. **`Agent.reasoning` is auto-migrated, so the Expert *switch* is the wrong
    control.** `agent/core.py:418-427` folds it into a `PlanningConfig` and warns.
    `Agent.planning` (bool) and `Agent.planning_config` (11 fields) are **not**
    deprecated and are the current surface.
12. **Deprecation is marked THREE ways here, and a scan that knows one
    under-reports.** `Field(deprecated=True)` (`reasoning`, `max_reasoning_attempts`,
    `multimodal`, `allow_code_execution`, `code_execution_mode`);
    `Field(deprecated="a sentence")` (`function_calling_llm` on both `Agent` and
    `Crew`); and **neither** - `Task.max_retries` carries `[DEPRECATED]` only in its
    description, enforced by a `model_validator`, so `model_fields[...].deprecated`
    reads `None` for it. A check written against the first mechanism alone passes
    plan 00's criterion 3 for the wrong reason. The scan that found all eight is
    reproduced in that criterion's own notes.
