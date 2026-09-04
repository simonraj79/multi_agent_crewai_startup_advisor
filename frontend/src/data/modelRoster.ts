import { shallowRef } from 'vue'
import type { ModelRoster } from '../types/builder'

/**
 * The loaded model roster, and nothing else.
 *
 * One `shallowRef` in its own module, split out of `data/models.ts` on
 * 2026-09-04 for one reason: `models.ts` fetches, and to fetch it imports
 * `services/httpCore`, which reads `import.meta.env` at module load. That is
 * correct in the app and correct under Vitest, and it makes the module
 * unimportable by anything that is not Vite - including
 * `scripts/dump-templates.mjs`, which needs the roster to resolve a template's
 * `{{workhorse}}` into the id it names and needs no network at all.
 *
 * So the STATE lives here and the LOADING lives there. `models.ts` re-exports
 * this ref, so every existing importer is unaffected and there is still exactly
 * one roster in the process - a second ref would be a second answer to "which
 * models does this build have", which is the whole thing that module exists to
 * prevent.
 *
 * Replaced whole, never mutated: `shallowRef` means a component re-renders on
 * assignment and not on a nested write, and the roster is a served document
 * rather than a thing anybody edits.
 */
export const roster = shallowRef<ModelRoster | null>(null)
