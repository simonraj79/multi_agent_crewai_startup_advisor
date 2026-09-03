# Gotchas and Insights

Every entry below cost somebody real time, and **none of them is discoverable
from the code that obeys them.** That is the entry criterion: if reading the
source would have told you, it belongs in a comment at the site, not here.

## How to use this file

- **Numbering is continuous and is never compacted.** Other files cross-
  reference these by number - `CLAUDE.md` alone cites them on eight lines - so
  entries are retired in place rather than removed and renumbered.
- **Entries 1–6 keep the numbers they had** when they lived in `CLAUDE.md`
  under "Traps that were hit for real".
- **This file is the only copy.** If you find yourself restating one of these
  somewhere else, link instead. The repo has already proved four separate times
  that duplicated prose drifts — see entry 28, which is the story of a knob
  count whose **five** published figures in a row were all wrong before the
  sixth. (`tech-stack.md` §6 owns that tally; it is deliberately not recounted
  here — the count of wrong counts is itself a figure in prose.)
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

**It bit repeatedly again during the builder work, and on the other process.**
The E2E Vite server sets `strictPort: true` on 5273
(`frontend/e2e/vite.e2e.config.ts`), which is the right choice for a harness —
a test must never quietly end up pointed at a different server — but it turns
"port already in use" into an **exit**, not a warning. The first Vite goes on
serving happily, the browser renders the page from the **old** config, and
nothing on screen is wrong. Sharpen the rule accordingly: **read the new
process's own log and find its bind line.** A process that never printed its
`Local: http://localhost:…` line is not the one answering that URL, however
healthy the URL looks. Reading the log is what caught this every single time;
nothing else did.

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
been published as *eleven*, *fifteen*, *eighteen*, *twenty*, *thirty-six*, and
now **thirty-nine**. The Python test count has read 65, 295, 341, 378, 415, 459,
522, 537, 660, 679, 698, 713, 772, and now **1228** (the last two regenerated
2026-09-02 at `b4ef654`, by the scan in [`tech-stack.md` §1](tech-stack.md) and
by `unittest discover`). Both were re-corrected, and both went stale again
within days.

**Cause.** Each correction fixed the number and left the process alone. As the
knob paragraph's own earlier correction put it: *"the regex was fixed; the
process was not."*

*Thirty-six* — the fifth and last wrong knob figure — is the cleanest
demonstration the file has. It was regenerated correctly on 2026-09-01 at
`b1a9c19`, written into `CLAUDE.md` in bold with the scan beside it and a
paragraph explaining why the figure had been wrong four times before it. It was
stale one commit later, and **not because of the flow builder**:
`AUTH_JWKS_TIMEOUT_SECONDS` landed in `5087f3c`, so the count was already wrong
at **thirty-seven** at `4d70cbf`, the last commit before the builder existed.
The builder then added exactly **two** knobs — `BUILDER_ALLOW_GATELESS_GRAPHS`
and `BUILDER_REHYDRATE_PUBLISHED` — taking it to thirty-nine. Regenerated per
commit on 2026-09-02 with the scan from [`tech-stack.md` §1](tech-stack.md):

```text
5087f3c total=37    4d70cbf total=37    6d2743c total=39    b4ef654 total=39
ADDED BY 6d2743c: ['BUILDER_ALLOW_GATELESS_GRAPHS', 'BUILDER_REHYDRATE_PUBLISHED']
```

Nothing was careless. A figure in prose has a shelf life measured in commits,
and no amount of care about the measurement extends it. **This entry is
stronger for the correction, not weaker**: the real cause was a knob added five
commits earlier that nobody scanned for, which is a purer instance of "the
correction fixed the number and left the process alone" than a same-day merge
would have been.

