# 07 — MCP client

## Problem

MCP is the highest-leverage item in the build: a user pastes a server URL
or a stdio command, the product introspects it, and a finite tool
catalogue becomes an open surface. Nothing in this repository touches MCP —
`grep -ri mcp src/ tests/` returns zero hits — and nothing needs to be
installed to change that. CrewAI 1.15.18 carries native MCP on the agent:

```python
Agent.mcps: list[str | MCPServerStdio | MCPServerHTTP | MCPServerSSE] | None
```

with three config models in `crewai/mcp/config.py`, a resolver
(`crewai/mcp/tool_resolver.py:81-120`) that discovers tools with retry
(`:572`) and reads their schemas (`:534`), and seven event types in
`crewai/events/types/mcp_events.py` (`MCPConnectionStarted/Completed/Failed`,
`MCPToolExecutionStarted/Completed/Failed`, `MCPConfigFetchFailed`). The
work is a record, a discovery endpoint, a node, and the security posture
Flowise arrived at after shipping without one.

One package fact shapes everything: **a bare string in `mcps` is a CrewAI
AMP marketplace reference unless it starts with `https://`**
(`tool_resolver.py:87-89`, `_parse_amp_ref` at `:121`). User input is
therefore never passed as a string; the runtime always builds a config
object.

## Scope

- `mcp_servers` table, per user, holding transport, address, credential references and the last discovery result.
- `POST /api/builder/mcp/servers/{id}/discover`: connect with the native client under a timeout, return sanitised tool names, descriptions and input schemas, store them on the row.
- The `mcp` attachment node `{server_id, tool_names[]}` whose card and inspector are generated from the discovered schemas.
- Run-time construction of `Agent.mcps` from the record with header credentials resolved through C4.
- Transport policy: HTTP (streamable) and SSE always; stdio only for commands on an allow-list that is empty by default.
- MCP events mapped to tool frames.

## Out of scope

- Author-pinned tool arguments (`pinned_args`). The agent supplies arguments at run time from the schema; a v2 contract request is recorded in Status.
- OAuth flows to MCP servers. v1 supports a static header credential; OAuth is a v2 item once Better Auth's token store can hold third-party tokens.
- Running MCP servers for users. The product connects to servers; it hosts none.
- Sampling, prompts and resources from the MCP spec. Tools only, which is what `Agent.mcps` consumes.

## Design

### D1 — A server is a per-user record, and the record never holds a secret

Flowise stores a workspace-level `CustomMcpServer` with encrypted auth
headers and shows the URL masked in lists (`docs/flowise-notes.md` §7).
Here the row holds the address and **references** to credentials: a
`header_credential_id` (kind `mcp_header`, the header **value**) beside a
plaintext `header_name` (e.g. `Authorization`), and an `env_credential_id`
for stdio servers that need a key in their environment. The value is
resolved through `resolve_credential` (C4) inside the discovery handler
and inside `runtime:run_agent`, and appears in no row, frame, log or
export. Lists show `url` masked to origin plus `/************`, exactly as
Flowise does.

### D2 — Discovery uses the package's own client, bounded, in a worker thread

`builder/mcp.py::discover(config, timeout) -> DiscoveredTool[]` builds the
config object for the transport (D4), runs `MCPToolResolver().resolve([config])`
to obtain `BaseTool`s, reads `name`, `description` and
`args_schema.model_json_schema()` from each, then calls `cleanup()` so no
client outlives the request. It runs under
`MCP_DISCOVERY_TIMEOUT_SECONDS = 20` in a sync `def` route so FastAPI's
threadpool absorbs the block, the way `current_user` absorbs a JWKS fetch
(`app.py:721-724`). A failure is a 200 with `status: error` and one
sentence — *"could not connect: <reason>"* — because the user needs the
sentence in the panel, not a stack trace in a toast. The result is stored
on the row (`discovered_tools`, `discovered_at`) so the inspector never
needs a live server to render, and `cache_tools_list=True` is set on the
run-time config so the agent's own discovery is served from CrewAI's
cache.

### D3 — Names and descriptions are sanitised before they reach a prompt

An MCP server's tool descriptions land verbatim in the agent's tool list,
which is a prompt. Flowise's `core.ts` treats that as the injection
surface it is; this plan copies the rules, not the code:

- **name**: `[^a-zA-Z0-9_-] → _`, max 128 (`MCP_TOOL_NAME_MAX_CHARS`).
- **description**: strip C0 controls and `​-‍     ‪-‮ ⁠ ﻿`; truncate at 1,024 (`MCP_TOOL_DESCRIPTION_MAX_CHARS`); test against thirteen patterns (`\bYOU\s+MUST\b`, `ignore\s+(previous|all|above|prior)\s+instructions?`, `disregard`, `system\s*prompt`, `new\s+instructions`, `act\s+as`, `you\s+are\s+now`, `override`, `jailbreak`, `\bDAN\b`, `do\s+anything\s+now`, `pretend`, `roleplay` — case-insensitive) and mark the tool `suspicious: true`.
- A suspicious tool is **still listed**, unchecked by default, with the matched pattern shown; selecting it yields a warning-level problem so the author decides with eyes open (see Status — code request).

The sanitised form is what is stored, what the card shows, and what
`tool_filter` matches at run time — so a server that renames a tool
between discovery and run simply fails to match and the agent runs
without it, reported as `mcp-tool-unknown` on the next validate.

### D4 — Transport policy

| `transport` | Config | Allowed when |
| --- | --- | --- |
| `http` | `MCPServerHTTP(url, headers, streamable=True, tool_filter, cache_tools_list=True)` | always; `https://` required except `127.0.0.1` / `localhost` under `MCP_ALLOW_INSECURE_LOCAL=1` |
| `sse` | `MCPServerSSE(url, headers, tool_filter, cache_tools_list=True)` | same URL rule |
| `stdio` | `MCPServerStdio(command, args, env, tool_filter, cache_tools_list=True)` | `command` is on `MCP_ALLOWED_COMMANDS` (comma-separated env, **empty by default**), `args` contain no shell metacharacters, no `cwd`, `env` keys on `MCP_ALLOWED_ENV_VARS` |

Flowise arrived at the same allow-list shape
(`CUSTOM_MCP_ALLOWED_COMMANDS`, `docs/flowise-notes.md` §7) and its streamable
HTTP-first, SSE-fallback client (`core.ts:128-165`); here the transport is
per server, not a global switch, because the global switch is the thing
its own UI has to warn about. Production (`render.yaml`) sets no
`MCP_ALLOWED_COMMANDS`, so a deployed instance is remote-only; a local
developer can allow `npx` and `uvx`. URLs pass the same SSRF rule the
custom HTTP tool uses (06 D7): resolve, refuse private / loopback /
link-local, no redirects off HTTPS.

### D5 — The node is generated from the schema, and the agent keeps the arguments

An `mcp` node references a server and a checked subset of its tools. Its
card shows the server label, the transport chip, and *"N of M tools"*;
its inspector shows the discovered tools as a checklist with each tool's
description, and for a checked tool a **read-only parameter preview**
rendered from `input_schema` — property names, types, required marks,
descriptions — so the author sees what the agent will be able to pass.
The agent supplies the arguments at run time, which is how MCP tools are
meant to be called; a pinned-argument form is v2 (Status).

Selecting no tool is a problem (`mcp-tool-unknown` with the sentence
*"pick at least one tool"* is wrong; the code is
`mcp-no-tools-selected` — Status). A server whose last discovery is
`error` or older than `MCP_DISCOVERY_STALE_SECONDS = 86400` shows a
*"re-discover"* button and the picker's first row is Flowise's sentinel
pattern — one entry reading *"No tools available — check the server and
re-discover"* — rather than a toast.

### D6 — Run time: build the config, filter by name, clean up

`runtime:run_agent` receives `mcps: [{server_id, tool_names}]` (FD10),
loads each row with the run user's ownership check (404 semantics become
`mcp-server-unavailable` at validate and a step error at run), resolves
credentials, builds the D4 config with `tool_filter` matching the
sanitised names, and passes the list to `Agent(mcps=[…])`. The resolver
connects when the agent is constructed; `cleanup()` is called in a
`finally` after `crew.kickoff` so no client outlives the step. A budget
note: an MCP-attached agent binds tools, so `budget.py:120-125` already
prices it at `(max_iter + 1)` calls per attempt — no new pricing term.

### D7 — Events become frames

The serializer maps `MCPConnectionStarted/Completed/Failed` to TOOL frames
with `details.transport = "mcp"`, `details.server = <label>`, and
`MCPToolExecutionStarted/Completed/Failed` to the same TOOL frames a
`crewai_tools` call produces, with `details.tool_id = "mcp:<server_id>:<name>"`.
`MCPConnectionFailedEvent` produces a `node_error` frame (C6) with
`error_class = "mcp_connection"` so 12 can render it on the card and, under
`tool_failure_policy: raise`, route the error edge.

