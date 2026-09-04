import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import InspectorRail from '../src/components/builder/InspectorRail.vue'
import { summaryLines } from '../src/components/builder/BuilderNode.vue'
import {
  EXPERT_STORAGE_KEY,
  resetInspectorTiers,
} from '../src/components/builder/inspectors/expertMode'
import {
  ADVANCED_FIELDS,
  AUTHORED_AGENT_FIELDS,
  ESSENTIAL_FIELDS,
  EXPERT_FIELDS,
} from '../src/components/builder/inspectors/authoredFields'
import { BUILDER_BUDGET } from '../src/composables/useBuilderValidation'
import { resetModels, roster } from '../src/data/models'
import { FIELD_CODES, PROBLEM_CODES, isAuthoredAgent, nodeId } from '../src/types/builder'
import type {
  AuthoredAgentConfig,
  BuilderBudget,
  BuilderEdge,
  BuilderNode,
  BuilderProblem,
  RegistryModel,
} from '../src/types/builder'
import type { InspectorCommit } from '../src/components/builder/commit'
import {
  DOCUMENT_PY,
  authoredAgentNode,
  authoredCrewNode,
  agentNode,
  documentFixture,
  edge,
  problem,
  problemsProvide,
  vocabularyFixture,
} from './builderInspectorFixtures'

/**
 * The authored arm: 04 D1's three regions, D2's field table, D3's capability
 * gate, D6's per-node cost and D8's shared multi-selection.
 *
 * WHAT THIS FILE IS FOR, in one sentence: **a control that is stored and not
 * rendered is a value the author cannot see and cannot change**, and it
 * round-trips through every save until somebody notices. That is why the first
 * test reads `document.py` at run time rather than listing field names here -
 * a hand-written list would agree with a hand-written form and both would be
 * wrong together, which is exactly what section 14's defect 2 was.
 *
 * THE THREE REGIONS ARE ASSERTED BY ABSENCE AS WELL AS PRESENCE. Advanced is a
 * `<details>` that is genuinely closed, and Expert is genuinely NOT IN THE DOM
 * while the switch is off - the difference between "hidden" and "absent"
 * matters because a keyboard walk can tell them apart and a screen reader
 * cannot be told a control exists that does not.
 */

/** Python's triple quote, spelled once so no string literal here carries three. */
const DOCSTRING = '"'.repeat(3)

/** Two roster rows, one of which supports nothing - which is what makes D3 testable. */
const CAPABLE: RegistryModel = {
  id: 'google/gemini-3.8-flash',
  name: 'Google: Gemini 3.8 Flash',
  provider: 'google',
  context_window: 1_048_576,
  supports_tools: true,
  supports_vision: true,
  supports_json_mode: true,
  supports_reasoning: true,
  cost_in: 0.75,
  cost_out: 3.75,
  cost_in_max_endpoint: 1.35,
  speed_tier: 'fast',
  recommended_for: ['synthesis'],
}

const PLAIN: RegistryModel = {
  id: 'google/gemini-3.5-flash-lite',
  name: 'Google: Gemini 3.5 Flash Lite',
  provider: 'google',
  context_window: 1_048_576,
  supports_tools: true,
  supports_vision: false,
  // The two that gate a control. Both false, so one fixture exercises both
  // halves of D3 and the assertions can say which control names which flag.
  supports_json_mode: false,
  supports_reasoning: false,
  cost_in: 0.3,
  cost_out: 2.5,
  cost_in_max_endpoint: 0.54,
  speed_tier: 'fast',
  recommended_for: ['research'],
}

/** A third, cheaper than both presets, so the sort order is observable. */
const CHEAPEST: RegistryModel = {
  ...PLAIN,
  id: 'qwen/qwen3.7-flash',
  name: 'Qwen: Qwen3.7 Flash',
  provider: 'qwen',
  cost_in: 0.03,
  cost_out: 0.12,
  cost_in_max_endpoint: 0.03,
}

