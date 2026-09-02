import { BUILDER_SCHEMA_ID } from '../types/builder'
import type {
  BuilderDocument,
  BuilderEdge,
  BuilderJoins,
  BuilderNode,
} from '../types/builder'

/**
 * Turning a document into the four shapes the rest of the builder needs: what
 * goes on the wire, what goes to `/validate`, what identifies a document's
 * MEANING, and how big it is.
 *
 * All four exist because the document on the client and the document on the
 * wire are not quite the same object, and every difference is load-bearing:
 *
 * - `toWire` owns the `schema` spelling. Pydantic refuses a field called
 *   `schema` (it shadows a `BaseModel` attribute), so the Python field is
 *   `document_schema` with `alias="schema"`. One function writing that key is
 *   what stops the alias becoming a thing every caller has to remember.
 * - `forValidate` removes `id` and forces `version` to a number, because
 *   `POST /api/builder/validate` reads both off the raw body BEFORE parsing.
 *   `_requested_version` answers **422** on a value that is not a whole number
 *   (`version must be a whole number; this document carries 'v7'`), and
 *   `str(... .get("id") or new_document_id())` feeds a malformed id straight
 *   into a 422 against `BUILDER_DOCUMENT_ID_PATTERN`. Neither is a refusal an
 *   author can act on - both name a field nobody typed and cannot see - and
 *   both are avoidable from here.
 * - `fingerprint` omits `position`, so dragging a node across the canvas does
 *   not spend a validate round trip on a field the compiler never reads.
 * - `wireBytes` is what tells an author their document is approaching
 *   `max_document_bytes` before the save comes back 413.
 *
 * Nothing here mutates its argument. `commit()` is the only write path in the
 * builder, and a serializer that quietly normalised a document would be a
 * second one.
 */

/**
 * A document as the server receives it.
 *
 * `id` is optional because that is the whole difference between the save shape
 * and the validate shape, and making it a type-level difference means
 * `forValidate`'s omission cannot be undone by a later edit without the
 * compiler noticing.
 */
export interface BuilderDocumentWire {
  schema: typeof BUILDER_SCHEMA_ID
  id?: string
  name: string
  version: number
  input_field: string
  nodes: BuilderNode[]
  edges: BuilderEdge[]
  joins: BuilderJoins
  /**
   * Always `null` on the way out. The budget block is written by `budget.py`
   * onto the document it priced; an author's copy is at best a stale estimate
   * of an older version, and sending it back would be asserting a price nothing
   * computed. The server recomputes it on every response anyway.
   */
  budget: null
}

/** The validate shape: the same document with no `id` at all. */
export type BuilderValidateWire = Omit<BuilderDocumentWire, 'id'>

/**
 * The document, spelled the way the wire spells it.
 *
 * Written out field by field rather than spread from `doc`, so the wire
 * contract is visible in one place and an extra key added to `BuilderDocument`
 * cannot travel to a server whose models are all `extra="forbid"` - which is a
 * 422 naming a key the author never typed.
 *
 * The node and edge arrays are passed through by reference. The document is
 * immutable by invariant (`commit` replaces it; dev deep-freezes it), and the
 * result of this function is serialised immediately, so a defensive clone would
 * cost 24 nodes of copying on every keystroke and buy nothing.
 */
export function toWire(doc: BuilderDocument): BuilderDocumentWire {
  return {
    schema: BUILDER_SCHEMA_ID,
    id: doc.id,
    name: doc.name,
    version: doc.version,
    input_field: doc.input_field,
    nodes: doc.nodes,
    edges: doc.edges,
    joins: doc.joins,
    budget: null,
  }
}

/**
 * The wire document with `id` deleted and `version` guaranteed numeric.
 *
 * `version` is coerced rather than trusted because of where the server reads
 * it. `/validate` is the only endpoint taking a version off the raw BODY -
 * `save` has a typed `expected_version` and `publish` a `Query(ge=1)`, both
 * refused by pydantic before their handler runs - so `_requested_version`
 * refuses it by hand, with **422** and the sentence `version must be a whole
 * number; this document carries 'v7'`.
 *
 * The REASON to coerce here is unchanged by which status that is, and it is
 * worth naming because the status has already moved once: until 2026-09-02 the
 * handler was a bare `int(...)`, so a string version raised `ValueError` and
 * came back a **500** that the canvas reads as `unreachable` - a document that
 * mysteriously would not validate, blaming the network. A well-formed 422 is a
 * far better failure, and still one the author never asked for.
 *
 * What comes out is `max(1, trunc(n))`, which is the handler's own
 * `max(FIRST_VERSION, int(...))` written on this side. The floor is not
 * belt-and-braces: `BuilderDocument.version` declares `ge=1`, so 0 is an
 * illegal version that survives today only because this one handler happens to
 * floor it, and `Number(null)` is 0. A client should not send a value the
 * schema refuses and depend on a caller to fix it.
 *
 * `id` is deleted rather than blanked. An empty string is falsy, so `or
 * new_document_id()` would produce the same outcome - but a malformed id, such
 * as one carried over from a draft written by an older build, would not: it
 * reaches `BuilderDocument` and comes back 422 against `BUILDER_DOCUMENT_ID_PATTERN`,
 * complaining about a field the author cannot see and did not choose.
 */
