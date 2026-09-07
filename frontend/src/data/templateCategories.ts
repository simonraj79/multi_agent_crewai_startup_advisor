/**
 * The six sections of the template gallery, in the order they are shown.
 *
 * A category is indexed by the QUESTION a person arrives with, never by an
 * architecture name. Both pattern audits (Google's design-pattern guide and
 * Anthropic's whitepaper, `docs/pattern-templates/`) sort their patterns by
 * workload characteristic rather than by topology, and a lay person browsing
 * a gallery has a job, not a vocabulary. The order is the progression both
 * sources recommend: start with one worker, then a line, then a fork, then
 * side by side, then a check, then a team.
 *
 * There is deliberately no "multi-agent" category. Google's own finding was
 * that the label is most often attached to a single model working through a
 * chain of prompts with agent names on it; a category by that name invites
 * exactly that confusion. And there is no "connect to outside systems"
 * category, because the one pattern that would fill it (a workflow exposed to
 * other agents as an MCP server) is not something this runtime does; the
 * gallery says so at its foot instead of pretending with a card.
 *
 * Human approval is not a category either. Eleven of the thirteen templates
 * carry a gate above their first billable node, so it is a property of the
 * gallery, said once in the lede, not a shelf to browse.
 *
 * These ids are a closed union and a Python test asserts every template names
 * one and every category has at least one template. Change an id here and
 * `tests/builder/test_templates.py` says which template still carries the old
 * one.
 */

export type TemplateCategoryId = 'start' | 'chain' | 'route' | 'parallel' | 'review' | 'team'

export interface TemplateCategory {
  readonly id: TemplateCategoryId
  /** The section heading. Two or three words. */
  readonly title: string
  /** The question a person is asking when this is the right shelf. Rendered under the title. */
  readonly question: string
  /** What every card on this shelf promises, in one sentence. Rendered on the jump list's tooltip and the section lede. */
  readonly promise: string
}

export const TEMPLATE_CATEGORIES: readonly TemplateCategory[] = [
  {
    id: 'start',
    title: 'Start here',
    question: 'I have one job and want the simplest thing that does it.',
    promise: 'One worker, one job. Prove it works before adding anything.',
  },
  {
    id: 'chain',
    title: 'Do it in order',
    question: 'The work has stages, and each stage needs the last one’s result.',
    promise: 'A line of focused steps, each easier than the whole.',
  },
  {
    id: 'route',
    title: 'Send it to the right place',
    question: 'Different requests need different handling, and most of them are easy.',
    promise: 'Sort first, then spend only where it is needed.',
  },
  {
    id: 'parallel',
    title: 'Do several things at once',
    question: 'Some of these steps do not need each other. Why are they waiting?',
    promise: 'Independent work runs side by side, and one step waits for all of it.',
  },
  {
    id: 'review',
    title: 'Get it right before it ships',
    question: 'How do I stop it sending something wrong?',
    promise: 'Nothing leaves until a check has passed, even when a model is down.',
  },
  {
    id: 'team',
    title: 'Let a lead run the team',
    question: 'The job is too broad for one worker and needs a plan.',
    promise: 'A lead decides the order and the emphasis over a team you chose.',
  },
]

/** The category record for an id, or a thrown error naming the id, never `undefined`. */
export function templateCategory(id: TemplateCategoryId): TemplateCategory {
  const found = TEMPLATE_CATEGORIES.find((category) => category.id === id)
  if (!found) throw new Error(`unknown template category '${id}'`)
  return found
}
