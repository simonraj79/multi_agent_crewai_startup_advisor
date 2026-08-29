# Agent Design Patterns — the six, as CrewAI actually implements them

Companion to `workflow.md`. The split:

| File | Question it answers |
|---|---|
| `workflow.md` | *Which* patterns does **this build** use, and why not the others? |
| **`patterns.md`** *(this file)* | *How* do you build **each** of the six in CrewAI, generically? |

Every mechanism below was verified against the **`crewai` 1.15.18** wheel —
file and line references are to that source, not to `docs.crewai.com`, which is
stale in several of the places that matter (§9).

---

## 1. The one-slide summary

| # | Pattern (slide 13) | CrewAI mechanism | LLM calls to *decide* | Native? |
|---|---|---|---|---|
| ① | **Sequential Pipeline** | `Process.sequential` + `context=[...]` | 0 | ✅ one word |
| ② | **Routing / Handoff** | `ConditionalTask(condition=…)` · or Flow `@router` | **0** | ⚠️ no `handoff()` |
| ③ | **Parallel Fan-out** | `Task(async_execution=True)` + a sync join · or Flow `and_()` | 0 | ✅ but constrained |
| ④ | **Supervisor / Workers** | `Process.hierarchical` + `manager_agent=` | **1+ per step** | ✅ one word |
| ⑤ | **Hierarchical (nested)** | **nothing native** — compose Flows over Crews | varies | ❌ |
| ⑥ | **Evaluator–Optimizer** | `Task(guardrail=…, guardrail_max_retries=N)` | 0 if callable, 1 per check if string | ✅ |

### The slide-worthy correction

Slide 45 says CrewAI is **four nouns** — Agent · Task · Crew · Process — and that
*"two of the six patterns are one word each."* That is exactly right, and it is
also the whole story of what `Process` covers. From source:

```python
class Process(str, Enum):
    sequential   = "sequential"
    hierarchical = "hierarchical"
    # TODO: consensual = 'consensual'
```

**Two members. Two patterns.** The other four are not process types at all —
they live in a **fifth noun the deck's slide 45 does not mention:**

> **Flow** — `@start` · `@router` · `@listen` · `and_()` / `or_()`

Patterns ②, ③ and ⑤ are most naturally Flow constructs; ⑥ is a Task field. If
you are reworking slide 45, the honest version is:

| The nouns | Covers |
|---|---|
| Agent · Task · Crew · **Process** | Patterns ① and ④ |
| **Flow** | Patterns ②, ③, ⑤ — and the loop half of ⑥ |
| **Task fields** (`guardrail`, `async_execution`, `condition`) | Patterns ⑥, ③, ② *inside* a Crew |

---

## 2. Pattern ① — Sequential Pipeline

> *Fixed-order stages; output feeds the next.* — slide 13
> Deck example: `Researcher → Writer → Editor` (slide 14)

```
Researcher ──▶ Analyst ──▶ Writer ──▶ Output
```

### Mechanism

```python
crew = Crew(
    agents=[researcher, analyst, writer],
    tasks=[research_task, analysis_task, writing_task],
    process=Process.sequential,
    verbose=True,
)
```

Tasks run **in list order**. `agents=[...]` order is irrelevant — `tasks=[...]`
is the pipeline.

### The one thing people get wrong: `context`

`Crew._get_context` (`crew.py:1866-1874`) has three branches, and they are not
additive:

| You write | The task receives |
|---|---|
| *nothing* (unset) | **every** prior task's output |
| `context=[task_a]` | **only** `task_a` — this **replaces** the default |
| `context=[]` | **nothing at all** |

So an explicit `context=[...]` is redundant *only while the list is complete*.
Trim it and you silently narrow what the agent sees, with **no error**. Slide 46
writes `context=[research, angle]` on the final task precisely because the Writer
needs the Researcher's URLs, which the Analyst compresses away.

### Cost

One LLM call per task, minimum — more if the agent uses tools. Slide 65: three
agents ≈ **5–10 calls per request**.

### Use when

Stages are genuinely fixed and non-overlapping. If you always do A then B then C,
this is the answer and anything fancier is overhead.

---

## 3. Pattern ② — Routing / Handoff

> *Classify once, hand control to a specialist.* — slide 13
> *OpenAI Agents SDK made this a first-class primitive: `handoff()`.* — slide 15

