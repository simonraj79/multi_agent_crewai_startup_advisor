import { mount } from '@vue/test-utils'
import type { App } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ChatRail from '../src/components/ChatRail.vue'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import { NODE_DATA_KEYS, sameNodeData, useValidatorRun } from '../src/composables/useValidatorRun'
import type { StudioNodeData } from '../src/composables/useValidatorRun'
import type { ChatEntry } from '../src/types/studio'
import { FakeStudioApi, flush, frameFactory, withSetup, zeroUsage } from './helpers'

/**
 * The trace row after the polish pass, and the duplicate DOM id that a
 * verification run found (S4).
 *
 * Three separate claims, and each of them is a thing somebody looked at and
 * decided rather than a thing that fell out of the code:
 *
 *  - a gate is a PERSON, so its row gets a marker and not a cast member;
 *  - a run-level row is about the run, so it says "Run" and never the
 *    registry's internal `workflow` node id;
 *  - a card publishes its node id as data, because publishing it as `id`
 *    collided with the launch textarea on a graph whose input node is called
 *    `idea` - two elements, one id, and `querySelector('#idea')` picking
 *    whichever came first.
 */

function chatEntry(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return {
    id: 'row-1',
    seq: 1,
    nodeId: 'confirm_scope',
    actor: 'Confirm scope',
    message: 'Waiting for you to confirm the scope.',
    timestamp: '10:00:01',
    variant: 'system',
    calls: [],
    identity: 'Confirm scope',
    tone: 'you',
    raw: {
      kind: 'gate_open',
      eventType: 'HUMAN_INTERACTION',
      seq: 1,
      message: 'Confirm the scope',
      details: '{}',
    },
    ...overrides,
  } as unknown as ChatEntry
}

const rail = (entries: ChatEntry[]) =>
  mount(ChatRail, { props: { entries, collapsed: false } })

describe('a row about the operator', () => {
  it('shows a marker rather than a character when the tone is `you`', () => {
    // The same decision the graph already makes about a gate node: a human is
    // not a cast member, and a face on a human's turn would be the one place
    // this console claimed an agent did work a person did.
    const wrapper = rail([chatEntry()])
    expect(wrapper.find('[data-testid="trace-you"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="trace-avatar"]').exists()).toBe(false)
    expect(wrapper.find('.trace-avatar .pip').exists()).toBe(false)
  })

  it('shows it for a gate frame the interpreter toned as a warning', () => {
    // `gate_expired` is advisory - the run stays waiting and a late reply is
    // still accepted - so the interpreter gives it a warning tone rather than
    // `you`. It is still a row about a person, which is why the kind is read
    // as well as the tone.
    const wrapper = rail([
      chatEntry({
        tone: 'warn',
        variant: 'warning',
        raw: {
          kind: 'gate_expired',
          eventType: 'HUMAN_INTERACTION',
          seq: 2,
          message: 'The gate passed its deadline',
          details: '{}',
        },
      } as Partial<ChatEntry>),
    ])
    expect(wrapper.find('[data-testid="trace-you"]').exists()).toBe(true)
  })

  it('leaves an agent row with its character', () => {
    const wrapper = rail([
      chatEntry({
        nodeId: 'research_market',
        actor: 'Market evidence analyst',
        identity: 'Market evidence analyst',
        tone: 'info',
        variant: 'agent',
        raw: {
          kind: 'tool',
          eventType: 'TOOL_CALL',
          seq: 3,
          message: 'search completed',
          details: '{}',
        },
      } as Partial<ChatEntry>),
    ])
    expect(wrapper.find('[data-testid="trace-you"]').exists()).toBe(false)
    expect(wrapper.get('.trace-avatar .pip').attributes('data-character'))
      .toBe('market evidence analyst')
  })
})

describe('the compact row', () => {
  it('carries the line and the time in the classes the shell owns', () => {
    const wrapper = rail([chatEntry()])
    expect(wrapper.get('.trace-line').text()).toBe('Waiting for you to confirm the scope.')
    // `.panel-meta` is W5's global for a timestamp beside a name; adopting it
    // is what keeps the two rails one surface rather than two that agree today.
    expect(wrapper.get('.trace-meta time').classes()).toContain('panel-meta')
    expect(wrapper.get('.trace-meta strong').text()).toBe('Confirm scope')
  })

  it('keeps the disclosure closed and its payload in the DOM', () => {
    // Unchanged by the polish, and asserted here because the polish moved every
    // other rule on the row: nothing was dropped, the raw is one click away.
    const details = rail([chatEntry()]).get('.trace-raw').element as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.querySelector('summary')?.textContent).toBe('Details')
  })
})

