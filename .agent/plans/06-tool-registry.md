# 06 — Tool registry

## Problem

"Tools = hands" is the product's clearest idea, and today a canvas has
three hands: `BUILDER_RESEARCH_TOOLS` is a frozenset of three names
(`config.py:2014-2020`), a tool is a checkbox inside the agent inspector
(`BillableForm.vue:141-148`), not a node, and every tool reads its
credential from a process-wide environment variable at call time
(`market_research.py:241`, `github_feasibility.py:333`). There is no custom
tool, no tool node to drag onto an agent, no per-user key, and no policy
for what happens when a tool fails other than the repo tools' own habit of
returning a `status: "failed"` envelope instead of raising
(`market_research.py:243-249`).

`crewai_tools` 1.15.18 ships 107 classes (`docs/crewai-notes.md` §8), and
the gauntlet names a dozen it wants. Three facts from the package decide
which of them can ship:

1. **`CodeInterpreterTool` no longer exists.** `Agent.allow_code_execution` is deprecated with the message *"CodeInterpreterTool is no longer available. Use dedicated sandbox services instead."* (`crewai/agent/core.py:279-282`, warned at `:407-410`). The sandboxed alternatives, `E2BPythonTool` and `DaytonaPythonTool`, are paid third-party services behind an API key.
2. **Every RAG-backed class embeds with OpenAI by default.** `CSVSearchTool`, `JSONSearchTool`, `GithubSearchTool`, `YoutubeVideoSearchTool`, `WebsiteSearchTool` and `RagTool` share the `adapter` / `config` / `similarity_threshold=0.6` / `limit=5` shape and route embeddings through the default provider unless `config` says otherwise. The platform rules forbid a direct OpenAI dependency and require embeddings through `brief_crew.embeddings`.
3. **Firecrawl `map` and `extract` have no class.** Only `FirecrawlScrapeWebsiteTool`, `FirecrawlCrawlWebsiteTool` and `FirecrawlSearchTool` exist.

## Scope

- A server-owned tool catalogue (`builder/tools.py`) with a stable entry shape, served through the vocabulary (C2), and a factory per entry that constructs the `BaseTool` with the user's credential at run time.
- The `tool` attachment node (C1 from 03): `{tool_id, credential_id | null, params}`, attached to an `agent` or `crew` node through the `attach` port.
- A declarative **custom HTTP tool** authored by the user — Flowise's schema grid with an HTTPS call in place of a JavaScript function — stored per user and offered in the catalogue beside the built-ins.
- Web search as **one** catalogue entry with a `provider` parameter over Serper, Tavily, Exa and Brave.
- `ToolFailurePolicy` as a per-agent setting, and the mapping from tool failure to the frames 12 renders.
- The tool card's credential state and the drag-onto-agent feedback contract, consuming 03's gesture.

## Out of scope

- User-authored **Python** tools. See D8; not started until the owner decides.
- RAG-backed tools, file tools and a file store. v2, listed in D3 with the wiring they need.
- Firecrawl `map` / `extract`. v2 through the SDK wrapper the repo already has in `tools/market_research.py`.
- The Pinecone retrieval tool on user canvases. It needs three platform keys, indexes the platform namespace, and raises `KeyError` on a missing env var (`pinecone_retrieval.py:68, 102`) — it is Brief Crew's, not a user's.
- Tool marketplaces, tool sharing between users, tool versioning.

## Design

### D1 — The catalogue is server-owned; the document names an id, never a class

The same principle as `BUILDER_ACTION_REFS` (`config.py:2046-2059`,
`compiler.py:319-350`): a document carries `tool_id`, the server maps it to
a factory, and no module path, class name or code reaches the definition.
`BUILDER_RESEARCH_TOOLS` becomes the three repo entries of the catalogue
and stays a `config.py` constant; the catalogue itself is a tuple of
`ToolCatalogueEntry` in `builder/tools.py`, exported through the vocabulary
so the palette and inspector never hold a copy (cut-list 17 stands — no
client fallback list).

### D2 — v1 membership, entry by entry

