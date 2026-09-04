import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BuilderView from '../src/components/builder/BuilderView.vue'
import { MINIMAL_GATED_AGENT, documentFromTemplate } from '../src/data/builderTemplates'
import { resetVocabulary } from '../src/data/builderVocabulary'
import { toWire } from '../src/utils/builderSerialize'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { flush } from './helpers'

/**
 * Plan 15 D3 from the document bar: Duplicate, and Delete with its confirm
 * DOCKED under the bar rather than in a dialog (R15) - and criterion 5's
 * client half, the 409 for a published-and-registered document rendered as
 * the server's own sentence with nothing destructive left to press (owner
 * decision 24, built on its recommendation).
 *
 * `window.confirm` is spied on and must never fire. The browser dialog blocks
 * the tab and hides the graph at the moment the author is being asked about
 * it, and it cannot say WHICH graph in a way that survives a misread. Typing
 * the name is what proves the right one was read - the same rule the gallery
 * already applies to its own delete.
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

const DOC = 'ug_1234abcd'
const COPY = 'ug_c0c0c0c0'

function model(id: string, name: string, version = 2, head = 2) {
  return {
    id,
    document: { ...toWire(documentFromTemplate(MINIMAL_GATED_AGENT)), id, version, name },
    status: 'draft',
    version,
    head_version: head,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
    problems: [],
    budget: vocabularyPayload.validation.budget,
    graph: null,
    published: false,
  }
}

interface ServerOptions {
  deleteAnswer?: { status: number; detail: string }
  /** A second delete, after an unpublish, answers this instead. */
  deleteAnswerAfterUnpublish?: { status: number; detail: string }
  /** What the stored document reports itself as. */
  status?: 'draft' | 'published'
}

function stubServer(options: ServerOptions = {}) {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const duplicates: string[] = []
  const deletes: string[] = []
  const unpublishes: string[] = []
  let listCalls = 0
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url.pathname.endsWith('/api/builder/vocabulary')) return json(vocabularyPayload.vocabulary)
    if (url.pathname.endsWith('/api/builder/validate')) return json(vocabularyPayload.validation)
    if (url.pathname === `/api/builder/workflows/${DOC}/duplicate` && method === 'POST') {
      duplicates.push(url.pathname + url.search)
      return json(model(COPY, 'Stored copy', 1, 1), 201)
    }
    if (url.pathname === `/api/builder/workflows/${DOC}/versions`) {
      return json([
        { version: 2, status: 'draft', created_at: '2026-09-02T00:02:00Z', bytes: 10, source: 'saved', name: 'Stored', node_count: 4 },
        { version: 1, status: 'draft', created_at: '2026-09-02T00:01:00Z', bytes: 10, source: 'created', name: 'Stored', node_count: 4 },
      ])
    }
    if (url.pathname === `/api/builder/workflows/${DOC}` && method === 'DELETE') {
      deletes.push(url.pathname)
      // After an unpublish the server's 409 is lifted: answer 204 unless the
      // test says otherwise.
      const answer = unpublishes.length > 0 ? options.deleteAnswerAfterUnpublish : options.deleteAnswer
      if (answer) return json({ detail: answer.detail }, answer.status)
      return new Response(null, { status: 204 })
    }
    if (url.pathname === `/api/builder/workflows/${DOC}/unpublish` && method === 'POST') {
      unpublishes.push(url.pathname)
      return json({ ...model(DOC, 'Stored', 2, 2), status: 'draft', published: false })
    }
    if (url.pathname === `/api/builder/workflows/${DOC}` && method === 'GET') {
      const at = url.searchParams.get('version')
      const stored = model(DOC, 'Stored', at ? Number(at) : 2, 2)
      if (options.status === 'published') return json({ ...stored, status: 'published', published: true })
      return json(stored)
    }
    if (url.pathname === '/api/builder/workflows' && method === 'GET') {
      listCalls += 1
      return json([])
    }
    return json({ detail: `unstubbed ${method} ${url.pathname}` }, 404)
  })
  vi.stubGlobal('fetch', fetch)
  return {
    fetch,
    duplicates,
    deletes,
    unpublishes,
    get listCalls() {
      return listCalls
    },
  }
}

async function settled(): Promise<void> {
  await flush(6)
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flush(6)
}

async function mountStored() {
  const wrapper = mount(BuilderView, { props: { documentId: DOC as never }, global: { stubs: STUBS } })
  await settled()
  return wrapper
}

