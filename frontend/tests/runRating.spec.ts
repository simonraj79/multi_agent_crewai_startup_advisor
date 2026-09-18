import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import RatingControl from '../src/components/RatingControl.vue'
import type { RatingApiLike } from '../src/components/RatingControl.vue'
import ReportPanel from '../src/components/ReportPanel.vue'
import RunHistory from '../src/components/RunHistory.vue'
import { MAX_RATING_NOTE_CHARS } from '../src/data/serverLimits'
import { ratingToSend, readRunRating } from '../src/data/runRating'
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

  /** Set to hold every call open, so a spec can assert what "mid-save" looks
   *  like. Released by `release()`. */
  hold: Array<() => void> = []
  defer = false

  async rateRun(runId: string, rating: RunRatingValue | null, note = ''): Promise<RunRating> {
    this.calls.push({ runId, rating, note })
    if (this.defer) await new Promise<void>((resolve) => this.hold.push(resolve))
    if (this.fail) throw this.fail
    return { ...this.answer, rating, note: note || null }
  }

  release(): void {
    for (const resolve of this.hold.splice(0)) resolve()
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
    // Rated, because the box is locked until a choice exists (D3).
    const { wrapper } = mountControl({ rating: 'good' })
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
    // The choice comes first: the note is locked until there is a verdict for
    // it to be the reason for (D3).
    await wrapper.get('[data-testid="rating-good"]').trigger('click')
    await settle()
    expect(api.calls).toEqual([{ runId: RUN_ID, rating: 'good', note: '' }])
    expect(wrapper.get('[data-testid="rating-good"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="rating-saved"]').text()).toBe('Saved.')

    await wrapper.get('[data-testid="rating-note"]').setValue('the segment was right')
    await wrapper.get('[data-testid="rating-note-save"]').trigger('click')
    await settle()
    expect(api.calls[1]).toEqual({ runId: RUN_ID, rating: 'good', note: 'the segment was right' })
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

/* ── refine round 1: the four defects the verifier found ─────────────────── */

describe('a note cannot be typed into a clear (D3)', () => {
  it('locks the note and its Save until a choice exists, and says why', async () => {
    const { wrapper } = mountControl()
    expect(wrapper.get('[data-testid="rating-note"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="rating-note-save"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="rating-note-locked"]').text()).toBe(
      'Choose Good, Bad or Not sure first.',
    )
    // And it unlocks the moment there is a verdict for the note to explain.
    await wrapper.setProps({ rating: 'bad' })
    expect(wrapper.get('[data-testid="rating-note"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-testid="rating-note-locked"]').exists()).toBe(false)
    wrapper.unmount()
  })

  /*
   * THE DATA LOSS ITSELF. `Save note` used to send `apply(current)` with
   * `current === null`, which the server reads as a CLEAR: it nulls the
   * rating, the note, the actor and the timestamp, answers 200, and the
   * control said "Saved." over the sentence it had just destroyed.
   */
  it('never sends a note alongside a null rating', async () => {
    const { wrapper, api } = mountControl({ rating: 'good' })
    await wrapper.get('[data-testid="rating-note"]').setValue('the segment was right')
    await wrapper.get('[data-testid="rating-clear"]').trigger('click')
    await settle()
    expect(api.calls).toEqual([{ runId: RUN_ID, rating: null, note: '' }])
    wrapper.unmount()
  })
})

describe('every refusal reaches the person in the SERVER own words', () => {
  /*
   * Three new ones since the first round - 409 for a run that has not
   * finished, 403 for a signed-in person on a run nobody owns, 422 for an
   * empty word - and none of them needs a branch here. That is the property
   * worth pinning: the control renders `error.message` verbatim, so a sentence
   * the server learns to say tomorrow arrives on screen without a client
   * release. A client that mapped status codes to its own wording would be a
   * second, quieter copy of the server's rules.
   */
  it.each([
    ['this run has not finished yet, so it cannot be rated'],
    ['that run has no owner, so only an admin can rate it'],
    ['rating must be one of good, bad, unsure, or null'],
  ])('renders %s without rewriting it', async (sentence) => {
    const { wrapper, api } = mountControl({ rating: 'good' })
    api.fail = new Error(sentence)
    await wrapper.get('[data-testid="rating-bad"]').trigger('click')
    await settle()
    expect(wrapper.get('[data-testid="rating-problem"]').text()).toBe(sentence)
    // And the value that was really there is back.
    expect(wrapper.get('[data-testid="rating-good"]').attributes('aria-pressed')).toBe('true')
    wrapper.unmount()
  })
})

describe('a run still going is not offered a verdict (409)', () => {
  it('disables every control and says when it can be rated', () => {
    const { wrapper } = mountControl({ status: 'running' })
    for (const value of ['good', 'bad', 'unsure']) {
      expect(wrapper.get(`[data-testid="rating-${value}"]`).attributes('disabled'), value)
        .toBeDefined()
    }
    expect(wrapper.get('[data-testid="rating-hint"]').text()).toBe(
      'You can rate this run when it has finished.',
    )
    wrapper.unmount()
  })

  it('offers it on every terminal spelling, including the history row own `failed`', () => {
    // `failed` is `BackendRunStatus`; `error` is `RunStatus`. A gate written
    // over one union would hide the control on the run somebody most wants to
    // call Bad.
    for (const status of ['completed', 'failed', 'error', 'cancelled']) {
      const { wrapper } = mountControl({ status })
      expect(wrapper.get('[data-testid="rating-good"]').attributes('disabled'), status)
        .toBeUndefined()
      wrapper.unmount()
    }
  })

  it('refuses to send an empty string, which is now a 422', async () => {
    expect(ratingToSend('')).toBeNull()
    expect(ratingToSend('good')).toBe('good')
    expect(ratingToSend('excellent')).toBeNull()
  })
})

describe('the pressed button keeps focus through its own save (D8)', () => {
  it('leaves document.activeElement on the button rather than dropping to body', async () => {
    const api = new FakeRatingApi()
    const wrapper = mount(RatingControl, {
      props: { runId: RUN_ID, api },
      attachTo: document.body,
    })
    api.defer = true
    const button = wrapper.get('[data-testid="rating-good"]')
    ;(button.element as HTMLButtonElement).focus()
    await button.trigger('click')
    await settle(1)
    // Mid-flight, with the call held open. `disabled` here is what moved focus
    // to `<body>`; `aria-busy` says the same thing and keeps the element in the
    // tab order.
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.attributes('disabled')).toBeUndefined()
    expect(document.activeElement).toBe(button.element)
    // A second press while the first is in flight is swallowed by the FLAG,
    // which is the guard that replaced the attribute.
    await button.trigger('click')
    expect(api.calls).toHaveLength(1)
    api.release()
    await settle()
    expect(document.activeElement).toBe(button.element)
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

  /*
   * D5. `studioApi.getRating` had no caller, so the panel showed three
   * unpressed buttons over a run somebody had already rated - and pressing one
   * would have overwritten a verdict the screen never showed them.
   */
  it('seeds the control from what the server already holds', async () => {
    const read = vi.spyOn(studioApi, 'getRating').mockResolvedValue({
      ...STORED, rating: 'bad', note: 'two branches came home empty',
    })
    const wrapper = mount(ReportPanel, {
      props: { report: REPORT, verdict: null, open: true, runId: RUN_ID, canRate: true },
    })
    await settle()
    expect(read).toHaveBeenCalledWith(RUN_ID)
    const control = wrapper.get('[data-testid="rating-control"]')
    expect(control.get('[data-testid="rating-bad"]').attributes('aria-pressed')).toBe('true')
    expect((control.get('[data-testid="rating-note"]').element as HTMLTextAreaElement).value)
      .toBe('two branches came home empty')

    // A new run re-asks rather than carrying the last run's verdict over.
    await wrapper.setProps({ runId: '9a2f0000-0000-4000-8000-000000000002' })
    await settle()
    expect(read).toHaveBeenCalledTimes(2)
    read.mockRestore()
    wrapper.unmount()
  })

  it('stays usable and unseeded when the rating cannot be read, with no banner', async () => {
    const read = vi.spyOn(studioApi, 'getRating').mockRejectedValue(new Error('read refused'))
    const wrapper = mount(ReportPanel, {
      props: { report: REPORT, verdict: null, open: true, runId: RUN_ID, canRate: true },
    })
    await settle()
    expect(read).toHaveBeenCalled()
    const control = wrapper.get('[data-testid="rating-control"]')
    expect(control.find('[data-testid="rating-problem"]').exists()).toBe(false)
    expect(control.get('[data-testid="rating-good"]').attributes('disabled')).toBeUndefined()
    read.mockRestore()
    wrapper.unmount()
  })

  it('withholds the control while the run is still going', async () => {
    vi.spyOn(studioApi, 'getRating').mockResolvedValue(null)
    const wrapper = mount(ReportPanel, {
      props: { report: REPORT, verdict: null, open: true, runId: RUN_ID, canRate: true, runStatus: 'running' },
    })
    await settle()
    expect(wrapper.get('[data-testid="rating-good"]').attributes('disabled')).toBeDefined()
    vi.restoreAllMocks()
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
  {
    run_id: '9a2f0000-0000-4000-8000-000000000003',
    workflow_id: 'ug_4d2b81ac',
    status: 'running',
    created_at: '2026-09-16T10:12:44Z',
    completed_at: null,
    label: 'a run that has not finished',
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
    expect(controls).toHaveLength(3)
    // The third row is still running, so its control is there and inert (409).
    expect(controls[2].get('[data-testid="rating-good"]').attributes('disabled')).toBeDefined()
    expect(controls[0].get('[data-testid="rating-good"]').attributes('disabled')).toBeUndefined()
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
