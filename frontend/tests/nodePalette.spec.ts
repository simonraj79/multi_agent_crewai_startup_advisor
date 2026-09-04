import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import NodePalette, {
  BUILDER_KIND_MIME,
  BUILDER_TOOL_ID_MIME,
  TOOL_FILTER_DEBOUNCE_MS,
} from '../src/components/builder/NodePalette.vue'
import { resetVocabulary, vocabulary } from '../src/data/builderVocabulary'
import { NODE_KINDS, NODE_KIND_ORDER } from '../src/data/nodeKinds'
import {
  HOTKEY_BINDINGS,
  dispatchHotkey,
  type HotkeyActions,
} from '../src/composables/useBuilderHotkeys'
import type { BuilderToolCatalogueEntry, BuilderVocabulary } from '../src/types/builder'

/**
 * The palette, once the vocabulary is ten kinds in two families (03 D7).
 *
 * Three things are being held here, and only the first was true before:
 *
 * 1. **The palette renders what the SERVER serves, in the server's order.** No
 *    fallback list, ever (cut-list item 17). That is why every test below seeds
 *    a vocabulary rather than reaching for `NODE_KIND_ORDER`: the day the two
 *    disagree, the palette is supposed to follow the server.
 * 2. **The three attachment tiles answer to letters.** Owner's decision 18,
 *    2026-09-04: `T`, `M`, `K` and not `8`, `9`, `0`, because the digits `1`-`7`
 *    already select a kind on this same surface and a second digit row is a
 *    collision an author discovers by pressing one.
 * 3. **A SPECIFIC tool can be dragged.** The generic tile drops a blank `tool`
 *    node; the sub-list under it drops a named one, and the drag carries both
 *    MIME entries so a drop handler that has never heard of the sub-list still
 *    makes the right kind of node.
 *
 * The existing palette tests - the billable counters, the ceiling, the saved
 * graph list, the absent fallback - are in `builderNode.spec.ts` and stay there.
 * This file is the ten-kind delta.
 */

enableAutoUnmount(afterEach)

afterEach(() => {
  resetVocabulary()
  vi.useRealTimers()
})

const CATALOGUE: BuilderToolCatalogueEntry[] = [
  {
    tool_id: 'firecrawl_scrape',
    label: 'Firecrawl scrape',
    category: 'web',
    description: 'Fetch one page as markdown.',
    credential_kind: 'firecrawl',
    attaches_to: ['agent', 'crew'],
    params: [],
  },
  {
    tool_id: 'github_search',
    label: 'GitHub repository search',
    category: 'code',
    description: 'Search public repositories.',
    credential_kind: 'github',
    attaches_to: ['agent'],
    params: [],
  },
  {
    tool_id: 'hn_threads',
    label: 'Hacker News threads',
    category: 'web',
    description: 'Search stories and their comment trees.',
    credential_kind: null,
    attaches_to: ['agent'],
    params: [],
  },
]

/**
 * The C2 **v2** envelope: ten kinds, in `document.py`'s own order.
 *
 * Hand-built, and it deliberately runs AHEAD of what this build's
 * `_vocabulary()` serves - that handler still writes the v1 seven, because C2 v2
 * is criterion 5 and lives on the Python side of this plan. What that means for
 * this file is worth being exact about rather than quiet: these tests prove the
 * palette draws ten tiles WHEN TEN ARE SERVED, and they do not and cannot prove
 * that ten are served today. `tests/nodeKinds.spec.ts` asserts the other half -
 * that every kind the handler actually serves has a record here.
 */
function vocabularyV2(overrides: Partial<BuilderVocabulary> = {}): BuilderVocabulary {
  return {
    schema_id: 'builder.flow/v1',
    node_kinds: [
      'input',
      'agent',
      'crew',
      'gate',
      'router',
      'transform',
      'output',
      'tool',
      'mcp',
      'skill',
    ],
    tools: CATALOGUE,
    tiers: ['cheap', 'escalation'],
    agent_ids: ['market_analyst', 'scoper'],
    crew_ids: ['market'],
    research_tools: ['market_research'],
    transform_ops: ['default', 'format', 'join_text', 'merge', 'pick', 'to_json'],
    router_comparisons: ['contains', 'eq', 'gt', 'gte', 'lt', 'lte', 'ne'],
    router_otherwise: 'otherwise',
    result_body_keys: ['markdown_body'],
    bounds: {
      max_graph_nodes: 24,
      max_billable_nodes: 13,
      max_escalation_nodes: 8,
      max_fanout_width: 4,
      min_router_branches: 2,
      max_cycles: 3,
      max_cycle_iterations: 3,
      max_agent_iter: 8,
      max_guardrail_retries: 2,
      max_label_chars: 40,
      max_name_chars: 80,
      max_gate_message_chars: 2000,
      max_input_chars: 2000,
      max_document_bytes: 262144,
      run_cost_ceiling_usd: 10,
    },
    ...overrides,
  }
}