| `id` | Class | Credential kind | Author-settable params | Reason it is in |
| --- | --- | --- | --- | --- |
| `research_market_landscape` | repo `MarketResearchTool` | `firecrawl` (optional — platform key by default) | `limit ≤ 3` | already offered; returns the JSON envelope |
| `analyze_community_sentiment` | repo `HackerNewsSentimentTool` | none | `story_limit ≤ 5`, `comments_per_story 1..20` | already offered; public API |
| `assess_technical_feasibility` | repo `GitHubFeasibilityTool` | `github` (optional) | `limit 1..5` | already offered; the non-RAG GitHub tool |
| `firecrawl_scrape` | `FirecrawlScrapeWebsiteTool` | `firecrawl` | `only_main_content`, `formats ⊆ {markdown, links}` | gauntlet names it |
| `firecrawl_crawl` | `FirecrawlCrawlWebsiteTool` | `firecrawl` | `limit ≤ 20`, `max_depth ≤ 2` | gauntlet names it; bounded because a crawl is a bill |
| `firecrawl_search` | `FirecrawlSearchTool` | `firecrawl` | `limit ≤ 5` | gauntlet names it |
| `web_search` | `SerperDevTool` \| `TavilySearchTool` \| `EXASearchTool` \| `BraveSearchTool` by `provider` | `serper` \| `tavily` \| `exa` \| `brave` | `provider`, `n_results 1..10` | one interface, four providers, as the gauntlet asks |
| `http_request` | `URLReadTool` | `http_header` (optional) | `timeout ≤ 30`, `max_bytes ≤ 5 MiB` | already refuses private, loopback and link-local targets (`url_read_tool.py:80, 112, 146`) |
| `scrape_website` | `ScrapeWebsiteTool` | none | — | keyless scrape for pages Firecrawl is not needed for |
| `postgres_query` | `NL2SQLTool` | `postgres` (the `db_uri`) | `tables[]`, `columns` | gauntlet names it; **`allow_dml=False` is locked** and not a param |
| `custom_http:<id>` | `builder/custom_tools.py` | `http_header` (optional) | none at attach time — the schema is the tool | D7 |

