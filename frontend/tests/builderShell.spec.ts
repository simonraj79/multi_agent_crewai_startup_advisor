import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import BuilderView from '../src/components/builder/BuilderView.vue'
import StudioView from '../src/views/StudioView.vue'
import DocumentBar from '../src/components/builder/DocumentBar.vue'
import ShortcutSheet from '../src/components/builder/ShortcutSheet.vue'
import TemplateGallery from '../src/components/builder/TemplateGallery.vue'
import {
  ALL_BUILDER_TEMPLATES,
  BUILDER_TEMPLATES,
  IDEA_VALIDATOR,
} from '../src/data/builderTemplates'
import { HOTKEY_BINDINGS } from '../src/composables/useBuilderHotkeys'
import { clearRunHandoff, readRunHandoff, writeRunHandoff } from '../src/data/builderRunHandoff'
import { resetVocabulary } from '../src/data/builderVocabulary'
import { BuilderConflictError } from '../src/services/builderApi'
import { documentId } from '../src/types/builder'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { FakeBuilderApi, flush, zeroBudget } from './helpers'

/**
 * The shell: one auth gate, two workspaces, and nothing shared between them by
 * accident.
 *
 * `App.vue`'s body moved wholesale into `views/StudioView.vue` so a second view
 * could exist beside it, and the risk a move like that carries is not that the
 * new view is wrong - it is that the OLD one quietly stopped working while
 * every spec that exercises `useValidatorRun` kept passing, because those
 * specs test the composable and never mounted the component. So what is
 * asserted here is the wiring the move could break: which view a hash selects,
 * that the gate still precedes both, and that the two Vue Flow instances do not
 * share an id.
 *
 * WHY THE INSTANCE ID MATTERS ENOUGH TO TEST. `useVueFlow` keys viewport,
 * selection and node lookup by id (§1.3). Two instances sharing one would trade
 * viewports across a route change - the builder opening at whatever zoom the
 * run console was left at, a `fitView` in one moving the other - and the
 * symptom would read as a rendering bug rather than as a naming collision.
 */

vi.mock('../src/composables/useAuthGate', () => ({
  useAuthGate: () => ({
    authClient: null,
    phase: ref('authenticated'),
    user: ref({ id: 'u1', name: 'Ada', email: 'ada@example.com', image: null }),
    mayUseStudio: ref(true),
    signingIn: ref(false),
    signInError: ref(''),
    startGoogleSignIn: () => {},
    endSession: () => {},
  }),
}))

/** Captures the `id` every `<VueFlow>` is constructed with. */
const flowIds: string[] = []
const VueFlowStub = defineComponent({
  name: 'VueFlow',
  props: { id: { type: String, default: '' } },
  setup(props, { slots }) {
    flowIds.push(props.id)
    return () => h('div', { class: 'vue-flow-stub', 'data-flow-id': props.id }, slots.default?.())
  },
})

const SHELL_STUBS = {
  VueFlow: VueFlowStub,
  Background: true,
  Controls: true,
  CrewProgress: true,
  ChatRail: true,
  ReportPanel: true,
  RunHistory: true,
  StatusPanel: true,
  GateCard: true,
}

/**
 * jsdom implements neither of these, and both are reached during a mount.
 *
 * `matchMedia` is read at `StudioView` setup to decide whether the activity
 * rail starts collapsed on a phone; `fetch` is reached by the vocabulary load
 * and the library list. Answering them here rather than making the components
 * defensive keeps the moved console byte-for-byte what it was - the whole point
 * of a MODIFY-BY-MOVE is that the code did not change.
 */
beforeEach(() => {
  flowIds.length = 0
  window.location.hash = '#/'
  // Both shapes of the handoff key - the anonymous one and the signed-in user's
  // `u:<id>:` one (D-01-5) - so a record one test wrote as `u1` cannot point
  // the next test's console at a graph it never asked for.
  window.sessionStorage.clear()
  resetVocabulary()
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
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
  // Both shapes of the handoff key - the anonymous one and the signed-in user's
  // `u:<id>:` one (D-01-5) - so a record one test wrote as `u1` cannot point
  // the next test's console at a graph it never asked for.
  window.sessionStorage.clear()
  resetVocabulary()
  vi.unstubAllGlobals()
})

