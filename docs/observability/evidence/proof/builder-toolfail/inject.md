# `builder-toolfail` - how the tool is made to throw, on the PAID backend

Written 2026-09-05 by V-PROOF-DOCS, before any paid run. Every file:line below
was read at the working tree of that date; every measured line says *measured*
and carries the command that produced it.

`document.json` beside this file is the exact `document` body to POST - but read
**section 7 first**: it gained a second, author-named tool on a follow-up, and that
made it launchable only by a signed-in caller. `document-anonymous.json` is the
one-tool body an anonymous paid backend can actually run.
`synthetic-check.txt` beside it is the proof that the document validates,
publishes and launches - **on a synthetic backend, which does not exercise the
failure**.

> **Line numbers, and one hazard.** Everything below was read at the working
> tree of 2026-09-05, while another agent was actively editing
> `service/app.py`, `service/registry.py`, `events/serializer.py` and
> `src/brief_crew/observability/`.
> `app.py` moved by about 28 lines and `serializer.py` by about 80 *during*
> this pass, so every citation into
> those two files was re-derived from a grep anchor at the end of it. If a
> number here does not land, grep the quoted symbol rather than reading around
> it: the anchor is the contract, the line is not.

---

## 1. What the plan asked for, and why it cannot be done as written

PLAN.md, "Failure injection, engine-neutral":

> **Raising tool**: on `builder-toolfail`, give the tool node a credential that
> is syntactically valid and wrong (create it through
> `POST /api/builder/credentials`, then reference it from the agent).

**That is not performable on the backend PLAN.md describes.** The planned paid
backend is `.env` loaded, no `SYNTHETIC`, and `.env` sets no `AUTH_BASE_URL`
(measured: `grep -o '^[A-Za-z_][A-Za-z0-9_]*' .env` lists twelve names and
`AUTH_BASE_URL` is not among them). On such a backend there is **no way to
become anybody**, and the vault is identity-only at three doors:

1. `service/credentials_api.py:118-127` - `vault()` calls `require_user(user)`
   for every credential route, create included.
2. `service/app.py:944-958` - `require_user` raises **401** for `None`.
3. `service/app.py:860-882` - `synthetic_identity` returns `None` unless the
   app was built `synthetic=True` **and** `AUTH_BASE_URL` is unset. On a paid
   backend `synthetic` is `False`, so `X-Synthetic-User` is ignored, not
   honoured.

**Measured** on the synthetic backend, where both arms can be shown side by
side (full transcript in `synthetic-check.txt`):

```text
POST /api/builder/credentials                                      -> 401 {"detail":"sign in to use this endpoint"}
POST /api/builder/credentials -H 'X-Synthetic-User: proof-author'  -> 201 {"id":"cr_88627cb9","kind":"firecrawl",...}
```

The second line is the one a paid backend cannot reach.

And even if a row could be written, an anonymous run could not read it:

> `service/credentials.py:685-702` - `resolve_credential` ... *"Raises
> `CredentialNotYours` for absent AND foreign - and for an unowned run, because
> every credential has an owner and a run with none can own nothing."*

```python
    user_id = current_run_user.get()
    if not user_id:
        raise CredentialNotYours(str(credential_id))      # credentials.py:698-701
```

An anonymous launch writes `user_id=None` on the run
(`service/app.py:1733`, `user_id=user.id if user is not None else None`),
so **every** `credential_id` on **every** node of an anonymously-launched graph
raises before the tool is built - inside `bind_attachments`, at agent
construction, with no TOOL observation at all. That is a *node* failure, not a
tool failure, so it would not satisfy "a tool that throws" even if the row
existed.

**Conclusion.** The credential arm of `audit/app-surface.md` section 9.2(A)
needs an identity end to end. It is kept below as the alternative, for a backend
that has one; the injection actually used needs no credential.

## 2. The injection used: a keyless library tool whose target cannot resolve

`the_sounding_line` is a `tool` node naming the catalogue id
**`scrape_website`** - `builder/tools.py:783-790`, `credential_kind` absent, so
`tool_problems` requires no credential (`builder/tools.py:1475-1487`). Its
factory is

