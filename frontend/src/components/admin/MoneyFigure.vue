<script setup lang="ts">
/**
 * A dollar figure, and the word that has to travel with it.
 *
 * `.agent/plans/17-admin-console.md` criterion 26: **every dollar on screen
 * carries the word "estimate"**. It is a component rather than a convention
 * because a convention is a thing twelve sites forget once - and the figure
 * this console prints is not a bill. It is tokens multiplied by a local price
 * table, measured wrong by −14.5 % to +9.95 % against OpenRouter's own records
 * (§9 risk 2, `docs/observability/` row E5), blind to embeddings, rerank and
 * Firecrawl entirely, and blind to prompt-cache discounts. A number of that
 * provenance printed bare is a number somebody makes a refund decision from.
 *
 * The billed figure exists and is one click away - `GET /runs/{id}/billed`,
 * fetched only on an explicit press. This component is what stands in for it
 * until somebody asks.
 */
import { money } from './adminFormat'

withDefaults(
  defineProps<{
    value: number | null | undefined
    /** `lead` is a tile's headline figure; `row` is a table cell. */
    size?: 'lead' | 'row'
    /** Suppresses the tag where a whole block is already labelled estimate. */
    tag?: boolean
  }>(),
  { size: 'row', tag: true },
)
</script>

<template>
  <span class="admin-money" :class="`is-${size}`" data-testid="admin-money">
    <span class="admin-money-amount">{{ money(value) }}</span>
    <!--
      Never `v-if`'d away to nothing: `tag: false` still renders the word, as
      a screen-reader-only span, because criterion 26 is about what the figure
      SAYS and not about how much room the layout had. The visible half is
      suppressed only where an enclosing kicker already reads `· estimate`, so
      the eye is not told twice and the machine is never told less.
    -->
    <span class="admin-money-tag" :class="{ 'sr-only': !tag }">estimate</span>
  </span>
</template>
