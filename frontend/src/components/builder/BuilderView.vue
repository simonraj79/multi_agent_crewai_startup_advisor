<script setup lang="ts">
import { computed, nextTick, onMounted, provide, ref, shallowRef, watch } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleDot,
  Info,
  KeyRound,
  PenTool,
  Play,
  RotateCcw,
  Unplug,
  X,
} from 'lucide-vue-next'
import SignInPanel from '../SignInPanel.vue'
import AccountChip from './AccountChip.vue'
import BudgetMeter from './BudgetMeter.vue'
import BuilderCanvas from './BuilderCanvas.vue'
import BuilderEdge from './BuilderEdge.vue'
import BuilderNode from './BuilderNode.vue'
import ConflictDialog from './ConflictDialog.vue'
import DocumentBar from './DocumentBar.vue'
import InspectorRail from './InspectorRail.vue'
import NodePalette from './NodePalette.vue'
import PortMenu from './PortMenu.vue'
import ProblemsPanel from './ProblemsPanel.vue'
import PublishDialog from './PublishDialog.vue'
import SaveChip from './SaveChip.vue'
import ShortcutSheet from './ShortcutSheet.vue'
import TemplateGallery from './TemplateGallery.vue'
import VersionBrowser from './VersionBrowser.vue'
import { useBuilderCanvas, canvasHasFocus, snapToGrid } from '../../composables/useBuilderCanvas'
import { useBuilderClipboard } from '../../composables/useBuilderClipboard'
import { edgeOptionsFor, useBuilderDocument } from '../../composables/useBuilderDocument'
import { useBuilderHotkeys } from '../../composables/useBuilderHotkeys'
import { useBuilderPersistence } from '../../composables/useBuilderPersistence'
import { BUILDER_PROBLEMS, useBuilderProblems } from '../../composables/useBuilderProblems'
import { useBuilderValidation } from '../../composables/useBuilderValidation'
import { useStudioTheme } from '../../composables/useStudioTheme'
import { BLANK, documentFromTemplate } from '../../data/builderTemplates'
import { BuilderConflictError, builderApi } from '../../services/builderApi'
import { ExportFileError, downloadExport, exportFilename, readExportFile } from '../../utils/builderExport'
import { loadVocabulary, vocabulary, vocabularyProblem } from '../../data/builderVocabulary'
import { writeRunHandoff } from '../../data/builderRunHandoff'
import type { BuilderTemplate } from '../../data/builderTemplates'
import type { SignedInUser } from '../../composables/useAuthGate'
import type { InspectorCommit } from './commit'
import type { PortMenuCreation } from './PortMenu.vue'
import type {
  BuilderDocumentModel,
  BuilderDocumentSummary,
  BuilderExportEnvelope,
  BuilderProblem,
  BuilderPublish,
  BuilderVersionRow,
  DocumentId,
  EdgeId,
  NodeId,
} from '../../types/builder'

/**
 * The builder shell: the one place that knows every other builder package
 * exists, and the only place a gesture becomes a commit.
 *
 * Everything below is wiring, and the shape of the wiring is spec §1.1's
 * one-way loop. `useBuilderDocument.commit()` is the sole write path; the
 * canvas, the inspectors and the hotkeys all propose and none of them assign.
 * That is why the inspector emits a whole next document rather than a patch,
 * why `@node-drag-stop` is the only drag event that reaches the store, and why
 * an author can undo a router branch deletion and get the edge back with it.
 *
 * WHAT IS NOT HERE. No Launch control and no Build/Run toggle inside the
 * builder (cut list item 1 stands): the run console keeps its own switch back
 * here, and this view's header carries the mirror of it - one pair, one
 * direction each. `PublishDialog` offers "Run it" AFTER a successful publish,
 * which is a different claim entirely: that button names a workflow the server
 * has just registered and confirmed it will accept a run for.
 *
 * IT REUSES `.studio-shell` / `.studio-main`. Not for tidiness - so the two
 * workspaces cannot drift apart on row height, gutter, rail transition or
 * either breakpoint, and so the `min-height: 0` lesson `studio.css` records at
 * length is inherited rather than re-learned. An `auto` row there once grew an
 * 848px container to 1894px and pushed Launch below the fold.
 */

const props = withDefaults(
  defineProps<{
    /** From `#/build/:documentId`, or null for `#/build`. */
    documentId: DocumentId | null
    /**
     * The signed-in account, or null when there is none - exactly what
     * `StudioView` receives (plan 01 D9). Optional with a null default rather
     * than required, because every spec that mounted this view before identity
     * reached it passes `documentId` alone, and a bare local checkout has no
     * account to pass.
     */
    user?: SignedInUser | null
    /** True once the session request resolved to a signed-in account. */
    authenticated?: boolean
    /**
     * Whether an auth server exists at all. `false` is the bare local checkout
     * and the SYNTHETIC harness (`useAuthGate`'s `unconfigured`), where the
     * builder works exactly as it did before identity reached it. `true` with
     * `authenticated: false` is "configured but signed out", and that is the
     * one combination this view refuses to draw a gallery for.
     */
    authConfigured?: boolean
    /** The sign-in wall's two props, passed through from `useAuthGate`. */
    signingIn?: boolean
    signInError?: string | null
  }>(),
  { user: null, authenticated: false, authConfigured: false, signingIn: false, signInError: null },
)

const emit = defineEmits<{
  /** Leave for the run console. */
  runWorkspace: []
  /**
   * Start and end a session. Handled by `App.vue` and nowhere else: `endSession`
   * drops the cached bearer token BEFORE revoking the cookie, and a second
   * sign-out path that forgot the order would leave a token alive in memory.
   */
  signIn: []
  signOut: []
  /** Change the hash to this document, so a refresh comes back to it. */
  openDocument: [documentId: DocumentId]
  /**
   * The document on screen just acquired a server id; put it in the address.
   *
   * Distinct from `openDocument` because it must REPLACE the history entry
   * rather than push one: the author has not navigated anywhere, the same graph
   * is still under the cursor, and only its address has become expressible.
   */
  adoptDocument: [documentId: DocumentId]
  /**
   * The document on screen was DELETED; take the address back to `#/build`.
   *
   * Replace rather than push, for the reason `adoptDocument` gives in reverse:
   * the entry for a document that no longer exists must not stay on the stack,
   * or Back lands on a 404 the author has just been told about.
   */
  closeDocument: []
}>()

/* ── the document, and everything hanging off it ───────────────────────────
 *
 * Seeded from BLANK rather than from an empty object, because
 * `useBuilderDocument` takes a document and `BuilderDocument` has no valid
 * empty value - `schema`, `id`, `name`, `version` and `input_field` are all
 * required. BLANK is that document, and it is the same one the gallery hands
 * over when an author picks "Blank canvas", so the two paths cannot diverge. */
const store = useBuilderDocument(documentFromTemplate(BLANK))
/*
 * `onSaved` is plan 15 D4's one permitted addition to the save loop, and it is
 * what keeps two lists honest: the palette's library, which read "No saved
 * graphs yet" under a chip saying `saved · v1`, and the version browser, which
 * would otherwise list v1..v6 under a chip saying v7. It fires once per
 * successful write, from inside the composable, so autosave reaches it too.
 */
const persistence = useBuilderPersistence(store, builderApi, {
  // The draft is this person's (D-01-5): keyed to the signed-in user so the
  // next person on the same browser never reads it, and swept on sign-out.
  userId: () => props.user?.id ?? null,
  onSaved: () => {
    void refreshLibrary()
    if (versionsOpen.value) void loadVersions()
  },
})
const clipboard = useBuilderClipboard(store)

/**
 * True while a connect drag is live, which is the only gesture that can move
 * the fingerprint.
 *
 * §6.2 says a drag suppresses validation; a NODE drag cannot reach it at all,
 * because `fingerprint` omits `position` by construction. What can is a connect
 * drag, where the author is halfway through describing an edge - so this is the
 * one signal, and naming only it is more honest than passing a flag that also
 * covers a gesture the loop is already blind to.
 *
 * A plain ref fed by a watcher rather than a `computed` over `canvas`, and the
 * ordering is why: the canvas needs the problem index, the index needs the
 * validation loop, and the loop needs this flag - a cycle. A computed reading
 * `canvas` from above its own declaration threw
 * `Cannot access 'canvas' before initialization` the first time this view was
 * mounted in a test, because `useBuilderValidation` installs its watcher
 * eagerly. Breaking the cycle at the cheapest link keeps every other dependency
 * pointing one way.
 */
const gestureLive = ref(false)

/**
 * Light or dark (02-canvas.md D6).
 *
 * Constructed here and handed to two callers - `⇧L` below and `DocumentBar`'s
 * button - because it is a preference and not a document: it never reaches
 * `commit`, so `Ctrl+Z` cannot change the lights and a published graph carries
 * nobody's idea of what colour a canvas should be.
 */
const theme = useStudioTheme()

const validation = useBuilderValidation(store.doc, { api: builderApi, suppressed: gestureLive })
const problems = useBuilderProblems(validation.problems)

/**
 * The canvas's view of the store, adapted rather than passed through.
 *
 * `CanvasDocumentStore` is a deliberately narrower interface with its own
 * argument shapes - `addNode(node, connectFrom)` against the store's
 * `addNode(node, { edge, label })` - and writing the adapter here is what keeps
 * both files honest: the canvas cannot reach a method it was not handed, and
 * the store is not reshaped to suit one caller.
 */