```python
def _scrape_website(params, credential, policy):            # builder/tools.py:497-502
    import crewai_tools
    return crewai_tools.ScrapeWebsiteTool(tool_failure_policy=_policy(policy))
```

The authored agent's task orders exactly one call at exactly one URL:
`website_url` set to `https://sounding-line.invalid/shoals`. `.invalid` is
RFC 2606 reserved and resolves nowhere, on any network, forever.

### The raise path, file:line

| # | file:line | what happens |
| --- | --- | --- |
| 1 | `crewai_tools/tools/scrape_website_tool/scrape_website_tool.py:69-77` | `_run` calls `page = safe_get(website_url, ...)`, with **no `try`/`except` anywhere in the method** |
| 2 | `crewai_tools/security/safe_requests.py:133` | `current_url = validate_url(url)` - before any socket is opened |
| 3 | `crewai_tools/security/safe_path.py:243-249` | `socket.getaddrinfo(...)` raises `socket.gaierror`; it is caught and re-raised as `raise ValueError(f"Could not resolve hostname: '{parsed.hostname}'") from exc` |

**Measured** 2026-09-05, no network reachable and no money:

```text
$ ./.venv/Scripts/python.exe -c "import crewai_tools; crewai_tools.ScrapeWebsiteTool()._run(website_url='https://sounding-line.invalid/shoals')"
RAISED builtins.ValueError | Could not resolve hostname: 'sounding-line.invalid'
  File ".../crewai_tools/security/safe_requests.py", line 133, in safe_get
    current_url = validate_url(url)
  File ".../crewai_tools/security/safe_path.py", line 249, in validate_url
    raise ValueError(f"Could not resolve hostname: '{parsed.hostname}'") from exc
```

### Why this repository's own research tools cannot satisfy this row

Because **they do not raise, by design.** `tools/market_research.py:282-289`:

```python
        except Exception as exc:
            status, notes = _error_status(exc)
            return _envelope(status=status, query=actual_query, ...)
```

The same shape is in `hn_sentiment.py` and `github_feasibility.py`. A wrong or
missing key there produces a `"failed"` **envelope**
(`market_research.py:241-249`), which the serializer lifts to
`tool_status: "failed"` on a `WARNING` frame (`events/serializer.py:549-564`) -
`app-surface.md` section 9.2(C)'s *partial* failure, and explicitly **not** a
throw. So `research_market_landscape` cannot satisfy D2 whatever key it is
given.

`build_custom_tool` cannot either: `builder/tools.py:1343-1349` -
`except Exception as exc:  # noqa: BLE001 - a tool reports, never raises`.

### Making the exception escape the step

`chart_the_shoals` carries `"tool_failure_policy": "raise"`
(`AuthoredAgentConfig.tool_failure_policy`, declared at
`builder/document.py:126-128` and `:432`). It reaches the tool instance through
`builder/runtime.py:698-702` (`bind_attachments(..., failure_policy=...)`) and
the agent through `:719`. CrewAI resolves most-specific-first
(`crewai/tools/tool_failure.py:177-205`) and, at `:381-382`:

```python
    if policy is ToolFailurePolicy.RAISE:
        raise ToolExecutionFailedError(record)
```

so the failure leaves the step instead of being narrated back to the model.
`warn` would also be legible - the event is emitted either way
(`tool_failure.py:57-68`) - but `raise` also fails the node and the run, which
is the louder and the cheaper outcome.

### What the app should record (`app-surface.md` section 5.2, checked at head)

| frame | site |
| --- | --- |
| `FrameKind.TOOL`, `stage: "error"`, `tool`, `query`, `error`, level `ERROR` | `events/serializer.py:565-566`, fed by `ToolUsageErrorEvent` from `crewai/tools/tool_usage.py:451-452` then `:1005-1028` |
| the node's own error frame with `error_class`, `attempt`, `will_retry`, `routed` | `builder/runtime.py:1680-1704` |
| run-level `FrameKind.ERROR` / `WORKFLOW_END`, run status `FAILED` | `service/registry.py:2770-2785` |

