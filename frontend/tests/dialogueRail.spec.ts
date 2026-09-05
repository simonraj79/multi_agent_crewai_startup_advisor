import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DialogueRail from '../src/components/DialogueRail.vue'
import { characterSeed, type PipState } from '../src/characters/pip'
import {
  characterIndex,
  type DialogueEntry,
} from '../src/composables/useRunChoreography'
import { MAX_UTTERANCE_CHARS } from '../src/data/serverLimits'
import { readSpeech } from '../src/trace/speech'

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

function rail(
  entries: DialogueEntry[],
  collapsed = false,
  cast?: { identityOf?: (nodeId: string) => string; stateOf?: (nodeId: string) => PipState },
) {
  return mount(DialogueRail, {
    props: { entries, collapsed, characterOf: characterIndex, ...cast },
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
    //
    // The index is still published on the WRAPPER even though the disc no
    // longer paints itself with it: it is the colour of the lucide medallion on
    // the node kinds that keep an icon instead of a character, and one property
    // with two readers is better than two properties that agree today. The
    // character's own colour is the same hash of the same seed - `pip.ts` uses
    // the raw FNV modulo twelve that `characterIndex` is, and says so.
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

  it('names where a trimmed answer went, at the number the server actually uses', () => {
    // "It ends mid-sentence for a reason" versus "it just ends". The figure was
    // written into the sentence as the literal 4,096 and would have gone on
    // saying 4,096 after the server moved.
    const wrapper = rail([entry({ truncated: true })])
    const note = wrapper.get('[data-testid="dialogue-trimmed"]').text()
    expect(note).toContain('run log')
    expect(note).toContain(MAX_UTTERANCE_CHARS.toLocaleString())
  })

  it('mirrors the server bound it quotes', () => {
    // Drift here is the whole hazard of a duplicated constant, so it is a test
    // rather than a comment. `MAX_UTTERANCE_CHARS` in src/brief_crew/config.py.
    expect(MAX_UTTERANCE_CHARS).toBe(4096)
  })

  it('says nothing about trimming on a whole answer', () => {
    expect(rail([entry()]).find('[data-testid="dialogue-trimmed"]').exists()).toBe(false)
  })

  it('puts the token counts behind the disclosure, not in front of the answer', () => {
    // AMENDED: they used to be a visible line under every entry. `640 in ·
    // 120 out` on every row is the same failure as the trace's raw payloads -
    // true, unreadable, and in front of the thing somebody came to read.
    const wrapper = rail([entry()])
    const tokens = wrapper.get('[data-testid="dialogue-tokens"]')
    expect(tokens.text()).toContain('640 in')
    expect(tokens.text()).toContain('120 out')
    // Inside a `<details>`, which is closed until somebody opens it.
    const details = tokens.element.closest('details')
    expect(details).not.toBeNull()
    expect((details as HTMLDetailsElement).open).toBe(false)
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

  it('holds a CHARACTER, not two initials', () => {
    // `MA` and `MO` are two letters apart at 32px and told a reader nothing the
    // name printed beside them did not. What the slot holds now is the same
    // figure standing on that node's card, which is a thing an eye can follow
    // across three surfaces.
    const avatar = rail([entry({ role: 'Scoper' })]).get('[data-testid="dialogue-avatar"]')
    expect(avatar.text()).toBe('')
    expect(avatar.findAll('.pip')).toHaveLength(1)
    expect(avatar.get('.pip').attributes('data-character')).toBe(characterSeed('Scoper'))
  })

  it('draws the seed and the pose the RUN resolved, not the entry\'s own role', () => {
    // The distinction T2.6 turns on. An entry's `role` is whatever the speakers
    // map held when its utterance landed, so an entry produced before the
    // node's first `agent_role` carries the label - two seeds for one agent.
    // The store answers with the first role it ever saw and never changes it.
    const avatar = rail([entry({ role: 'The research_market card' })], false, {
      identityOf: () => 'Market Evidence Analyst',
      stateOf: () => 'speaking',
    }).get('[data-testid="dialogue-avatar"]')
    expect(avatar.get('.pip').attributes('data-character')).toBe('market evidence analyst')
    expect(avatar.get('.pip').attributes('data-state')).toBe('speaking')
  })

  it('falls back to the entry\'s role when no store is wired up', () => {
    // A spec, a mock transport, a rail mounted on its own. It draws AN ordinary
    // character rather than a placeholder: a system whose strangers look broken
    // punishes the author of every flow it has never seen.
    const avatar = rail([entry({ role: 'Market Analyst' })]).get('[data-testid="dialogue-avatar"]')
    expect(avatar.get('.pip').attributes('data-character')).toBe('market analyst')
    expect(avatar.get('.pip').attributes('data-state')).toBe('idle')
  })

  it('names the identity on the entry and the seed on the avatar', () => {
    // T2.6: the tie-in between the node's character and the trace's is a string
    // comparison, so both surfaces have to publish the same seed.
    const wrapper = rail([entry({ role: 'Market Analyst' })])
    expect(wrapper.get('.dialogue-entry').attributes('data-identity')).toBe('Market Analyst')
    expect(wrapper.get('[data-testid="dialogue-avatar"]').attributes('data-character-seed'))
      .toBe('Market Analyst')
  })
})

/**
 * The three shapes an `utterance` frame can carry.
 *
 * `events/serializer.py` writes the completed response into `details.text` and
 * `json.dumps`es anything that is not already a string, so the rail receives
 * prose, JSON-encoded prose, and structured results that are not speech at all.
 * Before this it rendered all three as `pre-wrap` raw text, which is how a
 * guardrail's `{"valid":true,"feedback":null}` ended up on screen as something
 * an agent said, and how a wrapped response's newlines ended up as a literal
 * backslash-n.
 */
describe('what an utterance actually is', () => {
  const prose = 'Three of the five claims resolve to the filing.'

  it('renders prose as prose, with its Markdown resolved', () => {
    const text = '## What I checked\n\nThree claims **resolve**.'
    const wrapper = rail([entry({ text, revealed: text.length })])
    const html = wrapper.get('[data-testid="dialogue-text"]').html()
    expect(html).toContain('<h2>What I checked</h2>')
    expect(html).toContain('<strong>resolve</strong>')
    // The wire format is gone from the screen, not merely styled.
    expect(wrapper.get('[data-testid="dialogue-text"]').text()).not.toContain('**')
  })

  it('unwraps a response that went through json.dumps on its way here', () => {
    // The literal backslash-n case, which is what `pre-wrap` was rendering.
    const encoded = JSON.stringify('Two claims failed.\nBoth cite the same page.')
    const wrapper = rail([entry({ text: encoded, revealed: encoded.length })])
    const shown = wrapper.get('[data-testid="dialogue-text"]').text()
    expect(shown).toContain('Two claims failed.')
    expect(shown).toContain('Both cite the same page.')
    expect(shown).not.toContain('\\n')
    expect(shown).not.toContain('{"')
  })

  it('refuses to render a structured result as speech', () => {
    const payload = '{"feedback": null, "valid": true}'
    const wrapper = rail([entry({ role: 'Fact Checker', text: payload, revealed: payload.length })])
    expect(wrapper.get('[data-testid="dialogue-structured"]').text())
      .toBe('Fact Checker returned a structured result')
    expect(wrapper.find('[data-testid="dialogue-text"]').exists()).toBe(false)
    // Not dropped - behind the disclosure, closed.
    const raw = wrapper.get('[data-testid="dialogue-payload"]')
    expect(raw.text()).toContain('"valid": true')
    expect((raw.element.closest('details') as HTMLDetailsElement).open).toBe(false)
  })

  it('lifts a long string out of a one-key wrapper, which is prose in a coat', () => {
    const wrapped = JSON.stringify({ report: prose.repeat(3) })
    expect(readSpeech(wrapped).kind).toBe('prose')
    expect(readSpeech(wrapped).text).toContain('Three of the five claims')
  })

  it('leaves a sentence that merely begins with a brace alone', () => {
    // A model that wrote a sentence is far commoner than one that wrote JSON
    // and got the syntax wrong, so anything that fails to parse is prose.
    expect(readSpeech('{not json at all').kind).toBe('prose')
    expect(readSpeech('{not json at all').text).toBe('{not json at all')
  })

  it('keeps the newest thing anybody SAID open behind a run of structured results', () => {
    // `collapsed` is decided upstream over every entry, so three machine
    // answers in a row are enough to fold the last real utterance.
    const wrapper = rail([
      entry({ callId: 'said', text: prose, revealed: prose.length, collapsed: true }),
      entry({ callId: 'j1', text: '{"valid": true}', collapsed: true }),
      entry({ callId: 'j2', text: '{"valid": true}', collapsed: false }),
      entry({ callId: 'j3', text: '{"valid": true}', collapsed: false }),
    ])
    expect(wrapper.findAll('[data-testid="dialogue-fold"]')).toHaveLength(0)
    expect(wrapper.get('[data-testid="dialogue-text"]').text()).toContain('Three of the five claims')
    expect(wrapper.findAll('[data-testid="dialogue-structured"]')).toHaveLength(3)
  })

  it('escapes model output rather than sanitising it afterwards', () => {
    const hostile = 'read this <img src=x onerror="alert(1)"> and this'
    const wrapper = rail([entry({ text: hostile, revealed: hostile.length })])
    const html = wrapper.get('[data-testid="dialogue-text"]').html()
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })
})
