import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import {
  MAX_TRACE_LINE_CHARS,
  clip,
  duration,
  firstSentence,
  interpretFrame,
  plain,
  toolVerb,
  traceCallKey,
  type TraceContext,
  type TraceLine,
} from '../src/trace/interpret'
import ChatRail from '../src/components/ChatRail.vue'
import type { ChatEntry, FrameData, FrameKind, StudioFrame } from '../src/types/studio'

/**
 * The trace's vocabulary, asserted over REAL frame logs.
 *
 * T2.1 of `docs/run-shell/DEFINITION-OF-DONE.md` is explicit that this must be
 * proved over a real frame log rather than a hand-made one, and the reason is
 * the whole history of this repository's client/server drift: a double that
 * diverges from its subject certifies nothing (CLAUDE.md closed items 20 and
 * 33). `serializerFrames.ndjson` is produced by the real Python serializer
 * over real CrewAI events; `syntheticRun.ndjson` is what the synthetic backend
 * actually serves. Between them they cover both paths, and they disagree in
 * exactly the way that matters: the paid path stamps `agent_role` on every
 * frame and the synthetic path stamps none, so the identity ladder has to work
 * from the descriptor alone on one of them.
 *
 * The hand-written cases below the fixture block are for the shapes a fixture
 * cannot contain on demand - an unknown frame kind, a gate that expires, a
 * tool nobody here has heard of.
 */

/* ------------------------------------------------------------------ *
 *  The fixtures                                                       *
 * ------------------------------------------------------------------ */

const FIXTURE_NAMES = ['serializerFrames.ndjson', 'syntheticRun.ndjson'] as const

/**
 * `process.cwd()` and NOT `import.meta.url`.
 *
 * The suite runs under jsdom, whose `URL` is whatwg-url rather than Node's, so
 * `fileURLToPath(new URL('./fixtures/x', import.meta.url))` throws "The URL
 * must be of scheme file" on a URL object that plainly is one. Vitest's cwd is
 * this package, which is the one thing about the environment that is stable.
 */
function fixturePath(name: string): string {
  return resolve(process.cwd(), 'tests', 'fixtures', name)
}

/** NDJSON of either `StudioFrame` envelopes or bare frames; both are served. */
function loadFrames(name: string): FrameData[] {
  const path = fixturePath(name)
  if (!existsSync(path)) return []
  return readFileSync(path, 'utf8')
    .split('\n')
    .map((row) => row.trim())
    .filter(Boolean)
    .map((row) => {
      const parsed = JSON.parse(row) as StudioFrame | FrameData
      return 'data' in parsed && parsed.type === 'frame' ? parsed.data : (parsed as FrameData)
    })
}

const FIXTURES = FIXTURE_NAMES.filter((name) => existsSync(fixturePath(name)))

/**
 * A descriptor lookup for whatever nodes a fixture names.
 *
 * The label is deliberately NOT the agent's role: T2.2 says the subject of a
 * line comes from `agent_role` when the frame carries one, and a lookup whose
 * label happened to match would make that assertion vacuous.
 */
function contextFor(frames: FrameData[]): TraceContext {
  const ids = [...new Set(frames.map((frame) => frame.node_id).filter(Boolean) as string[])]
  const facts = new Map(
    // The label carries no node id on purpose: it is prose an author typed,
    // and a stand-in built out of the identifier would make the "no raw
    // identifier in a line" assertion fail on the FIXTURE rather than on the
    // product.
    ids.map((id, index) => [
      id,
      { label: `Card ${index + 1}`, kind: 'agent' as const, agentRole: undefined, taskName: undefined },
    ]),
  )
  return { node: (id) => facts.get(id) }
}

/** Every line a fixture produces, in order, with the frame that made it. */
function interpretAll(frames: FrameData[]): Array<{ frame: FrameData; line: TraceLine }> {
  const ctx = contextFor(frames)
  const out: Array<{ frame: FrameData; line: TraceLine }> = []
  for (const frame of frames) {
    const line = interpretFrame(frame, ctx)
    if (line) out.push({ frame, line })
  }
  return out
}

/* ------------------------------------------------------------------ *
 *  The bans                                                           *
 * ------------------------------------------------------------------ */