`on_error` is `"fail"` and `retry` is unset (`max_retries` 0), so there is one
node attempt and no error edge.

### The C2 identifiers, and the one part of C2 the builder cannot satisfy

- agent **role** - `Tidewater Cartographer`, `nodes[2].config.role`. Reaches
  every frame through the actor stamp and the descriptor's `agent_role`.
- **node id and label** - `chart_the_shoals`, both spellings identical.
- `sounding line` appears in the goal **and** in the backstory.
- Absence at the pre-Task-3 commit is `absent-before.txt` beside this file.

**The tool name is the server's, not the author's, and that is a fact about the
builder rather than a shortfall of the tracing.** A `tool` node carries a
`tool_id` out of a closed server-owned catalogue and nothing else
(`builder/document.py:597-614`; the rule is stated at `builder/tools.py:1-8`).
So the name that will appear as the TOOL observation is `ScrapeWebsiteTool.name`
- **`Read website content`** - and `scrape_website` is what appears in the
document. Neither is invented by the author. The only tool an author *does*
name is a custom HTTP tool (`parse_custom_tool`, `builder/tools.py:982-995`),
and that is the one tool in the product that can never raise. **Naming the tool
and having it throw are mutually exclusive here**; record it that way in
`RUNS.md`.

## 3. The request sequence on the paid backend

Anonymous throughout - no `Authorization`, no `X-Synthetic-User`. There is no
credential step, which is the point of section 1.

```bash
BASE=http://127.0.0.1:8000
DOC=docs/observability/evidence/proof/builder-toolfail/document.json

# 1. validate. Expect 200 with valid=true, problems=[]
curl -sS -X POST "$BASE/api/builder/validate" -H 'content-type: application/json' \
     --data "{\"document\": $(cat $DOC)}"

# 2. create. Expect 201; keep .id (ug_xxxxxxxx) as $ID
curl -sS -X POST "$BASE/api/builder/workflows" -H 'content-type: application/json' \
     --data "{\"document\": $(cat $DOC)}"

# 3. publish. Expect 200 with gated_before_spend=true
curl -sS -X POST "$BASE/api/builder/workflows/$ID/publish"

# 4. launch, unattended. Expect 202
curl -sS -X POST "$BASE/api/sessions/proof-toolfail/runs" -H 'content-type: application/json' \
     --data "{\"workflow_id\":\"$ID\",\"inputs\":{\"idea\":\"the Tidewater approaches, north channel\"},\"gates\":\"auto\"}"
```

Two rules decide steps 3 and 4, and this document already satisfies both:

- **`gates` must be `"auto"`, and the graph must HAVE a gate.**
  `service/app.py:1679-1724`: `gates="auto"` is 403 for an anonymous caller
  unless `VALIDATOR_ALLOW_AUTO_GATES` is set (it is, in `.env`), and 422 if
  `workflow_has_gates` is false. `auto` sets the reserved `no_gates` state key,
  which `builder/gates.py:162-166` answers with `{"decision": "approve"}` - so
  nobody has to be at the gate. **`gates:auto` is what makes this unattended.**
- **The graph must be gated before it spends.** `service/app.py:1644-1661`
  refuses an anonymous launch of a graph that reaches a billable node before any
  gate, with 403, unless `BUILDER_ALLOW_GATELESS_GRAPHS` is set - it is not, and
  should stay unset. `start_survey` sits between `the_brief` and
  `chart_the_shoals`, so `gate_before_first_billable`
  (`builder/descriptor.py:452-482`) answers **true**; the publish response in
  `synthetic-check.txt` says `"gated_before_spend": true`.

**Cost.** Static estimate **$0.0337**, 3 modelled calls, 1 billable node, 0
escalation (the validate response in `synthetic-check.txt`). The real bill is
one or two cheap-tier calls plus whatever the tool-retry loop adds; the tool
call itself is a DNS failure and costs nothing.

## 4. The alternative, for a backend that has an identity

If the paid backend is ever run with an auth server, swap
`the_sounding_line.config` for

```json
{ "tool_id": "firecrawl_search", "params": { "limit": 1 }, "credential_id": "<cr_...>" }
```

