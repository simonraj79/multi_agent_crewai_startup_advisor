import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PublishDialog from '../src/components/builder/PublishDialog.vue'
import { BuilderPublishRefusedError } from '../src/services/builderApi'
import { IDEA_VALIDATOR, MINIMAL_GATED_AGENT } from '../src/data/builderTemplates'
import { FakeBuilderApi, flush, zeroBudget } from './helpers'
import type { BuilderDocument, BuilderPublish } from '../src/types/builder'

/**
 * Publishing is the one step in this product with consequences outside the tab.
 *
 * It registers a runnable workflow in five server-side maps, changes what
 * `POST /api/sessions/{id}/runs` accepts, and hands the author a contract they
 * did not write and now own. R15 keeps zero modals in the EDITING path and
 * spends one of its two dialogs here, so this dialog has to earn it: every
 * refusal names itself, and every fact the author is now responsible for is on
 * screen rather than inferable.
 *
 * TWO THINGS THIS SPEC EXISTS TO STOP.
 *
 * A greyed Publish button with no sentence beside it. §6.5 lists five blockers
 * and each has its own wording; a dialog that showed one summary line would
 * leave an author who is dirty AND behind head fixing the wrong thing. Each is
 * asserted INDEPENDENTLY - one blocker at a time, everything else met - because
 * a checklist that only ever shows the first failure is indistinguishable from
 * one that works, right up until two things are wrong at once.
 *
 * A silent `gated_before_spend: false`. That boolean decides whether a stranger
 * with the link is answered 403, and the flagship template trips it: the idea
 * validator scopes before it gates, which was measured live -
 * `ug_e9afa950` published with `gated_before_spend: false` and an anonymous
 * launch came back 403. The dialog quotes the server's own sentence rather than
 * paraphrasing it, because that is the string the author's colleague will read.
 */

const READY = {
  errorCount: 0,
  saveState: 'clean' as const,
  version: 3,
  headVersion: 3,
  phase: 'fresh' as const,
  budget: zeroBudget(),
  publishedVersion: null,
}

/** The component's own prop type, so an override cannot name a prop it lacks. */
type DialogProps = InstanceType<typeof PublishDialog>['$props']

function mountDialog(
  overrides: Partial<DialogProps> = {},
  api = new FakeBuilderApi(),
  document: BuilderDocument = MINIMAL_GATED_AGENT.document,
) {
  const id = api.seed({ ...document, version: 3 }, 3)
  return {
    api,
    wrapper: mount(PublishDialog, {
      props: { open: true, document, documentId: id, api, ...READY, ...overrides },
    }),
  }
}

const rows = (wrapper: ReturnType<typeof mountDialog>['wrapper']) =>
  wrapper.findAll('.precondition-list li')

const blockedText = (wrapper: ReturnType<typeof mountDialog>['wrapper']) =>
  rows(wrapper)
    .filter((row) => row.classes('is-blocked'))
    .map((row) => row.find('.precondition-blocker').text())

