<script setup lang="ts">
import FieldRow from './FieldRow.vue'

/**
 * A boolean, as a native checkbox wearing a switch.
 *
 * NATIVE, not a `div role="switch"`. D9 asks for a native control or a full
 * `role` / `tabindex` / arrow implementation, and a checkbox already has the
 * keyboard behaviour, the focus ring, the label association and the
 * indeterminate-free semantics; painting it is CSS. The nine boolean fields an
 * authored agent carries would otherwise be nine chances to get one of those
 * wrong.
 *
 * IT CAN BE DISABLED WITH A REASON. D3's capability gating is the whole point
 * of `disabled` + `reason` travelling together: a control the chosen model
 * cannot honour is rendered `disabled`, carries `aria-disabled`, shows the
 * reason as its tooltip, and **keeps its stored value visible**. Flowise drops
 * such a parameter silently; the gauntlet scores the difference.
 *
 * `aria-disabled` is set BESIDE `disabled` rather than instead of it. `disabled`
 * takes the control out of the tab order, which is right - there is nothing to
 * do here - and some screen readers then say nothing at all about it, so the
 * ARIA attribute is what keeps the state announced.
 */
const props = withDefaults(
  defineProps<{
    label: string
    controlId: string
    field: string
    nodeId?: string
    modelValue: boolean
    help?: string
    note?: string
    noteWarn?: boolean
    disabled?: boolean
    /** Why it is disabled - the tooltip, and it must name the model. */
    reason?: string
  }>(),
  { disabled: false, noteWarn: false },
)

const emit = defineEmits<{ commit: [value: boolean] }>()

function toggle(event: Event): void {
  const next = (event.target as HTMLInputElement).checked
  if (next === props.modelValue) return
  emit('commit', next)
}
</script>

<template>
  <FieldRow
    :label="label"
    :control-id="controlId"
    :field="field"
    :node-id="nodeId"
    :help="help"
    :note="note"
    :note-warn="noteWarn"
    v-slot="row"
  >
    <span class="switch-wrap" :title="disabled ? reason : undefined">
      <input
        :id="controlId"
        class="switch-input"
        type="checkbox"
        :checked="modelValue"
        :disabled="disabled"
        :aria-disabled="disabled ? 'true' : undefined"
        :aria-describedby="row.describedBy"
        @change="toggle"
      />
      <span class="switch-track" aria-hidden="true"><i class="switch-thumb" /></span>
      <span class="switch-word">{{ modelValue ? 'on' : 'off' }}</span>
    </span>
  </FieldRow>
</template>

<style scoped>
.switch-wrap { display: inline-flex; align-items: center; gap: 8px; }
/* The input stays in the layout and stays focusable; the painted track sits
   over it. `opacity: 0` rather than `display: none`, because a hidden input is
   not focusable and the focus ring below has nothing to key on. */
.switch-input { position: absolute; width: 34px; height: 20px; margin: 0; opacity: 0; cursor: pointer; }
.switch-input:disabled { cursor: not-allowed; }
.switch-track { display: inline-flex; width: 34px; height: 20px; flex: 0 0 auto; align-items: center; padding: 2px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-full); transition: background var(--motion-fast) ease, border-color var(--motion-fast) ease; }
.switch-thumb { width: 14px; height: 14px; background: var(--text-40); border-radius: var(--r-full); transition: transform var(--motion-fast) ease, background var(--motion-fast) ease; }
.switch-input:checked ~ .switch-track { background: color-mix(in srgb, var(--accent-cyan) 22%, transparent); border-color: var(--accent-cyan); }
.switch-input:checked ~ .switch-track .switch-thumb { background: var(--accent-cyan); transform: translateX(14px); }
.switch-input:focus-visible ~ .switch-track { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }
.switch-input:disabled ~ .switch-track { opacity: 0.55; }
.switch-word { color: var(--text-muted); font: 500 var(--fs-11)/1 var(--font-mono); }
.switch-input:disabled ~ .switch-word { color: var(--text-40); }

@media (prefers-reduced-motion: reduce) {
  .switch-track,
  .switch-thumb { transition: none; }
}
</style>
