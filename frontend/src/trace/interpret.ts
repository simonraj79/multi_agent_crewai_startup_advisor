/**
 * One frame in, one sentence out — or nothing.
 *
 * The trace rail used to render `frame.message` verbatim, which is the
 * framework talking to itself: "persist started", "write_report to persist",
 * "ValidatorFlow completed", "AgentExecutor reporting_task", a guardrail's
 * `{"valid":true,"feedback":null}` shown as speech, and `5168 in · 3994 out`
 * on every row. All of it is true and none of it is addressed to the person
 * watching the run.
 *
 * This module is the only place that decides what a row SAYS. It is pure: a
 * frame and a lookup go in, a `TraceLine` or `null` comes out, so the whole
 * vocabulary is assertable over a real frame log without mounting anything.
 *
 * TWO RULES IT IS BUILT AROUND, and both are criteria rather than taste
 * (`docs/run-shell/DEFINITION-OF-DONE.md` T2.1, T2.2, G2):
 *
 * 1. **The verb comes from the frame kind and its stage, never from a role
 *    list.** Nothing here knows which flow is running. A tool's verb is chosen
 *    from words inside the tool name the framework emitted, which is data the
 *    run supplies rather than a table of this repository's own agents — so a
 *    flow invented next week narrates itself with no edit here.
 * 2. **The subject is the agent's identity**, resolved in this order:
 *    `details.agent_role` (CrewAI stamps it on every agent, task, tool and LLM
 *    event) → the descriptor node's declared `agent_role` (the synthetic path
 *    emits no agent frames at all, so this is the only identity a no-cost run
 *    has) → the node's label → nothing, which makes the line a system line.
 *
 * What is NOT here: the raw payload. Every line carries `raw`, and the rail
 * puts it behind a per-row disclosure collapsed by default. Nothing is hidden;
 * it is one click away instead of in the way.
 */

import type { FrameData, GraphNodeDefinition } from '../types/studio'
import { humaniseCode, humaniseTask, humaniseTool } from '../utils/humanise'

/** The bound T2.1 measures: one short line, never a paragraph. */
export const MAX_TRACE_LINE_CHARS = 140

/** How much of a payload string may reach a line before it is clipped. */
const MAX_QUOTED_CHARS = 60

export type TraceTone = 'info' | 'warn' | 'error' | 'you'

/**
 * How a later frame reaches an earlier row.
 *
 * `run` keys a row for the life of the run: a tool's `after` frame finds the
 * row its `before` frame wrote however many rows ago and rewrites it in place,
 * which is what turns two rows ("is searching…", "searched…") into one that
 * completes. `tail` merges only when the row is still the newest one, which is
 * what stops the highest-volume kind — reasoning — either repeating itself
 * forty times or silently rewriting a row the reader has already scrolled past.
 *
 * `precedence` breaks ties between frames that describe the same moment at
 * different resolutions. A node starting, a crew starting, a task starting and
 * an agent starting are four frames and one event; the most specific of them
 * wins the row, whichever order they arrive in.
 */
export interface TraceCoalesce {
  key: string
  precedence: number
  scope: 'run' | 'tail'
  /**
   * A key this line RETIRES when it opens a row of its own.
   *
   * The loop case, and it is the only thing that makes a revise readable. A
   * node that runs twice emits `open` / `close` twice, and without this the
   * second visit's frames merge into the first visit's rows and the whole
   * second pass is invisible in the surface whose job is saying what happened.
   * A close retires its open and an open retires its close, so each visit gets
   * one pair - while the crew/task/agent collapse WITHIN a visit still works,
   * because a merge retires nothing.
   */
  clears?: string
}

/**
 * The precedence a frame carries when it ends the thing it describes.
 *
 * A row keyed at this level is finished the moment it lands, so its key is
 * retired and the next call under the same name starts a fresh row. Without
 * that, the three tool calls one agent makes with the same tool collapse into
 * one row - which is exactly the two-thirds of a branch's spend the first paid
 * run went looking for.
 */
export const TRACE_TERMINAL_PRECEDENCE = 100

/** The payload the row hides behind its disclosure. */
export interface TraceRaw {
  /** The framework's own sentence, which used to BE the row. */
  message: string
  /** `frame.details`, pretty-printed. */
  details: string
  model?: string
  tool?: string
  tokens?: { prompt: number; completion: number }
  durationMs?: number
  seq: number
  ts: string
  kind: string
  eventType: string
}

