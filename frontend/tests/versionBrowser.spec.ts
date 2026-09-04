import { effectScope, nextTick, ref } from 'vue'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import BuilderView from '../src/components/builder/BuilderView.vue'
import BuilderNode from '../src/components/builder/BuilderNode.vue'
import DocumentBar from '../src/components/builder/DocumentBar.vue'
import NodePalette from '../src/components/builder/NodePalette.vue'
import PublishDialog from '../src/components/builder/PublishDialog.vue'
import VersionBrowser from '../src/components/builder/VersionBrowser.vue'
import { BUILDER_READ_ONLY } from '../src/composables/useBuilderCanvas'
import { useBuilderDocument } from '../src/composables/useBuilderDocument'
import { useBuilderPersistence } from '../src/composables/useBuilderPersistence'
import { MINIMAL_GATED_AGENT, documentFromTemplate } from '../src/data/builderTemplates'
import { resetVocabulary } from '../src/data/builderVocabulary'
import { BuilderConflictError } from '../src/services/builderApi'
import type { BuilderApiLike, SaveOptions } from '../src/services/builderApi'
import { BUILDER_SCHEMA_ID, documentId, nodeId } from '../src/types/builder'
import type {
  BuilderDocument,
  BuilderDocumentModel,
  BuilderDocumentSummary,
  BuilderPublish,
  BuilderValidation,
  BuilderVersionRow,
  DocumentId,
} from '../src/types/builder'
import { toWire } from '../src/utils/builderSerialize'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { FakeBuilderApi as HelperApi, flush, zeroBudget } from './helpers'

/**
 * Plan 15 D3, criterion 4: the version browser opens a prior version READ-ONLY,
 * and Restore commits it as the next head through the ordinary compare-and-set
 * save - one undo, one new version, never a rewrite of history.
 *
 * Three layers, because the property lives in three places and a green test
 * at one of them proves nothing about the others:
 *
 * 1. **The composable.** `open(id, 3)` under a head of 7 sets the store's lock,
 *    so every commit is refused, autosave never arms and Ctrl+S never PUTs -
 *    a PUT from v3 would carry `expected_version: 3` and be a 409 about a
 *    conflict nobody had. `restoreVersion` re-GETs head, adopts ITS version as
 *    the expected one, commits v3's content over it and saves: v8, with head
 *    one Ctrl+Z away and v4..v7 untouched.
 * 2. **The component.** Presentational: the rows are rendered in the order the
 *    server sends and never re-sorted, the banner is the whole read-only state,
 *    and `blocked` disables what a dirty canvas must not be allowed to do.
 * 3. **The shell.** `BuilderView` mounted over a stubbed transport, because the
 *    composable and the component were both unit-tested for a day while no
 *    `.vue` file read `viewingVersion` - the exact shape of "tests that pass
 *    for the wrong reason" CLAUDE.md records for the restore bar.
 *
 * `PublishDialog`'s `viewing head` precondition is asserted here too, once, so
 * the two halves of criterion 4 are pinned by one file.
 */

/* --- fixtures ------------------------------------------------------------ */

const DOC_ID = documentId('ug_0a1b2c3d')

function sample(name: string, version: number): BuilderDocument {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: DOC_ID,
    name,
    version,
    input_field: nodeId('idea'),
    nodes: [
      {
        id: nodeId('idea'),
        kind: 'input',
        label: 'Idea',
        position: { x: 0, y: 0 },
        config: { field: nodeId('idea'), label: null, max_chars: 2000, required: true },
      },
    ],
    edges: [],
    joins: {},
    budget: null,
  }
}

/**
 * A transport with a REAL version history behind it.
 *
 * `tests/helpers.ts`'s double keeps one document per id, which is right for
 * the save loop and wrong here: "v8 has v3's content" is only checkable
 * against a store that remembers what v3 said. `implements BuilderApiLike`
 * for the reason every double in this repo gives - the compiler refusing
 * this class when the client grows is the only mechanism that has ever kept
 * a double honest.
 */
class VersionedApi implements BuilderApiLike {
  readonly versions = new Map<number, BuilderDocument>()
  head = 0
  gets: Array<{ id: string; version: number | undefined }> = []
  saves: Array<{ id: string; expectedVersion: number; document: BuilderDocument; options: SaveOptions }> = []
  /** Another writer lands a version the moment head is read - the restore race. */
  bumpHeadOnGet = false

  seed(entries: Record<number, string>): void {
    for (const [version, name] of Object.entries(entries)) {
      this.versions.set(Number(version), sample(name, Number(version)))
      this.head = Math.max(this.head, Number(version))
    }
  }

  private model(version: number): BuilderDocumentModel {
    const document = this.versions.get(version)
    if (!document) throw new Error(`no version ${version}`)
    return {
      id: DOC_ID,
      document,
      status: 'draft',
      version,
      head_version: this.head,
      created_at: '2026-09-02T00:00:00Z',
      updated_at: `2026-09-02T00:0${version}:00Z`,
      problems: [],
      budget: zeroBudget(),
      graph: { id: DOC_ID, name: document.name, version: 'abc', start_nodes: [], nodes: [], edges: [] },
      published: false,
      live_version: null,
    }
  }

  async list(): Promise<BuilderDocumentSummary[]> {
    return []
  }

  async create(document: BuilderDocument): Promise<BuilderDocumentModel> {
    this.versions.set(1, { ...document, id: DOC_ID, version: 1 })
    this.head = 1
    return this.model(1)
  }

