<script setup lang="ts">
/**
 * Is the machine well, and what is it blind to.
 *
 * The fifth panel, and the only one whose most important content is a
 * paragraph. §9 row 14: this console cannot see sign-ins, page views, request
 * latency, status codes or uptime, on either server - so **it says so in
 * words**, because a blank tile reads as a zero and a zero here would be a
 * claim nobody can support.
 *
 * The three upstream probes each degrade to `{available: false, reason}` at
 * HTTP 200 (§3), and this panel renders the reason rather than a dash. A dead
 * upstream must never be indistinguishable from a healthy one reporting zero.
 */
import { computed } from 'vue'
import { Server, TriangleAlert } from 'lucide-vue-next'
import { count, money, when } from './adminFormat'
import { probeAvailable } from '../../services/adminApi'
import type { AdminHealth, AdminLinks, AdminProviders } from '../../services/adminApi'

const props = defineProps<{
  health: AdminHealth | null
  providers: AdminProviders | null
  links: AdminLinks | null
  loading: boolean
  problem: string
}>()

/**
 * `/readyz`'s own body, read for the two facts a person asks for first.
 *
 * Read defensively rather than typed: `/health` returns the readiness payload
 * VERBATIM (§3, criterion 13) precisely so the two can never disagree, and the
 * price of that is that its shape belongs to `health_payload` rather than to
 * this file. A key that moves must show as `—` here, never as a crash on the
 * one screen somebody opens when things are already wrong.
 */
function readyzField(...path: string[]): string {
  let cursor: unknown = props.health?.readyz
  for (const key of path) {
    if (typeof cursor !== 'object' || cursor === null) return '—'
    cursor = (cursor as Record<string, unknown>)[key]
  }
  if (cursor === null || cursor === undefined) return '—'
  if (typeof cursor === 'boolean') return cursor ? 'yes' : 'no'
  return String(cursor)
}

/**
 * The storage backend, found rather than addressed.
 *
 * `readyz.dependencies` is `registry.dependency_status()`, whose KEYS are the
 * registry's own - `storage` and `executor` on this build - and `readyz` is
 * typed `dict[str, Any]` all the way through, so criterion 21's key check does
 * not reach inside it. Naming one key here would be a fourth spelling of a
 * shape nobody owns; the honest read is "the dependency that reports a
 * backend", which survives a rename and answers `—` if the concept goes away.
 *
 * MEASURED, not assumed: the committed fixture's illustrative `readyz` says
 * `dependencies.persistence`, and the running service says
 * `dependencies.storage`. The E2E found that, and this is the repair.
 */
const storageBackend = computed(() => {
  const readyz = props.health?.readyz
  const dependencies =
    typeof readyz === 'object' && readyz !== null
      ? (readyz as Record<string, unknown>).dependencies
      : null
  if (typeof dependencies !== 'object' || dependencies === null) return '—'
  for (const value of Object.values(dependencies as Record<string, unknown>)) {
    if (typeof value !== 'object' || value === null) continue
    const backend = (value as Record<string, unknown>).backend
    if (typeof backend === 'string' && backend) return backend
  }
  return '—'
})

const openrouter = computed(() => props.providers?.openrouter ?? null)
const firecrawl = computed(() => props.providers?.firecrawl ?? null)
const langfuse = computed(() => props.providers?.langfuse ?? null)

const integrity = computed(() => props.health?.integrity ?? null)

/** Anything above zero on these three is a lost frame, and lost frames are
 *  what makes every other figure on this console a floor. */
const integrityClean = computed(() => {
  const rows = integrity.value
  if (!rows) return true
  return rows.dropped === 0 && rows.gaps === 0 && rows.emit_errors === 0
})
</script>

