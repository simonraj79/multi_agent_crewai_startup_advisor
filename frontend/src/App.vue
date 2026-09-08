<script setup lang="ts">
import { ref, watch } from 'vue'
import BrandLockup from './components/BrandLockup.vue'
import SignInPanel from './components/SignInPanel.vue'
import AdminView from './views/AdminView.vue'
import HomeView from './views/HomeView.vue'
import StudioView from './views/StudioView.vue'
import BuilderView from './components/builder/BuilderView.vue'
import { useAuthGate } from './composables/useAuthGate'
import { useStudioTheme } from './composables/useStudioTheme'
import { useWorkspaceRoute } from './composables/useWorkspaceRoute'
import { adminProbed, adminWhoami, probeAdmin, resetAdminGate } from './services/adminApi'
import type { WorkspaceRoute } from './composables/useWorkspaceRoute'

/**
 * The auth gate, then the route. Nothing else lives here any more.
 *
 * The console that used to be this file's whole body is `views/StudioView.vue`,
 * moved out unchanged; the builder is `BuilderView`; the home is `HomeView`.
 * Keeping the gate HERE and only here is what makes the workspaces the same
 * product rather than three apps behind one login: there is one session
 * request, one splash while it is in flight, and one sign-in wall, and no view
 * can accidentally render before the answer.
 *
 * WHY THE GATE IS OUTSIDE THE ROUTER. `#/build` reached before a session
 * resolves must show the same splash as `#/`, not a builder that will be
 * replaced by a login wall a tick later. Routing first and gating inside each
 * view would put that flash in three places and fix it in one.
 */

const {
  phase: authPhase,
  user: signedInUser,
  signingIn,
  signInError,
  startGoogleSignIn,
  endSession,
} = useAuthGate()

/**
 * The theme, started here rather than in one view.
 *
 * `useStudioTheme` resolves the stored preference (or `prefers-color-scheme`)
 * and writes `data-theme` on `<html>`, which is the only thing `tokens.css`'s
 * light palette reads. Until 2026-09-06 its ONLY caller was `BuilderView`, so
 * the attribute was written when and only when somebody opened the builder:
 * the run console rendered dark for a reader whose system is light, and it
 * rendered light after a visit to the builder in the same tab - the same page,
 * two palettes, decided by where you had been.
 *
 * Called with no arguments and its result discarded on purpose. The composable
 * is a module singleton behind a `started` guard, so this is the START and the
 * builder's own call goes on returning the same `setTheme`/`toggleTheme` it
 * always did. There is no toggle on this shell's header yet; that is a
 * follow-up, and it belongs beside a control rather than in the router.
 */
useStudioTheme()

const { route, navigate: setRoute } = useWorkspaceRoute()

/**
 * Whether the home may still hand over to the console (`DEFINITION-OF-DONE.md`
 * D2, and `homeResumesConsole` in `useWorkspaceRoute.ts` is the rule).
 *
 * True only while this page load has not navigated anywhere yet, which is the
 * exact shape of the thing the hand-over is for: a reload, with a run still in
 * flight or a graph the builder has just published. Pressing `Workflows` from a
 * live console is a navigation, so the window is shut by then and the home
 * stays put - without this the breadcrumb would bounce straight back and read
 * as broken. It is a ref rather than a module flag so a remount in a test
 * starts from a known state.
 */
const resumeOnLoad = ref(route.value.name === 'home')

function navigate(next: WorkspaceRoute, options: { replace?: boolean } = {}): void {
  resumeOnLoad.value = false
  setRoute(next, options)
}

/**
 * `replace`, not push: Back from the console must reach whatever was there
 * before the reload, rather than a home that would only redirect again.
 */
function resumeConsole(): void {
  navigate({ name: 'studio' }, { replace: true })
}

