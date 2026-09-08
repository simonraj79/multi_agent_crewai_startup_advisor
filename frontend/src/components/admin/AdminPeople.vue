<script setup lang="ts">
/**
 * Who is here, what they have, and what they have spent.
 *
 * A table rather than cards: every column is a number a reader compares across
 * rows, and nine grouped queries merged in Python (§3) exist precisely so this
 * can be one row per person rather than a fan-out join that multiplies them.
 *
 * `unowned runs` IS A ROW. `runs.user_id IS NULL` collapses to the reserved key
 * `__unowned__` and never merges with an account and is never dropped - those
 * runs were made by somebody, they cost real money, and a table that quietly
 * omitted them would not add up to the Money panel's total.
 *
 * `committed` CARRIES ITS OWN WARNING. `registry.account_spend` is memory-only
 * and lost on restart (§9 row 5), so it is shown beside the durable figure and
 * never folded into one headline.
 */
import { computed } from 'vue'
import { TriangleAlert, Users } from 'lucide-vue-next'
import MoneyFigure from './MoneyFigure.vue'
import { count, money, personLabel, when } from './adminFormat'
import type { AdminUserRow, AdminUsersPage } from '../../services/adminApi'

const props = defineProps<{
  page: AdminUsersPage | null
  sort: 'spend' | 'recent' | 'joined'
  selectedId: string | null
  loading: boolean
  problem: string
}>()

const emit = defineEmits<{
  openPerson: [userId: string]
  selectSort: [sort: 'spend' | 'recent' | 'joined']
}>()

const SORTS: ReadonlyArray<{ id: 'spend' | 'recent' | 'joined'; label: string }> = [
  { id: 'spend', label: 'Most spent' },
  { id: 'recent', label: 'Most recent run' },
  { id: 'joined', label: 'Newest account' },
]

const rows = computed(() => props.page?.rows ?? [])

function capWords(row: AdminUserRow): string {
  if (row.exempt) return 'exempt'
  return row.cap_usd === null ? 'no cap' : money(row.cap_usd)
}
</script>

<template>
  <section class="admin-panel" aria-labelledby="admin-people-title">
    <h2 id="admin-people-title" class="sr-only">People</h2>

    <div class="admin-axis" role="group" aria-label="Sort people by">
      <button
        v-for="option in SORTS"
        :key="option.id"
        class="admin-axis-button"
        type="button"
        :class="{ 'is-active': option.id === sort }"
        :aria-pressed="option.id === sort"
        :data-testid="`admin-sort-${option.id}`"
        @click="emit('selectSort', option.id)"
      >
        {{ option.label }}
      </button>
    </div>

    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Merging the per-account reads…</p>

    <div v-if="rows.length" class="admin-table-wrap">
      <table class="admin-table" data-testid="admin-people-table">
        <caption class="sr-only">
          Every account, with its spend, its cap and what it has built. Spend is an estimate.
        </caption>
        <thead>
          <tr>
            <th scope="col">Person</th>
            <th scope="col">Joined</th>
            <th scope="col">Last run</th>
            <th scope="col" class="is-number">Runs</th>
            <th scope="col" class="is-number">Spend · estimate</th>
            <th scope="col" class="is-number">Cap</th>
            <th scope="col" class="is-number">Graphs</th>
            <th scope="col" class="is-number">Keys</th>
            <th scope="col" class="is-number">Firecrawl today</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.user_id"
            :class="{ 'is-selected': row.user_id === selectedId }"
          >
            <th scope="row">
              <button
                class="admin-linkish"
                type="button"
                :data-testid="`admin-person-${row.user_id}`"
                @click="emit('openPerson', row.user_id)"
              >
                <Users :size="12" aria-hidden="true" />
                {{ personLabel(row.user_id, row.email) }}
              </button>
              <span v-if="row.exempt" class="admin-pill">exempt</span>
            </th>
            <td>{{ when(row.created_at) }}</td>
            <td>{{ when(row.last_run_at) }}</td>
            <td class="is-number">{{ count(row.runs) }}</td>
            <td class="is-number">
              <MoneyFigure :value="row.spent_usd" :tag="false" />
              <span v-if="row.committed_usd > 0" class="admin-sub">
                + {{ money(row.committed_usd) }} committed<span v-if="row.committed_is_volatile">
                  (lost on restart)</span>
              </span>
            </td>
            <td class="is-number">{{ capWords(row) }}</td>
            <td class="is-number">
              {{ count(row.documents ?? 0) }}<span v-if="row.published" class="admin-sub">
                {{ count(row.published) }} live</span>
            </td>
            <td class="is-number">{{ count(row.credentials ?? 0) }}</td>
            <td class="is-number">{{ count(row.firecrawl_today ?? 0) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else-if="!loading && !problem" class="admin-empty">No account has run anything yet.</p>

    <p v-if="page?.next" class="admin-warning" role="status">
      There are more accounts than this page holds.
    </p>

    <p class="admin-absent">
      <strong>Declared absent.</strong> Sign-ins and page views are recorded nowhere, on either
      server. <em>Last run</em> is the closest thing this console has to "was anybody here", and it
      is a run rather than a visit.
    </p>
  </section>
</template>