function mountPalette(props: Record<string, unknown> = {}) {
  return mount(NodePalette, { props })
}

async function palette(props: Record<string, unknown> = {}) {
  const wrapper = mountPalette(props)
  await wrapper.vm.$nextTick()
  return wrapper
}

beforeEach(() => {
  vocabulary.value = vocabularyV2()
})

/* ─── the ten tiles ──────────────────────────────────────────────────────── */

describe('the palette offers ten kinds in two families, in the server order', () => {
  it('renders one tile per served kind, unsorted', async () => {
    const wrapper = await palette()
    expect(
      wrapper.findAll('.builder-tile-name').map((span) => span.text().split(' ')[0]),
    ).toEqual(['Input', 'Agent', 'Crew', 'Gate', 'Router', 'Transform', 'Output', 'Tool', 'MCP', 'Skill'])
  })

  it('follows the server when the server disagrees with this build order', async () => {
    /*
     * The point of rendering `vocabulary.node_kinds` rather than
     * `NODE_KIND_ORDER`. A palette that sorted, or that read its own list, would
     * be a palette drawing a vocabulary nobody serves - and the hotkey printed
     * on each tile would drift off the kind above it.
     */
    vocabulary.value = vocabularyV2({ node_kinds: ['skill', 'agent', 'input'] })
    const wrapper = await palette()
    expect(wrapper.findAll('.builder-tile-name').map((span) => span.text().split(' ')[0])).toEqual([
      'Skill',
      'Agent',
      'Input',
    ])
  })

  it('marks each tile with the family it belongs to', async () => {
    // The palette's half of D5's silhouette channel: an author should be able to
    // tell before they drag that three of these ten produce a different sort of
    // object. The class is read off `nodeKinds.ts`, never recomputed here.
    const wrapper = await palette()
    const tiles = wrapper.findAll('.builder-tile')
    NODE_KIND_ORDER.forEach((kind, index) => {
      expect(tiles[index].classes(), kind).toContain(`is-family-${NODE_KINDS[kind].family}`)
    })
    expect(wrapper.findAll('.builder-tile.is-family-attachment')).toHaveLength(3)
  })
})

/* ─── T, M, K ────────────────────────────────────────────────────────────── */

describe('the attachment kinds answer to letters, not to a second digit row', () => {
  it('prints 1-7 on the flow tiles and T, M, K on the attachments', async () => {
    const wrapper = await palette()
    expect(wrapper.findAll('.builder-tile-key').map((kbd) => kbd.text())).toEqual([
      '1', '2', '3', '4', '5', '6', '7', 'T', 'M', 'K',
    ])
  })

  it('announces the same key to a screen reader as it prints', async () => {
    // A printed key nothing is listening for is worse than no key at all, and a
    // key announced that differs from the one drawn is worse again.
    const wrapper = await palette()
    const tiles = wrapper.findAll('.builder-tile')
    tiles.forEach((tile, index) => {
      expect(tile.attributes('aria-keyshortcuts')).toBe(tile.find('.builder-tile-key').text())
      expect(tile.attributes('aria-keyshortcuts')).toBe(NODE_KINDS[NODE_KIND_ORDER[index]].hotkey)
    })
  })

  it('inserts the three attachment kinds when T, M and K are pressed', () => {
    /*
     * The binding half, dispatched for real rather than inspected. Case is
     * matched insensitively by `matchesChord`, so a lowercase `t` - which is
     * what an author without shift actually sends - must work too, and that is
     * the pressing this asserts.
     */
    const log: string[] = []
    const actions = {
      insertKind: (kind: string) => log.push(kind),
    } as unknown as HotkeyActions
    const focused = { canvasHasFocus: () => true }

    for (const key of ['t', 'm', 'k']) {
      dispatchHotkey(
        new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key }),
        actions,
        focused,
      )
    }
    expect(log).toEqual(['tool', 'mcp', 'skill'])
  })

  it('binds no digit above 7, so 8, 9 and 0 stay free', () => {
    // Decision 18 stated as an absence, which is the half a positive assertion
    // cannot cover: the collision it avoids is with keys nothing has claimed.
    const keys = HOTKEY_BINDINGS.flatMap((binding) => binding.chords.map((chord) => chord.key))
    for (const digit of ['8', '9', '0']) expect(keys).not.toContain(digit)
  })
})

