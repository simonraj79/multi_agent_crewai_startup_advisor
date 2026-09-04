import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AuthoredAgentForm from '../src/components/builder/inspectors/AuthoredAgentForm.vue'
import AuthoredCrewForm from '../src/components/builder/inspectors/AuthoredCrewForm.vue'
import { edgeClassOf } from '../src/composables/useBuilderCanvas'
import { outPortsOf } from '../src/data/nodeKinds'
import type { BuilderDocument, BuilderNode } from '../src/types/builder'
import type { InspectorCommit } from '../src/components/builder/commit'
import {
  authoredAgentNode,
  authoredCrewNode,
  documentFixture,
  edge,
  inputNode,
  outputNode,
  problemsProvide,
  vocabularyFixture,
} from './builderInspectorFixtures'

/**
 * 12 D3 and criterion 7: the error port, the edge that leaves it, and what
 * happens when the switch that grew the port is turned back off.
 *
 * `on_error` is the SECOND config field in the whole vocabulary whose value
 * changes a card's shape - `router.branches` is the first - and it is the only
 * one outside `router`. `nodeKinds.ts::billableOut` answers `['out', 'error']`
 * while it is `'route'` and `['out']` otherwise, so flipping it back takes a
 * port away from a card an author may already have drawn from.
 *
 * That is the same hazard `RouterForm.removeBranch` was written for, and this
 * file asserts the same answer: ONE commit carrying the policy AND the edges,
 * so ONE undo restores both. Two commits would leave an intermediate document
 * the compiler refuses outright - an `edge-unknown-port` error the author never
 * made, on an edge whose port they can no longer see.
 *
 * The edge CLASS is asserted through `edgeClassOf`, which is the one function
 * that decides it. `BuilderEdge.vue` renders `is-class-${edgeClass}` from
 * `data` and computes nothing, deliberately - a second derivation in the
 * renderer would be a third opinion about a string `bounds.py` also has one
 * about.
 */

function routedGraph(policy: 'fail' | 'route' = 'route'): BuilderDocument {
  return documentFixture(
    [
      inputNode(),
      authoredAgentNode('scoper', { on_error: policy }),
      authoredAgentNode('fallback'),
      outputNode(),
    ],
    [
      edge('e1', 'idea', 'scoper'),
      edge('e2', 'scoper', 'result'),
      edge('e3', 'scoper', 'fallback', 'error'),
    ],
  )
}

function mountAgent(doc: BuilderDocument) {
  const node = doc.nodes.find((entry) => entry.id === 'scoper') as Extract<
    BuilderNode,
    { kind: 'agent' }
  >
  return mount(AuthoredAgentForm, {
    props: { doc, node: node as never, vocabulary: vocabularyFixture() },
    global: { provide: problemsProvide() },
  })
}

function lastCommit(wrapper: { emitted: (name: string) => unknown[][] | undefined }): InspectorCommit {
  const emitted = wrapper.emitted('commit')
  expect(emitted, 'nothing was committed').toBeTruthy()
  return emitted![emitted!.length - 1][0] as InspectorCommit
}

async function setPolicy(
  wrapper: ReturnType<typeof mountAgent>,
  policy: 'fail' | 'route',
): Promise<void> {
  const row = wrapper.find('[data-field="on_error"]')
  expect(row.exists(), 'the on_error control is not rendered').toBe(true)
  const button = row
    .findAll('button')
    .find((candidate) => candidate.text().includes(policy === 'fail' ? 'fail' : 'route'))
  expect(button, `no ${policy} option`).toBeTruthy()
  await button!.trigger('click')
}

describe('the error port', () => {
  it('appears only while on_error is route', () => {
    const routed = routedGraph().nodes[1]
    const failing = routedGraph('fail').nodes[1]
    expect(outPortsOf(routed)).toEqual(['out', 'error'])
    expect(outPortsOf(failing)).toEqual(['out'])
  })

  it('is a source port on an authored CREW too, not only on an agent', () => {
    // `on_error` is on `_BillableConfig`, which both arms share, and the canvas
    // draws the same second port for both. A test that only covered the agent
    // would pass over a crew whose port had quietly stopped being computed.
    const crew = authoredCrewNode('team', { on_error: 'route' })
    expect(outPortsOf(crew)).toEqual(['out', 'error'])
  })

  it('gives its edge the error class, and the ordinary edge the flow class', () => {
    const doc = routedGraph()
    const recovery = doc.edges.find((entry) => entry.source_port === 'error')!
    const ordinary = doc.edges.find((entry) => entry.id === 'e2')!
    expect(edgeClassOf(recovery)).toBe('error')
    expect(edgeClassOf(ordinary)).toBe('flow')
  })

  it('is decided by the SOURCE port and not by the target', () => {
    // The one thing that could make this look right and be wrong: an `attach`
    // or `member` edge is classed by its TARGET port, so a rule that read the
    // wrong end would still answer `flow` for an ordinary edge and be
    // undetectable on the happy path.
    expect(edgeClassOf({ source_port: 'error', target_port: 'in' })).toBe('error')
    expect(edgeClassOf({ source_port: 'out', target_port: 'attach' })).toBe('attach')
    expect(edgeClassOf({ source_port: 'out', target_port: 'member' })).toBe('member')
  })
})