describe('the publish checklist refuses one thing at a time and says which', () => {
  it('offers Publish when every precondition is met', async () => {
    const { wrapper } = mountDialog()
    await flush()
    expect(blockedText(wrapper)).toEqual([])
    const publish = wrapper.findAll('button').find((button) => button.text().includes('Publish'))
    expect(publish?.attributes('disabled')).toBeUndefined()
  })

  it('refuses a draft that has never been saved, before anything else', () => {
    const { wrapper } = mountDialog({ documentId: null })
    // First in the list on purpose: a never-saved draft fails every other row
    // too, for reasons that are not the real one.
    expect(blockedText(wrapper)[0]).toContain('never been saved')
  })

  it('refuses unsaved changes, and says publish registers the stored version', () => {
    const { wrapper } = mountDialog({ saveState: 'dirty' })
    expect(blockedText(wrapper)).toEqual([
      'save first — publish registers the stored version',
    ])
  })

  it('refuses an older version, naming both the one in hand and head', () => {
    const { wrapper } = mountDialog({ version: 3, headVersion: 7 })
    expect(blockedText(wrapper)).toEqual(['you are viewing v3; publish works on head (v7)'])
  })

  it('refuses a stale validation, and distinguishes stale from unreachable', () => {
    const { wrapper: stale } = mountDialog({ phase: 'stale' })
    expect(blockedText(stale)).toEqual(['validation is not current'])

    const { wrapper: unreachable } = mountDialog({ phase: 'unreachable' })
    // "The last check did not come back" and "you have edited since the last
    // check" are different situations with different fixes, and a shared
    // sentence would send an author looking for an edit they did not make.
    expect(blockedText(unreachable)[0]).toContain('the server did not answer')
  })

  it('refuses errors, counting them, and singular when there is one', () => {
    const { wrapper: three } = mountDialog({ errorCount: 3 })
    expect(blockedText(three)).toEqual(['3 errors must be fixed'])

    const { wrapper: one } = mountDialog({ errorCount: 1 })
    expect(blockedText(one)).toEqual(['1 error must be fixed'])
  })

  it('refuses a graph over the run cost ceiling, naming both figures', () => {
    const { wrapper } = mountDialog({
      budget: zeroBudget({ over_ceiling: true, static_cost_usd: 9.4, ceiling_usd: 10 }),
    })
    expect(blockedText(wrapper)[0]).toContain('$9.40')
    expect(blockedText(wrapper)[0]).toContain('$10.00')
  })

  it('lets warnings through, because warnings never block', () => {
    // The rule is stated once in `ProblemsPanel`'s empty state and enforced
    // here: `errorCount` is the only count this dialog reads.
    const { wrapper } = mountDialog({ errorCount: 0 })
    expect(blockedText(wrapper)).toEqual([])
  })
})

describe('a published graph hands the author its contract', () => {
  async function publish(result: Partial<BuilderPublish> = {}, document = MINIMAL_GATED_AGENT.document) {
    const api = new FakeBuilderApi()
    const mounted = mountDialog({}, api, document)
    api.publishResult = {
      workflow_id: mounted.api.store.keys().next().value as string,
      graph_version: '3345109819d3e09f',
      version: 3,
      input_field: 'idea',
      static_cost_usd: 1.5136,
      gated_before_spend: true,
      reserved_input_keys: ['out__draft', 'turns__confirm'],
      ...result,
    }
    const button = mounted.wrapper.findAll('button').find((b) => b.text().includes('Publish'))
    await button!.trigger('click')
    await flush()
    return mounted.wrapper
  }

  it('names the key a run request must carry', async () => {
    const wrapper = await publish()
    expect(wrapper.text()).toContain('Run input key')
    expect(wrapper.text()).toContain('inputs.idea')
  })

  it('prints the graph version the ETag will carry', async () => {
    const wrapper = await publish()
    expect(wrapper.text()).toContain('3345109819d3e09f')
  })

  it('lists every reserved key, because a run carrying one is refused 422', async () => {
    const wrapper = await publish()
    const keys = wrapper.findAll('.reserved-keys code').map((code) => code.text())
    expect(keys).toEqual(['out__draft', 'turns__confirm'])
  })

  it('states the price as the estimate it is', async () => {
    const wrapper = await publish()
    expect(wrapper.text()).toContain('$1.5136')
  })

  it('says a gated graph is safe for anyone with the link', async () => {
    const wrapper = await publish({ gated_before_spend: true })
    expect(wrapper.find('.gated-note').text()).toContain('anyone with the link can')
    expect(wrapper.find('.gateless-warning').exists()).toBe(false)
  })

  it('quotes the whole 403 when a billable node runs before any gate', async () => {
    const wrapper = await publish(
      { gated_before_spend: false, workflow_id: 'ug_e9afa950' },
      IDEA_VALIDATOR.document,
    )
    const warning = wrapper.find('.gateless-warning')
    expect(warning.exists()).toBe(true)
    // The service's own sentence, verbatim. An author who paraphrases it to a
    // colleague and an author who quotes it must be describing the same string.
    expect(warning.text()).toContain(
      'workflow ug_e9afa950 reaches a billable node before any human gate; '
      + 'sign in, or add a gate above the first agent',
    )
  })

  it('offers a jump to the first billable node on the ungated path', async () => {
    const wrapper = await publish({ gated_before_spend: false }, IDEA_VALIDATOR.document)
    // `scoper` is the first billable node reachable from `idea` without
    // crossing a gate - which is exactly what the server's own
    // `gate_before_first_billable` walk finds, and what an author has to move a
    // gate above.
    const jump = wrapper.findAll('button').find((button) => button.text().startsWith('Go to'))
    expect(jump?.text()).toBe('Go to Scope the idea')
    await jump!.trigger('click')
    expect(wrapper.emitted('focusNode')?.[0]).toEqual(['scoper'])
  })

  it('offers a real route to run it, carrying the workflow and its input key', async () => {
    const wrapper = await publish({ workflow_id: 'ug_e9afa950', input_field: 'idea' })
    const run = wrapper.findAll('button').find((button) => button.text().includes('Run it'))
    await run!.trigger('click')
    // Ruling R4 cut Run mode because no builder runner existed. One does, and
    // this button is the whole of what that override buys the author: the id
    // the server just registered, and the key it will demand inside `inputs`.
    expect(wrapper.emitted('run')?.[0]).toEqual(['ug_e9afa950', 'idea'])
  })
})

