<script setup lang="ts">
import { computed } from 'vue'
import type { BuilderDocument, BuilderNode, BuilderVocabulary, NodeId } from '../../../types/builder'
import { nodeId as toNodeId } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `skill` node: one SKILL.md pack attached to an agent.
 *
 * `SkillConfig` carries exactly one field, so this form has exactly one
 * control, and that is not a placeholder - it is the schema. **08 owns skill
 * storage** and the progressive-disclosure mechanism that makes a skill worth
 * having: a skill's name and description load at run start and its BODY loads
 * only when a task matches, which is what lets an agent carry domain knowledge
 * without carrying it in every prompt.
 *
 * The picker over a caller's own stored skills is 08's too - it is a per-user
 * list from an authenticated endpoint (C11), not vocabulary - which is why this
 * is a text field over an opaque id rather than a select over nothing.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'skill' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`

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
      help="Which knowledge pack this node attaches, by id. A skill is knowledge and not hands: its description loads at run start and its body only when a task matches."
      v-slot="row"
    >
      <input
        :id="control('skill_id')"
        type="text"
        :value="config.skill_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitSkillId(($event.target as HTMLInputElement).value)"
      />
    </FieldRow>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
</style>
