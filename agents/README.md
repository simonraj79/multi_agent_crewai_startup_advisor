# Agent Specifications — Brief Crew

Specifications for the CrewAI build defined in
`shaun-chong-multi-agent-orchestration-20260829.pdf` (slides 47–51, 62), extended
into a hosted service.

**Goal:** one topic in → one finished one-page brief out, backed by a warm vector
cache so repeat runs get cheaper.

These are *specifications*, and they remain authoritative. **As of 2026-08-29 the
implementation exists** — `src/brief_crew/` is these documents as running code,
and `00-shared-config.md` §11 maps every spec section to the file that implements
it. Where code and spec disagree, the spec is right and the code is a bug.

The deck's method (slide 50) is **"Steer, don't type"** — describe intent to your
AI assistant, read what it writes, tweak, re-run. Each file here is the intent,
written precisely enough to hand over verbatim, and that is exactly how the
`role` / `goal` / `backstory` / `description` blocks reached
`config/agents.yaml` and `config/tasks.yaml`: pasted, not paraphrased.

---

## The system

```
                      ┌──────────────────────┐
   topic ────────────▶│   retrieve_cached    │  Pinecone + Cohere
                      └──────────┬───────────┘
                                 │
                        ┌────────▼────────┐
                        │  check_cache    │   relevance + freshness
                        └───┬─────────┬───┘   0 LLM calls
                     miss   │         │  hit
                    ┌───────▼──────┐  │
                    │  Researcher  │  │       Firecrawl search + scrape
                    └───────┬──────┘  │
                    ┌───────▼──────┐  │
                    │ index_content│  │       chunk / embed / upsert
                    └───────┬──────┘  │       (plumbing, not a tool)
                            └────┬────┘
                        ┌────────▼────────┐
                        │     Analyst     │   no tools — judgement only
                        └────────┬────────┘
                        ┌────────▼────────┐
                        │     Writer      │   no tools — prose only
                        └────────┬────────┘
                                 ▼
                    output/brief.md + Postgres run record
```

Orchestrated by a **CrewAI Flow**. The cache-hit/miss branch is the only genuinely
dynamic decision in the system, and a `@router` resolves it deterministically.

**In the deck's vocabulary this is Pattern ① (Sequential Pipeline) with a
Pattern ② (Routing) branch resolved in code instead of by a classifier agent,
and a Pattern ⑥ (Evaluator–Optimizer) gate on the final task.** Patterns ③
Parallel and ④/⑤ Supervisor/Hierarchical are deliberately not used. Full
mapping, with the reasons, in `workflow.md` §7–§8 — that is the file that
answers slide 53. For how each pattern is *built* in CrewAI, see `patterns.md`.

---

## Files

| File | What it specifies |
|---|---|
| `00-shared-config.md` | Tech stack, credentials, models, prices, guard rails, documentation traps. **Read first.** |
| `workflow.md` | **The workflow map.** How the deck's six patterns land in *this* build, how the five agents derive from the Human Swarm, per-agent I/O contracts, and every declared deviation. **Read second.** |
| `patterns.md` | **Agent design patterns.** How each of the six is implemented in CrewAI generically — mechanisms, code, constraints and cost, verified against the 1.15.18 source. The reference for the slides. |
| `01-researcher.md` | Stage 1 — retrieval-first, then Firecrawl on a miss. The only agent with tools. |
| `02-analyst.md` | Stage 2 — judgement. No tools, deliberately. |
| `03-writer.md` | Stage 3 — the brief, and provenance rules. |
| `04-manager.md` | *Superseded* — kept as a measurable comparison against the router. |
| `05-evaluator.md` | Sourcing gate. A task guardrail first; an optional fourth agent second. |
| `06-retrieval-layer.md` | The Pinecone tool, embedding conventions, chunking, rerank, staleness gate. |
| `07-deployment.md` | Flow, Postgres schema, `render.yaml`, provisioned resources, costs. |
| `08-observability.md` | CrewAI AMP, why not LiteLLM, why not LangSmith, what to instrument. |

---

## Stack

| Concern | Provider | Credential |
|---|---|---|
| LLM — default | `z-ai/glm-5.3-flash` · $0.075/$0.250 | `OPENROUTER_API_KEY` |
| LLM — escalation | `google/gemini-3.7-flash` · $0.75/$3.75 | same |
| Embeddings | `google/gemini-embedding-2` @ **768** dims · $0.20/Mtok | same |
| Web search + fetch | Firecrawl | `FIRECRAWL_API_KEY` |
| Vector store | Pinecone · `agentic-crew-ai-index` | `PINECONE_API_KEY` |
| Rerank | Cohere `rerank-v4.0-fast` | `COHERE_API_KEY` |
| Database + hosting | Render · Postgres 18 + web + static | `RENDER_API_KEY` |
| Tracing | **CrewAI AMP** (free tier) + Postgres `run_metrics` | `crewai login` |