## Interfaces

### C12 — MCP server record and discovery (owned here)

`mcp_servers` table (a new table; safe with `create_all()`):

| Column | Type | Note |
| --- | --- | --- |
| `id` | String(32) PK | `ms_[0-9a-f]{12}` |
| `user_id` | String(128) NOT NULL | owner; index `(user_id, updated_at)` |
| `label` | String(80) NOT NULL | |
| `transport` | String(8) NOT NULL | `stdio` \| `sse` \| `http` |
| `url` | String(2048) | for `sse` / `http` |
| `command` | String(255) | for `stdio` |
| `args` | JSON | `list[str]` |
| `header_name` | String(80) | plaintext, e.g. `Authorization` |
| `header_credential_id` | String(32) | kind `mcp_header` |
| `env_credential_id` | String(32) | kind `mcp_header`, injected as `env[MCP_ENV_KEY_NAME]` |
| `status` | String(16) NOT NULL | `pending` \| `authorized` \| `error` |
| `discovered_tools` | JSON | `DiscoveredTool[]` |
| `discovered_at` | DateTime | |
| `last_error` | Text | one sentence |
| `created_at`, `updated_at` | DateTime NOT NULL | |

`DiscoveredTool`:

```json
{ "name": "search_docs", "description": "…≤1024…", "input_schema": { "type": "object", "properties": {…}, "required": [] }, "suspicious": false, "matched_pattern": null }
```

Endpoints (authenticated, 404-not-403):

| Method | Path | Body → result |
| --- | --- | --- |
| `GET` | `/api/builder/mcp/servers` | `{servers: [record with url masked, no credential ids]}` |
| `POST` | `/api/builder/mcp/servers` | `{label, transport, url?, command?, args?, header_name?, header_credential_id?, env_credential_id?}` → 201 record; a `stdio` command off the allow-list → 422 `mcp-transport-disallowed` |
| `PUT` | `/api/builder/mcp/servers/{id}` | same → 200; resets `status` to `pending` |
| `DELETE` | `/api/builder/mcp/servers/{id}` | 204 |
| `POST` | `/api/builder/mcp/servers/{id}/discover` | → 200 `{status, tools, discovered_at, error?}` within `MCP_DISCOVERY_TIMEOUT_SECONDS` |

### `mcp` node config (C1, owned by 03 — required shape)

`{ "server_id": "ms_…", "tool_names": ["search_docs"] }` — `tool_names`
non-empty, each present in the server's `discovered_tools`, validated at
validate and at run.

### `config.py` constants (Integrator-owned; specified here)

`MCP_DISCOVERY_TIMEOUT_SECONDS = 20`, `MCP_DISCOVERY_STALE_SECONDS = 86400`,
`MCP_TOOL_NAME_MAX_CHARS = 128`, `MCP_TOOL_DESCRIPTION_MAX_CHARS = 1024`,
`MCP_ALLOWED_COMMANDS` (env, default `()`), `MCP_ALLOWED_ENV_VARS` (env,
default `()`), `MCP_ALLOW_INSECURE_LOCAL` (env flag, default off),
`MCP_MAX_SERVERS_PER_USER = 16`, `MCP_MAX_TOOLS_PER_SERVER = 64`,
`MCP_INJECTION_PATTERNS` (the thirteen). Four new environment knobs — the
`docs/tech-stack.md` §6 scan must be re-run.

### Consumed

- **C4** (01): `resolve_credential`; kind `mcp_header`.
- **C5** (09): `with: {mcps: [{server_id, tool_names}]}`.
- **C6** (10): TOOL and `node_error` frames.
- **C8** (12): `mcp-server-unavailable`, `mcp-tool-unknown`, and the requested codes below.

## Acceptance criteria

