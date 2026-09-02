import { describe, expect, it } from 'vitest'
import { documentId } from '../src/types/builder'
import {
  routeHash,
  useWorkspaceRoute,
  workspaceRoute,
} from '../src/composables/useWorkspaceRoute'
import type { WorkspaceRoute } from '../src/composables/useWorkspaceRoute'
import { withSetup } from './helpers'

/**
 * The two workspaces are addressable, and the address survives the round trip.
 *
 * Sixty lines instead of `vue-router` (R13), and the risk that buys is that a
 * hand-rolled parser and a hand-rolled serialiser disagree - at which point
 * `#/build/ug_0a1b2c3d` is a link an author can send and cannot receive. So the
 * round trip is asserted in both directions for all three routes rather than
 * the parse alone.
 *
 * `ug_0a1b2c3d` is the real shape: `DOCUMENT_ID_PATTERN` is
 * `config.py:BUILDER_DOCUMENT_ID_PATTERN`, server-assigned and never
 * client-chosen, so a test that used `doc-1` would be testing a document id
 * that cannot exist.
 */

const ID = documentId('ug_0a1b2c3d')

function atHash<T>(hash: string, run: () => T): T {
  window.location.hash = hash
  return run()
}

describe('the hash names the workspace', () => {
  it('reads the studio from the root, from a bare hash and from nothing at all', () => {
    expect(workspaceRoute('#/')).toEqual({ name: 'studio' })
    expect(workspaceRoute('#')).toEqual({ name: 'studio' })
    expect(workspaceRoute('')).toEqual({ name: 'studio' })
  })

  it('reads the empty builder from #/build', () => {
    expect(workspaceRoute('#/build')).toEqual({ name: 'builder', documentId: null })
    expect(workspaceRoute('#/build/')).toEqual({ name: 'builder', documentId: null })
  })

  it('reads a document id from #/build/:documentId', () => {
    expect(workspaceRoute('#/build/ug_0a1b2c3d')).toEqual({ name: 'builder', documentId: ID })
  })

  it('falls to the studio for anything it does not recognise', () => {
    // An unknown hash is not an error state to render; it is a URL that means
    // nothing, and the console is what the app has instead of a 404 page.
    expect(workspaceRoute('#/nonsense')).toEqual({ name: 'studio' })
    expect(workspaceRoute('#/builder/ug_0a1b2c3d')).toEqual({ name: 'studio' })
  })

  it('lands a malformed document id on the EMPTY builder, not on a builder claiming to hold it', () => {
    // The id fails the server's own pattern, so no `GET /api/builder/workflows/{id}`
    // could ever return it. Carrying it forward would turn one wrong URL into
    // one wrong request and a 422 about a field the author never typed.
    expect(workspaceRoute('#/build/UG_0A1B2C3D')).toEqual({ name: 'builder', documentId: null })
    expect(workspaceRoute('#/build/ug_zzzz')).toEqual({ name: 'builder', documentId: null })
    expect(workspaceRoute('#/build/ug_0a1b2c3d/extra')).toEqual({ name: 'builder', documentId: ID })
  })
})

describe('every route round-trips through the address bar', () => {
  const routes: WorkspaceRoute[] = [
    { name: 'studio' },
    { name: 'builder', documentId: null },
    { name: 'builder', documentId: ID },
  ]

  it('writes a hash each route parses back to itself', () => {
    for (const route of routes) {
      expect(workspaceRoute(routeHash(route))).toEqual(route)
    }
  })

  it('writes the three hashes an author would recognise', () => {
    expect(routes.map(routeHash)).toEqual(['#/', '#/build', `#/build/${ID}`])
  })
})

describe('useWorkspaceRoute follows the window and leads it', () => {
  it('starts from the hash the page was loaded with', () => {
    const [{ route }, app] = atHash(`#/build/${ID}`, () => withSetup(() => useWorkspaceRoute()))
    expect(route.value).toEqual({ name: 'builder', documentId: ID })
    app.unmount()
  })

  it('assigns the route before the hashchange event, so the view never lags a tick', () => {
    // `hashchange` is dispatched as a task, not synchronously. Waiting for it
    // would show a frame of the outgoing workspace on every navigation.
    const [{ route, navigate }, app] = atHash('#/', () => withSetup(() => useWorkspaceRoute()))
    navigate({ name: 'builder', documentId: ID })
    expect(route.value).toEqual({ name: 'builder', documentId: ID })
    expect(window.location.hash).toBe(`#/build/${ID}`)
    app.unmount()
  })

  it('follows a hash changed from outside, such as the back button', () => {
    const [{ route }, app] = atHash('#/', () => withSetup(() => useWorkspaceRoute()))
    window.location.hash = '#/build'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(route.value).toEqual({ name: 'builder', documentId: null })
    app.unmount()
  })

  it('is idempotent, so a click and a pasted URL reach the same state by the same path', () => {
    const [{ route, navigate }, app] = atHash('#/', () => withSetup(() => useWorkspaceRoute()))
    navigate({ name: 'builder', documentId: ID })
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(route.value).toEqual({ name: 'builder', documentId: ID })
    app.unmount()
  })

  it('stops listening when the component that installed it goes away', () => {
    const [{ route }, app] = atHash('#/', () => withSetup(() => useWorkspaceRoute()))
    app.unmount()
    window.location.hash = '#/build'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    expect(route.value).toEqual({ name: 'studio' })
  })
})
