<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Check, LoaderCircle, Plus, X } from 'lucide-vue-next'
import { CREDENTIAL_KINDS, fieldLabel } from '../../data/credentialKinds'
import { credentialApi } from '../../services/builderApi'
import type { CredentialApiLike } from '../../services/builderApi'
import type { CredentialKind, CredentialProbe } from '../../types/builder'

/**
 * Pick one of the author's own credentials of a given kind, or add one, docked.
 *
 * `v-model` is a credential ID or null - the document carries the id and
 * nothing else (plan 01 D5). What this component holds about a credential is
 * `{id, kind, label}` and NOT ONE KEY MORE: `summarise` strips every row on
 * ingest, so a server that ever answered a list with a field value in it - or a
 * test double that does, which `credentialPicker.spec.ts` deliberately makes
 * one do - has nowhere in this component's state for that value to land, and
 * therefore nowhere in its markup. Filtering the template would be a promise;
 * stripping the state is a property.
 *
 * The one place a field VALUE exists on this side is `draft.fields`, on its way
 * out of the create form and into a POST body. It is cleared the moment the
 * server answers, and never read back: the 201 carries the same row shape the
 * list does. Secret fields render as `type="password"` - a courtesy to whoever
 * is looking over the author's shoulder, not a control.
 *
 * DOCKED, NEVER MODAL (R15). The create form opens inline under the select,
 * inside the same inspector row, and the graph stays visible beside it. The
 * competitor's credential dialog is a modal over a modal.
 *
 * `api` is a prop with a default rather than an import alone, so a spec can
 * hand this a double checked against `CredentialApiLike` - the narrower
 * surface `builderApi.ts` declares for exactly this reason. The double is
 * compiler-forced to match the four calls it stands in for.
 */
const props = withDefaults(
  defineProps<{
    kind: CredentialKind
    modelValue: string | null
    /** The `<select>`'s id, so a `FieldRow` label and `focusField` reach it. */
    controlId?: string
    /** From `FieldRow`'s slot: the problem and help ids, and the invalid flag. */
    describedBy?: string
    invalid?: 'true'
    api?: CredentialApiLike
  }>(),
  { controlId: 'credential-picker', describedBy: undefined, invalid: undefined, api: () => credentialApi },
)

const emit = defineEmits<{ 'update:modelValue': [id: string | null] }>()

/** What survives of a row: the three keys the picker renders, nothing else. */
interface PickerRow {
  id: string
  kind: CredentialKind
  label: string
}

function summarise(row: { id: string; kind: CredentialKind; label: string }): PickerRow {
  return { id: String(row.id), kind: row.kind, label: String(row.label) }
}

const spec = computed(() => CREDENTIAL_KINDS[props.kind])

/* --- the list ----------------------------------------------------------- */

const rows = ref<PickerRow[]>([])
const loading = ref(false)
/** Why the list is unavailable, as the server's own sentence, or ''. */
const listProblem = ref('')

