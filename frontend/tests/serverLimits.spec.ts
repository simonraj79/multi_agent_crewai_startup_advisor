import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatusPanel from '../src/components/StatusPanel.vue'
import {
  IDEA_CHARS_WARN_AT,
  MAX_IDEA_CHARS,
  MIN_IDEA_CHARS,
  readErrorDetail,
  retryAfterSentence,
} from '../src/data/serverLimits'
import { zeroUsage } from './helpers'

/**
 * The client knows the server's bounds now.
 *
 * Closes remaining-work item 11. The server has always enforced
 * `MAX_RUN_INPUT_CHARS` and answered a genuinely good 422 - "inputs.idea is
 * limited to 2000 characters; this one is 2001" - and the client had no idea a
 * limit existed: no `maxlength` anywhere in `src/`, a character counter that
 * counted calmly past it, and an error path that rendered the raw JSON
 * envelope, braces and all.
 */

function mountPanel(overrides: Record<string, unknown> = {}) {
  return mount(StatusPanel, {
    props: {
      status: 'idle',
      transportMode: 'live',
      transportProblem: '',
      connection: 'offline',
      runId: '',
      idea: 'A scheduling assistant for small veterinary clinics',
      usage: zeroUsage(),
      lastSequence: 0,
      droppedFrames: 0,
      canLaunch: true,
      isActive: false,
      primaryLabel: 'Launch run',
      activeView: 'graph',
      gatesMode: 'human',
      error: '',
      downloadStatus: 'idle',
      downloadMessage: '',
      ...overrides,
    },
  })
}

describe('the bounds are stated where they are enforced', () => {
  it('matches the server constant', () => {
    // Drift here is the whole hazard of a duplicated constant, so it is a test
    // rather than a comment. `MAX_RUN_INPUT_CHARS` in src/brief_crew/config.py.
    expect(MAX_IDEA_CHARS).toBe(2000)
  })

  it('caps the textarea at the server limit', () => {
    const textarea = mountPanel().find('#idea')
    expect(textarea.attributes('maxlength')).toBe(String(MAX_IDEA_CHARS))
  })

  it('states the ceiling in the counter, not just the position', () => {
    const panel = mountPanel({ idea: 'x'.repeat(40) })
    expect(panel.find('#idea-hint').text()).toBe(`40 / ${MAX_IDEA_CHARS} characters`)
  })

  it('explains the disabled Launch below the minimum', () => {
    // An operator who has typed six characters and sees a dead button has no
    // way to learn why. `canLaunch` is the client's own rule, not the server's.
    const panel = mountPanel({ idea: 'six ch', canLaunch: false })
    expect(panel.find('#idea-hint').text()).toBe(
      `${MIN_IDEA_CHARS - 6} more characters to launch`,
    )
  })

  it('says nothing about the minimum on an empty box', () => {
    // Before anyone has typed, a countdown to a minimum is nagging, not help.
    const panel = mountPanel({ idea: '', canLaunch: false })
    expect(panel.find('#idea-hint').text()).toBe(`0 / ${MAX_IDEA_CHARS} characters`)
  })

  it('warns as the hard cap approaches', () => {
    // `maxlength` discards keystrokes silently, so the approach is the only
    // moment a warning can still be acted on.
    const panel = mountPanel({ idea: 'x'.repeat(MAX_IDEA_CHARS - IDEA_CHARS_WARN_AT) })
    const hint = panel.find('#idea-hint')
    expect(hint.text()).toBe(`${IDEA_CHARS_WARN_AT} characters left of ${MAX_IDEA_CHARS}`)
    expect(hint.classes()).toContain('is-warn')
  })

  it('says plainly when the cap is reached', () => {
    const panel = mountPanel({ idea: 'x'.repeat(MAX_IDEA_CHARS) })
    expect(panel.find('#idea-hint').text()).toBe(`${MAX_IDEA_CHARS} character limit reached`)
    expect(panel.find('#idea-hint').classes()).toContain('is-warn')
  })

  it('stays quiet well inside the bound', () => {
    const panel = mountPanel({ idea: 'x'.repeat(MAX_IDEA_CHARS - IDEA_CHARS_WARN_AT - 1) })
    expect(panel.find('#idea-hint').classes()).not.toContain('is-warn')
  })
})

