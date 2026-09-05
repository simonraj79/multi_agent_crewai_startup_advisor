# Agentic Crew AI Studio

[![CI](https://github.com/simonraj79/multi_agent_crewai_startup_advisor/actions/workflows/ci.yml/badge.svg)](https://github.com/simonraj79/multi_agent_crewai_startup_advisor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![CrewAI 1.15.18](https://img.shields.io/badge/CrewAI-1.15.18-orange.svg)](https://github.com/crewAIInc/crewAI)
[![Node 24](https://img.shields.io/badge/node-24-green.svg)](https://nodejs.org/)

**Draw a multi-agent workflow on a canvas. The server compiles it into a real
CrewAI flow and runs it — and the run console shows you what the agents are
actually doing.**

Not a picture of a flow: agents, crews, human approval gates, routers, joins and
cycles are parsed into a typed document, structurally bounded, priced before a
token is spent, compiled into a `crewai.flow/v1` declaration, and executed by the
same service that streams every event back to the browser.

Live deployment: **<https://agentic-crew-ai-studio.onrender.com>** (API at
<https://agentic-crew-ai-api.onrender.com>). Sign-in is Google and currently
limited to approved test accounts, so the fastest way to try the product is the
**free local synthetic mode** below — it needs no API keys and spends nothing.

---

## Table of contents

- [What it does](#what-it-does)
- [Why it is useful](#why-it-is-useful)
- [How a run looks](#how-a-run-looks)
- [Getting started](#getting-started)
- [Using the CLI](#using-the-cli)
- [Running against real models](#running-against-real-models)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Observability](#observability)
- [Deployment](#deployment)
- [Getting help](#getting-help)
- [Contributing](#contributing)
- [License](#license)

---

## What it does

Three things share one Python package.

### 1. The flow builder

A canvas where somebody who is not a Python developer composes a multi-agent
workflow, and the server turns it into a running CrewAI flow.

- **Ten node kinds** — `input`, `agent`, `crew`, `gate`, `router`, `transform`,
  `output`, plus three attachment kinds (`tool`, `mcp`, `skill`) you hang off an
  agent or a crew.
- **Two model tiers** — `cheap` and `escalation` — both resolved from a
  regenerated OpenRouter registry ([`data/models.json`](data/models.json)) with a
  hard **$1.00 per 1M input tokens** ceiling that a test enforces over the whole
  source tree.
- **A budget meter that prices the graph before it runs.** Every node is costed
  as a worst case (every guardrail retried, every tool loop at `max_iter`, every
  cycle at its ceiling), with a 1.25× margin against a per-run ceiling. A graph
  that would blow the ceiling is refused at publish with a dollar figure, not a
  node count.
- **Structural bounds that catch the failures CrewAI does not.** One canvas gate
  compiles to *two* flow methods; every loop-closing node must be a router; a
  gate's `emit` must be null. Get any of those wrong by hand and the flow returns
  normally having produced nothing — silently. The compiler refuses the shape
  instead.
- **No author-supplied code, ever.** Every compiled action resolves to one of a
  closed set of compiler-owned entrypoints. Author data arrives as *values*,
  never as names of things to import or run.
- **Nine templates in the gallery**, including the six-agent idea validator
  (16 nodes, 22 edges, two revise loops), a sequential pipeline, a conditional
  router, a reflection loop, hierarchical delegation, and a news-to-social flow.
- Export, import, duplicate, version history, publish and unpublish, with
  per-user isolation and an AES-256-GCM credential vault for BYO API keys.

### 2. The run console

Every run is a live agent trace beside whatever the flow produced.

- **Every agent gets a character.** A "Pip" — a rounded body, two oversized eyes,
  a mouth and a crown flourish cut from the body's own fill — is derived
  deterministically from the agent's role string. 4 bodies × 4 eye shapes ×
  3 mouths × 6 crowns × 12 colours = **3,456 reachable characters**, all
  legible at 32 px, the same character on the node and in the trace rail. A flow
  authored next week gets a cast with no code change.
- **Six states, driven by run events, not by a clock**: `idle`, `working`,
  `speaking`, `blocked`, `blocked-error`, `done`. Blocked and blocked-error are
  separated by *two* signals (a wilted crown plus `×_×` eyes), not by colour
  alone. Reduced-motion is respected, and the number of live animations on the
  page is bounded whatever the graph's size.
- **Every event becomes one human-readable line — or nothing.** The trace layer
  is pure: one frame in, one sentence out, capped at 140 characters. The verb
  comes from the frame kind and the words inside the tool name the framework
  emitted, never from a hardcoded list of this repo's own agents. The raw payload
  is one click away behind a per-row disclosure, not in the way.
- **The verdict panel says what decided the run.** It keys on the decision reason
  rather than on the list of triggered floors, so a floor that did *not* decide
  the outcome is demoted to an also-ran instead of being presented as the cause.
  Internal codes (`FLOOR_NO_MARKET`, `market_task`, `NEEDS_WORK`) are rendered as
  words — including codes that did not exist when the renderer was written.
- Reconnecting WebSocket with replay and deduplication, refresh recovery, per-run
  and per-node token/cost display, NDJSON and ZIP log export, and a report panel
  that opens itself the first time a result arrives.

### 3. Two built-in flows

| Flow | What it is |
| --- | --- |
| **Idea Validator** | Six agents — Scoper, Market Analyst, Sentiment Analyst, Feasibility Analyst, Synthesist, Reporter — with three research branches running in parallel against Firecrawl, Hacker News and GitHub. Two durable human gates that survive the process dying. A scored, cited verdict against a ratified rubric, with mechanical guardrails that recompute the arithmetic and check every citation closes over real tool results. |
| **Brief Crew** | The original Researcher → Analyst → Writer pipeline behind a warm Pinecone vector cache, so repeat runs on a topic get cheaper. Writes `output/brief.md`. |

The validator also exists **as a builder template**, so you can open it, edit it
and publish your own variant. What the template carries is the flow's *shape* —
the rubric, the confidence arithmetic, the guardrails and the warm cache stay in
Python, and the gallery card says so.

---

## Why it is useful

- **The canvas maps onto real CrewAI primitives, one to one.** If a node cannot
  map, the node design is wrong — the runtime is never faked. What you draw is
  what runs, through the same registry, gates, event spine and console as the
  hand-written flows.
- **Cost is a first-class constraint, not an afterthought.** OpenRouter only, a
  $1/1M-input ceiling enforced by a test over the source tree, a static price on
  every graph before publish, a per-run ceiling enforced mid-flight at the step
  boundary, admission control on the one endpoint that spends money (body size,
  input size, per-client rate limit, queue depth), and a fully free
  `SYNTHETIC=1` mode for everything else.
- **A no-cost test suite.** Thousands of Python and frontend unit tests plus a
  Playwright browser suite, all against mocks and deterministic doubles. CI runs
  with **no credentials at all** — that is what makes "costs nothing and touches
  no network" checkable rather than aspirational.
- **Human gates that survive a restart.** A run paused for a person is durable:
  the reply is a compare-and-set, a duplicate answers 409, a reply that cannot
  start its resume is rolled back rather than left committed, and a run
  interrupted mid-flight reaches a terminal state instead of being orphaned.
- **Evidence over assertion.** The design premise throughout is that an agent's
  output is worth what its evidence is worth, so the interesting engineering is
  in the parts that refuse to let a model claim something it cannot support.

---

## How a run looks

There are no screenshots committed to this repository. What you see when you
press Launch:

1. **The canvas** draws the flow's topology — one card per node, each carrying
   its kind icon, its label and (for agent nodes) its character.
2. **A node starts.** Its character leans in and squints, a soft bob begins, and
   the edge into it animates. Everything else on the canvas stays still — that
   stillness is what makes the one working node legible.
3. **The trace rail fills, one sentence per event.** *"Market Analyst searched
   the web for competitors."* Not `AgentExecutor market_task` and not
   `5168 in · 3994 out`. Each row has a disclosure holding the raw frame.
4. **A gate opens.** The node's character wilts its crown and widens its eyes,
   the node goes amber, and a gate card appears with editable fields and
   read-only derived values. The run waits — across a page refresh, across a
   process restart — until a person answers `approve` or `revise`.
5. **A revise loops back.** The stage badge picks up a `×2` lap chip, and the
   crew strip says which pass the run is on.
6. **The run finishes.** The report panel opens itself with the rendered
   Markdown body and its sources; the verdict block above the scorecard says, in
   one sentence, what decided the outcome; the metrics grid shows tokens and
   estimated cost per node and for the run.

In `SYNTHETIC=1` mode every one of those steps happens for free against
deterministic doubles — the plumbing is real, the agents are not.

---

## Getting started

### Prerequisites

| | |
| --- | --- |
| **Python** | 3.13 recommended (3.10–3.13 supported; CrewAI requires `<3.14`) |
| **Node** | 24 |
| **Git** | any recent version |

Optional but recommended: [`uv`](https://docs.astral.sh/uv/) — the lockfile
[`uv.lock`](uv.lock) is committed, and CI and the deployment both install with it.

### 1. Clone and install the backend

```bash
git clone https://github.com/simonraj79/multi_agent_crewai_startup_advisor.git
cd multi_agent_crewai_startup_advisor
```

With `uv` (creates `.venv` for you, exactly the versions CI uses):

```bash
uv sync --frozen --extra service
```

Or with the standard library:

```bash
python -m venv .venv
# macOS / Linux
. .venv/bin/activate
# Windows PowerShell
# .\.venv\Scripts\Activate.ps1

pip install -e ".[service]"
```

> The `service` extra (FastAPI, Uvicorn, SQLAlchemy, psycopg, PyJWT) is required
> for the studio and for the `tests/service` and `tests/integration` suites. The
> CLI-only crews work without it.

### 2. Configure keys

```bash
cp .env.example .env
```

[`.env.example`](.env.example) is the canonical, annotated list — every variable
names the file that reads it and what happens if you leave it blank. `.env` is
gitignored.

**Nothing below is needed for the free synthetic mode.** For real runs:

| Variable | Needed for | Notes |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | **Every real run.** The only LLM provider this project uses; also used directly for embeddings. | <https://openrouter.ai/keys> |
| `FIRECRAWL_API_KEY` | Brief Crew's researcher and the validator's market branch. | Without it the branch reports a `failed` envelope rather than inventing sources. |
| `PINECONE_API_KEY` + `PINECONE_INDEX_NAME` | The warm cache (Brief Crew Track B, the validator's market cache). | You create the index yourself. |
| `COHERE_API_KEY` | Rerank, stage 2 of retrieval. | |
| `GITHUB_TOKEN` | *Optional.* Raises the feasibility branch's rate limit; changes no behaviour. | |
| `CREDENTIALS_MASTER_KEY` | The per-user credential vault. Any base64 of 32 bytes. | Without it the credential routes answer **503**; **with `AUTH_BASE_URL` also set, startup refuses outright** — a half-configured vault is the quiet failure this prevents. |
| `DATABASE_URL` | Production only. | Unset locally → SQLite at `output/validator-studio.db`. |

Mint a vault key:

```bash
python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

### 3. Start the free backend

`SYNTHETIC=1` swaps the real crews for deterministic no-cost doubles. It is a
factory swap inside the same app, not a second runner — the same routes, the same
event spine, the same gates.

```bash
# macOS / Linux
SYNTHETIC=1 \
SYNTHETIC_BRANCH_DELAY_SECONDS=5 \
PORT=8000 \
CREDENTIALS_MASTER_KEY="$(python -c 'import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())')" \
  .venv/bin/serve
```

```powershell
# Windows PowerShell
$env:SYNTHETIC = "1"
$env:SYNTHETIC_BRANCH_DELAY_SECONDS = "5"
$env:PORT = "8000"
$env:CREDENTIALS_MASTER_KEY = "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
.\.venv\Scripts\serve.exe
```

Check it:

```bash
curl http://127.0.0.1:8000/healthz          # {"status":"ok",...}
curl http://127.0.0.1:8000/api/workflows    # brief-flow, idea-validator
```

Interactive API docs are served at `http://127.0.0.1:8000/docs` whenever the
instance is synthetic (or `EXPOSE_API_DOCS=1`); they are **404 in production** by
design.

> `SYNTHETIC_BRANCH_DELAY_SECONDS=5` is not decoration — the synthetic runner
> finishes a branch instantly, so without it there is no "running" moment to
> watch, and the visual E2E specs fail with `No branch stayed in flight`.

> `PORT=8000` is where the Vite dev server proxies. `SYNTHETIC=1` is what makes
> that port free — the *same* port without it is the paid backend.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173/>. With no auth server running the console detects
that auth is unconfigured and opens the studio directly — no Google sign-in
needed for local development.

- `#/` — the run console
- `#/build` — the flow builder canvas and template gallery

Press **Launch** and watch a full synthetic run: gates, revise loops, trace,
verdict and report, for free.

### 5. Optional: the auth server

Sign-in is Google via [Better Auth](https://better-auth.com), served by a small
Hono service in [`frontend/server/`](frontend/server/) that also serves the built
SPA. It reads `BETTER_AUTH_URL`, `BETTER_AUTH_SECRET`, `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET`. You only need it if you are working on authentication or
per-user isolation.

```bash
cd frontend
npm run dev:server        # listens on :3000, which vite.config.ts proxies /api/auth to
```

> The proxy order in [`frontend/vite.config.ts`](frontend/vite.config.ts) is
> load-bearing: `/api/auth` must be declared before `/api`, or every Better Auth
> request — the Google callback included — is proxied to FastAPI and 404s with
> nothing in either log to say why.

---

## Using the CLI

The package installs five console scripts
([`pyproject.toml`](pyproject.toml) → `[project.scripts]`); `serve` is the one
covered above.

```bash
# Brief Crew — the three-agent sequential crew. Writes output/brief.md.
run_crew

# Brief Crew as a Flow, with the cache router.
kickoff

# Render the flow graph.
plot

# The six-agent idea validator. Pauses at the scope and verdict gates.
validate --idea "A scheduling assistant for clinics"

# Same flow, both gates auto-approved. For tests and CI.
validate --idea "A scheduling assistant for clinics" --no-gates
```

Other `validate` flags: `--resume FLOW_ID` and `--feedback '{"decision":"approve"}'`
to answer a pending gate, `--namespace` for cache isolation,
`--feasibility-cache`, and `--sequential-branches` to run the three research
branches one at a time.

> ⚠️ **Every CLI run above calls paid models and live external APIs.** There is
> no synthetic mode on the CLI path — `SYNTHETIC=1` applies to the service only.
> `validate` writes `output/validation.md`; `run_crew` writes `output/brief.md`
> and `output/last_run.json`.

---

## Running against real models

- **OpenRouter only.** Every agent LLM comes from `CHEAP_MODEL` or
  `ESCALATION_MODEL` in [`src/brief_crew/config.py`](src/brief_crew/config.py).
  There is no direct OpenAI fallback, and startup rejects any model constant or
  YAML override that does not carry the `openrouter/` prefix.
- **A hard price ceiling of $1.00 per 1M input tokens**, enforced by
  `tests/test_model_ceiling.py` scanning the *source tree* — not just the
  registry, because a registry checked against itself proves nothing. The
  registry [`data/models.json`](data/models.json) is regenerated from the live
  OpenRouter catalogue by [`scripts/refresh_models.py`](scripts/refresh_models.py),
  never typed from memory.
- **Every cost figure is an estimate**: tokens × a local price table. OpenRouter's
  own per-generation cost never reaches the process, and `:nitro` routes on speed
  rather than price, so the effective rate can exceed the published one.
- **`MAX_RUN_COST_USD`** (default `$10`) is a real per-run ceiling, recomputed as
  the run proceeds and enforced at the next step boundary.
- Do not install `crewai[litellm]` — OpenRouter is a native CrewAI provider at
  the pinned version.

---

## Project layout

```
src/brief_crew/
  builder/          the typed document, bounds, budget, compiler and runtime
  crews/            brief_crew/ and validator_crew/ — @CrewBase wrappers,
                    with every prompt in config/agents.yaml + config/tasks.yaml
  events/           the per-run event spine: frames, node registry, token/cost
  schemas/          the validator contracts and the deterministic verdict
  service/          FastAPI app, WebSocket, registry, SQL persistence,
                    builder API, credentials, auth (JWT verification)
  tools/            Firecrawl market research, HN sentiment, GitHub feasibility
  config.py         every constant and every environment knob
  main.py           Brief Crew entry points
  validator_flow.py the six-agent flow and the `validate` CLI

frontend/
  src/components/   the run console — canvas nodes, rails, gate card, report
  src/components/builder/   the builder — palette, canvas, inspector, gallery
  src/characters/   the Pip generator
  src/trace/        frame → one human sentence
  src/composables/  run state, choreography, builder document, auth gate
  server/           Hono + Better Auth (Google), serves the built SPA
  tests/            Vitest unit specs
  e2e/              Playwright specs

data/models.json          the OpenRouter registry, regenerated not typed
data/skills/builtin/      the four built-in skill packs
tests/                    the Python suites (unittest)
scripts/                  registry refresh, benchmarks, fixture generators
render.yaml               the deployment manifest
.env.example              the annotated environment reference
```

---

## Testing

Every suite is **no-cost**: CrewAI crews, OpenRouter, Pinecone, Cohere,
Firecrawl, Hacker News and GitHub are all mocked or replaced with deterministic
doubles.

```bash
# Python — unit and integration
.venv/bin/python -m unittest discover -s tests -t .

# Frontend — Vitest (single pass, no watch)
cd frontend && npm test

# Frontend — type-check (also the first step of `npm run build`)
cd frontend && npx vue-tsc -b --force
```

End-to-end, in a real browser. Playwright deliberately starts **no** Python
backend — an automated suite must not be able to press Launch against a paid
one — so start the free backend yourself first (step 3 above, on port `8099`),
then:

```bash
cd frontend
npx playwright install chromium     # first time only
npx playwright test
E2E_API_TARGET=http://127.0.0.1:8099 npx playwright test   # if the backend is elsewhere
```

Notes that will otherwise cost you an afternoon:

- Playwright starts its own second Vite server (`e2e/vite.e2e.config.ts`, port
  `5273`) which proxies to `127.0.0.1:8099` and stubs the auth origin.
- Specs tagged `@launch` press Launch for real. They are free against a synthetic
  backend; pointed at a paid origin with `E2E_BASE_URL` they are not.
  `npx playwright test --grep-invert @launch` excludes them.
- `e2e/builder-mcp.spec.ts` **skips** unless you start the MCP fixture server and
  set `E2E_MCP_URL` — it refuses to stub what it is there to verify.
- **Add an `__init__.py` in the same commit as any new test directory**, or
  `unittest discover` walks past it in silence and reports a green `OK` over
  tests it never ran.
- On Windows, stop a stray backend with `Stop-Process -Name serve -Force`.
  `pkill` reports success and leaves the old process serving stale code.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs the Python suite,
the frontend type-check, build and unit tests on every push, plus a two-writer
PostgreSQL 18 concurrency job on `main`. It carries no credentials by design.

---

## Observability

The app writes **one Langfuse trace per run** — the Langfuse session id *is* the
run id, so a console URL takes you straight to the trace. Under it sit the run,
its nodes, agents, tasks, tools and model calls, with durations, token counts,
the per-generation cost OpenRouter actually billed, and the exception class on
anything that failed.

It is **off by default** and turns on when `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` are set; with any of them missing
the exporter is a no-op that logs one line at startup. `GET /readyz` reports its
state. Nothing it does can fail a run: it is a second consumer of the same
bounded event pipeline the UI reads, and an unreachable Langfuse changes only
the exporter's own counters.

**Content is not sent.** A model call carries a fingerprint of its rendered
prompt plus message and character counts, never the text. Setting
`LANGFUSE_CAPTURE_CONTENT=1` adds completions and tool payloads, and everything
outbound is scrubbed for credential shapes either way.

The audit, the trace contract, the definition of done and the full evidence tree
live in [`docs/observability/`](docs/observability/).

---

## Deployment

[`render.yaml`](render.yaml) is a Render Blueprint declaring three services in
`region: singapore`:

| Service | Runtime | What it is |
| --- | --- | --- |
| `agentic-crew-ai-studio` | Node (web service) | Serves the built SPA **and** mounts Better Auth. It is not a static site — Better Auth needs a runtime a CDN cannot give it, and `onrender.com` being on the Public Suffix List rules out a cross-subdomain cookie, so both must come from one origin. |
| `agentic-crew-ai-api` | Python (web service) | The FastAPI service. |
| `agentic-crew-ai-db` | PostgreSQL 18 | Durable runs, frames, gates, documents and credentials. Its IP allow list is empty, which is *why* the region is load-bearing. |

Both web services carry `autoDeploy: yes`, so a merge to `main` **is** a deploy.
Before merging, confirm `CREDENTIALS_MASTER_KEY` is set on the API service —
`render.yaml` sets `AUTH_BASE_URL`, and the two together are a deliberate startup
refusal rather than a degraded feature. A [`Dockerfile`](Dockerfile) exists as an
alternative container path; the Blueprint does not use it.

---

## Getting help

- **Bugs and questions** → [open an issue](https://github.com/simonraj79/multi_agent_crewai_startup_advisor/issues).
- **Environment variables** → [`.env.example`](.env.example) documents every one,
  with the file that reads it and the consequence of leaving it blank.
- **Constants, ceilings and defaults** → [`src/brief_crew/config.py`](src/brief_crew/config.py).
  Each one carries the reasoning beside it.
- **What the API offers** → run a synthetic backend and open `/docs`; the OpenAPI
  schema is generated from the code.
- **Agent behaviour** → the prompts are YAML and are meant to be read:
  [`src/brief_crew/crews/validator_crew/config/`](src/brief_crew/crews/validator_crew/config/)
  and [`src/brief_crew/crews/brief_crew/config/`](src/brief_crew/crews/brief_crew/config/).
- **Skill packs** → [`data/skills/builtin/`](data/skills/builtin/).
- **Upstream** → [CrewAI](https://github.com/crewAIInc/crewAI) ·
  [OpenRouter](https://openrouter.ai/docs) · [Better Auth](https://better-auth.com) ·
  [Vue Flow](https://vueflow.dev/).

Most modules open with a docstring explaining *why* the code is shaped the way it
is, including the defect that shaped it. Read those before changing behaviour.

---

## Contributing

Maintained by **Simon Raj** ([@simonraj79](https://github.com/simonraj79)).
Issues and pull requests are welcome.

Branch from `main`, and before you open a PR:

1. **Run the three suites.** Python `unittest discover`, `npm test`, and
   `npx vue-tsc -b --force`. Add tests for what you change; a green suite over
   code nothing exercises is the failure mode this project watches for hardest.
2. **Keep prompts in YAML.** Agent and task instructions belong in
   `config/agents.yaml` and `config/tasks.yaml`, never in Python. A user's
   authored agent carries its prompts in the user's own document.
3. **Keep constants in `config.py`.** No inlined model names, prices, embedding
   prefixes, routing thresholds, cache policies or runtime limits.
4. **OpenRouter only, under the ceiling.** Never introduce a frontier-priced
   model — not in code, not in defaults, not in examples, not in tests. If you
   change `CHEAP_MODEL` or `ESCALATION_MODEL`, move `PRICES` in the same commit.
   A price written in prose is stale; look it up.
5. **Never launch against a paid backend in a test.** Use `SYNTHETIC=1`. E2E
   specs that press Launch are tagged `@launch`.
6. **Map every canvas node to a real CrewAI primitive.** If a node cannot map,
   the node design is wrong — fix the design, never fake the runtime.
7. **Do not regress Brief Crew.** `run_crew()`, `kickoff()`, `output/brief.md`
   and `output/last_run.json` behaviour is preserved deliberately.
8. **Use design tokens.** No new colours, spacing or type scales — a value is a
   token in `frontend/src/assets/styles/` or it does not exist.

Commit messages here describe the *behaviour* that changed and the evidence for
it, not the files touched.

---

## License

[MIT](LICENSE) © 2026 Simon Raj. Third-party files vendored into this repository
keep their own notices.