Every factory sets `tool_failure_policy` from the agent (D6) and never
reads `os.environ` for a user-scoped credential; the platform Firecrawl key
remains the default for the repo's own market tool because that is what
the idea-validator template runs on from a cold sign-in (gauntlet: "zero
configuration").

### D3 — Excluded in v1, with the wiring each needs to come back

| Item | Why excluded | v2 path |
| --- | --- | --- |
| `CSVSearchTool`, `JSONSearchTool`, `WebsiteSearchTool`, `RagTool`, `GithubSearchTool`, `YoutubeVideoSearchTool` | OpenAI embeddings by default | construct with `config={"embedder": …}` pointing at `brief_crew.embeddings` with `DOC_PREFIX` / `QUERY_PREFIX` paired; needs a per-user vector namespace (`validator_cache.py` already hashes one) |
| `FileReadTool`, `DirectoryReadTool` | no file store, and Render disk is ephemeral | after 08's skill store proves the per-user file pattern |
| Firecrawl `map`, `extract` | no `crewai_tools` class | wrap the SDK in `tools/market_research.py`'s style |
| YouTube transcript | only the RAG class exists | with the embeddings wiring above |
| Code interpreter | removed from CrewAI | D8 |

### D4 — Credentials are resolved inside the entrypoint, never before

A `tool` node's `credential_id` (C4) rides in the compiled `with:` block as
an opaque id (FD10). `runtime:run_agent` calls
`resolve_credential(credential_id)` — a ContextVar-scoped lookup bound to
the run's user the way `builder_cancellation` binds the cancel flag
(`runtime.py:126-139`) — and passes the plaintext to the factory as a
constructor argument (`api_key=` on the Firecrawl classes, `gh_token=` on
GitHub, `db_uri=` on NL2SQL, `headers=` on URLRead). The value lives on
the tool instance for the life of one crew kickoff and in nothing that is
serialised: the frame serializer's `_SECRET_KEYS` redaction
(`persistence.py:71-86`) is extended with `api_key`, `gh_token`, `db_uri`,
`headers`, and `tests/builder/test_tool_credentials.py` asserts a
captured tool frame never contains the plaintext.

A tool entry with a required `credential_kind` and no `credential_id`
validates with `credential-missing` (C8), the card shows an amber *"no
key"* chip, and the inspector offers the user's credentials of that kind
plus *"add one"* — the Flowise credential dropdown
(`docs/flowise-notes.md` §4) without the modal.

### D5 — Web search is one entry, four providers

`web_search` renders one card; `provider` is a select; the credential kind
follows the provider (`credential_kind_by_param`). The factory maps
`provider` to the class and its own `n_results` / `max_results` field
(`SerperDevTool.n_results`, `TavilySearchTool.max_results`,
`BraveSearchTool.n_results`; Exa takes `highlights=True` and no count).
The agent sees one tool name, `web_search`, whichever provider backs it, so
swapping providers changes no prompt.

### D6 — Tool failure is a policy, and the policy is priced into the error edge

`ToolFailurePolicy` (`crewai/tools/tool_failure.py:57-69`) is `ignore`,
`warn` (default) or `raise`. It is an Advanced control on the agent node
(04), passed to `Agent(tool_failure_policy=…)` and to each constructed
tool. `raise` is the setting that makes 12's error edge fire on a tool
timeout: a `ToolExecutionFailedError` leaves the step, the paired router
emits `error`, and the frame carries `error_class`. The three repo tools
keep returning envelopes (they never raise, by design — a failed tool must
not become an invented citation), so under `raise` they are still the
calm ones; the `crewai_tools` classes are the ones that throw.

### D7 — The custom tool is declarative: a schema and an HTTPS call

Flowise's `ToolDialog.jsx` is the reference (`docs/flowise-notes.md` §4):
name, description, an editable grid of typed properties, and a function.
The function is replaced by a request template, which removes the
interpreter and keeps the shape:

```json
{
  "name": "weather_lookup",
  "description": "Current weather for a city. Use when the user names a place.",
  "properties": [
    { "name": "city", "type": "string", "description": "City name", "required": true }
  ],
  "request": {
    "method": "GET",
    "url": "https://api.example.com/weather?q={city}",
    "header_name": "Authorization",
    "header_template": "Bearer {credential}",
    "body_template": null,
    "timeout_seconds": 15,
    "max_response_bytes": 1048576
  }
}
```

`builder/custom_tools.py` builds a `BaseTool` subclass per row: the
`args_schema` is a pydantic model generated from `properties`
(`create_model`), `_run` renders `{name}` placeholders with URL-encoding,
resolves the header credential through D4, performs the call with the
`httpx` client CrewAI already depends on, refuses non-HTTPS URLs and
redirects, resolves DNS and refuses private, loopback and link-local
addresses (the `URLReadTool` rule, `url_read_tool.py:112`), caps the
response at `max_response_bytes`, and returns the repo's envelope
`{status, tool, query, retrieved_at, result_count, results, notes}` with
the body as one result — so a custom tool's output looks to the guardrails
exactly like a built-in's. The row is per user (`user_tools`, C10), shows
up in the catalogue as `custom_http:<id>` for its owner only, and a
document referencing another user's custom tool validates with
`tool-unknown` (a code that exists today, `bounds.py:62-86`).

### D8 — The code interpreter is a decision, not a task

CrewAI removed the in-process interpreter; the only sandboxes it ships
are E2B and Daytona, each a paid account and a key. Offering *"code
interpreter (sandboxed, opt-in, resource-capped)"* therefore means one of:

1. **BYO sandbox key** — `E2BPythonTool(api_key=<credential e2b>, sandbox_timeout ≤ 300)` as a catalogue entry that is disabled until the user adds an `e2b` credential; resource caps are E2B's.
2. **Platform sandbox account** — the same entry on a platform key, metered into `MAX_RUN_COST_USD` by a per-call price the registry does not model today.
3. **Not in v1.**

The plan recommends 1 and ships nothing until the owner picks. Under 1,
the user's own Python (`func` in Flowise's grid) is also possible as a
second custom-tool form — but it executes in E2B, never here, and
`AGENTS.md:67` stays intact.

### D9 — Drag a tool onto an agent, and the agent shows it

03 owns the gesture; this plan owns what the author sees. Dropping a
catalogue tile on an agent card creates the `tool` node beside the agent
and the `attach` edge as **one** commit (one undo), the agent card gains a
tool chip in its summary row (Flowise v2's model pill and tool avatars,
`AgentFlowNode.jsx:440-656`), and the tool card shows icon, label,
provider (for `web_search`), and the credential state from D4. Dropping on
a node that is not `agent` or `crew` bounces the tile back with the
tooltip *"tools attach to agents"*; dropping on an agent whose model has
`supports_tools: false` bounces with the model's name in the sentence
(05 D7).

