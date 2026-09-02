<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Keyboard, Redo2, Rocket, Undo2 } from 'lucide-vue-next'
import type { SaveState } from '../../composables/useBuilderPersistence'
import type { DocumentStatus } from '../../types/builder'

/**
 * The canvas's top strip: what this graph is called, whether it is saved,
 * what the last command was, and the one control that makes it runnable.
 *
 * It sits in the 64px row `.graph-workspace` already reserves for the run
 * console's own heading, so the two workspaces have their title in the same
 * place at the same height - which is most of what makes them read as one
 * product rather than two apps behind one login.
 *
 * PRESENTATIONAL, DELIBERATELY. Every value arrives as a prop and every gesture
 * leaves as an event, so this component holds no opinion about undo, about
 * saving or about publishing - `BuilderView` is the only place a gesture becomes
 * a `commit`, and a bar that reached into the store would be a second place.
 * The exception is the inline name editor, whose in-progress text is nobody
 * else's business until it is committed on blur or Enter.
 */

const props = defineProps<{
  name: string
  saveState: SaveState
  /** The stored version on screen. 0 until the first successful save. */
  version: number
  /** What the store says this document IS. */
  status: DocumentStatus
  /**
   * The version registered as runnable, or null when none is.
   *
   * Distinct from `status` on purpose - see `liveNote` below, which is the whole
   * reason both are props.
   */
  publishedVersion: number | null
  /** Whether THIS process holds the registration. See `liveNote`. */
  publishedHere: boolean
  canUndo: boolean
  canRedo: boolean
  /** The label of the command `⌘Z` would undo, for the tooltip. */
  undoLabel: string
  redoLabel: string
  /**
   * What the last undo removed, or `''`.
   *
   * `BuilderView` sets it and clears it two seconds later, rather than this
   * component holding a timer keyed on the prop changing. Undoing the same
   * command twice - two deletes in a row - produces the SAME string, and Vue
   * batches synchronous writes to a ref into one callback that never fires when
   * the value is unchanged: a watcher here would announce the first delete and
   * go silent on the second. The owner of the commit is the only place that
   * knows an undo happened at all.
   */
  undoneLabel: string
  /** Longest a document name may be. `BUILDER_MAX_NAME_CHARS`. */
  maxNameChars: number
}>()

const emit = defineEmits<{
  rename: [name: string]
  undo: []
  redo: []
  publish: []
  shortcuts: []
}>()

const editing = ref(false)
const draftName = ref('')
const nameInput = ref<HTMLInputElement | null>(null)

/**
 * What the last undo removed, as the bar prints it.
 *
 * Undo is the confirmation this builder offers instead of an "are you sure?"
 * dialog on delete, and that trade only works if the author can SEE what just
 * went. Without this, `⌘Z` on a graph scrolled away from the change is a
 * keystroke with no visible effect at all.
 */
const announcement = computed(() => (props.undoneLabel ? `Undid: ${props.undoneLabel}` : ''))

/**
 * The published-version note, and the two ways it can be uncomfortable.
 *
 * `status` is a STORED fact and `publishedHere` is a fact about this process's
 * registration maps, and they disagree after a restart: every push to `main`
 * redeploys the API, the five registration maps are process-local, and a graph
 * whose row still says `published` may hold no runtime on the instance
 * answering right now. Reporting only `status` would tell the author their
 * graph is live when a launch would 404; reporting only `publishedHere` would
 * make a redeploy look like their publish was undone. Both, honestly.
 */
const liveNote = computed(() => {
  if (props.publishedVersion === null) return ''
  if (props.status === 'published' && !props.publishedHere) {
    return `v${props.publishedVersion} is published but not registered here — republish it`
  }
  if (props.publishedVersion === props.version) return `v${props.publishedVersion} is live`
  return `v${props.publishedVersion} is live · you are on v${props.version}`
})

const liveIsCurrent = computed(
  () => props.publishedHere && props.publishedVersion === props.version,
)

async function startRename(): Promise<void> {
  draftName.value = props.name
  editing.value = true
  await nextTick()
  nameInput.value?.select()
}

