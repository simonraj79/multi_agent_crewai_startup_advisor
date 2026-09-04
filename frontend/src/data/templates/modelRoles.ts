import { roster } from '../modelRoster'
import type { BuilderDocument, ModelRoster } from '../../types/builder'

/**
 * The three model ROLES a shipped template may name, and how each resolves.
 *
 * A template that hardcoded today's escalation slug would be wrong the first
 * time `scripts/refresh_models.py` runs, and wrong SILENTLY: the id would still
 * parse, the canvas would still draw, and the server would answer
 * `model-unknown` on a graph nobody had touched. This repository has published
 * a stale number six times by writing one down; a model slug in a gallery
 * template is the same mistake with a price attached.
 *
 * So a template says what a node is FOR and the roster says which id that is
 * today. Three roles, because three is what the four templates actually need to
 * teach anything about cost - a classifier that says one word, a workhorse that
 * does the reading, and the tier you escalate to when the writing matters:
 *
 *   {{cheapest}}    the least a decision can cost on this build
 *   {{workhorse}}   `presets.cheap`      - the tool-using research tier
 *   {{escalation}}  `presets.escalation` - synthesis and writing
 *
 * WHY `workhorse` IS NOT SPELLED `cheap`. It reads `presets.cheap`, and the two
 * words are deliberately different: `cheap` is the name of a TIER in
 * `config.py`, which is a policy word an author never sees, and `workhorse` is
 * what the node is for. A template that said `{{cheap}}` beside `{{cheapest}}`
 * would be two words one letter apart meaning two different models, on a card
 * whose whole job is to be read once and understood.
 *
 * WHY `cheapest` IS DERIVED RATHER THAN DECLARED. There is no `cheapest` preset
 * and there should not be one: `config.py`'s presets are the two models this
 * PROJECT configures, and the cheapest row is a fact about the catalogue that
 * moves whenever the catalogue does. It is measured on
 * `cost_in_max_endpoint` - what a slug CAN bill, not its headline - because
 * that is the figure plan 05 added for exactly this question, and because a
 * headline that hides a dearer endpoint is how a "cheap" classifier stops being
 * one. Ties break on `cost_in`, then on id, so the answer is total and stable.
 *
 * The two capability filters are not decoration. A role token is resolved into
 * a node whose model may later be given a tool or asked for JSON, and a row
 * that cannot do either would turn a template into a `model-lacks-capability`
 * the moment somebody dropped a tool on it. All ten rows satisfy both today, so
 * the filter changes no answer now - it is there so that a future roster row
 * priced at $0.01 and unable to call a tool cannot silently become the model
 * every template's classifier runs on.
 *
 * RESOLUTION IS AT LOAD, NOT AT PUBLISH. `documentFromTemplate` resolves, so
 * what reaches the store, the inspector, the budget meter and the server is an
 * ordinary document naming ordinary models - there is no token anywhere in the
 * save path and no second spelling of a model id for anything downstream to
 * learn. `scripts/emit_builder_fixtures.py` resolves the same three roles from
 * `config.MODEL_PRESETS` and `config.MODEL_REGISTRY`, and
 * `tests/builder/test_role_tokens.py` asserts the two agree, because a client
 * mirror of server truth is admitted only on that condition (spec R7).
 */

/** `{{name}}`, and nothing else. Anchored, so a slug containing braces is not a token. */
const TOKEN = /^\{\{([a-z]+)\}\}$/

/** The three role names a template may write. */
export const MODEL_ROLES = ['cheapest', 'workhorse', 'escalation'] as const

export type ModelRole = (typeof MODEL_ROLES)[number]

/** The token spelling of one role, for a template module to write. */
export const roleToken = (role: ModelRole): string => `{{${role}}}`

/** The role a string names, or null when it is an ordinary model id. */
export function roleOf(value: unknown): ModelRole | null {
  if (typeof value !== 'string') return null
  const match = TOKEN.exec(value)
  if (!match) return null
  const name = match[1] as ModelRole
  return MODEL_ROLES.includes(name) ? name : null
}

/**
 * The roster's least expensive row that could still be given a tool or asked
 * for JSON, by the price it can actually bill.
 */
function cheapestId(loaded: ModelRoster): string | null {
  const usable = loaded.models.filter(
    (model) => model.supports_tools && model.supports_json_mode,
  )
  if (usable.length === 0) return null
  return usable.reduce((best, model) => {
    if (model.cost_in_max_endpoint !== best.cost_in_max_endpoint) {
      return model.cost_in_max_endpoint < best.cost_in_max_endpoint ? model : best
    }
    if (model.cost_in !== best.cost_in) return model.cost_in < best.cost_in ? model : best
    return model.id < best.id ? model : best
  }).id
}

/**
 * What each role resolves to on this build, or `null` for a role this roster
 * cannot answer.
 *
 * `null` rather than a substitute, and that is `data/models.ts`'s rule rather
 * than a new one: a client-side stand-in for a model id is how a canvas starts
 * offering models the compiler has never heard of. An unresolved token is left
 * in the document, where the server answers `model-unknown` naming the token
 * itself - which is a sentence an author can act on, unlike a graph priced
 * against a model nobody chose.
 */
export function resolvedRoles(
  loaded: ModelRoster | null = roster.value,
): Record<ModelRole, string | null> {
  if (!loaded) return { cheapest: null, workhorse: null, escalation: null }
  return {
    cheapest: cheapestId(loaded),
    workhorse: loaded.presets.cheap ?? null,
    escalation: loaded.presets.escalation ?? null,
  }
}

/**
 * The same document with every `{{role}}` replaced by the id it names today.
 *
 * MUTATES its argument, because its one caller has just `structuredClone`d a
 * module singleton and a second copy would be a second thing to keep in step.
 * It walks `llm.model`, `manager_llm.model`, `planning_llm.model` and
 * `retry.fallback_model` by walking every string value under every node's
 * config rather than by naming those four paths - a fifth field carrying a
 * model id is a schema change away, and a path list is the kind of mirror that
 * rots without saying so.
 */
export function resolveModelRoles(
  document: BuilderDocument,
  loaded: ModelRoster | null = roster.value,
): BuilderDocument {
  const answers = resolvedRoles(loaded)
  const walk = (value: unknown): void => {
    if (!value || typeof value !== 'object') return
    if (Array.isArray(value)) {
      value.forEach(walk)
      return
    }
    for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
      const role = roleOf(entry)
      if (role) {
        const answer = answers[role]
        if (answer) (value as Record<string, unknown>)[key] = answer
      } else {
        walk(entry)
      }
    }
  }
  document.nodes.forEach((node) => walk(node.config))
  return document
}
