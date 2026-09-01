import { computed, ref, watch } from 'vue'
import {
  authClient,
  clearAccessToken,
  setSessionActive,
  signIn,
  signOut,
  useSession,
} from '../services/authClient'

/**
 * Whether the console should be showing the studio, a sign-in screen, or
 * neither yet.
 *
 * `unconfigured` is the state worth explaining. There is no `VITE_REQUIRE_AUTH`
 * flag anywhere, deliberately: a build-time boolean is a second source of truth
 * about a fact the runtime can simply observe, and the two drift. Instead the
 * console asks the auth server whether it exists. If `/api/auth/get-session`
 * answers, auth is configured and the answer decides; if the request fails
 * outright there is no auth server, which is the shape of a bare local checkout
 * and of the `SYNTHETIC` end-to-end harness, so the studio opens as it always
 * did.
 *
 * That mirrors what the API does with `VALIDATOR_REQUIRE_AUTH`, whose default is
 * derived from whether `AUTH_BASE_URL` is set rather than being a flat boolean -
 * the same rule, enforced independently on both sides.
 *
 * **This gate is a convenience, not the control.** Every endpoint that matters
 * verifies the bearer token for itself, so a browser that talked its way past
 * this screen would meet a wall of 401s and get nothing. Treating the UI as the
 * security boundary is the mistake this comment exists to prevent.
 */
export type AuthPhase = 'checking' | 'anonymous' | 'authenticated' | 'unconfigured'

export interface SignedInUser {
  id: string
  name: string
  email: string
  image: string | null
}

export function useAuthGate() {
  const session = useSession()
  const signingIn = ref(false)
  const signInError = ref<string | null>(null)

  const phase = computed<AuthPhase>(() => {
    const state = session.value
    if (state.isPending) return 'checking'
    // An `error` here is a failed REQUEST, not a refused sign-in: Better Auth
    // answers 200 with a null session for a signed-out visitor. So this only
    // fires when nothing is listening on /api/auth at all.
    if (state.error) return 'unconfigured'
    return state.data ? 'authenticated' : 'anonymous'
  })

  const user = computed<SignedInUser | null>(() => {
    const account = session.value.data?.user
    if (!account) return null
    return {
      id: account.id,
      name: account.name ?? '',
      email: account.email ?? '',
      image: account.image ?? null,
    }
  })

  /** True when the studio may be shown at all. */
  const mayUseStudio = computed(
    () => phase.value === 'authenticated' || phase.value === 'unconfigured',
  )

  async function startGoogleSignIn(): Promise<void> {
    signingIn.value = true
    signInError.value = null
    try {
      const { error } = await signIn.social({
        provider: 'google',
        // Back to the console. Better Auth resolves this against its own
        // baseURL, and because the Node server serves this SPA from the same
        // origin, "/" is the studio.
        callbackURL: '/',
      })
      if (error) {
        signInError.value = error.message ?? 'Google sign-in could not be started.'
        signingIn.value = false
      }
      // On success the browser is navigating to Google; leaving `signingIn`
      // true keeps the button disabled for the moment before the page unloads.
    } catch {
      signInError.value =
        'Could not reach the sign-in service. Check that it is running, then try again.'
      signingIn.value = false
    }
  }

  async function endSession(): Promise<void> {
    // Order matters. Drop the cached bearer token FIRST: `signOut` revokes the
    // session server-side, and a token minted from it would otherwise sit in
    // memory looking valid by its own `exp` until it expired on its own.
    clearAccessToken()
    await signOut()
  }

  /*
   * Tell the token provider whether there is a session to mint tokens from.
   *
   * `immediate` matters: the studio's own `initialize()` fires as soon as
   * `mayUseStudio` turns true, and that must not happen before the provider
   * knows a session exists, or the first API call would go out unauthenticated
   * and come back 401.
   *
   * It also covers a session ending in ANOTHER TAB. Better Auth broadcasts
   * session changes between tabs, so a sign-out over there flips `phase` here
   * and drops this tab's cached token with no polling of any kind - otherwise
   * a signed-out tab would keep working until its JWT aged out.
   */
  watch(
    () => phase.value === 'authenticated',
    (active) => setSessionActive(active),
    { immediate: true },
  )

  return {
    authClient,
    phase,
    user,
    mayUseStudio,
    signingIn,
    signInError,
    startGoogleSignIn,
    endSession,
  }
}
