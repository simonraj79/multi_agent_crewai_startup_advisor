<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BookOpen, LoaderCircle, Plus, Trash2, X } from 'lucide-vue-next'
import { attachmentsApi } from '../../services/attachmentsApi'
import type { AttachmentsApiLike } from '../../services/attachmentsApi'
import type { SkillDetail, SkillSummary } from '../../types/builder'
import { renderMarkdown } from '../../utils/markdown'

/**
 * The author's skill packs: the four this repository ships, and their own.
 *
 * A skill is KNOWLEDGE, not hands - its name and description load at run start
 * and its body loads only when a task matches - and the panel is written so
 * that distinction is visible rather than asserted. Four decisions:
 *
 * **Built-ins are listed first and cannot be edited.** A fresh account has
 * nothing else, and a palette whose first row is empty teaches an author that
 * the feature is empty. They belong to this repository, so `PUT` and `DELETE`
 * answer 404 for them and this renders no button that would produce one.
 *
 * **The body renders through the console's own escape-first renderer.** A skill
 * body is untrusted text in exactly the way a report body is - pasted by a
 * person, imported from an archive, and destined for a model's context - so it
 * goes through `utils/markdown.ts`, which escapes every character first and
 * only then recognises structure. A sanitiser applied after markup exists is
 * the opposite order and it is the one this repository has already argued
 * against.
 *
 * **A version is `v<n>` from the frontmatter**, because that is where a version
 * lives: the shipped `user_skills` table has no `version` column, so a `PUT`
 * bumps `metadata.version` in the file and the card reads it back. An author
 * who opens their own pack sees the number the card shows.
 *
 * **The import refusal names the entry.** A pack carrying `scripts/` is refused
 * with `skill-contains-scripts` and the sentence names the file, because a pack
 * that ships a script is a pack whose author expects something this product
 * will not do - and importing it silently minus the scripts would hand them a
 * skill that quietly does less than it says.
 *
 * DOCKED, NEVER MODAL (R15).
 */
const props = withDefaults(
  defineProps<{ api?: AttachmentsApiLike }>(),
  { api: () => attachmentsApi },
)

const emit = defineEmits<{ choose: [skillId: string] }>()

const rows = ref<SkillSummary[]>([])
const loading = ref(false)
const listProblem = ref('')
const opened = ref<SkillDetail | null>(null)
const openProblem = ref('')

const builtins = computed(() => rows.value.filter((row) => row.owner === 'builtin'))
const mine = computed(() => rows.value.filter((row) => row.owner === 'me'))

