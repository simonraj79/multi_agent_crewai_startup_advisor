# 00 — Architecture

Written 2026-09-02 against `main` = `25634c0`, with an unrelated uncommitted
working session in the tree (eleven frontend files, one new spec — another
agent's builder-library-refresh work; nothing in this plan touches those
files). Every figure below was measured in this pass unless it says
otherwise. The audit that produced this file is summarised in §1; the
reference material it rests on is `docs/crewai-notes.md`,
`docs/flowise-notes.md` and `docs/chatdev-notes.md`, all extracted from the
installed package and the two repos on disk rather than from memory.

## Problem

The gauntlet asks for a visual agent-creation platform on CrewAI: a signed-in
user drags components onto a canvas, composes their own agents with LLMs,
tools, skills and MCP servers, tests the flow, runs it, and watches it execute
in ChatDev's visual language — under four minutes, with no documentation.

This repository already contains **most of the machinery and almost none of
the authoring surface.** A flow builder shipped on 2026-09-02 (`6d2743c`,
59,489 lines): a typed document, structural bounds, a static price, a
compiler to a real `crewai.flow/v1` definition, durable human gates that open
on the author's own canvas node, per-node cancellation, a `$10` per-run cost
ceiling, boot rehydration, and a Vue 3 + Vue Flow canvas with undo, clipboard,
a problems dock, a budget meter and a template gallery. What it cannot do is
the thing the gauntlet is about:

- **An agent node is a six-way dropdown over prompts this repo owns.** `AgentConfig` carries `agent_id` and `tools`; there is no field anywhere in the document that can hold a role, a goal, a backstory or a task (`src/brief_crew/builder/document.py:182-204`; `runtime.py:170-177` states the rule in words).
- **A crew node is a four-way dropdown over pre-built `@CrewBase` classes**, and its `tier` / `max_iter` are accepted, priced, and then ignored by the factory (`runtime.py:441-468`).
- **Tools are three names on an allowlist**, not nodes (`config.py:2014-2020`). There is no tool node, no MCP anywhere in `src/` or `tests/`, no skills, no per-node model choice — only two tiers.
- **There is nowhere for a user's own API key to live.** No credential table, no encryption, no BYO key; every external credential is a process-wide environment variable (`market_research.py:241`, `github_feasibility.py:333`, `pinecone_retrieval.py:68`).
- **No test panel, no dry run, no single-node test, no code preview, no error edges, no per-node retry, no partial-run resume.** A failing node fails the run.
- **The run console narrates the fixed validator**, with a seven-stage strip declared in `crewStages.ts` and a rowing-boat metaphor; it has no agent dialogue, no handoff choreography, and its stage list cannot describe a graph a user drew.
- **One template**, the idea validator, whose card honestly says it is the evaluator's shape and not its judgement.

## Scope

Everything in the gauntlet's Stage 2, delivered as extensions of the existing
subsystems, in the dependency order the plan files carry (00 → 15). Four
working templates, a ChatDev-motion run view, Flowise-parity error handling,
per-user isolation including credentials, a ten-model roster under the price
ceiling, and the judge loop with a real reference comparison.

## Out of scope

- A frontend rewrite. See D1.
- Real-time multi-user editing, presence, locking (flow-builder-spec cut-list 11 stands).
- Template authoring by users (cut-list 12 stands — the four templates are code, pinned by fixtures).
- A YAML/JSON source tab as a second editing surface (cut-list 9 stands; the generated-code preview is read-only).
- CrewAI AMP marketplace references for MCP or skills (bare strings in `mcps` / `skills` resolve to AMP — `docs/crewai-notes.md` §6, §7). User input is never passed as a raw string.
- In-process execution of user-authored Python. See D8 and `06-tool-registry.md`.
- A brief-crew regression. `run_crew()`, `kickoff()`, `output/brief.md`, `output/last_run.json` are untouched.

## Design

### D1 — Extend the Vue 3 + Vue Flow builder; do not rewrite it in React

The gauntlet's plan index names "React Flow surface" in one file
description. Its actual requirement is Flowise-grade *interaction*, and
Flowise's React Flow 11 API (`reactFlowInstance.project`, `Handle`,
`NodeToolbar`, `getBezierPath`) is what Vue Flow 1.48 ports one-to-one
(`docs/flowise-notes.md` §0). Three facts decide it:

1. The existing builder is 34 components, 1,024 frontend tests and 28 E2E tests on Vue Flow. A rewrite discards that and buys nothing the rubric measures.
2. **The run-time reference is itself Vue 3 + Vue Flow.** `D:\ChatDev-main` is ChatDev 2.0, not the 1.0 Flask visualizer; its choreography is expressed in Vue Flow custom nodes and CSS and transfers verbatim (`docs/chatdev-notes.md` §0).
3. The repo's own spec rules `R2` (ride Vue Flow) and `R15` (docked, never modal) already encode the two interaction decisions Flowise gets right.