async function load(): Promise<void> {
  loading.value = true
  listProblem.value = ''
  try {
    const listed = await props.api.listCredentials()
    // Filtered by kind HERE rather than asked for by kind: the endpoint lists
    // everything the caller owns, and one request serves every picker on the
    // inspector rather than one per row.
    rows.value = listed.filter((row) => row.kind === props.kind).map(summarise)
  } catch (error) {
    rows.value = []
    listProblem.value =
      error instanceof Error ? error.message : 'your credentials could not be listed.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.kind, load)

/**
 * The stored id, when the list does not carry it.
 *
 * A document can name a credential this account does not hold - one deleted
 * since, or one imported from somebody else's export before the stripper
 * existed. Dropping it from the select would silently rewrite the document to
 * the platform key the moment the author touched anything else; keeping it
 * visible and marked leaves the document alone and lets the server's own
 * `credential-missing` problem, anchored to this row, say why.
 */
const orphan = computed(() =>
  props.modelValue && !rows.value.some((row) => row.id === props.modelValue)
    ? props.modelValue
    : null,
)

function choose(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  probe.value = null
  probeProblem.value = ''
  emit('update:modelValue', value === '' ? null : value)
}

/* --- the probe ---------------------------------------------------------- */

const testing = ref(false)
const probe = ref<CredentialProbe | null>(null)
const probeProblem = ref('')

async function test(): Promise<void> {
  const id = props.modelValue
  if (!id || testing.value) return
  testing.value = true
  probe.value = null
  probeProblem.value = ''
  try {
    probe.value = await props.api.testCredential(id)
  } catch (error) {
    probeProblem.value =
      error instanceof Error ? error.message : 'the credential could not be tested.'
  } finally {
    testing.value = false
  }
}

/* --- the create form ---------------------------------------------------- */

const creating = ref(false)
const draft = ref<{ label: string; fields: Record<string, string> }>({ label: '', fields: {} })
const saving = ref(false)
const saveProblem = ref('')

function blankFields(): Record<string, string> {
  const fields: Record<string, string> = {}
  for (const name of spec.value.fields) fields[name] = ''
  return fields
}

function openForm(): void {
  draft.value = { label: '', fields: blankFields() }
  saveProblem.value = ''
  creating.value = true
}

function closeForm(): void {
  // The typed secret is dropped with the form, whether or not it was sent.
  draft.value = { label: '', fields: {} }
  saveProblem.value = ''
  creating.value = false
}

const canSave = computed(
  () =>
    !saving.value &&
    draft.value.label.trim().length > 0 &&
    spec.value.fields.every((name) => (draft.value.fields[name] ?? '').trim().length > 0),
)

async function save(): Promise<void> {
  if (!canSave.value) return
  saving.value = true
  saveProblem.value = ''
  try {
    const created = await props.api.createCredential({
      kind: props.kind,
      label: draft.value.label.trim(),
      fields: { ...draft.value.fields },
    })
    rows.value = [...rows.value, summarise(created)]
    closeForm()
    // The new key is the one the author meant to use; selecting it is the
    // whole reason they opened the form from THIS row.
    emit('update:modelValue', created.id)
  } catch (error) {
    saveProblem.value = error instanceof Error ? error.message : 'the credential could not be saved.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="credential-picker" data-testid="credential-picker">
    <div class="credential-row">
      <select
        :id="controlId"
        class="credential-select"
        data-testid="credential-select"
        :value="modelValue ?? ''"
        :aria-describedby="describedBy"
        :aria-invalid="invalid"
        :disabled="loading"
        @change="choose"
      >
        <option value="">Platform key</option>
        <option v-for="row in rows" :key="row.id" :value="row.id">{{ row.label }}</option>
        <option v-if="orphan" :value="orphan">{{ orphan }} — not among your credentials</option>
      </select>
      <button
        type="button"
        class="credential-test"
        data-testid="credential-test"
        :disabled="!modelValue || testing"
        :title="modelValue ? 'Try this key against its provider' : 'Choose a key to test'"
        @click="test"
      >
        <LoaderCircle v-if="testing" class="spin" :size="12" aria-hidden="true" />
        Test
      </button>
    </div>

    <p v-if="loading" class="credential-note" role="status">Loading your credentials…</p>
    <p v-else-if="listProblem" class="credential-note is-problem" role="alert">
      {{ listProblem }}
    </p>

    <!-- `role="status"` so the answer is announced where the click was, and the
         provider's own sentence verbatim: it is the only part that tells an
         author WHAT was wrong with the key. -->
    <p
      v-if="probe"
      class="credential-probe"
      :class="probe.ok ? 'is-ok' : 'is-failed'"
      data-testid="credential-probe"
      role="status"
    >
      <Check v-if="probe.ok" :size="12" aria-hidden="true" />
      <X v-else :size="12" aria-hidden="true" />
      <span>{{ probe.detail }}</span>
    </p>
    <p v-else-if="probeProblem" class="credential-note is-problem" role="alert">{{ probeProblem }}</p>

    <button
      v-if="!creating"
      type="button"
      class="credential-new"
      data-testid="credential-new"
      @click="openForm"
    >
      <Plus :size="12" aria-hidden="true" />
      Add a {{ spec.label }} key
    </button>

    <form
      v-else
      class="credential-form"
      data-testid="credential-form"
      :aria-label="`New ${spec.label} credential`"
      @submit.prevent="save"
    >
      <label class="credential-field">
        <span>Label</span>
        <input
          v-model="draft.label"
          type="text"
          maxlength="80"
          autocomplete="off"
          spellcheck="false"
          data-testid="credential-label"
          placeholder="What you will call it"
        />
      </label>
      <label v-for="name in spec.fields" :key="name" class="credential-field">
        <span>{{ fieldLabel(name) }}</span>
        <input
          v-model="draft.fields[name]"
          :type="spec.secret.includes(name) ? 'password' : 'text'"
          autocomplete="off"
          spellcheck="false"
          :data-testid="`credential-field-${name}`"
        />
      </label>
      <p v-if="saveProblem" class="credential-note is-problem" role="alert">{{ saveProblem }}</p>
      <div class="credential-form-actions">
        <button type="submit" class="credential-save" data-testid="credential-save" :disabled="!canSave">
          <LoaderCircle v-if="saving" class="spin" :size="12" aria-hidden="true" />
          {{ saving ? 'Saving…' : 'Save key' }}
        </button>
        <button type="button" class="credential-cancel" data-testid="credential-cancel" @click="closeForm">
          Cancel
        </button>
      </div>
      <p class="credential-note">
        Encrypted at rest under the vault's key. It is sent once, now, and never shown again.
      </p>
    </form>
  </div>
</template>

<style scoped>
.credential-picker { display: grid; gap: 8px; }
.credential-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; align-items: stretch; }
.credential-test,
.credential-new,
.credential-save,
.credential-cancel {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 30px;
  padding: 0 10px;
  color: var(--text-muted);
  font: 600 var(--fs-11)/1 var(--font-body);
  background: transparent;
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease;
}
.credential-test { min-height: 34px; }
.credential-new { border-style: dashed; }
.credential-test:hover:not(:disabled),
.credential-new:hover,
.credential-cancel:hover { color: var(--text-title); border-color: var(--border-hover); }
.credential-test:disabled,
.credential-save:disabled { cursor: not-allowed; opacity: 0.45; }
.credential-test:focus-visible,
.credential-new:focus-visible,
.credential-save:focus-visible,
.credential-cancel:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }
.credential-save { color: var(--text-title); border-color: var(--accent-cyan); }

/* The same well the prompt-input rows use one section down: a label and a
   secret are one thing, and they must read as one. */
.credential-form { display: grid; gap: 8px; padding: 9px 10px; background: var(--surface-well); border: 1px solid var(--border-default); border-radius: var(--r-md); }
.credential-field { display: grid; gap: 4px; }
.credential-field span { color: var(--text-40); font: 700 10px/1 var(--font-mono); letter-spacing: 0.04em; text-transform: uppercase; }
.credential-field input {
  display: block;
  width: 100%;
  min-height: 32px;
  padding: 6px 8px;
  color: var(--text-body);
  font: 400 var(--fs-13)/1.4 var(--font-mono);
  background: var(--bg-node);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
  outline: 0;
}
.credential-field input:focus-visible { border-color: var(--accent-cyan); box-shadow: var(--glow-input); }
.credential-form-actions { display: flex; gap: 6px; }

.credential-note { margin: 0; color: var(--text-40); font-size: var(--fs-11); line-height: 1.5; }
.credential-note.is-problem { color: var(--err-text); }
.credential-probe { display: flex; gap: 6px; align-items: flex-start; margin: 0; padding: 6px 8px; font-size: var(--fs-11); line-height: 1.5; border: 1px solid; border-radius: var(--r-md); }
.credential-probe svg { flex: 0 0 auto; margin-top: 2px; }
.credential-probe.is-ok { color: var(--accent-mint); background: color-mix(in srgb, var(--accent-mint) 8%, transparent); border-color: color-mix(in srgb, var(--accent-mint) 30%, transparent); }
.credential-probe.is-failed { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }

.spin { animation: credential-spin 900ms linear infinite; }
@keyframes credential-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
}
</style>