export interface TraceLine {
  text: string
  tone: TraceTone
  nodeId?: string
  /**
   * The resolved role string, which is also the character seed. Empty when the
   * frame speaks for the run rather than for an agent.
   */
  identity: string
  raw: TraceRaw
  coalesce?: TraceCoalesce
}

/** What the interpreter is allowed to know about a node. */
export interface TraceNodeFacts {
  label?: string
  kind?: GraphNodeDefinition['kind']
  agentRole?: string
  taskName?: string
}

export interface TraceContext {
  /** The descriptor's facts for a node, or undefined if it draws no such node. */
  node(nodeId: string): TraceNodeFacts | undefined
  /**
   * When a call's `before` row was written, so an `after` frame can say how
   * long it took. Optional: without it a completed call still gets its line,
   * just without the duration.
   */
  startedAt?(coalesceKey: string): number | undefined
}

/* ------------------------------------------------------------------ *
 *  Text hygiene                                                       *
 * ------------------------------------------------------------------ */

/**
 * Everything a payload string has to survive before it can reach a line.
 *
 * The serializer `json.dumps`es a response that is not a string, so a literal
 * backslash-n arrives as two characters and renders as `\n` on screen; a
 * guardrail's answer arrives as `{"valid":true,"feedback":null}`. Both are
 * assertions in `traceInterpretation.spec.ts`, so this is the function that
 * makes them pass rather than a comment asking nicely.
 */

