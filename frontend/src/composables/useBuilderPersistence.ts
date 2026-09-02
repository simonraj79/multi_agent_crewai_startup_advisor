import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { BUILDER_SCHEMA_ID } from '../types/builder'
import type {
  BuilderDocument,
  BuilderDocumentModel,
  BuilderEdge,
  BuilderJoins,
  BuilderNode,
  DocumentId,
  DocumentStatus,
  NodeId,
} from '../types/builder'
import { BuilderConflictError, builderApi } from '../services/builderApi'
import type { BuilderApiLike } from '../services/builderApi'
import { fingerprint, toWire, wireBytes } from '../utils/builderSerialize'
import { vocabulary } from '../data/builderVocabulary'
import type { BuilderDocumentStore } from './useBuilderDocument'

/**
 * Getting an author's work out of this tab and into the database, and saying so
 * at every moment.
 *
 * Three separate stories live here because they are one story from the author's
 * side - "is my work safe?" - and answering it in three places is how a builder
 * ends up with a green tick over an unsaved document:
 *
 * 1. **The save**, with `expected_version` compare-and-set. Optimistic
 *    concurrency is the whole multi-user story (cut list item 11), so the 409
 *    is not an edge case, it is the design.
 * 2. **The local draft**, so a refresh, a crash or a closed laptop does not
 *    cost the last 2.5 seconds. Offered back only under a condition strict
 *    enough to be safe, and DISCARDED rather than merged when it is not.
 * 3. **The chip**, which is never silent. `saveState` has five values and every
 *    one of them is rendered; there is no sixth meaning "something went wrong
 *    and we are not saying".
 *
 * THE INVARIANT THIS FILE EXISTS TO KEEP is spec §1.1's fifth:
 * `expected_version` comes only from a server RESPONSE, never from
 * `doc.version`. The server assigns both the id and the version on every write,
 * so the copy on the document is whatever it was last parsed against - and on a
 * `/validate` round trip that is not the stored version at all. `version` below
 * is written in exactly two places, both of them holding a
 * `BuilderDocumentModel` that came off the wire.
 */

/** Spec §2 WP-B. Long enough that a sentence being typed is one save, short enough to be a safety net. */
const AUTOSAVE_IDLE_MS = 2500

/** `builder-draft:<id>`. One key per document, so two tabs on two graphs do not fight. */
const DRAFT_PREFIX = 'builder-draft:'

/** The stored-draft envelope. Versioned, because a shape change must discard rather than misread. */
interface StoredDraft {
  v: 1
  /** The server version this draft was edited FROM. The whole restore condition. */
  baseVersion: number
  /** ISO, so the restore bar can show the author both timestamps. */
  savedAt: string
  document: unknown
}

/** What the restore bar renders when a draft is genuinely offerable. */
export interface DraftOffer {
  savedAt: string
  baseVersion: number
  /**
   * When the server last wrote the version this draft was based on.
   *
   * Spec section 4.6 asks the bar for BOTH timestamps, and the reason is that
   * one of them alone answers the wrong question. "Unsaved work from 14:02" is
   * only meaningful beside "the stored copy is from 13:58" - the pair is what
   * tells an author whether the thing in the browser is ahead of the thing on
   * the server or a stale tab they left open yesterday.
   */
  storedAt: string
}

/** A 409, with everything `ConflictDialog` needs to start resolving it. */
export interface SaveConflict {
  /** The server's sentence, verbatim. */
  detail: string
  /** The version the server holds, or null when its sentence did not parse. */
  storedVersion: number | null
}

export type SaveState = 'clean' | 'dirty' | 'saving' | 'conflict' | 'offline'

/**
 * The save loop for one document.
 *
 * `document` is the store this writes; `api` is injected so tests never touch a
 * socket. The two are separate composables rather than one because the document
 * must be editable before anything has ever been stored - a template has no id,
 * no version and no head, and none of that stops an author drawing.
 */
