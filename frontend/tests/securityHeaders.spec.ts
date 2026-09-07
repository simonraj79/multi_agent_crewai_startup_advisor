import { readFileSync } from 'node:fs'
import path from 'node:path'
import { Hono } from 'hono'
import { describe, expect, it } from 'vitest'
import { apiConnectSources, securityHeaders } from '../server/headers.ts'

/**
 * Audit M6: the origin that holds the session cookie shipped no security
 * headers at all - no CSP, no frame-ancestors, no nosniff, no HSTS.
 *
 * Two halves are pinned here and they fail independently. The middleware
 * itself is asserted through `app.request()`, which needs no socket; and the
 * WIRING is asserted against `server/index.ts` as text, because the header set
 * being correct is worth nothing if nobody registers it, and `index.ts` runs
 * `applyMigrations()` and `serve()` at module scope so a test cannot import it
 * to find out.
 */

// Spelled the way `brand.spec.ts` already spells it: under jsdom
// `import.meta.url` is an http URL, so `fileURLToPath` refuses it and the
// Windows drive letter has to be recovered from the pathname by hand.
const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const INDEX_SOURCE = readFileSync(path.resolve(HERE, '../server/index.ts'), 'utf-8')

async function headersFor(apiUrl?: string | null): Promise<Headers> {
  const app = new Hono()
  app.use(securityHeaders(apiUrl))
  app.get('/healthz', (c) => c.json({ status: 'ok' }))
  const res = await app.request('/healthz')
  return res.headers
}

function directives(csp: string): Map<string, string> {
  const map = new Map<string, string>()
  for (const part of csp.split(';')) {
    const trimmed = part.trim()
    if (!trimmed) continue
    const space = trimmed.indexOf(' ')
    if (space === -1) map.set(trimmed, '')
    else map.set(trimmed.slice(0, space), trimmed.slice(space + 1))
  }
  return map
}

describe('M6: the Node origin ships security headers', () => {
  it('sets a Content-Security-Policy on an ordinary response', async () => {
    const headers = await headersFor('https://api.example.test')
    expect(headers.get('content-security-policy')).toBeTruthy()
  })

  it('names every directive the audit asked for', async () => {
    const csp = directives((await headersFor('https://api.example.test'))!.get('content-security-policy') ?? '')
    expect(csp.get('default-src')).toBe("'self'")
    expect(csp.get('object-src')).toBe("'none'")
    expect(csp.get('base-uri')).toBe("'none'")
    expect(csp.get('form-action')).toBe("'self'")
    expect(csp.get('frame-ancestors')).toBe("'none'")
    expect(csp.has('upgrade-insecure-requests')).toBe(true)
  })

  it('refuses inline and eval script, which is what the bundle needs and no more', async () => {
    const csp = directives((await headersFor(null)).get('content-security-policy') ?? '')
    expect(csp.get('script-src')).toBe("'self'")
    expect(csp.get('script-src')).not.toContain('unsafe-inline')
    expect(csp.get('script-src')).not.toContain('unsafe-eval')
  })

  it('admits the Google Fonts stylesheet and its faces, because studio.css @imports it', async () => {
    const csp = directives((await headersFor(null)).get('content-security-policy') ?? '')
    expect(csp.get('style-src')).toContain('https://fonts.googleapis.com')
    expect(csp.get('font-src')).toContain('https://fonts.gstatic.com')
  })

  it('admits the Google avatar host the account chip renders, and no other image origin', async () => {
    const csp = directives((await headersFor(null)).get('content-security-policy') ?? '')
    expect(csp.get('img-src')).toBe("'self' data: https://lh3.googleusercontent.com")
  })

  it("allows a style ATTRIBUTE but still refuses an injected <style> element", async () => {
    const csp = directives((await headersFor(null)).get('content-security-policy') ?? '')
    expect(csp.get('style-src-attr')).toBe("'unsafe-inline'")
    expect(csp.get('style-src')).not.toContain('unsafe-inline')
  })

  it('carries the API origin AND its WebSocket form in connect-src', async () => {
    const csp = directives((await headersFor('https://api.example.test')).get('content-security-policy') ?? '')
    const connect = csp.get('connect-src') ?? ''
    expect(connect).toContain("'self'")
    expect(connect).toContain('https://api.example.test')
    // studioApi.ts builds the run stream by swapping the scheme, so a policy
    // with only the http form would refuse every frame of every run.
    expect(connect).toContain('wss://api.example.test')
  })

  it('sets the non-CSP headers the audit named', async () => {
    const headers = await headersFor(null)
    expect(headers.get('x-frame-options')).toBe('DENY')
    expect(headers.get('x-content-type-options')).toBe('nosniff')
    expect(headers.get('referrer-policy')).toBe('strict-origin-when-cross-origin')
    expect(headers.get('strict-transport-security')).toBe('max-age=31536000; includeSubDomains')
    expect(headers.get('cross-origin-opener-policy')).toBe('same-origin-allow-popups')
    // require-corp would refuse the Google Fonts stylesheet.
    expect(headers.get('cross-origin-embedder-policy')).toBeNull()
  })
})

describe('M6: apiConnectSources', () => {
  it('derives both schemes from an https origin', () => {
    expect(apiConnectSources('https://api.example.test')).toEqual([
      'https://api.example.test',
      'wss://api.example.test',
    ])
  })

  it('derives both schemes from a plain http origin', () => {
    expect(apiConnectSources('http://127.0.0.1:8099')).toEqual([
      'http://127.0.0.1:8099',
      'ws://127.0.0.1:8099',
    ])
  })

  it('strips a trailing slash, matching what httpCore.ts does to the same value', () => {
    expect(apiConnectSources('https://api.example.test/')).toEqual([
      'https://api.example.test',
      'wss://api.example.test',
    ])
  })

  it("adds nothing when VITE_API_URL is unset, because 'self' already covers that build", () => {
    expect(apiConnectSources(undefined)).toEqual([])
    expect(apiConnectSources(null)).toEqual([])
    expect(apiConnectSources('   ')).toEqual([])
  })
})

describe('M6: server/index.ts registers the middleware, and registers it first', () => {
  it('imports and applies securityHeaders with the build-time API origin', () => {
    expect(INDEX_SOURCE).toContain('securityHeaders')
    expect(INDEX_SOURCE).toMatch(/app\.use\(\s*securityHeaders\(process\.env\.VITE_API_URL\)\s*\)/)
  })

  it('applies it above the health check, the auth mount and the static handler', () => {
    const use = INDEX_SOURCE.indexOf('app.use(securityHeaders(')
    const healthz = INDEX_SOURCE.indexOf('"/healthz"')
    const authMount = INDEX_SOURCE.indexOf('"/api/auth/*"')
    const staticMount = INDEX_SOURCE.indexOf('serveStatic({ root:')
    expect(use).toBeGreaterThan(-1)
    // A header middleware registered after a handler that already answered is
    // a header nobody sends; ordering is the whole contract of `app.use` here.
    expect(use).toBeLessThan(healthz)
    expect(use).toBeLessThan(authMount)
    expect(use).toBeLessThan(staticMount)
  })
})