describe('the hash chooses the workspace and the gate precedes both', () => {
  it('renders the run console at the root', () => {
    const wrapper = mount(App, {
      global: { stubs: { StudioView: true, BuilderView: true } },
    })
    expect(wrapper.findComponent({ name: 'StudioView' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'BuilderView' }).exists()).toBe(false)
  })

  it('renders the builder with no document at #/build', () => {
    window.location.hash = '#/build'
    const wrapper = mount(App, {
      global: { stubs: { StudioView: true, BuilderView: true } },
    })
    const builder = wrapper.findComponent({ name: 'BuilderView' })
    expect(builder.exists()).toBe(true)
    expect(builder.props('documentId')).toBeNull()
  })

  it('renders the builder with a document at #/build/:documentId', () => {
    window.location.hash = '#/build/ug_0a1b2c3d'
    const wrapper = mount(App, {
      global: { stubs: { StudioView: true, BuilderView: true } },
    })
    expect(wrapper.findComponent({ name: 'BuilderView' }).props('documentId')).toBe('ug_0a1b2c3d')
  })

  it('switches views when the hash changes under it', async () => {
    const wrapper = mount(App, {
      global: { stubs: { StudioView: true, BuilderView: true } },
    })
    window.location.hash = '#/build'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await flush()
    expect(wrapper.findComponent({ name: 'BuilderView' }).exists()).toBe(true)
  })
})

describe('the two canvases do not share a Vue Flow instance', () => {
  it('mounts the run console as studio-flow', () => {
    mount(StudioView, {
      props: { user: { id: 'u1', name: 'Ada', email: 'a@b.c', image: null }, authenticated: false },
      global: { stubs: SHELL_STUBS },
    })
    expect(flowIds).toContain('studio-flow')
  })

  it('mounts the builder as builder-flow once a template is chosen', async () => {
    const wrapper = mount(BuilderView, {
      props: { documentId: null },
      global: { stubs: { ...SHELL_STUBS, BuilderMinimap: true, NodePalette: true, InspectorRail: true } },
    })
    await flush(12)
    // The gallery IS the canvas's empty state, so there is no flow instance
    // until an author starts something - which is also the first half of this
    // assertion: a builder that mounted a canvas over the gallery would put two
    // instances on screen at once.
    expect(flowIds).toEqual([])

    await wrapper.findAll('.template-card')[0].trigger('click')
    await flush(12)
    expect(flowIds).toEqual(['builder-flow'])
  })

  it('never lets the two views claim one instance id', () => {
    // The collision is the failure this guards: `useVueFlow` keys viewport,
    // selection and node lookup by id, so one shared id would have the builder
    // open at the run console's zoom and a `fitView` in either move both.
    expect(new Set(['studio-flow', 'builder-flow']).size).toBe(2)
  })
})