## Interfaces

### Catalogue entry (consumed by C2, shape owned here)

```json
{
  "id": "web_search",
  "label": "Web search",
  "category": "research",
  "credential_kind": null,
  "credential_kind_by_param": { "param": "provider", "map": { "serper": "serper", "tavily": "tavily", "exa": "exa", "brave": "brave" } },
  "param_schema": {
    "type": "object",
    "properties": {
      "provider": { "type": "string", "enum": ["serper", "tavily", "exa", "brave"], "default": "serper" },
      "n_results": { "type": "integer", "minimum": 1, "maximum": 10, "default": 5 }
    },
    "additionalProperties": false
  },
  "description": "Search the web through one of four providers; the agent sees a single tool.",
  "docs_url": "https://docs.crewai.com/en/tools/search-research/serperdevtool",
  "owner": "builtin"
}
```

`category ∈ {research, web, data, custom}`; `owner ∈ {builtin, user}`;
`class_ref` exists only on the server side of the entry and is never
serialised. The vocabulary's `research_tools` list becomes `tools:
[entry…]` and keeps its order.

### `tool` node config (C1, owned by 03 — the shape this plan requires)

`{ "tool_id": "web_search", "credential_id": "cr_…" | null, "params": { "provider": "tavily", "n_results": 5 } }`
— `params` validated against the entry's `param_schema` at parse (`bounds`
reports `tool-param-invalid`), `credential_id` validated for ownership at
validate and again at run.

### `user_tools` table (C10, owned by 15 — required here)

`id` PK String(32) `ut_[0-9a-f]{12}`, `user_id` String(128) NOT NULL,
`name` String(40) (`^[a-z][a-z0-9_]{0,39}$`, unique per user), `description`
Text (≤ 1024), `properties` JSON, `request` JSON, `created_at`,
`updated_at`. A new table, safe with `create_all()`.

### Endpoints (owned here, mounted in `builder_api.py`)

| Method | Path | Body / result |
| --- | --- | --- |
| `GET` | `/api/builder/tools` | `{tools: [entry…]}` — builtins plus the caller's custom tools |
| `POST` | `/api/builder/tools/custom` | the D7 document → 201 with the entry |
| `PUT` | `/api/builder/tools/custom/{id}` | same → 200 |
| `DELETE` | `/api/builder/tools/custom/{id}` | 204; documents referencing it validate with `tool-unknown` thereafter |
| `POST` | `/api/builder/tools/custom/{id}/test` | `{args}` → runs the call once, 200 with the envelope; billed to nobody |

All authenticated (`Depends(current_user)`), 404-not-403 for another
user's tool (`store.py:602-610`'s rule).

### Consumed

- **C1** (03): `tool` kind, `attach` port, `MAX_ATTACHMENTS_PER_NODE = 8`.
- **C4** (01): `resolve_credential`, credential kinds.
- **C5** (09): `with: {tools: [{tool_id, credential_id, params}]}`.
- **C6** (10): tool frames carry `tool_id`, `status`, `duration_ms`, `error_class`.
- **C8** (12): `credential-missing`, `tool-unknown`, `tool-param-invalid`, `model-lacks-capability`.

## Acceptance criteria

1. `GET /api/builder/tools` lists the eleven v1 builtins with the entry shape above and no `class_ref` key. Test: `tests/service/test_tools_endpoint.py`.
2. Each builtin factory constructs its class with a supplied credential and never reads `os.environ` for it: `tests/builder/test_tool_factories.py` patches `os.environ` clear (the pattern `tests/tools/test_github_feasibility.py` already uses) and asserts construction succeeds with `credential="x"` for every entry with a credential kind.
3. A tool frame captured during a synthetic run with a Firecrawl credential attached contains no substring of the credential. Test: `tests/builder/test_tool_credentials.py`.
4. `web_search` with each of the four providers constructs the matching class and exposes the single tool name `web_search`. Test: same file, four cases.
5. `postgres_query` cannot be constructed with `allow_dml=True` from any document value. Test: `tests/builder/test_tool_factories.py::test_dml_locked`.
6. A custom HTTP tool: creating one, attaching it, and running the fan-out template with a stub HTTPS server returns the envelope; a URL resolving to `127.0.0.1`, an `http://` URL, and a 2 MiB response are each refused with a `status: failed` envelope naming the reason. Test: `tests/builder/test_custom_tools.py` (six cases).
7. Another user's custom tool id in a document validates with `tool-unknown`; the owner's validates clean. Test: `tests/service/test_tools_isolation.py`. Rubric 14.
8. `tool_failure_policy: raise` on an agent with a tool that throws makes the paired router emit `error` and the run reach the error edge's target; `warn` completes the step. Test: `tests/builder/test_failure_modes.py::test_tool_timeout` (12's file, this plan's case). Rubric 12.
9. Playwright: drag `Web search` from the palette onto an agent card — one node and one edge appear, the agent card shows a tool chip, Ctrl+Z removes both; drop it on a `transform` node — nothing is created and the tooltip reads *"tools attach to agents"*. Spec: `frontend/e2e/builder-tools.spec.ts`. Rubric 3, 4.
10. Playwright: an attached `firecrawl_search` with no credential shows the amber *"no key"* chip and the problems dock lists `credential-missing` anchored to the tool node; adding a credential in the inspector clears both. Same spec. Rubric 12.
11. The Python catalogue and the client's `data/toolCatalogue` fixture are byte-identical through `tests/builder/test_client_fixtures.py`.

