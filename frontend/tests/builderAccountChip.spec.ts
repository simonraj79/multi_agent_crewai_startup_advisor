import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App.vue'
import AccountChip from '../src/components/builder/AccountChip.vue'
import BuilderView from '../src/components/builder/BuilderView.vue'
import SignInPanel from '../src/components/SignInPanel.vue'
import { resetVocabulary } from '../src/data/builderVocabulary'
import { MINIMAL_GATED_AGENT, documentFromTemplate } from '../src/data/builderTemplates'
import { toWire } from '../src/utils/builderSerialize'
import type { SignedInUser } from '../src/composables/useAuthGate'
import vocabularyPayload from './fixtures/builderValidatorTemplate.json'
import { flush } from './helpers'

/**
 * Identity reaches the builder (plan 01 D9, criterion 9).
 *
 * Three claims, and the third is the one a green suite could not otherwise
 * see. The chip renders from the `user` prop and its sign-out reaches
 * `App.vue`'s `endSession` and nothing else. The builder, told that an auth
 * server exists and nobody is signed in, draws the sign-in wall where the
 * gallery would be - and fires no request on behalf of nobody. And a bare
 * local checkout, where no auth server exists at all, works exactly as it did
 * before any of this: gallery, no chip, no wall.
 *
 * `App.vue` never mounts the builder in the `anonymous` phase - it gates
 * outside the router - so the wall inside `BuilderView` is the second lock.
 * It is asserted here directly, without the app around it, because that is
 * the only way to prove the property belongs to the component rather than to
 * whoever happens to mount it.
 */

const auth = vi.hoisted(() => ({
  phase: 'authenticated' as 'checking' | 'anonymous' | 'authenticated' | 'unconfigured',
  endSession: vi.fn(),
  startGoogleSignIn: vi.fn(),
}))

vi.mock('../src/composables/useAuthGate', async () => {
  const { computed, ref } = await import('vue')
  return {
    useAuthGate: () => ({
      authClient: null,
      phase: computed(() => auth.phase),
      user: ref({ id: 'u1', name: 'Ada', email: 'ada@example.com', image: null }),
      mayUseStudio: ref(true),
      signingIn: ref(false),
      signInError: ref(null),
      startGoogleSignIn: auth.startGoogleSignIn,
      endSession: auth.endSession,
    }),
  }
})

const ADA: SignedInUser = {
  id: 'u1',
  name: 'Ada',
  email: 'ada@example.com',
  image: 'https://lh3.example.test/ada=s96',
}

const STUBS = {
  VueFlow: true,
  Background: true,
  Controls: true,
  BuilderMinimap: true,
  NodePalette: true,
  InspectorRail: true,
}

let fetchMock: ReturnType<typeof vi.fn>

/** The id the deep-link case below arrives on, and what the server holds under it. */
const DEEP_LINKED = 'ug_0a1b2c3d'
const STORED_AT = '2026-09-03T00:00:00.000Z'

function storedModel() {
  return {
    id: DEEP_LINKED,
    document: { ...toWire(documentFromTemplate(MINIMAL_GATED_AGENT)), id: DEEP_LINKED, version: 1 },
    status: 'draft',
    version: 1,
    head_version: 1,
    created_at: STORED_AT,
    updated_at: STORED_AT,
    problems: [],
    budget: vocabularyPayload.validation.budget,
    graph: null,
    published: false,
  }
}

beforeEach(() => {
  auth.phase = 'authenticated'
  window.location.hash = '#/'
  resetVocabulary()
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    let body: unknown = []
    if (url.includes('/api/builder/vocabulary')) body = vocabularyPayload.vocabulary
    else if (url.includes('/api/builder/validate')) body = vocabularyPayload.validation
    else if (url.includes(`/api/builder/workflows/${DEEP_LINKED}`)) body = storedModel()
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  resetVocabulary()
  vi.unstubAllGlobals()
})

/** Every URL the stubbed `fetch` was asked for. */
function asked(): string[] {
  return fetchMock.mock.calls.map(([input]) => String(input))
}