export function forValidate(doc: BuilderDocument): BuilderValidateWire {
  const wire = toWire(doc)
  delete wire.id
  const version = Number(wire.version)
  wire.version = Number.isFinite(version) ? Math.max(1, Math.trunc(version)) : 1
  return wire
}

/**
 * A stable string identifying what a document MEANS, with `position` omitted.
 *
 * Two properties, and the validation loop rests on both. It is invariant under
 * a drag, because position is never compiled and never read at runtime, so
 * moving a card must not spend a round trip or dim the problem list. And it is
 * variant under any edit the compiler would notice, because a fingerprint that
 * missed one is a stale problem list presented as current - the single failure
 * this whole loop exists to avoid.
 *
 * Keys are sorted rather than emitted in insertion order. `prompt_inputs`,
 * `transform.args` and `joins` are author-keyed records, and rebuilding one
 * (a rename, a paste, a round trip through the server) reorders its keys
 * without changing a thing it means.
 *
 * `id` and `version` ARE included. They are server-assigned and the validate
 * endpoint ignores both, so they cannot change a problem list - but the spec
 * omits only `position`, and widening that quietly is how two packages come to
 * disagree about what "the same document" means.
 */
export function fingerprint(doc: BuilderDocument): string {
  return stableStringify({
    schema: BUILDER_SCHEMA_ID,
    id: doc.id,
    name: doc.name,
    version: doc.version,
    input_field: doc.input_field,
    nodes: doc.nodes.map((node) => ({
      id: node.id,
      kind: node.kind,
      label: node.label,
      config: node.config,
    })),
    edges: doc.edges,
    joins: doc.joins,
  })
}

/**
 * How many bytes the document occupies on the wire, for the author's own
 * warning against `bounds.max_document_bytes` (256 KiB).
 *
 * It is an estimate, and it errs in the direction that matters least but is
 * worth naming: the server measures `json.dumps(...).encode("utf-8")` with
 * Python's default `ensure_ascii=True`, which writes a non-ASCII character as a
 * six-byte `\uXXXX` escape where `TextEncoder` writes two or three real UTF-8
 * bytes. So a document whose gate messages are full of em-dashes or CJK counts
 * SMALLER here than it does there. The gap is a warning that fires late, never
 * a save that is refused unexpectedly - the server's own 413 is the bound, and
 * it names both figures.
 */
export function wireBytes(doc: BuilderDocument): number {
  return new TextEncoder().encode(JSON.stringify(toWire(doc))).length
}

/**
 * Every node position rounded to an integer.
 *
 * `Position` declares `int` in `document.py`, and pydantic will coerce `120.0`
 * but not `120.5` - so a drag that ends on a half pixel is a hard 422 on the
 * next save, arriving long after the gesture that caused it. Rounding at the
 * write is the fix; this is the belt for anything that reaches a document by
 * another route, such as a pasted subgraph or a restored draft.
 *
 * The SAME document is returned when every position is already integral. A
 * commit that changes nothing is still an undo step, and an undo that visibly
 * does nothing is worse than no undo at all.
 */
export function roundPositions(doc: BuilderDocument): BuilderDocument {
  let changed = false
  const nodes = doc.nodes.map((node) => {
    const x = Math.round(node.position.x)
    const y = Math.round(node.position.y)
    if (x === node.position.x && y === node.position.y) return node
    changed = true
    return { ...node, position: { x, y } }
  })
  return changed ? { ...doc, nodes } : doc
}

/**
 * JSON with object keys in code-unit order, at every depth.
 *
 * `localeCompare` is deliberately not used: it is locale-dependent, so the same
 * document would fingerprint differently in two browsers and a reconnecting
 * client would re-validate for no reason.
 */
function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value) ?? 'null'
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(',')}]`
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, entry]) => entry !== undefined)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
  const body = entries
    .map(([key, entry]) => `${JSON.stringify(key)}:${stableStringify(entry)}`)
    .join(',')
  return `{${body}}`
}
