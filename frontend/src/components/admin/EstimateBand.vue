<script setup lang="ts">
/**
 * The error band, in the server's own sentence.
 *
 * The second half of criterion 26. `error_note` is measured - the plan quotes
 * `"measured −14.5% to +9.95% against billed"` - so it is rendered VERBATIM
 * and never paraphrased: a band this screen invented would be a band nobody
 * measured, which is worse than none.
 *
 * When the server sends no note the band says so rather than filling in. A
 * missing band is a fact about this deployment (an old build, a window with
 * nothing in it), and printing a remembered range over it would be exactly the
 * "a price written in prose is stale" failure CLAUDE.md keeps recording.
 */
defineProps<{
  note?: string | null
  /** A sentence about what is in the total, when the panel has one to add. */
  scope?: string | null
}>()
</script>

<template>
  <p class="admin-band" data-testid="admin-estimate-band">
    <span class="admin-band-lead">Every dollar here is an estimate</span>
    <span v-if="note" class="admin-band-note">{{ note }}</span>
    <span v-else class="admin-band-note is-absent">
      the server reported no error band for this window
    </span>
    <span v-if="scope" class="admin-band-scope">{{ scope }}</span>
  </p>
</template>