const canvas = useBuilderCanvas({
  document: {
    doc: store.doc,
    addNode: (node, connectFrom, attachTo) =>
      store.addNode(node, edgeOptionsFor(node, connectFrom ?? null, attachTo ?? null)),
    addEdge: (origin, target) =>
      store.addEdge({ source: origin.source, source_port: origin.source_port, target }),
    moveNodes: (moves, coalesceKey) => store.moveNodes(moves, { coalesce: coalesceKey !== undefined }),
    deleteSelection: (nodes, edges) => store.deleteSelection(nodes, edges),
    setEdgePort: (edge, port) => store.setEdgePort(edge, port),
    retargetEdge: (edge, endpoint, node, port) =>
      store.retargetEdge(
        edge,
        endpoint === 'source' ? { source: node, source_port: port } : { target: node },
      ),
    setJoin: (node, join) => store.setJoin(node, join === 'all'),
  },
  problems: {
    byNode: () => problems.problemsByNode.value,
    byEdge: () => problems.problemsByEdge.value,
  },
})

watch(
  () => canvas.connectDrag.value !== null,
  (live) => {
    gestureLive.value = live
  },
)

/* ── shell state ───────────────────────────────────────────────────────── */

/**
 * Below this width both rails start CLOSED (02-canvas.md D9).
 *
 * 640 is `studio.css`'s own narrow breakpoint, named once here so the state and
 * the stylesheet cannot disagree about where a rail becomes an overlay. Above
 * it the two rails are columns and closing them would take the author's tools
 * away for no reason; at 390 they are a bottom sheet and a full-width panel,
 * and OPEN BY DEFAULT means the first thing a reader sees is the inspector
 * covering the entire graph. Measured before this landed: the inspector at
 * 390x792 over a canvas nobody could see, and a Playwright click on a card
 * timing out as "not stable" because the card was underneath it.
 *
 * Read once, at setup, rather than watched. A viewport that crosses 640px
 * mid-session is a window being resized on a desktop, and re-closing somebody's
 * rails while they drag a window edge is worse than leaving them where they put
 * them - the CSS follows the width either way.
 */
const NARROW_VIEWPORT_PX = 640
const startsNarrow =
  typeof window !== 'undefined' && window.innerWidth <= NARROW_VIEWPORT_PX

const paletteCollapsed = ref(startsNarrow)
const inspectorCollapsed = ref(startsNarrow)
const publishOpen = ref(false)
const shortcutsOpen = ref(false)
const library = shallowRef<readonly BuilderDocumentSummary[]>([])
/** A publish 422's problems, merged into the panel tagged `from publish`. */
const publishProblems = shallowRef<readonly BuilderProblem[]>([])
/** The label of the last undone command, for `DocumentBar`'s announcement. */
const undoneLabel = ref('')
let undoneTimer = 0
/** One line from a structural rewrite or a denied clipboard. Never silent. */
const notice = ref('')
let noticeTimer = 0

/**
 * What KIND of line, and what it offers (round 2, D-15-5).
 *
 * The notice was a bare string in the header: no icon, no dismiss, no action,
 * and `max-width: 42ch; white-space: nowrap` cut the one fact an author
 * needed off the end - `imported alice.builder.json as a new draft, "Minimal
 * g…` in a library that had just gained a second row by that name. `notice`
 * stays a string, because inspectors inject it as one; the kind and the
 * action ride beside it and are cleared with it.
 */
type NoticeKind = 'info' | 'success' | 'error'
interface NoticeAction {
  label: string
  run: () => void
}
const noticeKind = ref<NoticeKind>('info')
const noticeAction = shallowRef<NoticeAction | null>(null)
const noticeIcon = computed(() =>
  noticeKind.value === 'success' ? CircleCheck : noticeKind.value === 'error' ? CircleAlert : Info,
)

/**
 * Whether the author has a document in hand yet.
 *
 * The gallery is the empty state of the CANVAS, not of the route: `#/build`
 * with nothing started shows it, and picking a template or opening a saved
 * graph replaces it. It is not a separate page, so there is nothing to navigate
 * back from and no state to lose by starting.
 */
const started = ref(false)

const doc = computed(() => store.doc.value)

/* ── plan 15: versions, export, import, duplicate, delete ───────────────── */

const versionsOpen = ref(false)
const versions = shallowRef<readonly BuilderVersionRow[]>([])
const versionsLoading = ref(false)
const versionsProblem = ref('')
/** True while Restore's GET-then-PUT is in flight. */
const restoring = ref(false)

/**
 * Why the version browser's rows are disabled right now, or `''`.
 *
 * Opening a stored version LOADS it - history cleared, canvas replaced - so a
 * canvas that is ahead of the store must be written first. Saying so in the
 * browser is what turns a click that would have discarded work into a click
 * that cannot.
 */
const versionsBlocked = computed(() => {
  switch (persistence.saveState.value) {
    case 'dirty':
      return 'save your changes first — opening a stored version replaces what is on the canvas.'
    case 'saving':
      return 'saving… a stored version can be opened once this write lands.'
    case 'conflict':
      return 'resolve the save conflict first.'
    case 'offline':
      return 'the last save did not land — the canvas is ahead of every stored version.'
    default:
      return ''
  }
})

/**
 * Nodes the last import stripped a credential from (plan 15 D2, ruling S1-7).
 *
 * Keyed by document id so the notice cannot outlive the document it is about:
 * open something else and it is gone. It is a NOTICE and not a problem code -
 * C8's union is a Python-generated mirror and the only server-side
 * `credential-missing` is the one `validate` emits - so it lives beside the
 * restore bar rather than in `ProblemsPanel`.
 */
/**
 * The stored version on screen, or null while head is being edited.
 *
 * `persistence.viewingVersion` is a BOOLEAN - "this is not head" - and the
 * problems dock needs the number, so it can say the document bar's own words
 * rather than a paraphrase of them (D-15-17).
 */
const readOnlyVersion = computed(() =>
  persistence.viewingVersion.value ? persistence.version.value : null,
)

/** The inspector, for `focusField` - the notice's "Choose a key" (D-15-19). */
const inspectorRef = ref<{ focusField: (field: string) => Promise<boolean> } | null>(null)
const importNotice = shallowRef<{ documentId: DocumentId; nodeIds: readonly string[] } | null>(null)
const importNoticeShown = computed(
  () =>
    importNotice.value !== null &&
    importNotice.value.documentId === persistence.documentId.value,
)

/** The dock row's element, handed to the canvas so a strip opening re-fits the graph (D-15-2). */
const dockEl = ref<HTMLElement | null>(null)

/** The docked delete confirm (plan 15 D3, R15: no dialog). */
const deleteAsk = ref(false)
const deleteTyped = ref('')
const deleteProblem = ref('')
const deleteInFlight = ref(false)
/**
 * The server said no and resending cannot change its mind - a 409 for a
 * document with a version still registered (owner decision 24). The confirm
 * keeps the sentence and loses the Delete button, and offers the ONE thing
 * that lifts the refusal: Unpublish (round 2, D-15-10). Until then the
 * confirm's own copy promised that deleting a published graph would
 * unregister it, the server said the opposite, and the 409's remedy was a
 * save that turned the guard off one version deep.
 */
const deleteRefused = ref(false)
/** True while the confirm's Unpublish is in flight, so it cannot be pressed twice. */
const unpublishing = ref(false)

/**
 * Trimmed and case-insensitive, the same rule `TemplateGallery` applies and
 * for the same reason: the typed name proves the author read WHICH graph, and
 * an exact-bytes match would fail on a trailing space and teach nothing.
 */
const deleteConfirmed = computed(
  () => deleteTyped.value.trim().toLowerCase() === doc.value.name.trim().toLowerCase(),
)

/** The one sentence a refused gesture gets while a stored version is on screen. */
const readOnlyNotice = computed(
  () =>
    `v${persistence.version.value} is read-only — restore it, or go back to ` +
    `v${persistence.headVersion.value}, to edit.`,
)

/** A node's label for the import notice, or its id when the document has moved on. */
function nodeLabel(id: string): string {
  return doc.value.nodes.find((node) => node.id === id)?.label ?? id
}

function messageOf(failure: unknown, fallback: string): string {
  return failure instanceof Error && failure.message ? failure.message : fallback
}

/**
 * Errors the live loop reported, PLUS any the publish refusal added.
 *
 * The checklist read `problems.errorCount` alone, so a 422 from publish could
 * sit in the panel underneath a green `No errors` tick in the very dialog that
 * printed the refusal. `ProblemsPanel` already merges the two lists and
 * de-duplicates them by identity; this counts the same union the same way, so
 * the checklist can never outrank the server's own answer.
 */
const blockingErrorCount = computed(() => {
  const seen = new Set<string>()
  let count = 0
  for (const problem of [...validation.problems.value, ...publishProblems.value]) {
    const key = `${problem.code}\u0000${problem.message}\u0000${problem.node_id ?? ''}\u0000${problem.edge_id ?? ''}`
    if (seen.has(key)) continue
    seen.add(key)
    if (problem.severity !== 'warning') count += 1
  }
  return count
})

/** Every node and edge label, for `ProblemsPanel`'s anchor column. */
const anchorLabels = computed(() => {
  const labels: Record<string, string> = {}
  for (const node of doc.value.nodes) labels[node.id] = node.label
  for (const edge of doc.value.edges) labels[edge.id] = `${edge.source} → ${edge.target}`
  return labels
})

function say(
  message: string,
  options: { kind?: NoticeKind; action?: NoticeAction | null } = {},
): void {
  window.clearTimeout(noticeTimer)
  notice.value = message
  noticeKind.value = options.kind ?? 'info'
  noticeAction.value = options.action ?? null
  if (!message) return
  /*
   * A REFUSAL DOES NOT RETIRE ITSELF (D-15-22).
   *
   * Every refusal on the import, duplicate, export, restore and open-version
   * paths used to clear after four seconds, leaving no surface anywhere to
   * re-read the server's sentence - while delete (its docked confirm) and a
   * save conflict (`ConflictDialog`) both kept theirs. An operator who looked
   * away lost the one thing that told them what to do, and the sentence is
   * the server's own words, which is the whole reason round 2 made these
   * paths carry it (D-15-10).
   *
   * "Until dismissed or until their next action" is exactly what this gives:
   * `dismissNotice` clears it, and the next `say()` - which every action
   * makes - replaces it. Only an error stays; a success is a receipt and
   * still leaves on its own, because a console that accumulates green
   * confirmations teaches an operator to stop reading the bar.
   */
  if (noticeKind.value === 'error') return
  // Longer when there is something to press: a notice that offers a way
  // back and then leaves in four seconds is a door that closes on its own.
  noticeTimer = window.setTimeout(() => {
    notice.value = ''
    noticeAction.value = null
  }, noticeAction.value ? 8000 : 4000)
}

