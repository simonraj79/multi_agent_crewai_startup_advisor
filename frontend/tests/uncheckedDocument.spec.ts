import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BuilderView from '../src/components/builder/BuilderView.vue'
import ProblemsPanel from '../src/components/builder/ProblemsPanel.vue'
import PublishDialog from '../src/components/builder/PublishDialog.vue'
import { useBuilderValidation } from '../src/composables/useBuilderValidation'
import { resetVocabulary } from '../src/data/builderVocabulary'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { FakeBuilderApi, flush, withSetup } from './helpers'
import { BLANK, documentFromTemplate } from '../src/data/builderTemplates'
import type { BuilderDocument } from '../src/types/builder'

/**
 * "Nobody has answered yet" and "the answer is clean" are different facts, and
 * this file is the set of places that used to render them identically.
 *
 * The hole was real and it was on the FIRST screen. `useBuilderValidation`
 * watches the document's fingerprint, and `useBuilderDocument` is seeded from
 * `BLANK` - which is byte-for-byte the document the gallery hands over when an
 * author picks "Blank canvas". The fingerprint therefore never moved, the
 * watcher never fired, and no `/api/builder/validate` request was ever sent:
 * measured with a fetch spy, zero POSTs, ever. Over that, the dock read
 * `Ready to publish`, the publish checklist ticked `Validation is current` and
 * `No errors`, and pressing Publish got a 422 from a server that answers
 * `valid: false` with `no-input-node` for the same bytes. Every other template
 * differs from the seed and so validated by accident, which is exactly why a
 * green unit suite never saw it.
 *
 * Three locks, because one of them is the fix and the other two are the reason
 * it cannot come back:
 *
 * 1. `BuilderView` kicks `validateNow()` whenever a document is shown, so no
 *    document is ever unvalidated regardless of what its fingerprint does.
 * 2. `phase === 'idle'` BLOCKS publish, so any future path that leaves the loop
 *    idle refuses rather than repeating the lie.
 * 3. `ProblemsPanel` and `PublishDialog` both read the phase, so the sentence on
 *    screen is about the state the loop is actually in.
 */

const VueFlowStub = defineComponent({
  name: 'VueFlow',
  props: { id: { type: String, default: '' } },
  setup(_props, { slots }) {
    return () => h('div', { class: 'vue-flow-stub' }, slots.default?.())
  },
})

const STUBS = {
  VueFlow: VueFlowStub,
  Background: true,
  Controls: true,
  BuilderMinimap: true,
  NodePalette: true,
  InspectorRail: true,
}

let fetched: string[] = []

beforeEach(() => {
  fetched = []
  window.location.hash = '#/build'
  resetVocabulary()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      fetched.push(url)
      let body: unknown = []
      if (url.includes('/api/builder/vocabulary')) body = vocabularyPayload.vocabulary
      else if (url.includes('/api/builder/validate')) body = vocabularyPayload.validation
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  resetVocabulary()
  vi.unstubAllGlobals()
})

/** Two ticks plus two animation frames: what `showGraph` waits for. */
async function settled(): Promise<void> {
  await flush(6)
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flush(6)
}

const validateCount = (): number =>
  fetched.filter((url) => url.includes('/api/builder/validate')).length

describe('a document is checked the moment it is shown, whatever its fingerprint does', () => {
  it('validates the blank canvas, whose fingerprint equals the loop mount value', async () => {
    const wrapper = mount(BuilderView, {
      props: { documentId: null },
      global: { stubs: STUBS },
    })
    await settled()

    // The gallery prices its own cards, so the count before is not zero - which
    // is precisely what made this hole hard to see in a request log.
    const before = validateCount()
    const blankCard = wrapper.findAll('.template-card').find((card) => card.text().includes('Blank'))
    expect(blankCard, 'the gallery no longer offers a blank canvas').toBeTruthy()
    await blankCard!.trigger('click')
    await settled()

    expect(
      validateCount(),
      'choosing Blank canvas sent no validate request, so nothing on screen is a verdict',
    ).toBeGreaterThan(before)
    wrapper.unmount()
  })

  it('hands the loop the same document the gallery hands the store', () => {
    // The premise of the defect, asserted directly: the seed and the "Blank
    // canvas" card are one document, so nothing about the fingerprint changes
    // when it is chosen and the watcher can never be what checks it.
    //
    // Asserted as EQUALITY against the template rather than as "it is empty",
    // which is what it said until 2026-09-04. BLANK now seeds one input node
    // (02-canvas.md D7) and the emptiness was never the point - sameness was,
    // and sameness is what the defect turned on.
    expect(documentFromTemplate(BLANK)).toEqual(BLANK.document)
    expect(documentFromTemplate(BLANK)).not.toBe(BLANK.document)
  })
})

describe('the phase decides whether an empty list means anything', () => {
  const panel = (phase: 'idle' | 'fresh' | 'unreachable', reason = '') =>
    mount(ProblemsPanel, { props: { problems: [], phase, publishProblems: [], labels: {}, reason } })

  it('says nothing has been asked while the phase is idle', () => {
    const wrapper = panel('idle')
    expect(wrapper.get('[data-testid="problems-headline"]').text()).toBe('Not checked yet')
    expect(wrapper.get('[data-testid="problems-unchecked"]').text()).toContain(
      'nothing here is a verdict',
    )
    // The mint tick is a claim, and there is nothing to claim yet.
    expect(wrapper.get('[data-testid="problems-headline"]').classes()).not.toContain('is-clean')
  })

  it('names the failure while the phase is unreachable, rather than reading clean', () => {
    const wrapper = panel('unreachable', 'the validator could not be reached')
    expect(wrapper.get('[data-testid="problems-headline"]').text()).toBe('Validation unavailable')
    expect(wrapper.get('[data-testid="problems-unreachable"]').text()).toContain(
      'the validator could not be reached',
    )
  })

  it('still states the rule once when an empty list is an actual answer', () => {
    const wrapper = panel('fresh')
    expect(wrapper.get('[data-testid="problems-headline"]').text()).toBe('Ready to publish')
    expect(wrapper.text()).toContain('Warnings never block; errors always do.')
  })
})

describe('an unchecked document cannot be published', () => {
  it('blocks publish at idle with a reason, not only at stale and unreachable', () => {
    const doc = ref<BuilderDocument>(documentFromTemplate(BLANK))
    const api = new FakeBuilderApi()
    const [validation, app] = withSetup(() => useBuilderValidation(doc, { api }))

    expect(validation.phase.value).toBe('idle')
    expect(validation.phaseBlocksPublish.value).toBe(true)
    expect(validation.phaseBlockReason.value).toBe('validation has not run yet')
    app.unmount()
  })

  it('fails the publish checklist freshness row at idle', () => {
    const wrapper = mount(PublishDialog, {
      props: {
        open: true,
        document: documentFromTemplate(BLANK),
        documentId: 'ug_00000001',
        errorCount: 0,
        saveState: 'clean' as const,
        version: 1,
        headVersion: 1,
        phase: 'idle' as const,
        budget: null,
        publishedVersion: null,
        api: new FakeBuilderApi(),
      },
    })

    expect(wrapper.text()).toContain('validation has not run yet')
    const action = wrapper.findAll('button').find((button) => /^Publish$/.test(button.text()))
    expect(action?.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
