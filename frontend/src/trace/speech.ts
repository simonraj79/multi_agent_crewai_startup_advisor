/**
 * What an `utterance` frame is actually carrying, and how to render it.
 *
 * `events/serializer.py:720-723` writes the completed response into
 * `details.text`, and it `json.dumps`es anything that is not already a string.
 * Three shapes therefore arrive at the dialogue rail and only one of them is
 * speech:
 *
 * 1. **Prose.** The common case, and the only one the rail was written for.
 *    Rendered as Markdown, because the models write Markdown and a rail showing
 *    `**the point**` with the asterisks is showing the wire format.
 * 2. **A JSON-encoded string**, i.e. prose that went through `json.dumps` on
 *    its way here. It arrives wrapped in quotes with every newline written out
 *    as a literal backslash-n, which is what put `\n` on screen.
 * 3. **A structured result** - `{"valid":true,"feedback":null}` is a guardrail
 *    LLM's answer, and it was being rendered as something an agent SAID. It is
 *    not speech, it is a machine answering a machine, and the rail says so in
 *    one line and puts the object behind the disclosure.
 *
 * A one-key object whose single value is a long string is case 2 wearing a
 * wrapper - a model asked for `{"report": "..."}` - so the string is lifted out
 * and rendered as the prose it is.
 *
 * Pure and dependency-free apart from the escape-first Markdown renderer, so
 * `dialogueRail.spec.ts` can assert all three shapes without a mount.
 */

import { renderMarkdown } from '../utils/markdown'

/** Above this many characters, a lone string value is prose rather than a field. */
const PROSE_MIN_CHARS = 80

/** Beyond this many keys, nothing is worth lifting out; it is a record. */
const LIFTABLE_KEYS = 1

export type SpeechKind = 'prose' | 'structured'

export interface Speech {
  kind: SpeechKind
  /** The prose to render, or '' for a structured result. */
  text: string
  /** The payload to show behind the disclosure, pretty-printed. */
  payload: string
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? ''
  } catch {
    return ''
  }
}

/**
 * Decide what one utterance is, and hand back both halves.
 *
 * Deliberately conservative: anything that does not parse as JSON is prose,
 * because a model that wrote a sentence beginning with a brace is far rarer
 * than one that wrote a sentence.
 */
export function readSpeech(raw: string): Speech {
  const trimmed = (raw ?? '').trim()
  if (!trimmed) return { kind: 'prose', text: '', payload: '' }
  if (!trimmed.startsWith('{') && !trimmed.startsWith('[') && !trimmed.startsWith('"')) {
    return { kind: 'prose', text: raw, payload: '' }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    // It looked like JSON and is not. Whatever it is, a person wrote it.
    return { kind: 'prose', text: raw, payload: '' }
  }

  if (typeof parsed === 'string') return { kind: 'prose', text: parsed, payload: '' }
  if (parsed === null || typeof parsed !== 'object') {
    return { kind: 'structured', text: '', payload: pretty(parsed) }
  }
  if (Array.isArray(parsed)) return { kind: 'structured', text: '', payload: pretty(parsed) }

  const entries = Object.entries(parsed as Record<string, unknown>)
  if (entries.length <= LIFTABLE_KEYS) {
    const [, only] = entries[0] ?? []
    if (typeof only === 'string' && only.trim().length >= PROSE_MIN_CHARS) {
      return { kind: 'prose', text: only, payload: pretty(parsed) }
    }
  }
  return { kind: 'structured', text: '', payload: pretty(parsed) }
}

/**
 * The rendered HTML for a spoken entry.
 *
 * `renderMarkdown` escapes every character of input BEFORE it recognises any
 * structure, so this is safe on model output by construction rather than by
 * sanitising afterwards - see CLAUDE.md's note on why the renderer is
 * escape-first. The only reason the call is wrapped at all is the reveal: the
 * rail hands in a PREFIX of the text while it is still being spoken, and a
 * prefix can end inside a fence or a link, so the renderer has to be safe on a
 * half-written document. It is: an unclosed construct degrades to an escaped
 * paragraph.
 */
export function renderSpeech(visible: string): string {
  return renderMarkdown(visible)
}
