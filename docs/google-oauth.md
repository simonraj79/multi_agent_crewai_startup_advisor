# Google OAuth for Validator Studio

Validator Studio signs people in with Google and nothing else. This file is the
complete recipe for the credentials that makes possible, and the reasoning
behind the values, because most of them are matched **exactly** by Google and a
character out of place fails in a way that names nothing useful.

Nothing here is a secret. Following it produces two values — a client ID and a
client secret — which go in `frontend/.env` locally and in the Render dashboard
in production. **Neither is ever committed.**

---

## What you are creating, and why it needs exact strings

Better Auth mounts its endpoints under `/api/auth`, and derives the Google
callback from the origin the browser sees:

```
{BETTER_AUTH_URL}/api/auth/callback/google
```

Google compares the redirect URI it is handed against its registered list by
**exact string match**. No wildcards, no subpaths, no trailing-slash tolerance,
no http/https interchange. That single fact is behind almost every
`redirect_uri_mismatch` anyone has ever seen.

`BETTER_AUTH_URL` therefore has to be the origin the **browser** is on, not the
port the Node server happens to listen on. Locally those differ: Vite serves the
page on 5173 and proxies `/api/auth` through to the Node server on 3000, so the
browser only ever sees 5173.

---

## The values to register

**Application type:** Web application

**Authorised JavaScript origins**

| Origin | Why |
| --- | --- |
| `http://localhost:5173` | Vite dev server — what you browse during development |
| `http://localhost:3000` | The Node server directly, for running without Vite |
| `https://agentic-crew-ai-studio.onrender.com` | Production. Replace if your service has a different name |

**Authorised redirect URIs**

| Redirect URI |
| --- |
| `http://localhost:5173/api/auth/callback/google` |
| `http://localhost:3000/api/auth/callback/google` |
| `https://agentic-crew-ai-studio.onrender.com/api/auth/callback/google` |

> Register all three now. Adding one later means coming back here, and Google
> can take a few minutes to propagate a change — long enough to convince you the
> problem is somewhere else.

**Scopes:** none beyond the defaults. Better Auth requests `openid`, `email` and
`profile`, which is what fills in the name, address and avatar. Do not add more:
every extra scope is a permission screen the user has to read and a reason for
Google to require verification of the app.

---

## Steps in the Google Cloud console

1. Open <https://console.cloud.google.com/> and pick or create a project.
   A dedicated project is easier to reason about than an existing one — the
   OAuth consent screen is project-wide, so sharing a project means sharing it.

2. **APIs & Services → OAuth consent screen.**
   - User type **External** unless everyone signing in is inside your Google
     Workspace organisation, in which case **Internal** skips the verification
     question entirely.
   - App name, support email and developer contact email are required.
   - Leave the scopes page alone. The three defaults are added automatically.
   - While the app is in **Testing**, only accounts listed under *Test users*
     can sign in, and everyone else gets `access_denied` that reads like a bug.
     **Add your own Google account there** — this is the single most common
     reason a first sign-in fails.

3. **APIs & Services → Credentials → Create credentials → OAuth client ID.**
   - Application type: **Web application**.
   - Name it something you will recognise later, e.g. `validator-studio`.
   - Add the three JavaScript origins and the three redirect URIs from the
     tables above.
   - **Create.**

4. Copy the **Client ID** and **Client secret** from the dialog. The secret is
   shown once; if you lose it, create a new secret rather than a new client.

No API needs enabling. "Sign in with Google" uses OpenID Connect, which is on by
default — the Google+ API that older guides tell you to enable was retired years
ago.

---

## Where the values go

### Local development

`frontend/.env` — already created, already git-ignored (verified with
`git check-ignore -v frontend/.env`, which is the only way to check; reading
`.gitignore` will mislead you — see
[`gotchas-and-insights.md`](gotchas-and-insights.md) entry 5):

```dotenv
BETTER_AUTH_URL=http://localhost:5173
BETTER_AUTH_SECRET=<openssl rand -base64 32>
GOOGLE_CLIENT_ID=<from step 4>
GOOGLE_CLIENT_SECRET=<from step 4>
```