/**
 * The authored config off a committed node, narrowed.
 *
 * A helper rather than an inline cast at seven call sites: `BuilderNode` is a
 * union of ten kinds and `AgentConfig` a union of two arms, so reading
 * `.llm.model` off a commit is two narrowings deep. Throwing rather than
 * casting means a commit that produced the WRONG arm fails here with a sentence
 * instead of at `undefined.model` three lines later.
 */
function authoredOf(node: BuilderNode): AuthoredAgentConfig {
  if (node.kind !== 'agent' || !isAuthoredAgent(node.config)) {
    throw new Error(`${node.id} is not an authored agent`)
  }
  return node.config
}

function seedRoster(): void {
  roster.value = {
    schema: 'builder.models/v1',
    generated_at: '2026-09-04T00:00:00Z',
    source: 'test',
    ceiling_usd_per_m_input: 1,
    presets: { cheap: 'google/gemini-3.5-flash-lite:nitro', escalation: 'google/gemini-3.8-flash' },
    // Deliberately NOT in price order, so "sorted by cost_in" is a claim the
    // fixture can falsify rather than one it accidentally satisfies.
    models: [PLAIN, CAPABLE, CHEAPEST],
  }
}

function mountRail(
  node: BuilderNode,
  options: {
    problems?: BuilderProblem[]
    budget?: BuilderBudget | null
    nodes?: BuilderNode[]
    edges?: ReturnType<typeof edge>[]
    selected?: string[]
  } = {},
) {
  const doc = documentFixture(options.nodes ?? [node], options.edges ?? [])
  const commits: InspectorCommit[] = []
  const wrapper = mount(InspectorRail, {
    props: {
      doc,
      vocabulary: vocabularyFixture(),
      selectedNodeIds: options.selected ?? [node.id],
      selectedEdgeIds: [],
      onCommit: (change: InspectorCommit) => commits.push(change),
    },
    global: {
      provide: {
        ...problemsProvide(options.problems ?? []),
        [BUILDER_BUDGET as symbol]: ref(options.budget ?? null),
      },
    },
  })
  return { wrapper, commits, doc }
}

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  resetInspectorTiers()
  resetModels()
  seedRoster()
})

afterEach(() => {
  resetModels()
  vi.restoreAllMocks()
})