/**
 * Which template the builder should seed itself with, handed over the route
 * change rather than through it.
 *
 * The home opens a template by navigating to `#/build` and passing the id as a
 * prop. THE ALTERNATIVE WAS A QUERY - `#/build?template=<id>` - and it was
 * refused for a specific reason rather than on taste: `workspaceRoute` and
 * `routeHash` are exact inverses, asserted in both directions, and a template
 * id in the hash is a fourth field on a route that has to survive that round
 * trip while meaning nothing on a reload. A template is a thing you PICKED one
 * click ago, not an address: reloading `#/build` should show the gallery, which
 * is exactly what a prop that does not survive a reload gives you.
 *
 * Cleared when the builder has taken it, so a later `#/build` opens the gallery
 * rather than re-seeding the template the reader opened this morning.
 */
const pendingTemplate = ref<string | null>(null)

function openTemplate(templateId: string): void {
  pendingTemplate.value = templateId
  navigate({ name: 'builder', documentId: null })
}

/* ── the admin gate (plan 17, criterion 24) ────────────────────────────────
 *
 * `GET /api/admin/whoami` is the ONLY thing that decides whether `#/admin`
 * exists. It answers 404 - FastAPI's own body, byte for byte - for an
 * anonymous caller, for a signed-in non-admin and for a deployment with
 * `ADMIN_EMAILS` unset, so a refused reader cannot tell the route from one
 * that was never built (§9 row 9).
 *
 * THE ROUTER IS NOT THE GATE. Anybody can type `#/admin`; what they get is a
 * bounce to the home with one sentence, and no fabricated screen at any point
 * in between. Deciding it here rather than in `workspaceRoute` keeps the rule
 * where the answer is - the server's - instead of in a parser a reader can
 * edit with the devtools open.
 */
const adminNotice = ref('')

/**
 * The sentence a refused visitor lands on. One, and it says what happened
 * without saying whether the route exists - the same discretion the 404 keeps.
 */
const ADMIN_REFUSED =
  'That address is not available on this account.'

/**
 * Ask once the session is settled, and once only.
 *
 * `checking` is skipped because the probe carries a bearer token and minting
 * one before the gate has answered would race `useAuthGate`'s own request; a
 * sign-out resets the gate outright, because the next person on this browser
 * is not this one and an Admin entry left in the header would be a claim about
 * somebody who has gone.
 */
watch(
  () => authPhase.value,
  (phase) => {
    if (phase === 'authenticated' || phase === 'unconfigured') {
      void probeAdmin()
      return
    }
    if (phase === 'anonymous') resetAdminGate()
  },
  { immediate: true },
)

/**
 * A refused `#/admin` lands on the home. Watched rather than computed because
 * the answer arrives after the route does: a reader who pastes the address
 * gets the route first and the verdict a round trip later, and the screen must
 * show neither an admin console nor a wrong error in between.
 */
watch(
  [() => route.value.name, adminProbed, adminWhoami],
  ([name, probed, who]) => {
    if (name !== 'admin') return
    if (!probed || who !== null) return
    adminNotice.value = ADMIN_REFUSED
    navigate({ name: 'home' }, { replace: true })
  },
  { immediate: true },
)

/** The notice is for the landing, not for the session: any later navigation
 *  clears it, so it cannot follow a reader around. */
watch(
  () => route.value.name,
  (name) => {
    if (name !== 'home') adminNotice.value = ''
  },
)
</script>

