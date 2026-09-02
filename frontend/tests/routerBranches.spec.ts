import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RouterForm from '../src/components/builder/inspectors/RouterForm.vue'
import { outPortsOf } from '../src/data/nodeKinds'
import { nodeId } from '../src/types/builder'
import type { BuilderDocument, BuilderNode } from '../src/types/builder'
import type { InspectorCommit } from '../src/components/builder/commit'
import {
  DOCUMENT_PY,
  agentNode,
  documentFixture,
  edge,
  inputNode,
  outputNode,
  problemsProvide,
  routerNode,
  vocabularyFixture,
} from './builderInspectorFixtures'

/**
 * A router's branches are its PORTS, so editing one is a graph edit.
 *
 * That is the fact this whole file is about, and it is what separates this
 * editor from one where branches are a list of strings in a modal.
 * `_OUT_PORTS_BY_KIND` computes a router's out-ports from its branch labels, so
 * every edge leaving it names a branch by name - and three of the four
 * operations below would silently break those edges if they touched only the
 * config:
 *
 *   - deleting a branch leaves its edge naming a port that no longer exists;
 *   - renaming one leaves every edge on it naming the old name;
 *   - both are `edge-unknown-port`, an error the author did not make.
 *
 * So each is asserted here as ONE commit carrying both halves, because one
 * commit is what makes one undo restore both - and two commits would leave an
 * intermediate document that the compiler refuses outright.
 *
 * The cross-field rules are asserted against `document.py` rather than against
 * this file's idea of them: `RouterBranch._validate_shape` refuses a key or a
 * value on `otherwise` and refuses a missing key on everything else, and both
 * are 422s, so both must be impossible to produce here.
 */

function routerGraph(): BuilderDocument {
  return documentFixture(
    [inputNode(), agentNode(), routerNode(), outputNode()],
    [
      edge('e1', 'idea', 'scoper'),
      edge('e2', 'scoper', 'route'),
      edge('e3', 'route', 'result', 'match'),
      edge('e4', 'route', 'scoper', 'otherwise'),
    ],
  )
}

function mountRouter(doc: BuilderDocument = routerGraph()) {
  const node = doc.nodes.find((entry) => entry.kind === 'router') as Extract<
    BuilderNode,
    { kind: 'router' }
  >
  return mount(RouterForm, {
    props: { doc, node, vocabulary: vocabularyFixture() },
    global: { provide: problemsProvide() },
  })
}

function lastCommit(wrapper: ReturnType<typeof mountRouter>): InspectorCommit {
  const emitted = wrapper.emitted('commit')
  expect(emitted, 'nothing was committed').toBeTruthy()
  return (emitted as unknown[][])[emitted!.length - 1][0] as InspectorCommit
}

/** The same graph with `otherwise` not yet taken by anything. */
function withTwoComparisons(): BuilderDocument {
  const doc = routerGraph()
  const router = doc.nodes[2]
  if (router.kind !== 'router') throw new Error('the router moved in the fixture')
  const swapped = {
    ...router,
    config: {
      branches: [
        router.config.branches[0],
        { label: nodeId('second'), op: 'ne' as const, key: nodeId('decision'), value: 'no' },
      ],
    },
  }
  return { ...doc, nodes: [doc.nodes[0], doc.nodes[1], swapped, doc.nodes[3]] }
}

function branchesOf(doc: BuilderDocument) {
  const router = doc.nodes.find((entry) => entry.kind === 'router')
  return router?.kind === 'router' ? router.config.branches : []
}

