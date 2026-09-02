<script setup lang="ts">
import { computed } from 'vue'
import FieldProblem from './FieldProblem.vue'

/**
 * One labelled row of the docked inspector: a label, the control, its character
 * counter, the server's problems, and the help that explains the rule.
 *
 * This exists because the inspector is fourteen components and the alternative
 * is fourteen copies of the same `<label>`, the same focus ring and the same
 * `aria-describedby` wiring - which is how a form surface starts looking
 * assembled rather than designed. The control itself stays in the slot and is
 * styled from here through `:deep()`, so a `<select>` in `RouterBranchEditor`
 * and an `<input>` in `GateForm` are visibly the same object.
 *
 * `:deep()` is load-bearing rather than a shortcut. Slotted content is compiled
 * in the PARENT's scope and carries the parent's `data-v-…`, so a plain
 * `.field-row input` written here would match nothing at all - the class has
 * this component's scope id and the input has another's.
 *
 * IT DOES NOT DECIDE WHAT IS LEGAL. Every server sentence it shows comes
 * through `FieldProblem`, which reads the index `POST /api/builder/validate`
 * filled: the client renders problems, it never computes one (§1.1 invariant 3).
 * The one thing a caller may pass that the server did not say is `hint` - a
 * refusal the WIDGET itself made, and the widget may only refuse the §6.1 Tier-1
 * parse rules, which are 422s that must never be sent.
 *
 * `data-field` is the hook `InspectorRail.focusField()` uses, which is what makes
 * a `ProblemsPanel` row click and `F8` land on the control rather than on the
 * form (§6.3).
 */
const props = withDefaults(
  defineProps<{
    /** What the row is called. Rendered as the control's `<label>`. */
    label: string
    /** The control's `id`, so `for` and `aria-describedby` resolve to real elements. */
    controlId: string
    /** The document field this row edits, as `FIELD_CODES` spells it: `tier`, `branches`. */
    field: string
    /**
     * The node this control belongs to. Absent for the graph-level and edge-level
     * rows, which anchor no node problem - and absent is why `FieldProblem` is
     * skipped rather than handed an empty id it would look up and find nothing for.
     */
    nodeId?: string
    /** A sentence about a rule the widget enforces, or a consequence worth stating. */
    help?: string
    /**
     * A refusal this widget made - a taken id, a duplicate chip, a nested state
     * ref. It reads like an error because it is one; it is simply the client's
     * own Tier-1 refusal rather than something the server said.
     */
    hint?: string
    /** A short mono chip beside the label: `MIXED`, `3 of 5 used`. */
    note?: string
    /** Whether that chip reads as a warning. */
    noteWarn?: boolean
    /** Character counter: how many are used, and the ceiling. */
    used?: number | null
    max?: number | null
    /** Below this many characters remaining, the counter raises its voice. */
    warnAt?: number
    /**
     * True when the control is a GROUP of focusable things - a segmented pair, a
     * chip list, a checklist. A `<label for>` pointing at a group is a lie to a
     * screen reader, so the row becomes a labelled group instead.
     */
    group?: boolean
    /**
     * Render the control in the mono face.
     *
     * A row-level flag rather than a rule in the field component, because
     * `.field-row[data-v-…] input` outranks `input[data-v-…]` and the child
     * would have to reach for `!important` to win a fight this side started.
     * Identifiers, state keys and JSON scalars all want it: `market_analyst` and
     * `market_analyist` differ at a glance in mono and nowhere else.
     */
    mono?: boolean
  }>(),
  { warnAt: 100, group: false, noteWarn: false, mono: false },
)

const helpId = computed(() => `${props.controlId}-help`)
const hintId = computed(() => `${props.controlId}-hint`)

/**
 * What the control announces itself by.
 *
 * The widget's own refusal comes first, then the server's problems, then the
 * help - the order a reader needs them in. `FieldProblem` hands its id in; the
 * other two are ours.
 */
function describedBy(fromProblems: string | undefined): string | undefined {
  const ids = [props.hint ? hintId.value : '', fromProblems ?? '', props.help ? helpId.value : '']
  const present = ids.filter(Boolean)
  return present.length ? present.join(' ') : undefined
}

/**
 * A widget refusal is an invalid control even when the server has not spoken yet.
 *
 * Narrowed to the literal rather than `string`, because `aria-invalid` is typed
 * `Booleanish | 'grammar' | 'spelling'` in `runtime-dom` and a widened `string`
 * fails the check at every one of the four call sites. Which is the type system
 * doing its job: `aria-invalid="yes"` is inert in every screen reader.
 */
function invalid(fromProblems: string | undefined): 'true' | undefined {
  return props.hint || fromProblems ? 'true' : undefined
}

const counter = computed(() => {
  if (props.used == null || props.max == null) return null
  return {
    text: `${props.used} / ${props.max} characters`,
    warn: props.max - props.used <= props.warnAt,
  }
})
</script>

