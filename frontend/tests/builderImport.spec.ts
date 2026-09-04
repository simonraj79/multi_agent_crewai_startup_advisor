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
 * Plan 15 D2 and criterion 2, the client half, under ruling S1-7: import is a
 * SERVER route. The client reads the file, checks the two facts that make it
 * an export, POSTs the envelope to `/api/builder/workflows/import`, opens the
 * 201 through the same `persistence.adopt` a route open uses, and renders
 * `needs_credentials` as a notice group pointing at each node.
 *
 * Two entry points - the gallery and the document bar - and one code path.
 * Both are driven here through a real `File` on a real `<input type="file">`,
 * because a test that called `importFile` directly would prove the function
 * and leave the picker, the `change` handler and the reset unproved: the
 * exact place where "the same file cannot be picked twice" would hide.
 *
 * What is asserted about the notice is that it is NOT a problem code: the
 * problems dock's `role="log"` never carries it, and it has no `code`. C8's
 * union is a Python-generated mirror; a client-side code would be the second
 * declaration the fixtures exist to forbid.
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
}

const IMPORTED_ID = 'ug_9999beef'
const EXISTING_ID = 'ug_1234abcd'

const EXPORTED_DOCUMENT = {
  ...(toWire(documentFromTemplate(MINIMAL_GATED_AGENT)) as unknown as Record<string, unknown>),
  name: 'Brought in from a file',
  // Not a v1 field. It must reach the server untouched: judging the document
  // is `POST /import`'s job, and a client that dropped it would be quietly
  // editing the author's file on the way in.
  future_field: { kept: true },
}

const ENVELOPE = {
  export: 'builder.flow/v1',
  exported_at: '2026-09-02T10:14:00Z',
  name: 'Brought in from a file',
  source_version: 4,
  needs_credentials: ['draft', 'confirm'],
  document: EXPORTED_DOCUMENT,
}

function model(id: string, document: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return {
    id,
    document: { ...document, id, version: 1 },
    status: 'draft',
    version: 1,
    head_version: 1,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: '2026-09-02T00:00:00Z',
    problems: [],
    budget: vocabularyPayload.validation.budget,
    graph: null,
    published: false,
    ...extra,
  }
}

interface ServerOptions {
  /** What `POST /import` answers instead of a 201. */
  importRefusal?: { status: number; detail: string }
}

function stubServer(options: ServerOptions = {}) {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const imports: Array<Record<string, unknown>> = []
  let listCalls = 0
  let validates = 0
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url.pathname.endsWith('/api/builder/vocabulary')) return json(vocabularyPayload.vocabulary)
    if (url.pathname.endsWith('/api/builder/validate')) {
      validates += 1
      return json(vocabularyPayload.validation)
    }
    if (url.pathname === '/api/builder/workflows/import' && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      imports.push(body)
      if (options.importRefusal) {
        return json({ detail: options.importRefusal.detail }, options.importRefusal.status)
      }
      return json(
        model(IMPORTED_ID, body.document as Record<string, unknown>, {
          needs_credentials: (body.needs_credentials as string[]) ?? [],
        }),
        201,
      )
    }
    if (url.pathname === `/api/builder/workflows/${EXISTING_ID}` && method === 'GET') {
      return json(
        model(EXISTING_ID, {
          ...(toWire(documentFromTemplate(MINIMAL_GATED_AGENT)) as unknown as Record<string, unknown>),
          name: 'Already open',
        }),
      )
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
    imports,
    get listCalls() {
      return listCalls
    },
    get validates() {
      return validates
    },
  }
}

async function settled(): Promise<void> {
  await flush(6)
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flush(6)
}

/** Put a File on a hidden picker and fire `change`, the way the browser does. */
async function pick(wrapper: ReturnType<typeof mount>, testid: string, file: File): Promise<void> {
  const input = wrapper.get(`[data-testid="${testid}"]`)
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await settled()
  await settled()
}

const exportFile = (body: unknown = ENVELOPE, name = 'brief.builder.json') =>
  new File([typeof body === 'string' ? body : JSON.stringify(body)], name, { type: 'application/json' })

beforeEach(() => {
  window.localStorage.clear()
  resetVocabulary()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetVocabulary()
  window.localStorage.clear()
})

