# 06 · Retrieval Layer

The Pinecone tool, the embedding conventions, and the Cohere rerank pass.

> 🔨 **Implemented** across three files, matching this file's insistence that
> retrieval is a tool, indexing is not, and reranking is neither:
>
> | This file | Code |
> |---|---|
> | `retrieve_and_rerank` | `src/brief_crew/tools/pinecone_retrieval.py` — a `BaseTool`, plus a plain `retrieve()` the Flow calls with no agent involved |
> | the two embedding prefixes | `src/brief_crew/config.py`, applied only in `embeddings.py` — two constants, one call site each |
> | chunking + write-back | `src/brief_crew/indexing.py` — a Flow step, not a tool |
> | the staleness gate | `config.py` constants, applied in `main.py::check_cache` |
>
> `source_run_id` is on every upsert, so one bad run is revocable with a filtered
> delete.
>
> **Updated 2026-08-29 — namespaces and metadata filtering are now both wired,
> on the validator path only.** An earlier revision of this line said per-tenant
> namespaces were "supported but not set" and that `retrieve()` could not filter
> at all. Both have since changed:
>
> | | Then | Now |
> |---|---|---|
> | `retrieve()` filtering | no `filter=` argument; per-branch/per-category retrieval impossible | takes `metadata_filter` and forwards it as `filter=` (`pinecone_retrieval.py:84-113`) |
> | namespace on read | not passed | takes `namespace` and forwards it |
> | namespace on write | `index_documents` accepted one, nothing passed it | `validator_cache.resolve_namespace()` passes a per-user opaque hash |
>
> Both arguments are **additive and default to `None`**, so the Brief Crew path
> issues exactly the same unfiltered, default-namespace query it always did —
> namespaces and metadata filters remain a validator-path feature.
>
> The **provenance** defect described below is a separate matter, and it is now
> **closed on both paths**: `main.py::index_content` indexes one document per
> scraped source URL. See the correction in that section.
>
> Verified live 2026-08-29: direct embedding calls return **768** dims, the index
> is dimension 768 / cosine, and Cohere separates a relevant from an irrelevant
> document by 0.26 where cosine would have separated them by far less. The index
> now holds **3 vectors**, written back by the first `crewai run`; that topic
> returns `cache_hit` on a re-run. The full round trip — chunk, embed, upsert,
> query, rerank, gate, and a filtered delete by `source_run_id` — is verified.

This is **not an agent**. It is one tool the Researcher calls, plus one piece of
plumbing that runs without the Researcher's involvement. Reading it as "the
retrieval agent" is the mistake this file exists to prevent.

---

## Why no agent lives here

Three candidate agents were considered and all three rejected against CrewAI's
own heuristic, the same one quoted in `02-analyst.md`:

> If two "agents" share the same persona, the same tool surface, and the same
> LLM, they are one agent with a longer task description.

| Candidate | Verdict |
|---|---|
| **Indexer / Librarian** — chunks and upserts scraped text | **Rejected.** No persona a backstory could inhabit, no judgement, no branching. It is a deterministic function of text the Researcher already produced. |
| **Retriever** — queries the index | **Rejected as an agent, accepted as a tool.** Deciding *whether* the retrieved material is good enough is judgement — but it is the Researcher's judgement, of exactly the kind it already exercises. |
| **Reranker** — scores candidates | **Rejected, most clearly of the three.** A cross-encoder scoring call has zero reasoning content. Wrapping it in an Agent buys a role, a backstory and an LLM call around a pure function. |

Indexing goes further than "not an agent": it is **not even a tool**. There is no
decision content in "chunk this page and write it to the index", so exposing it
as a tool only adds something the agent can forget to call, mis-call, or skip.
It runs as a Flow step (`@listen(scrape_web)`), always, with no model in the loop.

---

## Embedding conventions — the rule that must not drift

Both sides use `google/gemini-embedding-2` via OpenRouter at **768 dimensions**.