`02-canvas.md` therefore reads "Vue Flow surface". Every other plan file is
framework-independent.

### D2 — Two node families: **authored** and **library**. The document carries prompt text for authored nodes.

This is the one architectural rule of the existing builder that must be
overturned, and it is overturned on purpose, by number:

- `AGENTS.md:63` — *"there is no field anywhere in the document schema that carries prompt text"* — **overturned for authored nodes.** A user's agent has a role, a goal, a backstory and a task, and those live in the user's document, because the user's document is the only place they can live. The YAML rule (`AGENTS.md:39`, "prompts go in YAML, never in Python") **stands for this repository's own crews**, which remain offerable as *library* nodes.
- `AGENTS.md:64` — *"a document cannot spell a model"* — **overturned.** A document names a model **by registry id**, validated against the model registry (`05-model-registry.md`), never as a free string. The two tiers survive as named presets.
- `AGENTS.md:66` — the three-name `BUILDER_RESEARCH_TOOLS` allowlist — **extended** into the tool registry (`06-tool-registry.md`). The principle — tools are chosen from a closed catalogue the server owns — stands.
- `AGENTS.md:67` — *"no code on the canvas"*; `BUILDER_ACTION_REFS` is a closed set of compiler-owned entrypoints — **stands.** Authored text reaches those entrypoints as `with:` values. See D8 for the one place this bites.

Authored and library nodes share a kind (`agent`, `crew`) and are told apart
by which fields are present; exactly one of `agent_id` / `role` is required
and the parser refuses both or neither (`03-node-library.md` C1).

Four rulings of `docs/flow-builder-spec.md` are overturned with it, each
because its premise has expired rather than because it was wrong:

- **R4 and cut-list items 1–2** (run mode is out of scope; no Launch inside the builder). R4's own stated reason was that no `builder_runner` existed; `service/builder_runner.py` and `builder_rehydrate.py` shipped in the same merge. The test panel (`13-flow-testing.md`) launches from the editor, docked.
- **Cut-list item 14** (no light mode). The gauntlet's capture step requires light and dark at both viewports, so `assets/styles/tokens.css` — today one unconditional dark `:root` — gains a light theme.
- **Cut-list item 9** stands in letter (no YAML/JSON source tab) and is narrowed in spirit: the generated-code preview is **read-only**, and the prompt fields on an authored node are the primary surface, not a second one.
- **`BuilderView` receives no `user` prop today** (`App.vue:60-67`); it gains one, because credentials, skills and MCP servers are per-user surfaces inside the builder.

Everything else in the spec — R1–R3, R5–R13, R15, and cut-list items 3–8,
10–13, 15–17 — stands unchanged.

### D3 — The canvas is a **Flow** canvas; an agent node is a step; a crew node is a team

Every node maps to a real primitive, and the mapping is the table below.
The existing compiler already treats the canvas as `Flow` methods wired by
`@listen` / `@router` / `and_` (`compiler.py:234-244`), and that is the right
level for "each user builds their own team": a step is one agent doing one
task, a team is a crew of agents with a process.

| Canvas node | Family | CrewAI primitive | Owner |
| --- | --- | --- | --- |
| `input` | — | the `@start` seed into `Flow` state | existing (`runtime:seed_input`) |
| `agent` | authored | `Agent(role, goal, backstory, llm, tools, skills, mcps, …)` + `Task(description, expected_output)` + `Crew(process=sequential)` of one | 03, 04, 09 |
| `agent` | library | `Agent(config=agents.yaml[agent_id])` + `Task(config=tasks.yaml[task_key])` | existing (`runtime:run_agent`) |
| `crew` | authored | `Crew(agents=[members], tasks=[…], process, manager_llm, memory, …)`; members are `agent` nodes attached through the `member` port | 03, 04, 09 |
| `crew` | library | `<Class>().crew()` from `BUILDER_CREW_LIBRARY` | existing (`runtime:run_crew`) |
| `gate` | — | `@human_feedback(llm=None, emit=None)` + paired `@router` | existing |
| `router` | — | `@router` emitting labelled events | existing |
| `transform` | — | pure state op | existing |
| `output` | — | the run result body | existing |
| `tool` | attachment | one `crewai_tools` class or repo tool, constructed with the user's credential | 06 |
| `mcp` | attachment | `MCPServerStdio` / `MCPServerHTTP` / `MCPServerSSE` on `Agent.mcps` | 07 |
| `skill` | attachment | a `Path` on `Agent.skills` → `crewai.skills.Skill` with progressive disclosure | 08 |
| `join` (and/or) | edge property | `and_()` / `or_()` on the listener | existing (`joins`), extended in 09 |
| flow `state` | document property | `FlowDefinition.state` of kind `json_schema` | 09 |