export function plain(value: unknown): string {
  if (value === null || value === undefined) return ''
  const raw = typeof value === 'string' ? value : String(value)
  return raw
    // A literal escape sequence, written out. Not a newline — those are next.
    .replace(/\\[nrt]/g, ' ')
    // Real control characters, including the newlines the clip is about.
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** True when a string is a serialised structure rather than something said. */
export function looksStructured(value: string): boolean {
  const head = value.trimStart()
  return head.startsWith('{') || head.startsWith('[') || value.includes('{"')
}

/**
 * The first sentence of a message, bounded.
 *
 * An error is the one payload worth quoting, and a stack-shaped one is the one
 * most likely to be a paragraph. The first sentence is almost always the part
 * a person can act on.
 */
export function firstSentence(value: unknown, max = MAX_QUOTED_CHARS): string {
  const flat = plain(value)
  if (!flat) return ''
  if (looksStructured(flat)) return ''
  const stop = flat.search(/[.!?](\s|$)/)
  const sentence = stop > 0 ? flat.slice(0, stop) : flat
  return clip(sentence, max)
}

/** Clip to `max` characters on a word boundary where one is near. */
export function clip(value: string, max: number): string {
  if (value.length <= max) return value
  const cut = value.slice(0, max - 1)
  const space = cut.lastIndexOf(' ')
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`
}

/** A duration a person reads, from milliseconds. */
export function duration(ms: number | undefined): string {
  if (ms === undefined || !Number.isFinite(ms) || ms < 0) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`
}

/** `3` -> "3 results", `1` -> "1 result". */
function countPhrase(count: number): string {
  return count === 1 ? '1 result' : `${count} results`
}

/* ------------------------------------------------------------------ *
 *  The tool word table                                                *
 * ------------------------------------------------------------------ */

/**
 * The verb a tool call takes, chosen from words INSIDE the emitted tool name.
 *
 * This is the one table in the module, and it is admissible under T2.2 for a
 * precise reason: every key is a word the framework itself puts in a tool id,
 * not a name from any particular flow. A tool called `search_web`,
 * `web_search_tool` or `SerperDevTool` all reach "searching" by the same rule,
 * and one nobody here has heard of falls through to "using" rather than to a
 * wrong verb.
 *
 * Ordered: the first matching row wins, so `read_website` is reading and not
 * whatever a later row would have claimed.
 */
const TOOL_VERBS: ReadonlyArray<{ words: readonly string[]; gerund: string; past: string }> = [
  { words: ['search', 'query', 'lookup', 'find', 'research', 'retrieve'], gerund: 'searching', past: 'searched' },
  { words: ['scrape', 'read', 'fetch', 'crawl', 'browse', 'load', 'open'], gerund: 'reading', past: 'read' },
  { words: ['write', 'save', 'store', 'export', 'record', 'upload'], gerund: 'saving', past: 'saved' },
  { words: ['run', 'exec', 'execute', 'eval', 'compute', 'calculate'], gerund: 'running', past: 'ran' },
  { words: ['analyse', 'analyze', 'assess', 'check', 'inspect', 'review', 'audit', 'classify'], gerund: 'checking', past: 'checked' },
]

const DEFAULT_TOOL_VERB = { gerund: 'using', past: 'used' } as const

export function toolVerb(toolName: string): { gerund: string; past: string } {
  const tokens = new Set(
    String(toolName ?? '')
      .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter(Boolean),
  )
  for (const row of TOOL_VERBS) {
    if (row.words.some((word) => tokens.has(word))) return { gerund: row.gerund, past: row.past }
  }
  return DEFAULT_TOOL_VERB
}

/* ------------------------------------------------------------------ *
 *  Reading a frame                                                    *
 * ------------------------------------------------------------------ */

function text(details: Record<string, unknown>, key: string): string {
  const value = details[key]
  return typeof value === 'string' ? value.trim() : ''
}

function count(details: Record<string, unknown>, key: string): number | undefined {
  const value = details[key]
  // `null` and `''` both coerce to 0, and the serializer writes `null` for a
  // count the event did not carry - so "absent" would read as "zero of them",
  // which is a claim nobody made.
  if (value === null || value === undefined || value === '') return undefined
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function stageOf(frame: FrameData): string {
  return text(frame.details, 'stage')
}

/** The role the frame itself named, if CrewAI stamped one on the event. */
function frameRole(frame: FrameData): string {
  return text(frame.details, 'agent_role')
}

/**
 * Who this line is about.
 *
 * The fallback ladder is the whole of T2.2's identity rule, and each rung
 * exists because a real path has only that one: a paid CrewAI run stamps
 * `agent_role` on the event; the synthetic backend emits no agent frame at all
 * and the descriptor's declared `agent_role` is all there is; a graph an author
 * drew may declare neither, and its node label is what they typed.
 */
function identityFor(frame: FrameData, ctx: TraceContext): string {
  const stamped = frameRole(frame)
  if (stamped) return stamped
  const nodeId = frame.node_id
  if (!nodeId) return ''
  const facts = ctx.node(nodeId)
  // A role and a label are both prose somebody wrote and are used verbatim. A
  // NODE ID is an identifier, and putting one in a sentence is the leak T1.3
  // measures - so the last rung of the ladder is humanised.
  return facts?.agentRole || facts?.label || humaniseCode(nodeId)
}

/** The task this frame is about, however the ladder happened to name it. */
function taskFor(frame: FrameData, ctx: TraceContext): string {
  const declared = text(frame.details, 'task') || text(frame.details, 'task_name')
  if (declared) return declared
  return (frame.node_id && ctx.node(frame.node_id)?.taskName) || ''
}

/**
 * The kinds of node whose lifecycle is worth a row of its own.
 *
 * A router, a transform and an output step are plumbing: they are what
 * produced "persist started" and "write_report to persist", two rows that told
 * an operator nothing they could not see on the canvas. An agent node is
 * different, and on the synthetic path its `node_state` frames are the ONLY
 * start signal there is.
 */
function narratesLifecycle(frame: FrameData, ctx: TraceContext): boolean {
  if (frameRole(frame)) return true
  const facts = frame.node_id ? ctx.node(frame.node_id) : undefined
  if (!facts) return false
  if (facts.agentRole) return true
  return facts.kind === 'agent'
}

function possessive(name: string): string {
  return name.endsWith('s') ? `${name}'` : `${name}'s`
}

/* ------------------------------------------------------------------ *
 *  The vocabulary                                                     *
 * ------------------------------------------------------------------ */

function line(
  frame: FrameData,
  text_: string,
  tone: TraceTone,
  identity: string,
  coalesce?: TraceCoalesce,
): TraceLine {
  return {
    text: clip(plain(text_), MAX_TRACE_LINE_CHARS),
    tone,
    nodeId: frame.node_id,
    identity,
    raw: rawOf(frame),
    coalesce,
  }
}

/**
 * A statement about the RUN, which is nobody's node.
 *
 * The serializer stamps run-level frames with the registry's own workflow node
 * id, and that node is instrumentation rather than something the graph draws -
 * attributing "Run started" to it would file the row under a card no canvas has
 * and give it an avatar for an agent that does not exist.
 */
function runLine(frame: FrameData, text_: string, tone: TraceTone): TraceLine {
  return { ...line(frame, text_, tone, ''), nodeId: undefined }
}

function rawOf(frame: FrameData): TraceRaw {
  const prompt = count(frame.details, 'prompt_tokens')
  const completion = count(frame.details, 'completion_tokens')
  return {
    message: frame.message,
    details: safeJson(frame.details),
    model: text(frame.details, 'model') || undefined,
    tool: text(frame.details, 'tool') || undefined,
    tokens:
      prompt !== undefined || completion !== undefined
        ? { prompt: prompt ?? 0, completion: completion ?? 0 }
        : undefined,
    durationMs: frame.duration_ms,
    seq: frame.seq,
    ts: frame.ts,
    kind: String(frame.kind),
    eventType: frame.event_type,
  }
}

/**
 * A frame's details, pretty-printed, never throwing.
 *
 * `details` is `Record<string, unknown>` off the wire, and a server that put a
 * cycle or a BigInt in it must not be able to blank the rail. The disclosure is
 * the one place raw is allowed, so it degrades to a note rather than to
 * nothing.
 */
function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? ''
  } catch {
    return '(this payload could not be displayed)'
  }
}

