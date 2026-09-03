# 01 — Auth and workspaces

Login, per-user scoping, and the credential vault. Written 2026-09-02
against `25634c0`. Owns contract **C4** (credentials) and the isolation
rules every later plan applies; consumes **C10** (tables, owned by 15).

## Problem

Sign-in exists and is sound. Better Auth mints a fifteen-minute Ed25519 JWT
on the SPA's own origin, FastAPI verifies it offline against JWKS with an
algorithm allow-list, one generic 401, and a cache that survives a failed
refetch (`service/auth.py:101-268`). Runs and builder documents carry
`user_id`; a row you do not own answers 404, never 403, because a 403
confirms it exists (`app.py:756-776`, `store.py:602-610`). The rate limit is
keyed by the verified user id (`app.py:932`).

What the gauntlet's isolation rubric needs and the tree does not have:

1. **A published graph can be launched by anyone who knows its id.** `register_builder_workflow` (`service/graph.py:322`) records no owner, `create_run` checks admission and gating but not ownership (`app.py:1061-1096`), and `/api/workflows` lists every registered workflow. User B can run user A's flow and pay for it out of the platform key.
2. **There is nowhere to keep a user's own API key.** No credential table, no encryption, no BYO key; `grep -ri 'credential|secret|fernet|encrypt' src/` finds only a redaction allow-list and JWT plumbing. Every external credential is a process-wide environment variable (`market_research.py:241`, `github_feasibility.py:333`, `pinecone_retrieval.py:68`).
3. **The builder has no identity.** `App.vue:60-67` passes `BuilderView` no `user` and no `authenticated`; the builder shows no account chip and cannot render a per-user picker for anything.
4. **`POST /api/builder/validate` is anonymous** by design (`builder_api.py:538-559`), which was right while validation touched no per-user state. A document that references a credential, a skill or an MCP server can only be validated against its owner's rows.
5. **No zero-cost way to be two users.** The E2E stub auth origin returns one signed-in session (`e2e/vite.e2e.config.ts:24-42`) and FastAPI, with no `AUTH_BASE_URL`, sees everyone as nobody. Rubric 14 cannot be exercised end to end without money or a real Google account.

## Scope

- Identity reaches the builder: `user` prop, account chip, sign-out, and the `authedFetch` path `builderApi` already uses (`services/builderApi.ts:11, 244, 301`; `httpCore.ts:47-84` retries exactly once on 401).
- **Ownership of published workflows**, enforced on launch, list and graph read.
- The **credential vault**: table, cryptography, API, run-time resolution, redaction, export stripping, BYO OpenRouter key.
- The three isolation rules, stated once here and applied by 06, 07, 08, 13 and 15 to their tables.
- `validate` gains an optional identity.
- A **synthetic identity** for zero-cost two-user tests.
- The isolation test matrix (rubric 14).

## Out of scope

- Teams, organisations, sharing, roles. A "workspace" in v1 is one user's scope.
- Email/password, SSO, MFA. Google only (`frontend/server/auth.ts:106-109` disables email/password explicitly).
- Credential sharing between users, and a key-rotation UI. Rotation is `key_version` plus a CLI re-encrypt script, specified but not built in v1.
- Encrypting `flow_states` / `run_frames` at rest. Frames are redacted, not encrypted; the database's own at-rest encryption is Render's.

## Design

### D1 — Ownership on published workflows, and 404 on launch

`BuilderWorkflow` gains `user_id: str | None`, written by `publish` from the
document's owner (`builder_api.py:561-629`) and by rehydration from the row
(`builder_rehydrate.py:208-242`). Three checks follow:

| Where | Rule |
| --- | --- |
| `create_run` (`app.py:1061`) | a builder workflow whose `user_id` is set and differs from the caller's → **404 `workflow not found`**, before admission, so a stranger's probe costs nothing and learns nothing |
| `GET /api/workflows` | builder workflows are listed only to their owner; the two hand-written flows stay public |
| `GET /api/workflows/{id}/graph` | same 404 collapse |

