# Agentic Crew AI

**Draw a multi-agent workflow on a canvas, and it compiles to real CrewAI.** Not
a picture of one — agents, crews, human gates, routers, joins and cycles, parsed
into a typed document, structurally bounded, priced before a token is spent, and
turned into a `crewai.flow/v1` declaration that this service then runs, streams,
pauses at a gate and resumes after a restart. That is what the product now is.

Three things share one Python package.

**The flow builder** is the canvas — seven node kinds, two model tiers, a budget
meter that prices a graph before it runs, and a publish step that registers the
compiled flow as a first-class workflow the run API will launch. See
[The flow builder](#the-flow-builder).

**Validator Studio** takes a startup idea and returns a scored, cited verdict:
six agents, three of them researching in parallel against real sources, two
human approval gates that survive the process dying, and a browser console that
draws the agent graph and animates it as the run happens. It is **also a
template inside the builder** now — 16 nodes, 22 edges, two revise loops — rather
than a special case beside it. What the template carries is its *shape*; the
rubric, the confidence arithmetic, the guardrails and the warm cache are Python
and stay Python.

**Brief Crew** turns one topic into one one-page brief — a Researcher → Analyst →
Writer pipeline sitting behind a warm vector cache, so repeat runs get cheaper.

None of them is a demo of a framework. All three are built around a specific
claim: an agent's output is only worth what its evidence is worth, so the
interesting engineering is in the parts that refuse to let a model assert
something it cannot support.

---

## Status — read this before you judge anything

The service is **deployed and serving**, and CI is **green**. It has run end to
end against paid live services **exactly once**, on 2026-08-30, and that run
found three defects no test had caught. Those sentences are not in tension, and holding
all three is the single most important thing to know about this project: a
deployment that answers its health checks is not a deployment that has done the
work, a green pipeline measures the code against doubles rather than the product
against reality, and one paid run is evidence that the doubles are insufficient
rather than evidence that the product works.

**What that one paid run actually produced** (from the commit messages of
`aa7bdc1` and `add21d1`, which are the record): a validation report **truncated
at 4096 characters**, priced at **$0.00 over 128,069 real tokens**, with **two
of three research branches empty** because the Scoper was asking keyword APIs in
prose, scoring `NEEDS_WORK 4.2` at **0.17 confidence**. All three defects are
fixed — the un-truncated body, the priced calls, the keyword-shaped queries —
and **not one of them has been re-exercised against live tools.** So the
un-run thing is not "a paid run"; it is *a paid run that produces a result worth
reading*, and citation closure over an acceptance set is still unmeasured.

Until 2026-09-02 this README said nothing had ever run against paid services.
That was wrong from the moment `aa7bdc1` landed on 2026-08-30 - three days, in
the first section a newcomer reads, and `new features/feature-list.md` struck
the same claim the same day this one was found. The sentence understated what
had happened **and** overstated what is proven, which is the pair of errors a
status table exists to prevent.

The reason not to make the *next* paid run used to be the rubric. That reason is
gone — the rubric was ratified on 2026-09-01 — so what is left is nobody having
spent the money a second time. The flow builder does not change this: a published
graph runs end to end against the no-cost backend and has never been pointed at a
paid model at all.

| | State |
|---|---|
| Python test suite | ✅ 1228 tests, 0 failures, 0 errors, 1 skipped |
| Frontend unit tests | ✅ 1024 tests across 54 files (Vitest + jsdom) |
| Frontend end-to-end | ✅ 28 Playwright specs — real browser, real WebSocket, both durable gates, the builder canvas, and three node-card visual baselines, against a no-cost backend. Zero console errors tolerated. ⚠️ **The 28 is a listing** (`npx playwright test --list`, 2026-09-02); the green is `6d2743c`'s own measurement, and no browser was launched on 2026-09-02. Seven of the 28 are `@launch` and are free only against the local `SYNTHETIC=1` backend. |
| Frontend type-check + build | ✅ `vue-tsc -b --force` and `vite build` clean |
| Flow builder | ✅ a graph composes, validates, prices, publishes and **runs** — gates open on the author's own canvas node id, resume produces output, cancel reaches `CANCELLED`, and a published graph survives the restart auto-deploy guarantees. ⚠️ All of that was proved against the **no-cost** backend. Nothing in this README rests on a builder graph having called a paid model, and this pass did not establish that one ever has. |
| CI | ✅ green at `b4ef654`, both jobs, `ubuntu-latest` — clean checkout, no `.env`, no credential of any kind. Run `33597756398`. See [CI](#ci-and-the-clean-checkout). |
| Brief Crew, live | ✅ run end to end against real OpenRouter / Firecrawl / Pinecone / Cohere; numbers below are measured |
| Deployed | ✅ **live on Render** — API, console and PostgreSQL 18. See [Live deployment](#live-deployment), and note that nothing there was re-probed on 2026-09-02. |
| Validator Studio, live | ⚠️ **run once end to end, and the result was not usable.** One paid run (2026-08-30) produced a report truncated at 4096 chars, `cost_usd` $0.00 over 128,069 real tokens, two of three research branches empty, `NEEDS_WORK 4.2` at 0.17 confidence. All three defects fixed, **none re-exercised live**. The deployed console also recorded two runs that day (`e0b3b65e…` 04:01, `8b5a0a78…` 05:13) that **stopped at the scope gate** — one escalation-tier call each, well under a cent. Nothing in this repo records whether the completed paid run is one of those two or a third; `aa7bdc1` says its report existed only "on ephemeral container disk", which puts it on the deployed instance but does not identify it. Every automated test still uses a double. |
| Rubric | ✅ **ratified 2026-09-01** — seven changes applied, four of them rated *Critical*, and the adversarial review's standing "do not spend money on a live acceptance run" verdict lifted. The record is [`docs/rubric-ratification.md`](docs/rubric-ratification.md); read it **beside** [`docs/rubric-review.md`](docs/rubric-review.md), which was never updated when its own findings were repaired and therefore overstates what is broken. |
| PostgreSQL | ⚠️ the deployed API reports `"backend":"postgresql"` on `/readyz`, so the schema now exists on a real server. The automated suite still runs on SQLite only, and two-process gate contention remains untested. |
| Fan-out speedup | ❌ the benchmark harness is built and tested; **the measurement has not been taken** |

Every count above was **re-measured on 2026-09-02 at `b4ef654`** (the merge of
PR #6) on Windows, and the CI row was read from `gh run list`, not assumed. The
one exception is flagged in its own row: the E2E suite was *listed*, not run. The
commands are in [Tests](#tests) — and the command is the contract, not the
figure. These numbers have been published wrong here every time somebody
reconciled prose instead of re-running the command; the tally and the sequence
are owned by [`docs/gotchas-and-insights.md`](docs/gotchas-and-insights.md)
rather than restated here, for exactly that reason. If yours disagree, yours are
right.

The test suite is deliberately free to run. CrewAI crews, OpenRouter, Pinecone,
Cohere, Firecrawl, Hacker News and GitHub are all mocked or replaced with
deterministic doubles, so `git clone && npm ci && python -m unittest` costs
nothing and touches no network. The flip side is the row above: coverage is not
evidence that the live integration works.

Full, current, unflattering detail lives in [`CLAUDE.md`](CLAUDE.md) under
*Remaining Work and Unverified Risks*. It is maintained as a working handoff, not
as marketing, and it is the file to trust when this one and it disagree.

---

## The flow builder

> To open it: start the **free** backend with `SYNTHETIC=1 .venv/Scripts/serve`,
> run `npm run dev` in `frontend/`, and go to `http://localhost:5173/#/build`.
> Full steps in [As a service](#as-a-service-the-studio-and-the-builder).

`#/build` is a canvas. Drag nodes onto it, wire them, and what comes out is not
a diagram of a CrewAI flow — it is one.
[`src/brief_crew/builder/compiler.py`](src/brief_crew/builder/compiler.py) turns
a `builder.flow/v1` document into a `crewai.flow/v1` declaration made of real
`Agent`, `Task`, `Crew` and `Flow` objects, and
[`service/builder_runner.py`](src/brief_crew/service/builder_runner.py) runs it
through the same run registry, the same frame spine, the same durable gates and
the same WebSocket that Validator Studio uses. There is no second execution
path, and that is the point: a builder whose output runs somewhere else is a
diagram tool with extra steps.

**Seven node kinds, two model tiers.** `input`, `agent`, `crew`, `gate`,
`router`, `transform`, `output`; `cheap` and `escalation`, both resolved out of
[`config.py`](src/brief_crew/config.py), so an authored graph cannot name a model
the platform rules forbid. Gates are the native CrewAI `@human_feedback` ones —
a published graph pauses, writes its state to SQL, lets the process exit, and
resumes on a reply that arrives later. The gate opens on **the author's own
canvas node id**, carrying the label and editable fields they declared, rather
than on the compiler's generated `n1_confirm`; a builder whose runtime speaks a
different vocabulary from its editor is one an author cannot debug.

**A graph is priced before it runs.** The budget meter is live in the editor:
every edit re-prices the document, and `POST /api/builder/validate` returns the
same numbers the server will enforce. Two figures, because they answer different
questions — `static_cost_usd` is the worst case with the cycle allowance
inflated, `floor_cost_usd` the un-inflated one.

**Three layers refuse a graph, and they refuse different things.** Conflating
them is how a builder either blocks a legitimate shape or ships a money hole:

| Layer | Refuses | Where |
|---|---|---|
| Parse | a document that is not a document — bad ids, dangling edges, an `int` position written `120.5` | `builder/document.py` |
| Bounds | *shape*: at most 24 drawn nodes, 13 billable, 8 of those on the escalation tier, out-degree 4, 3 cycles | `builder/bounds.py`, constants in `config.py` |
| Budget | *money*: a worst case priced above `MAX_RUN_COST_USD` (default `$10.00`) | `builder/budget.py` |

The billable/escalation/cycle counts were raised (8→13, 5→8, 2→3) so the
evaluator template had headroom instead of sitting exactly on every bound.
Fan-out width deliberately **did not move**: it bounds concurrent threads and an
external rate limit nobody has re-measured, not spend, and widening it on
judgement alone would be inventing a number. The raise opened no money hole
because the counts never bounded money — the budget layer does, and it refuses
the worst shape the new counts permit *by price*: 13 billable / 8 escalation,
468 modelled calls, floor $15.31, **static $17.30**, and **$21.62 once the 1.25x
margin is applied to the static price** — against the $10.00 ceiling. (The
margin multiplies the static figure, not the floor; $15.31 x 1.25 would be
$19.14.) Regenerated 2026-09-02 at `b4ef654` by the command in
[`CLAUDE.md`](CLAUDE.md) section 14, which owns this figure — do not copy it,
run it. The same number is written beside the constant it justifies at
`config.py:1793`.

> This README published **$16.01** here until 2026-09-02, attributed to the
> change author and hedged as "not re-derived". It reproduces from no shape:
> probing `frontier_document(cheap, escalation)` at (3,5), (4,6), (5,8), (8,5)
> and (13,8) gives $10.55, $14.57, $21.62, $21.28 and $45.12, and $16.01 is not
> even the $15.31 floor. The hedge was honest about
> provenance and did not stop a wrong figure reaching the front page, which is
> the lesson: **a number handed down by a change author or a handoff is exactly
> as trustworthy as one copied between two documents.**

**Publish makes a graph a first-class workflow.** `register_builder_workflow`
writes it into five places at once — the graph descriptor map, the node registry,
the workflow map, the builder record, and the reserved-run-input-key table — and
`service/graph.py` says in its own docstring what each omission looks like,
because four of the five fail *silently* and differently. **A *publish* touches
six**, and the difference is scope rather than disagreement: the sixth is the
application's own runtime dict, which `service/builder_api.py::_register_runtime`
writes in the same request because `service/graph.py` holds no registry
instance. `config.py:1920` enumerates all six; count the function's writes and
you get five, count the request's and you get six. Afterwards
`GET /api/workflows`, `GET /api/workflows/{id}/graph` and
`POST /api/sessions/{id}/runs` all work on the author's graph exactly as they do
on `idea-validator`. `BUILDER_REHYDRATE_PUBLISHED` re-registers published graphs
at startup, which matters because auto-deploy restarts the API on every push to
`main`.

### The evaluator is a template now, not a special case

[`frontend/src/data/templates/ideaValidator.ts`](frontend/src/data/templates/ideaValidator.ts)
is the six-agent startup-idea evaluator expressed as a builder document: **16
nodes, 22 edges**, a `{score: all}` join, two revise loops closed through router
nodes. Recorded against a live `POST /api/builder/validate`: `valid: true`, zero
problems, `static_cost_usd $1.5137` / `floor_cost_usd $1.2159`, 8 billable nodes,
5 escalation, 2 cycles, `over_ceiling: false`. (Those budget figures are the ones
recorded in the template's own source comment and asserted by
`frontend/tests/builderShell.spec.ts`; they were **not** re-measured against a
running service for this README.)

Its gallery card carries a caveat rendered verbatim, and the caveat is the
honest half of the claim: **this is the evaluator's shape, not its judgement.**
The rubric anchors, the confidence arithmetic, the guardrails that bind a score
to counted evidence and the warm Pinecone cache are Python, they stay Python,
and a template that draws the same boxes does not inherit any of them.

### Two defects worth recording

Not a changelog — these are the two that say something about how this kind of
system fails.

**A graph naming `crew_id: "synthesis"` validated clean, published clean, was
priced, registered and launchable — and then raised a bare `TypeError` from
inside the crew factory at the moment that node ran.** The library factory's
whole body is a zero-argument call, and two of the six validator crews have no
zero-argument `__init__`: `SynthesisCrew` and `ReportCrew` take typed pydantic
findings from upstream nodes, which a drawn document has no way to express. So
every structural check passed — the check was that the crew *exists*, not that
it is constructible — and the failure landed at the one point where it costs the
most: after the scoper and all three research branches have billed for context
nothing would ever consume. `library_problems` now refuses it at validate, where
it costs nothing, and the refusal is closed at four doors including rehydration,
so a row published *before* the fix cannot return through a restart.
`tests/builder/test_crew_library_arity.py` imports the crew module for real and
asserts the declared map is exactly the required arguments of all six `__init__`s
— so adding a seventh crew fails a test rather than a run.

**A mirrored constant agreed with itself at the wrong number.** `PROBLEM_CODES`
in `frontend/src/types/builder.ts` listed 27 codes where the server emits 30 —
and the anti-rot test that was supposed to catch that read **two** of the
**three** Python files declaring them, so the mirror and its guard were wrong
together and confirmed each other. The code that fell through the gap,
`library-missing-prompt-input`, is the single most common problem in the whole
builder, because a fresh agent node defaults `prompt_inputs: {}`.

At head it is guarded from both sides: `PROBLEM_CODES` has **30** entries and
carries that code (counted from `builder.ts` on 2026-09-02),
`tests/builder/test_problem_code_declarations.py` reads all three sources
(`SOURCES = ("bounds.py", "budget.py", "compiler.py")`) and forbids the inline
string-literal spelling that a grep of the frontend's mirror cannot see. This is
the same failure this repository's *counts* keep having, one layer down: a
duplicate is only safe for as long as something can fail when it drifts.

---

## Live deployment

| | |
|---|---|
| Web console | **https://agentic-crew-ai-web.onrender.com** — `render.yaml` now declares this as `agentic-crew-ai-studio`, a Render **Node web service** in `singapore` rather than a static site, because Better Auth needs a Node runtime and a session cookie cannot be shared across two `onrender.com` subdomains. A rename does not move a Render subdomain, and **the live URL was not re-probed for this README** — treat the address above as the last one confirmed, not as today's. |
| API | **https://agentic-crew-ai-api.onrender.com** — Render web service, `python` runtime, `starter`, `singapore` |
| Database | `agentic-crew-ai-db` — Render PostgreSQL **18**, `basic_256mb`, `singapore`. Pre-existing; **reused, not recreated.** |
| Source | https://github.com/simonraj79/multi_agent_crewai_startup_advisor — public, `main`, auto-deploy on |

> ⚠️ **Everything in this section was measured on 2026-08-30 at `e539811` and
> was NOT re-probed on 2026-09-02.** `main` is `b4ef654` and auto-deploy is on
> for both services, so the deployment has almost certainly moved twice since —
> once for authentication, once for the flow builder. "Almost certainly" is
> doing real work in that sentence: nothing below was re-checked, and the service
> exposes no version endpoint to check it against. Re-probe before quoting one of
> these as current.

What was verified against the deployed origin, at `e539811`:

- `GET /healthz` returns `200`.
- `GET /readyz` returns `200` with `"storage": {"backend": "postgresql"}` — the
  service is talking to a real PostgreSQL 18 instance, not the SQLite fallback.
- `GET /api/workflows/idea-validator/graph` serves the full descriptor: **14
  nodes, 16 edges**, matching the graph the tests assert against.
- CORS behaves as configured — the API echoes
  `Access-Control-Allow-Origin` for the static site's origin and refuses a
  preflight from an unlisted one with `400`.
- `wss://agentic-crew-ai-api.onrender.com/ws` completes a `101` upgrade.
- The admission bounds are live, not just unit-tested: an oversized body is
  refused with `413` and a 2001-character idea with `422`.
- `GET /docs` returns `404` — `EXPOSE_API_DOCS` is unset on the paid instance.
- A **2-of-2 read-only Playwright smoke test** passes against the deployed web
  console (`--grep-invert @launch`, so nothing spent money).

**What was not verified in this probe: anything that costs money.** Nothing here
pressed *Launch* — that spends real OpenRouter, Firecrawl and Cohere credit.

That is narrower than "nothing ever has", which this section claimed until
2026-09-02 while the status table eighty lines above described three runs. The
deployed console recorded two on 2026-08-30 (`e0b3b65e…` 04:01, `8b5a0a78…`
05:13) that **stopped at the scope gate** — one escalation-tier call each, well
under a cent — and `aa7bdc1`'s completed paid run left its report "on ephemeral
container disk", which places it on the deployed instance without identifying
it. See the [status table](#status) row for what that run produced and why it
is not an acceptance. The deployment is live; the product is still unproven.

> ⚠️ The API runs on Render's free-adjacent `starter` plan behind a proxy that
> idles instances. A first request after a quiet period can take tens of seconds
> to answer while the service wakes.

---

## What is actually interesting here

[The flow builder](#the-flow-builder) is the headline and is covered above.
Four more things here are unusual enough to be worth your time even if you never
run any of it.

### A rubric bound to counted evidence

The validator scores an idea on five dimensions and computes a verdict
arithmetically:

```
score = 2 × (0.30·Demand + 0.20·Moat + 0.20·Competition + 0.15·Feasibility + 0.15·Headroom)
```

Any arithmetic the model supplies is **overwritten**, not trusted. But the real
work is a layer up. Each dimension has a written ladder of anchors, and two
independent guardrails police it:

- `anchor_problems` checks the *wording* — the text the model quotes must be the
  anchor for that dimension at that score, matched at 0.85 token overlap.
- `score_support_problems` checks the *findings* — the evidence actually counted
  from tool output must be able to carry the score claimed.

The second exists because the first is not enough. A model that has read the
rubric can quote the "strong demand" anchor verbatim over two stale forum
threads. Wording matching catches plagiarism of the rubric; evidence support
catches the claim. Scores are bounded from above everywhere, and from below only
at levels 0 and 1 — the two levels where a *low* score is itself a strong claim
that ought to need support. Judgement clauses are never mechanically enforced,
because pretending a judgement is a count is how you get confident nonsense.

### A router that makes the one real decision without a model

Brief Crew's cache hit-or-miss decision is the only genuinely dynamic branch in
the pipeline. It is a CrewAI `@router` returning a `Literal["cache_hit",
"cache_miss"]`, resolved from three thresholds — at least 3 reranked hits, top
rerank score at least 0.30, indexed within 60 days — for **zero LLM calls**. A
manager agent would make the identical binary decision and bill a model call per
run to do it.

Missing `indexed_at` is treated as stale, never as fresh. The validator's two
approval gates route the same way: deterministic approve/revise, no model asked.

### Human gates that survive the process dying

Both validator gates use CrewAI's native `@human_feedback`. When a run reaches
one it raises `HumanFeedbackPending`, the flow state is written to SQL, and the
process is free to exit. A reply arriving minutes or hours later — over HTTP or
over the WebSocket, through one shared compare-and-set path — rehydrates the flow
and resumes it. A duplicate reply gets HTTP 409 rather than a second run.

The gate payload is split into editable `fields` and read-only `derived` values,
and at the verdict gate *every* key is derived. Seven of them are arithmetic the
schema recomputes and discards; the rest are inputs the guardrails bind to the
rubric and to real tool URLs. Neither survives a text box. So `fields` is
**pruned** rather than annotated — a stale client cannot go on offering an edit
the server would silently throw away. The operator's lever is `decision=revise`
plus written feedback, which is the honest one.

### An event spine with a visible quarantine node

The UI is driven by an immutable, versioned frame stream with gapless per-run
sequence numbers, a bounded 2,000-frame run ring and 512-frame subscriber queues.
Serialization is field-bounded: it never walks a whole live CrewAI object.
Capture callbacks do no socket and no database I/O — frames enter a bounded queue
and a separate batching thread persists them, so database latency never reaches a
CrewAI event handler.

The part worth stealing: events that cannot be attributed to a known node are not
dropped and not silently folded into their neighbours. They are routed to a node
called `unattributed`, which is **rendered in the UI** — quiet when empty, loud
when it holds frames. An observability layer that hides its own blind spot is
worse than one that admits it, because you will believe it.

---

## What you need

| | |
|---|---|
| Python | 3.10–3.13 (**not 3.14** — CrewAI excludes it). `.python-version` pins 3.13. |
| Node | 20+ for the frontend (CI uses 24) |
| [uv](https://docs.astral.sh/uv/) | for the Python environment and the lockfile |

Those are floors, not pins. **Every exact version lives in
[`docs/tech-stack.md`](docs/tech-stack.md)**, beside the command that
regenerates it; do not read one out of prose here or anywhere else.

### API keys

Copy [`.env.example`](.env.example) to `.env` and fill it in. That file documents
the variables and names the source file that reads each one. (`SYNTHETIC` is not
in it — it is a per-invocation switch, not configuration; see
[Service configuration](#service-configuration) below.) The short version:

| Key | Needed for | Get one |
|---|---|---|
| `OPENROUTER_API_KEY` | **everything.** Every agent LLM call and every embedding. | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `FIRECRAWL_API_KEY` | web search + scrape: Brief Crew's Researcher, the validator's Market Analyst | [firecrawl.dev](https://www.firecrawl.dev/app/api-keys) |
| `PINECONE_API_KEY` + `PINECONE_INDEX_NAME` | the warm cache (Brief Crew Track B, validator market cache) | [app.pinecone.io](https://app.pinecone.io) |
| `COHERE_API_KEY` | stage-2 rerank on every retrieval | [dashboard.cohere.com](https://dashboard.cohere.com/api-keys) |
| `GITHUB_TOKEN` | **optional.** Raises the validator's GitHub search limit from 8 to 24 req/min. No scopes needed. | any GitHub PAT |

You create the Pinecone index yourself: **768 dimensions, cosine, serverless.**
The dimension is not negotiable — embeddings are truncated to 768 via the
`dimensions` parameter, and a mismatch fails upserts silently rather than
raising.

**OpenRouter is the only model provider.** There is no OpenAI fallback and
`OPENAI_API_KEY` is not used. Every model constant carries an `openrouter/`
prefix and the service refuses to start if one does not.

You can run the whole test suite with none of these set — and, with
`SYNTHETIC=1`, the whole application too, the flow builder included. See
[As a service](#as-a-service-the-studio-and-the-builder). That is checked by a
machine with no keys rather than asserted: CI runs from a clean checkout with no
`.env`, and did so green at `b4ef654`. See [CI](#ci-and-the-clean-checkout).

### Service configuration

Not secrets. These only matter when you run the hosted service.

| Variable | Default | What it does |
|---|---|---|
| `SYNTHETIC` | unset | `1` starts `serve` with **no-cost doubles** instead of the paid runners. `src/brief_crew/service/app.py::app_from_env`. |
| `CORS_ALLOW_ORIGINS` | *empty* | Comma-separated **origins** — scheme, host, optional port, no trailing slash — allowed to call `/api`. Empty means no cross-origin caller at all. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address. A container or PaaS needs `HOST=0.0.0.0`. |
| `DATABASE_URL` | *unset* | PostgreSQL when set; SQLite at `output/validator-studio.db` when not. |
| `RUN_CONCURRENCY` | `1` | Concurrent runs; the rest queue. One run is the memory ceiling on a 512 MB instance. |
| `RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS` | `5.0` | How long a resubmission waits for a still-settling run future before refusing the caller. |
| `MAX_QUEUED_RUNS` | `8` | Runs queued or executing, across every caller, above which a **new** run gets `429`. The keyless cost bound. |
| `RUN_RATE_LIMIT_MAX_RUNS` | `10` | Per-client run-creation burst. **`0` disables the limiter** — the intended escape hatch for load testing. |
| `RUN_RATE_LIMIT_WINDOW_SECONDS` | `60.0` | The window that burst refills over. |
| `RUN_RATE_LIMIT_TRUST_FORWARDED_FOR` | `true` | Key the limiter on the leftmost `X-Forwarded-For` entry. **Turn it off** where the service is reachable directly and the socket peer is the real client. |
| `EXPOSE_API_DOCS` | `false` | Serve `/docs`, `/redoc` and `/openapi.json`. Off by default on a paid app; **forced on** for a synthetic one. |
| `PINECONE_INDEX_NAME` | *unset* | Named above under [API keys](#api-keys); it is read in `config.py` like the rest of this table. |
| `VALIDATOR_FEASIBILITY_CACHE_ENABLED` | `false` | Opt the feasibility branch into the warm cache as a GitHub rate-limit shock absorber. |
| `VALIDATOR_SEQUENTIAL_BRANCHES` | `false` | Withdraw the three-way fan-out to one-at-a-time without a code edit. Parallel stays the shipped default. |
| `MAX_RUN_COST_USD` | `10.0` | Estimated per-run spend ceiling, enforced at the next CrewAI step boundary. **`0` disables it; unset does not** — a deployment that does nothing still gets a brake. It enforces an estimate, not an invoice, and it is blind to embeddings, rerank and Firecrawl. |
| `BUILDER_REHYDRATE_PUBLISHED` | `true` | Re-register published builder graphs at startup, so one survives the restart auto-deploy causes on every push. |
| `BUILDER_ALLOW_GATELESS_GRAPHS` | `false` | Permit an **anonymous** caller to **launch** a published graph that reaches a billable node before any human gate; otherwise `403`. It does **not** govern publishing — publishing such a graph is always allowed. Read at exactly one site, `service/app.py` inside `create_run` (`not (user or BUILDER_ALLOW_GATELESS_GRAPHS)`), so wherever auth is on — which `render.yaml` turns on — `user` is truthy and the flag is inert. Off, because while nobody is signed in, human inaction is the de facto spend cap. |

**This table is a curated subset, not the list.** The canonical inventory — and
the multiline scan that regenerates it, which is the only method that has ever
produced a right answer here — lives in
[`docs/tech-stack.md`](docs/tech-stack.md). Do not count the rows above and
publish the number. Every figure this repository has published for it but the
current one has been wrong; [`docs/tech-stack.md`](docs/tech-stack.md) §6 keeps
the tally, and it is the only file that should.

Everything above is read at **import time** in
[`src/brief_crew/config.py`](src/brief_crew/config.py) — except `SYNTHETIC`,
`HOST`, `PORT` and `DATABASE_URL`, which
`src/brief_crew/service/app.py` reads. A malformed value for any of the numeric
ones **stops startup** rather than being silently coerced.

**The rest of the admission-control settings are constants, not knobs.** They
are deliberately not environment-tunable, so changing one is a code edit and a
commit rather than a dashboard field nobody remembers setting:

| Constant | Value | What it bounds |
|---|---|---|
| `MAX_REQUEST_BODY_BYTES` | 64 KiB | The declared `Content-Length` of any HTTP request. Matches `WS_MAX_MESSAGE_BYTES`, so both transports agree on "too big". |
| `MAX_RUN_INPUT_CHARS` | 2000 | One run input — `inputs.idea` or `inputs.topic`. This is the token-amplification bound. |
| `MAX_RUN_INPUT_KEYS` / `MAX_RUN_INPUT_BYTES` | 16 / 8 KiB | The shape of the whole `inputs` mapping, which is typed `dict[str, Any]`. |
| `RUN_ADMISSION_RETRY_AFTER_SECONDS` | 30 | The `Retry-After` on a capacity refusal — a fixed hint, deliberately not a live queue-depth estimate. |
| `RUN_RATE_LIMIT_MAX_CLIENTS` / `RUN_RATE_LIMIT_KEY_MAX_CHARS` | 4096 / 64 | The limiter's own memory, since its map is keyed by attacker-supplied text. |

`CORS_ALLOW_ORIGINS` is invisible locally — Vite proxies `/api` and `/ws` to the
API, so every request is same-origin and no CORS header is ever involved. It is
load-bearing in production, where the Vue app is a **separate** static site and
the browser discards every response the API does not opt into by name. The empty
default is deliberate: a new deployment fails closed and the operator names the
frontend origin on purpose, rather than the service shipping `*` and nobody ever
revisiting it. A malformed value **stops startup** and the error names the
corrected string — a trailing slash is the common way to get this wrong, because
a browser never sends one in an `Origin` header, so it would match nothing and
fail as though the middleware were missing.

It does **not** govern `/ws`. Browsers do not apply CORS to a WebSocket
handshake, and Starlette's middleware passes non-HTTP scopes straight through, so
any page can open the socket. What it cannot do is guess the uuid4 `run_id` and
the `session_id` the socket demands before it sends a frame.

---

## Install

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv -e .

# The hosted service (FastAPI, SQLAlchemy, psycopg) is an optional extra:
uv pip install --python .venv -e '.[service]'
```

> ⚠️ `crewai install` runs `uv sync`, which **uninstalls** anything absent from
> `pyproject.toml`'s default dependencies — including the whole `service` extra.
> If the API stops importing after you run it, that is why. Reinstall the extra.

> ⚠️ **`.venv` has no `pip` and no `pytest`.** `uv venv` does not seed pip, so
> `python -m pip ...` fails with `No module named pip` — read versions from
> `importlib.metadata` instead. `[tool.pytest.ini_options]` in `pyproject.toml`
> is inert; the suite is `unittest`, and so is CI.

Exact versions of everything installed, and the commands that regenerate them,
are in [`docs/tech-stack.md`](docs/tech-stack.md).

---

## Running Brief Crew

Two tracks over the same three agents.

|  | **Track A** — `run_crew()` | **Track B** — `kickoff()` |
|---|---|---|
| Orchestration | `Process.sequential` | `Flow` with a deterministic `@router` |
| Who checks the cache | the Researcher, as a tool | the Flow, *before* any agent runs |
| Researcher tools | 3 | 2 |
| Needs | API keys only | + Pinecone, Cohere |

**Start with Track A.** Everything else presupposes a working sequential crew.

```bash
.venv/Scripts/python -c "from brief_crew.main import run_crew; run_crew('your topic')"   # Track A
.venv/Scripts/python -c "from brief_crew.main import kickoff;  kickoff('your topic')"    # Track B
```

The brief lands in `output/brief.md`; Track B also writes `output/last_run.json`.

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

> ⚠️ **Known gap.** Cache write-back carries no structured provenance. The cache
> genuinely warms — one miss writes chunks, the next run hits — but every chunk
> is stored with `url=""` and `publisher=""`, because the Flow indexes the
> Researcher's *notes* rather than the scraped *pages*. Briefs are unaffected
> (the URLs survive inside the chunk text) but per-source provenance cannot be
> reconstructed. Detail in [`agents/06-retrieval-layer.md`](agents/06-retrieval-layer.md).

---

## Running Validator Studio

Six agents. Two of them — Scoper and Synthesist — and the Reporter have **no
tools at all**; that boundary is deliberate, and it is what keeps judgement
separate from retrieval.

| Agent | Model tier | Tools |
|---|---|---|
| Scoper | escalation | none |
| Market Analyst | cheap | Firecrawl search + scrape |
| Sentiment Analyst | cheap | Hacker News (Algolia) |
| Feasibility Analyst | cheap | GitHub repository search |
| Synthesist | escalation | none |
| Reporter | escalation | none |

```
scope ─▶ scope gate ─┬─▶ market      ─┐
                     ├─▶ sentiment   ─┼─▶ synthesis ─▶ verdict gate ─▶ report
                     └─▶ feasibility ─┘                                  │
                                                                         ▼
                                                            output/validation.md
```

The three research branches are sibling `@listen` methods on one event, so CrewAI
runs them concurrently in worker threads, with an `and_()` fan-in before
synthesis.

### From the command line

```bash
.venv/Scripts/validate --idea "A scheduling assistant for clinics"
```

This stops at both human gates and waits for you. To skip them:

```bash
.venv/Scripts/validate --idea "A scheduling assistant for clinics" --no-gates
```

> ⚠️ `--no-gates` skips the *approvals*, not the *spending*. A real `--no-gates`
> run still calls paid models and external tools.

### As a service: the studio and the builder

Two processes. **Start the API in synthetic mode** — this is the way to try the
app, and the only way to try it without spending anything:

```bash
SYNTHETIC=1 .venv/Scripts/serve     # http://127.0.0.1:8000, spends nothing
```

Then the frontend:

```bash
cd frontend
npm install
npm run dev                         # http://localhost:5173
```

The dev server proxies `/api` and `/ws` to `127.0.0.1:8000`, so no configuration
is needed locally. (`/api/auth` is proxied separately to a Node server on
`:3000` and is declared **before** `/api`, because Vite matches in declaration
order and `/api` is a prefix of `/api/auth`. You only need that process if you
are working on sign-in.)

| Open | For |
|---|---|
| `http://localhost:5173/` | the studio — launch a run, watch the graph, answer both gates |
| `http://localhost:5173/#/build` | **the flow builder** — the template gallery, then the canvas |
| `http://localhost:5173/#/build/ug_xxxxxxxx` | one saved graph, deep-linked; this is the URL an author shares |

Routing is a **108-line** hash router of this repo's own, not `vue-router`
(`wc -l frontend/src/composables/useWorkspaceRoute.ts`, 2026-09-02 at
`b4ef654`; the spec budgeted 60 at `docs/flow-builder-spec.md` R13, and the gap
between the budget and what shipped is the more interesting of the two
numbers). The reason is deployment:
the SPA is served by a Node process, history mode needs a catch-all rewrite in
two places, and everything after `#` never leaves the browser — so a deep link
cannot 404 on a server that was never told about it.

**Start in the builder with a template.** `Blank` is a legitimate starting point
and a bad first impression; the gallery's three worked graphs — minimal gated
agent, fan-out with a join, and the full idea-validator — each open as an
editable document you can price, break and re-price.

> ⚠️ **`serve` without `SYNTHETIC=1` is the paid service.** It builds the real
> crew runners, so the first time anyone presses *Launch* — to look at the graph,
> to check the UI renders, to see what the thing does — it calls OpenRouter,
> Firecrawl, Hacker News and GitHub for real and bills you. Nothing in the UI
> distinguishes the two modes. `SYNTHETIC=1` selects the same no-cost doubles the
> integration tests use: real frames, real WebSocket, both durable gates, no
> spend and no API keys required.
>
> Use the paid mode when you actually mean to validate an idea.

**If no backend answers, the UI falls back to a scripted mock and shows a
complete, entirely fabricated run.** This is deliberate — it makes the UI
developable and testable without a backend — but it means a misconfigured
deployment fails by showing you plausible fiction rather than an error. The
single most common cause is `VITE_API_URL` set to a bare hostname instead of a
full origin; see [`docs/deploying.md`](docs/deploying.md).

### The API

```
GET  /healthz
GET  /readyz
GET  /api/workflows
GET  /api/workflows/{workflow_id}/graph
POST /api/sessions/{session_id}/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/frames
POST /api/runs/{run_id}/gates/{gate_id}
POST /api/runs/{run_id}/cancel
GET  /api/runs/{run_id}/logs?format=ndjson|zip
WS   /ws?session_id=&run_id=&after=
```

And the builder's own surface, all under `/api/builder`:

```
GET    /api/builder/vocabulary               node kinds, tiers, tools, bounds
GET    /api/builder/workflows                the caller's graphs
POST   /api/builder/workflows                create one
GET    /api/builder/workflows/{document_id}
PUT    /api/builder/workflows/{document_id}  save, expected_version compare-and-set
DELETE /api/builder/workflows/{document_id}  unregisters first, then deletes
POST   /api/builder/validate                 problems + budget for an unsaved document
POST   /api/builder/workflows/{document_id}/publish
```

`PUT` answers **409** on a version mismatch rather than overwriting — two tabs
editing one graph is the ordinary case, not the exotic one. `DELETE`
unregisters before it deletes, deliberately: the window where a graph is stored
but unlaunchable is survivable, and the reverse — a run compiling against a
document nobody can read — is not. Once `publish` has registered a graph, its
document id **is** a `workflow_id`, so the run endpoints above take it with no
special casing.

Run state, frames and gates persist to SQL — SQLite at
`output/validator-studio.db` by default, PostgreSQL when `DATABASE_URL` is set.
Cancellation is cooperative and lands at the next CrewAI step boundary.

`/docs`, `/redoc` and `/openapi.json` return **404 unless `EXPOSE_API_DOCS=1`**
(or the app is synthetic). That is obscurity, not a control — the endpoints are
unchanged and a reader can still find them.

### What the run endpoint refuses

`POST /api/sessions/{session_id}/runs` is the only endpoint that spends money.

**Whether it is authenticated depends on one variable, and the default is not
`False`.** `VALIDATOR_REQUIRE_AUTH` defaults to `bool(AUTH_BASE_URL)`, so
configuring an auth server *is* turning auth on and the half-configured state
does not exist — a flat `False` default would fail open, serving every paid
endpoint anonymously with nothing on screen to say so. `render.yaml` sets
`AUTH_BASE_URL`, so the deployed API demands a verified identity; a local
`SYNTHETIC=1` service sets neither and is open, which is what makes it
convenient and also what makes it worth nothing.

The bounds below run in **both** cases. They were written when the endpoint was
an open demo and they are still the layer that holds if a signed-in caller
misbehaves — chosen to be invisible to one honest visitor pressing *Launch* and
expensive for a script:

| Condition | Status | Response |
|---|---|---|
| Body larger than 64 KiB | **413** | `the request body is limited to 65536 bytes` — refused by ASGI middleware on the declared `Content-Length`, before FastAPI or pydantic parses anything |
| Over the per-client rate limit | **429** | `too many runs from this client; wait and try again`, plus a computed `Retry-After` |
| Server at the admission cap | **429** | `the service is at capacity; try again shortly`, plus `Retry-After: 30` |
| `inputs.idea` / `inputs.topic` over 2000 chars | **422** | `inputs.idea is limited to 2000 characters; this one is N` |
| `inputs` over 8 KiB of JSON, or over 16 keys | **422** | a pydantic value error naming the bound |
| Unknown `workflow_id` | **404** | `workflow not found` |

Two carve-outs are deliberate and tested:

- **A run waiting at a gate holds no admission slot.** It has already returned
  its worker thread, so a human thinking about a scope does not consume capacity
  from anyone else.
- **A gate reply is never refused for capacity.** It belongs to a run the caller
  already holds, and refusing one would strand a human mid-run. A flood must not
  be able to do that.

The rate limit runs *first*, ahead of the workflow and input checks, so a flood
of deliberately malformed bodies is throttled too. It is the only endpoint
limited at all — `/healthz`, `/readyz` and every read-only `GET` are left alone,
so monitoring and a reconnecting UI are never affected.

> ⚠️ **The rate limit is a courtesy limiter, not a security control**, and
> `config.py` says so at length. It is an in-process token bucket in one
> instance: it resets on every deploy and it multiplies by the instance count if
> the service is ever scaled out. Its key is `user:<id>` when a caller is
> authenticated and the client address otherwise — and an address is a poor
> proxy for a person in both directions, since behind Render's proxy a shared
> `X-Forwarded-For` puts strangers in one bucket while a phone changing network
> gets a fresh allowance. Anonymously, anyone willing to rotate a header walks
> past it. The layer that holds against someone actually trying is
> `MAX_QUEUED_RUNS`, because that one is keyless and cannot be rotated around.

Covered by `tests/service/test_run_admission.py` — 37 tests, including the two
carve-outs, thread-safety of the bucket, and that hiding the docs does not hide
the API.

---

## Tests

```bash
.venv/Scripts/python -m unittest discover -s tests -t .    # 1228 tests, 1 skipped

cd frontend
npm run build                                              # vue-tsc -b && vite build
npm test                                                   # 1024 tests over 54 files
```

All three are free to run and touch no network. Measured 2026-09-02 at
`b4ef654`; **the command is the contract, not the figure.**

398 of the Python tests are the builder's, and they are worth running alone when
you touch it:

```bash
.venv/Scripts/python -m unittest discover -s tests/builder -t .   # 310
.venv/Scripts/python -m unittest tests.service.test_builder_gates tests.service.test_builder_runner tests.service.test_builder_rehydration tests.service.test_builder_validate_and_history   # 34 + 17 + 19 + 18
```

### End to end, in a real browser

28 Playwright specs across four files — 15 for the builder, 3 for builder
layout, 7 for the studio's operator journey (launch, both durable gate round
trips over a real WebSocket, the verdict gate's read-only fields, reload
recovery), and 3 node-card visual baselines — all against a real FastAPI
service. Start the **free** backend first:

```bash
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099 .venv/Scripts/serve

cd frontend
npx playwright install chromium     # once
npm run test:e2e                    # 28 tests
```

> ⚠️ **`SYNTHETIC_BRANCH_DELAY_SECONDS=5` is not optional**, and leaving it out
> fails in a way that reads like something else entirely. (It is read in
> `service/runner.py`, not `config.py`, so the knob scan in
> [`docs/tech-stack.md`](docs/tech-stack.md) does not list it.) The three
> `e2e/visual/run-canvas.spec.ts` specs screenshot a branch *while it is
> running*; the synthetic runner finishes a branch instantly, so there is no
> running moment to capture and they fail with `No branch stayed in flight`.
> That reads exactly like a CSS regression in the node card. It is not one.

Two of the layout specs exist because of defects found by *looking* rather than
by testing. On an empty gallery neither rail renders, but the shell still
declared three columns — so the gallery landed in the palette's narrow slot
inside a zero-height row. And the canvas fitted its viewport *before* the budget
meter and problems dock took their height, so a 16-node template opened with its
last two nodes under the dock **while reporting itself fitted**. (The pixel
figures behind both — a 236px-wide box holding 1356px of content, a fit of 0.544
against a settled container wanting 0.466 — are the finding agent's measurements
and were **not** re-derived for this README.) Both were invisible to a
four-figure green unit suite, because a jsdom mount asserts structure and never
asks how wide anything ended up. `e2e/builder-layout.spec.ts` — the three layout
specs — asserts both in a real browser, which is the only place either question
has an answer.

The suite starts its own Vite server (`frontend/e2e/vite.e2e.config.ts`) pointed
at port 8099, so `vite.config.ts` — which proxies to the *paid* service on 8000 —
is never used and the suite cannot launch a paid run.

The same specs run against a deployed origin:

```bash
E2E_BASE_URL=https://agentic-crew-ai-web.onrender.com \
  npx playwright test --grep-invert @launch
```

> ⚠️ **`--grep-invert @launch` is not optional against production.** Seven of
> the 28 tests press Launch and are tagged `@launch`; a deployed API is backed
> by paid runners, so without that flag every smoke test spends real money on a
> full six-agent run. What that flag leaves is **21** — measured with
> `npx playwright test --list --grep-invert @launch` — the read-only half:
> topology, the builder canvas, and that the page reached the live backend
> rather than falling through to its mock.

### CI and the clean checkout

GitHub Actions runs the Python suite and the frontend build/unit tests on
`ubuntu-latest`. Both jobs pass at `b4ef654` — verified for this README with
`gh run list`, run `33597756398`, rather than assumed. The **first** green run
in this repository's history was `e539811`; the three commits before that one
failed, and it is worth being precise about why, because the cause was not a
broken test.

No `.env` is ever committed, so CI starts from a genuinely clean checkout. But
`brief_crew/__init__.py` calls `load_dotenv(..., override=True)` at import time,
and around 40 tests *construct* real `LLM` and Firecrawl objects in order to
assert their wiring — which model a crew was given, which tools an agent carries,
that the Reporter has none. Nothing ever *calls* those objects, but both
constructors demand a key and refuse to build without one. On a machine with a
real `.env` the suite passed; on CI it collapsed at object construction in ~5s
with 4 failures and 36 errors.

The fix is `tests/__init__.py`, which runs before anything imports `brief_crew`
and `setdefault`s two obviously-fake placeholders. Three rules govern it, and
they are written out in the module docstring: `setdefault` and never assignment,
so a developer's real keys still win; a value that could not be mistaken for a
credential in a traceback or a screenshot; and only the variables an actual
failure demands, so it does not become a mirror of `.env.example` masking real
assertions.

The practical consequence is worth stating on its own: **`git clone && uv pip
install -e . && python -m unittest` now passes with no keys and no `.env` at
all.**

The Playwright suite is **not** in CI — that job would need the `SYNTHETIC=1`
backend started alongside it, the `SYNTHETIC_BRANCH_DELAY_SECONDS` above, and a
browser download.

> ⚠️ **If you add a test directory, add its `__init__.py` in the same commit.**
> This suite reported 65 passing tests for a long time and that number was a lie:
> `tests/events/` and `tests/service/` had no `__init__.py`, so `unittest
> discover` walked straight past the entire event spine and service layer and
> printed a green `OK`. Discovery does not warn you. (`pyproject.toml` configures
> pytest, which collects by rootdir and would have caught it — but pytest is not
> in the default dependency set.)

Test counts move. The command is the contract, not the figure.

---

## What it costs

### Brief Crew — measured, one run each, cold cache

| | Track A | Track B (`cache_miss`) |
|---|---|---|
| LLM calls | 9 | 13 |
| Prompt tokens | 178,711 | 109,104 |
| Completion tokens | 13,614 | 30,085 |
| Wall time | ~7 min | ~7 min |
| Cost | $0.017 – $0.185 | ≤ $0.1946 (upper bound) |

The ranges are wide for an honest reason: crew-level token usage is not split by
model, so the upper bound prices every call at the escalation tier. Track B's
four extra calls are the cache round-trip — overhead paid on every miss and
repaid only by a later hit.

**72% of Track A's completion tokens were reasoning tokens** (9,757 of 13,614),
billed at the completion rate. That is the largest untaken cost lever in the
project.

### The architecture only pays for itself if runs repeat

A cache **miss** costs *more* than the plain crew, not less — it does everything
the crew does plus retrieve, rerank, embed and upsert. A cache **hit** skips
search and scrape entirely and is markedly cheaper. The first run on any topic is
always the expensive one. That is the design working, not failing.

### Validator Studio

**Run once, priced never.** It has been run end to end against live services
exactly once (2026-08-30), and that run reported `cost_usd` **$0.00 over 128,069
real tokens** — a defect, since fixed, in which an unpriced model slug turned
"no price on file" into "this call was free". So a paid run exists and a
measured dollar figure does not, and the two facts are easy to confuse.

Structurally it is one escalation-tier scope, three cheap-tier research branches
with real tool calls, then two escalation-tier passes — expect it to cost more
than a Brief Crew run. Do not quote a number until someone has taken a run with
the pricing repair in place. Note also that every figure the product itself
reports is tokens x a local price table; OpenRouter's own per-generation cost
never reaches the process.

### A per-run ceiling now exists, and it enforces an estimate

`MAX_RUN_COST_USD` (default `$10.00`) stops a run at the next CrewAI step
boundary once its accumulated estimate crosses the line, and the builder's budget
layer refuses to publish a graph whose worst case prices above it. Three things
it does **not** do, each structural rather than a tuning problem, and each
written out at `config.py` where it is defined:

1. **It enforces an estimate, not an invoice.** CrewAI never asks OpenRouter for
   its per-generation cost, so every figure is recomputed from a local price
   table. Cached-prompt discounts, BYOK fees and any price change made after that
   table was written move the billed number away from the enforced one, in either
   direction.
2. **It cannot stop a call already in flight.** The total only moves when a call
   *completes*. Expect to overshoot by roughly one escalation call.
3. **It is blind to everything that is not an LLM call.** Embeddings, Cohere
   rerank and Firecrawl never raise the event it reads, so the enforced total is
   always a *lower* bound on true spend.

`0` disables it; **unset does not** — a deployment that does nothing still gets a
brake, and turning it off takes a deliberate `MAX_RUN_COST_USD=0`.

### Hosting

About **$13.30/month** fixed on Render — `$6.30` Postgres `basic_256mb` with 1 GB,
`$7.00` for the API on `starter`, `$0` for the console. Model tokens, Firecrawl
calls and Cohere rerank units are on top.

The console's `$0` now costs something other than money: it is a Node web
service on `plan: free`, and a free Render service spins down after inactivity —
so the first visitor of the day waits out a cold start **on the sign-in page**,
which is the worst place in the app to put a 30-second pause. `render.yaml` says
so where it sets the plan. Moving it to `starter` is a one-word change and about
`$7.00`.

---

## Deploying

It is deployed. See [Live deployment](#live-deployment) for the URLs and for
exactly what was and was not verified there.

`render.yaml` is a complete Render Blueprint for the API, the console and a
PostgreSQL 18 database, and it remains the readable description of the target
shape. The console is declared as a **Node web service**, not a static site: it
serves the SPA *and* mounts Better Auth, because `onrender.com` is on the Public
Suffix List and a browser will not set a cookie two subdomains can share. Serving
both from one origin is what makes an ordinary httpOnly session cookie work at
all. **The live services were not created from it** — they were created
directly against the Render API, against the same GitHub repository, and the
pre-existing `agentic-crew-ai-db` was reused rather than redefined.
[`agents/07-deployment.md`](agents/07-deployment.md) records what is actually
running and where the manifest and the reality differ.

There are two ways to get this wrong that fail *silently* rather than loudly, and
both are covered step by step in **[`docs/deploying.md`](docs/deploying.md)**.
Read it before you touch the deployment.

---

## Layout

```
src/brief_crew/
├── config.py                  models · prices · thresholds · rubric anchors · builder bounds
├── embeddings.py              OpenRouter embeddings, called directly
├── indexing.py                chunk / embed / upsert
├── guardrails.py              Brief Crew's evaluator gate
├── main.py                    run_crew() = Track A · kickoff() = Track B
├── validator_flow.py          the six-agent flow, gates, routers, fan-out
├── validator_guardrails.py    scope, URL closure, evidence counts, rubric binding
├── validator_cache.py         validator cache policy and namespacing
├── schemas/validator.py       Evidence · Verdict · ValidationReport · …
├── crews/                     @CrewBase wiring + agents.yaml / tasks.yaml
├── tools/                     Firecrawl · Hacker News · GitHub · Pinecone
├── events/                    the frame spine, registry and serializer
├── builder/                   the authored-graph half
│   ├── document.py                builder.flow/v1 — parse, types, 7 node kinds
│   ├── bounds.py                  structural refusals: counts, fan-out, cycles
│   ├── budget.py                  static / floor price, and the ceiling check
│   ├── compiler.py                → crewai.flow/v1: Agent · Task · Crew · Flow
│   ├── runtime.py                 node entrypoints, checkpoints, cancellation
│   ├── gates.py                   author's node id ⇄ compiled gate
│   ├── descriptor.py              the graph descriptor the console draws
│   └── store.py                   documents, versions, compare-and-set saves
└── service/                   FastAPI, WebSocket, SQL persistence, run registry
    ├── builder_api.py             /api/builder/* — list, save, validate, publish
    ├── builder_runner.py          what a published graph actually runs with
    └── builder_rehydrate.py       re-register published graphs after a restart

frontend/                      Vue 3 + TypeScript + Vite + Vue Flow
├── src/components/builder/        33 components — palette, canvas, inspector,
│                                  budget meter, problems dock, minimap, gallery
├── src/composables/useBuilder*.ts document · canvas · validation · problems ·
│                                  persistence · clipboard · hotkeys
├── src/data/templates/            the evaluator as a BuilderDocument
├── tests/                     1024 Vitest specs over 54 files
└── e2e/                       28 Playwright specs over 4 files
agents/                        the authoritative specifications
tests/                         1228 tests, all free to run
└── builder/                       310 of them, on the builder alone
docs/                          the spec, deployment, gotchas, licensing
```

Counts measured 2026-09-02 at `b4ef654`. **The builder added zero npm
dependencies** — verified, not asserted: `git diff 6d2743c~1 6d2743c --
frontend/package.json frontend/package-lock.json` is empty. The minimap and the
hash router are hand-rolled, each for a reason written at its own source.

**Prompts are data, wiring is code, and constants are neither duplicated nor
inlined.** `agents.yaml` and `tasks.yaml` hold every word an agent reads;
`config.py` holds every model name, price, embedding prefix and threshold, exactly
once. If you find a model name or a threshold inlined in Python, that is a bug.

---

## Three things to know before changing anything

**1. `Task.context` is three-valued.** Unset means *inherit every prior output*;
an explicit list means *exactly these*; an empty list means *nothing at all*.
CrewAI models this with a `_NotSpecified` sentinel rather than `None`. Trimming
`writing_task`'s context to `[analysis_task]` looks like tidying and silently
strips every source URL, because the Analyst compresses them away.

**2. An agent's tool list and its task description must change together.** Track
A's task tells the Researcher to call the retrieval tool first; Track B's does
not, because the Flow already retrieved and already failed the staleness gate. An
agent told to call a tool it does not have **will invent the result** — that is
the direct cause of fabricated citations. Both are selected from one `track`
argument so they cannot be mismatched.

**3. Do not route embeddings through CrewAI.** ChromaDB forwards the `dimensions`
parameter only when the model name contains `"text-embedding-3"`. The model used
here fails that test, so `dimensions=768` is dropped silently and 3072-dim vectors
are sent to a 768-dim index — no error, just failed upserts a long way from the
cause. Call `brief_crew.embeddings` directly, and keep `DOC_PREFIX` and
`QUERY_PREFIX` paired.

---

## Documentation

| File | What it is |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **The honest handoff.** What is implemented, what is not, and what is unverified. Read it before believing anything else. |
| [`agents/`](agents/) | The authoritative specifications. Where code and spec disagree, the spec is right and the code is a bug. |
| [`AGENTS.md`](AGENTS.md) | CrewAI reference for anyone — human or coding agent — changing crew code. |
| [`PRD.md`](PRD.md) | The requirements document that extends `agents/` into Validator Studio. |
| [`docs/flow-builder-spec.md`](docs/flow-builder-spec.md) | **The contract the flow builder was built against.** Fifteen numbered rulings on the questions the design judges disagreed about — ride Vue Flow or own the pointer layer, snapshot ring or command algebra, whether the client mirrors a server bound — each with the one-line reason. Where reality contradicts it, that is a finding to report, not a licence to improvise. |
| [`new features/feature-list.md`](new%20features/feature-list.md) | Feature ledger. Every row names the test or source path it rests on. |
| [`docs/tech-stack.md`](docs/tech-stack.md) | **Every version, pin and toolchain quirk**, with the command that regenerates each figure. Interpreter, packages, models, external API versions, the canonical environment-knob inventory, and the open stack-hygiene defects. Check a version here, not in prose — and regenerate the knob list rather than quoting a count, because every figure published for it but the current one has been wrong — the tally lives in §6 of that file. |
| [`docs/gotchas-and-insights.md`](docs/gotchas-and-insights.md) | **The mistakes, and how not to repeat them** — each one symptom → cause → what to do, and each one something not discoverable from the code. Read it before a deployment, before adding a column, and before believing a green suite. |
| [`docs/rubric-ratification.md`](docs/rubric-ratification.md) | The record of the rubric decision, made 2026-09-01. Read it *beside* `rubric-review.md`, which was never updated when its own findings were repaired. |
| [`docs/deploying.md`](docs/deploying.md) | Post-push Render checklist. |
| [`docs/preflight.md`](docs/preflight.md) | What to check before the first **paid** validator run — credentials, the live path, cost estimate, failure modes. |
| [`docs/rubric-review.md`](docs/rubric-review.md) | An independent adversarial pass over the five rubric ladders, `rubric_support` and the verdict arithmetic. Written by an agent that had no part in the derivation — which is not the same as a human having read them. |
| [`docs/licensing.md`](docs/licensing.md) | Licence options and the decision still to be made. |

The four official CrewAI agent skills are vendored into `.agents/skills/` and
`.claude/skills/` (installed with `npx skills add crewaiinc/skills`, MIT). They
are committed on purpose, so any coding agent that opens this repository gets the
same CrewAI guidance without a separate install step.

---

## Author and licence

**Author: Simon Raj.** Every word of prose and every line of code in this
repository is his own work — the CrewAI implementation, the six-agent validator,
the event spine, the FastAPI / WebSocket service, the Vue 3 console, the flow
builder and its compiler, the specifications in [`agents/`](agents/), the scoring
rubric and every test.
Copyright © 2026 Simon Raj.

Where it builds on published thinking it cites a public source. Five of the six
orchestration *pattern names* used in
[`agents/workflow.md`](agents/workflow.md) §3 — prompt chaining, routing,
parallelisation, orchestrator-workers, evaluator-optimizer — are Anthropic's,
from [*Building Effective Agents*](https://www.anthropic.com/engineering/building-effective-agents),
and are cited there directly; the sixth is this repository's own. The analysis of
how each pattern maps onto CrewAI — analysed against 1.15.18, the version
pinned when it was written; [`docs/tech-stack.md`](docs/tech-stack.md) owns the
current pin — is original throughout. The only
third-party *files* in the repository are the four vendored MIT CrewAI skills
noted above.

**No `LICENSE` file exists**, which means default copyright applies: you may read
this code but not legally reuse it. [`docs/licensing.md`](docs/licensing.md) sets
out the options — or open an issue and ask.

---

## A note on traces

`crewai traces enable` before a run gives you a shareable trace URL. Traces can
include prompts, task inputs and outputs, tool arguments and results, and model
responses. Check what a trace actually contains before you share the link.