describe('every field the schema stores has a control', () => {
  /**
   * The leaf paths `AuthoredAgentConfig` declares, read out of `document.py`.
   *
   * READ, NOT LISTED. The alternative is a constant here that agrees with a
   * constant in `authoredFields.ts`, which is one mistake written twice - and
   * the failure mode is silent, because both sides would be self-consistent
   * while the schema had moved. The parse is deliberately crude and
   * deliberately anchored: it takes the annotated names inside one class body,
   * which is the smallest thing that answers the question.
   */
  function schemaLeaves(className: string, composites: Record<string, string>): string[] {
    const whole = DOCUMENT_PY.split(`class ${className}(`)[1]?.split('\nclass ')[0] ?? ''
    /*
     * THE DOCSTRING HAS TO GO FIRST. `TaskConfig`'s own prose wraps across a
     * line as "a Task is one CrewAI / primitive: `description` and ..." - four
     * spaces, a lower-case word, a colon - which is indistinguishable from a
     * field declaration to any regex worth writing. Dropping the leading
     * triple-quoted block is what tells prose from schema, and getting it
     * wrong made this test demand a control for `task.primitive`.
     */
    const opened = whole.indexOf(DOCSTRING)
    const body =
      opened === -1 ? whole : whole.slice(whole.indexOf(DOCSTRING, opened + 3) + 3)
    const names: string[] = []
    for (const match of body.matchAll(/^ {4}([a-z_]+): /gm)) {
      const name = match[1]
      const composite = composites[name]
      if (composite) {
        for (const leaf of schemaLeaves(composite, {})) names.push(`${name}.${leaf}`)
        continue
      }
      names.push(name)
    }
    return names
  }

  it('renders every AuthoredAgentConfig leaf exactly once, across the three regions', async () => {
    // `planning` on, so `planning_config`'s four are rendered too - they are
    // the only conditional group and leaving them off would let this pass over
    // four controls it never looked for.
    const node = authoredAgentNode('scoper', {
      planning: true,
      planning_config: {
        reasoning_effort: 'medium',
        max_attempts: null,
        max_steps: 20,
        max_replans: 3,
      },
    })
    window.localStorage.setItem(EXPERT_STORAGE_KEY, '1')
    resetInspectorTiers()
    const { wrapper } = mountRail(node)
    // The Advanced disclosure is closed by default; its content is in the DOM
    // behind a `<details>`, which is what a `<details>` is.
    await nextTick()

    const stored = schemaLeaves('AuthoredAgentConfig', {
      task: 'TaskConfig',
      llm: 'LlmConfig',
      retry: 'RetryConfig',
      planning_config: 'PlanningConfig',
    })
    expect(stored.length).toBeGreaterThan(30)

    for (const path of stored) {
      // `credential_id` is the one stored leaf with no control on the AUTHORED
      // form: it is 01's BYO-key picker and it lives on the library arm, where
      // the key a node bills to is the only thing the document says about its
      // model. Stated here rather than skipped silently.
      if (path === 'credential_id') continue
      const rows = wrapper.findAll(`[data-field="${path}"]`)
      expect(rows.length, `${path} should have exactly one control`).toBe(1)
    }
  })

  it('places every rendered control in exactly one region, and nowhere twice', () => {
    const all = [...ESSENTIAL_FIELDS, ...ADVANCED_FIELDS, ...EXPERT_FIELDS]
    expect(new Set(all).size, 'a field is in two regions').toBe(all.length)
    expect(AUTHORED_AGENT_FIELDS).toEqual(all)
  })

  it('renders every AuthoredCrewConfig leaf, verbose included', async () => {
    const node = authoredCrewNode()
    window.localStorage.setItem(EXPERT_STORAGE_KEY, '1')
    resetInspectorTiers()
    const { wrapper } = mountRail(node)
    await nextTick()

    // `verbose` is the fifteenth field, ruled 2026-09-04: the gauntlet's Crew
    // Essentials line names it, `Crew.verbose` is not deprecated, and 04's own
    // fourteen do not include it.
    expect(wrapper.find('[data-field="verbose"]').exists()).toBe(true)
    // The two the crew paragraph never names but `_BillableConfig` stores. A
    // stored field with no control round-trips a value nobody can see.
    expect(wrapper.find('[data-field="max_iter"]').exists()).toBe(true)
    expect(wrapper.find('[data-field="guardrail_max_retries"]').exists()).toBe(true)
  })

  it('renders no control for a field the S9 ruling cut or replaced', async () => {
    window.localStorage.setItem(EXPERT_STORAGE_KEY, '1')
    resetInspectorTiers()
    const { wrapper } = mountRail(authoredAgentNode())
    await nextTick()
    // A control bound to a deprecated field is a control that warns today and
    // breaks at the next major. All four are absent; two of them are absent
    // from the SCHEMA too, which is what makes this checkable at all.
    for (const cut of ['multimodal', 'function_calling_llm', 'reasoning', 'max_reasoning_attempts']) {
      expect(wrapper.find(`[data-field="${cut}"]`).exists(), `${cut} is deprecated`).toBe(false)
      expect(DOCUMENT_PY).not.toContain(`\n    ${cut}: `)
    }
    // `Task.max_retries` is deprecated at 1.15.18 and shares a NAME with the
    // builder's own whole-node retry. The form renders `retry.max_retries` and
    // `guardrail_max_retries`, and never a bare `max_retries`.
    expect(wrapper.find('[data-field="max_retries"]').exists()).toBe(false)
  })
})

