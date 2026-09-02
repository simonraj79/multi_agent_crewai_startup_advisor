import { computed, shallowRef } from 'vue'
import { edgeId } from '../types/builder'
import type {
  AgentConfig,
  BuilderDocument,
  BuilderEdge,
  BuilderJoins,
  BuilderNode,
  CrewConfig,
  EdgeId,
  GateConfig,
  InputConfig,
  NodeId,
  NodePosition,
  OutputConfig,
  RouterConfig,
  TransformConfig,
} from '../types/builder'
import { renameCascade } from '../utils/builderGraph'
import type { BuilderSubgraph } from '../utils/builderGraph'

/**
 * The document, and the single write path to it.
 *
 * Spec §1.1 states five invariants and this file is where four of them are
 * either kept or broken. They are worth restating as mechanisms rather than as
 * rules, because each one is a defect this architecture is written against:
 *
 * 1. **`commit()` is the only function that assigns to the document.** Not the
 *    canvas, not an inspector, not Vue Flow. Everything else in the builder
 *    reads `doc` and calls a mutator; there is no second door. The one other
 *    assigner is `load()`, which is not an edit at all - it starts a session on
 *    a different document and CLEARS the history, so it can never be mistaken
 *    for a command and no gesture reaches it (a route change, a template pick
 *    and a conflict resolution are its only callers).
 * 2. **The document is replaced, never mutated**, and `import.meta.env.DEV`
 *    deep-freezes every version to prove it. The freeze is not decoration: the
 *    undo ring holds references to previous documents, so a single in-place
 *    mutation anywhere would silently rewrite history as well as the present,
 *    and the author would undo into a state that never existed.
 * 3. **Vue Flow's arrays are projections**, which is WP-D's half of the same
 *    contract; what this file guarantees is that a projection built from `doc`
 *    is stable until a commit replaces it.
 * 4. **`expected_version` never comes from here.** `doc.version` is
 *    server-assigned and overwritten on every write, so it is decorative on the
 *    client; `useBuilderPersistence` holds the authoritative one, read only out
 *    of a response.
 *
 * The history is a SNAPSHOT RING (R3), not a command algebra with `invert()`.
 * The document is capped at 256 KiB and frozen, so 200 references cost nothing
 * an inversion bug would not cost more - and an inverse that is subtly wrong
 * corrupts a document in a way no test written against the forward operation
 * would ever see.
 */

/** Spec R3. Deep enough that no editing session reaches the floor in practice. */
const HISTORY_LIMIT = 200

/**
 * Spec §2 WP-B. Consecutive commits carrying the same `coalesceKey` inside this
 * window are ONE undo step, so a typed word does not cost eight of them.
 *
 * The window restarts on every merged keystroke rather than running from the
 * first, which is what makes "a typed word" the unit: a steady typist never
 * pauses 600ms mid-word, and the moment they do, the next character starts a
 * fresh step exactly where a reader would put the boundary.
 */
const COALESCE_WINDOW_MS = 600

/** One restorable point in the ring: the document to go back to, and what it undoes. */
interface Snapshot {
  /** The document as it was BEFORE the labelled action. */
  readonly document: BuilderDocument
  /** What `DocumentBar` says after an undo: `Undid: delete node`. */
  label: string
  /**
   * The merge key, or `undefined` for a step nothing may merge into.
   * `sealHistory()` clears it, which is how a blur ends a burst.
   */
  coalesceKey: string | undefined
  /** When this entry last absorbed a commit, for the 600ms window. */
  at: number
}

/**
 * A patch over any node config, with every field carrying its own type.
 *
 * The intersection is what makes this safe rather than a bag of `unknown`:
 * `Partial<A & B>` gives each key the type it has on whichever config declares
 * it, so `patch.max_iter` is a `number` and `patch.branches` a `RouterBranch[]`
 * even though no single config has both. The seven configs share several field
 * names (`tier`, `max_iter`, `prompt_inputs`) and no two of them disagree about
 * a type, so the intersection is well formed rather than a pile of `never`.
 *
 * What it deliberately does NOT do is prove the field belongs to the node being
 * patched - that needs the kind, which a caller holding only an id does not
 * have. `patchConfig` closes that at run time by refusing a key the node's own
 * config does not declare, which is the honest place for it: every field of
 * every config is required, so a key that is absent is a caller's bug and never
 * an author's document.
 */