/** A literal backslash-n, which is what a `json.dumps`ed response renders as. */
const LITERAL_ESCAPE = /\\[nrt]/
/** The opening of a serialised object, wherever it appears in the line. */
const JSON_OPENING = '{"'
/** `5168 in · 3994 out`, the token counts that were on every row. */
const TOKEN_COUNTS = /\d[\d,]*\s*(in|out)\b\s*[·|]/
/** SNAKE_CASE and snake_case identifiers, which are codes and not words. */
const SNAKE_TOKEN = /\b[A-Za-z0-9]+(_[A-Za-z0-9]+)+\b/

describe('the interpretation layer, over the real frame logs', () => {
  it('has both frame logs to interpret', () => {
    // A missing fixture must be a RED test and never a skipped one: a criterion
    // that quietly does not run is the failure mode this whole file exists to
    // rule out. `syntheticRun.ndjson` is the synthetic backend's own output.
    expect(FIXTURES).toEqual([...FIXTURE_NAMES])
  })

  for (const name of FIXTURES) {
    describe(name, () => {
      const frames = loadFrames(name)
      const produced = interpretAll(frames)

      it('produces at least one line, and fewer lines than frames', () => {
        // Fewer, not equal: the whole point is that some frames have another
        // surface that owns them and some have nothing a person could act on.
        expect(frames.length).toBeGreaterThan(0)
        expect(produced.length).toBeGreaterThan(0)
        expect(produced.length).toBeLessThan(frames.length)
      })

      it('says everything in one short line', () => {
        for (const { frame, line } of produced) {
          expect(line.text.length, `seq ${frame.seq}: ${line.text}`).toBeLessThanOrEqual(
            MAX_TRACE_LINE_CHARS,
          )
          expect(line.text.trim(), `seq ${frame.seq}`).not.toBe('')
        }
      })

      it('never leaks a literal escape, a JSON opening or a token count', () => {
        for (const { frame, line } of produced) {
          expect(line.text, `seq ${frame.seq}`).not.toMatch(LITERAL_ESCAPE)
          expect(line.text, `seq ${frame.seq}`).not.toContain(JSON_OPENING)
          expect(line.text, `seq ${frame.seq}`).not.toContain('\n')
          expect(line.text, `seq ${frame.seq}`).not.toMatch(TOKEN_COUNTS)
        }
      })

      it('never leaves a raw identifier in a line', () => {
        for (const { frame, line } of produced) {
          expect(line.text, `seq ${frame.seq}: ${line.text}`).not.toMatch(SNAKE_TOKEN)
        }
      })

      it('drops every frame kind another surface owns', () => {
        const dropped = frames.filter((frame) => !interpretFrame(frame, contextFor(frames)))
        for (const frame of dropped) {
          const stage = String(frame.details.stage ?? '')
          expect(
            ['token', 'metrics', 'edge_taken'].includes(frame.kind) ||
              ['chunk', 'utterance', 'plan', 'paused'].includes(stage),
            `seq ${frame.seq} (${frame.kind}/${stage}) was dropped for no declared reason`,
          ).toBe(true)
        }
      })

      it('carries the raw payload on every line it does produce', () => {
        // Nothing is hidden; it is one click away. A row whose disclosure was
        // empty would be the dump problem solved by deletion.
        for (const { frame, line } of produced) {
          expect(line.raw.seq).toBe(frame.seq)
          expect(line.raw.message).toBe(frame.message)
          expect(line.raw.details.length).toBeGreaterThan(0)
        }
      })

      it('takes its subject from agent_role wherever a frame carries one', () => {
        const stamped = produced.filter(
          ({ frame }) => typeof frame.details.agent_role === 'string' && frame.details.agent_role,
        )
        for (const { frame, line } of stamped) {
          expect(line.identity, `seq ${frame.seq}`).toBe(frame.details.agent_role)
          expect(line.text, `seq ${frame.seq}`).toContain(String(frame.details.agent_role))
        }
      })
    })
  }
})

/* ------------------------------------------------------------------ *
 *  Coalescing                                                         *
 * ------------------------------------------------------------------ */

function frameOf(kind: FrameKind, overrides: Partial<FrameData> = {}): FrameData {
  return {
    v: 1,
    seq: 1,
    run_id: 'r1',
    ts: '2026-09-05T09:00:00.000Z',
    kind,
    event_type: 'EVENT',
    level: 'INFO',
    message: `${kind} frame`,
    details: {},
    ...overrides,
  }
}

const CTX: TraceContext = {
  node: (id) =>
    id === 'step-1'
      ? { label: 'The first step', kind: 'agent', agentRole: 'Declared Role' }
      : id === 'plumbing'
        ? { label: 'Save it', kind: 'output' }
        : undefined,
}