**And this entry itself carried the wrong story until 2026-09-02**, in the
identical shape it warns about. It named `MAX_RUN_COST_USD` as one of three
knobs the builder added. `MAX_RUN_COST_USD` landed in `1b79197`
(`git log -S MAX_RUN_COST_USD -- src/brief_crew/config.py`) and was already
inside the correctly-measured thirty-six; `git log -S` names `6d2743c` only
because the builder *changed an existing reference* to it. The claim came from
the pass's own orchestrating handoff and was copied into two files without a
scan — so the rule this entry now carries is: **a number handed down by an
orchestrator, a handoff or a change author is exactly as trustworthy as one
copied between two documents.** Reasoning about what a commit added is not
regenerating the list. [`tech-stack.md` §6](tech-stack.md) owns the
enumeration and got it right; this entry and `CLAUDE.md` were the two that
restated it.

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

### 36. `crewai`'s lock file is an NTFS alternate data stream, and nothing ever removes one

**Symptom.** Seventeen persistence tests fail at once with
`OSError: [Errno 22] Invalid argument:
'C:\Users\<you>\AppData\Local\Temp\crewai:9e4096…ab.lock'`, on a tree that
was green an hour ago and on code that does not touch that path. Every failing
test is one that runs a real CrewAI `Flow` with persistence; nothing else
notices, and the same modules pass on a colleague's machine.

**Cause.** `crewai_core/lock_store.py:97-108` names its cross-process lock
`crewai:<md5 of the lock name>` — a Redis channel name — and, when Redis is
absent, reuses that string verbatim as a file name under
`tempfile.gettempdir()` and hands it to `portalocker`. On NTFS a colon in a
file name is stream syntax: `Temp\crewai:9e40….lock` is not a file called
`crewai:9e40….lock`, it is a named stream `9e40….lock` on a zero-byte *file*
called `crewai`. `portalocker` creates it without complaint. Every distinct
lock name adds another stream to that one file, and **nothing removes a
stream** — not the lock's release, not a test's teardown, not any cleanup this
repository runs, because none of them knows the file exists. NTFS caps how
many attributes one file can carry; measured 2026-09-03, the file (created
2026-08-29) held **2,520** `.lock` streams plus its own `:$DATA`, and the next
new lock name failed with `EINVAL`. The tests that fail are simply the ones
whose lock name has not been seen before, which is why the set looks arbitrary
and why a *new* test module fails first.

**Do this.** Delete the file — it is a file, so `-Recurse` is beside the
point:

```powershell
Remove-Item -LiteralPath "$env:TEMP\crewai" -Force
```

The streams go with it and the next run recreates it with one. To see it
coming: `@(Get-Item "$env:TEMP\crewai" -Stream *).Count`. Do not "fix" it by
pointing the tests at another temp directory — `gettempdir()` is CrewAI's
choice, not this repository's, and the count climbs again wherever it points.
The first time this presented, the path was not read literally and it cost
most of a session; the second time (six `test_builder_runner` errors during the
round-2 build) it cost one `Get-Item -Stream` and one `Remove-Item`, which is
the whole argument for this entry.

## Checks that were satisfied by the wrong thing

Five entries from the flow-builder work, kept together because they share a
shape and the shape is the lesson. In each one a check **ran**, was
**satisfied**, and was measuring something adjacent to the thing everybody
believed it measured: a mirror compared against itself, a validator that ran
earlier than the constructor, a leak hidden by a sort order, a mount with no
layout engine, and honest arithmetic about a box that stopped existing one frame
later. "Tests that pass for the wrong reason" above is the earlier half of the
same family.

### 31. A mirror kept honest by grepping for a *spelling*

**Symptom.** `PROBLEM_CODES` in `frontend/src/types/builder.ts` listed 27 codes.
The server emits 30. `builderTypes.spec.ts` — the test whose entire job is to
keep those two in step — was green.

