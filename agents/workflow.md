# Agent Workflow Mapping

**Extracted from** `shaun-chong-multi-agent-orchestration-20260829.pdf` (67 slides),
then mapped onto this repository's five agent specifications.

Every claim about the deck carries a slide number. Where this project deviates
from the deck, the deviation is declared in §10 rather than quietly absorbed.

> **Read order.** `00-shared-config.md` tells you *what things are*. This file
> tells you *what happens, in what order, and who is allowed to do it*. The
> per-agent files `01`–`05` are the detail behind §5 and §6 below.
>
> For **how each of the six patterns is built in CrewAI** — the mechanisms, code
> and constraints, independent of this project — see **`patterns.md`**. This file
> is *which* patterns and *why*; that one is *how*.

---

## 1. Two layers of workflow

The deck specifies workflow at two different altitudes, and conflating them is
the main way people misread it.

| Layer | What it is | Slides | Where it lives in this repo |
|---|---|---|---|
| **A · Pattern vocabulary** | Six abstract topologies for coordinating agents. Framework-agnostic. | 12–23 | §3 of this file |
| **B · The build** | One concrete crew the class actually constructs: a topic in, a one-page brief out. | 45–53, 62 | §4–§6, and `01`–`05` |

Layer A is the design vocabulary — slide 03: *"You'll leave with a design
vocabulary, not a tool list."* Layer B is one instantiation of it.

Slide 53 grades the seam between them: every group must say **"which of the six
you used, and whether you'd keep it."** §7 and §10 exist to make that answerable.

---

## 2. The five ceilings — why any of this exists

Slide 09 gives the entry condition for multi-agent. A workflow that clears none
of these is a single agent wearing a costume.

| # | Ceiling | Deck wording | Does this build clear it? |
|---|---|---|---|
| 1 | Context overload | Deep expertise in many domains overwhelms one prompt. | **Partly.** Scraped markdown is bulky, but one topic is one domain. |
| 2 | Tool overload | 20+ tools confuse routing decisions; error rates climb. | **No.** Three tools, all on one agent (`01`). |
| 3 | Cognitive scatter | Research AND analyse AND write AND critique → mediocre at each. | **Yes.** This is the real justification. Four verbs, four owners. |
| 4 | Speed | Sequential tool use is slow; parallel agents work at the same time. | **No.** The pipeline is strictly serial by construction (§8). |
| 5 | Specialisation | Different subtasks want different prompts, temperatures, even models. | **Yes.** Two model tiers, deliberately split (`00` §3). |

**Two of five.** Slide 55 is blunt about what that means: *"Most things you'll
want to build as a crew are cheaper, faster, and more reliable as one agent."*
Slide 56's test — *"single-agent tried and measurably failed"* — has **not** been
run for this crew. That is a known, declared gap, not an oversight; see §10.

---

## 3. The six patterns (slides 13–19)

Slide 13's map. These are not competing options — slide 13's takeaway: *"think
LEGO bricks, not a menu."*

| # | Pattern | Deck definition (slide 13) | Used here? |
|---|---|---|---|
| 1 | **Sequential Pipeline** | Fixed-order stages; output feeds the next. | ✅ core |
| 2 | **Routing / Handoff** | Classify once, hand control to a specialist. | ✅ as a *deterministic* router |
| 3 | **Parallel Fan-out** | Run independent subtasks at the same time. | ❌ — see §8 |
| 4 | **Supervisor / Workers** | A manager plans and delegates to workers. | ⚠️ specified as a comparison, **not built** (`04`) |
| 5 | **Hierarchical** | Supervisors of supervisors; nested teams. | ❌ — see §8 |
| 6 | **Evaluator–Optimizer** | A generator and a critic loop to quality. | ⚠️ specified as a task guardrail (`03`, `05`) — optional, attach it deliberately |

### Pattern 1 · Sequential Pipeline — slide 14

```
Researcher ──▶ Writer ──▶ Editor ──▶ Output
```