```
Input ──▶ Router ──┬──▶ Specialist A     (exactly one fires)
                   ├──▶ Specialist B
                   └──▶ Specialist C
```

> ⚠️ **CrewAI has no `handoff()`.** That is the OpenAI Agents SDK's primitive,
> and slide 15 says so explicitly. In CrewAI you build routing yourself, three
> ways, and they differ enormously in cost.

### Option A — `ConditionalTask` (deterministic skip, 0 LLM calls)

```python
from crewai.tasks.conditional_task import ConditionalTask

def needs_deep_dive(output) -> bool:
    return "INSUFFICIENT" in output.raw

deep_dive = ConditionalTask(
    description="...",
    expected_output="...",
    agent=researcher,
    condition=needs_deep_dive,      # Callable[[TaskOutput], bool]
)
```

`condition` is evaluated against the **previous task's output**
(`conditional_task.py`). Returns `False` → the task is **skipped** and yields an
empty `TaskOutput`; the crew continues.

**Constraints, from source:**

- Cannot be the **first** task — it needs a previous output to judge.
- Cannot be the **only** task (`validate_must_have_non_conditional_task`).
- **Cannot be async** — `validate_async_tasks_not_async` raises
  `invalid_async_conditional_task`.

**Honest limit:** this is a *skip*, not a *route*. It answers "should this task
run?" — not "which of three specialists should handle this?". For one-of-N
selection you need Option B.

### Option B — Flow `@router` (real branching, 0 LLM calls)

```python
from crewai.flow import Flow, listen, or_, router, start

class SupportFlow(Flow[State]):
    @start()
    def classify(self):
        self.state.kind = triage(self.state.query)   # code, or an agent

    @router(classify, emit=["billing", "technical", "refund"])
    def route(self) -> str:
        return self.state.kind                        # the emitted label

    @listen("billing")
    def handle_billing(self):  ...

    @listen("technical")
    def handle_technical(self): ...

    @listen(or_("billing", "technical"))              # rejoin either branch
    def respond(self): ...
```

A router **returns a string label**; `@listen("label")` picks it up. `emit=[...]`
declares the label set for static analysis and visualisation — otherwise a
`Literal`/`Enum` return annotation is used (`flow/dsl/_router.py:97-140`).

**This is the real Pattern 2**, and it costs **zero LLM calls if the decision is
code**. Only put a model in the router when the classification genuinely needs
judgement — a threshold check does not.

### Option C — let a manager decide (1+ LLM call per decision)

`Process.hierarchical`. That is Pattern ④, priced accordingly — see §5.

### Choosing between them

| | `ConditionalTask` | Flow `@router` | Manager |
|---|---|---|---|
| Expresses | skip / don't skip | one-of-N branch | dynamic, open-ended |
| LLM calls | **0** | **0** (code) or 1 (agent) | **1+ per step** |
| Lives in | a `Crew` | a `Flow` | a `Crew` |
| Effort | one function | a Flow class | one agent |

**Default to the cheapest one that expresses your decision.** A binary threshold
does not need a model, and a model asked to make it will still be wrong
sometimes.

---

## 4. Pattern ③ — Parallel Fan-out / Fan-in

> *Run independent subtasks at the same time.* — slide 13
> *Sectioning* (different subtasks) and *Voting* (same task N times) — slide 16
> *Trade tokens for speed. Parallelise what's independent.*

```
          ┌──▶ Agent A ──┐
Input ────┼──▶ Agent B ──┼──▶ Merge ──▶ Output
          └──▶ Agent C ──┘
```

### Option A — inside a Crew: `async_execution=True`

```python
zh = Task(description="Translate to Chinese",  agent=t1, async_execution=True)
ms = Task(description="Translate to Malay",    agent=t2, async_execution=True)
ta = Task(description="Translate to Tamil",    agent=t3, async_execution=True)

publish = Task(description="Assemble the announcement",
               agent=editor,
               context=[zh, ms, ta])        # sync — this is the fan-in

crew = Crew(agents=[t1, t2, t3, editor],
            tasks=[zh, ms, ta, publish],
            process=Process.sequential)
```