  async get(id: string, version?: number): Promise<BuilderDocumentModel> {
    this.gets.push({ id, version })
    const answered = this.model(version ?? this.head)
    if (this.bumpHeadOnGet && version === undefined) {
      this.versions.set(this.head + 1, sample('Somebody else', this.head + 1))
      this.head += 1
    }
    return answered
  }

  async save(
    id: string,
    document: BuilderDocument,
    expectedVersion: number,
    options: SaveOptions = {},
  ): Promise<BuilderDocumentModel> {
    this.saves.push({ id, expectedVersion, document, options })
    if (expectedVersion !== this.head) {
      throw new BuilderConflictError(
        `document ${id} is at version ${this.head}, not ${expectedVersion}; reload it before saving again`,
        this.head,
      )
    }
    this.head += 1
    this.versions.set(this.head, { ...document, id: DOC_ID, version: this.head })
    return this.model(this.head)
  }

  async remove(): Promise<void> {}

  async validate(): Promise<BuilderValidation> {
    return { valid: true, problems: [], budget: zeroBudget() }
  }

  async publish(): Promise<BuilderPublish> {
    throw new Error('unused')
  }
}

const openScopes: Array<() => void> = []

function session(options: { onSaved?: () => void } = {}) {
  const api = new VersionedApi()
  api.seed({ 3: 'Three', 5: 'Five', 7: 'Seven' })
  const scope = effectScope()
  let built!: ReturnType<typeof build>
  function build() {
    const document = useBuilderDocument(sample('Unsaved', 0))
    return { document, persistence: useBuilderPersistence(document, api, options) }
  }
  scope.run(() => {
    built = build()
  })
  openScopes.push(() => scope.stop())
  return { api, ...built }
}

beforeEach(() => {
  window.localStorage.clear()
  resetVocabulary()
})

afterEach(() => {
  while (openScopes.length) openScopes.pop()?.()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  resetVocabulary()
  window.localStorage.clear()
})

/* --- 1. the composable ----------------------------------------------------- */

describe('opening a stored version that is not head', () => {
  it('puts that version on the canvas and says so', async () => {
    const { persistence, document } = session()
    await persistence.open(DOC_ID as DocumentId, 3)

    expect(document.doc.value.name).toBe('Three')
    expect(persistence.version.value).toBe(3)
    expect(persistence.headVersion.value).toBe(7)
    expect(persistence.viewingVersion.value).toBe(true)
    expect(persistence.saveState.value).toBe('clean')
  })

  it('locks the store, so no gesture anywhere can write', async () => {
    const { persistence, document } = session()
    await persistence.open(DOC_ID as DocumentId, 3)
    expect(document.readOnly.value).toBe(true)

    const before = document.doc.value
    document.setName('Typed into v3')
    document.commit('any gesture', { ...before, name: 'Committed directly' })

    // The one write path refused both, and counted them so the shell can say so.
    expect(document.doc.value).toBe(before)
    expect(document.lockedRefusals.value).toBe(2)
    expect(document.dirty.value).toBe(false)
    expect(document.canUndo.value).toBe(false)
  })

  it('never autosaves and never PUTs on Ctrl+S, because a PUT from v3 is a 409 nobody caused', async () => {
    vi.useFakeTimers()
    const { api, persistence, document } = session()
    await persistence.open(DOC_ID as DocumentId, 3)

    document.setName('Refused anyway')
    await vi.advanceTimersByTimeAsync(10_000)
    await persistence.save()

    expect(api.saves).toEqual([])
    expect(persistence.saveState.value).toBe('clean')
    expect(persistence.conflict.value).toBeNull()
  })

  it('writes no local draft for the old version, so a head-based draft is not overwritten', async () => {
    const { persistence } = session()
    await persistence.open(DOC_ID as DocumentId, 3)
    await nextTick()

    // A draft is a claim about HEAD. One written from v3 would carry
    // `baseVersion: 3`, be discarded on the next load, and have overwritten a
    // genuine head-based draft under the same key on the way.
    expect(window.localStorage.getItem(`builder-draft:${DOC_ID}`)).toBeNull()
  })

  it('offers no stale draft over a version it is not about', async () => {
    window.localStorage.setItem(
      `builder-draft:${DOC_ID}`,
      JSON.stringify({
        v: 1,
        baseVersion: 7,
        savedAt: '2026-09-02T13:29:00.000Z',
        document: toWire(sample('Unsaved work on head', 7)),
      }),
    )
    const { persistence } = session()
    await persistence.open(DOC_ID as DocumentId, 3)

    // `baseVersion === head_version` is still TRUE while v3 is on screen, so
    // without the guard the bar would offer head's draft over v3.
    expect(persistence.restoreOffer.value).toBeNull()
    // And it is not discarded either - it is head's, and head is where it belongs.
    expect(window.localStorage.getItem(`builder-draft:${DOC_ID}`)).not.toBeNull()
  })

  it('releases the lock when head is opened again', async () => {
    const { persistence, document } = session()
    await persistence.open(DOC_ID as DocumentId, 3)
    await persistence.open(DOC_ID as DocumentId)

    expect(persistence.viewingVersion.value).toBe(false)
    expect(document.readOnly.value).toBe(false)
    expect(document.doc.value.name).toBe('Seven')
    document.setName('Editable again')
    expect(document.doc.value.name).toBe('Editable again')
    expect(persistence.saveState.value).toBe('dirty')
  })

  it('is not "viewing a version" for an unsaved draft, where both numbers are 0', () => {
    const { persistence, document } = session()
    expect(persistence.viewingVersion.value).toBe(false)
    expect(document.readOnly.value).toBe(false)
  })
})