- Output of one agent feeds the next, in a fixed order.
- When to use: tasks with clear, non-overlapping stages.
- Callback: this is **prompt chaining** in Anthropic's terminology.
- Deck demo (slide 22): *Singapore's e-payment landscape.* Watch — *"Three stages
  fire in fixed order; output improves at each."*

> ⚠️ **The deck's Pattern-1 example is `Researcher → Writer → Editor`. The build
> is `Researcher → Analyst → Writer`.** Different triples, same shape. The deck
> never reconciles them and the difference has confused people: the build swaps
> the *post-hoc polisher* (Editor) for a *pre-hoc judgement step* (Analyst). That
> is a real design change, not a renaming — see §6.

### Pattern 2 · Routing / Handoff — slide 15

```
Input ──▶ Router ──┬──▶ Tech support     (exactly one fires)
                   ├──▶ Billing
                   └──▶ Refund
```

- A classifier agent examines the input and hands **full control** to a specialist.
- The receiving agent takes over the conversation entirely.
- OpenAI Agents SDK made this a first-class primitive: `handoff()`.
- Deck demo (slide 22): *Triage → HDB / CPF / IRAS.* Watch — *"Only ONE
  specialist activates per query."*

### Pattern 3 · Parallel Fan-out / Fan-in — slide 16

```
          ┌──▶ Agent A ──┐
Input ────┼──▶ Agent B ──┼──▶ Merge ──▶ Output
          └──▶ Agent C ──┘
```

- **Sectioning** — different subtasks in parallel. **Voting** — same task several
  times, pick the best or the majority.
- Deck demo (slide 22): *Announce → ZH / MS / TA → Aggregator.* Watch —
  *"Three translators at once; wall-clock = one, not three."*
- Takeaway: *"Trade tokens for speed. Parallelise what's independent."*

### Pattern 4 · Supervisor / Orchestrator-Workers — slide 17

```
        Supervisor
             │
   ┌─────────┼─────────┐
Worker 1  Worker 2  Worker 3
```

- A manager plans subtasks, delegates, then synthesises. It decides
  **dynamically**: which worker, what task, when to stop.
- *"This is what Claude Code does — a main agent spawns sub-agents."*
- Deck demo (slide 22): *Supervisor ⇄ Attractions / Food / Logistics.* Watch —
  *"Supervisor dynamically picks the next worker."*
- Takeaway: *"The workhorse of production multi-agent. One brain, many hands —
  and the most common pattern."*

### Pattern 5 · Hierarchical (Nested Teams) — slide 18

```
              CEO agent
          ┌───────┴───────┐
      CTO agent       CMO agent
      ┌───┴───┐       ┌───┴───┐
    Eng     Eng     Mktg    Mktg
```

- Trade-off: **coordination overhead grows with depth.**
- *"Most production systems use flat supervisor-worker."*
- Deck demo (slide 22): *CEO → 2 Leads → 4 workers → Integrator.* Watch —
  *"Three tiers; longest run (9 agents) — coordination tax."*

### Pattern 6 · Evaluator–Optimizer — slide 19

```
Generator ──▶ Evaluator ──▶ pass ──▶ Output
    ▲              │
    └──── fail ────┘
```

- One generates, another critiques — iterating until a quality threshold is met.
- Callback: this is agentic RAG's **self-check**, split across two agents.
- Deck demo (slide 22): *Generator ⇄ Evaluator (**max 3**).* Watch — *"Must be
  exactly 13 words; **fails round 1, passes by 2–3**."*
- Takeaway: *"Separate the creator from the critic."*

### Composition — slide 20

Patterns compose. The deck's own example:

```
Query ──▶ Router ② ──▶ Supervisor ④ ──▶ Evaluator ⑥ ──▶ Answer
```

*"Four patterns, one system: routing ② + parallel ③ + supervisor ④ + evaluator ⑥."*
Takeaway: *"Most real systems are LEGO compositions of the six — not a single
clean pattern."* This project is a composition too — ① + ② + ⑥ (§5).

