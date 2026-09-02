import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BuilderView from '../src/components/builder/BuilderView.vue'
import { routeHash, useWorkspaceRoute, workspaceRoute } from '../src/composables/useWorkspaceRoute'
import { resetVocabulary } from '../src/data/builderVocabulary'
import { MINIMAL_GATED_AGENT, documentFromTemplate } from '../src/data/builderTemplates'
import { toWire } from '../src/utils/builderSerialize'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { flush, withSetup } from './helpers'

/**
 * Where the work IS, and how an author gets back to it.
 *
 * Two defects, one subject. A draft saved for the first time got a server id
 * and the address bar stayed `#/build`: the chip read `saved · v1`, a
 * `builder-draft:ug_…` key appeared in `localStorage`, and a reload landed on
 * the template gallery with the work keyed by an id no URL had ever carried.
 * The route itself was never broken - opening the same document from the
 * library produced `#/build/ug_…` and survived a reload - only the create path
 * failed to use it. And the restore bar that would have offered the draft back
 * was never rendered by anything at all: `restoreOffer`, `acceptRestore` and
 * `dismissRestore` existed, were unit-tested by calling the composable, and no
 * `.vue` file read one. That is this repo's own "tests that pass for the wrong
 * reason", so both assertions below are made against a MOUNTED view.
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

const DOCUMENT_ID = 'ug_1234abcd'
const STORED_AT = '2026-09-02T05:29:00.000Z'

/** The stored model `GET /api/builder/workflows/{id}` answers with. */
function storedModel(version = 1) {
  return {
    id: DOCUMENT_ID,
    document: { ...toWire(documentFromTemplate(MINIMAL_GATED_AGENT)), id: DOCUMENT_ID, version },
    status: 'draft',
    version,
    head_version: version,
    created_at: STORED_AT,
    updated_at: STORED_AT,
    problems: [],
    budget: vocabularyPayload.validation.budget,
    graph: null,
    published: false,
  }
}

let created = 0

beforeEach(() => {
  created = 0
  window.location.hash = '#/build'
  window.localStorage.clear()
  resetVocabulary()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = (init?.method ?? 'GET').toUpperCase()
      let body: unknown = []
      if (url.includes('/api/builder/vocabulary')) body = vocabularyPayload.vocabulary
      else if (url.includes('/api/builder/validate')) body = vocabularyPayload.validation
      else if (url.includes('/api/builder/workflows') && method === 'POST') {
        created += 1
        body = storedModel()
      } else if (url.includes(`/api/builder/workflows/${DOCUMENT_ID}`)) body = storedModel()
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})

afterEach(() => {
  window.localStorage.clear()
  resetVocabulary()
  vi.unstubAllGlobals()
})

async function settled(): Promise<void> {
  await flush(6)
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flush(6)
}

describe('the address follows the first save', () => {
  it('asks the shell to adopt the id the server assigned, once', async () => {
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()
    const card = wrapper.findAll('.template-card').find((entry) => entry.text().includes('Minimal'))
    await card!.trigger('click')
    await settled()

    expect(wrapper.emitted('adoptDocument')).toBeUndefined()

    // Ctrl+S on the window, the way an author saves: the hotkey table owns the
    // chord and `BuilderView` owns what it means.
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 's', ctrlKey: true }))
    await settled()

    expect(created, 'the first save did not create anything').toBe(1)
    expect(wrapper.emitted('adoptDocument')).toEqual([[DOCUMENT_ID]])
    wrapper.unmount()
  })

  it('replaces the history entry rather than pushing one', () => {
    // Pushing would put the gallery and the document next to each other on the
    // stack, so Back would leave a graph the author is still editing for a
    // gallery they never visited. `replaceState` also fires no `hashchange`,
    // which is why `navigate` assigns the ref before it touches the URL.
    window.location.hash = '#/build'
    const [route, app] = withSetup(() => useWorkspaceRoute())
    const depth = window.history.length

    route.navigate({ name: 'builder', documentId: DOCUMENT_ID as never }, { replace: true })

    expect(window.location.hash).toBe(`#/build/${DOCUMENT_ID}`)
    expect(window.history.length).toBe(depth)
    expect(route.route.value).toEqual({ name: 'builder', documentId: DOCUMENT_ID })
    // And the parser and the writer still agree about the address it produced.
    expect(workspaceRoute(routeHash(route.route.value))).toEqual(route.route.value)
    app.unmount()
  })
})

describe('unsaved work in the browser is offered back, on screen', () => {
  it('renders a restore bar with both timestamps and takes the draft when asked', async () => {
    const drafted = documentFromTemplate(MINIMAL_GATED_AGENT)
    window.localStorage.setItem(
      `builder-draft:${DOCUMENT_ID}`,
      JSON.stringify({
        v: 1,
        baseVersion: 1,
        savedAt: '2026-09-02T13:29:00.000Z',
        document: {
          ...toWire(drafted),
          id: DOCUMENT_ID,
          version: 1,
          name: 'The version only this browser has',
        },
      }),
    )

    const wrapper = mount(BuilderView, {
      props: { documentId: DOCUMENT_ID as never },
      global: { stubs: STUBS },
    })
    await settled()

    const bar = wrapper.find('[data-testid="restore-bar"]')
    expect(bar.exists(), 'the draft was written and never offered back').toBe(true)
    // Both times, because one alone answers the wrong question: "unsaved work
    // from 13:29" only means something beside "the stored copy is from 05:29".
    expect(bar.findAll('time')).toHaveLength(2)

    await bar.find('[data-testid="restore-accept"]').trigger('click')
    await flush(4)

    expect(wrapper.text()).toContain('The version only this browser has')
    expect(wrapper.find('[data-testid="restore-bar"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('takes the bar away without restoring when the draft is declined', async () => {
    window.localStorage.setItem(
      `builder-draft:${DOCUMENT_ID}`,
      JSON.stringify({
        v: 1,
        baseVersion: 1,
        savedAt: '2026-09-02T13:29:00.000Z',
        document: {
          ...toWire(documentFromTemplate(MINIMAL_GATED_AGENT)),
          id: DOCUMENT_ID,
          version: 1,
          name: 'Declined',
        },
      }),
    )

    const wrapper = mount(BuilderView, {
      props: { documentId: DOCUMENT_ID as never },
      global: { stubs: STUBS },
    })
    await settled()

    await wrapper.find('[data-testid="restore-dismiss"]').trigger('click')
    await flush(4)

    expect(wrapper.find('[data-testid="restore-bar"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Declined')
    // Out of the browser too, so the same bar cannot appear a second time.
    expect(window.localStorage.getItem(`builder-draft:${DOCUMENT_ID}`)).toBeNull()
    wrapper.unmount()
  })
})