An **unowned** published workflow (published anonymously, in `SYNTHETIC`
mode or before this change) stays launchable by anyone, for the same reason
unowned rows stay readable: refusing them would strand every graph ever
published. `runs.user_id` already records who launched; nothing changes
there.

### D2 — The three isolation rules, applied to every new table

1. **Owner column, `NOT NULL`.** New tables (`user_credentials`, `user_skills`, `mcp_servers`, `user_tools`, `builder_test_inputs`) never existed before auth, so unlike `runs.user_id` (nullable, `persistence.py:138-142`) they have no legacy rows to protect. A request with no identity gets **401**, not a public row.
2. **List is scoped in SQL**, never filtered after the fact (`store.py:293-297` is the pattern).
3. **Single-row access collapses not-found and not-yours into one 404**, through one exception class per store, rendered by `_guarded` (`builder_api.py:689-708`).

Identity resolution order in `current_user` (`app.py:716-754`) becomes:
bearer JWT when `AUTH_BASE_URL` is set → synthetic header (D8) when
`SYNTHETIC=1` **and** `AUTH_BASE_URL` is unset → `None`. Owned routes call
`require_user`, which turns `None` into 401 with `WWW-Authenticate: Bearer`.

### D3 — The vault: AES-256-GCM, a master key from the environment, the row bound into the ciphertext

`service/credentials.py` owns encryption and is the only module that ever
sees a plaintext secret outside a tool constructor.

- Cipher: **AES-256-GCM** from `cryptography` (already installed — `pyjwt[crypto]`, `pyproject.toml:52`; 50.0.1 in `.venv`). A 12-byte random nonce per write. **Associated data = `credential_id || user_id`**, so a ciphertext copied under another user or another id fails to authenticate rather than decrypting.
- Master key: `CREDENTIALS_MASTER_KEY`, base64 of 32 bytes, read once in `config.py` through the same `_env_*` helpers as every other knob (so the §6 scan finds it). `key_version` on every row, default 1, for a future re-encrypt pass.
- Boot check, mirroring `app.py:519-524`: **auth on and no master key → refuse to start.** Auth off and no key → the credential routes answer **503 `credential vault is not configured`**; nothing else changes.
- Flowise's primitive is the counter-example: `crypto-js` `AES.encrypt(json, passphrase)` is OpenSSL `EVP_BytesToKey` + CBC with no authentication tag (`docs/flowise-notes.md` §4). Its *shape* — plaintext name beside encrypted data, secret never returned to the client — is kept.

### D4 — Kinds, fields, probes

A credential has a `kind`, a `label`, and one or more fields. The vault
stores the fields as one encrypted JSON object; the API never returns them.

| kind | fields | consumed by | probe (`POST /{id}/test`) |
| --- | --- | --- | --- |
| `openrouter` | `api_key` | `llm.credential_id` → `LLM(api_key=…)` | `GET https://openrouter.ai/api/v1/auth/key` (free) |
| `firecrawl` | `api_key` | Firecrawl tools | format check only, and the response says so — Firecrawl has no free authenticated read |
| `serper` / `tavily` / `exa` / `brave` | `api_key` | the web-search tool's provider | provider's cheapest authenticated call, each named in 06 |
| `github` | `token` | `GitHubFeasibilityTool` | `GET https://api.github.com/rate_limit` (free) |
| `postgres` | `dsn` | `NL2SQLTool(db_uri=…)` | `SELECT 1` with a 5 s timeout |
| `http_header` | `name`, `value` | custom HTTP tools (06) | none — format check |
| `mcp_header` | `name`, `value` | MCP server headers (07) | the server's `initialize` (07 owns the call) |
| `e2b` | `api_key` | sandbox tools, if the owner decides (06) | not built in v1 |