**Attachment nodes are not steps.** They connect to an `agent` node through a
second, visually distinct port class (`attach`), never through `in`. The
compiler folds them into the agent's constructor and they never appear as
Flow methods. An LLM configuration is inline on the agent (Essentials: model;
Advanced/Expert: sampling), not a node — nothing in the four templates needs
a shared LLM node, and a node with nothing to execute is a rubric-13 liability.

The things the package **cannot** do, so the canvas will not offer them
(`docs/crewai-notes.md` §11): `allow_code_execution` / `code_execution_mode`
(deprecated, no tool behind them); a three-way memory toggle (memory is one
unified field); `retry_count` as a setting (it is a counter — `max_retries`
is the setting); Firecrawl `map` / `extract` (no `crewai_tools` class);
Pydantic state editing (a canvas authors `json_schema` state).

### D4 — The model registry is data, and the ceiling maintains itself

`config.py` holds two models and two prices, and both prices are stale
against the live catalogue on 2026-09-02:

| Model | `PRICES` in `config.py:57-60` | Live catalogue headline |
| --- | --- | --- |
| `google/gemini-3.5-flash-lite` (cheap) | $0.30 / $2.50 | **$0.15 / $1.25** |
| `google/gemini-3.7-flash` (escalation) | $0.75 / $3.75 | **$0.38 / $1.88** |

The catalogue headline is the **cheapest endpoint** for a slug;
`list-model-endpoints` on 2026-09-01 showed flash-lite served by eight
endpoints from $0.15 to $0.54 (CLAUDE.md, "OpenRouter MCP"). So neither
number is wrong — they measure different things — and that is exactly why a
hand-maintained price table cannot be the source of truth. `05-model-registry.md`
replaces it with a committed JSON snapshot regenerated from the live
endpoint, carrying headline and maximum-endpoint price, and `PRICES` is
derived from it. **The gauntlet's ceiling is $1.00 per million *input*
tokens**, and a test asserts it over every model id in the codebase —
defaults, templates, examples and tests included (rubric 13).

Of the gauntlet's ten candidate slugs, checked live on 2026-09-02: all ten
exist; **`openai/o4-mini` is over the ceiling at $1.10** and is dropped;
`moonshotai/kimi-k2` and `deepseek/deepseek-r1` pass on input but bill $2.30
and $2.50 per million output, which the registry shows and the picker warns
about. The roster is seeded from the live list, not from the document.

### D5 — Isolation: one identity, every owned row, 404 never 403

Identity already exists: Better Auth mints a 15-minute Ed25519 JWT, FastAPI
verifies it offline against JWKS (`service/auth.py:211-268`), runs and
builder documents carry `user_id`, and a document you do not own answers
**404**, because a 403 confirms it exists (`store.py:602-610`,
`app.py:756-776`). `01-auth-and-workspaces.md` extends the same three rules —
owner column, SQL-scoped list, 404 collapse — to every new table:
credentials, skills, test inputs, MCP server records.

Two existing carve-outs are kept deliberately and named: an **unowned** row
(written before auth existed, or in `SYNTHETIC` / local mode with no
`AUTH_BASE_URL`) stays readable by everyone, and `VALIDATOR_REQUIRE_AUTH`
derives from `bool(AUTH_BASE_URL)` so a half-configured deployment fails
closed. Rubric 14 is measured against a deployment with auth on.

### D6 — Credentials: encrypted at rest, resolved at run time, never on the wire

There is no credential store today (§1). `01` adds one table,
`user_credentials`, with AES-GCM envelope encryption under a master key from
the environment, a per-row random nonce and the credential id as associated
data. Flowise's primitive — `crypto-js` `AES.encrypt(json, passphrase)`,
OpenSSL KDF, CBC, no authentication tag (`docs/flowise-notes.md` §4) — is
the thing to learn from and not to copy. A document references a credential
**by id**; the compiler never sees the secret; the runtime resolves it inside
the action entrypoint into a tool constructor or `LLM(api_key=…)`; the frame
serializer's existing `_SECRET_KEYS` redaction (`persistence.py:71-86`) is
extended to every new key name; exports strip credential ids the way
Flowise's `_removeCredentialId` does.

### D7 — Runtime: the same registry, the same frames, the same gates

A published graph runs through `builder_runner.py` into the one `RunRegistry`
and the one frame spine. `10-runtime.md` adds, on that path only:

- **Error edges.** A step that can fail gains an `error` out-port. Because only a `@router` can choose an event, an error-capable step compiles to **two** methods — the step and a paired deterministic router emitting `ok` / `error` — the same shape a gate already has (`compiler.py:436-440`).
- **Retry with fallback.** `max_retries`, backoff, and an optional fallback model from the registry, executed inside the action entrypoint and **priced** — retries multiply `modelled_calls` in `budget.py`.
- **Partial-run resume.** Not a CrewAI resume. A derived compilation in which every node upstream of the chosen one becomes `runtime:replay_output` — an eleventh action ref that writes the cached `out__<node>` from the failed run's persisted state and emits normally. Same mechanism gives `13-flow-testing.md` its single-node test with mocked upstream values.
- **Dry run** = parse + bounds + budget + compile with no kickoff, returning the definition — the existing `POST /validate` plus the compiled artifact.

The `$10` ceiling, `HookAborted` at every checkpoint, and cooperative cancel
are unchanged (`registry.py:1266-1335`, `runtime.py:142-156`).

### D8 — "No code on the canvas" survives one exception, and the exception is sandboxed or absent

The gauntlet asks for a user-authored Python custom tool. `AGENTS.md:67`
closes exactly that door, and it is the right door to keep closed on a
shared host. CrewAI 1.15.18 has **removed** `CodeInterpreterTool`; the
sandboxed alternatives (`E2BPythonTool`, `DaytonaPythonTool`) are paid
third-party services behind a key (`docs/crewai-notes.md` §8).

Decision: v1 ships a **declarative custom tool** — Flowise's schema grid
(name, description, typed properties, required) with the function replaced
by an HTTP call (URL, method, header credential, body template) — which needs
no interpreter. The Python-function form is a **decision for the owner**,
gated on a BYO sandbox key, recorded in `06-tool-registry.md` and not
started until decided.

### D9 — The run view extends the console with ChatDev's motion and our own art

`11-run-visualizer.md` adds to the existing run console, not beside it:
active-speaker emphasis with **idle recede** (the reference has none —
`docs/chatdev-notes.md` §6), a handoff token that walks the real edge path on
an explicit `edge_traversal` frame (the reference regex-matches a log line),
a dialogue rail revealed progressively from a new bounded `utterance` frame
(the serializer today drops the completed response text at
`events/serializer.py:472`, and the client drops every stream chunk at
`useValidatorRun.ts:973`), a launch sequence, and a stage lane derived from
the compiled plan's topological layers instead of `crewStages.ts`'s fixed
seven — which today hides itself entirely for any published graph, because
`assertStageCoverage` cannot match a graph that shares none of the
validator's node ids (`CrewProgress.vue:44-56`). Characters are **ours**: the sprite adoption was tried and reversed on
the evidence (CLAUDE.md §14), so identity is the per-kind icon plus a stable
per-node colour, and the design commission for real characters stays open.

### D10 — Stage 0 R: the rules file, and what happens to CLAUDE.md

> **Decided 2026-09-02 by the owner: declined.** `CLAUDE.md` stays the
> session file; it is not replaced by `@AGENTS.md` and not moved. Plan
> status is tracked in `PLANS.md` at the repo root, not in `CLAUDE.md`.
> The rules block, if adopted, is **prepended to `CLAUDE.md`** — the
> paste-ready text is `.agent/RULES.draft.md` (decision 2 in `PLANS.md`).
> The paragraphs below are the recommendation as it stood, kept for the
> reasoning.

`CLAUDE.md` is 2,883 lines of reconciliation prose loaded into every
session; `AGENTS.md` is 1,471 lines, of which the first 246 are this
project's invariants and the rest is CrewAI's generated reference. The
gauntlet wants `AGENTS.md` = rules and `CLAUDE.md` = `@AGENTS.md`.

Recommendation as originally written (superseded by the decision above):

1. Move `CLAUDE.md` to `docs/handoff.md` unchanged — it *is* a handoff document and every cross-reference into it survives a path change.
2. Prepend the gauntlet's rules block to `AGENTS.md`'s project section, with three corrections the audit forces: the price rule reads "**$1.00 / 1M input tokens**, enforced by `tests/test_model_ceiling.py`"; "Plans in `.agent/plans/`" names the collision with `.agents/skills/` (vendored MIT CrewAI skills) and `agents/` (the authoritative specs) so nobody merges them; and the invariants a fresh file would otherwise regress are carried forward verbatim — prompts in YAML for library crews, constants in `config.py`, no `crewai[litellm]`, embeddings through `brief_crew.embeddings`, `SYNTHETIC=1` is a factory swap.
3. `CLAUDE.md` becomes two lines: `@AGENTS.md` and a pointer to `docs/handoff.md`.
4. Smoke-test with the absurd-rule trick before anything else is built.