<template>
  <!--
    Three states, and the middle one is why `checking` exists at all. Rendering
    the sign-in screen while the session request is still in flight makes an
    already-signed-in visitor see a login wall flash on every page load, which
    reads as "it logged me out again".
  -->
  <div v-if="authPhase === 'checking'" class="auth-splash" role="status" aria-live="polite">
    <!--
      The STATIC lockup, so the one moment the page is otherwise blank still
      says which product is loading. `.auth-splash` is a centred column, so the
      lockup stacks above the sentence rather than beside it.
    -->
    <BrandLockup as="static" :mark-size="22" />
    <p>Checking your session…</p>
  </div>

  <SignInPanel
    v-else-if="authPhase === 'anonymous'"
    :signing-in="signingIn"
    :error="signInError"
    @sign-in="startGoogleSignIn"
  />

  <!--
    Three views, and the two canvases each mount their own <VueFlow> with a
    distinct `id` (`studio-flow` / `builder-flow`). `useVueFlow` keys viewport,
    selection and node state per instance id, so two instances sharing one would
    trade viewports across a route change - the builder would open at whatever
    zoom the run console was left at, and a fitView in one would move the other.
    The home mounts no canvas at all: its pictures are `GraphThumbnail`, which
    is a static SVG.
  -->
  <HomeView
    v-else-if="route.name === 'home'"
    :user="signedInUser"
    :resume-on-load="resumeOnLoad"
    :notice="adminNotice"
    @resume="resumeConsole"
    @run="navigate({ name: 'studio' })"
    @build="navigate({ name: 'builder', documentId: null })"
    @open-document="navigate({ name: 'builder', documentId: $event })"
    @open-template="openTemplate"
    @admin="navigate({ name: 'admin' })"
    @sign-out="endSession"
  />

  <!--
    The admin console, drawn only for somebody the SERVER has already called an
    admin. The `v-if` is the whoami answer rather than the route: while the
    probe is in flight a reader who pasted `#/admin` sees the splash they would
    see for any other unsettled state, and never a console that a tick later
    turns out not to be theirs. A refused reader never reaches this element -
    the watcher above has already sent them home with a sentence.
  -->
  <AdminView
    v-else-if="route.name === 'admin' && adminWhoami !== null"
    :user="signedInUser"
    @home="navigate({ name: 'home' })"
    @sign-out="endSession"
  />

  <div
    v-else-if="route.name === 'admin'"
    class="auth-splash"
    role="status"
    aria-live="polite"
  >
    <BrandLockup as="static" :mark-size="22" />
    <p>Checking…</p>
  </div>

  <!--
    Identity reaches the builder the same way it reaches the console (plan 01
    D9): the account and the phase as props, sign-in and sign-out as events
    handled HERE, so `endSession` stays the only code that ends a session.
    `auth-configured` is what lets the builder tell "configured but signed out"
    from "no auth server at all" - `unconfigured` is the bare local checkout
    and the SYNTHETIC harness, where everything works exactly as before.
  -->
  <BuilderView
    v-else-if="route.name === 'builder'"
    :document-id="route.documentId"
    :template-id="pendingTemplate"
    :user="signedInUser"
    :authenticated="authPhase === 'authenticated'"
    :auth-configured="authPhase !== 'unconfigured'"
    :signing-in="signingIn"
    :sign-in-error="signInError"
    @home="navigate({ name: 'home' })"
    @template-taken="pendingTemplate = null"
    @run-workspace="navigate({ name: 'studio' })"
    @open-document="navigate({ name: 'builder', documentId: $event })"
    @adopt-document="navigate({ name: 'builder', documentId: $event }, { replace: true })"
    @sign-in="startGoogleSignIn"
    @sign-out="endSession"
    @close-document="navigate({ name: 'builder', documentId: null }, { replace: true })"
  />

  <!--
    The console's Build half carries the document it is running, or `null` for
    the built-in validator that has none (item 57, ROUND-2 R3). It used to be
    `documentId: null` unconditionally, so pressing Build while running a graph
    somebody drew landed on the gallery rather than on that graph. The payload
    is the event's, so this line does not have to know how the console works
    out which workflow is on screen.
  -->
  <StudioView
    v-else
    :user="signedInUser"
    :authenticated="authPhase === 'authenticated'"
    @home="navigate({ name: 'home' })"
    @build="navigate({ name: 'builder', documentId: $event })"
    @sign-out="endSession"
  />
</template>