**How it actually runs** (`crew.py:1579-1625`): consecutive `async_execution`
tasks accumulate into a `concurrent.futures.Future` list. The next **synchronous**
task triggers `_process_async_tasks`, which joins them all before proceeding.
**The synchronous task is the fan-in.** There is no separate "merge" primitive.

**Four validators will stop you — know them before you design:**

| Rule | Source | Why it exists |
|---|---|---|
| The crew must **end with at most one** async task | `validate_end_with_at_most_one_async_task` | Otherwise nothing joins the futures and results are dropped |
| An async task **cannot have another async task in its `context`** unless a sync task separates them | `validate_async_task_cannot_include_sequential_async_tasks_in_context` | It would be waiting on a result that has not been joined |
| `ConditionalTask` cannot be async | `validate_async_tasks_not_async` | The condition needs a settled previous output |
| `context` cannot reference **future** tasks | `validate_context_no_future_tasks` | No forward references |

Practically: **fan out, then always fan in with a synchronous task.** That shape
satisfies all four.

**Two properties of this option that the validators do not warn you about:**

1. **Each async task gets a raw daemon thread, and nothing bounds them.**
   `Task.execute_async` starts `threading.Thread(daemon=True, ...)` per call
   (`task.py:616-623`) — there is no pool and no ceiling. Ten async tasks are ten
   OS threads. On a memory-capped host, fan out deliberately.
2. **Parallel async tasks cannot see each other's outputs.** An async task's
   context is built from `[last_sync_output]` only (`crew.py:1597-1600`), so
   sibling branches are invisible to one another until the fan-in task joins
   them. Design branches to be genuinely independent, not merely concurrent.

### Option B — inside a Flow: `and_()`

```python
@listen(fetch)
def summarise_a(self): ...

@listen(fetch)
def summarise_b(self): ...

@listen(and_("summarise_a", "summarise_b"))   # fires only after BOTH
def merge(self): ...
```

`and_(*triggers)` fires **after all** triggers fire; `or_(*triggers)` fires when
**any** does (`flow/dsl/_conditions.py:22-30`). `and_()` is the Flow's fan-in
join, and it is more explicit than the Crew's "next sync task" convention.

**But `and_()` is only the *join*. Say where the parallelism comes from, or
readers will assume Flow methods run one after another — they do not.** When one
event triggers several listeners, the runtime builds a task per listener and
awaits them together with `asyncio.gather`
(`flow/runtime/__init__.py:3241-3249`). A listener declared `def` rather than
`async def` is not thereby serialised: the runtime copies the context and runs it
on a worker thread via `asyncio.to_thread` (`:2966-2972`). So **sibling
`@listen(same_trigger)` methods are the fan-out**, whether or not they are
coroutines, and `and_()` is what makes the next method wait for all of them.

This is the mechanism the validator's three research branches rely on — see
`workflow.md` §8.

### Option C — across inputs: `kickoff_for_each` (⚠️ NOT parallel)

```python
results = crew.kickoff_for_each(inputs=[{"topic": t} for t in topics])
# the concurrent variant — this is the one that actually gathers:
results = await crew.akickoff_for_each(inputs=[...])
```

⚠️ **`kickoff_for_each` is a sequential `for` loop.** It copies the crew and
calls `kickoff()` once per input, in order (`crew.py:1108-1115`). Nothing about
it is concurrent, and it belongs under Pattern ③ only as the contrast case. The
async forms — `akickoff_for_each` / `kickoff_for_each_async` — are the ones that
build tasks and `asyncio.gather` them (`crews/utils.py:500-505`).

Either way: same crew, many inputs. This is the right tool for "run my pipeline
over 20 topics", not for parallelising *within* one run.

### Cost

**Parallelism does not reduce tokens — only wall-clock.** Slide 16's framing is
exact: *trade tokens for speed*. Voting mode multiplies cost by N for one output.

### Use when

Subtasks are genuinely independent. If stage B needs stage A's output, this
pattern does not apply no matter how much you want it to.

---

## 5. Pattern ④ — Supervisor / Orchestrator-Workers

> *A manager plans and delegates to workers.* — slide 13
> *It decides dynamically: which worker, what task, when to stop.* — slide 17
> *"The workhorse of production multi-agent."*

```
        Supervisor
             │
   ┌─────────┼─────────┐
Worker 1  Worker 2  Worker 3
```

