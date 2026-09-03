import { scopedKey } from './identityStorage'
import type { StorageIdentity } from './identityStorage'

/**
 * The one fact the builder hands the run console: which published graph to run,
 * and what its request input is called.
 *
 * NOT IN THE SPEC'S MANIFEST, and it exists because ruling R4 was overridden.
 * The spec cut Run mode on the grounds that no builder runner existed; one does
 * now (`service/builder_runner.py`), and a published graph really launches - so
 * `PublishDialog` offers "Run it" and something has to carry the workflow id
 * across the route change.
 *
 * WHY NOT THE URL. `useWorkspaceRoute` is WP-0's file and its studio route is
 * `{ name: 'studio' }` with no fields; `tests/workspaceRoute.spec.ts` asserts
 * that shape with `toEqual` in four places. Adding a field to it would edit
 * another package's spec to make room for this one, which is the sort of
 * cross-package reach the collision map exists to prevent. So the handoff rides
 * beside the route rather than inside it.
 *
 * WHY IT IS NOT HIDDEN. A silent channel that quietly repointed the console at
 * a different workflow would be exactly the mock-mode failure this repo has
 * already written up twice: a convincing screen that is not about what the
 * reader thinks it is about. `StudioView` renders a strip naming the graph with
 * a control that clears this key, and the header shows the loaded graph's own
 * name either way.
 *
 * `sessionStorage`, not `localStorage`. The handoff is about THIS tab's
 * navigation. A published graph is not a preference, and finding the console
 * pointed at a graph published on another machine last week would be a
 * mystery with no visible cause.
 *
 * AND IT IS THE SIGNED-IN USER'S (D-01-5). Written by one person and read by
 * the next on the same browser, it pointed a stranger's console at the previous
 * user's graph under "Running your published graph". Every function here takes
 * the identity and keys the record to it (`identityStorage.ts`); `null` is
 * nobody, which is the auth-off backend and the unit suite, and keeps the
 * anonymous key shape.
 */

export const HANDOFF_KEY = 'builder-run-handoff'

export interface BuilderRunHandoff {
  /** The published document id, which is also the workflow id. */
  workflowId: string
  /** `BuilderPublish.input_field` - the key `inputs` must carry. */
  inputField: string
  /** The graph's name, so the console can say what it is pointed at. */
  name: string
}

/** The handoff, or null. Never throws: storage can be blocked outright. */
export function readRunHandoff(userId: StorageIdentity = null): BuilderRunHandoff | null {
  try {
    const raw = window.sessionStorage.getItem(scopedKey(HANDOFF_KEY, userId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<BuilderRunHandoff>
    // Every field checked, because a value that survived a build change is
    // indistinguishable from one this build wrote - and a missing `inputField`
    // would launch a graph under the wrong `inputs` key and answer 422.
    if (!parsed.workflowId || !parsed.inputField || !parsed.name) return null
    return { workflowId: parsed.workflowId, inputField: parsed.inputField, name: parsed.name }
  } catch {
    return null
  }
}

export function writeRunHandoff(handoff: BuilderRunHandoff, userId: StorageIdentity = null): void {
  try {
    window.sessionStorage.setItem(scopedKey(HANDOFF_KEY, userId), JSON.stringify(handoff))
  } catch {
    /* A browser refusing storage must not stop the navigation. The console then
     * opens on the built-in validator and says so, which is wrong but visible -
     * unlike a thrown error inside a click handler. */
  }
}

export function clearRunHandoff(userId: StorageIdentity = null): void {
  try {
    window.sessionStorage.removeItem(scopedKey(HANDOFF_KEY, userId))
  } catch {
    /* Same reasoning as the write. */
  }
}
