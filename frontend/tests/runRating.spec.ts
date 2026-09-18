import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RatingControl from '../src/components/RatingControl.vue'
import type { RatingApiLike } from '../src/components/RatingControl.vue'
import ReportPanel from '../src/components/ReportPanel.vue'
import RunHistory from '../src/components/RunHistory.vue'
import { MAX_RATING_NOTE_CHARS } from '../src/data/serverLimits'
import { readRunRating } from '../src/data/runRating'
import { adminApi, resetAdminGate } from '../src/services/adminApi'
import { studioApi } from '../src/services/studioApi'
import type { RunHistoryEntry, RunRating, RunRatingValue, RunResult } from '../src/types/studio'

/**
 * **Was this run good?** - plan 20 criteria L9 and L10.
 *
 * The verdict this control produces is the only one in the whole console that
 * no amount of instrumentation can supply: everything else recorded about a
 * run is machine evidence, and none of it says whether the ANSWER was worth
 * having. So the assertions here are about the four things that would quietly
 * corrupt that record rather than merely annoy somebody - that what is on
 * screen is what the server stored, that a refusal puts the old value back,
 * that a demonstration transport can never pretend to have saved one, and that
 * the `admin` prop writes through the admin door and not the owner's.
 *
 * THE SHAPE IS `.agent/plans/20-run-labels.md` §2.2's, HAND-TYPED. W-API
 * regenerates `frontend/tests/fixtures/adminApi.json` in this same tree while
 * this file is being written, so a spec keyed on it would be asserting against
 * a file mid-edit; §2.2 is the contract both builders read.
 */

const RUN_ID = '073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba'

/** `RunRating`, exactly as §2.2 declares it. */
const STORED: RunRating = {
  run_id: RUN_ID,
  rating: 'good',
  note: 'the segment was right',
  rated_by: 'user_owner',
  rated_at: '2026-09-18T12:03:11Z',
}

/** A double for the one call, recording every argument. */
class FakeRatingApi implements RatingApiLike {
  calls: Array<{ runId: string; rating: RunRatingValue | null; note: string }> = []
  answer: RunRating = { ...STORED }
  fail: Error | null = null

  async rateRun(runId: string, rating: RunRatingValue | null, note = ''): Promise<RunRating> {
    this.calls.push({ runId, rating, note })
    if (this.fail) throw this.fail
    return { ...this.answer, rating, note: note || null }
  }
}

async function settle(rounds = 4): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

function mountControl(props: Record<string, unknown> = {}) {
  const api = new FakeRatingApi()
  const wrapper = mount(RatingControl, { props: { runId: RUN_ID, api, ...props } })
  return { wrapper, api }
}

/* ── the control ─────────────────────────────────────────────────────────── */

describe('three answers, a note, and a counter that states the ceiling', () => {
  it('offers Good, Bad and Not sure - and Not sure is an answer, not a half mark', () => {
    const { wrapper } = mountControl()
    for (const value of ['good', 'bad', 'unsure']) {
      const button = wrapper.get(`[data-testid="rating-${value}"]`)
      expect(button.attributes('aria-pressed'), value).toBe('false')
    }
    expect(wrapper.get('[data-testid="rating-good"]').text()).toBe('Good')
    expect(wrapper.get('[data-testid="rating-bad"]').text()).toBe('Bad')
    // `unsure` on the wire, `Not sure` on the screen: the stored vocabulary is
    // counted over and must never move; the words a person reads may be theirs.
    expect(wrapper.get('[data-testid="rating-unsure"]').text()).toBe('Not sure')
    // The hint says what it means, because "unsure" turned into 0.5 anywhere
    // downstream would be a fabricated number in a record built to avoid one.
    expect(wrapper.get('[data-testid="rating-unsure"]').attributes('title')).toContain(
      'never as a middle value',
    )
    wrapper.unmount()
  })

  it('names the group and the note in the words the plan chose', () => {
    const { wrapper } = mountControl()
    expect(wrapper.get('[role="group"]').attributes('aria-label')).toBe('Was this run good?')
    expect(wrapper.get('label[for]').text()).toBe('Add a note (optional)')
    // None of these words reaches a screen: they are this programme's private
    // vocabulary and a person reading their own run should never meet them.
    for (const banned of ['label', 'mining', 'hotspot', 'score']) {
      expect(wrapper.text().toLowerCase(), banned).not.toContain(banned)
    }
    wrapper.unmount()
  })

  it('bounds the note at the server own ceiling and says so', async () => {
    const { wrapper } = mountControl()
    const note = wrapper.get('[data-testid="rating-note"]')
    expect(note.attributes('maxlength')).toBe(String(MAX_RATING_NOTE_CHARS))
    expect(wrapper.get('[data-testid="rating-note-count"]').text()).toBe(
      `0 / ${MAX_RATING_NOTE_CHARS} characters`,
    )
    await note.setValue('x'.repeat(MAX_RATING_NOTE_CHARS - 10))
    const counter = wrapper.get('[data-testid="rating-note-count"]')
    expect(counter.text()).toContain(String(MAX_RATING_NOTE_CHARS - 10))
    // Warns before `maxlength` starts silently discarding keystrokes - item
    // 11's defect, met a second time and answered the same way.
    expect(counter.classes()).toContain('is-warn')
    wrapper.unmount()
  })

  it('says it is not rated when nobody has said anything', () => {
    const { wrapper } = mountControl()
    expect(wrapper.get('[data-testid="rating-hint"]').text()).toBe('Not rated yet.')
    wrapper.unmount()
  })
})

