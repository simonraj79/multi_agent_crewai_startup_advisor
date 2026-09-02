import { STATE_OUTPUT_PREFIX } from '../types/builder'
import type {
  BuilderDocument,
  BuilderEdge,
  BuilderJoins,
  BuilderNode,
  BuilderNodeConfig,
  EdgeId,
  NodeId,
} from '../types/builder'

/**
 * Pure graph questions about a builder document, and the one rewrite that has
 * to answer all of them at once.
 *
 * Nothing here computes a Problem. `bounds.py` counts nodes, branches, cycles
 * and dollars and reports them; a client-side recount is a second opinion that
 * silently disagrees with the compiler the first time the server changes
 * (spec R6). What these functions produce is either a PRESENTATION fact - which
 * cards to rim during a connect drag, which edge to dash - or a rewrite the
 * author asked for and the server would otherwise never see was incomplete.
 *
 * `backEdges` is the one deliberate mirror of server logic, and R7 is explicit
 * about the terms: it exists so a cycle is LEGIBLE, it styles and nothing else,
 * and it is pinned by a Python-generated fixture because a hand-maintained
 * mirror rots. Every other function here answers a question the server has no
 * opinion about.
 *
 * THE HARD PART IS `renameCascade`, and it is hard for a reason that is not
 * obvious from the schema. A node id is not only an identity; the compiler
 * DERIVES state keys from it - `out__<id>` for what the node returned, and
 * `turns__<id>` for a gate's turn counter - and an author writes those keys by
 * hand, in prose, inside values the schema is happy to accept as plain strings.
 * Rename the node and miss one, and the reference is still perfectly valid
 * text.
 *
 * The two halves fail in opposite ways, and both were measured against the real
 * compiler rather than reasoned about. A dangling `out__` fails LOUDLY:
 * `compiler.py::_referenced_state_keys` refuses the publish naming the id no
 * node has. A dangling `turns__` does not fail at all - the existence check
 * reads `if referenced.startswith(BUILDER_STATE_OUTPUT_PREFIX)`
 * (compiler.py:732), so the same document compiles clean, `validate_document`
 * returns zero problems, and `route_branch` then reads `state.get("turns__old")`
 * (runtime.py:819), gets None because nothing ever seeded that key, never
 * matches, and falls to `otherwise` on every pass for the life of the workflow.
 * No exception, no warning, no frame. That is the failure this file is written
 * against.
 */

/**
 * `runtime.py:BUILDER_STATE_TURNS_PREFIX` (and `gates.py:_TURNS_PREFIX`, which
 * is the same literal declared a second time on that side).
 *
 * Restated here rather than imported from `types/builder.ts` because that file
 * mirrors the WIRE and this key never appears on it: it is compiled, not
 * authored. `tests/builderGraph.spec.ts` reads the Python and asserts the two
 * agree, the `serverLimits.ts` idiom - a duplicated constant that drifts should
 * be a failing test, not a router that stops routing.
 */
export const STATE_TURNS_PREFIX = 'turns__'

/** A copied fragment of a document: what the clipboard carries, minus its own chrome. */
export interface BuilderSubgraph {
  nodes: readonly BuilderNode[]
  edges: readonly BuilderEdge[]
  joins: BuilderJoins
}

/**
 * Where a pasted fragment's new ids come from.
 *
 * The caller mints, not this module, because uniqueness is a property of the
 * DESTINATION document and of every id minted earlier in the same paste -
 * neither of which a fragment knows. Two methods rather than one because node
 * ids and edge ids are separate namespaces that only happen to share a shape.
 */
export interface SubgraphMinter {
  node(previous: NodeId): NodeId
  edge(previous: EdgeId): EdgeId
}

/* --- reachability -------------------------------------------------------- */

function forwardEdges(doc: BuilderDocument): Map<string, string[]> {
  const known = new Set(doc.nodes.map((node) => node.id as string))
  const out = new Map<string, string[]>()
  for (const edge of doc.edges) {
    if (!known.has(edge.source) || !known.has(edge.target)) continue
    const list = out.get(edge.source)
    if (list) list.push(edge.target)
    else out.set(edge.source, [edge.target])
  }
  return out
}