A probe is a **user-initiated** call and is rate-limited with the run
limiter's key. A failed probe returns `{ok: false, detail}` with the
provider's sentence, never a stack trace.

### D5 — Resolution at run time, never at compile time

The compiled definition carries **ids only** (C5). `builder_runner` sets a
`current_run_user` ContextVar around `kickoff` and `resume`, exactly as
`builder_cancellation` scopes the cancel flag (`runtime.py:126-139`).
Inside an action entrypoint, `resolve_credential(credential_id)`:

1. loads the row **scoped to `current_run_user`** — a miss is `CredentialNotYours`, one exception for both absent and foreign;
2. decrypts with the row's `key_version`;
3. writes `last_used_at`;
4. returns a frozen `ResolvedCredential(kind, fields)` that is passed straight into a constructor and dropped.

`CredentialNotYours` at run time becomes a `node_error` frame with
`error_class: credential-not-yours` (C6) and the step fails as any tool
failure does. Synthetic factories (`runtime.py:476-484`) never call
`resolve_credential`; the synthetic path stays offline.

### D6 — Nothing secret reaches a frame, a log, an export or a document

- `_SECRET_KEYS` (`persistence.py:71-86`) gains `api_key`, `token`, `authorization`, `headers`, `dsn`, `secret`, `password`, `ciphertext`, `fields`. A test writes a frame carrying each and reads back `***`.
- The serializer's bounded field walk (`events/serializer.py`) applies the same list to `details`.
- Export (15) strips every `credential_id` and every `*_credential_id`, the way Flowise's `_removeCredentialId` recurses (`docs/flowise-notes.md` §3). An imported document with a foreign `credential_id` validates as `credential-missing` (C8), never as someone else's row.
- The document schema (C1) carries `credential_id` as an opaque string matching `^cr_[0-9a-f]{8}$`; the parser never resolves it.

### D7 — BYO OpenRouter key, and who pays

`llm.credential_id` on an authored agent, when set, becomes
`LLM(model=…, api_key=<resolved>)`; absent, the platform key is used.
Three things do **not** change with a BYO key: admission, the
`MAX_RUN_COST_USD` ceiling (`registry.py:1266-1335` prices tokens, not
keys), and the per-user rate limit. `usage.cost_usd` gains
`billed_to: "platform" | "user"` per model so the run result says whose
money it was.

### D8 — A synthetic identity, so two users cost nothing

When `SYNTHETIC=1` and `AUTH_BASE_URL` is unset, `current_user` accepts
`X-Synthetic-User: <id>` and returns a `User(id, email=f"{id}@synthetic")`.
Any other configuration ignores the header — the same fail-closed shape as
`expose_docs = EXPOSE_API_DOCS or synthetic` (CLAUDE.md §9). The E2E auth
stub (`vite.e2e.config.ts`) forwards the header from a test-set cookie, so a
Playwright test can be Alice in one context and Bob in another against the
free backend. Python isolation tests keep signing **real** Ed25519 tokens
with two subjects (`tests/service/test_auth_jwt.py` already does).

### D9 — Identity in the builder

`App.vue` passes `user` and `authenticated` to `BuilderView` as it does to
`StudioView`. The document bar gains the same account chip
(`StudioView.vue:280-301`, avatar with `referrerpolicy="no-referrer"`). The
credential picker (04) reads `GET /api/builder/credentials` through
`authedFetch`; the vocabulary stays on plain `fetch` because it resolves
before the auth gate (`builderVocabulary.ts:23-27`).

### D10 — `validate` with an optional identity

`POST /api/builder/validate` takes `Depends(current_user)` without
requiring one. With a user, credential / skill / MCP references are checked
against that user's rows and problems `credential-missing`,
`skill-unknown`, `mcp-server-unavailable` are emitted; without one, those
checks are skipped and the response carries `identity_checked: false` so the
client can say why a problem may still appear at publish. Publish always has
a user or is anonymous-and-unowned, and re-validates.