describe('a refusal reads as a sentence, not an envelope', () => {
  it('unwraps a FastAPI detail string', () => {
    const body = JSON.stringify({
      detail: 'inputs.idea is limited to 2000 characters; this one is 2001',
    })
    expect(readErrorDetail(body, 422)).toBe(
      'inputs.idea is limited to 2000 characters; this one is 2001',
    )
  })

  it('unwraps pydantic\'s list-of-errors shape', () => {
    const body = JSON.stringify({
      detail: [
        { loc: ['body', 'inputs'], msg: 'Value error, too many keys' },
        { loc: ['body', 'gates'], msg: 'Input should be human or auto' },
      ],
    })
    expect(readErrorDetail(body, 422)).toBe(
      'Value error, too many keys; Input should be human or auto',
    )
  })

  it('keeps plain text as it is', () => {
    expect(readErrorDetail('the service is at capacity', 429)).toBe(
      'the service is at capacity',
    )
  })

  it('falls back rather than swallowing an unparseable body', () => {
    // An ugly message beats a missing one.
    expect(readErrorDetail('{not json', 500)).toBe('{not json')
  })

  it('names the status when the body is empty', () => {
    expect(readErrorDetail('', 503)).toBe('Request failed (503)')
  })

  it('falls back on JSON with no usable detail', () => {
    const body = JSON.stringify({ error: 'something', detail: [] })
    expect(readErrorDetail(body, 400)).toBe(body)
  })
})

describe('Retry-After is finally read', () => {
  it('turns seconds into a sentence', () => {
    expect(retryAfterSentence('30')).toBe(' Try again in 30s.')
  })

  it('rounds up a fractional wait', () => {
    expect(retryAfterSentence('12.4')).toBe(' Try again in 13s.')
  })

  it('switches to minutes past a minute', () => {
    expect(retryAfterSentence('180')).toBe(' Try again in about 3 min.')
  })

  it('says nothing when the header is absent', () => {
    // `CORS_EXPOSE_HEADERS` makes this readable cross-origin, but a
    // same-origin dev server or a misconfigured deploy can still omit it.
    expect(retryAfterSentence(null)).toBe('')
  })

  it('says nothing for a malformed or non-positive value', () => {
    expect(retryAfterSentence('soon')).toBe('')
    expect(retryAfterSentence('0')).toBe('')
    expect(retryAfterSentence('-5')).toBe('')
  })
})

/**
 * The way back to the built-in validator (2026-09-05).
 *
 * It used to live on the handoff banner, which is the only place it lived - and
 * that banner now retires itself when a run reaches a terminal status, because
 * a cold reader found it stacked above "Run failed" still saying "Running your
 * published graph …". Retiring it without moving the control would have removed
 * the route home at the exact moment somebody who had just watched a published
 * graph fail would reach for it, so the control moved into the WORKFLOW well:
 * the one surface that names the graph Launch is about to spend money on.
 */
describe('the way back from a published graph', () => {
  it('is absent when the console is running the built-in workflow', () => {
    // No handoff, so there is nowhere to go back TO, and a control that did
    // nothing would be worse than none.
    expect(mountPanel().find('.workflow-home').exists()).toBe(false)
  })

  it('appears in the workflow well when a published graph is loaded', () => {
    const panel = mountPanel({ canReturnHome: true, workflowName: 'News to social post' })
    const back = panel.get('.read-only-well .workflow-home')
    // The label names the DESTINATION rather than the direction. A screen
    // reader listing the controls in this rail would otherwise hear "back"
    // with no object.
    expect(back.attributes('aria-label')).toBe('Back to Idea Validator')
    // And the well still names the graph it is leaving.
    expect(panel.get('.workflow-title').text()).toBe('News to social post')
  })

  it('emits once when it is pressed', async () => {
    const panel = mountPanel({ canReturnHome: true })
    await panel.get('.workflow-home').trigger('click')
    expect(panel.emitted('returnHome')).toHaveLength(1)
  })

  it('is disabled while a run is in flight, because leaving reloads the page', () => {
    // `backToValidator` rebuilds the composable by reloading - the honest way
    // to change a workflow that is a construction option - so pressing it
    // mid-run would drop a run that is spending money.
    const panel = mountPanel({ canReturnHome: true, isActive: true })
    expect(panel.get('.workflow-home').attributes('disabled')).toBeDefined()
  })

  it('is a real button, so it is reachable without a pointer', () => {
    const back = mountPanel({ canReturnHome: true }).get('.workflow-home')
    expect(back.element.tagName).toBe('BUTTON')
    expect(back.attributes('type')).toBe('button')
    // Not taken out of the tab order: this one is the only route home, unlike
    // the 640px scrim, whose gesture the rail toggles already carry.
    expect(back.attributes('tabindex')).toBeUndefined()
  })
})
