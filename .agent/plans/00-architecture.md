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

Everything else in the spec — R1–R3, R5–R15, and cut-list items 3–8,
10–13, 15–17 — stands unchanged.

> **Corrected 2026-09-04: this sentence used to read `R5–R13, R15`, so R14
> appeared in neither list.** The spec runs R1–R15 — counted, not assumed:
> `grep -oE "R1[0-5]|R[1-9]" docs/flow-builder-spec.md | sort -V | uniq -c`
> returns fifteen distinct tokens. R14 — the idea-validator template ships
> agent-only with its caveat rendered verbatim — is **not** overturned:
> `14-templates.md` keeps it, caveat and all. So a ruling that stands was
> silently absent from the list of rulings that stand, which is the one failure
> mode a supersession list has. The same enumeration was repeated verbatim in
> `docs/flow-builder-spec.md`'s header and is corrected there in the same
> commit — a duplicated list drifts, and this one had already duplicated the
> omission rather than catching it.

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

`config.py` holds two models and two prices, and **both prices are exactly
right.** This paragraph claimed the opposite until 2026-09-04; the correction
is below, and producing it is what criterion 5 exists for.

Measured 2026-09-04 with `mcp__openrouter__get-model`, one call per cell:

| Model | `PRICES` in `config.py` | Live headline | `:batch` variant |
| --- | --- | --- | --- |
| `google/gemini-3.5-flash-lite` (cheap) | $0.30 / $2.50 | **$0.30 / $2.50** — identical | $0.15 / $1.25 |
| `google/gemini-3.8-flash` (escalation) | $0.75 / $3.75 | **$0.75 / $3.75** — identical | $0.375 / $1.875 |

> **What this table said before, and why it was wrong.** Its third column was
> headed *"Live catalogue headline"* and carried **$0.15 / $1.25** and
> **$0.38 / $1.88**, concluding that *"both prices are stale"*. Those are the
> **`:batch` variant** prices — confirmed by asking for
> `google/gemini-3.5-flash-lite:batch` directly, which answers $0.15 / $1.25.
> The headline price for the plain slug is what `PRICES` already held.
>
> So the discrepancy this criterion asks to reproduce **is not reproducible**,
> and the honest outcome is that the document was wrong and the code was right.
> It is worse than merely wrong: `config.py` rules the batch lane out on
> architectural grounds — batch is a queued lane, and a run with streaming
> frames and a human waiting at a gate cannot be queued — so the third column
> was quoting a price this system can never pay, as evidence that the price it
> does pay was stale.
>
> The escalation row also names a different model than it did: the tier moved
> to `gemini-3.8-flash` in `f19a2c6` on 2026-09-04, at an identical price.

The argument this paragraph was making survives its own correction, and is in
fact strengthened by it. One slug has **many** endpoint prices —
`list-model-endpoints` on 2026-09-01 showed flash-lite served by eight
endpoints from $0.15 to $0.54, a 3.6x spread — and `:nitro` routes on speed
rather than price, so a recorded rate is a **floor** and a real run can bill
above it. A hand-maintained two-row table cannot represent that. The fact that
this very table misread its own third column, and then reasoned from the
misreading, is the demonstration. `05-model-registry.md`
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

## FD — the reconstructed reference index

Nine plan files cite a reference called `FD` **26 times** — `FD2`, `FD3`, `FD4`,
`FD5`, `FD6`, `FD9`, `FD10`, `FD14`. **Nothing anywhere defined any of them.**
Regenerate rather than trust the sentence:

```bash
# --exclude this file, or the index counts its own definitions as citations
grep -rno "FD[0-9]\+" .agent/plans/ --exclude=00-architecture.md | wc -l          # 26
grep -rho "FD[0-9]\+" .agent/plans/ --exclude=00-architecture.md | sort | uniq -c
# 1·FD2  2·FD3  4·FD4  9·FD5  2·FD6  1·FD9  3·FD10  4·FD14   — measured 2026-09-04
```

> **These eight definitions were RECONSTRUCTED from the citations on
> 2026-09-04. They were not recovered from an original document, because there
> is no original document — not in this repository and not on this machine.**
>
> Searched and empty: the sixteen plan files, all of `docs/` (including
> `docs/flow-builder-spec.md`), and the gauntlet itself at
> `C:\Users\Simon\Downloads\gauntlet-crewai-visual-builder.md`, which contains
> the string `FD` **zero** times. `git log --all -S "FD5" --oneline` answers
> exactly one commit — `4d5f942`, the commit that *introduced* the plan set —
> so the reference was dangling the day it was written and has never resolved
> against anything inside the tree.
>
> Each row below is an inference from the sentences that cite it, and each row
> names the evidence that fixes it. Where the citations do not settle a
> question the row says so rather than choosing. **A reconstructed definition
> that is honest about being reconstructed is useful; one that presents itself
> as recovered is a trap for the next reader.** If the original ever surfaces,
> it wins, and the difference is a defect in this section.