describe('restoreVersion', () => {
  it('declares itself to the server, and the idle autosave declares itself too (D-15-3)', async () => {
    vi.useFakeTimers()
    const { api, document, persistence } = session()
    await persistence.open(DOC_ID, 3)
    await persistence.restoreVersion()
    expect(api.saves.at(-1)?.options).toEqual({ source: 'restore', restoredFrom: 3 })

    document.commit('Rename', { ...document.doc.value, name: 'Idle' })
    await vi.advanceTimersByTimeAsync(3_000)
    expect(api.saves.at(-1)?.options).toEqual({ source: 'autosave', restoredFrom: undefined })

    await persistence.save()
    expect(api.saves.at(-1)?.options).toEqual({ source: 'save', restoredFrom: undefined })
  })

  it('commits the version on screen as head + 1 through the CAS, with head one undo away', async () => {
    const onSaved = vi.fn()
    const { api, persistence, document } = session({ onSaved })
    await persistence.open(DOC_ID as DocumentId, 3)

    await persistence.restoreVersion()

    // Head was re-GET (the ring needs its DOCUMENT), then v3's content was PUT
    // against head's version - never against the 3 this tab opened with.
    expect(api.gets.at(-1)).toEqual({ id: DOC_ID, version: undefined })
    expect(api.saves).toHaveLength(1)
    expect(api.saves[0].expectedVersion).toBe(7)
    expect(api.saves[0].document.name).toBe('Three')

    // v8 with v3's content; v4..v7 exactly where they were.
    expect(persistence.version.value).toBe(8)
    expect(persistence.headVersion.value).toBe(8)
    expect(persistence.viewingVersion.value).toBe(false)
    expect(document.readOnly.value).toBe(false)
    expect(document.doc.value.name).toBe('Three')
    expect(api.versions.get(7)?.name).toBe('Seven')
    expect(api.versions.get(8)?.name).toBe('Three')
    expect(persistence.saveState.value).toBe('clean')
    expect(onSaved).toHaveBeenCalledTimes(1)

    // The author who restored the wrong version is a single Ctrl+Z from head.
    document.undo()
    expect(document.doc.value.name).toBe('Seven')
  })

  it('meets a head that moved in between as an ordinary 409, touching nothing', async () => {
    const { api, persistence, document } = session()
    await persistence.open(DOC_ID as DocumentId, 3)
    api.bumpHeadOnGet = true

    await persistence.restoreVersion()

    // The PUT compared against the head that was read (7); the server holds 8.
    expect(api.saves[0].expectedVersion).toBe(7)
    expect(persistence.saveState.value).toBe('conflict')
    expect(persistence.conflict.value?.storedVersion).toBe(8)
    // The author's copy is v3's content, on screen, with the head they read
    // one undo away - exactly what `ConflictDialog` will resolve against.
    expect(document.doc.value.name).toBe('Three')
    document.undo()
    expect(document.doc.value.name).toBe('Seven')
    expect(api.versions.get(8)?.name).toBe('Somebody else')
  })

  it('does nothing while head is on screen', async () => {
    const onSaved = vi.fn()
    const { api, persistence } = session({ onSaved })
    await persistence.open(DOC_ID as DocumentId)
    api.gets.length = 0

    await persistence.restoreVersion()

    expect(api.gets).toEqual([])
    expect(api.saves).toEqual([])
    expect(onSaved).not.toHaveBeenCalled()
  })
})

/* --- 2. the component ------------------------------------------------------ */

