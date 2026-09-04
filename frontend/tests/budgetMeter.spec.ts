import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import BudgetMeter, {
  GRAPH_STATIC_BUDGET_MARGIN,
  NITRO_PRICE_FACTOR,
} from '../src/components/builder/BudgetMeter.vue'
import { resetVocabulary, vocabulary, vocabularyProblem } from '../src/data/builderVocabulary'
import type { BuilderBudget, BuilderBounds, BuilderVocabulary } from '../src/types/builder'

/**
 * A cost display that rounds a real graph to $0.00, or draws a percentage of a
 * disabled ceiling, is worse than none at all.
 *
 * This repo has already shipped the first of those: 128,069 real tokens
 * reported at `cost_usd = 0.0`, because "no price on file" and "this call was
 * free" had the same spelling. The meter is the author-facing half of the same
 * arithmetic, and every assertion below is about it refusing to state something
 * it cannot support - one figure where there are two, a bar where there is no
 * ceiling, a denominator where the bounds have not loaded.
 *
 * The two duplicated constants are asserted against `config.py` at run time
 * rather than trusted, which is the `data/serverLimits.ts` idiom: the drift is
 * a failing test instead of a bar that fills at the wrong moment.
 */

/** Through a parameter, or Vite rewrites the literal into an asset URL. See `builderProblems.spec.ts`. */
function pythonSource(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8')
}

const CONFIG_PY = pythonSource('../../src/brief_crew/config.py')

function pythonNumber(name: string): number {
  const row = new RegExp(`^${name} = ([0-9.]+)$`, 'm').exec(CONFIG_PY)
  expect(row, `${name} moved or changed shape in config.py`).not.toBeNull()
  return Number((row as RegExpExecArray)[1])
}

/**
 * Bounds as the wire sends them: `dict[str, float]` in Python, so every value
 * arrives as a JSON FLOAT. `13.0`, not `13` - and a pip row that forgot to
 * truncate would read `2 of 13.0`.
 */
const BOUNDS: BuilderBounds = {
  max_graph_nodes: 24.0,
  max_billable_nodes: 13.0,
  max_escalation_nodes: 8.0,
  max_fanout_width: 4.0,
  min_router_branches: 2.0,
  max_cycles: 3.0,
  max_cycle_iterations: 3.0,
  max_agent_iter: 8.0,
  max_guardrail_retries: 2.0,
  max_label_chars: 40.0,
  max_name_chars: 80.0,
  max_gate_message_chars: 2000.0,
  max_input_chars: 2000.0,
  max_document_bytes: 262144.0,
  run_cost_ceiling_usd: 10.0,
  // C2 v2\'s two authored-node bounds: BUILDER_MAX_PROMPT_CHARS and
  // BUILDER_MAX_NODE_RETRIES, served since plan 04 and read by every
  // PromptField and node-retry stepper rather than restated as a constant.
  max_prompt_chars: 4000,
  max_retries: 3,
}

const VOCABULARY: BuilderVocabulary = {
  schema_id: 'builder.flow/v1',
  node_kinds: ['input', 'agent', 'crew', 'gate', 'router', 'transform', 'output'],
  tiers: ['cheap', 'escalation'],
  agent_ids: ['scoper'],
  crew_ids: ['brief'],
  research_tools: ['market_research'],
  transform_ops: ['pick'],
  router_comparisons: ['eq'],
  router_otherwise: 'otherwise',
  result_body_keys: ['markdown_body'],
  bounds: BOUNDS,
}

function budget(overrides: Partial<BuilderBudget> = {}): BuilderBudget {
  return {
    static_cost_usd: 2.0,
    floor_cost_usd: 1.2,
    modelled_calls: 24,
    billable_nodes: 4,
    escalation_nodes: 2,
    cycles: 1,
    unpriced_models: [],
    over_ceiling: false,
    ceiling_usd: 10,
    ...overrides,
  }
}

function meter(
  overrides: Partial<BuilderBudget> | null = {},
  options: { nodeCount?: number; withVocabulary?: boolean; stale?: boolean } = {},
) {
  if (options.withVocabulary !== false) vocabulary.value = VOCABULARY
  return mount(BudgetMeter, {
    props: {
      budget: overrides === null ? null : budget(overrides),
      nodeCount: options.nodeCount ?? 9,
      stale: options.stale ?? false,
    },
  })
}

afterEach(() => resetVocabulary())

describe('the two duplicated server constants are held against the Python', () => {
  it('matches GRAPH_STATIC_BUDGET_MARGIN', () => {
    expect(GRAPH_STATIC_BUDGET_MARGIN).toBe(pythonNumber('GRAPH_STATIC_BUDGET_MARGIN'))
  })

  it('matches NITRO_PRICE_FACTOR', () => {
    expect(NITRO_PRICE_FACTOR).toBe(pythonNumber('NITRO_PRICE_FACTOR'))
  })
})

