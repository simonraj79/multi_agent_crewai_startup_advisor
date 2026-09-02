<script setup lang="ts">
import { CircleDot } from 'lucide-vue-next'
import SignInPanel from './components/SignInPanel.vue'
import StudioView from './views/StudioView.vue'
import BuilderView from './components/builder/BuilderView.vue'
import { useAuthGate } from './composables/useAuthGate'
import { useWorkspaceRoute } from './composables/useWorkspaceRoute'

/**
 * The auth gate, then the route. Nothing else lives here any more.
 *
 * The console that used to be this file's whole body is `views/StudioView.vue`,
 * moved out unchanged; the builder is `BuilderView`. Keeping the gate HERE and
 * only here is what makes the two workspaces the same product rather than two
 * apps behind one login: there is one session request, one splash while it is
 * in flight, and one sign-in wall, and neither view can accidentally render
 * before the answer.
 *
 * WHY THE GATE IS OUTSIDE THE ROUTER. `#/build` reached before a session
 * resolves must show the same splash as `#/`, not a builder that will be
 * replaced by a login wall a tick later. Routing first and gating inside each
 * view would put that flash in two places and fix it in one.
 */

const {
  phase: authPhase,
  user: signedInUser,
  signingIn,
  signInError,
  startGoogleSignIn,
  endSession,
} = useAuthGate()

const { route, navigate } = useWorkspaceRoute()
</script>

<template>
  <!--
    Three states, and the middle one is why `checking` exists at all. Rendering
    the sign-in screen while the session request is still in flight makes an
    already-signed-in visitor see a login wall flash on every page load, which
    reads as "it logged me out again".
  -->
  <div v-if="authPhase === 'checking'" class="auth-splash" role="status" aria-live="polite">
    <span class="auth-splash-mark" aria-hidden="true"><CircleDot :size="22" :stroke-width="1.8" /></span>
    <p>Checking your session…</p>
  </div>

  <SignInPanel
    v-else-if="authPhase === 'anonymous'"
    :signing-in="signingIn"
    :error="signInError"
    @sign-in="startGoogleSignIn"
  />

  <!--
    Two views, and each mounts its own <VueFlow> with a distinct `id`
    (`studio-flow` / `builder-flow`). `useVueFlow` keys viewport, selection and
    node state per instance id, so two instances sharing one would trade
    viewports across a route change - the builder would open at whatever zoom
    the run console was left at, and a fitView in one would move the other.
  -->
  <BuilderView
    v-else-if="route.name === 'builder'"
    :document-id="route.documentId"
    @run-workspace="navigate({ name: 'studio' })"
    @open-document="navigate({ name: 'builder', documentId: $event })"
    @adopt-document="navigate({ name: 'builder', documentId: $event }, { replace: true })"
    @close-document="navigate({ name: 'builder', documentId: null }, { replace: true })"
  />

  <StudioView
    v-else
    :user="signedInUser"
    :authenticated="authPhase === 'authenticated'"
    @build="navigate({ name: 'builder', documentId: null })"
    @sign-out="endSession"
  />
</template>
