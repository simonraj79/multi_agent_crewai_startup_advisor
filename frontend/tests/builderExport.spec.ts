import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BuilderView from '../src/components/builder/BuilderView.vue'
import { MINIMAL_GATED_AGENT, documentFromTemplate } from '../src/data/builderTemplates'
import { resetVocabulary } from '../src/data/builderVocabulary'
import { EXPORT_SCHEMAS } from '../src/types/builder'
import type { BuilderExportEnvelope } from '../src/types/builder'
import {
  EXPORT_FILE_SUFFIX,
  ExportFileError,
  downloadExport,
  exportFilename,
  parseExportEnvelope,
  readExportFile,
} from '../src/utils/builderExport'
import { toWire } from '../src/utils/builderSerialize'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { flush } from './helpers'

/**
 * Plan 15 D1 on the client: a stored document leaves as `<name>.builder.json`
 * through the one blob-URL path `downloadLogs` already pins, and D2's first
 * half: the two facts that decide whether a file is a builder export at all.
 *
 * What is NOT here, deliberately. Nothing validates the document inside the
 * envelope - `POST /import` does, and answers 422 in its own words - and
 * nothing strips a secret on this side, because `strip_for_export` runs on
 * the server before the bytes exist (criterion 1, `tests/builder/test_export.py`).
 * A client that re-checked either would be the second opinion §6.1 forbids.
 */

const ENVELOPE: BuilderExportEnvelope = {
  export: 'builder.flow/v1',
  exported_at: '2026-09-02T10:14:00Z',
  name: 'Clinic scheduling brief',
  source_version: 7,
  needs_credentials: ['search', 'docs_mcp'],
  document: toWire(documentFromTemplate(MINIMAL_GATED_AGENT)) as unknown as Record<string, unknown>,
}

/* --- the envelope check ---------------------------------------------------- */

describe('parseExportEnvelope', () => {
  it('accepts every schema the importer admits, v1 today and v2 the day C1 lands', () => {
    // Ruling S1-4: `export` carries the document's own `schema`, so a file
    // written today says v1 and one written after 03 says v2. Both import.
    expect(EXPORT_SCHEMAS).toEqual(['builder.flow/v1', 'builder.flow/v2'])
    for (const schema of EXPORT_SCHEMAS) {
      const parsed = parseExportEnvelope(JSON.stringify({ ...ENVELOPE, export: schema }), 'a.builder.json')
      expect(parsed.export).toBe(schema)
      expect(parsed.document).toEqual(ENVELOPE.document)
      expect(parsed.needs_credentials).toEqual(['search', 'docs_mcp'])
    }
  })

  it('refuses a file that is not JSON, naming the file', () => {
    expect(() => parseExportEnvelope('{not json', 'notes.builder.json')).toThrow(ExportFileError)
    expect(() => parseExportEnvelope('{not json', 'notes.builder.json')).toThrow(
      'notes.builder.json is not JSON',
    )
  })

  it('refuses JSON that is not an object', () => {
    expect(() => parseExportEnvelope('[1, 2]', 'list.json')).toThrow('list.json is not a builder export')
    expect(() => parseExportEnvelope('null', 'null.json')).toThrow('null.json is not a builder export')
  })

  it('refuses the wrong export field, saying what it found and what it wanted', () => {
    // A run log, a clipboard envelope, somebody's package.json: all JSON, all
    // objects, none an export. The sentence names the field so the author is
    // not sent to `POST /import` for a 422 about a field they never typed.
    const clipboard = JSON.stringify({ __builder: 'builder.flow/v1', nodes: [], document: {} })
    expect(() => parseExportEnvelope(clipboard, 'fragment.json')).toThrow(
      'fragment.json is not a builder export: its "export" field is missing, not one of builder.flow/v1, builder.flow/v2.',
    )
    const future = JSON.stringify({ ...ENVELOPE, export: 'builder.flow/v9' })
    expect(() => parseExportEnvelope(future, 'later.builder.json')).toThrow('is "builder.flow/v9"')
  })

  it('refuses an envelope with nothing to import', () => {
    expect(() => parseExportEnvelope(JSON.stringify({ export: 'builder.flow/v1' }), 'empty.builder.json')).toThrow(
      'empty.builder.json carries no "document" to import.',
    )
    expect(() =>
      parseExportEnvelope(JSON.stringify({ export: 'builder.flow/v1', document: [] }), 'arr.builder.json'),
    ).toThrow('carries no "document"')
  })

  it('defaults what is not one of the two facts, and never invents a document', () => {
    const minimal = JSON.stringify({ export: 'builder.flow/v1', document: { name: 'X', nodes: [] } })
    const parsed = parseExportEnvelope(minimal, 'hand-written.builder.json')
    expect(parsed.needs_credentials).toEqual([])
    expect(parsed.name).toBe('hand-written')
    expect(parsed.source_version).toBe(0)
    expect(parsed.exported_at).toBe('')
    // The document goes through untouched - an unknown key included, because
    // judging it is the server's job and a client that dropped it would be
    // quietly editing the author's file.
    expect(parsed.document).toEqual({ name: 'X', nodes: [] })
  })

  it('reads a picked File through the same parser', async () => {
    const file = new File([JSON.stringify(ENVELOPE)], 'brief.builder.json', { type: 'application/json' })
    await expect(readExportFile(file)).resolves.toMatchObject({ name: 'Clinic scheduling brief' })
    const bad = new File(['nope'], 'bad.builder.json')
    await expect(readExportFile(bad)).rejects.toBeInstanceOf(ExportFileError)
  })
})

