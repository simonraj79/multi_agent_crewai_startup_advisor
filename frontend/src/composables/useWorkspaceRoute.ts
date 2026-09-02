import { onBeforeUnmount, ref } from 'vue'
import { DOCUMENT_ID_PATTERN } from '../types/builder'
import type { DocumentId } from '../types/builder'

/**
 * Which of the two workspaces the window is showing, read from and written to
 * `location.hash`.
 *
 * Sixty lines instead of `vue-router`, and the reason is deployment rather than
 * taste (R13). `frontend/server/index.ts` is a Hono service that serves the
 * built SPA, and history mode would need a catch-all rewrite declared there AND
 * in the Vite dev server - two places, both of which fail by serving a 404 for
 * a URL the author bookmarked and neither of which any test would notice. A
 * hash is inert: every request is for `/`, and the part after `#` never leaves
 * the browser. The cut list also forbids the dependency outright (item 7).
 *
 * `#/build/:documentId` is a real deep link. It is the URL an author sends a
 * colleague and the URL a refresh returns to, so the document id has to survive
 * a round trip through the address bar unchanged - which is what
 * `workspaceRoute`/`routeHash` are tested on.
 */
export type WorkspaceRoute =
  | { name: 'studio' }
  | { name: 'builder'; documentId: DocumentId | null }

const STUDIO: WorkspaceRoute = { name: 'studio' }

/**
 * The route a hash names, with anything unrecognised falling to the studio.
 *
 * A malformed document id lands on the EMPTY builder rather than on a builder
 * claiming to hold it. `DOCUMENT_ID_PATTERN` is the server's own
 * `BUILDER_DOCUMENT_ID_PATTERN`, so a hash that fails it names a document no
 * `GET /api/builder/workflows/{id}` can return - the gallery is the honest
 * landing for that, and carrying the bad id forward would only turn one wrong
 * URL into one wrong request and a 422 about a field the author never typed.
 *
 * Exported because it is the whole parser: `useWorkspaceRoute` is a ref, a
 * listener and a setter around this function, and a test that has to mount a
 * composable to find out what `#/build/x` means is testing the wrong thing.
 */
export function workspaceRoute(hash: string): WorkspaceRoute {
  const path = hash.replace(/^#/, '')
  const segments = path.split('/').filter((segment) => segment.length > 0)
  if (segments[0] !== 'build') return STUDIO
  const id = segments[1]
  if (id === undefined || !DOCUMENT_ID_PATTERN.test(id)) return { name: 'builder', documentId: null }
  return { name: 'builder', documentId: id as DocumentId }
}

/** The hash a route is written as. The exact inverse of `workspaceRoute`. */
export function routeHash(route: WorkspaceRoute): string {
  if (route.name === 'studio') return '#/'
  return route.documentId === null ? '#/build' : `#/build/${route.documentId}`
}

/**
 * The current route, and the one function that changes it.
 *
 * `navigate` assigns the ref BEFORE it writes `location.hash`, and that
 * ordering is deliberate twice over. A `hashchange` is dispatched as a task
 * rather than synchronously, so without it the view would lag one tick behind
 * the click - visible as a flash of the outgoing workspace. And it makes the
 * listener idempotent instead of load-bearing: the same route parsed twice
 * assigns the same value, so a back button, a pasted URL and a click all arrive
 * at the same state by the same path.
 *
 * Writing the hash is skipped when it already matches, because assigning an
 * unchanged `location.hash` still pushes a history entry in some browsers, and
 * a Back that appears to do nothing is worse than no Back at all.
 */
export function useWorkspaceRoute() {
  const route = ref<WorkspaceRoute>(workspaceRoute(window.location.hash))

  const sync = () => {
    route.value = workspaceRoute(window.location.hash)
  }
  window.addEventListener('hashchange', sync)
  onBeforeUnmount(() => window.removeEventListener('hashchange', sync))

  /**
   * `replace` rewrites the current history entry instead of pushing a new one.
   *
   * There is exactly one caller and it is the reason the option exists: the
   * first save of a new draft, where the server hands back an id and the
   * address has to start naming it. Pushing there would put `#/build` (the
   * gallery) and `#/build/<id>` (the same document, now stored) next to each
   * other on the stack, so Back would land the author on a gallery they never
   * visited from a graph they are still editing. Replacing keeps Back meaning
   * "the page before I started building".
   *
   * `replaceState` does not fire `hashchange`, which is exactly right here -
   * `route.value` was already assigned above, and re-parsing the same hash
   * would be a no-op anyway.
   */
  const navigate = (next: WorkspaceRoute, options: { replace?: boolean } = {}) => {
    route.value = next
    const hash = routeHash(next)
    if (window.location.hash === hash) return
    if (options.replace) {
      window.history.replaceState(window.history.state, '', hash)
      return
    }
    window.location.hash = hash
  }

  return { route, navigate }
}
