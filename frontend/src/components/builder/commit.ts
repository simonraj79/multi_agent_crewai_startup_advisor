import type { BuilderDocument, BuilderNode, NodeId } from '../../types/builder'

/**
 * What an inspector control hands upward when the author changes something.
 *
 * The inspector NEVER writes the document. `useBuilderDocument.commit()` is the
 * only function that assigns to `doc.value` (spec §1.1 invariant 1), and
 * `BuilderView` is the only place an emitted patch becomes a call to it
 * (§2 WP-F). So every form here proposes a WHOLE NEXT DOCUMENT and lets that one
 * caller decide it is a commit.
 *
 * A whole document rather than a field patch, and the reason is atomicity
 * rather than laziness. Three of the things this package has to do are not one
 * field: renaming a node id rewrites edges, joins and every `${state.out__…}`
 * that named it; deleting a router branch deletes the edge that left by it;
 * setting a tier across a multi-selection touches N nodes. Each of those is ONE
 * undo step or it is a bug, and the only shape that makes "one step" structural
 * rather than a convention is handing over one object. R3 chose a snapshot ring
 * over a command algebra for the same reason - the document is capped at
 * 256 KiB, so a fresh object per idle keystroke is cheap and an inversion bug is
 * not available.
 *
 * `coalesceKey` is what keeps a typed word from becoming eleven undo steps:
 * `useBuilderDocument` merges consecutive commits carrying the same key inside
 * 600ms. Text controls send one; selects, steppers and anything structural
 * deliberately do not, because those are single decisions an author expects to
 * be able to step back through one at a time.
 */
export interface InspectorCommit {
  /** The undo label, as `DocumentBar` will print it: `Undid: rename node`. */
  label: string
  /** A NEW document. Never the prop object, never a mutation of it. */
  next: BuilderDocument
  /** `node:<id>:<field>` for a text field; absent for a discrete decision. */
  coalesceKey?: string
}

/** `node:<id>:<field>` - the one spelling, so two controls cannot half-agree. */
export function coalesceKeyFor(id: NodeId, field: string): string {
  return `node:${id}:${field}`
}

/**
 * One node swapped for a new one, as a new document.
 *
 * Identity is preserved for every node that did not change, which is not a
 * micro-optimisation: `NodeIdField` counts what a rename touches by comparing
 * `renameCascade`'s output against its input with `!==`, and `builderGraph`'s
 * rewrites make the same promise. A helper here that rebuilt every node would
 * quietly make that count read "everything".
 */
export function replaceNode(doc: BuilderDocument, node: BuilderNode): BuilderDocument {
  return {
    ...doc,
    nodes: doc.nodes.map((existing) => (existing.id === node.id ? node : existing)),
  }
}

/**
 * A node's config with `patch` folded in, as a new document.
 *
 * The one cast in this package, and it is here so it is nowhere else. `patch` is
 * typed `Partial<N['config']>` at every call site, so the VALUES are checked;
 * what TypeScript cannot see is that spreading a partial of the right config
 * back into `{...node, config}` leaves the union member intact, because
 * `BuilderNode` is discriminated on `kind` - a sibling key the spread does not
 * touch and the checker will not correlate. Widening it to `BuilderNode` here,
 * once, with the generic pinning the call sites, is the smallest place to put
 * that.
 */
export function patchConfig<N extends BuilderNode>(
  doc: BuilderDocument,
  node: N,
  patch: Partial<N['config']>,
): BuilderDocument {
  const next = { ...node, config: { ...node.config, ...patch } } as BuilderNode
  return replaceNode(doc, next)
}

/**
 * How many inbound edges a node has.
 *
 * `joins` is only meaningful at two or more - `join-single-predecessor` is one
 * of the three warnings - so this is what decides whether a fan-in toggle is
 * offered at all, in both `GraphSettings` and the edge inspector.
 */
export function inboundCount(doc: BuilderDocument, id: NodeId): number {
  return doc.edges.reduce((total, edge) => (edge.target === id ? total + 1 : total), 0)
}