describe('three regions, and nothing is ever merely absent', () => {
  it('opens Advanced closed and keeps Expert out of the DOM with the switch off', async () => {
    const { wrapper } = mountRail(authoredAgentNode())
    await nextTick()

    const advanced = wrapper.find('[data-tier="advanced"]')
    expect(advanced.exists()).toBe(true)
    expect((advanced.element as HTMLDetailsElement).open).toBe(false)
    expect(advanced.find('summary').attributes('aria-expanded')).toBe('false')

    // ABSENT, not hidden. `v-if`, so a keyboard walk cannot reach it and a
    // screen reader is never told about a control that is not there.
    expect(wrapper.find('[data-tier="expert"]').exists()).toBe(false)
    for (const path of EXPERT_FIELDS) {
      expect(wrapper.find(`[data-field="${path}"]`).exists(), path).toBe(false)
    }
  })

  it('says how many expert settings are hidden, and the count is what appears', async () => {
    const { wrapper } = mountRail(authoredAgentNode())
    await nextTick()
    const line = wrapper.find('[data-tier="expert-hidden"]')
    expect(line.exists()).toBe(true)
    // Planning is off, so `planning_config`'s four are not among them. A fixed
    // number would be wrong half the time, which is why the component counts.
    expect(line.text()).toContain(`${EXPERT_FIELDS.length - 4} expert settings hidden`)

    await line.find('button').trigger('click')
    await nextTick()
    const revealed = EXPERT_FIELDS.filter(
      (path) => wrapper.find(`[data-field="${path}"]`).exists(),
    )
    expect(revealed.length).toBe(EXPERT_FIELDS.length - 4)
  })

  it('remembers Advanced per node kind, and Expert for the person', async () => {
    const { wrapper } = mountRail(authoredAgentNode())
    await nextTick()
    const details = wrapper.get('[data-tier="advanced"]').element as HTMLDetailsElement
    details.open = true
    await wrapper.get('[data-tier="advanced"]').trigger('toggle')
    // `sessionStorage`, keyed by kind: a statement about the work in front of
    // you, and it dies with the tab.
    expect(window.sessionStorage.getItem('builder-inspector-advanced')).toContain('"agent":true')

    await wrapper.get('[data-tier="expert-hidden"] button').trigger('click')
    // `localStorage`, global: decision 19, a statement about the person.
    expect(window.localStorage.getItem(EXPERT_STORAGE_KEY)).toBe('1')
  })

  it('forces the region open for a problem behind it, and turns the switch on', async () => {
    const hidden = problem({
      code: 'model-lacks-capability',
      message: 'this model does not support reasoning',
      node_id: 'scoper',
      field: 'llm.reasoning_effort',
    })
    const { wrapper } = mountRail(authoredAgentNode(), { problems: [hidden] })
    await nextTick()

    // An error behind a closed disclosure is R15's modal-stack failure in
    // miniature: the document is refused, the form looks clean, and there is
    // nowhere to go.
    expect(wrapper.find('[data-tier="expert"]').exists()).toBe(true)
    expect(wrapper.find('[data-field="llm.reasoning_effort"]').exists()).toBe(true)
    expect(wrapper.find('[data-tier="expert-hidden"]').exists()).toBe(false)
    // The sentence is rendered verbatim under the control it is about.
    expect(wrapper.get('[data-field="llm.reasoning_effort"]').text()).toContain(
      'this model does not support reasoning',
    )
  })

  it('focusField turns the switch on before it looks for an expert control', async () => {
    const { wrapper } = mountRail(authoredAgentNode())
    await nextTick()
    expect(wrapper.find('[data-field="llm.seed"]').exists()).toBe(false)

    const found = await (
      wrapper.vm as unknown as { focusField: (field: string) => Promise<boolean> }
    ).focusField('llm.seed')
    // Without the switch flip this answers false about a control that exists -
    // which reads to the caller as "not on this form".
    expect(found).toBe(true)
    expect(wrapper.find('[data-field="llm.seed"]').exists()).toBe(true)
  })
})

