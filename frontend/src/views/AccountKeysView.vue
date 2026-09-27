<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Check, Copy, KeyRound, TriangleAlert } from 'lucide-vue-next'
import AccountChip from '../components/builder/AccountChip.vue'
import BrandLockup from '../components/BrandLockup.vue'
import { PRODUCT_NAME } from '../data/brand'
import {
  API_KEY_NAME_MAX_CHARS,
  apiOrigin,
  createApiKey,
  listApiKeys,
  revokeApiKey,
} from '../services/accountApi'
import type { ApiKey } from '../services/accountApi'
import { formatStamp } from '../utils/storedTime'
import type { SignedInUser } from '../composables/useAuthGate'

/**
 * `#/account/api-keys` - personal API keys (`.agent/plans/22-api-keys.md` D9).
 *
 * A page rather than a panel, laid out like the home (`is-home`: one scrolling
 * column under the header). Three things happen here and nowhere else: a key
 * is minted, its secret is shown ONCE, and a key is revoked.
 *
 * THE SECRET LIVES IN ONE REF AND IS DROPPED ON "Done". It is never written to
 * storage, never put in the list, and never shown again - the server keeps only
 * its hash (D2), so there is nothing to show a second time even if we wanted to.
 *
 * REVOKE CONFIRMS INLINE, NOT IN A DIALOG. The editing path has no modals
 * (spec R15), and `window.confirm` stalls the browser tooling the E2E suite and
 * the verifiers drive this app with.
 */

const props = defineProps<{
  /** The signed-in account, or null when authentication is not configured. */
  user: SignedInUser | null
}>()

const emit = defineEmits<{ home: []; signOut: [] }>()

const keys = ref<ApiKey[]>([])
const limit = ref<number | null>(null)
const loading = ref(true)
const loadError = ref('')

const name = ref('')
const creating = ref(false)
const actionError = ref('')

/** The one-time secret, and the key it belongs to. Null once dismissed. */
const created = ref<{ key: ApiKey; secret: string } | null>(null)
const copied = ref(false)

/** The key id whose inline Revoke confirmation is open, if any. */
const confirming = ref<string | null>(null)
const revoking = ref<string | null>(null)

const atLimit = computed(() => limit.value !== null && keys.value.length >= limit.value)
const canCreate = computed(
  () => !loading.value && !loadError.value && !creating.value && !atLimit.value && name.value.trim().length > 0,
)

const origin = apiOrigin()
const curlLaunch = computed(
  () =>
    `curl -X POST "${origin}/api/sessions/my-script/runs" \\\n`
    + '  -H "Authorization: Bearer <key>" \\\n'
    + '  -H "Content-Type: application/json" \\\n'
    + `  -d '{"workflow_id":"<workflow id>","inputs":{"<input>":"<value>"},"gates":"auto"}'`,
)
const curlRead = computed(
  () => `curl "${origin}/api/runs/<run_id>" \\\n  -H "Authorization: Bearer <key>"`,
)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const answer = await listApiKeys()
    keys.value = answer.keys
    limit.value = answer.limit
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function create(): Promise<void> {
  if (!canCreate.value) return
  creating.value = true
  actionError.value = ''
  copied.value = false
  try {
    const answer = await createApiKey(name.value.trim())
    created.value = { key: answer.key, secret: answer.secret }
    keys.value = [answer.key, ...keys.value.filter((entry) => entry.id !== answer.key.id)]
    name.value = ''
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    creating.value = false
  }
}

async function copySecret(): Promise<void> {
  if (!created.value) return
  try {
    await navigator.clipboard.writeText(created.value.secret)
    copied.value = true
  } catch {
    // Clipboard permission is not guaranteed; the secret stays selectable.
    copied.value = false
  }
}

function dismissSecret(): void {
  created.value = null
  copied.value = false
}

async function revoke(key: ApiKey): Promise<void> {
  revoking.value = key.id
  actionError.value = ''
  try {
    await revokeApiKey(key.id)
    keys.value = keys.value.filter((entry) => entry.id !== key.id)
    if (created.value?.key.id === key.id) dismissSecret()
    confirming.value = null
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    revoking.value = null
  }
}

onMounted(() => {
  document.title = `API keys · ${PRODUCT_NAME}`
  void load()
})
</script>

