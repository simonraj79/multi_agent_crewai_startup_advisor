<script setup lang="ts">
/**
 * "Open in Langfuse" - or nothing at all.
 *
 * Criterion 27, and the second half is the whole of it: **hidden when
 * `links.langfuse.configured` is false, rather than rendering a broken URL.**
 * A link to `undefined/project//traces/` is worse than an absent one - it looks
 * like a feature, it is clicked, and what it teaches is that this console lies.
 *
 * The URLs are the SERVER's. `trace_id_for` lives in
 * `observability/backend.py` and the plan's criterion 20 makes the link builder
 * import it, so a trace id is derived in exactly one place. Deriving the hex
 * here as well would be a second spelling of one rule, and the two would
 * disagree the first time a run id is not a UUID.
 *
 * WHERE THIS LINK IS **NOT** DRAWN, AND WHY (criterion 27, recorded 2026-09-08).
 * The run console's own run header at `#/run` carries no Langfuse link in
 * Phase 1, and it is not an oversight: the only response that carries
 * `LANGFUSE_BASE_URL` and `LANGFUSE_PROJECT_ID` is `GET /api/admin/links`,
 * which is behind `require_admin` and 404s for everybody else. The other
 * candidate is `/readyz`'s `observability` block, and `exporter_state`'s own
 * docstring rules it out in so many words - *"Deliberately NOT here: the base
 * URL and either key. A URL can carry credentials in its userinfo, `/readyz`
 * is unauthenticated"*. So an ordinary operator has no source for the host and
 * the project id, and the only way to give the console header a link would be
 * a second endpoint in `src/`, which is not this task's file and not this
 * plan's scope. The link therefore lives where a reader who CAN read those
 * constants already is: the run-history rows (session) and the admin drawer's
 * run header (session and trace). A non-admin's console is byte-identical to
 * what it has always been.
 */
import { ExternalLink } from 'lucide-vue-next'

withDefaults(
  defineProps<{
    /** `null` for a link the server did not build; the anchor is not drawn. */
    href?: string | null
    /** Whether Langfuse is configured at all. False hides every link. */
    configured?: boolean
    /** `session` or `trace` - the two things a run has. */
    kind?: 'session' | 'trace' | 'user'
    /** A compact form for a table row, where the words do not fit. */
    compact?: boolean
  }>(),
  { href: null, configured: true, kind: 'trace', compact: false },
)

const WORDS: Record<string, string> = {
  session: 'Open session in Langfuse',
  trace: 'Open trace in Langfuse',
  user: 'Open this person in Langfuse',
}
</script>

<template>
  <a
    v-if="configured && href"
    class="admin-langfuse-link"
    :class="{ 'is-compact': compact }"
    :href="href"
    target="_blank"
    rel="noreferrer noopener"
    :data-testid="`langfuse-${kind}`"
    :title="WORDS[kind]"
  >
    <ExternalLink :size="12" aria-hidden="true" />
    <span :class="{ 'sr-only': compact }">{{ WORDS[kind] }}</span>
  </a>
</template>

<style scoped>
/*
 * SCOPED, not in `admin.css`, and the reason is where this component is
 * mounted: the run console's history rows carry it too, and `admin.css` is
 * loaded by `AdminView` alone - a rule there would style the link on `#/admin`
 * and leave it a bare blue anchor on `#/run`.
 */
.admin-langfuse-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--link-strong);
  font: var(--type-meta);
  text-decoration: none;
}

.admin-langfuse-link:hover { text-decoration: underline; }
.admin-langfuse-link:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }
/* In a table cell or a history row there is no room for six words, and the
   icon plus a `sr-only` name is the whole control. */
.admin-langfuse-link.is-compact { gap: 0; }
</style>
