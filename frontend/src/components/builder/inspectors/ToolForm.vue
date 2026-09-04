<script setup lang="ts">
import { computed } from 'vue'
import type {
  BuilderDocument,
  BuilderNode,
  BuilderToolParam,
  BuilderVocabulary,
  CredentialKind,
  JsonScalar,
  NodeId,
} from '../../../types/builder'
import { nodeId as toNodeId } from '../../../types/builder'
import FieldRow from '../fields/FieldRow.vue'
import CredentialPicker from '../CredentialPicker.vue'
import ToolCard from '../ToolCard.vue'
import { patchConfig } from '../commit'
import type { InspectorCommit } from '../commit'

/**
 * The `tool` node: one catalogue tool, hung off an agent or a crew.
 *
 * **Every control here is generated from the served catalogue.** The entry
 * declares its parameters - name, type, bound, default, closed set - and this
 * renders one control per declaration and refuses to render anything else.
 * That is the gauntlet's "forbidden: a parameter rendered in the UI that the
 * compiler ignores" turned into a property rather than a review item: there is
 * no list of controls in this file to drift from the server's list, and a
 * parameter the server drops is a control that stops existing.
 *
 * `tool_id` is a SELECT when the server has served a catalogue and a text box
 * when it has not. Never a hardcoded list: a client-side catalogue is cut-list
 * item 17, and it would offer tools the compiler has never heard of.
 *
 * **The credential row is conditional on the entry, not on the kind alone.**
 * `web_search` is one tool over four providers and which key it needs follows
 * `provider`, so the picker's `kind` is computed from the CURRENT params - and
 * an entry whose key is optional gets the picker without the amber chip,
 * because `assess_technical_feasibility` unauthenticated is a lower rate limit
 * rather than a refusal.
 */
const props = defineProps<{
  doc: BuilderDocument
  node: Extract<BuilderNode, { kind: 'tool' }>
  vocabulary: BuilderVocabulary
}>()

const emit = defineEmits<{ commit: [change: InspectorCommit] }>()

const config = computed(() => props.node.config)
const control = (name: string) => `insp-${props.node.id}-${name}`

/** The served catalogue, or null while this build's `/vocabulary` is still v1. */
const catalogue = computed(() => props.vocabulary.tools ?? null)

/** This node's own entry, or null when the catalogue does not carry its id. */
const entry = computed(
  () => catalogue.value?.find((row) => row.tool_id === config.value.tool_id) ?? null,
)

/**
 * The options, with the node's own id folded in when the catalogue does not
 * carry it.
 *
 * A select whose value is not among its options renders BLANK, which would show
 * an author an empty control over a document that says something - so a stored
 * id from an older catalogue is offered as itself rather than silently dropped.
 * The server answers `tool-unknown` for it, which is the honest message.
 */
const options = computed(() => {
  const rows = catalogue.value ?? []
  const known = rows.some((row) => row.tool_id === config.value.tool_id)
  return known
    ? rows
    : [
        ...rows,
        { tool_id: config.value.tool_id as string, label: config.value.tool_id as string },
      ]
})

/** The effective value of one parameter: what the document says, else the default. */
function valueOf(param: BuilderToolParam): JsonScalar {
  const current = config.value.params[param.name]
  return (current === undefined ? (param.default as JsonScalar) : current) ?? null
}

const params = computed(() => entry.value?.params ?? [])

/** Which credential kind THIS configuration needs - `provider` considered. */
const credentialKind = computed<CredentialKind | null>(() => {
  const row = entry.value
  if (!row) return null
  const byParam = row.credential_kind_by_param
  if (byParam) {
    const chosen = config.value.params[byParam.param] ?? defaultOf(byParam.param)
    return byParam.map[String(chosen)] ?? null
  }
  return row.credential_kind
})

function defaultOf(name: string): JsonScalar | undefined {
  return entry.value?.params.find((row) => row.name === name)?.default as JsonScalar | undefined
}

function commitToolId(value: string): void {
  if (value === config.value.tool_id) return
  emit('commit', {
    label: 'Set tool',
    // Changing the tool CLEARS the parameters, and that is the honest edit:
    // `n_results` means nothing to `postgres_query`, and carrying it over would
    // leave the author with a document the server answers
    // `tool-param-invalid` for and no control that shows why.
    next: patchConfig(props.doc, props.node, {
      tool_id: toNodeId(value) as NodeId,
      params: {},
    }),
  })
}

function commitParam(param: BuilderToolParam, raw: string | boolean | string[]): void {
  let value: JsonScalar | JsonScalar[]
  if (param.type === 'boolean') value = Boolean(raw)
  else if (param.type === 'integer' || param.type === 'number') value = Number(raw)
  else if (param.type === 'array') value = raw as string[]
  else value = String(raw)
  emit('commit', {
    label: `Set ${param.name}`,
    next: patchConfig(props.doc, props.node, {
      params: { ...config.value.params, [param.name]: value as JsonScalar },
    }),
  })
}

function commitCredential(id: string | null): void {
  emit('commit', {
    label: id ? 'Set tool key' : 'Clear tool key',
    next: patchConfig(props.doc, props.node, { credential_id: id }),
  })
}