The paste-ready text, with all three corrections applied and the smoke-test
rule included, is `.agent/RULES.draft.md`, now targeted at the top of
`CLAUDE.md`. The plan set is complete and buildable without it.

### D11 — Verification is layered, and the judge loop is real

Unit: `unittest` (1,228 at `b4ef654`) and Vitest (1,024) — not re-run this
pass. Mirrors: every client copy of server truth is a Python-generated
fixture byte-compared by a Python test (`tests/builder/test_client_fixtures.py`);
new mirrors (problem codes, model registry, vocabulary) follow the same rule.
E2E: Playwright against a `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5
PORT=8099` backend, already at the gauntlet's **1440×900** viewport
(`playwright.config.ts:57`); `390×844` is added. Judge: `benchmarks/reference/`
holds Flowise and ChatDev captures made locally, `benchmarks/DEFECTS.md`
holds every open comparison defect, and the critic is a fresh agent with the
plan file, the captures and nothing else.

## Boundaries and data flow

```text
 browser (Vue 3, Vue Flow)                         Node (Hono + Better Auth)
 ┌───────────────────────────┐   cookie session    ┌──────────────────────┐
 │ #/build   canvas, palette,│◄───────────────────►│ /api/auth/*  Google  │
 │           inspector, test │   15-min JWT         │ JWKS at /api/auth/jwks│
 │ #/        run console     │◄────────┐           └──────────┬───────────┘
 └─────────────┬─────────────┘         │                      │ offline verify
               │ bearer JWT            │                      ▼
               ▼                       │           ┌──────────────────────┐
 ┌─────────────────────────────────────┴─────┐     │ FastAPI (Python)     │
 │ /api/builder/*  documents, validate,      │     │  service/auth.py     │
 │                 vocabulary, registry,     │     │  builder_api.py      │
 │                 credentials, skills, mcp  │◄────┤  builder_runner.py   │
 │ /api/sessions/{id}/runs  launch, test,    │     │  registry.py         │
 │                 node-test, resume-from    │     │  events/ (frames)    │
 │ /ws  frames: node, edge_traversal,        │     └──────────┬───────────┘
 │      utterance, tool, gate, metrics       │                │
 └───────────────────────────────────────────┘                ▼
                                                   ┌──────────────────────┐
   document ──parse──▶ bounds ──price──▶ compile ──▶│ crewai.flow/v1       │
   (builder.flow/v2)                               │ Flow.from_declaration│
                                                   │ Agent/Task/Crew      │
                                                   │ mcps, skills, tools  │
                                                   └──────────┬───────────┘
                                                              ▼
                                        OpenRouter (only), tool APIs with the
                                        user's credential, MCP servers
```

Persistence is one PostgreSQL (Render) / SQLite (local) through
`service/persistence.py`; **new tables are safe with `create_all()`, new
columns on shipped tables are not** (`persistence.py:533-546`) — every plan
that adds a column adds a row to `_ADDITIVE_COLUMNS`.

## Interfaces — the contracts index

Each contract is frozen in the owning plan's *Interfaces* section before
implementation. The Integrator (S9) owns every change to one of these; a
silent drift is a P0.

| # | Contract | Owner | Consumers |
| --- | --- | --- | --- |
| C1 | `builder.flow/v2` document schema — node kinds, families, attachment ports, `llm`, `state`, `retry`, `error` ports, joins `all`/`any` | 03 | 02, 04, 09, 12, 13, 14, 15 |
| C2 | `GET /api/builder/vocabulary` v2 — kinds, ports, tiers, registry summary, tool catalogue, problem codes, bounds | 03 | 02, 04, 05, 06, 12 |
| C3 | Model registry JSON (`data/models.json`) and `GET /api/builder/models` | 05 | 04, 06, 09, 10, 14 |
| C4 | Credential API and run-time resolution (`user_credentials`, `/api/builder/credentials`, `credential_id` on tool / mcp / llm) | 01 | 06, 07, 09, 10 |
| C5 | Compiled definition shape and `BUILDER_ACTION_REFS` (eleven refs, `runtime:replay_output` added); the budget response gains `per_node: {node_id: {calls, usd}}` for the inspector's per-node cost line (requested by 04) | 09 | 04, 10, 13 |
| C6 | Frame details: `utterance`, `edge_traversal`, `node_error`, `retry`, `stage` — `details.stage` discriminators over the existing `FrameKind` values (`events/models.py:20`), not new enum members | 10 | 11, 12, 13 |
| C7 | Run API additions: `mode ∈ {run, test, dry_run, node_test}`, `resume_from`, `test_input_id`; `GET /api/runs/{id}/state`; `GET /api/builder/workflows/{id}/compiled`. `CreateRunRequest` is `service/models.py:125` (`gates` at `:162`) and `RunSnapshot.result` at `:398` — CLAUDE.md's `:106-118` / `:309` are stale | 10 | 13, 12 |
| C8 | Problem-code union and the client fixture — 30 → 57 codes, `WARNING_CODES` six, an optional `field` on the payload | 12 | 02, 03, 04, 06, 07, 08 |
| C9 | Template fixtures (`frontend/tests/fixtures/templates/*.json`, Python-generated) | 14 | 15, E2E |
| C10 | Persistence tables and additive columns | 15 | 01, 06, 07, 08, 13 |
| C11 | Skill package layout on disk (`data/skills/<user>/<skill>/SKILL.md`) and `/api/builder/skills` | 08 | 04, 09 |
| C12 | MCP server record and discovery result (`/api/builder/mcp/servers`, `/discover`) | 07 | 04, 06, 09 |

