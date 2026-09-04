<script setup lang="ts">
import { computed } from 'vue'
import { KeyRound, TriangleAlert, Wrench } from 'lucide-vue-next'
import type { BuilderToolCatalogueEntry, JsonScalar } from '../../types/builder'

/**
 * What a `tool` attachment says about itself - plan 06 D9 and D4.
 *
 * A tool node's whole job on the canvas is to answer three questions at a
 * glance, and the third is the one this component exists for:
 *
 * 1. **which tool** - the catalogue LABEL, never the id. An author picked
 *    "Web search" from a list and should see that, not `web_search`.
 * 2. **which provider**, when one tool is several. `web_search` is four
 *    classes behind one name, and which one is running is the difference
 *    between a Serper bill and a Tavily one.
 * 3. **whether it can run at all.** A tool that needs a key and has none does
 *    not fail at publish - it fails at the first paid step, after every
 *    upstream node has already billed. So the card carries an amber "no key"
 *    chip and the problems dock carries `tool-credential-required`, and the
 *    two say the same thing in the two places an author looks.
 *
 * **`credential_optional` is why this is not simply "kind set, id absent".**
 * `assess_technical_feasibility` runs unauthenticated at a lower rate limit and
 * `http_request` runs with no header at all; showing the amber chip on either
 * would be inventing a problem the server does not report. The server is the
 * one that decides, and this reads its answer rather than recomputing it.
 *
 * It renders no button and owns no state. `BuilderNode` composes it, the
 * inspector edits, and the canvas is 02's - so a card that could act would be
 * a fourth place a document changes.
 */
const props = withDefaults(
  defineProps<{
    /** The document's own `tool_id`. Shown when the catalogue has no entry. */
    toolId: string
    /** The catalogue row, or null while `/vocabulary` has not answered. */
    entry?: BuilderToolCatalogueEntry | null
    /** The node's `params`, for the provider chip and nothing else. */
    params?: Record<string, JsonScalar>
    /** Whether the node names a credential. The ID never reaches this component. */
    hasCredential?: boolean
    /** Compact enough for a node card; false gives the inspector's fuller row. */
    dense?: boolean
  }>(),
  { entry: null, params: () => ({}), hasCredential: false, dense: true },
)

/** The label, or the id - never a guess, and never an empty string. */
const label = computed(() => props.entry?.label || props.toolId)

/**
 * Which credential kind THIS configuration needs, or null.
 *
 * `credential_kind_by_param` is `web_search`'s alone: the entry's kind is null
 * and the answer depends on `provider`. Reading the map rather than the entry's
 * own field is what makes the chip say `tavily` when the author chose Tavily.
 */
const credentialKind = computed<string | null>(() => {
  const entry = props.entry
  if (!entry) return null
  const byParam = entry.credential_kind_by_param
  if (byParam) {
    const chosen = props.params[byParam.param] ?? defaultOf(byParam.param)
    return byParam.map[String(chosen)] ?? null
  }
  return entry.credential_kind
})

function defaultOf(name: string): JsonScalar | undefined {
  const param = props.entry?.params.find((row) => row.name === name)
  return param?.default as JsonScalar | undefined
}

/** The provider chip: only for an entry whose behaviour a parameter selects. */
const provider = computed<string | null>(() => {
  const name = props.entry?.credential_kind_by_param?.param
  if (!name) return null
  const chosen = props.params[name] ?? defaultOf(name)
  return chosen == null ? null : String(chosen)
})

/**
 * The amber chip. A key is REQUIRED, and this node names none.
 *
 * The same predicate `tool_problems` uses server-side, and it is a mirror of
 * exactly one boolean rather than of the rule: the server sends
 * `credential_optional`, and this reads it. A client that re-derived "is a key
 * optional" from the kind would be a second policy quietly drifting from the
 * first.
 */
const missingKey = computed(
  () => credentialKind.value !== null && !props.entry?.credential_optional && !props.hasCredential,
)

/** A tool this deployment cannot build - `tavily-python` is not installed. */
const unavailable = computed(() => {
  const entry = props.entry
  if (!entry) return false
  if (entry.available === false) return true
  const name = entry.packages_param
  if (!name || !entry.requires_packages) return false
  const chosen = String(props.params[name] ?? defaultOf(name) ?? '')
  return (entry.requires_packages[chosen] ?? []).length > 0
})
</script>

<template>
  <div class="tool-card" :class="{ 'is-dense': dense }" data-testid="tool-card">
    <span class="tool-icon" aria-hidden="true"><Wrench :size="dense ? 12 : 14" /></span>
    <span class="tool-label" data-testid="tool-label">{{ label }}</span>

    <span v-if="provider" class="tool-chip" data-testid="tool-provider">{{ provider }}</span>

    <span
      v-if="missingKey"
      class="tool-chip is-warn"
      data-testid="tool-no-key"
      :title="`This tool needs a ${credentialKind} key and this node names none.`"
    >
      <KeyRound :size="10" aria-hidden="true" />
      no key
    </span>
    <span
      v-else-if="hasCredential"
      class="tool-chip is-key"
      data-testid="tool-key"
      title="A key of your own is attached to this tool."
    >
      <KeyRound :size="10" aria-hidden="true" />
      key
    </span>

    <span
      v-if="unavailable"
      class="tool-chip is-warn"
      data-testid="tool-unavailable"
      title="This deployment does not have the package this tool needs installed, so it would fail at the first call."
    >
      <TriangleAlert :size="10" aria-hidden="true" />
      unavailable
    </span>
  </div>
</template>

<style scoped>
.tool-card {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.tool-icon { display: inline-flex; color: var(--text-40); }
.tool-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-body);
  font: 500 var(--fs-12)/1.3 var(--font-body);
}
.is-dense .tool-label { font-size: var(--fs-11); }
.tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex: none;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--surface-well);
  color: var(--text-40);
  font: 500 10px/1.4 var(--font-mono);
  text-transform: lowercase;
}
/*
  Amber, not red. A missing key is a graph that is not finished rather than a
  graph that is wrong, and it is exactly what a tool looks like the moment it is
  dropped - the same judgement `attachment-unattached` is a warning for.
*/
.tool-chip.is-warn { background: var(--warn-bg); color: var(--warn-text); }
.tool-chip.is-key { color: var(--text-body); }
</style>