**Cause.** Two independent failures of one mechanism. The gate greps the Python
for module-level declarations,
`/^[A-Z][A-Z0-9_]* = "([a-z]+(?:-[a-z]+)+)"$/gm`, so it is a gate on a
**spelling**, not on the codes: write
`problems.append(Problem(code="inline-literal", …))` and the regex finds
nothing, the TypeScript tuple stays at its old length, and the frontend suite
stays green while the client renders a problem it does not know. And it read two
of the **three** Python files that declare codes — so the mirror agreed with
**itself** at the wrong number, 27 against 27, with nothing left to disagree.
Among the missing was `library-missing-prompt-input`, the most common problem in
the whole builder, because a fresh agent node defaults `prompt_inputs: {}`. The
code the client was least able to render was the one it would meet first.

**Do this.** **Put the anti-drift check where the drift happens.** A test in
`frontend/` cannot fail on a Python refactor it never reads, so the guard has to
live on the Python side: `tests/builder/test_problem_code_declarations.py` walks
the AST and forbids the one shape the frontend's regex is blind to — every
`Problem(...)` must be constructed with `code=<NAME>`, and every such NAME must
resolve to a module-level constant written in exactly the spelling the regex
matches. Then enumerate the source files in both places and pin the two lists
against each other; the third file's absence was the whole of the 27-versus-30.

Both sides measured at **30** on 2026-09-02 at `b4ef654`, by the scan below and
by counting `PROBLEM_CODES`:

```bash
./.venv/Scripts/python.exe -c "import re,pathlib; D=re.compile(r'^([A-Z][A-Z0-9_]*) = \"([a-z]+(?:-[a-z]+)+)\"$',re.M); b=pathlib.Path('src/brief_crew/builder'); print(len({v for f in ('bounds.py','budget.py','compiler.py') for _,v in D.findall((b/f).read_text(encoding='utf-8'))}))"
```

### 32. A validator that runs earlier than the constructor can be confidently wrong

**Symptom.** A document naming `crew_id: "synthesis"` passed every structural
check, **published cleanly**, was priced and registered — then raised a bare
`TypeError` inside a worker thread at the moment that node ran, *after the
scoper and all three research branches had billed real money* for a context
nothing would consume.

**Cause.** `BUILDER_CREW_LIBRARY` advertises six `@CrewBase` classes and
`DefaultCrewFactories.crew` builds them with a bare zero-argument call. Two of
the six have no zero-argument `__init__`: `SynthesisCrew` wants three typed
research findings and `ReportCrew` wants a verdict and the tool URLs behind it,
both passed in Python by the validator flow. *Registered* and *buildable* are
different properties, and every check on the publish path tested the first one.

**Do this.** Move the check to the earliest door at which the failure is
knowable, then close **every** door — validate, publish **and rehydration**, so a
row published before the fix cannot walk back in through the restart that
`autoDeploy: yes` guarantees on every push to `main`. Where the check must be a
declaration rather than a derivation — importing `crews.validator_crew` into the
compiler would drag the Firecrawl, HN and GitHub clients in with it — pin the
declaration against the real thing rather than trusting it:
`tests/builder/test_crew_library_arity.py` imports the classes, reads
`inspect.signature`, and asserts the map is exactly right for all six, at no
cost and with nothing instantiated. The general form is worth saying plainly:
**a bound enforced later than the money is spent is not a bound.**

### 33. A test that was green only because `discover` sorted two modules kindly

**Symptom.** `tests/service/test_builder_rehydration.py` asserts that no `ug_`
workflow is left registered, and it passed. It passed because `unittest
discover` sorts `test_builder_rehydration` before `test_builder_runner`. The
ordering is alphabetical, so it is stable rather than flaky — which is worse,
because it will hold right up until somebody renames a module, and then a suite
that has been green for months goes red in a file nobody touched.

**Cause.** Publishing through the real HTTP surface writes **five**
process-global registration maps, and `TestClient.close` unwinds none of them,
so a published graph outlived the case that made it. Reverse the two modules and
a file that had done nothing wrong fails. Its sibling defect is the same
arithmetic one layer down: `unregister_builder_workflow` cleared **four** maps
while registration writes five, so even the explicit teardown left one behind —
and that one is not inert. A stale `WORKFLOW_RESERVED_RUN_INPUT_KEYS` entry is
the answer `all_reserved_run_input_keys` unions into **every unknown workflow
id**, so a deleted graph goes on refusing its own state names as control keys in
some later author's perfectly ordinary `inputs`, until the process restarts. The
other four maps merely make a deleted graph 404, which is loud; this one is
silent, which is why it was the one nobody cleared.