function say(kind: FrameKind, overrides: Partial<FrameData> = {}): TraceLine | null {
  return interpretFrame(frameOf(kind, overrides), CTX)
}

describe('a call is one row, not two', () => {
  it('gives a tool call the same coalesce key before and after', () => {
    const before = frameOf('tool', {
      node_id: 'step-1',
      details: { stage: 'before', tool: 'claim_lookup', query: 'Q3 filing' },
    })
    const after = frameOf('tool', {
      seq: 2,
      node_id: 'step-1',
      details: { stage: 'after', tool: 'claim_lookup', query: 'Q3 filing', result_count: 3 },
    })
    const first = interpretFrame(before, CTX)
    const second = interpretFrame(after, CTX)

    expect(first?.coalesce?.key).toBe(second?.coalesce?.key)
    expect(first?.coalesce?.key).toBe(traceCallKey(before))
    // The `after` frame outranks its own `before`, always.
    expect(second!.coalesce!.precedence).toBeGreaterThan(first!.coalesce!.precedence)
    expect(first?.text).toBe('Declared Role is searching “Q3 filing” with Claim lookup')
    expect(second?.text).toBe('Declared Role searched “Q3 filing” — 3 results')
  })

  it('lets the most specific view of one moment win the row', () => {
    // A node starting, a crew starting and an agent starting are three frames
    // about one event, and they share a key so only one row survives.
    const node = say('node_state', { node_id: 'step-1', details: { stage: 'before' } })
    const crew = say('agent', { node_id: 'step-1', details: { stage: 'before' } })
    const agent = say('agent', {
      node_id: 'step-1',
      details: { stage: 'before', agent_role: 'Fact Checker', task: 'verify_claims' },
    })

    expect(node?.coalesce?.key).toBe('open:step-1')
    expect(crew?.coalesce?.key).toBe('open:step-1')
    expect(agent?.coalesce?.key).toBe('open:step-1')
    expect(agent!.coalesce!.precedence).toBeGreaterThan(crew!.coalesce!.precedence)
    expect(crew!.coalesce!.precedence).toBeGreaterThan(node!.coalesce!.precedence)
    expect(agent?.text).toBe('Fact Checker started on Verify claims')
  })

  it('merges a burst of reasoning only while it is still the newest row', () => {
    const line = say('reasoning', { node_id: 'step-1', details: { stage: 'thinking' } })
    expect(line?.coalesce?.scope).toBe('tail')
    expect(line?.text).toBe('Declared Role is reasoning')
  })

  it('never coalesces a failure away', () => {
    const failed = say('node_state', {
      node_id: 'step-1',
      level: 'ERROR',
      details: { stage: 'error', error: 'no signing key configured. Set one and retry.' },
    })
    expect(failed?.coalesce).toBeUndefined()
    expect(failed?.tone).toBe('error')
    expect(failed?.text).toBe('Declared Role could not finish: no signing key configured')
  })
})

/* ------------------------------------------------------------------ *
 *  The vocabulary, case by case                                       *
 * ------------------------------------------------------------------ */