export type ConfigPatch = Partial<
  InputConfig &
    AgentConfig &
    CrewConfig &
    GateConfig &
    RouterConfig &
    TransformConfig &
    OutputConfig
>

/** Where one node is being moved to. `moveNodes` rounds; `Position` is `int`. */
export interface NodeMove {
  id: NodeId
  position: NodePosition
}

/** The endpoints of a new edge. The id is minted here so one function owns `e<n>`. */
export interface EdgeEnds {
  source: NodeId
  source_port: string
  target: NodeId
}

/**
 * The first free `e<n>`, against every edge id the document already holds.
 *
 * Exported because three packages mint edges - `addEdge` here, `PortMenu`'s
 * one-commit node-plus-edge, and the clipboard's paste - and three minters
 * would be three chances to produce a `duplicate-edge-id` the author cannot
 * see. The first FREE suffix rather than a count, for the reason
 * `builderDefaults.newNode` gives about node ids: a monotonic counter drifts
 * with every delete until an author is looking at `e37` in a graph with four
 * edges.
 *
 * `e<n>` matches `BUILDER_ID_PATTERN` for every n, so `edgeId()` can assert
 * rather than hope.
 */
export function mintEdgeId(taken: ReadonlySet<string>): EdgeId {
  let suffix = 1
  while (taken.has(`e${suffix}`)) suffix += 1
  return edgeId(`e${suffix}`)
}

/**
 * The merge key a single-field edit coalesces under.
 *
 * Exported so `BuilderView` (spec §4.4: "ONE commit with
 * `coalesceKey = node:<id>:<field>`") and the mutators below produce the same
 * string. Two spellings of one key is two undo steps where the author expects
 * one, and nothing would fail.
 */
export function fieldCoalesceKey(id: string, field: string): string {
  return `node:${id}:${field}`
}

/**
 * Freeze a document and everything it holds, in dev only.
 *
 * Recursive because the mutation this catches is never at the top level - it is
 * `node.config.branches.push(...)` or `doc.joins[id] = 'all'`, three levels
 * down, in code that believes it owns the object it was handed. Skipping an
 * already-frozen subtree keeps this O(what changed) rather than O(document) on
 * every keystroke: `renameCascade` and the mutators below all return the SAME
 * reference for anything they did not touch, so a label edit re-walks one node.
 */
function deepFreeze<T>(value: T): T {
  if (value === null || typeof value !== 'object' || Object.isFrozen(value)) return value
  Object.freeze(value)
  for (const entry of Object.values(value as Record<string, unknown>)) deepFreeze(entry)
  return value
}

/**
 * The editing session for one document.
 *
 * `initial` is required rather than defaulted. A blank document is a TEMPLATE
 * (`builderTemplates.BLANK`, WP-F) and minting a second one here would be two
 * answers to "what does an empty graph look like" - the shape this repo has
 * already been bitten by often enough to have a name for.
 */