**Do this.** Register the undo at the point of the mutation — `addCleanup`
beside the publish, not at the bottom of the class — and **count the maps**: a
registration that writes N places needs an unregistration that clears N, and
that is worth an assertion rather than a careful reading. When you suspect an
ordering dependency, run the module **alone**
(`./.venv/Scripts/python.exe -m unittest tests.service.test_builder_runner`); a
green full suite cannot tell you which ordering you were handed.

### 34. A jsdom mount asserts structure and never asks how wide anything ended up

**Symptom.** Two defects that shipped behind a green unit suite. On the empty
gallery `BuilderView` renders neither rail, but `.studio-main` still declared
three columns and `.graph-workspace` still declared its rows — so the gallery
became the grid's first child and landed in the **236px palette column**, inside
a row sized for a crew strip that is not there: measured at 2000x1150, a 236x70
box holding 1356px of content, four template cards reduced to a clipped sliver.
And the canvas fitted its viewport *before* the budget meter and the problems
dock took their height, so a 16-node template opened with its last two nodes
under the dock **while reporting itself fitted** (entry 35).

**Cause.** A unit mount renders a tree and asserts on the tree. There is no
layout engine behind it, so "how wide", "at what scale" and "is any of this
clipped" are not answered wrongly — they are never asked. Every element was in
the DOM and every assertion about the DOM was true.

**Do this.** Treat it as a **recurring class**, because it is one. The console
had already produced two more: the implicit `auto` grid row that let three panes
overflow an 848px container to **1894px** (fixed with `minmax(0, 1fr)` on
`.studio-main` *plus* `min-height: 0` on its children, since a grid item's
automatic minimum size is its content), and the 18px `.canvas-heading` inset
that let the two rail collapse toggles render straight through the text, so the
heading read *"XED VALIDATOR GRAPH"*. All four were found by starting the app
and **looking**, and none of the four was ever going to be found any other way.

Note what this file's own history says about the class: it did **not** carry an
entry for it until now. The two console instances were written up at their fix
sites in `studio.css` and in `CLAUDE.md`'s frontend section — good comments, in
two places neither of which is the file somebody reads before believing a green
suite. That is exactly how a class recurs.

So assert geometry where geometry exists.
`frontend/e2e/builder-layout.spec.ts` measures the gallery's real `clientWidth`
in a browser, puts every node of the validator template inside the canvas pane,
and checks all three shell columns are present and non-zero once a document is
open.

### 35. Fitting a viewport against a container that is still settling

**Symptom.** A 16-node template opens with its last two nodes hidden under the
problems dock, on a canvas that reports itself fitted. The fits chose **0.544**,
then **0.524**, against a settled container that wanted **0.466**.

**Cause.** `fit-view-on-init` and the shell's own post-load fit each compute
against what the element measures *at that instant* — and at that instant it is
still full-bleed, because the budget meter sits in `.graph-workspace`'s `auto`
row and the problems dock below it, and neither has taken its height yet. Both
fits are honest arithmetic about a box that stops existing one frame later.

**Do this.** Observe the real signal instead of guessing at it: a
`ResizeObserver` on the canvas frame re-fits on each genuine height change. A
`setTimeout` is a guess about somebody else's layout, and that layout is free to
get slower — "long enough" is not a property you can assert. Two details the
observer has to get right, each a bug of its own if skipped: **ignore the
collapse to zero** that unmounting reports, and **stop at the author's first
gesture**, because after a wheel or a pan the viewport is theirs and a late
re-fit that discards a pan somebody just made is a worse bug than the one this
fixes. `BuilderCanvas.vue` does both, and says why at the site.

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