<template>
  <a class="skip-link" href="#account-keys">Skip to your API keys</a>
  <div class="studio-shell is-home is-account">
    <header class="app-header">
      <BrandLockup as="link">
        <template #default>
          <h1 class="sr-only">API keys</h1>
        </template>
      </BrandLockup>

      <div class="header-context">
        <nav class="breadcrumb" aria-label="Breadcrumb">
          <a class="breadcrumb-crumb" href="#/" @click.prevent="emit('home')">Workflows</a>
          <span class="breadcrumb-sep" aria-hidden="true">/</span>
          <span class="breadcrumb-crumb is-current" aria-current="page">
            <KeyRound :size="13" aria-hidden="true" />
            <span class="breadcrumb-name">API keys</span>
          </span>
        </nav>
        <AccountChip v-if="props.user" :user="props.user" @sign-out="emit('signOut')" />
      </div>
    </header>

    <main class="home-main">
      <div class="home-page account-page">
        <section class="account-intro" aria-labelledby="account-keys-title">
          <h2 id="account-keys-title">API keys</h2>
          <p>
            Run your published workflows from your own code - a script, a cron job, a CI step or
            an automation tool. A key acts as you: its runs are yours, count against your spending
            limit, and can see only your workflows. It cannot manage keys or saved credentials.
            Treat it like a password.
          </p>
        </section>

        <p v-if="actionError" class="account-error" role="alert" data-testid="account-keys-error">
          <TriangleAlert :size="14" aria-hidden="true" /> {{ actionError }}
        </p>

        <!-- The one-time secret. Docked in the page, never a dialog. -->
        <section
          v-if="created"
          class="account-secret"
          aria-labelledby="account-secret-title"
          data-testid="account-keys-secret"
        >
          <h3 id="account-secret-title">Your new key, “{{ created.key.name }}”</h3>
          <p class="account-warn">
            <TriangleAlert :size="14" aria-hidden="true" />
            Copy it now. It will not be shown again - if you lose it, revoke it and make a new one.
          </p>
          <div class="account-secret-row">
            <code class="account-secret-value" data-testid="account-keys-secret-value">{{ created.secret }}</code>
            <button
              class="button button-secondary"
              type="button"
              data-testid="account-keys-copy"
              @click="copySecret"
            >
              <Check v-if="copied" :size="14" aria-hidden="true" />
              <Copy v-else :size="14" aria-hidden="true" />
              {{ copied ? 'Copied' : 'Copy' }}
            </button>
          </div>
          <p class="account-hint">Start a run of a published workflow, then read it back until it finishes:</p>
          <pre class="account-code" data-testid="account-keys-curl"><code>{{ curlLaunch }}

