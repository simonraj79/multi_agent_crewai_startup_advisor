# Agent Workflow Mapping

**What this file is:** the map from an abstract vocabulary of agent-coordination
patterns onto the five agent specifications in this directory, and onto the code
in `src/brief_crew/`.

Five of the six patterns named here are Anthropic's, from
[*Building Effective Agents*](https://www.anthropic.com/engineering/building-effective-agents):
prompt chaining, routing, parallelisation, orchestrator-workers and
evaluator-optimizer. The sixth is this repository's own — §3 says which and why.
Everything else below — the mapping onto this build, the role decomposition, the
per-agent contracts, the design decisions and the declared gaps — is this
repository's own work.

> **Read order.** `00-shared-config.md` tells you *what things are*. This file
> tells you *what happens, in what order, and who is allowed to do it*. The
> per-agent files `01`–`05` are the detail behind §5 and §6 below.
>
> For **how each of the six patterns is built in CrewAI** — the mechanisms, code
> and constraints, independent of this project — see **`patterns.md`**. This file
> is *which* patterns and *why*; that one is *how*.

---

## 1. Two layers of workflow

Workflow here means two different things at two different altitudes, and
conflating them is the main way people misread these specs.

| Layer | What it is | Where it lives in this repo |
|---|---|---|
| **A · Pattern vocabulary** | Six abstract topologies for coordinating agents. Framework-agnostic. | §3 of this file; `patterns.md` for the mechanisms |
| **B · The build** | One concrete crew: a topic in, a one-page brief out. | §4–§6, and `01`–`05` |

Layer A is a design vocabulary, not a tool list. Layer B is one instantiation of
it. §7 and §10 exist to keep the seam between them answerable: which patterns
this build actually uses, and which of them are worth keeping.

---

## 2. Why multi-agent at all

The starting position is Anthropic's: *"find the simplest solution possible, and
only increasing complexity when needed"*, and add complexity *"only when it
demonstrably improves outcomes"*
([*Building Effective Agents*](https://www.anthropic.com/engineering/building-effective-agents)).
Agentic systems trade latency and cost for task performance. A crew is that
trade. This section is the bill.

Five things could justify splitting this workflow across agents. Two of them do:

| # | Would justify a crew | Does it here? |
|---|---|---|
| 1 | **Context pressure** — deep expertise across many domains overwhelming one context window. | **Partly.** Scraped markdown is bulky, but one topic is one domain. |
| 2 | **Tool pressure** — enough tools that one agent's routing decisions start degrading. | **No.** Three tools, all on one agent (`01`). |
| 3 | **Cognitive scatter** — one prompt asked to research AND analyse AND write AND critique does all four indifferently. | **Yes.** This is the real justification. Four verbs, four owners. |
| 4 | **Speed** — independent subtasks running at the same time. | **No.** This pipeline is strictly serial by construction (§8). |
| 5 | **Specialisation** — different subtasks want different prompts, temperatures, even models. | **Yes.** Two model tiers, deliberately split (`00` §3). |

**Two of five.** That is not a comfortable score, and the honest reading is that
most of what you would build as a crew is cheaper, faster and more reliable as a
single agent. The discipline that follows from Anthropic's rule — reach for a
crew only once one agent has been tried and has *measurably* failed — has
**not** been applied to this crew. That is a known, declared gap, not an
oversight; see §10.

---

## 3. The six patterns — the vocabulary

Five of the six are Anthropic's, named and defined in
[*Building Effective Agents*](https://www.anthropic.com/engineering/building-effective-agents):
**prompt chaining**, **routing**, **parallelisation** (in its two modes,
*sectioning* and *voting*), **orchestrator-workers** and
**evaluator-optimizer**. The one-line descriptions below are this repository's
own; for the definitions, read the article.

The sixth — ⑤ **nested teams** — has no entry in that article and is this
repository's own addition. It earns a slot for exactly one reason: CrewAI spells
pattern ④ `Process.hierarchical`, and without a separate name for the *nested*
case that word collision cannot be discussed at all. `patterns.md` §6 is the
argument; the collision is the single most common mistake made with these specs.

The ①–⑥ numbering is this repository's own, and it is load-bearing:
`patterns.md`, `PRD.md`, `agents/README.md` and the agent specs all refer to
these by number.

| # | Pattern | In one line | Anthropic's name | Used here? |
|---|---|---|---|---|
| 1 | **Sequential Pipeline** | Fixed stages in a fixed order, each consuming the previous one's output. | prompt chaining | ✅ core |
| 2 | **Routing / Handoff** | Classify the input once, then hand control to one specialist. | routing | ✅ as a *deterministic* router |
| 3 | **Parallel Fan-out / Fan-in** | Run independent subtasks at once and merge — either different subtasks (*sectioning*) or the same task N times (*voting*). | parallelisation | ❌ — see §8 |
| 4 | **Supervisor / Orchestrator-Workers** | A manager decides dynamically which worker runs next and when to stop, then synthesises. | orchestrator-workers | ⚠️ specified as a comparison, **not built** (`04`) |
| 5 | **Hierarchical (nested teams)** | Supervisors of supervisors. Coordination cost grows with depth. | *(none — this repo's own)* | ❌ — see §8 |
| 6 | **Evaluator–Optimizer** | A generator and a critic loop until a stated quality bar is met. | evaluator-optimizer | ⚠️ specified as a task guardrail (`03`, `05`) — optional, attach it deliberately |

The six compose rather than compete; a real system is usually two or three of
them stacked. This project is a composition of ① + ② + ⑥ — see §5 and §7.

> ⚠️ **Why `Researcher → Analyst → Writer` and not `Researcher → Writer →
> Editor`.** The obvious three-stage chain puts the quality step *after* the
> draft. This build puts it *before*. That is a real design change rather than a
> renaming: a *post-hoc polisher* (Editor) is swapped for a *pre-hoc judgement
> step* (Analyst), which is what lets the Writer receive an argument rather than
> a pile of facts. See §6.

---

## 4. The five agents — the role decomposition

**This is the load-bearing mapping in this repository, and it is not obvious.**

The crew is decomposed by *verb*: five roles, each with an explicit list of what
it may do and — more importantly — what it may not. The five roles are, one for
one, the five agent specifications in this directory.

| Role | May | Must not | Spec file |
|---|---|---|---|
| **Orchestrator** | Delegate the work, then synthesise the final answer | Search, calculate, write, or critique | `04-manager.md` |
| **Researcher** | Find facts and numbers in the source material | Calculate, write, or critique | `01-researcher.md` |
| **Analyst** | Calculate and compare — margins, deltas, rankings | Search, write, or critique | `02-analyst.md` |
| **Writer** | Compose the summary from facts it is handed | Search, calculate, or critique | `03-writer.md` |
| **Critic** | Approve or reject the summary, with a written reason | Search, calculate, or write | `05-evaluator.md` |

Two consequences that explain design decisions elsewhere in this repo:

1. **The "must not" column is a specification, not flavour, and it is enforced in
   two places.** Each agent's prohibitions are written into the `Constraints:`
   block of its task `description` in
   `src/brief_crew/crews/brief_crew/config/tasks.yaml`; the Analyst's and
   Writer's inability to search is `tools=[]` in `brief_crew.py`. So
   `02-analyst.md`'s refusal to hold a retrieval tool is not fastidiousness; it
   is that constraint, enforced in code. Same for the Writer and the Evaluator.
2. **An Orchestrator is a bottleneck by design.** Every hand-off passes through
   it, so it is simultaneously the coordination cost and the single point of
   failure. That is the structural case `04-manager.md` argues from, before
   retiring the Manager.

Routing everything through an Orchestrator makes a **star** topology.
`Process.sequential` is a **chain**. This build therefore takes the role
decomposition and not the star. That is the right call for a fixed three-stage
pipeline, but it is a decision worth naming (§10).

### The agent contract

Every agent in §6 is specified against five fields:

**Role** · **Tools** · **Inputs** · **Outputs** · **Guardrail** (what it must not
do).

They are not decoration — each maps onto something real. **Role** is
`agents.yaml`'s `role`/`goal`/`backstory`; **Tools** is the `tools=[...]` list in
`brief_crew.py`; **Inputs** is `context:` plus the `kickoff` inputs; **Outputs**
is the task's `expected_output`; **Guardrail** is the `Constraints:` block in the
task `description`. ⚠️ That last one is a *prompt-level* prohibition, not
CrewAI's `guardrail:` field, which is a post-hoc output validator — `00` §8
untangles the four senses of the word.

---

## 5. The workflow this project builds

### 5a · Track A — the sequential crew

```
Researcher ──▶ Analyst ──▶ Writer ──▶ One-page brief
```

**Pattern ①, unmodified.** Two of the six patterns are a single CrewAI keyword —
`Process.sequential` for ①, `Process.hierarchical` for ④ — which is why the
pipeline is the sensible place to start.

The wiring, in its minimal form:

```python
research = Task(description="List 3 facts on {topic}", expected_output="3 points", agent=researcher)
angle    = Task(..., agent=analyst, context=[research])
brief    = Task(..., agent=writer,  context=[research, angle])

crew = Crew(agents=[researcher, analyst, writer],
            tasks=[research, angle, brief],
            process=Process.sequential, verbose=True)
crew.kickoff(inputs={"topic": "cashless payments in SG"})
```

Note `brief` takes **both** prior tasks as context — the Writer needs the
Analyst's argument *and* the Researcher's source URLs, which the Analyst
compresses away. `03-writer.md` preserves this.

The build procedure that produced it, in order: scaffold something that already
runs → define three agents → define three tasks with specific `expected_output` →
`kickoff(topic)`, read the verbose log, tweak, re-run.

### 5b · Track B — the hosted Flow

This repo extends Track A with a warm vector cache. The extension adds exactly
one branch, and that branch is **Pattern ② with the classifier removed**.

```
                     topic
                       │
                       ▼
          ┌────────────────────────┐
          │     retrieve_cached    │  @start
          │  Pinecone → Cohere     │  0 LLM calls
          └───────────┬────────────┘
                      ▼
          ┌────────────────────────┐
          │       check_cache      │  ≥3 hits · score ≥0.30 · ≤60d
          │  cache_hit | cache_miss│  0 LLM calls — no model
          └────┬──────────────┬────┘
        miss   │              │   hit
               ▼              │
       ┌──────────────┐       │
       │  Researcher  │       │   ① Firecrawl search + scrape
       └──────┬───────┘       │
              ▼               │
       ┌──────────────┐       │
       │ index_content│       │   chunk / embed / upsert
       └──────┬───────┘       │   plumbing — not a tool
              └───────┬───────┘
                      ▼
             ┌─────────────────┐
             │    Analyst      │   ② no tools — judgement only
             └────────┬────────┘
                      ▼
             ┌─────────────────┐
             │     Writer      │   ③ no tools — prose only
             └────────┬────────┘
                      │  ◀── guardrail: fail → re-run Writer (Pattern 6)
                      ▼
        output/brief.md + Postgres run record
```

**The router is the whole point.** A Manager could sequence this dynamically;
this system has exactly one dynamic decision (hit vs miss) and resolves it in
code for **zero LLM calls**. `04-manager.md` keeps the Manager as a measurable
comparison rather than a component — which turns *keep it or drop it* into two
traces and a call count instead of an opinion.

| Flow step | Decorator | Actor | LLM calls |
|---|---|---|---|
| `retrieve_cached` | `@start()` | calls the `retrieve_and_rerank` tool (Pinecone + Cohere) | 0 |
| `check_cache` | `@router(retrieve_cached)` | **code** — threshold check | **0** |
| `scrape_web` | `@listen("cache_miss")` | **Researcher** | many (tool loop) |
| `index_content` | `@listen(scrape_web)` | plumbing | 0 |
| `write_brief` | `@listen(or_("cache_hit", index_content))` | **Analyst** → **Writer** | 2 (+ guardrail retries) |
| `persist` | `@listen(write_brief)` | code | 0 |

---

## 6. Per-agent workflow contracts

The agent contract (§4) for each of the five, plus the hand-off contract.
**Inputs and Outputs are the workflow**; role and backstory are how you get them.

### ① Researcher — `01-researcher.md`

| Field | Value |
|---|---|
| **Role** | Senior Research Analyst specialising in `{topic}` |
| **Tools** | `retrieve_and_rerank` (**Track A only** — under Track B the Flow has already retrieved) · `FirecrawlSearchTool(limit=5)` · `FirecrawlScrapeWebsiteTool` |
| **Inputs** | `{topic}` (from `kickoff`), today's date (`inject_date=True`) |
| **Outputs** | Structured markdown notes, 400–700 words: *Verified findings* (8–12 facts, each with publisher + date + URL) · *Competing views* · *Unverified / gaps* · *Sources consulted* |
| **Guardrail** | Do NOT analyse, rank, or draw conclusions. Do NOT write prose. Do NOT include a fact not traced to a source actually opened. Never invent a citation. |

**The only agent that touches the outside world.** Its internal order is
specified, not left to the model: retrieve first → judge relevance *and*
freshness → search only on a miss → scrape 3–4, not all five → at most one
follow-up round.

### ② Analyst — `02-analyst.md`

| Field | Value |
|---|---|
| **Role** | Strategy Analyst turning raw research on `{topic}` into a defensible point of view |
| **Tools** | **none — deliberate** (§4: the Analyst may not search) |
| **Inputs** | `context: [research_task]` |
| **Outputs** | *Bottom line* (one sentence) · *What matters* (3–4 findings + "so what") · *Confidence: High/Medium/Low* + justification · *What would change this*. 300–500 words. |
| **Guardrail** | Use ONLY the research notes. Introducing an outside fact is a failure, not initiative. Do NOT write the brief. Do not promote an unverified item by restating it confidently. |

**Why the empty tool surface is load-bearing.** With no tools, every claim *must*
trace to the Researcher's notes — so anything new is unambiguously invented, and
it sits one hand-off from its source in the trace. This is the cleanest place in
the system to observe an **error cascade** (§9 #1).

### ③ Writer — `03-writer.md`

| Field | Value |
|---|---|
| **Role** | Business Brief Writer producing decision-ready one-pagers on `{topic}` |
| **Tools** | none |
| **Inputs** | `context: [research_task, analysis_task]` — the argument *and* the URLs |
| **Outputs** | `output/brief.md` — conclusion-stating title · summary · 3–4 sections · *What this means* · *Sources*. **500–700 words, hard ceiling.** |
| **Guardrail** | Introduce no new facts. Carry the confidence rating through in plain language. **Provenance:** never present cached material as freshly verified. No orphan numbers. If the analysis was thin, write a short honest brief — do not pad. |

The only agent whose output anyone outside the crew reads, and the only one that
writes a file.

### ④ Manager — `04-manager.md` · *superseded, kept as a comparison*

| Field | Value |
|---|---|
| **Role** | Editorial Manager accountable for the quality of the `{topic}` brief |
| **Tools** | none — it delegates, it does not do the work |
| **Inputs** | The topic and the workers' outputs |
| **Outputs** | Task assignments, rejections with concrete reasons, final sign-off |
| **Guardrail** | Never "improve this" — send work back with a specific reason. Must NOT appear in `agents=[...]`; it goes in `manager_agent=`. |

Retired because the router already makes the only decision available, for free —
but building it once produces the trace comparison §10 asks for.

### ⑤ Evaluator — `05-evaluator.md` · *sourcing gate*

| Field | Value |
|---|---|
| **Role** | Editorial Fact-Checker with sign-off authority over the `{topic}` brief |
| **Tools** | none — it checks internal consistency, it does not re-research |
| **Inputs** | `context: [research_task, analysis_task, writing_task]` |
| **Outputs** | `VERDICT: PASS` / `FAIL` + a six-row checklist table + required fixes. Under 250 words. |
| **Guardrail** | Judge only against the checklist — style, tone and persuasiveness are out of scope. Do NOT rewrite or suggest wording. A brief honest about thin evidence is a PASS. |

The obvious shape for this is a fourth agent that rejects any brief without
sources — Pattern ⑥, in a few lines. `05` implements the gate primarily as a
**task guardrail** on `writing_task` instead, because in `Process.sequential` a
fourth agent produces a verdict that nothing acts upon. The guardrail is the
version that actually closes the loop.

### Hand-off contract

| Boundary | What crosses | What must NOT cross |
|---|---|---|
| Researcher → Analyst | Facts + sources + explicit gaps | Conclusions, prose, rankings |
| Analyst → Writer | An argument, a confidence rating, what would change it | New facts; the finished brief |
| Writer → Evaluator | The brief + its Sources section | Meta-commentary about the process |
| Evaluator → Writer | A verdict and named failing checks | A rewrite |

Every row is a place an **error cascade** (§9 #1) can start. The right-hand
column is what to grep the trace for.

---

## 7. Pattern coverage — what this build uses

| Pattern | Status | Where | Evidence |
|---|---|---|---|
| ① Sequential Pipeline | **Core** | Researcher → Analyst → Writer | The verbose log's three stages |
| ② Routing / Handoff | **Used, LLM-free** | Flow `@router` on the staleness gate | `runs.route` in Postgres; router costs 0 calls |
| ③ Parallel Fan-out | **Not used** | — | See §8 |
| ④ Supervisor / Workers | **Comparison only** | `04-manager.md` | Two traces + a call count |
| ⑤ Nested teams | **Not used** | — | See §8 |
| ⑥ Evaluator–Optimizer | **Specified, not in the baseline** | `writing_task.guardrail` (`03` word count, `05` sourcing) | The Writer running twice, second time carrying the failure — *once you attach it* |

**Which of the six this build uses, and which are worth keeping:** the running
system is ① + ②; ⑥ is one line away and specified in `03` and `05`. Keep ①.
Attach ⑥ — a callable guardrail is free and it is the only thing that catches an
unsourced brief. ② is worth keeping *only* if runs repeat (§10).

---

## 8. Why patterns 3 and 5 are absent

A vocabulary of six with two unused is a gap unless the absences are argued. Both
are deliberate.

**③ Parallel Fan-out — no independent subtasks in this decomposition.**
Parallelisation requires the subtasks to be genuinely independent. The three
stages are not: the Analyst cannot start before the Researcher finishes, and the
Writer cannot start before the Analyst does. Every stage consumes its
predecessor's entire output.

Be precise about this, though — "impossible" would be overstating it. Three
parallel variants *are* structurally available and were rejected on cost, not on
shape:

| Variant | Mode | Why not |
|---|---|---|
| Scrape the 3–4 chosen URLs concurrently | sectioning | Real, but **tool-level**, not an agent topology. Worth doing; changes no boxes. |
| Query the cache **and** the live web at once, then merge | sectioning | The whole point of the router is to *avoid* paying for the web call on a hit. Parallelising here spends the money the cache exists to save. |
| Run `writing_task` 3× and pick the best | voting | Triples the crew's most output-heavy agent to improve a one-page brief. |

And there is a hard measured ceiling underneath all three: `00-shared-config.md`
§2 records **~210 MB resident before any work**, against 512 MB on Render
`starter` — **one concurrent crew run per instance**.

> ⚠️ **Correction — the ceiling is real, but this paragraph used to over-apply
> it.** An earlier revision continued: *"Agent-level fan-out on this deployment
> would not buy wall-clock anyway without moving to the 2 GB plan."* That
> conflates two different things:
>
> - **Concurrent *runs*** — each one a fresh `Flow` with its own crews and state.
>   The ~210 MB baseline genuinely does cap this at one per 512 MB instance, and
>   that is why `RUN_CONCURRENCY` defaults to `1`.
> - **Concurrent *branches inside one run*** — sibling `@listen` methods sharing
>   a single already-resident interpreter, package set and Flow state. These add
>   per-branch working set, not another baseline.
>
> The second case is not bounded by the first, so the memory number is not on its
> own an argument against in-run fan-out. Validator Studio does exactly that:
> three sibling research branches inside one run
> (`src/brief_crew/validator_flow.py`), with run-level concurrency still pinned
> at 1. See `patterns.md` §4 Option B for the mechanism.
>
> What this does **not** license is asserting the fan-out is cheap. The peak-RSS
> and speedup numbers for the three-branch layout have **not been measured**
> (feature F42 in `new features/feature-list.md`). Until they are, treat in-run
> fan-out as permitted-but-unmeasured rather than as proven.

For the three variants in the table above the rejection still stands, on cost and
on shape rather than on memory.

**⑤ Nested teams — nothing to nest.** Coordination overhead grows with depth:
every tier adds a manager reasoning before and after every step below it, so ⑤ is
④'s cost compounded. Pattern ④ is already retired here for having no decision to
make (§6④); ⑤ would add a tier above that. A three-stage pipeline with three
workers has nothing to nest, and reaching for depth before you have proven you
need it is the most expensive mistake available in this vocabulary.

---

## 9. Where this workflow breaks

Six failure modes, mapped onto this specific topology. They are referred to by
number from `01`, `02`, `05` and `06`.

| # | Failure mode | Where it lands here | Mitigation in these specs |
|---|---|---|---|
| 1 | **Error cascade** | A fabricated citation in stage 1 becomes a confident claim in stage 3. The Analyst's empty tool surface makes it visible one hand-off from its source. | Analyst confidence rating (`02`) · sourcing guardrail (`05`) |
| 2 | **Cost explosion** | Scraping all five search results; guardrail retries; `glm-5.3-flash` reasoning tokens billing at completion rate. | `limit: 5` + "read snippets first" (`01`) · `guardrail_max_retries: 2` (`05`) · `reasoning_effort: "minimal"` (`00` §3) |
| 3 | **Debugging complexity** | Which stage lost the source URL? | `verbose=True` · CrewAI AMP tracing · `run_sources` table (`07`) |
| 4 | **Security & trust** | **Weakest coverage.** Scraped web content enters an LLM context, then rides forward into the Analyst's and Writer's contexts. Prompt injection through retrieved content, and MCP tool poisoning, are both documented attack classes. | Now **specified but not implemented**: `01-researcher.md` §"Untrusted input" (injection via scraped pages) and `06-retrieval-layer.md` §"The cache is shared mutable state" (poisoning, which is durable and outlives the run). Both name concrete containment; neither is built. |
| 5 | **State management** | Flow state; the Pinecone index is shared mutable state across runs. A bad scrape poisons future cache hits. | Write-back rules (`06`) · `indexed_at` staleness gate |
| 6 | **Evaluation** | Is the brief good? Nothing scores it end to end. | Checklist gate (`05`) · `run_metrics` (`07`) — but no quality score |

The staleness gate deserves its own warning. It is the **single most dangerous
failure this architecture can produce**: a cache hit on month-old material yields
a brief that is perfectly well-sourced and wrong. All three conditions — ≥3 hits,
top rerank score ≥0.30, `indexed_at` ≤60 days — must hold, and the threshold sits
on the **rerank** score, not the cosine score, because cosine scores on this index
cluster within 0.06 and admit no defensible cutoff.

---

## 10. Design decisions and declared gaps

Listed so they can be defended rather than rediscovered. The left column is the
obvious or default choice; the middle is what this build does instead.

| # | The obvious choice | This build | Why |
|---|---|---|---|
| 1 | `Researcher → Writer → Editor` | `Researcher → Analyst → Writer` | An Analyst judges *before* writing; an Editor polishes *after*. Judgement before drafting is what lets the Writer receive an argument instead of a pile of facts. |
| 2 | An evaluator as a fourth agent | Primarily a **task guardrail**; the agent is optional | In `Process.sequential` a fourth agent emits a verdict that gates nothing. The guardrail closes the loop; the agent only reports. `05` documents both. |
| 3 | CrewAI's default `guardrail_max_retries: 3` | `guardrail_max_retries: 2` | Each retry is a full task re-run *plus* a judgement call. If two focused attempts fail, the defect is upstream in stage 1 and no rewrite conjures sources. |
| 4 | A Manager for dynamic sequencing | Retired; a code `@router` decides | The only dynamic decision is binary and thresholded. A Manager would charge one LLM call per run to reach the same answer. Kept as a measured comparison (`04`). |
| 5 | A **star** through an Orchestrator | A **chain** via `context=[...]` | Star topology needs a hub; the hub is the Manager, which is retired. Sequential chaining passes prior outputs implicitly. |
| 6 | An MCP tool on the Researcher | Native Firecrawl tools; MCP documented as the next step | Native tools deliver the substance now. `01` specifies the MCP swap as a clean A/B — capability held constant, only transport changes. |
| 7 | Use the whole vocabulary | Three used, two refused with reasons, one retired | §7 and §8. Anthropic's rule: find the simplest solution possible. |
| 8 | Go multi-agent only once a single agent has been tried and has measurably failed | **Not done.** No single-agent baseline exists. | Honest gap. The cheapest experiment available and the strongest evidence this project could produce — see below. |

### The two experiments worth running

1. **The single-agent baseline (row 8).** One well-prompted agent with the same
   three tools, same topic, same brief format. Count the calls in both traces.
   The measured Track A run made **9** LLM calls for one brief
   (`agents/README.md`); what one good agent would have spent on the same topic
   is unknown, and that unknown is the whole argument for the crew.
2. **Router versus Manager (row 4).** Same decision, two implementations, two
   call counts. `04-manager.md` exists to make this runnable.

### The unmitigated risk (§9 #4)

Scraped web content flows into three agents' contexts with no sanitisation. A
page containing instructions rather than facts is an untested attack path, and
the Researcher's own failure table already notes that a failed tool call followed
by confident output is the fabrication signature to watch for.

The harness that would contain it — token and call budgets, bounded retries,
output guardrails, per-agent scoped credentials, and validation gates between
agents — is exactly what this build does not have. That is fine for a project
someone is reading. It is not fine for anything running unattended.
