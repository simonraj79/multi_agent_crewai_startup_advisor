<script setup lang="ts">
/**
 * The server's sentence, under the control it is about.
 *
 * Spec section 6.3, sink two of three. The same problem is already colouring
 * the node's rim and already sitting in the panel; this is the one place it
 * appears beside the thing the author has to change, which is the difference
 * between "3 errors" and knowing which stepper is wrong.
 *
 * THE MESSAGE IS RENDERED VERBATIM. `bounds.py` writes a full sentence aimed at
 * the author - "this router has 5 branches; between 2 and 4 are allowed" - and
 * every attempt to summarise one into a label loses the number that makes it
 * actionable. Nothing here reformats, truncates or re-cases.
 *
 * WHY THIS IS A SCOPED SLOT rather than a wrapper that sets attributes itself.
 * `aria-describedby` and `aria-invalid` belong on the CONTROL, and the control
 * is whatever the caller passed in - a native input in one form, a component in
 * the next. A wrapper cannot set an attribute on slot content it has not been
 * handed a ref to, and reaching into the first child element after mount is
 * exactly the kind of guess that breaks the first time somebody wraps their
 * input in a label. So the ids are handed OUT and the caller binds them:
 *
 *     <FieldProblem :node-id="node.id" field="max_turns" v-slot="field">
 *       <input :aria-describedby="field.describedBy" :aria-invalid="field.invalid" />
 *     </FieldProblem>
 */
import { computed, inject, useId } from 'vue'
import { AlertTriangle, OctagonAlert } from 'lucide-vue-next'
import { BUILDER_PROBLEMS } from '../../../composables/useBuilderProblems'

const props = defineProps<{
  /** The node whose config this control edits. */
  nodeId: string
  /** The control's field name, as `FIELD_CODES` spells it. */
  field: string
}>()

/**
 * Required, and it throws when absent.
 *
 * A missing provider is not a state this component can render its way out of -
 * it would silently show no problems, which is the one outcome the whole
 * package exists to prevent. `BuilderView` provides the index once for the
 * whole builder, so an absent one means a form was mounted somewhere it does
 * not belong, and failing at mount says so where a blank space would not.
 */
const index = inject(BUILDER_PROBLEMS)
if (!index) {
  throw new Error(
    'FieldProblem needs the BUILDER_PROBLEMS index; provide it from BuilderView',
  )
}

const problems = computed(() => index.problemsForField(props.nodeId, props.field))

/**
 * `aria-invalid` for an error only.
 *
 * The three warning codes describe a graph that is legal and probably not what
 * was meant - an unconnected router branch, no output node, a join over one
 * predecessor. Announcing a control as invalid when the server has said the
 * document is publishable would be telling a screen-reader user the opposite of
 * what the Publish button does.
 */
const hasError = computed(() => problems.value.some((problem) => problem.severity !== 'warning'))
const tone = computed(() => (hasError.value ? 'is-error' : 'is-warning'))

const messageId = `field-problem-${useId()}`
const describedBy = computed(() => (problems.value.length ? messageId : undefined))
const invalid = computed(() => (hasError.value ? 'true' : undefined))
</script>

<template>
  <div class="field-problem" :class="{ 'has-problem': problems.length }">
    <slot :described-by="describedBy" :invalid="invalid" :problems="problems" />

    <!-- One region for however many problems this control carries, so a control
         with two of them announces both under one `aria-describedby`. -->
    <div v-if="problems.length" :id="messageId" class="field-problem-list" :class="tone">
      <p v-for="problem in problems" :key="problem.code + problem.message" class="field-problem-row">
        <OctagonAlert v-if="problem.severity !== 'warning'" :size="12" aria-hidden="true" />
        <AlertTriangle v-else :size="12" aria-hidden="true" />
        <span>{{ problem.message }}</span>
      </p>
    </div>
  </div>
</template>

<style scoped>
.field-problem { display: block; }
.field-problem-list { display: grid; gap: 5px; margin-top: 6px; padding: 7px 8px; border: 1px solid; border-radius: var(--r-sm); }
/* The washes are `color-mix` over the existing warn/err tokens rather than two
   new custom properties - the technique `WorkflowNode.vue` already uses, and
   the reason this package adds no variables to `tokens.css`. */
.field-problem-list.is-error { color: var(--err-text); background: color-mix(in srgb, var(--err-border) 22%, transparent); border-color: var(--err-border); }
.field-problem-list.is-warning { color: var(--warn-text); background: color-mix(in srgb, var(--warn-border) 18%, transparent); border-color: var(--warn-border); }
.field-problem-row { display: flex; gap: 6px; margin: 0; font-size: var(--fs-11); line-height: 1.5; }
.field-problem-row svg { flex: 0 0 auto; margin-top: 2px; }
/* `overflow-wrap` because a message can name a node id or a dollar figure with
   no space in it, and a 260px inspector rail is narrower than several of them. */
.field-problem-row span { overflow-wrap: anywhere; }
</style>
