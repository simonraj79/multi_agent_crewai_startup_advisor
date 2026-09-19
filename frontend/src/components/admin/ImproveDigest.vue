<script setup lang="ts">
/**
 * **The only thing on this screen that costs money**, and it says so before you
 * press it.
 *
 * `.agent/plans/21-test-a-change.md` R5 and R7's fourth section. One explicit
 * `POST`, admin only, off by default, one call per click, no scheduler, no
 * retry, no fetch on mount. The ceiling is proved at import from `PRICES` on
 * the server - a model swap that broke it disables the feature rather than
 * quietly raising the bill - and what this component owes the reader is that
 * the ceiling, the model and the sample bounds are on screen BEFORE the press
 * rather than in a changelog.
 *
 * THE FIGURES ARE THE SERVER'S. The cap, the model, the two sample bounds and
 * the two input bounds all ride on the same `GET` that lists the stored
 * reviews, and when the server sends none this panel says so instead of
 * filling one in. A cap written into a client is a second answer to "what does
 * this cost", and the copy is always the half that goes stale.
 *
 * THE BODY IS RENDERED AS TEXT, NOT AS MARKUP. It is model output over data
 * this deployment's own users typed, and the escape-first renderer exists for
 * a document the reader asked for - not for a paragraph that arrives inside an
 * admin console. `white-space: pre-wrap` keeps the model's own line breaks and
 * nothing in the string can ever become an element, which is a stronger
 * guarantee than a sanitiser and needs no argument about which tags are safe.
 *
 * `over_cap` IS SHOWN, NEVER HIDDEN (R5). The measured cost is compared with
 * the cap by the server, and a breach is a fact about a call that already
 * happened: a panel that dropped it would be a spending screen editing its own
 * record.
 */
import { computed } from 'vue'
import { Sparkles, TriangleAlert } from 'lucide-vue-next'
import MoneyFigure from './MoneyFigure.vue'
import { count, money, when } from './adminFormat'
import type { ImproveDigestPage } from '../../services/adminApi'

const props = withDefaults(
  defineProps<{
    page: ImproveDigestPage | null
    /** The workflow the button would run against, or '' when none is chosen. */
    workflowId: string
    loading?: boolean
    running?: boolean
    problem?: string
  }>(),
  { loading: false, running: false, problem: '' },
)

const emit = defineEmits<{ run: [] }>()

const enabled = computed(() => props.page?.enabled === true)
const cap = computed(() => props.page?.max_cost_usd ?? null)

/** Newest first, whatever order the page arrived in. */
const rows = computed(() =>
  [...(props.page?.rows ?? [])].sort((left, right) =>
    String(right.created_at ?? '').localeCompare(String(left.created_at ?? '')),
  ),
)

/**
 * How many reviews this workflow has, and what they cost.
 *
 * `total_count` when the server counts them, and the page's own length when it
 * does not - which is a floor rather than a wrong number, and the sentence
 * reads the same either way.
 */
const reviewCount = computed(() => props.page?.total_count ?? rows.value.length)

/**
 * What one press reads, as one sentence, or `''` when the server named none.
 *
 * Assembled from whatever arrived rather than from a fixed list, so an older
 * API that carries three of the four reads as three facts instead of as three
 * facts and a dash.
 */
const bounds = computed(() => {
  const page = props.page
  if (!page) return ''
  const parts: string[] = []
  if (page.max_sample_runs) parts.push(`${count(page.max_sample_runs)} newest runs`)
  if (page.max_sample_frames) parts.push(`${count(page.max_sample_frames)} frames`)
  if (page.max_input_chars) parts.push(`${count(page.max_input_chars)} characters in`)
  if (page.max_output_tokens) parts.push(`${count(page.max_output_tokens)} tokens back`)
  return parts.join(' · ')
})

/**
 * How many reviews are left today, out of how many, or `null` for neither.
 *
 * Read off the same `GET` as the cap, and printed BEFORE the press for the
 * reason the cap is: a brake somebody only meets by hitting it is a brake that
 * reads as a fault. `remaining === 0` is a real zero and a real refusal; an
 * absent key is not zero and must never disable anything.
 */
const remaining = computed(() => {
  const value = props.page?.remaining_today
  return value === null || value === undefined || !Number.isFinite(value) ? null : value
})

const perDay = computed(() => {
  const value = props.page?.max_per_day
  return value === null || value === undefined || !Number.isFinite(value) ? null : value
})

const spentToday = computed(() => remaining.value !== null && remaining.value <= 0)

const canRun = computed(
  () =>
    enabled.value &&
    Boolean(props.workflowId) &&
    !spentToday.value &&
    !props.running &&
    !props.loading,
)

/** Why the button is off, in the order a person hits the reasons. */
const blockedBecause = computed(() => {
  if (!props.workflowId) return 'Pick a workflow first.'
  if (!enabled.value) return 'Turned off on this server. Nothing here can spend money.'
  if (spentToday.value) {
    return perDay.value === null
      ? 'No reviews left today. Try again tomorrow.'
      : `No reviews left today, out of ${count(perDay.value)}. Try again tomorrow.`
  }
  return ''
})