**Only the eight cited numbers are defined.** `FD1`, `FD7`, `FD8` and
`FD11`–`FD13` are cited nowhere, so they are **undefined** — the numbering's own
logic is not reconstructable from eight samples, and guessing at it would be
inventing provenance, which this repository has been bitten by before
(remaining-work item 5, question 6: a REJECT floor citing a PRD word the PRD
does not contain). Do not invent one to fill a gap, and do not renumber: the 26
citations resolve where they stand, which is why this index lives here rather
than in nine edited files.

| Ref | Denotes | Owned by | What fixes it |
| --- | --- | --- | --- |
| **FD2** | The document schema version and the **v1 → v2 upgrade** — `upgrade_document(dict) -> dict`, pure, total and idempotent, run in the store's re-validation path so every stored row reads as v2 | **03 D4**; the store hook is 15 D5, and S1 ruling 5 above governs the Stage 1 stand-in | `03:30` scopes "the v1→v2 upgrade (FD2)" to this plan, and 03 D4 is the only section in the set that specifies it |
| **FD3** | The **node-kind vocabulary** — the ten kinds `input · agent · crew · gate · router · transform · output · tool · mcp · skill` and the two families (flow / attachment) | **03 D1** | `03:28` "the ten-kind vocabulary (FD3)"; `02:36` "three new node kinds (FD3)" — the three being `tool`, `mcp`, `skill`. 03 D1's table is exactly that |
| **FD4** | The **port table and the edge-class rules** — target ports (`in`, `attach`, `member`), source ports (`out`, `approve`/`revise`, branch labels, conditional `error`) per kind, and which sources each class accepts | **03 D1** (the table) with **03 D2** (the legality rules and their codes) | `02:35` names the three port classes; `02:88` names the rules verbatim — "`attach` accepts only tool/mcp/skill sources, `member` only agent sources, `in` refuses attachment kinds and member agents" — which is 03 D2's first three rows; `02:168` binds it to C1 |
| **FD5** | The **document field list** — every field each node kind carries, its tier, and the CrewAI primitive it compiles to. Nine citations, the most-depended-on of the eight, and the only one that had a live contradiction. **Resolved below.** | The schema is **03 D3** (C1); the placement and tiers are **04 D2**; the attachment configs are 06, 07 and 08. The canonical enumeration is **this section**, because it is the thing both cite and neither contains in full | `03:86` "The document (C1, spelled out in FD5)"; `04:14` "An authored agent has thirty-four (FD5)"; `04:55` "Every FD5 field, its widget, bound and source of truth"; `14:168` "which is why FD5 admits `'any'`" — `joins` is a `BuilderDocument` field, so FD5 spans the document, not only its nodes |
| **FD6** | The **bounds and the static budget model** — the structural counts a document is refused on, and the `modelled_calls` arithmetic those counts feed | **03 D2** (the structural half, reported never raised, R6) with **09 D4** (`modelled_calls`, retry multiplication, worst-case fallback pricing) | `03:29` "their bounds (FD6)" for authored agents and crews; `09:93` "The compiler's contribution is `modelled_calls` (FD6)". **Mildly ambiguous:** the pair could be read as bounds-only with 09 borrowing the label. They are given one entry because `bounds.py` and `budget.py` are one refusal surface — shape and money, checked together — and neither citation is coherent without the other |
| **FD9** | The **isolation rule** — one identity, every owned row SQL-scoped at the query, 404 never 403, and an unowned row readable by everyone | **00 D5** (the rule) with **01** (the routes that apply it); 15 D6 applies it per table | `15:128` is the only citation: "Every table carries `user_id` and is listed SQL-scoped, per FD9." That sentence is 00 D5's title almost word for word |
| **FD10** | The **runtime entrypoint contract** — the closed set of `BUILDER_ACTION_REFS` and the `with:` argument shape. Author data reaches an entrypoint as **values and opaque ids, never names, paths or code**; the entrypoint dereferences them against the run's user inside the call | **C5 / 09** (the ref set and the compiled `with:` block) with **10 D3** (the entrypoint bodies) | All three citations are the same sentence shape about `runtime:run_agent`'s arguments — `06:89` `credential_id` "as an opaque id (FD10)", `07:131` `mcps: [{server_id, tool_names}]`, `08:99` `skills: [skill_id]`. Every one is an id the runtime resolves, never a value the document carries |
| **FD14** | The **problem-code catalogue** — the union of validation codes with severity, grouped by area, mirrored client-side by a Python-generated fixture | **C8 / 12** | `06:292` "add `tool-param-invalid` beside the seven codes FD14 lists" — so FD14 enumerated per area; `07:240` "three codes beyond FD14"; `04:145` and `04:192` both read "every FD14 code with a fixed field", which is exactly C8's union |

### FD5 — the field list, and the 25-versus-34 contradiction resolved

Two plans stated different sizes for the same authored agent, and a subagent
told to *"render every FD5 field"* could satisfy neither:

- **03 D3** spells the fields out inline and names **25**.
- **04's Problem** says an authored agent "has **thirty-four** (FD5)", and is
  internally consistent about it — "the five that matter" and "the twenty-nine
  that rarely do" sum to the same 34.

