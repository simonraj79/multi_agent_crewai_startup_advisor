# Brief Crew

One topic in, one one-page brief out — a CrewAI Researcher → Analyst → Writer
pipeline over a warm Pinecone cache.

Built to the specifications in [`agents/`](agents/), which remain authoritative:
this code implements them, it does not supersede them. Start with
[`agents/00-shared-config.md`](agents/00-shared-config.md) (§0 first — *why a
crew at all*) and [`agents/workflow.md`](agents/workflow.md).

---

## Quick start

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv -e .

# Track A — the three-agent crew. Start here.
.venv/Scripts/python -c "from brief_crew.main import run_crew; run_crew('your topic')"

# Track B — the same crew behind a warm-cache router.
.venv/Scripts/python -c "from brief_crew.main import kickoff; kickoff('your topic')"
```

The brief lands in `output/brief.md`. Watch the verbose trace while it runs —
that is the only view you have of who handed off to whom, and it is what slide 53
asks you to show.

Credentials come from `.env` (five keys, all already provisioned). Nothing else
needs configuring.

---

## The two tracks

| | **Track A** — `run_crew()` | **Track B** — `kickoff()` |
|---|---|---|
| Orchestration | `Process.sequential` | `Flow` with a deterministic `@router` |
| Who checks the cache | the Researcher, via `retrieve_and_rerank` | the Flow, *before* any agent runs |
| Researcher tools | 3 | 2 |
| Infrastructure | none beyond the API keys | Pinecone · Cohere · (Render Postgres) |

**Build and run Track A first.** Every stretch in this repository presupposes a
working sequential crew.

```
                      ┌──────────────────────┐
   topic ────────────▶│   retrieve_cached    │  Pinecone + Cohere
                      └──────────┬───────────┘
                        ┌────────▼────────┐
                        │  check_cache    │   relevance + freshness
                        └───┬─────────┬───┘   0 LLM calls
                     miss   │         │  hit
                    ┌───────▼──────┐  │
                    │  Researcher  │  │       Firecrawl search + scrape
                    └───────┬──────┘  │
                    ┌───────▼──────┐  │
                    │ index_content│  │       chunk / embed / upsert
                    └───────┬──────┘  │
                            └────┬────┘
                        ┌────────▼────────┐
                        │     Analyst     │   no tools — judgement only
                        └────────┬────────┘
                        ┌────────▼────────┐
                        │     Writer      │   no tools — prose only
                        └────────┬────────┘
                                 ▼
                          output/brief.md