describe('the otherwise branch cannot carry a key or a value', () => {
  it('refuses both in the schema, which is what makes this the widget’s job', () => {
    expect(DOCUMENT_PY).toContain(
      'the otherwise branch takes no key and no value: it is what happens',
    )
  })

  it('clears key and value in the same commit that sets the op', async () => {
    // A router where NOBODY holds `otherwise` yet - because once one branch
    // does, the option is not in any other select at all, which is the
    // structural rule the next block asserts.
    const wrapper = mountRouter(withTwoComparisons())
    await wrapper.findAll('select')[0].setValue('otherwise')

    const branch = branchesOf(lastCommit(wrapper).next)[0]
    expect(branch.op).toBe('otherwise')
    expect(branch.key).toBeNull()
    expect(branch.value).toBeNull()
  })

  it('disables the key and value controls on the branch that holds it', () => {
    const wrapper = mountRouter()
    // Branch 1 in the fixture is already `otherwise`.
    const rows = wrapper.findAll('.branch')
    const key = rows[1].get('[data-field="key"] input')
    expect(key.attributes('disabled')).toBeDefined()
    expect(rows[1].get('[data-field="value"] .scalar-null').attributes('aria-disabled')).toBe('true')
    for (const button of rows[1].findAll('[data-field="value"] .scalar-types button')) {
      expect(button.attributes('disabled')).toBeDefined()
    }
  })

  it('leaves the comparison branch’s controls alone', () => {
    const rows = mountRouter().findAll('.branch')
    expect(rows[0].get('[data-field="key"] input').attributes('disabled')).toBeUndefined()
  })

  it('says what otherwise is for, instead of leaving an inert box unexplained', () => {
    const rows = mountRouter().findAll('.branch')
    expect(rows[1].get('[data-field="key"]').text()).toContain(
      'what happens when every declared comparison missed',
    )
  })
})

describe('exactly one otherwise, enforced structurally', () => {
  it('drops the option from every other branch once it is taken', () => {
    const wrapper = mountRouter()
    const selects = wrapper.findAll('select')
    const comparison = selects[0].findAll('option').map((option) => option.text())
    const fallback = selects[1].findAll('option').map((option) => option.text())

    expect(comparison).not.toContain('otherwise')
    expect(fallback).toContain('otherwise')
  })

  it('offers it again when no branch holds it', () => {
    const wrapper = mountRouter(withTwoComparisons())

    for (const select of wrapper.findAll('select')) {
      expect(select.findAll('option').map((option) => option.text())).toContain('otherwise')
    }
  })
})

describe('a comparison with nothing to compare marks its own row', () => {
  it('refuses a null key in the schema, so the row has to say so first', () => {
    expect(DOCUMENT_PY).toContain('branch must name the state key it compares')
  })

  it('names the op in the row when the key is empty', () => {
    const doc = routerGraph()
    const router = doc.nodes[2]
    if (router.kind !== 'router') throw new Error('fixture moved')
    const broken = {
      ...router,
      config: {
        branches: [
          { ...router.config.branches[0], key: null },
          router.config.branches[1],
        ],
      },
    }
    const wrapper = mountRouter({ ...doc, nodes: [doc.nodes[0], doc.nodes[1], broken, doc.nodes[3]] })

    expect(wrapper.findAll('.branch')[0].get('.branch-hint').text()).toBe(
      'the eq branch must name the state key it compares',
    )
  })
})

describe('deleting a branch takes its edge with it, in one commit', () => {
  it('removes the branch and the edge together', async () => {
    const wrapper = mountRouter()
    await wrapper.findAll('.branch')[0].get('.branch-action.is-remove').trigger('click')

    const commits = wrapper.emitted('commit') ?? []
    expect(commits).toHaveLength(1)

    const next = lastCommit(wrapper).next
    expect(branchesOf(next).map((branch) => branch.label)).toEqual(['otherwise'])
    expect(next.edges.map((entry) => entry.id)).toEqual(['e1', 'e2', 'e4'])
  })

  it('names the edge it took, beside the list rather than over the graph', async () => {
    const wrapper = mountRouter()
    await wrapper.findAll('.branch')[0].get('.branch-action.is-remove').trigger('click')

    const notice = wrapper.get('.branch-notice')
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('match')
    expect(notice.text()).toContain('result')
    expect(notice.text()).toContain('One undo restores both')
    expect(wrapper.emitted('notice')?.[0]?.[0]).toBe(notice.text())
  })

  it('leaves the edges alone when the deleted branch had none', async () => {
    const doc = routerGraph()
    const wrapper = mountRouter({ ...doc, edges: doc.edges.filter((entry) => entry.id !== 'e3') })
    await wrapper.findAll('.branch')[0].get('.branch-action.is-remove').trigger('click')

    expect(lastCommit(wrapper).next.edges.map((entry) => entry.id)).toEqual(['e1', 'e2', 'e4'])
    expect(wrapper.find('.branch-notice').exists()).toBe(false)
  })

  it('will not delete the last branch, which has nothing left to route to', () => {
    const doc = routerGraph()
    const router = doc.nodes[2]
    if (router.kind !== 'router') throw new Error('fixture moved')
    const single = { ...router, config: { branches: [router.config.branches[1]] } }
    const wrapper = mountRouter({
      ...doc,
      nodes: [doc.nodes[0], doc.nodes[1], single, doc.nodes[3]],
    })

    expect(
      wrapper.get('.branch-action.is-remove').attributes('disabled'),
    ).toBeDefined()
  })
})