and create the credential first:

```bash
curl -sS -X POST "$BASE/api/builder/credentials" -H 'content-type: application/json' \
     --data '{"kind":"firecrawl","label":"deliberately wrong","fields":{"api_key":"fc-00000000000000000000000000000000"}}'
```

This raises too, one layer deeper. `builder/tools.py:401-414` constructs
`crewai_tools.FirecrawlSearchTool(api_key=...)`, whose `_run`
(`firecrawl_search_tool.py:106-116`) calls `self._firecrawl.search(...)` with no
`try`/`except`; firecrawl-py answers 401 and
`firecrawl/v2/utils/error_handler.py:87-89` raises `UnauthorizedError`.
**Measured** 2026-09-05, free:

```text
$ ./.venv/Scripts/python.exe -c "from firecrawl import FirecrawlApp; FirecrawlApp(api_key='fc-000...').search(query='tidewater sounding line', limit=1)"
RAISED firecrawl.v2.utils.error_handler.UnauthorizedError
msg: Unauthorized: Failed to search. Unauthorized: Invalid token - No additional error details provided.
  File ".../firecrawl/v2/methods/search.py", line 50, in search
    handle_response_error(getattr(err, "response"), "search")
  File ".../firecrawl/v2/utils/error_handler.py", line 89, in handle_response_error
    raise UnauthorizedError(message, response.status_code, response)
```

`firecrawl_search` **requires** a credential; without one the document is
refused before publish. Measured against the live validate route:

```text
firecrawl_search with NO credential_id -> valid=false
   error tool-credential-required | the_sounding_line runs 'Search the web (Firecrawl)',
   which needs a firecrawl key, and names none; add a firecrawl credential and pick it here
```

and **with** one an anonymous validate answers `valid=true,
identity_checked=false` - `builder/compiler.py:1817-1847` only asks whether the
row is the caller's when there is a caller, so an anonymous green is not a
promise the run will resolve it. That is exactly the trap section 1 describes.

## 5. A2 / D5 - launching two runs at once

`RUN_CONCURRENCY=2` makes two runs **execute** together rather than queue, and
this is what makes that true:

- `config.py:1270` - `RUN_CONCURRENCY = int(os.getenv("RUN_CONCURRENCY", "1"))`.
- `service/app.py:741-760` builds `RunRegistry(...)` with **no** `max_workers`,
  so `service/registry.py:1380-1381` takes `max_workers = RUN_CONCURRENCY`.
- `service/registry.py:1460-1462` -
  `ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="brief-run")`.
  Two workers, two runs in flight; at the default of 1 the second would sit in
  the pool's queue until the first finished.
- Admission is a separate and larger bound: `MAX_QUEUED_RUNS = 8`
  (`config.py:1414`), counted by `_active_slots` (`registry.py:1534-1545`), so
  two concurrent launches are nowhere near it.
- Isolation is by identity rather than by a filter: each `_execute` enters its
  own `capture_events(...)` on its own pool thread (`registry.py:2715-2722`),
  and `events/context.py:41` resets `current_node_scope`, so a reused thread
  cannot inherit the other run's sink. This is the case `app-surface.md`
  section 10.1 says only shows up "the first time `RUN_CONCURRENCY` is raised
  above 1".

Recipe, with the backend already carrying `RUN_CONCURRENCY=2`. Both bodies are
prepared first so the two POSTs leave within two seconds of each other:

```powershell
$validator = '{"workflow_id":"idea-validator","inputs":{"idea":"<the real idea>"},"gates":"auto"}'
$toolfail  = '{"workflow_id":"<ug_id>","inputs":{"idea":"the Tidewater approaches, north channel"},"gates":"auto"}'

$a = Start-Job { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/sessions/proof-a/runs" `
        -ContentType 'application/json' -Body $using:validator }
$b = Start-Job { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/sessions/proof-b/runs" `
        -ContentType 'application/json' -Body $using:toolfail }