async function choose(wrapper: ReturnType<typeof mount>, item: string): Promise<void> {
  await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
  await flush(2)
  await wrapper.get(`[data-testid="${item}"]`).trigger('click')
  await settled()
}

async function makeDirty(wrapper: ReturnType<typeof mount>): Promise<void> {
  await wrapper.get('.document-name').trigger('click')
  await flush(2)
  await wrapper.get('.document-name-input').setValue('Edited but not saved')
  await wrapper.get('.document-name-input').trigger('blur')
  await flush(4)
}

let confirmSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  window.localStorage.clear()
  resetVocabulary()
  confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetVocabulary()
  window.localStorage.clear()
})

/* --- duplicate ------------------------------------------------------------- */

describe('Duplicate', () => {
  it('POSTs to the duplicate route and opens the copy through the route, so Back returns', async () => {
    const server = stubServer()
    const wrapper = await mountStored()
    const listsBefore = server.listCalls

    await choose(wrapper, 'menu-duplicate')

    expect(server.duplicates).toEqual([`/api/builder/workflows/${DOC}/duplicate`])
    // A PUSH, by way of `openDocument` rather than `adoptDocument`: the copy is
    // a second document, and Back should land on the first.
    expect(wrapper.emitted('openDocument')).toEqual([[COPY]])
    expect(wrapper.emitted('adoptDocument')).toBeUndefined()
    expect(server.listCalls).toBeGreaterThan(listsBefore)
    expect(wrapper.get('.builder-notice').text()).toContain('Stored copy')
    wrapper.unmount()
  })

  it('copies the version on screen while an older one is being viewed', async () => {
    const server = stubServer()
    const wrapper = await mountStored()
    await choose(wrapper, 'menu-versions')
    await wrapper.get('[data-testid="version-row-1"]').trigger('click')
    await settled()

    await choose(wrapper, 'menu-duplicate')

    expect(server.duplicates).toEqual([`/api/builder/workflows/${DOC}/duplicate?version=1`])
    wrapper.unmount()
  })

  it('refuses while the canvas is ahead of the store, and says so', async () => {
    const server = stubServer()
    const wrapper = await mountStored()
    await makeDirty(wrapper)

    await choose(wrapper, 'menu-duplicate')

    expect(server.duplicates).toEqual([])
    expect(wrapper.emitted('openDocument')).toBeUndefined()
    expect(wrapper.get('.builder-notice').text()).toContain('save your changes first')
    wrapper.unmount()
  })

  it('keeps a refusal on screen and lets a success retire itself (D-15-22)', async () => {
    /*
     * Every refusal on the import, duplicate, export, restore and
     * open-version paths cleared after four seconds and left no surface
     * anywhere to re-read the server's sentence, while delete's docked
     * confirm and a save conflict both kept theirs. An operator who looked
     * away lost the one thing telling them what to do.
     *
     * Fake timers rather than a wait: what is asserted is the RULE, and 4000
     * and 8000 are the two figures `say()` uses.
     */
    const server = stubServer()
    const wrapper = await mountStored()
    await makeDirty(wrapper)

    /*
     * A spy that RECORDS rather than replaces: `vi.spyOn` keeps the original,
     * so Vue's own scheduling is untouched. Fake timers were tried first and
     * are the wrong instrument here - `mountStored` awaits real work, and
     * installing them around it hung eleven tests in this file.
     *
     * `say()`'s two retirement delays are 4000 and 8000. Arming neither is
     * the whole property.
     */
    const timers = vi.spyOn(window, 'setTimeout')
    await choose(wrapper, 'menu-duplicate')

    expect(server.duplicates).toEqual([])
    const refusal = wrapper.get('.builder-notice')
    expect(refusal.text()).toContain('save your changes first')
    expect(refusal.classes()).toContain('is-error')
    const retirements = timers.mock.calls.filter(([, ms]) => ms === 4000 || ms === 8000)
    expect(retirements).toEqual([])
    timers.mockRestore()

    // It goes when the operator says so, which is the other half of
    // "until dismissed or until their next action".
    await wrapper.get('[data-testid="notice-dismiss"]').trigger('click')
    await flush(2)
    expect(wrapper.find('.builder-notice').exists()).toBe(false)
    wrapper.unmount()
  })

  it('is disabled for a draft nothing has stored', async () => {
    stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()
    await wrapper.findAll('.template-card')[0].trigger('click')
    await settled()

    await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
    await flush(2)
    expect(wrapper.get('[data-testid="menu-duplicate"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="menu-delete"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})

/* --- delete ------------------------------------------------------------------ */

describe('Delete', () => {
  it('confirms in the dock, gated on the typed name, and never through window.confirm', async () => {
    const server = stubServer()
    const wrapper = await mountStored()

    await choose(wrapper, 'menu-delete')

    const confirm = wrapper.get('[data-testid="delete-confirm"]')
    // Docked under the bar, in the layout. Not a dialog, not the browser's.
    expect(wrapper.get('[data-testid="builder-dock"]').find('[data-testid="delete-confirm"]').exists()).toBe(true)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(confirm.text()).toContain('Delete Stored and every stored version')
    expect(confirm.text()).not.toContain('unregisters it')
    /*
     * D-15-16: this document is a DRAFT, so the strip says nothing about
     * publishing. It used to carry "A published graph cannot be deleted;
     * unpublish it first" on every confirm - a sentence that cannot apply to
     * what is on screen here, and the only warning there was, so on a graph
     * that really was published the author learnt the truth after typing the
     * name. The publish rule is still the server's own words; it is now said
     * where it is true, which is the refused branch below.
     */
    expect(confirm.text()).not.toContain('unpublish it first')
    expect(confirm.get('[data-testid="delete-submit"]').attributes('disabled')).toBeDefined()

    // The wrong name keeps it disabled; the right one, trimmed and
    // case-insensitive, enables it. Proof of reading, not of typing.
    await confirm.get('[data-testid="delete-name"]').setValue('Something else')
    expect(confirm.get('[data-testid="delete-submit"]').attributes('disabled')).toBeDefined()
    await confirm.get('[data-testid="delete-name"]').setValue('  stored ')
    expect(confirm.get('[data-testid="delete-submit"]').attributes('disabled')).toBeUndefined()
    expect(server.deletes).toEqual([])
    expect(confirmSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('DELETEs the row, returns to the gallery, and hands the address back', async () => {
    const server = stubServer()
    const wrapper = await mountStored()
    const listsBefore = server.listCalls
    await choose(wrapper, 'menu-delete')
    await wrapper.get('[data-testid="delete-name"]').setValue('Stored')
    await wrapper.get('[data-testid="delete-confirm"]').trigger('submit')
    await settled()

    expect(server.deletes).toEqual([`/api/builder/workflows/${DOC}`])
    expect(wrapper.find('[data-testid="delete-confirm"]').exists()).toBe(false)
    expect(wrapper.find('.builder-canvas').exists()).toBe(false)
    expect(wrapper.find('.template-card').exists()).toBe(true)
    expect(wrapper.emitted('closeDocument')).toHaveLength(1)
    expect(server.listCalls).toBeGreaterThan(listsBefore)
    expect(confirmSpy).not.toHaveBeenCalled()

    // Nothing about the deleted graph arms the unload guard.
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(false)
    wrapper.unmount()
  })

  it('renders a 409 for a registered graph verbatim and offers only the remedy it names', async () => {
    const sentence = `document ${DOC} is published - v1 is registered as a launchable workflow - and cannot be deleted; unpublish it first, then delete it`
    const server = stubServer({ deleteAnswer: { status: 409, detail: sentence } })
    const wrapper = await mountStored()
    await choose(wrapper, 'menu-delete')
    await wrapper.get('[data-testid="delete-name"]').setValue('Stored')
    await wrapper.get('[data-testid="delete-confirm"]').trigger('submit')
    await settled()

    const confirm = wrapper.get('[data-testid="delete-confirm"]')
    expect(confirm.get('[data-testid="delete-problem"]').text()).toBe(sentence)
    expect(confirm.get('[data-testid="delete-problem"]').attributes('role')).toBe('alert')
    // D-15-18: the server's sentence, once. The "Not deleted — it is still
    // published." line that used to sit above it said the same thing in
    // different words and named no graph.
    expect(confirm.text()).not.toContain('still published')
    // The Delete button and the box are GONE, not disabled: resending cannot
    // lift a 409. What is offered is the one thing that can (D-15-10).
    expect(confirm.find('[data-testid="delete-submit"]').exists()).toBe(false)
    expect(confirm.find('[data-testid="delete-name"]').exists()).toBe(false)
    expect(confirm.get('[data-testid="delete-unpublish"]').text()).toContain('Unpublish')
    expect(confirm.get('[data-testid="delete-cancel"]').text()).toBe('Keep it published')

    // Submitting the form again sends nothing.
    await confirm.trigger('submit')
    await settled()
    expect(server.deletes).toHaveLength(1)
    expect(server.unpublishes).toHaveLength(0)

    // And the document is still open, still addressed.
    expect(wrapper.find('.builder-canvas').exists()).toBe(true)
    expect(wrapper.emitted('closeDocument')).toBeUndefined()

    await confirm.get('[data-testid="delete-cancel"]').trigger('click')
    await flush(2)
    expect(wrapper.find('[data-testid="delete-confirm"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('refuses a published graph BEFORE the confirm, then Unpublish opens the real one (D-15-16)', async () => {
    /*
     * The refusal used to arrive after the work: the strip asked for the
     * name, the author typed it, pressed Delete, and only then met the 409.
     * The state that decides it is on screen the whole time, so the strip
     * now opens in its refused state with the remedy and no name box, and
     * NO DELETE IS SENT. The server is still the authority - see the test
     * below, where the client believes it is a draft and the server says
     * otherwise.
     */
    const server = stubServer({
      deleteAnswer: undefined,
      deleteAnswerAfterUnpublish: undefined,
      status: 'published',
    })
    const wrapper = await mountStored()
    await choose(wrapper, 'menu-delete')

    const refused = wrapper.get('[data-testid="delete-confirm"]')
    expect(refused.find('[data-testid="delete-name"]').exists()).toBe(false)
    expect(refused.get('[data-testid="delete-problem"]').text()).toContain(
      'cannot be deleted; unpublish it first, then delete it',
    )
    // Named, not identified by row id (D-15-18's rule, applied client-side).
    expect(refused.get('[data-testid="delete-problem"]').text()).toContain('Stored')
    expect(refused.get('[data-testid="delete-problem"]').text()).not.toContain(DOC)
    expect(server.deletes, 'nothing was sent for an answer already known').toHaveLength(0)

    await wrapper.get('[data-testid="delete-unpublish"]').trigger('click')
    await settled()

    expect(server.unpublishes).toEqual([`/api/builder/workflows/${DOC}/unpublish`])
    const confirm = wrapper.get('[data-testid="delete-confirm"]')
    // The real confirm, now that the answer is no longer known: a name box
    // and nothing destructive pressed for the author.
    expect(confirm.find('[data-testid="delete-problem"]').exists()).toBe(false)
    expect(confirm.find('[data-testid="delete-name"]').exists()).toBe(true)
    expect(server.deletes).toHaveLength(0)

    await confirm.get('[data-testid="delete-name"]').setValue('Stored')
    await confirm.trigger('submit')
    await settled()
    expect(server.deletes).toHaveLength(1)
    expect(wrapper.find('[data-testid="delete-confirm"]').exists()).toBe(false)
    expect(wrapper.emitted('closeDocument')).toHaveLength(1)
    wrapper.unmount()
  })

  it('still lets the server have the last word when the client thought it was a draft', async () => {
    /*
     * The client-side refusal is an early answer, never the answer. A graph
     * published from another tab reads as a draft in this one, so the strip
     * asks properly, the DELETE goes, and the 409 is handled exactly as it
     * was before D-15-16 - which is what keeps that fix a convenience rather
     * than a second source of truth.
     */
    const sentence = '“Stored” is live as v1 and cannot be deleted; unpublish it first, then delete it'
    const server = stubServer({ deleteAnswer: { status: 409, detail: sentence } })
    const wrapper = await mountStored()

    await choose(wrapper, 'menu-delete')
    const confirm = wrapper.get('[data-testid="delete-confirm"]')
    // It asked, because as far as this tab knows there is nothing to refuse.
    expect(confirm.find('[data-testid="delete-name"]').exists()).toBe(true)
    await confirm.get('[data-testid="delete-name"]').setValue('Stored')
    await confirm.trigger('submit')
    await settled()

    expect(server.deletes).toHaveLength(1)
    expect(confirm.get('[data-testid="delete-problem"]').text()).toBe(sentence)
    expect(confirm.find('[data-testid="delete-unpublish"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('Unpublish in the menu POSTs the same route and the bar stops calling the version live', async () => {
    const server = stubServer({ status: 'published' })
    const wrapper = await mountStored()
    expect(wrapper.text()).toContain('is live')

    const timers = vi.spyOn(window, 'setTimeout')
    await choose(wrapper, 'menu-unpublish')
    // A success DOES arm its retirement (D-15-22's other half).
    expect(timers.mock.calls.some(([, ms]) => ms === 4000 || ms === 8000)).toBe(true)
    timers.mockRestore()

    expect(server.unpublishes).toEqual([`/api/builder/workflows/${DOC}/unpublish`])
    expect(wrapper.text()).not.toContain('is live')
    expect(wrapper.find('.builder-notice').text()).toContain('unpublished')
    // A SUCCESS still retires itself (D-15-22): only refusals persist, or a
    // console that accumulates green receipts teaches an operator to stop
    // reading the bar.
    expect(wrapper.get('.builder-notice').classes()).toContain('is-success')
    // The document, its history and its address are untouched.
    expect(wrapper.find('.builder-canvas').exists()).toBe(true)
    expect(wrapper.emitted('closeDocument')).toBeUndefined()
    wrapper.unmount()
  })

  it('offers Unpublish only when something is known to be published', async () => {
    stubServer()
    const wrapper = await mountStored()
    await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
    await flush(2)
    expect(wrapper.get('[data-testid="menu-unpublish"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('keeps the retry for a refusal that is not the 409', async () => {
    const server = stubServer({ deleteAnswer: { status: 503, detail: 'the service is restarting' } })
    const wrapper = await mountStored()
    await choose(wrapper, 'menu-delete')
    await wrapper.get('[data-testid="delete-name"]').setValue('Stored')
    await wrapper.get('[data-testid="delete-confirm"]').trigger('submit')
    await settled()

    const confirm = wrapper.get('[data-testid="delete-confirm"]')
    expect(confirm.get('[data-testid="delete-problem"]').text()).toBe('the service is restarting')
    expect(confirm.get('[data-testid="delete-submit"]').attributes('disabled')).toBeUndefined()
    expect(confirm.get('[data-testid="delete-cancel"]').text()).toBe('Keep it')

    await confirm.trigger('submit')
    await settled()
    expect(server.deletes).toHaveLength(2)
    wrapper.unmount()
  })

  it('closes on Keep it and on Escape without sending anything', async () => {
    const server = stubServer()
    const wrapper = await mountStored()

    await choose(wrapper, 'menu-delete')
    await wrapper.get('[data-testid="delete-cancel"]').trigger('click')
    await flush(2)
    expect(wrapper.find('[data-testid="delete-confirm"]').exists()).toBe(false)

    await choose(wrapper, 'menu-delete')
    expect(wrapper.find('[data-testid="delete-confirm"]').exists()).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flush(4)
    expect(wrapper.find('[data-testid="delete-confirm"]').exists()).toBe(false)

    expect(server.deletes).toEqual([])
    wrapper.unmount()
  })
})

/* --- the menu itself --------------------------------------------------------- */

describe('the overflow menu', () => {
  it('opens as a menu, closes on a choice, on Escape and on a pointer landing elsewhere', async () => {
    stubServer()
    const wrapper = await mountStored()
    const button = wrapper.get('[data-testid="document-menu-button"]')
    expect(button.attributes('aria-haspopup')).toBe('menu')
    expect(button.attributes('aria-expanded')).toBe('false')

    await button.trigger('click')
    await flush(2)
    const menu = wrapper.get('[data-testid="document-menu"]')
    expect(menu.attributes('role')).toBe('menu')
    // D-15-6: Delete is set apart by a rule and wears the error colour's class
    // at rest; it is the last item and the only one after the separator.
    const separator = menu.get('[data-testid="menu-separator"]')
    expect(separator.attributes('role')).toBe('separator')
    expect(separator.element.nextElementSibling?.getAttribute('data-testid')).toBe('menu-delete')
    expect(menu.get('[data-testid="menu-delete"]').classes()).toContain('is-danger')
    expect(menu.findAll('[data-testid="menu-separator"]')).toHaveLength(1)
    expect(menu.findAll('[role="menuitem"]').map((item) => item.attributes('data-testid'))).toEqual([
      // Save leads (D-15-13): the bar's icon covers the common case, and an
      // author who opened the menu looking for it should not find every
      // action except that one.
      'menu-save',
      'menu-versions',
      'menu-export',
      'menu-import',
      'menu-duplicate',
      'menu-unpublish',
      'menu-delete',
    ])
    expect(button.attributes('aria-expanded')).toBe('true')

    await menu.trigger('keydown', { key: 'Escape' })
    await flush(2)
    expect(wrapper.find('[data-testid="document-menu"]').exists()).toBe(false)

    await button.trigger('click')
    await flush(2)
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await flush(2)
    expect(wrapper.find('[data-testid="document-menu"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