export function useBuilderDocument(initial: BuilderDocument) {
  const doc = shallowRef<BuilderDocument>(import.meta.env.DEV ? deepFreeze(initial) : initial)
  /**
   * The document as the server last stored it, by REFERENCE.
   *
   * Identity rather than content, and that is exact rather than approximate:
   * the document is immutable by invariant, so two references are equal exactly
   * when the content is. It also gets undo-back-to-clean right for free - an
   * author who types a word and undoes it is back on the saved reference, and
   * the chip honestly reads `saved` rather than offering to write a document
   * byte-identical to the one already stored.
   */
  const baseline = shallowRef<BuilderDocument>(doc.value)

  const history: Snapshot[] = []
  const future: Snapshot[] = []
  /**
   * Bumped on every assignment, purely so `computed`s over the two arrays
   * recompute. The arrays are plain rather than reactive because they hold up
   * to 200 whole documents and a deep proxy over that is paid for on every
   * read; a counter is the smallest honest signal that one of them changed.
   */
  const revision = shallowRef(0)

  const dirty = computed(() => doc.value !== baseline.value)
  const canUndo = computed(() => revision.value >= 0 && history.length > 0)
  const canRedo = computed(() => revision.value >= 0 && future.length > 0)
  const undoLabel = computed(() =>
    revision.value >= 0 ? (history[history.length - 1]?.label ?? '') : '',
  )
  const redoLabel = computed(() =>
    revision.value >= 0 ? (future[future.length - 1]?.label ?? '') : '',
  )
  /** Introspection for tests and for nothing else; the ring's bound is a claim worth asserting. */
  const depth = computed(() => (revision.value >= 0 ? history.length : 0))
  const redoDepth = computed(() => (revision.value >= 0 ? future.length : 0))

  function assign(next: BuilderDocument): void {
    doc.value = import.meta.env.DEV ? deepFreeze(next) : next
    revision.value += 1
  }

  /**
   * The one write path. Everything else in this file goes through it.
   *
   * A commit that changes nothing is dropped rather than recorded. `roundPositions`
   * already states the reason for the mirror case and it holds here: an undo
   * step that visibly does nothing is worse than no undo step at all, and the
   * ring is 200 deep, not 200 useful.
   *
   * A new commit CLEARS the redo future. That is the standard contract and it
   * is the one an author has: having undone three steps and then typed, the
   * three are gone, because there is no longer a single timeline they belong
   * to.
   */
  function commit(label: string, next: BuilderDocument, coalesceKey?: string | null): void {
    if (next === doc.value) return

    const key = coalesceKey ?? undefined
    const top = history[history.length - 1]
    const now = Date.now()
    if (
      key !== undefined &&
      top !== undefined &&
      top.coalesceKey === key &&
      now - top.at <= COALESCE_WINDOW_MS
    ) {
      // The entry keeps the document it was born with - the state BEFORE the
      // burst began - so one undo returns to where the author started typing
      // rather than to the penultimate keystroke.
      top.label = label
      top.at = now
      future.length = 0
      assign(next)
      return
    }

    history.push({ document: doc.value, label, coalesceKey: key, at: now })
    if (history.length > HISTORY_LIMIT) history.shift()
    future.length = 0
    assign(next)
  }

  /**
   * End the current coalescing burst, so the next commit is its own step.
   *
   * Called on blur, on leaving a mode, and before a save (spec §2 WP-B). A save
   * is on the list because the ring is the author's only record of what they
   * have done since the last one: an undo that crosses a save boundary should
   * land ON the boundary, not halfway through the word that preceded it.
   */
  function sealHistory(): void {
    const top = history[history.length - 1]
    if (top) top.coalesceKey = undefined
  }

  function undo(): void {
    const entry = history.pop()
    if (!entry) return
    future.push({ document: doc.value, label: entry.label, coalesceKey: undefined, at: Date.now() })
    assign(entry.document)
  }

  function redo(): void {
    const entry = future.pop()
    if (!entry) return
    history.push({ document: doc.value, label: entry.label, coalesceKey: undefined, at: Date.now() })
    assign(entry.document)
  }

  /**
   * Start a session on a different document, discarding the history.
   *
   * Not an edit and not undoable, which is exactly why it clears the ring: an
   * undo that crossed a load would restore a version of a DIFFERENT document
   * into an editor addressing this one, and the next save would write it under
   * the wrong id.
   *
   * `dirty` says whether the loaded document is already stored. A template is
   * seeded dirty (nothing has stored it); a server response is seeded clean.
   * The conflict path uses neither - it goes through `commit`, so whichever
   * version the author displaces stays one Ctrl+Z away.
   */
  function load(next: BuilderDocument, options?: { dirty?: boolean }): void {
    history.length = 0
    future.length = 0
    assign(next)
    // UNSAVED is a document no session can ever hold, so `dirty` is true
    // without inventing a fake previous version to compare against.
    baseline.value = options?.dirty === true ? UNSAVED : doc.value
  }

  /** The document is now what the server holds. Identity, so the comparison is exact. */
  function markSaved(): void {
    baseline.value = doc.value
  }

  /* --- typed mutators --------------------------------------------------- */

  /**
   * A new node, and optionally the edge that reaches it, as ONE commit.
   *
   * The optional edge is what makes `PortMenu` and the auto-connecting number
   * keys honest (spec §4.1): "Enter -> ONE commit containing the node AND the
   * edge, labelled `Add market analyst`. One undo removes both." Two commits
   * would leave an author who pressed Ctrl+Z once looking at an orphan node
   * they never asked for.
   */
  function addNode(node: BuilderNode, options?: { edge?: EdgeEnds; label?: string }): void {
    const edges = options?.edge
      ? [
          ...doc.value.edges,
          {
            ...options.edge,
            id: mintEdgeId(new Set(doc.value.edges.map((edge) => edge.id as string))),
            target_port: 'in' as const,
          },
        ]
      : doc.value.edges
    commit(options?.label ?? `Add ${node.label}`, {
      ...doc.value,
      nodes: [...doc.value.nodes, node],
      edges,
    })
  }

  /**
   * Delete nodes and edges, with the cascade, in one command.
   *
   * The cascade is the whole point and it is two rules, both of which turn a
   * deletion into a graph the server would refuse:
   *
   * - Every edge incident to a deleted node goes too. Left behind it is
   *   `edge-unknown-endpoint`, an error naming an id that is no longer anywhere
   *   on the canvas.
   * - Every `joins` key naming a deleted node goes too - `join-unknown-node`,
   *   for the same reason.
   *
   * A join is dropped only when its NODE is gone. A join whose node merely fell
   * below two predecessors is `join-single-predecessor`, a WARNING that
   * `bounds.py` owns; deleting the key here would be the client computing a
   * Tier 2 count and silently editing the author's declaration on the strength
   * of it (spec §6.1, R6).
   *
   * One commit, so one Ctrl+Z restores all of it. `deleteSelection` is also why
   * enabling the Delete key is safe here and is not in ChatDev: undo IS the
   * confirmation, so there is no dialog.
   */
  function deleteSelection(
    nodeIds: Iterable<NodeId>,
    edgeIds?: Iterable<EdgeId>,
    label?: string,
  ): void {
    const goneNodes = new Set<string>(nodeIds)
    const goneEdges = new Set<string>(edgeIds ?? [])
    if (goneNodes.size === 0 && goneEdges.size === 0) return

    const nodes = doc.value.nodes.filter((node) => !goneNodes.has(node.id))
    const edges = doc.value.edges.filter(
      (edge) =>
        !goneEdges.has(edge.id) && !goneNodes.has(edge.source) && !goneNodes.has(edge.target),
    )
    const joins: BuilderJoins = {}
    for (const key of Object.keys(doc.value.joins)) {
      if (!goneNodes.has(key)) joins[key] = doc.value.joins[key]
    }

    const lostNodes = doc.value.nodes.length - nodes.length
    const lostEdges = doc.value.edges.length - edges.length
    if (lostNodes === 0 && lostEdges === 0) return

    commit(label ?? deleteLabel(lostNodes, lostEdges), { ...doc.value, nodes, edges, joins })
  }

  /**
   * Final positions for a set of nodes, as one commit.
   *
   * Fed from `@node-drag-stop`, never from `@nodes-change` (spec invariant 4).
   * A per-frame commit would spend the entire 200-entry ring on one gesture and
   * leave an author unable to undo anything they did before picking the node
   * up - which is the failure this signature exists to make impossible: it
   * takes the END of a drag, so there is nothing per-frame to commit.
   *
   * `coalesce` is for the arrow keys, where consecutive nudges under one key
   * are one step (spec §4.3). A drag passes nothing, because two drags of the
   * same node inside 600ms are two things the author did.
   */
  function moveNodes(moves: readonly NodeMove[], options?: { coalesce?: boolean }): void {
    if (moves.length === 0) return
    const wanted = new Map<string, NodePosition>()
    for (const move of moves) {
      wanted.set(move.id, { x: Math.round(move.position.x), y: Math.round(move.position.y) })
    }
    let changed = false
    const nodes = doc.value.nodes.map((node) => {
      const position = wanted.get(node.id)
      if (!position || (position.x === node.position.x && position.y === node.position.y)) {
        return node
      }
      changed = true
      return { ...node, position }
    })
    if (!changed) return

    const key = options?.coalesce ? `move:${[...wanted.keys()].sort().join(',')}` : undefined
    commit(
      moves.length === 1 ? 'Move node' : `Move ${moves.length} nodes`,
      { ...doc.value, nodes },
      key,
    )
  }

  /**
   * A node id changed everywhere it is written, as one commit.
   *
   * `renameCascade` does the work and its docblock explains why the naive
   * version is dangerous: a dangling `${state.turns__old}` COMPILES, returns
   * zero problems, and then routes to `otherwise` forever. One commit because
   * one rename is one thing the author did, and a partial undo of it would
   * leave the document in a state the cascade exists to make unreachable.
   */
  function renameNode(from: NodeId, to: NodeId): void {
    commit(`Rename ${from} to ${to}`, renameCascade(doc.value, from, to))
  }

  /** The node's canvas label. Coalesced, so an inline rename is one undo step. */
  function setLabel(id: NodeId, label: string): void {
    const nodes = doc.value.nodes.map((node) => (node.id === id ? { ...node, label } : node))
    commit('Rename node', { ...doc.value, nodes }, fieldCoalesceKey(id, 'label'))
  }

  /**
   * Merge `patch` into one node's config.
   *
   * A key the node's config does not declare THROWS rather than being written
   * or dropped. Every field of all seven configs is required, so an absent key
   * is never an author's document - it is an inspector dispatching to the wrong
   * kind, and writing it would produce a node the server refuses with a 422
   * naming a field nobody typed. Dropping it silently would be worse still: the
   * control would appear to work.
   *
   * The default coalesce key is `node:<id>:<field>` for a single-field patch,
   * which is the spec's own (§4.4). Pass `null` to force a distinct step.
   */
  function patchConfig(id: NodeId, patch: ConfigPatch, coalesceKey?: string | null): void {
    const target = doc.value.nodes.find((node) => node.id === id)
    if (!target) return
    const keys = Object.keys(patch)
    for (const key of keys) {
      if (!(key in target.config)) {
        throw new Error(
          `patchConfig: a ${target.kind} node has no '${key}'; ` +
            'every field of every config is required, so this is an inspector ' +
            'dispatching to the wrong kind rather than a document that lost a key.',
        )
      }
    }
    const config = { ...target.config, ...patch }
    const nodes = doc.value.nodes.map((node) =>
      node.id === id ? ({ ...node, config } as BuilderNode) : node,
    )
    const key =
      coalesceKey === null
        ? undefined
        : (coalesceKey ?? (keys.length === 1 ? fieldCoalesceKey(id, keys[0]) : undefined))
    commit(keys.length === 1 ? `Edit ${keys[0]}` : 'Edit node', { ...doc.value, nodes }, key)
  }

  /** One new edge, with its id minted here. Returns the id so a caller can select it. */
  function addEdge(ends: EdgeEnds): EdgeId {
    const id = mintEdgeId(new Set(doc.value.edges.map((edge) => edge.id as string)))
    const edge: BuilderEdge = { ...ends, id, target_port: 'in' }
    commit('Connect nodes', { ...doc.value, edges: [...doc.value.edges, edge] })
    return id
  }

  function deleteEdges(ids: Iterable<EdgeId>, label?: string): void {
    const gone = new Set<string>(ids)
    if (gone.size === 0) return
    const edges = doc.value.edges.filter((edge) => !gone.has(edge.id))
    if (edges.length === doc.value.edges.length) return
    const lost = doc.value.edges.length - edges.length
    commit(label ?? (lost === 1 ? 'Delete edge' : `Delete ${lost} edges`), {
      ...doc.value,
      edges,
    })
  }

  /**
   * Move an edge to a different out-port of the same source.
   *
   * The gate case is the one that matters: this is how an edge moves between
   * `approve` and `revise`, which on the canvas is a drag of one endpoint onto
   * the neighbouring port and in the inspector is a select.
   */
  function setEdgePort(id: EdgeId, sourcePort: string): void {
    const edges = doc.value.edges.map((edge) =>
      edge.id === id ? { ...edge, source_port: sourcePort } : edge,
    )
    commit('Change edge port', { ...doc.value, edges })
  }

  /** Re-point either end of an existing edge. `target_port` is always `'in'`; there is no other. */
  function retargetEdge(
    id: EdgeId,
    ends: { source?: NodeId; source_port?: string; target?: NodeId },
  ): void {
    const edges = doc.value.edges.map((edge) => (edge.id === id ? { ...edge, ...ends } : edge))
    commit('Reconnect edge', { ...doc.value, edges })
  }

  /**
   * Declare a node's fan-in as AND, or take the declaration away.
   *
   * `'all'` is the only value written, ever. `'any'` is refused at PARSE time
   * rather than reported, because a multi-event `or_()` listener is added to
   * CrewAI's `_fired_or_listeners` the first time it fires and skipped forever
   * after - the second arrival ends the run normally having produced nothing.
   * There is no widget for it and there is nothing here to write it with.
   */
  function setJoin(id: NodeId, all: boolean): void {
    const joins: BuilderJoins = { ...doc.value.joins }
    if (all) joins[id] = 'all'
    else delete joins[id]
    commit(all ? 'Fan-in: wait for all' : 'Fan-in: first arrival', { ...doc.value, joins })
  }

  /** Which input node's `field` the run's `inputs` key is. Not a node id - a field name. */
  function setInputField(field: NodeId): void {
    commit('Set run input', { ...doc.value, input_field: field }, 'doc:input_field')
  }

  function setName(name: string): void {
    commit('Rename graph', { ...doc.value, name }, 'doc:name')
  }

  /**
   * Seed a template as an ordinary unsaved draft (spec §4.6).
   *
   * A load rather than a commit, and dirty rather than clean: there is nothing
   * behind a template to undo back to, and nothing has stored it, so the first
   * Ctrl+S is a create. "Same commands, same undo, same inspectors, no special
   * case anywhere in the code" begins the moment this returns.
   */
  function applyTemplate(template: BuilderDocument): void {
    load(template, { dirty: true })
  }

  /**
   * Merge a re-minted fragment into the document as one commit.
   *
   * The fragment arrives with its ids ALREADY minted against this document -
   * `useBuilderClipboard` does that through `remapIds`, which is also what
   * rewrites the `${state.out__…}` references between the copied nodes. Nothing
   * is re-checked here: a second opinion about uniqueness would be a second
   * minter, and the label is the author's ("Paste 4 nodes"), not this
   * function's.
   */
  function pasteSubgraph(subgraph: BuilderSubgraph, label: string): void {
    commit(label, {
      ...doc.value,
      nodes: [...doc.value.nodes, ...subgraph.nodes],
      edges: [...doc.value.edges, ...subgraph.edges],
      joins: { ...doc.value.joins, ...subgraph.joins },
    })
  }

  return {
    doc,
    dirty,
    revision,
    commit,
    load,
    markSaved,
    sealHistory,
    undo,
    redo,
    canUndo,
    canRedo,
    undoLabel,
    redoLabel,
    depth,
    redoDepth,
    addNode,
    deleteSelection,
    moveNodes,
    renameNode,
    setLabel,
    patchConfig,
    addEdge,
    deleteEdges,
    setEdgePort,
    retargetEdge,
    setJoin,
    setInputField,
    setName,
    applyTemplate,
    pasteSubgraph,
  }
}

