import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig, type Plugin, type ProxyOptions } from 'vite'
import { DEFAULT_SYNTHETIC_USER, syntheticUserOf } from './syntheticUser'

/**
 * A second dev server for the end-to-end suite, kept separate from
 * `vite.config.ts` on purpose.
 *
 * `vite.config.ts` proxies `/api` and `/ws` to `127.0.0.1:8000`, which in this
 * project is the *paid* backend: real OpenRouter, Firecrawl, GitHub and
 * Pinecone credentials, and a real bill on every Launch. An automated suite
 * must never be able to press that button, so the e2e server points at a
 * separate origin - by default the no-cost `SYNTHETIC=1` service on 8099.
 *
 * Proxying rather than setting `VITE_API_URL` is deliberate: the app then sees
 * a same-origin API exactly as it does in production behind a reverse proxy,
 * so nothing in the suite depends on CORS being configured for a test origin.
 *
 *   E2E_API_TARGET  http origin of the backend to proxy to (default :8099)
 *   E2E_UI_PORT     port this dev server binds (default 5273)
 */
const target = process.env.E2E_API_TARGET ?? 'http://127.0.0.1:8099'
const wsTarget = target.replace(/^http/, 'ws')

/**
 * Stands in for the Better Auth origin, which in production is the same Node
 * server that serves the SPA (`frontend/server/`) and here does not exist -
 * this harness is Vite plus a synthetic Python backend.
 *
 * It returns a SIGNED-IN session rather than a signed-out one, and rather than
 * a build flag that switches authentication off. The reasoning is the one this
 * repo keeps rediscovering: a double that diverges from its subject certifies
 * nothing. A flag would make the suite exercise the `unconfigured` phase, which
 * production never reaches, and would leave the header chip, the history panel
 * and the whole bearer-token path untested. Stubbing the origin means the suite
 * drives the console exactly as a real signed-in operator does.
 *
 * It must be registered with `server.middlewares.use` DIRECTLY rather than by
 * returning a function from `configureServer`: the direct form installs ahead
 * of Vite's internal middlewares, and the `/api` proxy below is one of those.
 * Returned late, every one of these paths would be forwarded to the Python
 * service instead, which answers 404 - the exact console error this replaces.
 */
function stubAuthOrigin(): Plugin {
  const now = new Date().toISOString()
  const user = {
    id: DEFAULT_SYNTHETIC_USER,
    name: 'E2E Operator',
    email: 'e2e@example.test',
    emailVerified: true,
    // Deliberately null: a real avatar URL would make the suite fetch an image
    // from a third party, and a blocked or slow request there would surface as
    // a flaky console error in a test about something else entirely.
    image: null,
    createdAt: now,
    updatedAt: now,
  }
  const routes: Record<string, unknown> = {
    '/api/auth/get-session': {
      session: {
        id: 'e2e-session',
        userId: user.id,
        token: 'e2e-session-token',
        expiresAt: new Date(Date.now() + 86_400_000).toISOString(),
        createdAt: now,
        updatedAt: now,
      },
      user,
    },
    // The bearer token the SPA sends to the Python service. That service runs
    // with no AUTH_BASE_URL here, so it has no keys to verify against and
    // ignores the header rather than refusing it - see `current_user` in
    // service/app.py, which had to be made consistent with the WebSocket path
    // before this stub could work at all.
    '/api/auth/token': { token: 'e2e-access-token' },
    '/api/auth/sign-out': { success: true },
  }

  /**
   * The same session shape for a test-chosen identity (`syntheticUser.ts`).
   *
   * `email` is spelled `<id>@synthetic` because that is what the Python side
   * answers for the forwarded header (plan 01 D8), so the chip in the header
   * and the owner column in the database name the same person. `name` is the
   * id itself, which is what `isolation.spec.ts` reads off the chip to prove a
   * context is who it thinks it is before asserting anything about isolation.
   */
  function sessionFor(id: string): unknown {
    return {
      session: {
        id: `e2e-session-${id}`,
        userId: id,
        token: `e2e-session-token-${id}`,
        expiresAt: new Date(Date.now() + 86_400_000).toISOString(),
        createdAt: now,
        updatedAt: now,
      },
      user: { ...user, id, name: id, email: `${id}@synthetic` },
    }
  }

  return {
    name: 'e2e-stub-auth-origin',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '').split('?')[0]
        if (!path.startsWith('/api/auth/')) return next()
        // A context that set the synthetic-user cookie is that user here as
        // well as at the API, so the header chip, the history panel and the
        // owner of every row agree. No cookie: the E2E Operator, as always.
        const synthetic = path === '/api/auth/get-session' ? syntheticUserOf(req.headers.cookie) : null
        const body = synthetic ? sessionFor(synthetic) : routes[path]
        res.setHeader('content-type', 'application/json')
        // An unmapped /api/auth/* path answers `null` with a 200 rather than
        // falling through to the proxy. Falling through would 404 against the
        // Python service and fail the suite's zero-console-errors rule for a
        // reason that has nothing to do with the test.
        res.statusCode = 200
        res.end(JSON.stringify(body ?? null))
      })
    },
  }
}

/**
 * Turn the synthetic-user cookie into the header the free backend honours.
 *
 * On BOTH proxies: the HTTP one for every API call and `proxyReqWs` for the
 * WebSocket upgrade, because a run's frames are read over the socket by a
 * route that checks who is asking - a page that was Alice on `/api` and nobody
 * on `/ws` would fail rubric 14's journey at the one step that costs nothing
 * to get right. The cookie itself still reaches the backend in the `Cookie`
 * header; the Python side never reads it, and `X-Synthetic-User` is ignored by
 * any deployment that is not `SYNTHETIC=1` with no `AUTH_BASE_URL`, so nothing
 * here can make a paid or an authenticated service believe a cookie.
 */
const forwardSyntheticUser: NonNullable<ProxyOptions['configure']> = (proxy) => {
  // No cookie is the E2E Operator, not nobody: the stub already signed that
  // context in, and an API that sees a stranger behind a signed-in page is a
  // state production never reaches (see DEFAULT_SYNTHETIC_USER).
  proxy.on('proxyReq', (proxyReq, req) => {
    proxyReq.setHeader('X-Synthetic-User', syntheticUserOf(req.headers.cookie) ?? DEFAULT_SYNTHETIC_USER)
  })
  proxy.on('proxyReqWs', (proxyReq, req) => {
    proxyReq.setHeader('X-Synthetic-User', syntheticUserOf(req.headers.cookie) ?? DEFAULT_SYNTHETIC_USER)
  })
}

export default defineConfig({
  root: fileURLToPath(new URL('..', import.meta.url)),
  plugins: [vue(), stubAuthOrigin()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.E2E_UI_PORT ?? 5273),
    // Fail loudly rather than silently landing on another port - a suite that
    // quietly moved to 5274 while Playwright watched 5273 would just time out.
    strictPort: true,
    proxy: {
      '/api': { target, configure: forwardSyntheticUser },
      '/ws': { target: wsTarget, ws: true, configure: forwardSyntheticUser },
    },
  },
})