describe('renaming a branch moves the edges that left by it', () => {
  it('rewrites source_port in the same commit', async () => {
    const wrapper = mountRouter()
    const field = wrapper.findAll('.branch')[0].get('[data-field="branches"] input')
    await field.setValue('approved')
    await field.trigger('keydown.enter')

    const commits = wrapper.emitted('commit') ?? []
    expect(commits).toHaveLength(1)

    const next = lastCommit(wrapper).next
    expect(branchesOf(next).map((branch) => branch.label)).toEqual(['approved', 'otherwise'])
    expect(next.edges.find((entry) => entry.id === 'e3')?.source_port).toBe('approved')
    expect(next.edges.find((entry) => entry.id === 'e4')?.source_port).toBe('otherwise')
  })

  it('leaves the drawn ports and the accepted ports agreeing afterwards', async () => {
    const wrapper = mountRouter()
    const field = wrapper.findAll('.branch')[0].get('[data-field="branches"] input')
    await field.setValue('approved')
    await field.trigger('keydown.enter')

    const next = lastCommit(wrapper).next
    const router = next.nodes.find((entry) => entry.kind === 'router') as BuilderNode
    const ports = outPortsOf(router)
    for (const entry of next.edges.filter((candidate) => candidate.source === 'route')) {
      expect(ports).toContain(entry.source_port)
    }
  })

  it('states how many edges move before the rename is committed', async () => {
    const wrapper = mountRouter()
    const field = wrapper.findAll('.branch')[0].get('[data-field="branches"] input')
    await field.setValue('approved')

    expect(wrapper.findAll('.branch')[0].get('.field-help').text()).toContain(
      'updates 1 reference',
    )
    expect(wrapper.emitted('commit')).toBeUndefined()
  })

  it('refuses a label another branch already holds', async () => {
    const wrapper = mountRouter()
    const field = wrapper.findAll('.branch')[0].get('[data-field="branches"] input')
    await field.setValue('otherwise')
    await field.trigger('keydown.enter')

    expect(wrapper.findAll('.branch')[0].get('.field-hint').text()).toBe(
      'Another branch is already called otherwise.',
    )
    expect(wrapper.emitted('commit')).toBeUndefined()
  })
})

describe('a branch added from here is born legal', () => {
  it('carries a key, because a comparison without one is a 422', async () => {
    const wrapper = mountRouter()
    await wrapper.get('.row-add').trigger('click')

    const added = branchesOf(lastCommit(wrapper).next)
    expect(added.map((branch) => branch.label)).toEqual(['match', 'branch_1', 'otherwise'])
    expect(added[1].key).toBe('decision')
    expect(added[1].op).not.toBe('otherwise')
  })

  it('lands before otherwise, which is what happens when nothing else did', async () => {
    const wrapper = mountRouter()
    await wrapper.get('.row-add').trigger('click')
    expect(branchesOf(lastCommit(wrapper).next).at(-1)?.op).toBe('otherwise')
  })

  it('states the count against the served bound rather than a constant', () => {
    const wrapper = mountRouter()
    expect(wrapper.get('[data-field="branches"] .field-note').text()).toBe('2 of 2–4')
  })
})

describe('reordering is a commit, not a drag that loses the undo', () => {
  it('moves one branch and commits once', async () => {
    const wrapper = mountRouter()
    await wrapper.findAll('.branch')[1].findAll('.branch-action')[0].trigger('click')

    expect(wrapper.emitted('commit')).toHaveLength(1)
    expect(branchesOf(lastCommit(wrapper).next).map((branch) => branch.label)).toEqual([
      'otherwise',
      'match',
    ])
  })

  it('disables the move that would go off the end', () => {
    const rows = mountRouter().findAll('.branch')
    expect(rows[0].findAll('.branch-action')[0].attributes('disabled')).toBeDefined()
    expect(rows[1].findAll('.branch-action')[1].attributes('disabled')).toBeDefined()
  })
})