**Both are right, and neither is the number of controls.** The two figures are
one field list counted at two depths, and the depth is the whole difference.
Three of 03 D3's names are *composites* — `task`, `llm` and `retry` — and 04 D2
places their sub-fields individually, because a form has a widget per leaf and
not per object. Expanded fully, 04 D2's authored-agent table is **41 leaf
controls**. Then:

```text
41 leaves
 − 4   task.{description, expected_output, output_schema, markdown, async_execution} → task
 − 10  llm.{model, temperature, top_p, max_tokens, timeout, response_format,
            frequency_penalty, presence_penalty, stop, seed, reasoning_effort} → llm
 − 2   retry.{max_retries, backoff_seconds, fallback_model} → retry
 = 25  ← 03 D3, every composite collapsed
```

```text
41 leaves
 − 4   task collapsed      (a Task is one primitive, edited as one object)
 − 2   retry collapsed     (builder-only, edited as one object)
 − 1   tier                (04 D2 renders it as a preset that SETS llm.model, bound
                            column "—"; it is a control over another field, not a field)
 = 34  ← 04, with `llm` expanded because a model's parameters are eleven separate widgets
```

The five that matter are then `role`, `goal`, `backstory`, `task`, `llm` — and
`34 − 5 = 29`, which is 04's own second figure, reached independently. **The
obvious hypothesis — that `llm` expanding into eleven is the whole story — is
very nearly right and is short by one:** it also needs `tier` not to count.
`35` is the honest total *with* `tier`, and `tier` is a real stored field: it is
on `_BillableConfig` (`document.py:175`) and `bounds.py` counts it against
`MAX_ESCALATION_NODES` on that word alone.

> **Ruling.** FD5's authored agent is **41 leaf controls / 35 document fields**
> once `llm` is expanded. **Neither plan needs editing**: 03 D3's **25** is
> correct at composite depth and 04's **34** is correct at leaf depth minus the
> tier preset. **The number to build against is the table below**, because
> "render every FD5 field" is a question about leaves and only a leaf list
> answers it.

Both counts were derived from the plan text, not asserted:

```bash
sed -n '86,99p'   .agent/plans/03-node-library.md         # D3's 25 names
sed -n '58,90p'   .agent/plans/04-inspector-and-params.md # D2's authored-agent table
```

#### The canonical table — authored `agent`

**Verified field by field against the installed package**, per the gauntlet's
own instruction for this section: *"Verify all of the above against the
installed CrewAI source. Where this document and the package disagree, the
package wins."* Regenerate the CrewAI column rather than trusting it:

```bash
PYTHONPATH=D:/MultiAgentSystem-wt/integration/src \
D:/MultiAgentSystem/.venv/Scripts/python.exe -c "
from crewai import Agent, Task, Crew, LLM
for m, c in (('Agent',Agent),('Task',Task),('Crew',Crew),('LLM',LLM)):
    for n, f in sorted(c.model_fields.items()):
        d = getattr(f,'deprecated',None) or ('DEPRECAT' in (f.description or '').upper())
        print(m, n, 'DEPRECATED' if d else 'ok')"
```

Tier is 04 D2's: **E** Essentials, **A** Advanced, **X** Expert. `—` in the
CrewAI column means *builder-only*: the field is ours, it configures the
compiler or the runtime, and no CrewAI attribute carries it.

