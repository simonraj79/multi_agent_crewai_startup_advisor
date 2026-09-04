<script setup lang="ts">
import { LogOut } from 'lucide-vue-next'
import type { SignedInUser } from '../../composables/useAuthGate'

/**
 * Who is signed in, and the one way out.
 *
 * The same chip `StudioView.vue` draws in its header, as a component so the
 * builder can draw it too - plan 01 D9's "identity reaches the builder". It
 * holds no session: the account arrives as a prop from `useAuthGate` and
 * sign-out leaves as an event, so `App.vue`'s `endSession` stays the ONLY code
 * that ends one. Two views ending a session two ways is how one of them keeps
 * a cached bearer token alive after the cookie is gone.
 *
 * The classes are `studio.css`'s global `.account-*` rules rather than a
 * scoped copy, and there is no `<style>` block here on purpose: the DOM this
 * renders is byte-for-byte the console's chip, so the two workspaces cannot
 * drift apart on the one element that says whose work is on screen.
 * `StudioView` keeps its inline markup for now - its header sits behind an
 * E2E baseline and a pure extraction is a separate, deliberate change.
 */
defineProps<{
  user: SignedInUser
}>()

const emit = defineEmits<{ signOut: [] }>()
</script>

<template>
  <div class="account-chip" data-testid="account-chip">
    <!--
      `referrerpolicy` is not decoration. Google's avatar host receives a
      Referer naming this app on every load otherwise, and `no-referrer`
      costs nothing here because the image is public.
      @error hides a broken avatar rather than showing the browser's
      placeholder - Google's URLs do expire.
    -->
    <img
      v-if="user.image"
      class="account-avatar"
      :src="user.image"
      alt=""
      referrerpolicy="no-referrer"
      @error="($event.target as HTMLImageElement).style.display = 'none'"
    />
    <span class="account-name">{{ user.name || user.email }}</span>
    <button class="account-signout" type="button" title="Sign out" @click="emit('signOut')">
      <LogOut :size="14" aria-hidden="true" />
      <span class="sr-only">Sign out</span>
    </button>
  </div>
</template>
