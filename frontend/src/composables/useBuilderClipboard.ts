import { ref, shallowRef } from 'vue'
import { BUILDER_SCHEMA_ID } from '../types/builder'
import type {
  BuilderEdge,
  BuilderJoins,
  BuilderNode,
  EdgeId,
  NodeId,
  NodePosition,
} from '../types/builder'
import { remapIds } from '../utils/builderGraph'
import type { BuilderSubgraph } from '../utils/builderGraph'
import { mintNodeId } from '../data/builderDefaults'
import { mintEdgeId } from './useBuilderDocument'
import type { BuilderDocumentStore } from './useBuilderDocument'

/**
 * Copy, cut, paste and duplicate, across tabs and across workflows.
 *
 * The system clipboard rather than an in-memory ref, because the thing an
 * author actually wants is to copy a working fan-out out of one graph and into
 * another - which means a second tab, a second document, and a payload that has
 * to survive leaving this JavaScript context entirely. An in-memory ref cannot
 * do that; it is the FALLBACK, for a browser or a permission state that refuses
 * the real one.
 *
 * THE HARD PART IS THAT IDS ARE ALSO DATA. A node id is not only an identity:
 * the compiler derives `out__<id>` from it and an author writes that key by
 * hand, in prose, inside values the schema takes as plain strings. Re-minting
 * the ids of a pasted fragment without moving those references produces a
 * fragment whose nodes talk to the ORIGINALS - or, if the original is not in
 * this document, to nothing at all. `remapIds` in `utils/builderGraph.ts` is
 * the one implementation of that rewrite and this file calls it rather than
 * writing a second one; its docblock carries the measurement of what each half
 * fails like, and the `turns__` half fails silently.
 *
 * Two rules follow the fragment out of the document and are `remapIds`'s, not
 * this file's: an edge survives only when BOTH endpoints were copied, and a
 * `joins` key survives only when its node was. Pasting three nodes out of a
 * five-node selection must not hand the author two `edge-unknown-endpoint`
 * errors they did not make.
 */

/**
 * The clipboard envelope, tagged so a paste can tell a builder fragment from
 * whatever else is on the system clipboard.
 *
 * `__builder` carries the SCHEMA ID rather than a bare marker, so a fragment
 * copied by a future build under `builder.flow/v2` is refused by this one
 * instead of being pasted as a shape neither side agrees about. That is the
 * same reasoning `StoredDraft.v` uses, one layer out.
 */
export interface ClipboardEnvelope {
  __builder: typeof BUILDER_SCHEMA_ID
  nodes: BuilderNode[]
  edges: BuilderEdge[]
  joins: BuilderJoins
  /** The fragment's own bounding box, so a paste can land its top-left at the cursor. */
  bbox: { x: number; y: number; width: number; height: number }
}

/** Spec §4.4: `⌘D` offsets +24/+24. Also where a paste lands when no cursor position is given. */
const DUPLICATE_OFFSET = 24

/** The one sentence a refused or absent system clipboard gets. Never nothing. */
const IN_TAB_ONLY =
  'Copied inside this tab only — the browser did not allow clipboard access, ' +
  'so this will not paste into another window.'

