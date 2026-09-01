// Better Auth server configuration for Validator Studio.
//
// WHY THIS FILE EXISTS AT ALL, AND WHY IT IS IN `frontend/`:
// Better Auth is a TypeScript library that needs a Node runtime. This repo had
// nowhere to put one - `frontend/` shipped as a Render *static* site (a CDN,
// no process) and the API is Python. So `frontend/` stops being a static site
// and becomes a small Node service that serves the built SPA *and* mounts auth
// at /api/auth/*.
//
// Serving both from ONE origin is the load-bearing decision, and it is forced
// by a fact that is not discoverable from the code: `onrender.com` is on the
// Public Suffix List, so a browser REFUSES to set a cookie scoped to
// `.onrender.com`. Better Auth's usual `crossSubDomainCookies` answer is
// therefore unavailable on Render's default domains - a separate
// `agentic-crew-ai-auth.onrender.com` could never share a session cookie with
// the SPA. Same-origin sidesteps the whole problem: an ordinary httpOnly
// Secure cookie just works, and no session token is ever exposed to JavaScript.
//
// The FastAPI service is still a separate origin and cannot read that cookie.
// That is what the `jwt` plugin below is for; see the comment on it.
import { betterAuth } from "better-auth";
import { jwt } from "better-auth/plugins";
import { Pool } from "pg";
import Database from "better-sqlite3";
import type { BetterAuthOptions } from "better-auth";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const isProduction = process.env.NODE_ENV === "production";

/**
 * The origin the BROWSER sees. Every OAuth redirect URI, cookie domain and JWT
 * `iss`/`aud` claim is derived from this, so it must match what is registered
 * in the Google Cloud console character for character.
 */
export const baseURL =
  process.env.BETTER_AUTH_URL ?? "http://localhost:5173";

/**
 * Local dev runs Vite on 5173 proxying /api/auth to this server on 3000, so a
 * request can legitimately arrive bearing either origin. Production is a single
 * origin and needs only itself.
 */
const trustedOrigins = [
  baseURL,
  ...(isProduction ? [] : ["http://localhost:5173", "http://localhost:3000"]),
  ...(process.env.BETTER_AUTH_TRUSTED_ORIGINS ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean),
];

/**
 * Postgres in production, SQLite locally.
 *
 * This is not laziness, it is forced: the Render database declares
 * `ipAllowList: []` (render.yaml), which on Render means NO external
 * connections at all - only traffic from inside the same region reaches it. A
 * developer on a laptop therefore cannot point at production even if they want
 * to. It also matches what `src/brief_crew/service/persistence.py` already does
 * (SQLite at output/validator-studio.db locally, DATABASE_URL in production),
 * so the two halves of the system fail over the same way.
 */
// The return type is annotated, and annotated as Better Auth's OWN option
// type rather than as `Pool | Database`. Left inferred, tsc refuses to emit
// declarations for the exported `auth` with TS4023: better-sqlite3's
// `Database` is declared inside a namespace behind an `export =`, so it
// reaches the public surface of `auth` as a type this file cannot name.
// Widening here keeps the concrete driver an implementation detail.
function resolveDatabase(): BetterAuthOptions["database"] {
  const url = process.env.DATABASE_URL;
  if (url) return new Pool({ connectionString: url });

  const file = resolve(
    process.cwd(),
    process.env.AUTH_SQLITE_PATH ?? "../output/auth.db",
  );
  mkdirSync(dirname(file), { recursive: true });
  return new Database(file);
}

export const auth = betterAuth({
  appName: "Validator Studio",
  baseURL,
  basePath: "/api/auth",
  secret: process.env.BETTER_AUTH_SECRET,
  database: resolveDatabase(),
  trustedOrigins,

  socialProviders: {
    google: {
      clientId: process.env.GOOGLE_CLIENT_ID as string,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET as string,
      // Google matches this EXACTLY - no wildcards, no trailing-slash
      // tolerance. Leaving it implicit works, but stating it means a wrong
      // BETTER_AUTH_URL fails loudly here rather than as an opaque
      // `redirect_uri_mismatch` on Google's own error page.
      redirectURI: `${baseURL}/api/auth/callback/google`,
      // Google reports a trustworthy `email_verified`, so honour it. Without
      // this a provider that hands back an unverified address would still mint
      // a session.
      requireEmailVerification: true,
    },
  },

  // Google is the only provider, so email/password is deliberately OFF rather
  // than merely unused: an enabled-but-unmentioned credential path is exactly
  // the kind of thing that survives a review because nothing links to it.
  emailAndPassword: { enabled: false },

  session: {
    expiresIn: 60 * 60 * 24 * 7, // 7 days
    updateAge: 60 * 60 * 24, // refresh the expiry at most once a day
  },

  advanced: {
    // Render terminates TLS, so production is always https. Forcing this off
    // localhost stops a Secure-less cookie ever being issued in production.
    useSecureCookies: isProduction,
    // `strict` would drop the cookie on the way back from Google's redirect,
    // which is a top-level cross-site navigation. `lax` is the correct and
    // standard choice for an OAuth callback.
    defaultCookieAttributes: { sameSite: "lax", httpOnly: true },
  },

  plugins: [
    // WHY A JWT AT ALL, when the session already lives in the shared database.
    //
    // The SPA and the FastAPI API are different origins, so the session cookie
    // above cannot reach the API. Something has to travel in an Authorization
    // header, and whatever that is becomes readable by JavaScript - which is
    // precisely why it must NOT be the session token. `authClient.token()` is
    // called same-origin (authenticated by the httpOnly cookie) and returns a
    // SHORT-LIVED JWT. The durable credential stays in the cookie; the thing
    // exposed to script expires in 15 minutes and is held in memory only.
    //
    // FastAPI verifies it offline against /api/auth/jwks - no shared secret, no
    // database round trip on the hot path, and no call back into this service.
    jwt({
      jwks: {
        // Declared rather than left to the default. PyJWT verifies this on the
        // Python side (see src/brief_crew/service/auth.py) and a silent change
        // to Better Auth's default algorithm would break that verifier at
        // runtime, in production, with a signature error that names nothing.
        keyPairConfig: { alg: "EdDSA", crv: "Ed25519" },
      },
      jwt: {
        issuer: baseURL,
        audience: baseURL,
        expirationTime: "15m",
      },
    }),
  ],
});

export type Session = typeof auth.$Infer.Session;