<template>
  <div
    class="field-row"
    :class="{ 'has-hint': Boolean(hint), 'is-mono': mono }"
    :data-field="field"
    :role="group ? 'group' : undefined"
    :aria-labelledby="group ? `${controlId}-label` : undefined"
  >
    <div class="field-head">
      <!-- A group gets a labelled container rather than a `for=` pointing at
           something that is not one control, which announces as empty. -->
      <component
        :is="group ? 'span' : 'label'"
        :id="group ? `${controlId}-label` : undefined"
        :for="group ? undefined : controlId"
        class="field-label"
      >
        {{ label }}
      </component>
      <!-- A slot with the string as its default, because two callers need
           CONTROLS up here rather than a word: `ScalarInput`'s type toggle has
           to sit on the label line or it reads as a separate field. -->
      <slot name="note">
        <span v-if="note" class="field-note" :class="{ 'is-warn': noteWarn }">{{ note }}</span>
      </slot>
    </div>

    <FieldProblem v-if="nodeId" :node-id="nodeId" :field="field" v-slot="anchor">
      <slot :described-by="describedBy(anchor.describedBy)" :invalid="invalid(anchor.invalid)" />
      <p v-if="counter" class="field-meta" :class="{ 'is-warn': counter.warn }">{{ counter.text }}</p>
    </FieldProblem>
    <template v-else>
      <slot :described-by="describedBy(undefined)" :invalid="invalid(undefined)" />
      <p v-if="counter" class="field-meta" :class="{ 'is-warn': counter.warn }">{{ counter.text }}</p>
    </template>

    <p v-if="hint" :id="hintId" class="field-hint">{{ hint }}</p>
    <p v-if="help" :id="helpId" class="field-help">{{ help }}</p>
  </div>
</template>

<style scoped>
.field-row { display: block; margin-top: 15px; }
.field-row:first-child { margin-top: 0; }
.field-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 7px; }
.field-label { color: var(--text-40); font: 700 var(--fs-11)/1 var(--font-mono); letter-spacing: 0.04em; text-transform: uppercase; }
.field-note { color: var(--text-muted); font: 500 10px/1 var(--font-mono); white-space: nowrap; }
.field-note.is-warn { color: var(--warn-text); }

/* The controls live in the slot, so they carry the PARENT's scope id and a
   plain descendant selector here would match nothing. `:deep()` is what lets
   one file own the look of every input in the rail. */
.field-row :deep(input[type='text']),
.field-row :deep(input[type='number']),
.field-row :deep(select),
.field-row :deep(textarea) {
  display: block;
  width: 100%;
  min-height: 34px;
  padding: 7px 9px;
  color: var(--text-body);
  font: 400 var(--fs-13)/1.4 var(--font-body);
  background: var(--surface-well);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  outline: 0;
  transition: border-color var(--motion-fast) ease, box-shadow var(--motion-fast) ease;
}
.field-row :deep(textarea) { min-height: 78px; resize: vertical; line-height: 1.5; }
.field-row :deep(select) { cursor: pointer; }
.field-row :deep(input:focus-visible),
.field-row :deep(select:focus-visible),
.field-row :deep(textarea:focus-visible) { border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.field-row :deep(input:disabled),
.field-row :deep(select:disabled),
.field-row :deep(textarea:disabled) { cursor: not-allowed; color: var(--text-40); opacity: 0.55; }
.field-row :deep(input[type='number']) { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.field-row.is-mono :deep(input[type='text']),
.field-row.is-mono :deep(textarea) { font-family: var(--font-mono); }

/* The rim the eye reaches before it reads a word. Only the widget's own refusal
   is drawn here - a server problem is already rimmed and boxed by
   `FieldProblem`, and painting it twice would say it twice. */
.field-row.has-hint :deep(input),
.field-row.has-hint :deep(select),
.field-row.has-hint :deep(textarea) { border-color: var(--err-border); }

/* The segmented pair, owned here for the same reason the inputs are: four forms
   render one and four copies of it is how a design system stops being one.
   Slotted content carries the caller's scope id, so `:deep()` is the only
   selector that reaches it. */
.field-row :deep(.segmented) { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); padding: 3px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.field-row :deep(.segmented button) { display: inline-flex; min-height: 30px; align-items: center; justify-content: center; gap: 6px; padding: 0 8px; color: var(--text-muted); font: 600 var(--fs-12)/1 var(--font-body); background: transparent; border: 0; border-radius: var(--r-sm); cursor: pointer; transition: color var(--motion-fast) ease, background var(--motion-fast) ease; }
.field-row :deep(.segmented button:hover) { color: var(--text-body); }
.field-row :deep(.segmented button[aria-pressed='true']) { color: var(--text-title); background: var(--surface-raised); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent-cyan) 24%, transparent); }
.field-row :deep(.segmented button:focus-visible) { outline: 2px solid var(--accent-cyan); outline-offset: -2px; }
.field-row :deep(.segmented button:disabled) { cursor: not-allowed; opacity: 0.45; }

.field-meta { margin: 6px 0 0; color: var(--text-40); font: 500 10px/1 var(--font-mono); text-align: right; }
/* Amber only near the ceiling: `maxlength` is a hard stop that discards
   keystrokes with no feedback at all, so a counter identical at 1,900 and at
   2,000 would be the only warning an author ever got. The idiom, and the
   reasoning, are `serverLimits.ts`'s. */
.field-meta.is-warn { color: var(--warn-text); }

.field-hint { margin: 7px 0 0; color: var(--err-text); font-size: var(--fs-11); line-height: 1.5; }
.field-help { margin: 7px 0 0; color: var(--text-muted); font-size: var(--fs-11); line-height: 1.5; }
</style>
