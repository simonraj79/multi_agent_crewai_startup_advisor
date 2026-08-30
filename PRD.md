# PRD — Validator Studio

**A CrewAI startup-idea validator with a live agent-graph UI.**

| | |
|---|---|
| **Status** | Draft for review |
| **Author** | Simon |
| **Date** | 2026-08-29 |
| **Repo** | `D:\MultiAgentSystem` (`brief_crew`) |
| **Supersedes** | nothing — additive to the existing Brief Crew |
| **Authoritative specs** | [`agents/`](agents/) remains authoritative. This PRD extends it; where they conflict, `agents/` wins until this document is folded back in. |

---

## 1. Summary

Two things ship together, and neither is interesting without the other.

**The crew.** A six-agent startup-idea validator built from CrewAI primitives —
`Flow` + `Process.sequential` + task guardrails — that takes a one-line startup
idea and returns a sourced, scored validation report with an explicit
`VALIDATE / NEEDS_WORK / REJECT` verdict and a *separate* confidence figure.

**The studio.** A Vue 3 + Vue Flow web UI that renders that crew as a live graph:
nodes light up as agents run, edges pulse on hand-off, a chat rail streams every
tool call and model turn with timestamps, and the run **stops and asks the user**
at two decision points before continuing.

The reference material is a Firecrawl tutorial that builds the same idea on
LangGraph. We are not porting it. We are rebuilding it on CrewAI and fixing what
the tutorial left out — which, as §2.1 shows, is most of the architecture.

---

## 2. Audit

Three things were audited before any of this was designed: the tutorial we were
pointed at, the repository we are building into, and the UI we were shown.

### 2.1 Audit — the Firecrawl LangGraph tutorial

Source: `https://www.firecrawl.dev/blog/langgraph-startup-validator-tutorial`

**Finding: the title oversells the architecture.** Despite "LangGraph", the
tutorial builds a *single* `create_react_agent` with three tools. There is no
graph to port.

```python
agent = create_react_agent(
    model="openai:o4-mini",
    tools=[research_market_landscape,
           analyze_community_sentiment,
           assess_technical_feasibility],
    prompt=CONVERSATIONAL_VALIDATOR_PROMPT,
    checkpointer=InMemorySaver(),
)
```

| Thing you would expect | Present? | What is there instead |
|---|---|---|
| Multi-node graph topology | ❌ | one prebuilt ReAct node |
| Custom `StateSchema` | ❌ | the default message list |
| Explicit edges / conditional routing | ❌ | implicit in ReAct reasoning |
| Human-in-the-loop `interrupt()` | ❌ | fully autonomous, no pauses |
| Structured output (Pydantic / JSON schema) | ❌ | tools return raw `str` |
| Scoring rubric behind the verdict | ❌ | *"End with VALIDATE/NEEDS_WORK/REJECT"* in the prompt |
| Source attribution on claims | ❌ | not enforced anywhere |

**Finding: only one of its three tools is actually Firecrawl.**

| Tool | Endpoint | Notes |
|---|---|---|
| `research_market_landscape` | Firecrawl `app.search(..., limit=5, scrape_options=ScrapeOptions(formats=["markdown"]))` | the only Firecrawl call |
| `analyze_community_sentiment` | Hacker News Algolia `hn.algolia.com/api/v1/search` | plain `requests.get` |
| `assess_technical_feasibility` | GitHub `api.github.com/search/repositories` | plain `requests.get`, unauthenticated |

**Verdict on the tutorial.** Take the *domain decomposition* — market, community
sentiment, technical feasibility is a genuinely good three-way cut of "is this
idea real". Take the three data sources. Discard the architecture: a single ReAct
agent with string-returning tools is exactly the shape this repository's
`agents/workflow.md` §6 already argues against, and it cannot produce the
traceable, sourced output the house rules require.

**What we add that the tutorial has none of:** real multi-agent decomposition,
deterministic routing, parallel fan-out, human gates, Pydantic structured output,
a mechanical scoring rubric, per-claim source attribution, a warm cache, and cost
accounting.

### 2.2 Audit — the current repository

**What exists and works.** `brief_crew` is a mature, spec-backed CrewAI project.
It is *not* a prototype and must not be treated as one.

```
src/brief_crew/
├── config.py                     models · prices · embedding prefixes · thresholds
├── embeddings.py                 OpenRouter embeddings, called directly
├── indexing.py                   chunk / embed / upsert
├── guardrails.py                 check_mechanics (callable) + ATTRIBUTION_GUARDRAIL (string)
├── main.py                       run_crew() = Track A · kickoff() = Track B Flow
├── crews/brief_crew/
│   ├── config/agents.yaml        role · goal · backstory · runtime caps
│   ├── config/tasks.yaml         descriptions · expected outputs
│   └── brief_crew.py             @CrewBase — the wiring
└── tools/pinecone_retrieval.py   retrieve_and_rerank
```

Plus ~7,800 lines of authoritative specification in `agents/`, including
`patterns.md` — all six orchestration patterns verified against the
**`crewai 1.15.18` wheel** with file:line citations — and
`08-observability.md`, which already names the exact event-bus hooks a live UI
needs.

**Assets we inherit, and must reuse rather than re-derive:**

| Asset | Where | Why it matters here |
|---|---|---|
| Model tiering + price table | `config.py` | `CHEAP_MODEL` / `ESCALATION_MODEL`, and `compute_cost_usd()` — CrewAI discards OpenRouter's own cost figure, so every dollar this project reports is arithmetic over that table |
| Warm Pinecone cache | `tools/pinecone_retrieval.py`, `indexing.py` | retrieve → Cohere rerank → staleness gate. Reusable for validation research |
| Deterministic `@router` | `main.py` `check_cache` | the pattern-② reference implementation: 0 LLM calls to branch |
| Two-tier guardrails | `guardrails.py` | free arithmetic check first, LLM judgement second. Directly portable |
| Event-bus spec | `agents/08-observability.md` §7 | listener shape, contextvar run-scoping, the singleton trap, handler threading |
| `.env` override fix | `__init__.py` | `load_dotenv(path, override=True)` — machine env silently shadowed `PINECONE_API_KEY`. Do not regress this |
| Service dependency group | `pyproject.toml` `[service]` | `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg` already declared, not yet used |

**Gaps this PRD fills:**

| Gap | Consequence today |
|---|---|
| No HTTP/WebSocket service | the crew is CLI-only; `[service]` extras are declared but unimplemented |
| No frontend of any kind | the repo is Python-only |
| No event-bus listener | `08-observability.md` §7 specifies one; nothing implements it |
| No human-in-the-loop anywhere | `Flow` runs start-to-finish, unattended |
| Pattern ③ (parallel fan-out) unused | deliberately — see §2.4, which revisits that decision |

**Credentials.** Five keys already provisioned in `.env`: `OPENROUTER_API_KEY`,
`FIRECRAWL_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `COHERE_API_KEY`
(plus `RENDER_API_KEY`). The validator needs **no new paid credential** — HN
Algolia is open, and GitHub search works unauthenticated at a reduced rate limit.

### 2.3 Audit — the reference UI

The screenshot is **DevAll** (a local checkout of `ChatDev-main`),
a Vue 3 + Vue Flow app served by a FastAPI + WebSocket backend, running at
`localhost:5173/launch?workflow=…yaml&session=…`.

Its transport contract is small enough to adopt wholesale:

```jsonc
// server → client
{ "type": "log", "data": {
    "timestamp": "…", "level": "INFO", "node_id": "…",
    "event_type": "NODE_START", "message": "…",
    "details": {…}, "execution_path": [...], "duration": 1.23 } }

{ "type": "human_input_required", "data": {
    "node_id": "…", "input": "…", "task_description": "…" } }
```

with `EventType ∈ { NODE_START, NODE_END, EDGE_PROCESS, MODEL_CALL, TOOL_CALL,
AGENT_CALL, HUMAN_INTERACTION, THINKING_PROCESS, MEMORY_OPERATION,
WORKFLOW_START, WORKFLOW_END }`.

**Why this matters more than it looks:** that enum maps almost 1:1 onto CrewAI's
event bus. `NODE_START`/`NODE_END` ← `MethodExecutionStarted/Finished`,
`TOOL_CALL` ← `ToolUsageStarted/Finished`, `MODEL_CALL` ← `LLMCallCompleted`,
`AGENT_CALL` ← `AgentExecutionStarted/Completed`. The adapter between the two
systems is **one listener class**, not a framework.

DevAll's human-gate primitive is also directly reusable in shape:
`WebPromptChannel.request()` calls `set_waiting_for_input()`, emits
`human_input_required`, then blocks on `wait_for_human_input()` — a synchronous
block on a worker thread, released by a WebSocket message. That is exactly what
CrewAI needs, because `Flow.kickoff()` is synchronous and blocking.

**What we take:** the three-pane shell, the dark token set, the Vue Flow node and
edge treatments, the sprite-avatar chat rail, the WebSocket message contract, and
the session/prompt-channel pattern.

**What we do not take:** DevAll's graph *editor*, its YAML workflow-definition
runtime, its dynamic-edge and subgraph machinery, its memory nodes. Our topology
is **fixed per workflow and defined in Python**. We need a runner and a
visualiser, not an authoring tool.

### 2.4 Declared deviation — Pattern ③ becomes load-bearing

`agents/workflow.md` §8 excludes parallel fan-out on two grounds. This feature
overturns the first and must be honest about the second.

| §8's argument | Status under the validator |
|---|---|
| *"No independent subtasks — every stage consumes its predecessor's entire output."* | **No longer true.** Market landscape, community sentiment and technical feasibility depend only on the scoped idea. They share no inputs and never read each other. This is slide 16's *sectioning* mode, literally. |
| *"~210 MB resident caps a Render `starter` at one concurrent run, so fan-out buys no wall-clock."* | **Misapplied to this case.** That 210 MB is a per-**process** import cost (`chromadb`/`lancedb`/`onnxruntime` load whether used or not). Fan-out inside one run is *threads in that same process* (§2.5), so it shares the baseline. §8's ceiling caps concurrent **runs**, not concurrent **branches within a run**. The work is network-bound (Firecrawl scrapes at 10–30 s each), so those threads spend their time in I/O wait. |

Peak RSS and wall-clock are still M3 exit criteria (§12, §13) — the mechanism is
now proven, the *budget* is not. If measurement contradicts it, the fallback is
sequential execution of the same agents: worse latency, identical graph.

### 2.5 Correction — how parallelism actually works in a CrewAI Flow

Verified against the installed `crewai 1.15.18` wheel, by execution.

**`and_()` does not cause anything to run.** It returns a plain dict —
`{"type": "AND", "conditions": [...]}` (`flow/dsl/_conditions.py:22-29`) — and is
consumed as pure bookkeeping (`flow/runtime/__init__.py:3265-3276`). It is a
**join predicate only**.

Parallelism comes from two lines elsewhere:

```python
# flow/runtime/__init__.py:3241-3249 — every listener on the same trigger is gathered
tasks = [self._execute_single_listener(name, result, event_id)
         for name in listeners_triggered]
await asyncio.gather(*tasks)