```
POST https://openrouter.ai/api/v1/embeddings
{ "model": "google/gemini-embedding-2", "input": [...], "dimensions": 768 }
```

`gemini-embedding-2` has **no `task_type` field** — Google removed it and moved
task signalling into the prompt text. So the asymmetry is a string convention,
and it must match exactly on both sides:

| Side | Prefix |
|---|---|
| Indexing | `Represent this document for retrieval: ` |
| Querying | `Represent this query for retrieving relevant documents: ` |

Define these as two module-level constants used by both the indexer and the
tool. Never inline them at two call sites. If they drift, nothing raises —
retrieval quality just quietly drops, which is the hardest class of bug to
notice in a system whose output is prose.

**Batching** is supported: pass a list to `input`. Do so — one call per chunk is
pure latency and overhead.

**Do not route this through CrewAI's embedder.** `chromadb` gates the
`dimensions` parameter behind a `"text-embedding-3"` substring check on the model
name, so `dimensions=768` would be silently dropped and 3072-dim vectors would be
sent to a 768-dim index. See `00-shared-config.md` §4.

---

## Chunking

`gemini-embedding-2` accepts 8,192 tokens, which is larger than most scraped
articles — but the ceiling is not the constraint that matters. Chunk to
**200–800 tokens** for retrieval precision, well before the limit binds.
Embedding a whole page as one vector produces a single blurry centroid that
matches everything weakly and nothing strongly.

Chunk on structural boundaries (headings, paragraphs) rather than a fixed
character count, and carry a small overlap so a fact spanning a boundary is not
lost.

### Required metadata on every upsert

| Field | Purpose |
|---|---|
| `text` | the chunk itself — returned to the agent |
| `url` | provenance; the Writer needs it for citations |
| `publisher` | provenance |
| `published_date` | **staleness gate input** |
| `indexed_at` | **staleness gate input** |
| `topic` | namespace-adjacent filtering |

`published_date` and `indexed_at` are not optional. Without them the staleness
gate below cannot work, and a cache silently turns month-old facts into
"current" ones — the single worst failure this architecture can produce, because
the brief will look perfectly well-sourced while being wrong.

---

## The tool — `retrieve_and_rerank`

One composite tool, one call per query, four steps inside:

1. Embed the query with the **query** prefix, `dimensions=768`.
2. Pinecone `query` for top-**20** candidates (`include_metadata=True`).
3. Cohere `rerank-v4.0-fast` over those 20 against the query.
4. Return the top-**5** reranked chunks with metadata.

Retrieving 20 and returning 5 is deliberate. The reranker needs candidates to
discriminate between, but the agent must not receive 20 chunks — every one it
receives becomes prompt tokens in every subsequent call of the run. This is the
same cost discipline as `FirecrawlSearchTool(config={"limit": 5})`, applied to
vector search.

### Shape

```python
class PineconeRetrieveRerankTool(BaseTool):
    name = "retrieve_and_rerank"
    description = "Search the indexed corpus for material on a topic."
    args_schema = ...        # query: str, top_k: int = 5
    env_vars = [EnvVar("PINECONE_API_KEY", required=True),
                EnvVar("OPENROUTER_API_KEY", required=True),
                EnvVar("COHERE_API_KEY",   required=True)]
```

Returns, per hit: `text`, `url`, `publisher`, `published_date`, `indexed_at`,
`rerank_score`. The agent needs the dates as much as the text — it is being asked
to judge freshness, not just relevance.

Install: `pinecone` (v9.1.0). **Not** `pinecone-client`, which is the deprecated
old package name.

---

## The staleness gate

This is the decision the `@router` makes, and it is deterministic — no LLM.

| Condition | Threshold |
|---|---|
| Minimum reranked hits | **≥ 3** |
| Minimum `rerank_score` on the top hit | **≥ 0.30** |
| Maximum age (`indexed_at`) | **≤ 60 days** |

All three must hold for `cache_hit`. Any failure routes to `cache_miss` and the
Researcher scrapes the live web.