```

---

## Layout

```
src/brief_crew/
├── config.py                     models · prices · embedding prefixes · thresholds
├── embeddings.py                 OpenRouter embeddings, called directly
├── indexing.py                   chunk / embed / upsert — plumbing, not a tool
├── guardrails.py                 the evaluator gate on writing_task
├── main.py                       run_crew() = Track A · kickoff() = Track B
├── crews/brief_crew/
│   ├── config/agents.yaml        role · goal · backstory · runtime guard rails
│   ├── config/tasks.yaml         descriptions · expected outputs
│   └── brief_crew.py             @CrewBase — the wiring
└── tools/pinecone_retrieval.py   retrieve_and_rerank
```

**The prompts are data, the wiring is code, and the constants are neither
duplicated nor inlined.** `agents.yaml` and `tasks.yaml` hold every word an agent
reads; `brief_crew.py` holds only what cannot be expressed as data — LLM objects,
tool instances, the guardrail list, the track switch. Every model name, embedding
prefix and threshold exists exactly once, in `config.py`.

`agents/00-shared-config.md` §11 maps each file back to the spec section it
implements.

---

## Three things worth knowing before you change anything

**1. `context` is three-valued.** `Task.context` unset means *inherit every prior
output*; an explicit list means *exactly these*; an empty list means *nothing at
all*. CrewAI models this with a `_NotSpecified` sentinel rather than `None`. So
trimming `writing_task`'s context to `[analysis_task]` looks like tidying and
silently strips every source URL, because the Analyst compresses them away.

**2. The Researcher's tool list and its task must change together.** Track A's
task tells the agent to call `retrieve_and_rerank` first; Track B's does not,
because the Flow has already retrieved and already failed the staleness gate. An
agent told to call a tool it does not have will invent the result — that is the
direct cause of fabricated citations. `BriefCrew` selects both from one `track`
argument so they cannot be mismatched.

**3. Do not route embeddings through CrewAI.** ChromaDB forwards the `dimensions`
parameter only when the model name contains `"text-embedding-3"`.
`google/gemini-embedding-2` fails that test, so `dimensions=768` would be dropped
silently and 3072-dim vectors would be sent at a 768-dim index — no error, just
failed upserts a long way from the cause.

---

## Testing without spending tokens

The deterministic half of this system costs nothing to check, and both gates are
pure functions:

```python
from brief_crew.guardrails import check_mechanics   # word count, sources
from brief_crew.main import BriefFlow               # check_cache: the staleness gate
```

`check_mechanics` runs before the string guardrail precisely so the free check
rejects first. `check_cache` returns `cache_hit` only for ≥3 hits with a top
rerank score ≥0.30 indexed within 60 days — and treats missing `indexed_at` as
stale, never as fresh.

---

## Honest cost note

A cache **miss** costs the full pipeline — retrieve, rerank, search, scrape,
embed, upsert, then three agents — which is *more* than the plain crew, not less.
A cache **hit** skips search and scrape entirely and is markedly cheaper. The
architecture only pays for itself if runs repeat.

The first run on any topic is always the expensive one; that is the design
working, not failing. As of the last `crewai run` the index holds **3 vectors**
for *cashless payments in Singapore*, and that topic now routes `cache_hit` —
any other topic still misses.

> ⚠️ **Known gap — write-back carries no structured provenance.** The cache *does*
> warm: one `cache_miss` run writes 3 chunks and the next run returns `cache_hit`
> (verified, top rerank 0.7877). But every chunk has `url=""` and `publisher=""`,
> because the Flow indexes the Researcher's *notes* rather than the scraped
> *pages*. Briefs are not blocked — the URLs survive inside the chunk text — but
> `run_sources` cannot be populated, and 3 chunks sits exactly on the ≥3
> threshold with no margin. Detail and fix in `agents/06-retrieval-layer.md`.

### Measured, 2026-08-29 — one Track A run, cold cache

**9 LLM calls** · 178,711 prompt / 13,614 completion tokens · ~7 minutes ·
between **$0.017 and $0.185** depending on how the calls split across the two
tiers. Slide 55 predicted "~10 calls where one good agent makes one"; it was 9.

**72% of every completion token was reasoning** (9,757 of 13,614), and reasoning
bills at the completion rate. `agents/00-shared-config.md` §3 measured
`reasoning_effort: "minimal"` at 8.8× cheaper on short mechanical calls — on this
evidence that is the largest untaken cost lever in the project.

### Measured, 2026-08-29 — one Track B run via `crewai run`, cold cache

**13 LLM calls** · 109,104 prompt / 30,085 completion tokens · ~7 minutes ·
**≤$0.1946** (upper bound, everything priced at the escalation tier). Route
`cache_miss`, 3 chunks written back, `output/last_run.json` produced.

Four more calls than the Track A run (13 vs 9) for the same topic and the same
brief. The Flow adds the retrieval round-trip and re-runs the writer path through
its own crew construction; that difference is the Track B overhead, paid on every
miss and only repaid on a subsequent hit.

`agents/02-analyst.md` documents the strongest argument against its own agent's
existence, and none of the retrieval infrastructure changes it — all of that sits
upstream. Read it before deciding whether you would keep this shape.

---

## Toolchain

The CrewAI CLI is installed globally as a uv tool, so `crewai` works from any
directory:

```bash
uv tool install crewai        # -> crewai 1.15.18 on PATH
crewai install                # uv sync + writes uv.lock
crewai run                    # runs the Flow (pyproject [tool.crewai] type = "flow")
```

`crewai run` maps to `[project.scripts] kickoff` — the **Track B Flow**. For the
Track A crew, call `run_crew` directly (see Quick start above).

**Agent skills.** The four official CrewAI skills are vendored into the repo by
`npx skills add crewaiinc/skills`, which writes `.agents/skills/` (read by Cursor,
Codex, Gemini CLI and a dozen others) and `.claude/skills/` (read by Claude Code).
They are committed on purpose, so any coding agent that opens this repo gets the
same CrewAI guidance without a separate install step. Re-run the command to update.

> Two CLI behaviours worth knowing, both documented in
> `agents/00-shared-config.md` §9:
>
> - `CREWAI_DMN=true crewai create` **fails** — DMN is non-interactive mode, which
>   makes TYPE and NAME required. Use `CREWAI_DMN=true crewai create flow <name>`.
>   Bare `crewai create` needs a TTY for its picker, so DMN-with-arguments is the
>   only form that works in CI.
> - `crewai install` runs `uv sync`, which **uninstalls** anything absent from
>   `pyproject.toml`'s default dependencies. That correctly prunes this project's
>   optional `service` extra (`fastapi`, `sqlalchemy`, `psycopg`); install it back
>   with `uv pip install -e '.[service]'` when Track B deployment gets built.