Pinned: Python 3.13 · `crewai` **1.15.18** · `crewai-tools` **1.15.18** ·
`firecrawl-py` **4.40.0** · `pinecone` **9.1.0**.

**No new accounts are required** — all five credentials already exist. Notably no
Google key (Gemini embeddings are served through OpenRouter) and no OpenAI key
(`Crew.memory` stays `False`, so the default OpenAI embedder is never reached).

> ✅ **`.env` is complete and correctly spelled** (verified 2026-08-29). An
> earlier revision of these specs warned about a `FIRECRWALL_API_KEY` typo; it
> has been corrected. `.env` additionally sets `PINECONE_INDEX_NAME`.

---

## Using these specs

Steps 2–5 below are **done**. They are kept because the order is the lesson, and
because reading them tells you what each part of `src/brief_crew/` is for.

0. **Toolchain.** `uv tool install crewai` puts the CLI on PATH;
   `npx skills add crewaiinc/skills` vendors the four official CrewAI skills into
   `.agents/skills/` and `.claude/skills/` so any coding agent opening this repo
   gets the same guidance. Both done — see `README.md` → Toolchain.
1. Read `00-shared-config.md` (§0 first — *why a crew at all*) and
   `workflow.md`. Create the isolated venv `00` specifies; installing into the
   conda base **will** conflict on pydantic. `crewai install` does this for you,
   but note it runs `uv sync` and will *uninstall* anything outside
   `pyproject.toml`'s default dependencies.
2. ~~Scaffold something that already runs~~ — done via `crewai create flow`,
   which generates the `@CrewBase` + YAML structure these specs assume. The
   scaffold was generated by the CLI and then edited, never hand-written.
   ⚠️ In CI or any non-TTY shell the *only* working form is
   `CREWAI_DMN=true crewai create flow <name>` — DMN is non-interactive mode and
   makes TYPE and NAME required, while bare `crewai create` needs a TTY picker.
3. ~~Hand your assistant `01`, `02`, `03`~~ — done. Their identity and task
   blocks are in `config/agents.yaml` and `config/tasks.yaml`, verbatim.
4. ~~Assemble Track A and run it end to end~~ — done: `run_crew()`.
5. ~~Build the retrieval tool from `06`, wire the Flow from `07`~~ — the tool and
   the Flow are built, and the Flow has been run end to end via `crewai run`
   (route `cache_miss`, 13 calls, 3 chunks written back). **Deployment is done
   too**, as of 2026-08-30: the repo is on GitHub, the FastAPI service and the
   static site are live on Render, and the schema exists on real PostgreSQL 18.
   An earlier revision of this line said none of that existed; it is stale, not
   cautious. What is *not* done is the thing deployment was clearing the way for:
   **no validator run has ever been launched against paid services**, so nothing
   end to end is proven. See the checklist in `07-deployment.md`.

**What remains open**, in the order worth doing it:

| # | Gap | Where |
|---|---|---|
| 0 | **Write-back has no structured provenance.** One `cache_miss` run writes **3 chunks** and the next run does return `cache_hit` (verified: top rerank 0.7877) — but every chunk carries `url=""` and `publisher=""`, because the Flow indexes the Researcher's *notes* rather than the scraped *pages*. URLs survive inside the chunk text, so briefs are not blocked; `run_sources` cannot be populated and the Analyst is shown `url: unknown` above passages containing real URLs. Three chunks is also exactly the threshold, with no margin. | `06` |
| 1 | **The single-agent baseline.** Still not run. `00` §0 calls this the most important missing sentence in the repo, and it is now the cheapest experiment available — the crew it must beat already runs. | `00` §0, `workflow.md` §10 |
| 2 | **Quality scoring.** Cost is measured; quality is not, so all four A/B comparisons still resolve to "the cheap one won" by construction. | `05` |
| 3 | **Per-agent cost split.** Crew-level `token_usage` is not broken down by model, so the recorded figure is an upper bound ($0.017–$0.185 on the measured run — a 11× band). Needs a `BaseEventListener` on `LLMCallCompletedEvent`. **The same listener fixes gap 0**, so do them together. | `08`, `06` |
| 4 | **Namespaces.** `index_documents` takes a `namespace` argument that nothing passes — the blast-radius containment `06` asks for is one keyword away. | `06` |
| 5 | **The paid acceptance run.** Everything is deployed and answering health checks; nothing has validated an idea. One real run through both gates, with citation closure inspected, is what turns this from built into working. | `07` |