function toggleMember(param: BuilderToolParam, member: string, on: boolean): void {
  const current = (valueOf(param) as unknown as string[]) ?? []
  const next = on ? [...current, member] : current.filter((entry) => entry !== member)
  commitParam(param, next)
}
</script>

<template>
  <div class="inspector-form">
    <FieldRow
      label="Tool"
      :control-id="control('tool_id')"
      field="tool_id"
      :node-id="node.id"
      mono
      help="Which catalogue tool this node attaches. An opaque id the server looks up in a closed set - never a module path, which is why a document cannot execute code."
      v-slot="row"
    >
      <select
        v-if="catalogue"
        :id="control('tool_id')"
        :value="config.tool_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitToolId(($event.target as HTMLSelectElement).value)"
      >
        <option v-for="option in options" :key="option.tool_id" :value="option.tool_id">
          {{ option.label }}
        </option>
      </select>
      <input
        v-else
        :id="control('tool_id')"
        type="text"
        :value="config.tool_id"
        :aria-describedby="row.describedBy"
        :aria-invalid="row.invalid"
        @change="commitToolId(($event.target as HTMLInputElement).value)"
      />
    </FieldRow>

    <!-- What the canvas card shows, shown here too, so the two cannot disagree. -->
    <ToolCard
      v-if="entry"
      class="tool-preview"
      :tool-id="config.tool_id"
      :entry="entry"
      :params="config.params"
      :has-credential="Boolean(config.credential_id)"
      :dense="false"
    />
    <p v-if="entry" class="tool-blurb" data-testid="tool-description">{{ entry.description }}</p>

    <!--
      One control per DECLARED parameter, and no control for anything else.
      The bounds are the entry's own, so a number this widget accepts is a
      number the server accepts.
    -->
    <FieldRow
      v-for="param in params"
      :key="param.name"
      :label="param.name"
      :control-id="control(param.name)"
      field="params"
      :node-id="node.id"
      :help="param.description"
      v-slot="row"
    >
      <select
        v-if="param.enum && param.type !== 'array'"
        :id="control(param.name)"
        :value="String(valueOf(param))"
        :aria-describedby="row.describedBy"
        @change="commitParam(param, ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="member in param.enum" :key="String(member)" :value="String(member)">
          {{ member }}
        </option>
      </select>

      <input
        v-else-if="param.type === 'boolean'"
        :id="control(param.name)"
        type="checkbox"
        :checked="Boolean(valueOf(param))"
        :aria-describedby="row.describedBy"
        @change="commitParam(param, ($event.target as HTMLInputElement).checked)"
      />

      <input
        v-else-if="param.type === 'integer' || param.type === 'number'"
        :id="control(param.name)"
        type="number"
        :value="valueOf(param)"
        :min="param.min"
        :max="param.max"
        :aria-describedby="row.describedBy"
        @change="commitParam(param, ($event.target as HTMLInputElement).value)"
      />

      <!--
        An `array` with a closed member set is a checkbox group rather than a
        text box: `formats` takes `markdown` and `links` and nothing else, and a
        free-text control would let an author type a third that the server then
        refuses.
      -->
      <span v-else-if="param.type === 'array' && param.enum" class="tool-members">
        <label v-for="member in param.enum" :key="String(member)" class="tool-member">
          <input
            type="checkbox"
            :checked="((valueOf(param) as unknown as string[]) ?? []).includes(String(member))"
            :data-member="String(member)"
            @change="
              toggleMember(param, String(member), ($event.target as HTMLInputElement).checked)
            "
          />
          {{ member }}
        </label>
      </span>

      <input
        v-else
        :id="control(param.name)"
        type="text"
        :value="valueOf(param)"
        :aria-describedby="row.describedBy"
        @change="commitParam(param, ($event.target as HTMLInputElement).value)"
      />
    </FieldRow>

    <!--
      The key. Present only when THIS configuration needs one, which for
      `web_search` is a function of `provider` and for everything else is a
      property of the entry.
    -->
    <FieldRow
      v-if="credentialKind"
      label="Key"
      :control-id="control('credential_id')"
      field="credential_id"
      :node-id="node.id"
      :note="entry?.credential_optional ? 'optional' : undefined"
      :help="
        entry?.credential_optional
          ? 'This tool runs without a key at a lower rate limit. Adding one raises it.'
          : 'Which of your own keys this tool runs on. The document carries the id; the key itself is decrypted inside the tool constructor at run time and reaches no frame, no log and no export.'
      "
      v-slot="row"
    >
      <CredentialPicker
        :kind="credentialKind"
        :model-value="config.credential_id ?? null"
        :control-id="control('credential_id')"
        :described-by="row.describedBy"
        :invalid="row.invalid"
        @update:model-value="commitCredential"
      />
    </FieldRow>
  </div>
</template>

<style scoped>
.inspector-form { display: block; }
.tool-preview { margin: 6px 0 2px; }
.tool-blurb {
  margin: 0 0 6px;
  color: var(--text-40);
  font: 400 var(--fs-11)/1.5 var(--font-body);
}
.tool-members { display: flex; flex-wrap: wrap; gap: 8px; }
.tool-member {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-40);
  font: 400 var(--fs-11)/1.3 var(--font-body);
}
</style>