describe('a row about the whole run', () => {
  let api: FakeStudioApi
  let run: ReturnType<typeof useValidatorRun>
  let app: App
  let build: ReturnType<typeof frameFactory>

  beforeEach(async () => {
    localStorage.clear()
    api = new FakeStudioApi()
    build = frameFactory()
    ;[run, app] = withSetup(() => useValidatorRun(api))
    await run.initialize()
    await run.launch()
  })

  afterEach(() => app.unmount())

  it('is attributed to "Run", not to the registry\'s workflow node', async () => {
    // The serializer stamps run-level frames with the registry's own workflow
    // node id. `interpret.ts::runLine` drops it, because no canvas draws that
    // node - but the actor was still read off the FRAME, found `workflow`,
    // failed to match a descriptor node and fell through to the id itself. The
    // one row about the whole run was labelled with an internal name.
    api.emit(
      build('run_state', {
        event_type: 'WORKFLOW_START',
        node_id: 'workflow',
        message: 'Synthetic validator started',
        details: { status: 'running', inputs: { idea: 'A rota assistant' } },
      }),
    )
    await flush()
    const rows = run.chatEntries.value.filter((row) => row.raw.kind === 'run_state')
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      expect(row.actor).toBe('Run')
      expect(row.actor).not.toBe('workflow')
      expect(row.nodeId).toBeUndefined()
    }
  })
})

describe('the card does not take the node id as a DOM id', () => {
  function nodeData(overrides: Partial<StudioNodeData> = {}): StudioNodeData {
    return {
      label: 'Idea',
      eyebrow: '01 - INPUT',
      description: 'The idea to validate.',
      kind: 'agent',
      state: 'idle',
      usage: zeroUsage(),
      frameCount: 0,
      visits: 0,
      activeCall: null,
      character: 1,
      receded: false,
      errorMessage: '',
      replayed: false,
      receiving: false,
      index: 0,
      landing: false,
      nodeId: 'idea',
      rerunnable: false,
      ...overrides,
    }
  }

  it('publishes it as `data-node-id` and takes no fallthrough attributes', () => {
    // S4, exactly as the verification run met it: Vue Flow passes the node's id
    // through `v-bind="nodeProps"`, and on a graph whose input node is called
    // `idea` that made a SECOND element carrying the launch textarea's id.
    // `document.querySelector('#idea')` then resolved to whichever came first.
    const wrapper = mount(WorkflowNode, {
      props: { data: nodeData() },
      attrs: { id: 'idea', 'data-junk': 'x' },
      global: { stubs: { Handle: true } },
    })
    const card = wrapper.get('.workflow-node')
    expect(card.attributes('id')).toBeUndefined()
    expect(card.attributes('data-junk')).toBeUndefined()
    expect(card.attributes('data-node-id')).toBe('idea')
  })
})

describe('the card payload comparison is exhaustive (T2.8)', () => {
  /**
   * `graphNodes` hands a card the SAME `data` object back while its fields are
   * unchanged, so Vue can skip it - which took the card re-renders of a
   * 262-frame replay from 2,912 to 340. The whole thing rests on `sameNodeData`
   * seeing every field: one it does not compare is a card that never repaints
   * for that kind of change, and nothing else in the suite would notice.
   */
  function fullCard(): StudioNodeData {
    return {
      label: 'Market Analyst',
      eyebrow: '03 - RESEARCH',
      description: 'Searches the live market.',
      kind: 'agent',
      state: 'running',
      model: 'google/gemini-3.5-flash-lite',
      tool: 'research_market_landscape',
      usage: { ...zeroUsage(), callCount: 2, totalTokens: 900, costUsd: 0.004 },
      frameCount: 12,
      visits: 2,
      activeCall: { label: 'search', kind: 'tool', query: 'q', startedAt: 17 },
      character: 4,
      receded: false,
      errorMessage: '',
      replayed: false,
      receiving: true,
      index: 3,
      landing: true,
      nodeId: 'research_market',
      rerunnable: false,
    }
  }

  it('names every key of the payload', () => {
    expect([...NODE_DATA_KEYS].sort()).toEqual(Object.keys(fullCard()).sort())
  })

  it('sees a change in every one of them', () => {
    const base = fullCard()
    expect(sameNodeData(base, fullCard())).toBe(true)
    for (const key of NODE_DATA_KEYS) {
      const changed = fullCard() as Record<string, unknown>
      if (key === 'usage') changed[key] = { ...base.usage, costUsd: base.usage.costUsd + 1 }
      else if (key === 'activeCall') changed[key] = { ...base.activeCall!, startedAt: 99 }
      else if (typeof changed[key] === 'string') changed[key] = `${changed[key] as string}!`
      else if (typeof changed[key] === 'number') changed[key] = (changed[key] as number) + 1
      else changed[key] = !changed[key]
      expect(
        sameNodeData(base, changed as unknown as StudioNodeData),
        `a change to \`${String(key)}\` was not seen, so that card would never repaint`,
      ).toBe(false)
    }
  })

  it('sees the two object fields by CONTENT, not by identity', () => {
    // `usage` is mutated in place by `addUsage`, so identity says "unchanged"
    // about a card that just billed. `activeCall` is replaced on every call, so
    // identity says "changed" about a card doing exactly what it was.
    const base = fullCard()
    const billed = { ...base, usage: { ...base.usage, totalTokens: 1000 } }
    expect(sameNodeData(base, billed)).toBe(false)
    const sameCallNewObject = { ...base, activeCall: { ...base.activeCall! } }
    expect(sameNodeData(base, sameCallNewObject)).toBe(true)
  })
})