describe('a parameter the model cannot honour is disabled with a reason, never dropped', () => {
  it('disables response_format and reasoning_effort, names the model, and keeps the value', async () => {
    const node = authoredAgentNode('scoper', {
      llm: {
        ...authoredOf(authoredAgentNode()).llm,
        model: PLAIN.id,
        // Both values STORED against a model that supports neither. This is the
        // state D3 exists for: the author switched model and has to be able to
        // see exactly what stopped working.
        response_format: 'json_object',
        reasoning_effort: 'high',
      },
    } as never)
    window.localStorage.setItem(EXPERT_STORAGE_KEY, '1')
    resetInspectorTiers()
    const { wrapper } = mountRail(node)
    await nextTick()

    for (const [field, capability] of [
      ['llm.response_format', 'JSON mode'],
      ['llm.reasoning_effort', 'reasoning'],
    ] as const) {
      const row = wrapper.get(`[data-field="${field}"]`)
      const buttons = row.findAll('button')
      expect(buttons.length).toBeGreaterThan(0)
      for (const button of buttons) {
        expect(button.attributes('disabled'), field).toBeDefined()
        expect(button.attributes('aria-disabled'), field).toBe('true')
      }
      // The tooltip NAMES THE MODEL - "{model} does not support {capability}" -
      // because the author's next action is to change one of the two.
      const tooltip = row.get('.segmented').attributes('title') ?? ''
      expect(tooltip).toContain(PLAIN.id)
      expect(tooltip).toContain(capability)
    }

    // The STORED VALUE is still on screen: `aria-pressed` is true on the option
    // the document carries, so nothing was silently dropped.
    const pressed = wrapper
      .get('[data-field="llm.response_format"]')
      .findAll('button')
      .filter((button) => button.attributes('aria-pressed') === 'true')
    expect(pressed).toHaveLength(1)
    expect(pressed[0].text()).toBe('json')
  })

  it('leaves both enabled on a model that supports them', async () => {
    const node = authoredAgentNode('scoper', {
      llm: { ...authoredOf(authoredAgentNode()).llm, model: CAPABLE.id },
    } as never)
    window.localStorage.setItem(EXPERT_STORAGE_KEY, '1')
    resetInspectorTiers()
    const { wrapper } = mountRail(node)
    await nextTick()
    for (const field of ['llm.response_format', 'llm.reasoning_effort']) {
      const buttons = wrapper.get(`[data-field="${field}"]`).findAll('button')
      expect(buttons.every((button) => button.attributes('disabled') === undefined), field).toBe(
        true,
      )
    }
  })

  it('anchors model-lacks-capability to the control the server named', async () => {
    // The client cannot derive this: the code blames `response_format` on one
    // node and `reasoning_effort` on the next, and `FIELD_CODES` holds one
    // string per code. C8's `field` is what makes it placeable at all.
    const { wrapper } = mountRail(authoredAgentNode(), {
      problems: [
        problem({
          code: 'model-lacks-capability',
          message: 'gemini-3.5-flash-lite does not support JSON mode',
          node_id: 'scoper',
          field: 'llm.response_format',
        }),
      ],
    })
    await nextTick()
    expect(wrapper.get('[data-field="llm.response_format"]').text()).toContain(
      'does not support JSON mode',
    )
    // And it is NOT on the node-level strip, which is where an unanchored
    // problem goes.
    expect(wrapper.find('.rail-problems').exists()).toBe(false)
  })
})

