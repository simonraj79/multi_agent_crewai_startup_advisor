# `identity` - a signed-in caller on a PAID backend, without Google

Written 2026-09-05 by V-PROOF-IDENTITY. Everything below was **measured** on
the main tree that day, against a non-synthetic backend on **127.0.0.1:8094**,
with **no run launched and $0.00 spent**. `transcript.txt` beside this file is
the command-by-command record; `backend-8094.log` and `jwks-8093.log` are the
two processes' own logs, kept unedited.

## Why this exists

`builder-toolfail/inject.md` section 7 found that the two-tool proof document
is **not launchable by an anonymous caller**, and that nothing warns you:

* `POST /api/builder/tools/custom` answers **401** with no identity
  (`builder_api.py::require_owner` - a tool, an MCP server and a skill are
  per-user by construction), so `sounding_line_lookup` cannot be created;
* `builder/runtime.py::_custom_tool_spec` raises at bind time - *"this run has
  no identity to look it up for"* - so an anonymous run of a document naming a
  `ut_` id loses **every** tool frame, C2 and D2 together;
* and `/api/builder/validate` comes back **clean** for that same document on an
  anonymous backend, because `tool_problems` leaves a `ut_` id alone when there
  is nobody to ask.

Section 7's two ways out were "run the paid backend with an identity" or "drop
the custom tool". This directory is the first one, and it is now proved rather
than proposed.

`SYNTHETIC=1` is **not** the alternative. It would make `X-Synthetic-User` live,
but it also swaps in `SyntheticCrewFactories`, so every run on it is fake - and
the paid proof needs the real engine. Measured here: on this backend the header
is **ignored**, not honoured (section 2 of the transcript).

## The two processes

`scripts/observability/mint_identity.py` is the whole auth server. It is small
because the surface is small: `service/auth.py` verifies a bearer JWT
**offline** against `${AUTH_BASE_URL}/api/auth/jwks` and calls the auth service
for nothing else, so a stand-in needs one GET and one signature.

**Start the JWKS server first and kill it last.** `JwksCache` caches for
`AUTH_JWKS_CACHE_SECONDS` (3600) and *a failed refresh keeps serving the
previous keys* - so a backend that outlives it does not fail immediately, it
fails an hour later with `token is not valid`, which names nothing.

### Terminal 1 - the JWKS server

```powershell
.\.venv\Scripts\python.exe scripts\observability\mint_identity.py serve --port 8093
```

It prints the issuer, the `kid` and the key-file path to stderr and then serves
`http://127.0.0.1:8093/api/auth/jwks` until killed. The Ed25519 private key
lives in `%TEMP%\brief-crew-proof-identity\ed25519.pem` - **outside the
repository, and the script refuses any path inside it**. Delete it when the
proof session ends.

### Terminal 2 - the paid backend

```powershell
$env:AUTH_BASE_URL           = "http://127.0.0.1:8093"
$env:CREDENTIALS_MASTER_KEY  = "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
$env:LANGFUSE_EXPORT_ENABLED = "0"      # omit for the real proof run
$env:PORT                    = "8094"
.\.venv\Scripts\serve.exe
```

Four names and each is load-bearing:

| name | why |
| --- | --- |
| `AUTH_BASE_URL` | the issuer, the audience **and** the JWKS origin - `verify_token` passes this one value as both `issuer=` and `audience=`, and `JwksCache.url` appends `/api/auth/jwks`. It must equal the server's `--issuer` exactly, **no trailing slash**. Setting it also turns auth on: `VALIDATOR_REQUIRE_AUTH` defaults to `bool(AUTH_BASE_URL)`, so never set that separately |
| `CREDENTIALS_MASTER_KEY` | `_assert_credential_vault_startup_safety` raises a `RuntimeError` at startup when `AUTH_BASE_URL` is set and this is empty. This is **remaining-work item 46 met locally**, and it is the one that stops the process dead rather than degrading a feature. The value above is `tests/__init__.py`'s placeholder; it authenticates against nothing and is fine for a local backend. Rotating it later is *refused*, not silently re-wrapped |
| `LANGFUSE_EXPORT_ENABLED` | not an assertion - it just keeps an identity check off the trace budget. Leave it unset for the real proof run |
| `PORT` | `HOST` stays unset (127.0.0.1). `SYNTHETIC` **must** stay unset |