export function useBuilderPersistence(
  document: BuilderDocumentStore,
  api: BuilderApiLike = builderApi,
) {
  /** Server-assigned, so null until a create comes back. `builder-draft:<id>` keys off it. */
  const documentId = shallowRef<DocumentId | null>(null)
  /**
   * The version the next PUT compares against - `expected_version` itself.
   *
   * 0 means "nothing is stored", which is not a version the schema allows
   * (`ge=1`) and so cannot be confused with one. It is assigned in exactly two
   * places, both from a `BuilderDocumentModel`.
   */
  const version = ref(0)
  const headVersion = ref(0)
  const status = ref<DocumentStatus>('draft')
  /**
   * Whether THIS EXACT version is registered on the process that answered.
   *
   * It can be false while `status` is `'published'`, and both are honest: a
   * restart clears the five in-process registration maps and nothing
   * re-registers them (backend gap §3d). `DocumentBar` renders the divergence
   * rather than picking a winner.
   */
  const publishedHere = ref(false)
  /**
   * The version known to be live, or null when this session has not been told.
   *
   * There is no `published_version` on the wire, so this is knowledge rather
   * than a field: a load that reports `published: true` proves it is the
   * version in hand, and a successful publish names its own. A load of a
   * document whose status is `'published'` but whose `published` flag is false
   * proves only that SOME version was, which is exactly the divergence above
   * and is not a number.
   */
  const publishedVersion = ref<number | null>(null)

  const saving = ref(false)
  const conflict = shallowRef<SaveConflict | null>(null)
  /**
   * Why the last save did not land, as the server's own sentence or the
   * transport's.
   *
   * `saveState` has five values and none of them is "refused", so this is what
   * stops `offline` from being a lie in the rarer case: a 413 over
   * `max_document_bytes` or a 422 on a malformed document is not a network
   * failure, and `SaveChip` renders this sentence instead of the offline
   * wording when it is set. One state, two truthful readings, and never a
   * silent one.
   */
  const error = ref('')
  /** True when a draft was too big to keep locally. The chip says so; §5.6 forbids a silent drop. */
  const draftDropped = ref(false)
  const restoreOffer = shallowRef<DraftOffer | null>(null)
  /**
   * The offered draft, held in memory rather than re-read on accept.
   *
   * Re-reading would find nothing: adopting a server response replaces the
   * document, the watcher below writes a fresh draft for the new baseVersion,
   * and the recovery the bar is offering would have been overwritten by the
   * time the author clicked it. Holding the candidate means the bar's promise
   * survives its own side effects.
   */
  const pendingRestore = shallowRef<BuilderDocument | null>(null)

  const dirty = document.dirty

  const saveState = computed<SaveState>(() => {
    if (conflict.value) return 'conflict'
    if (saving.value) return 'saving'
    if (error.value) return 'offline'
    return dirty.value ? 'dirty' : 'clean'
  })

  let idleTimer = 0

  function cancelAutosave(): void {
    window.clearTimeout(idleTimer)
    idleTimer = 0
  }

  /**
   * Arm the idle autosave, if there is anything to autosave TO.
   *
   * Three conditions, and each is a different kind of "not yet":
   * - no id means nothing is stored, and a create is a decision the author
   *   makes with Ctrl+S rather than one a timer makes for them;
   * - a save in flight already covers the current document, and the watcher
   *   re-arms when it lands;
   * - a conflict freezes the loop entirely, because every autosave under an
   *   unresolved 409 is another 409 and the dialog would never be readable.
   */
  function scheduleAutosave(): void {
    cancelAutosave()
    if (!dirty.value || documentId.value === null || saving.value || conflict.value) return
    idleTimer = window.setTimeout(() => {
      idleTimer = 0
      void save()
    }, AUTOSAVE_IDLE_MS)
  }

  /* --- the local draft --------------------------------------------------- */

  function draftKey(id: DocumentId): string {
    return `${DRAFT_PREFIX}${id}`
  }

  /**
   * Write the current document to `localStorage`, or drop it and say so.
   *
   * Every branch here is a failure this must survive rather than propagate. A
   * private window throws on `setItem`; a quota-full origin throws; a document
   * over `max_document_bytes` would be refused by the server anyway and is not
   * worth the quota. In all three cases the EDIT still lands - a storage
   * failure that reached the commit path would make the canvas unusable to
   * protect a convenience.
   *
   * A dropped draft REMOVES any existing key rather than leaving the last small
   * one behind. A stale draft claiming a current `baseVersion` is the one thing
   * worse than no draft: it would be offered on the next load and would restore
   * work the author has since moved past.
   */
  function writeDraft(): void {
    const id = documentId.value
    if (id === null) return

    const limit = vocabulary.value?.bounds.max_document_bytes
    if (limit !== undefined && wireBytes(document.doc.value) > limit) {
      draftDropped.value = true
      try {
        window.localStorage.removeItem(draftKey(id))
      } catch {
        /* Nothing to do: the draft is unwritable and unremovable alike. */
      }
      return
    }

    const draft: StoredDraft = {
      v: 1,
      baseVersion: version.value,
      savedAt: new Date().toISOString(),
      document: toWire(document.doc.value),
    }
    try {
      window.localStorage.setItem(draftKey(id), JSON.stringify(draft))
      draftDropped.value = false
    } catch {
      draftDropped.value = true
    }
  }

  function removeDraft(): void {
    const id = documentId.value
    if (id === null) return
    try {
      window.localStorage.removeItem(draftKey(id))
    } catch {
      /* See writeDraft. */
    }
  }

  function readDraft(id: DocumentId): { draft: StoredDraft; document: BuilderDocument } | null {
    let raw: string | null
    try {
      raw = window.localStorage.getItem(draftKey(id))
    } catch {
      return null
    }
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw) as Partial<StoredDraft>
      if (parsed.v !== 1 || typeof parsed.baseVersion !== 'number') return null
      const restored = rehydrate(parsed.document, id)
      if (!restored) return null
      return { draft: parsed as StoredDraft, document: restored }
    } catch {
      return null
    }
  }

  /**
   * Offer the draft back, but only when it is provably about the same head.
   *
   * The condition is `draft.baseVersion === head_version`, and it is strict on
   * purpose. A draft edited from v4 while somebody else stored v5 describes a
   * document that no longer exists; restoring it would silently discard their
   * work, and MERGING it - taking some nodes from each - is the one thing spec
   * §4.6 forbids outright, because nothing on the client knows which of two
   * edits to the same node the author meant.
   *
   * A draft whose content already equals what the server sent is not offered
   * either. It is not a recovery, it is the same document, and a bar asking
   * whether to restore what is already on screen teaches an author to dismiss
   * the bar without reading it - which is exactly when it will matter.
   */
  function considerDraft(id: DocumentId, model: BuilderDocumentModel): void {
    restoreOffer.value = null
    pendingRestore.value = null

    const found = readDraft(id)
    if (!found) return
    if (found.draft.baseVersion !== model.head_version) {
      removeDraft()
      return
    }
    if (fingerprint(found.document) === fingerprint(document.doc.value)) return

    pendingRestore.value = found.document
    restoreOffer.value = {
      savedAt: found.draft.savedAt,
      baseVersion: found.draft.baseVersion,
      storedAt: model.updated_at,
    }
  }

  /** Take the draft. It is based on head, so the version in hand is still the right one to save against. */
  function acceptRestore(): void {
    const restored = pendingRestore.value
    restoreOffer.value = null
    pendingRestore.value = null
    if (!restored) return
    document.load(restored, { dirty: true })
  }

  /** Decline it, and take it out of the browser so the same bar cannot appear twice. */
  function dismissRestore(): void {
    restoreOffer.value = null
    pendingRestore.value = null
    removeDraft()
  }

  /* --- adopting a server response ---------------------------------------- */

  /**
   * Take everything a `BuilderDocumentModel` knows, and NOTHING it does not.
   *
   * This is the only place `version` is written, which is what makes spec
   * §1.1's fifth invariant checkable rather than aspirational: there is one
   * assignment, its argument is a response, and a test that tampers with
   * `doc.version` can prove the PUT body was unmoved.
   */
  function adoptIdentity(model: BuilderDocumentModel): void {
    documentId.value = model.id as DocumentId
    version.value = model.version
    headVersion.value = model.head_version
    status.value = model.status
    publishedHere.value = model.published
    if (model.status === 'draft') publishedVersion.value = null
    else if (model.published) publishedVersion.value = model.version
  }

  /**
   * Load a stored document into the session, clean, and consider its draft.
   *
   * `document.load` rather than `commit`, because opening a different document
   * is not an edit: an undo across it would restore a version of another graph
   * into an editor addressing this one.
   */
  function adopt(model: BuilderDocumentModel): void {
    document.load(model.document)
    adoptIdentity(model)
    conflict.value = null
    error.value = ''
    considerDraft(model.id as DocumentId, model)
  }

  /** Fetch a document by id and adopt it. The `#/build/:documentId` entry point. */
  async function open(id: DocumentId, atVersion?: number): Promise<BuilderDocumentModel> {
    const model = await api.get(id, atVersion)
    adopt(model)
    return model
  }

  /**
   * Forget every stored fact, for a template or a brand-new graph.
   *
   * The document store is seeded separately (`applyTemplate`); this is the half
   * that stops the next Ctrl+S PUTting a template over whatever was open
   * before, which is the failure a shared `documentId` would produce silently.
   */
  function startNew(): void {
    cancelAutosave()
    documentId.value = null
    version.value = 0
    headVersion.value = 0
    status.value = 'draft'
    publishedHere.value = false
    publishedVersion.value = null
    conflict.value = null
    error.value = ''
    draftDropped.value = false
    restoreOffer.value = null
  }

  /** A successful publish is the other way this session learns which version is live. */
  function notePublished(publishedAt: number): void {
    publishedVersion.value = publishedAt
    status.value = 'published'
    if (publishedAt === version.value) publishedHere.value = true
  }

  /* --- the save ----------------------------------------------------------- */

  /**
   * Write the document, creating it if it has never been stored.
   *
   * The document is captured by REFERENCE before the request goes out, and that
   * reference is what decides whether the save cleaned anything. An author who
   * keeps typing during a 300ms round trip has a document the server has not
   * seen; marking it clean because a save succeeded would show `saved · v4`
   * over unsaved work, which is the single most expensive lie this chip could
   * tell. The identity comparison is exact because the document is immutable.
   *
   * A conflict does not touch the document. Nothing is reloaded, nothing is
   * merged, and no autosave fires again until `ConflictDialog` resolves it -
   * spec §4.6 is explicit that a 409 never auto-reloads, because the author's
   * only copy of their work is the one on screen.
   */
  async function save(): Promise<void> {
    if (saving.value || conflict.value) return
    cancelAutosave()
    document.sealHistory()

    const snapshot = document.doc.value
    const id = documentId.value
    saving.value = true
    try {
      const model =
        id === null ? await api.create(snapshot) : await api.save(id, snapshot, version.value)
      adoptIdentity(model)
      error.value = ''
      if (document.doc.value === snapshot) document.markSaved()
      // Rewritten rather than removed, so the key carries the NEW baseVersion.
      // A draft left behind at an older base is discarded on the next load and
      // the author is told nothing; one that matches head is simply not offered.
      writeDraft()
    } catch (failure) {
      if (failure instanceof BuilderConflictError) {
        conflict.value = { detail: failure.detail, storedVersion: failure.storedVersion }
      } else {
        error.value = failure instanceof Error ? failure.message : String(failure)
      }
    } finally {
      saving.value = false
      // Re-armed only when the save left work behind - the author typed during
      // the round trip. A failure deliberately does NOT re-arm: retrying every
      // 2.5s against a server that is down is a request loop nobody asked for,
      // and the next commit arms it again anyway.
      if (dirty.value && !error.value) scheduleAutosave()
    }
  }

  /* --- conflict resolution ------------------------------------------------ */

  /** Re-GET head so the dialog can diff against something real rather than guess. */
  async function loadHead(): Promise<BuilderDocumentModel> {
    const id = documentId.value
    if (id === null) throw new Error('loadHead: there is no stored document to compare against.')
    return api.get(id)
  }

  /**
   * Take the server's version, and leave the author's one Ctrl+Z away.
   *
   * A `commit` rather than a `load`, and that is the entire point: the head
   * document becomes the present and the author's displaced version stays on
   * the undo ring, so a single Ctrl+Z brings it back to copy from. A load would
   * clear the ring and the work would be gone with no warning that it had been.
   */
  function discardMine(head: BuilderDocumentModel): void {
    document.commit(`Loaded v${head.version} from the server`, head.document)
    adoptIdentity(head)
    document.markSaved()
    conflict.value = null
    error.value = ''
    writeDraft()
  }

  /**
   * Keep the author's version, and leave the server's one Ctrl+Z away.
   *
   * The mirror image, and the same principle: whatever is displaced goes onto
   * the ring. `load(head)` clears the history and puts the server's version in
   * hand, then the author's is committed over it - so the ring holds exactly
   * one entry, head, and one undo is a recovery of the work about to be
   * overwritten.
   *
   * `expected_version` is adopted from head BEFORE the re-PUT, which is what
   * makes the second attempt succeed rather than 409 again. It is still a
   * server-supplied number - it came out of `head`, which is a response.
   */
  async function keepMine(head: BuilderDocumentModel): Promise<void> {
    const mine = document.doc.value
    document.load(head.document)
    document.commit(`Kept your version over v${head.version}`, mine)
    adoptIdentity(head)
    conflict.value = null
    error.value = ''
    await save()
  }

  /* --- wiring ------------------------------------------------------------- */

  watch(document.doc, () => {
    writeDraft()
    scheduleAutosave()
  })

  /**
   * The last line of defence, and deliberately the weakest one.
   *
   * A browser shows its own wording for this, not ours, and a reload triggered
   * by the OS never asks at all - which is why the draft above exists and why
   * this is a courtesy rather than the mechanism.
   */
  function guardUnload(event: BeforeUnloadEvent): void {
    if (!dirty.value) return
    event.preventDefault()
    event.returnValue = ''
  }
  window.addEventListener('beforeunload', guardUnload)

  onScopeDispose(() => {
    cancelAutosave()
    window.removeEventListener('beforeunload', guardUnload)
  })

  return {
    documentId,
    version,
    headVersion,
    status,
    publishedHere,
    publishedVersion,
    saveState,
    error,
    conflict,
    draftDropped,
    restoreOffer,
    save,
    open,
    adopt,
    startNew,
    notePublished,
    loadHead,
    discardMine,
    keepMine,
    acceptRestore,
    dismissRestore,
  }
}