describe('the model picker, and what the card says', () => {
  it('lists exactly the roster, presets pinned, then cheapest first', async () => {
    const { wrapper } = mountRail(authoredAgentNode())
    await nextTick()
    const options = wrapper
      .get('[data-field="llm.model"]')
      .findAll('option')
      .map((option) => option.attributes('value'))

    // Exactly the roster: no invented row, no dropped one.
    expect(new Set(options)).toEqual(new Set([PLAIN.id, CAPABLE.id, CHEAPEST.id]))
    // The two presets first, in the roster's own preset order, then the rest
    // by `cost_in`. The fixture's array order is none of these, so a picker
    // that just rendered `models` would fail here.
    expect(options).toEqual([PLAIN.id, CAPABLE.id, CHEAPEST.id])
  })

  it('moves the card model pill in the same tick the picker writes', () => {
    const before = authoredAgentNode()
    expect(summaryLines(before)[0]).toContain('gemini-3.5-flash-lite')
    const held = authoredOf(before)
    const after = {
      ...before,
      config: { ...held, llm: { ...held.llm, model: CAPABLE.id } },
    } as BuilderNode
    // The card reads the document, so "same tick" is a property of the commit
    // rather than of a watcher - there is nothing in between to be late.
    expect(summaryLines(after)[0]).toContain('gemini-3.8-flash')
    // The provider prefix is dropped: at the card's type size the half that
    // identifies the model is the half after the slash.
    expect(summaryLines(after)[0]).not.toContain('google/')
  })

  it('a tier chip writes the model AND the tier in one commit', async () => {
    const { wrapper, commits } = mountRail(authoredAgentNode())
    await nextTick()
    const chips = wrapper.get('[data-field="llm.model"]').findAll('.preset-chips button')
    expect(chips).toHaveLength(2)
    await chips[1].trigger('click')

    // ONE commit, so one undo - and both fields, because `bounds.py` counts the
    // tier word and `budget.py` prices the model. Writing one without the other
    // admits a graph at one price and runs it at another.
    expect(commits).toHaveLength(1)
    const written = authoredOf(commits[0].next.nodes[0])
    expect(written.llm.model).toBe('google/gemini-3.8-flash')
    expect(written.tier).toBe('escalation')
  })
})

describe('the per-node cost line', () => {
  const budget: BuilderBudget = {
    static_cost_usd: 1.51,
    floor_cost_usd: 1.2,
    modelled_calls: 60,
    billable_nodes: 3,
    escalation_nodes: 1,
    cycles: 0,
    unpriced_models: [],
    over_ceiling: false,
    ceiling_usd: 10,
    per_node: { scoper: { calls: 6, usd: 0.12 } },
  }

  it('renders "this node ≈ $x of $y (static)" from the server breakdown', async () => {
    const { wrapper } = mountRail(authoredAgentNode(), { budget })
    await nextTick()
    const line = wrapper.get('[data-testid="node-cost"]')
    expect(line.text()).toContain('$0.12')
    expect(line.text()).toContain('$1.51')
    expect(line.text()).toContain('6 modelled calls')
  })

  it('says nothing at all when the server serves no breakdown', async () => {
    // Today's state: `per_node` is C5's, owned by plan 09, and not served yet.
    // Computing the figure here instead would be a second estimator quietly
    // disagreeing with the one that enforces the ceiling.
    const { wrapper } = mountRail(authoredAgentNode(), {
      budget: { ...budget, per_node: undefined },
    })
    await nextTick()
    expect(wrapper.find('[data-testid="node-cost"]').exists()).toBe(false)
  })

  it('reprices when the budget ref changes, without the form remounting', async () => {
    const node = authoredAgentNode()
    const live = ref<BuilderBudget | null>(budget)
    const wrapper = mount(InspectorRail, {
      props: {
        doc: documentFixture([node]),
        vocabulary: vocabularyFixture(),
        selectedNodeIds: [node.id],
        selectedEdgeIds: [],
      },
      global: { provide: { ...problemsProvide([]), [BUILDER_BUDGET as symbol]: live } },
    })
    await nextTick()
    expect(wrapper.get('[data-testid="node-cost"]').text()).toContain('$0.12')

    // What the 400 ms validation debounce delivers: a new estimate for the same
    // document, arriving on the ref the form already reads.
    live.value = { ...budget, per_node: { scoper: { calls: 12, usd: 0.31 } } }
    await nextTick()
    expect(wrapper.get('[data-testid="node-cost"]').text()).toContain('$0.31')
  })
})