| Field | CrewAI 1.15.18 | At 1.15.18 | Tier |
| --- | --- | --- | --- |
| `role` | `Agent.role` | ✓ | E |
| `goal` | `Agent.goal` | ✓ | E |
| `backstory` | `Agent.backstory` | ✓ | E |
| `tier` | — (pricing; `bounds.py` → `MAX_ESCALATION_NODES`) | — | E (preset) |
| `task.description` | `Task.description` | ✓ | E |
| `task.expected_output` | `Task.expected_output` | ✓ | E |
| `task.output_schema` | `Task.output_json` / `Task.response_model` via `create_model` | ✓ indirect — the document carries `json_schema`, the compiler builds the class (crewai-notes §11.8) | A |
| `task.markdown` | `Task.markdown` | ✓ | A |
| `task.async_execution` | `Task.async_execution` | ✓ | A |
| `llm.model` | `LLM.model` | ✓ | E |
| `llm.temperature` | `LLM.temperature` | ✓ | A |
| `llm.top_p` | `LLM.top_p` | ✓ | A |
| `llm.max_tokens` | `LLM.max_tokens` | ✓ (also `max_completion_tokens`) | A |
| `llm.timeout` | `LLM.timeout` | ✓ | A |
| `llm.response_format` | `LLM.response_format` | ✓ | A |
| `llm.frequency_penalty` | `LLM.frequency_penalty` | ✓ | X |
| `llm.presence_penalty` | `LLM.presence_penalty` | ✓ | X |
| `llm.stop` | `LLM.stop` | ✓ | X |
| `llm.seed` | `LLM.seed` | ✓ | X |
| `llm.reasoning_effort` | `LLM.reasoning_effort` | ✓ **but silently dropped for OpenRouter models** (`config.py:628`) — 04 D2 already gates it and says so in its help text | X |
| `max_iter` | `Agent.max_iter` | ✓ | A |
| `max_rpm` | `Agent.max_rpm` | ✓ | A |
| `max_execution_time` | `Agent.max_execution_time` | ✓ | A |
| `allow_delegation` | `Agent.allow_delegation` | ✓ | A |
| `memory` | `Agent.memory` | ✓ unified (`bool \| Memory \| MemoryScope \| MemorySlice`) — **not** three toggles | A |
| `cache` | `Agent.cache` | ✓ | A |
| `respect_context_window` | `Agent.respect_context_window` | ✓ | A |
| `guardrail_max_retries` | `Agent.guardrail_max_retries` / `Task.guardrail_max_retries` | ✓ | A |
| `prompt_inputs` | — (`${state.x}` interpolation, `document.py:105-123`) | — | A |
| `retry.max_retries` | — (the loop is inside `run_agent`, 09 D4 / 10 D3) | — | A |
| `retry.backoff_seconds` | — | — | A |
| `retry.fallback_model` | — | — | A |
| `on_error` | — (compiles to the conditional `error` port and its router) | — | A |
| `system_template` | `Agent.system_template` | ✓ | X |
| `prompt_template` | `Agent.prompt_template` | ✓ | X |
| `response_template` | `Agent.response_template` | ✓ | X |
| `tool_failure_policy` | `Agent.tool_failure_policy` | ✓ | X |
| `reasoning` | `Agent.reasoning` | **⚠ DEPRECATED** — `deprecated=True`, *"[DEPRECATED: Use planning_config instead]"* (`agent/core.py:318-322`) | X |
| `max_reasoning_attempts` | `Agent.max_reasoning_attempts` | **⚠ DEPRECATED** — *"[DEPRECATED: Use planning_config.max_attempts instead]"* (`core.py:323-327`) | X |
| `multimodal` | `Agent.multimodal` | **⚠ DEPRECATED** — *"[DEPRECATED, will be removed in v2.0 - pass files natively.]"* (`core.py:292-296`) | X |
| `function_calling_llm` | `Agent.function_calling_llm` | **⚠ DEPRECATED** — *"will be removed in a future release"* (`core.py:261-268`); deprecated on `Crew` too | X |

41 rows. Attachments (`tools`, `mcps`, `skills`) are deliberately **not** rows:
they are `attach` edges (FD4), they reach the constructor as
`Agent(tools=…, mcps=…, skills=…)` through the compiled `with:` block (FD10),
and 04 D2 renders them read-only precisely because Flowise v2's `agentTools`
array is the anti-pattern it is avoiding.

#### What the package refuses, and what nobody has decided

**Four rows above are deprecated at 1.15.18**, and this plan's own acceptance
criterion 3 says no row's primitive may be. That criterion is scoped to the D3
*kind* table, so it does not fail — but the same rule read one level down says
these four cannot ship as written. Each needs an Integrator ruling; **none is
decided here**, because a field is a contract and C1 is 03's.

| Field | The package's replacement | Note |
| --- | --- | --- |
| `reasoning` | `Agent.planning_config: PlanningConfig` | Not cosmetic. `core.py:418-427` builds a `PlanningConfig` out of `reasoning` / `max_reasoning_attempts` and emits a `DeprecationWarning`; `PlanningConfig` carries `llm, max_attempts, max_replans, max_step_iterations, max_steps, observe_steps, plan_prompt, reasoning_effort, refine_prompt, step_timeout, system_prompt`, so an Expert *switch* is no longer the right control for it |
| `max_reasoning_attempts` | `PlanningConfig.max_attempts` | as above |
| `multimodal` | pass files natively | The Expert switch has no replacement control |
| `function_calling_llm` | none named | 04 D2 gates it on `supports_tools`; it warns on both `Agent` and `Crew` |

`Agent.planning` and `Crew.planning` are **not** deprecated — only the
`reasoning` spelling is. Whatever replaces the three Expert rows, it is a
`planning_config` object, not a rename.

