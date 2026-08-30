import { fileURLToPath } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

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

export default defineConfig({
  root: fileURLToPath(new URL('..', import.meta.url)),
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.E2E_UI_PORT ?? 5273),
    // Fail loudly rather than silently landing on another port - a suite that
    // quietly moved to 5274 while Playwright watched 5273 would just time out.
    strictPort: true,
    proxy: {
      '/api': target,
      '/ws': { target: wsTarget, ws: true },
    },
  },
})