function dismissNotice(): void {
  say('')
}

function runNoticeAction(): void {
  const action = noticeAction.value
  dismissNotice()
  action?.run()
}

/* ── loading ───────────────────────────────────────────────────────────── */

/**
 * "Configured but signed out" - the one state this view will not draw a
 * gallery for (plan 01 criterion 9).
 *
 * `App.vue` gates outside the router, so under it this view is never mounted
 * while the phase is `anonymous`; the wall here is the second lock, the way
 * `useBuilderValidation.idle` is the second lock under `showGraph`'s kick. It
 * makes the answer a property of THIS component rather than of whoever mounts
 * it, and it is what a spec can assert without mounting the whole app.
 */
const signedOut = computed(() => props.authConfigured && !props.authenticated)

/**
 * The two reads that need an identity, started once and only once allowed.
 *
 * `StudioView` does the same with `initialize()`: a list request fired on
 * behalf of nobody is a guaranteed 401, wasted, and it would leave the library
 * decided by a request made before the visitor signed in. The vocabulary is
 * NOT behind this - `get_vocabulary` carries no `Depends(current_user)` and
 * has to resolve before the gate does, or the palette is disabled for the whole
 * of a sign-in.
 */
let builderStarted = false
async function startBuilder(): Promise<void> {
  if (builderStarted || signedOut.value) return
  builderStarted = true
  void refreshLibrary()
  if (props.documentId) await openDocument(props.documentId)
}

onMounted(async () => {
  // Before anything else, because three of the seven kinds have REQUIRED fields
  // whose legal values only the server knows. Every creation path is disabled
  // until this resolves (cut list item 17 forbids a hardcoded fallback), so a
  // late load means a briefly-disabled palette rather than a graph the compiler
  // will reject.
  void loadVocabulary()
  await startBuilder()
})

watch(signedOut, (out) => {
  if (!out) void startBuilder()
})

watch(
  () => props.documentId,
  async (id) => {
    if (id && id !== persistence.documentId.value) await openDocument(id)
  },
)

async function refreshLibrary(): Promise<void> {
  try {
    library.value = await builderApi.list()
  } catch {
    // The palette's library list degrades to empty. It is a convenience list;
    // `TemplateGallery` is where a failure to read your own graphs is REPORTED,
    // because that is the screen whose whole job is opening one.
    library.value = []
  }
}

/**
 * Show the canvas with the whole graph in view.
 *
 * `fit-view-on-init` is not enough on its own and the reason is a sequencing
 * one: the canvas is only mounted when `started` flips, so Vue Flow's init fit
 * runs against a graph whose nodes have not been projected and measured yet.
 * It fits nothing, and nothing ever fits again - which is why a 16-node
 * template opened with its last two nodes below the bottom edge.
 *
 * And it has to wait for PAINT, not just for ticks. Two `nextTick`s do mount
 * the canvas and project the nodes, but the budget meter and the problems dock
 * have not taken their height yet, so the canvas is still full-bleed and the
 * fit is computed against a box taller than the one it ends up in. Measured on
 * the 16-node validator template: fitting after ticks alone chose scale 0.544
 * and left the last node under the dock, where fitting once the rows had
 * settled chose 0.466 and showed the whole graph. Both are "a fit" - only one
 * of them fits the container that exists a frame later.
 *
 * Two frames rather than one, for the same reason there are two ticks: the
 * first frame paints the new rows, the second measures against them.
 */
async function showGraph(): Promise<void> {
  started.value = true
  await nextTick()
  await new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
  })
  canvas.fitView()
  /*
   * Ask the compiler about this document, now, before the author touches it.
   *
   * `useBuilderValidation` watches the document's FINGERPRINT, so a document
   * that arrives equal to the one the loop mounted with never moves the
   * watcher. That is not a hypothetical: `store` is seeded from BLANK, and
   * "Blank canvas" hands over BLANK - so the one card a first-time visitor is
   * most likely to click produced a canvas that had never been validated,
   * reading `Ready to publish` with Publish enabled over a graph the server
   * refuses with `no-input-node`. Every other template differs from the seed
   * and validated by accident, which is why 988 green tests never saw it.
   *
   * This is the kick the composable's own `idle` docstring always described.
   * The second lock is in the composable: `idle` now blocks publish outright.
   */
  validation.validateNow()
}

async function openDocument(id: DocumentId): Promise<void> {
  try {
    await persistence.open(id)
    await afterAdopt()
  } catch (error) {
    say(error instanceof Error ? error.message : 'that graph could not be opened.', { kind: 'error' })
  }
}

/**
 * What every stored document goes through once `persistence.adopt` has it -
 * a route open, an import, a duplicate followed through the route. One tail,
 * so a third entry point cannot forget the fit or the validation kick.
 */
async function afterAdopt(): Promise<void> {
  publishProblems.value = []
  deleteAsk.value = false
  await showGraph()
}

/**
 * Seed a template as an ordinary unsaved draft.
 *
 * `applyTemplate` and `startNew` together, and both are needed: the first
 * replaces the document and clears the history so the template is not something
 * you can undo your way out of into a blank canvas, and the second forgets the
 * previously-open document's id and version so the next save CREATES rather
 * than overwriting whatever was open before.
 */
function startTemplate(template: BuilderTemplate): void {
  store.applyTemplate(documentFromTemplate(template))
  persistence.startNew()
  publishProblems.value = []
  versionsOpen.value = false
  deleteAsk.value = false
  void showGraph()
}

/* ── plan 15 D3: the version browser ───────────────────────────────────── */

async function loadVersions(): Promise<void> {
  const id = persistence.documentId.value
  if (id === null) {
    versions.value = []
    return
  }
  versionsLoading.value = true
  try {
    // Rendered in the server's order, newest first, and never re-sorted here:
    // a client that sorted would hide a server that stopped.
    versions.value = await builderApi.listVersions(id)
    versionsProblem.value = ''
  } catch (error) {
    versionsProblem.value = messageOf(error, 'the stored versions could not be read.')
  } finally {
    versionsLoading.value = false
  }
}

function toggleVersions(): void {
  versionsOpen.value = !versionsOpen.value
  if (versionsOpen.value) void loadVersions()
}

/** Open a stored version read-only. `persistence.adopt` sets the store's lock. */
async function viewVersion(version: number): Promise<void> {
  const id = persistence.documentId.value
  if (id === null || versionsBlocked.value) return
  if (version === persistence.version.value) return
  try {
    await persistence.open(id, version === persistence.headVersion.value ? undefined : version)
    publishProblems.value = []
    validation.validateNow()
  } catch (error) {
    // `kind: 'error'` was missing here and nowhere else on this path, so a
    // refused open rendered in the INFO colour with an info icon - the one
    // refusal on the version rail that did not look like one (D-15-22).
    say(messageOf(error, `v${version} could not be opened.`), { kind: 'error' })
  }
}

async function viewHead(): Promise<void> {
  await viewVersion(persistence.headVersion.value)
}

/**
 * Commit the version on screen as the NEXT head, through the ordinary CAS
 * save. History is append-only on the server, so this is v8 whose content is
 * v3's, with v4..v7 exactly where they were and head one Ctrl+Z away.
 */
async function restoreVersion(): Promise<void> {
  if (restoring.value || versionsBlocked.value) return
  const from = persistence.version.value
  restoring.value = true
  try {
    await persistence.restoreVersion()
    if (persistence.conflict.value === null && !persistence.error.value) {
      say(`restored v${from} as v${persistence.version.value} — head is one undo away.`, { kind: 'success' })
    }
  } catch (error) {
    say(messageOf(error, `v${from} could not be restored.`), { kind: 'error' })
  } finally {
    restoring.value = false
  }
}

/* ── plan 15 D1: export ────────────────────────────────────────────────── */

/**
 * Whether an action on the STORED document may proceed, saying why not.
 *
 * Export, duplicate and the version list all read what the server holds, and
 * a canvas that is ahead of it would hand the author a file, a copy or a list
 * missing their last edit with nothing on screen saying so.
 */
function storedIsCurrent(verb: string): boolean {
  // Both are REFUSALS with something for the author to do, so both carry
  // `kind: 'error'` and both persist (D-15-22). They rendered in the info
  // colour with an info icon, which is the same mismatch the row calls out at
  // the version-open site - found here by the test for that rule rather than
  // by the critic, because a refusal that does not look like one is exactly
  // what "no persistent surface to re-read it" hides.
  if (persistence.documentId.value === null) {
    say(`save this graph first — ${verb} works on the stored version.`, { kind: 'error' })
    return false
  }
  if (persistence.saveState.value !== 'clean') {
    say(
      `save your changes first — ${verb} works on the stored version, and the canvas is ahead of it.`,
      { kind: 'error' },
    )
    return false
  }
  return true
}

async function exportDocument(): Promise<void> {
  if (!storedIsCurrent('export')) return
  const id = persistence.documentId.value as DocumentId
  try {
    const envelope = await builderApi.exportWorkflow(
      id,
      persistence.viewingVersion.value ? persistence.version.value : undefined,
    )
    downloadExport(envelope)
    say(
      `exported ${exportFilename(envelope.name)} — credentials stripped, ${envelope.needs_credentials.length} node${envelope.needs_credentials.length === 1 ? '' : 's'} will need one on import.`,
      { kind: 'success' },
    )
  } catch (error) {
    say(messageOf(error, 'the export could not be written.'), { kind: 'error' })
  }
}