**Why the threshold is on the rerank score, not the cosine score.** Measured on
this index, three documents against one query:

| | Pinecone cosine | Cohere rerank |
|---|---|---|
| best match | 0.8107 | 0.3717 |
| second | 0.7933 | 0.2184 |
| worst | 0.7532 | 0.0906 |

The cosine scores span 0.06 — there is no defensible cutoff inside that band,
because a good match and an irrelevant one differ by less than the noise. The
reranked scores span 0.28. **The reranker is not an optimisation here; it is what
makes the router's threshold implementable at all.**

Tune `0.30` against real data before trusting it. It is a starting point taken
from one measurement, not a constant.

---

## Write-back

After any successful scrape, the Flow chunks, embeds and upserts the new material
— always, automatically, whether or not the run needed it. That is what refills
the cache so the *next* run is cheaper.

Two honest caveats:

- **This only pays off if runs repeat.** Same topic across demo runs, adjacent
  topics across groups, or reuse over a semester. For a genuinely one-shot run on
  a novel topic, the cache hit rate is zero and the retrieve-first branch costs an
  embed, a Pinecone query and a rerank call every run for nothing. That overhead
  is small (~$0.00002 in embeddings plus one rerank unit) but it is not free.
- **Write-back must not be conditional on the brief being good.** Index what was
  scraped, not what was used. Otherwise the cache only ever contains material
  that already worked, which biases what future runs can find.

---

## ⚠️ Measured: write-back works, but its provenance metadata is empty

**Corrected 2026-08-29 after a real `crewai run`.** An earlier revision of this
section claimed the cache "cannot warm itself" — that one run writes 1 chunk
against a ≥3 threshold, so three runs would be needed before a hit. **That was
wrong**, and the error is worth recording because of how it was made: the figure
came from a synthetic fixture built as one structureless blob of repeated words.
`chunk_markdown` splits on markdown headings, and real research notes have four
(`## Verified findings`, `## Competing views`, `## Unverified / gaps`,
`## Sources consulted`). A fixture with no headings cannot split, so it measured
the chunker's fallback rather than its behaviour.

What a real run actually does:

| | |
|---|---|
| Chunks written by one `cache_miss` run | **3** |
| Router threshold | ≥ 3 hits |
| Next run's verdict | **`cache_hit`** — top rerank score **0.7877**, 0 days old |

So the cache **does** warm in a single run, and the retrieve → rerank → gate path
was verified end to end against real indexed material. Two caveats stand:

**1. Three chunks is exactly the threshold, not comfortably above it.** A thinner
research note, or one the Researcher writes with fewer headings, drops below and
silently reverts to a permanent `cache_miss`. There is no margin and nothing
reports its absence.

**2. `url` and `publisher` were empty on every chunk — this was the real
defect, and it is now fixed.** The description below is kept in the past tense
because the reasoning still explains why the current shape is what it is; the
correction is at the end of this item. `index_content` used to index the
Researcher's *notes* as one document, and notes have no single source URL, so
both metadata fields were written as `""`. Consequences, while that held:

- `_format_hits` renders `url: unknown` and `publisher: unknown` above passages
  whose body contains real URLs — actively misleading to the Analyst.
- `run_sources` (`07-deployment.md`) cannot be populated with per-source rows.
- The Writer's provenance rule has no structured field to cite from.

It is **not** fatal, which is worth stating precisely because the earlier revision
implied it was: the URLs survive inside the chunk *text* (13 distinct URLs
recoverable across the 3 passages), so a cache-hit brief can still produce a
Sources list and `check_mechanics` passes. The provenance is recoverable by
reading prose rather than by reading a field.

**The fix is unchanged, only its priority is lower than previously stated.**
Subscribe a `BaseEventListener` to tool-usage events, keep each
`firecrawl_web_scrape_tool` result with the URL that produced it, and index those
per page — several chunks each, with real `url` and `publisher`. That restores
structured provenance and puts comfortable margin above the ≥3 threshold. It is
the same listener `08-observability.md` needs for the per-agent cost split, so it
remains one piece of work serving two gaps.