/**
 * A row the model never answered.
 *
 * It has no review text and no cost, and NEITHER is rendered: a `$0.00` beside
 * a failed attempt would read as "this one was free", which is the one thing
 * nobody can promise - the tokens may already have been spent, which is why
 * the attempt is a row at all.
 */
function failed(row: { error?: string | null }): boolean {
  return typeof row.error === 'string' && row.error.trim() !== ''
}
</script>

<template>
  <div class="improve-review" data-testid="improve-review">
    <p class="improve-lede">
      A short written review of these runs, by a cheap model, on one press. It reads the same counts
      the numbers above are made of and adds nothing to them.
    </p>

    <!--
      WHAT IT COSTS, BEFORE THE CLICK. Five facts and each is the server's: the
      ceiling, the model, what it reads, what it writes back, and whether the
      feature is even on here. A button that priced itself only afterwards
      would be a button somebody presses twice to find out.
    -->
    <p class="admin-warning" data-testid="improve-review-price">
      <TriangleAlert :size="13" aria-hidden="true" />
      <template v-if="cap !== null">
        This spends real money: at most {{ money(cap) }} per review.
      </template>
      <template v-else>
        This spends real money, and the server did not report a ceiling for it.
      </template>
    </p>

    <dl class="admin-facts improve-quote" data-testid="improve-review-quote">
      <div class="admin-fact">
        <dt>What one press costs, at most</dt>
        <dd v-if="cap !== null">
          up to {{ money(cap) }}
          <span class="admin-sub">checked against the price table before it is offered</span>
        </dd>
        <dd v-else class="is-absent">the server did not report a ceiling</dd>
      </div>
      <div class="admin-fact">
        <dt>Model</dt>
        <dd>
          {{ page?.model || '—' }}<span class="admin-sub">the cheap tier, and only that</span>
        </dd>
      </div>
      <div class="admin-fact">
        <dt>What it reads, and writes back</dt>
        <dd v-if="bounds">{{ bounds }}</dd>
        <dd v-else class="is-absent">the server did not report its bounds</dd>
      </div>
      <div class="admin-fact" :class="{ 'is-warn': !enabled }">
        <dt>Turned on here</dt>
        <dd v-if="enabled">yes</dd>
        <dd v-else>no<span class="admin-sub">Turned off on this server</span></dd>
      </div>
      <!--
        HOW MANY ARE LEFT TODAY, before the press. A brake somebody only meets
        by hitting it is a brake that reads as a fault; this one says what it
        is while there is still room under it.
      -->
      <div class="admin-fact" :class="{ 'is-warn': spentToday }" data-testid="improve-review-left">
        <dt>Left today</dt>
        <dd v-if="remaining !== null && perDay !== null">
          {{ count(remaining) }} of {{ count(perDay) }} reviews left today
        </dd>
        <dd v-else-if="remaining !== null">{{ count(remaining) }} reviews left today</dd>
        <dd v-else class="is-absent">the server did not report a daily allowance</dd>
      </div>
    </dl>

    <div class="improve-controls">
      <!--
        `aria-busy` while the one paid call is in flight, beside the disabled
        state rather than instead of it: `disabled` is what stops a second
        press, and `aria-busy` is what tells a reader who cannot see the word
        change that the press was taken.
      -->
      <button
        type="button"
        class="improve-button"
        :disabled="!canRun"
        :aria-busy="running ? 'true' : 'false'"
        data-testid="improve-review-run"
        @click="emit('run')"
      >
        <Sparkles :size="13" aria-hidden="true" />
        {{ running ? 'Writing…' : 'Ask a model to review' }}
      </button>
      <!--
        `role="status"` on the flag, so a reader who never sees the pressed
        state of a button is still told the feature is off here.
      -->
      <span
        v-if="blockedBecause"
        class="improve-note"
        role="status"
        data-testid="improve-review-blocked"
      >
        {{ blockedBecause }}
      </span>
      <span v-else class="improve-note">One call. No retry, no schedule, nothing on page load.</span>
    </div>

    <p v-if="problem" class="admin-problem" role="alert" data-testid="improve-review-problem">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Reading stored reviews…</p>

    <!--
      WHAT REVIEWS HAVE COST THIS WORKFLOW so far - every stored row's cost
      summed by the server, never re-added here. Kept above the list rather than
      beside the button: the button prices one press, this prices every press
      this workflow has already spent.
    -->
    <!--
      FOUND BY LOOKING. `MoneyFigure` prints the word `estimate` after the
      figure, which is criterion 26 working exactly as written - and in the
      middle of a sentence it came out as "$0.01 ESTIMATE spent". The tag is
      suppressed to screen-reader-only and the word carried by the kicker at
      the end of the line instead, which is the arrangement that component
      documents for precisely this case: the eye is not told twice and the
      machine is never told less.
    -->
    <p v-if="page" class="admin-sub improve-review-total" data-testid="improve-review-total">
      Reviews so far: {{ count(reviewCount) }},
      <template v-if="page.total_cost_usd !== null && page.total_cost_usd !== undefined">
        <MoneyFigure :value="page.total_cost_usd" :tag="false" /> spent · estimate
      </template>
      <template v-else>and the server did not report what they cost</template>
    </p>

    <ul v-if="rows.length" class="improve-review-list" data-testid="improve-review-rows">
      <li
        v-for="row in rows"
        :key="row.id"
        class="improve-review-row"
        :class="{ 'is-failed': failed(row) }"
      >
        <!--
          A FAILED ATTEMPT IS A ROW, and it is a row because it may already
          have been billed. It carries no review text and no cost: `$0.00`
          beside it would say it was free, which is exactly the thing nobody
          can promise about a call whose tokens may have been spent.
        -->
        <template v-if="failed(row)">
          <header class="improve-review-head">
            <span class="improve-review-when">{{ when(row.created_at) }}</span>
            <span class="admin-sub">
              {{ row.model }}
              <template v-if="row.sample_runs"> · {{ count(row.sample_runs) }} run(s) read</template>
            </span>
          </header>
          <p class="admin-warning" role="status" :data-testid="`improve-review-failed-${row.id}`">
            <TriangleAlert :size="13" aria-hidden="true" />
            The model did not answer. The attempt was recorded because it may still have been
            billed.
          </p>
        </template>
        <template v-else>
        <header class="improve-review-head">
          <span class="improve-review-when">{{ when(row.created_at) }}</span>
          <span class="admin-sub">
            <!-- THE MEASURED COST, beside the ceiling it was made under. A
                 constant can move between the press and the reading, so the
                 row's own ceiling wins over today's. -->
            cost <MoneyFigure :value="row.cost_usd ?? null" :tag="false" />
            <template v-if="(row.max_cost_usd ?? cap) !== null">
              of the {{ money(row.max_cost_usd ?? cap) }} ceiling
            </template>
            · {{ row.model }} · {{ count(row.sample_runs) }} run(s) read
            <template v-if="row.sample_frames"> · {{ count(row.sample_frames) }} frames</template>
            <template v-if="row.prompt_tokens">
              · {{ count(row.prompt_tokens) }} in / {{ count(row.completion_tokens) }} out
            </template>
            <template v-if="row.truncated_sample">
              · the sample was clipped to fit, so this review read less than the window holds
            </template>
          </span>
        </header>
        <p
          v-if="row.over_cap"
          class="admin-warning"
          role="status"
          :data-testid="`improve-review-over-cap-${row.id}`"
        >
          <TriangleAlert :size="13" aria-hidden="true" />
          This one came out above the ceiling it was meant to stay under. It has already been paid
          for; check the model and the ceiling before asking for another.
        </p>
        <p class="improve-review-body">{{ row.body }}</p>
        </template>
      </li>
    </ul>
    <p v-else-if="!loading && !problem" class="admin-empty" data-testid="improve-review-empty">
      Nobody has asked for a review of this workflow. The numbers above are complete without one.
    </p>
  </div>