/* --- the download ---------------------------------------------------------- */

describe('downloadExport', () => {
  let createSpy: ReturnType<typeof vi.spyOn>
  let revokeSpy: ReturnType<typeof vi.spyOn>
  let clickSpy: ReturnType<typeof vi.spyOn>
  interface ClickSnapshot {
    href: string
    download: string
    attached: boolean
    revokesBefore: number
  }
  let clicks: ClickSnapshot[]
  const mintedUrl = () => createSpy.mock.results[0]?.value as string
  const strayAnchors = () => document.querySelectorAll('a[download]').length

  beforeEach(() => {
    clicks = []
    // Real jsdom implementations underneath: the spies observe, they do not stub.
    createSpy = vi.spyOn(URL, 'createObjectURL')
    revokeSpy = vi.spyOn(URL, 'revokeObjectURL')
    clickSpy = vi
      .spyOn(HTMLElement.prototype, 'click')
      .mockImplementation(function recordClick(this: HTMLAnchorElement) {
        clicks.push({
          href: this.href,
          download: this.download,
          attached: this.isConnected,
          revokesBefore: revokeSpy.mock.calls.length,
        })
      })
  })

  it('names the file after the envelope, with the suffix the server also uses', () => {
    expect(EXPORT_FILE_SUFFIX).toBe('.builder.json')
    expect(exportFilename('Clinic scheduling brief')).toBe('Clinic scheduling brief.builder.json')

    downloadExport(ENVELOPE)

    expect(clicks).toHaveLength(1)
    expect(clicks[0].download).toBe('Clinic scheduling brief.builder.json')
    expect(clicks[0].href).toBe(mintedUrl())
    expect(clicks[0].attached).toBe(true)
  })

  it('writes the envelope as readable JSON that parses back to itself', async () => {
    downloadExport(ENVELOPE)

    const blob = createSpy.mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/json')
    const text = await blob.text()
    // Two-space indented, so a file an author opens in an editor is readable.
    expect(text).toContain('\n  "export": "builder.flow/v1"')
    expect(JSON.parse(text)).toEqual(ENVELOPE)
    // And what it wrote is what it would read: the two halves agree by construction.
    expect(parseExportEnvelope(text, 'round-trip.builder.json')).toEqual(ENVELOPE)
  })

  it('keeps the object URL alive for the click and releases it straight after', () => {
    downloadExport(ENVELOPE)

    expect(clicks[0].revokesBefore).toBe(0)
    expect(revokeSpy).toHaveBeenCalledTimes(1)
    expect(revokeSpy).toHaveBeenCalledWith(mintedUrl())
    expect(strayAnchors()).toBe(0)
  })

  it('releases the object URL even when the click throws', () => {
    clickSpy.mockImplementation(() => {
      throw new Error('Download blocked by the browser.')
    })

    expect(() => downloadExport(ENVELOPE)).toThrow('Download blocked by the browser.')

    expect(revokeSpy).toHaveBeenCalledWith(mintedUrl())
    expect(strayAnchors()).toBe(0)
  })
})

/* --- the bar ----------------------------------------------------------------- */

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