> ⚠️ **Correction — both paths now do this. Verified 2026-08-29.** An earlier
> revision of this block said `main.py::index_content` had not been migrated and
> still indexed the notes. That is no longer true, and the sentence is corrected
> rather than deleted so the change is visible.
>
> `src/brief_crew/validator_cache.py` captures each tool envelope and indexes
> **one document per source URL** with real `url`, `publisher`, `branch`,
> `category` and `idea_hash`, refusing to index generated `ScopedIdea` /
> `Verdict` / `ValidationReport` objects.
>
> `main.py` now does the same for the Brief Crew: a capture sink keeps every
> `firecrawl_web_scrape_tool` result with the URL that produced it in
> `BriefState.scraped_sources`, and `index_content` calls
> `index_documents(documents=self.state.scraped_sources, ...)` — one document per
> page, each with a real `url` and `publisher`. A run that opened no page indexes
> nothing and says so, rather than inventing a source from the Researcher's
> prose. `_format_hits`'s `url: unknown` fallback survives, but only for a hit
> that genuinely carries no URL. `tests/test_brief_crew_regression.py` pins the
> scrape tool's name and its `result_schema`, which is what keeps the captured
> page body chunkable.

**Do not lower `MIN_RERANK_HITS` to 1.** The threshold is what stops a single
lucky chunk from certifying a topic as cached.

---

## ⚠️ The cache is shared mutable state

**State management** - the question of who owns shared, mutable state - and
**security & trust** are failure modes #5 and #4 in `workflow.md` §9. The
Pinecone index is where both land, and it is the only thing in this system that
outlives a run.

`Crew.memory=False` means CrewAI writes nothing durable. That makes this index
**the** shared mutable state of the project: written by a Flow step, read by
every subsequent run — and, in a shared deployment, by every other user.

**Nobody owns it.** No agent file states what state its agent may read or write.
The Researcher does not even write to it directly; `index_content` does, on its
behalf, unconditionally.

### The consequence of unconditional write-back

The write-back rule above is correct — *"index what was scraped, not what was
used"* — and it is also a trust decision with a cost. One wrong, stale, or
adversarial page is embedded and upserted, and from then on it is served to
future runs as a **`cache_hit`**: material the router has certified as relevant
and fresh, which the Writer will present with full confidence and a real URL.

Freshness is gated. **Trustworthiness is not.** A poisoned chunk is
indistinguishable from a good one at query time, and it is durable and
cross-tenant in a way a bad single run is not. This is the more serious of the
two security exposures in this design (the other is in `01-researcher.md`).

### Minimum viable containment

- **`source_run_id` on every upsert.** Without it a bad run is irrevocable; with
  it, deleting everything one run wrote is one filtered delete.
- **Namespace per user**, so one user cannot poison another's retrieval. Costs
  nothing and removes the blast radius entirely.
- **Do not write back from a failed run.** A run that scrapes, indexes, then
  fails currently leaves the cache mutated. `runs.status='failed'` records it;
  nothing compensates for it.
- **Decide who may purge**, and write it down. Right now the answer is nobody.

---

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Upserts rejected on dimension | 3072-dim vectors sent to a 768-dim index | `dimensions=768` dropped — check you are not routing through CrewAI's embedder |
| Retrieval quality quietly poor | Index and query prefixes drifted apart | Both must come from the same two constants |
| Brief cites stale facts as current | TTL too loose, or `indexed_at` missing on upsert | Tighten the gate; verify write-back metadata |
| Router never fires `cache_hit` | Threshold set on cosine rather than rerank score | Use the rerank score |
| Every run scrapes despite a warm index | Namespace mismatch between write and read | Same namespace both sides |
| Agent context bloated, costs high | Returning 20 candidates instead of 5 | Rerank then truncate, before returning |