1. `POST …/discover` against a local test MCP server (a stdio server on the allow-list in tests, an HTTP one over a loopback fixture) returns the tool list with schemas, stores it on the row, and a second call within the stale window is served from the row. Test: `tests/builder/test_mcp_discovery.py`.
2. A server whose command is not on `MCP_ALLOWED_COMMANDS` is refused at create with 422 and never spawned; `MCP_ALLOWED_COMMANDS=""` (the default) refuses every stdio server. Test: same file. Rubric 14.
3. A tool description containing `Ignore previous instructions` is stored with `suspicious: true` and `matched_pattern` set, control and zero-width characters stripped, length ≤ 1,024; a name `weird name!` is stored as `weird_name_`. Test: `tests/builder/test_mcp_sanitise.py`.
4. `runtime:run_agent` with an `mcp` attachment constructs `MCPServerHTTP` with the header resolved from the credential and `tool_filter` matching exactly the checked names; `cleanup()` is called after kickoff (asserted through a fake resolver). Test: `tests/builder/test_mcp_runtime.py`.
5. The resolved header value appears in no frame, no `run_frames` row, and no log line during a synthetic run with an MCP attachment. Test: `tests/builder/test_mcp_credentials.py`.
6. A document naming another user's `server_id` validates with `mcp-server-unavailable`; the owner's validates clean; an unknown `tool_names` entry yields `mcp-tool-unknown`. Test: `tests/service/test_mcp_isolation.py`. Rubric 14.
7. A discovery that times out answers 200 `status: error` within `MCP_DISCOVERY_TIMEOUT_SECONDS + 1` and the row's `status` is `error`. Test: `tests/builder/test_mcp_discovery.py::test_timeout`.
8. `MCPConnectionFailedEvent` during a run produces a `node_error` frame and, under `raise`, the error edge fires. Test: `tests/builder/test_failure_modes.py::test_mcp_unreachable` (12's file). Rubric 12.
9. Playwright: add an HTTP server by URL in the builder's MCP panel, discover, see the tool list, drag an `MCP` tile onto an agent, check two tools, and see the read-only parameter preview for each; the agent card shows the server chip. Spec: `frontend/e2e/builder-mcp.spec.ts`, against the loopback fixture server started by the E2E config. Rubric 4.
10. The client's `PROBLEM_CODES` fixture and the Python union agree after the codes below are added (`tests/builder/test_client_fixtures.py`).

## References

- `.venv/Lib/site-packages/crewai/mcp/config.py` (`MCPServerStdio`, `MCPServerHTTP`, `MCPServerSSE` fields — `docs/crewai-notes.md` §6); `crewai/mcp/tool_resolver.py:58` (`MCPToolResolver`), `:81-120` (`resolve`, the `https://` / AMP split, `cleanup`), `:121` (`_parse_amp_ref`), `:534` (`_get_mcp_tool_schemas`), `:572` (`_retry_mcp_discovery`); `crewai/events/types/mcp_events.py:24-89`.
- `docs/flowise-notes.md` §7: `packages/components/nodes/tools/MCP/CustomMCP.ts` (config shape, `listActions`, the sentinel option), `MCP/core.ts:38-72` (sanitisers), `:128-165` (streamable-first, SSE fallback), `:418-453` (`validateMCPServerConfig`), `CustomMcpServerTool.ts`, `packages/ui/src/views/tools/CustomMcpServerDialog.jsx`.
- `src/brief_crew/service/app.py:721-724` (sync route for a blocking fetch), `builder/runtime.py:126-139` (ContextVar scoping), `:406-439` (`Agent(...)` construction), `budget.py:120-125`.
- Gauntlet: Stage 2 "MCP = extensibility … support stdio, SSE and streamable HTTP", "auto-generate the tool card and parameter form".

## Status

**Planned · 2026-09-02.**

Contract requests for 00:

- **C8 (12):** three codes beyond FD14 — `mcp-transport-disallowed` (error), `mcp-no-tools-selected` (error), `mcp-tool-description-suspicious` (warning).
- **C10 (15):** the `mcp_servers` table above.
- **C1 (03), v2:** `pinned_args: {tool_name: {arg: JsonScalar}}` on the `mcp` node for author-pinned arguments. Not required for any template.

Open decisions for the owner:

- Whether production should allow any stdio command at all. Recommendation: none — remote-only — until a sandboxed process model exists; document `npx` / `uvx` for local development.
- Whether a suspicious tool may be selected at all, or only shown. Recommendation: selectable with the warning, because the pattern list has false positives (`act as` is ordinary English).

### Owner decisions answered — 2026-09-04

**Decision 7 — remote servers only in production; stdio behind a flag that is
OFF. PROVISIONAL: the owner confirms.** An arbitrary stdio command would let an
author's document name a process to run on the server, which is the one thing
the compiler's closed set of ten action refs exists to prevent.

**Decision 8 — selectable with a warning. PROVISIONAL: the owner confirms.**
Hiding it in the picker is the quietly-divergent double this repository keeps
warning about; the author should see the warning and decide.

### Built · 2026-09-04

Record, discovery, sanitiser, transport policy, run-time construction, panel and
form. Python **2019** run / 0 failures / 6 skipped; frontend **1400** in 72
files; `vue-tsc` exit 0.

| # | Criterion | | Shown by |
| ---: | --- | --- | --- |
| 1 | discovery stores its result; a second read is served from the row | **partial** | `tests/builder/test_mcp_discovery.py`, `tests/service/test_mcp_isolation.py` |
| 2 | a stdio command off the allow-list is refused and never spawned | **met** | `test_mcp_discovery.py::TransportPolicyTests` |
| 3 | names and descriptions are sanitised; injection marked | **met** | `tests/builder/test_mcp_sanitise.py` |
| 4 | `run_agent` builds the config, filters, and cleans up | **met, extended** | `tests/builder/test_mcp_runtime.py` |
| 5 | the resolved header reaches no frame | **met** | `test_mcp_runtime.py::CredentialInFramesTests` |
| 6 | another user's server is `mcp-server-unavailable` | **met** | `tests/service/test_mcp_isolation.py` |
| 7 | a timed-out discovery is 200 `status: error` | **met** | `test_mcp_discovery.py::test_timeout` |
| 8 | `MCPConnectionFailedEvent` becomes a `node_error` frame | **not reached** | — |
| 9 | Playwright: add, discover, drag, check two, see the preview | **partial** | `frontend/tests/attachmentPanels.spec.ts` |
| 10 | the client `PROBLEM_CODES` fixture agrees | **met** | `tests/builder/test_client_fixtures.py` |

**Criterion 1 - partial, and the missing half is a fixture server.** Discovery
is proved against an injected resolver: the tool list, the schemas, the
sanitised names, the truncation at `MCP_MAX_TOOLS_PER_SERVER`, a malformed
schema degrading rather than raising, and the header reaching the config. The
stored-and-read-back half is proved through the route
(`test_mcp_isolation.py::test_discovery_stores_the_sanitised_tools_on_the_row`)
and the stale window is proved directly. What is NOT done is a **live** local
MCP server - neither the stdio one the criterion names nor an HTTP loopback
fixture. The seam exists precisely so a test need not start one, and standing a
real server up is the E2E harness's job, which is criterion 9's.

**Criterion 4 - met, and it grew a clause the plan did not have.** `cleanup()`
in a `finally` is asserted, and so is something the plan could not have known:
**CrewAI cleans up an agent's MCP clients only on the HAPPY path.**
`agent/core.py` calls `_cleanup_mcp_clients()` after the completion event is
emitted, so a task that RAISES skips it and the client survives the step. A
builder graph fails a step for a dozen ordinary reasons - a guardrail, a cancel,
a cost ceiling - so `release_mcp_clients` sweeps the crew's agents in
`run_agent`'s `finally` and covers what the package does not.

**Criterion 8 - not reached, and it is honestly two things.** The frame mapping
for MCP events is not written and neither is the error edge. The edge is plan
12's (`tests/builder/test_failure_modes.py` does not exist); the MAPPING is D7's
and is this plan's, and it was cut for time rather than for a reason. The
equivalent for skills IS written and tested against real event objects
(`builder/skills.py::skill_frame_details`), so the shape a reviewer would want
exists next door and the MCP one is a small, well-specified piece of work.

**Criterion 9 - partial. The panel is built and unit-proved; the browser is
not.** `frontend/e2e/builder-mcp.spec.ts` was not written and no loopback
fixture server exists. What is proved without a browser: the masked URL, the
`key` chip with no value beside it, a failed discovery landing as a sentence
under its own row, a suspicious tool staying checkable with its pattern shown,
the sentinel "no tools available" row, the transport refusal shown verbatim with
the option still in the select, and the read-only parameter preview appearing
for a CHECKED tool only. A jsdom mount cannot say how wide any of that ended up,
and that is exactly the gap this repository has been bitten through twice.

#### Departures from the plan, each with its reason

1. **There is no `header_name` column and none is missing.** An `mcp_header`
   credential's two fields ARE the header's name and value
   (`config.CREDENTIAL_FIELDS`), so the plaintext name travels with the secret it
   labels rather than beside it in a second place. The shipped `mcp_servers`
   table (15 C10) has no such column and needs none.
2. **`discover` and `mcp_problems` take an injectable DNS resolver.** Without it
   every transport test measures `getaddrinfo` rather than the policy - which is
   how the first draft of `test_mcp_isolation.py` produced ten red tests and one
   honest message. The same seam `service/credentials.py` opened for its probes.
3. **`sanitise_description` turns a control character into a SPACE** and still
   deletes a zero-width one. A zero-width joiner sits between two halves of one
   word and deleting it restores the word; a newline separates two words and
   deleting it glues them into a third that appears in no source - a sanitiser
   inventing text.
4. **`mcp-transport-disallowed` is a validate-time problem code as well as a
   create-time 422.** The plan asks only for the 422. The stdio flag can be
   turned off after a row exists, and a stored row whose transport is no longer
   permitted has to say so on the canvas rather than at the first run.

#### Provisional rulings: what was built, and what would turn each on

**Decision 7, stdio.** Two independent gates, and they stack. `MCP_STDIO_ENABLED`
is **off**, so every stdio server is refused at create, at validate and at
`server_config` - three doors, and the refusal names the policy rather than the
row. Lifting that flag alone still refuses everything, because
`MCP_ALLOWED_COMMANDS` defaults to `()`. **Turning it on is BOTH**: the flag,
and a comma-separated allow-list of commands. `render.yaml` sets neither. Even
then, arguments carrying shell metacharacters are refused, `cwd` is not
settable, and environment keys must be on `MCP_ALLOWED_ENV_VARS`. Both defaults
and both refusals are asserted in both directions.

> The reason to hold it: an arbitrary stdio command lets an author's ROW name a
> process to run on the server, which is the one thing `BUILDER_ACTION_REFS`'
> closed set exists to prevent. A row is not a document, so the compiler's
> guarantee does not cover it - the allow-list is the equivalent guarantee, and
> an empty allow-list is the equivalent of a closed set with nothing in it.

**Decision 8, a suspicious tool.** Built exactly as ruled: the tool is stored,
listed, checkable and attachable, with `matched_pattern` shown on the chip and
in the title. Selecting one produces `mcp-tool-description-suspicious`, the
**fifth** warning code, which contributes no error and blocks no publish.
Nothing anywhere hides a row. **Turning it the other way** - hiding a suspicious
tool - would be a change to `mcp_problems` and to the two pickers, and the
argument against it is in the code: the thirteen patterns have false positives
by design, `act as` is ordinary English, and
`test_the_list_has_false_positives_and_that_is_why_it_only_WARNS` is the case
that would have to be deleted.

### Wave A/B closers — 2026-09-04

| # | Criterion | | Shown by |
| ---: | --- | --- | --- |
| 1 | discovery stores its result; a second read is served from the row | **met** | `tests/service/test_mcp_live_discovery.py` (7, new) + `tests/service/mcp_fixture_server.py` |

**The missing half was a live server, and standing one up found that discovery
had never worked at all.** Every other test in this plan injects a `Resolver` —
the right seam for policy, sanitising, truncation and the stale window, and this
Status said so. What it also meant is that **nothing in this repository had ever
constructed the real `MCPToolResolver`.** The first thing that did got:

```text
status: error   could not connect: MCPToolResolver.__init__() missing 2
                required positional arguments: 'agent' and 'logger'
```

`_default_resolver` called it with none. So `POST …/discover` against any real
server, in any deployment, answered `status: error` with a sentence about a
Python constructor in the place where an author expects to read why their server
would not connect — and it would have survived review indefinitely, because it
*looks* like a connection failure to anybody not reading the string.

The repair is `MCPToolResolver(agent=None, logger=Logger(verbose=False))`, and
`agent=None` is correct rather than a stand-in: the resolver reads `self._agent`
in exactly one place, building a `ToolFilterContext` for a **callable**
`tool_filter`, and discovery passes no filter at all — the filter belongs to the
run, where `server_config` builds it from the author's checked names. Reverting
the one line turns **5 of the 7** new tests red.

**Both transports the criterion names are exercised.** An HTTP `FastMCP` over
loopback in a daemon thread (`MCP_ALLOW_INSECURE_LOCAL`, the flag whose own
docstring names this fixture), and a **stdio server that is really spawned** —
this interpreter on the fixture file, with `MCP_STDIO_ENABLED` and
`MCP_ALLOWED_COMMANDS` both patched on. That is the only place in the suite
where those two gates are lifted together, and the same record with the flag off
is asserted refused beside it so the arm cannot be vacuous.

**"Served from the row" is proved OFFLINE, which is the only way to prove it.**
After discovery the server's URL is repointed at a dead port; the row still
answers with both tools, the same `discovered_at` and `stale: false`. A read
that dialled anything could not do that. Asking it to *re-discover* then errors,
which is the control.

**Three facts measured against the real package, none of which any plan knew:**

1. **CrewAI namespaces a discovered tool name with the SERVER.** `search` on the
   loopback fixture arrives as `127_0_0_1_54253_mcp_search`, and on the stdio
   fixture as the whole sanitised command line. `MCPNativeTool` derives its name
   from the server; `sanitise_tool` only normalises what it is handed.
   Consequence worth knowing before an author meets it: **an HTTP server's
   discovered names contain its port**, so re-discovering the same server on a
   different port renames every tool and a stored `tool_names` selection stops
   matching. A hosted server has a stable address and does not have this;
   a loopback fixture on an ephemeral port always does.
2. **A stdio command's own path must be spelled with forward slashes.**
   `_SHELL_METACHARACTERS` includes the backslash, so a Windows path passed as an
   *argument* is refused — correctly, and the fixture passes one the way a caller
   would have to.
3. **The schemas really do arrive.** `input_schema` is a JSON Schema object with
   both of `search`'s parameters in `properties`, which is what the inspector's
   read-only parameter preview renders and the reason discovery stores more than
   a list of names.

**The fixture's `fetch` carries an injection phrase on purpose**, word for word
from `MCP_INJECTION_PATTERNS`. A fixture whose descriptions were all innocuous
could not tell decision 8's rule working apart from the sanitiser never having
run; here the tool comes back `suspicious` with its pattern named **and still
selectable**, from a description a real server actually sent.

| # | Criterion | | Shown by |
| ---: | --- | --- | --- |
| 8 | `MCPConnectionFailedEvent` becomes a `node_error` frame | **met** | `tests/events/test_mcp_frames.py` (6, new) · `tests/builder/test_failure_modes.py::McpUnreachableTests` (3) |

**Both of the "honestly two things" are here.** This Status recorded the
criterion as not reached and split it: the frame mapping, which it called
this plan's and *"cut for time rather than for a reason"*, and the error edge,
which was plan 12's. Plan 10 landed C6 and plan 09 the error router, so both are
reachable now.

*The mapping* is one additive branch in `_event_drafts`. Before it,
`MCPConnectionFailedEvent` reached `record_unhandled` — **counted and
invisible**, which is the failure that counter exists to make findable rather
than to excuse. Every test asserts the frame **and** that the tally stopped
moving, because a branch that drafts a frame and falls through anyway would
satisfy every assertion about the frame alone.

*The edge* is `test_mcp_unreachable`, in `tests/builder/test_failure_modes.py` —
the file criterion 8 names. **CrewAI raises the event itself**: `MCPClient`
emits `MCPConnectionFailedEvent` from its own failure path and then raises
`MCPConnectionError`, so pointing the real `_default_resolver` at a port nothing
is listening on produces both halves for real — the event that becomes the
frame, and the exception that reaches `_attempted` and its error port. Nothing
is hand-raised.

**Two decisions in the frame's shape, both asserted:**

- **`attempt`, `will_retry` and `routed` are deliberately absent.** They are
  facts about a node's retry loop; this frame is about a connection. The
  node-level `node_error` frame the runtime writes when the failure propagates
  carries all three, and both frames appear in the same run — the second says
  *what happened to the step*, the first says **which server** and why, which
  the second structurally cannot because by then the failure is just an
  exception. An author with three servers attached needs the first.
- **`server_url` is not copied onto the frame.** A hosted MCP server can carry a
  token in its path — `mask_url` exists for exactly that — so putting the raw
  URL on a frame would publish a credential to everyone who can see the run
  console. The server's `name`, `transport`, `error_type` and `status_code`
  travel; the address does not. Pinned by a test that greps the details for the
  path.

**One departure: the error class is spelled `mcp_connection_failed`, with
underscores.** `MCP_CONNECTION_ERROR_CLASS` lives in `builder/mcp.py` beside the
subsystem it names, and three greps sweep every module-level
`NAME = "kebab-case"` under `brief_crew/builder/` into the canvas problem-code
union (`test_problem_code_declarations.py`). A kebab spelling would have
appeared in the client's `PROBLEM_CODES` mirror as a problem an author can
repair on a node, which it is not. `skills.SKILL_LOAD_ERROR_CLASS` is spelled
the same way for the same reason, so the two frame discriminators agree with
each other. **They do not agree with `credential-not-yours`**, which is kebab —
a pre-existing inconsistency in `error_class` spellings across the three, and a
follow-up rather than something to change under this criterion.

**"Under `raise`" is read as the node's `on_error`, not `tool_failure_policy`.**
An MCP connection failure is raised while an agent's clients are being resolved,
before any tool runs, so no tool policy is in the path. Both `route` and `fail`
are asserted, which is what that clause distinguishes.

**Criterion 9 closes, against a REAL server.** `frontend/e2e/builder-mcp.spec.ts`
adds a server by URL in the docked panel, discovers it over a live loopback MCP
connection, sees both tools, checks them, reads the read-only parameter preview
for each, attaches, and finds the server chip on the form and the avatar on the
agent card. Green at `369a8c4`; capture in `benchmarks/ours/07/`.

| # | Criterion | State | Shown by |
| ---: | --- | --- | --- |
| 9 | add, discover, drag, check two tools, see the preview | **met** | `frontend/e2e/builder-mcp.spec.ts`, 1 test, real discovery |

**No stub, and that distinction earned its keep immediately.** Every other test
in this plan injects a `Resolver`, which is the seam's whole purpose and is also
exactly why nothing had ever constructed the real one: `_default_resolver`
called `MCPToolResolver()` with no arguments, and discovery against ANY real
server answered `status: error` carrying a Python `TypeError` in the sentence
where an author expected to read why their server would not connect. The fix is
`wd/ab-backend@604a4e5` and was taken verbatim into this worktree on the
Integrator's instruction; it is not this package's file and was not edited here.
A stubbed `page.route` discovery would have passed over that defect, which is
the argument for not writing one.

**The fixture server is a second process and the spec says so.** It is
`tests/service/mcp_fixture_server.py` — two tools over streamable HTTP on
loopback, one of them carrying an injection phrase on purpose, so the
`suspicious` rule is tested against the real pattern list rather than a phrase
invented for the test. `playwright.config.ts` deliberately starts no Python, so
the URL arrives as `E2E_MCP_URL` and the file **skips** when it is absent rather
than falling back to a stub. Run as measured:

```text
python -c "import sys; sys.path.insert(0,'tests/service'); from mcp_fixture_server \
  import build_server; build_server(port=8791).run(transport='streamable-http')"
SYNTHETIC=1 PORT=8094 MCP_ALLOW_INSECURE_LOCAL=1 CREDENTIALS_MASTER_KEY=... serve.exe
E2E_MCP_URL=http://127.0.0.1:8791/mcp npx playwright test e2e/builder-mcp.spec.ts
```

`MCP_ALLOW_INSECURE_LOCAL` is not optional and its absence does not read like a
missing flag: `refuse_private_target` answers *"is not https, and only https
targets are dialled"*, which sounds like a rule about the fixture rather than
about the deployment.

**What the browser confirmed that the unit tests could not.** Discovery returned
`authorized` with two tools whose names CrewAI prefixes with the server's own
address (`127_0_0_1_8791_mcp_search`), so the spec reads the names off the panel
rather than writing them; the injection-phrase tool is marked AND its checkbox
is still enabled, which is decision 8 seen from the pointer; the URL is masked
in the list; and the parameter preview appears per CHECKED tool in both the
panel and the form.

**One idiom worth recording for the next author.** `McpForm` opens its own
docked panel when the caller has no servers yet — correct behaviour, and exactly
the state this test starts in, so a blind click on *"Manage servers"* SHUT it and
the failure read as a missing component. The spec opens rather than toggles.

### Decisions 7 and 8 ruled — 2026-09-05

**Decision 7: remote servers only in production** — `MCP_STDIO_ENABLED` stays
unset; a document must never be able to name a server-side process, the same
reason the compiler's action refs are a closed set. **Decision 8: selectable
with a warning** — the warning is information the author needs, and hiding the
tool is the quietly-divergent picker R10 refused. Both ruled by the Integrator
under the owner's delegation of 2026-09-05; PLANS.md carries the same wording.