### Track A — the minimum runnable crew

Slide 48 step 4 is `kickoff(topic)`, and it is the step most likely to get
skipped when the specs are this detailed. This is the whole of it.

> ✅ **The retrieval tool now exists, so this is *full* Track A** — three tools
> and step 0 included. Earlier revisions of this block described a two-tool
> day-one version and told you to delete step 0; that no longer applies here,
> but the underlying rule still does, and it is now enforced in code: the tool
> list and the task variant are chosen together from one `track` argument, so an
> agent can never be told to call a tool it does not have. That mismatch is
> exactly what produces fabricated citations.

It is one call, because the assembly lives in `BriefCrew`:

```python
from brief_crew.main import run_crew

result = run_crew("cashless payments in Singapore")
print(result.token_usage)          # successful_requests is your call count
```

Which is this, with every prompt loaded from YAML and every constant from
`config.py`:

```python
# src/brief_crew/crews/brief_crew/brief_crew.py
@CrewBase
class BriefCrew:
    @agent
    def researcher(self) -> Agent:
        tools = [FirecrawlSearchTool(config={"limit": 5}), FirecrawlScrapeWebsiteTool()]
        if self.track == "A":
            tools.insert(0, PineconeRetrieveRerankTool())
        return Agent(config=self.agents_config["researcher"], tools=tools,
                     llm=LLM(model=CHEAP_MODEL))

    @agent
    def analyst(self) -> Agent:      # tools=[] is the point, not an omission
        return Agent(config=self.agents_config["analyst"], tools=[],
                     llm=LLM(model=ESCALATION_MODEL))

    @crew
    def crew(self) -> Crew:
        return Crew(agents=..., tasks=..., process=Process.sequential,
                    memory=False,   # keeps the OpenAI embedder unreachable
                    verbose=True)
```

`verbose=True` is not decoration — it is the trace slide 50 tells you to watch,
and the only view you have of who handed off to whom. `token_usage` is what turns
slide 53's *"whether you'd keep it"* into a number.

### Choosing your topic

Slide 47: *"Pick a topic your group actually cares about."* Beyond that, these
specs imply four hard constraints, and picking badly is the direct cause of the
most common failure in `01-researcher.md`:

- **Narrow enough to converge.** "Topic too broad" is `01`'s top failure mode,
  and the fix is a narrower topic, never a higher `max_iter`.
- **It must have a *finding*, not just a subject.** The Writer is required to put
  the conclusion in the title. If the topic has no arguable answer, that is
  impossible and the whole pipeline reads as a summary.
- **Recent, datable, numeric material must exist.** `inject_date`, the 18-month
  rule and the 60-day staleness gate all assume sources that carry dates and
  numbers.
- **Prefer something you will run more than once.** The cache only pays off if
  runs repeat — see the cost note below.

---

## What to bring to the demo

Per slide 53, three minutes each:

- **Your topic** — one sentence, and why your group picked it. See "Choosing
  your topic" above.
- **One run** — the brief, or the trace of it being produced. `output/brief.md`
  plus the verbose log; have both open.