# flow/runtime/__init__.py:2966-2972 — a sync `def` method gets a real thread
ctx = contextvars.copy_context()
result = await asyncio.to_thread(ctx.run, method, *args, **kwargs)
```

So **sibling `@listen` methods on the same trigger run concurrently**, and a plain
`def` method holding a blocking `Crew().kickoff()` runs on its own thread.
Measured: three listeners each sleeping 2 s completed in **2.90 s**, on three
distinct threads, with `and_()` firing once after all three.

| Consequence | Why it matters here |
|---|---|
| Keep fan-out methods `def`, **not** `async def` | an `async def` is awaited directly on the loop (`:2967`); a blocking body there serialises the fan-out |
| `contextvars.copy_context()` propagates into the worker | run-scoping and event correlation survive the thread boundary *for free* — but only for Flow-hosted threads. A hand-rolled `threading.Thread` loses it |
| Each branch can be a **whole Crew** | `Crew.kickoff()` is fully synchronous with no internal loop (`crew.py:1040-1067`), so it is safe inside a worker thread |
| Width is capped at `min(32, cpu_count + 4)` | irrelevant at 3-way |
| `max_method_calls` defaults to **100** | exceeding it raises `RecursionError` (`flow/runtime/__init__.py:614`) |

**We therefore fan out at the Flow level, not with `Task(async_execution=True)`.**
The Crew-level route was rejected on three verified counts:

- a validator minefield — *"the crew must end with at most one asynchronous task"* (`crew.py:779-797`), and an async task may not name another async task in its `context` (`:840-862`);
- it spawns an **unbounded raw daemon thread per task** (`task.py:616-623`) — no pool, no cap;
- **parallel async tasks cannot see each other's output** (`crew.py:1597-1600` passes only `[last_sync_output]`).

⚠️ **Correction to `agents/patterns.md` §4 Option C.** `kickoff_for_each` is
listed under Pattern ③ but is a **sequential `for` loop** (`crew.py:1108-1115`).
Only `kickoff_for_each_async` / `akickoff_for_each` actually gather
(`crews/utils.py:500-505`). See Appendix B.

---

## 3. Problem and opportunity

**Problem.** Multi-agent systems are opaque. The only view this repo currently
has of "who handed off to whom" is `verbose=True` scrolling past in a terminal —
`README.md` says so explicitly. That is fine for a developer running one crew and
useless for anyone else: you cannot show it to a stakeholder, you cannot steer a
run that has gone wrong, and you cannot point at the moment a fabricated citation
entered the pipeline.

**Opportunity.** The repository already emits, on a process-wide event bus,
everything a live view would need — per-agent, per-tool, per-model-call, with
token counts and task/agent attribution. Nothing consumes it. A relatively thin
listener plus a WebSocket turns an invisible pipeline into a legible one, and the
same surface makes human gating possible for the first time.

**Why a startup validator as the vehicle.** It is the smallest realistic problem
that *needs* all of it: genuinely independent research tracks (so the graph has
something to show in parallel), a judgement call worth interrupting a human for
(scope, then verdict), and an output where unsourced claims are actively
dangerous (so the guardrail work is not decoration).

---

## 4. Goals and non-goals

### 4.1 Goals

| # | Goal | Measured by |
|---|---|---|
| G1 | A six-agent validator built from CrewAI primitives — no LangGraph, no bespoke orchestrator | `crewai` is the only orchestration dependency |
| G2 | Every claim in the report traces to a URL that appeared in a tool result | guardrail rejection rate; zero fabricated citations in the acceptance set |
| G3 | A verdict backed by a mechanical rubric, with confidence reported separately | two runs on identical evidence produce the same verdict band |
| G4 | A live graph UI reproducing the reference screenshot's information design | side-by-side visual review |
| G5 | The run pauses at two gates and resumes on user input | gate → reply → resume round-trip works over a reconnecting socket |
| G6 | Zero regression to the existing Brief Crew | `run_crew()` and `kickoff()` behave identically; `output/brief.md` unchanged |
| G7 | Per-run, per-node cost and token accounting visible in the UI | figures reconcile with `compute_cost_usd()` |

### 4.2 Non-goals

| Not doing | Why |
|---|---|
| A graph **editor** | our topology is code, not user-authored YAML. DevAll's editor is the bulk of its complexity and none of its value to us |
| Multi-tenant auth / accounts | single-operator tool; adding auth now buys nothing |
| Replacing the Brief Crew | it works, it is spec-backed, and it shares the spine (§2.2) |
| Agent memory / RAG chat across runs | `memory=False` is deliberate (`brief_crew.py`) — it keeps CrewAI's default OpenAI embedder unreachable, which is why this project needs no `OPENAI_API_KEY` |
| Mobile layout | a pan/zoom graph on a phone is not a real use case here. Breakpoints down to tablet are in scope — DevAll has none at all (§8.1) |
| DevAll's graph **editor** and its dynamic-schema form generator | the single biggest chunk of that codebase, and inapplicable to a fixed topology (§8.8) |

---

## 5. Users and scenarios

**Primary user — the operator.** Runs the validator on their own ideas, watches
the graph, and intervenes at the gates. Needs to see *why* a verdict landed, not
just what it was.

**Secondary user — the audience.** Someone being shown the system. Needs the
graph to be legible without narration: which agent is running, what it just did,
where the run branched.

### Scenario A — the happy path

1. Operator types *"an AI tool that turns Figma files into production React"* and hits Launch.
2. `Scoper` node lights amber; the chat rail shows it parsing the idea into a market, a user, and a technology claim.
3. The run **pauses**. A card appears: *"Confirm scope"* with the parsed fields editable. The `Scoper` node shows the waiting state.
4. Operator corrects the market from *"design tools"* to *"design-to-code tooling"* and approves.
5. Three nodes light simultaneously. Tool-call lines stream: `firecrawl.search`, `hn.search`, `github.search_repositories`. Edges pulse.
6. `Synthesist` runs, emits a rubric table and a draft verdict. The run **pauses** again: *"Review verdict — NEEDS_WORK, confidence 0.62"*.
7. Operator accepts. `Reporter` writes `output/validation.md`. `Final` node turns green; the rail shows total cost and call count.

### Scenario B — thin evidence

Sentiment research returns two weak hits. The rubric's confidence term drops
below threshold. The verdict is `NEEDS_WORK` with confidence `0.31`, and the
report says *which* dimension is under-evidenced rather than presenting a
confident `REJECT`. **This is a required behaviour, not a degradation** — it is
the direct analogue of the Analyst's *"the evidence is thin here"* rule in
`agents/02-analyst.md`.

### Scenario C — the operator walks away

A gate is reached and nobody answers. After the configured timeout the run does
not silently proceed on a guess; it parks in a resumable waiting state and the
UI says so. A reconnecting client recovers the pending prompt.

---

## 6. Architecture

### 6.1 The shape

```
                                  ┌──────────────┐
   idea ─────────────────────────▶│    Scoper    │  CHEAP tier, no tools
                                  └──────┬───────┘
                                  ┌──────▼───────┐
                                  │  ⏸  GATE 1   │  confirm scope
                                  │ human_input  │  (editable, timeout-guarded)
                                  └──────┬───────┘
              ┌──────────────────────────┼──────────────────────────┐
     ┌────────▼────────┐        ┌────────▼────────┐        ┌────────▼────────┐
     │ Market Analyst  │        │Sentiment Analyst│        │Feasibility Anlst│
     │ Firecrawl search│        │  HN Algolia     │        │  GitHub search  │
     │ + scrape        │        │                 │        │                 │
     └────────┬────────┘        └────────┬────────┘        └────────┬────────┘
              └──────────────────────────┼──────────────────────────┘
                                  ┌──────▼───────┐
                                  │  Synthesist  │  ESCALATION tier, no tools
                                  │  the rubric  │  ← the one real judgement step
                                  └──────┬───────┘
                                  ┌──────▼───────┐
                                  │  ⏸  GATE 2   │  review verdict
                                  └──────┬───────┘
                                  ┌──────▼───────┐
                                  │   Reporter   │  guardrails: mechanics + attribution
                                  └──────┬───────┘
                                         ▼
                                output/validation.md
```

### 6.2 Pattern coverage

This extends the table in `agents/workflow.md` §7. **The validator is the first
thing in this repository to use four of the six patterns in one run.**

| Pattern | Brief Crew | Validator | Where |
|---|---|---|---|
| ① Sequential Pipeline | Core | **Core** | Scoper → fan-out → Synthesist → Reporter |
| ② Routing / Handoff | Used, LLM-free | **Used, LLM-free** | cache staleness gate + gate-response routing |
| ③ Parallel Fan-out | Not used | **Core — new** | the three research analysts (§2.4) |
| ④ Supervisor / Workers | Comparison only | Not used | no decision a `@router` cannot make for free |
| ⑤ Hierarchical | Not used | Not used | nothing to nest |
| ⑥ Evaluator–Optimizer | Specified, not attached | **Attached** | `report_task` guardrails |

The deliberate absence of ④ is unchanged and for the same reason as
`agents/04-manager.md`: a manager agent would make decisions a deterministic
router already makes, and charge an LLM call per run to do it.

### 6.3 Why CrewAI primitives, restated

Not because LangGraph cannot do this — it can — but because the decomposition
maps onto CrewAI's five nouns with nothing left over, and `agents/patterns.md`
already documents each mechanism against the installed wheel:

| Need | CrewAI mechanism | Cost to decide |
|---|---|---|
| Fixed-order stages | `Process.sequential` + `context=[...]` | 0 |
| Branch on cache / gate response | Flow `@router` | **0 LLM calls** |
| Three independent research tracks | `Task(async_execution=True)` + sync join | 0 |
| Reject an unsourced report and retry | `Task(guardrail=...)` | 0 for the callable, 1 per string check |
| Pause for a human | *not native* — see §9 | 0 |

---

## 7. Agent roster and orchestration

### 7.0 Resolved conflict — where the fan-out lives

Two defensible designs surfaced, and the choice is decided by the product
requirement rather than by CrewAI mechanics.

| | **A · Crew-level** | **B · Flow-level** ✅ |
|---|---|---|
| Shape | one `ValidateCrew`: 3 tasks `async_execution: true` + 1 sync join | 3 sibling `@listen(gate_1)` Flow methods, each its own single-agent Crew, joined by `@listen(and_(...))` |
| Parallelism | real — `Task.execute_async` spawns a daemon thread per task with copied contextvars (`task.py:616`) | real — `asyncio.gather` + `asyncio.to_thread` (§2.5) |
| Synthesist context | free: names all four tasks, sync join drains futures (`crew.py:1611`) | inputs passed via `kickoff()` |
| **Graph nodes** | **1 node lights up** — all three tasks live inside one Flow method | **3 nodes light up** |

**B, on the graph argument alone.** The visible parallel fan-out *is* the
feature (§3, G4); a design that renders it as a single node defeats the reason
the pattern was adopted. B also sidesteps the async-task validator minefield and
the unbounded-daemon-thread issue (§2.5).

The roster, prompts, schemas and rubric below are assembly-independent and
transfer unchanged. Two consequences of choosing B: `async_execution` leaves
`tasks.yaml` entirely, and the async-context trap (`crew.py:1598` passes async
tasks only `[last_sync_output]`) never arises, because each branch crew receives
its inputs through `kickoff()`.

**Five crews, not one.** A `Crew` cannot pause mid-sequence and return control,
so the pipeline is cut at exactly the two gates: `ScopeCrew` → gate → three
branch crews → `SynthesisCrew` → gate → `ReportCrew`.

### 7.1 The roster

Six agents. Prompts are written in the register of `agents/01-researcher.md` —
specific, sceptical, earned-experience, no marketing adjectives — because
`agents.yaml` blocks in this repo are *"written to be pasted, not paraphrased"*.

| Agent | Tier | Tools | `max_iter` | `max_rpm` | `max_exec` | `inject_date` |
|---|---|---|---|---|---|---|
| `scoper` | **ESCALATION** | none | 3 | — | 120 | ✅ |
| `market_analyst` | CHEAP | `research_market_landscape` | 12 | 6 | 600 | ✅ |
| `sentiment_analyst` | CHEAP | `analyze_community_sentiment` | 8 | 10 | 240 | ✅ |
| `feasibility_analyst` | CHEAP | `assess_technical_feasibility` | 8 | 4 | 240 | ✅ |
| `synthesist` | **ESCALATION** | none | 6 | — | 300 | — |
| `reporter` | ESCALATION *(A/B)* | none | 8 | — | 300 | — |

**Why the Scoper is escalation-tier despite being the smallest agent.** Its
output fans out ×3. A bad `market_query` is not one bad answer — it is three
branches researching the wrong category, and a human approving a scope that
reads plausible. The repo's own rule (*"selection and framing is where quality is
decided"*, `02-analyst.md`) applies harder here than to the Analyst, because the
Analyst's errors are visible in its output and the Scoper's are invisible until
the verdict. Cost is ~$0.0024/run; the cheap tier would save $0.002 and risk the
run.

**Why the Scoper writes the queries at all.** The tutorial builds them by
f-string: `f"{startup_idea} market size competitors industry analysis"`. For *"an
AI tool that reads physio clinic intake forms"* that searches the literal pitch
and returns nothing about the clinic-software market. A query written from the
*category* is the single highest-leverage improvement in this design, and it
costs one already-necessary LLM call.

**Why the three analysts are cheap-tier.** Same argument as the Researcher: their
context is dominated by scraped markdown, so **input price dominates** — $0.075
vs $0.75/Mtok. The judgement they exercise is a rule their task states, not an
inference they must originate.

**Why the Synthesist is not.** Mapping heterogeneous evidence onto anchor text is
the one genuine judgement in the pipeline, and its errors are the least visible
downstream — a wrong score still produces a well-formed report.

⚠️ **Do not copy `reasoning_effort: "minimal"` from `agents/05-evaluator.md` onto
the Synthesist.** It works there because the Evaluator does *lookup* (does a
`## Sources` section exist). The Synthesist does *anchoring* — whether three
independent posts in 24 months put us at D=3 or D=4. Minimal effort buys ~8× on
the cheapest call in the run and removes the only reasoning it does.

⚠️ **Escalation trigger, `feasibility_analyst` only.** This is where cheap models
fail characteristically: the **star-count fallacy** — treating popularity as
maturity and repo count as saturation. If verdicts start turning on *"there are
40 projects so this is solved"* with no licence or commit date in the rationale,
escalate that agent alone. Do not escalate the fan-out.

**Two A/B candidates, ranked.** `reporter` is the best cheap-tier candidate for
exactly the reason `03-writer.md` nominates the Writer — heavily templated task,
most output-heavy agent, 15× difference on completion tokens. `scoper` is second,
and it is the more interesting experiment: the human gate is a free corrector, so
*"how often does the operator hit `scope_revise` on each arm"* is a real quality
metric, unlike the four unresolvable comparisons in `05-evaluator.md`.

### 7.2 Tool surface

All three tools return a **JSON envelope**, following
`PineconeRetrieveRerankTool`'s precedent. The tutorial returns prose; prose
cannot be counted, and both the rubric (§10.2) and the guardrails (§10.4) depend
on counting.

```json
{ "status": "ok | empty | rate_limited | failed",
  "tool": "research_market_landscape",
  "query": "<the query actually sent>",
  "retrieved_at": "2026-08-29T06:20:13Z",
  "result_count": 5, "results": [ … ], "notes": "…" }
```

**URL attribution is structural, not prose.** Every result carries a non-empty
`url`; each agent is told in its task that it has no other way to obtain one. So
a URL in the findings that is not in a tool result is *unambiguously invented*,
and `check_findings` enforces exactly that by set difference. This also closes a
known repo defect — `index_content` writes `url: ""` and `_format_hits` then
renders `url: unknown` above passages that contain real URLs
(`agents/06-retrieval-layer.md`).

| Tool | Endpoint | Auth | Limit |
|---|---|---|---|
| `research_market_landscape` | Firecrawl `search()` v2 with `ScrapeOptions(formats=["markdown"])` | `FIRECRAWL_API_KEY` | plan-dependent, **not verified** — detect, don't hard-code |
| `analyze_community_sentiment` | HN Algolia `/api/v1/search?tags=story` | none | ~10k/hr per IP |
| `assess_technical_feasibility` | GitHub `/search/repositories` | optional `GITHUB_TOKEN` | **10/min per IP** unauth |

⚠️ **`from firecrawl import ScrapeOptions` is an `ImportError` on 4.x** — it is
`from firecrawl.v2.types import ScrapeOptions`. This is already recorded in
`agents/00-shared-config.md` §9, **and it is exactly what the tutorial's code
does.**

⚠️ **`SearchData.web` is an undiscriminated union.** With `scrape_options` you
get `Document`s (URL at `.url`); without it, `SearchResultWeb`s (URL at
`.metadata.source_url`). Handle both, or the tool works in testing and returns
`url: None` the first time a scrape degrades a row.

⚠️ **HN Algolia returns no `x-ratelimit-*` headers at all** — verified live
2026-08-29; the response carries only `content-type`, `x-cloud-trace-context`,
`date`, `server`. You cannot observe your approach to the limit. Detect 429 and
back off; do not write logic that reads a remaining-quota header.

⚠️ **HN `story_url` is frequently `null` for Ask HN posts** — which are the
highest-value threads for the Demand dimension. Always cite
`https://news.ycombinator.com/item?id={objectID}`, which always exists. It is
also the *correct* citation on principle: the claim is "people said this", and
the artefact supporting it is the thread, not the article it linked to.