{{ curlRead }}</code></pre>
          <div class="account-actions">
            <button class="button button-primary" type="button" data-testid="account-keys-done" @click="dismissSecret">
              I have copied it
            </button>
          </div>
        </section>

        <section id="account-keys" class="account-panel" aria-labelledby="account-list-title">
          <header class="account-panel-heading">
            <h3 id="account-list-title">Your keys</h3>
            <span v-if="limit !== null" class="account-count" data-testid="account-keys-count">
              {{ keys.length }} of {{ limit }} keys
            </span>
          </header>

          <form class="account-create" @submit.prevent="create">
            <label class="account-label" for="account-key-name">Name</label>
            <input
              id="account-key-name"
              v-model="name"
              class="account-input"
              type="text"
              :maxlength="API_KEY_NAME_MAX_CHARS"
              placeholder="e.g. nightly report script"
              autocomplete="off"
              :disabled="atLimit || creating"
              data-testid="account-keys-name"
            />
            <button
              class="button button-primary"
              type="submit"
              :disabled="!canCreate"
              data-testid="account-keys-create"
            >
              {{ creating ? 'Creating…' : 'Create key' }}
            </button>
          </form>
          <p v-if="atLimit" class="account-hint" data-testid="account-keys-at-limit">
            You have the most keys one account can hold. Revoke one to make another.
          </p>

          <p v-if="loading" class="account-hint" role="status">Loading your keys…</p>
          <p v-else-if="loadError" class="account-error" role="alert" data-testid="account-keys-load-error">
            <TriangleAlert :size="14" aria-hidden="true" /> {{ loadError }}
          </p>
          <p v-else-if="keys.length === 0" class="account-hint" data-testid="account-keys-empty">
            You have no API keys yet. Name one above to create it.
          </p>

          <table v-else class="account-table" data-testid="account-keys-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Key</th>
                <th scope="col">Created</th>
                <th scope="col">Last used</th>
                <th scope="col"><span class="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="key in keys" :key="key.id" :data-testid="`account-key-${key.id}`">
                <td>{{ key.name }}</td>
                <td><code>{{ key.prefix }}…</code></td>
                <td>{{ formatStamp(key.created_at) }}</td>
                <td>{{ key.last_used_at ? formatStamp(key.last_used_at) : 'never' }}</td>
                <td>
                  <div class="account-row-actions">
                  <template v-if="confirming === key.id">
                    <span class="account-confirm">Revoke? Anything using it stops at once.</span>
                    <button
                      class="button button-secondary account-danger"
                      type="button"
                      :disabled="revoking === key.id"
                      data-testid="account-keys-revoke-confirm"
                      @click="revoke(key)"
                    >
                      {{ revoking === key.id ? 'Revoking…' : 'Revoke' }}
                    </button>
                    <button
                      class="button button-quiet"
                      type="button"
                      data-testid="account-keys-revoke-cancel"
                      @click="confirming = null"
                    >
                      Keep
                    </button>
                  </template>
                  <button
                    v-else
                    class="button button-quiet"
                    type="button"
                    data-testid="account-keys-revoke"
                    @click="confirming = key.id"
                  >
                    Revoke
                  </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* Every value is a token (`tokens.css`); surfaces are opaque (`--surface-strong`). */
.account-page { width: min(880px, 100%); gap: var(--space-6); }

.account-intro h2 { margin: 0 0 var(--space-2); font: var(--type-title); }
.account-intro p { margin: 0; color: var(--text-muted); font: var(--type-body); }

.account-panel,
.account-secret {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  background: var(--surface-strong);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
}

.account-secret { border-color: var(--warn-border-strong); }
.account-secret h3,
.account-panel h3 { margin: 0; font: var(--type-label); color: var(--text-title); }

.account-panel-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-4);
}

.account-count,
.account-hint { margin: 0; color: var(--text-muted); font: var(--type-meta); }

.account-warn,
.account-error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--r-md);
  font: var(--type-meta);
}

.account-warn { color: var(--warn-text); background: var(--warn-bg); border: 1px solid var(--warn-border); }
.account-error { color: var(--err-text); background: var(--err-bg); border: 1px solid var(--err-border); }

.account-secret-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.account-secret-value {
  flex: 1;
  min-width: 0;
  padding: var(--space-3) var(--space-4);
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
  font-size: var(--fs-13);
  color: var(--text-primary);
  background: var(--bg-app);
  border: 1px solid var(--border-control);
  border-radius: var(--r-md);
  user-select: all;
}

.account-code {
  margin: 0;
  padding: var(--space-4);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  color: var(--text-body);
  background: var(--bg-app);
  border: 1px solid var(--border-default);
  border-radius: var(--r-md);
}

.account-actions { display: flex; justify-content: flex-end; }

.account-create {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.account-label { font: var(--type-meta); color: var(--text-muted); }

.account-input {
  flex: 1;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  font: var(--type-body);
  color: var(--text-primary);
  background: var(--bg-app);
  border: 1px solid var(--border-control);
  border-radius: var(--r-md);
}

.account-table {
  width: 100%;
  border-collapse: collapse;
  font: var(--type-meta);
}

.account-table th {
  padding: var(--space-2) var(--space-3);
  text-align: left;
  color: var(--text-muted);
  font: var(--type-kicker);
  letter-spacing: var(--track-kicker);
  border-bottom: 1px solid var(--border-default);
}

.account-table td {
  padding: var(--space-3);
  color: var(--text-body);
  border-bottom: 1px solid var(--border-default);
  overflow-wrap: anywhere;
}

.account-table code { font-family: var(--font-mono); }

.account-row-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
}

.account-confirm { color: var(--warn-text); }
.account-danger { color: var(--err-text); border-color: var(--err-border-strong); }
</style>