function commitRename(): void {
  if (!editing.value) return
  editing.value = false
  const next = draftName.value.trim()
  // Empty is refused in the widget rather than sent: `name` is `min_length=1`
  // server-side, so a blank would be a 422 about a field the author can see
  // and would read as the builder losing their title.
  if (next.length === 0 || next === props.name) return
  emit('rename', next)
}

function cancelRename(): void {
  editing.value = false
  draftName.value = props.name
}
</script>

<template>
  <div class="document-bar">
    <div class="document-identity">
      <input
        v-if="editing"
        ref="nameInput"
        v-model="draftName"
        class="document-name-input"
        type="text"
        :maxlength="maxNameChars"
        aria-label="Graph name"
        @blur="commitRename"
        @keydown.enter.prevent="commitRename"
        @keydown.esc.prevent="cancelRename"
      />
      <button
        v-else
        class="document-name"
        type="button"
        :title="`Rename ${name}`"
        @click="startRename"
      >
        {{ name }}
      </button>

      <slot name="save-chip" />

      <span v-if="liveNote" class="live-note" :class="{ 'is-current': liveIsCurrent }">
        <i aria-hidden="true" />{{ liveNote }}
      </span>
    </div>

    <div class="document-actions">
      <!--
        `role="status"`, and it lives in the bar rather than as a floating toast
        because a toast over the canvas would cover the very node the undo just
        restored.
      -->
      <span class="undo-announcement" role="status" aria-live="polite">{{ announcement }}</span>

      <button
        class="icon-button"
        type="button"
        :disabled="!canUndo"
        :title="canUndo ? `Undo: ${undoLabel}` : 'Nothing to undo'"
        aria-label="Undo"
        @click="emit('undo')"
      >
        <Undo2 :size="15" aria-hidden="true" />
      </button>
      <button
        class="icon-button"
        type="button"
        :disabled="!canRedo"
        :title="canRedo ? `Redo: ${redoLabel}` : 'Nothing to redo'"
        aria-label="Redo"
        @click="emit('redo')"
      >
        <Redo2 :size="15" aria-hidden="true" />
      </button>
      <button
        class="icon-button"
        type="button"
        title="Keyboard shortcuts (?)"
        aria-label="Keyboard shortcuts"
        @click="emit('shortcuts')"
      >
        <Keyboard :size="15" aria-hidden="true" />
      </button>

      <button class="button button-primary document-publish" type="button" @click="emit('publish')">
        <Rocket :size="15" aria-hidden="true" />
        {{ publishedVersion === null ? 'Publish' : 'Republish' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.document-bar {
  position: relative;
  z-index: 9;
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  /* 40px matches `.canvas-heading` in `studio.css`, for the same reason it does
     there: the rail collapse toggles are absolutely positioned into this strip
     from either side and outrank it on z-index. */
  padding: 0 40px;
  background: linear-gradient(to bottom, rgba(26, 26, 26, 0.96), rgba(26, 26, 26, 0.78), transparent);
}

.document-identity { display: flex; min-width: 0; align-items: center; gap: 12px; }

.document-name,
.document-name-input {
  min-width: 0;
  max-width: 320px;
  padding: 5px 8px;
  color: var(--text-title);
  font: 600 17px/1.2 var(--font-display);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-md);
}

.document-name { overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; cursor: text; }
.document-name:hover { border-color: var(--border-default); }
.document-name-input { background: var(--surface-well); border-color: var(--accent-cyan); box-shadow: var(--glow-input); outline: 0; }

.live-note {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  color: var(--text-40);
  font: 600 var(--fs-11)/1 var(--font-mono);
  white-space: nowrap;
}
.live-note i { width: 7px; height: 7px; background: currentColor; border-radius: var(--r-full); }
/* Mint only when the live version IS the one on screen. Amber otherwise, which
   covers both divergences: an older version live, and a stored publish this
   process is not serving. */
.live-note.is-current { color: var(--accent-mint); }
.live-note:not(.is-current) { color: var(--warn-text); }

.document-actions { display: flex; flex-shrink: 0; align-items: center; gap: 8px; }
.document-actions .icon-button { border-radius: var(--r-md); }
.document-actions .icon-button:disabled { cursor: not-allowed; opacity: 0.42; }
.document-publish { min-height: 36px; }

.undo-announcement {
  min-width: 0;
  color: var(--text-muted);
  font-size: var(--fs-11);
  white-space: nowrap;
}
</style>
