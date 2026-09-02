<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { nodeId } from '../../../types/builder'
import type { BuilderDocument, BuilderNode, BuilderVocabulary, NodeId } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import TokenListInput from '../fields/TokenListInput.vue'
import { coalesceKeyFor, patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `gate` node: the pause a person answers.
 *
 * `message` is the one string in the whole document an OPERATOR reads rather
 * than an author, which is why it gets the textarea and the counter rather than
 * a line - and why the counter warns in the last hundred characters, the
 * `serverLimits.ts` idiom, because `maxlength` past the ceiling discards
 * keystrokes with no feedback at all.
 *
 * THERE IS NO `expiry_seconds` CONTROL (R8). The field is authored,
 * range-validated, round-tripped - and read by nothing in `src/`: the service
 * expires every gate on `VALIDATOR_GATE_TIMEOUT_SECONDS` globally. A control for
 * it would be a promise this build cannot keep, so the value travels untouched
 * through every commit this form makes and no widget claims otherwise.
 *
 * `max_turns` is deliberately not clamped here either. `GateConfig` declares it
 * `ge=0` with NO upper bound, on purpose: above `MAX_CYCLE_ITERATIONS` it is a
 * `cycle-iterations` PROBLEM naming the bound and by how much - which
 * `FieldProblem` prints under this very stepper - rather than a pydantic error
 * an author cannot act on. Clamping it in the widget would replace a sentence
 * that explains a cycle's cost with a number that silently refuses to move.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'gate' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const id = computed(() => props.node.id)
const config = computed(() => props.node.config)
const control = (name: string) => `insp-${id.value}-${name}`

const messageDraft = ref(config.value.message)
watch(config, (next) => {
  messageDraft.value = next.message
})

function commitMessage(): void {
  const value = messageDraft.value.trim()
  // `min_length=1` - an empty message is a 422, and reverting is honest about
  // which of the two values is real.
  if (!value) {
    messageDraft.value = config.value.message
    return
  }
  if (value === config.value.message) return
  emit('commit', {
    label: 'Edit gate message',
    next: patchConfig(props.doc, props.node, { message: value }),
    coalesceKey: coalesceKeyFor(id.value, 'message'),
  })
}

function commitEditableFields(fields: string[]): void {
  emit('commit', {
    label: 'Set editable gate fields',
    next: patchConfig(props.doc, props.node, {
      editable_fields: fields.map((field) => nodeId(field)) as NodeId[],
    }),
  })
}

function commitMaxTurns(event: Event): void {
  const raw = Number((event.target as HTMLInputElement).value)
  if (!Number.isFinite(raw) || raw < 0) return
  const turns = Math.round(raw)
  if (turns === config.value.max_turns) return
  emit('commit', {
    label: 'Set revise turns',
    next: patchConfig(props.doc, props.node, { max_turns: turns }),
  })
}

const cycleBound = computed(() => props.vocabulary.bounds.max_cycle_iterations)
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Message"
      :control-id="control('message')"
      field="message"
      :node-id="id"
      :used="messageDraft.length"
      :max="vocabulary.bounds.max_gate_message_chars"
      help="What the operator reads while the run is paused. The only string in this document written for them rather than for you."
      v-slot="row"
    >
      <textarea
        :id="control('message')"
        v-model="messageDraft"
        rows="4"
        :maxlength="vocabulary.bounds.max_gate_message_chars"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @blur="commitMessage"
      />
    </FieldRow>

    <!-- R9, in one sentence and honestly. The compiler DOES seed these keys into
         the payload the operator is shown; what it does not yet do is render
         everything else read-only, the way the validator's verdict gate prunes
         rather than annotates. Half-honoured, not dead - so it ships with the
         half stated. -->
    <TokenListInput
      :model-value="config.editable_fields"
      label="Editable fields"
      :control-id="control('editable_fields')"
      field="editable_fields"
      :node-id="id"
      subject="field"
      duplicate-message="the same editable field is named twice; list each field once"
      placeholder="Add a key, then Enter"
      help="Seeds the keys the gate payload offers. This build does not yet render the rest read-only, so treat it as what the operator is invited to change rather than as all they can."
      @commit="commitEditableFields"
    />

    <FieldRow
      label="Revise turns"
      :control-id="control('max_turns')"
      field="max_turns"
      :node-id="id"
      :help="`How many times an operator may send this step back. A revise loop IS a cycle, so every node on it is billed again each time round - above ${cycleBound} the compiler says so and by how much.`"
      v-slot="row"
    >
      <input
        :id="control('max_turns')"
        type="number"
        min="0"
        step="1"
        :value="config.max_turns"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitMaxTurns"
      />
    </FieldRow>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
</style>
