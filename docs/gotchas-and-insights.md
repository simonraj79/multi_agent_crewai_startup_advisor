# Gotchas and Insights

Every entry below cost somebody real time, and **none of them is discoverable
from the code that obeys them.** That is the entry criterion: if reading the
source would have told you, it belongs in a comment at the site, not here.

## How to use this file

- **Numbering is continuous and is never compacted.** Other files cross-
  reference these by number (`CLAUDE.md` says "see trap 5" in five places), so
  entries are retired in place rather than removed and renumbered.
- **Entries 1–6 keep the numbers they had** when they lived in `CLAUDE.md`
  under "Traps that were hit for real".
- **This file is the only copy.** If you find yourself restating one of these
  somewhere else, link instead. The repo has already proved four separate times
  that duplicated prose drifts — see entry 28, which is the story of a count
  that was wrong five times running.
- Each entry is **symptom → cause → what to do**. The symptom comes first
  because that is what you will have when you arrive.

---

## Deployment and platform

### 1. The database's `ipAllowList` is empty

**Symptom.** `/readyz` reports the storage backend is unreachable, with nothing
wrong at startup.

**Cause.** On Render an empty allow list means *no external connections at all* —
only traffic from inside the same region. It is not a missing control, it is the
tightest possible one.

**Do this.** `DATABASE_URL` must be the **internal** connection string, and every
service that touches the database must stay in `singapore`. Move one and it
becomes unreachable with no configuration change to blame.

> `render.yaml` and `docs/deploying.md` used to assert the live database
> "already has an allow list" that an apply would overwrite — reassurance about a
> control that does not exist. Both were corrected in `e539811`. The entry stays
> because the *reasoning* has to survive, not because the files still lie.

### 2. `VITE_API_URL` is a build-time variable, and getting it wrong is silent

**Symptom.** The console renders a complete, plausible validation run that never
happened. No error anywhere on screen.

**Cause.** Two compounding facts. Vite bakes `import.meta.env` at build time, so
changing it does nothing until the site is redeployed. And it must be a **full
origin including `https://`** — `fromService … property: host` yields a bare
hostname, which resolves as a relative path, breaks `/ws`, and drops the client
into its silent scripted mock.

**Do this.** Set a full origin, redeploy, and check the graph version on the
canvas: `MOCK_GRAPH.version` is deliberately prefixed `mock-of-` so the page
states which transport served it. `frontend/e2e/studio.spec.ts` has a test
asserting the transport is live for exactly this reason.

### 3. Render snapshots a deploy's environment when the deploy is *created*

**Symptom.** You add an environment variable, the deploy says `live`, and the
behaviour does not change. Then it starts working on its own a minute later.

**Cause.** The snapshot happens at deploy creation, not at container start, so an
existing service needs a *second* deploy. Worse: after a deploy reports `live`,
the edge can keep routing to the draining instance for roughly a minute.

**Do this.** Redeploy after changing environment variables, then wait a minute
before believing a failure. A phantom CORS bug that fixes itself is this.

### 4. `vue-tsc -b` is incremental, and it type-checks more than `src/`

**Symptom.** A green local build, a failed **static site** build on Render.

**Cause.** `-b` builds a project graph and skips work it thinks is done; a warm
`.tsbuildinfo` can skip a newly added file entirely. A strict-null error in a
*test* file failed the site build once (commit `5daf401`).

**Do this.** `npx vue-tsc -b --force` before trusting a green local build.

### 5. `.gitignore` matched `.env` and nothing near it

**Symptom.** Seven live keys sitting untracked in the root of a **public** repo,
one `git add -A` from publication.

**Cause.** The rules were `.env`, `.env.local`, `.env.*.local`. A *backup* named
`.env.ci-bak` matched none of them. Reading `.gitignore` showed three reassuring
`.env` lines.

**Do this.** **Check the path, never the pattern.** `git check-ignore -v <the
actual filename>` is the only answer that means anything. The rule is now
`.env.*` with `!.env.example`, but the method is the lesson.