### Mechanism

```python
crew = Crew(
    agents=[researcher, analyst, writer],   # manager NOT in this list
    tasks=[research_task, analysis_task, writing_task],
    process=Process.hierarchical,
    manager_agent=manager,                  # or: manager_llm="openrouter/..."
    verbose=True,
)
```

### Four hard rules, all enforced in source

1. **`manager_agent` or `manager_llm` is required.** Neither set →
   `PydanticCustomError("missing_manager_llm_or_manager_agent", "Attribute
   'manager_llm' or 'manager_agent' is required when using hierarchical
   process.")` (`crew.py:722-732`). Slide 51: *"Forget the manager and it breaks."*
2. **The manager must NOT be in `agents=[...]`.** Both → `PydanticCustomError(
   "manager_agent_in_agents", "Manager agent should not be included in agents
   list.")` (`crew.py:734-741`).
3. **The manager must NOT have tools.** `_create_manager_agent()` warns, clears
   `manager.tools`, then raises `Exception("Manager agent should not have
   tools")` (`crew.py:1522-1532`). It delegates; it does not work.
4. **`allow_delegation` is forced `True` on the manager** regardless of what you
   set (`crew.py:1520`). Keep it `False` on every worker, or they delegate to
   each other and loop until `max_iter` burns.

### What delegation actually *is*

Not magic — two injected tools. `_prepare_tools` (`crew.py:1645-1656`) adds them
to any agent with `allow_delegation=True`:

| Tool | Purpose |
|---|---|
| `"Delegate work to coworker"` | hand a whole subtask to another agent |
| `"Ask question to coworker"` | query another agent without transferring the task |

So a supervisor is **an ordinary agent holding two extra tools.** That is worth a
slide on its own — it demystifies the pattern completely.

### Cost

The manager reasons **before and after every step**. Slide 23: *"patterns 4 & 5
ran slowest and priciest."* You are buying one genuine capability — **rejection**,
which `Process.sequential` cannot express at all — and paying manager reasoning
on every hand-off to get it.

### Use when

There is a real decision to make about *who works next*. If the order is always
the same, a supervisor is overhead with no job.

---

## 6. Pattern ⑤ — Hierarchical (Nested Teams)

> *Supervisors of supervisors; nested teams.* — slide 13
> *Don't go hierarchical until you've proven you need it.* — slide 18

```
              CEO agent
          ┌───────┴───────┐
      CTO agent       CMO agent
      ┌───┴───┐       ┌───┴───┐
    Eng     Eng     Mktg    Mktg
```

> ⚠️ **NAMING TRAP — the single most common mistake with these slides.**
> CrewAI spells **Pattern ④** `Process.hierarchical`. The deck's **Pattern ⑤** is
> *also* called *Hierarchical* and means something different: nested teams,
> supervisors of supervisors.
>
> **`Process.hierarchical` gives you Pattern 4, not Pattern 5.**
> A student who builds a manager crew and reports "we used Pattern 5" is wrong,
> and the word collision is why. Worth an explicit callout on your slide.

### Mechanism: there isn't one

**CrewAI 1.15.18 has no nested-crew primitive.** No `sub_crew`, no `nested_crew`,
no crew-of-crews type. `Process` has two members and neither nests.

Two ways to build it anyway:

**A · A Flow orchestrating several Crews** — the cleaner option:

```python
class Company(Flow[State]):
    @start()
    def plan(self):
        self.state.plan = exec_crew.kickoff(inputs=...)     # top tier

    @listen(plan)
    def engineering(self):
        return eng_crew.kickoff(inputs=...)   # itself hierarchical

    @listen(plan)
    def marketing(self):
        return mkt_crew.kickoff(inputs=...)

    @listen(and_("engineering", "marketing"))
    def integrate(self):
        return integrator_crew.kickoff(inputs=...)
```

Each `Crew` may internally be `Process.hierarchical` — so you get Pattern ④
inside Pattern ⑤, which is what the deck's slide-22 demo (*CEO → 2 Leads → 4
workers → Integrator*, 9 agents) actually is.

**B · A Crew wrapped as a `BaseTool`** — a parent agent calls a whole sub-crew as
a tool. Compact, but the sub-crew's trace is buried inside a tool call, which
makes Pattern ⑤'s main risk — *debugging* — considerably worse.