Receive-Job -Job $a,$b -Wait | ConvertTo-Json -Depth 4
```

PLAN.md's preferred form applies: these are `validator-live` and
`builder-toolfail` themselves, launched concurrently, so A2/D5 costs no extra
run. Record both run ids, then check that neither Langfuse session carries a
frame belonging to the other run.

## 6. What to record in `RUNS.md`

1. The credential injection was **not performable** on this backend, and the
   reason is identity rather than tooling (section 1). The tool that throws is
   keyless instead.
2. The tool NAME in the trace is the server's (`Read website content`, from the
   catalogue id `scrape_website`) and never the author's; C2's "tool name
   appears verbatim" can only be satisfied that way (section 2).
3. Whether the model actually called the tool. The task orders one call in plain
   words and `expected_output` demands the URL be cited, but a model can still
   answer without calling. If it does, the run **completes** with no TOOL frame
   and D2 is unmet - relaunch with the instruction hardened, and say in
   `RUNS.md` that it took two attempts.

## 7. The second tool: `sounding_line_lookup`, and what it costs to have it

Added 2026-09-05 on the orchestrator's follow-up, **after** sections 1-6 were
written. It changes which body `document.json` holds, so read this before
posting anything.

### What was added

`the_depth_register`, a second `tool` node on the same agent, naming a **custom
HTTP tool the author named themselves**:

```json
{ "id": "the_depth_register", "kind": "tool", "label": "The depth register",
  "config": { "tool_id": "ut_786b6870f07e", "params": {} } }
```

created by

```bash
curl -sS -X POST "$BASE/api/builder/tools/custom" -H 'content-type: application/json' \
     --data '{"name":"sounding_line_lookup",
              "description":"Look a stretch of water up in the survey office depth register and return the recorded soundings for it.",
              "properties":[{"name":"water","type":"string","description":"The stretch of water to look up","required":true}],
              "request":{"method":"GET","url":"https://sounding-line.invalid/depths","timeout_seconds":15}}'
```

and the task now orders **both** calls, `sounding_line_lookup` first and then
`scrape_website` on the shoals URL, with each tool's return reported by name.

Two tools on one agent is well inside `MAX_ATTACHMENTS_PER_NODE = 8`
(`config.py:2366`); the builder refused nothing about it. The name is legal:
`CUSTOM_TOOL_NAME_PATTERN` is `^[a-z][a-z0-9_]{0,39}$` (`config.py:3300`), and
`sounding_line_lookup` is 20 characters of lowercase and underscores.

### Where the author's name becomes the name CrewAI sees

This is the whole point of the addition, and it is one line:

```python
    class _CustomHttpTool(BaseTool):                 # builder/tools.py:1307
        name: str = spec.name                        # builder/tools.py:1308
        description: str = spec.description
```

`spec` is the `CustomToolSpec` parsed from the author's own JSON
(`parse_custom_tool`, `builder/tools.py:982-995`, where `name` is checked
against `CUSTOM_TOOL_NAME_PATTERN` and nothing else touches it). So the tool
instance CrewAI is handed is literally called `sounding_line_lookup`, and every
tool event carries `event.tool_name` off that instance -
`crewai/tools/tool_usage.py:1005-1028` for the error path and the
`ToolUsageStarted`/`Finished` pair for the happy one, which
`events/serializer.py:549-566` turns into `details.tool` on the TOOL frame.
`CustomToolSpec.as_entry()` (`builder/tools.py:968-971`) puts the same string in
the catalogue `label`, so the picker and the trace agree.

**After this change the two C2 halves are split across the two tools**:
`sounding_line_lookup` is the invented TOOL NAME appearing verbatim, and
`scrape_website` remains the D2 raise. Section 2's sentence "Naming the tool and
having it throw are mutually exclusive in this product" is still exactly true -
it is *why* two tools were needed rather than one.

### What it costs: the document is no longer launchable anonymously

**A custom tool has an owner by construction, so the whole graph now needs
one.** `builder_api.py:1817-1834`, `require_owner`, in its own words: *"Unlike a
document - which may be unowned ... a tool, a server and a skill are per-user by
construction (15 C10 makes `user_id` NOT NULL on all three)."*

**Measured**, in the transcript appended to `synthetic-check.txt`:

```text
POST /api/builder/tools/custom                                       -> 401 "sign in first; tools, MCP servers and skills belong to somebody"
POST /api/builder/tools/custom  -H 'X-Synthetic-User: proof-author'  -> 201 {"id":"ut_786b6870f07e","name":"sounding_line_lookup",...}
POST /api/sessions/.../runs                    (anonymous, owned doc) -> 404 "workflow not found"
POST /api/sessions/.../runs  -H 'X-Synthetic-User: proof-author'      -> 202
```

That is the **same wall** as section 1's credential, reached by a different
route, and it has the same consequence: **on the paid backend PLAN.md describes
- `.env` loaded, no `AUTH_BASE_URL`, not synthetic - there is no identity, so
`POST /api/builder/tools/custom` answers 401 and `sounding_line_lookup` cannot
be created at all.**

There is a trap on top of it, which the transcript deliberately shows:

```text
POST /api/builder/validate  (ANONYMOUS, two-tool document) -> 200 valid=true problems=[] identity_checked=false
```

An anonymous validate of a document naming a `ut_` id comes back **clean**,
because `tool_problems` leaves such an id alone when there is nobody to ask:

```python
        if entry is None:
            if config.tool_id.startswith("ut_"):
                if custom_tools is None or custom_tools(config.tool_id):
                    continue                          # builder/tools.py:1436-1439