/* ── plan 15 D2: import, through the one load path ─────────────────────── */

/**
 * A `.builder.json` becomes a NEW draft owned by the importer (ruling S1-7).
 *
 * Two refusals, kept apart on purpose. `readExportFile` refuses a file that
 * is not an export at all - the wrong `export` field, no `document` - with a
 * sentence naming the FILE, and nothing is sent. `POST /import` refuses the
 * document inside it, in the server's own words. Neither path touches the
 * canvas: the document on screen survives a bad import untouched.
 *
 * The 201 is opened through `persistence.adopt`, the same call a route open
 * makes, so an imported graph and a stored one are one code path from here on.
 */
async function importFile(file: File): Promise<void> {
  let envelope: BuilderExportEnvelope
  try {
    envelope = await readExportFile(file)
  } catch (error) {
    say(
      error instanceof ExportFileError
        ? error.message
        : `${file.name} could not be read — ${messageOf(error, 'the browser refused the file')}`,
      { kind: 'error' },
    )
    return
  }
  let result: BuilderDocumentModel & { needs_credentials: string[] }
  try {
    result = await builderApi.importWorkflow(envelope)
  } catch (error) {
    say(`${file.name} was not imported — ${messageOf(error, 'the server refused it')}`, { kind: 'error' })
    return
  }
  persistence.adopt(result)
  importNotice.value =
    result.needs_credentials.length > 0
      ? { documentId: result.id as DocumentId, nodeIds: [...result.needs_credentials] }
      : null
  versionsOpen.value = false
  void refreshLibrary()
  await afterAdopt()
  // The new document's name IN FULL - it may carry an ` imported` the file did
  // not (D-15-4), and it is the one fact that finds the row in the library.
  say(`imported ${file.name} as a new draft, “${result.document.name}”.`, { kind: 'success' })
}

function dismissImportNotice(): void {
  importNotice.value = null
}

/**
 * Take the author to the credential picker on the first node that needs one
 * (round 3, D-15-19).
 *
 * The notice could already point at each node, and pointing selects it - but
 * the thing to actually DO then sat unnamed in an inspector the author had to
 * find. `InspectorRail.focusField` was written for exactly this journey and
 * had no caller anywhere in `src/`; this is it.
 *
 * Two steps, and the order matters: selecting the node is what mounts the
 * agent form the credential row lives on, so the field cannot be focused
 * until the selection has rendered - `focusField` awaits a tick of its own
 * for that reason and reports whether it found the row.
 */
async function openCredentialPicker(nodeId: string): Promise<void> {
  canvas.focusNode(nodeId as NodeId)
  await inspectorRef.value?.focusField('credential_id')
}

/* ── plan 15 D3: duplicate and delete ──────────────────────────────────── */

/**
 * `<name> copy`, version 1, draft, then opened THROUGH THE ROUTE - the same
 * path the gallery takes - so the address names the copy and Back returns to
 * the original. The 201 body is read only for its id.
 */
async function duplicateDocument(): Promise<void> {
  if (!storedIsCurrent('duplicate')) return
  const id = persistence.documentId.value as DocumentId
  try {
    const copy = await builderApi.duplicateWorkflow(
      id,
      persistence.viewingVersion.value ? persistence.version.value : undefined,
    )
    void refreshLibrary()
    say(`duplicated as “${copy.document.name}”.`, { kind: 'success' })
    emit('openDocument', copy.id as DocumentId)
  } catch (error) {
    say(messageOf(error, 'the graph could not be duplicated.'), { kind: 'error' })
  }
}

/**
 * What the store says about this graph's life, for the delete strip's copy
 * (D-15-16).
 *
 * Three states, and the strip said the same thing in all of them: on a plain
 * DRAFT it warned "A published graph cannot be deleted; unpublish it first",
 * a sentence that cannot apply to what is on screen, and on a published head
 * it said nothing until the author had typed the name and pressed Delete -
 * so the one case the warning was written for was the one case it arrived
 * too late for.
 *
 * `publishedVersion` is knowledge rather than a field (see
 * `useBuilderPersistence`): a load or a publish proves a version is live, and
 * a `status` of `published` with no number proves only that SOME version was.
 * Both mean a delete will be refused, so both count as live here; the number
 * is used when there is one and the wording stays true when there is not.
 */
const deleteLiveVersion = computed<number | null>(() =>
  persistence.publishedVersion.value ?? null,
)
const deleteWillBeRefused = computed(
  () => deleteLiveVersion.value !== null || persistence.status.value === 'published',
)

/**
 * Ask to delete - or say why not, before the work rather than after it.
 *
 * A delete the server is going to refuse opens the strip already in its
 * refused state, with the remedy (Unpublish) rather than a name box. The
 * server is still the authority: `confirmDelete` handles the 409 exactly as
 * before, and this only stops the author typing a name into a form whose
 * answer is already known.
 */
function askDelete(): void {
  if (persistence.documentId.value === null) return
  deleteAsk.value = true
  deleteTyped.value = ''
  if (deleteWillBeRefused.value) {
    deleteRefused.value = true
    deleteProblem.value = deleteLiveVersion.value === null
      ? `“${doc.value.name}” is live and cannot be deleted; unpublish it first, then delete it`
      : `“${doc.value.name}” is live as v${deleteLiveVersion.value} and cannot be deleted; `
        + 'unpublish it first, then delete it'
    return
  }
  deleteProblem.value = ''
  deleteRefused.value = false
}

/**
 * `POST /workflows/{id}/unpublish`: the graph leaves service, the head
 * returns to draft, and the document on screen is untouched (decision 24,
 * D-15-10). Reached from the menu and from the delete confirm's refusal; from
 * the confirm, a success puts the confirm back the way it was - typed name
 * kept - so the delete the author asked for is one more click, not a fresh
 * start.
 */
async function unpublishDocument(): Promise<void> {
  const id = persistence.documentId.value
  if (id === null || unpublishing.value) return
  unpublishing.value = true
  try {
    await builderApi.unpublish(id)
    persistence.noteUnpublished()
    publishProblems.value = []
    if (deleteRefused.value) {
      deleteRefused.value = false
      deleteProblem.value = ''
    }
    if (versionsOpen.value) void loadVersions()
    void refreshLibrary()
    say(`unpublished “${doc.value.name}” — it no longer answers launches.`, { kind: 'success' })
  } catch (error) {
    const message = messageOf(error, 'the graph could not be unpublished.')
    if (deleteAsk.value) deleteProblem.value = message
    else say(message, { kind: 'error' })
  } finally {
    unpublishing.value = false
  }
}

function cancelDelete(): void {
  deleteAsk.value = false
  deleteTyped.value = ''
  deleteProblem.value = ''
  deleteRefused.value = false
}

/**
 * `DELETE /workflows/{id}`: the row and every version go together
 * (`ON DELETE CASCADE`), and the canvas goes back to the gallery.
 *
 * A 409 is the one refusal with no retry: the head is published and
 * registered, and a registered workflow with no document cannot be
 * rehydrated. The sentence is the server's, verbatim, and the only control
 * left is the one that closes the confirm.
 */
async function confirmDelete(): Promise<void> {
  const id = persistence.documentId.value
  if (id === null || !deleteConfirmed.value || deleteInFlight.value || deleteRefused.value) return
  deleteInFlight.value = true
  const name = doc.value.name
  try {
    await builderApi.remove(id)
    cancelDelete()
    versionsOpen.value = false
    importNotice.value = null
    publishProblems.value = []
    persistence.startNew()
    // Clean, not a template: a template is seeded dirty, and a dirty document
    // nobody can see would arm `beforeunload` over a graph that is gone.
    store.load(documentFromTemplate(BLANK))
    started.value = false
    void refreshLibrary()
    emit('closeDocument')
    say(`deleted “${name}”.`, { kind: 'success' })
  } catch (error) {
    deleteProblem.value = messageOf(error, 'the graph could not be deleted.')
    deleteRefused.value = error instanceof BuilderConflictError
  } finally {
    deleteInFlight.value = false
  }
}

/* A swallowed gesture is never silent. Every write funnels through
 * `store.commit`, so this one watcher covers the canvas, the inspector, the
 * hotkeys, the clipboard and the port menu at once. */
watch(
  () => store.lockedRefusals.value,
  () => {
    if (store.readOnly.value) {
      say(readOnlyNotice.value, {
        action: { label: `Back to v${persistence.headVersion.value}`, run: () => void viewHead() },
      })
    }
  },
)

/* A different document, or none: the list and the notice were about the old one. */
watch(
  () => persistence.documentId.value,
  (id) => {
    versions.value = []
    versionsProblem.value = ''
    if (id !== null && versionsOpen.value) void loadVersions()
  },
)

/**
 * The address follows the first save.
 *
 * `persistence.documentId` is null for a draft and is assigned exactly once,
 * by `adoptIdentity`, from the create response. Until this watcher existed the
 * hash stayed `#/build` forever: the chip read `saved · v1`, the localStorage
 * draft was keyed by an id the URL never carried, and a refresh landed on the
 * gallery with the work unreachable - the one place a draft key and an address
 * could disagree, and they did. The library path had always navigated
 * correctly, so the plumbing was never the problem; only the create path
 * failed to use it.
 *
 * Guarded on `props.documentId` being absent so that opening a document
 * through the route does not re-navigate to the address it arrived from.
 */
watch(
  () => persistence.documentId.value,
  (id) => {
    if (id && id !== props.documentId) emit('adoptDocument', id)
  },
)

function openFromGallery(id: string): void {
  // Through the route rather than straight to `openDocument`, so the address
  // bar names the graph. `#/build/:documentId` is the URL an author sends a
  // colleague, and one that silently stayed `#/build` would send them the
  // gallery instead.
  emit('openDocument', id as DocumentId)
}