</template>

<style scoped>
.improve-review { display: grid; gap: var(--space-3); }
.improve-lede,
.improve-note { margin: 0; color: var(--text-meta); font: var(--type-meta); line-height: 1.55; }
.improve-note { color: var(--text-40); }

.improve-quote {
  padding: var(--space-4);
  background: var(--surface-well);
  border: 1px solid var(--border-control);
  border-radius: var(--r-md);
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
}

.improve-controls { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: center; }

.improve-button {
  display: inline-flex;
  gap: var(--space-2);
  align-items: center;
  min-height: 44px;
  padding: var(--space-2) var(--space-4);
  color: var(--text-title);
  font: var(--type-label);
  background: var(--surface-raised);
  border: 1px solid var(--border-control);
  border-radius: var(--r-sm);
  cursor: pointer;
}

.improve-button:hover:not(:disabled) { border-color: var(--border-hover-strong); }
.improve-button:disabled { opacity: 0.45; cursor: default; }
.improve-button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 1px; }

.improve-review-list { display: grid; gap: var(--space-3); margin: 0; padding: 0; list-style: none; }

.improve-review-row {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-4);
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}

.improve-review-row.is-failed { border-color: var(--warn-border); }
.improve-review-head { display: grid; gap: var(--space-1); }
.improve-review-when { color: var(--text-body); font: var(--type-label); }

/* MODEL OUTPUT, AS TEXT. `pre-wrap` keeps the model's own paragraphs without
   any of it becoming an element, and `overflow-wrap` stops one unbroken string
   from widening the panel it sits in. */
.improve-review-body {
  margin: 0;
  color: var(--text-body);
  font: var(--type-meta);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