export type BuilderDocumentStore = ReturnType<typeof useBuilderDocument>

/**
 * A document no editing session can ever hold, used only as the `dirty`
 * baseline for something the server has never seen.
 *
 * A sentinel rather than a nullable baseline, so `dirty` stays one identity
 * comparison with no branch: a template is dirty because the document it would
 * have to equal is this, and nothing is this.
 */
const UNSAVED = Object.freeze({
  schema: 'builder.flow/v1',
  id: 'ug_00000000',
  name: '',
  version: 0,
  input_field: 'unsaved',
  nodes: [],
  edges: [],
  joins: {},
  budget: null,
}) as unknown as BuilderDocument

/**
 * `Delete 1 node and 2 edges` - the CASCADE counted, not just what was selected.
 *
 * Both halves carry a number whenever both are present, because the edge count
 * is the part the author did not choose: deleting one node that silently took
 * three connections with it is exactly the thing a label should say before the
 * author decides whether to undo.
 */
function deleteLabel(nodes: number, edges: number): string {
  if (edges === 0) return nodes === 1 ? 'Delete node' : `Delete ${nodes} nodes`
  if (nodes === 0) return edges === 1 ? 'Delete edge' : `Delete ${edges} edges`
  return `Delete ${nodes} node${nodes === 1 ? '' : 's'} and ${edges} edge${edges === 1 ? '' : 's'}`
}