## Interfaces

### C4 — credentials (owned here)

**Table** `user_credentials` (DDL owned by 15, shape fixed here):

| column | type | note |
| --- | --- | --- |
| `id` | `VARCHAR(16)` PK | `cr_` + 8 hex, `secrets.token_hex(4)` like document ids (`store.py:43`) |
| `user_id` | `VARCHAR(128)` NOT NULL | index `(user_id, updated_at)` |
| `kind` | `VARCHAR(32)` NOT NULL | D4 |
| `label` | `VARCHAR(80)` NOT NULL | |
| `ciphertext` | `BLOB` NOT NULL | AES-256-GCM over the fields JSON |
| `nonce` | `BLOB` NOT NULL | 12 bytes |
| `key_version` | `INTEGER` NOT NULL DEFAULT 1 | |
| `created_at`, `updated_at`, `last_used_at` | timestamps | `last_used_at` nullable |

**Endpoints**, all `require_user`, all under `/api/builder/credentials`:

| method | path | body / response |
| --- | --- | --- |
| GET | `/` | `[{id, kind, label, created_at, updated_at, last_used_at}]` — never a field |
| POST | `/` | `{kind, label, fields: {…}}` → 201 same shape; 422 on an unknown kind or a missing field; 413 over `MAX_CREDENTIAL_BYTES` (4 KiB) |
| DELETE | `/{id}` | 204; 404 if absent or not yours. Documents that referenced it validate as `credential-missing` |
| POST | `/{id}/test` | `{ok: bool, detail: str}`; rate-limited |

**Python**

```python
resolve_credential(credential_id: str) -> ResolvedCredential   # service/credentials.py
class ResolvedCredential(kind: str, fields: Mapping[str, str])  # frozen
current_run_user: ContextVar[str | None]                        # set by builder_runner
class CredentialNotYours(Exception)                             # one class, both causes
```

**Document** (C1, owned by 03): `credential_id: str | None` on `tool`,
`mcp` (as `header_credential_id` / `env_credential_id` on the server
record, 07) and `llm`; pattern `^cr_[0-9a-f]{8}$`.

**Config** (Integrator adds): `CREDENTIALS_MASTER_KEY` (env),
`MAX_CREDENTIAL_BYTES = 4096`, `CREDENTIAL_ID_PATTERN`,
`CREDENTIAL_KINDS` (frozenset of D4).

### Ownership of workflows (owned here, consumed by 10, 15)

`BuilderWorkflow.user_id: str | None`; `register_builder_workflow` stores
it; `create_run`, `list_workflows`, `get_graph` apply D1.

### Synthetic identity (owned here, consumed by E2E)

Header `X-Synthetic-User: <[a-z0-9_-]{1,64}>`, honoured only when
`SYNTHETIC=1` and `AUTH_BASE_URL` is unset.

### Consumed

C5 (ids in `with:`), C6 (`node_error` with `credential-not-yours`), C8
(`credential-missing`), C10 (DDL), C12 (MCP header credentials).

## Acceptance criteria