/**
 * `llm`, `tool` and `guardrail` frames bracket a call; this pairs the two.
 *
 * Exported because the composable has to record a call's start time under the
 * SAME key the interpreter will look it up by, and two independently written
 * key functions that drift produce a duration that is silently absent rather
 * than wrong - the hardest kind of gap to notice.
 */
export function traceCallKey(frame: FrameData): string {
  const node = frame.node_id ?? '-'
  const callId = text(frame.details, 'call_id')
  if (callId) return `${frame.kind}:${callId}`
  // A guardrail runs the same check again after a rejection, and CrewAI counts
  // the attempts. Without the count in the key, round two's `before` merges
  // into round one's row and the trace reads backwards.
  const retry = count(frame.details, 'retry_count')
  const round = retry === undefined ? '' : `#${retry}`
  const named =
    text(frame.details, 'tool') || text(frame.details, 'guardrail') || text(frame.details, 'model')
  return `${frame.kind}:${node}:${named || frame.kind}${round}`
}

function elapsedFor(frame: FrameData, ctx: TraceContext, key: string): string {
  if (frame.duration_ms !== undefined) return duration(frame.duration_ms)
  const started = ctx.startedAt?.(key)
  if (started === undefined) return ''
  const at = Date.parse(frame.ts)
  if (!Number.isFinite(at)) return ''
  return duration(Math.max(0, at - started))
}

/** What a finished tool call actually came back with. */
function toolOutcome(details: Record<string, unknown>): string {
  const failure = plain(details.failure)
  if (failure) return 'it failed'
  const status = text(details, 'tool_status')
  if (status && status.toLowerCase() !== 'ok') return humaniseCode(status).toLowerCase()
  const results = count(details, 'result_count')
  const cached = details.from_cache === true
  if (results !== undefined) {
    if (results <= 0) return cached ? 'nothing in the cache' : 'nothing found'
    return cached ? `${countPhrase(results)} from the cache` : countPhrase(results)
  }
  return cached ? 'from the cache' : ''
}

function agentLine(frame: FrameData, ctx: TraceContext): TraceLine | null {
  const who = identityFor(frame, ctx)
  const node = frame.node_id ?? '-'
  const stage = stageOf(frame)
  const rawTask = taskFor(frame, ctx)
  const task = rawTask ? humaniseTask(rawTask) : ''
  // The most specific frame wins the row: a node starting, a crew starting, a
  // task starting and an agent starting are four frames about one moment.
  const precedence = (frameRole(frame) ? 2 : 0) + (rawTask ? 1 : 0) + 1

  if (stage === 'skill') {
    const verb = text(frame.details, 'skill_event') || 'used'
    const skill = text(frame.details, 'skill')
    return line(
      frame,
      skill ? `${who} ${verb} the ${humaniseTask(skill)} skill` : `${who} ${verb} a skill`,
      'info',
      who,
    )
  }
  if (stage === 'before') {
    return line(
      frame,
      task ? `${who} started on ${task}` : `${who} started`,
      'info',
      who,
      { key: `open:${node}`, precedence, scope: 'run', clears: `close:${node}` },
    )
  }
  if (stage === 'after') {
    return line(
      frame,
      task ? `${who} finished ${task}` : `${who} finished`,
      'info',
      who,
      { key: `close:${node}`, precedence, scope: 'run', clears: `open:${node}` },
    )
  }
  if (stage === 'error') {
    const why = firstSentence(frame.details.error)
    const what = task ? `${who} could not finish ${task}` : `${who} could not finish`
    // Deliberately UNCOALESCED. A failure is rare, it is the row a reader is
    // looking for, and letting it share a key with the node's completion means
    // one of the two silently overwrites the other - in either direction.
    return line(frame, why ? `${what}: ${why}` : what, 'error', who)
  }
  // A stage this ladder does not know is still an agent doing something, and
  // the payload is one click away. Better a plain line than a dropped frame.
  return line(frame, `${who} is working`, frame.level === 'ERROR' ? 'error' : 'info', who)
}

