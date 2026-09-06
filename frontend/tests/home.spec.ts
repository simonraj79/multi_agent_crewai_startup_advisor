import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import HomeView from '../src/views/HomeView.vue'
import { PRODUCT_NAME, PRODUCT_SENTENCE } from '../src/data/brand'
import { ALL_BUILDER_TEMPLATES } from '../src/data/builderTemplates'
import { HANDOFF_KEY, writeRunHandoff } from '../src/data/builderRunHandoff'
import { takeRevealHistory } from '../src/components/RunHistory.vue'
import { scopedKey } from '../src/data/identityStorage'
import { ACTIVE_RUN_STORAGE_KEY } from '../src/composables/useValidatorRun'
import { studioApi } from '../src/services/studioApi'
import { MOCK_GRAPH } from '../src/data/mockGraph'
import { emptyDocument } from './helpers'
import type { BuilderDocumentSummary } from '../src/types/builder'

/**
 * The home lists every workflow, and it knows when it should not be on screen
 * at all.
 *
 * `docs/ux-shell/DEFINITION-OF-DONE.md` U1 and U2. Two halves, and the second
 * is the one worth the most: `#/` used to BE the console, so moving it had to
 * leave refresh recovery exactly where it was. The rule is
 * `homeResumesConsole` (pure, and `workspaceRoute.spec.ts` owns it); what this
 * file pins is the READING - the handoff before any request, the pointer
 * behind one, and the fact that a terminal run becomes a card rather than a
 * hand-over.
 *
 * WHY IT MOUNTS THE VIEW RATHER THAN `App`. `builderShell.spec.ts` owns which
 * hash mounts which view and stubs all three; this file owns what the home
 * does once it is mounted, which needs it unstubbed. Between them they cover
 * the route and the page without either one testing both.
 */

const SAVED: BuilderDocumentSummary[] = [
  {
    id: 'ug_0a1b2c3d',
    name: 'Weekly digest',
    version: 3,
    status: 'published',
    live_version: 3,
    created_at: '2026-09-01T09:00:00Z',
    updated_at: '2026-09-05T09:00:00Z',
  },
  {
    id: 'ug_1b2c3d4e',
    name: 'Support triage',
    version: 1,
    status: 'draft',
    live_version: null,
    created_at: '2026-09-02T09:00:00Z',
    updated_at: '2026-09-06T09:00:00Z',
  },
]

/** What `GET /api/runs/{id}` will answer, per test. */
let runStatus = 'running'
/** Every URL the page asked for, so a test can assert what it did NOT ask. */
let asked: string[] = []

function stubFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      asked.push(url)
      let body: unknown = []
      if (url.includes('/api/builder/workflows/')) {
        body = { id: 'ug_0a1b2c3d', document: emptyDocument(), status: 'draft', version: 1 }
      } else if (url.includes('/api/builder/workflows')) {
        body = SAVED
      } else if (url.includes('/graph')) {
        body = MOCK_GRAPH
      } else if (url.includes('/api/runs/')) {
        body = { run_id: 'run-1', status: runStatus, frames: {}, usage: {} }
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

/**
 * Drain microtasks AND the macrotask queue.
 *
 * `helpers.flush` drains microtasks alone, which is enough for a composable's
 * promise chain and not enough here: `studioApi.initialize` races the token
 * mint against a `setTimeout`, so the pointer check has a real timer in it.
 * A microtask-only flush left `resolvePointer` pending and the assertions read
 * a page that had not finished asking.
 */
async function settle(rounds = 6): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

function mountHome(resumeOnLoad = true) {
  return mount(HomeView, {
    props: { user: null, resumeOnLoad },
  })
}

/** A run pointer of the shape `useValidatorRun` writes, for nobody in particular. */
function storeRunPointer(runId = 'run-1'): void {
  window.localStorage.setItem(
    scopedKey(ACTIVE_RUN_STORAGE_KEY, null),
    JSON.stringify({ version: 1, runId, sessionId: 'sess-1', workflowId: 'idea-validator' }),
  )
}

beforeEach(() => {
  asked = []
  runStatus = 'running'
  window.localStorage.clear()
  window.sessionStorage.clear()
  // The singleton carries its transport decision between tests in one file, so
  // it is put back to `probing` rather than left holding the previous test's.
  studioApi.mode = 'probing'
  stubFetch()
})

afterEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('the home lists every workflow this account can open', () => {
  it('names the built-in workflow and says it is run only', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    const card = wrapper.get('[data-testid="home-validator"]')
    expect(card.text()).toContain(MOCK_GRAPH.name)
    expect(card.text().toLowerCase()).toContain('run only')
  })

  it('lists every saved document with its status and version', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    const rows = wrapper.findAll('[data-testid="home-library"] li')
    expect(rows).toHaveLength(SAVED.length)
    const text = wrapper.get('[data-testid="home-library"]').text()
    for (const row of SAVED) {
      expect(text).toContain(row.name)
    }
    expect(text).toContain('published')
    expect(text).toContain('draft')
  })

  it('draws a thumbnail for a saved document once its document has arrived', async () => {
    const wrapper = mountHome(false)
    await settle(12)
    // `GET /api/builder/workflows` is a SUMMARY and carries no document, so the
    // picture costs one read per row. What this pins is that the read happens
    // and lands: without it every row would keep the held-open empty slot.
    expect(wrapper.findAll('[data-testid="home-library"] svg').length).toBeGreaterThan(0)
  })

  it('shows all nine templates by title, both of the gallery rows', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    const list = wrapper.get('[data-testid="home-templates"]')
    expect(wrapper.findAll('[data-testid="home-templates"] li')).toHaveLength(9)
    expect(ALL_BUILDER_TEMPLATES).toHaveLength(9)
    for (const template of ALL_BUILDER_TEMPLATES) {
      expect(list.text(), template.id).toContain(template.title)
    }
  })

  it('names the tab after the product and nothing else', async () => {
    mountHome(false)
    await settle(4)
    expect(document.title).toBe(PRODUCT_NAME)
  })

  /* ── ROUND-2 X1 and X2: what this page IS, and what its cards do ─────────
   *
   * Three assertions over three findings the audit measured on `8d17209`, and
   * each fails on the state it was written for rather than on a paraphrase:
   * H1 (no product sentence anywhere on the signed-in home), N1 (the same
   * object called `graph` here and `workflow` one route away) and ruling 4 (a
   * template card whose click had an unstated effect).
   */

  it('says what the product is, under the brand, from the one constant', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    expect(wrapper.get('[data-testid="product-sentence"]').text()).toBe(PRODUCT_SENTENCE)
  })

  it('names the template shelf and says what a click does', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    const text = wrapper.text()
    expect(text).toContain('TEMPLATES')
    expect(text).toContain('Start from a working example')
    expect(text).toContain('Click one to copy it onto the canvas as a new workflow.')
    // The words it replaced. `A shape that already works` is a good sentence
    // and was a bad label: it names no category, which is the whole of N4.
    expect(text).not.toContain('START FROM')
    expect(text).not.toContain('A shape that already works')
  })

  it('gives every template card the action its click performs', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    const actions = wrapper.findAll('[data-testid="home-templates"] .home-card-action')
    expect(actions).toHaveLength(9)
    for (const action of actions) expect(action.text()).toContain('Use this template')
  })

  it('calls the thing a person makes a workflow, and never a graph', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    expect(wrapper.text()).toContain('YOUR WORKFLOWS')
    // Case-insensitive and word-anchored: `GraphThumbnail`'s class names are
    // not on screen, and the point is the noun a reader sees.
    expect(wrapper.text()).not.toMatch(/\bgraphs?\b/i)
  })

  it('says so, and stays a list, when the saved graphs cannot be read', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes('/api/builder/workflows')) {
          return new Response(JSON.stringify({ detail: 'nope' }), {
            status: 500,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        return new Response(JSON.stringify(MOCK_GRAPH), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    const wrapper = mountHome(false)
    await settle(10)
    expect(wrapper.find('.home-empty.is-problem').exists()).toBe(true)
    // The templates and the built-in workflow are unaffected: one failed read
    // must not blank a page whose other two sections need nothing from it.
    expect(wrapper.findAll('[data-testid="home-templates"] li')).toHaveLength(9)
  })
})

