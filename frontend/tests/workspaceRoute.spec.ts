import { describe, expect, it } from 'vitest'
import { documentId } from '../src/types/builder'
import {
  homeResumesConsole,
  routeHash,
  useWorkspaceRoute,
  workspaceRoute,
} from '../src/composables/useWorkspaceRoute'
import type { RunPointerState, WorkspaceRoute } from '../src/composables/useWorkspaceRoute'
import { withSetup } from './helpers'

/**
 * The three workspaces are addressable, and the address survives the round trip.
 *
 * Sixty lines instead of `vue-router` (R13), and the risk that buys is that a
 * hand-rolled parser and a hand-rolled serialiser disagree - at which point
 * `#/build/ug_0a1b2c3d` is a link an author can send and cannot receive. So the
 * round trip is asserted in both directions for all four routes rather than
 * the parse alone.
 *
 * `ug_0a1b2c3d` is the real shape: `DOCUMENT_ID_PATTERN` is
 * `config.py:BUILDER_DOCUMENT_ID_PATTERN`, server-assigned and never
 * client-chosen, so a test that used `doc-1` would be testing a document id
 * that cannot exist.
 *
 * WHAT MOVED ON 2026-09-06 (`docs/ux-shell/DEFINITION-OF-DONE.md` D2). `#/` was
 * the console and is now the home; `#/run` is the console. Four assertions here
 * were re-pointed rather than added to, and they are named in W1's report - the
 * three that read the console off the root, off a bare hash and off nothing,
 * and the one that lists the hashes an author would recognise. Every assertion
 * about `#/build` is untouched, which is the deep-link promise stated as a
 * diff.
 */

const ID = documentId('ug_0a1b2c3d')

function atHash<T>(hash: string, run: () => T): T {
  window.location.hash = hash
  return run()
}