`CORS_ALLOW_ORIGINS` needs **no value**. `_assert_auth_startup_safety` refuses
only `"*"` while auth is required; the default is the empty tuple, `"*" in ()`
is false, and the assertion passes. Leave it unset for a curl-driven proof - it
fails closed, and no browser is involved. If a console will be pointed at this
backend, name origins instead (`http://localhost:5173,http://127.0.0.1:5173`).
Never `*`.

`.env` is loaded by `brief_crew/__init__.py` with `override=True`, so anything
it declares beats the shell. It declares **none** of those five names, so they
are safe to export; `OPENROUTER_API_KEY` and the Langfuse keys arrive from the
file as normal.

### Terminal 2, per call - one token

```powershell
$T = .\.venv\Scripts\python.exe scripts\observability\mint_identity.py token --ttl 3600
curl.exe -sS -X POST "http://127.0.0.1:8094/api/builder/validate" `
  -H "content-type: application/json" -H "Authorization: Bearer $T" `
  --data "@docs/observability/evidence/proof/identity/validate-body.json"
```

`token` writes the JWT to stdout **and nothing else** - every explanatory line
goes to stderr - so `$T = ...` is a usable idiom. Other subcommands:
`token --sub other-runner` (a second identity, for an isolation check),
`token --tamper` (one signature byte flipped), and `jwks` (the public document;
public keys only).

## What was measured

Backend on 8094, non-synthetic (`GET /docs` -> 404; `expose_docs` is
`EXPOSE_API_DOCS or synthetic`, so a synthetic instance would have served it).

| # | request | caller | status |
| ---: | --- | --- | ---: |
| 1 | `GET /readyz` | - | **200** `storage: sqlite`, `exporter: disabled` |
| 2 | `GET /healthz` | - | **200** |
| 3 | `GET /docs` | - | **404** (proves not synthetic) |
| 4 | `POST /api/builder/tools/custom` | anonymous | **401** `sign in to use this endpoint` |
| 5 | `POST /api/builder/tools/custom` | `X-Synthetic-User: proof-runner` | **401** (header ignored) |
| 6 | `POST /api/builder/tools/custom` | **tampered** bearer | **401** `WWW-Authenticate: Bearer error="invalid_token"` |
| 7 | `POST /api/builder/tools/custom` | minted bearer | **201** `ut_0595b92a265e` |
| 8 | `POST /api/builder/validate` | anonymous | **401** |
| 9 | `POST /api/builder/validate` | minted bearer | **200** `valid:true problems:[] identity_checked:true` |
| 10 | `POST /api/builder/validate` | bearer for `other-runner` | **200** `valid:false` - `tool-unknown` |
| 11 | `POST /api/builder/workflows` | minted bearer | **201** `ug_4e7e952f` |
| 12 | `POST /api/builder/workflows/ug_4e7e952f/publish` | minted bearer | **200** `graph_version c3b393e1a89362dd`, `gated_before_spend: true` |
| 13 | `POST /api/builder/workflows/ug_4e7e952f/publish` | anonymous | **401** |
| 14 | `GET /api/workflows/ug_4e7e952f/graph` | minted bearer | **200** |
| 15 | `GET /api/workflows/ug_4e7e952f/graph` | `other-runner` / anonymous | **404** each |