/* ─── the tool sub-list ──────────────────────────────────────────────────── */

describe('a specific tool can be dragged out of the catalogue', () => {
  it('renders no sub-list at all when the server serves no catalogue', async () => {
    // Cut-list item 17, applied to a catalogue rather than to a kind list. An
    // empty search box over nothing is a feature that looks broken; absent is
    // the honest state while `/vocabulary` is still v1.
    vocabulary.value = vocabularyV2({ tools: undefined })
    const wrapper = await palette()
    expect(wrapper.find('.builder-subtoggle').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="tool-row"]')).toHaveLength(0)
  })

  it('opens under the tool tile and lists the whole catalogue', async () => {
    const wrapper = await palette()
    await wrapper.find('.builder-subtoggle').trigger('click')
    expect(wrapper.findAll('[data-testid="tool-row"]').map((row) => row.text())).toEqual([
      'Firecrawl scrapeweb',
      'GitHub repository searchcode',
      'Hacker News threadsweb',
    ])
  })

  it('filters on the label, and only after the debounce has elapsed', async () => {
    /*
     * 250ms, which is Flowise's 500 halved: its catalogue is hundreds of nodes
     * behind a fuzzy scorer, ours is <= 30 entries behind a substring match, and
     * half a second of stillness after a keystroke reads as a hang.
     *
     * Both halves are asserted - that it does NOT filter before the interval and
     * that it does after - because a debounce tested only at the far end passes
     * just as happily with no debounce at all.
     */
    vi.useFakeTimers()
    const wrapper = await palette()
    await wrapper.find('.builder-subtoggle').trigger('click')

    const search = wrapper.find('[data-testid="tool-search"]')
    await search.setValue('git')
    expect(wrapper.findAll('[data-testid="tool-row"]')).toHaveLength(3)

    vi.advanceTimersByTime(TOOL_FILTER_DEBOUNCE_MS - 1)
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[data-testid="tool-row"]')).toHaveLength(3)

    vi.advanceTimersByTime(1)
    await wrapper.vm.$nextTick()
    const rows = wrapper.findAll('[data-testid="tool-row"]')
    expect(rows).toHaveLength(1)
    expect(rows[0].attributes('data-tool-id')).toBe('github_search')
  })

  it('says which query matched nothing rather than showing an empty box', async () => {
    vi.useFakeTimers()
    const wrapper = await palette()
    await wrapper.find('.builder-subtoggle').trigger('click')
    await wrapper.find('[data-testid="tool-search"]').setValue('quantum')
    vi.advanceTimersByTime(TOOL_FILTER_DEBOUNCE_MS)
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('[data-testid="tool-row"]')).toHaveLength(0)
    expect(wrapper.find('.builder-subempty').text()).toContain('quantum')
  })

  it('sets BOTH mime entries when a named tool is dragged', async () => {
    /*
     * The kind entry is what every existing drop handler already reads, so a
     * specific tool lands as a `tool` node even on a canvas that ignores the
     * second key; the id entry is what makes it that particular tool. Two keys
     * rather than one compound value, because a handler that had to parse
     * `tool:firecrawl_scrape` is a handler that can get the split wrong.
     */
    const wrapper = await palette()
    await wrapper.find('.builder-subtoggle').trigger('click')

    const written: Array<[string, string]> = []
    await wrapper.findAll('[data-testid="tool-row"]')[0].trigger('dragstart', {
      dataTransfer: { setData: (type: string, value: string) => written.push([type, value]) },
    })
    expect(written).toEqual([
      [BUILDER_KIND_MIME, 'tool'],
      [BUILDER_TOOL_ID_MIME, 'firecrawl_scrape'],
      // The id rather than the word `tool`, because that is the useful thing to
      // paste into a text field in another window.
      ['text/plain', 'firecrawl_scrape'],
    ])
  })

  it('keeps the generic tile dragging the kind and nothing more', async () => {
    // The two gestures stay distinguishable: the tile is "a tool node", the row
    // is "that tool". A tile that quietly carried the first catalogue id would
    // make an author's blank node arrive pre-configured as something they never
    // chose.
    const wrapper = await palette()
    const written: Array<[string, string]> = []
    await wrapper.findAll('.builder-tile')[7].trigger('dragstart', {
      dataTransfer: { setData: (type: string, value: string) => written.push([type, value]) },
    })
    expect(written).toEqual([
      [BUILDER_KIND_MIME, 'tool'],
      ['text/plain', 'tool'],
    ])
  })
})
