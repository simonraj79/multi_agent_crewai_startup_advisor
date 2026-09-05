import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import GateCard from '../src/components/GateCard.vue'
import type { PendingGate } from '../src/types/studio'

function gate(overrides: Partial<PendingGate> = {}): PendingGate {
  return {
    gateId: 'scope-confirmation',
    nodeId: 'confirm_scope',
    title: 'Confirm scope',
    summary: 'Check the market, primary user, and technical claim.',
    editable: true,
    expiresAt: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
    expired: false,
    options: [
      { id: 'scope_revise', label: 'Revise', emphasis: 'danger' },
      { id: 'scope_ok', label: 'Approve scope', emphasis: 'primary' },
    ],
    fields: { market: 'Design-to-code tooling' },
    ...overrides,
  }
}

function mountGate(props: { gate: PendingGate; submitting?: boolean }) {
  return mount(GateCard, { props: { submitting: false, ...props } })
}

function actionButtons(wrapper: ReturnType<typeof mountGate>) {
  return wrapper.findAll('.gate-actions button')
}

/**
 * PRD F03 / Scenario C. The server keeps an expired gate open and still accepts
 * and records a late reply. A client that disables the controls locks the
 * operator out of a run the server would happily finish - that was the bug, and
 * these tests exist to stop it coming back.
 */
describe('GateCard expiry is informational, never a lockout', () => {
  it('keeps every option enabled after the server reports expiry', () => {
    const wrapper = mountGate({ gate: gate({ expired: true, overdueSeconds: 240 }) })
    const buttons = actionButtons(wrapper)

    expect(buttons).toHaveLength(2)
    for (const button of buttons) {
      expect(button.attributes('disabled')).toBeUndefined()
    }
  })

  it('still submits a late reply, with the edited fields', async () => {
    const wrapper = mountGate({ gate: gate({ expired: true, overdueSeconds: 240 }) })
    await wrapper.get('input').setValue('Design tooling, revised')
    await actionButtons(wrapper)[1].trigger('click')

    expect(wrapper.emitted('submit')).toEqual([['scope_ok', { market: 'Design tooling, revised' }]])
  })

  it('reads as a notice rather than a failure', () => {
    const wrapper = mountGate({ gate: gate({ expired: true, overdueSeconds: 240 }) })
    const notice = wrapper.get('.gate-late')

    expect(notice.attributes('role')).toBe('status')
    expect(notice.text()).toContain('The run has not failed')
    expect(notice.text()).toContain('recorded as late')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('.gate-expiry').classes()).toContain('is-expired')
    expect(wrapper.findAll('.late-tag')).toHaveLength(2)
  })

  it('adds the alert wording without touching the controls', () => {
    const wrapper = mountGate({ gate: gate({ expired: true, alerting: true, overdueSeconds: 900 }) })

    expect(wrapper.get('.gate-late').text()).toContain('flagged for review')
    for (const button of actionButtons(wrapper)) {
      expect(button.attributes('disabled')).toBeUndefined()
    }
  })

  it('keeps the controls live when only the local countdown has run out', async () => {
    const wrapper = mountGate({
      gate: gate({ expired: false, expiresAt: new Date(Date.now() - 30 * 1000).toISOString() }),
    })

    // The client never decides expiry, so no late notice and no lockout.
    expect(wrapper.find('.gate-late').exists()).toBe(false)
    expect(wrapper.get('.gate-expiry').text()).toContain('Deadline passed')
    for (const button of actionButtons(wrapper)) {
      expect(button.attributes('disabled')).toBeUndefined()
    }

    await actionButtons(wrapper)[0].trigger('click')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toBe('scope_revise')
  })

  it('blocks only while a reply is already in flight', async () => {
    const wrapper = mountGate({ gate: gate({ expired: true }), submitting: true })

    for (const button of actionButtons(wrapper)) {
      expect(button.attributes('disabled')).toBeDefined()
    }
    await actionButtons(wrapper)[1].trigger('click')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('sends no fields for a read-only gate', async () => {
    const wrapper = mountGate({
      gate: gate({
        editable: false,
        expired: true,
        fields: undefined,
        verdict: 'NEEDS_WORK',
        confidence: 0.62,
        options: [{ id: 'verdict_ok', label: 'Accept verdict', emphasis: 'primary' }],
      }),
    })

    expect(wrapper.get('.verdict-row').text()).toContain('Needs work')
    expect(wrapper.get('.verdict-row').text()).toContain('62% confidence')
    await actionButtons(wrapper)[0].trigger('click')
    expect(wrapper.emitted('submit')).toEqual([['verdict_ok', undefined]])
  })

  it('shows a countdown while the deadline is still ahead', () => {
    const wrapper = mountGate({ gate: gate() })

    expect(wrapper.get('.gate-expiry').text()).toMatch(/\d{2}:\d{2} remaining/)
    expect(wrapper.get('.gate-expiry').classes()).not.toContain('is-expired')
    expect(wrapper.find('.gate-late').exists()).toBe(false)
  })
})