describe('the vocabulary', () => {
  it('says nothing for the kinds another surface owns', () => {
    expect(say('token', { node_id: 'step-1' })).toBeNull()
    expect(say('metrics')).toBeNull()
    expect(say('edge_taken', { node_id: 'step-1', details: { from: 'a', to: 'b' } })).toBeNull()
    expect(say('llm', { node_id: 'step-1', details: { stage: 'chunk', chunk: 'ab' } })).toBeNull()
    expect(say('llm', { node_id: 'step-1', details: { stage: 'utterance', text: 'hi' } })).toBeNull()
    expect(say('run_state', { details: { stage: 'plan', index: 1, of: 3 } })).toBeNull()
    expect(say('node_state', { node_id: 'step-1', details: { stage: 'paused' } })).toBeNull()
  })

  it('says nothing for a frame kind from a newer server', () => {
    // The conservative half of the rule: a row nobody can read is worse than
    // no row, and the frame is in the run's log either way.
    expect(say('telemetry_beacon' as FrameKind, { message: 'from a newer server' })).toBeNull()
  })

  it('still speaks up when that unknown kind is an error', () => {
    const line = say('telemetry_beacon' as FrameKind, {
      node_id: 'step-1',
      level: 'ERROR',
      message: 'the beacon could not be reached',
    })
    expect(line?.tone).toBe('error')
    expect(line?.text).toContain('hit an error')
  })

  it('leaves the plumbing off the trace and keeps its failures on it', () => {
    expect(say('node_state', { node_id: 'plumbing', details: { stage: 'before' } })).toBeNull()
    expect(say('node_state', { node_id: 'plumbing', details: { stage: 'after' } })).toBeNull()
    const failed = say('node_state', {
      node_id: 'plumbing',
      details: { stage: 'error', error: 'the disk was full' },
    })
    expect(failed?.text).toBe('Save it could not finish: the disk was full')
  })

  it('narrates a run from its own frames', () => {
    expect(say('run_state', { details: { status: 'running' } })?.text).toBe('Run started')
    expect(say('run_state', { details: { status: 'completed' } })?.text).toBe('Run finished')
    // A run-level statement belongs to no node, so it gets no avatar and is
    // filed under no card.
    expect(say('run_state', { node_id: 'workflow', details: { status: 'running' } })?.nodeId)
      .toBeUndefined()
  })

  it('speaks to the operator at a gate', () => {
    expect(
      say('gate_open', {
        node_id: 'step-1',
        message: 'Confirm the two unsupported claims',
        details: { stage: 'before', gate_id: 'g1' },
      })?.text,
    ).toBe('Waiting for you: Confirm the two unsupported claims')
    expect(say('gate_open', { node_id: 'step-1', details: {} })?.tone).toBe('you')
    expect(
      say('gate_closed', { node_id: 'step-1', details: { outcome: 'scope_ok' } })?.text,
    ).toBe('You approved')
    expect(
      say('gate_closed', { node_id: 'step-1', details: { outcome: 'scope_revise' } })?.text,
    ).toBe('You asked for changes')
    // CrewAI's own gate leaves `outcome` null and puts the reply in `feedback`.
    expect(
      say('gate_closed', {
        node_id: 'step-1',
        details: { outcome: null, feedback: '{"decision": "approve"}' },
      })?.text,
    ).toBe('You approved')
    expect(
      say('gate_expired', { node_id: 'step-1', details: { title: 'Confirm scope' } })?.text,
    ).toBe('The review window for Confirm scope expired')
    expect(
      say('gate_alert', {
        node_id: 'step-1',
        details: { title: 'Confirm scope', overdue_seconds: 95 },
      })?.text,
    ).toBe('Confirm scope is still waiting for you — 1m 35s past the deadline')
  })

  it('reads a guardrail as a check on somebody work, not as speech', () => {
    expect(
      say('guardrail', { node_id: 'step-1', details: { stage: 'before', guardrail: 'cites' } })
        ?.text,
    ).toBe("Declared Role's work is being checked")
    expect(
      say('guardrail', {
        node_id: 'step-1',
        details: { stage: 'after', guardrail: 'cites', success: true },
      })?.text,
    ).toBe("Declared Role's work passed the check")
    const rejected = say('guardrail', {
      node_id: 'step-1',
      level: 'WARNING',
      details: { stage: 'after', guardrail: 'cites', success: false, retry_count: 1 },
    })
    expect(rejected?.text).toBe("Declared Role's work failed the check — trying again (attempt 2)")
    expect(rejected?.tone).toBe('warn')
  })

  it('scores a verdict in words', () => {
    expect(
      say('verdict', {
        node_id: 'step-1',
        details: { verdict: 'NEEDS_WORK', composite_score: 4.24 },
      })?.text,
    ).toBe('Scored 4.2/10 — Needs work')
  })

  it('says how a tool call came back, however it came back', () => {
    const outcome = (details: Record<string, unknown>) =>
      say('tool', { node_id: 'step-1', details: { stage: 'after', tool: 'x_search', ...details } })
        ?.text

    expect(outcome({ query: 'q', result_count: 0 })).toBe('Declared Role searched “q” — nothing found')
    expect(outcome({ query: 'q', result_count: 1 })).toBe('Declared Role searched “q” — 1 result')
    expect(outcome({ query: 'q', result_count: 4, from_cache: true })).toBe(
      'Declared Role searched “q” — 4 results from the cache',
    )
    expect(outcome({ query: 'q', tool_status: 'RATE_LIMITED' })).toBe(
      'Declared Role searched “q” — rate limited',
    )
    expect(outcome({ query: 'q', failure: 'upstream 503' })).toBe(
      'Declared Role searched “q” — it failed',
    )
    expect(
      say('tool', {
        node_id: 'step-1',
        level: 'ERROR',
        details: { stage: 'error', tool: 'x_search', query: 'q', error: 'boom' },
      })?.text,
    ).toBe("Declared Role's X search call failed")
  })

  it('times a model call from the row its own start wrote', () => {
    const withClock: TraceContext = { ...CTX, startedAt: () => Date.parse('2026-09-05T09:00:00.000Z') }
    const line = interpretFrame(
      frameOf('llm', {
        node_id: 'step-1',
        ts: '2026-09-05T09:00:02.800Z',
        details: { stage: 'after', call_id: 'c1', model: 'a/b' },
      }),
      withClock,
    )
    expect(line?.text).toBe('Declared Role thought for 2.8s')
    // Without a clock it still gets a line - just not a duration.
    expect(
      say('llm', { node_id: 'step-1', details: { stage: 'after', call_id: 'c1' } })?.text,
    ).toBe('Declared Role finished thinking')
  })
})

