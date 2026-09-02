import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import InspectorRail from '../src/components/builder/InspectorRail.vue'
import { NODE_KIND_ORDER } from '../src/data/nodeKinds'
import type { BuilderDocument, BuilderNode, NodeKind } from '../src/types/builder'
import type { InspectorCommit } from '../src/components/builder/commit'
import {
  DOCUMENT_PY,
  agentNode,
  crewNode,
  documentFixture,
  edge,
  gateNode,
  inputNode,
  outputNode,
  problem,
  problemsProvide,
  routerNode,
  transformNode,
  vocabularyFixture,
} from './builderInspectorFixtures'

/**
 * The inspector is DOCKED, dispatches totally over kind, and never drops a
 * problem.
 *
 * Three gaps, and all three are things a form surface fails at silently.
 *
 * ONE. ChatDev's `FormGenerator.vue` renders a `modalStack` - overlays opened
 * from inside overlays - so configuring a node means covering the graph you are
 * configuring it inside of. R15 makes zero modals a rule, and the only way to
 * keep a rule like that is to assert it: nothing this rail renders is a dialog.
 *
 * TWO. Dispatch is `Record<NodeKind, Component>`, so a kind with no form is a
 * COMPILE error. That is checked here by mounting all seven and asserting each
 * one produced the form that belongs to it - which is stronger than reading the
 * record's keys, because it also catches a record that is total and WRONG.
 *
 * THREE. A problem whose `FIELD_CODES` control this form does not render must
 * land on the node-level strip, not vanish. The real case is
 * `library-unknown-id`, which maps to `agent_id` and which `compiler.py` raises
 * for a CREW's unregistered `crew_id` too - where no such control exists.
 */

/** A control that only the right form renders, per kind. */
const SIGNATURE: Record<NodeKind, string> = {
  input: '[data-field="max_chars"]',
  agent: '[data-field="agent_id"]',
  crew: '[data-field="crew_id"]',
  gate: '[data-field="max_turns"]',
  router: '[data-field="branches"]',
  transform: '[data-field="op"]',
  output: '[data-field="body_key"]',
}

function nodeOfKind(kind: NodeKind): BuilderNode {
  switch (kind) {
    case 'input':
      return inputNode()
    case 'agent':
      return agentNode()
    case 'crew':
      return crewNode()
    case 'gate':
      return gateNode()
    case 'router':
      return routerNode()
    case 'transform':
      return transformNode()
    case 'output':
      return outputNode()
  }
}

function graph(): BuilderDocument {
  return documentFixture(
    [inputNode(), agentNode(), gateNode(), outputNode()],
    [edge('e1', 'idea', 'scoper'), edge('e2', 'scoper', 'confirm'), edge('e3', 'confirm', 'result', 'approve')],
  )
}

function mountRail(
  overrides: {
    doc?: BuilderDocument
    nodes?: string[]
    edges?: string[]
    vocabulary?: ReturnType<typeof vocabularyFixture> | null
    problems?: Parameters<typeof problemsProvide>[0]
    vocabularyProblem?: string
  } = {},
) {
  const doc = overrides.doc ?? graph()
  return mount(InspectorRail, {
    props: {
      doc,
      vocabulary: overrides.vocabulary === undefined ? vocabularyFixture() : overrides.vocabulary,
      vocabularyProblem: overrides.vocabularyProblem ?? '',
      selectedNodeIds: overrides.nodes ?? [],
      selectedEdgeIds: overrides.edges ?? [],
    },
    global: { provide: problemsProvide(overrides.problems ?? []) },
  })
}

function lastCommit(wrapper: ReturnType<typeof mountRail>): InspectorCommit {
  const emitted = wrapper.emitted('commit')
  expect(emitted, 'nothing was committed').toBeTruthy()
  return (emitted as unknown[][])[emitted!.length - 1][0] as InspectorCommit
}