## References

- `docs/crewai-notes.md` §8 (tool table, env vars, RAG warning, `CodeInterpreterTool` removal), §11 items 1, 7, 9.
- `.venv/Lib/site-packages/crewai/agent/core.py:279-282, 305-308, 407-410`; `crewai/tools/tool_failure.py:57-69`; `crewai_tools/tools/url_read_tool/url_read_tool.py:80, 112, 146`; `crewai_tools/tools/nl2sql/`, `serper_dev_tool/`, `tavily_search_tool/`, `exa_tools/`, `brave_search_tool/`, `firecrawl_scrape_website_tool/`, `scrape_website_tool/`.
- `src/brief_crew/config.py:2014-2020` (`BUILDER_RESEARCH_TOOLS`), `:2046-2059` (`BUILDER_ACTION_REFS`); `builder/runtime.py:365-390` (tool instantiation), `:126-139` (ContextVar scoping); `tools/market_research.py:159-178, 223-249`; `tools/hn_sentiment.py:97-119, 310-329`; `tools/github_feasibility.py:63-67, 292-333`; `tools/pinecone_retrieval.py:68, 102, 142-146`; `service/persistence.py:71-86` (`_SECRET_KEYS`).
- `frontend/src/components/builder/inspectors/BillableForm.vue:29-35, 141-148, 326-349`.
- `docs/flowise-notes.md` §4 (`views/tools/ToolDialog.jsx`, the schema grid; `CredentialInputHandler.jsx`; `ToolAgent.ts:46-51` list anchors; `Agent.ts:251-271` v2 tool array), §9 (adopt / avoid).
- Gauntlet: Stage 2 "Tools, skills and MCP — keep the three distinct", "Forbidden: a parameter rendered in the UI that the compiler ignores".

## Status

**Planned · 2026-09-02.**

Contract requests for 00:

- **C8 (12):** add `tool-param-invalid` beside the seven codes FD14 lists.
- **C10 (15):** the `user_tools` table above.
- **C2 (03):** `research_tools: [str]` in the vocabulary becomes `tools: [entry]`; the client's `BillableForm` checklist is replaced by the attachment model, so the field goes away rather than being mirrored.

Open decisions for the owner:

- **D8, the code interpreter.** Recommendation: option 1, BYO E2B key, not started until decided.
- Whether the platform Firecrawl key should back `research_market_landscape` for every user by default (zero-config templates) or only until the user adds their own. Recommendation: platform key by default, per-user override, and a per-user daily cap recorded in 01.

### Owner decisions answered — 2026-09-04

**Decision 3 (D8) — BYO E2B key behind a flag, default OFF. PROVISIONAL: the
owner confirms before it is enabled.** It runs somebody else's code on our
machine. Build the flag and the key handling; stop before enabling it by
default.

**Decision 9 — the per-user override is built and the daily cap is built; the
platform Firecrawl default stays OFF. PROVISIONAL: the owner confirms.** A
platform key backing every user's research spends the owner's money on other
people's requests.

### Built · 2026-09-04

Server, client and tests. Python **2019** run / 0 failures / 6 skipped;
frontend **1400** in 72 files; `vue-tsc` exit 0; `npm run build` green. Every
row below names the command that shows it.