describe('the home opens things', () => {
  it('sends the built-in workflow to the console', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    await wrapper.get('[data-testid="home-validator"]').trigger('click')
    expect(wrapper.emitted('run')).toHaveLength(1)
  })

  it('opens a saved document by id', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    await wrapper.get('[data-testid="home-document-ug_0a1b2c3d"]').trigger('click')
    expect(wrapper.emitted('openDocument')?.[0]).toEqual(['ug_0a1b2c3d'])
  })

  it('opens a template by id, which is what survives a rename', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    await wrapper.get('[data-testid="home-template-news-to-social"]').trigger('click')
    expect(wrapper.emitted('openTemplate')?.[0]).toEqual(['news-to-social'])
  })

  it('offers the empty builder for a workflow that does not exist yet', async () => {
    const wrapper = mountHome(false)
    await settle(10)
    await wrapper.get('[data-testid="home-build"]').trigger('click')
    expect(wrapper.emitted('build')).toHaveLength(1)
  })
})

describe('the home hands the console back what it was doing (D2)', () => {
  it('hands over for a builder handoff without asking the server anything', async () => {
    writeRunHandoff({ workflowId: 'ug_0a1b2c3d', inputField: 'topic', name: 'Weekly digest' }, null)
    const wrapper = mountHome()
    await settle(10)
    expect(wrapper.emitted('resume')).toHaveLength(1)
    // The handoff is synchronous, so the hand-over must not wait on a network
    // round trip that can time out - and there is no run to ask about anyway.
    expect(asked.some((url) => url.includes('/api/runs/'))).toBe(false)
  })

  it('hands over for a run the server says is still going', async () => {
    storeRunPointer()
    runStatus = 'waiting'
    const wrapper = mountHome()
    await settle(12)
    expect(wrapper.emitted('resume')).toHaveLength(1)
  })

  it('hands over when the server will not say, because recovery wins', async () => {
    storeRunPointer()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes('/api/runs/')) throw new Error('offline')
        return new Response(JSON.stringify(url.includes('/graph') ? MOCK_GRAPH : []), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    const wrapper = mountHome()
    await settle(12)
    expect(wrapper.emitted('resume')).toHaveLength(1)
  })

  it('stays put for a finished run and offers it as a card instead', async () => {
    storeRunPointer()
    runStatus = 'completed'
    const wrapper = mountHome()
    await settle(12)
    expect(wrapper.emitted('resume')).toBeUndefined()
    const card = wrapper.get('.home-last-run')
    expect(card.text()).toContain('Finished')
    await card.get('button').trigger('click')
    expect(wrapper.emitted('run')).toHaveLength(1)
  })

  it('stays put when there is nothing to recover', async () => {
    const wrapper = mountHome()
    await settle(12)
    expect(wrapper.emitted('resume')).toBeUndefined()
    expect(wrapper.find('.home-last-run').exists()).toBe(false)
  })

  it('never hands over on a visit that is not the page load', async () => {
    // Pressing `Workflows` from a live console is leaving, not recovering.
    // Asked on every mount, the same predicate would bounce the reader
    // straight back and the breadcrumb would read as broken.
    storeRunPointer()
    window.sessionStorage.setItem(
      scopedKey(HANDOFF_KEY, null),
      JSON.stringify({ workflowId: 'ug_0a1b2c3d', inputField: 'topic', name: 'Weekly digest' }),
    )
    const wrapper = mountHome(false)
    await settle(12)
    expect(wrapper.emitted('resume')).toBeUndefined()
  })
})

/*
 * EVERY CARD NAMES ITS ACTION, AND THE HOME MENTIONS RUNS - item 3, ROUND-2 X2,
 * AUDIT-R2 H2 and the Q1/Q5 failures behind it.
 *
 * Measured on `8d17209`: a card was a mystery target you learned by clicking,
 * the LAST RUN strip read `LAST RUN / Finished / Open it` - three lines that
 * say a run happened and never what it was about - and after two finished runs
 * the page mentioned runs nowhere else at all.
 */
