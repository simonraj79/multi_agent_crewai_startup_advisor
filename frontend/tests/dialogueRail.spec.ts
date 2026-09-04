import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DialogueRail from '../src/components/DialogueRail.vue'
import {
  characterIndex,
  type DialogueEntry,
} from '../src/composables/useRunChoreography'

/**
 * The rail that shows what the agents said.
 *
 * The reveal itself is `runChoreography.spec.ts`'s - it is arithmetic over a
 * clock and belongs where it can be driven at exact millisecond boundaries.
 * What is here is what the rail DOES with the numbers: how much of an entry is
 * on screen, which entries are folded, what a truncated one says, and whether
 * the avatar wears the same colour as the node's own medallion.
 */

function entry(overrides: Partial<DialogueEntry> = {}): DialogueEntry {
  return {
    callId: 'call-1',
    nodeId: 'research_market',
    role: 'Market Analyst',
    task: 'market_task',
    text: 'The market is larger than the scope implies.',
    revealed: 43,
    truncated: false,
    tokens: { prompt: 640, completion: 120 },
    at: 1_700_000_000_000,
    collapsed: false,
    ...overrides,
  }
}

function rail(entries: DialogueEntry[], collapsed = false) {
  return mount(DialogueRail, {
    props: { entries, collapsed, characterOf: characterIndex },
  })
}

describe('the dialogue rail', () => {
  it('says so when nothing has been said', () => {
    expect(rail([]).text()).toContain('Nothing said yet')
  })

  it('shows only the revealed part of an entry', () => {
    // The difference the critic sees in a recording: the reference lands a
    // bubble whole at NODE_END and this reads as speech.
    const wrapper = rail([entry({ revealed: 10 })])
    expect(wrapper.get('[data-testid="dialogue-text"]').text()).toBe('The market')
  })

  it('floors a fractional reveal rather than rendering half a character', () => {
    const wrapper = rail([entry({ revealed: 10.9 })])
    expect(wrapper.get('[data-testid="dialogue-text"]').text()).toBe('The market')
  })

  it('gives the avatar the colour of the node it speaks for', () => {
    // The property the whole character design rests on. The reference's chat
    // avatars never match its graph, because its chat path omits the node id.
    const wrapper = rail([entry({ nodeId: 'research_market' })])
    const avatar = wrapper.get('[data-testid="dialogue-avatar"]')
    expect(avatar.attributes('data-character')).toBe(String(characterIndex('research_market')))
    expect(avatar.attributes('style')).toContain(
      `--character-color: var(--character-${characterIndex('research_market')})`,
    )
  })

  it('shows the role and the task it was working', () => {
    const wrapper = rail([entry()])
    expect(wrapper.text()).toContain('Market Analyst')
    expect(wrapper.text()).toContain('market_task')
  })

  it('folds an older entry to one line and opens it on demand', async () => {
    // Keyed on RECENCY, not length. The reference collapses anything long,
    // which hides exactly the entry somebody is reading when a model is verbose.
    const wrapper = rail([
      entry({ callId: 'old', collapsed: true, text: 'x'.repeat(300), revealed: 300 }),
      entry({ callId: 'new' }),
    ])
    expect(wrapper.findAll('[data-testid="dialogue-fold"]')).toHaveLength(1)
    await wrapper.get('[data-testid="dialogue-fold"]').trigger('click')
    expect(wrapper.findAll('[data-testid="dialogue-fold"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid="dialogue-text"]')).toHaveLength(2)
  })

  it('names where a trimmed answer went', () => {
    // "It ends mid-sentence for a reason" versus "it just ends".
    const wrapper = rail([entry({ truncated: true })])
    expect(wrapper.get('[data-testid="dialogue-trimmed"]').text()).toContain('run log')
  })

  it('says nothing about trimming on a whole answer', () => {
    expect(rail([entry()]).find('[data-testid="dialogue-trimmed"]').exists()).toBe(false)
  })

  it('shows the token counts, which are the entry\'s own cost', () => {
    expect(rail([entry()]).text()).toContain('640 in')
    expect(rail([entry()]).text()).toContain('120 out')
  })

  it('hides the list when collapsed but keeps the count', () => {
    const wrapper = rail([entry()], true)
    expect(wrapper.get('[data-testid="dialogue-list"]').isVisible()).toBe(false)
    expect(wrapper.get('.dialogue-count').text()).toBe('1')
  })

  it('announces text changes, not only additions', () => {
    // A progressive reveal is a TEXT change to an element already in the tree.
    // Without `text` in `aria-relevant` a screen reader announces the empty
    // bubble and then goes silent for the whole sentence.
    const list = rail([entry()]).get('[data-testid="dialogue-list"]')
    expect(list.attributes('aria-relevant')).toBe('additions text')
    expect(list.attributes('role')).toBe('log')
  })

  it('makes initials out of a one-word role', () => {
    expect(rail([entry({ role: 'Scoper' })]).get('[data-testid="dialogue-avatar"]').text())
      .toBe('SC')
  })
})