/* ------------------------------------------------------------------ *
 *  The rules the vocabulary rests on                                  *
 * ------------------------------------------------------------------ */

describe('the verb comes from the tool name, never from a role list', () => {
  it('reads the words the framework put in the id', () => {
    expect(toolVerb('firecrawl_search').gerund).toBe('searching')
    expect(toolVerb('SerperDevSearchTool').past).toBe('searched')
    expect(toolVerb('scrape_website').gerund).toBe('reading')
    expect(toolVerb('FirecrawlScrapeWebsiteTool').past).toBe('read')
    expect(toolVerb('save_to_file').gerund).toBe('saving')
    expect(toolVerb('code_interpreter').gerund).toBe('using')
  })

  it('falls through to a neutral verb for a tool nobody here has heard of', () => {
    // The generalisation criterion in one assertion: a flow invented next week
    // narrates its tools without an edit to this module.
    expect(toolVerb('zorb_the_widgets')).toEqual({ gerund: 'using', past: 'used' })
    expect(
      say('tool', {
        node_id: 'step-1',
        details: { stage: 'before', tool: 'zorb_the_widgets', query: 'a widget' },
      })?.text,
    ).toBe('Declared Role is using “a widget” with Zorb the widgets')
  })

  it('makes a sentence of a call that carries no query', () => {
    // "is using with X" is not a sentence: the neutral verb takes the tool as
    // its object where a specific one takes it as an instrument.
    expect(
      say('tool', { node_id: 'step-1', details: { stage: 'before', tool: 'zorb_the_widgets' } })
        ?.text,
    ).toBe('Declared Role is using Zorb the widgets')
    expect(
      say('tool', { node_id: 'step-1', details: { stage: 'before', tool: 'scrape_website' } })
        ?.text,
    ).toBe('Declared Role is reading with Scrape website')
  })
})

/* ------------------------------------------------------------------ *
 *  The rail                                                           *
 * ------------------------------------------------------------------ */

function chatEntry(overrides: Partial<ChatEntry> = {}): ChatEntry {
  return {
    id: 'r1-1',
    seq: 1,
    nodeId: 'step-1',
    actor: 'Declared Role',
    message: 'Declared Role searched “Q3 filing” — 3 results',
    timestamp: '09:00:01',
    variant: 'agent',
    calls: [],
    identity: 'Declared Role',
    tone: 'info',
    raw: {
      message: 'claim_lookup completed',
      details: '{\n  "stage": "after",\n  "tool": "claim_lookup"\n}',
      model: 'a/b',
      tool: 'claim_lookup',
      tokens: { prompt: 5168, completion: 3994 },
      durationMs: 1400,
      seq: 1,
      ts: '2026-09-05T09:00:01.000Z',
      kind: 'tool',
      eventType: 'TOOL_CALL',
    },
    ...overrides,
  }
}

