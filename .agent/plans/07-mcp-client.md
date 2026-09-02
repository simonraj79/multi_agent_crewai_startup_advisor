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