### Cost

Slide 18: *"coordination overhead grows with depth."* Slide 22's Pattern-5 demo
was the longest run of the six. Slide 54 is the counterweight: **almost every
real system is 2–5 agents.** Most production systems use flat supervisor-worker.

### Use when

Genuinely large agent organisations with real reporting lines. In a workshop,
almost never — and the deck says so twice.

---

## 7. Pattern ⑥ — Evaluator–Optimizer

> *A generator and a critic loop to quality.* — slide 13
> *Separate the creator from the critic.* — slide 19
> Deck demo: *Generator ⇄ Evaluator (**max 3**)*, *"fails round 1, passes by 2–3."*

```
Generator ──▶ Evaluator ──▶ pass ──▶ Output
    ▲              │
    └──── fail ────┘
```

**The judging is easy. The loop is the part that needs a decision** —
`Process.sequential` has no mechanism to send a task backwards.

### Option A — Task guardrail (the real loop, and the cheap one)

```python
def within_length(output) -> tuple[bool, str]:
    n = len(output.raw.split())
    if 500 <= n <= 700:
        return (True, output.raw)
    return (False, f"Brief is {n} words; cut to 500-700.")

writing_task = Task(
    description="...", expected_output="...", agent=writer,
    guardrail=within_length,          # callable = FREE
    guardrail_max_retries=2,          # default is 3
)
```

On failure the agent receives the message back and **re-runs the same task**.
That is the evaluator–optimizer loop, complete, with no second agent.

**Cost — the intuition is wrong, so state it on the slide:**

| Guardrail type | Cost per evaluation |
|---|---|
| **Callable** | **zero** — plain Python, no model |
| **String** | **one full LLM call, pass or fail** |

A string guardrail constructs a throwaway `Agent(role="Guardrail Agent")` and
calls `.kickoff()` (`tasks/llm_guardrail.py:70-93`) — *every time it runs*. And a
rejection re-runs the **entire task**, not just the check. At the default 3
retries, worst case for one output is **4 task executions + 4 judgement calls**.

> **Put arithmetic in a callable.** Word counts and "does a Sources section
> exist" are string operations. Only attribution and faithfulness need a model.

**Five gotchas from source:**

1. **`guardrails` (plural) overrides `guardrail` (singular)** — setting the list
   nulls the single field; they do **not** combine (`task.py:466-469`).
2. **A string guardrail requires `task.agent` to be set**, else
   `ValueError("Agent is required to use non-programmatic guardrails")`
   (`task.py:421-424`). This bites under `Process.hierarchical`, where you are
   told `agent:` is optional.
3. **Exhaustion raises.** The guardrail retry loop (`task.py:1382-1391`) raises a
   plain `Exception` — there is **no** best-effort passthrough. In sequential,
   the run dies.
4. ⚠️ **Attaching *any* guardrail suppresses `output_pydantic` conversion —
   this is the one that silently changes your data.** In `Task._export_output`'s
   caller, the structured-conversion branch is guarded by
   `elif not self._guardrails and not self._guardrail:` (`task.py:872-877`); the
   `else` sets `pydantic_output, json_output = None, None`. So a guarded task
   returns a `TaskOutput` whose `.pydantic` is `None` no matter what
   `output_pydantic=` says, and the guardrail itself receives **raw text**, not a
   model. Two consequences, both load-bearing for this project:
   - A guardrail must parse `TaskOutput.raw` itself, and must return the
     successful raw string **unchanged** so nothing downstream is corrupted.
   - Any Pydantic validation you were relying on has to be re-applied after the
     task, by the caller. See `src/brief_crew/validator_guardrails.py` and
     `ValidatorFlow._extract_model`.
5. **Agent-level `guardrail` does not work inside a Crew.** `Agent` has a
   `guardrail` field, but it fires only on standalone `agent.kickoff()`, never
   when that agent executes a task in a `Crew`. **Task-level is the only option.**

### Option B — a visible evaluator agent

A fourth agent with a review task. Understand clearly: **in `Process.sequential`
this gates nothing.** It writes a verdict that lands *after* the output and
changes it not at all. It is a demonstration of the reviewer role, not a gate.

It becomes a real gate under `Process.hierarchical` (the manager can send work
back) or in a Flow with a `@router` back-edge:

```python
@router(evaluate, emit=["pass", "fail"])
def gate(self) -> str:
    return "pass" if self.state.verdict.ok else "fail"

@listen("fail")
def regenerate(self):
    self.state.attempts += 1
    if self.state.attempts < 3:      # bound it, or it loops forever
        return self.write()
```

**Always bound the loop.** Slide 22's own demo caps at **3**.

### Use when

Quality is checkable against a stated standard. If you cannot write the check
down, an evaluator agent will just produce agreeable noise.

---

## 8. Composition — the real shape

Slide 20: *"Most real systems are LEGO compositions of the six — not a single
clean pattern."*

```
Query ──▶ Router ② ──▶ Supervisor ④ ──▶ Evaluator ⑥ ──▶ Answer
```

In CrewAI a composition is almost always **a Flow at the top and Crews inside
it** — because Flows can branch, loop and join, and mix plain Python freely with
agent calls, while a Crew can only run a task list.

**Rule of thumb:** the moment you need a decision that is *not* "run the next
task", you need a Flow. Everything else is a `Crew`.

This project is a composition of **① + ② + ⑥** — see `workflow.md` §7.

---

## 9. What CrewAI does *not* give you

Worth a slide, because three of these look like they should exist:

| Missing | Reality | Do this instead |
|---|---|---|
| `handoff()` | OpenAI Agents SDK primitive (slide 15). No CrewAI equivalent. | Flow `@router` + `@listen(label)` |
| Nested crews | No `sub_crew` / crew-of-crews type in 1.15.18 | Flow over multiple Crews (§6) |
| A `consensual` process | `# TODO` comment in `process.py`. Not implemented. | — |
| Agent-level guardrails in a Crew | Fires only on standalone `agent.kickoff()` | Task-level `guardrail` |
| Native Pinecone | `SupportedProvider = Literal["chromadb", "qdrant"]` | A custom `BaseTool` |
| Cost in `token_usage` | Token counts only, no `cost` field | Compute from a price table |

### What CrewAI *does* give you that this document used to imply it did not

An earlier revision of this section left readers building these by hand. All
three are native in 1.15.18 and should be used rather than reinvented:

| Capability | Where it lives | Notes |
|---|---|---|
| **Flow human-in-the-loop pause/resume** | `flow/async_feedback/`, `flow/human_feedback.py` | `@human_feedback` pauses by raising `HumanFeedbackPending`; `Flow.from_pending(flow_id)` (`flow/runtime/__init__.py:1223`) and `Flow.resume(feedback)` (`:1311`, `resume_async` at `:1364`) restart it. Do **not** hand-roll a gate. |
| **Durable Flow state persistence** | `flow/persistence/` (`base.py`, `sqlite.py`, `factory.py`, `decorators.py`) | A `FlowPersistence` interface with a shipped SQLite backend. Subclass it for Postgres rather than inventing a state store. |
| **`Flow.ask()` and native streaming** | `flow/runtime/__init__.py:3452` (`ask`), `:2029` (`astream`) | `astream()` yields scoped public `StreamFrame` objects (`crewai/types/streaming.py:31`) — a supported alternative to the event bus for streaming a run. |

### Docs that are stale (verified against the 1.15.18 wheel)

| Docs say | Source says |
|---|---|
| Default `max_iter` is **20** | **25** (`base_agent.py:304`) |
| `function_calling_llm` is fine | Carries a `deprecated=` marker (`agent/core.py:268`) |
| Firecrawl tools take flattened kwargs | They take a `config` dict |
| MCP connection failures "log a warning and continue" | Native `MCPServerStdio`/`MCPServerHTTP` objects **raise** |

---

## 10. Choosing a pattern — the decision table

Adapted from slide 32's shape, at the pattern level rather than the framework
level:

| If your problem is… | Pattern | CrewAI |
|---|---|---|
| Fixed stages, each feeding the next | ① Pipeline | `Process.sequential` |
| One of N specialists should handle this | ② Routing | Flow `@router` |
| Should this step run at all? | ② Routing | `ConditionalTask` |
| Independent subtasks, want them faster | ③ Parallel | `async_execution=True` + sync join |
| Same crew over many inputs | ③ Parallel | `akickoff_for_each` — **not** `kickoff_for_each`, which is a sequential `for` loop (§4 Option C) |
| Who works next depends on the input | ④ Supervisor | `Process.hierarchical` |
| Work must be rejectable and redone | ④ or ⑥ | manager, or a `guardrail` |
| Output must meet a checkable standard | ⑥ Evaluator | `Task(guardrail=…)` |
| Large org with real reporting lines | ⑤ Hierarchical | Flow over Crews |
| **You are not sure you need multi-agent** | — | **One agent.** Slides 32, 33, 55. |

> Slide 33, quoting Anthropic: *"Find the simplest solution possible, and only
> increase complexity when needed."* Slide 55: *"Most things you'll want to build
> as a crew are cheaper, faster, and more reliable as one agent."*
> The default is one agent. Every pattern here is a cost you should be able to
> justify.

---

## 11. Cost, per pattern

Slide 65's complexity tax, refined by which mechanism you pick:

| Pattern | Extra LLM calls over a plain pipeline | Extra wall-clock |
|---|---|---|
| ① Pipeline | baseline (1 per task) | baseline |
| ② Routing — `ConditionalTask` / code `@router` | **0** | ~0 |
| ② Routing — agent classifier | +1 per run | +1 turn |
| ③ Parallel | **0** (same tokens) | **negative** — that is the point |
| ③ Parallel — voting mode | **×N** | ~0 |
| ④ Supervisor | **+1 or more per step** | +manager turns |
| ⑤ Hierarchical | ④ compounded per tier | worst of the six |
| ⑥ Evaluator — callable guardrail | **0** unless it fails | +1 task re-run per failure |
| ⑥ Evaluator — string guardrail | **+1 per check**, pass or fail | +1 turn per check |

Slide 55: *"Your crew made ~10 LLM calls for one brief. A single good agent might
have made one. That gap is the tax."* Slides 55 and 65: production teams report
**3–10×** single-agent cost.

**The cheapest patterns are ② and ③ done in code.** The expensive ones are ④ and
⑤ — which is exactly what slide 23 observed in the live demo.

---

## 12. Slide-ready one-liners

Paste-able summaries, one per pattern:

| # | Pattern | One line |
|---|---|---|
| ① | Sequential Pipeline | `Process.sequential` — the list order *is* the pipeline. |
| ② | Routing / Handoff | No `handoff()` in CrewAI. `ConditionalTask` to skip, Flow `@router` to branch — both free. |
| ③ | Parallel Fan-out | `async_execution=True`, then **always** fan in with a sync task. Buys wall-clock, not tokens. |
| ④ | Supervisor / Workers | `Process.hierarchical` + `manager_agent=`. A supervisor is just an agent holding two delegation tools. |
| ⑤ | Hierarchical | Not native. A Flow over several Crews. And it is **not** `Process.hierarchical` — that is Pattern ④. |
| ⑥ | Evaluator–Optimizer | `Task(guardrail=…)`. Callable is free; a string costs an LLM call every single check. |

---

## 13. Source map

| Claim | Verified at |
|---|---|
| `Process` has two members | `process.py` |
| `context` replaces rather than adds | `crew.py:1866-1874` |
| Async fan-in via futures | `crew.py:1579-1625` |
| Four async validators | `crew.py:780-870` |
| `ConditionalTask.condition` / `should_execute` | `tasks/conditional_task.py` |
| `@router` labels and `emit=` | `flow/dsl/_router.py:97-140` |
| `and_()` / `or_()` join semantics | `flow/dsl/_conditions.py:22-30` |
| Manager required / not in agents / no tools / forced delegation | `crew.py:722-741`, `1520`, `1522-1532` |
| Delegation is two injected tools | `crew.py:1645-1656`, `tools/agent_tools/` |
| String guardrail builds a throwaway Agent | `tasks/llm_guardrail.py:70-93` |
| `guardrails` overrides `guardrail` | `task.py:466-469` |
| String guardrail needs `task.agent` | `task.py:421-424` |
| Guardrail exhaustion raises | `task.py:1382-1391` (async path `:1503-1512`) |
| `guardrail_max_retries` default 3 | `task.py:279-281` |

All references are to the **`crewai` 1.15.18** wheel, read directly. Where these
disagree with `docs.crewai.com`, the source is what runs.