describe('the rail shows the line and hides the payload', () => {
  it('renders one line per row and nothing else in front of it', () => {
    const wrapper = mount(ChatRail, { props: { entries: [chatEntry()], collapsed: false } })
    expect(wrapper.get('[data-testid="trace-line"]').text()).toBe(
      'Declared Role searched “Q3 filing” — 3 results',
    )
    // The bans, in the DOM this time rather than in the interpreter.
    const visible = wrapper.get('.trace-bubble p').text()
    expect(visible).not.toContain('{"')
    expect(visible).not.toMatch(TOKEN_COUNTS)
  })

  it('puts the raw payload, the model and the token counts behind a closed disclosure', () => {
    const wrapper = mount(ChatRail, { props: { entries: [chatEntry()], collapsed: false } })
    const details = wrapper.get('.trace-raw').element as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.querySelector('summary')?.textContent).toBe('Details')
    // Nothing was dropped: the framework's own sentence and the whole payload
    // are both here, one click away.
    expect(wrapper.get('[data-testid="trace-raw"]').text()).toContain('"tool": "claim_lookup"')
    expect(wrapper.get('.trace-raw-message').text()).toBe('claim_lookup completed')
    expect(wrapper.get('[data-testid="trace-tokens"]').text()).toContain('5,168 in · 3,994 out')
  })

  it('publishes the character seed the node card is drawn from', () => {
    const wrapper = mount(ChatRail, {
      props: { entries: [chatEntry()], collapsed: false, characterOf: () => 7 },
    })
    const row = wrapper.get('[data-testid="trace-entry"]')
    expect(row.attributes('data-node')).toBe('step-1')
    expect(row.attributes('data-identity')).toBe('Declared Role')
    const avatar = wrapper.get('[data-testid="trace-avatar"]')
    expect(avatar.attributes('data-character-seed')).toBe('Declared Role')
    expect(avatar.attributes('data-character')).toBe('7')
    expect(avatar.attributes('style')).toContain('--character-color: var(--character-7)')
  })

  it('gives a run-level row no avatar to give it', () => {
    const wrapper = mount(ChatRail, {
      props: {
        entries: [chatEntry({ identity: '', nodeId: undefined, variant: 'system', message: 'Run started' })],
        collapsed: false,
      },
    })
    expect(wrapper.find('[data-testid="trace-avatar"]').exists()).toBe(false)
  })

  it('does not put an unbounded number of rows in the DOM', () => {
    // T2.8 and S3: a run of 119+ frames is the criterion and a long one goes
    // well past it. The window bounds the node count; `content-visibility`
    // bounds the work per node.
    const entries = Array.from({ length: 260 }, (_, index) =>
      chatEntry({ id: `r1-${index}`, seq: index, message: `line ${index}` }),
    )
    const wrapper = mount(ChatRail, { props: { entries, collapsed: false } })
    const rows = wrapper.findAll('[data-testid="trace-entry"]')
    expect(rows.length).toBeLessThan(entries.length)
    // The NEWEST rows are the ones kept - the fold is history, not the present.
    expect(rows.at(-1)?.text()).toContain('line 259')
    expect(wrapper.get('[data-testid="trace-earlier"]').text()).toBe('60 earlier lines')
  })

  it('opens the fold on demand rather than losing what it folded', async () => {
    const entries = Array.from({ length: 260 }, (_, index) =>
      chatEntry({ id: `r1-${index}`, seq: index, message: `line ${index}` }),
    )
    const wrapper = mount(ChatRail, { props: { entries, collapsed: false } })
    await wrapper.get('[data-testid="trace-earlier"]').trigger('click')
    expect(wrapper.findAll('[data-testid="trace-entry"]')).toHaveLength(260)
    expect(wrapper.find('[data-testid="trace-earlier"]').exists()).toBe(false)
  })
})

describe('the text hygiene the bans rest on', () => {
  it('resolves a literal escape sequence rather than printing it', () => {
    expect(plain('Two claims failed.\\nBoth cite the same page.')).toBe(
      'Two claims failed. Both cite the same page.',
    )
  })

  it('flattens a real newline and every run of whitespace', () => {
    expect(plain('a\n\n  b\tc')).toBe('a b c')
  })

  it('refuses to quote a serialised structure as though it were a sentence', () => {
    expect(firstSentence('{"valid": true, "feedback": null}')).toBe('')
    expect(firstSentence('[1, 2, 3]')).toBe('')
    expect(firstSentence('It failed. Then it failed again.')).toBe('It failed')
  })

  it('clips on a word boundary and says that it clipped', () => {
    const clipped = clip('the quick brown fox jumps over the lazy dog', 20)
    expect(clipped.length).toBeLessThanOrEqual(20)
    expect(clipped.endsWith('…')).toBe(true)
    expect(clipped).not.toContain('jumps')
  })

  it('reads a duration the way a person says one', () => {
    expect(duration(0)).toBe('0ms')
    expect(duration(940)).toBe('940ms')
    expect(duration(2800)).toBe('2.8s')
    expect(duration(95_000)).toBe('1m 35s')
    expect(duration(120_000)).toBe('2m')
    expect(duration(undefined)).toBe('')
  })
})