/**
 * A library row's Versions / Duplicate / Export (D-15-15).
 *
 * The row used to offer a trash icon and nothing else, so every other action
 * cost an open first - and the one thing reachable in a single click from the
 * list was the destructive one.
 *
 * Each of these OPENS the graph and then does the thing, rather than acting on
 * a document nobody is looking at. That is not a limitation of the plumbing:
 * duplicate and export both refuse a canvas that is ahead of the store
 * (`storedIsCurrent`), and a version rail belongs beside the canvas it
 * describes. Acting on an unopened row would also make "Duplicate" the only
 * control in the product that changes something off screen.
 */
async function actOnLibraryRow(id: string, action: 'versions' | 'duplicate' | 'export'): Promise<void> {
  await openDocument(id as DocumentId)
  emit('adoptDocument', id as DocumentId)
  if (persistence.documentId.value !== (id as DocumentId)) return
  if (action === 'versions') {
    if (!versionsOpen.value) toggleVersions()
    return
  }
  if (action === 'duplicate') {
    await duplicateDocument()
    return
  }
  await exportDocument()
}

/* ── the one write path ────────────────────────────────────────────────── */

/** Every inspector patch, and the only place one becomes a commit (§2 WP-F). */
function applyInspectorCommit(change: InspectorCommit): void {
  store.commit(change.label, change.next, change.coalesceKey ?? null)
}

function onPortMenuCreate(creation: PortMenuCreation): void {
  store.addNode(creation.node, {
    edge: { source: creation.source, source_port: creation.sourcePort, target: creation.target },
    label: creation.label,
  })
  canvas.cancelPortMenu()
  canvas.selectNode(creation.node.id)
}

/**
 * Undo, and say what it removed for two seconds.
 *
 * The label is read BEFORE the undo, because `store.undoLabel` afterwards names
 * the command one step further back - announcing that would tell the author
 * they undid something they still have.
 *
 * The timer lives here rather than in `DocumentBar` because two deletes in a
 * row produce the same string, and Vue batches synchronous ref writes into one
 * callback that never fires for an unchanged value: a watcher in the bar would
 * announce the first and go silent on the second. Restarting the timer on every
 * undo is also the behaviour an author expects - the message follows the last
 * thing they did, not the first.
 */
function undo(): void {
  const label = store.undoLabel.value
  store.undo()
  window.clearTimeout(undoneTimer)
  undoneLabel.value = label
  if (!label) return
  undoneTimer = window.setTimeout(() => {
    undoneLabel.value = ''
  }, 2000)
}

/* ── publish and run ───────────────────────────────────────────────────── */

async function onPublished(result: BuilderPublish): Promise<void> {
  persistence.notePublished(result.version)
  publishProblems.value = []
  await refreshLibrary()
}

/**
 * Hand the run console this workflow and leave.
 *
 * The handoff rides in `sessionStorage` beside the route rather than inside it -
 * `useWorkspaceRoute`'s studio route is `{ name: 'studio' }` and belongs to
 * another package - and `StudioView` renders a strip naming the graph with a
 * control that clears it, so nothing about which workflow is loaded is hidden.
 */
function runPublished(workflowId: string, inputField: string): void {
  writeRunHandoff({ workflowId, inputField, name: doc.value.name }, props.user?.id ?? null)
  publishOpen.value = false
  emit('runWorkspace')
}

/* ── keyboard ──────────────────────────────────────────────────────────── */

useBuilderHotkeys(
  {
    undo,
    redo: () => store.redo(),
    save: () => void persistence.save(),
    publish: () => {
      publishOpen.value = true
    },
    validateNow: validation.validateNow,
    deleteSelection: canvas.deleteSelection,
    selectAll: canvas.selectAll,
    escape,
    leaveCanvas,
    /*
     * NODES ONLY, and the edges are not an omission. The clipboard keeps an
     * edge exactly when BOTH its endpoints were copied, which is a fact about
     * the selected nodes rather than about the selected edges - a lone edge on
     * the clipboard could only be pasted onto nodes it would then be a
     * duplicate of.
     */
    copy: () => void clipboard.copy(canvas.selectedNodeIds.value),
    cut: () => void clipboard.cut(canvas.selectedNodeIds.value),
    paste: () => void clipboard.paste(canvas.viewportCentre()),
    duplicate: () => void clipboard.duplicate(canvas.selectedNodeIds.value),
    insertKind: canvas.insertKind,
    renameFocused,
    linkFromFocused,
    nudge: canvas.nudge,
    /*
     * Tab walks the numbered candidates while a keyboard link is live, and the
     * graph's topological order otherwise. One key, two meanings, and the mode
     * decides - the same way Escape already means four things down a ladder.
     */
    traverse: (step) => {
      if (canvas.linkMode.value) canvas.cycleLink(step)
      else canvas.traverse(step)
    },
    confirmLink: canvas.commitLink,
    cycleSibling: canvas.cycleSibling,
    fitView: canvas.fitView,
    zoomToActual: canvas.zoomToActual,
    zoomToSelection: canvas.zoomToSelection,
    focusFilter,
    walkProblems,
    toggleShortcuts: () => {
      shortcutsOpen.value = !shortcutsOpen.value
    },
    toggleTheme: theme.toggleTheme,
  },
  { canvasHasFocus },
)

/**
 * `Shift+Escape` - the documented way out of the canvas.
 *
 * `BuilderCanvas` declares `role="application"` and the builder repurposes
 * `Tab` inside it for topological traversal, which is legitimate under WCAG
 * 2.1.1 and was argued for carefully in `useBuilderHotkeys`. What that argument
 * never covered is 2.1.2, No Keyboard Trap, a separate criterion with a
 * separate requirement: there must be a way OUT, and it must be discoverable.
 * There was not one. Focus entering the canvas never left it - Tab traversed
 * nodes forever, Shift+Tab traversed them backwards, and Escape cleared the
 * selection without moving focus - so 57 controls after the canvas in DOM order
 * became unreachable by keyboard for as long as the view was mounted.
 *
 * `blur()` rather than a hand-rolled focus advance: returning focus to the
 * document body puts `Tab` back under the browser's own sequential navigation,
 * which is the behaviour every other page on the web already has and the one an
 * author trying to escape is expecting. The sheet renders this row from the
 * binding table, so it is documented by construction.
 */
function leaveCanvas(): void {
  const active = document.activeElement
  if (active instanceof HTMLElement) active.blur()
  /*
   * Focus is HANDED to the problems dock, not merely dropped.
   *
   * A bare `blur()` returns focus to `<body>`, and the very next `Tab` lands on
   * the first focusable element in the document - which is a node wrapper
   * inside the canvas, so the author is back in the trap after one keystroke.
   * The dock's disclosure button is the first control AFTER the canvas in DOM
   * order, so handing focus there makes the remaining 50-odd controls - the
   * inspector's fields, the zoom buttons, both rail toggles - reachable by
   * ordinary sequential navigation, which is the whole of what 2.1.2 asks for.
   */
  const dock = document.querySelector<HTMLElement>('.problems-toggle')
  dock?.focus()
  say(
    dock
      ? 'left the canvas — focus is on the problems dock, and Tab moves through the page.'
      : 'left the canvas — Tab now moves through the page.',
  )
}

/**
 * §4.5's Escape ladder, in order: abort the live gesture, then clear the
 * selection, then close the topmost sheet.
 *
 * The order matters and it is the reverse of what feels natural. A connect drag
 * aborted by Escape must leave ZERO commits, so it has to be caught before
 * anything else can interpret the key - and a sheet closed while a drag is live
 * would strand the drag with nothing on screen to cancel it.
 */
function escape(): void {
  if (canvas.connectDrag.value || canvas.linkMode.value || canvas.portMenuRequest.value) {
    // `cancelConnect`, not `cancelPortMenu`. The old call cleared one of the
    // three refs a live connect owns, so Escape left `connectDrag` set - the
    // container kept `.is-connecting`, two `port-ready` animations kept running
    // on an idle canvas, and this ladder was pinned on its first rung for the
    // rest of the session, so Escape could never clear a selection again.
    canvas.cancelConnect()
    return
  }
  if (canvas.selectionSize.value > 0) {
    canvas.clearSelection()
    return
  }
  if (deleteAsk.value) {
    cancelDelete()
    return
  }
  if (publishOpen.value) {
    publishOpen.value = false
    return
  }
  shortcutsOpen.value = false
}

/**
 * `R` - rename the focused node's label on the card.
 *
 * Focus rather than a store call: the card owns the contenteditable and commits
 * the result through `@rename`, so the shortcut's whole job is to put the caret
 * in it. Reaching into the store here would open a second rename path that the
 * card's own Escape-reverts contract knows nothing about.
 */
function renameFocused(): void {
  const id = canvas.anchorId.value ?? [...canvas.selectedNodeIds.value][0]
  if (!id) return
  canvas.requestRename(id)
}

/**
 * `E` - the keyboard half of connecting (section 4.1).
 *
 * Every legal target is numbered on its card, Tab walks them, Enter connects,
 * Escape aborts. Pressing `E` again while the mode is live cancels it, so the
 * key that starts the gesture also ends it.
 *
 * It used to call `canvas.onConnectStart` and stop there, which armed the
 * mouse's gesture from a keyboard that could never finish it: `connectDrag` is
 * cleared only by `onConnectEnd`, which no pointer event was ever going to
 * fire. The canvas was left `.is-connecting` forever with two infinite port
 * animations running and Escape permanently stuck on the abort rung.
 */