export function useBuilderClipboard(document: BuilderDocumentStore) {
  /**
   * The fallback copy, and the reason a denied clipboard is an inconvenience
   * rather than a dead command.
   *
   * `navigator.clipboard` is permission-gated, absent over plain HTTP, and
   * absent in a headless test environment. All three are states an author can
   * be in through no fault of their own, and in all three copy-and-paste inside
   * this tab still works because of this ref.
   */
  const held = shallowRef<ClipboardEnvelope | null>(null)
  /**
   * One line of what just happened, or `''`.
   *
   * Never left empty after a refusal. A copy that silently does nothing is
   * indistinguishable from a copy that worked, and the author finds out at
   * paste time - by which point they have lost the selection they made.
   */
  const notice = ref('')

  /**
   * Build the envelope for a set of node ids.
   *
   * Edges are selected here rather than passed in, because "both endpoints
   * copied" is a fact about the SELECTION and not about what the canvas had
   * highlighted: an author who marquees three nodes has selected the edges
   * between them whether or not the marquee touched the curves.
   */
  function envelopeFor(ids: Iterable<NodeId>): ClipboardEnvelope | null {
    const wanted = new Set<string>(ids)
    const doc = document.doc.value
    const nodes = doc.nodes.filter((node) => wanted.has(node.id))
    if (nodes.length === 0) return null

    const edges = doc.edges.filter(
      (edge) => wanted.has(edge.source) && wanted.has(edge.target),
    )
    const joins: BuilderJoins = {}
    for (const key of Object.keys(doc.joins)) {
      if (wanted.has(key)) joins[key] = doc.joins[key]
    }
    return { __builder: BUILDER_SCHEMA_ID, nodes, edges, joins, bbox: boundingBox(nodes) }
  }

  /**
   * Put a fragment on the system clipboard, and always in the ref as well.
   *
   * Both, not either. The write is asynchronous and can be refused after the
   * fact, so a copy that only reached `navigator.clipboard` would be a copy the
   * author cannot paste and cannot know they cannot paste until they try.
   */
  async function publish(envelope: ClipboardEnvelope): Promise<void> {
    held.value = envelope
    notice.value = ''
    // An ABSENT `navigator.clipboard` is checked separately from a rejected
    // write, because optional chaining would swallow it: `navigator.clipboard?.
    // writeText(...)` resolves to `undefined` with nothing thrown, and the copy
    // would report success having reached nothing outside this tab. The API is
    // absent over plain HTTP and in every headless runner, so this is the
    // common case rather than the exotic one.
    const clipboard = navigator.clipboard
    if (!clipboard) {
      notice.value = IN_TAB_ONLY
      return
    }
    try {
      await clipboard.writeText(JSON.stringify(envelope))
    } catch {
      notice.value = IN_TAB_ONLY
    }
  }

  async function copy(ids: Iterable<NodeId>): Promise<void> {
    const envelope = envelopeFor(ids)
    if (!envelope) {
      notice.value = 'Nothing selected to copy.'
      return
    }
    await publish(envelope)
  }

  /**
   * Copy, then delete, as one deletion the author can undo.
   *
   * The copy happens first and the delete only follows a successful envelope,
   * so a cut can never be a delete that lost the payload.
   */
  async function cut(ids: Iterable<NodeId>): Promise<void> {
    const envelope = envelopeFor(ids)
    if (!envelope) {
      notice.value = 'Nothing selected to cut.'
      return
    }
    await publish(envelope)
    document.deleteSelection(
      envelope.nodes.map((node) => node.id),
      [],
      envelope.nodes.length === 1 ? 'Cut node' : `Cut ${envelope.nodes.length} nodes`,
    )
  }

  /**
   * Read whatever is on the system clipboard, falling back to the held copy.
   *
   * The system clipboard is read FIRST even when a held copy exists, because
   * the author may have copied in another tab since - and the tab they last
   * copied in is the one they expect to paste from.
   */
  async function readEnvelope(): Promise<ClipboardEnvelope | null> {
    try {
      const text = await navigator.clipboard?.readText()
      const parsed = parseEnvelope(text ?? '')
      if (parsed) return parsed
    } catch {
      // Denied or unavailable. Not a failure yet - the held copy may serve.
    }
    return held.value
  }

  /**
   * Paste a fragment at `at`, as ONE commit.
   *
   * `at` is a flow-space position the CALLER has already snapped to the canvas
   * grid: the 20px grid is `BuilderCanvas`'s constant (R12) and reading it from
   * here would be a second copy of it. What this owns is the integer rounding,
   * which is not cosmetic - `Position` declares `int` in `document.py`, so a
   * half-pixel paste is a hard 422 on a save that happens minutes later.
   *
   * Returns the ids of what landed, so the canvas can make them the selection.
   */
  async function paste(at?: NodePosition): Promise<NodeId[]> {
    const envelope = await readEnvelope()
    if (!envelope) {
      notice.value = 'Nothing on the clipboard to paste.'
      return []
    }
    return place(envelope, at, 'Paste')
  }

  /**
   * `⌘D`. The selection copied +24/+24, without touching the system clipboard.
   *
   * Deliberately not "copy then paste": duplicating must not destroy whatever
   * the author had copied earlier, which is a thing they are entitled to still
   * have after pressing a key that says nothing about the clipboard.
   */
  function duplicate(ids: Iterable<NodeId>): NodeId[] {
    const envelope = envelopeFor(ids)
    if (!envelope) {
      notice.value = 'Nothing selected to duplicate.'
      return []
    }
    return place(
      envelope,
      { x: envelope.bbox.x + DUPLICATE_OFFSET, y: envelope.bbox.y + DUPLICATE_OFFSET },
      'Duplicate',
    )
  }

  /**
   * Re-mint, re-position, and commit.
   *
   * The minter is closed over `taken`, which starts as the destination's ids
   * and GROWS as the paste proceeds. Minting against a snapshot instead would
   * let two nodes in one fragment claim the same free id - the commonest case
   * being a fragment whose nodes carry the same label, which is exactly what a
   * previous paste produces.
   */
  function place(
    envelope: ClipboardEnvelope,
    at: NodePosition | undefined,
    verb: string,
  ): NodeId[] {
    const doc = document.doc.value
    const takenNodes = new Set<string>(doc.nodes.map((node) => node.id as string))
    const takenEdges = new Set<string>(doc.edges.map((edge) => edge.id as string))
    const labels = new Map<string, string>()
    for (const node of envelope.nodes) labels.set(node.id, node.label)

    const subgraph: BuilderSubgraph = {
      nodes: envelope.nodes,
      edges: envelope.edges,
      joins: envelope.joins,
    }
    const remapped = remapIds(subgraph, {
      node(previous: NodeId): NodeId {
        const minted = mintNodeId(labels.get(previous) ?? previous, takenNodes)
        takenNodes.add(minted)
        return minted
      },
      edge(): EdgeId {
        const minted = mintEdgeId(takenEdges)
        takenEdges.add(minted)
        return minted
      },
    })

    const target = at ?? {
      x: envelope.bbox.x + DUPLICATE_OFFSET,
      y: envelope.bbox.y + DUPLICATE_OFFSET,
    }
    const dx = Math.round(target.x) - envelope.bbox.x
    const dy = Math.round(target.y) - envelope.bbox.y
    const nodes = remapped.nodes.map((node) => ({
      ...node,
      position: { x: Math.round(node.position.x + dx), y: Math.round(node.position.y + dy) },
    }))

    const count = nodes.length
    document.pasteSubgraph(
      { nodes, edges: remapped.edges, joins: remapped.joins },
      `${verb} ${count} ${count === 1 ? 'node' : 'nodes'}`,
    )
    notice.value = ''
    return nodes.map((node) => node.id)
  }

  return { copy, cut, paste, duplicate, notice, held }
}