describe('field-anchored problems', () => {
  it('anchors every code with a fixed field, and names the ones whose field varies', () => {
    /*
     * The partition has to be TOTAL: a code that is neither anchored nor
     * documented as node-level is a message the server wrote and no surface
     * renders, which is worse than no check at all - the author cannot publish
     * and is told nothing.
     *
     * The list below is the node-level half, and each entry is a fact about the
     * graph or about a node as a whole rather than about one control.
     */
    const nodeLevel = new Set([
      // Graph-wide counts: both anchors arrive null.
      'node-count', 'billable-count', 'fanout-width', 'cycle-count',
      'duplicate-node-id', 'duplicate-edge-id',
      'no-input-node', 'input-field-undeclared', 'node-unreachable', 'no-output-node',
      'join-unknown-node', 'join-single-predecessor',
      'budget-over-ceiling', 'budget-unpriced-model',
      'ident-pattern', 'ident-collision',
      // Edge facts, rendered on the edge form rather than on a node control.
      'edge-unknown-endpoint', 'edge-target-refuses-incoming', 'back-edge-not-router',
      'attach-target-not-agent', 'member-target-not-crew', 'member-agent-has-flow-edges',
      'attachment-unattached', 'attachments-over-max', 'attachment-nodes-over-max',
      // A fact about the crew as a whole: no single control is at fault.
      'library-unbuildable-crew',
      'router-branch-unconnected',
      // The four whose field VARIES with the document, and which therefore
      // carry `field` on the payload (C8) instead of an entry in `FIELD_CODES`.
      'model-lacks-capability',
      'tool-param-invalid',
      // 09 D6's two carry `field` - the offending STATE KEY - which varies with
      // the document, so neither can have a `FIELD_CODES` entry either. They
      // are document-level besides: a declared state key belongs to no node.
      'state-key-reserved',
      'state-schema-invalid',
      // A fact about a pair: the attachment node and the edge that hung it on
      // an agent, rendered on the edge form rather than on a control.
      'attachment-reference-missing',
    ])

    for (const code of PROBLEM_CODES) {
      const placed = code in FIELD_CODES
      expect(
        placed || nodeLevel.has(code),
        `${code} is neither anchored to a control nor documented as node-level`,
      ).toBe(true)
    }
  })

  it('prefers the payload field over the code map', async () => {
    // `model-unknown` HAS a `FIELD_CODES` entry - `llm.model`, the commoner of
    // its two sites - and the server can still say `retry.fallback_model`,
    // which is the site nobody exercises before publishing.
    const { wrapper } = mountRail(authoredAgentNode(), {
      problems: [
        problem({
          code: 'model-unknown',
          message: 'that fallback is not a model this build offers',
          node_id: 'scoper',
          field: 'retry.fallback_model',
        }),
      ],
    })
    await nextTick()
    expect(wrapper.get('[data-field="retry.fallback_model"]').text()).toContain(
      'not a model this build offers',
    )
    expect(wrapper.get('[data-field="llm.model"]').text()).not.toContain(
      'not a model this build offers',
    )
  })
})

