<script setup lang="ts">
/**
 * The sign-in wall.
 *
 * Deliberately says what the console DOES before asking for an account. A
 * bare "Sign in with Google" on an unexplained dark page is indistinguishable
 * from a phishing prompt, and this one asks for a Google identity on a
 * `.onrender.com` host, which is exactly the shape people are told to distrust.
 * Naming the app, the provider and what is stored is the cheapest way to earn
 * the click honestly.
 */
import { CircleDot, LoaderCircle, ShieldCheck } from 'lucide-vue-next'

defineProps<{
  signingIn: boolean
  error: string | null
}>()

const emit = defineEmits<{ (event: 'signIn'): void }>()
</script>

<template>
  <div class="signin-shell">
    <main class="signin-card">
      <div class="signin-brand">
        <div class="brand-mark" aria-hidden="true">
          <CircleDot :size="20" :stroke-width="1.8" />
        </div>
        <div>
          <span>M2</span>
          <h1>Validator Studio</h1>
        </div>
      </div>

      <p class="signin-lede">
        A six-agent crew that scores a startup idea against real market,
        sentiment and feasibility evidence &mdash; and shows its working, live.
      </p>

      <button
        class="google-button"
        type="button"
        :disabled="signingIn"
        @click="emit('signIn')"
      >
        <LoaderCircle v-if="signingIn" class="spin" :size="18" aria-hidden="true" />
        <svg v-else class="google-g" viewBox="0 0 18 18" aria-hidden="true">
          <path
            fill="#4285F4"
            d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z"
          />
          <path
            fill="#34A853"
            d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z"
          />
          <path
            fill="#FBBC05"
            d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z"
          />
          <path
            fill="#EA4335"
            d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z"
          />
        </svg>
        <span>{{ signingIn ? 'Opening Google…' : 'Continue with Google' }}</span>
      </button>

      <p v-if="error" class="signin-error" role="alert">{{ error }}</p>

      <p class="signin-note">
        <ShieldCheck :size="14" aria-hidden="true" />
        <span>
          Google confirms who you are. This app stores your name, email and
          profile picture, and keeps your runs private to your account.
        </span>
      </p>
    </main>
  </div>
</template>

<style scoped>
.signin-shell {
  display: grid;
  place-items: center;
  min-height: 100vh;
  padding: 24px;
  background:
    radial-gradient(60% 50% at 50% 0%, rgba(153, 234, 249, 0.09), transparent 70%),
    var(--bg-app);
}

.signin-card {
  display: flex;
  flex-direction: column;
  gap: 20px;
  width: min(420px, 100%);
  padding: 32px;
  background: var(--surface-panel);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
}

.signin-brand { display: flex; align-items: center; gap: 12px; }
.signin-brand span { color: var(--accent-mint); font: 700 var(--fs-11)/1 var(--font-mono); }
.signin-brand h1 {
  margin: 2px 0 0;
  color: var(--text-title);
  font: 600 var(--fs-18)/1.2 var(--font-display);
}

.brand-mark {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  color: var(--accent-cyan);
  background: rgba(153, 234, 249, 0.08);
  border: 1px solid rgba(153, 234, 249, 0.28);
  border-radius: var(--r-lg);
}

.signin-lede {
  margin: 0;
  color: var(--text-muted);
  font: 400 var(--fs-14)/1.55 var(--font-body);
}

.google-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 100%;
  padding: 12px 16px;
  color: var(--text-title);
  font: 600 var(--fs-14)/1 var(--font-body);
  background: var(--surface-raised);
  border: 1px solid var(--border-hover);
  border-radius: var(--r-lg);
  cursor: pointer;
  transition: background var(--motion-fast), border-color var(--motion-fast);
}

.google-button:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.09);
  border-color: var(--accent-cyan);
}

.google-button:focus-visible { outline: 2px solid var(--accent-cyan); outline-offset: 2px; }
.google-button:disabled { cursor: progress; opacity: 0.7; }

.google-g { flex: none; width: 18px; height: 18px; }

.spin { animation: signin-spin 900ms linear infinite; }

/* The button is the only moving thing on this screen, and someone who has
   asked their OS for less motion should not have it spinning at them. */
@media (prefers-reduced-motion: reduce) {
  .spin { animation: none; }
}

@keyframes signin-spin {
  to { transform: rotate(360deg); }
}

.signin-error {
  margin: 0;
  padding: 10px 12px;
  color: var(--err-text);
  font: 500 var(--fs-13)/1.5 var(--font-body);
  background: var(--err-bg);
  border: 1px solid var(--err-border);
  border-radius: var(--r-md);
}

.signin-note {
  display: flex;
  gap: 8px;
  margin: 0;
  padding-top: 4px;
  color: var(--text-40);
  font: 400 var(--fs-12)/1.5 var(--font-body);
  border-top: 1px solid var(--border-default);
  padding-top: 16px;
}

.signin-note svg { flex: none; margin-top: 2px; }
</style>