/** The fragment's own top-left and extent, in flow units. Empty is `0,0,0,0`. */
function boundingBox(nodes: readonly BuilderNode[]): ClipboardEnvelope['bbox'] {
  if (nodes.length === 0) return { x: 0, y: 0, width: 0, height: 0 }
  const xs = nodes.map((node) => node.position.x)
  const ys = nodes.map((node) => node.position.y)
  const x = Math.min(...xs)
  const y = Math.min(...ys)
  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y }
}

/**
 * A clipboard string turned back into an envelope, or null.
 *
 * Every check is a way the system clipboard is NOT a builder fragment: it holds
 * a URL, a paragraph, a screenshot, or a fragment from a build that spelled the
 * schema differently. A paste that guessed would produce a document the server
 * refuses with a message about a field nobody typed, so the honest answer to
 * anything unrecognised is to say there is nothing to paste.
 *
 * The node and edge arrays are asserted rather than element-checked. `remapIds`
 * is about to walk every one of them and the document is validated on the next
 * keystroke; re-implementing `document.py` here would be a third opinion about
 * a shape two others already own.
 */
export function parseEnvelope(text: string): ClipboardEnvelope | null {
  if (!text.trim().startsWith('{')) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return null
  }
  if (parsed === null || typeof parsed !== 'object') return null
  const envelope = parsed as Partial<ClipboardEnvelope>
  if (envelope.__builder !== BUILDER_SCHEMA_ID) return null
  if (!Array.isArray(envelope.nodes) || envelope.nodes.length === 0) return null
  if (!Array.isArray(envelope.edges)) return null
  const joins =
    envelope.joins !== null && typeof envelope.joins === 'object' && !Array.isArray(envelope.joins)
      ? envelope.joins
      : {}
  return {
    __builder: BUILDER_SCHEMA_ID,
    nodes: envelope.nodes,
    edges: envelope.edges,
    joins,
    bbox: envelope.bbox ?? boundingBox(envelope.nodes),
  }
}
