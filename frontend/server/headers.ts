// The security header set for the Node origin, in its own file so it can be
// asserted without booting the server.
//
// `index.ts` runs `applyMigrations()` and `serve()` at module scope, so
// importing it from a test opens a database and a listening socket. The
// middleware is the part worth pinning, so it lives here and index.ts is one
// import plus one `app.use`.
//
// WHY THIS EXISTS AT ALL (audit M6). This is the origin that holds the session
// cookie, and until this file it shipped no CSP, no frame-ancestors, no nosniff
// and no HSTS - so the app's whole XSS posture rested on one hand-rolled
// Markdown renderer with nothing behind it. No injection was found there, so
// this is the second layer rather than a hole being closed: any future script
// injection on this origin can call /api/auth/token with the cookie, receive a
// 15-minute API bearer token, and post it anywhere, and without `connect-src`
// nothing would stop the last step.
import type { MiddlewareHandler } from "hono";
import { secureHeaders } from "hono/secure-headers";

/**
 * The `connect-src` entries the SPA needs for the FastAPI service, derived from
 * the SAME variable the build inlined into the bundle (`VITE_API_URL`, set on
 * this service by render.yaml). Derived rather than written as a literal so the
 * policy cannot drift from what the client actually fetches.
 *
 * Two entries, not one: `studioApi.ts` builds the run stream by taking that
 * base URL and swapping `https:` for `wss:` (`http:` for `ws:`), and a CSP that
 * allowed only the http form would refuse every WebSocket. An unset variable
 * yields none - the bundle then resolves every path against the page's own
 * origin, which `'self'` already covers.
 */
export function apiConnectSources(apiUrl: string | undefined | null): string[] {
  const origin = (apiUrl ?? "").trim().replace(/\/+$/, "");
  if (!origin) return [];
  return [origin, origin.replace(/^http/, "ws")];
}

/**
 * Every directive below was checked against a real `vite build` of this repo
 * rather than assumed:
 *
 * - `script-src 'self'`: dist/index.html carries one `<script type="module"
 *   src=...>` and no inline script, and the bundle contains no `eval`, no
 *   `new Function` and no `new Worker`. So no 'unsafe-inline', no 'unsafe-eval'
 *   and no nonce plumbing is needed.
 * - `style-src` names fonts.googleapis.com because `src/studio.css` opens with
 *   `@import url('https://fonts.googleapis.com/css2?...')`, which survives the
 *   build as an `@import` in the emitted stylesheet; `font-src` names
 *   fonts.gstatic.com because that is where that sheet's faces live.
 * - `style-src-attr 'unsafe-inline'` and NOT 'unsafe-inline' on `style-src`:
 *   Vue writes `:style` bindings through the CSSOM, which CSP does not govern,
 *   but a `style` attribute that reached the parser would be refused by
 *   `style-src` alone and the failure would be silent and cosmetic. Splitting
 *   the attribute case out keeps an injected `<style>` ELEMENT refused, which
 *   is the case that matters.
 * - `img-src` names lh3.googleusercontent.com: `AccountChip.vue` renders
 *   `user.image`, which for a Google account is served from there. `data:` is
 *   kept for inline SVG/icon data URLs.
 * - `object-src 'none'`, `base-uri 'none'` and `frame-ancestors 'none'` are the
 *   three that cost nothing here and close whole classes: no plugins, no `<base>`
 *   rewrite of every relative URL in the SPA, no framing.
 *
 * `upgrade-insecure-requests` is set, and it was checked rather than assumed:
 * the only place anybody exercises this file is a plain-http loopback origin,
 * and a directive that rewrote this origin's own asset requests to https there
 * would make the policy unverifiable where it is edited. Measured with the
 * built server on http://127.0.0.1:3100 driving the real bundle - home, run
 * console and builder gallery, 21 font faces loaded, the API fetch and the
 * WebSocket both up, zero `securitypolicyviolation` events - so the loopback
 * carve-out holds and production keeps the directive.
 *
 * @param apiUrl the API origin the bundle was built against (`VITE_API_URL`).
 */
export function securityHeaders(apiUrl?: string | null): MiddlewareHandler {
  return secureHeaders({
    contentSecurityPolicy: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", "https://fonts.googleapis.com"],
      styleSrcAttr: ["'unsafe-inline'"],
      fontSrc: ["'self'", "https://fonts.gstatic.com"],
      imgSrc: ["'self'", "data:", "https://lh3.googleusercontent.com"],
      connectSrc: ["'self'", ...apiConnectSources(apiUrl)],
      objectSrc: ["'none'"],
      baseUri: ["'none'"],
      formAction: ["'self'"],
      frameAncestors: ["'none'"],
      upgradeInsecureRequests: [],
    },
    xFrameOptions: "DENY",
    xContentTypeOptions: "nosniff",
    referrerPolicy: "strict-origin-when-cross-origin",
    strictTransportSecurity: "max-age=31536000; includeSubDomains",
    // Google sign-in is a full-page redirect here, not a popup, but Better Auth
    // supports both and `same-origin` would break the popup form silently.
    crossOriginOpenerPolicy: "same-origin-allow-popups",
    // `require-corp` would refuse the Google Fonts stylesheet, which carries no
    // CORP header of its own.
    crossOriginEmbedderPolicy: false,
  });
}