---

## 4. The five agents are the deck's Human Swarm roles

**This is the load-bearing mapping in this repository, and it is not obvious.**

Slide 25 runs a physical exercise — "Become a multi-agent system" — in groups of
five. It defines five roles with an explicit **CAN / CANNOT** table. Those five
roles are, one for one, the five agent specifications in this directory:

| Slide 25 role | CAN | CANNOT | Spec file |
|---|---|---|---|
| **Orchestrator** | Read task, delegate by note, synthesise the final answer | Search, calculate, write, or critique | `04-manager.md` |
| **Researcher** | Search the data table for facts & numbers | Calculate, write, or critique | `01-researcher.md` |
| **Analyst** | Calculate — profit margins, comparisons | Search, write, or critique | `02-analyst.md` |
| **Writer** | Compose the **3-sentence** summary from given facts | Search, calculate, or critique | `03-writer.md` |
| **Critic** | Approve / reject **the summary** with a written reason | Search, calculate, or write | `05-evaluator.md` |

Two consequences that explain design decisions elsewhere in this repo:

1. **The CANNOT column is a specification, not flavour.** Slide 28 formalises it
   as the **Guardrail** field of the Agent Spec Card: *"what it must NOT do."* So
   `02-analyst.md`'s refusal to hold a retrieval tool is not fastidiousness —
   it is the deck's `CANNOT: search`, enforced in code. Same for the Writer and
   the Evaluator.
2. **The Orchestrator is a bottleneck by design, and the deck knows it.**
   Slide 27's debrief: *"Where was the bottleneck? Usually the Orchestrator — a
   single point of failure."* That is the empirical case `04-manager.md` argues
   from, before retiring the Manager.

Slide 25's communication rule — *"all communication via written notes to the
Orchestrator — no agent-to-agent talk"* — is a **star** topology. `Process.sequential`
is a **chain**. The build therefore does not reproduce the swarm's topology, only
its role decomposition. That is the right call for a fixed three-stage pipeline,
but it is a deviation worth naming (§10).

### The Agent Spec Card — slide 28

Every agent below is specified against the deck's five fields:

> **Role** (one sentence) · **Tools** (what it can access) · **Inputs** (what it
> receives) · **Outputs** (what it produces) · **Guardrail** (what it must NOT do)

---

## 5. The workflow this project builds

### 5a · Track A — the classroom crew (slides 45–48)

What the deck asks every group to build. Slide 47's diagram, verbatim:

```
Researcher ──▶ Analyst ──▶ Writer ──▶ One-page brief
```

**Pattern 1, unmodified.** Slide 45: *"Two of the six patterns are one word
each: `Process.sequential` (Pattern 1) and `Process.hierarchical` (Pattern 4).
That's why it's a great place to START."*

Slide 46 wires it:

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

Slide 48's four steps are the build procedure: scaffold something that already
runs → define three agents → define three tasks with specific `expected_output` →
`kickoff(topic)`, read the verbose log, tweak, re-run.

Slide 50's method: **"Steer, don't type."**

### 5b · Track B — the hosted Flow

This repo extends Track A with a warm vector cache. The extension adds exactly
one branch, and that branch is **Pattern 2 with the classifier removed**.

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

**The router is the whole point.** Slide 51 offers a Manager for dynamic
sequencing; this system has exactly one dynamic decision (hit vs miss) and
resolves it in code for **zero LLM calls**. `04-manager.md` keeps the Manager as
a measurable comparison rather than a component — which is what turns slide 53's
*"whether you'd keep it"* into two traces and a call count instead of an opinion.

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

The Agent Spec Card (slide 28) for each of the five, plus the hand-off contract.
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
| **Tools** | **none — deliberate** (slide 25: `CANNOT: search`) |
| **Inputs** | `context: [research_task]` |
| **Outputs** | *Bottom line* (one sentence) · *What matters* (3–4 findings + "so what") · *Confidence: High/Medium/Low* + justification · *What would change this*. 300–500 words. |
| **Guardrail** | Use ONLY the research notes. Introducing an outside fact is a failure, not initiative. Do NOT write the brief. Do not promote an unverified item by restating it confidently. |