**Already cut, and the cut is confirmed correct.** `allow_code_execution` and
`code_execution_mode` are deprecated at `core.py:279-282` and `:305-308`
(*"CodeInterpreterTool is no longer available. Use dedicated sandbox services
instead."*) with a runtime warning at `:407-410`. Neither appears in 03 D3 or
04 D2. crewai-notes §11.1 and decision 3 (BYO E2B behind a flag, default off)
already own this.

**A name collision worth knowing before it costs a debugging session.** The
builder's `retry.max_retries` is **not** `Task.max_retries`. `Task.max_retries`
is itself deprecated at 1.15.18 — *"[DEPRECATED] … Use `guardrail_max_retries`
instead. Will be removed in v1.0.0"* (`task.py:275-278`), with a
`model_validator` that copies it across and warns (`task.py:574-583`) — and it
counts *guardrail* retries, where the builder's counts whole-node attempts
inside `run_agent`. `Task.retry_count` is a live counter (`default=0`), not a
setting. crewai-notes §11.2 says *"Render `max_retries`"*; **the package now
disagrees with that note**, and the package wins.

**Fields the gauntlet names that exist and no plan places.** Not defects — a
cut list is allowed — but they are cuts nobody has recorded, and an unrecorded
cut is indistinguishable from an oversight:

| Field | Exists | Why it is probably absent |
| --- | --- | --- |
| `Agent.verbose` | ✓ | Gauntlet Advanced. Console noise; the run console reads frames instead |
| `Agent.knowledge_sources`, `Agent.embedder` | ✓ | Gauntlet Expert. RAG is 06's surface, and crewai-notes §11.9 records that the RAG family embeds with OpenAI by default, which the platform rules forbid |
| `Task.tools` (per-task override), `Task.human_input`, `Task.output_file`, `Task.guardrail`, `Task.callback` | ✓ | `human_input` is the console prompt, not the durable gate — gates are `gate` nodes; `output_file` writes to ephemeral container disk; `callback` is code on a canvas |
| `LLM.stream` | ✓ | The gauntlet's LLM line names eleven fields *including* `stream`; 04 D2 also lists eleven, with `stream` swapped for `reasoning_effort`. A builder run streams frames by construction, so there is nothing for an author to decide |

#### The authored `crew` — 04 says fifteen, the prose names fourteen

04 D2's crew paragraph names, as stored fields: **E** `process`, `task_order`
(the member list is `member` edges; drag-to-reorder writes the order),
`manager_llm`, `manager_agent`; **A** `memory`, `cache`, `max_rpm`, `planning`,
`planning_llm`, `retry`, `on_error`, `prompt_inputs`; **X** none. With `retry`
expanded the same way as the agent's, that is **fourteen** leaves.

| Field | CrewAI 1.15.18 | At 1.15.18 |
| --- | --- | --- |
| `process` | `Crew.process` (`Process.sequential` / `hierarchical`) | ✓ |
| `task_order` | — (member edge order → the `Crew.tasks` order) | — |
| `manager_llm` | `Crew.manager_llm` | ✓ — `crew.py:729` raises when hierarchical and neither manager is set |
| `manager_agent` | `Crew.manager_agent` | ✓ |
| `memory` | `Crew.memory` | ✓ unified; `short_term_memory` / `long_term_memory` / `entity_memory` are **absent from the model** |
| `cache` | `Crew.cache` | ✓ |
| `max_rpm` | `Crew.max_rpm` | ✓ |
| `planning` | `Crew.planning` | ✓ (not deprecated — unlike `Agent.reasoning`) |
| `planning_llm` | `Crew.planning_llm` | ✓ |
| `retry.max_retries` / `.backoff_seconds` / `.fallback_model` | — (the loop is inside `run_crew`) | — |
| `on_error` | — | — |
| `prompt_inputs` | — | — |

> **UNRESOLVED — an Integrator ruling, not a reconstruction.** Fourteen is what
> the prose names; 04 says fifteen. Exactly one field is missing and the
> evidence does not say which, so picking one on judgement would be inventing
> the reconciliation this section exists to prevent. Three candidates:
>
> 1. **`verbose`** — the gauntlet's Crew *Essentials* names it, `Crew.verbose`
>    exists and is not deprecated, and 04's *agent* list drops `verbose` too,
>    so dropping it twice would at least be consistent. Most likely of the three.
> 2. **`tier`** — `CrewConfig` inherits it from `_BillableConfig`
>    (`document.py:175`) and 03 D3 says the authored crew is the "same shape",
>    so it is a stored field the crew paragraph does not mention. But it also
>    inherits `max_iter` and `guardrail_max_retries`, which would make the total
>    seventeen — so this candidate does not close cleanly either.
> 3. **members counted separately from `task_order`** — arithmetically exact,
>    but it counts a derived read-only list as a field, contradicting the same
>    paragraph's own reason for showing it read-only.
>
> Until this is ruled on, **build the fourteen above** and treat 04's "fifteen"
> as unverified. Whichever way it goes, the ruling belongs here and in 04's
> `Status`, not in a builder's head.

#### The other kinds

FD5 covers the whole document, not only the agent. The remaining kinds are
specified in full by their own plans and are **not** restated here — a contract
lives in one file:

| Kind | Fields | Specified in |
| --- | --- | --- |
| library `agent` / `crew` | `agent_id` / `crew_id`, `tier`, `tools`, `max_iter`, `guardrail_max_retries`, `prompt_inputs`, `credential_id` | `document.py:175-230` today; 03 D3 makes each a union arm discriminated by presence and refuses both-or-neither at parse |
| `tool` | `{tool_id, credential_id \| null, params}` | 06 (`06:27`, `06:230`) |
| `mcp` | `{server_id, tool_names[]}`, plus `pinned_args` if C1 v2 takes 07's request | 07 (`07:33`, `07:193`) |
| `skill` | `{skill_id}` | 08 (`08:42`, `08:176`) |
| `gate`, `router`, `transform`, `input`, `output` | unchanged from v1 | `document.py`; 04 D2 leaves their forms alone |
| document level | `schema`, `state: FlowStateSchema \| None`, `joins` accepting `'all' \| 'any'`, `budget`, positions | 03 D3. `14:168`'s citation is this row: `joins: 'any'` is an FD5 admission, and it is what lets the router template's three mutually exclusive branches converge instead of waiting forever |

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
| S4 | Extensions | 06, 07, 08 | `builder/tools.py`, `builder/mcp.py`, `builder/skills.py`, `frontend/src/components/builder/{ToolCard,McpServerPanel,SkillPanel}.vue` |
| S5 | Compiler & Runtime | 09, 10 | `builder/compiler.py`, `builder/runtime.py`, `builder/budget.py`, `builder/gates.py`, `service/builder_runner.py`, `service/registry.py` (builder paths), `events/serializer.py` |
| S6 | Run Visualizer | 11 | `frontend/src/components/{WorkflowNode,CrewProgress,DialogueRail,HandoffToken}.vue`, `frontend/src/composables/useValidatorRun.ts`, `useRunChoreography.ts`, `frontend/src/data/crewStages.ts`, `frontend/src/assets/styles/{node-card,motion}.css` |
| S7 | Resilience | 12, 13 | `frontend/src/components/builder/{ProblemsPanel,TestPanel,CodePreview}.vue`, `frontend/src/composables/{useBuilderValidation,useBuilderProblems,useFlowTest}.ts`, `tests/builder/test_failure_modes.py` |
| S8 | Templates | 14 | `frontend/src/data/templates/**`, `frontend/src/data/builderTemplates.ts`, `scripts/emit_builder_fixtures.py`, `frontend/tests/fixtures/templates/**` |
| S9 | Integrator | contracts, merges, E2E, gauntlet | `frontend/e2e/**`, `benchmarks/**`, `docs/**`, `config.py`, `tests/builder/test_client_fixtures.py`, `AGENTS.md`, `CLAUDE.md` |

> **Corrected 2026-09-04.** `service/builder_api.py` appeared in **both** S4
> ("tool / mcp / skill routes only") and S7 ("validate / test routes"), which
> the preamble's own rule — *files are owned exclusively* — forbids. The two
> route carve-outs are genuinely disjoint, so nothing had gone wrong yet; what
> had gone wrong is that the map said something it did not mean, and the next
> reader resolves that by guessing. It is removed from both rows, which by the
> preamble's own *"a path not listed is the Integrator's"* default makes it
> Integrator-owned — the same answer, for the same reason, that `config.py`
> already gets below. S4 and S7 still contribute those routes; they do it
> through the Integrator, who owns the file.
>
> Related, and deliberately **not** changed: `service/persistence.py` is S1's
> in the map while S1 ruling 2 reserves its C10 DDL to the Integrator. That is
> one path in one row with a carve-out inside a ruling, not a path in two rows,
> so criterion 6 does not turn on it — but it is the same shape of ambiguity,
> and whoever touches that file next should read ruling 2 first.

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


### Criteria complete — 2026-09-04

All seven verified against the tree at `9f98d5a` by a fresh-context agent that
ran each check itself, then two documentary defects were repaired and the two
failing criteria re-checked. **Five held on first inspection; two did not, and
both were the document being wrong rather than the code.** That ratio is the
argument for the criterion being a command rather than a claim.

| # | State | Evidence |
| ---: | --- | --- |
| 1 | holds | Three notes files exist with the required sections; §11 of the CrewAI notes lists the gauntlet/package disagreements. **Nine `file:line` citations spot-checked and all nine exact**, including two `crewai/agent/core.py` deprecation lines, `crew.py:729`'s error string, ChatDev's `clamp(pathLength × 0.02, 2000, 4000)` and Flowise's 5×20 handle. Both reference repos are on disk |
| 2 | holds | Sixteen plan files `00`–`15`, each carrying all seven required sections; every contract token in every *Interfaces* section falls inside the C1–C12 index |
| 3 | holds | Every C1 node kind appears in the D3 table with a CrewAI primitive, and each named primitive was resolved in the installed package at 1.15.18 and is not deprecated |
| 4 | **holds after a fix** | The supersession list names its overturned rulings by number and `docs/flow-builder-spec.md` carries the pointing header. **But the companion clause read `R1–R3, R5–R13, R15`, so R14 was in neither list** — the spec runs R1–R15 and R14 stands (`14-templates.md` keeps the idea-validator template and its caveat). Corrected here and in the spec header, which had duplicated the omission verbatim rather than catching it |
| 5 | **holds after a fix** | The check was run with `mcp__openrouter__get-model` **before** `PRICES` was touched, which is what the criterion asks. What it found is that **the discrepancy does not exist**: flash-lite is $0.30 / $2.50 live and `gemini-3.8-flash` is $0.75 / $3.75, both identical to `PRICES`. D4's third column was the **`:batch` variant**, mislabelled as the headline — a price this system can never pay, quoted as evidence that the price it does pay was stale. D4 is rewritten with the measured figures. `PRICES` was consequently **not** changed by `f19a2c6`; only the constant beside it moved |
| 6 | **holds after a fix** | `service/builder_api.py` was listed under **both** S4 and S7, which the map's own *"files are owned exclusively"* rule forbids. Removed from both, which by the map's *"a path not listed is the Integrator's"* default makes it Integrator-owned — the same treatment `config.py` already gets. The `service/persistence.py` / ruling-2 tension is noted beside it and deliberately left, because it is one path in one row and this criterion does not turn on it |
| 7 | holds | D10 recorded in this Status as **declined 2026-09-02**, dated, and `PLANS.md` decision 1 agrees |

**What is NOT claimed.** Criteria 1–3 and 7 were verified by a delegated agent
and their evidence is that agent's, re-read but not independently re-run here;
4, 5 and 6 were repaired and re-checked directly. No judge round has run
against this plan, so it is **not** `Built` — plan 00 owns rubric dimension 16
(RAMP integrity), which is scored at the whole-product gauntlet, and its gate
is the last thing this programme closes rather than the first.

**Two of the seven failed, and both failures were a document asserting
something nobody had re-measured.** That is the same failure mode this
repository has recorded six times about its own counts, appearing here in the
plan whose job is to prevent it. The lesson is not that the author was careless
— D4's mislabelled column is a genuinely easy mistake, and the R14 omission was
faithfully copied into a second file. It is that a supersession list and a
price table are both claims, and a claim in this repository is worth what its
last regeneration is worth.


### S9 ruling — the deprecated fields the plan set renders, 2026-09-04

Raised while reconstructing the `FD` index above, and settled here because C1
is a contract and the Integrator owns every change to one. The governing rule
is already written twice — the rules block's *"where the gauntlet and the
installed package disagree, the package wins"*, and **this plan's own criterion
3**, *"no row's primitive is deprecated at 1.15.18"*.

Scanned across **all three** mechanisms CrewAI uses to mark a field deprecated,
because a scan that knows only the first under-reports and would pass criterion
3 for the wrong reason:

```text
Field(deprecated=True)     Agent.reasoning, Agent.max_reasoning_attempts,
                           Agent.multimodal, Agent.allow_code_execution,
                           Agent.code_execution_mode
Field(deprecated="msg")    Agent.function_calling_llm, Crew.function_calling_llm
description + validator    Task.max_retries          <- FieldInfo.deprecated is None
```

Eight in total. Two were already cut by the plans (`allow_code_execution`,
`code_execution_mode`, `crewai-notes.md` §11.1). The ruling on the other six:

| Field | Ruling | Why |
| --- | --- | --- |
| `Agent.multimodal` | **cut** | deprecated "removed in v2.0 — pass files natively". A control for a field that disappears at the next major is a trap, not a feature |
| `Agent.function_calling_llm` | **cut** | deprecated on `Agent` *and* `Crew`; nothing in this product sets it |
| `Crew.function_calling_llm` | **cut** | as above |
| `Agent.reasoning` | **replaced** by `Agent.planning` (bool) | `agent/core.py:418-427` already folds `reasoning` into a `PlanningConfig` and warns. The switch an author sees should be the one CrewAI keeps |
| `Agent.max_reasoning_attempts` | **replaced** by `planning_config.max_attempts` | same migration |
| `Task.max_retries` | **not rendered**; use `guardrail_max_retries` | already the builder's own field name on `_BillableConfig`, so this costs nothing. **Watch the collision:** the builder's `retry.max_retries` is a NODE-level retry and is a different concept |

**`planning_config` is bounded to four of its eleven fields** —
`reasoning_effort`, `max_attempts`, `max_steps`, `max_replans`. Those four bound
cost and iteration, which is what this product has to care about. The three
prompt overrides (`system_prompt`, `plan_prompt`, `refine_prompt`) are
deliberately excluded: prompts for this repository's crews live in YAML and an
authored agent's live in the author's document, and a third place would be a
third place. `planning_config.llm` is excluded because it would silently put the
planner on a different model from the one the node names, which is a cost
surprise with no visible cause.

**The field counts move, and they are NOT restated here.** The `FD5` table above
is the canonical list; regenerate the totals from it rather than carrying the
41 / 34 / 25 figures forward through this ruling. That is the discipline the
whole of the 2026-09-04 pass exists to enforce, and this is the first place it
would be easy to break.

**One consequence for a decision still open.** PLANS.md decision 3 — the code
interpreter, BYO E2B key behind a flag — is marked *provisional, owner to
confirm*. CrewAI's own code-execution surface (`allow_code_execution`,
`code_execution_mode`) is **deprecated**, so the native path is going away
regardless of what the owner decides. That is a new argument the decision was
not made with, and it is recorded here rather than acted on.