**Rows 6 and 10 are what make this a proof.** Row 6 says the signature is
*checked*, not merely *present* - the tampered token has a valid `kid`, valid
claims and an expiry in the future, and the only thing wrong with it is the
last byte. Row 10 says the identity is *load-bearing* - a different verified
user is refused the same document, so row 9's green belongs to `proof-runner`
and nobody else.

The keys were fetched by the backend **exactly once**, on its first bearer
request (`jwks-8093.log`, 23:47:42); every later request was served from
`JwksCache`.

## What was created, and where it lives

| thing | id | note |
| --- | --- | --- |
| custom tool | `ut_0595b92a265e` | `sounding_line_lookup`, owned by `proof-runner` |
| document | `ug_4e7e952f` | *Tidewater survey*, v1, owned by `proof-runner` |
| published workflow | `ug_4e7e952f` | `graph_version c3b393e1a89362dd`, `static_cost_usd 0.0336975`, `gated_before_spend: true` |

Both rows are in the **default local database**, `output/validator-studio.db`
(no `DATABASE_URL` was set), so they survive a restart and rehydrate at boot -
which is the point: the paid proof run can use this same workflow id without
recreating anything, provided it runs with the same `DATABASE_URL` and the same
`AUTH_BASE_URL`/key file.

`document-owned.json` beside this file is `builder-toolfail/document.json` with
the one substitution the proof needs:

```text
the_depth_register.config.tool_id:  ut_786b6870f07e  ->  ut_0595b92a265e
```

Nothing else in it changed.

## Caveats

- **A token expires.** `--ttl` defaults to 900 s, matching production's
  15-minute `expirationTime`. A long proof session wants `--ttl 3600` or a
  fresh token per call; a run already in flight is unaffected, because the
  token is checked at the request and never again.
- **`ut_0595b92a265e` is this backend's row id and exists nowhere else.** A
  custom tool id is minted per deployment per owner. Point the paid run at a
  different `DATABASE_URL` and the id is gone, `validate` says `tool-unknown`,
  and the fix is to re-create the tool and re-substitute - the same hazard
  `inject.md` section 7 records for `ut_786b6870f07e`.
- **The JWKS server must outlive the backend.** Kill it first and the backend
  keeps working for up to an hour on cached keys, then starts refusing tokens
  with a message that names nothing. Start it first, kill it last.
- **The key file is a private key.** `%TEMP%\brief-crew-proof-identity\ed25519.pem`,
  outside the repository by construction. Delete it at the end of the proof
  session; a new one is minted on the next `serve`, which invalidates every
  token from the old one (that is a feature, not a loss).
- **`sub` is the whole identity.** `proof-runner` is an arbitrary string with
  no account behind it. That is exactly what a Better Auth `sub` is to this
  API - it verifies the signature and the issuer, and takes the subject on
  trust from there - so this stand-in is faithful, not a shortcut. It is
  faithful only *for this API*; it says nothing about Google, Better Auth's own
  session handling, or `frontend/server/`.
- **The anonymous `validate` trap is silenced here, and is still a trap
  elsewhere.** `inject.md` section 7 measured an anonymous validate of the
  two-tool document coming back **200 clean** with `identity_checked:false`. On
  *this* backend the same call is **401**, because `VALIDATOR_REQUIRE_AUTH` is
  on. The clean-200 remains reachable on any keyless backend - which is the
  configuration PLAN.md describes - so the warning stands for anyone who runs
  without `AUTH_BASE_URL`.
- **No run was launched and no model was called.** Creating a tool, validating,
  saving and publishing are all free. `grep -c "sessions/" backend-8094.log`
  answers 0.

## Shutting down

By PID, backend first and the JWKS server last:

```powershell
netstat -ano | Select-String ":8094"      # then the same for :8093
taskkill /PID <pid> /T /F
netstat -ano | Select-String ":8093 :8094"   # expect nothing
```

Never `Stop-Process -Name serve`: a stale process keeps answering `/healthz`
from old code, and the symptom is a mysterious 401 (gotchas 25 and 26).