## Stage 0 — RAMP state, what exists and what is left

| | Item | State on 2026-09-02 |
| --- | --- | --- |
| R | `AGENTS.md` rules block, `CLAUDE.md` = `@AGENTS.md` | **Decision pending (D10).** Content drafted in D10. |
| A | `docs/crewai-notes.md`, `docs/flowise-notes.md`, `docs/chatdev-notes.md` | **Done**, from the installed package and the repos on disk. |
| A | `.agent/mcp.json` | **Done** — Playwright (browser) and OpenRouter (catalogue) named; both are configured at user level in this environment and neither is checked into the repo with a credential. |
| M | `.agent/plans/00…15` | **This set.** |
| P | Fallback ladder | Playwright MCP is live in this environment; `npx playwright test` against the synthetic backend is the second rung; the E2E recipe is in CLAUDE.md "Verified Baseline". |

## Stage 1 — ownership map

Files are owned exclusively. The table names the *repo paths* each agent
may write; a path not listed is the Integrator's.

| # | Agent | Plans | Writes under |
| --- | --- | --- | --- |
| S1 | Foundation & Auth | 00, 01, 15 | `service/auth.py`, `service/persistence.py`, `service/credentials*.py`, `builder/store.py`, `frontend/server/`, `frontend/src/services/authClient.ts`, `frontend/src/composables/useAuthGate.ts`, `frontend/src/composables/useBuilderPersistence.ts` |
| S2 | Canvas & Nodes | 02, 03 | `builder/document.py`, `builder/bounds.py`, `frontend/src/components/builder/{BuilderCanvas,BuilderNode,BuilderEdge,NodePalette,PortMenu,BuilderMinimap}.vue`, `frontend/src/composables/{useBuilderCanvas,useBuilderDocument,useBuilderHotkeys,useBuilderClipboard}.ts`, `frontend/src/utils/builderGraph.ts`, `frontend/src/data/nodeKinds.ts`, `types/builder.ts`, `frontend/src/assets/styles/{tokens,builder}.css` |
| S3 | Configuration | 04, 05 | `builder/registry.py`, `data/models.json`, `scripts/refresh_models.py`, `frontend/src/components/builder/inspectors/**`, `fields/**`, `frontend/src/data/{builderDefaults,builderVocabulary,models}.ts` |
| S4 | Extensions | 06, 07, 08 | `builder/tools.py`, `builder/mcp.py`, `builder/skills.py`, `service/builder_api.py` (tool / mcp / skill routes only), `frontend/src/components/builder/{ToolCard,McpServerPanel,SkillPanel}.vue` |
| S5 | Compiler & Runtime | 09, 10 | `builder/compiler.py`, `builder/runtime.py`, `builder/budget.py`, `builder/gates.py`, `service/builder_runner.py`, `service/registry.py` (builder paths), `events/serializer.py` |
| S6 | Run Visualizer | 11 | `frontend/src/components/{WorkflowNode,CrewProgress,DialogueRail,HandoffToken}.vue`, `frontend/src/composables/useValidatorRun.ts`, `useRunChoreography.ts`, `frontend/src/data/crewStages.ts`, `frontend/src/assets/styles/{node-card,motion}.css` |
| S7 | Resilience | 12, 13 | `frontend/src/components/builder/{ProblemsPanel,TestPanel,CodePreview}.vue`, `frontend/src/composables/{useBuilderValidation,useBuilderProblems,useFlowTest}.ts`, `service/builder_api.py` (validate / test routes), `tests/builder/test_failure_modes.py` |
| S8 | Templates | 14 | `frontend/src/data/templates/**`, `frontend/src/data/builderTemplates.ts`, `scripts/emit_builder_fixtures.py`, `frontend/tests/fixtures/templates/**` |
| S9 | Integrator | contracts, merges, E2E, gauntlet | `frontend/e2e/**`, `benchmarks/**`, `docs/**`, `config.py`, `tests/builder/test_client_fixtures.py`, `AGENTS.md`, `CLAUDE.md` |