describe('both dollar figures are shown, because either one alone is a lie', () => {
  it('renders the published-price figure and the enforced one, each labelled', () => {
    const wrapper = meter({ floor_cost_usd: 1.2, static_cost_usd: 2 })

    const floor = wrapper.get('[data-testid="budget-floor"]')
    const enforced = wrapper.get('[data-testid="budget-static"]')

    expect(floor.text()).toContain('$1.20')
    expect(floor.text()).toContain('at published prices')
    // The enforced figure is above any invoice, so it says why it is: shown
    // alone it reads as an error rather than as a margin.
    expect(enforced.text()).toContain('$2.00')
    expect(enforced.text()).toContain('nitro margin')
    expect(enforced.text()).toContain(String(NITRO_PRICE_FACTOR))
  })

  it('never rounds a sub-cent graph down to $0.00', () => {
    const wrapper = meter({ floor_cost_usd: 0.004, static_cost_usd: 0.007 })

    // Two decimal places here is the shape of the defect this repo shipped
    // once. A four-cent graph reading `$0.00` is indistinguishable from a graph
    // nothing could price.
    expect(wrapper.get('[data-testid="budget-floor"]').text()).toContain('$0.0040')
    expect(wrapper.get('[data-testid="budget-static"]').text()).toContain('$0.0070')
  })

  it('still says $0.00 for an honest zero', () => {
    const wrapper = meter({ floor_cost_usd: 0, static_cost_usd: 0 })
    expect(wrapper.get('[data-testid="budget-floor"]').text()).toContain('$0.00')
  })

  it('renders nothing but a stated pending state before the first answer', () => {
    const wrapper = meter(null)

    expect(wrapper.find('[data-testid="budget-pending"]').text()).toBe('not yet priced')
    expect(wrapper.find('[data-testid="budget-track"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="budget-floor"]').exists()).toBe(false)
  })
})

describe('the bar reaches full exactly where the compiler starts refusing', () => {
  it('fills to the margin-applied fraction of the ceiling', () => {
    const wrapper = meter({ static_cost_usd: 4, ceiling_usd: 10 })

    // 4 x 1.25 = 5 of 10.
    expect(wrapper.get('[data-testid="budget-track"]').find('span').attributes('style')).toContain(
      'width: 50%',
    )
  })

  it('is exactly full at the graph that flips over_ceiling', () => {
    const ceiling = 10
    const atTheLine = ceiling / GRAPH_STATIC_BUDGET_MARGIN
    const wrapper = meter({ static_cost_usd: atTheLine, ceiling_usd: ceiling, over_ceiling: false })
    const track = wrapper.get('[data-testid="budget-track"]')

    expect(track.find('span').attributes('style')).toContain('width: 100%')
    expect(track.classes()).toContain('is-over')
  })

  it('warns in amber from 80% of the way there', () => {
    const wrapper = meter({ static_cost_usd: 6.4, ceiling_usd: 10 })
    // 6.4 x 1.25 = 8 of 10.
    expect(wrapper.get('[data-testid="budget-track"]').classes()).toContain('is-near')
  })

  it('stays clear below 80%', () => {
    const wrapper = meter({ static_cost_usd: 2, ceiling_usd: 10 })
    expect(wrapper.get('[data-testid="budget-track"]').classes()).toContain('is-clear')
  })

  it('reads the server boolean, not its own arithmetic, for the refusal tone', () => {
    // A ceiling that has been refused but whose arithmetic rounds just under
    // 100% must still render as over: the boolean is the compiler's answer and
    // the fraction is a picture of it.
    const wrapper = meter({ static_cost_usd: 7.999, ceiling_usd: 10, over_ceiling: true })
    expect(wrapper.get('[data-testid="budget-track"]').classes()).toContain('is-over')
  })
})

describe('a disabled ceiling removes the bar rather than drawing a zero', () => {
  it('hides the track entirely and says so when ceiling_usd is 0', () => {
    const wrapper = meter({ ceiling_usd: 0 })

    // A percentage of zero is either 0 or infinity, and both are lies about a
    // deployment that deliberately set MAX_RUN_COST_USD=0.
    expect(wrapper.find('[data-testid="budget-track"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="budget-ceiling"]').text()).toContain('no ceiling configured')
  })

  it('hides it for a negative ceiling too', () => {
    const wrapper = meter({ ceiling_usd: -1 })
    expect(wrapper.find('[data-testid="budget-track"]').exists()).toBe(false)
  })

  it('still shows both dollar figures with no ceiling', () => {
    const wrapper = meter({ ceiling_usd: 0, floor_cost_usd: 3, static_cost_usd: 5 })

    expect(wrapper.get('[data-testid="budget-floor"]').text()).toContain('$3.00')
    expect(wrapper.get('[data-testid="budget-static"]').text()).toContain('$5.00')
  })
})