**Put the guard on the side that can break the invariant.** The frontend's copy
of the server's problem codes was kept honest by a test in `frontend/` grepping
Python — so the one change that would break it, a refactor inside Python, was
the one change that test could never see. The guard belongs where the breaking
edit happens (entry 31). Same shape as *prove a fix by breaking it*: ask what
edit would falsify this, then check that the edit fails something.

**Bound shape and bound money with two different bounds.** The builder's
structural counts (`MAX_BILLABLE_NODES`, `MAX_ESCALATION_NODES`, `MAX_CYCLES`)
say what a graph may look like; `MAX_RUN_COST_USD` says what it may cost.
Because the two are independent, "may we raise a count?" becomes a question with
an arithmetic answer instead of an argument:
`test_the_worst_graph_the_counts_permit_is_still_refused_on_price` builds the
pathological corner and watches the budget layer refuse it on price — so the
count was never the money bound in the first place, and
`tests/builder/test_budget.py`'s own docstring says so. A single bound doing
both jobs could not have been interrogated that way.

**Name the shape beside the money, or the money means nothing.** That test
prices **$10.55**, and $10.55 is the *pre-raise* frontier: it builds
`frontier_document(cheap=3, escalation=5)`, which is **8 billable / 5
escalation**, the bounds as they stood before `MAX_BILLABLE_NODES` went 8→13
and `MAX_ESCALATION_NODES` 5→8. The worst graph the counts permit **at head**
is 13/8 and prices at **$21.62** — 468 modelled calls, floor $15.31, static
$17.30, and the 1.25x margin applied to the *static* price rather than the
floor. The figure [`CLAUDE.md`](../CLAUDE.md) section 14 owns and regenerates. So the test
name is stale at head, and a document that quoted its $10.55 as the current
frontier would be publishing a two-releases-old number under a name that
promises the current one. Both figures were regenerated 2026-09-02 at
`b4ef654`; only the test's own constant is unchanged, because the test still
builds the old shape.

**A comment earns its place by explaining what the code cannot.** Prefer the
reason over the restatement — why the order is load-bearing, why the default is
derived, what was tried and rejected. Every entry above started life as a comment
that was not there.

## Six traps a green suite could not see — plan 15, round 2 (2026-09-03)

Recorded together because they share a shape with 31-35: every one was
invisible to 1,157 green frontend tests and 1,642 green Python ones, and two
of them were found only by LOOKING at a 1440x900 capture of the running app.
The captures are in `docs/comparison/ours/round2/` (ignored); the commits
they forced are `b249d89` and `d9672a0`.

### 37. `withDefaults` uses a Function-typed prop's default as the value, not as a factory

**Symptom.** Every version row rendered the dated form ("3 Sept, 04:38")
and never "12 s ago", in the real app only. `versionBrowser.spec.ts` was
green, 31 tests.

**Cause.** Vue calls a prop's default as a factory only for `Object` and
`Array` props; for a `Function` prop the default IS the function. The prop
was declared `clock?: () => number` with the default written as a factory,
`clock: () => () => Date.now()`, so `props.clock()` answered a *function*,
`now - at` was `NaN`, every comparison was false and every row fell through
to the dated form. The spec passed because every test handed in a stilled
clock and never exercised the default.

**Do this.** For a Function prop, write the function itself as the default:
`clock: () => Date.now()`. And give every prop default a test that does NOT
override it - the one test that would have caught this cost four lines.

### 38. A template ref is `null` at a child's `onMounted`

**Symptom.** The canvas was handed the shell's dock row as a prop and
observed it in `onMounted`; the jsdom test passed; the capture showed two
strips docked over a graph that had not moved.

**Cause.** Vue assigns template refs in a post-render effect after the whole
tree is mounted, and a child's `onMounted` runs before its parent's - so
when the child looked, `props.dock` was still `null` and `observe` was
skipped. The test passed because it handed the element in from the first
render. And the obvious repair - `watch(() => props.dock, …, { immediate:
true, flush: 'post' })` - fails the other way: an immediate post-flush
callback is queued from setup, *ahead* of the mounted hook, and runs before
the observer it needs exists.