### S9 ruling — the crew's fifteenth field is `verbose`, 2026-09-04

The `FD5` reconstruction above closed the authored **agent** at 41 leaves and
left the **crew** one short: plan 04 says fifteen, its own prose names fourteen,
and three candidates were escalated rather than guessed. Correctly — but the
evidence does settle it.

It is **`verbose`**, on three grounds:

1. The gauntlet spec's own *Crew (canvas root) — Essentials* line reads
   `process (sequential/hierarchical), verbose`. `process` is in plan 04's
   fourteen and `verbose` is not, so the omission is on our side of the copy.
2. `Crew.verbose` exists at CrewAI 1.15.18 and is **not** deprecated — checked
   in the same scan that found the eight that are.
3. The two rival candidates each break something. `tier` cannot be it: `tier`
   arrives from `_BillableConfig` and drags `max_iter` and
   `guardrail_max_retries` with it, giving seventeen rather than fifteen.
   Counting members separately from `task_order` is arithmetically exact and
   contradicts the paragraph's own reasoning, which treats membership as one
   thing.

So: **build fifteen, with `verbose` as the fifteenth.** If a later pass finds a
better candidate, the number is not the thing to preserve — the enumeration is.


### S9 ratification — C8's optional `field` is implemented, not changed, 2026-09-04