function reversed(forward: Map<string, string[]>): Map<string, string[]> {
  const back = new Map<string, string[]>()
  for (const [source, targets] of forward) {
    for (const target of targets) {
      const list = back.get(target)
      if (list) list.push(source)
      else back.set(target, [source])
    }
  }
  return back
}

/**
 * Everything reachable from `start` over `adjacency`, EXCLUDING `start` itself
 * unless a path of one or more edges leads back to it.
 *
 * The exclusion is what makes the result honest on a cyclic graph: a node is in
 * its own ancestor set exactly when it sits on a cycle, which is a fact worth
 * seeing rather than an artefact of how the walk was seeded. `bounds._reachable`
 * is inclusive of its starts because it answers a different question - which
 * nodes an input can ever run - and erring the other way there would report a
 * live node unreachable.
 */
function walk(start: string, adjacency: Map<string, string[]>): Set<NodeId> {
  const seen = new Set<NodeId>()
  const queue = [...(adjacency.get(start) ?? [])]
  while (queue.length) {
    const next = queue.pop() as NodeId
    if (seen.has(next)) continue
    seen.add(next)
    queue.push(...(adjacency.get(next) ?? []))
  }
  return seen
}

/**
 * Every node from which `id` can be reached by one or more edges.
 *
 * This is the loop advisory's whole input (spec §4.2): drawing an edge from
 * `source` to any member of `ancestorsOf(doc, source)` closes a loop, so the
 * canvas rims them during a connect drag. It never REFUSES the connection -
 * `back-edge-not-router` is the server's to report, and a client that refused
 * it would be enforcing a rule it does not own.
 *
 * A self-edge is the one loop this set does not describe: `source -> source`
 * closes a cycle through no intermediate node at all, so a caller wanting every
 * loop-closing target unions `{source}` in. Folding it in here would instead
 * claim a node is its own ancestor on an acyclic graph, which is false.
 */
export function ancestorsOf(doc: BuilderDocument, id: NodeId): Set<NodeId> {
  return walk(id, reversed(forwardEdges(doc)))
}

/** Every node reachable FROM `id` by one or more edges. The mirror of `ancestorsOf`. */
export function descendantsOf(doc: BuilderDocument, id: NodeId): Set<NodeId> {
  return walk(id, forwardEdges(doc))
}

/* --- ordering ------------------------------------------------------------ */

/**
 * The nodes in an order where every node follows the ones that feed it.
 *
 * Back edges are removed first and then it is Kahn's algorithm, which is
 * `bounds.billable_depths` written on this side - and the reason it terminates
 * on a graph with cycles rather than hanging. Removing a depth-first search's
 * back edges always leaves a DAG, so this is a TOTAL order over every node, not
 * a partial one that silently drops whatever it could not sort.
 *
 * Ties break in document order and the queue is FIFO, both mirroring the Python
 * (`queue.pop(0)`, seeded from `document.nodes`). Two clients rendering the
 * same document must not disagree about what "first" means.
 *
 * The trailing sweep should never find anything. It is there because the
 * alternative to a defensive append is a node that vanishes from a list the
 * canvas is about to render, and a wrong order is a far cheaper failure than a
 * missing node.
 */
export function topoOrder(doc: BuilderDocument): NodeId[] {
  const loops = new Set(backEdges(doc))
  const known = new Set(doc.nodes.map((node) => node.id as string))
  const outgoing = new Map<string, string[]>()
  const indegree = new Map<string, number>()
  for (const node of doc.nodes) indegree.set(node.id, 0)

  doc.edges.forEach((edge, position) => {
    if (loops.has(position) || !known.has(edge.source) || !known.has(edge.target)) return
    const list = outgoing.get(edge.source)
    if (list) list.push(edge.target)
    else outgoing.set(edge.source, [edge.target])
    indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1)
  })

  const queue: NodeId[] = doc.nodes
    .filter((node) => indegree.get(node.id) === 0)
    .map((node) => node.id)
  const ordered: NodeId[] = []
  const placed = new Set<string>()
  while (queue.length) {
    const current = queue.shift() as NodeId
    ordered.push(current)
    placed.add(current)
    for (const target of outgoing.get(current) ?? []) {
      const remaining = (indegree.get(target) ?? 0) - 1
      indegree.set(target, remaining)
      if (remaining === 0) queue.push(target as NodeId)
    }
  }
  for (const node of doc.nodes) if (!placed.has(node.id)) ordered.push(node.id)
  return ordered
}