function linkFromFocused(): void {
  if (canvas.linkMode.value) {
    canvas.cancelConnect()
    say('link cancelled.')
    return
  }
  const id = canvas.anchorId.value ?? [...canvas.selectedNodeIds.value][0]
  if (!id) return
  const node = doc.value.nodes.find((candidate) => candidate.id === id)
  if (!node) return
  if (node.kind === 'output') {
    say(`${node.label} has no outgoing port to link from.`)
    return
  }
  const count = canvas.beginLink(id)
  if (count === 0) {
    say(`nothing left for ${node.label} to connect to - every legal target already has that edge.`)
    return
  }
  say(`${count} ${count === 1 ? 'target' : 'targets'}: Tab to choose, Enter to connect, Esc to abort.`)
}

/**
 * `/` - focus the node filter (section 4.5).
 *
 * The selector is `.builder-filter-input` and there is now a control behind it.
 * It used to read `.builder-palette input[type="search"]`, and `NodePalette`
 * contained no `<input>` at all - so the key did nothing, the `?.` swallowed
 * the miss, and `ShortcutSheet` advertised the binding anyway. The palette is
 * collapsible, so the rail is opened first: focusing a control inside a
 * `display: none` subtree silently fails and would put the key straight back
 * where it was.
 */
function focusFilter(): void {
  paletteCollapsed.value = false
  void nextTick(() => {
    document.querySelector<HTMLInputElement>('.builder-filter-input')?.focus()
  })
}

/**
 * An ISO timestamp as a local wall clock, for the restore bar's two times.
 *
 * Date and time when the draft is not from today, time alone when it is - the
 * bar's whole job is to answer "is what is in this browser newer than what is
 * on the server", and a full ISO string in two places makes that comparison
 * harder rather than easier.
 */
function clockOf(iso: string): string {
  const when = new Date(iso)
  if (Number.isNaN(when.getTime())) return iso
  const today = new Date()
  const sameDay =
    when.getFullYear() === today.getFullYear() &&
    when.getMonth() === today.getMonth() &&
    when.getDate() === today.getDate()
  return sameDay
    ? when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : when.toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
}

/** How many graph nodes the current query matches, for the filter box's count. */
const filterMatchCount = computed(
  () => canvas.nodes.value.filter((node) => node.data.filterMatch).length,
)

/** `F8` / `⇧F8` - the same path a `ProblemsPanel` row click takes. */
let problemCursor = -1
function walkProblems(step: 1 | -1): void {
  const list = problems.ordered.value
  if (list.length === 0) return
  problemCursor = (problemCursor + step + list.length) % list.length
  canvas.focusProblem(list[problemCursor])
}

/* ── what the cards and edges hand back ────────────────────────────────── */

function onNodeRename(payload: { id: string; label: string }): void {
  store.setLabel(payload.id as NodeId, payload.label)
}

function onToggleJoin(payload: { id: string }): void {
  canvas.toggleJoin(payload.id as NodeId)
}

function onInspectProblem(payload: { problem: BuilderProblem }): void {
  canvas.focusProblem(payload.problem)
}

function onSelectBranch(payload: { nodeId: string }): void {
  canvas.selectNode(payload.nodeId as NodeId)
}

/**
 * The edge's own hover-only delete button (02-canvas.md D4).
 *
 * Straight to `deleteSelection` with one edge id rather than "select it, then
 * delete the selection": the button names the edge it is drawn on, and routing
 * it through the selection would make the author's current selection collateral
 * damage of clicking an X they were pointing at. One commit, so one Ctrl+Z.
 */
function onDeleteEdge(payload: { edgeId: string }): void {
  store.deleteSelection([], [payload.edgeId as EdgeId])
}

function onEdgeSelectFromPanel(problem: BuilderProblem): void {
  canvas.focusProblem(problem)
}

/**
 * Where a palette click drops a node: the viewport centre, grid-snapped.
 *
 * `snapToGrid` on both axes rather than trusting Vue Flow's `snap-to-grid`,
 * because that prop only governs a DRAG. `Position` declares `int` in
 * `document.py` and pydantic coerces `120.0` but not `120.5`, so an unrounded
 * drop is a hard 422 that arrives on a later save, long after the click.
 */
function placeKind(kind: Parameters<typeof canvas.insertKind>[0]): void {
  const centre = canvas.viewportCentre()
  canvas.dropKind(kind, { x: snapToGrid(centre.x), y: snapToGrid(centre.y) })
}

/**
 * `PortMenu`'s three geometry props, from the one screen point the canvas
 * recorded.
 *
 * `onConnectEnd` has a `MouseEvent` and nothing else, so what it stores is
 * `clientX`/`clientY` - viewport pixels. The menu needs two other frames: `at`
 * is pixels inside the canvas host it is absolutely positioned in, and
 * `position` is FLOW coordinates, because that is where the node lands.
 * Converting here rather than in the composable keeps `useBuilderCanvas`
 * testable without a DOM, which is the whole reason its geometry lives behind
 * an attached bridge.
 *
 * `useVueFlow('builder-flow')` from this level is deliberate and is the same
 * instance `BuilderCanvas` mounts: the store is keyed by id, which is exactly
 * why §1.3 insists the two views use different ones.
 *
 * `snapToGrid` on both axes, again. `Position` declares `int` and pydantic
 * refuses `120.5`, so a node created from a drag that ended between two dots
 * would be a 422 arriving on a save minutes later.
 */
const flow = useVueFlow('builder-flow')

const portMenu = computed(() => {
  const request = canvas.portMenuRequest.value
  if (!request) return null
  const rect = flow.vueFlowRef.value?.getBoundingClientRect()
  const point = flow.screenToFlowCoordinate(request.at)
  return {
    origin: {
      // Always `source`: the only gesture that opens this menu is a drag that
      // LEFT an out-port. Retargeting an existing edge onto empty canvas is
      // `onEdgeUpdate`'s business and reverts rather than creating.
      direction: 'source' as const,
      node: request.origin.source,
      port: request.origin.source_port,
    },
    at: rect
      ? { x: request.at.x - rect.left, y: request.at.y - rect.top }
      : { x: request.at.x, y: request.at.y },
    position: { x: snapToGrid(point.x), y: snapToGrid(point.y) },
  }
})

/*
 * The problem index, published rather than threaded.
 *
 * `InspectorRail` and every `FieldProblem` inside it read this, and both throw
 * by name if it is absent - which is the right shape for a contract between two
 * packages: passing it as a prop would mean every form, every field row and
 * every control forwarding an index none of them chose to care about, and the
 * one that forgot would render a control with no problem under it and nothing
 * anywhere saying a problem existed. Hover and selection travel the same way
 * from `BuilderCanvas`, for the reason stated there: per-edge props would
 * rebuild both element arrays on every mousemove.
 */
provide(BUILDER_PROBLEMS, problems)

/* The notice channel, so a structural rewrite deep in an inspector can say what
 * it took with it. */
provide('builder-notice', notice)

watch(
  () => clipboard.notice.value,
  (message) => {
    if (message) say(message)
  },
)
</script>

