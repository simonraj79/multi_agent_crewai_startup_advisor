// The Node service that replaces the Render static site.
//
// It does exactly two things, and the restraint is deliberate. It serves the
// built SPA, and it mounts Better Auth at /api/auth/*. It does NOT proxy
// /api or /ws through to the FastAPI service, even though that would make
// production mirror the Vite dev proxy and would let the session cookie reach
// the API directly.
//
// The reason is the run stream. A Render web service on the free plan spins
// down when idle; the API is on `starter` and does not. Proxying the WebSocket
// through here would put the one channel that carries every frame of a live
// validator run behind the instance most likely to be asleep, and a run that
// goes quiet at a gate is exactly when that happens. The SPA therefore talks to
// the API directly, as it already does, and carries a short-lived JWT.
import "dotenv/config";
import { serve } from "@hono/node-server";
import { serveStatic } from "@hono/node-server/serve-static";
import { Hono } from "hono";
import { auth, baseURL } from "./auth.ts";
import { applyMigrations } from "./migrate.ts";

const app = new Hono();

// Liveness for Render's health check. Deliberately above the auth mount and the
// static handler so it answers even if `dist/` was never built.
app.get("/healthz", (c) => c.json({ status: "ok", baseURL }));

// Better Auth owns this prefix entirely: sign-in, the Google callback, session
// reads, sign-out, /token and /jwks. `auth.handler` takes a web-standard
// Request, which is why Hono is a better fit here than Express - `c.req.raw` is
// already the right type and there is no adapter in between.
app.on(["GET", "POST"], "/api/auth/*", (c) => auth.handler(c.req.raw));

// Everything else is the SPA. `index: false` stops serveStatic inventing a
// directory listing; unmatched paths fall through to the rewrite below.
app.use("/*", serveStatic({ root: "./dist" }));

// SPA fallback, mirroring the `rewrite /* -> /index.html` route the static site
// used to declare in render.yaml. Scoped to GET so a POST to a nonexistent API
// path 404s honestly instead of being handed an HTML page.
app.get("*", serveStatic({ path: "./dist/index.html" }));

const port = Number(process.env.PORT ?? 3000);
const hostname = process.env.HOST ?? "0.0.0.0";

// Schema first, then listen. Running it here rather than in Render's build step
// is deliberate: a build container is not guaranteed to reach a database whose
// `ipAllowList` is empty, and a migration that silently did not run would
// surface as "no such table: session" on the first sign-in attempt instead of
// as a failed deploy.
await applyMigrations();

serve({ fetch: app.fetch, port, hostname }, (info) => {
  console.log(`[auth-web] listening on ${hostname}:${info.port}`);
  console.log(`[auth-web] baseURL ${baseURL}`);
  console.log(
    `[auth-web] google callback ${baseURL}/api/auth/callback/google`,
  );
});