**Do this.** Observe whatever is there at mount, and add a non-immediate
post-flush watch for the element arriving, changing or going. Test both
orders: the element present from the start, and the element set after mount.

### 39. A top-level injected ref is unwrapped in the template

**Symptom.** `inject(BUILDER_READ_ONLY, null)` in `<script setup>`, then
`v-if="readOnly?.value"` in the template; the lock never rendered.

**Cause.** Top-level refs in `<script setup>` are auto-unwrapped in the
template, so `readOnly` is already the boolean and `true.value` is
`undefined`. Reading `.value` in the template is exactly wrong for a
top-level ref and exactly right for a nested one, which is why it reads as
plausible.

**Do this.** `v-if="readOnly"`. A null default from `inject` is falsy, so the
same expression covers "outside a canvas".

### 40. SQLite drops the timezone, and `Date.parse` reads a naive stamp as local time

**Symptom.** A version saved seconds ago read "8 h ago" on a machine at
UTC+8, against a SQLite backend; the same code against PostgreSQL was right.

**Cause.** `created_at` is written with `utcnow()` into
`DateTime(timezone=True)`. PostgreSQL hands the offset back and the API
serialises `…Z`; SQLite - every local and synthetic backend - drops the
tzinfo, the API serialises `2026-09-03T04:38:12` with no zone, and the
ECMAScript spec reads a date-time with no offset as LOCAL time.

**Do this.** On the client, treat a stamp with no zone as UTC before parsing
(`/(?:Z|[+-]\d\d:?\d\d)$/` or append `Z`). On the server the honest fix is
to emit the offset regardless of dialect; until then, every `Date.parse` of
an API timestamp needs the guard.

### 41. A re-fit that fires on any shrink fights the author, and the E2E drag test measures it

**Symptom.** After the first cut of D-15-2 - "re-fit whenever the canvas
frame shrinks after the author's first gesture" - `e2e/builder.spec.ts`'s
router-branch test failed 2 runs in 6, and 0 in 6 without it.

**Cause.** The problems panel is under the canvas frame too, and it grows
about 400ms after a node is placed, as the validate answer lands. The
re-fit then moved every node under the author's next drag, which is the
same jolt a human gets on every edit that changes the problem count. The
strip the critic asked about - the version browser, the delete confirm -
lives in a different row, the dock, which changes only when the author
opens something.

**Do this.** Observe the specific element whose change is the author's own
action (the dock row) rather than the frame it shrinks, and defer any
re-fit while a pointer is down. When a rule is about timing, measure it
with the timing-sensitive test, six runs each way, before and after; a
single green run of a flaky test is not evidence in either direction
(CLAUDE.md remaining-work item 44 has the base rates).

### 42. `git checkout <rev> -- <path>` wipes the uncommitted edits under that path

**Symptom.** After measuring a flake rate against the frontend source at
the base commit - `git checkout a952c74 -- src` then `git checkout HEAD --
src` - the palette-row edit made ten minutes earlier was gone.

**Cause.** A path checkout writes the named revision's files over the
working tree and then `HEAD --` writes HEAD's over that; anything not
committed under the path is overwritten both times, silently, and
`git status` afterwards looks clean because the tree matches HEAD.

**Do this.** Commit or `git stash push -- <path>` before checking an old
revision into a path, and prefer a second worktree (`git worktree add`) for
any measurement against an older tree. The repair here was re-applying the
edit script; a hand edit would have been re-typed from memory.


### 43. .NET's current directory does not follow PowerShell's `Set-Location`

**Symptom.** A script that did `Set-Location <worktree>\frontend` and then
`[IO.File]::ReadAllText("src\components\builder\BuilderView.vue")` reported
`Could not find a part of the path 'D:\MultiAgentSystem\src\components\...'` -
a path in the MAIN tree, from a shell whose prompt was in the worktree. The
same script's `npx` call in the next line ran in the right place, so the
failure read as an intermittent path problem rather than a systematic one.