1. `tests/service/test_workflow_ownership.py`: Alice publishes; Bob's `POST /api/sessions/{s}/runs` for that workflow answers **404** before any admission counter moves; Bob's `GET /api/workflows` omits it; Bob's `GET /api/workflows/{id}/graph` is 404; Alice's own launch succeeds. An unowned published workflow launches for both.
2. `tests/service/test_credentials.py`: create / list / delete round-trip; the list never contains a field; a second user gets 404 on Alice's id for GET, DELETE and test; a POST with no identity is 401.
3. `tests/service/test_credential_crypto.py`: a ciphertext re-labelled under another `user_id` or `id` fails to decrypt (associated-data binding); a wrong master key fails; `key_version` round-trips; the nonce is never reused across 10,000 writes.
4. `tests/service/test_boot_checks.py`: `AUTH_BASE_URL` set + no `CREDENTIALS_MASTER_KEY` → `create_app` raises with a sentence naming the knob; auth off + no key → credential routes answer 503.
5. `tests/builder/test_credential_resolution.py`: a compiled definition for a document with three credential references contains the three ids and no field value (string search over the YAML); `resolve_credential` inside the entrypoint returns the fields for the owner and raises `CredentialNotYours` for anyone else; `last_used_at` moves.
6. `tests/service/test_secret_redaction.py`: a frame whose `details` carries every D6 key name round-trips as `***` through the serializer and the persistence sanitiser; a run log export (`/logs?format=ndjson`) contains none of the plaintext fixtures.

   **Amended 2026-09-03 (round 2, D-01-3; ratified by the owner).** `fields`
   is excluded from "every D6 key name". It is the gate form's own key -
   `pending_gate.fields` is the editable half of every gate payload
   (`registry.py`, `persistence.py`, `RunStatusResponse`) - and redacting it
   by name turned every gate form into the string `***` and failed
   `RunStatusResponse` validation on the first synthetic run. The vault's
   plaintext object of the same name never reaches a frame: it lives in
   `ResolvedCredential`, whose `repr` hides it, and is handed to one
   constructor. Every other D6 name round-trips as `***` exactly as the
   sentence above says. The exclusion is pinned by
   `tests/service/test_secret_redaction.py::ListTests::test_fields_is_deliberately_not_on_the_list`,
   and this note is pinned beside it by
   `ListTests::test_the_plan_records_the_fields_exclusion_beside_the_pin`.
   Recorded as a dated amendment rather than an edit to the sentence,
   because round 1 ticked this criterion with its text unchanged and the
   deviation living only in a Status row - which is the process failure the
   critic's dimension 16 exists to catch.
7. `tests/service/test_synthetic_identity.py`: the header is honoured only under `SYNTHETIC=1` with `AUTH_BASE_URL` unset; with `AUTH_BASE_URL` set it is ignored and the bearer path wins; with neither, the caller is anonymous.
8. `tests/service/test_validate_identity.py`: `validate` with a user emits `credential-missing` for a foreign id; without a user it emits nothing and returns `identity_checked: false`.
9. `frontend/tests/builderAccountChip.spec.ts`: `BuilderView` renders the chip from the `user` prop and calls sign-out; with `authenticated: false` and auth configured, the builder shows the sign-in panel, not the gallery.
10. `frontend/tests/credentialPicker.spec.ts`: the picker lists `{kind, label}` rows filtered by the field's kind, offers "create new", and never renders a field value even when the fake API returns one.
11. E2E `e2e/isolation.spec.ts` (synthetic backend, two browser contexts via `X-Synthetic-User`): Alice creates a document, a credential and publishes; Bob's gallery lists neither; deep-linking Bob to `#/build/<alice-id>` lands on the empty builder; Bob's launch of Alice's workflow shows the console's 404 sentence and no run starts. **Rubric 14.**
12. `docs/tech-stack.md` §6's scan reports the new knob (`CREDENTIALS_MASTER_KEY`) and the count in that file is regenerated, not edited.
13. `git grep -n "api_key\|token" -- src/brief_crew/service/credentials.py` shows no `print`, no `logging` of a field value; a review checklist item, not a test.

## References

