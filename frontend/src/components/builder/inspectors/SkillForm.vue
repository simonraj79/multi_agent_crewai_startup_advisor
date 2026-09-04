<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { BuilderDocument, BuilderNode, BuilderVocabulary, NodeId } from '../../../types/builder'
import type { SkillDetail, SkillSummary } from '../../../types/builder'
import { nodeId as toNodeId } from '../../../types/builder'
import { attachmentsApi } from '../../../services/attachmentsApi'
import type { AttachmentsApiLike } from '../../../services/attachmentsApi'
import FieldRow from '../fields/FieldRow.vue'
import SkillPanel from '../SkillPanel.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'
import { renderMarkdown } from '../../../utils/markdown'

/**
 * The `skill` node: one SKILL.md pack attached to an agent.
 *
 * `SkillConfig` carries exactly one field, so the form has exactly one control
 * - and everything else here exists to answer the question that one field
 * cannot: **what does this pack actually say?** A skill is knowledge, its body
 * loads only when a task matches, and an author who cannot read the body is
 * attaching a name.
 *
 * **The body renders through the console's own escape-first renderer.** A pack
 * is untrusted text in exactly the way a report body is - pasted by a person or
 * imported from an archive, and destined for a model's context - so every
 * character is escaped BEFORE any structure is recognised. A sanitiser applied
 * after markup exists is the opposite order and is the one this repository has
 * already argued against.
 *
 * **The picker lists built-ins and the caller's own together**, with a chip
 * saying which. The four built-ins belong to this repository and cannot be
 * edited; that is why the panel offers no delete for them and why this form
 * offers no edit at all - a skill is edited in the Skills panel, and an
 * inspector that could rewrite a pack four graphs share would be a surprising
 * place to do it from.
 */
const props = withDefaults(
  defineProps<{
    doc: BuilderDocument
    node: Extract<BuilderNode, { kind: 'skill' }>
    vocabulary: BuilderVocabulary
    api?: AttachmentsApiLike
  }>(),
  { api: () => attachmentsApi },
)

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`

/** The write-and-manage panel, docked under the form. See `McpForm` for why. */
const managing = ref(false)
const rows = ref<SkillSummary[]>([])
const detail = ref<SkillDetail | null>(null)
const problem = ref('')

const summary = computed(() => rows.value.find((row) => row.id === config.value.skill_id) ?? null)

async function load(): Promise<void> {
  problem.value = ''
  try {
    rows.value = await props.api.listSkills()
  } catch (error) {
    problem.value = error instanceof Error ? error.message : String(error)
  }
}

async function loadBody(): Promise<void> {
  const id = config.value.skill_id
  if (!id) {
    detail.value = null
    return
  }
  if (detail.value?.id === id) return
  try {
    detail.value = await props.api.getSkill(id)
  } catch {
    // A pack that is not this caller's answers 404, and the PROBLEM for that is
    // `skill-unknown` on the node - which `FieldRow` already renders from the
    // server's own index. Repeating it here would say the same thing twice in
    // two wordings, and the second would be ours.
    detail.value = null
  }
}

onMounted(async () => {
  await load()
  await loadBody()
})

watch(() => config.value.skill_id, loadBody)

/** The rendered pack. Escape-first; never `v-html` over raw input. */
const bodyHtml = computed(() => (detail.value ? renderMarkdown(detail.value.body) : ''))

/** A pack written or picked in the panel becomes this node's pack. */
function adopt(id: string): void {
  managing.value = false
  commitSkillId(id)
  void load()
}

function commitSkillId(value: string): void {
  if (value === config.value.skill_id) return
  emit('commit', {
    label: 'Set skill',
    next: patchConfig(props.doc, props.node, { skill_id: toNodeId(value) as NodeId }),
  })
}
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Skill"
      :control-id="control('skill_id')"
      field="skill_id"
      :node-id="node.id"
      mono
      :note="summary ? (summary.owner === 'builtin' ? 'built-in' : 'mine') : undefined"
      help="Which knowledge pack this node attaches. A skill is knowledge and not hands: its description loads at run start and its body only when a task matches."
      v-slot="row"
    >
      <select
        v-if="rows.length"
        :id="control('skill_id')"
        :value="config.skill_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitSkillId(($event.target as HTMLSelectElement).value)"
      >
        <!--
          The stored id, folded in when the list does not carry it. A select
          whose value is absent from its options renders BLANK, which would show
          an author an empty control over a document that says something.
        -->
        <option v-if="!summary" :value="config.skill_id">{{ config.skill_id }}</option>
        <option v-for="option in rows" :key="option.id" :value="option.id">
          {{ option.name }}
        </option>
      </select>
      <input
        v-else
        :id="control('skill_id')"
        type="text"
        :value="config.skill_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitSkillId(($event.target as HTMLInputElement).value)"
      />
    </FieldRow>

    <p v-if="problem" class="skill-note is-error" data-testid="skill-form-problem">{{ problem }}</p>

    <div v-if="summary" class="skill-summary" data-testid="skill-summary">
      <span class="skill-chip" data-testid="skill-form-version">v{{ summary.version }}</span>
      <span class="skill-chip" data-testid="skill-form-owner">
        {{ summary.owner === 'builtin' ? 'built-in' : 'mine' }}
      </span>
      <span class="skill-desc">{{ summary.description }}</span>
    </div>

    <button
      type="button"
      class="is-quiet skill-manage"
      data-testid="skill-manage"
      :aria-expanded="managing"
      @click="managing = !managing"
    >
      {{ managing ? 'Hide packs' : 'Manage packs' }}
    </button>
    <SkillPanel v-if="managing" class="skill-docked" :api="api" @choose="adopt" />

    <div
      v-if="detail"
      class="markdown-body skill-body"
      data-testid="skill-form-body"
      v-html="bodyHtml"
    />
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.skill-note { margin: 6px 0 0; color: var(--text-40); font: 400 var(--fs-11)/1.5 var(--font-body); }
.skill-note.is-error { color: var(--warn-text); }
.skill-summary { display: flex; align-items: baseline; gap: 6px; margin: 6px 0 0; flex-wrap: wrap; }
.skill-chip { padding: 1px 5px; border-radius: 3px; background: var(--surface-well); color: var(--text-40); font: 500 10px/1.4 var(--font-mono); }
.skill-desc { color: var(--text-40); font: 400 var(--fs-11)/1.4 var(--font-body); }
.skill-manage { margin-top: 8px; }
.skill-docked { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border-default); }
.skill-body { margin: 8px 0 0; max-height: 260px; overflow: auto; }
</style>