**Fetch comments, not just titles.** The tutorial reads `tags=story` and infers
sentiment from **titles and point counts** — but a title is a headline, and
sentiment lives in the replies. Our tool pulls the comment tree for the top N
threads (`GET /api/v1/items/{objectID}`). This is the difference between *"a
thread about this got 300 points"* and *"four people described the spreadsheet
they maintain instead"* — and the second is what the Demand anchors at level 4
and 5 actually require.

⚠️ **GitHub returns `403` to any request with no `User-Agent` header.** It reads
as an auth failure and is not one. Send one.

⚠️ **GitHub's 10 req/min is per IP and shared across all three threads** —
verified live 2026-08-29 (`X-RateLimit-Resource: search`, `Limit: 10`, ~60 s
reset; the separate `core` bucket is 60/hr). `max_rpm` **cannot** enforce this:
per-agent controllers cannot see siblings, and they throttle the executor loop,
not the HTTP call. **A module-level token bucket must live inside the tool** —
8/min unauthenticated, 24/min with a token. This is the one limiter in the design
that belongs below the agent layer.

⚠️ **Per-agent `max_rpm` silently discards a crew-level budget.**
`base_agent.py:614` builds the agent's own `RPMController` at construction;
`set_rpm_controller` (`base_agent.py:821`) assigns *only if none exists*, so
`crew.py:762`'s shared controller is dropped with no warning. Three per-agent
budgets therefore do not sum to a system budget.

### 7.3 Gates

Both gates use the native `@human_feedback` primitive (§9), not
`Task(human_input=True)` (§14 R-5).

| Gate | After | `emit` | What the operator sees |
|---|---|---|---|
| 1 | `scoper` | `["scope_ok", "scope_revise"]` | the parsed `ScopedIdea`, fields editable |
| 2 | `synthesist` | `["verdict_ok", "verdict_revise"]` | the scored rubric, verdict and confidence band |

⚠️ **`@human_feedback` defaults to `llm="gpt-5.4-mini"`** (`flow/human_feedback.py:176`).
This project has **no `OPENAI_API_KEY`** — `memory=False` exists specifically to
keep the OpenAI embedder unreachable. The default is truthy, so the
`emit`-requires-`llm` validator *passes*, and the run then dies at the first
pause on a missing key. **Pass `llm=CHEAP_MODEL` explicitly at both gates.**
Collapsing free text to a two-value label is the cheapest call in the system and
belongs on the cheap tier — and per §14 R-10, a button-click resume with `""` +
`default_outcome` skips it entirely.

### 7.4 Interpolation traps

⚠️ **A missing `{variable}` raises — `tasks.yaml`'s own comment is wrong for
1.15.18.** It claims *"a missing input is not an error — CrewAI leaves the
literal `{research_notes}` in the prompt"*. In fact `interpolate_only`
(`utilities/string_utils.py:138`) raises `KeyError`, which
`task.py:1090` converts to `ValueError("Missing required template variable …")`.
It fails loudly. **Correct that comment** — it is in the Brief Crew's file and
currently misleads.

⚠️ **Lists interpolate as Python `repr`.** `community_queries: ["a","b"]` renders
as `['a', 'b']` in the prompt. Pass pre-joined newline blocks
(`community_queries_block`) instead. Types are validated to
`str|int|float|bool|dict|list`; a `datetime` raises.

⚠️ Because a missing key raises, **optional inputs must be passed as `""`, never
omitted** — `human_override` on the accept path being the live case.

### 7.5 ⚠️ Three parallel crews interleave on one stdout

`verbose=True` output is not decoration in this repo — `agents/00-shared-config.md`
§8 calls it *"the only view you have of who handed off to whom"*, and `README.md`
makes it the demo artefact. Three branch crews running on three threads write to
one stdout, so **the fan-out segment of the trace becomes unreadable.**

Prefix every branch's output with its node name via a `task_callback`, or accept
it and say so. This is separate from the cp1252 encoding fix already in
`__init__.py`, which solves a different problem (that one *destroys* the trace;
this one *scrambles* it).

The UI is the real answer — per-node chat rails (§8.6) make interleaving a
non-issue — but M3 lands the crew before M2's studio is wired to it, so the
headless trace has to stay legible on its own.

## 8. UI / UX specification

Derived by reverse-engineering DevAll's `frontend/src/pages/LaunchView.vue`
(3,705 lines) and its components. File:line references below are into
`<local-checkout>/ChatDev-main/frontend/`.

### 8.1 Layout

`/launch` owns the whole viewport — `App.vue:9` hides the global sidebar on that
route. Structure is pure flex plus two absolute-overlay modes.

```
.launch-view                 100% × 100vh · flex column · #1a1a1a · Inter
├─ .launch-bg                fixed · top -150px · h 500px · brand gradient
│                            · blur(120px) · opacity .15 · pointer-events none
├─ .header                   h 40px · rgba(255,255,255,.05) · blur(5px)
│                            h1 18/600 · gear button (#a0c4ff)
└─ .content                  flex 1 · padding 20 · gap 20
   ├─ .left-panel            flex 3
   │  ├─ .chat-panel         ← two modes, below
   │  ├─ .graph-panel        v-show graph · VueFlow + Background + Controls
   │  └─ .right-panel-fab    bottom-right 56×56 r16
   └─ .right-panel           flex 1 · min-width 250px
```

| Pane | Chat mode | Graph mode (the screenshot) |
|---|---|---|
| Chat rail | `position: relative`, fills `.left-panel`, flat panel skin | `position: absolute; width 380px; max-width 50%; z 10; pointer-events none` with an inner `pointer-events: auto` overlay skin `rgba(26,26,26,.92)` + `blur(12px)`, `transition: width .3s` |
| Right panel | in-flow `flex 1` | `position: absolute; width 300px; max-width 40%; z 10` |
| Collapsed (either) | — | `width: 0` |

Rail collapse control: `.chat-panel-toggle`, 28×28, `top 12px; right -28px`,
`border-radius 0 8px 8px 0`, chevron rotates 180° when collapsed.

⚠️ **There are no media queries anywhere in DevAll.** Below ~900 px a 380 px rail
plus a 300 px panel plus node cards collapse into mush. **We add breakpoints** —
this is a defect we are not inheriting.

⚠️ **Correction to the brief.** The photo's bottom-left round control is Vue
Flow's own `<Controls>` (zoom / fit / lock), not a pencil FAB. The only FAB is
`.right-panel-fab`, bottom-**right**, a 3-circle graph glyph.

### 8.2 Design tokens

DevAll defines no CSS custom properties except two node vars. The token block
below was hand-extracted from its scoped styles and is what we actually ship.
Abridged here to the load-bearing values; the full block goes in
`frontend/src/assets/styles/tokens.css`.

```css
:root {
  /* Ground */
  --bg-app:          #1a1a1a;   /* app background                  */
  --bg-node:         #2a2a2a;   /* node fill + handle ring         */
  --surface-panel:   rgba(255,255,255,0.03);  /* panels, canvas    */
  --surface-raised:  rgba(255,255,255,0.05);  /* bubbles, chips    */
  --surface-overlay: rgba(26,26,26,0.92);     /* rail in graph mode*/
  --surface-well:    rgba(0,0,0,0.20);        /* status, toggle    */

  /* Borders */
  --border-default:  rgba(255,255,255,0.10);
  --border-avatar:   rgba(255,255,255,0.20);
  --border-hover:    rgba(255,255,255,0.30);

  /* Text */
  --text-primary: #f2f2f2;  --text-body: #e0e0e0;  --text-title: #fff;
  --text-muted:   #aaa;     --text-40: rgba(255,255,255,0.4);  /* labels, timestamps */

  /* Accent triad — the brand gradient */
  --accent-mint: #aaffcd;  --accent-cyan: #99eaf9;  --accent-blue: #a0c4ff;
  --gradient-brand: linear-gradient(135deg,#aaffcd,#99eaf9,#a0c4ff);
  --gradient-danger: linear-gradient(135deg,#e07152,#dc5d4c,#bd4a4a);
  --link-cyan: #64b5f6;                        /* "Show More" toggle */

  /* Semantic */
  --warn-bg: rgba(255,204,0,.12); --warn-border: rgba(255,204,0,.4); --warn-text: #ffe082;
  --err-bg:  rgba(255,82,82,.12); --err-border:  rgba(255,82,82,.4); --err-text:  #ffcccc;

  /* Canvas + dot grid */
  --canvas-bg: var(--surface-panel);   /* ≈ #1f1f1f over --bg-app */
  --dot-color: #aaa;  --dot-gap: 20px;  --dot-size: 1px;

  /* Edges */
  --edge-stroke: #f2f2f2;  --edge-width: 1.2px;  --edge-inactive: #868686;
  --edge-label-bg: rgba(10,10,10,.9);  --edge-label-brd: #f2f2f2;
  --edge-in-grad:  #FFD97A → #FFB84D → #FF6A00;   /* entry hover  */
  --edge-out-grad: #00F5D4 → #00C7E6 → #00A0FF;   /* exit hover   */

  /* Radii — 12px is the house radius: panels, bubbles, nodes, primary buttons */
  --r-xs: 3px; --r-sm: 4px; --r-md: 6px; --r-lg: 8px; --r-2xl: 12px;
  --r-fab: 16px; --r-pill: 20px; --r-full: 50%;
  /* Bubbles are asymmetric: r12 with border-top-LEFT-radius 2px (agent),
     flipped to top-RIGHT for the user. */

  /* Type — Inter variable 100–900 */
  --fs-11: 11px;  /* NODE KIND LABEL: 700, uppercase, ls 1px */
  --fs-12: 12px;  /* section labels (600, ls .5px), timestamps, node desc, edge label */
  --fs-13: 13px;  /* status, view toggle */
  --fs-14: 14px;  /* body, markdown, inputs */
  --fs-15: 15px;  /* node title (600, #fff) */
  --fs-18: 18px;  /* header h1 */

  /* Spacing — 4/6/8/10/12/16/20/24 */
  /* content pad 20 gap 20 · control-section pad 20 gap 16
     · chat-messages pad 20 gap 12 · node pad 12 */

  /* Glow — all keyed off --accent-cyan */
  --glow-input:  0 0 15px rgba(153,234,249,.30);
  --glow-bubble: 0 0 12px rgba(153,234,249,.35);
  --blur-panel:  blur(5px);  --blur-rail: blur(12px);  --blur-hero: blur(120px);
}
```

**Animations worth lifting:** `node-glowing` (4 s linear infinite — hue-rotate
0→360°, saturate→1.6, `drop-shadow(0 0 16px var(--node-shadow-color))`,
scale→1.02) and `node-pulse` (2 s ring stack) together *are* the running-node
look. Plus `borderPulse` on the input shell, `gradientShift` on primary buttons,
and `bubbleGlow` on the spinner bubble.

### 8.3 Node rendering — where we diverge most

**DevAll has exactly two node states: default and `.workflow-node-active`.**
There is no idle / completed / error / waiting treatment at all. Our graph needs
five, so this is invented, not copied:

| State | Treatment |
|---|---|
| `idle` | base skin, gradient border at ~40 % opacity |
| `running` | `node-glowing` + `node-pulse` + the sprite's 2-frame walk (`D-2 ↔ D-3` @ 500 ms) |
| `waiting` | steady `--accent-blue` border, no animation, prompt badge on the node |
| `completed` | gradient border at full opacity, subtle inner fill, no animation |
| `error` | `--err-border`, `--err-bg` tint, no animation |

The base skin itself is worth lifting verbatim — a **gradient-border trick** that
avoids a wrapper element (`utils/vueflow.css:3-26`):

```css
--node-bg: #2a2a2a;
--node-gradient: linear-gradient(135deg,#666,#999);   /* per node type */
background-image: linear-gradient(var(--node-bg),var(--node-bg)), var(--node-gradient);
background-origin: border-box;
background-clip: padding-box, border-box;
border: 2px solid transparent;
```

⚠️ **Do not copy `utils/colorUtils.js`.** Its palette (15 curated 3-stop pastels)
is good; its assignment is broken. `index = hash % 15 + 1` can yield `15`, which
is out of range, and if all slots are taken the linear-probe loop never breaks →
`PREDEFINED_PALETTES[15]` is `undefined` → TypeError. Colours are also unstable
across reloads, because assignment order depends on render order. **Our roster is
fixed — hard-code the agent→palette map.**

### 8.4 Sprites

Scheme: `/sprites/{character}-{stance}-{frame}.png` — 144 PNGs = 12 characters ×
4 stances (`D`/`L`/`R`/`U`) × 3 frames (1 = idle, 2/3 = the walk cycle's contact
poses). Individual files, not a spritesheet.

⚠️ **Assignment is random-without-replacement and not memoised on the chat
path.** `fetchSprite()` called with no `node_id` (which is what `addDialogue`
does) returns a *random* character unrelated to that node's graph sprite — so an
agent's face in the rail can differ from its face on the canvas, depending on
which code path ran first. Collisions also begin at the 13th distinct id.

**We replace this with `character = (hash(agentName) % 12) + 1`** so an agent
keeps one face across the canvas, the rail, and reloads.

⚠️ **Downscale the assets.** Source PNGs are 500–1000 px (`1-D-1.png` is
508×847) and render at 32×40. Ship them at 64×80.

### 8.5 Edges and the handoff animation

Lift the **label pill** and the **hover entry/exit treatment**; reject the
routing.

The pill is HTML in `<EdgeLabelRenderer>`, not SVG: `rgba(10,10,10,.9)` on a 1 px
`#f2f2f2` border, `r3`, 12 px, `white-space: pre-line` so multi-clause conditions
stack. That is the `includes: ###REVISE###` chip in the screenshot.

On hover, edges split into entry (warm `#FF6A00` family) and exit (cyan
`#00A0FF` family): stroke swaps to a gradient, a **second overlaid `<BaseEdge>`**
turns on at `strokeWidth 2.3` with a `feGaussianBlur σ6` glow filter, and a Web
Animations dash march runs `strokeDashoffset 0 → -totalLength`.

⚠️ **Reject `WorkflowEdge.vue`'s routing** — 260 lines of bespoke arc maths
including a hand-written SVG-arc centre-parameterisation, all of it compensating
for a *free-form editor's* node placement. We lay out a fixed topology
ourselves; `getBezierPath` plus one self-loop case covers it. Also hoist the
`<defs>` out of the per-edge component — DevAll renders N duplicate `<defs>`
with identical ids.