Plan 04's build added `field: str | None = None` to `bounds.Problem` and
`BuilderProblemModel`, set it on the three model codes in `registry.py`, and had
`useBuilderProblems.fieldFor` prefer it over `FIELD_CODES`. It flagged the change
rather than making it silently, because `bounds.py` is S2's and
`service/builder_api.py` is the Integrator's. **Ratified**, on two grounds.

**It implements a frozen contract.** C8's own index row above already reads
*"an optional `field` on the payload"*, and the `field` payload key is named in
this plan's list of contract requests integrated during plan-writing. Nothing
was widened; something specified was finally built.

**Criterion 3 is unreachable without it, and the reason generalises.**
`FIELD_CODES` maps a problem CODE to a control. Plan 04 criterion 3 needs
`model-lacks-capability` to anchor at `llm.response_format` on one node and at
`llm.reasoning_effort` on the next — and **one string per code cannot say two
different things**. A code-keyed map answers "which control does this KIND of
problem belong to"; the payload answers "which control does THIS problem belong
to". Only the second can carry a problem an author can click.

`FIELD_CODES` stays as the fallback rather than being deleted: a code with a
fixed field needs no payload, and criterion 7's total partition over
`PROBLEM_CODES` is what proves the fallback still covers everything the payload
does not.


### S9 ratification — `BuilderJoins` widened to `'all' | 'any'`, 2026-09-04