### 6. A line-anchored `grep` under-reports `config.py`

**Symptom.** An authoritative-sounding list of environment variables that is
missing several, including one that a non-Render deployment *must* change.

**Cause.** The obvious command —
`grep -oE 'os\.getenv\("[A-Z_]+"' src/brief_crew/config.py` — misses every call
the formatter wrapped so the name lands on the *next* line.

**Do this.** Use a multiline match (`grep -Pzo`, `rg -U`, or Python `re.findall`
with `re.S`). The exact scan lives in [`tech-stack.md` §1](tech-stack.md). Same
lesson as entry 5 one layer up: check the thing, not a pattern that resembles it.

### 7. `onrender.com` is on the Public Suffix List

**Symptom.** A session cookie set by one `*.onrender.com` service is simply not
present on another. No error, no warning; the browser drops it silently.

**Cause.** The [Public Suffix List](https://publicsuffix.org/) marks
`onrender.com` as a registry-like suffix, so a cookie scoped to `.onrender.com`
would be a supercookie across unrelated tenants. Browsers refuse it outright.

**Do this.** On Render's default domains, **cross-subdomain cookies do not
exist**, and Better Auth's `crossSubDomainCookies` option cannot rescue it. Two
services that must share a session have to share an *origin* — which is why
`frontend/` serves both the SPA and `/api/auth/*` from one Node process. A
genuinely separate origin needs a token in a header instead. A custom apex
domain you control does not have this problem.

### 8. A free Render web service sleeps, and that decides your architecture

**Symptom.** A perfectly reasonable design that stalls for 30 seconds at the
worst possible moment.

**Cause.** Free web services spin down when idle. Static sites do not.

**Do this.** Do not put a long-lived or latency-critical path through a free
instance. Concretely: the Node service deliberately does **not** proxy `/api` or
`/ws` to the Python API, even though that would make production mirror the Vite
dev proxy exactly — it would put the WebSocket carrying every frame of a live run
behind the instance most likely to be asleep, and a run that goes quiet at a
human gate is exactly when that happens.

---

## Toolchain and build

### 9. Node's type stripping resolves import paths literally

**Symptom.** `node server/index.ts` dies with
`ERR_MODULE_NOT_FOUND: Cannot find module '…/auth.js'`, for a file that plainly
exists as `auth.ts`.

**Cause.** Node 22.18+/23.6+ runs TypeScript by *erasing types*, not by
resolving like a bundler. `./auth.js` means `./auth.js`. It will not map the
extension back to `.ts` the way `tsx` or a bundler does.

**Do this.** Write the real `./auth.ts` in source and set **both**
`allowImportingTsExtensions` and `rewriteRelativeImportExtensions` (TS 5.7+) in
the tsconfig. `tsc` then rewrites it to `./auth.js` on emit, so one source file
both runs directly under `node` in development and compiles to correct ESM for
production. `erasableSyntaxOnly: true` keeps you inside what Node can strip —
enums, namespaces and parameter properties would break it.

### 10. `tsc -b` builds a graph, and a config outside it is checked by nothing

**Symptom.** A directory full of type errors that no build ever reports, and
that looks fine in the editor.

**Cause.** `-b` walks `references`. A tsconfig nobody references is not a node in
that graph — there is no warning, because from the build's point of view the
directory does not exist. An editor disagrees because a language server resolves
the *nearest* config walking up from the open file, which is a different
algorithm.

**Do this.** Every tsconfig must be in the root `references` array. **Prove it by
breaking it**: put a deliberate `const x: number = "nope"` in the directory,
confirm the build fails and names the file, then revert. Without that proof, "I
added the reference" is indistinguishable from the broken state.

### 11. Vite proxy keys are matched in declaration order

**Symptom.** Google sign-in redirects out, comes back, and lands on a blank 404.
Nothing appears in the auth server's log — the request never reached it.

**Cause.** `/api` is a prefix of `/api/auth`. Declared first, it swallows every
auth request and forwards it to the Python API, which knows nothing about
`/api/auth`.

**Do this.** Declare the **most specific prefix first**:

```ts
proxy: {
  '/api/auth': 'http://127.0.0.1:3000',   // must precede '/api'
  '/api':      'http://127.0.0.1:8000',
}
```

### 12. `configureServer` installs middleware before *or* after the proxy, depending on how you write it

**Symptom.** A Vite middleware that never runs, because the proxy handled the
request first.

**Cause.** Calling `server.middlewares.use()` **directly** inside
`configureServer` installs ahead of Vite's internal middlewares — and the proxy
is one of those. **Returning a function** from `configureServer` defers
installation until after them.

**Do this.** To intercept a path that the proxy also matches, use the direct
form. `frontend/e2e/vite.e2e.config.ts` stubs the auth origin this way; returned
late, every stubbed path would have been proxied to FastAPI and 404'd.

### 13. A `.gitignore` entry matches whole path segments

**Symptom.** `dist` is ignored, so you assume build output is covered, and
`server-dist/` shows up in `git status`.

**Cause.** Gitignore matches path *segments*, not substrings. `dist` never
matches the segment `server-dist`.

**Do this.** Entry 5's method again: `git check-ignore -v frontend/server-dist`
returned nothing, which is how this was caught. Check every new build-output
directory the moment you create it.

---

## Runtime and library surprises

### 14. `metadata.create_all()` never touches a table that already exists

**Symptom.** A new column works perfectly everywhere in development and every
test, then produces `no such column` from a production database *mid-request* on
the first INSERT after deploy.

**Cause.** `create_all` is create-if-absent **per table**. A table that exists is
skipped whole — including any index you added alongside the new column.

**Do this.** Ship an explicit additive migration. This repo has no Alembic, so
`persistence._add_missing_columns()` inspects and issues `ALTER TABLE … ADD
COLUMN` for what is genuinely absent, then creates indexes with
`checkfirst=True`. Constraints on the shape are deliberate: **additive, nullable
columns only.** Anything needing a backfill, a `NOT NULL`, a rename or a drop is
the point at which a real migration tool has become cheaper than the list.

`tests/service/test_additive_migration.py` builds the old table from **raw DDL**
and asserts the upgrade. Raw DDL matters: a first attempt built it from the
`Table` object with the column removed, and failed because the index definition
still referenced the column that had been taken away. That is not what a deployed
database contains.

### 15. A defaulted dataclass field cannot precede a required one

**Symptom.** `TypeError: non-default argument 'inputs' follows default argument
'user_id'` at *import*, from a field you added in a sensible-looking place.

**Cause.** `@dataclass` generates `__init__` in field order, and Python will not
accept a required parameter after an optional one.

**Do this.** Add optional fields among the other defaulted ones, not next to the
semantically related required ones. Readability loses to the language here.

### 16. `value or DEFAULT` swallows a legitimate zero

**Symptom.** A caller asks for "never cache" with `ttl_seconds=0` and silently
gets an hour — the exact opposite.

**Cause.** `0 or DEFAULT` evaluates to `DEFAULT`. Every falsy legitimate value
(`0`, `""`, `False`, `[]`) is affected.

**Do this.** `DEFAULT if value is None else value`. This one was caught by a test
that asked for `ttl=0` and observed a cache that never refreshed — the
implementation bug was found *by writing the test*, which is the argument for
writing the awkward test.

### 17. `Authorization` is not a CORS-safelisted request header

**Symptom.** Every authenticated cross-origin request fails, and it looks like
the API is down. The server logs show nothing, because the request never arrived.

**Cause.** A non-safelisted header forces a preflight, and the browser drops the
real request unless `Access-Control-Allow-Headers` names it.

**Do this.** Add `Authorization` to `CORS_ALLOW_HEADERS`. Note this does **not**
require flipping `CORS_ALLOW_CREDENTIALS` — that governs cookies and TLS client
certs, which the browser attaches on its own. A header your own JavaScript sets
is an ordinary header.

### 18. PyJWT refuses to sign *or* verify HMAC with asymmetric key material

**Symptom.** You try to write a test for the classic algorithm-confusion attack
and get `InvalidKeyError` from your own test setup.

**Cause.** PyJWT guards this on both sides, deliberately.

**Do this.** Assemble the forgery by hand (base64url segments plus an
`hmac.new(...)` signature) so the *verifier* is what is under test. And be aware
of what you have proved: PyJWT's guard is a second, independent defence, but the
`algorithms=[…]` allowlist you pass to `jwt.decode` is the one that is yours.
Never pass the token's own `alg` header — that is the whole attack.

### 19. Windows will not delete a file that still has an open handle

**Symptom.** `PermissionError: [WinError 32]` during test teardown, turning six
passing tests into seven errors.

**Cause.** A SQLAlchemy engine holding a SQLite file while
`TemporaryDirectory.cleanup` tries to remove the directory.

**Do this.** Register `engine.dispose` with `addCleanup` **after** the directory
cleanup — `addCleanup` is LIFO, so registering later means running earlier.

---

## Tests that pass for the wrong reason

This section exists because a test that passes for the wrong reason is worse than
no test: it is a green light nobody will re-examine.

### 20. `unittest discover` walks past a directory with no `__init__.py`

**Symptom.** A confident `OK` covering far fewer tests than you have. The Python
count sat at **65** for a long time and was wrong; `tests/events/` and
`tests/service/` were never being collected.

**Do this.** Add the `__init__.py` in the *same commit* as any new test
directory. `pyproject.toml` configures pytest, which collects by rootdir and
would have caught it — but pytest is not installed in `.venv`.

### 21. A constant read at construction cannot be patched afterwards

**Symptom.** A test that patches `config.SOMETHING` and passes — while proving
nothing, because the object under test captured the value at `__init__`.

**Cause.** `RunRateLimiter.__init__` reads `RUN_RATE_LIMIT_MAX_RUNS` once, inside
`create_app`. A `patch.object(config, …)` in the test body arrives far too late.

**Do this.** Inject the configured object (`create_app(rate_limiter=…)`) rather
than patching the constant. And **write the control**: a test asserting that two
users are *not* throttled is meaningless without a sibling asserting that one
user *is*. Both live in `tests/service/test_auth_endpoints.py`.

### 22. A double that diverges from its subject certifies nothing

**Symptom.** A large green suite that cannot see a defect in the deliverable
itself. Three separate incidents in this repo: the report body was untestable
because `SyntheticValidatorRunner._finish` returned no body at all (133 tests
green); `RUN_STATE` frames were asserted against `event_type` values the backend
never emits (116 tests green); the revise loop was never traversed because the
double ignored `decision`.

**Do this.** Make the double's *shape* an obligation the compiler or a fixture
enforces. `StudioApiLike` is a `Pick<StudioApi, …>`, so adding `listRuns` to the
real client broke `FakeStudioApi` until it implemented one too — the divergence
could not stay quiet. Where types cannot help, pin both sides against **one
committed fixture generated by the real serializer**
(`frontend/tests/fixtures/backendRunStateFrames.json`).

### 23. A client-side fetch will eat your test's mocked response queue

**Symptom.** 25 assertions in three files fail together, each off by one
response, after a change that touched none of them.

**Cause.** `getAccessToken()` called `fetch('/api/auth/token')` on first use.
Tests mock global `fetch` with `mockResolvedValueOnce`, so the token request
consumed the response queued for the API call.

**Do this.** Do not let infrastructure fire network requests speculatively. The
fix was also the better design: `getAccessToken` now returns `null` unless a
session is *known* to exist, so a signed-out visitor makes zero token requests
too. When a test change and a design improvement coincide, prefer the design.

### 24. An E2E test that inherits an unrelated default is not testing what it says

**Symptom.** All five `@launch` tests fail with `element(s) not found` waiting
for a gate card.

**Cause.** `useValidatorRun` defaults `gatesMode` to `'auto'`. With
`VALIDATOR_ALLOW_AUTO_GATES=1` the run completes unattended and no gate ever
appears; without it, `create_run` answers 403 and no run starts. Tests whose
entire subject is the journey *through* the gates depended on an environment
variable they never mentioned.

**Do this.** Have the test **declare** what it needs — `launchRun` now clicks
Review and asserts `aria-pressed` — rather than inherit a product default that
is free to change. And when a suite fails after your change, **stash your work
and run it at HEAD** before debugging: this one was already broken.

---

## Process and environment

### 25. `pkill` reports success on Windows and leaves the process running

**Symptom.** You patch something, restart the service, and every probe returns a
healthy 200 from the **old code**. Half an hour testing a patch that was never
loaded.

**Cause.** `pkill -f serve.exe` from Git Bash does not kill Windows processes.
The replacement then fails to bind with `WinError 10048` *in its own log* while
`/healthz` keeps answering from the stale one.

**Do this.** `Stop-Process -Name serve -Force` from PowerShell. And **read the
service log rather than trusting a 200** — a 200 says something is listening, not
that it is your code. This bit again during the authentication work: a 401 that
looked like a real defect was a backend started before the fix.

### 26. `Stop-Process -Name node` kills your MCP servers

**Symptom.** Six MCP servers disconnect mid-session, immediately after a cleanup
step that had nothing to do with them.

**Cause.** MCP servers run as `node`. A name-wide `Stop-Process` is indiscriminate.

**Do this.** Kill by PID (`$pid = Start-Process … -PassThru`), or filter on the
command line, or use a distinct port and kill the owner of that port. Never
`-Name node` on a developer machine.

### 27. Moving `.env` aside is the single most hazardous routine step here

**Symptom.** Seven live credentials in an untracked backup in a public repo.

**Do this.** Restore from a shell trap that fires on any exit, name the backup so
the ignore rules cover it (`git check-ignore -v` on the **actual filename**, per
entry 5), and check the file is back before you finish. Better still, **shrink
the window**: a process reads `.env` at import, so start the process, restore the
file immediately, and let the long test run happen against the restored file.
Verify by loading the keys and printing their *lengths*, never their values.

### 28. Counts in prose drift, and the fix is never to correct the number

**Symptom.** Confident figures that are wrong. The environment-knob count has
been published as *eleven*, *fifteen*, *eighteen*, *twenty*, and finally
**thirty-six**. The Python test count has read 65, 295, 341, 378, 415, 459, 522,
537, 660, 679, 698, 713, and 772. Both were re-corrected, and both went stale
again within days.

**Cause.** Each correction fixed the number and left the process alone. As the
knob paragraph's own earlier correction put it: *"the regex was fixed; the
process was not."*

**Do this.** **The command is the contract, not the figure.** Regenerate before
quoting anything: the env scan in [`tech-stack.md` §1](tech-stack.md), and
`unittest discover` / `vitest run` for counts. If a regenerated number surprises
you, the number is right and the prose is old. Keep figures in as few files as
possible and link to them from everywhere else.

### 29. `NODE_ENV=production` makes `npm ci` skip every devDependency

**Symptom.** The first deploy of `agentic-crew-ai-studio` failed with:

```text
added 196 packages, and audited 197 packages in 4s
> vue-tsc -b && vite build && tsc -p tsconfig.server.json
sh: 1: vue-tsc: not found
```

**Cause.** npm reads `NODE_ENV`. At `production` it omits `devDependencies` —
and `vue-tsc`, `vite` and `typescript` all live there. The 196 is the tell: a
correct install is roughly twice that. Nothing warned; the install *succeeded*.

**Why the obvious fix is wrong.** Dropping `NODE_ENV=production` makes the build
pass and is a security regression: `frontend/server/auth.ts` reads it to decide
`useSecureCookies`, so a production deploy would then issue a session cookie
with no `Secure` flag. One variable serves a build-time and a run-time purpose
that disagree, and npm resolves the disagreement in favour of the wrong one.

**Do this.** Make the install explicit — `npm ci --include=dev && npm run build`
— and keep `NODE_ENV=production` for the runtime. Any service that sets
`NODE_ENV=production` *and* builds from devDependencies has this bug latent in
it, including one whose `render.yaml` has never been applied.

### 30. Renaming a Render service does not move its `.onrender.com` subdomain

**Symptom.** `agentic-crew-ai-web` (a static site) was renamed to
`agentic-crew-ai-web-legacy` specifically to free the hostname for a new Node
service. The rename returned 200 and the name changed — and
`agentic-crew-ai-web.onrender.com` kept serving the *renamed* service, while
`agentic-crew-ai-web-legacy.onrender.com` did not resolve at all.

**Cause.** The subdomain is assigned at **creation** and is sticky. The service
name and the hostname are independent after that point.

**Consequence.** A service type cannot be changed in place either — a
`static_site` cannot become a `web_service` — so the replacement is always a
*new* service, and it collides with the old one's hostname. Render then appends
a random suffix, which is why this account already contains
`agentic-rag-app-cvhu`, `council-frontend-cvic`, `kota-7bev` and `pace-api-sw3s`.

**Do this.** Choose a **new, unused** name up front and verify it is free
(`curl https://<name>.onrender.com/` → 404 means available, 200 means taken),
*then* register that origin everywhere it is load-bearing. Here that is three
places at once — the Google OAuth redirect URI, the cookie origin, and the JWT
`iss`/`aud` — so a guessed hostname fails in three different-looking ways. This
is [trap 2](#2-vite_api_url-is-a-build-time-variable-and-getting-it-wrong-is-silent)'s
lesson one layer up: the production origin cannot be known until the service
exists, so create it first and hardcode second.

---

## Insights worth reusing

Not traps — the positive patterns that repeatedly turned out to be right.

**Derive a security default instead of declaring one.**
`VALIDATOR_REQUIRE_AUTH` defaults to `bool(AUTH_BASE_URL)`, not to `False`. A
flat default fails *open*: a deployment that configures an auth server and
forgets one boolean would serve every paid endpoint anonymously with nothing on
screen to say so. Deriving it means the half-configured state **does not exist**.
`CORS_ALLOW_ORIGINS`' empty default is the same idea: when a mistake is possible,
make the mistake the loud one.

**Refuse at startup what would otherwise be a silent misconfiguration.**
`_assert_auth_startup_safety()` refuses auth-required-without-a-server, and
refuses `"*"` CORS while auth is required. Both would start cleanly and be wrong.

**Prove a fix by breaking it.** Adding `./e2e` to `tsconfig.references` is
indistinguishable from not adding it until you introduce a type error and watch
the build name the file. Same for the additive migration, and for the
`_discard_or_listener` fix whose test fails on revert with a message naming the
replacement.

**Escape-first beats sanitise-after.** `src/utils/markdown.ts` HTML-escapes every
character *before* recognising any structure, and every emitted tag is a literal
in that file. A sanitiser is a denylist applied after markup already exists;
this is the opposite order, so there is no path by which input becomes markup.

**Answer "not found" rather than "forbidden" to a stranger.** A 403 confirms the
resource exists. Another user's run answers 404. The owner never sees it, because
the UI only asks for ids it was given.

**Put the bound where it cannot be argued with.** The run-history query filters
by `user_id` in SQL, not in Python. A bug in the service layer then *cannot* leak
another person's row, because the row was never selected.

**Name the mode, not just the value.** `CREWAI_TRACING_ENABLED` is `true` on
Render and `false` in the Dockerfile, and that read as an inversion to an auditor
until both comments said *which mode* each was choosing. A boolean without its
rationale invites a well-meaning "fix".

**A comment earns its place by explaining what the code cannot.** Prefer the
reason over the restatement — why the order is load-bearing, why the default is
derived, what was tried and rejected. Every entry above started life as a comment
that was not there.