function nodeStateLine(frame: FrameData, ctx: TraceContext): TraceLine | null {
  const who = identityFor(frame, ctx)
  const node = frame.node_id ?? '-'
  const stage = stageOf(frame)
  const label = who || node

  // An error is always worth a row, whatever kind of node raised it: a
  // transform that threw is the most important thing on the page, and it is
  // the one lifecycle frame that is never coalesced away.
  if (stage === 'error' || frame.level === 'ERROR') {
    const why = firstSentence(frame.details.error)
    return line(frame, why ? `${label} could not finish: ${why}` : `${label} could not finish`, 'error', who)
  }
  // `paused` is CrewAI saying a method is parked. The gate frame that follows
  // says what it is parked ON, which is the only half a person can act on.
  if (stage === 'paused') return null
  if (!narratesLifecycle(frame, ctx)) return null
  if (stage === 'after') {
    return line(frame, `${label} finished`, 'info', who, { key: `close:${node}`, precedence: 0, scope: 'run', clears: `open:${node}` })
  }
  return line(frame, `${label} started`, 'info', who, { key: `open:${node}`, precedence: 0, scope: 'run', clears: `close:${node}` })
}

function toolLine(frame: FrameData, ctx: TraceContext): TraceLine | null {
  const stage = stageOf(frame)
  const who = identityFor(frame, ctx)
  const emitted = text(frame.details, 'tool')
  const tool = emitted ? humaniseTool(emitted) : 'a tool'
  const verb = toolVerb(emitted)
  const query = clip(plain(frame.details.query), MAX_QUOTED_CHARS)
  const key = traceCallKey(frame)

  if (stage === 'error') {
    return line(frame, `${possessive(who)} ${tool} call failed`, 'error', who, {
      key,
      precedence: TRACE_TERMINAL_PRECEDENCE,
      scope: 'run',
    })
  }
  if (stage === 'after') {
    const outcome = toolOutcome(frame.details)
    const what = query ? `${who} ${verb.past} “${query}”` : `${who} ${verb.past} ${tool}`
    return line(frame, outcome ? `${what} — ${outcome}` : what, frame.level === 'WARNING' ? 'warn' : 'info', who, {
      key,
      precedence: TRACE_TERMINAL_PRECEDENCE,
      scope: 'run',
    })
  }
  if (stage === 'before') {
    return line(
      frame,
      query
        ? `${who} is ${verb.gerund} “${query}” with ${tool}`
        // “is using with X” is not a sentence; the neutral verb takes the tool
        // as its object where a specific one takes it as an instrument.
        : verb === DEFAULT_TOOL_VERB
          ? `${who} is using ${tool}`
          : `${who} is ${verb.gerund} with ${tool}`,
      'info',
      who,
      { key, precedence: 0, scope: 'run' },
    )
  }
  return null
}

