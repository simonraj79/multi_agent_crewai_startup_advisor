import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AuthoredAgentForm from '../src/components/builder/inspectors/AuthoredAgentForm.vue'
import BudgetMeter from '../src/components/builder/BudgetMeter.vue'
import { ADVANCED_FIELDS, EXPERT_FIELDS } from '../src/components/builder/inspectors/authoredFields'
import { useBuilderProblems } from '../src/composables/useBuilderProblems'
import { FIELD_CODES } from '../src/types/builder'
import type { BuilderBudget, BuilderDocument, BuilderNode, BuilderProblem } from '../src/types/builder'
import type { InspectorCommit } from '../src/components/builder/commit'
import { ref } from 'vue'
import {
  authoredAgentNode,
  documentFixture,
  edge,
  inputNode,
  outputNode,
  problemsProvide,
  vocabularyFixture,
} from './builderInspectorFixtures'

/**
 * 12 D4 and criterion 8: the retry group, where it sits, and what it costs.
 *
 * Three fields - `max_retries`, `backoff_seconds`, `fallback_model` - and the
 * first of them is the one place in the whole vocabulary where a single number
 * MULTIPLIES a node's price rather than adding to it. `budget.py:251` is
 * literally `calls *= max_retries + 1`, applied above the guardrail loop, so an
 * author raising it from 0 to 3 doubles-and-doubles what admission will be
 * measured against.
 *
 * That is why the tier placement matters and is asserted rather than assumed:
 * ADVANCED and not ESSENTIAL, so a first-time author is not handed a cost
 * multiplier before they have named their agent, and not EXPERT, because
 * resilience is an ordinary thing to want.
 *
 * ONE CONTRADICTION WITH THE PLAN, recorded in its Status and stated here so a
 * reader of the test is not left guessing. C8's table gives `retry-over-max` to
 * `document.py`, and at head `RetryConfig.max_retries` is
 * `Field(ge=0, le=BUILDER_MAX_NODE_RETRIES)` - a PARSE-time constraint that
 * refuses the whole document rather than reporting a fixable position, and
 * `NumberRow` CLAMPS above it so the value cannot be typed either. So the code
 * has no reachable instance and is not in the union. What IS asserted below is
 * the half that would carry it the day it exists: the bound is served rather
 * than hardcoded, the control refuses to exceed it, and a problem naming
 * `retry.max_retries` reaches that control through C8's `field` key.
 */

function graph(retry: Partial<{ max_retries: number; backoff_seconds: number }> = {}): BuilderDocument {
  return documentFixture(
    [
      inputNode(),
      authoredAgentNode('scoper', {
        retry: { max_retries: 0, backoff_seconds: 0, fallback_model: null, ...retry },
      }),
      outputNode(),
    ],
    [edge('e1', 'idea', 'scoper'), edge('e2', 'scoper', 'result')],
  )
}

function mountAgent(doc: BuilderDocument = graph(), problems: BuilderProblem[] = []) {
  const node = doc.nodes.find((entry) => entry.id === 'scoper') as Extract<
    BuilderNode,
    { kind: 'agent' }
  >
  return mount(AuthoredAgentForm, {
    props: { doc, node: node as never, vocabulary: vocabularyFixture() },
    global: { provide: problemsProvide(problems) },
  })
}

function lastCommit(wrapper: { emitted: (name: string) => unknown[][] | undefined }): InspectorCommit {
  const emitted = wrapper.emitted('commit')
  expect(emitted, 'nothing was committed').toBeTruthy()
  return emitted![emitted!.length - 1][0] as InspectorCommit
}

function budgetFixture(overrides: Partial<BuilderBudget> = {}): BuilderBudget {
  return {
    billable_nodes: 1,
    escalation_nodes: 0,
    cycles: 0,
    modelled_calls: 6,
    floor_cost_usd: 0.01,
    static_cost_usd: 0.02,
    ceiling_usd: 10,
    over_ceiling: false,
    unpriced_models: [],
    ...(overrides as object),
  } as BuilderBudget
}

describe('where the retry group sits', () => {
  it('is ADVANCED, not essential and not expert', () => {
    for (const field of ['retry.max_retries', 'retry.backoff_seconds', 'retry.fallback_model']) {
      expect(ADVANCED_FIELDS as readonly string[]).toContain(field)
      expect(EXPERT_FIELDS as readonly string[]).not.toContain(field)
    }
  })

  it('renders all three controls, with on_error beside them', () => {
    const wrapper = mountAgent()
    for (const field of [
      'retry.max_retries',
      'retry.backoff_seconds',
      'retry.fallback_model',
      'on_error',
    ]) {
      expect(wrapper.find(`[data-field="${field}"]`).exists(), field).toBe(true)
    }
  })

  it('says which counter it is, because CrewAI has one with the same name', () => {
    // `guardrail_max_retries` is CrewAI's, counted PER GUARDRAIL; `retry` is
    // the builder's own whole-node loop. Two numbers one row apart with almost
    // the same label is a trap unless the help text separates them.
    const wrapper = mountAgent()
    const help = wrapper.find('[data-field="retry.max_retries"]').text()
    expect(help.toLowerCase()).toContain('whole node')
  })
})