`config.py` is Integrator-owned because every plan adds constants to it and
the single-writer rule is the only thing that keeps its knob count honest
(CLAUDE.md's "thirty-nine" paragraph is the record of what happens
otherwise). Fan-out: S2 / S3 / S4 after S1 clears; S6 / S7 / S8 after S5.

The environment knobs this set adds, collected from every plan so the §6
scan in `docs/tech-stack.md` is re-run once rather than argued about:
`CREDENTIALS_MASTER_KEY` (01), `MCP_ALLOWED_COMMANDS`,
`MCP_ALLOWED_ENV_VARS`, `MCP_ALLOW_INSECURE_LOCAL` (07), `SKILLS_ROOT` (08),
`SYNTHETIC_FAILURE`, `SYNTHETIC_FAILURE_NODE` (12),
`VALIDATOR_RUN_RETENTION_DAYS` (15). Thirty-nine becomes forty-seven; the
number is right only on the day the scan prints it.

## Acceptance criteria

1. `docs/crewai-notes.md`, `docs/flowise-notes.md`, `docs/chatdev-notes.md` exist, cite file:line into the installed package and the two repos, and section 11 of the CrewAI notes lists every point where the gauntlet and the package disagree.
2. Sixteen plan files `00`–`15` exist under `.agent/plans/`, each with Problem / Scope / Design / Interfaces / Acceptance criteria / References / Status, and no plan file's *Interfaces* section names a contract absent from the index above.
3. Every canvas node kind in C1 appears in the D3 table with a CrewAI primitive, and no row's primitive is deprecated at 1.15.18.
4. The supersession list in D2 names every ruling of `docs/flow-builder-spec.md` and every line of `AGENTS.md` this plan set overturns, by number, and `docs/flow-builder-spec.md` gains a one-paragraph header pointing here when the first feature lands.
5. The D4 price discrepancy is reproduced by `mcp__openrouter__get-model` (or the `scripts/refresh_models.py` it becomes) before `PRICES` is touched.
6. The Stage 1 ownership map has no path in two rows.
7. The D10 decision is recorded in `Status` below as *taken* or *declined*, with the date, before any feature file moves past *Planned*.

## References

- `docs/flow-builder-spec.md` §0 (R1–R15), §3, §5.5, §5.7, §9 (cut list) — the contract this set supersedes by number.
- `AGENTS.md:39, 55, 61-67, 92-95, 115, 199-206` — the enforced-by-construction table.
- `src/brief_crew/builder/{document,compiler,runtime,bounds,budget,store}.py`, `service/{builder_api,builder_runner,builder_rehydrate,auth,persistence,registry}.py` — audited 2026-09-02; line references throughout this set are against `25634c0`.
- `docs/crewai-notes.md` — Agent / Task / Crew / LLM / Flow / MCP / Skills / tools at 1.15.18.
- `docs/flowise-notes.md` — `D:\Flowise-main\Flowise-main\packages\ui\src\views\{canvas,agentflowsv2,tools,chatmessage,agentexecutions}`, `packages\server\src\{services\validation,utils}`, `packages\components\nodes\tools\MCP`.
- `docs/chatdev-notes.md` — `D:\ChatDev-main\frontend\src\{pages\LaunchView.vue,components\WorkflowNode.vue,utils\vueflow.css}`, `assets\launch.gif`.
- `docs/tech-stack.md` §2–§6, `docs/gotchas-and-insights.md` 14, 20, 22, 34, 35.
- CLAUDE.md §9 (admission), §13 (auth), §14 (builder), "OpenRouter MCP", remaining-work items 3, 40, 41.

## Status

**Planned.** Audit complete and all sixteen plan files written 2026-09-02.
Every contract request raised by 02–08 during writing (five plus five
problem codes, the `field` payload key, `budget.per_node`, the vocabulary's
`tools: [entry]`, three tables) is integrated into 12, 09, 03, 15 and the
index above; no plan references a contract outside C1–C12. D10 decision:
**declined 2026-09-02** — `CLAUDE.md` stays; `PLANS.md` tracks status. No
feature code written; nothing committed.


### S1 rulings — Integrator, 2026-09-02

Recorded here because 00 owns the contracts index and each of these is a
place where two plans disagreed, or where a plan consumed a contract that a
later stage owns and Stage 1 needs a stand-in. Every ruling names the plan
it binds; the plan files themselves are unchanged.