describe('the inspector is docked and dispatches over every kind', () => {
  it('renders as an aside, and nothing in it is a dialog', () => {
    const wrapper = mountRail()
    expect(wrapper.element.tagName).toBe('ASIDE')
    expect(wrapper.attributes('aria-label')).toBe('Inspector')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.find('.modal-overlay').exists()).toBe(false)
  })

  it('has a form for each of the seven kinds, and the RIGHT one', () => {
    for (const kind of NODE_KIND_ORDER) {
      const node = nodeOfKind(kind)
      const doc = documentFixture([node], [], { input_field: inputNode().config.field })
      const wrapper = mountRail({ doc, nodes: [node.id] })
      expect(wrapper.find(SIGNATURE[kind]).exists(), `${kind} rendered the wrong form`).toBe(true)
    }
  })

  it('covers exactly the kinds the vocabulary offers', () => {
    // The type-level half is `Record<NodeKind, Component>` in the rail itself,
    // where a missing key does not compile. This is the runtime half: the set
    // this build can DRAW equals the set the server offers.
    expect([...NODE_KIND_ORDER].sort()).toEqual([...vocabularyFixture().node_kinds].sort())
  })

  it('sends an agent and a crew to one form, because they extend one config', () => {
    const doc = documentFixture([agentNode(), crewNode()])
    const asAgent = mountRail({ doc, nodes: ['scoper'] })
    const asCrew = mountRail({ doc, nodes: ['market'] })

    for (const field of ['tier', 'max_iter', 'guardrail_max_retries', 'prompt_inputs']) {
      expect(asAgent.find(`[data-field="${field}"]`).exists()).toBe(true)
      expect(asCrew.find(`[data-field="${field}"]`).exists()).toBe(true)
    }
  })

  it('shows graph settings rather than blank space when nothing is selected', () => {
    const wrapper = mountRail()
    expect(wrapper.find('[data-field="input_field"]').exists()).toBe(true)
    expect(wrapper.find('[data-field="joins"]').exists()).toBe(true)
  })

  it('states the reason instead of offering a made-up vocabulary', () => {
    const wrapper = mountRail({
      vocabulary: null,
      vocabularyProblem: 'The builder vocabulary could not be loaded: the API answered 503.',
      nodes: ['scoper'],
    })
    const alert = wrapper.get('[role="alert"]')
    expect(alert.text()).toContain('the API answered 503')
    expect(wrapper.find('[data-field="agent_id"]').exists()).toBe(false)
  })
})

describe('a crew is offered only the crews this build can construct', () => {
  it('offers exactly what the vocabulary served, with no local skip-list', () => {
    const wrapper = mountRail({ doc: documentFixture([crewNode()]), nodes: ['market'] })
    const offered = wrapper
      .findAll('[data-field="crew_id"] option')
      .map((option) => option.text())

    expect(offered).toEqual(vocabularyFixture().crew_ids)
    // `_vocabulary()` serves `sorted(BUILDABLE_BUILDER_CREW_IDS)`, so the two
    // crews whose `__init__` takes typed findings never reach a picker at all.
    expect(offered).not.toContain('synthesis')
    expect(offered).not.toContain('report')
  })

  it('keeps an unbuildable id a stored document already names, and marks it', () => {
    const doc = documentFixture([crewNode('synth', 'synthesis')])
    const wrapper = mountRail({ doc, nodes: ['synth'] })
    const row = wrapper.get('[data-field="crew_id"]')

    // Dropping it would silently rewrite the author's document to the first
    // legal option the moment they touched anything else.
    expect(row.findAll('option').map((option) => option.text())).toContain('synthesis')
    expect(row.get('.field-note').text()).toBe('not in this build')
  })

  it('renders no tools control at all, because the key is a 422', () => {
    const wrapper = mountRail({ doc: documentFixture([crewNode()]), nodes: ['market'] })
    expect(wrapper.find('[data-field="tools"]').exists()).toBe(false)
    // The agent form does render one, and not behind a disclosure.
    const agent = mountRail({ doc: documentFixture([agentNode()]), nodes: ['scoper'] })
    expect(agent.find('[data-field="tools"] input[type="checkbox"]').exists()).toBe(true)
  })

  it('says which two settings the runtime ignores rather than hiding them', () => {
    const wrapper = mountRail({ doc: documentFixture([crewNode()]), nodes: ['market'] })
    expect(wrapper.get('[data-field="max_iter"]').text()).toContain('ignored at run time')
    expect(wrapper.get('[data-field="guardrail_max_retries"]').text()).toContain(
      'priced and counted on',
    )
  })

  it('counts escalation nodes against the served bound without disabling anything', async () => {
    const doc = documentFixture([
      agentNode('a1', { tier: 'escalation' }),
      agentNode('a2', { tier: 'escalation' }),
    ])
    const wrapper = mountRail({ doc, nodes: ['a1'] })
    expect(wrapper.get('[data-field="tier"] .field-note').text()).toBe('2 of 5 used')

    for (const button of wrapper.findAll('[data-field="tier"] .segmented button')) {
      expect(button.attributes('disabled')).toBeUndefined()
    }
  })
})