describe('import from the gallery', () => {
  it('POSTs the envelope, opens the 201 as a new draft, and the address follows', async () => {
    const server = stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()
    expect(wrapper.find('[data-testid="gallery-import"]').exists()).toBe(true)

    await pick(wrapper, 'gallery-import-file', exportFile())

    // The envelope went as the file said it, the document inside untouched.
    expect(server.imports).toHaveLength(1)
    expect(server.imports[0].export).toBe('builder.flow/v1')
    expect(server.imports[0].needs_credentials).toEqual(['draft', 'confirm'])
    expect((server.imports[0].document as Record<string, unknown>).future_field).toEqual({ kept: true })

    // Opened through the one load path: the canvas is up, the chip says the
    // server's version, the compiler was asked about it, and the address was
    // told - the same way it is after a first save.
    expect(wrapper.find('.builder-canvas').exists()).toBe(true)
    expect(wrapper.get('.document-name').text()).toBe('Brought in from a file')
    expect(wrapper.get('[data-testid="save-chip"]').text()).toContain('saved · v1')
    expect(server.validates).toBeGreaterThan(0)
    expect(wrapper.emitted('adoptDocument')).toEqual([[IMPORTED_ID]])
    expect(server.listCalls).toBeGreaterThan(1)
    wrapper.unmount()
  })

  it('renders needs_credentials as a notice group pointing at each node, not as a problem', async () => {
    stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()

    await pick(wrapper, 'gallery-import-file', exportFile())

    const notice = wrapper.get('[data-testid="import-notice"]')
    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('2 nodes need a credential you own')
    // Docked, in the layout above the canvas - never over it (R15).
    expect(wrapper.get('[data-testid="builder-dock"]').find('[data-testid="import-notice"]').exists()).toBe(true)
    // One chip per node, labelled by the node's own label.
    expect(wrapper.get('[data-testid="import-notice-node-draft"]').text()).toBe('Draft')
    expect(wrapper.get('[data-testid="import-notice-node-confirm"]').text()).toBe('Confirm the request')
    // NOT a C8 problem: the problems dock never carries it, and it has no code.
    expect(wrapper.get('[role="log"]').text()).not.toContain('credential')
    expect(notice.find('code').exists()).toBe(false)

    // A chip selects its node - the inspector binds to it.
    await wrapper.get('[data-testid="import-notice-node-draft"]').trigger('click')
    await flush(4)
    expect(wrapper.get('[data-testid="inspector-rail"]').text()).toContain('Draft')

    await wrapper.get('[data-testid="import-notice-dismiss"]').trigger('click')
    await flush(2)
    expect(wrapper.find('[data-testid="import-notice"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('offers the one thing to do, and it opens the picker on the first node (D-15-19)', async () => {
    /*
     * The chips navigate; this is the ACTION. `InspectorRail.focusField` was
     * written for exactly this journey and had no caller anywhere in `src/`
     * until the notice became reachable at all - which it was not, because
     * the server answered `needs_credentials: []` for the very file the
     * export wrote.
     */
    stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()
    await pick(wrapper, 'gallery-import-file', exportFile())

    const fix = wrapper.get('[data-testid="import-notice-fix"]')
    expect(fix.text()).toBe('Choose a key')
    await fix.trigger('click')
    await flush(6)

    // The FIRST named node is selected, so the form the credential row lives
    // on is the one on screen.
    expect(wrapper.get('[data-testid="inspector-rail"]').text()).toContain('Draft')
    wrapper.unmount()
  })

  it('says what it imported in full, as a success, with a dismiss (D-15-5)', async () => {
    /*
     * Round 1's capture: `imported alice.builder.json as a new draft, "Minimal
     * g…` - a bare string, no icon, no dismiss, truncated on the one fact that
     * finds the new row in a library that had just gained a second row by that
     * name. The name is asserted whole, and the toast is asserted to be one.
     */
    const server = stubServer()
    const wrapper = mount(BuilderView, { global: { stubs: STUBS } })
    await settled()
    await pick(wrapper, 'gallery-import-file', exportFile(ENVELOPE, 'alice.builder.json'))

    const toast = wrapper.get('[data-testid="builder-notice"]')
    expect(toast.classes()).toContain('is-success')
    expect(toast.attributes('role')).toBe('status')
    expect(toast.get('.builder-notice-text').text()).toBe(
      'imported alice.builder.json as a new draft, “Brought in from a file”.',
    )
    expect(toast.get('.builder-notice-text').attributes('title')).toContain('Brought in from a file')
    expect(toast.find('svg').exists()).toBe(true)
    expect(server.imports).toHaveLength(1)

    await toast.get('[data-testid="notice-dismiss"]').trigger('click')
    await flush(2)
    expect(wrapper.find('[data-testid="builder-notice"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows no notice when every node arrived with what it needs', async () => {
    stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()

    await pick(wrapper, 'gallery-import-file', exportFile({ ...ENVELOPE, needs_credentials: [] }))

    expect(wrapper.find('.builder-canvas').exists()).toBe(true)
    expect(wrapper.find('[data-testid="import-notice"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('refuses a file that is not an export, naming the file, and sends nothing', async () => {
    const server = stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()

    await pick(wrapper, 'gallery-import-file', exportFile({ nodes: [], edges: [] }, 'package.json'))

    expect(server.imports).toEqual([])
    expect(wrapper.get('.builder-notice').text()).toContain('package.json is not a builder export')
    expect(wrapper.get('.builder-notice').text()).toContain('"export" field is missing')
    // The gallery is still the screen; nothing was opened.
    expect(wrapper.find('.template-card').exists()).toBe(true)
    expect(wrapper.find('.builder-canvas').exists()).toBe(false)
    wrapper.unmount()
  })

  it('refuses a file that is not JSON the same way', async () => {
    const server = stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()

    await pick(wrapper, 'gallery-import-file', exportFile('{ not json', 'broken.builder.json'))

    expect(server.imports).toEqual([])
    expect(wrapper.get('.builder-notice').text()).toContain('broken.builder.json is not JSON')
    wrapper.unmount()
  })

  it('renders the server refusal in its own words, and opens nothing', async () => {
    const server = stubServer({
      importRefusal: { status: 422, detail: 'nodes.2.config.max_iter: Input should be less than or equal to 8' },
    })
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()

    await pick(wrapper, 'gallery-import-file', exportFile())

    expect(server.imports).toHaveLength(1)
    const notice = wrapper.get('.builder-notice').text()
    expect(notice).toContain('brief.builder.json was not imported')
    expect(notice).toContain('nodes.2.config.max_iter: Input should be less than or equal to 8')
    expect(notice).not.toContain('{')
    expect(wrapper.find('.builder-canvas').exists()).toBe(false)
    expect(wrapper.emitted('adoptDocument')).toBeUndefined()
    wrapper.unmount()
  })

  it('lets the same file be picked twice', async () => {
    const server = stubServer({ importRefusal: { status: 422, detail: 'refused once' } })
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()

    await pick(wrapper, 'gallery-import-file', exportFile())
    // The picker was cleared after the first choice, so the browser will fire
    // `change` for the same file again - a fixed export re-picked must land.
    expect((wrapper.get('[data-testid="gallery-import-file"]').element as HTMLInputElement).value).toBe('')
    await pick(wrapper, 'gallery-import-file', exportFile())

    expect(server.imports).toHaveLength(2)
    wrapper.unmount()
  })
})

describe('import from the document bar', () => {
  it('takes the same path over an open document and replaces it with the new draft', async () => {
    const server = stubServer()
    const wrapper = mount(BuilderView, {
      props: { documentId: EXISTING_ID as never },
      global: { stubs: STUBS },
    })
    await settled()
    expect(wrapper.get('.document-name').text()).toBe('Already open')

    await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
    await wrapper.get('[data-testid="menu-import"]').trigger('click')
    await pick(wrapper, 'import-file', exportFile())

    expect(server.imports).toHaveLength(1)
    expect(wrapper.get('.document-name').text()).toBe('Brought in from a file')
    expect(wrapper.get('[data-testid="save-chip"]').text()).toContain('saved · v1')
    expect(wrapper.get('[data-testid="import-notice"]').text()).toContain('2 nodes need a credential')
    expect(wrapper.emitted('adoptDocument')).toEqual([[IMPORTED_ID]])
    wrapper.unmount()
  })

  it('leaves the open document untouched when the file is refused', async () => {
    const server = stubServer()
    const wrapper = mount(BuilderView, {
      props: { documentId: EXISTING_ID as never },
      global: { stubs: STUBS },
    })
    await settled()

    await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
    await wrapper.get('[data-testid="menu-import"]').trigger('click')
    await pick(wrapper, 'import-file', exportFile('[]', 'list.json'))

    expect(server.imports).toEqual([])
    expect(wrapper.get('.document-name').text()).toBe('Already open')
    expect(wrapper.get('[data-testid="save-chip"]').text()).toContain('saved · v1')
    expect(wrapper.get('.builder-notice').text()).toContain('list.json is not a builder export')
    wrapper.unmount()
  })
})