function model(version: number, head = version) {
  return {
    id: DOC,
    document: { ...toWire(documentFromTemplate(MINIMAL_GATED_AGENT)), id: DOC, version, name: 'Stored' },
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

function stubServer() {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  const exports: string[] = []
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url.pathname.endsWith('/api/builder/vocabulary')) return json(vocabularyPayload.vocabulary)
    if (url.pathname.endsWith('/api/builder/validate')) return json(vocabularyPayload.validation)
    if (url.pathname === `/api/builder/workflows/${DOC}/export`) {
      exports.push(url.pathname + url.search)
      return json({
        ...ENVELOPE,
        name: 'Stored',
        source_version: Number(url.searchParams.get('version') ?? 2),
      })
    }
    if (url.pathname === `/api/builder/workflows/${DOC}/versions`) {
      return json([
        { version: 2, status: 'draft', created_at: '2026-09-02T00:02:00Z', bytes: 10 },
        { version: 1, status: 'draft', created_at: '2026-09-02T00:01:00Z', bytes: 10 },
      ])
    }
    if (url.pathname === `/api/builder/workflows/${DOC}` && method === 'GET') {
      const at = url.searchParams.get('version')
      return json(model(at ? Number(at) : 2, 2))
    }
    if (url.pathname === '/api/builder/workflows' && method === 'GET') return json([])
    return json({ detail: `unstubbed ${method} ${url.pathname}` }, 404)
  })
  vi.stubGlobal('fetch', fetch)
  return { fetch, exports }
}

async function settled(): Promise<void> {
  await flush(6)
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flush(6)
}

describe('Export from the document bar', () => {
  let clicks: string[]

  beforeEach(() => {
    window.localStorage.clear()
    resetVocabulary()
    clicks = []
    vi.spyOn(HTMLElement.prototype, 'click').mockImplementation(function record(this: HTMLElement) {
      if (this instanceof HTMLAnchorElement) clicks.push(this.download)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    resetVocabulary()
    window.localStorage.clear()
  })

  async function openMenu(wrapper: ReturnType<typeof mount>) {
    await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
    await flush(2)
  }

  it('asks the server for the stored head and hands the file to the browser', async () => {
    const { exports } = stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: DOC as never }, global: { stubs: STUBS } })
    await settled()

    await openMenu(wrapper)
    await wrapper.get('[data-testid="menu-export"]').trigger('click')
    await settled()

    // No `?version` - head is what a plain export means.
    expect(exports).toEqual([`/api/builder/workflows/${DOC}/export`])
    expect(clicks).toEqual(['Stored.builder.json'])
    // The menu closed on the choice, and nothing modal appeared.
    expect(wrapper.find('[data-testid="document-menu"]').exists()).toBe(false)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('exports the version on screen while an older one is being viewed', async () => {
    const { exports } = stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: DOC as never }, global: { stubs: STUBS } })
    await settled()
    await openMenu(wrapper)
    await wrapper.get('[data-testid="menu-versions"]').trigger('click')
    await settled()
    await wrapper.get('[data-testid="version-row-1"]').trigger('click')
    await settled()

    await openMenu(wrapper)
    await wrapper.get('[data-testid="menu-export"]').trigger('click')
    await settled()

    expect(exports).toEqual([`/api/builder/workflows/${DOC}/export?version=1`])
    wrapper.unmount()
  })

  it('is disabled for a draft nothing has stored, and says why', async () => {
    const { exports } = stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: null }, global: { stubs: STUBS } })
    await settled()
    await wrapper.findAll('.template-card')[0].trigger('click')
    await settled()

    await openMenu(wrapper)
    const item = wrapper.get('[data-testid="menu-export"]')
    expect(item.attributes('disabled')).toBeDefined()
    expect(item.attributes('title')).toContain('Save this graph first')
    await item.trigger('click')
    await settled()

    expect(exports).toEqual([])
    expect(clicks).toEqual([])
    wrapper.unmount()
  })

  it('refuses to export a stored version the canvas is ahead of', async () => {
    const { exports } = stubServer()
    const wrapper = mount(BuilderView, { props: { documentId: DOC as never }, global: { stubs: STUBS } })
    await settled()
    await wrapper.get('.document-name').trigger('click')
    await flush(2)
    await wrapper.get('.document-name-input').setValue('Renamed but not saved')
    await wrapper.get('.document-name-input').trigger('blur')
    await flush(4)

    await openMenu(wrapper)
    await wrapper.get('[data-testid="menu-export"]').trigger('click')
    await settled()

    // A file missing the author's last edit, with nothing saying so, is the
    // failure. The notice names the reason; nothing was fetched.
    expect(exports).toEqual([])
    expect(clicks).toEqual([])
    expect(wrapper.get('.builder-notice').text()).toContain('save your changes first')
    wrapper.unmount()
  })
})