/**
 * The POSITIONS in `doc.edges` of the edges that close a loop.
 *
 * A line-for-line mirror of `bounds._back_edges_with_index`, and it exists for
 * ONE reason: STYLING (R7). A back edge is drawn dashed and curved back on
 * itself so a cycle is legible on the canvas. Nothing here gates an
 * interaction, nothing here produces a Problem, and `back-edge-not-router`
 * stays entirely the server's to report.
 *
 * Positions rather than edges, because that is the Python's own unit and its
 * reason is exact: two parallel edges between the same pair are equal as values
 * and only their position tells them apart.
 *
 * A mirror rots unless something checks it, which is why R7 pairs this with a
 * fixture emitted by the real `bounds.back_edge_indices` over order-permuted
 * documents and byte-compared by a Python test in CI. This function takes a
 * plain document and returns plain numbers precisely so that fixture can drive
 * it with no adapter in between.
 *
 * Three details are the difference between a mirror and a lookalike. The roots
 * are the INPUT nodes first and then every node, so the numbering matches the
 * order the graph actually runs and a detached cycle is still counted. An edge
 * to an id no node has is skipped rather than descended into. And each stack
 * frame keeps its own cursor, because Python's `for ... in pending` over a
 * stored iterator resumes where it left off after the `break`.
 */
export function backEdges(doc: BuilderDocument): number[] {
  const outgoing = new Map<string, Array<[number, BuilderEdge]>>()
  doc.edges.forEach((edge, position) => {
    const list = outgoing.get(edge.source)
    if (list) list.push([position, edge])
    else outgoing.set(edge.source, [[position, edge]])
  })
  const known = new Set(doc.nodes.map((node) => node.id as string))
  const roots = [
    ...doc.nodes.filter((node) => node.kind === 'input').map((node) => node.id as string),
    ...doc.nodes.map((node) => node.id as string),
  ]

  // 1 = on the search stack, 2 = finished. Absent = never seen.
  const state = new Map<string, 1 | 2>()
  const found: number[] = []
  for (const root of roots) {
    if (state.has(root)) continue
    state.set(root, 1)
    const stack: Array<{ id: string; edges: Array<[number, BuilderEdge]>; cursor: number }> = [
      { id: root, edges: outgoing.get(root) ?? [], cursor: 0 },
    ]
    while (stack.length) {
      const frame = stack[stack.length - 1]
      let descended = false
      while (frame.cursor < frame.edges.length) {
        const [position, edge] = frame.edges[frame.cursor]
        frame.cursor += 1
        if (!known.has(edge.target)) continue
        const target = state.get(edge.target)
        if (target === 1) {
          found.push(position)
        } else if (target === undefined) {
          state.set(edge.target, 1)
          stack.push({ id: edge.target, edges: outgoing.get(edge.target) ?? [], cursor: 0 })
          descended = true
          break
        }
      }
      if (!descended) {
        state.set(frame.id, 2)
        stack.pop()
      }
    }
  }
  return found
}

/* --- renaming and re-minting --------------------------------------------- */

/** One `${state.…}` token to swap, wherever a string carries it. */
interface TokenSwap {
  readonly find: string
  readonly replace: string
}

/**
 * The token and bare-key swaps a set of renames implies.
 *
 * `out__<id>` follows every kind, because every node writes its return there.
 * `turns__<id>` follows only a GATE, because only a gate has a turn counter -
 * and being precise costs one conditional and buys the guarantee that this
 * never rewrites an author's own state key that merely happens to be spelled
 * like a derived one.
 */
