import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import BuilderView from '../src/components/builder/BuilderView.vue'
import { readRunHandoff } from '../src/data/builderRunHandoff'
import { resetVocabulary } from '../src/data/builderVocabulary'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { flush } from './helpers'

/**
 * The Run half of the mode switch carries the workflow (item 57, ROUND-2 R3).
 *
 * It was `emit('runWorkspace')` and nothing else, so leaving a builder document
 * by the switch landed on a console pointed at the BUILT-IN validator: the
 * breadcrumb had just named the author's workflow and the next screen did not.
 * Measured on 2026-09-06 before the change - from `#/build/ug_e8d48b6a` the
 * switch reached `#/run` reading `RUN — BUILT IN / Evidence pipeline / Idea
 * Validator / IDEA TO VALIDATE`.
 *
 * A run resolves a REGISTERED version, so an unpublished document has nothing
 * to carry: navigating would land on a console that answers 404 for this graph,
 * a refusal the author can do nothing about from there. The switch says so
 * instead, in the control rather than only in a tooltip - a reason only a hover
 * can reach is a dead button to everybody who does not hover.
 *
 * The PUBLISHED arm is proved end to end in `e2e/console-identity.spec.ts`,
 * where a graph is really published and the console really loads it. Here the
 * two states a mount can reach honestly are asserted: the gallery, which has no
 * workflow to carry and must keep behaving as it did, and an open document that
 * has never been published.
 */

const stubs = {
  VueFlow: true,
  Background: true,
  BuilderMinimap: true,
  NodePalette: true,
  InspectorRail: true,
  GraphThumbnail: true,
}

describe('the builder Run switch', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    resetVocabulary()
    window.matchMedia = ((query: string) => ({
      matches: false, media: query, onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      let body: unknown = []
      if (url.includes('/api/builder/vocabulary')) body = vocabularyPayload.vocabulary
      else if (url.includes('/api/builder/validate')) body = vocabularyPayload.validation
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }))
  })

  afterEach(() => {
    window.sessionStorage.clear()
    resetVocabulary()
    vi.unstubAllGlobals()
  })

  it('stays a plain navigation on the gallery, where there is no workflow to carry', async () => {
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs } })
    await flush(12)

    const run = wrapper.get('[data-testid="run-switch"]')
    // `data-run-state`, not the text: BOTH labels are always in the DOM so the
    // control cannot change width (D-15-14), and only one of them is visible.
    expect(run.attributes('data-run-state')).toBe('ready')
    expect(run.get('.switch-label > span.is-spare').text()).toBe('Publish to run')
    expect(run.attributes('disabled')).toBeUndefined()

    await run.trigger('click')
    expect(wrapper.emitted('runWorkspace')).toHaveLength(1)
    // Nothing was carried, because there is nothing open to carry.
    expect(readRunHandoff(null)).toBeNull()
    wrapper.unmount()
  })

  it('refuses, and says why, on a document that has never been published', async () => {
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs } })
    await flush(12)
    await wrapper.findAll('.template-card')[0].trigger('click')
    await flush(12)

    const run = wrapper.get('[data-testid="run-switch"]')
    expect(run.attributes('data-run-state')).toBe('blocked')
    expect(run.get('.switch-label > span.is-spare').text()).toBe('Run')
    expect(run.attributes('disabled')).toBeDefined()
    // And the tooltip names the control that lifts the refusal, rather than
    // restating the refusal in other words.
    expect(run.attributes('title')).toContain('Publish button')

    await run.trigger('click')
    expect(wrapper.emitted('runWorkspace')).toBeUndefined()
    expect(readRunHandoff(null)).toBeNull()
    wrapper.unmount()
  })
})