describe('the home names what each card does, and how to get back to a run', () => {
  /** A pointer for a specific workflow, which the plain helper does not take. */
  function storePointerFor(workflowId: string, runId = 'run-1'): void {
    window.localStorage.setItem(
      scopedKey(ACTIVE_RUN_STORAGE_KEY, null),
      JSON.stringify({ version: 1, runId, sessionId: 'sess-1', workflowId }),
    )
  }

  it('names the workflow on the last-run card, and keeps the state beside it', async () => {
    storePointerFor('idea-validator')
    runStatus = 'completed'
    const wrapper = mountHome()
    await settle(12)

    const card = wrapper.get('.home-last-run')
    expect(card.get('h2').text()).toBe(MOCK_GRAPH.name)
    // Not instead of: `Finished` is the other half of what this card says.
    expect(card.text()).toContain('Finished')
  })

  it('names a SAVED workflow on that card, from the library it already fetched', async () => {
    storePointerFor(SAVED[0].id)
    runStatus = 'completed'
    const wrapper = mountHome()
    await settle(14)

    expect(wrapper.get('.home-last-run h2').text()).toBe(SAVED[0].name)
    // No extra request: the name came off `GET /api/builder/workflows`, which
    // this page reads for the list anyway.
    expect(asked.filter((url) => url.includes(`/api/runs/`))).toHaveLength(1)
  })

  it('falls back to a heading that is true when the workflow cannot be named', async () => {
    storePointerFor('ug_deleted0')
    runStatus = 'completed'
    const wrapper = mountHome()
    await settle(14)

    expect(wrapper.get('.home-last-run h2').text()).toBe('Your last run')
    expect(wrapper.get('.home-last-run').text()).toContain('Finished')
  })

  it('gives the built-in card and every saved card the action its click performs', async () => {
    const wrapper = mountHome(false)
    await settle(12)

    expect(wrapper.get('[data-testid="home-validator"] .home-card-action').text())
      .toContain('Run')
    const saved = wrapper.findAll('[data-testid="home-library"] .home-card-action')
    expect(saved).toHaveLength(SAVED.length)
    for (const action of saved) expect(action.text()).toContain('Open in Build')
  })

  it('offers Run on a PUBLISHED saved workflow and on no other', async () => {
    const wrapper = mountHome(false)
    await settle(14)

    // SAVED[0] is published; SAVED[1] is a draft, and a run resolves a
    // REGISTERED version, so a Run there would answer 404.
    expect(wrapper.find(`[data-testid="home-run-${SAVED[0].id}"]`).exists()).toBe(true)
    expect(wrapper.find(`[data-testid="home-run-${SAVED[1].id}"]`).exists()).toBe(false)
  })

  it('writes the same handoff the builder writes, with the graph\u2019s own input key', async () => {
    const wrapper = mountHome(false)
    await settle(14)

    await wrapper.get(`[data-testid="home-run-${SAVED[0].id}"]`).trigger('click')

    const raw = window.sessionStorage.getItem(scopedKey(HANDOFF_KEY, null))
    expect(raw, 'pressing Run wrote no handoff').not.toBeNull()
    const handoff = JSON.parse(raw as string) as Record<string, string>
    expect(handoff.workflowId).toBe(SAVED[0].id)
    expect(handoff.name).toBe(SAVED[0].name)
    // Not the literal `idea`: the key is the document's own, which is why the
    // action waits for the document rather than firing off the summary.
    expect(handoff.inputField).toBe(emptyDocument().input_field)
    expect(wrapper.emitted('run')).toHaveLength(1)
  })

  it('has a Run history link that asks the console to show the list, once', async () => {
    const wrapper = mountHome(false)
    await settle(12)

    await wrapper.get('[data-testid="home-run-history"]').trigger('click')
    expect(wrapper.emitted('run')).toHaveLength(1)

    // One shot, so a reload of `#/run` does not scroll a reader away from a run
    // they are watching. `RunHistory.vue` owns both halves of the note.
    expect(takeRevealHistory()).toBe(true)
    expect(takeRevealHistory()).toBe(false)
  })
})