- `service/auth.py:76-83, 86-98, 101-186, 211-268`; `service/app.py:519-524, 716-776, 932, 1061-1096, 1148, 1190`; `service/graph.py:322`; `service/builder_api.py:415-420, 538-559, 561-629, 689-708`; `builder/store.py:43, 293-297, 602-610`; `service/persistence.py:71-86, 138-142, 547-549`; `builder/runtime.py:126-139, 476-484`; `service/registry.py:1266-1335`.
- `frontend/server/auth.ts:3-20, 106-153`; `frontend/src/services/httpCore.ts:47-84`; `frontend/src/services/builderApi.ts:11, 244, 301`; `frontend/src/data/builderVocabulary.ts:23-27`; `frontend/src/App.vue:60-67`; `frontend/src/views/StudioView.vue:280-301`; `frontend/e2e/vite.e2e.config.ts:24-42`.
- `docs/flowise-notes.md` §3 (export strips secrets), §4 (credential dialog, `crypto-js` AES — the anti-pattern); `packages/server/src/utils/index.ts:1553-1655`, `packages/server/src/database/entities/Credential.ts`.
- `docs/crewai-notes.md` §4 (`LLM.api_key`), §8 (tool credential fields).
- CLAUDE.md §13 (auth), §9 (`expose_docs` fail-closed shape); `docs/gotchas-and-insights.md` 14, 17, 18.
- Gauntlet: "per-user isolation", rubric 14, Forbidden "Credentials in flow JSON, exports, or logs".

## Status

**Planned · 2026-09-02.** Contract requests for 00: none — C4 is owned here
and C10's DDL is delegated to 15 with the shape fixed above. Open decisions
for the owner: (a) whether `e2b` / `daytona` credentials ship in v1 — tied
to the code-interpreter decision in 06; (b) whether unowned published
workflows stay launchable in production (D1 keeps them so; a deployment
that never published anonymously can turn that off with a one-line check).

**Criteria complete · 2026-09-03.** Built on `s1/01-api` (`bc6eab6`) and
`s1/01-ui` (`a44fa3d`), integrated on `gauntlet/plans` at `18a7944`. **No
judge round has run**; PLANS.md carries the status. Every row below was
measured on the integrated tree, not copied from a branch report.

| # | State | Where |
| ---: | --- | --- |
| 1 | done; **amended 2026-09-03 (round 2, D-01-1 / D-01-4)** | `tests/service/test_workflow_ownership.py` (14 → 23) — the 404 fires before any admission counter moves and beats the `gates: auto` 403; ownership survives a restart. **The round-1 tick rested on clean bodies only**: a body carrying one of the graph's own state names (`__builder__`, `out__<node>`) answered 422 from the request schema before the rate limiter and before the ownership 404, which is an oracle for which ids exist (D-01-1). Fixed in `config.declared_reserved_run_input_keys`; the proof is `StateKeyProbeTests`, `StateKeyProbeIsChargedTests` and `AnonymousStateKeyProbeTests` there, plus `LaunchRoute` in `tests/service/test_isolation_matrix.py` — Bob and nobody, both bodies, foreign id indistinguishable from an invented one |
| 2 | done | `tests/service/test_credentials.py` (19) |
| 3 | done | `tests/service/test_credential_crypto.py` (24) — plus a real row re-labelled by SQL `UPDATE` failing to decrypt |
| 4 | done | `tests/service/test_boot_checks.py` (8) |
| 5 | done | `tests/builder/test_credential_resolution.py` (15) — a registry run fails with a frame carrying `error_class: credential-not-yours` |
| 6 | done; **criterion amended 2026-09-03 (D-01-3)** | `tests/service/test_secret_redaction.py` (13 → 23, measured after the suffix-rule tests landed in the same file). **`fields` is NOT on the redaction list**: it is the gate form's own key, and redacting it turned every gate into `***`. Pinned by `test_fields_is_deliberately_not_on_the_list`; the criterion's own text now carries the dated exclusion, and `test_the_plan_records_the_fields_exclusion_beside_the_pin` fails if that note and the pin ever part company |
| 7 | done | `tests/service/test_synthetic_identity.py` (14) — also honoured on the `/ws` handshake (4404 for others, 4400 malformed), which D8 did not say |
| 8 | done | `tests/service/test_validate_identity.py` (18); `credential-missing` is problem code 31, fixtures regenerated, both mirrors agree |
| 9 | done | `frontend/tests/builderAccountChip.spec.ts` (12) |
| 10 | done | `frontend/tests/credentialPicker.spec.ts` (29) — a leaking fake API never reaches markup or component state |
| 11 | done, run | `frontend/e2e/isolation.spec.ts` (4, last `@launch`), green in the 33-test run of 2026-09-03 against `SYNTHETIC=1` |
| 12 | done | `docs/tech-stack.md` §6 regenerated at 41 (`52bdc2e`) |
| 13 | done | `credentials.py` matches no `print`/`logging` on a field; neither module imports `logging` |