function swapsFor(
  nodes: readonly BuilderNode[],
  rename: ReadonlyMap<string, NodeId>,
): { tokens: TokenSwap[]; keys: Map<string, string> } {
  const tokens: TokenSwap[] = []
  const keys = new Map<string, string>()
  for (const node of nodes) {
    const to = rename.get(node.id)
    if (to === undefined || to === node.id) continue
    const prefixes =
      node.kind === 'gate' ? [STATE_OUTPUT_PREFIX, STATE_TURNS_PREFIX] : [STATE_OUTPUT_PREFIX]
    for (const prefix of prefixes) {
      const before = `${prefix}${node.id}`
      const after = `${prefix}${to}`
      keys.set(before, after)
      tokens.push({ find: '${state.' + before + '}', replace: '${state.' + after + '}' })
    }
  }
  return { tokens, keys }
}

/**
 * Every string leaf of `value`, with each token swapped wherever it appears.
 *
 * A whole-config walk rather than a list of known reference sites, because the
 * compiler's own scan is a whole-config walk: `_referenced_state_keys` flattens
 * EVERY leaf of every node config and matches with an UNANCHORED regex
 * (`compiler.py:763-771`), so a `${state.out__x}` embedded mid-sentence in a
 * gate message is a reference as far as the compiler is concerned, and a
 * dangling one refuses the publish. Enumerating only the four sites the schema
 * type-checks would have left that message behind - and a gate message is
 * exactly where an author writes "here is what the analyst said:
 * ${state.out__market}".
 *
 * The token carries its closing brace, so swapping `${state.out__foo}` can
 * never touch `${state.out__foo_bar}`.
 *
 * The SAME reference comes back when nothing matched, at every depth. The
 * document is immutable by invariant, and a rename that reallocated every
 * untouched config would make an identity comparison useless to everything
 * downstream that wants to know what actually changed.
 */
function rewriteStrings(value: unknown, tokens: readonly TokenSwap[]): unknown {
  if (typeof value === 'string') {
    let next = value
    for (const token of tokens) {
      if (next.includes(token.find)) next = next.split(token.find).join(token.replace)
    }
    return next === value ? value : next
  }
  if (Array.isArray(value)) {
    let changed = false
    const items = value.map((item) => {
      const rewritten = rewriteStrings(item, tokens)
      if (rewritten !== item) changed = true
      return rewritten
    })
    return changed ? items : value
  }
  if (value !== null && typeof value === 'object') {
    let changed = false
    const entries = Object.entries(value as Record<string, unknown>).map(([key, item]) => {
      const rewritten = rewriteStrings(item, tokens)
      if (rewritten !== item) changed = true
      return [key, rewritten] as const
    })
    return changed ? Object.fromEntries(entries) : value
  }
  return value
}

/**
 * One node with its id, its router branch keys and its state references moved.
 *
 * A router's `key` is the one place a derived state key is written BARE rather
 * than inside `${state.…}` - `compiler.py:565` passes `branch.key` straight
 * into the compiled `with:` block as the key `route_branch` reads. So it is
 * swapped by whole-string equality, before the token pass, and it is the reason
 * this cannot be a pure string walk.
 *
 * The swapped key is asserted rather than minted. `RouterBranch.key` is typed
 * `NodeId`, and `out__` costs five of a node id's forty characters, so renaming
 * a node to a 36-character id yields a key the id pattern refuses - a 422 on
 * the next save. Running it through `nodeId()` here would turn that into a
 * thrown exception in the middle of a rename the author is still typing, losing
 * the document to save them a refusal they were going to be shown anyway.
 */
function rewriteNode(
  node: BuilderNode,
  rename: ReadonlyMap<string, NodeId>,
  tokens: readonly TokenSwap[],
  keys: ReadonlyMap<string, string>,
): BuilderNode {
  let config: BuilderNodeConfig = node.config
  if (node.kind === 'router') {
    let changed = false
    const branches = node.config.branches.map((branch) => {
      const swapped = branch.key === null ? undefined : keys.get(branch.key)
      if (swapped === undefined) return branch
      changed = true
      return { ...branch, key: swapped as NodeId }
    })
    if (changed) config = { branches }
  }
  const rewritten = rewriteStrings(config, tokens) as BuilderNodeConfig
  const id = rename.get(node.id) ?? node.id
  if (rewritten === node.config && id === node.id) return node
  return { ...node, id, config: rewritten } as BuilderNode
}