describe('turning routing off', () => {
  it('removes the port and its edges in ONE commit', async () => {
    const wrapper = mountAgent(routedGraph())
    await setPolicy(wrapper, 'fail')

    const commit = lastCommit(wrapper)
    const node = commit.next.nodes.find((entry) => entry.id === 'scoper')!
    expect(node.config.on_error).toBe('fail')
    expect(outPortsOf(node)).toEqual(['out'])
    expect(commit.next.edges.map((entry) => entry.id)).toEqual(['e1', 'e2'])
  })

  it('is one undo step, because it is one commit', async () => {
    const wrapper = mountAgent(routedGraph())
    await setPolicy(wrapper, 'fail')
    // The assertion the whole design rests on: the policy and the edges arrive
    // together, so the ring holds one snapshot and one Ctrl+Z restores both.
    expect(wrapper.emitted('commit')).toHaveLength(1)
    expect(lastCommit(wrapper).coalesceKey).toBeUndefined()
  })

  it('says what it took with it, beside the control', async () => {
    const wrapper = mountAgent(routedGraph())
    await setPolicy(wrapper, 'fail')
    const notice = wrapper.find('.branch-notice')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('fallback')
    expect(notice.text()).toContain('One undo')
  })

  it('says nothing when there was nothing on the port', async () => {
    const doc = documentFixture(
      [inputNode(), authoredAgentNode('scoper', { on_error: 'route' }), outputNode()],
      [edge('e1', 'idea', 'scoper'), edge('e2', 'scoper', 'result')],
    )
    const wrapper = mountAgent(doc)
    await setPolicy(wrapper, 'fail')
    expect(wrapper.find('.branch-notice').exists()).toBe(false)
    expect(lastCommit(wrapper).next.edges).toHaveLength(2)
  })

  it('leaves every other edge alone, including one arriving AT the node', async () => {
    const doc = routedGraph()
    const wrapper = mountAgent(doc)
    await setPolicy(wrapper, 'fail')
    const kept = lastCommit(wrapper).next.edges
    expect(kept.find((entry) => entry.id === 'e1')).toBeTruthy()
    expect(kept.find((entry) => entry.id === 'e2')).toBeTruthy()
  })

  it('does not touch an error edge leaving a DIFFERENT node', async () => {
    const doc = documentFixture(
      [
        inputNode(),
        authoredAgentNode('scoper', { on_error: 'route' }),
        authoredAgentNode('second', { on_error: 'route' }),
        outputNode(),
      ],
      [
        edge('e1', 'idea', 'scoper'),
        edge('e2', 'scoper', 'result'),
        edge('e3', 'scoper', 'second', 'error'),
        edge('e4', 'second', 'result', 'error'),
      ],
    )
    const wrapper = mountAgent(doc)
    await setPolicy(wrapper, 'fail')
    const kept = lastCommit(wrapper).next.edges.map((entry) => entry.id)
    expect(kept).toContain('e4')
    expect(kept).not.toContain('e3')
  })
})

describe('turning routing on', () => {
  it('grows the port and rewrites no edges', async () => {
    const doc = documentFixture(
      [inputNode(), authoredAgentNode('scoper'), outputNode()],
      [edge('e1', 'idea', 'scoper'), edge('e2', 'scoper', 'result')],
    )
    const wrapper = mountAgent(doc)
    await setPolicy(wrapper, 'route')

    const commit = lastCommit(wrapper)
    const node = commit.next.nodes.find((entry) => entry.id === 'scoper')!
    expect(outPortsOf(node)).toEqual(['out', 'error'])
    expect(commit.next.edges).toEqual(doc.edges)
    expect(wrapper.find('.branch-notice').exists()).toBe(false)
  })
})

describe('the crew arm does the same thing', () => {
  it('drops its own error edges in one commit', async () => {
    const doc = documentFixture(
      [
        inputNode(),
        authoredCrewNode('team', { on_error: 'route' }),
        authoredAgentNode('fallback'),
        outputNode(),
      ],
      [
        edge('e1', 'idea', 'team'),
        edge('e2', 'team', 'result'),
        edge('e3', 'team', 'fallback', 'error'),
      ],
    )
    const node = doc.nodes[1] as Extract<BuilderNode, { kind: 'crew' }>
    const wrapper = mount(AuthoredCrewForm, {
      props: { doc, node: node as never, vocabulary: vocabularyFixture() },
      global: { provide: problemsProvide() },
    })
    const row = wrapper.find('[data-field="on_error"]')
    const button = row.findAll('button').find((candidate) => candidate.text().includes('fail'))
    await button!.trigger('click')

    const commit = lastCommit(wrapper)
    expect(commit.next.edges.map((entry) => entry.id)).toEqual(['e1', 'e2'])
    expect(wrapper.emitted('commit')).toHaveLength(1)
  })
})