Then, in two terminals:

```powershell
Push-Location frontend
npm run dev:server     # Node: Better Auth on 3000, migrates the schema on boot
Pop-Location

Push-Location frontend
npm run dev            # Vite on 5173, proxying /api/auth to 3000
Pop-Location
```

Browse `http://localhost:5173`. The API is separate and unchanged:
`.\.venv\Scripts\serve.exe` for the paid backend, or `$env:SYNTHETIC = "1"`
first for the free one.

### Production (Render)

Set these on the **`agentic-crew-ai-studio`** service. They are all `sync: false`
in `render.yaml`, so Render prompts for them and never reads them from the repo:

| Variable | Value |
| --- | --- |
| `BETTER_AUTH_URL` | The service's own URL, e.g. `https://agentic-crew-ai-studio.onrender.com` |
| `BETTER_AUTH_SECRET` | `openssl rand -base64 32`. Rotating it invalidates every session **and** every issued JWT |
| `GOOGLE_CLIENT_ID` | From step 4 |
| `GOOGLE_CLIENT_SECRET` | From step 4 |
| `VITE_API_URL` | The API's origin, e.g. `https://agentic-crew-ai-api.onrender.com` |

`AUTH_BASE_URL` on the **API** service must equal `BETTER_AUTH_URL` here. It is
committed as a literal in `render.yaml` because it is knowable in advance; if
you rename the web service, change it in the same commit.

> **`VITE_API_URL` is a build-time variable.** Changing it does nothing until
> the web service is redeployed, and it must be a full origin **including
> `https://`** — a bare hostname resolves as a relative path, breaks `/ws`, and
> drops the console into its silent scripted mock. That is entry 2 in
> [`gotchas-and-insights.md`](gotchas-and-insights.md), and it costs an hour
> every time.

---

## Verifying it works

```bash
# The auth server is up and knows its own origin
curl -s https://agentic-crew-ai-studio.onrender.com/healthz

# The public keys the API verifies tokens against. Must return one Ed25519 key.
curl -s https://agentic-crew-ai-studio.onrender.com/api/auth/jwks

# The API refuses an anonymous run. 401 here is the whole point.
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://agentic-crew-ai-api.onrender.com/api/sessions/probe/runs \
  -H 'Content-Type: application/json' \
  -d '{"workflow_id":"idea-validator","inputs":{"idea":"probe"}}'
```

The last one costs nothing: it is refused before a model is ever reached.

---

## When it goes wrong

| Symptom | Cause |
| --- | --- |
| `redirect_uri_mismatch` | The registered URI differs from `{BETTER_AUTH_URL}/api/auth/callback/google` — usually a trailing slash, `http` vs `https`, or a `BETTER_AUTH_URL` naming the server's port instead of the browser's |
| `access_denied` on your own account | The consent screen is in **Testing** and the account is not in *Test users* |
| Sign-in works, then the studio shows 401s | `AUTH_BASE_URL` on the API does not exactly equal `BETTER_AUTH_URL` on the web service. Those two strings are the JWT's `iss` and `aud`; a mismatch is an invalid token |
| Sign-in works locally, fails on Render | `NODE_ENV` is not `production`, so cookies are issued without `Secure` and a cross-site OAuth redirect drops them |
| Everything 401s right after a deploy | `BETTER_AUTH_SECRET` changed. It encrypts the stored JWKS private key; a new secret means the old key cannot be decrypted |
| The console renders a whole run that never happened | The silent mock. `VITE_API_URL` is wrong or unset — see the trap above |

---

## What is stored about a person

Google returns, and the `user` table keeps: an opaque user id, name, email
address, whether Google considers that address verified, and an avatar URL. The
`account` table additionally holds Google's OAuth tokens, which is what would
let the app call Google APIs on the user's behalf — it never does, and no scope
permitting it is requested.

Runs are attributed to the user id, so each person sees only their own. The
`SignInPanel` says all of this on screen before the button is pressed, which is
both the decent thing to do and the reason someone will trust a Google prompt
raised by an `.onrender.com` host.