describe('the account chip', () => {
  it('names the account and loads the avatar without a Referer', () => {
    const wrapper = mount(AccountChip, { props: { user: ADA } })
    expect(wrapper.text()).toContain('Ada')
    const avatar = wrapper.get('img.account-avatar')
    expect(avatar.attributes('src')).toBe(ADA.image)
    // Google's avatar host would otherwise receive a Referer naming this app on
    // every load. Not decoration, and the one attribute worth pinning.
    expect(avatar.attributes('referrerpolicy')).toBe('no-referrer')
    expect(avatar.attributes('alt')).toBe('')
  })

  it('falls back to the email when the account has no name, and to no avatar', () => {
    const wrapper = mount(AccountChip, { props: { user: { ...ADA, name: '', image: null } } })
    expect(wrapper.text()).toContain('ada@example.com')
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it('emits sign-out and decides nothing about the session itself', async () => {
    const wrapper = mount(AccountChip, { props: { user: ADA } })
    const button = wrapper.get('button.account-signout')
    expect(button.text()).toContain('Sign out')
    await button.trigger('click')
    expect(wrapper.emitted('signOut')).toHaveLength(1)
    // No session call left this component: sign-out is App.vue's, so the
    // token-before-cookie order in `endSession` cannot be got wrong twice.
    expect(asked()).toEqual([])
  })
})

describe('the builder with an identity', () => {
  it('renders the chip from the user prop and re-emits its sign-out', async () => {
    const wrapper = mount(BuilderView, {
      props: { documentId: null, user: ADA, authenticated: true, authConfigured: true },
      global: { stubs: STUBS },
    })
    await flush(12)
    const chip = wrapper.get('[data-testid="account-chip"]')
    expect(chip.text()).toContain('Ada')
    await chip.get('button.account-signout').trigger('click')
    expect(wrapper.emitted('signOut')).toHaveLength(1)
    // And the gallery is there, because this author is allowed in.
    expect(wrapper.findAll('.template-card').length).toBeGreaterThan(0)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(false)
  })

  it('shows the sign-in wall, not the gallery, when auth is configured and nobody is in', async () => {
    const wrapper = mount(BuilderView, {
      props: { documentId: null, user: null, authenticated: false, authConfigured: true },
      global: { stubs: STUBS },
    })
    await flush(12)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(true)
    expect(wrapper.findAll('.template-card')).toHaveLength(0)
    expect(wrapper.find('.studio-main').exists()).toBe(false)
    expect(wrapper.find('[data-testid="account-chip"]').exists()).toBe(false)

    // Nothing was asked for on behalf of nobody. The vocabulary is the one
    // exception, deliberately: it describes the build, not a person, and has to
    // resolve before the gate does or the palette is dead for the whole sign-in.
    expect(asked().filter((url) => url.includes('/api/builder/workflows'))).toEqual([])
    expect(asked().filter((url) => url.includes('/api/builder/vocabulary'))).toHaveLength(1)

    // The wall is live: its button reaches App.vue's `startGoogleSignIn`.
    await wrapper.get('button.google-button').trigger('click')
    expect(wrapper.emitted('signIn')).toHaveLength(1)
  })

  it('opens up the moment the session resolves, and only then asks for the library', async () => {
    const wrapper = mount(BuilderView, {
      props: { documentId: null, user: null, authenticated: false, authConfigured: true },
      global: { stubs: STUBS },
    })
    await flush(12)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(true)
    expect(asked().filter((url) => url.includes('/api/builder/workflows'))).toEqual([])

    await wrapper.setProps({ user: ADA, authenticated: true })
    await flush(12)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(false)
    expect(wrapper.get('[data-testid="account-chip"]').text()).toContain('Ada')
    expect(wrapper.findAll('.template-card').length).toBeGreaterThan(0)
    /*
     * "At least one", not "exactly one". The shell's `refreshLibrary` feeds the
     * palette's list and `TemplateGallery` reads the same endpoint for its own
     * "Saved here" section, so a signed-in gallery is two reads of one route -
     * a fact about the product, not about the gate. What the gate owns is the
     * ORDER: nothing before the session, something after.
     */
    expect(asked().filter((url) => url.includes('/api/builder/workflows')).length).toBeGreaterThan(0)
  })

  it('does not fetch a deep-linked document on behalf of nobody, and does once somebody is in', async () => {
    // `#/build/<id>` is the URL an author sends a colleague. Reached signed out,
    // the id must not be looked up - the answer would be a 401, and a 404 for a
    // foreign id would be leaking through a wall that is supposed to be blank.
    const wrapper = mount(BuilderView, {
      props: { documentId: DEEP_LINKED as never, user: null, authenticated: false, authConfigured: true },
      global: { stubs: STUBS },
    })
    await flush(12)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(true)
    expect(asked().filter((url) => url.includes('/api/builder/workflows'))).toEqual([])

    await wrapper.setProps({ user: ADA, authenticated: true })
    await flush(12)
    expect(asked().filter((url) => url.includes(`/api/builder/workflows/${DEEP_LINKED}`))).toHaveLength(1)
    // And it opened: the document bar names the stored graph, not the gallery.
    expect(wrapper.findAll('.template-card')).toHaveLength(0)
    expect(wrapper.text()).toContain(MINIMAL_GATED_AGENT.document.name)
  })

  it('works exactly as before when no auth server exists at all', async () => {
    // The bare local checkout and the SYNTHETIC harness: `unconfigured`. No
    // props beyond `documentId`, which is what every older spec passes.
    const wrapper = mount(BuilderView, {
      props: { documentId: null },
      global: { stubs: STUBS },
    })
    await flush(12)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(false)
    expect(wrapper.find('[data-testid="account-chip"]').exists()).toBe(false)
    expect(wrapper.findAll('.template-card').length).toBeGreaterThan(0)
    expect(asked().filter((url) => url.includes('/api/builder/workflows')).length).toBeGreaterThan(0)
  })

  it('draws the wall, never the gallery, for "configured but signed out" whatever else is passed', async () => {
    // The wall keys on the PAIR: an auth server exists and nobody is in. A
    // `user` object arriving with `authenticated: false` is the shape of a
    // session that just ended in another tab, and the gallery must not stay up
    // on the strength of a stale account.
    const wrapper = mount(BuilderView, {
      props: { documentId: null, user: ADA, authenticated: false, authConfigured: true },
      global: { stubs: STUBS },
    })
    await flush(12)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(true)
    expect(wrapper.findAll('.template-card')).toHaveLength(0)
    expect(asked().filter((url) => url.includes('/api/builder/workflows'))).toEqual([])
  })
})

describe('App.vue hands the builder what it hands the console', () => {
  it('passes the account, the phase and both session events', async () => {
    window.location.hash = '#/build'
    const wrapper = mount(App, {
      global: { stubs: { StudioView: true, BuilderView: true } },
    })
    const builder = wrapper.findComponent({ name: 'BuilderView' })
    expect(builder.exists()).toBe(true)
    expect(builder.props('user')).toMatchObject({ id: 'u1', name: 'Ada' })
    expect(builder.props('authenticated')).toBe(true)
    expect(builder.props('authConfigured')).toBe(true)

    // The builder's sign-out is `endSession` - the same path as the console's,
    // so there is one place that drops the cached token before the cookie.
    builder.vm.$emit('signOut')
    await flush()
    expect(auth.endSession).toHaveBeenCalledTimes(1)
    builder.vm.$emit('signIn')
    await flush()
    expect(auth.startGoogleSignIn).toHaveBeenCalledTimes(1)
  })

  it('tells the builder when there is no auth server, so it stays open', () => {
    auth.phase = 'unconfigured'
    window.location.hash = '#/build'
    const wrapper = mount(App, {
      global: { stubs: { StudioView: true, BuilderView: true } },
    })
    const builder = wrapper.findComponent({ name: 'BuilderView' })
    expect(builder.props('authConfigured')).toBe(false)
    expect(builder.props('authenticated')).toBe(false)
  })

  it('still gates before routing: the anonymous phase never mounts the builder', () => {
    auth.phase = 'anonymous'
    window.location.hash = '#/build'
    const wrapper = mount(App, {
      global: { stubs: { StudioView: true, BuilderView: true } },
    })
    expect(wrapper.findComponent({ name: 'BuilderView' }).exists()).toBe(false)
    expect(wrapper.findComponent(SignInPanel).exists()).toBe(true)
  })
})