1. **`user_credentials.id` is `cr_` + 8 hex in a `String(128)` column** (C4
   over C10). 01 C4 wrote `VARCHAR(16)` and `^cr_[0-9a-f]{8}$`; 15 D6 wrote
   `cred_` + 16 hex. C4 owns the id shape, C10 owns the column type;
   `config.CREDENTIAL_ID_PATTERN` is the one place either is spelled. The
   indexes are 15 D6's: `ix_user_credentials_user_kind (user_id, kind)` and
   unique `(user_id, label)`.
2. **The C10 DDL is landed by the Integrator, before either S1 branch**, in
   `service/persistence.py`: the five new tables plus `runs.mode` on the
   `Table` and in `_ADDITIVE_COLUMNS`, with
   `tests/service/test_additive_migration.py::GauntletSchemaTests` (15 criterion
   7). 15 owns the shape; neither branch adds a column.
3. **`config.py` stays Integrator-owned**: `CREDENTIALS_MASTER_KEY`,
   `MAX_CREDENTIAL_BYTES`, `CREDENTIAL_ID_PATTERN`, `CREDENTIAL_KINDS`,
   `CREDENTIAL_FIELDS` and `VALIDATOR_RUN_RETENTION_DAYS` are landed with
   this ruling. A branch needing another constant asks for it rather than
   adding it; `docs/tech-stack.md` §6 is regenerated once, at integration,
   for 01 criterion 12 and 15 criterion 8.
4. **The export envelope's `export` field carries the document's own
   `schema` value.** 15 D1 wrote `builder.flow/v2`; C1 v2 is owned by 03,
   which is Stage 2. Today that is `builder.flow/v1`; the importer accepts
   both and passes the document through `upgrade_document` (15 D5), so a v1
   file imports unchanged now and a v2 file imports the day 03 lands.
5. **`upgrade_document` in Stage 1 is the hook, not the mapping.** It runs in
   the store's re-validation path, is pure and idempotent, and passes every
   committed v1 fixture through unchanged. The v1 → v2 field mapping in 15
   D5 lands with C1.
6. **`strip_for_export` works on the raw document dict**, before any schema
   validation, over key names — `credential_id`, `*_credential_id`,
   `server_id`, `skill_id` — so it covers the C1 v2 fields the day they
   exist and is testable today over a dict that carries them. A stripped
   `credential_id` becomes `null` and the node id goes to `needs_credentials`.
7. **Import is a server route**, `POST /api/builder/workflows/import`, taking
   the envelope and answering 201 with the same model shape as create plus
   `needs_credentials: [node_id, …]`. The client renders that list as an
   import notice group pointing at each node; it is not a C8 problem code,
   because C8's union is a Python-generated mirror and the only server-side
   `credential-missing` is the one 01 D10 emits from `validate`.
8. **`credential_id` on `AgentConfig` is Stage 1's stand-in for C1's field**,
   added by 01 alongside its compile-and-resolve path (01 D5, D7) with the
   pattern read from `config.py`; 03 absorbs it into v2 unchanged. Its client
   mirrors are regenerated by 01 in the same change.
9. **`usage.cost_usd.billed_to` (01 D7) is deferred to 10**, which owns C6
   and the cost frames. Stage 1 resolves a BYO key into `LLM(api_key=…)`;
   saying whose money it was is a frame-shape change and belongs with the
   other frame-shape changes.
10. **Open owner decisions are built on their recommendation** and stay open:
    23 (`VALIDATOR_RUN_RETENTION_DAYS` defaults to `0`), 24 (delete of a
    published-and-registered document refuses with 409), 25 (the PostgreSQL
    CI job runs on `main` only), 26 (unowned published workflows stay
    launchable).

### C10 amendments — round 2, 2026-09-03

Recorded here because C10 is indexed above and its body is plan 15 D6; the
plan carries the same note beside its table.

- **`builder_document_versions.source VARCHAR(64)`, nullable, through
  `_ADDITIVE_COLUMNS`** (plan 15 round 2, D-15-3). How a version came to be,
  for the version browser. The table shipped on 2026-09-02, so this is the
  second column to reach a deployed table by the additive path after
  `runs.mode`; `NULL` reads as `stored`, nothing is backfilled, and the
  upgrade is asserted against the shipped DDL. Consumers: 15 only.

### Owner decisions answered — 2026-09-04

**Decision 2 — taken, applied in `c9e8521`.** The rules block is now at the
head of `CLAUDE.md` and in force, amended in two clauses: parallel subagents
are authorized, and a money bound was added where the draft had none.
`.agent/RULES.draft.md` is history, not the live copy.