<template>
  <a class="skip-link" href="#builder-canvas">Skip to the graph</a>
  <div
    class="studio-shell is-builder"
    :class="{
      'chat-is-collapsed': paletteCollapsed,
      'controls-are-collapsed': inspectorCollapsed,
      'is-gallery': !started,
    }"
  >
    <header class="app-header">
      <div class="brand-lockup">
        <div class="brand-mark" aria-hidden="true"><CircleDot :size="20" :stroke-width="1.8" /></div>
        <div>
          <span>M2</span>
          <h1>Flow builder</h1>
        </div>
      </div>

      <div class="header-context">
        <div class="segmented workspace-switch" role="group" aria-label="Workspace">
          <button type="button" :aria-pressed="true">
            <PenTool :size="14" aria-hidden="true" /> Build
          </button>
          <button type="button" :aria-pressed="false" @click="emit('runWorkspace')">
            <Play :size="14" aria-hidden="true" /> Run
          </button>
        </div>

        <!--
          One line, and never blank while something has happened. A denied
          clipboard, a branch deletion that took an edge with it, a graph that
          would not open - all three are things the author would otherwise
          discover by finding something missing.
        -->
        <div
          v-if="notice"
          class="builder-notice"
          :class="`is-${noticeKind}`"
          role="status"
          data-testid="builder-notice"
        >
          <component :is="noticeIcon" class="builder-notice-icon" :size="14" aria-hidden="true" />
          <span class="builder-notice-text" :title="notice">{{ notice }}</span>
          <button
            v-if="noticeAction"
            type="button"
            class="builder-notice-action"
            data-testid="notice-action"
            @click="runNoticeAction"
          >
            {{ noticeAction.label }}
          </button>
          <button
            type="button"
            class="icon-button builder-notice-dismiss"
            aria-label="Dismiss"
            title="Dismiss"
            data-testid="notice-dismiss"
            @click="dismissNotice"
          >
            <X :size="13" aria-hidden="true" />
          </button>
        </div>

        <!--
          The console's chip, in the console's place. Plan 01 D9 says "the
          document bar", but the bar exists only once a graph is open and the
          gallery has no bar at all - so an author on the empty state would
          have had no way to sign out while the run console, one click away,
          showed one in its header. Same element, same header row, in both
          workspaces.
        -->
        <AccountChip v-if="user" :user="user" @sign-out="emit('signOut')" />
      </div>
    </header>

    <!--
      Configured but signed out: the wall, where the gallery would be. Never
      reached under `App.vue`, which gates before routing; see `signedOut`.
    -->
    <SignInPanel
      v-if="signedOut"
      class="builder-signin"
      :signing-in="signingIn"
      :error="signInError"
      @sign-in="emit('signIn')"
    />

    <main v-else class="studio-main">
      <NodePalette
        v-if="started"
        class="builder-palette"
        :budget="validation.budget.value"
        :library="library"
        :open-document-id="persistence.documentId.value"
        :filter="canvas.filterQuery.value"
        :filter-matches="filterMatchCount"
        :read-only="persistence.viewingVersion.value"
        @place="placeKind"
        @open="openFromGallery"
        @update:filter="canvas.filterQuery.value = $event"
      />

      <section id="builder-canvas" class="graph-workspace" aria-label="Flow builder" tabindex="-1">
        <template v-if="started">
          <DocumentBar
            :name="doc.name"
            :save-state="persistence.saveState.value"
            :version="persistence.version.value"
            :status="persistence.status.value"
            :published-version="persistence.publishedVersion.value"
            :published-here="persistence.publishedHere.value"
            :can-undo="store.canUndo.value"
            :can-redo="store.canRedo.value"
            :undo-label="store.undoLabel.value"
            :redo-label="store.redoLabel.value"
            :undone-label="undoneLabel"
            :max-name-chars="vocabulary?.bounds.max_name_chars ?? 80"
            :document-id="persistence.documentId.value"
            :versions-open="versionsOpen"
            :read-only="persistence.viewingVersion.value"
            :head-version="persistence.headVersion.value"
            @rename="store.setName"
            @save="() => void persistence.save()"
            @undo="undo"
            @redo="store.redo"
            :theme="theme.resolved.value"
            @publish="publishOpen = true"
            @shortcuts="shortcutsOpen = true"
            @theme="theme.toggleTheme"
            @versions="toggleVersions"
            @export="exportDocument"
            @import="importFile"
            @duplicate="duplicateDocument"
            @unpublish="unpublishDocument"
            @delete="askDelete"
          >
            <template #save-chip>
              <SaveChip
                :state="persistence.saveState.value"
                :version="persistence.version.value"
                :head-version="persistence.headVersion.value"
                :error="persistence.error.value"
                :draft-dropped="persistence.draftDropped.value"
                :viewing="persistence.viewingVersion.value"
              />
            </template>
          </DocumentBar>

          <!--
            The DOCK: one grid row under the bar holding every strip that has
            to sit above the canvas IN THE LAYOUT rather than over it - the
            version browser, the restore bar, the import notice and the delete
            confirm. One wrapper rather than four siblings, because
            `.graph-workspace` names its rows by position and a conditional
            sibling used to push the canvas into an implicit `auto` row the
            moment the restore bar appeared. R15: nothing here covers the graph
            it is about.
          -->
          <div ref="dockEl" class="builder-dock" data-testid="builder-dock">
            <VersionBrowser
              v-if="versionsOpen"
              :versions="versions"
              :version="persistence.version.value"
              :head-version="persistence.headVersion.value"
              :loading="versionsLoading"
              :problem="versionsProblem"
              :restoring="restoring"
              :document-id="persistence.documentId.value"
              :blocked="versionsBlocked"
              @view="viewVersion"
              @head="viewHead"
              @restore="restoreVersion"
              @close="versionsOpen = false"
            />

            <!--
              Section 4.6's restore bar, and the reason it is here rather than
              anywhere else: it must sit above the canvas it is offering to
              replace, in the layout, so accepting it is a decision made while
              looking at what is on screen.

              `restoreOffer`, `acceptRestore` and `dismissRestore` all existed and
              were unit-tested for months while NO component read them - so a
              draft was written to `localStorage` on every commit and could never
              be got back out. The composable tests passed because they called the
              composable; nothing mounted anything. That is this repo's own "tests
              that pass for the wrong reason", and the fix is a rendered control
              with an E2E-addressable testid, not another composable test.
            -->
            <div
              v-if="persistence.restoreOffer.value"
              class="builder-restore"
              role="status"
              data-testid="restore-bar"
            >
              <RotateCcw :size="14" aria-hidden="true" />
              <span class="builder-restore-copy">
                Unsaved work from this browser, saved
                <time :datetime="persistence.restoreOffer.value.savedAt">{{
                  clockOf(persistence.restoreOffer.value.savedAt)
                }}</time>
                — the stored v{{ persistence.restoreOffer.value.baseVersion }} is from
                <time :datetime="persistence.restoreOffer.value.storedAt">{{
                  clockOf(persistence.restoreOffer.value.storedAt)
                }}</time
                >.
              </span>
              <button
                type="button"
                class="builder-restore-accept"
                data-testid="restore-accept"
                @click="persistence.acceptRestore"
              >
                Restore it
              </button>
              <button
                type="button"
                class="builder-restore-dismiss"
                data-testid="restore-dismiss"
                @click="persistence.dismissRestore"
              >
                Discard
              </button>
            </div>

            <!--
              Plan 15 D2's import notice (ruling S1-7): the nodes whose
              credential the export stripped, each a jump to its card. A
              notice group, not a problem code - the document opened honestly
              rather than green, and the fix is in the inspector, not here.
            -->
            <div
              v-if="importNoticeShown && importNotice"
              class="builder-import-notice"
              role="status"
              data-testid="import-notice"
            >
              <KeyRound :size="14" aria-hidden="true" />
              <span class="builder-import-copy">
                {{ importNotice.nodeIds.length }}
                {{ importNotice.nodeIds.length === 1 ? 'node needs' : 'nodes need' }} a credential you
                own — the export carried none.
              </span>
              <!--
                The one thing to DO, named (D-15-19). The per-node buttons
                below select a node; this opens the control that fixes it, on
                the first one, which is what the notice is for.
              -->
              <button
                type="button"
                class="builder-import-fix"
                data-testid="import-notice-fix"
                @click="openCredentialPicker(importNotice.nodeIds[0])"
              >
                Choose a key
              </button>
              <span class="builder-import-nodes">
                <button
                  v-for="id in importNotice.nodeIds"
                  :key="id"
                  type="button"
                  class="builder-import-node"
                  :data-testid="`import-notice-node-${id}`"
                  :title="`Select ${nodeLabel(id)}`"
                  @click="canvas.focusNode(id as NodeId)"
                >
                  {{ nodeLabel(id) }}
                </button>
              </span>
              <button
                type="button"
                class="icon-button builder-import-dismiss"
                aria-label="Dismiss the import notice"
                title="Dismiss"
                data-testid="import-notice-dismiss"
                @click="dismissImportNotice"
              >
                <X :size="14" aria-hidden="true" />
              </button>
            </div>

            <!--
              Plan 15 D3's delete confirm, DOCKED (R15). Never `window.confirm`:
              the browser dialog blocks the tab and hides the graph at the
              moment the author is being asked about it, and it cannot say WHICH
              graph in a way that survives a misread - typing the name is what
              proves the right one was read.
            -->
            <form
              v-if="deleteAsk"
              class="builder-delete-confirm"
              data-testid="delete-confirm"
              @submit.prevent="confirmDelete"
            >
              <!--
                The second sentence is the SERVER's rule in the server's words
                (D-15-10): `delete_document`'s 409 ends "cannot be deleted;
                unpublish it first, then delete it", and a confirm that
                promised anything else would be a remedy the server does not
                honour. `documentLifecycle.spec.ts` pins the shared clause.
              -->
              <label for="builder-delete-name" class="builder-delete-copy">
                <!--
                  DERIVED FROM THIS DOCUMENT'S STATE (D-15-16). This used to
                  warn "A published graph cannot be deleted; unpublish it
                  first" on every confirm, including a plain draft where the
                  sentence cannot apply - and it was the only warning, so on a
                  graph that really was published the author learnt the truth
                  only after typing the name. A graph that will be refused
                  never reaches this branch now: `askDelete` opens the strip
                  in its refused state with the remedy.
                -->
                <template v-if="!deleteRefused">
                  Delete <strong>{{ doc.name }}</strong> and every stored version of it? This
                  cannot be undone. Type <strong>{{ doc.name }}</strong> to confirm.
                </template>
                <!--
                  Nothing here when refused (D-15-18). This read "Not deleted
                  — it is still published." directly above the server's own
                  sentence, which since round 3 names the graph and says live
                  once - so the pair said published twice in two vocabularies
                  and neither of them named which graph.
                -->
              </label>
              <p
                v-if="deleteProblem"
                id="builder-delete-problem"
                class="builder-delete-problem"
                role="alert"
                data-testid="delete-problem"
              >
                {{ deleteProblem }}
              </p>
              <div class="builder-delete-actions">
                <input
                  v-if="!deleteRefused"
                  id="builder-delete-name"
                  v-model="deleteTyped"
                  type="text"
                  autocomplete="off"
                  :aria-describedby="deleteProblem ? 'builder-delete-problem' : undefined"
                  data-testid="delete-name"
                />
                <!--
                  The remedy the 409 names, where the 409 is read. Unpublish
                  lifts the refusal; the confirm then returns to its asking
                  state with the typed name kept.
                -->
                <button
                  v-if="deleteRefused"
                  class="button button-primary"
                  type="button"
                  :disabled="unpublishing"
                  data-testid="delete-unpublish"
                  @click="unpublishDocument"
                >
                  <Unplug :size="14" aria-hidden="true" />
                  {{ unpublishing ? 'Unpublishing…' : 'Unpublish' }}
                </button>
                <button
                  class="button button-quiet"
                  type="button"
                  data-testid="delete-cancel"
                  @click="cancelDelete"
                >
                  {{ deleteRefused ? 'Keep it published' : 'Keep it' }}
                </button>
                <button
                  v-if="!deleteRefused"
                  class="button button-danger"
                  type="submit"
                  :disabled="!deleteConfirmed || deleteInFlight"
                  data-testid="delete-submit"
                >
                  {{ deleteInFlight ? 'Deleting…' : 'Delete' }}
                </button>
              </div>
            </form>
          </div>

          <BudgetMeter
            :budget="validation.budget.value"
            :node-count="doc.nodes.length"
            :stale="validation.phase.value === 'stale'"
          />

          <BuilderCanvas :canvas="canvas" :label="doc.name" :read-only="persistence.viewingVersion.value" :dock="dockEl">
            <template #node="nodeProps">
              <BuilderNode
                v-bind="nodeProps"
                @rename="onNodeRename"
                @rename-started="canvas.noteRenameStarted"
                @toggle-join="onToggleJoin"
                @inspect-problem="onInspectProblem"
              />
            </template>
            <template #edge="edgeProps">
              <BuilderEdge
                v-bind="edgeProps"
                @select-branch="onSelectBranch"
                @delete="onDeleteEdge"
              />
            </template>
            <template #overlay>
              <PortMenu
                :open="portMenu !== null"
                :origin="portMenu?.origin ?? null"
                :at="portMenu?.at ?? { x: 0, y: 0 }"
                :position="portMenu?.position ?? { x: 0, y: 0 }"
                :taken-ids="new Set(doc.nodes.map((node) => node.id))"
                @create="onPortMenuCreate"
                @close="canvas.cancelPortMenu"
              />
            </template>
          </BuilderCanvas>

          <ProblemsPanel
            :problems="validation.problems.value"
            :phase="validation.phase.value"
            :reason="validation.unreachableReason.value"
            :publish-problems="publishProblems"
            :labels="anchorLabels"
            :viewing-version="readOnlyVersion"
            @focus="onEdgeSelectFromPanel"
          />
        </template>

        <!--
          §5.6: the gallery IS the canvas's empty state, centred on the same dot
          grid. Not a separate page, so picking a template loses nothing and
          going back costs nothing.
        -->
        <TemplateGallery
          v-else
          @start="startTemplate"
          @open="openFromGallery"
          @import="importFile"
          @versions="(id: string) => void actOnLibraryRow(id, 'versions')"
          @duplicate="(id: string) => void actOnLibraryRow(id, 'duplicate')"
          @export="(id: string) => void actOnLibraryRow(id, 'export')"
        />
      </section>

      <InspectorRail
        v-if="started"
        ref="inspectorRef"
        class="builder-inspector"
        :doc="doc"
        :vocabulary="vocabulary"
        :vocabulary-problem="vocabularyProblem"
        :selected-node-ids="[...canvas.selectedNodeIds.value]"
        :selected-edge-ids="[...canvas.selectedEdgeIds.value]"
        :read-only="persistence.viewingVersion.value"
        @commit="applyInspectorCommit"
        @notice="say"
      />

      <!--
        The two rail toggles, positioned into the canvas heading strip from
        either side by `studio.css`'s existing rules. They exist here for the
        same reason the console has them: at 1180px the inspector is the first
        thing an author wants out of the way, and at 860px the palette follows.
      -->
      <button
        v-if="started"
        class="rail-toggle icon-button"
        type="button"
        :aria-expanded="!paletteCollapsed"
        :aria-label="paletteCollapsed ? 'Expand the palette' : 'Collapse the palette'"
        :title="paletteCollapsed ? 'Expand the palette' : 'Collapse the palette'"
        @click="paletteCollapsed = !paletteCollapsed"
      >
        <ChevronRight v-if="paletteCollapsed" :size="17" aria-hidden="true" />
        <ChevronLeft v-else :size="17" aria-hidden="true" />
      </button>
      <button
        v-if="started"
        class="control-toggle icon-button"
        type="button"
        :aria-expanded="!inspectorCollapsed"
        :aria-label="inspectorCollapsed ? 'Expand the inspector' : 'Collapse the inspector'"
        :title="inspectorCollapsed ? 'Expand the inspector' : 'Collapse the inspector'"
        @click="inspectorCollapsed = !inspectorCollapsed"
      >
        <ChevronLeft v-if="inspectorCollapsed" :size="17" aria-hidden="true" />
        <ChevronRight v-else :size="17" aria-hidden="true" />
      </button>
    </main>

    <!--
      The two dialogs and the one overlay, and there are no others in the
      editing path (R15). Both dialogs cover the graph because both are about
      leaving it: publishing registers what is stored, and a conflict is a
      decision between two documents.
    -->
    <ConflictDialog
      v-if="persistence.conflict.value && persistence.documentId.value"
      :conflict="persistence.conflict.value"
      :mine="doc"
      :document-id="persistence.documentId.value"
      :load-head="persistence.loadHead"
      @discard="persistence.discardMine"
      @keep="persistence.keepMine"
    />

    <PublishDialog
      :open="publishOpen"
      :document="doc"
      :document-id="persistence.documentId.value"
      :error-count="blockingErrorCount"
      :save-state="persistence.saveState.value"
      :version="persistence.version.value"
      :head-version="persistence.headVersion.value"
      :phase="validation.phase.value"
      :budget="validation.budget.value"
      :published-version="persistence.publishedVersion.value"
      @close="publishOpen = false"
      @refused="publishProblems = $event"
      @focus-node="canvas.focusNode($event as NodeId)"
      @published="onPublished"
      @run="runPublished"
    />

    <ShortcutSheet :open="shortcutsOpen" @close="shortcutsOpen = false" />
  </div>