**Why the empty tool surface is load-bearing.** With no tools, every claim *must*
trace to the Researcher's notes — so anything new is unambiguously invented, and
it sits one hand-off from its source in the trace. This is the cleanest place in
the system to observe slide 66's **error cascade**.

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

Slide 51 is the source (*"Fast finisher? Add a manager."*). It is retired because
the router already makes the only decision available, for free — but building it
once produces the trace comparison slide 53 asks for.

### ⑤ Evaluator — `05-evaluator.md` · *sourcing gate*

| Field | Value |
|---|---|
| **Role** | Editorial Fact-Checker with sign-off authority over the `{topic}` brief |
| **Tools** | none — it checks internal consistency, it does not re-research |
| **Inputs** | `context: [research_task, analysis_task, writing_task]` |
| **Outputs** | `VERDICT: PASS` / `FAIL` + a six-row checklist table + required fixes. Under 250 words. |
| **Guardrail** | Judge only against the checklist — style, tone and persuasiveness are out of scope. Do NOT rewrite or suggest wording. A brief honest about thin evidence is a PASS. |

Slide 62 asks for *"a fourth agent that rejects any brief without sources —
Pattern 6, in a few lines."* `05` implements the gate primarily as a **task
guardrail** on `writing_task`, because in `Process.sequential` a fourth agent
produces a verdict that nothing acts upon. The guardrail is the version that
actually closes the loop.

### Hand-off contract

| Boundary | What crosses | What must NOT cross |
|---|---|---|
| Researcher → Analyst | Facts + sources + explicit gaps | Conclusions, prose, rankings |
| Analyst → Writer | An argument, a confidence rating, what would change it | New facts; the finished brief |
| Writer → Evaluator | The brief + its Sources section | Meta-commentary about the process |
| Evaluator → Writer | A verdict and named failing checks | A rewrite |

Every row is a place slide 66's **error cascade** can start. The right-hand
column is what to grep the trace for.

---

## 7. Pattern coverage — what this build uses

| Pattern | Status | Where | Evidence to bring to slide 53 |
|---|---|---|---|
| ① Sequential Pipeline | **Core** | Researcher → Analyst → Writer | The verbose log's three stages |
| ② Routing / Handoff | **Used, LLM-free** | Flow `@router` on the staleness gate | `runs.route` in Postgres; router costs 0 calls |
| ③ Parallel Fan-out | **Not used** | — | See §8 |
| ④ Supervisor / Workers | **Comparison only** | `04-manager.md` | Two traces + a call count |
| ⑤ Hierarchical | **Not used** | — | See §8 |
| ⑥ Evaluator–Optimizer | **Specified, not in the baseline** | `writing_task.guardrail` (`03` word count, `05` sourcing) | The Writer running twice, second time carrying the failure — *once you attach it* |

**Answer to slide 53's "which of the six you used, and whether you'd keep it":**
the running system is ① + ②; ⑥ is one line away and specified in `03` and `05`.
Keep ①. Attach ⑥ — a callable guardrail is free and it is the only thing that
catches an unsourced brief. ② is worth keeping *only* if runs repeat (§10).

---

## 8. Why patterns 3 and 5 are absent

The deck teaches all six, so an unexplained absence is a gap. Both absences are
deliberate.

**③ Parallel Fan-out — no independent subtasks in this decomposition.** Slide 16's
condition is *"independent subtasks"*. The three stages have none: the Analyst
cannot start before the Researcher finishes, and the Writer cannot start before
the Analyst does. Every stage consumes its predecessor's entire output.

Be precise about this in a demo, though — "impossible" would be overstating it.
Three parallel variants *are* structurally available and were rejected on cost,
not on shape:

| Variant | Slide 16 mode | Why not |
|---|---|---|
| Scrape the 3–4 chosen URLs concurrently | sectioning | Real, but **tool-level**, not an agent topology. Worth doing; changes no boxes. |
| Query the cache **and** the live web at once, then merge | sectioning — *"search DB A, B, C at once"* | The whole point of the router is to *avoid* paying for the web call on a hit. Parallelising here spends the money the cache exists to save. |
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

**⑤ Hierarchical — explicitly warned against.** Slide 18: *"Don't go hierarchical
until you've proven you need it."* Slide 23: *"patterns 4 & 5 ran slowest and
priciest."* Slide 54: *"almost every real system is 2–5 agents."* A three-stage
pipeline with three workers has nothing to nest. Pattern 4 is already retired for
having no decision to make (§6④); pattern 5 would add a tier above that.

---

## 9. Where this workflow breaks

Slide 66's six production problems, mapped onto this specific topology.

| # | Slide 66 problem | Where it lands here | Mitigation in these specs |
|---|---|---|---|
| 1 | **Error cascade** | A fabricated citation in stage 1 becomes a confident claim in stage 3. The Analyst's empty tool surface makes it visible one hand-off from its source. | Analyst confidence rating (`02`) · sourcing guardrail (`05`) |
| 2 | **Cost explosion** | Scraping all five search results; guardrail retries; `glm-5.3-flash` reasoning tokens billing at completion rate. | `limit: 5` + "read snippets first" (`01`) · `guardrail_max_retries: 2` (`05`) · `reasoning_effort: "minimal"` (`00` §3) |
| 3 | **Debugging complexity** | Which stage lost the source URL? | `verbose=True` · CrewAI AMP tracing · `run_sources` table (`07`) |
| 4 | **Security & trust** | **Weakest coverage.** Scraped web content enters an LLM context, then rides forward into the Analyst's and Writer's contexts. Slide 57 notes MCP tool poisoning and the first agentic-AI CVE. | Now **specified but not implemented**: `01-researcher.md` §"Untrusted input" (injection via scraped pages) and `06-retrieval-layer.md` §"The cache is shared mutable state" (poisoning, which is durable and cross-group). Both name concrete containment; neither is built. |
| 5 | **State management** | Flow state; the Pinecone index is shared mutable state across runs *and across groups*. A bad scrape poisons future cache hits. | Write-back rules (`06`) · `indexed_at` staleness gate |
| 6 | **Evaluation** | Is the brief good? Nothing scores it end to end. | Checklist gate (`05`) · `run_metrics` (`07`) — but no quality score |

The staleness gate deserves its own warning. It is the **single most dangerous
failure this architecture can produce**: a cache hit on month-old material yields
a brief that is perfectly well-sourced and wrong. All three conditions — ≥3 hits,
top rerank score ≥0.30, `indexed_at` ≤60 days — must hold, and the threshold sits
on the **rerank** score, not the cosine score, because cosine scores on this index
cluster within 0.06 and admit no defensible cutoff.

---

## 10. Declared deviations from the deck

Listed so they can be defended in a demo rather than discovered in one.