function rewriteJoins(joins: BuilderJoins, rename: ReadonlyMap<string, NodeId>): BuilderJoins {
  const declared = Object.keys(joins)
  if (!declared.some((key) => rename.has(key))) return joins
  const next: BuilderJoins = {}
  for (const key of declared) next[rename.get(key) ?? key] = joins[key]
  return next
}

/**
 * A node id changed everywhere it is written, as ONE new document.
 *
 * One document and one pass, because this is one commit: `NodeIdField` runs it
 * on blur and the author gets one undo back to the name they had. Five places
 * carry the id and all five move together - the node itself, both endpoints of
 * every incident edge, the `joins` key that declares it a fan-in, its
 * `${state.out__…}` and (for a gate) `${state.turns__…}` references anywhere in
 * any config, and a router branch `key` that reads either derived key bare.
 *
 * `input_field` is NOT one of them, and this is the one place this file departs
 * from the manifest's sentence in §2. `bounds.py:668-671` matches
 * `document.input_field` against each input node's `config.field`, never
 * against a node id; they are different namespaces, and the compiler even
 * forbids a field spelled with a derived prefix (`_checked_field`). So on the
 * only document where such a rewrite could fire - one whose `input_field`
 * happens to equal the renamed node's id - moving `input_field` alone leaves it
 * declared by no input node and INTRODUCES an `input-field-undeclared` error
 * into a document that was valid before the rename. Leaving both alone cannot.
 * A client rewrite that can only make a valid document invalid is not a
 * rewrite.
 *
 * Nothing is refused here. A `to` that is already taken is a
 * `duplicate-node-id`, which the server reports and the widget prevents; this
 * function is not a third opinion about it.
 */
export function renameCascade(doc: BuilderDocument, from: NodeId, to: NodeId): BuilderDocument {
  if (from === to) return doc
  const rename = new Map<string, NodeId>([[from, to]])
  const { tokens, keys } = swapsFor(doc.nodes, rename)
  return {
    ...doc,
    nodes: doc.nodes.map((node) => rewriteNode(node, rename, tokens, keys)),
    edges: doc.edges.map((edge) => {
      const source = rename.get(edge.source) ?? edge.source
      const target = rename.get(edge.target) ?? edge.target
      return source === edge.source && target === edge.target ? edge : { ...edge, source, target }
    }),
    joins: rewriteJoins(doc.joins, rename),
  }
}

/**
 * A copied fragment with every id re-minted and every reference following it.
 *
 * The same rewrite as `renameCascade` over many ids at once, plus the two rules
 * a fragment needs and a rename does not:
 *
 * An edge survives only when BOTH of its endpoints were copied. A dangling
 * endpoint is `edge-unknown-endpoint`, and pasting three nodes out of a
 * five-node selection should not hand the author two errors they did not make.
 *
 * A `joins` entry survives only when its node was copied, for the same reason:
 * `join-unknown-node` names an id that is no longer anywhere on the canvas.
 *
 * Edge ids are re-minted too. They are a separate namespace from node ids but
 * they are equally unique per document, and a paste that kept them would be a
 * `duplicate-edge-id` the first time anyone pasted back into the document they
 * copied from - which is the commonest paste there is.
 */
export function remapIds(subgraph: BuilderSubgraph, mint: SubgraphMinter): BuilderSubgraph {
  const rename = new Map<string, NodeId>()
  for (const node of subgraph.nodes) rename.set(node.id, mint.node(node.id))
  const { tokens, keys } = swapsFor(subgraph.nodes, rename)

  const edges: BuilderEdge[] = []
  for (const edge of subgraph.edges) {
    const source = rename.get(edge.source)
    const target = rename.get(edge.target)
    if (source === undefined || target === undefined) continue
    edges.push({ ...edge, id: mint.edge(edge.id), source, target })
  }

  const joins: BuilderJoins = {}
  for (const key of Object.keys(subgraph.joins)) {
    const renamed = rename.get(key)
    if (renamed !== undefined) joins[renamed] = subgraph.joins[key]
  }

  return {
    nodes: subgraph.nodes.map((node) => rewriteNode(node, rename, tokens, keys)),
    edges,
    joins,
  }
}