async function load(): Promise<void> {
  loading.value = true
  listProblem.value = ''
  try {
    rows.value = await props.api.listSkills()
  } catch (error) {
    listProblem.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function open(row: SkillSummary): Promise<void> {
  openProblem.value = ''
  if (opened.value?.id === row.id) {
    opened.value = null
    return
  }
  try {
    opened.value = await props.api.getSkill(row.id)
  } catch (error) {
    openProblem.value = error instanceof Error ? error.message : String(error)
  }
}

/** The rendered body, escape-first. Never `v-html` over raw input. */
const openedHtml = computed(() => (opened.value ? renderMarkdown(opened.value.body) : ''))

/* --- writing one --------------------------------------------------------- */

const adding = ref(false)
const draftBody = ref('')
const addProblem = ref('')
const saving = ref(false)

function openAdd(): void {
  adding.value = true
  addProblem.value = ''
  draftBody.value = TEMPLATE
}

/**
 * The starting text, which is a teaching device rather than a convenience.
 *
 * An author's first pack is where they learn what a skill IS, and the two lines
 * that matter are the description's "Use when" clause - the thing an agent
 * reads to decide whether to activate - and the absence of anything that looks
 * like code.
 */
const TEMPLATE = `---
name: my-method
description: What this teaches, in one line. Use when <the situation that makes it relevant>.
metadata:
  version: "1"
---

# My method

The steps, in the order somebody would do them.
`

async function save(): Promise<void> {
  if (saving.value || !draftBody.value.trim()) return
  saving.value = true
  addProblem.value = ''
  try {
    const created = await props.api.createSkill(draftBody.value)
    rows.value = [...rows.value, created]
    adding.value = false
  } catch (error) {
    addProblem.value = error instanceof Error ? error.message : String(error)
  } finally {
    saving.value = false
  }
}

async function remove(row: SkillSummary): Promise<void> {
  try {
    await props.api.deleteSkill(row.id)
    rows.value = rows.value.filter((current) => current.id !== row.id)
    if (opened.value?.id === row.id) opened.value = null
  } catch (error) {
    listProblem.value = error instanceof Error ? error.message : String(error)
  }
}
</script>

<template>
  <section class="skill-panel" data-testid="skill-panel">
    <header class="skill-head">
      <h3>Skills</h3>
      <button type="button" class="skill-add" data-testid="skill-add" @click="openAdd">
        <Plus :size="12" aria-hidden="true" /> Write one
      </button>
    </header>

    <p class="skill-blurb">Knowledge: how to do a job well.</p>

    <p v-if="loading" class="skill-note" data-testid="skill-loading">
      <LoaderCircle :size="12" class="spin" aria-hidden="true" /> Loading…
    </p>
    <p v-else-if="listProblem" class="skill-note is-error" data-testid="skill-list-problem">
      {{ listProblem }}
    </p>

    <form v-if="adding" class="skill-form" data-testid="skill-form" @submit.prevent="save">
      <label>
        SKILL.md
        <textarea v-model="draftBody" rows="10" spellcheck="false" data-testid="skill-body" />
      </label>
      <p v-if="addProblem" class="skill-note is-error" data-testid="skill-add-problem">
        {{ addProblem }}
      </p>
      <div class="skill-actions">
        <button type="submit" :disabled="saving" data-testid="skill-save">Save</button>
        <button type="button" class="is-quiet" data-testid="skill-cancel" @click="adding = false">
          <X :size="12" aria-hidden="true" /> Cancel
        </button>
      </div>
    </form>

    <template v-for="group in [
      { key: 'builtin', title: 'Built in', rows: builtins },
      { key: 'me', title: 'Mine', rows: mine },
    ]" :key="group.key">
      <h4 v-if="group.rows.length" class="skill-group">{{ group.title }}</h4>
      <ul v-if="group.rows.length" class="skill-rows">
        <li
          v-for="row in group.rows"
          :key="row.id"
          class="skill-row"
          data-testid="skill-row"
          :data-skill-id="row.id"
          :data-owner="row.owner"
        >
          <div class="skill-row-head">
            <span class="skill-icon" aria-hidden="true"><BookOpen :size="12" /></span>
            <button type="button" class="skill-name" data-testid="skill-open" @click="open(row)">
              {{ row.name }}
            </button>
            <span class="skill-chip" data-testid="skill-version">v{{ row.version }}</span>
            <span class="skill-chip" data-testid="skill-owner">
              {{ row.owner === 'builtin' ? 'built-in' : 'mine' }}
            </span>
            <button
              type="button"
              class="is-quiet"
              data-testid="skill-attach"
              @click="emit('choose', row.id)"
            >
              Attach
            </button>
            <!--
              No delete for a built-in, and not because the button would fail:
              it WOULD, with a 404, and rendering a control whose only outcome is
              a refusal is a worse answer than not rendering it.
            -->
            <button
              v-if="row.owner === 'me'"
              type="button"
              class="is-quiet"
              data-testid="skill-delete"
              @click="remove(row)"
            >
              <Trash2 :size="12" aria-hidden="true" />
              <span class="sr-only">Delete {{ row.name }}</span>
            </button>
          </div>
          <p class="skill-desc">{{ row.description }}</p>

          <!--
            `v-html` over `renderMarkdown`, which escapes EVERY character before
            it recognises any structure - so there is no path by which a pasted
            body becomes markup. `.markdown-body` is styled globally in
            studio.css for the reason that file gives: a scoped selector never
            matches injected html.
          -->
          <div
            v-if="opened && opened.id === row.id"
            class="markdown-body skill-body"
            data-testid="skill-body-render"
            v-html="openedHtml"
          />
          <p v-if="openProblem && opened === null" class="skill-note is-error">{{ openProblem }}</p>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.skill-panel { display: block; }
.skill-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.skill-head h3 { margin: 0; color: var(--text-title); font: 600 var(--fs-12)/1.3 var(--font-body); }
.skill-blurb { margin: 2px 0 8px; color: var(--text-40); font: 400 var(--fs-11)/1.4 var(--font-body); }
.skill-group { margin: 10px 0 4px; color: var(--text-40); font: 600 10px/1 var(--font-mono); text-transform: uppercase; letter-spacing: 0.08em; }
.skill-note { margin: 4px 0; display: flex; align-items: center; gap: 4px; color: var(--text-40); font: 400 var(--fs-11)/1.5 var(--font-body); }
.skill-note.is-error { color: var(--warn-text); }
.skill-form { display: grid; gap: 6px; padding: 8px; background: var(--surface-well); border-radius: var(--r-sm); }
.skill-form label { display: grid; gap: 3px; color: var(--text-40); font: 500 var(--fs-11)/1.3 var(--font-body); }
.skill-form textarea { font: 400 var(--fs-11)/1.5 var(--font-mono); resize: vertical; }
.skill-actions { display: flex; gap: 6px; }
.skill-rows { margin: 0; padding: 0; list-style: none; display: grid; gap: 6px; }
.skill-row { padding: 7px 8px; background: var(--surface-panel); border: 1px solid var(--border-default); border-radius: var(--r-sm); }
.skill-row-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.skill-icon { display: inline-flex; color: var(--text-40); }
.skill-name { padding: 0; background: none; border: 0; color: var(--text-body); font: 500 var(--fs-12)/1.3 var(--font-body); cursor: pointer; }
.skill-chip { padding: 1px 5px; border-radius: 3px; background: var(--surface-well); color: var(--text-40); font: 500 10px/1.4 var(--font-mono); }
.skill-desc { margin: 3px 0 0 18px; color: var(--text-40); font: 400 var(--fs-11)/1.4 var(--font-body); }
.skill-body { margin: 6px 0 0 18px; max-height: 280px; overflow: auto; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.spin { animation: skill-spin 1s linear infinite; }
@keyframes skill-spin { to { transform: rotate(360deg); } }
</style>