```

The refusal arrives at run time instead, before either tool is built and before
the model is called:

```python
def _custom_tool_spec(node_id: str, tool_id: str) -> Any:      # builder/runtime.py:1490
    store, user_id = _attachment_store("CustomToolStore")
    if store is None:
        raise BuilderRuntimeError(
            f"node {node_id!r} names the custom tool {tool_id}, and this run has no "
            "identity to look it up for"                        # builder/runtime.py:1493-1496
        )
```

`bind_attachments` (`builder/runtime.py:1408-1430`) dereferences attachments in
the order they were drawn and this raises on the first one, so an anonymous paid
run of the two-tool document would **lose C2 and D2 together**: no TOOL frame of
any kind, one node error, run failed.

### Which body to POST - a decision for the orchestrator

Two files now sit in this directory:

| file | tools | launchable by | proves |
| --- | --- | --- | --- |
| `document.json` | `sounding_line_lookup` + `scrape_website` | a **signed-in** caller only | C2's invented tool name **and** D2's raise |
| `document-anonymous.json` | `scrape_website` only | anonymous, which is the PLAN.md backend | D2's raise; C2 through the role and node id only |

`document.json` was overwritten because validation was clean, which is what the
follow-up instructed. But it is **not postable to the backend PLAN.md
describes**, for the reason above, and the anonymous green at `/validate` will
not warn anybody. So either:

- **run the paid backend with an identity** - an auth server; `SYNTHETIC` is not
  an alternative, since it makes every run fake - mint the tool there, and
  substitute the returned `ut_` id into `document.json`; or
- **post `document-anonymous.json`** instead and accept that C2's tool-name half
  is unmet, recording in `RUNS.md` that this builder cannot let an author name a
  tool without an identity.

**`ut_786b6870f07e` is this synthetic backend's row id and exists nowhere else.**
A custom tool id is minted per deployment per owner, so on whatever backend the
paid run uses, create the tool first and replace the `tool_id` in
`document.json` with whatever the 201 returns.

### What the follow-up does NOT prove

The appended transcript ran on the synthetic backend, where
`SyntheticCrewFactories` replaces both tools: the run completed with **0 TOOL
frames**. That `sounding_line_lookup` will appear as the TOOL observation name
is a prediction from `builder/tools.py:1308`, not a measurement.

Note also that the custom tool **reports rather than raises**, by design
(`builder/tools.py:1343-1349`), so on a paid run its call against
`https://sounding-line.invalid/depths` produces a `"failed"` envelope with the
DNS/SSRF refusal in `notes` - a `WARNING` TOOL frame carrying
`tool_status: "failed"` and the name `sounding_line_lookup`. That is exactly
what C2 wants and exactly not what D2 wants, which is why `scrape_website` is
still attached beside it.