Plan 14's build widened `types/builder.ts`'s `BuilderJoins` from
`Record<string, 'all'>` to `Record<string, 'all' | 'any'>` and asked whether that
reads as a mirror repair or a C1 change. **Mirror repair. Ratified.**

The server has admitted both words since 03 D3, and it is not incidental —
`document._validate_joins` refuses a third word *by name*, and the two it
accepts compile to **two different shapes**: `"all"` is `{"and": [...]}` and
`"any"` is the alternatives. The client type was simply a generation behind the
schema it mirrors.

Worth recording *why* `"any"` is safe, because somebody will want to re-tighten
it. The measured `or_()` defect is real: a multi-event `or_()` listener is added
to `_fired_or_listeners` the first time it fires and skipped forever after, so a
second arrival ends the run silently. But that is a fact about a MULTI-EVENT
condition, and it is not what `"any"` compiles to — `_listen_for` builds
alternatives, each one a router label, only one fires per pass, and CrewAI
re-arms an or-listener whose condition names the label a router just emitted.
That is what "the first arrival wins" means, and it is what lets a router's
mutually exclusive branches converge on one node instead of waiting forever for
the branch nobody took.

A mirror narrower than its source is the same class of defect as one wider: both
mean the client is reasoning about a different contract than the server
enforces. This one would have rejected a document the server accepts.


### Decision 11 answered, and where today's contract log lives — 2026-09-04

**Decision 11 is no longer *not answerable*: the licence is MIT.** It was the
one ruling in `PLANS.md`'s table that could not be made rather than had not
been — it asks for a licence header on the four built-in skill packs, and there
was no repository licence for a header to name. `LICENSE` is now at the root
with `license = "MIT"` in `pyproject.toml` and `"license": "MIT"` in
`frontend/package.json` (`e7dfb86`), and the four packs carry `license: MIT` in
their frontmatter (`f122322`). `docs/licensing.md` records the decision and its
scope, including what it deliberately does **not** cover: the vendored MIT
skills keep their own notices, and the third-party reference captures under
`benchmarks/reference/` stay uncommitted.

**The Integrator's contract log for today is in [`PLANS.md`](../../PLANS.md)'s
`## Log`, not here.** Plans 11, 12 and 13 built; the six wave A/B backend
closers and the six integration closers; the eighteen-row round-3 build; and
judge round **product-1**, the first whole-product gauntlet — seventeen ledger
rows verified absent and closed, one (D-15-2) present for the fourth round
running, four dimensions under the gate. The entry is named here only so a
reader of this plan is not left to discover it by grep. One contract figure did
move in the wave and its plan carries it rather than this index: **C8 is at 57
problem codes and `WARNING_CODES` at 7**, both of plan 12's two new codes
carrying the optional `field` this Status ratified above
(`12-error-handling.md`, criterion 1).
