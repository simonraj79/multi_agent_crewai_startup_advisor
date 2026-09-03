import { mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import BuilderView from '../src/components/builder/BuilderView.vue'
import StudioView from '../src/views/StudioView.vue'
import DocumentBar from '../src/components/builder/DocumentBar.vue'
import ShortcutSheet from '../src/components/builder/ShortcutSheet.vue'
import TemplateGallery from '../src/components/builder/TemplateGallery.vue'
import { BUILDER_TEMPLATES, IDEA_VALIDATOR } from '../src/data/builderTemplates'
import { HOTKEY_BINDINGS } from '../src/composables/useBuilderHotkeys'
import { clearRunHandoff, readRunHandoff, writeRunHandoff } from '../src/data/builderRunHandoff'
import { resetVocabulary } from '../src/data/builderVocabulary'
import { BuilderConflictError } from '../src/services/builderApi'
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

  it('shows all four templates', async () => {
    const { wrapper } = await gallery()
    expect(wrapper.findAll('.template-card')).toHaveLength(BUILDER_TEMPLATES.length)
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
    expect(api.validateCalls).toHaveLength(BUILDER_TEMPLATES.length)
    const facts = wrapper.findAll('.template-card')[3].findAll('.template-facts dd')
    expect(facts[1].text()).toBe('8')
    // Both figures: the published floor and the enforced one. The inflated
    // figure alone reads as an error beside anyone's arithmetic.
    expect(facts[2].text()).toContain('$1.22')
    expect(facts[2].text()).toContain('$1.51')
  })

  it('says prices are unavailable rather than showing a wrong one', async () => {
    const api = new FakeBuilderApi()
    api.failWith.validate = new Error('the server did not answer')
    const wrapper = mount(TemplateGallery, { props: { api } })
    await flush(12)
    expect(wrapper.find('.gallery-notice').text()).toContain('Prices are unavailable')
    // The cards still open. A price nobody could fetch is missing information,
    // not a broken template.
    expect(wrapper.findAll('.template-card')).toHaveLength(BUILDER_TEMPLATES.length)
  })

  it('hands the chosen template up rather than mutating the module copy', async () => {
    const { wrapper } = await gallery()
    await wrapper.findAll('.template-card')[3].trigger('click')
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

    await form.find('input').setValue('Clinic scheduler')
    await form.trigger('submit')
    await flush()
    expect(form.find('.delete-problem').text()).toBe(sentence)
    expect(form.find('[data-testid="gallery-unpublish"]').exists()).toBe(true)
    expect(form.find('input').exists()).toBe(false)

    await form.find('[data-testid="gallery-unpublish"]').trigger('click')
    await flush()
    expect(unpublished).toEqual([id])
    expect(wrapper.find('.status-pill').text()).toBe('draft')
    // Back to asking, with the name kept; one more submit deletes.
    expect((form.find('input').element as HTMLInputElement).value).toBe('Clinic scheduler')
    await form.trigger('submit')
    await flush()
    expect(api.removeCalls).toHaveLength(2)
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