describe('the gate form ships no expiry control, and does not lose the value', () => {
  it('renders no expiry_seconds anywhere (R8)', () => {
    const wrapper = mountRail({ doc: documentFixture([gateNode()]), nodes: ['confirm'] })
    expect(wrapper.find('[data-field="expiry_seconds"]').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('expiry')
  })

  it('round-trips the stored value through a commit made on another field', async () => {
    const doc = documentFixture([
      { ...gateNode(), config: { ...gateNode().config, expiry_seconds: 900 } },
    ])
    const wrapper = mountRail({ doc, nodes: ['confirm'] })
    await wrapper.get('[data-field="max_turns"] input').setValue('2')

    const gate = lastCommit(wrapper).next.nodes[0]
    if (gate.kind !== 'gate') throw new Error('the gate moved')
    expect(gate.config.max_turns).toBe(2)
    expect(gate.config.expiry_seconds).toBe(900)
  })

  it('does not clamp max_turns, because the ceiling is a problem and not a 422', async () => {
    const wrapper = mountRail({ doc: documentFixture([gateNode()]), nodes: ['confirm'] })
    await wrapper.get('[data-field="max_turns"] input').setValue('9')

    const gate = lastCommit(wrapper).next.nodes[0]
    if (gate.kind !== 'gate') throw new Error('the gate moved')
    expect(gate.config.max_turns).toBe(9)
  })

  it('refuses a duplicate editable field in the compiler’s own words', async () => {
    const message = 'the same editable field is named twice; list each field once'
    expect(DOCUMENT_PY).toContain(message)

    const doc = documentFixture([
      { ...gateNode(), config: { ...gateNode().config, editable_fields: [inputNode().config.field] } },
    ])
    const wrapper = mountRail({ doc, nodes: ['confirm'] })
    await wrapper.get('[data-field="editable_fields"] input').setValue('idea')

    expect(wrapper.get('[data-field="editable_fields"] .field-hint').text()).toBe(message)
    expect(wrapper.emitted('commit')).toBeUndefined()
  })
})

describe('renaming a node states what it moves before it moves it', () => {
  function renameable(): BuilderDocument {
    return documentFixture(
      [
        inputNode(),
        agentNode('scoper', { prompt_inputs: { brief: '${state.idea}' } }),
        { ...outputNode(), config: { body_key: 'markdown_body', source: '${state.out__scoper}' } },
      ],
      [edge('e1', 'idea', 'scoper'), edge('e2', 'scoper', 'result')],
    )
  }

  it('counts the edges, the joins and the state references, not just the edges', async () => {
    const wrapper = mountRail({ doc: renameable(), nodes: ['scoper'] })
    await wrapper.get('[data-field="id"] input').setValue('scope_step')

    // Two edges name it, and the output node's `source` reads `out__scoper`.
    expect(wrapper.get('[data-field="id"] .field-help').text()).toBe(
      'This rename updates 3 references elsewhere in the graph.',
    )
    expect(wrapper.emitted('commit')).toBeUndefined()
  })

  it('cascades all of them in ONE commit', async () => {
    const wrapper = mountRail({ doc: renameable(), nodes: ['scoper'] })
    const field = wrapper.get('[data-field="id"] input')
    await field.setValue('scope_step')
    await field.trigger('keydown.enter')

    expect(wrapper.emitted('commit')).toHaveLength(1)
    const next = lastCommit(wrapper).next
    expect(next.nodes.map((node) => node.id)).toEqual(['idea', 'scope_step', 'result'])
    expect(next.edges.map((entry) => [entry.source, entry.target])).toEqual([
      ['idea', 'scope_step'],
      ['scope_step', 'result'],
    ])
    const output = next.nodes[2]
    if (output.kind !== 'output') throw new Error('the output moved')
    expect(output.config.source).toBe('${state.out__scope_step}')
  })

  it('refuses an identifier another node already holds', async () => {
    const wrapper = mountRail({ doc: renameable(), nodes: ['scoper'] })
    const field = wrapper.get('[data-field="id"] input')
    await field.setValue('idea')
    await field.trigger('keydown.enter')

    expect(wrapper.get('[data-field="id"] .field-hint').text()).toBe(
      'Another node is already called idea.',
    )
    expect(wrapper.emitted('commit')).toBeUndefined()
  })

  it('refuses a shape the compiler parses rather than reports', async () => {
    const wrapper = mountRail({ doc: renameable(), nodes: ['scoper'] })
    await wrapper.get('[data-field="id"] input').setValue('Scope Step')

    expect(wrapper.get('[data-field="id"] .field-hint').text()).toContain(
      'Start with a lowercase letter',
    )
  })
})

describe('a transform’s arguments are checked in both directions', () => {
  function formatDoc(args: Record<string, string>): BuilderDocument {
    return documentFixture([{ ...transformNode('shape', 'format'), config: { op: 'format', args } }])
  }

  it('flags a placeholder with no argument', () => {
    const wrapper = mountRail({
      doc: formatDoc({ template: 'Hello {name} and {other}', name: 'x' }),
      nodes: ['shape'],
    })
    expect(wrapper.get('[data-field="args"] .field-hint').text()).toContain(
      '{other} has no argument',
    )
  })

  it('flags an argument with no placeholder', () => {
    const wrapper = mountRail({
      doc: formatDoc({ template: 'Hello {name}', name: 'x', spare: 'y' }),
      nodes: ['shape'],
    })
    expect(wrapper.get('[data-field="args"] .field-hint').text()).toContain(
      'spare is never referenced by the template',
    )
  })

  it('says nothing when the two agree', () => {
    const wrapper = mountRail({
      doc: formatDoc({ template: 'Hello {name}', name: 'x' }),
      nodes: ['shape'],
    })
    expect(wrapper.find('[data-field="args"] .field-hint').exists()).toBe(false)
  })

  it('does not treat {template} as a placeholder, because _format skips it', () => {
    const wrapper = mountRail({
      doc: formatDoc({ template: 'Literally {template}' }),
      nodes: ['shape'],
    })
    expect(wrapper.find('[data-field="args"] .field-hint').exists()).toBe(false)
  })

  it('changes shape per op, because the runtime reads different keys', () => {
    const pick = mountRail({ doc: documentFixture([transformNode('shape', 'pick')]), nodes: ['shape'] })
    expect(pick.find('[data-field="args.source"]').exists()).toBe(true)
    expect(pick.find('[data-field="args.key"]').exists()).toBe(true)
    expect(pick.find('[data-field="args"]').exists()).toBe(false)

    const join = mountRail({
      doc: documentFixture([transformNode('shape', 'join_text')]),
      nodes: ['shape'],
    })
    expect(join.find('[data-field="args.separator"]').exists()).toBe(true)
    expect(join.get('[data-field="args"]').text()).toContain('joins these VALUES')
  })

  it('says that only null and the empty string count as absent for `default`', () => {
    const wrapper = mountRail({
      doc: documentFixture([transformNode('shape', 'default')]),
      nodes: ['shape'],
    })
    expect(wrapper.get('[data-field="args.default"]').text()).toContain(
      'a legitimate 0 or false survives',
    )
  })
})

describe('no problem is ever dropped on the way to the rail', () => {
  it('pins a problem whose control this form does not render', () => {
    const wrapper = mountRail({
      doc: documentFixture([crewNode('synth', 'synthesis')]),
      nodes: ['synth'],
      // `library-unknown-id` maps to `agent_id`, which a crew form has not got.
      problems: [
        problem({ code: 'library-unknown-id', message: 'synth names the crew "synthesis"', node_id: 'synth' }),
      ],
    })
    expect(wrapper.get('.rail-problems').text()).toContain('synth names the crew "synthesis"')
  })

  it('leaves a problem that DOES have a control to the control', () => {
    const wrapper = mountRail({
      doc: documentFixture([agentNode()]),
      nodes: ['scoper'],
      problems: [
        problem({
          code: 'library-missing-prompt-input',
          message: 'scoper runs "scoper", whose task needs idea and this node does not supply it',
          node_id: 'scoper',
        }),
      ],
    })
    expect(wrapper.find('.rail-problems').exists()).toBe(false)
    expect(wrapper.get('[data-field="prompt_inputs"]').text()).toContain('does not supply it')
  })

  it('shows an edge’s problems when the edge is selected', () => {
    const wrapper = mountRail({
      edges: ['e3'],
      problems: [
        problem({
          code: 'edge-unknown-port',
          message: 'edge e3 leaves confirm by "approve", which is not one of its ports',
          node_id: 'confirm',
          edge_id: 'e3',
        }),
      ],
    })
    expect(wrapper.get('.rail-problems').text()).toContain('which is not one of its ports')
  })
})

describe('the edge form moves an endpoint without breaking the port', () => {
  it('offers only sources that have an out-port and targets that accept one', () => {
    const wrapper = mountRail({ edges: ['e1'] })
    const sources = wrapper.findAll('[data-field="source"] option').map((option) => option.text())
    const targets = wrapper.findAll('[data-field="target"] option').map((option) => option.text())

    // `output` has an empty out-port tuple; `input` refuses everything inbound.
    expect(sources.some((text) => text.includes('(result)'))).toBe(false)
    expect(targets.some((text) => text.includes('(idea)'))).toBe(false)
  })

  it('states that `in` is the only inbound port rather than offering a choice', () => {
    const wrapper = mountRail({ edges: ['e1'] })
    expect(wrapper.get('[data-field="target_port"] .readout').text()).toBe('in')
    expect(wrapper.find('[data-field="target_port"] select').exists()).toBe(false)
  })

  it('carries the port across a source change, or falls to the new source’s first', async () => {
    const wrapper = mountRail({ edges: ['e3'] })
    await wrapper.get('[data-field="source"] select').setValue('scoper')

    const moved = lastCommit(wrapper).next.edges.find((entry) => entry.id === 'e3')
    expect(moved?.source).toBe('scoper')
    // `approve` is a gate port; an agent has only `out`.
    expect(moved?.source_port).toBe('out')
  })

  it('keeps a stored port the source does not declare visible rather than swapping it', () => {
    const doc = graph()
    const wrapper = mountRail({
      doc: { ...doc, edges: doc.edges.map((entry) => (entry.id === 'e1' ? { ...entry, source_port: 'ghost' } : entry)) },
      edges: ['e1'],
    })
    expect(wrapper.get('[data-field="source_port"]').text()).toContain('not a port of idea')
  })

  it('offers the fan-in toggle only where two edges actually arrive', () => {
    const single = mountRail({ edges: ['e1'] })
    expect(single.find('[data-field="joins"]').exists()).toBe(false)

    const doc = graph()
    const wrapper = mountRail({
      doc: { ...doc, edges: [...doc.edges, edge('e4', 'idea', 'confirm')] },
      edges: ['e2'],
    })
    expect(wrapper.get('[data-field="joins"] .field-note').text()).toBe('2 inbound')
  })
})

describe('a multi-selection edits what its members share, once', () => {
  function twoAgents(): BuilderDocument {
    return documentFixture([
      agentNode('a1', { tier: 'cheap', max_iter: 2 }),
      agentNode('a2', { tier: 'escalation', max_iter: 4 }),
      gateNode(),
    ])
  }

  it('says MIXED where they disagree', () => {
    const wrapper = mountRail({ doc: twoAgents(), nodes: ['a1', 'a2'] })
    expect(wrapper.get('[data-field="tier"] .field-note').text()).toBe('MIXED')
    expect(wrapper.get('[data-field="max_iter"] .field-note').text()).toBe('MIXED')
  })

  it('applies one commit to every billable node, and leaves the rest alone', async () => {
    const wrapper = mountRail({ doc: twoAgents(), nodes: ['a1', 'a2', 'confirm'] })
    await wrapper.findAll('[data-field="tier"] .segmented button')[0].trigger('click')

    expect(wrapper.emitted('commit')).toHaveLength(1)
    const next = lastCommit(wrapper).next
    expect(next.nodes.map((node) => (node.kind === 'agent' ? node.config.tier : node.kind))).toEqual(
      ['cheap', 'cheap', 'gate'],
    )
  })

  it('says so rather than going blank when nothing is shared', () => {
    const doc = documentFixture([gateNode(), outputNode()])
    const wrapper = mountRail({ doc, nodes: ['confirm', 'result'] })
    expect(wrapper.get('.rail-empty').text()).toContain('Nothing in this selection shares a setting')
  })
})

describe('the run input is fixed from the node it is about', () => {
  it('offers the one-click repair when this node is not the run input', async () => {
    const doc = documentFixture([inputNode('second', 'topic'), inputNode()], [], {
      input_field: inputNode().config.field,
    })
    const wrapper = mountRail({ doc, nodes: ['second'] })
    expect(wrapper.get('.run-input').text()).toContain('not this node')

    await wrapper.get('.run-input-action').trigger('click')
    expect(lastCommit(wrapper).next.input_field).toBe('topic')
  })

  it('states the fact instead when it already is', () => {
    const wrapper = mountRail({ nodes: ['idea'] })
    expect(wrapper.get('.run-input').classes()).toContain('is-current')
    expect(wrapper.find('.run-input-action').exists()).toBe(false)
  })

  it('picks the run input from declared fields only, never free text', () => {
    const wrapper = mountRail()
    const row = wrapper.get('[data-field="input_field"]')
    expect(row.find('select').exists()).toBe(true)
    expect(row.find('input').exists()).toBe(false)
    expect(row.findAll('option').map((option) => option.text())).toEqual(['idea'])
  })
})

describe('landing on a control is a real focus, not a scroll', () => {
  it('focuses the control the panel names and flashes its row', async () => {
    const wrapper = mountRail({ doc: documentFixture([gateNode()]), nodes: ['confirm'] })
    document.body.appendChild(wrapper.element)

    const landed = await (
      wrapper.vm as unknown as { focusField: (field: string) => Promise<boolean> }
    ).focusField('max_turns')

    expect(landed).toBe(true)
    expect(wrapper.get('[data-field="max_turns"]').classes()).toContain('problem-anchor')
    expect(document.activeElement).toBe(wrapper.get('[data-field="max_turns"] input').element)
  })

  it('reports a miss rather than pretending, when the form has no such control', async () => {
    const wrapper = mountRail({ doc: documentFixture([gateNode()]), nodes: ['confirm'] })
    const landed = await (
      wrapper.vm as unknown as { focusField: (field: string) => Promise<boolean> }
    ).focusField('agent_id')
    expect(landed).toBe(false)
  })
})