| # | Deck says | This build does | Why |
|---|---|---|---|
| 1 | Pattern 1 example is `Researcher → Writer → Editor` (s14, s22) | `Researcher → Analyst → Writer` | The deck's own build slides (47, 48) specify this triple. An Analyst judges *before* writing; an Editor polishes *after*. The build follows slides 47–48. |
| 2 | Evaluator is *"a fourth agent"* (s62) | Primarily a **task guardrail**; the agent is optional | In `Process.sequential` a fourth agent emits a verdict that gates nothing. The guardrail closes the loop; the agent only reports. `05` documents both. |
| 3 | Evaluator loop is `max 3` (s22) | `guardrail_max_retries: 2` | Each retry is a full task re-run *plus* a judgement call. If two focused attempts fail, the defect is upstream in stage 1 and no rewrite conjures sources. |
| 4 | Manager for dynamic sequencing (s51) | Retired; a code `@router` decides | The only dynamic decision is binary and thresholded. A Manager would charge one LLM call per run to reach the same answer. Kept as a measured comparison. |
| 5 | Human Swarm is a **star** through the Orchestrator (s25) | A **chain** via `context=[...]` | Star topology needs a hub; the hub is the Manager, which is retired. Sequential chaining passes prior outputs implicitly. |
| 6 | *"Give your Researcher a real MCP tool"* (s62) | Native Firecrawl tools; MCP documented as the next step | Native tools deliver the substance now. `01` specifies the MCP swap as a clean A/B — capability held constant, only transport changes. |
| 7 | Six patterns taught | Three used, two refused with reasons, one retired | §7 and §8. Slide 33: *"Find the simplest solution possible."* |
| 8 | Slide 56: go multi-agent when *"single-agent tried and measurably failed"* | **Not done.** No single-agent baseline exists. | Honest gap. The cheapest experiment available and the strongest possible demo evidence — see below. |

### The two experiments worth running

1. **The single-agent baseline (deviation 8).** One well-prompted agent with the
   same three tools, same topic, same brief format. Count the calls in both
   traces. Slide 55 predicts ~10 calls for the crew against ~1 for a single
   agent; slide 65 predicts 3–10× cost. Measure it on your own topic instead of
   taking it on faith.
2. **Router versus Manager (deviation 4).** Same decision, two implementations,
   two call counts. `04-manager.md` exists to make this runnable.

### The unmitigated risk (§9 #4)

Scraped web content flows into three agents' contexts with no sanitisation. A
page containing instructions rather than facts is an untested attack path, and
the Researcher's own failure table already notes that a failed tool call followed
by confident output is the fabrication signature to watch for. Slide 67's harness
— *"budgets, retries, guardrails, scoped permissions, validation gates between
agents"* — is exactly what is missing. Slide 67's takeaway applies without
qualification: *"Your crew ran with no seatbelts. Fine for learning; not fine for
anything real."*

---

## 11. Demo mapping (slide 53)

Three minutes, one rep per group, four things to bring.

| Requirement | Where the evidence comes from |
|---|---|
| **Your topic** — one sentence, and why | Your group's choice. `kickoff(inputs={"topic": ...})` |
| **One run** — the brief, or the trace | `output/brief.md` (`03`) and the verbose log / AMP trace (`08`) |
| **One surprise** — a hallucination, a strange hand-off, a manager rejection | The failure tables in `01`, `03`, `05`. Slide 52: ***"If it produces junk, don't fix it quietly — junk makes the best demo."*** Screenshot it first. |
| **One pattern** — which of the six you used, and whether you'd keep it | §7 for which; §10 and `02`'s closing argument for whether |

The strongest available answer to "whether you'd keep it" is not an opinion but the
call count from two traces — which is why §10's two experiments are the highest-value
work left in this repository.

---

## 12. Source map

Slides actually cited in each section, extracted from the text rather than
written by hand:

| This file's section | Slides cited |
|---|---|
| §1 two layers | 3, 53 |
| §2 five ceilings | 9, 55, 56 |
| §3 six patterns | 13, 14, 15, 16, 17, 18, 19, 20, 22 |
| §4 Human Swarm roles · Agent Spec Card | 25, 27, 28 |
| §5 the build (A and B) | 45, 46, 47, 48, 50, 51, 53 |
| §6 agent contracts | 25, 28, 51, 53, 62, 66 |
| §7 pattern coverage | 53 |
| §8 why 3 and 5 are absent | 16, 18, 23, 54 |
| §9 what breaks | 57, 66 |
| §10 deviations | 22, 25, 33, 47, 48, 51, 55, 56, 62, 65, 67 |
| §11 demo | 52, 53 |

Track B (§5b) is this project's own extension and cites no slide — see
`07-deployment.md`.