describe('a compile refusal goes to the problems panel, not into this dialog', () => {
  it('emits the 422 problem list and keeps the checklist on screen', async () => {
    const api = new FakeBuilderApi()
    const problems = [
      {
        code: 'billable-count',
        severity: 'error' as const,
        message: 'this graph runs 14 billable nodes and the ceiling is 13',
        node_id: 'scoper',
        edge_id: null,
      },
    ]
    api.failWith.publish = new BuilderPublishRefusedError('this graph cannot be compiled', problems)
    const { wrapper } = mountDialog({}, api)
    const button = wrapper.findAll('button').find((b) => b.text().includes('Publish'))
    await button!.trigger('click')
    await flush()

    // They are the same `Problem` objects with the same anchors and the author
    // fixes them the same way, so they belong beside every other problem rather
    // than in a paragraph inside a dialog that is about to close.
    expect(wrapper.emitted('refused')?.[0]).toEqual([problems])
    expect(wrapper.find('.publish-failure').text()).toContain('cannot be compiled')
    expect(wrapper.find('.publish-contract').exists()).toBe(false)
  })

  it('reports any other failure without pretending it published', async () => {
    const api = new FakeBuilderApi()
    api.failWith.publish = new Error('the service is at capacity; try again shortly')
    const { wrapper } = mountDialog({}, api)
    const button = wrapper.findAll('button').find((b) => b.text().includes('Publish'))
    await button!.trigger('click')
    await flush()
    expect(wrapper.find('.publish-failure').text()).toContain('at capacity')
    expect(wrapper.emitted('published')).toBeUndefined()
  })
})

describe('the dialog behaves like a dialog', () => {
  it('declares itself modal and labels itself', () => {
    const { wrapper } = mountDialog()
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.attributes('aria-labelledby')).toBe('publish-title')
  })

  it('closes on Escape without publishing', async () => {
    const { wrapper, api } = mountDialog()
    await wrapper.find('.publish-scrim').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(api.publishCalls).toEqual([])
  })

  it('renders nothing at all when closed', () => {
    const api = new FakeBuilderApi()
    const id = api.seed({ ...MINIMAL_GATED_AGENT.document, version: 3 }, 3)
    const wrapper = mount(PublishDialog, {
      props: { open: false, document: MINIMAL_GATED_AGENT.document, documentId: id, api, ...READY },
    })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})