</template>

<style scoped>
/* Five rows, named by position. The console's `.graph-workspace` reserves 64px
   for its heading, an auto lane for the crew strip and the flow; the builder
   uses the first for `DocumentBar`, adds a DOCK row for the strips that sit
   above the canvas in the layout (version browser, restore bar, import notice,
   delete confirm), then `BudgetMeter`, the canvas, and a fifth for
   `ProblemsPanel` - real tracks rather than overlays, so an expanded problem
   list SHRINKS the canvas instead of covering the nodes it is describing.
   Covering the graph you are editing is the single failure this product is
   measured against.

   Every child is PINNED to its row. Before this, the rows were positional and
   the restore bar was a conditional sibling: the moment it rendered, the
   budget meter took the canvas's `1fr` and the canvas fell into an implicit
   `auto` row. A jsdom mount cannot see that; only a browser can. */
.graph-workspace {
  grid-template-rows: 64px auto auto minmax(0, 1fr) auto;
}
.graph-workspace > .document-bar { grid-row: 1; }
.graph-workspace > .builder-dock { grid-row: 2; }
.graph-workspace > .budget-meter { grid-row: 3; }
.graph-workspace > .builder-canvas { grid-row: 4; }
.graph-workspace > .problems-panel { grid-row: 5; }

.workspace-switch { grid-template-columns: auto auto; padding: 2px; }
.workspace-switch button { min-height: 28px; padding: 0 10px; font-size: var(--fs-12); }

/* A toast in the header row, in the layout (never over the canvas, R15): an
   icon that says which kind of line it is, room for two lines before an
   ellipsis so a document's name survives, an action when there is one, and a
   dismiss. Every value is a token; the three kinds are the three semantic
   colours the rest of the builder already uses. */
/*
 * OUT OF THE FLOW (D-15-14).
 *
 * The notice used to be an ordinary child of `.header-context`, which is the
 * right-hand item of a `space-between` header - so every notice widened that
 * group and pushed its own left-hand siblings LEFT. Measured by the critic:
 * the Build/Run toggle moved 314px after a duplicate, 322 after a restore and
 * 455 after an import, on every success. A persistent mode control that jumps
 * whenever something goes well is a control an author stops trusting the
 * position of, and it moves under the pointer they were about to click with.
 *
 * Absolute, centred in the header (which is already `position: relative`), so
 * it occupies no space in either group and the toggle's x is a property of the
 * toggle alone. The width is bounded well inside the gap between the brand
 * lockup and the context group so a long sentence truncates - which
 * `.builder-notice-text` already does - rather than colliding with either.
 */
.builder-notice {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  z-index: 1;
  display: inline-flex;
  gap: 8px;
  align-items: center;
  min-width: 0;
  max-width: min(56ch, 34vw);
  padding: 4px 4px 4px 10px;
  color: var(--text-body);
  font-size: var(--fs-12);
  line-height: 1.3;
  background: var(--surface-raised);
  border: 1px solid var(--border-default);
  border-radius: var(--r-lg);
}
.builder-notice-icon { flex: 0 0 auto; color: var(--text-muted); }
.builder-notice.is-success { border-color: color-mix(in srgb, var(--accent-mint) 42%, transparent); }
.builder-notice.is-success .builder-notice-icon { color: var(--accent-mint); }
.builder-notice.is-error { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }
.builder-notice.is-error .builder-notice-icon { color: var(--err-text); }
.builder-notice-text {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow-wrap: anywhere;
}
.builder-notice-action {
  flex: 0 0 auto;
  min-height: 24px;
  padding: 0 8px;
  color: var(--accent-cyan);
  font: 600 var(--fs-11)/1 var(--font-mono);
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--accent-cyan) 42%, transparent);
  border-radius: var(--r-md);
  cursor: pointer;
}
.builder-notice-action:hover { background: color-mix(in srgb, var(--accent-cyan) 14%, transparent); }
.builder-notice-dismiss { flex: 0 0 auto; width: 24px; height: 24px; }

/* The wall takes the shell's main row rather than its own viewport: the panel
   declares `min-height: 100vh` for the page it usually IS, and under a 52px
   header that would scroll the whole shell by a header's height. Two classes
   deep so this outranks the panel's own scoped rule at equal specificity. */
.studio-shell > .builder-signin { min-height: 0; }

/* Mirrors `.control-toggle` in `studio.css`, on the other side. Both sit in the
   64px heading strip and both outrank it on z-index, which is why that strip
   carries a 40px inset rather than 18px. */
.rail-toggle {
  position: absolute;
  z-index: 2;
  top: 13px;
  left: var(--chat-width);
  width: 32px;
  height: 38px;
  border-left: 0;
  border-radius: 0 var(--r-lg) var(--r-lg) 0;
}

.control-toggle {
  position: absolute;
  z-index: 2;
  top: 13px;
  right: var(--control-width);
  left: auto;
  width: 32px;
  height: 38px;
  border-right: 0;
  border-radius: var(--r-lg) 0 0 var(--r-lg);
}

@media (max-width: 860px) {
  .workspace-switch { display: none; }
}
</style>