export type BuilderPersistence = ReturnType<typeof useBuilderPersistence>

/**
 * A stored draft turned back into a document, or null if it is not one.
 *
 * Everything that comes out of `localStorage` is untrusted input: it may have
 * been written by an older build with a different shape, hand-edited, or
 * truncated by a quota failure mid-write. The checks below are the minimum that
 * makes the result safe to hand to the canvas - anything subtler than "is this
 * the right shape" is `bounds.py`'s job and the document will be validated the
 * moment it loads anyway.
 *
 * The id is taken from the KEY, not from the payload. `builder-draft:<id>` is
 * how the draft was found, so a payload disagreeing with it is either corrupt
 * or someone else's, and neither should be able to redirect the next save.
 */
function rehydrate(raw: unknown, id: DocumentId): BuilderDocument | null {
  if (raw === null || typeof raw !== 'object') return null
  const wire = raw as Record<string, unknown>
  if (typeof wire.name !== 'string' || typeof wire.input_field !== 'string') return null
  if (!Array.isArray(wire.nodes) || !Array.isArray(wire.edges)) return null
  if (wire.joins === null || typeof wire.joins !== 'object' || Array.isArray(wire.joins)) return null
  const version = Number(wire.version)
  return {
    schema: BUILDER_SCHEMA_ID,
    id,
    name: wire.name,
    version: Number.isFinite(version) ? version : 1,
    input_field: wire.input_field as NodeId,
    nodes: wire.nodes as BuilderNode[],
    edges: wire.edges as BuilderEdge[],
    joins: wire.joins as BuilderJoins,
    budget: null,
  }
}