| # | Criterion | | Shown by |
| ---: | --- | --- | --- |
| 1 | catalogue endpoint, no `class_ref` | **met, count corrected** | `tests/service/test_tools_endpoint.py` |
| 2 | every factory takes a supplied credential | **met** | `tests/builder/test_tool_factories.py` |
| 3 | no credential substring in a tool frame | **partial** | `tests/builder/test_tool_credentials.py` |
| 4 | `web_search` over four providers, one name | **met** | `test_tool_factories.py::WebSearchProviderTests` |
| 5 | `postgres_query` cannot be writable | **met, hardened** | `test_tool_factories.py::DmlLockTests` |
| 6 | the declarative custom HTTP tool | **met** | `tests/builder/test_custom_tools.py` |
| 7 | another user's custom tool is `tool-unknown` | **met** | `tests/service/test_tools_isolation.py` |
| 8 | `tool_failure_policy: raise` reaches the error edge | **partial** | `test_tool_factories.py::FailurePolicyTests` |
| 9 | Playwright: drag a tool onto an agent | **not reached** | — |
| 10 | Playwright: the amber "no key" chip and the dock | **partial** | `frontend/tests/attachmentPanels.spec.ts` |
| 11 | the catalogue fixture is byte-identical | **met** | `tests/builder/test_tool_catalogue_fixture.py` |

**Criterion 1 - ten builtins, not eleven, and the arithmetic is asserted.**
D2's table has eleven rows and its last is `custom_http:<id>`, which is
per-user rather than a builtin. The eleventh BUILTIN is `code_interpreter`,
which exists and is withheld behind `BUILDER_CODE_INTERPRETER_ENABLED`. Both
counts are asserted - ten with the flag off, eleven with it on.

**Criterion 3 - partial, and the missing half is a wave away.** The credential
is proved absent from a frame through the real redaction walk and the real
`FieldBoundedSerializer.clip`, over a payload carrying a plaintext under every
name a factory here hands one to. It is NOT captured during a synthetic run with
a Firecrawl tool attached, because the compiler does not emit `tool`
attachments into a definition yet - that is C5, plan 09's, and no builder run
can carry an attachment until it does. The test found a real leak on the way:
`db_uri` normalises to `dburi`, which ends in none of `SECRET_KEY_SUFFIXES`, so
NL2SQL's constructor keyword was the one credential-bearing name in the builder
that reached a frame in clear. Fixed in `events/redaction.py`.

**Criterion 6 - met, with one clause read differently.** The six cases are the
six that decide whether this is a tool or a hole in the network, and all six
pass: the envelope, a URL resolving to `127.0.0.1`, an `http://` URL, a
2 MiB response, a redirect, and every refusal arriving as a `status: failed`
ENVELOPE rather than an exception. The clause about "running the fan-out
template with a stub HTTPS server" is not honoured literally - the tool's own
`_run` is driven with an injected transport instead, which exercises the same
code with no server to start and no port to collide on.

**Criterion 8 - the half that is reachable, and the half that is not.** The
policy is a real `ToolFailurePolicy`, it reaches every constructed tool
including the custom HTTP one, and `run_agent` passes a non-default through
while passing nothing when it is the default. The error edge, the paired router
and the `node_error` frame are plan 12's and `tests/builder/test_failure_modes.py`
does not exist. The distinction matters: if the policy did not reach the tool,
`raise` would silently behave as `warn` and 12's error edge would never fire for
a reason nothing in 12 could find.

**Criteria 9 and 10 - the browser half is not reached and is not approximated.**
`frontend/e2e/builder-tools.spec.ts` was not written. A jsdom mount asserts
structure and never asks how wide anything ended up, and a `dragstart`
dispatched in jsdom proves a handler is bound and nothing about whether a tile
lands on a card - so writing that spec in vitest would have been the failure
this repository already records twice. What IS proved without a browser is
criterion 10's substance: the amber chip renders exactly when a REQUIRED key is
absent (`attachmentPanels.spec.ts`), and `tool-credential-required` is reported
by the server and anchored to the tool node (`test_tools_isolation.py`).

#### Departures from the plan, each with its reason