<template>
  <section class="admin-panel" aria-labelledby="admin-health-title">
    <h2 id="admin-health-title" class="sr-only">Health</h2>

    <p v-if="problem" class="admin-problem" role="alert">
      <TriangleAlert :size="14" aria-hidden="true" />{{ problem }}
    </p>
    <p v-else-if="loading" class="admin-loading" role="status">Probing…</p>

    <div class="admin-blocks">
      <section class="admin-block" aria-labelledby="admin-now-title">
        <header class="admin-block-head">
          <h3 id="admin-now-title">Right now</h3>
          <span class="panel-meta"><Server :size="12" aria-hidden="true" /> /readyz, verbatim</span>
        </header>
        <dl class="admin-facts" data-testid="admin-readyz">
          <div class="admin-fact">
            <dt>API</dt>
            <dd>{{ readyzField('status') }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Storage</dt>
            <dd>{{ storageBackend }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Gates open · expired</dt>
            <dd>{{ readyzField('gates', 'open') }} · {{ readyzField('gates', 'expired') }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Trace exporter</dt>
            <dd>{{ readyzField('observability', 'exporter') }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Why</dt>
            <dd>{{ readyzField('observability', 'reason') }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Environment</dt>
            <dd>{{ readyzField('observability', 'environment') }}</dd>
          </div>
          <div class="admin-fact">
            <dt>Runs stuck past grace</dt>
            <dd>{{ count(health?.orphans) }}</dd>
          </div>
        </dl>
      </section>

      <section class="admin-block" aria-labelledby="admin-integrity-title">
        <header class="admin-block-head">
          <h3 id="admin-integrity-title">Stream integrity</h3>
          <span class="panel-meta">from runs</span>
        </header>
        <dl v-if="integrity" class="admin-facts" data-testid="admin-integrity">
          <div class="admin-fact">
            <dt>Frames captured</dt>
            <dd>{{ count(integrity.captured) }}</dd>
          </div>
          <div class="admin-fact" :class="{ 'is-warn': !integrityClean }">
            <dt>Dropped · gaps · emit errors</dt>
            <dd>
              {{ count(integrity.dropped) }} · {{ count(integrity.gaps) }} ·
              {{ count(integrity.emit_errors) }}
            </dd>
          </div>
          <div class="admin-fact">
            <dt>Subscriber drops</dt>
            <dd>
              {{ count(integrity.subscriber_dropped) }} across
              {{ count(integrity.runs_with_drop) }} run(s)
            </dd>
          </div>
        </dl>
        <p v-else-if="!loading" class="admin-empty">The integrity read has not answered.</p>
      </section>
    </div>

    <section class="admin-block" aria-labelledby="admin-providers-title">
      <header class="admin-block-head">
        <h3 id="admin-providers-title">Upstream</h3>
        <span class="panel-meta">probed server-side, behind a short cache</span>
      </header>
      <dl class="admin-facts" data-testid="admin-providers">
        <div class="admin-fact">
          <dt>OpenRouter balance</dt>
          <dd v-if="probeAvailable(openrouter)">
            <template v-if="openrouter.remaining_usd !== null">
              {{ money(openrouter.remaining_usd) }} left
            </template>
            <template v-else>
              {{ money(openrouter.usage) }} used of {{ money(openrouter.limit) }}
            </template>
            <span class="admin-sub">
              source: {{ openrouter.source }}<template v-if="openrouter.source === 'key'">
                — a management key would give the account balance</template>
              <template v-if="openrouter.checked_at"> · read {{ when(openrouter.checked_at) }}</template>
            </span>
          </dd>
          <dd v-else class="is-absent">
            unavailable<span class="admin-sub">{{ openrouter?.reason ?? 'not probed' }}</span>
          </dd>
        </div>
        <div class="admin-fact">
          <dt>Firecrawl credits</dt>
          <dd v-if="probeAvailable(firecrawl)">
            {{ count(firecrawl.remaining_credits) }} of {{ count(firecrawl.plan_credits) }}
            <span v-if="firecrawl.billing_period_end" class="admin-sub">
              period ends {{ when(firecrawl.billing_period_end) }}
            </span>
          </dd>
          <dd v-else class="is-absent">
            unavailable<span class="admin-sub">{{ firecrawl?.reason ?? 'not probed' }}</span>
          </dd>
        </div>
        <div class="admin-fact">
          <dt>Langfuse</dt>
          <dd v-if="probeAvailable(langfuse)">
            exporter {{ langfuse.exporter }}
            <span class="admin-sub">
              {{ langfuse.environment ?? 'environment unset' }} ·
              project {{ langfuse.project_configured ? 'configured' : 'not configured' }}
            </span>
          </dd>
          <dd v-else class="is-absent">
            unavailable<span class="admin-sub">{{ langfuse?.reason ?? 'not probed' }}</span>
          </dd>
        </div>
      </dl>
      <p v-if="links" class="admin-links">
        <a :href="links.openrouter_credits_url" target="_blank" rel="noreferrer noopener">
          OpenRouter credits
        </a>
        <a :href="links.openrouter_activity_url" target="_blank" rel="noreferrer noopener">
          OpenRouter activity
        </a>
        <a :href="links.firecrawl_dashboard_url" target="_blank" rel="noreferrer noopener">
          Firecrawl billing
        </a>
      </p>
    </section>

    <section class="admin-block" aria-labelledby="admin-retention-title">
      <header class="admin-block-head">
        <h3 id="admin-retention-title">Retention</h3>
      </header>
      <p class="admin-facts-line" data-testid="admin-retention">
        {{ health === null ? '—' : health.retention_days === 0
          ? '0 days · keep everything'
          : `${count(health.retention_days)} days` }}
      </p>
      <!--
        §9 row 4, and it is the sharpest warning on this screen: a purge
        cascades from `runs` to `run_frames`, `run_node_metrics` and
        `run_gates`, so raising this destroys the verdict history, the gate
        latency AND the lifetime spend every account cap is computed from - and
        a purged account's cap silently resets to nothing spent.
      -->
      <p class="admin-warning" role="status" data-testid="admin-retention-warning">
        <TriangleAlert :size="13" aria-hidden="true" />
        Do not raise this. A purge cascades from runs to frames, node metrics and gates: verdict
        history, gate latency and the lifetime spend behind every account cap go with it, and a
        purged account's cap silently resets to zero spent.
      </p>
    </section>

    <!--
      WHAT THIS CONSOLE CANNOT SEE, IN THE SERVER'S OWN WORDS.
      `AdminHealthModel.blind_to` is a list of sentences the API ships, and it
      is rendered verbatim: the list is a fact about which instruments exist in
      THIS deployment, and a client copy of it would be the thing that goes
      stale the day one of them is built. The fallback below is one sentence
      rather than a second list, so an older server degrades to less rather
      than to something untrue.
    -->
    <div class="admin-absent" data-testid="admin-blind">
      <strong>Not measured anywhere.</strong>
      <ul v-if="health?.blind_to?.length" class="admin-plain">
        <li v-for="line in health.blind_to" :key="line">{{ line }}</li>
      </ul>
      <span v-else>
        Uptime history, request latency, status-code counts, sign-ins and page views. There is no
        request log on the Node origin.
      </span>
      <span>A blank tile here means the instrument does not exist, not that the figure is zero.</span>
    </div>
  </section>
</template>