describe('VersionBrowser', () => {
  const ROWS: BuilderVersionRow[] = [
    { version: 7, status: 'draft', created_at: '2026-09-02T10:14:00Z', bytes: 2048, source: 'saved', name: 'Seven', node_count: 5, edge_count: 4 },
    { version: 5, status: 'published', created_at: '2026-09-02T09:00:00Z', bytes: 1900, source: 'restored from v3', name: 'Five', node_count: 4, edge_count: 4 },
    { version: 3, status: 'draft', created_at: '2026-09-01T18:30:00Z', bytes: 640, source: 'created', name: 'Three', node_count: 1, edge_count: 0 },
  ]
  /** Held still, so the relative times below are facts rather than a race. */
  const NOW = Date.parse('2026-09-02T10:15:00Z')

  function browser(overrides: Record<string, unknown> = {}) {
    return mount(VersionBrowser, {
      props: {
        versions: ROWS,
        version: 7,
        headVersion: 7,
        loading: false,
        problem: '',
        restoring: false,
        documentId: DOC_ID,
        clock: () => NOW,
        ...overrides,
      },
    })
  }

  /*
   * D-15-24. Round 3: "version rows carry no diff. Rows differ only by
   * `5 nodes`/`4 nodes` and `1.4 KB`/`1.3 KB` - two clicks per candidate to
   * eyeball, and it does not scale."
   *
   * The delta is against the row BELOW, because the server answers newest
   * first and nothing re-sorts; that makes it a property of the list's order,
   * which is why it is computed here and not served.
   */
  it('says what each version changed, against the version below it (D-15-24)', () => {
    const wrapper = browser()
    const deltas = wrapper.findAll('.version-delta').map((node) => node.text())
    // v7 has 5 nodes / 4 edges over v5's 4 / 4; v5 has 4 / 4 over v3's 1 / 0.
    expect(deltas).toEqual(['+1 node', '+3 nodes, +4 edges', ''])
  })

  it('counts down as well as up, with a real minus sign', () => {
    const shrunk: BuilderVersionRow[] = [
      { ...ROWS[0], version: 9, node_count: 2, edge_count: 1 },
      { ...ROWS[1], version: 8, node_count: 5, edge_count: 4 },
    ]
    const wrapper = browser({ versions: shrunk, version: 9, headVersion: 9 })
    // U+2212, not a hyphen: these sit in tabular monospace beside `+`.
    expect(wrapper.findAll('.version-delta')[0].text()).toBe('\u22123 nodes, \u22123 edges')
  })

  it('says "same shape" rather than nothing when the counts agree', () => {
    /* A rename or a reposition changes bytes and not shape, and "nothing
       moved" is a real answer - different from "we cannot tell". */
    const renamed: BuilderVersionRow[] = [
      { ...ROWS[0], version: 4, name: 'After', node_count: 3, edge_count: 2 },
      { ...ROWS[1], version: 3, name: 'Before', node_count: 3, edge_count: 2 },
    ]
    const wrapper = browser({ versions: renamed, version: 4, headVersion: 4 })
    const first = wrapper.findAll('.version-delta')[0]
    expect(first.text()).toBe('same shape')
    expect(first.classes()).toContain('is-same')
  })

  it('says nothing at all for a row whose counts could not be read', () => {
    /* A version stored under a schema this service no longer parses lists
       with whatever it can say, and "no change" is not something it can say. */
    const unreadable: BuilderVersionRow[] = [
      { ...ROWS[0], version: 2, node_count: null, edge_count: null },
      { ...ROWS[1], version: 1, node_count: 4, edge_count: 4 },
    ]
    const wrapper = browser({ versions: unreadable, version: 2, headVersion: 2 })
    expect(wrapper.findAll('.version-delta')[0].text()).toBe('')
  })

  it('keeps the delta column present on every row so the list does not jitter', () => {
    const wrapper = browser()
    expect(wrapper.findAll('.version-delta')).toHaveLength(3)
    // Including the oldest, which has nothing to be a delta from.
    expect(wrapper.get('[data-testid="version-delta-3"]').text()).toBe('')
  })

  it('tells two versions from the same minute apart by label, source and seconds (D-15-3)', () => {
    /*
     * Round 1's capture: "v2 HEAD DRAFT 3 Sept, 00:19 1.4 KB" over
     * "v1 DRAFT 3 Sept, 00:19 1.2 KB". Two autosaves, one minute, nothing to
     * choose by. The same minute here, and every row differs in three places.
     */
    const twins: BuilderVersionRow[] = [
      { version: 2, status: 'draft', created_at: '2026-09-02T10:14:48Z', bytes: 1400, source: 'autosaved', name: 'Minimal gated agent', node_count: 5, edge_count: 4 },
      { version: 1, status: 'draft', created_at: '2026-09-02T10:14:12Z', bytes: 1200, source: 'created', name: 'Minimal gated agent', node_count: 4, edge_count: 3 },
    ]
    const wrapper = browser({ versions: twins, version: 2, headVersion: 2 })
    const [head, older] = wrapper.findAll('.version-row')
    expect(head.get('[data-testid="version-label"]').text()).toBe('Minimal gated agent · 5 nodes')
    expect(older.get('[data-testid="version-label"]').text()).toBe('Minimal gated agent · 4 nodes')
    expect(head.get('[data-testid="version-source"]').text()).toBe('autosaved')
    expect(older.get('[data-testid="version-source"]').text()).toBe('created')
    expect(head.get('[data-testid="version-when"]').text()).toBe('12 s ago')
    expect(older.get('[data-testid="version-when"]').text()).toBe('48 s ago')
    // The full stamp, seconds included, is one hover away - in the author's
    // own zone, so only the minute and second are asserted.
    expect(head.get('[data-testid="version-when"]').attributes('title')).toMatch(/:14:48/)
    expect(head.get('time').attributes('datetime')).toBe('2026-09-02T10:14:48Z')
    expect(head.text()).not.toEqual(older.text())
  })

  it('reads the real clock by default, and a naive stamp as UTC (D-15-3)', () => {
    /*
     * Round 2's capture showed every row in the dated form: the default
     * `clock` returned a function, and a SQLite stamp with no zone parsed as
     * local time. Both are what a real backend hands this component.
     */
    const twelveSecondsAgo = new Date(Date.now() - 12_000).toISOString()
    const live = mount(VersionBrowser, {
      props: {
        versions: [{ ...ROWS[0], created_at: twelveSecondsAgo }],
        version: 7,
        headVersion: 7,
        loading: false,
        problem: '',
        restoring: false,
        documentId: DOC_ID,
      },
    })
    expect(live.get('[data-testid="version-when"]').text()).toMatch(/^1[0-9] s ago$/)

    // No zone on the stamp - what SQLite hands back - and it still means UTC.
    const naive = browser({ versions: [{ ...ROWS[0], created_at: '2026-09-02T10:14:48' }] })
    expect(naive.get('[data-testid="version-when"]').text()).toBe('12 s ago')
    expect(naive.get('time').attributes('datetime')).toBe('2026-09-02T10:14:48')
  })

  it('scales the relative time and falls back to the dated form', () => {
    const wrapper = browser()
    const whens = wrapper.findAll('[data-testid="version-when"]').map((w) => w.text())
    expect(whens).toEqual(['1 min ago', '1 h ago', '16 h ago'])
    const label = wrapper.findAll('[data-testid="version-label"]').map((w) => w.text())
    expect(label).toEqual(['Seven · 5 nodes', 'Five · 4 nodes', 'Three · 1 node'])
    const old = browser({
      versions: [{ ...ROWS[2], created_at: '2026-08-20T08:00:00Z', name: null, node_count: null, edge_count: null }],
    })
    expect(old.get('[data-testid="version-when"]').text()).toMatch(/20 Aug/)
    expect(old.get('[data-testid="version-label"]').text()).toBe('unreadable version')
  })

  it('renders the rows in the order the server sent them, and never re-sorts', () => {
    // Deliberately NOT newest-first, so a component that sorted would pass a
    // newest-first fixture and hide a server that stopped sending them so.
    const shuffled = [ROWS[2], ROWS[0], ROWS[1]]
    const rendered = browser({ versions: shuffled })
      .findAll('.version-row')
      .map((row) => row.attributes('data-testid'))
    expect(rendered).toEqual(['version-row-3', 'version-row-7', 'version-row-5'])
  })

  it('marks head with a pill and the viewed version with aria-current', () => {
    const wrapper = browser({ version: 5 })
    expect(wrapper.get('[data-testid="version-row-7"]').text()).toContain('head')
    expect(wrapper.get('[data-testid="version-row-5"]').text()).not.toContain('head')
    expect(wrapper.get('[data-testid="version-row-5"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-testid="version-row-7"]').attributes('aria-current')).toBeUndefined()
    expect(wrapper.get('[data-testid="version-row-5"]').text()).toContain('published')
  })

  it('shows the read-only banner only while an older version is on screen', () => {
    expect(browser().find('[data-testid="version-viewing"]').exists()).toBe(false)

    const viewing = browser({ version: 3 })
    const banner = viewing.get('[data-testid="version-viewing"]')
    expect(banner.attributes('role')).toBe('status')
    expect(banner.text()).toContain('Viewing v3 of v7')
    expect(banner.text()).toContain('read-only')
    expect(viewing.get('[data-testid="version-restore"]').text()).toBe('Restore v3')
    expect(viewing.get('[data-testid="version-back"]').text()).toBe('Back to v7')
  })

  it('emits view, head, restore and close, and holds no persistence of its own', async () => {
    const wrapper = browser({ version: 3 })
    await wrapper.get('[data-testid="version-row-5"]').trigger('click')
    await wrapper.get('[data-testid="version-back"]').trigger('click')
    await wrapper.get('[data-testid="version-restore"]').trigger('click')
    await wrapper.get('[aria-label="Close the version browser"]').trigger('click')

    expect(wrapper.emitted('view')).toEqual([[5]])
    expect(wrapper.emitted('head')).toHaveLength(1)
    expect(wrapper.emitted('restore')).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('cannot be pressed twice while a restore is in flight', () => {
    const wrapper = browser({ version: 3, restoring: true })
    expect(wrapper.get('[data-testid="version-restore"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="version-back"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="version-restore"]').text()).toBe('Restoring…')
  })

  it('disables every row and says why while the canvas is ahead of the store', () => {
    const wrapper = browser({
      version: 3,
      blocked: 'save your changes first — opening a stored version replaces what is on the canvas.',
    })
    expect(wrapper.get('[data-testid="version-blocked"]').text()).toContain('save your changes first')
    for (const row of wrapper.findAll('.version-row')) expect(row.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="version-restore"]').attributes('disabled')).toBeDefined()
  })

  it('names the three states that are not a list', () => {
    expect(browser({ documentId: null, versions: [] }).text()).toContain('Save this graph')
    expect(browser({ loading: true }).text()).toContain('Reading the stored versions')
    const failed = browser({ problem: 'Request failed (503)' })
    expect(failed.get('[role="alert"]').text()).toContain('Request failed (503)')
    expect(failed.findAll('.version-row')).toHaveLength(0)
  })
})

/* --- the palette and the card say read-only too (D-15-1) ------------------- */

describe('read-only on the palette and on the card', () => {
  const vocabularyServer = () =>
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify(vocabularyPayload.vocabulary), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

  it('disables every tile, says why, and drops nothing on click', async () => {
    vocabularyServer()
    const wrapper = mount(NodePalette, { props: { readOnly: true } })
    await flush(6)
    expect(wrapper.get('.builder-palette').classes()).toContain('is-read-only')
    expect(wrapper.get('[data-testid="palette-read-only"]').text()).toContain('Read-only')
    const tiles = wrapper.findAll('.builder-tile')
    expect(tiles.length).toBeGreaterThan(0)
    for (const tile of tiles) {
      expect(tile.attributes('disabled')).toBeDefined()
      expect(tile.attributes('title')).toContain('Read-only')
    }
    await tiles[0].trigger('click')
    expect(wrapper.emitted('place')).toBeUndefined()
    wrapper.unmount()
  })

  it("carries each library row's whole name in its title (D-15-4)", async () => {
    vocabularyServer()
    const name = 'Minimal gated agent copy'
    const wrapper = mount(NodePalette, {
      props: {
        library: [
          { id: 'ug_00000001', name, version: 1, status: 'draft', live_version: null, created_at: '2026-09-02T00:00:00Z', updated_at: '2026-09-02T00:00:00Z' },
        ],
      },
    })
    await flush(6)
    expect(wrapper.get('.builder-library-name').attributes('title')).toBe(name)
    wrapper.unmount()
  })

  it('is an ordinary palette when nothing is being viewed', async () => {
    vocabularyServer()
    const wrapper = mount(NodePalette)
    await flush(6)
    expect(wrapper.get('.builder-palette').classes()).not.toContain('is-read-only')
    expect(wrapper.find('[data-testid="palette-read-only"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('puts a lock in the card eyebrow only while the canvas is read-only', () => {
    // Shaped as `useBuilderCanvas` projects a node, the way `builderNode.spec.ts` does.
    const data = {
      node: sample('x', 1).nodes[0],
      index: 1,
      ports: [],
      acceptsIncoming: false,
      targetPorts: [],
      refused: false,
      problems: [],
      severity: null,
      joined: false,
      anchor: false,
      loopTarget: false,
      loopIllegal: false,
      connectable: false,
      flashing: false,
      runState: 'idle',
      inbound: 0,
      landing: false,
    }
    const locked = mount(BuilderNode, {
      props: { id: 'idea', data: data as never },
      global: { stubs: { Handle: true }, provide: { [BUILDER_READ_ONLY as symbol]: ref(true) } },
    })
    expect(locked.find('[data-testid="node-lock"]').exists()).toBe(true)
    const open = mount(BuilderNode, {
      props: { id: 'idea', data: data as never },
      global: { stubs: { Handle: true }, provide: { [BUILDER_READ_ONLY as symbol]: ref(false) } },
    })
    expect(open.find('[data-testid="node-lock"]').exists()).toBe(false)
    const outsideACanvas = mount(BuilderNode, { props: { id: 'idea', data: data as never }, global: { stubs: { Handle: true } } })
    expect(outsideACanvas.find('[data-testid="node-lock"]').exists()).toBe(false)
  })
})

/* --- publish keeps refusing a non-head ------------------------------------- */

describe('PublishDialog over a viewed version', () => {
  it('still refuses to publish anything but head, naming both versions', () => {
    const api = new HelperApi()
    const document = MINIMAL_GATED_AGENT.document
    const id = api.seed({ ...document, version: 7 }, 7)
    const wrapper = mount(PublishDialog, {
      props: {
        open: true,
        document,
        documentId: id,
        api,
        errorCount: 0,
        saveState: 'clean',
        version: 3,
        headVersion: 7,
        phase: 'fresh',
        budget: zeroBudget(),
        publishedVersion: null,
      },
    })
    expect(wrapper.text()).toContain('you are viewing v3; publish works on head (v7)')
    const publish = wrapper.findAll('button').find((button) => /^(Publish|Republish)$/.test(button.text()))
    expect(publish?.attributes('disabled')).toBeDefined()
  })
})

/* --- 3. the shell ---------------------------------------------------------- */

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

const SHELL_ID = 'ug_1234abcd'

/**
 * A stubbed transport with a version history, answering by method and path
 * the way `builder_api.py` does. `versionsCalls` counts the list reads, which
 * is how `onSaved` reaching the browser is proved.
 */
function stubServer() {
  const state = {
    head: 2,
    versions: new Map<number, Record<string, unknown>>(),
    sources: new Map<number, string>(),
    versionsCalls: 0,
    puts: [] as Array<Record<string, unknown>>,
  }
  const base = toWire(documentFromTemplate(MINIMAL_GATED_AGENT)) as unknown as Record<string, unknown>
  state.versions.set(1, { ...base, id: SHELL_ID, version: 1, name: 'First' })
  state.versions.set(2, {
    ...base,
    id: SHELL_ID,
    version: 2,
    name: 'Second',
    nodes: [...(base.nodes as unknown[]), {
      id: 'extra',
      kind: 'transform',
      label: 'Extra',
      position: { x: 600, y: 300 },
      config: { op: 'default', args: {} },
    }],
  })

  const model = (version: number) => ({
    id: SHELL_ID,
    document: state.versions.get(version),
    status: 'draft',
    version,
    head_version: state.head,
    created_at: '2026-09-02T00:00:00Z',
    updated_at: `2026-09-02T00:0${version}:00Z`,
    problems: [],
    budget: vocabularyPayload.validation.budget,
    graph: null,
    published: false,
  })

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = url.pathname
    if (path.endsWith('/api/builder/vocabulary')) return json(vocabularyPayload.vocabulary)
    if (path.endsWith('/api/builder/validate')) return json(vocabularyPayload.validation)
    if (path === `/api/builder/workflows/${SHELL_ID}/versions`) {
      state.versionsCalls += 1
      const rows = [...state.versions.keys()]
        .sort((a, b) => b - a)
        .map((version) => ({
          version,
          status: 'draft',
          created_at: `2026-09-02T00:0${version}:00Z`,
          bytes: JSON.stringify(state.versions.get(version)).length,
          source: state.sources.get(version) ?? 'created',
          name: (state.versions.get(version) as { name?: string }).name ?? null,
          node_count: ((state.versions.get(version) as { nodes?: unknown[] }).nodes ?? []).length,
          edge_count: ((state.versions.get(version) as { edges?: unknown[] }).edges ?? []).length,
        }))
      return json(rows)
    }
    if (path === `/api/builder/workflows/${SHELL_ID}` && method === 'GET') {
      const at = url.searchParams.get('version')
      return json(model(at ? Number(at) : state.head))
    }
    if (path === `/api/builder/workflows/${SHELL_ID}` && method === 'PUT') {
      const body = JSON.parse(String(init?.body)) as {
        document: Record<string, unknown>
        expected_version: number
        source?: string
        restored_from?: number
      }
      state.puts.push(body)
      if (body.expected_version !== state.head) {
        return json(
          { detail: `document ${SHELL_ID} is at version ${state.head}, not ${body.expected_version}; reload it before saving again` },
          409,
        )
      }
      state.head += 1
      state.versions.set(state.head, { ...body.document, id: SHELL_ID, version: state.head })
      state.sources.set(
        state.head,
        body.source === 'restore' ? `restored from v${body.restored_from}` : body.source === 'autosave' ? 'autosaved' : 'saved',
      )
      return json(model(state.head))
    }
    if (path === '/api/builder/workflows' && method === 'GET') return json([])
    return json({ detail: `unstubbed ${method} ${path}` }, 404)
  })
  vi.stubGlobal('fetch', fetch)
  return { state, fetch }
}

async function settled(): Promise<void> {
  await flush(6)
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flush(6)
}

async function mountOpen() {
  const server = stubServer()
  const wrapper = mount(BuilderView, {
    props: { documentId: SHELL_ID as never },
    global: { stubs: STUBS },
  })
  await settled()
  await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
  await wrapper.get('[data-testid="menu-versions"]').trigger('click')
  await settled()
  return { ...server, wrapper }
}

describe('the shell', () => {
  /*
   * D-15-23. A version has no status column: `_version_status` derives it from
   * which version is REGISTERED, so an open browser's rows are computed before
   * the publish and say `draft` afterwards - including the row for the version
   * that is now live. The critic caught all three surfaces disagreeing at once:
   * header `v3 is live`, library row `v3 PUBLISHED`, version row `HEAD DRAFT`.
   *
   * `unpublishDocument` had always reloaded the list. `onPublished` had not.
   */
  it('re-reads the version rows after a publish, because their status is derived (D-15-23)', async () => {
    const { wrapper, state } = await mountOpen()
    expect(state.versionsCalls).toBe(1)

    await wrapper.get('[data-testid="document-publish"]').trigger('click')
    await settled()
    const dialog = wrapper.findComponent(PublishDialog)
    expect(dialog.exists()).toBe(true)
    dialog.vm.$emit('published', {
      workflow_id: 'ug_1234abcd',
      version: 2,
      input_field: 'idea',
      name: 'Second',
    } as unknown as BuilderPublish)
    await settled()

    expect(state.versionsCalls).toBe(2)
    wrapper.unmount()
  })

  it('does not re-read them when the browser is closed, because nothing is on screen', async () => {
    /* The reload is for the rows an author is LOOKING at; fetching a list
       nobody has open is a request that buys nothing. `toggleVersions` reads
       fresh on open, which is the other half of the same rule. */
    const server = stubServer()
    const wrapper = mount(BuilderView, {
      props: { documentId: SHELL_ID as never },
      global: { stubs: STUBS },
    })
    await settled()
    expect(server.state.versionsCalls).toBe(0)

    await wrapper.get('[data-testid="document-publish"]').trigger('click')
    await settled()
    wrapper.findComponent(PublishDialog).vm.$emit('published', {
      workflow_id: 'ug_1234abcd',
      version: 2,
      input_field: 'idea',
      name: 'Second',
    } as unknown as BuilderPublish)
    await settled()

    expect(server.state.versionsCalls).toBe(0)
    wrapper.unmount()
  })

  it('names the version the export writes, in the menu that covers the rows (D-15-25)', async () => {
    /* The menu sits over the version rows it operates on, and the label said
       `Export .builder.json` - the file format, which the Import item below it
       already implies, and nothing about WHICH version leaves. */
    const { wrapper } = await mountOpen()
    // The menu closes on choosing, which is what makes it a menu; reopen it
    // over the rows exactly as the critic's capture had it.
    await wrapper.get('[data-testid="document-menu-button"]').trigger('click')
    await settled()
    const label = wrapper.get('[data-testid="menu-export"]').text()
    expect(label).toContain('Export head')
    expect(label).toContain('(v2)')
    expect(label).not.toContain('.builder.json')
    wrapper.unmount()
  })

  it('lists the stored versions from the menu, newest first as the server answers', async () => {
    const { wrapper, state } = await mountOpen()

    expect(state.versionsCalls).toBe(1)
    const rows = wrapper.findAll('.version-row').map((row) => row.attributes('data-testid'))
    expect(rows).toEqual(['version-row-2', 'version-row-1'])
    expect(wrapper.get('[data-testid="version-row-2"]').text()).toContain('head')
    // In the layout, under the bar, never over the canvas (R15).
    expect(wrapper.get('[data-testid="builder-dock"]').find('[data-testid="version-browser"]').exists()).toBe(true)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('opens an older version read-only on every surface, and publish refuses it', async () => {
    const { wrapper, fetch } = await mountOpen()

    await wrapper.get('[data-testid="version-row-1"]').trigger('click')
    await settled()

    expect(fetch.mock.calls.map(([url]) => String(url))).toContain(
      `/api/builder/workflows/${SHELL_ID}?version=1`,
    )
    expect(wrapper.get('[data-testid="version-viewing"]').text()).toContain('Viewing v1 of v2')
    // The canvas draws v1 (four nodes, not five), refuses drags, and the
    // inspector's controls are disabled rather than editable-and-reverting.
    expect(wrapper.text()).not.toContain('Extra')
    expect(wrapper.get('.builder-canvas').classes()).toContain('is-read-only')
    expect(wrapper.get('fieldset.rail-lock').attributes('disabled')).toBeDefined()

    // D-15-1: the DOCUMENT BAR says read-only too, not only the dock and the
    // rail. The chip stops calling v1 "saved" in the editable colour, the
    // name is no longer a text control, a lock sits beside it, and Publish is
    // disabled with the dialog's own sentence rather than left looking live.
    const chip = wrapper.get('[data-testid="save-chip"]')
    expect(chip.text()).toContain('viewing v1 of v2 · read-only')
    expect(chip.text()).not.toContain('saved · v1')
    expect(wrapper.get('.save-chip').classes()).toContain('is-viewing')
    expect(wrapper.get('.document-bar').classes()).toContain('is-read-only')
    expect(wrapper.find('[data-testid="document-lock"]').exists()).toBe(true)
    expect(wrapper.get('.document-name').attributes('disabled')).toBeDefined()
    const publish = wrapper.get('[data-testid="document-publish"]')
    expect(publish.attributes('disabled')).toBeDefined()
    expect(publish.attributes('title')).toBe('you are viewing v1; publish works on head (v2)')
    // The palette is stubbed in this mount; it is handed the same fact.
    expect(wrapper.findComponent(NodePalette).props('readOnly')).toBe(true)

    await wrapper.get('[data-testid="version-back"]').trigger('click')
    await settled()
    expect(chip.text()).toContain('saved · v2')
    expect(wrapper.get('.document-bar').classes()).not.toContain('is-read-only')
    expect(wrapper.find('[data-testid="document-lock"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="document-publish"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('says why when a gesture is swallowed, rather than looking broken', async () => {
    const { wrapper } = await mountOpen()
    await wrapper.get('[data-testid="version-row-1"]').trigger('click')
    await settled()

    // The bar's name is not a text control while read-only (D-15-1), so the
    // rename cannot start there; a rename REQUEST reaching the shell - the
    // bar's own event, as a stale surface might still send it - is the one
    // gesture reachable without Vue Flow, and the store must swallow it aloud.
    expect(wrapper.get('.document-name').attributes('disabled')).toBeDefined()
    wrapper.findComponent(DocumentBar).vm.$emit('rename', 'Typed over v1')
    await flush(4)

    expect(wrapper.get('.document-name').text()).toBe('First')
    expect(wrapper.get('.builder-notice').text()).toContain('v1 is read-only')
    // D-15-5: the notice offers the way back, and pressing it takes it.
    const back = wrapper.get('[data-testid="notice-action"]')
    expect(back.text()).toBe('Back to v2')
    await back.trigger('click')
    await settled()
    expect(wrapper.find('[data-testid="version-viewing"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="save-chip"]').text()).toContain('saved · v2')
    wrapper.unmount()
  })

  it('restores through the CAS save and refreshes the list it just changed', async () => {
    const { wrapper, state } = await mountOpen()
    await wrapper.get('[data-testid="version-row-1"]').trigger('click')
    await settled()

    await wrapper.get('[data-testid="version-restore"]').trigger('click')
    await settled()

    expect(state.puts).toHaveLength(1)
    expect(state.puts[0].expected_version).toBe(2)
    expect((state.puts[0].document as { name: string }).name).toBe('First')
    // D-15-3: the restore says what it is, so the new row can say "restored from v1".
    expect(state.puts[0].source).toBe('restore')
    expect(state.puts[0].restored_from).toBe(1)
    expect(state.head).toBe(3)
    expect(wrapper.get('[data-testid="save-chip"]').text()).toContain('saved · v3')
    expect(wrapper.find('[data-testid="version-viewing"]').exists()).toBe(false)
    expect(wrapper.get('.builder-canvas').classes()).not.toContain('is-read-only')
    // `onSaved` reached the browser: a second list read, and v3 leads it.
    expect(state.versionsCalls).toBe(2)
    expect(wrapper.findAll('.version-row').map((row) => row.attributes('data-testid'))).toEqual([
      'version-row-3',
      'version-row-2',
      'version-row-1',
    ])
    expect(wrapper.get('[data-testid="version-row-3"] [data-testid="version-source"]').text()).toBe('restored from v1')
    wrapper.unmount()
  })

  it('will not open a version over unsaved work', async () => {
    const { wrapper, fetch } = await mountOpen()
    await wrapper.get('.document-name').trigger('click')
    await flush(2)
    const input = wrapper.get('.document-name-input')
    await input.setValue('Edited but not saved')
    await input.trigger('blur')
    await flush(4)

    expect(wrapper.get('[data-testid="version-blocked"]').text()).toContain('save your changes first')
    const before = fetch.mock.calls.length
    await wrapper.get('[data-testid="version-row-1"]').trigger('click')
    await settled()

    expect(fetch.mock.calls.length).toBe(before)
    expect(wrapper.get('.document-name').text()).toBe('Edited but not saved')
    wrapper.unmount()
  })
})