1. **The wire key is `tool_id`, not `id`, and `params` is a list rather than
   `param_schema`.** Three client files already read `tool_id`, `attaches_to`
   and `params[]` off `types/builder.ts::BuilderToolCatalogueEntry`, written
   before this catalogue existed, and two of them are outside this plan's
   surfaces. Serving the plan's spelling meant editing files this plan may not
   touch, or shipping a palette that renders an empty label for every tool. The
   plan's own extra fields are ADDED to the client's six.
2. **A custom tool's catalogue id is `ut_<12 hex>`, not `custom_http:<id>`.**
   `ToolConfig.tool_id` is a `NodeId` and `BUILDER_ID_PATTERN` has no colon in
   it, so the plan's spelling is not expressible in the document schema. Fixing
   that is a C1 change and C1 is not this plan's.
3. **A missing required key is `tool-credential-required`, not
   `credential-missing`.** D4 reuses the latter for both. The repairs differ -
   "add a key of this kind and pick it" against "that id is not yours" - and
   `compiler.py` already states the rule that a different repair earns a
   different code.
4. **`builder/custom_tools.py` does not exist; the custom tool lives in
   `builder/tools.py`.** One module rather than two for a catalogue entry and
   its factory.
5. **The stores live in `service/attachments.py`**, a new file, rather than in
   the builder package. The builder package must stay importable without
   SQLAlchemy - `compile_document` and `estimate_budget` must not pay for it.

#### Package facts the plan did not have, all measured

- **`SerperDevTool` and `BraveSearchTool` have no `api_key` field** and read
  `os.environ` inside `_run`. D4's "never reads `os.environ`" is not achievable
  by construction for them, so the key is bound in a CLOSURE and written to the
  environment for the length of one call under a process lock. It is never a
  pydantic field, so `model_dump` cannot emit it - which is a stronger property
  than the redaction list. Brave reads it at CONSTRUCTION too, so that window
  covers the constructor.
- **`NL2SQLTool.model_post_init` lets `CREWAI_NL2SQL_ALLOW_DML=true` OVERRIDE
  the constructor argument.** `allow_dml=False` is therefore locked three ways:
  a literal, a forced environment across construction, and an assertion on the
  built instance. A deployment with that variable set would otherwise have got a
  writable tool through a constructor that says `allow_dml=False`.
- **`TavilySearchTool.__init__` calls `click.confirm`** to offer to install its
  own package, which raises `Abort` in a service process. `tavily` and `exa_py`
  are both absent here, so availability is checked with `find_spec` BEFORE
  constructing and the entry is served with `available`/`requires_packages` so a
  picker can grey out what cannot run.
- **`postgres_query`'s constructor dials the database.** Its behaviour is
  asserted through a recorder rather than by building one, which is the more
  precise test anyway.

#### Provisional rulings: what was built, and what would turn each on

**Decision 3, the code interpreter.** `code_interpreter` is a full catalogue
entry - `E2BPythonTool`, BYO `e2b` credential, `sandbox_timeout` fixed at E2B's
own cap and not author-settable. `BUILDER_CODE_INTERPRETER_ENABLED` is **off**,
`entry_enabled` withholds it from every list, and `resolved_tool` refuses it by
naming the flag. **Turning it on is one environment variable** and nothing else;
`test_the_only_thing_between_it_and_shipping` asserts that.

> **New evidence the decision was not made with, surfaced again as asked.**
> CrewAI's own `Agent.allow_code_execution` and `code_execution_mode` are
> `Field(deprecated=True)` at 1.15.18 with the message *"CodeInterpreterTool is
> no longer available. Use dedicated sandbox services instead."* The native path
> is going away regardless of what the owner decides, so the choice is between a
> paid third-party sandbox and nothing - there is no third option in which
> CrewAI keeps executing code.

**Decision 9, the platform Firecrawl key.** `BUILDER_PLATFORM_FIRECRAWL_DEFAULT`
is **off** and `BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` is 50. With the flag off,
`research_market_landscape` reports `credential_optional: false` and an author
with no Firecrawl key gets the amber chip and
`tool-credential-required`. **Turning it on is that one flag**: the entry's
`credential_optional` follows it, the chip and the problem both stop, and an
author with no key of their own runs on the platform's. **What is NOT built is
the counter the cap would read.** The constant exists and nothing decrements
it, because a per-user daily counter is a table and a table is C10, which is
plan 15's - so enabling the flag today would spend the owner's money with a
documented cap and no enforcement. That is the gap to close before the owner
says yes.