**Cause.** `Set-Location` moves the PowerShell provider's location.
`[System.IO]` reads `Environment.CurrentDirectory`, which PowerShell does not
keep in step - by design, because a provider location can be a registry key
or a certificate store. A native process launched from the shell inherits the
provider location, which is why `npx` was fine.

**Do this.** Give every `[IO.File]` and `[IO.Directory]` call an ABSOLUTE
path. The dangerous shape is a revert-and-restore probe - read the file,
patch it, run a test, write the original back - because the read throws, the
variable is null, the write throws, and the *test still runs and passes*
against an unmodified file. That is a red-then-green measurement reporting
green for the wrong reason, and it happened here: "1 passed" for a probe that
had reverted nothing.

### 44. An HTML comment inside a tag's attribute list is a Vue compile error

**Symptom.** Adding a three-line `<!-- … -->` between two attributes of
`<VueFlow>` took the whole builder off the air. Playwright reported
`locator.click: Timeout` waiting for a template card; the page snapshot held
`[plugin:vite:vue] Duplicate attribute` and Vite's error overlay.

**Cause.** Vue's template compiler tokenises a tag's attribute list and has no
state for a comment inside it; the `<!--` is parsed as an attribute name and
the second `--` collides. The message names neither comments nor the line the
comment starts on.

**Do this.** Put the comment ABOVE the tag, or move the value into a named
constant in `<script setup>` and comment it there - which is what
`initialFitOptions` in `BuilderCanvas.vue` is for. The wider lesson is that a
timeout waiting for an element that should exist is worth one look at the
page snapshot before it is worth any look at the selector: the snapshot said
exactly what was wrong and the selector was never the problem.

### 45. `vi.useFakeTimers()` around a mount that awaits real work hangs the file

**Symptom.** One new test installed fake timers, mounted a component through a
helper that awaits a stubbed fetch, advanced 30 s and asserted. It failed -
and took ten OTHER tests in the file with it, including three about delete,
with a 55-second duration. The eleven failures read as a regression in the
code under test.

**Cause.** Two compounding. The helper's awaits resolve on timers that fake
timers now control, so the mount never finishes. And the one test that failed
never reached its `wrapper.unmount()`, leaking the `beforeunload` listener
`useBuilderPersistence` registers on the shared `window` - so a later test's
unload assertion read the leaked, dirty document instead of its own.

**Do this.** To assert that *no* timer was armed, `vi.spyOn(window,
'setTimeout')` - a spy records and keeps the original, so nothing else in the
mount changes - and read `spy.mock.calls` for the delay. Reserve fake timers
for a subject with no async mount. And when a change makes a cluster of
unrelated tests fail, suspect a leaked listener from the one test that failed
first before suspecting the change: the file's own `openScopes` comment
already says this about scopes, and `beforeunload` is the same hazard one
level up.

### 46. The builder canvas pans on space-drag or middle-drag, never on a left drag

**Symptom.** An E2E step that panned by pressing the canvas background and
dragging reported "a pan did not reach it" for a node 3 px outside the pane.
The canvas pans perfectly well by hand.

**Cause.** `pan-on-drag` is `[1, 2]` - middle and right button - unless the
space bar is held, at which point it is `true` (`BuilderCanvas.vue`, §1.48,
so that `selection-key-code="true"` can own the left button). A left drag
therefore drew a selection box and moved the viewport not at all.

**Do this.** `keyboard.down('Space')` around the drag, which is also the
gesture a human uses, or `mouse.down({ button: 'middle' })`. And read the
viewport's zoom as `rect.width / offsetWidth` on any node rather than off
`getComputedStyle(...).transform`, which answered `none` here and yields an
identity matrix - a zoom of 1 that is really 0.66 is exactly the confident
wrong number a layout test exists to catch.
