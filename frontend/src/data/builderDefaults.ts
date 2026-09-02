import { nodeId } from '../types/builder'
import type { BuilderNode, NodeId, NodeKind, NodePosition } from '../types/builder'
import { vocabulary } from './builderVocabulary'
import { NODE_KINDS } from './nodeKinds'

/**
 * What a node is born as.
 *
 * One rule governs everything here: **a node arrives schema-valid**. Not
 * nearly-valid, not valid-once-you-fill-two-boxes - a fresh node must survive
 * `BuilderDocument.model_validate` on the very next save, or dragging a tile
 * produces a 422 about a field the author has never seen. That is why a router
 * is born with two branches (`router-branch-count` and `router-otherwise` are
 * satisfied on arrival), why a gate is born with a real sentence in `message`,
 * and why an input node's `field` is its own id rather than a shared word that
 * would make the second one `input-field-ambiguous`.
 *
 * The DEFAULTS themselves live in `nodeKinds.ts`, one per kind, beside the ports
 * and the icon - kind is one fact and it has one home. This file owns identity:
 * which id, which label, and how a slugified rename finds a free one.
 *
 * Every number those defaults use is the Python's own
 * (`builder/document.py` and `config.py`), and `tests/builderDefaults.spec.ts`
 * reads both files at run time and asserts the key set of each produced config
 * equals the pydantic model's field set. A default that drifts is a failing test
 * rather than a save the author cannot explain.
 */

/**
 * `config.py:BUILDER_MAX_ID_CHARS`, the ceiling in `BUILDER_ID_PATTERN`'s own
 * `{0,39}` (one leading letter plus 39).
 *
 * Not cosmetic: a node compiles to the flow method ident `n{index}_{node_id}`,
 * and `MAX_IDENTIFIER_LENGTH` in `events/models.py` TRUNCATES silently rather
 * than raising - a truncation there merges two nodes into one in every frame the
 * run emits.
 */
export const MAX_NODE_ID_CHARS = 40

/** What a slug falls back to when a label carries no usable character at all. */
const FALLBACK_SLUG = 'node'

/**
 * A fresh node of `kind`, at `position`, with an id no existing node holds.
 *
 * `position` is rounded here as well as at every other write (R12). `Position`
 * declares `int` in `document.py`, and pydantic coerces `120.0` but not `120.5`
 * - so an unrounded drop is a hard 422 arriving on a later save, long after the
 * gesture that caused it.
 *
 * THROWS when the vocabulary has not loaded. Three of the seven kinds have
 * REQUIRED fields whose legal values only the server knows (`agent_id`,
 * `crew_id`, `body_key`), and inventing them is cut list item 17: a hardcoded
 * fallback is how a client starts drawing graphs the compiler rejects. Every
 * creation path - the palette, the number keys, `PortMenu`, paste - is disabled
 * while `vocabularyUnavailable`, so reaching this is a caller's bug rather than
 * a state an author can produce, and it should read like one.
 */
export function newNode(
  kind: NodeKind,
  position: NodePosition,
  existingIds: Iterable<string>,
): BuilderNode {
  const served = vocabulary.value
  if (!served) {
    throw new Error(
      'newNode() needs the builder vocabulary, which has not loaded; the palette is ' +
        'disabled until it does, so this is a caller that skipped the gate.',
    )
  }

  const taken = new Set(existingIds)
  const meta = NODE_KINDS[kind]
  // The first free suffix rather than a count, so deleting `agent_2` and adding
  // a node reuses the gap. A monotonic counter would drift with every delete and
  // an author would be looking at `agent_9` in a graph with three agents.
  let suffix = 1
  while (taken.has(`${kind}_${suffix}`)) suffix += 1
  const id = nodeId(`${kind}_${suffix}`)
  const label = `${meta.defaultLabel} ${suffix}`
  const base = { id, label, position: { x: Math.round(position.x), y: Math.round(position.y) } }

  /*
   * An exhaustive switch rather than one generic call, and the verbosity buys
   * the thing the union exists for: `BuilderNode` is discriminated on `kind`, so
   * only a per-case construction proves that an `agent` node carries an
   * `AgentConfig`. An eighth kind is then a compile error here - the same
   * argument `InspectorRail`'s `Record<NodeKind, Component>` makes - rather than
   * a node with the wrong config shape that fails at the server.
   */
  switch (kind) {
    case 'input':
      return { ...base, kind, config: NODE_KINDS.input.defaultConfig(served, id) }
    case 'agent':
      return { ...base, kind, config: NODE_KINDS.agent.defaultConfig(served, id) }
    case 'crew':
      return { ...base, kind, config: NODE_KINDS.crew.defaultConfig(served, id) }
    case 'gate':
      return { ...base, kind, config: NODE_KINDS.gate.defaultConfig(served, id) }
    case 'router':
      return { ...base, kind, config: NODE_KINDS.router.defaultConfig(served, id) }
    case 'transform':
      return { ...base, kind, config: NODE_KINDS.transform.defaultConfig(served, id) }
    case 'output':
      return { ...base, kind, config: NODE_KINDS.output.defaultConfig(served, id) }
  }
}

/**
 * A node id derived from a label, guaranteed legal and guaranteed free.
 *
 * This is the rename path and the paste path, not the create path - `newNode`
 * mints `agent_1` from the kind, because a node created by dragging a tile has
 * no label yet worth slugifying. What both share is that the id they produce is
 * a `BUILDER_ID_PATTERN` match by construction: the pattern is a server PARSE
 * refusal, so an id that misses it is a 422 rather than a Problem, and a 422 is
 * a refusal the author cannot act on from the canvas.
 *
 * The disambiguating suffix starts at 2, so "Scoper" beside an existing `scoper`
 * becomes `scoper_2` and the first one keeps the name it already had. Renaming
 * the ORIGINAL is what `renameCascade` is for.
 */
export function mintNodeId(label: string, taken: ReadonlySet<string>): NodeId {
  const base = slugify(label)
  if (!taken.has(base)) return nodeId(base)
  for (let suffix = 2; ; suffix += 1) {
    // The base is trimmed to leave room for the suffix rather than the suffix
    // being dropped when the id gets long: a truncated id that collides again is
    // an infinite loop, and a 41-character id is a 422.
    const tail = `_${suffix}`
    const candidate = `${trimSlug(base, MAX_NODE_ID_CHARS - tail.length)}${tail}`
    if (!taken.has(candidate)) return nodeId(candidate)
  }
}

/**
 * A label reduced to `^[a-z][a-z0-9_]{0,39}$`.
 *
 * Every step is a way a real label breaks the pattern rather than a general
 * slugifier: labels are title-cased ("Market Analyst"), carry punctuation an
 * identifier cannot ("Scope - v2"), and are freely allowed to start with a digit
 * or an emoji, none of which the pattern's leading `[a-z]` accepts. A label made
 * entirely of characters the pattern refuses - "🙂", "2024" - has nothing left
 * to slugify, which is what `FALLBACK_SLUG` is for; `mintNodeId` then numbers it.
 */
function slugify(label: string): string {
  const slug = trimSlug(
    label
      .toLowerCase()
      .replace(/[^a-z0-9_]+/g, '_')
      .replace(/^[^a-z]+/, '')
      .replace(/_{2,}/g, '_'),
    MAX_NODE_ID_CHARS,
  )
  return slug || FALLBACK_SLUG
}

/** Cut to `limit` characters without leaving the trailing underscore behind. */
function trimSlug(slug: string, limit: number): string {
  return slug.slice(0, limit).replace(/_+$/, '')
}