- **One surprise** — a hallucination, a strange hand-off, or — for this build —
  a stale cache hit. (The deck's own example is a manager rejection.) The
  failure tables in `01`, `03` and `06` are a catalogue of candidates.
- **One pattern** — which of the six you used, and whether you'd keep it.
  **The answer is in `workflow.md` §7**: a composition of ① Sequential Pipeline
  + ② Routing + ⑥ Evaluator–Optimizer.

### Running the 70 minutes (slide 50)

- **Steer, don't type.** Describe each agent and task to the assistant, read what
  it writes, tweak.
- **Rotate the driver** every ~20 minutes; everyone touches the crew.
- **Stuck more than 5 minutes?** Flag it rather than burning the block.
- **Before the end**, pick your demo rep and the one run you want to show — do
  not leave this to the last two minutes.
- Slide 52's checkpoint, half-way: a crew that runs end to end, a brief, a
  verbose log you can point at, and a rep.

---

## Measured runs — 2026-08-29

Two real runs on *cashless payments in Singapore*, both against a **cold cache**
(the index held 0 vectors, so both took the expensive path by construction).
This is the evidence slide 53 asks for.

| | Track A — `run_crew()` | Track B — `crewai run` |
|---|---|---|
| LLM calls | **9** | **13** |
| Prompt / completion tokens | 178,711 / 13,614 | 109,104 / 30,085 |
| Cost, escalation-tier bound | ≤ $0.1851 | ≤ $0.1946 |
| Route | n/a (no router) | `cache_miss` |
| Write-back | none | **3 chunks** |

**The Flow costs +4 LLM calls for the same brief** — the retrieval round-trip
plus its own crew construction. That is the Track B overhead, paid on every miss
and only repaid on a later hit. The 3 chunks it wrote back are what make the
repayment possible: a re-run on that topic now returns `cache_hit` (top rerank
**0.7877**), so the warm-cache design is confirmed working rather than assumed.

The detail below is the Track A run.

| | |
|---|---|
| LLM calls (`successful_requests`) | **9** |
| Prompt / completion tokens | 178,711 / 13,614 |
| — cached prompt tokens | 58,624 (**33%** of prompt) |
| — **reasoning** tokens | 9,757 (**72% of all completion tokens**) |
| Cost, all-cheap-tier bound | $0.0168 |
| Cost, all-escalation bound | $0.1851 |
| Guardrails | both ran, both passed **first attempt** — no retry |
| Wall clock | ~7 minutes |

**Slide 55 predicted "~10 LLM calls" where one good agent makes one. It was 9.**
That is the multi-agent premium, measured on this build rather than assumed.

**The reasoning finding is the actionable one.** 72% of every completion token
this crew produced was reasoning, and reasoning bills at the completion rate —
$3.75/Mtok on the escalation tier. Reasoning alone accounts for **$0.0366** of
the upper bound, roughly a fifth of the run. `00` §3 already measured
`reasoning_effort: "minimal"` at **8.8× cheaper** on short mechanical calls and
recommended testing it on the Researcher; this run turns that from a suggestion
into the single largest untaken cost lever in the project.

**The brief passed on its own terms**, which is the part that matters more than
the cost:

- Title states a *finding*, not the subject — "Singapore Settles into a Permanent
  Cash-Lite Equilibrium, Not a Cashless Future". `03-writer.md` calls this the
  cheapest test of whether the pipeline produced anything, and it passed.
- 583 words, inside the 500–700 ceiling. Five distinct sources.
- The Analyst's **Medium** confidence survived the hand-off into the brief, in
  plain language, as `03`'s constraint requires.
- It stayed honest about gaps: *"commercial POS market datasets exhibit
  unresolved internal discrepancies, and official 2025 MAS cash-in-circulation
  statistics remain unavailable."* The Researcher's "Unverified" discipline
  propagated all three stages without being flattened.
- It preserved the tension rather than resolving it — 92% digital adoption
  against 82% continuing cash use — which is exactly what `02-analyst.md` means
  by "do not flatten recorded disagreement".

**Three failures worth demoing** (slide 53 asks for one surprise; there are
three, and the best two are the ones that did not look like failures):

1. **The first run died with `TimeoutError` and produced nothing**, at the
   spec'd `max_execution_time: 300`. Under `Process.sequential` a task timeout is
   fatal, not partial. Raised to 600 — see `01`'s failure table. This one at
   least announced itself.
2. **Every trace line was silently discarded on that same run** by a Windows
   cp1252 encoding error in the event bus. Handler exceptions never break a run,
   so the crew ran to completion, cost full price, and produced no usable log.
   `00` §9 has the detail.
3. **The Flow reported `cost=$0.000000` for a run that cost real money** — a
   `.get("cost_usd", 0)` against a dict whose key was `cost_usd_upper_bound`.
   The correct figure was in `output/last_run.json` the whole time. `08` has it.

Two and three are the interesting ones, because **an instrument that is broken
and an instrument reading zero look identical**. Both were found by checking the
artifact against the run rather than by anything failing. That is the honest
answer to "what surprised you": not that the agents hallucinated, but that the
measurement did.

---

## Honest cost note

The deck is blunt about this (slides 55, 65) and the specs inherit it.

A cache **miss** costs the full pipeline — retrieval, rerank, search, scrape,
embed, upsert, then three agents — which is *more* than the original crew, not
less. A cache **hit** skips search and scrape entirely and is markedly cheaper.
The architecture only pays for itself if runs actually repeat: same topic across
demo runs, adjacent topics across groups, reuse across a semester. On a genuinely
one-shot novel topic the hit rate is zero and the retrieval branch is pure
overhead.

`02-analyst.md` still documents the strongest case against its own existence, and
none of the new infrastructure changes that argument — all of it sits upstream.
Read it before the demo — slide 53's "whether you'd keep it" is a graded
question.

The measurement is built in: `run_metrics.successful_requests` in Postgres, from
`CrewOutput.token_usage`, with the dollar figure **computed** from those token
counts against the price table in `00-shared-config.md` §3. CrewAI discards
OpenRouter's per-generation `cost` before it reaches any event, so the billed
figure is not available in-process — reconcile against OpenRouter's Activity API
if you need it. Every cost claim this project makes should be a query, not an
anecdote. See `08-observability.md`.