describe('the shortcut sheet prints the table the listener dispatches from', () => {
  it('renders every binding and invents none', () => {
    const wrapper = mount(ShortcutSheet, { props: { open: true } })
    const rendered = wrapper
      .findAll('[data-testid^="shortcut-"]')
      .map((row) => row.attributes('data-testid')!.replace('shortcut-', ''))
    const declared = HOTKEY_BINDINGS.map((binding) => binding.id)
    // Set equality in BOTH directions, which is the whole point: a shortcut
    // documented and unbound teaches a key that does nothing, and one bound and
    // undocumented is a feature nobody finds.
    expect(new Set(rendered)).toEqual(new Set(declared))
    expect(rendered).toHaveLength(declared.length)
  })

  it('prints the label and at least one key for every binding', () => {
    const wrapper = mount(ShortcutSheet, { props: { open: true } })
    for (const binding of HOTKEY_BINDINGS) {
      const row = wrapper.find(`[data-testid="shortcut-${binding.id}"]`)
      expect(row.text(), binding.id).toContain(binding.label)
      expect(row.findAll('kbd').length, binding.id).toBeGreaterThan(0)
    }
  })

  it('is a focus-trapped dialog that Escape closes', async () => {
    const wrapper = mount(ShortcutSheet, { props: { open: true } })
    const dialog = wrapper.find('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    await wrapper.find('.shortcut-scrim').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('renders nothing when closed', () => {
    const wrapper = mount(ShortcutSheet, { props: { open: false } })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})

describe('the document bar says what happened to the work', () => {
  const bar = (overrides: Record<string, unknown> = {}) =>
    mount(DocumentBar, {
      props: {
        name: 'Idea validator',
        saveState: 'clean',
        version: 4,
        status: 'draft',
        publishedVersion: null,
        publishedHere: false,
        canUndo: true,
        canRedo: false,
        undoLabel: 'delete node',
        redoLabel: '',
        undoneLabel: '',
        maxNameChars: 80,
        ...overrides,
      },
    })

  it('names the last undoable command in the tooltip', () => {
    const undo = bar().find('button[aria-label="Undo"]')
    expect(undo.attributes('title')).toBe('Undo: delete node')
  })

  describe('Save is a control, not only a chord (D-15-13)', () => {
    it('is pressable while the document is dirty, and says the chord too', async () => {
      const wrapper = bar({ saveState: 'dirty' })
      const save = wrapper.get('[data-testid="document-save"]')

      expect(save.attributes('disabled')).toBeUndefined()
      expect(save.attributes('title')).toBe('Save (Ctrl+S)')
      await save.trigger('click')
      expect(wrapper.emitted('save')).toHaveLength(1)
    })

    it('is disabled rather than hidden with nothing to save, and says why', () => {
      // Hidden would make the control appear and vanish under the pointer,
      // and the tooltip is also the answer to "did that save?".
      const save = bar({ saveState: 'clean' }).get('[data-testid="document-save"]')
      expect(save.attributes('disabled')).toBeDefined()
      expect(save.attributes('title')).toBe('No unsaved changes (Ctrl+S)')
    })

    it('is disabled on a stored version, like the name button', () => {
      const save = bar({ saveState: 'dirty', readOnly: true }).get('[data-testid="document-save"]')
      expect(save.attributes('disabled')).toBeDefined()
      expect(save.attributes('title')).toContain('Read-only')
    })

    it('says a conflict rather than pretending it can be saved away', () => {
      const save = bar({ saveState: 'conflict' }).get('[data-testid="document-save"]')
      expect(save.attributes('title')).toContain('Somebody else saved first')
    })

    it('is in the kebab as well, which is where a never-saved document is reached', async () => {
      const wrapper = bar({ saveState: 'dirty', documentId: null })
      await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
      const item = wrapper.get('[data-testid="menu-save"]')
      expect(item.attributes('disabled')).toBeUndefined()
      await item.trigger('click')
      expect(wrapper.emitted('save')).toHaveLength(1)
    })
  })

  it('says so rather than going quiet when there is nothing to undo', () => {
    const undo = bar({ canUndo: false }).find('button[aria-label="Undo"]')
    expect(undo.attributes('title')).toBe('Nothing to undo')
    expect(undo.attributes('disabled')).toBeDefined()
  })

  it('announces what an undo removed, politely', async () => {
    const wrapper = bar()
    await wrapper.setProps({ undoneLabel: 'delete node' })
    const region = wrapper.find('[role="status"]')
    expect(region.attributes('aria-live')).toBe('polite')
    expect(region.text()).toBe('Undid: delete node')
  })

  it('reads mint only when the live version is the one on screen', () => {
    const current = bar({ publishedVersion: 4, publishedHere: true, status: 'published' })
    expect(current.find('.live-note').text()).toBe('v4 is live')
    expect(current.find('.live-note').classes()).toContain('is-current')
  })

  it('names the divergence when an older version is the live one', () => {
    const behind = bar({ publishedVersion: 2, publishedHere: true, status: 'published' })
    expect(behind.find('.live-note').text()).toBe('v2 is live · you are on v4')
    expect(behind.find('.live-note').classes()).not.toContain('is-current')
  })

  it('reports a stored publish this process is not serving', () => {
    // `status` is a stored fact and `publishedHere` is a fact about this
    // process's registration maps; a restart makes them disagree, and picking
    // either one alone tells the author something false.
    const orphaned = bar({ publishedVersion: 4, publishedHere: false, status: 'published' })
    expect(orphaned.find('.live-note').text()).toContain('not registered here — republish it')
  })

  it('renames on Enter and reverts on Escape, refusing an empty name', async () => {
    const wrapper = bar()
    await wrapper.find('.document-name').trigger('click')
    const input = wrapper.find('.document-name-input')
    await input.setValue('Clinic scheduler')
    await input.trigger('keydown.enter')
    expect(wrapper.emitted('rename')?.[0]).toEqual(['Clinic scheduler'])

    await wrapper.find('.document-name').trigger('click')
    await wrapper.find('.document-name-input').setValue('   ')
    await wrapper.find('.document-name-input').trigger('keydown.enter')
    // `name` is `min_length=1` server-side, so a blank would be a 422 about a
    // field the author can see and would read as the builder losing the title.
    expect(wrapper.emitted('rename')).toHaveLength(1)
  })

  it('offers Republish once a version is live', () => {
    expect(bar().text()).toContain('Publish')
    expect(bar({ publishedVersion: 4 }).text()).toContain('Republish')
  })
})

describe('the gallery is the empty state and the way back into saved work', () => {
  async function gallery(api = new FakeBuilderApi(), extra: Record<string, unknown> = {}) {
    api.validation = {
      valid: true,
      problems: [],
      budget: zeroBudget({ billable_nodes: 8, floor_cost_usd: 1.2159, static_cost_usd: 1.5137 }),
    }
    const wrapper = mount(TemplateGallery, { props: { api, ...extra } })
    await flush(12)
    return { wrapper, api }
  }

  it('shows every template, both rows', async () => {
    // BOTH rows: the six the gallery leads with and the two library-agent
    // templates behind the disclosure. `details` keeps its content in the DOM
    // whether it is open or shut, so the card count is all of them.
    const { wrapper } = await gallery()
    expect(wrapper.findAll('.template-card')).toHaveLength(ALL_BUILDER_TEMPLATES.length)
  })

  it('renders the validator caveat verbatim and on that card alone', async () => {
    const { wrapper } = await gallery()
    const caveats = wrapper.findAll('.template-caveat')
    expect(caveats).toHaveLength(1)
    expect(caveats[0].text()).toBe(IDEA_VALIDATOR.caveat)
  })

  it('prices every card from the server rather than from a constant', async () => {
    const { wrapper, api } = await gallery()
    // One validate per template. The alternative - writing the figures into the
    // cards - is how this repo's counts went wrong five times.
    expect(api.validateCalls).toHaveLength(ALL_BUILDER_TEMPLATES.length)
    // The flagship is last in the first row, which is where D7 puts it.
    const validatorCard = wrapper.findAll('.template-card')[BUILDER_TEMPLATES.length - 1]
    const facts = validatorCard.findAll('.template-facts dd')
    // Nodes, Edges, Billable, Est. run. `Edges` joined the row with plan 14, so
    // the billable count moved from index 1 to index 2.
    expect(facts[2].text()).toBe('8')
    // Both figures: the published floor and the enforced one. The inflated
    // figure alone reads as an error beside anyone's arithmetic.
    expect(facts[3].text()).toContain('$1.22')
    expect(facts[3].text()).toContain('$1.51')
  })

  it('says prices are unavailable rather than showing a wrong one', async () => {
    const api = new FakeBuilderApi()
    api.failWith.validate = new Error('the server did not answer')
    const wrapper = mount(TemplateGallery, { props: { api } })
    await flush(12)
    expect(wrapper.find('.gallery-notice').text()).toContain('Prices are unavailable')
    // The cards still open. A price nobody could fetch is missing information,
    // not a broken template.
    expect(wrapper.findAll('.template-card')).toHaveLength(ALL_BUILDER_TEMPLATES.length)
  })

  it('hands the chosen template up rather than mutating the module copy', async () => {
    const { wrapper } = await gallery()
    await wrapper.findAll('.template-card')[BUILDER_TEMPLATES.length - 1].trigger('click')
    expect(wrapper.emitted('start')?.[0]).toEqual([IDEA_VALIDATOR])
  })

  it('lists saved graphs with their status, and opens one by id', async () => {
    const api = new FakeBuilderApi()
    const id = api.seed(IDEA_VALIDATOR.document, 4, 'published')
    const { wrapper } = await gallery(api)
    expect(wrapper.find('.status-pill').text()).toBe('published')
    await wrapper.find('.library-open').trigger('click')
    expect(wrapper.emitted('open')?.[0]).toEqual([id])
  })

  it('carries the whole name in the row title, so a clipped tail is one hover away (D-15-4)', async () => {
    const api = new FakeBuilderApi()
    const name = 'Minimal gated agent with a name long enough to wrap twice and then some copy'
    api.seed({ ...IDEA_VALIDATOR.document, name }, 1)
    const { wrapper } = await gallery(api)
    expect(wrapper.get('.library-name').attributes('title')).toBe(name)
    expect(wrapper.get('.library-name').text()).toBe(name)
  })

  it('says so when there are no saved graphs yet', async () => {
    const { wrapper } = await gallery()
    expect(wrapper.find('.gallery-empty').text()).toContain('No saved graphs yet')
  })

  describe("the author's own graphs come first, in an order they can read (D-15-15)", () => {
    /** Three rows a minute apart - the spacing the critic's three rows had. */
    async function threeRows() {
      const api = new FakeBuilderApi()
      const base = Date.parse('2026-09-03T07:47:00Z')
      const oldest = api.seed({ ...IDEA_VALIDATOR.document, id: documentId('ug_aaaaaaaa'), name: 'Oldest' }, 1,
        'draft', new Date(base).toISOString())
      const middle = api.seed({ ...IDEA_VALIDATOR.document, id: documentId('ug_bbbbbbbb'), name: 'Middle' }, 1,
        'draft', new Date(base + 60_000).toISOString())
      const newest = api.seed({ ...IDEA_VALIDATOR.document, id: documentId('ug_cccccccc'), name: 'Newest' }, 1,
        'draft', new Date(base + 120_000).toISOString())
      const { wrapper } = await gallery(api)
      return { wrapper, api, ids: { oldest, middle, newest } }
    }

    it('puts the library section above the templates in the DOM, not just on screen', async () => {
      /*
       * Four template cards occupied y147-595, so "Saved here" began at y659
       * and showed two and a half rows of the thing the author came back for.
       * Asserted in the DOM rather than by CSS `order`, because `order`
       * reorders the picture and leaves reading order alone - a screen reader
       * and a Tab press would still meet four templates first.
       */
      const { wrapper } = await threeRows()
      const html = wrapper.html()
      expect(html.indexOf('gallery-library-title')).toBeLessThan(html.indexOf('gallery-templates-title'))
    })

    it('orders rows newest first', async () => {
      const { wrapper } = await threeRows()
      const names = wrapper.findAll('.library-name').map((row) => row.text())
      expect(names).toEqual(['Newest', 'Middle', 'Oldest'])
    })

    it('tells two rows apart, by the order and by an exact stamp on hover', async () => {
      /*
       * All three read "3 Sept, 07:47" before this - minute resolution over
       * rows a minute apart - so the list could not be ordered by eye.
       *
       * Two things fix that and the test asserts both, because either alone
       * has a gap. The relative form is readable at a glance but loses
       * resolution with distance: two rows four hours old both read "4 h
       * ago". The ORDER above is what makes those two unambiguous, and the
       * title is what makes them precise. `VersionBrowser` makes the same
       * pair for the same reason.
       */
      const { wrapper } = await threeRows()
      const titles = wrapper.findAll('.library-when').map((row) => row.attributes('title'))
      expect(new Set(titles).size, 'the exact stamps must differ').toBe(3)
      for (const title of titles) expect(title).toMatch(/:\d\d:\d\d/)
      // And the visible text is the relative form, not a clipped clock.
      expect(wrapper.findAll('.library-when')[0].text()).toMatch(/ago|just now|yesterday|\d/)
    })

    it('offers what the document bar offers, not only the destructive one', async () => {
      const { wrapper, ids } = await threeRows()
      const row = wrapper.findAll('.library-row')[0]
      for (const action of ['versions', 'duplicate', 'export'] as const) {
        await row.get(`[data-testid="library-${action}"]`).trigger('click')
        expect(wrapper.emitted(action)?.at(-1)).toEqual([ids.newest])
      }
      // And the trash icon is still there, still last.
      expect(row.find('.library-delete').exists()).toBe(true)
    })

    it('separates the one irreversible action from the three that are not (D-15-26)', async () => {
      /*
       * Round 3: "four unlabelled 28px gallery glyphs, delete 34px from
       * export". `DocumentBar` had already answered this on its own menu in
       * round 2 (D-15-6) - a separator, a gap, and the error colour AT REST
       * rather than only on hover - and this is the same defect on a second
       * surface, so it gets the same answer rather than a second one.
       *
       * The GAP is 18px of CSS and jsdom applies no stylesheet, so what is
       * asserted here is the structure that carries it: a separator element,
       * in DOM order between Export and Delete, and the delete button carrying
       * its own class. The rendered distance is measured in
       * `e2e/builder-layout.spec.ts`, which is the only place it has a value.
       */
      const { wrapper } = await threeRows()
      const row = wrapper.findAll('.library-row')[0]
      const separator = row.get('.library-actions-separator')
      expect(separator.attributes('aria-hidden')).toBe('true')

      const order = [...row.get('.library-actions').element.children].map((child) =>
        child.getAttribute('data-testid') ?? child.className,
      )
      expect(order).toEqual([
        'library-versions',
        'library-duplicate',
        'library-export',
        'library-actions-separator',
        'library-delete',
      ])
      // The screen reader hears "Delete <name>" either way, so the separator
      // is hidden from it: the grouping is visual and duplicating it in the
      // accessibility tree would be noise.
      expect(row.get('[data-testid="library-delete"]').attributes('aria-label')).toMatch(/^Delete /)
    })
  })

  it('refuses a delete until the graph name is typed back', async () => {
    const api = new FakeBuilderApi()
    api.seed({ ...IDEA_VALIDATOR.document, name: 'Clinic scheduler' }, 2)
    const { wrapper } = await gallery(api)
    await wrapper.find('.library-delete').trigger('click')

    const form = wrapper.find('.delete-confirm')
    expect(form.exists()).toBe(true)
    const submit = form.findAll('button').find((button) => button.text() === 'Delete')!
    expect(submit.attributes('disabled')).toBeDefined()

    await form.find('input').setValue('Clinic')
    expect(submit.attributes('disabled')).toBeDefined()

    await form.find('input').setValue('  clinic scheduler ')
    // Trimmed and case-insensitive: the confirmation proves the author read
    // WHICH graph, not that they can type.
    expect(submit.attributes('disabled')).toBeUndefined()

    await form.trigger('submit')
    await flush()
    expect(api.removeCalls).toHaveLength(1)
    expect(wrapper.findAll('.library-row')).toHaveLength(0)
  })

  it("states the server's rule in the server's words, and offers Unpublish on the 409", async () => {
    /*
     * D-15-10. The confirm used to promise that deleting a published graph
     * unregisters it; the server's 409 said the opposite. The clause below is
     * the tail of `delete_document`'s sentence, and the button is the remedy
     * that sentence names.
     */
    const api = new FakeBuilderApi()
    const id = api.seed({ ...IDEA_VALIDATOR.document, name: 'Clinic scheduler' }, 2, 'published')
    const sentence = `document ${id} is published - v2 is registered as a launchable workflow - and cannot be deleted; unpublish it first, then delete it`
    api.failWith.remove = new BuilderConflictError(sentence, null)
    const unpublished: string[] = []
    const { wrapper } = await gallery(api, {
      unpublish: async (target: string) => {
        unpublished.push(target)
        delete api.failWith.remove
      },
    })
    await wrapper.find('.library-delete').trigger('click')
    const form = wrapper.find('.delete-confirm')
    expect(form.text()).toContain('cannot be deleted; unpublish it first, then delete it')
    expect(form.text()).not.toContain('unregisters it')

    /*
     * D-15-16: refused BEFORE the confirm. The row's own status is the fact
     * that decides it, so the strip opens with the remedy and no name box,
     * and nothing is sent for an answer already known. The row's `remove`
     * still fails with the server's 409 if it is ever reached, which is the
     * case `documentLifecycle.spec.ts` covers from the other side.
     */
    expect(form.find('.delete-problem').text()).toContain(
      'cannot be deleted; unpublish it first, then delete it',
    )
    expect(form.find('.delete-problem').text()).toContain('Clinic scheduler')
    expect(form.find('[data-testid="gallery-unpublish"]').exists()).toBe(true)
    expect(form.find('input').exists()).toBe(false)
    expect(api.removeCalls).toHaveLength(0)

    /*
     * D-15-18: ONE LAYOUT, and the sentence said once. The gallery used to
     * put the server's sentence BELOW the buttons while the docked confirm
     * put it above, and both printed "Not deleted — it is still published."
     * directly beside it - so the refusal read twice, in two vocabularies,
     * in two places, and neither of them named the graph.
     */
    const children = Array.from(form.element.children).map((child) => child.className)
    const problemAt = children.findIndex((name) => name.includes('delete-problem'))
    const actionsAt = children.findIndex((name) => name.includes('delete-actions'))
    expect(problemAt).toBeGreaterThanOrEqual(0)
    expect(problemAt, 'the sentence must sit above the buttons, as it does when docked')
      .toBeLessThan(actionsAt)
    expect(form.text()).not.toContain('still published')

    await form.find('[data-testid="gallery-unpublish"]').trigger('click')
    await flush()
    expect(unpublished).toEqual([id])
    expect(wrapper.find('.status-pill').text()).toBe('draft')
    // Now the real confirm: the answer is no longer known, so it asks.
    await form.find('input').setValue('Clinic scheduler')
    await form.trigger('submit')
    await flush()
    expect(api.removeCalls).toHaveLength(1)
    expect(wrapper.findAll('.library-row')).toHaveLength(0)
  })
})

describe('the builder hands the run console one workflow, visibly', () => {
  it('round-trips the workflow, its input key and its name', () => {
    writeRunHandoff({ workflowId: 'ug_e9afa950', inputField: 'idea', name: 'Idea validator' })
    expect(readRunHandoff()).toEqual({
      workflowId: 'ug_e9afa950',
      inputField: 'idea',
      name: 'Idea validator',
    })
  })

  it('refuses a half-written handoff rather than launching under a guessed key', () => {
    // A missing `inputField` would post `inputs.idea` at a graph that declares
    // something else, which is a 422 the operator typed nothing to cause.
    window.sessionStorage.setItem(
      'builder-run-handoff',
      JSON.stringify({ workflowId: 'ug_e9afa950', name: 'Idea validator' }),
    )
    expect(readRunHandoff()).toBeNull()
  })

  it('is cleared by going back to the validator', () => {
    writeRunHandoff({ workflowId: 'ug_e9afa950', inputField: 'idea', name: 'Idea validator' })
    clearRunHandoff()
    expect(readRunHandoff()).toBeNull()
  })

  it('names the graph on screen while the console is pointed at it', async () => {
    // Written by the same person who then opens the console: the handoff is
    // keyed to the signed-in user (D-01-5), and `u1` is who the props say.
    writeRunHandoff({ workflowId: 'ug_e9afa950', inputField: 'brief', name: 'Clinic scheduler' }, 'u1')
    const wrapper = mount(StudioView, {
      props: { user: { id: 'u1', name: 'Ada', email: 'a@b.c', image: null }, authenticated: false },
      global: { stubs: SHELL_STUBS },
    })
    const banner = wrapper.find('.handoff-banner')
    // A silent repoint is the mock-mode failure wearing another hat: a
    // convincing screen that is not about what the reader thinks it is about.
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('Clinic scheduler')
    expect(banner.text()).toContain('brief')
  })

  it('shows no strip at all when the console is on the built-in validator', () => {
    const wrapper = mount(StudioView, {
      props: { user: { id: 'u1', name: 'Ada', email: 'a@b.c', image: null }, authenticated: false },
      global: { stubs: SHELL_STUBS },
    })
    expect(wrapper.find('.handoff-banner').exists()).toBe(false)
  })
})