⚠️ **The single most fragile thing in DevAll, and we are not inheriting it.** The
sprite-walking-the-edge handoff animation is triggered by **regex-matching a
human-readable log string** — `/Edge condition met for (.+) -> (.+)/`
(`LaunchView.vue:1972-1993`). There is no structured edge event. We emit
`{type:"edge_traversed", data:{from, to}}` and keep only the animation body
(`:1996-2093`), which is sound: it creates an `<image>` in the SVG namespace and
walks it along `path.getPointAtLength(t·len)` over
`clamp(pathLength × 0.02, 2000, 4000) ms`, cycling frames `1→2→1→3` every 250 ms
with stance `L`/`R` from the path direction.

### 8.6 The chat rail

Lift near-verbatim. Per entry: 40×40 round avatar (`object-position: 50% 20%` so
the sprite's head centres), actor name at 12 px `rgba(255,255,255,.5)`, HH:MM:SS
timestamp at `--text-40`, then the asymmetric bubble. System entries render as
centred cards with no avatar; warning and error variants use the semantic tokens.

`CollapsibleMessage.vue` **is** the Show More / Show Less card, and its fade is
the nice part — `mask-image: linear-gradient(to bottom, black calc(100% - 60px),
transparent)`. Two fixes on the way in: hard-coded English at `:39`, and
`checkHeight()` running only on mount and on content change with no
`ResizeObserver`, so late-loading images leave the toggle in the wrong state.

**The loading-bubble machinery is the best UX in DevAll and transplants cleanly.**
One spinner bubble per node; a chip per model/tool call carrying a live `mm:ss`;
all chips frozen on `NODE_END`. It is keyed on `MODEL_CALL`/`TOOL_CALL` with
`stage: "before" | "after"` — which is exactly the shape of CrewAI's
`LLMCallStarted`/`Completed` and `ToolUsageStarted`/`Finished` pairs.

### 8.7 Right panel and controls

`WORKFLOW SELECTION` (select) · `STATUS` (read-only well) · `VIEW`
(Chat | Graph segmented toggle) · then the button stack: one computed primary
button, then Cancel, then Download Logs.

The primary button's label is derived, not fixed: **Send** while running,
**Relaunch** when `Completed`/`Cancelled`, else **Launch**.

⚠️ **Two behaviours we deliberately change:**

1. **Relaunch makes no HTTP call.** In DevAll it wipes the chat and session and
   merely *re-arms* — the user must then press Launch again. Ours re-runs.
2. **Cancel is optimistic.** DevAll flips the UI to `Cancelled` on send and never
   waits for `workflow_cancelled`. Given §14 R-4 (a CrewAI Flow may not be
   cooperatively cancellable), ours must show *"stopping…"* and settle only on
   the server's confirmation — the UI must not claim a run stopped when it has
   not.

⚠️ `getTranslatedStatus` omits four statuses it needs and maps three that no code
sets. **Model status as an enum and derive the label**, rather than switching on
a display string.

### 8.8 Verdict table

| DevAll asset | Verdict |
|---|---|
| `utils/vueflow.css` | **Lift** — the gradient-border trick and both active animations |
| `components/StartNode.vue` | **Lift** — strip `RichTooltip` + `configStore` |
| `components/CollapsibleMessage.vue` | **Lift** — fix i18n and add a `ResizeObserver` |
| Chat rail markup + CSS | **Lift** — zero backend coupling |
| Right-panel control section | **Lift** |
| Loading-bubble / call-chip machinery | **Lift** — re-key onto CrewAI event pairs |
| `components/WorkflowNode.vue` | **Adapt** — 2 states → 5; de-duplicate the tooltip template branches |
| `utils/colorUtils.js` | **Adapt** — keep the palette, replace the assignment |
| `utils/spriteFetcher.js` | **Adapt** — deterministic hash, memoise both paths |
| WS client layer | **Adapt** — keep the `processMessage` switch; rewrite the socket lifecycle (no reconnect/backoff/dedupe today) |
| `components/WorkflowEdge.vue` | **Split** — lift the label pill + hover glow, reject the routing |
| The two-mode overlay layout | **Adapt** — add breakpoints |
| Graph editor (`WorkflowWorkbench`, `FormGenerator`, `schema_registry/`, `/api/vuegraphs`) | **Drop** — biggest chunk of the codebase, none of it applies to a fixed topology |
| `BatchRunView` + batch WS messages | **Drop** |
| Microphone recorder (~140 lines behind `v-if="false"`) | **Drop** |
| `RichTooltip` + `helpContent.js` | **Drop** — and this removes the template duplication in three components |
| `"Edge condition met"` regex handshake | **Drop** — replaced by a structured event |

## 9. Transport, event bridge and human gates

Every claim in this section was verified by **executing** probes against
`crewai==1.15.18` in `.venv`, not by reading source alone.

### 9.0 ⚠️ The Brief Flow's graph is disconnected today

Running `build_flow_structure(BriefFlow)` right now produces:

```
WARNING  Router events for 'check_cache' are dynamic or not statically inferable
WARNING  Static visualization could not match listener triggers
         {'cache_hit', 'cache_miss'} to explicit router events

edges: retrieve_cached→check_cache, scrape_web→index_content,
       index_content→write_brief, write_brief→persist
paths: 1
```

`check_cache` is a **dead end**. `scrape_web` is **orphaned**. The entire
`cache_hit` branch — the feature the Flow exists for — does not appear in the
graph at all.

Cause: `@router` infers its events from a `Literal`/`Enum` return annotation when
`emit=` is not given (`flow/dsl/_router.py:86-88`), and `main.py:105` declares
`def check_cache(self) -> str:`.

**The fix is one line, verified:**

```python
@router(retrieve_cached)
def check_cache(self) -> Literal["cache_hit", "cache_miss"]:
```

→ 6 edges, including `check_cache --cache_hit--> write_brief` and
`check_cache --cache_miss--> scrape_web`; `paths: 2`; zero warnings.

It is a type annotation and changes no runtime behaviour, so it is **G6-safe**.
It is also the highest-priority change in this PRD: without it the graph endpoint
returns a wrong topology and the entire UI is drawing a lie.

### 9.1 The capture seam — four candidates, measured

`agents/08-observability.md` §7 specifies a sync `BaseEventListener`. **Measurement
says that is the worst of the four options.**

| Seam | Runs on | Order | Run isolation | Payload control |
|---|---|---|---|---|
| **A · Stream sink** (`add_stream_sink`) | inline, emitting thread | ✅ **0 inversions** | ✅ **free** — sinks live in a ContextVar | full |
| **B · `async def` listener** | the bus's single `CrewAIEventsLoop` | ✅ **0 inversions** | via ContextVar | full |
| C · **sync** listener *(as §7 writes it)* | 10-worker `CrewAISyncHandler` pool | ⚠️ **11 inversions / 200 events** | via ContextVar | full |
| D · `Flow.astream()` | uvicorn loop | ✅ | ✅ free | ❌ none |

**A as primary, B as the safety net.**

The sink is the only seam where the process-wide-singleton problem *cannot
occur*: sinks are held in a ContextVar, so it is structurally impossible for run
A's sink to see run B's events. Measured across two concurrent runs × 120 events:
**0 inversions, 0 leakage.** That retires §14 R-1 by construction rather than by
discipline. Its one cost is that it is inline — the sink body must be O(1) and
must never raise, since `publish_stream_event` has no `try/except` of its own.

**Reject D.** `astream()` is tempting, but `stream_frame_from_event` dumps the
whole event at `to_serializable(max_depth=5)` — and a `CrewKickoffCompletedEvent`
carries a live `Crew`, which carries agents → tools → LLM objects. Frames run to
hundreds of KB. Its `seq` is also a *per-context* counter, not globally
monotonic, so it cannot support the gap-check §13 requires.

⚠️ **Order is a correctness precondition, not a cosmetic one.** `seq` is assigned
at capture, so if capture order ≠ emission order the UI can render `NODE_END`
before `NODE_START`. Never register a plain sync handler.

### 9.2 The frame contract

DevAll's envelope, kept, with four additions:

```jsonc
{ "type": "frame", "data": {
    "v": 1,
    "seq": 128,                        // ADDED — per-run, gapless, server-assigned
    "run_id": "3c0ebab7-…",            // ADDED — DevAll conflates run and session
    "ts": "2026-08-29T06:14:02.418Z",
    "kind": "node_state",              // ADDED — frame family
    "event_type": "NODE_START",        // DevAll's enum, unchanged
    "level": "INFO",
    "node_id": "market_research",
    "message": "Market Analyst started",
    "details": { },
    "duration_ms": 1234 } }
```

`kind ∈ {run_state, node_state, edge_taken, agent, tool, llm, token, gate_open,
gate_closed, metrics, error}`.

`seq` exists because §13 makes *"0 dropped frames, measured by sequence gap
check"* a success metric, and DevAll's `LogEntry` has no sequence field at all.

**Mapping highlights** (full table in the implementation notes):

| CrewAI event | `kind` | Notes |
|---|---|---|
| `MethodExecutionStarted/Finished` | `node_state` | the graph nodes |
| ↳ when `method_name` is a router | `edge_taken` | **`event.result` *is* the branch** — there is no router event |
| `MethodExecutionFailedEvent` | `node_state` (ERROR) | ⚠️ the Finished event has **no** `error` field; failure is a separate class |
| `HumanFeedbackRequested/Received` | `gate_open`/`gate_closed` | §9.4 |
| `ToolUsageFinishedEvent` | `tool` | carries **`from_cache`** — makes `run_sources` populatable for the first time |
| `LLMCallCompletedEvent` | `llm` | carries `model`, so cost is **per-tier**, not an upper bound |

⚠️ **The correlation trap.** Field population is inconsistent per family, and the
obvious code is wrong:

```python
node = registry.resolve(event.task_name, event.agent_role)   # WRONG on agent events
```

| Family | `task_id`/`task_name` | `agent_id`/`agent_role` |
|---|---|---|
| LLM, ToolUsage | ✅ populated | ✅ populated |
| `TaskStarted/Completed` | ✅ | ❌ `None` — read `event.task.agent` |
| `AgentExecution*` | ❌ `None` | ❌ `None` — read `event.agent.role` |
| Flow / MethodExecution / CrewKickoff | ❌ `None` | ❌ `None` — correlate via `parent_event_id` |

⚠️ **`source` is the emitting object, not the Flow** — a `Task`, an `Agent`, an
`LLM`. `source.flow_id` works only for Flow-family events. The universal key is
CrewAI's own `current_flow_id` ContextVar, set at
`flow/runtime/__init__.py:2186`.

⚠️ **Never call `event.to_json()`.** Build frames field-by-field through a
`clip()` helper that bounds every string and stops at `repr()` for objects. One
un-clipped `CrewKickoffCompletedEvent` serialises an entire live `Crew`.

### 9.3 Node identity

| Candidate | Measured on `BriefCrew` | Stable? |
|---|---|---|
| `agent_id` | `0dab7da7-…` fresh UUID per construction | ❌ |
| `agent_role` | `'Senior Research Analyst specialising in {topic}\n'` | ❌ interpolated, plus YAML's trailing `\n` |
| `task_name` | `'research_task'` | ✅ |
| flow `method_name` | `'retrieve_cached'`, `'check_cache'` | ✅ |

> **`node_id` is a declared string in the graph descriptor. Nothing is derived
> from a UUID or from an interpolated string.**

A `NodeRegistry` joins graph space to CrewAI space, resolving in order:
**`task_name` → `agent_role` template prefix → `current_flow_method_name`
ContextVar → `QUARANTINE`**.

**The hard case is the validator's own fan-out.** Three analysts inside one flow
method share `current_flow_method_name`, so rule 3 alone would collapse them into
one box. **Rule 1 separates them** — `Task.name` is distinct and stable, and
`Task.execute_async` copies the context (`task.py:616-623`), so `ui_run_id`,
`current_flow_id` and `current_flow_method_name` all survive into a branch.

**On `QUARANTINE`.** Unattributable frames land on a *visible* node labelled
"Unattributed", counted in `/status`. This node will not stay empty: a bare
`threading.Thread` inside a flow method loses the entire context
(`ui_run_id=None`, `flow_method='<unset>'` — measured). Routing those frames to
`None` and filtering them would hide a real instrumentation gap; routing them to
a box turns it into a bug report.

### 9.4 Human gates — the native primitive

`Flow.plot()` is a two-liner that writes an HTML file and opens a browser —
useless as an API. But `build_flow_structure()` underneath it is exactly right,
and **`FlowMethodDefinition.description` is auto-populated from the first line of
each method's docstring** (`flow/dsl/_utils.py:417-423`). Labels and descriptions
already live in the code.

**Recommendation: derive, then enrich.** DevAll declares topology in YAML because
DevAll is an authoring tool; §4.2 makes an editor a non-goal. A sidecar would be
a second source of truth that drifts the moment someone adds a `@listen`. So:
derive nodes/edges/labels from `build_flow_structure()` at import; overlay only
what the Flow cannot express — `kind` refinement, `x`/`y`, and the sub-node split
— and **validate the overlay against the derived structure at import**, so a
stale key raises at startup rather than rendering wrongly.

Assert at import that every router has non-empty `router_events` (§9.0's failure
is a `logging.warning` nobody reads).

**The gate mechanism.** The provider raises `HumanFeedbackPending`; the engine
catches it, persists, emits `FlowPausedEvent`, and — critically —

```python
# flow/runtime/__init__.py:2440-2442
# Return the pending exception instead of raising
return e
```

So the idiom is `result = flow.kickoff(); if isinstance(result, HumanFeedbackPending): …`,
and the resume arrives later on a different thread, request, **or process**.

This is not a stylistic preference. **Scenario C (§5) and Render's
SIGTERM-then-SIGKILL shutdown make it a correctness requirement**: a blocking
primitive parks a worker thread for up to 30 minutes and loses the run on the
next deploy.

**Routing the reply for zero LLM calls.** This project's thesis is that the one
dynamic decision costs no LLM calls. So the gates carry **no `emit=`**; the reply
is structured JSON and a following deterministic `@router` parses it:

```python
@human_feedback(message="Confirm the parsed scope before research begins.")
@listen(scope_idea)
def confirm_scope(self): ...

@router(confirm_scope)
def route_scope(self) -> Literal["scope_approved", "scope_revised"]:
    d = json.loads(self.state.gate_reply_raw or "{}").get("decision", "approve")
    return "scope_revised" if d == "revise" else "scope_approved"
```

Fallback if native routing is preferred: `emit=[…]` with `llm=CHEAP_MODEL` and a
`default_outcome`, where the Approve button resumes with `""` and skips the call.

⚠️ **Re-scoping on resume is mandatory and easy to forget.** The resume runs on a
new thread with a fresh context; without re-setting `ui_run_id` and re-registering
the sink, **every frame after the gate is unattributed.**

| Event | Behaviour |
|---|---|
| Timeout (default 1800 s) | gate marked `expired`, frame pushed. **The run is not failed and not auto-answered** — it stays resumable indefinitely. Scenario C, verbatim |
| Client disconnect | nothing happens; the flow is already unwound, there is no thread to lose |
| Reconnect | two independent paths: `GET /api/runs/{id}` returns `pending_gate`, and WS replay redelivers the `gate_open` frame |
| Redeploy | survives **only** with durable persistence — §9.6 |

⚠️ `pending_feedback` has `flow_uuid UNIQUE` — **one pending gate per run.** Ours
are sequential, but the descriptor validator must reject a graph with two `human`
nodes reachable in parallel.

### 9.5 Cancellation — R-4 is resolvable

There is no `stop()`, `cancel()` or `abort()` on `Flow`, `Crew`, `Agent` or
`Task`. `Crew._execute_tasks` is a plain `for` loop with no flag check, and
`Agent.max_execution_time` calls `future.cancel()` — **a no-op on a running
thread**, so the agent keeps burning tokens in an orphaned thread. An event
handler cannot abort anything either; its exceptions are swallowed.

**But `crewai.hooks` is a separate subsystem with the opposite contract:
`HookAborted` propagates by design.** `PRE_STEP` is dispatched before every flow
method and every task, and neither catches it.

```python
with scoped_hooks():                       # per-run, ContextVar-backed, no globals
    def guard(ctx):
        if rec.cancel.is_set():
            raise HookAborted(f"cancelled before {ctx.step_name}")
    register_scoped(InterceptionPoint.PRE_STEP, guard)
    return flow.kickoff(inputs=inputs)
```

Verified: with cancel set during method 2 of 3, `a` and `b` ran, `c` aborted, and
`kickoff()` raised `HookAborted('cancelled before c')`.

**Be honest about granularity.** Cancellation lands at the next flow-method or
task boundary. It will **not** interrupt an in-flight LLM call or a 30 s
Firecrawl scrape, so worst case is one agent turn — potentially minutes.
Therefore `POST /cancel` returns `{"status":"cancelling", "effect":"stops at the
next step boundary", "eta_hint":"up to one agent turn"}` and **the UI says
"stopping after the current step", never "stopped"** (§8.7).

⚠️ `HookAborted` *is* swallowed at `PRE_MODEL_CALL` and `PRE_TOOL_CALL`. Only
`PRE_STEP`/`POST_STEP` and the execution-boundary points work.

### 9.6 Backpressure, concurrency and persistence

**Three bounded stages, none of which can block a run:** a per-run ring
(2000 frames, oldest dropped, **counted**), a per-subscriber `asyncio.Queue`
(512, oldest dropped), and the socket write, awaited on the uvicorn loop only.
The capture side never awaits, never blocks, never raises. **A slow browser tab
cannot slow a crew**, and every drop is visible as a `seq` gap.

A bounded ring rather than an unbounded queue is the direct fix for R-2: it makes
loss *measurable* instead of *invisible*.

⚠️ `LLMStreamChunkEvent` is dispatched **inline in the emitting thread**, so its
handler must be a single `deque.append` — anything slower slows the model call.

`RUN_CONCURRENCY=1` on Render `starter` (~210 MB baseline against 512 MB).
Additional requests queue and report `status: "queued"`.

**Postgres, extending `agents/07-deployment.md`'s schema:** `runs` gains
`session_id`, `workflow_id`, `flow_id`, `graph_version`; three tables are added —
`run_node_metrics` (the per-agent split both `07` and `08` ask for),
`run_frames` (durable frame log, batched every 250 ms from a single writer task —
**never from a bus handler**, so a Postgres stall cannot slow a run), and
`run_gates`.

**`run_metrics.cost_usd` becomes measured rather than an upper bound** the moment
this listener lands: `LLMCallCompletedEvent` carries `model`, so tokens price per
tier instead of all at escalation. `07-deployment.md`'s caveat — *"writing it
into a column named `cost_usd` would launder an estimate into a measurement"* —
is retired by the listener, not by renaming the column.

⚠️ **`PostgresFlowPersistence` is required, not optional.** The default SQLite
backend writes to `db_storage_path()/flow_states.db` on Render's **ephemeral
disk**, so a gate pending at deploy time becomes unresumable. Implementing
`FlowPersistence` over one table mirroring `pending_feedback` is the single change
that makes **G5 true across a deploy** rather than only within one process
lifetime. Also raise `maxShutdownDelaySeconds` to 300.

⚠️ **Do not source per-node cost from `Flow.usage_metrics`.** Its own docstring
warns that sibling kickoffs under one parent share a correlation id and
over-count — which is exactly the validator's fan-out. Accumulate from
`LLMCallCompletedEvent` keyed on `(run_id, node_id, model)`; use `usage_metrics`
for the run total only, and **log the delta** if the two disagree rather than
silently trusting either.

**G6 is preserved literally.** `persist` is untouched; `output/brief.md` and
`last_run.json` keep the same keys. The listener is a **no-op** when both
`ui_run_id` and `current_flow_id` are unset, so `run_crew()` and `kickoff()`
behave identically whether the service is running or not.

### 9.7 API surface

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/workflows` | registered flows |
| `GET` | `/api/workflows/{id}/graph` | GraphDescriptor, `ETag: version` |
| `POST` | `/api/sessions/{sid}/runs` | **`202`** `{run_id, status:"queued", graph_version}` |
| `GET` | `/api/runs/{rid}` | status + `pending_gate` + `frames{count,dropped}` + `usage` |
| `GET` | `/api/runs/{rid}/frames` | `after`, `limit≤500`, `kinds` |
| `POST` | `/api/runs/{rid}/gates/{gid}` | `202` / `409` if already answered |
| `POST` | `/api/runs/{rid}/cancel` | `202` + explicit granularity |
| `GET` | `/api/runs/{rid}/logs` | `?format=ndjson\|zip` |
| `WS` | `/ws?session_id=&run_id=&after=` | frame stream |

**Deliberate divergences from DevAll:**

| Divergence | Reason |
|---|---|
| `run_id` ≠ `session_id` | DevAll conflates them; a session must hold several runs |
| Frames carry `seq`; ring reports `dropped` | DevAll's buffer silently `pop(0)`s at 1000 |
| No workflow CRUD | 8 of DevAll's 11 workflow routes exist to serve a graph editor (§4.2) |
| `gate_open`/`gate_reply` not `human_input_required`/`human_input` | ours carry `gate_id`, `options`, `expires_at`, `editable`, and resume **across processes**. Reusing the name for different semantics is worse than renaming |
| Gate reply over **both** HTTP and WS | a gate that outlives the socket must be answerable without one |
| No `/execute_sync` SSE route | Render's proxy will not hold a minutes-long request open |
| Kept verbatim | the `{type, data}` envelope, the `EventType` enum, `ping`/`pong`, reconnect-with-replay, session TTL GC |

## 10. Data model, rubric and guardrails

### 10.1 Schemas

Nine models in `src/brief_crew/schemas/`. **One level of nesting, never two** —
deep nesting makes models retry endlessly. `Evidence`, `Competitor`, `Thread`,
`Repo` and `DimensionScore` are flat leaves used as `list[...]` on a parent.

| Model | Stage | Notable fields |
|---|---|---|
| `Evidence` | leaf | `claim`, `url`, `publisher`, `dated`, `retrieved_via` |
| `Competitor` | leaf | `pricing` (as stated or `"not published"`), `vendor_owned` |
| `Thread` | leaf | `classification ∈ {HAS_PROBLEM, PAYS, BUILT_WORKAROUND, OPINION, OFF_TOPIC}`, `quote` |
| `Repo` | leaf | `license_permits_commercial`, `months_since_push`, `relevance` |
| `DimensionScore` | leaf | `score 0-5`, `anchor_matched`, `evidence_urls`, `evidence_thin` |
| `ScopedIdea` | 1 | the queries, 3–5 `assumptions`, `scoping_gaps`, `as_of` |
| `MarketFindings` / `SentimentFindings` / `FeasibilityFindings` | 2 | `sources`, `source_urls`, `gaps`, `tool_status` |
| `Verdict` | 3 | 5 `dimensions`, `evidence_counts`, `kill_criteria`, `cheapest_next_test` |
| `ValidationReport` | 4 | `markdown_body`, `provisional`, `thin_dimensions`, `sources` |

**`str` for URLs, not `HttpUrl`.** An `HttpUrl` rejection surfaces as an opaque
converter failure the retrying agent cannot act on. A `field_validator` with a
written message *becomes* the retry instruction — the same principle
`check_mechanics` already applies.

**`source_urls` deliberately duplicates the URLs in `sources`.** It exists to be
countable by a zero-cost guardrail without parsing nested objects. A guardrail
asserts the two stay in sync.

**The `Verdict` computes itself.** A `model_validator(mode="after")` overwrites
`composite_score`, `verdict`, `confidence`, `confidence_band` and `provisional`
from the five integers and the counts. Overwriting rather than validating is
deliberate: a model that miscomputes should produce a *correct verdict*, not a
failed run. The LLM contributes five anchored integers and nothing else — **that
is what makes two runs over the same evidence agree.**

### 10.2 The rubric

The tutorial has none. Five dimensions, all same-polarity (higher is better —
an inverted "risk" dimension is the most reliable source of run-to-run
disagreement).

| Code | Dimension | Weight | Question |
|---|---|---|---|
| **D** | Demand | **0.30** | Is anyone actively trying to solve this today? |
| **M** | Market | 0.20 | Is there money, and can you name whose? |
| **C** | Competitive room | 0.20 | Is the incumbent set beatable on a stated axis? |
| **F** | Feasibility | 0.15 | Can 2–3 engineers ship a v1? |
| **X** | Headroom over free | 0.15 | Is the core already free and good? |

**Demand is weighted highest because it is what the tutorial handles worst** —
a single ReAct agent reads HN sentiment as approval of the *idea* rather than
evidence of the *problem*. Anchoring D on workarounds and payments rather than
upvotes is the substantive improvement.

Every anchor is stated in countable terms; partial satisfaction of anchor *N*
scores *N−1*. Illustrative, the Demand ladder — **as first drafted, and
defective. It is kept verbatim below because this document is a design record;
do not score against it. Read the correction that follows:**

| | Anchor — *as first drafted. Superseded: see the correction below* |
|---|---|
| 0 | Every retrieved thread is ADJACENT. Nobody in the evidence describes having this problem. |
| **1** | **Evidence does not reach this question** — the branch returned nothing, or fewer than 3 usable threads. |
| 2 | 1–2 threads state the problem, or all such threads are older than 36 months. |
| 3 | ≥3 threads state it, ≥1 within 24 months, but nobody describes a workaround or a price paid. |
| 4 | Anchor 3, **and** ≥1 describes a manual workaround they maintain, or names a tool they pay for. |
| 5 | ≥5 threads within 24 months, ≥2 naming a workaround or a price, **and** the market branch independently names a paying segment. |

#### ⚠️ Correction, 2026-08-29 — three defects in the table above

Found by an audit of `RUBRIC_ANCHORS` in
[`src/brief_crew/config.py`](src/brief_crew/config.py) and verified against
[`src/brief_crew/schemas/validator.py`](src/brief_crew/schemas/validator.py).
All three make the ladder above unscoreable as written, on the dimension
weighted **0.30** — the heaviest of the five.

**1. D=4 was logically unsatisfiable.** Anchor 3 ended *"**but nobody describes
a workaround or a price paid**"*; anchor 4 read *"**Anchor 3**, and ≥1 describes
a manual workaround they maintain, or names a tool they pay for."* Anchor 4
required anchor 3 to hold **and** required the exact thing anchor 3 excludes. No
evidence state scores it. D=5 was reachable while D=4 was not, so the ladder
jumped 3 → 5 and the 0.30-weighted dimension silently lost a level.
**Fix:** anchor 3 no longer excludes the acted-on case; it is now the neutral
*"≥3 problem threads, ≥1 dated within 24 months"*, and anchor 4 adds the
workaround/payment clause on top of it. Anchor 5 builds on anchor 4 in turn.

**2. D=0 scored on `ADJACENT`, which is not a value the schema carries.**
`ThreadClassification` is `Literal["HAS_PROBLEM", "PAYS", "BUILT_WORKAROUND",
"OPINION", "OFF_TOPIC"]`. `ADJACENT` is not among them, so *"Every retrieved
thread is ADJACENT"* could not be evaluated against any field — and D=0 is a
`FLOOR_NO_DEMAND` **REJECT**.
**Fix:** D=0 is now stated over classifications that exist — at least one
*usable* thread (not `OFF_TOPIC`) and no *problem* thread (`HAS_PROBLEM`, `PAYS`
or `BUILT_WORKAROUND`).

**3. A dead band sat between D=2 and D=3.** D=2 fired on *"all such threads are
older than **36 months**"*; D=3 required *"≥1 within **24 months**"*. Three
threads whose newest is 28 months old matched neither anchor, so the dimension
had no score at all for that evidence state.
**Fix:** D=2's window is now **24 months**, the same window D=3 uses, which
closes the band. This is an amendment to this document's own text, not a
transcription of it.

#### The corrected Demand ladder

Semantically identical to `config.DEMAND_ANCHORS`, in this document's notation.
**The exact strings in `config.py` are what the guardrail matches** at
`ANCHOR_MATCH_THRESHOLD` token overlap; this table is the reasoning behind them.

| | Anchor |
|---|---|
| 0 | ≥1 usable thread, and none is a problem thread: nobody in the evidence describes having this problem. |
| **1** | **Evidence does not reach this question** — the sentiment branch returned no usable thread. |
| 2 | 1–2 problem threads, or ≥3 problem threads none of which is dated within 24 months. |
| 3 | ≥3 problem threads, ≥1 of them dated within 24 months. |
| 4 | Anchor 3, **and** ≥1 problem thread is classified `BUILT_WORKAROUND` or `PAYS`. |
| 5 | Anchor 4, **and** ≥5 problem threads dated within 24 months, ≥2 of them `BUILT_WORKAROUND` or `PAYS`, **and** the market branch names ≥1 paying segment. |

*usable thread* = a `Thread` not classified `OFF_TOPIC`. *problem thread* = a
`Thread` classified `HAS_PROBLEM`, `PAYS` or `BUILT_WORKAROUND`. Both terms are
defined once in the Synthesist prompt and reused across all five ladders, so
anchors stay short — short anchors stay far apart under the overlap metric,
which is what stops the guardrail accepting the neighbouring level's text.

Two rules make the ladders scoreable, and the Synthesist prompt states both:
score the **highest** level whose anchor is fully satisfied, treating
*"Anchor N, and …"* as cumulative; and partial satisfaction of anchor *N* scores
*N−1*.

#### ⚠️ This section is normative, but superseded where it conflicts with `config.py`

The five shipped ladders live in
[`src/brief_crew/config.py`](src/brief_crew/config.py) — `DEMAND_ANCHORS`,
`MARKET_ANCHORS`, `COMPETITIVE_ROOM_ANCHORS`, `FEASIBILITY_ANCHORS`,
`HEADROOM_ANCHORS`, keyed together as `RUBRIC_ANCHORS`. They are quoted verbatim
into `crews/validator_crew/config/tasks.yaml` and matched verbatim by
`validator_guardrails.anchor_problems`, so **they, not this section, decide what
a run scores.** Where this section and `config.py` disagree, `config.py` is
correct and this section is the record of how it got there. Read them before the
paid acceptance run: if an anchor is wrong, every verdict inherits the error and
the guardrail enforces it confidently.

#### ⚠️ M/C/F/X are a derivation, not a transcription

This section wrote out **only** the Demand ladder, and labelled it
*"Illustrative"*. **The Market, Competitive-room, Feasibility and
Headroom-over-free ladders were never written — not here, not in `agents/`, not
anywhere in the repo.** The four shipped ladders were *derived* from this
section's stated rules, weights, floor definitions and dimension questions, and
from the fields the schemas actually carry. They have since been **audited,
repaired and covered by tests**; they have **never been read by a human.** State
that plainly rather than presenting them as specification, because the two
failure modes are different: a transcription error is a typo, and a derivation
error is a judgement nobody made.

#### ⚠️ Level 1's reservation was under-specified, and three hard floors turned on it

⚠️ **Level 1 is "the evidence does not reach this", not a low score.** It sits
deliberately *above* 0 and must never be reached by inference: a model that
scores 1 because it *judges* demand weak has made an error — weak demand *with*
evidence is a 2. This is what keeps `composite_score` and `confidence` measuring
different things, and the guardrail enforces it (a score of 1 whose
`anchor_matched` is not the level-1 anchor verbatim is rejected).

What this section never said is **when level 1 fires.** The Demand ladder gave a
condition (*"the branch returned nothing, or fewer than 3 usable threads"*);
M, C, F and X carried the bare phrase *"evidence does not reach this question"*
and **no firing condition at all**. That left the boundary between a **fatal
floor** and *"we didn't look hard enough"* undefined for three of the four hard
floors — `FLOOR_NO_MARKET` (M=0), `FLOOR_NOT_BUILDABLE` (F=0) and
`FLOOR_ALREADY_FREE` (X=0) are each decided on exactly that boundary. Under the
under-specified wording an empty market branch — a Firecrawl 429, an exhausted
plan — could be scored M=0 and **REJECT an idea on the absence of evidence**,
which is the single failure §10.3's confidence override exists to prevent.

**Fix:** every shipped ladder now names its own branch condition at level 1 —
*"the market branch returned no source"*, *"the market branch named no
competitor"*, *"the feasibility branch returned no repository"*, *"no repository
is marked SOLVES_ENTIRELY or PARTIAL and no free product is named"* — and every
level-0 anchor is stated over evidence that **was** returned. A branch that came
back empty scores 1, never 0.

⚠️ The Demand level-1 condition also **drops this section's "or fewer than 3
usable threads"**. That test duplicates `DimensionScore.evidence_thin` (which is
`len(evidence_urls) < 3`) and the coverage term of confidence, and pushing it
into the score as well is the one thing this section says must not happen. It
also collided head-on with D=2 (*"1–2 threads state the problem"*), so a run
with two problem threads matched anchor 1 and anchor 2 at once.

```python
composite = round(2 * (0.30*D + 0.20*M + 0.20*C + 0.15*F + 0.15*X), 1)   # 0.0–10.0
```

Verdict, in evaluation order — **the confidence override runs first and beats
everything**:

```python
# 1. Thin evidence. Beats every floor and every threshold.
if confidence < 0.35:  return "NEEDS_WORK", "INSUFFICIENT_EVIDENCE"

# 2. Hard floors. A fatal dimension cannot be averaged away.
if D == 0:             return "REJECT",     "FLOOR_NO_DEMAND"
if X == 0:             return "REJECT",     "FLOOR_ALREADY_FREE"
if M == 0 and D <= 2:  return "REJECT",     "FLOOR_NO_MARKET"
if F == 0:             return "NEEDS_WORK", "FLOOR_NOT_BUILDABLE"

# 3. Thresholds.
if composite >= 7.0 and min(D,M,C,F,X) >= 3 and confidence >= 0.60:
    return "VALIDATE", None
if composite < 4.0:    return "REJECT", None
return "NEEDS_WORK", None
```

**Ordering is the design.** Putting the confidence override *first* means a floor
can never produce a REJECT on thin evidence — which is the failure this whole
rubric exists to prevent. Gating only VALIDATE is the intuitive mistake.

**The floors exist because averaging hides kills.** D=0 with M=C=F=X=5 composites
to 7.0 — a VALIDATE for an idea nobody has ever asked for. A weighted mean cannot
express *"this one is fatal"*; a floor can.

**`F == 0` caps at NEEDS_WORK rather than REJECT** because *"not buildable by
this team"* is a fact about the team, not about the idea. The other three floors
are facts about the world.

**`X == 0` is the most valuable output this system produces:** a maintained,
permissively licensed, popular project that already does the whole thing. No
market report surfaces it. The tutorial's GitHub tool *has* the data — it drops
the `license` and `archived` fields before the model ever sees them.

### 10.3 Confidence — separate, mechanical, gating both directions

```python
coverage  = 0.40*market_cov + 0.35*sentiment_cov + 0.25*feasibility_cov
staleness = 1.00 | 0.85 | 0.70      # by median market-source age: ≤12mo, ≤24mo, older
branch_penalty = 0.60 if branches_ok < 3 else 1.00
confidence = round(coverage * staleness * branch_penalty, 2)
```

Bands: **HIGH** ≥ 0.70 · **MODERATE** 0.35–0.69 · **LOW** < 0.35.

**The confidence override is the point of the entire design: at LOW confidence,
REJECT is unreachable.** A REJECT built on three sources is not a finding about
the idea, it is a finding about the run — and a system reporting it as the former
is worse than one reporting nothing. Below 0.35 the honest verdict is
`NEEDS_WORK / INSUFFICIENT_EVIDENCE`, which means *go and get evidence*, not
*this is mediocre*. This is Scenario B (§5) made mechanical.

Between 0.35 and 0.60 a REJECT is permitted but **must be labelled
`provisional`**, in both the title and the summary line, enforced by guardrail.
That is the difference between *"we looked and found nothing"* and *"there is
nothing"*.

**`branch_penalty = 0.60` is the biggest single lever, and it should be.** One
dead tool call — a Firecrawl 429, an exhausted GitHub budget — drops 0.75 to 0.45
and 0.55 to 0.33, crossing into LOW and forcing NEEDS_WORK. Correct: a verdict
produced with one of three evidence branches missing is not a verdict. **The
tutorial's design has no way to notice this at all.**

### 10.4 Guardrails

Same split as `guardrails.py` — free arithmetic first, LLM judgement second —
with their own thresholds in `validator_guardrails.py`. The Brief Crew's
500–700-word contract is untouched (§11.2).

| Task | Guardrails |
|---|---|
| `scoping_task` | `check_scope` *(callable only)* |
| each branch task | `check_findings(branch)` *(callable only)* |
| `synthesis_task` | `check_rubric` *(callable only)* |
| `reporting_task` | `check_report_mechanics`, then `CITATION_GUARDRAIL` *(string)* |

**Only one task carries an LLM guardrail.** Three parallel string guardrails
would be three extra LLM calls on the hot path, each constructing a throwaway
`Agent(role="Guardrail Agent")` — and every check on the branches is a set
operation. This follows `agents/05-evaluator.md`'s cost argument to its
conclusion rather than half-way.

The load-bearing checks:

- **URL closure** — every URL anywhere in a findings object must appear in the
  set of URLs the tools actually returned this run. Exact set difference. This is
  the mechanical defence against fabricated citations (G2).
- **Status honesty** — `tool_status != "ok"` ⇒ `sources` empty **and** `gaps`
  non-empty. Catches the silent-failure cascade: tool failed, agent invented.
- **Counts match lists** — every integer the confidence formula consumes is
  recomputed from the lists. An LLM-asserted count is not a count.
- **Anchor-text match** — `anchor_matched` must match the rubric text for that
  dimension at that score (≥0.85 token overlap). **This is what makes the rubric
  binding.** Without it the Synthesist writes a number and a paraphrase, and the
  rubric degrades into exactly the prompt-instruction verdict the tutorial has.
- **Calibration floor** — at LOW confidence the body may not contain *"clearly"*,
  *"no demand"*, *"proven"*, *"confirms"*.
- **Provisional label** — enforced in title *and* summary line.

⚠️ **The first guardrail in a list sees `TaskOutput.pydantic is None`** (§14 R-9).
Parse `output.raw`. Return `(True, output.raw)` **unchanged** — the return value
*replaces* `raw`, and `_export_output` then runs on whatever you returned, so a
"helpfully" normalised string silently becomes the task's output. A second
guardrail in the chain *does* see a populated model.

⚠️ **`output_file` + `output_pydantic` writes JSON into your `.md`.**
`task.py:781-791` prefers `json_dict`, then `pydantic.model_dump_json()`, then
`raw`. `writing_task` gets markdown in `brief.md` only because it has no
`output_pydantic`. Add one to `reporting_task` with an `output_file` and
`output/validation.md` becomes a JSON blob with a `.md` extension — no error, no
warning. **Resolution:** `reporting_task` carries `output_pydantic` and **no**
`output_file`; the Flow's `persist` step writes `ValidationReport.markdown_body`,
mirroring what `main.py::persist` already does for `brief.md`.

⚠️ **Guardrail exhaustion raises and the run dies with no report.** For a product
that returns a verdict about someone's idea, that is the right failure — a report
that failed its citation gate is worse than no report. Choose it knowingly, and
render it in the UI as a terminal state (§14 R-6).

### 10.5 Cache integration — mostly off, and the reason matters

The warm cache was tuned for a news brief on a *topic*. Three things differ.

**1. The cache key is wrong.** A brief's key is *"cashless payments in
Singapore"* — a phrase many runs repeat. A validator's key is *"an AI tool that
reads physio clinic intake forms"* — a near-unique string never typed twice.
**Hit rate on the raw idea is approximately zero**, and retrieve-first then costs
an embed, a Pinecone query and a rerank unit every run for nothing. The reusable
unit is `ScopedIdea.category` + `market_query`: ten founders validating ten
scheduling products research the same scheduling market.

**2. Two of three upstreams are free.** The cache exists to avoid paying
Firecrawl. HN Algolia and GitHub search cost nothing. For those branches the
cache spends an embed + query + rerank unit to avoid a free API call — a net loss
before you count staleness risk.

| Branch | Retrieve? | `MIN_RERANK_SCORE` | `MAX_INDEX_AGE_DAYS` | Index back? |
|---|---|---|---|---|
| Market | **yes** | **0.35** ↑ | **30** ↓ | yes, per source URL |
| Sentiment | **no** — permanently | — | — | yes |
| Feasibility | **no** by default; yes under concurrency | 0.40 | 90 ↑ | yes |

*0.35 not 0.30:* the measured 0.30 came from one topic-shaped query. A *category*
query has more near-neighbours that are adjacent-but-wrong markets — "clinic
scheduling" retrieves "restaurant scheduling" at a respectable score — and an
adjacent market cited as this one's is a subtle, plausible, uncorrectable error.
`agents/06-retrieval-layer.md` says outright: *"Tune 0.30 against real data
before trusting it."*

*30 days not 60:* pricing is load-bearing for M and for two C anchors, and a
wrong price does not degrade gracefully — it moves M by a whole anchor.

*Feasibility, under concurrency only:* the reason is not cost, it is the 10/min
shared-IP budget — the cache is a rate-limit shock absorber. **Say that in the
code comment**, because someone will later "optimise" it back off.

⚠️ **Never gate the whole run on the cache.** The Brief Flow's `@router` skips
the Researcher entirely on a hit. **Do not do that here.** A whole-run hit means
returning a verdict on an idea nobody researched this run — against a scope the
human just confirmed and the cached material was never gathered for. For a news
brief, serving cached facts is defensible; the facts do not depend on who asked.
For a verdict on a founder's idea it fails silently while looking perfectly
well-sourced. **The cache is a per-branch source of evidence, not a route** — all
three branches always run, and cached passages arrive labelled and dated
*alongside* live results.

⚠️ **Never index a `ScopedIdea`, `Verdict` or `ValidationReport` back into the
corpus.** A future run would retrieve a *conclusion as evidence*, cite it with a
real score, and partly score one idea on a previous scoring of a different idea.
Circular, invisible, and worse every run. **Enforce with a type check at the
`index_documents` boundary, not a comment.**

⚠️ **`retrieve()` needs a `filter=` argument it does not currently have.** It
calls `index.query(vector=…, top_k=…, include_metadata=True)` with no filter.
Per-branch retrieval is impossible until it passes
`filter={"branch": {"$eq": branch}, "category": {"$eq": category}}`. This is a
required, concrete change to a shared module — the one exception to §11.2's
read-only rule, and it is additive.

**Index per source URL, not per findings blob.** This also fixes the known defect
where `index_content` indexes notes as one document with `url: ""` on every
chunk. New metadata: `branch`, `category`, `idea_hash` (for revocation and audit,
never for retrieval).

⚠️ **Structural consequence: retrieval cannot be a `@start()` step.** The cache
key (`category`) does not exist until the Scoper has run *and* the human has
confirmed it. Cache lookup therefore moves **inside each branch method** — which
is the opposite of the Brief Flow's shape, where `retrieve_cached` is the first
thing that happens. Do not copy that structure across.

⚠️ **Namespace per user.** `agents/06-retrieval-layer.md` recommends per-group for
the classroom; here the stakes are different. A shared index would hold one
founder's scoped market research and serve it as a warm cache to a competitor
validating the same idea. `index_documents` already accepts `namespace` and
nothing currently passes it. Pass it.

**When the cache actually pays.** On a novel idea it is a net loss — one embed,
one query, one rerank unit, returning nothing. It pays when runs cluster by
category, and **the design creates exactly that case**: the scope gate encourages
re-scoping, and a re-scope within the same category is a guaranteed warm hit on
the market branch. Worth having for that reason — but state the reason rather
than assuming the brief's cache economics carry over.

## 11. Repository integration

### 11.1 Target layout

New paths marked `+`. Everything unmarked is untouched — **G6 requires the Brief
Crew behave identically after this work.**

```
D:\MultiAgentSystem\
├── agents/                              authoritative specs — unchanged
│                                        (reconciliation debt: Appendix B)
├── src/brief_crew/
│   ├── config.py                        SHARED · + validator thresholds only
│   ├── embeddings.py                    SHARED · untouched
│   ├── indexing.py                      SHARED · untouched
│   ├── guardrails.py                    untouched (Brief Crew's own)
│   ├── main.py                          untouched — run_crew() / kickoff() / plot()
│   ├── crews/
│   │   ├── brief_crew/                  untouched
│   │   └── validator_crew/            + agents.yaml · tasks.yaml · validator_crew.py
│   ├── tools/
│   │   ├── pinecone_retrieval.py        SHARED · untouched
│   │   ├── market_research.py         + Firecrawl search + scrape
│   │   ├── hn_sentiment.py            + HN Algolia
│   │   └── github_feasibility.py      + GitHub search
│   ├── schemas/                       + Pydantic models (§10)
│   ├── validator_guardrails.py        + mechanics callable + attribution string
│   ├── validator_flow.py              + the Flow: fan-out, gates, persistence
│   ├── events/                        + UIEventListener + frame types (§9)
│   └── service/                       + FastAPI app, WS manager, run registry (§9)
├── frontend/                          + Vue 3 + Vite + Vue Flow (§8)
│   ├── public/sprites/                + downscaled to 64×80 (§8.4)
│   └── src/{pages,components,composables,assets/styles}/
├── output/                              brief.md · last_run.json  (+ validation.md)
├── PRD.md                             + this document
└── pyproject.toml                       + [service] installed; + [ui] scripts
```

### 11.2 What is shared, and the rule for touching it

| Module | Rule |
|---|---|
| `config.py` | **Append only.** Validator thresholds get their own commented block. Never change `CHEAP_MODEL`, `ESCALATION_MODEL`, `PRICES`, `DOC_PREFIX`/`QUERY_PREFIX`, or the staleness constants — `agents/00-shared-config.md` is authoritative and the Brief Crew reads them |
| `embeddings.py`, `indexing.py` | **Read-only.** Reuse as-is. ⚠️ `DOC_PREFIX`/`QUERY_PREFIX` must stay paired — if they drift, nothing raises and retrieval quality quietly degrades |
| `tools/pinecone_retrieval.py` | **Read-only.** Reuse `retrieve()` and `PineconeRetrieveRerankTool` unchanged |
| `guardrails.py` | **Do not edit.** Its `MIN_WORDS=500 / MAX_WORDS=700 / MIN_DISTINCT_URLS=3` are the *brief's* contract. Validator guardrails live in a separate module with their own thresholds |
| `main.py` | **Do not edit** in M0–M4. The service imports `BriefFlow`; it does not modify it |
| `__init__.py` | **Do not regress the `.env` fix.** `load_dotenv(_ENV_PATH, override=True)` resolved from `__file__` is load-bearing: a machine-level `PINECONE_API_KEY` silently shadows the repo's, and resolving from CWD breaks under uvicorn |

### 11.3 New dependencies

No new *paid* credential is required. The three validator data sources are
Firecrawl (already provisioned), HN Algolia (open), and GitHub search
(unauthenticated, rate-limited — see §14 R-7).

```toml
# pyproject.toml — [project.optional-dependencies]
service = [            # already declared, NOT yet installed
  "fastapi>=0.115.0", "uvicorn>=0.32.0",
  "sqlalchemy>=2.0.0", "psycopg[binary]>=3.2.0",
]
```

```bash
uv pip install --python .venv -e ".[service]"      # fastapi is currently absent
cd frontend && npm install                         # node v24.19.0 / npm 11.17.0 present
```

⚠️ `crewai` pins `pydantic<2.13`; the machine's conda base has 2.13.2. The
isolated `.venv` is mandatory, not advisory (`agents/00-shared-config.md` §2).

⚠️ Set `PYTHONIOENCODING=utf-8` in the service environment (Appendix B).

### 11.4 Entry points

```toml
[project.scripts]
run_crew  = "brief_crew.main:run_crew"           # unchanged — Track A
kickoff   = "brief_crew.main:kickoff"            # unchanged — Track B
plot      = "brief_crew.main:plot"               # unchanged
validate  = "brief_crew.validator_flow:validate" # NEW — headless validator
serve     = "brief_crew.service.app:serve"       # NEW — FastAPI + WS
```

`validate` exists so **M3 can be tested without a frontend** and the crew stays
runnable headless afterwards — the same discipline that keeps Track A runnable
independently of Track B.

### 11.5 Sequencing constraint

M0 (`events/`) is built against the **existing** `BriefFlow`, not the validator.
This decouples the two risky halves: the event mapping is proven on a crew that
already works, so frontend work is never blocked on crew work and vice versa. It
also means a regression in G6 surfaces immediately, at the point the shared
listener is introduced, rather than at integration.

---

## 12. Milestones

**M−1 · Land three changes first.** Each is small, each unblocks everything after
it, and the first is a live defect.

1. **`main.py:105` → `-> Literal["cache_hit", "cache_miss"]`** (§9.0). One
   annotation. Without it every graph this system draws is wrong. G6-safe.
2. **`UIEventListener` with `async def` handlers + a per-run stream sink**
   (§9.1). M0's whole deliverable, testable with no frontend.
3. **`PostgresFlowPersistence`** (§9.6). Without it G5 holds only inside one
   process lifetime, and Scenario C is a promise the system cannot keep.

| # | Milestone | Exit criteria |
|---|---|---|
| M0 | Spine | `events/` package + `UIEventListener` emitting frames for an existing `kickoff()` run, printed to stdout. No UI. **`seq` is gapless and every `NODE_START` pairs with a `NODE_END`.** Proves the bus mapping before any frontend exists. |
| M1 | Service | FastAPI + WebSocket; a browser `wscat` sees live frames from a real Brief Crew run. Graph descriptor endpoint returns valid topology. |
| M2 | Studio (read-only) | Vue 3 + Vue Flow three-pane shell. Brief Crew runs render live: nodes change state, chat rail streams, edges animate. Matches the reference screenshot's information design. |
| M3 | Validator crew | Six agents, three tools, rubric, Pydantic schemas, guardrails. Runs headless via CLI. **Fan-out measured** — wall-clock vs sequential, peak RSS (§2.4). |
| M4 | Gates | Both human checkpoints working end-to-end, including timeout, cancel, and recovery by a reconnecting client. |
| M5 | Hardening | Cost/token per node in the UI, log download, Postgres persistence per `agents/07-deployment.md`, cancellation via scoped `PRE_STEP` hooks. *(The concurrent-run smoke test that was this milestone's headline check already passes — see R-1.)* |

**M0 before M2 is deliberate.** The event mapping is the riskiest unknown and the
one thing everything else depends on; proving it against the *existing* crew
means a frontend is never blocked on crew work, and crew work is never blocked on
a frontend.

---

## 13. Success metrics

| Metric | Target | How measured |
|---|---|---|
| Fabricated citations in the acceptance set | **0** | every URL in a report appears in a captured tool result |
| Verdict reproducibility | same band on 2 runs over identical evidence | replay the same findings into `Synthesist` |
| Fan-out speedup | ≥ 1.8× vs sequential, or the deviation is withdrawn | wall-clock, 5 runs each |
| Peak RSS during fan-out | < 400 MB (512 MB Render `starter`, ~210 MB baseline) | measured, M3 |
| Frame loss under a run | 0 dropped UI frames | frame sequence numbers, gap check |
| Gate round-trip | < 500 ms from reply to resume | client timestamp to node-state change |
| Brief Crew regression | byte-identical behaviour | `run_crew()` / `kickoff()` before-and-after |

---

## 14. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R-0 | **The Brief Flow's graph is disconnected today** — `check_cache` returns `-> str`, so its router events are not statically inferable. `check_cache` has zero outgoing edges; `scrape_web` is orphaned; `paths: 1`. The failure is a `logging.warning` nobody reads | The graph endpoint returns a wrong topology and **the entire UI draws a lie** | One-line annotation: `-> Literal["cache_hit", "cache_miss"]` (§9.0). Verified: 6 edges, `paths: 2`, no warnings. Zero runtime effect, so G6-safe. **Land this first.** Then assert at import that every router has non-empty `router_events`, so the class of bug fails startup rather than rendering wrongly |
| R-1 | ~~The event bus is a process-wide singleton~~ — **structurally retired** | — | Capture on a **ContextVar-scoped stream sink** (§9.1): it is impossible for run A's sink to see run B's events. Measured across 2 concurrent runs × 120 events: 0 leakage. ContextVar scoping is kept as belt-and-braces on the listener. **The M5 two-concurrent-run smoke test already passes** |
| R-2 | **Handler exceptions are caught and logged, never propagated.** A failing emit degrades observability silently | Blank UI, no error | A **bounded ring** (2000) that counts drops rather than an unbounded queue — this makes loss *measurable* instead of *invisible*. `push()` wraps everything and increments `emit_errors`; `/status` and the UI show a live frame counter; `seq` gaps make loss provable. A `gate_open` with no `gate_closed` after `timeout+60s` raises an alert |
| R-3 | Fan-out does not deliver the speedup, or blows the memory ceiling | §2.4's deviation collapses | Measure at M3. Fallback is sequential execution of the same agents — same graph, worse latency |
| R-4 | `Flow.kickoff()` is synchronous and blocking, and there is **no** `stop`/`cancel`/`abort` anywhere. `Agent.max_execution_time` calls `future.cancel()`, a **no-op on a running thread** — the agent keeps burning tokens in an orphaned thread | "Cancel" cannot stop a run | **Resolvable** (§9.5): a scoped `PRE_STEP` hook raising `HookAborted` gives real, per-run cancellation — verified. But granularity is the next *step boundary*, so worst case is one agent turn. The API returns explicit granularity and **the UI says "stopping after the current step", never "stopped"** — the opposite of DevAll's optimistic flip (§8.7) |
| R-17 | **Sync bus handlers reorder.** Measured: 11 adjacent inversions in 200 paired events on the 10-worker pool — which is the seam `agents/08-observability.md` §7 currently specifies | The UI renders `NODE_END` before `NODE_START`; `seq` is assigned at capture, so this corrupts the sequence itself | Capture on the inline sink (0 inversions) or on `async def` handlers (0 inversions). **Never register a plain sync handler.** Correction owed to §7 — Appendix B |
| R-5 | **`Task(human_input=True)` blocks on `input()`** — confirmed at `core/providers/human_input.py:364`, with no `isatty()` check, no timeout, and no events emitted. Closed stdin raises `EOFError` *outside* the executor's try/except, which the agent then treats as a task failure and **retries up to `max_retry_limit`** — burning ~3 full LLM executions before the error escapes. An idle pipe hangs forever | Unusable from a web server, expensively so | **Never use it.** Gates use the native `@human_feedback` provider (§9) |
| R-9 | **Guardrails suppress `output_pydantic` conversion.** `task.py:872-877` — when a guardrail is present, `.pydantic` and `.json_dict` are `None` and only `.raw` is populated. Worse, it is *inconsistent*: retry attempt ≥ 2 always converts, so a guardrail sees `None` on attempt 1 and a model on attempt 2 | A guardrail reading `output.pydantic.field` throws on first run and works on retry — the worst possible failure signature | Validate against `output.raw`. Return `(True, <str>)` — the only return shape that both passes and lets conversion happen afterwards. `(True, TaskOutput)` silently drops `output_pydantic` forever; `(True, <anything else>)` is a silent no-op |
| R-10 | `@human_feedback` with `emit=[...]` **requires an `llm`**, and routing free-text feedback to a label costs an LLM call per gate (`_collapse_to_outcome`, `flow/runtime/__init__.py:3707-3721`) | Two gates × every run = 2 extra paid calls, in a system whose router is deliberately LLM-free | Resume with `""` plus a matching `default_outcome` when the user clicks a button rather than typing — the empty path skips the call entirely. Reserve the LLM collapse for genuinely free-text replies |
| R-11 | `LLMStreamChunkEvent` handlers are **special-cased to run inline in the emitting thread** (`event_bus.py:628-630`), unlike every other event which goes to a `ThreadPoolExecutor(max_workers=10)` | A slow WebSocket write inside a chunk handler slows the model call itself | The chunk handler must be non-blocking — enqueue and return. Never do I/O in it |
| R-12 | Stream sinks and event-correlation state live in **contextvars** (`events/stream_context.py:12-14`). A bare `threading.Thread` starts with an empty context and streams silently to nothing, with `parent_event_id`/`emission_sequence` reset | Silent, total loss of streaming and trace nesting | Never hand-roll threads. Flow-hosted methods already use `asyncio.to_thread(ctx.run, ...)` and get correct correlation free |
| R-6 | Guardrail exhaustion **raises** — `Task._invoke_guardrail_function` throws a plain `Exception` and the run dies | A failed sourcing gate kills the run with no output | Correct behaviour for a sourcing gate, but the UI must render it as a terminal *state*, not a disconnect. Surface the last failure message |
| R-7 | **GitHub search is 10 req/min *per IP*, shared by all three parallel branches and every concurrent run on the host** — verified live 2026-08-29 | Feasibility research fails silently under exactly the fan-out this feature introduces | `max_rpm` cannot enforce it (per-agent controllers cannot see siblings, and throttle the executor loop not the HTTP call). A module-level token bucket **inside the tool** — 8/min unauth, 24/min with `GITHUB_TOKEN`. Degrade to `status: "rate_limited"`, which drops `branches_ok` and forces NEEDS_WORK via §10.3 rather than producing a confident verdict on two branches |
| R-13 | **`@human_feedback` defaults to `llm="gpt-5.4-mini"`.** This project has no `OPENAI_API_KEY` — `memory=False` exists to keep the OpenAI embedder unreachable. The default is truthy, so the `emit`-requires-`llm` validator *passes* and the run dies at the first gate | Both gates fail, on a key the project deliberately does not have | Pass `llm=CHEAP_MODEL` explicitly at both gates. Add a startup assertion that no CrewAI object resolves to an OpenAI model |
| R-14 | **`output_file` + `output_pydantic` writes JSON into a `.md` file** (`task.py:781-791`) — no error, no warning | `output/validation.md` is a JSON blob that passes a glance at the file listing | `reporting_task` carries `output_pydantic` and **no** `output_file`. The Flow's `persist` step writes `markdown_body`, mirroring `main.py::persist` |
| R-15 | **Indexing a `Verdict` or `ValidationReport` back into the Pinecone corpus** | A later run retrieves a *conclusion as evidence* and scores one idea partly on a previous scoring of a different one. Circular, invisible, compounding | Type check at the `index_documents` boundary — not a comment. Only tool output is indexable |
| R-16 | **A missing `{variable}` raises in 1.15.18**, contradicting `tasks.yaml`'s own comment | A template typo kills the run rather than degrading; worse, the repo currently documents the opposite | Correct the comment (Appendix B). Pass `community_queries_block`/`tech_queries_block` as pre-joined strings — lists interpolate as Python `repr` |
| R-8 | The `agents/` specs and this PRD drift | Two sources of truth | This PRD is folded back into `agents/` at M5. Until then, `agents/` wins on anything it already covers |

---

## 15. Open questions

Everything the four coordinating agents could settle has been folded into the
sections above. What remains genuinely open:

| # | Question | Why it is still open | Decide by |
|---|---|---|---|
| Q1 | Does the fan-out actually deliver ≥1.8× and stay under 400 MB peak RSS? | The *mechanism* is proven (§2.5); the *budget* is not. Three concurrent Firecrawl scrapes at 10–30 s each is the real test | M3 |
| Q2 | Does `resume_async` re-hydrate persisted state **over** a pre-resume write to `state.gate_reply_raw`? | The deterministic gate router (§9.4) writes state immediately before resuming. If hydration wins, the write must move into a `POST_STEP` hook instead | M4, first gate test |
| Q3 | Firecrawl's actual rate limit and per-credit cost on this plan | Not verified in this session, and search-with-scrape bills per result *fetched* **and** per result *scraped* | M3 |
| Q4 | Is the `reporter` cheap-tier arm as good? And how often does the operator hit `scope_revise` per arm? | Both are real experiments the gates make measurable, unlike the four unresolvable comparisons in `agents/05-evaluator.md` | after M4 |
| Q5 | Exact export path for `HumanFeedbackPending` / `PendingFeedbackContext` | Read from source, not executed; `crewai.flow` re-exports them but the deep path may be the stable one | M0 |
| Q6 | Should `write_brief` render as one node or two (Analyst, Writer)? | The registry resolves by `task_name` first, so splitting it is free and needs no Flow change. Purely a presentation call | M2 |

---

## 16. Deferred

| Item | Revisit when |
|---|---|
| ~~Token-by-token streaming~~ | **Promoted into scope.** `LLMStreamChunkEvent` exists with a `chunk: str` field, carrying populated `agent_role`/`task_name`. There is also a native `Flow.astream()` yielding `StreamFrame`s on `llm`/`flow`/`tools` channels. DevAll has no streaming at all — this is where we exceed the reference (§9) |
| Postgres-backed run history browser | more than one operator, or runs worth comparing over time |
| Comparing the validator against a `Process.hierarchical` manager variant | there is a decision a router genuinely cannot make |
| Multi-idea batch validation (`kickoff_for_each`) | single-idea flow is stable |

---

## Appendix A — source map

| Claim in this PRD | Source |
|---|---|
| Tutorial architecture (§2.1) | `firecrawl.dev/blog/langgraph-startup-validator-tutorial`, fetched 2026-08-29 |
| Repo layout, tracks, guardrails (§2.2) | `README.md`, `src/brief_crew/**` |
| Pattern mechanisms and costs (§6.2, §6.3) | `agents/patterns.md`, verified against the `crewai 1.15.18` wheel |
| Event bus, listener, singleton trap (§2.3, R-1, R-2) | `agents/08-observability.md` §7 |
| Memory ceiling, Render plan (§2.4) | `agents/00-shared-config.md` §2, `agents/07-deployment.md` |
| Pattern ③ exclusion being overturned (§2.4) | `agents/workflow.md` §8 |
| DevAll transport contract (§2.3) | `ChatDev-main/server/services/websocket_logger.py`, `entity/enums.py`, `server/services/prompt_channel.py` |
| UI layout, tokens, node/edge/sprite rendering (§8) | `ChatDev-main/frontend/src/pages/LaunchView.vue`, `components/*.vue`, `utils/vueflow.css`, `utils/colorUtils.js`, `utils/spriteFetcher.js` |
| Flow parallelism, HITL, guardrail/pydantic interaction, event catalogue (§2.5, §9, R-5, R-9…R-12) | the `crewai 1.15.18` wheel at `.venv/Lib/site-packages/crewai/`, verified by execution |

---

## Appendix B — corrections owed to `agents/`

Found while verifying this PRD against the installed wheel. **These are defects
in the authoritative specs and must be folded back**, per §14 R-8. Listed here so
the debt is visible rather than lost in a diff.

⚠️ **Status, re-verified 2026-08-29.** Most of this appendix has since been
folded back into the documents it names. Each entry is now marked
**✓ folded back** or **open**, so the list stops implying work that is already
done. What was checked, and where:

| Entry | State |
|---|---|
| `agents/patterns.md` §4 Option C (`kickoff_for_each` is sequential) | ✓ folded back — §4 now heads it *"⚠️ NOT parallel"*. §10's decision table still recommended it under ③ Parallel and has been corrected in this pass |
| `agents/patterns.md` §4 Option B (`and_()` is only the join) | ✓ folded back — §4 now names `asyncio.gather` over sibling listeners as the source of parallelism |
| `agents/patterns.md` §7 gotcha 3 (`task.py` line drift) | ✓ folded back in §7; the §11 source map still pointed at `task.py:1327` for the *raise* and has been corrected to `task.py:1382-1391`. Note 1327 is not wrong everywhere — it is where `Task._invoke_guardrail_function` is **defined**, which is what `agents/03-writer.md` and `agents/05-evaluator.md` cite, and both remain correct |
| `agents/patterns.md` §9 *"What CrewAI does not give you"* | ✓ folded back — a *"what it does give you"* table now covers Flow HITL, `FlowPersistence`, `Flow.ask()` and `astream()` |
| `agents/patterns.md` §4 unbounded daemon thread per async task | ✓ folded back |
| `agents/patterns.md` §7 guardrails suppress `output_pydantic` | ✓ folded back |
| `agents/workflow.md` §8 memory-ceiling conflation | ✓ folded back, with the runs-versus-branches distinction spelled out and the fan-out marked permitted-but-unmeasured |
| `crews/brief_crew/config/tasks.yaml` *"a missing input is not an error"* | ✓ corrected — the comment is gone |
| `tools/pinecone_retrieval.py` no `filter=` | ✓ implemented — `retrieve()` takes `metadata_filter` and `namespace` |
| `indexing.py` / `main.py::index_content` writing `url: ""` | ✓ implemented — `index_content` now indexes `BriefState.scraped_sources`, one document per scraped URL. `agents/06-retrieval-layer.md` still said this was open and has been corrected in this pass |
| `agents/08-observability.md` §5 and §7 | ✓ folded back — sync-handler reordering, the stream sink, `LLMStreamChunkEvent`, `astream()`, `source_fingerprint` and the `usage_metrics` caveat are all present |
| `src/brief_crew/main.py` `check_cache -> str` | ✓ fixed — the annotation is `Literal["cache_hit", "cache_miss"]` and two tests pin it |
| Environment: `PYTHONIOENCODING=utf-8` | **open** — it is set nowhere in `render.yaml`, the `Dockerfile` or CI. `src/brief_crew/__init__.py` reconfigures `sys.stdout`/`sys.stderr` instead, which is stronger in-process but does not reach a subprocess |
| §10.2's own Demand ladder | ✓ corrected in place — see the entry immediately below |

The entries below are the original text, kept because the *reason* each was a
defect is still worth reading.

### This document — §10.2, the Demand ladder

⚠️ **The one entry here that is a defect in *this* PRD rather than in
`agents/`.** §10.2's own Demand ladder — the only ladder the document ever wrote,
on the dimension weighted 0.30 — was unscoreable in three separate ways: D=4
required anchor 3 to hold *and* required the exact thing anchor 3 excludes, so no
evidence state reached it; D=0 scored on a classification `ADJACENT` that
`ThreadClassification` does not carry; and a dead band between D=2's "older than
36 months" and D=3's "within 24 months" left three threads whose newest is 28
months old matching no anchor at all. **Corrected in place in §10.2**, with the
original table kept verbatim above the correction — this is a design record, so
the correction is visible as a correction rather than as a silent rewrite.

Two further points recorded there: §10.2 is **normative but superseded wherever
it conflicts with `config.RUBRIC_ANCHORS`**, which is what the guardrail actually
matches; and the M/C/F/X ladders were **never written in this document or
anywhere in `agents/`** — they are a derivation from §10.2's stated rules, audited
and tested but not yet reviewed by a human.

### `agents/patterns.md`

| § | Says | Source says |
|---|---|---|
| §4 Option C | lists `kickoff_for_each` under Pattern ③ Parallel | it is a **sequential `for` loop** (`crew.py:1108-1115`). Only `kickoff_for_each_async` / `akickoff_for_each` gather (`crews/utils.py:500-505`) |
| §4 Option B | `and_()` is "the Flow's fan-in join" | correct but incomplete, and the omission invites the common wrong assumption that Flow methods are sequential. Parallelism is `asyncio.gather` over sibling listeners (`flow/runtime/__init__.py:3241-3249`) plus `asyncio.to_thread` for sync methods (`:2966-2972`) |
| §7 gotcha 3 | guardrail exhaustion raises at `task.py:1327` | behaviour correct, line has drifted to `task.py:1382-1391` |
| §9 *"What CrewAI does not give you"* | — | **incomplete.** CrewAI *does* provide Flow HITL pause/resume (`flow/async_feedback/`, `flow/persistence/`), `Flow.ask()`, and native streaming (`Flow.astream()`). None are covered anywhere in `agents/` |
| §4 | — | **not recorded:** `Task(async_execution=True)` spawns an *unbounded raw daemon thread per task* (`task.py:616-623`), and parallel async tasks cannot see each other's outputs (`crew.py:1597-1600`) |
| §7 | — | **not recorded, highest impact:** guardrails suppress `output_pydantic` conversion (`task.py:872-877`). See §14 R-9 |

### `agents/workflow.md`

§8's second argument against Pattern ③ — the ~210 MB memory ceiling — conflates
concurrent **runs** with concurrent **branches within a run**. The ceiling is
real; its application to in-run fan-out is not. See §2.4.

### `src/brief_crew/crews/brief_crew/config/tasks.yaml`

A comment states *"A missing input is not an error — CrewAI leaves the literal
`{research_notes}` in the prompt."* **This is wrong for 1.15.18.**
`interpolate_only` (`utilities/string_utils.py:138`) raises `KeyError`, which
`task.py:1090` converts to `ValueError("Missing required template variable …")`.
It fails loudly. The comment currently documents the opposite of the behaviour
and should be corrected in place.

### `src/brief_crew/tools/pinecone_retrieval.py`

`retrieve()` calls `index.query(...)` with **no `filter=`**. Per-branch,
per-category retrieval (§10.5) is impossible until it accepts and forwards one.
Additive change; no existing caller is affected.

### `src/brief_crew/indexing.py`

`index_content` indexes research notes as one document and writes `url: ""` /
`publisher: ""` on every chunk, after which `_format_hits` renders
`url: unknown` above passages that contain real URLs. Already noted in
`agents/06-retrieval-layer.md`; the validator's per-source-URL indexing (§10.5)
fixes it for the new path and the Brief Crew path should follow.

### `agents/08-observability.md`

| § | Says | Should say |
|---|---|---|
| §7 listener | registers a **sync** handler — `@bus.on(LLMCallCompletedEvent) def _(source, event)` | ⚠️ **Sync handlers reorder** — measured, 11 adjacent inversions in 200 paired events on the 10-worker pool. Use `async def`, or the ContextVar-scoped stream sink (§9.1). This is the one place the spec's recommended code is actively wrong for a UI |
| §7 singleton warning | ContextVar scoping is the mitigation | Correct, but a **stream sink** removes the problem structurally rather than mitigating it — sinks live in a ContextVar, so cross-run leakage is impossible |
| §7 event table | four events | understates the surface: add `LLMStreamChunkEvent` (`chunk: str`, dispatched **inline in the emitting thread**), the `Flow.astream()` / `StreamFrame` API, the paused/human-feedback events, and the per-family correlation matrix — several families leave `agent_id`/`task_id` `None`, which §7 does not warn about |
| §7 base fields | — | the base fields are `source_fingerprint` / `source_type` / `fingerprint_metadata`. **There is no field named `fingerprint`.** |
| §5 flow totals | *"`Flow.usage_metrics` … use it for run totals"* | correct, and the sibling-over-count caveat it already notes becomes **live** under the validator's fan-out. Per-node cost must come from `LLMCallCompletedEvent` keyed on `(run_id, node_id, model)` |

### `src/brief_crew/main.py`

⚠️ **`check_cache` is annotated `-> str`, which disconnects the Flow graph.**
`@router` infers its events from a `Literal`/`Enum` return annotation; with
`str`, `build_flow_structure` emits two warnings, gives `check_cache` zero
outgoing edges, orphans `scrape_web`, and reports `paths: 1`. See §9.0 and R-0.
This is a live defect today, independent of anything in this PRD — the Flow runs
correctly, but nothing that reads its structure sees the branch.

### Environment

Set `PYTHONIOENCODING=utf-8` in the service environment. CrewAI's Rich console
formatter crashes on Windows `cp1252` when printing emoji, and because handler
exceptions are swallowed (R-2) it floods logs rather than failing loudly.
