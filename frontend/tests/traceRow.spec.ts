import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import type { App } from 'vue'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ChatRail from '../src/components/ChatRail.vue'
import WorkflowNode from '../src/components/WorkflowNode.vue'
import { NODE_DATA_KEYS, sameNodeData, useValidatorRun } from '../src/composables/useValidatorRun'
import type { StudioNodeData } from '../src/composables/useValidatorRun'
import type { ChatEntry, FrameData, StudioFrame } from '../src/types/studio'
import { FakeStudioApi, RUN_ID, flush, frameFactory, withSetup, zeroUsage } from './helpers'

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

describe('the seam between the dialogue block and the trace list', () => {
  /*
   * WHAT WAS ACTUALLY WRONG, because two guesses came before it.
   *
   * A cold reader saw the "Review verdict / You approved" row cut across its
   * name and apparently sliding UNDER the pinned "WHAT THE CREW SAID" block,
   * with no avatar. Nothing slides under anything: the slot holding the
   * dialogue and the trace list are static siblings in a column flex, neither
   * is positioned, and the assertions below pin that. Two duller things were
   * happening at once.
   *
   * 1. THE LIST IS SCROLLED TO THE BOTTOM, so its topmost visible row is cut by
   *    the scroller's own top edge - which is what a scrolled list does. It
   *    read as an overlap because the cut landed flush against the block above
   *    with no drawn edge between them. Two rounds of padding did not help and
   *    could not: a padding INSIDE a scroll box scrolls away with the content
   *    and is not there at the moment of the clip. `.rail-list` now carries a
   *    `border-top`, which is on the scroller's own box and does not scroll, and
   *    `.rail-slot` a margin, which is outside both boxes.
   * 2. THE ROW HAD LOST ITS AVATAR COLUMN. `.trace-entry.is-system` set
   *    `display: block`, and `is-system` arrives for a `you` row from its
   *    VARIANT as well as from having no identity - so the gate marker added in
   *    round three had a column to sit in only on paper. That is the
   *    `has-mark` case below, and it is the half a reader actually notices.
   *
   * WHY THE CSS IS ASSERTED FROM SOURCE AND NOT FROM `getComputedStyle`.
   * This suite runs Vitest with `css` off: a mounted component puts ZERO
   * `<style>` tags in the document, measured rather than assumed, so
   * `getComputedStyle(slot).position` answers `static` and
   * `getComputedStyle(list).overflowY` answers `visible` whatever the stylesheet
   * says. Asserting those would be a test that passes for the wrong reason - the
   * exact failure this repository keeps a section about. So the STRUCTURE is
   * asserted against the DOM, where it is real, and the two CSS facts that make
   * an overlap impossible are asserted against the stylesheet text, labelled as
   * what they are. The pixels are `e2e/cast.spec.ts`'s.
   */

  function styleBlock(component: string): string {
    const source = readFileSync(resolve(process.cwd(), 'src', 'components', component), 'utf8')
    const at = source.indexOf('<style')
    expect(at, `${component} has no style block`).toBeGreaterThan(-1)
    return source.slice(at)
  }

  it('keeps the dialogue in its own slot, a sibling above the scrolling list', () => {
    const wrapper = mount(ChatRail, {
      props: { entries: [chatEntry()], collapsed: false },
      slots: { above: '<div class="dialogue-rail">spoken</div>' },
    })
    const slot = wrapper.get('.rail-slot')
    const list = wrapper.get('.rail-list')
    expect(slot.find('.dialogue-rail').exists()).toBe(true)
    // The one containment fact that makes an overlap impossible: the scroller
    // does not hold the block, so the block cannot scroll with the rows or be
    // pinned over them.
    expect(list.element.contains(slot.element)).toBe(false)
    expect(slot.element.contains(list.element)).toBe(false)
    expect(slot.element.parentElement).toBe(list.element.parentElement)
    const children = Array.from(wrapper.element.children)
    expect(children.indexOf(slot.element)).toBeLessThan(children.indexOf(list.element))
    wrapper.unmount()
  })

  it('positions neither region, and gives the scroller the edge that does not scroll', () => {
    const chat = styleBlock('ChatRail.vue')
    const dialogue = styleBlock('DialogueRail.vue')
    // No rule anywhere in either sheet takes either region out of flow.
    for (const [name, sheet] of [['ChatRail.vue', chat], ['DialogueRail.vue', dialogue]] as const) {
      for (const rule of ['.rail-slot', '.rail-list', '.dialogue-rail', '.dialogue-list']) {
        const at = sheet.indexOf(`${rule} {`)
        if (at < 0) continue
        const body = sheet.slice(at, sheet.indexOf('}', at))
        expect(body, `${name} ${rule} is positioned`).not.toMatch(/position:\s*(sticky|absolute|fixed)/)
      }
    }
    // The list is its own scroller, and its top edge is drawn.
    const listRule = chat.slice(chat.indexOf('.rail-list {'))
    const listBody = listRule.slice(0, listRule.indexOf('}'))
    expect(listBody).toMatch(/overflow-y:\s*auto/)
    expect(listBody).toMatch(/border-top:\s*1px solid var\(--border-default\)/)
    // And the gutter between them is outside both scroll boxes.
    const slotRule = chat.slice(chat.indexOf('.rail-slot {'))
    expect(slotRule.slice(0, slotRule.indexOf('}'))).toMatch(/margin-bottom:\s*var\(--space-/)
  })

  it('leaves a gate row its avatar column, and a run row without one', () => {
    // The half the reader actually noticed. A `you` row is `is-system` by
    // variant, and that used to drop the two-column grid - so the marker added
    // in round three had nowhere to sit and the row started hard against the
    // left edge unlike every row above it.
    const gate = mount(ChatRail, { props: { entries: [chatEntry()], collapsed: false } })
    const gateRow = gate.get('.trace-entry')
    expect(gateRow.classes()).toContain('is-system')
    expect(gateRow.classes()).toContain('has-mark')
    expect(gate.find('[data-testid="trace-you"]').exists()).toBe(true)
    gate.unmount()

    // A row about the run itself has nothing to put in the column and keeps the
    // full width it always had.
    const runRow = mount(ChatRail, {
      props: {
        entries: [
          chatEntry({
            identity: '',
            actor: 'Run',
            tone: 'info',
            variant: 'system',
            nodeId: undefined,
            // A run-level frame, not a gate: `isYou` reads the kind as well as
            // the tone, so a `gate_*` row is about a person even when the
            // interpreter attributed it to no node.
            raw: {
              kind: 'run_state',
              eventType: 'WORKFLOW_END',
              seq: 9,
              message: 'ValidatorFlow completed',
              details: '{}',
            },
          } as Partial<ChatEntry>),
        ],
        collapsed: false,
      },
    })
    const row = runRow.get('.trace-entry')
    expect(row.classes()).toContain('is-system')
    expect(row.classes()).not.toContain('has-mark')
    expect(runRow.find('[data-testid="trace-you"]').exists()).toBe(false)
    expect(runRow.find('[data-testid="trace-avatar"]').exists()).toBe(false)
    runRow.unmount()
  })
})

describe('an identical failure, twice in a row, is one row', () => {
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

  const failure = (nodeId: string, error: string) =>
    build('node_state', {
      event_type: 'NODE_END',
      level: 'ERROR',
      node_id: nodeId,
      message: `${nodeId} failed`,
      details: { stage: 'error', error },
    })

  it('folds the duplicate and counts it in the disclosure', async () => {
    // `evidence/S/failure.png`: the same sentence four times, twice from the
    // agent and twice from "System", each cut at the same word. A reader counts
    // four failures.
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()

    const errors = run.chatEntries.value.filter((row) => row.tone === 'error')
    expect(errors).toHaveLength(1)
    expect(errors[0].repeats).toBe(2)

    const wrapper = mount(ChatRail, { props: { entries: run.chatEntries.value, collapsed: false } })
    // In the DISCLOSURE and never in the sentence: the sentence is what
    // happened, the count is a fact about the log.
    expect(wrapper.get('.trace-line').text()).not.toContain('2')
    expect(wrapper.get('[data-testid="trace-repeats"]').text()).toContain('2')
    wrapper.unmount()
  })

  it('says nothing about repeats when a failure happened once', async () => {
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()
    const wrapper = mount(ChatRail, { props: { entries: run.chatEntries.value, collapsed: false } })
    expect(wrapper.find('[data-testid="trace-repeats"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps two DIFFERENT failures, and two nodes failing alike, apart', async () => {
    // Same node, different sentence: two things went wrong. Different nodes,
    // same sentence: two branches hit the same wall, which is the fact.
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()
    api.emit(failure('step-1', 'the signing key is missing'))
    await flush()
    api.emit(failure('step-2', 'the signing key is missing'))
    await flush()
    const errors = run.chatEntries.value.filter((row) => row.tone === 'error')
    expect(errors).toHaveLength(3)
    expect(errors.every((row) => row.repeats === undefined)).toBe(true)
  })

  it('does not fold a repeat that is no longer consecutive', async () => {
    // A failure that recurs after other rows keeps its own place in the
    // sequence, because WHEN it happened again is the interesting part.
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()
    api.emit(
      build('llm', {
        event_type: 'MODEL_CALL',
        node_id: 'step-1',
        details: { stage: 'before', model: 'google/gemini-3.5-flash-lite' },
      }),
    )
    await flush()
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()
    const errors = run.chatEntries.value.filter((row) => row.tone === 'error')
    expect(errors).toHaveLength(2)
  })

  it("keeps the first row's id and clock when it folds", async () => {
    // A row that jumped its own timestamp because the same thing was reported
    // again would move under the reader, and its Vue key would change for no
    // reason at all.
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()
    const first = run.chatEntries.value.filter((row) => row.tone === 'error')[0]
    const { id, seq, timestamp } = first
    api.emit(failure('step-1', 'the provider refused the request'))
    await flush()
    const folded = run.chatEntries.value.filter((row) => row.tone === 'error')[0]
    expect(folded.id).toBe(id)
    expect(folded.seq).toBe(seq)
    expect(folded.timestamp).toBe(timestamp)
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

/* ------------------------------------------------------------------ *
 *  T2.1 - every row carries its sentence in `.trace-line`             *
 * ------------------------------------------------------------------ */

function fixtureFrames(name: string): FrameData[] {
  const path = resolve(process.cwd(), 'tests', 'fixtures', name)
  if (!existsSync(path)) return []
  return readFileSync(path, 'utf8')
    .split(/\r?\n/)
    .map((row) => row.trim())
    .filter(Boolean)
    .map((row) => {
      const parsed = JSON.parse(row) as StudioFrame | FrameData
      return 'data' in parsed && parsed.type === 'frame' ? parsed.data : (parsed as FrameData)
    })
    .map((frame, index) => ({ ...frame, run_id: RUN_ID, seq: index + 1 }))
}

const FIXTURES = ['syntheticRunGated.ndjson', 'syntheticRun.ndjson', 'serializerFrames.ndjson'] as const

describe('every trace row carries a sentence', () => {
  /*
   * A verification run read 24 of the rows of a 119-event run as an EMPTY line
   * and recorded it against T2.1. This is that assertion in the one place it
   * can be made deterministically: the real interpreter over a committed frame
   * log, the real rail mounted over the result, every row inspected.
   *
   * It is deliberately not a screenshot's question. What the browser measures
   * is `innerText`, which is the RENDERED text - and a row scrolled out of view
   * under `content-visibility: auto` renders nothing at all. This asserts what
   * the DOM says, which is the half this component is responsible for.
   */
  for (const name of FIXTURES) {
    it(`renders one non-empty line per row over ${name}`, async () => {
      const api = new FakeStudioApi()
      const [run, app] = withSetup(() => useValidatorRun(api)) as [
        ReturnType<typeof useValidatorRun>,
        App,
      ]
      await run.initialize()
      await run.launch()
      const frames = fixtureFrames(name)
      expect(frames.length, `${name} is missing or empty`).toBeGreaterThan(0)
      for (const frame of frames) {
        api.emit(frame)
        await flush()
      }

      const entries = run.chatEntries.value
      expect(entries.length, `${name} produced no rows`).toBeGreaterThan(0)
      const wrapper = mount(ChatRail, { props: { entries, collapsed: false } })

      const rows = wrapper.findAll('.trace-entry')
      const lines = wrapper.findAll('.trace-line')
      expect(lines.length, 'a row rendered no `.trace-line` at all').toBe(rows.length)

      const blank = lines
        .map((line, index) => ({ index, text: line.text().trim() }))
        .filter((row) => row.text.length === 0)
      expect(
        blank.map((row) => `row ${row.index}: empty line`),
        'a row reached the rail with nothing to say (T2.1)',
      ).toEqual([])

      wrapper.unmount()
      app.unmount()
    }, 60_000)
  }
})