function llmLine(frame: FrameData, ctx: TraceContext): TraceLine | null {
  const stage = stageOf(frame)
  // Both belong to another surface. `chunk` and `utterance` are what the model
  // SAID, and the dialogue rail renders them as speech; carrying the same 4,096
  // characters here is noise in the surface whose job is the mechanics.
  if (stage === 'chunk' || stage === 'utterance') return null
  const who = identityFor(frame, ctx)
  const key = traceCallKey(frame)

  if (stage === 'error') {
    return line(frame, `${possessive(who)} model call failed`, 'error', who, {
      key,
      precedence: TRACE_TERMINAL_PRECEDENCE,
      scope: 'run',
    })
  }
  if (stage === 'after') {
    const took = elapsedFor(frame, ctx, key)
    return line(frame, took ? `${who} thought for ${took}` : `${who} finished thinking`, 'info', who, {
      key,
      precedence: TRACE_TERMINAL_PRECEDENCE,
      scope: 'run',
    })
  }
  if (stage === 'before') {
    return line(frame, `${who} is thinking`, 'info', who, { key, precedence: 0, scope: 'run' })
  }
  return null
}

function guardrailLine(frame: FrameData, ctx: TraceContext): TraceLine | null {
  const stage = stageOf(frame)
  const who = identityFor(frame, ctx)
  const key = traceCallKey(frame)
  if (stage === 'after') {
    const passed = frame.details.success === true
    if (passed) {
      return line(frame, `${possessive(who)} work passed the check`, 'info', who, {
        key,
        precedence: TRACE_TERMINAL_PRECEDENCE,
        scope: 'run',
      })
    }
    const retry = count(frame.details, 'retry_count')
    const again = retry && retry > 0 ? ` (attempt ${retry + 1})` : ''
    return line(frame, `${possessive(who)} work failed the check — trying again${again}`, 'warn', who, {
      key,
      precedence: TRACE_TERMINAL_PRECEDENCE,
      scope: 'run',
    })
  }
  if (stage === 'before') {
    return line(frame, `${possessive(who)} work is being checked`, 'info', who, {
      key,
      precedence: 0,
      scope: 'run',
    })
  }
  return null
}

/**
 * What the gate is asking, from whichever half of the stack raised it.
 *
 * The SERVICE's `gate_open` carries the whole prompt in `details`, `title`
 * included. CrewAI's own carries the question as the frame MESSAGE and nothing
 * in `details` - and unlike every other message on this ladder, that one is
 * authored text addressed to a person rather than the framework naming a
 * method. It is the only place `frame.message` is admitted.
 */
function gateTitle(frame: FrameData): string {
  return text(frame.details, 'title') || plain(frame.message)
}

/**
 * The decision, wherever the reply put it.
 *
 * The service writes `outcome`. CrewAI's own `gate_closed` leaves `outcome`
 * null and carries the reply as a JSON `feedback` string - so reading only
 * `outcome` made every native gate close as "You answered", which is the one
 * thing about a gate a reader already knows.
 */
function gateDecision(details: Record<string, unknown>): string {
  const outcome = text(details, 'outcome')
  if (outcome) return outcome
  const feedback = text(details, 'feedback')
  if (!feedback.startsWith('{')) return feedback
  try {
    const parsed = JSON.parse(feedback) as Record<string, unknown>
    const decision = parsed?.decision ?? parsed?.outcome
    return typeof decision === 'string' ? decision : ''
  } catch {
    return ''
  }
}

function gateLine(frame: FrameData, ctx: TraceContext): TraceLine | null {
  const who = identityFor(frame, ctx)
  const title = gateTitle(frame)
  if (frame.kind === 'gate_open') {
    return line(frame, title ? `Waiting for you: ${title}` : 'Waiting for you', 'you', who, {
      key: `gate:${text(frame.details, 'gate_id') || frame.node_id || frame.seq}`,
      precedence: 0,
      scope: 'run',
    })
  }
  if (frame.kind === 'gate_closed') {
    const outcome = gateDecision(frame.details).toLowerCase()
    if (/revis|reject|change|decline|no\b/.test(outcome)) return line(frame, 'You asked for changes', 'you', who)
    if (/ok\b|approve|accept|confirm|continue|yes\b/.test(outcome)) return line(frame, 'You approved', 'you', who)
    return line(frame, outcome ? `You answered: ${humaniseCode(outcome)}` : 'You answered', 'you', who)
  }
  // Both sweep frames are the SERVICE's, and both carry `title` in `details`.
  // The message fallback above is not reached for them on purpose: theirs
  // already contains the whole sentence, and pasting it into another one reads
  // as a stutter.
  const declared = text(frame.details, 'title')
  if (frame.kind === 'gate_expired') {
    return line(
      frame,
      declared ? `The review window for ${declared} expired` : 'The review window expired',
      'warn',
      who,
    )
  }
  // `gate_alert`: the sweep saying a gate has gone unanswered past its grace.
  const overdue = count(frame.details, 'overdue_seconds')
  const late = overdue !== undefined ? duration(overdue * 1000) : ''
  const what = declared ? `${declared} is still waiting for you` : 'A review is still waiting for you'
  return line(frame, late ? `${what} — ${late} past the deadline` : what, 'warn', who)
}