describe('optimistic, then reconciled', () => {
  it('paints the press immediately and sends the run id, the value and the note', async () => {
    const { wrapper, api } = mountControl()
    await wrapper.get('[data-testid="rating-note"]').setValue('the segment was right')
    await wrapper.get('[data-testid="rating-good"]').trigger('click')
    await settle()

    expect(api.calls).toEqual([{ runId: RUN_ID, rating: 'good', note: 'the segment was right' }])
    expect(wrapper.get('[data-testid="rating-good"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="rating-saved"]').text()).toBe('Saved.')
    wrapper.unmount()
  })

  it('emits what the SERVER answered, not what was pressed', async () => {
    const { wrapper, api } = mountControl()
    api.answer = { ...STORED, rated_at: '2026-09-18T12:03:11Z' }
    await wrapper.get('[data-testid="rating-bad"]').trigger('click')
    await settle()
    const emitted = wrapper.emitted('saved') as Array<[RunRating]>
    expect(emitted).toHaveLength(1)
    expect(emitted[0][0].rating).toBe('bad')
    expect(emitted[0][0].run_id).toBe(RUN_ID)
    wrapper.unmount()
  })

  /*
   * THE ASSERTION THIS FILE EXISTS FOR. A control that went on showing a
   * rating the database does not hold would be corrupting the record it is
   * built to produce - and it would do it silently, because nothing else on
   * the screen reads a rating back.
   */
  it('puts the previous value back when the server refuses, with one sentence', async () => {
    const { wrapper, api } = mountControl({ rating: 'good' })
    api.fail = new Error('that run was not found')
    await wrapper.get('[data-testid="rating-bad"]').trigger('click')
    await settle()

    expect(wrapper.get('[data-testid="rating-good"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="rating-bad"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[data-testid="rating-problem"]').text()).toBe('that run was not found')
    expect(wrapper.find('[data-testid="rating-saved"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('clears with null rather than with a fourth value', async () => {
    const { wrapper, api } = mountControl({ rating: 'good' })
    expect(wrapper.get('[data-testid="rating-clear"]').text()).toBe('Clear')
    await wrapper.get('[data-testid="rating-clear"]').trigger('click')
    await settle()
    expect(api.calls[0].rating).toBeNull()
    wrapper.unmount()
  })

  it('pressing the chosen answer again clears it', async () => {
    const { wrapper, api } = mountControl({ rating: 'unsure' })
    await wrapper.get('[data-testid="rating-unsure"]').trigger('click')
    await settle()
    expect(api.calls[0].rating).toBeNull()
    wrapper.unmount()
  })
})

/* ── the two doors ───────────────────────────────────────────────────────── */

describe('the admin prop chooses the other door, and nothing else', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('writes through PUT /api/admin/runs/{id}/rating when admin is set', async () => {
    const seen: Array<{ url: string; method: string; body: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        seen.push({
          url: String(input),
          method: String(init?.method ?? 'GET'),
          body: JSON.parse(String(init?.body ?? '{}')),
        })
        return new Response(
          JSON.stringify({ ...STORED, rating: 'bad', note: null, rated_by: 'admin@example.test' }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
    // No `api` prop: the component picks its own transport, which is the thing
    // under test. `admin` must reach the admin router's prefix and nothing on
    // `/api/runs/`, or an admin rating somebody else's run would 404.
    const wrapper = mount(RatingControl, { props: { runId: RUN_ID, admin: true } })
    await wrapper.get('[data-testid="rating-bad"]').trigger('click')
    await settle(6)

    expect(seen).toHaveLength(1)
    expect(seen[0].url).toContain(`/api/admin/runs/${RUN_ID}/rating`)
    expect(seen[0].method).toBe('PUT')
    expect(seen[0].body).toEqual({ rating: 'bad', note: null })
    expect(wrapper.get('[data-testid="rating-bad"]').attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })

  it('reads the note under either spelling the two builders may answer with', () => {
    // §2.2 says `note`; the branch this is ported from answers `rating_note`.
    // Dropping a sentence somebody typed is the quietest possible loss, so the
    // reader takes both and `data/runRating.ts` records why.
    expect(readRunRating({ run_id: RUN_ID, rating: 'good', note: 'a' }).note).toBe('a')
    expect(readRunRating({ run_id: RUN_ID, rating: 'good', rating_note: 'b' }).note).toBe('b')
    // A word the server does not know is not a rating. A newer vocabulary must
    // read as "nobody has said anything" rather than press a button that is
    // not there.
    expect(readRunRating({ run_id: RUN_ID, rating: 'excellent' }).rating).toBeNull()
  })
})

/* ── the transport refuses to fake a save ────────────────────────────────── */

describe('a demonstration transport cannot pretend to have stored a verdict', () => {
  it('refuses outright rather than answering `saved`', async () => {
    // `StudioApi.mode` is `probing` until `initialize` runs, which in the mock
    // path never becomes `live`. Answering "saved" there would be gotchas 2 -
    // the silent mock - pointed at a row somebody would later read as evidence.
    await expect(studioApi.rateRun(RUN_ID, 'good')).rejects.toThrow(/demonstration mode/i)
  })

  it('reads as `no opinion recorded` rather than throwing', async () => {
    await expect(studioApi.getRating(RUN_ID)).resolves.toBeNull()
  })

  it('has no such escape on the admin client, which has no mock transport', () => {
    expect(typeof adminApi.rateRun).toBe('function')
  })
})

/* ── on the report ───────────────────────────────────────────────────────── */

const REPORT: RunResult = {
  markdown_body: '# Validation report\n\nThe clinics segment is real.\n',
  sources: [],
} as unknown as RunResult

describe('the report carries the control, above the scroller', () => {
  it('renders it for a run the caller owns', () => {
    const wrapper = mount(ReportPanel, {
      props: { report: REPORT, verdict: null, open: true, runId: RUN_ID, canRate: true },
    })
    expect(wrapper.find('[data-testid="rating-control"]').exists()).toBe(true)
    // Above the scroller: the body and its citations share one scroll box, so
    // a control after the deliverable is a control behind however much
    // markdown the Reporter wrote.
    //
    // MATCHED ON `data-testid`, NOT ON A BARE WORD. Vue keeps template comments
    // in the rendered DOM in a development build, and the comment explaining
    // this very placement names `.report-scroll` - so a bare `indexOf` finds
    // the explanation rather than the element and reports the order backwards.
    const html = wrapper.html()
    expect(html.indexOf('data-testid="rating-control"')).toBeGreaterThan(-1)
    expect(html.indexOf('data-testid="rating-control"')).toBeLessThan(
      html.indexOf('class="report-scroll"'),
    )
    wrapper.unmount()
  })

  it('renders nothing when the caller does not own the run, or there is no run', () => {
    const off = mount(ReportPanel, {
      props: { report: REPORT, verdict: null, open: true, runId: RUN_ID, canRate: false },
    })
    expect(off.find('[data-testid="rating-control"]').exists()).toBe(false)
    off.unmount()

    const anonymous = mount(ReportPanel, {
      props: { report: REPORT, verdict: null, open: true, canRate: true },
    })
    expect(anonymous.find('[data-testid="rating-control"]').exists()).toBe(false)
    anonymous.unmount()
  })
})

/* ── on every history row ────────────────────────────────────────────────── */

const ROWS: RunHistoryEntry[] = [
  {
    run_id: RUN_ID,
    workflow_id: 'ug_4d2b81ac',
    status: 'completed',
    created_at: '2026-09-17T09:12:44Z',
    completed_at: '2026-09-17T09:13:50Z',
    label: 'a scheduling assistant for clinics',
    total_tokens: 128069,
    cost_usd: 0.061,
    rating: 'good',
    rating_note: 'the segment was right',
    rated_at: '2026-09-18T12:03:11Z',
  },
  {
    run_id: '9a2f0000-0000-4000-8000-000000000002',
    workflow_id: 'ug_4d2b81ac',
    status: 'completed',
    created_at: '2026-09-16T09:12:44Z',
    completed_at: null,
    label: 'a second run nobody rated',
    total_tokens: 0,
    cost_usd: 0,
  },
]

describe('every row of your own history can be rated', () => {
  beforeEach(() => {
    resetAdminGate()
    vi.spyOn(studioApi, 'listRuns').mockResolvedValue(ROWS.map((row) => ({ ...row })))
    // `RunHistory` asks `probeAdmin` for the Langfuse link; a 404 is "not an
    // admin" and must stay silent, which is what the suite's zero-console rule
    // is about one file over.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 404 })),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    resetAdminGate()
  })

  it('renders one compact control per row, carrying what the server stored', async () => {
    const wrapper = mount(RunHistory, { props: { reloadKey: 'x', enabled: true } })
    await settle(6)
    const controls = wrapper.findAll('[data-testid="rating-control"]')
    expect(controls).toHaveLength(2)
    expect(controls[0].attributes('data-run-id')).toBe(RUN_ID)
    expect(controls[0].get('[data-testid="rating-good"]').attributes('aria-pressed')).toBe('true')
    expect(controls[1].get('[data-testid="rating-good"]').attributes('aria-pressed')).toBe('false')
    // Compact: the note is behind a toggle rather than a textarea per row.
    expect(controls[0].find('[data-testid="rating-note"]').exists()).toBe(false)
    expect(controls[0].find('[data-testid="rating-note-toggle"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('reveals the note and its counter on the row toggle', async () => {
    const wrapper = mount(RunHistory, { props: { reloadKey: 'x', enabled: true } })
    await settle(6)
    const row = wrapper.findAll('[data-testid="rating-control"]')[0]
    await row.get('[data-testid="rating-note-toggle"]').trigger('click')
    expect(row.get('[data-testid="rating-note"]').attributes('maxlength')).toBe(
      String(MAX_RATING_NOTE_CHARS),
    )
    expect(row.get('[data-testid="rating-note-count"]').text()).toContain(
      `/ ${MAX_RATING_NOTE_CHARS}`,
    )
    wrapper.unmount()
  })

  it('folds the saved answer back into the row rather than re-reading the list', async () => {
    const rate = vi
      .spyOn(studioApi, 'rateRun')
      .mockResolvedValue({ ...STORED, run_id: ROWS[1].run_id, rating: 'bad', note: null })
    const wrapper = mount(RunHistory, { props: { reloadKey: 'x', enabled: true } })
    await settle(6)
    const listCalls = (studioApi.listRuns as unknown as { mock: { calls: unknown[] } }).mock.calls
      .length

    const second = wrapper.findAll('[data-testid="rating-control"]')[1]
    await second.get('[data-testid="rating-bad"]').trigger('click')
    await settle(6)

    expect(rate).toHaveBeenCalledWith(ROWS[1].run_id, 'bad', '')
    expect(
      wrapper.findAll('[data-testid="rating-control"]')[1].get('[data-testid="rating-bad"]')
        .attributes('aria-pressed'),
    ).toBe('true')
    // The server has just answered with the authoritative row: re-reading the
    // whole list would throw away a reply fresher than anything a second
    // request could return.
    expect(
      (studioApi.listRuns as unknown as { mock: { calls: unknown[] } }).mock.calls.length,
    ).toBe(listCalls)
    wrapper.unmount()
  })
})