describe('the hash names the workspace', () => {
  it('reads the home from the root, from a bare hash and from nothing at all', () => {
    expect(workspaceRoute('#/')).toEqual({ name: 'home' })
    expect(workspaceRoute('#')).toEqual({ name: 'home' })
    expect(workspaceRoute('')).toEqual({ name: 'home' })
  })

  it('reads the run console from #/run', () => {
    expect(workspaceRoute('#/run')).toEqual({ name: 'studio' })
    expect(workspaceRoute('#/run/')).toEqual({ name: 'studio' })
    // A trailing segment is not a second console, and there is nothing for it
    // to name: the console runs one workflow, chosen by a stored handoff rather
    // than by the address.
    expect(workspaceRoute('#/run/anything')).toEqual({ name: 'studio' })
  })

  /**
   * `#/admin` (plan 17, criterion 22).
   *
   * IT IS NOT A PERMISSION AND THIS FILE MUST NOT LOOK LIKE ONE. The parser
   * resolves the hash for anybody who types it; whether the console is drawn is
   * `GET /api/admin/whoami`'s answer, and `adminGate.spec.ts` owns that half. A
   * router that hid the route would put the rule in the one place a reader can
   * edit with the devtools open, and would leave the server's 404 - the actual
   * control - unexercised on this side.
   */
  it('reads the admin console from #/admin', () => {
    expect(workspaceRoute('#/admin')).toEqual({ name: 'admin' })
    expect(workspaceRoute('#/admin/')).toEqual({ name: 'admin' })
    // A trailing segment names nothing: the console's own tab is component
    // state, deliberately not an address (the template-prop reasoning in
    // `App.vue`, applied to a tab).
    expect(workspaceRoute('#/admin/money')).toEqual({ name: 'admin' })
  })

  it('reads the empty builder from #/build', () => {
    expect(workspaceRoute('#/build')).toEqual({ name: 'builder', documentId: null })
    expect(workspaceRoute('#/build/')).toEqual({ name: 'builder', documentId: null })
  })

  it('reads a document id from #/build/:documentId', () => {
    expect(workspaceRoute('#/build/ug_0a1b2c3d')).toEqual({ name: 'builder', documentId: ID })
  })

  it('falls to the home for anything it does not recognise', () => {
    // An unknown hash is not an error state to render; it is a URL that means
    // nothing, and the home is what the app has instead of a 404 page - the
    // screen that lists everything the reader could have meant. It was the
    // console, which listed one workflow and ran it.
    expect(workspaceRoute('#/nonsense')).toEqual({ name: 'home' })
    expect(workspaceRoute('#/builder/ug_0a1b2c3d')).toEqual({ name: 'home' })
    // The old root of the console, one letter out. It must not resolve to the
    // console by accident, or the fallback would be doing it rather than a rule.
    expect(workspaceRoute('#/runs')).toEqual({ name: 'home' })
    // One letter out from the admin route, and it must fall to the home by the
    // rule rather than by luck.
    expect(workspaceRoute('#/admins')).toEqual({ name: 'home' })
    expect(workspaceRoute('#/administration')).toEqual({ name: 'home' })
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
    { name: 'home' },
    { name: 'studio' },
    { name: 'admin' },
    { name: 'builder', documentId: null },
    { name: 'builder', documentId: ID },
  ]

  it('writes a hash each route parses back to itself', () => {
    for (const route of routes) {
      expect(workspaceRoute(routeHash(route))).toEqual(route)
    }
  })

  it('writes the five hashes an author would recognise', () => {
    // Five since plan 17. `#/admin` is in the round trip like any other route:
    // a hand-rolled parser and a hand-rolled serialiser that disagree is the
    // whole risk R13 accepted, and a route exempted from this check is the one
    // that would drift.
    expect(routes.map(routeHash)).toEqual(['#/', '#/run', '#/admin', '#/build', `#/build/${ID}`])
  })
})

/**
 * The one decision the home makes before it settles (D2).
 *
 * It is a pure function taking two facts because the READING of those facts is
 * three different things - `localStorage`, `sessionStorage`, and possibly one
 * `GET /api/runs/{id}` - and none of them is a decision. This is the decision,
 * and it is the half that must not be flaky.
 */
describe('the home hands over to the console only for a run that is still live', () => {
  const pointers: RunPointerState[] = ['none', 'live', 'terminal']

  it('hands over for a builder handoff whatever the pointer says', () => {
    // A graph the author published seconds ago and asked to run. There may be
    // no pointer at all yet, because nothing has been launched.
    for (const pointer of pointers) {
      expect(homeResumesConsole({ handoff: true, pointer }), pointer).toBe(true)
    }
  })

  /**
   * The clause above is about an UN-LAUNCHED handoff, and after RV4 follow-up 1
   * that is the only kind there is.
   *
   * The rule did not change and this test asserts what changed around it: the
   * handoff is a navigation record, `StudioView.launchRun` clears it the moment
   * the run it carried is created, so `handoff: true` with a TERMINAL pointer -
   * the state a Build-launched author was left in, where `#/` handed straight
   * back to a finished run and R4's Last-run card was unreachable - is no
   * longer a state this predicate can be asked about. It is spelled out here
   * because a reader of the row above would otherwise reasonably conclude the
   * home still bounces, and the predicate alone cannot say otherwise.
   */
  it('is only ever asked about a handoff nothing has launched yet', () => {
    expect(homeResumesConsole({ handoff: true, pointer: 'none' })).toBe(true)
    expect(homeResumesConsole({ handoff: false, pointer: 'terminal' })).toBe(false)
  })

  it('hands over for a live pointer, which includes one the server would not confirm', () => {
    expect(homeResumesConsole({ handoff: false, pointer: 'live' })).toBe(true)
  })

  it('stays put for a terminal pointer, and for no pointer at all', () => {
    // History, not a hand-over: the home shows a Last run card and `#/run`
    // still restores it exactly as it did when `#/` was the console.
    expect(homeResumesConsole({ handoff: false, pointer: 'terminal' })).toBe(false)
    expect(homeResumesConsole({ handoff: false, pointer: 'none' })).toBe(false)
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

  it('writes #/admin when it is sent to the admin console', () => {
    const [{ route, navigate }, app] = atHash('#/', () => withSetup(() => useWorkspaceRoute()))
    navigate({ name: 'admin' })
    expect(route.value).toEqual({ name: 'admin' })
    expect(window.location.hash).toBe('#/admin')
    app.unmount()
  })

  it('writes #/run when it is sent to the console', () => {
    const [{ route, navigate }, app] = atHash('#/', () => withSetup(() => useWorkspaceRoute()))
    navigate({ name: 'studio' })
    expect(route.value).toEqual({ name: 'studio' })
    expect(window.location.hash).toBe('#/run')
    app.unmount()
  })

  it('replaces rather than pushes when asked, which is what the home hand-over needs', () => {
    // `replaceState` does not fire `hashchange`, and the ref was already
    // assigned, so the state is right either way - what this pins is that Back
    // from the console reaches whatever was there before the reload rather than
    // a home that would only redirect again.
    const [{ route, navigate }, app] = atHash('#/', () => withSetup(() => useWorkspaceRoute()))
    navigate({ name: 'studio' }, { replace: true })
    expect(route.value).toEqual({ name: 'studio' })
    expect(window.location.hash).toBe('#/run')
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
    expect(route.value).toEqual({ name: 'home' })
  })
})