What the build decided that the plan did not say, in the order a reader
will meet it:

- **D2's list**: `GET /api/workflows` answers the two hand-written flows plus
  the caller's own published graphs. **Unowned** builder graphs are not
  listed there — their home is `/api/builder/workflows` — so the anonymous
  set-equality invariant every existing test reads still holds. They remain
  launchable (decision 26, built on its recommendation).
- **A behaviour change on two read routes**: `GET /api/workflows` and the
  graph now take an optional identity, so an *offered bad* bearer is 401 where
  it was silently ignored. A *missing* one still gets 200.
- The run rate limiter still runs **before** the ownership 404 (existing,
  deliberate); only the registry's admission counter is guaranteed untouched.
- A **synthetic** run does resolve credentials — a database read, offline —
  and writes `last_used_at`; the plan's sentence that synthetic *factories*
  never call `resolve_credential` stays literally true.
- **Anonymous publish with credential ids is not checked** (D10 as written);
  such a graph fails at its first agent with `credential-not-yours`.
- **D9's chip sits in the builder's header row**, not the document bar: the
  bar exists only once a graph is open. Commented in `BuilderView.vue`.
- **The E2E backend needs `CREDENTIALS_MASTER_KEY`** set, or Alice's
  credential step answers 503 — the same placeholder `tests/__init__.py`
  uses is fine. And a context with no synthetic-user cookie is now
  `e2e-user` at the API as well as at the SPA (`DEFAULT_SYNTHETIC_USER`),
  because an anonymous API behind a signed-in page is a state production
  never reaches and it failed seven builder tests on the zero-console-errors
  rule (integration commit `e62235a`).
- **A console defect this plan's E2E walked into, not fixed here**: a 404 on
  `GET /api/workflows/{id}/graph` drops the console into **mock mode** and
  draws the demonstration graph under a banner naming the foreign workflow,
  because `studioApi.ts`'s probe treats every non-401 failure as "no
  backend". The launch still fails honestly (it re-probes live) and the
  isolation spec asserts that sentence. CLAUDE.md remaining-work item 43.
- `redaction.py` claimed `x-api-key` was covered; it normalises to `xapikey`
  and now has its own entry. SQLite returned naive timestamps so a row and
  its 201 disagreed by a `Z`; normalised in the summary.
- The two open decisions: (a) `e2b` — the row can exist, nothing constructs
  from it, tied to decision 3; (b) unowned launchable — built per decision 26.

**In judge · round 1 scored 2026-09-03** (`benchmarks/rounds/01-1.md`): dim 14 =
**6**, dim 16 = **7**, gate 8 not met; 4 located defects open in
`benchmarks/DEFECTS.md` as D-01-1 … D-01-4, in the critic's order, which is
the round-2 build list. The critic re-ran every suite itself.

**In judge · round 2 scored 2026-09-03** (`benchmarks/rounds/01-2.md`, persona
staff frontend engineer): dim 14 = **9**, dim 16 = **10**; gate 8 met on
score, not on rows. A row verifier re-ran all four round-1 rows and found
every defect absent. Two rows closed (D-01-3, D-01-4), two stay open held
by dimension 14 under its reference (D-01-1, D-01-2), and one new row
opened (D-01-5, a sign-out that leaves the previous user's draft and run
pointer in browser storage): **3 open**, the round-3 build list. Round 3's
critic is the CrewAI power user.