describe('the four headroom rows read the served bounds and never a constant', () => {
  it('truncates the JSON floats the vocabulary sends', () => {
    const wrapper = meter({ billable_nodes: 4, escalation_nodes: 2, cycles: 1 }, { nodeCount: 9 })

    // The server has already moved these twice - billable 8 -> 13, escalation
    // 5 -> 8 - so a hardcoded denominator would now be calling a legal graph
    // over the line.
    expect(wrapper.get('[data-testid="budget-pip-billable"]').text()).toBe('4 of 13')
    expect(wrapper.get('[data-testid="budget-pip-escalation"]').text()).toBe('2 of 8')
    expect(wrapper.get('[data-testid="budget-pip-cycles"]').text()).toBe('1 of 3')
    expect(wrapper.get('[data-testid="budget-pip-nodes"]').text()).toBe('9 of 24')
  })

  it('counts every node for the graph row, not just the billable ones', () => {
    const wrapper = meter({ billable_nodes: 2 }, { nodeCount: 17 })

    expect(wrapper.get('[data-testid="budget-pip-billable"]').text()).toBe('2 of 13')
    expect(wrapper.get('[data-testid="budget-pip-nodes"]').text()).toBe('17 of 24')
  })

  it('draws one pip per unit of the bound, filled up to the count', () => {
    const wrapper = meter({ cycles: 1 })
    const row = wrapper.get('[data-testid="budget-pip-cycles"]').element.parentElement as HTMLElement
    const pips = row.querySelectorAll('.budget-pip')

    expect(pips).toHaveLength(3)
    expect(row.querySelectorAll('.budget-pip.is-filled')).toHaveLength(1)
  })

  it('goes amber AT the bound, not one past it', () => {
    const wrapper = meter({ escalation_nodes: 8 })
    const row = wrapper.get('[data-testid="budget-pip-escalation"]').element
      .parentElement as HTMLElement

    // The author has to see the row go full BEFORE they place the node the
    // server refuses. Amber one past the line is a warning that arrives with
    // the error it was supposed to precede.
    expect(row.classList.contains('is-near')).toBe(true)
    expect(row.classList.contains('is-over')).toBe(false)
  })

  it('goes red once a bound has actually been exceeded', () => {
    const wrapper = meter({ escalation_nodes: 9 })
    const row = wrapper.get('[data-testid="budget-pip-escalation"]').element
      .parentElement as HTMLElement

    expect(row.classList.contains('is-over')).toBe(true)
  })

  it('drops the denominator, and says why, when the vocabulary has not loaded', () => {
    vocabularyProblem.value = 'the vocabulary could not be fetched'
    const wrapper = meter({ billable_nodes: 4 }, { withVocabulary: false })

    // Cut list item 17 applied to a number: a guessed bound is how a canvas
    // starts telling authors things the compiler never said.
    expect(wrapper.get('[data-testid="budget-pip-billable"]').text()).toBe('4')
    expect(wrapper.text()).toContain('the vocabulary could not be fetched')
  })
})

describe('an unpriced model is named, because it is the one that costs nothing on paper', () => {
  it('renders an alert naming the slug', () => {
    const wrapper = meter({ unpriced_models: ['openrouter/some-new-model'] })
    const alert = wrapper.get('[data-testid="budget-unpriced"]')

    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toContain('openrouter/some-new-model')
    expect(alert.text()).toContain('contribute nothing to this total')
  })

  it('renders nothing when every model is priced', () => {
    const wrapper = meter({ unpriced_models: [] })
    expect(wrapper.find('[data-testid="budget-unpriced"]').exists()).toBe(false)
  })
})

describe('a pending check dims the figures rather than removing them', () => {
  it('keeps the last estimate on screen while validation is stale', () => {
    const wrapper = meter({ floor_cost_usd: 1.2 }, { stale: true })

    expect(wrapper.classes()).toContain('is-stale')
    expect(wrapper.get('[data-testid="budget-floor"]').text()).toContain('$1.20')
  })
})

describe('the bar is announced, not just drawn', () => {
  it('carries a progressbar role with the figures in its value text', () => {
    const track = meter({ static_cost_usd: 4, ceiling_usd: 10 }).get('[data-testid="budget-track"]')

    expect(track.attributes('role')).toBe('progressbar')
    expect(track.attributes('aria-valuenow')).toBe('50')
    expect(track.attributes('aria-valuetext')).toContain('$4.00')
    expect(track.attributes('aria-valuetext')).toContain('$10.00')
  })
})