function runStateLine(frame: FrameData): TraceLine | null {
  const stage = stageOf(frame)
  // The stage lane owns the plan: seven statements about the graph, made
  // before anything happens, which in a trace read as seven system messages
  // before the run starts.
  if (stage === 'plan') return null
  const status = text(frame.details, 'status').toLowerCase()
  if (status === 'completed') return runLine(frame, 'Run finished', 'info')
  if (status === 'cancelled' || status === 'cancelling') return runLine(frame, 'Run cancelled', 'warn')
  if (status === 'failed') {
    const why = firstSentence(frame.details.error)
    return runLine(frame, why ? `Run failed: ${why}` : 'Run failed', 'error')
  }
  if (status === 'running' || status === 'queued' || frame.event_type.includes('WORKFLOW_START')) {
    return runLine(frame, 'Run started', 'info')
  }
  // A run_state frame this ladder cannot read says nothing a person can act
  // on, and the canvas already shows where the run is.
  return null
}

function errorLine(frame: FrameData, ctx: TraceContext): TraceLine {
  const who = identityFor(frame, ctx)
  const why = firstSentence(frame.details.error) || firstSentence(frame.details.message) || firstSentence(frame.message)
  const runLevel = !frame.node_id || frame.event_type.includes('WORKFLOW')
  if (runLevel) return runLine(frame, why ? `Run failed: ${why}` : 'Run failed', 'error')
  return line(frame, why ? `${who} hit an error: ${why}` : `${who} hit an error`, 'error', who)
}

/* ------------------------------------------------------------------ *
 *  The entry point                                                    *
 * ------------------------------------------------------------------ */

/**
 * One frame in, one line or nothing.
 *
 * `null` is a first-class answer and not a failure: `token`, `metrics`,
 * `edge_taken`, a stream chunk, an utterance, a plan statement and a paused
 * method all have another surface that owns them, or nothing a person could
 * act on. A frame kind from a newer server also returns null, which is the
 * conservative half of the same rule — a row nobody can read is worse than no
 * row, and the frame is still in the run's log either way.
 */
export function interpretFrame(frame: FrameData, ctx: TraceContext): TraceLine | null {
  switch (frame.kind) {
    case 'run_state':
      return runStateLine(frame)
    case 'node_state':
      return nodeStateLine(frame, ctx)
    case 'agent':
      return agentLine(frame, ctx)
    case 'tool':
      return toolLine(frame, ctx)
    case 'llm':
      return llmLine(frame, ctx)
    case 'guardrail':
      return guardrailLine(frame, ctx)
    case 'reasoning': {
      const who = identityFor(frame, ctx)
      return line(frame, `${who} is reasoning`, 'info', who, {
        key: `think:${frame.node_id ?? '-'}`,
        precedence: 0,
        // `tail` and not `run`: this is the highest-volume kind there is, and
        // a run-scoped key would rewrite a row the reader scrolled past ten
        // rows ago. Merging only while it is still the newest row collapses a
        // burst and leaves history alone.
        scope: 'tail',
      })
    }
    case 'gate_open':
    case 'gate_closed':
    case 'gate_expired':
    case 'gate_alert':
      return gateLine(frame, ctx)
    case 'verdict': {
      const score = count(frame.details, 'composite_score')
      const label = humaniseCode(text(frame.details, 'verdict'))
      if (!label && score === undefined) return null
      const scored = score === undefined ? '' : `Scored ${Number(score.toFixed(1))}/10`
      return line(frame, [scored, label].filter(Boolean).join(' — '), 'info', '')
    }
    case 'error':
      return errorLine(frame, ctx)
    case 'token':
    case 'metrics':
    case 'edge_taken':
      return null
    default:
      // A kind this client has never heard of. Nothing here can name what it
      // means, and inventing a sentence for it is exactly the dump this module
      // replaced — except an ERROR, which is always worth saying.
      return frame.level === 'ERROR' ? errorLine(frame, ctx) : null
  }
}