describe('multi-selection over authored nodes', () => {
  function twoAgents(models: [string, string]) {
    return [
      authoredAgentNode('one', {
        llm: { ...authoredOf(authoredAgentNode()).llm, model: models[0] },
      } as never),
      authoredAgentNode('two', {
        llm: { ...authoredOf(authoredAgentNode()).llm, model: models[1] },
      } as never),
    ]
  }

  it('shows MIXED on llm.model when they differ', async () => {
    const nodes = twoAgents([PLAIN.id, CAPABLE.id])
    const { wrapper } = mountRail(nodes[0], { nodes, selected: ['one', 'two'] })
    await nextTick()
    expect(wrapper.get('[data-field="llm.model"]').text()).toContain('MIXED')
  })

  it('applies one model to both in ONE commit, so it is one undo step', async () => {
    const nodes = twoAgents([PLAIN.id, CAPABLE.id])
    const { wrapper, commits } = mountRail(nodes[0], { nodes, selected: ['one', 'two'] })
    await nextTick()
    const select = wrapper.get('[data-field="llm.model"] select')
    await select.setValue(CHEAPEST.id)

    expect(commits).toHaveLength(1)
    for (const node of commits[0].next.nodes) {
      expect(authoredOf(node).llm.model).toBe(CHEAPEST.id)
    }
    // The other ten `llm` leaves survive: `patchConfig` merges one level, so a
    // patch that did not spread `llm` would drop them and the document would
    // still parse, ten fields lighter.
    expect(Object.keys(authoredOf(commits[0].next.nodes[0]).llm).sort()).toEqual(
      Object.keys(authoredOf(authoredAgentNode()).llm).sort(),
    )
  })

  it('offers nothing authored when the selection mixes a library agent in', async () => {
    const nodes: BuilderNode[] = [authoredAgentNode('one'), agentNode('two')]
    const { wrapper } = mountRail(nodes[0], { nodes, selected: ['one', 'two'] })
    await nextTick()
    // A library agent has no `llm` at all, and `BuilderModel` is
    // `extra="forbid"` - so writing one would be a 422 rather than a dropped
    // key. The three shared count fields are still offered.
    expect(wrapper.find('[data-field="llm.model"]').exists()).toBe(false)
    expect(wrapper.find('[data-field="tier"]').exists()).toBe(true)
  })
})

describe('conversion, attachments and the docked rule', () => {
  it('converts a library agent to an authored one in a single commit', async () => {
    const { wrapper, commits } = mountRail(agentNode('scoper'))
    await nextTick()
    await wrapper.get('[data-field="convert"] button').trigger('click')

    expect(commits).toHaveLength(1)
    const converted = authoredOf(commits[0].next.nodes[0])
    expect(converted.role.length).toBeGreaterThan(0)
    // The library keys are GONE, not left beside the authored ones: `_one_of`
    // refuses a config carrying both arms' discriminants.
    expect('agent_id' in converted).toBe(false)
    expect('tools' in converted).toBe(false)
    // What survives is what both arms have, and the tier is one of them.
    expect(converted.tier).toBe('cheap')
  })

  it('shows attachments read-only, with a jump rather than a dropdown', async () => {
    const nodes: BuilderNode[] = [
      authoredAgentNode('scoper'),
      {
        id: nodeId('search'),
        kind: 'tool',
        label: 'Web search',
        position: { x: 0, y: 0 },
        config: { tool_id: 'web_search', credential_id: null, params: {} },
      } as BuilderNode,
    ]
    const attach: BuilderEdge = { ...edge('e1', 'search', 'scoper', 'out'), target_port: 'attach' }
    const { wrapper } = mountRail(nodes[0], { nodes, edges: [attach] })
    await nextTick()

    const row = wrapper.get('[data-field="attachments"]')
    expect(row.text()).toContain('Web search')
    // NO select: Flowise v2's `agentTools` array is the anti-pattern, and the
    // reason is that a list inside a form cannot show that two agents share one
    // tool while the canvas can.
    expect(row.find('select').exists()).toBe(false)
    await row.get('.attach-jump').trigger('click')
    expect(wrapper.emitted('focusNode')?.[0]).toEqual(['search'])
  })

  it('renders no dialog anywhere in the authored form - R15', async () => {
    window.localStorage.setItem(EXPERT_STORAGE_KEY, '1')
    resetInspectorTiers()
    const { wrapper } = mountRail(
      authoredAgentNode('scoper', {
        planning: true,
        planning_config: {
          reasoning_effort: 'medium',
          max_attempts: null,
          max_steps: 20,
          max_replans: 3,
        },
      }),
    )
    await nextTick()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.find('dialog').exists()).toBe(false)
  })
})