describe('the ceiling on max_retries', () => {
  it('comes from the served vocabulary, not from a literal in the form', () => {
    const wrapper = mountAgent()
    const input = wrapper.find('[data-field="retry.max_retries"] input[type="number"]')
    expect(input.exists()).toBe(true)
    expect(input.attributes('max')).toBe(String(vocabularyFixture().bounds.max_retries))
    expect(input.attributes('min')).toBe('0')
  })

  it('CLAMPS a value above the bound rather than committing it', async () => {
    // This is why `retry-over-max` has no reachable instance today: the control
    // will not produce one, and `RetryConfig` refuses one at parse. The clamp
    // is `NumberRow`'s documented behaviour and it is asserted here rather than
    // trusted, because it is the whole reason the code is absent.
    const bound = vocabularyFixture().bounds.max_retries
    const wrapper = mountAgent()
    const input = wrapper.find('[data-field="retry.max_retries"] input[type="number"]')
    await input.setValue(String(bound + 5))
    await input.trigger('change')

    const node = lastCommit(wrapper).next.nodes.find((entry) => entry.id === 'scoper')!
    expect((node.config as { retry: { max_retries: number } }).retry.max_retries).toBe(bound)
  })

  it('commits a legal value as one discrete undo step', async () => {
    const wrapper = mountAgent()
    const input = wrapper.find('[data-field="retry.max_retries"] input[type="number"]')
    await input.setValue('2')
    await input.trigger('change')

    const commit = lastCommit(wrapper)
    const node = commit.next.nodes.find((entry) => entry.id === 'scoper')!
    expect((node.config as { retry: { max_retries: number } }).retry.max_retries).toBe(2)
    // A stepper is a decision, not typing: no coalesce key, so two presses are
    // two undo steps.
    expect(commit.coalesceKey).toBeUndefined()
  })

  it('keeps the other two retry fields when one is changed', async () => {
    const wrapper = mountAgent(graph({ backoff_seconds: 7 }))
    const input = wrapper.find('[data-field="retry.max_retries"] input[type="number"]')
    await input.setValue('1')
    await input.trigger('change')

    const node = lastCommit(wrapper).next.nodes.find((entry) => entry.id === 'scoper')!
    const retry = (node.config as { retry: { backoff_seconds: number; fallback_model: unknown } }).retry
    // `patchConfig` merges ONE level, so a retry patch that did not spread
    // `retry` itself would drop the other two and the document would still
    // parse - the one failure in this form that is silent.
    expect(retry.backoff_seconds).toBe(7)
    expect(retry.fallback_model).toBeNull()
  })
})

describe('a retry problem finds its control', () => {
  it('anchors to retry.max_retries through C8 field, code or no code', () => {
    const problems = ref<BuilderProblem[]>([
      {
        code: 'retry-over-max',
        severity: 'error',
        message: 'max_retries is 9 and the ceiling is 3.',
        node_id: 'scoper',
        edge_id: null,
        field: 'retry.max_retries',
      },
    ])
    const index = useBuilderProblems(problems)
    // The payload's own `field` wins, which is what lets a code this build has
    // never heard of still land on the right control - `FIELD_CODES` holds
    // nothing for it.
    expect(FIELD_CODES['retry-over-max' as never]).toBeUndefined()
    expect(index.fieldFor(problems.value[0])).toBe('retry.max_retries')
    expect(index.problemsForField('scoper', 'retry.max_retries')).toHaveLength(1)
    expect(index.unplacedForNode('scoper', ['retry.max_retries'])).toHaveLength(0)
  })

  it('renders on the control rather than in the node strip', () => {
    const wrapper = mountAgent(graph(), [
      {
        code: 'retry-over-max',
        severity: 'error',
        message: 'max_retries is 9 and the ceiling is 3.',
        node_id: 'scoper',
        edge_id: null,
        field: 'retry.max_retries',
      },
    ])
    const row = wrapper.find('[data-field="retry.max_retries"]')
    expect(row.text()).toContain('the ceiling is 3')
  })
})

describe('the price of resilience is visible before it is spent', () => {
  it('is the SERVER figure, re-rendered - the meter computes no multiplier', () => {
    // 09 D4 prices the retry loop: `budget.py:251` is `calls *= max_retries+1`,
    // above the guardrail loop, because the whole node re-runs. The meter's job
    // is to show what came back, and `tests/builder/test_budget.py::
    // RetryPricingTests` is what pins the arithmetic. Two figures here, and the
    // second is what admission is measured against.
    const cheap = mount(BudgetMeter, {
      props: { budget: budgetFixture({ modelled_calls: 6, static_cost_usd: 0.02 }), nodeCount: 3 },
    })
    expect(cheap.find('[data-testid="budget-static"]').text()).toContain('0.02')

    const retried = mount(BudgetMeter, {
      props: { budget: budgetFixture({ modelled_calls: 24, static_cost_usd: 0.08 }), nodeCount: 3 },
    })
    expect(retried.find('[data-testid="budget-static"]').text()).toContain('0.08')
  })

  it('says it is not yet priced rather than showing a stale number', () => {
    const wrapper = mount(BudgetMeter, { props: { budget: null, nodeCount: 3 } })
    expect(wrapper.find('[data-testid="budget-pending"]').exists()).toBe(true)
  })
})
