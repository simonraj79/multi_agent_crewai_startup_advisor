import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccountKeysView from '../src/views/AccountKeysView.vue'
import type { ApiKey } from '../src/services/accountApi'

/**
 * Personal API keys - `.agent/plans/22-api-keys.md` criterion 11.
 *
 * The shapes are §3's, hand-typed: the page creates, shows the secret ONCE,
 * copies it, lists and revokes, and every refusal reaches the reader as the
 * server's own sentence rather than its JSON envelope.
 */

const KEY_A: ApiKey = {
  id: 'key_a',
  name: 'nightly script',
  prefix: 'cs_live_AbCd',
  created_at: '2026-09-27T09:00:00Z',
  last_used_at: null,
}
const KEY_B: ApiKey = {
  id: 'key_b',
  name: 'zapier',
  prefix: 'cs_live_EfGh',
  created_at: '2026-09-26T09:00:00Z',
  last_used_at: '2026-09-27T08:00:00Z',
}
const SECRET = 'cs_live_AbCdTHE-WHOLE-SECRET-0123456789'

type Handler = (url: string, init: RequestInit | undefined) => Response

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

let calls: Array<{ url: string; method: string; body: string | null }> = []

function stubFetch(handler: Handler): void {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, method: init?.method ?? 'GET', body: (init?.body as string | undefined) ?? null })
    return handler(url, init)
  }))
}

async function mountView() {
  const wrapper = mount(AccountKeysView, { props: { user: null } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  document.title = ''
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the list', () => {
  it('lists every key with its prefix, created date and "never" for an unused key', async () => {
    stubFetch(() => json({ keys: [KEY_A, KEY_B], limit: 10 }))
    const wrapper = await mountView()

    expect(calls[0]).toMatchObject({ url: '/api/account/api-keys', method: 'GET' })
    const rowA = wrapper.get('[data-testid="account-key-key_a"]').text()
    expect(rowA).toContain('nightly script')
    expect(rowA).toContain('cs_live_AbCd…')
    expect(rowA).toContain('never')
    expect(wrapper.get('[data-testid="account-key-key_b"]').text()).not.toContain('never')
    expect(wrapper.get('[data-testid="account-keys-count"]').text()).toBe('2 of 10 keys')
    expect(document.title).toContain('API keys')
  })

  it('says so when there are no keys', async () => {
    stubFetch(() => json({ keys: [], limit: 10 }))
    const wrapper = await mountView()
    expect(wrapper.find('[data-testid="account-keys-empty"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="account-keys-table"]').exists()).toBe(false)
  })

  it('shows the server sentence when the list is refused, not the JSON around it', async () => {
    stubFetch(() => json({ detail: 'API keys cannot manage API keys or credentials; sign in to the console' }, 403))
    const wrapper = await mountView()
    const error = wrapper.get('[data-testid="account-keys-load-error"]').text()
    expect(error).toContain('API keys cannot manage API keys or credentials; sign in to the console')
    expect(error).not.toContain('{')
  })
})

describe('create, and the secret shown once', () => {
  it('posts the trimmed name, shows the secret once with a warning and a curl example, and forgets it on Done', async () => {
    stubFetch((_url, init) => {
      if (init?.method === 'POST') return json({ key: KEY_A, secret: SECRET }, 201)
      return json({ keys: [KEY_B], limit: 10 })
    })
    const wrapper = await mountView()

    await wrapper.get('[data-testid="account-keys-name"]').setValue('  nightly script  ')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    const post = calls.find((call) => call.method === 'POST')!
    expect(post.url).toBe('/api/account/api-keys')
    expect(JSON.parse(post.body!)).toEqual({ name: 'nightly script' })

    const callout = wrapper.get('[data-testid="account-keys-secret"]')
    expect(wrapper.get('[data-testid="account-keys-secret-value"]').text()).toBe(SECRET)
    expect(callout.text()).toMatch(/will not be shown again/i)
    const curl = wrapper.get('[data-testid="account-keys-curl"]').text()
    expect(curl).toContain(`${window.location.origin}/api/sessions/my-script/runs`)
    expect(curl).toContain('Authorization: Bearer <key>')
    expect(curl).toContain('"gates":"auto"')
    expect(curl).toContain(`${window.location.origin}/api/runs/<run_id>`)

    // The new key joins the list, and the list never carries the secret.
    expect(wrapper.get('[data-testid="account-keys-count"]').text()).toBe('2 of 10 keys')
    expect(wrapper.get('[data-testid="account-keys-table"]').text()).not.toContain(SECRET)
    expect((wrapper.get('[data-testid="account-keys-name"]').element as HTMLInputElement).value).toBe('')

    await wrapper.get('[data-testid="account-keys-done"]').trigger('click')
    expect(wrapper.find('[data-testid="account-keys-secret"]').exists()).toBe(false)
    expect(wrapper.html()).not.toContain(SECRET)
  })

  it('copies the secret to the clipboard', async () => {
    const writeText = vi.fn(async () => undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    stubFetch((_url, init) =>
      init?.method === 'POST' ? json({ key: KEY_A, secret: SECRET }, 201) : json({ keys: [], limit: 10 }),
    )
    const wrapper = await mountView()
    await wrapper.get('[data-testid="account-keys-name"]').setValue('nightly script')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    await wrapper.get('[data-testid="account-keys-copy"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith(SECRET)
    expect(wrapper.get('[data-testid="account-keys-copy"]').text()).toBe('Copied')
  })

  it('does not create with a blank name, and bounds the box at 64 characters', async () => {
    stubFetch(() => json({ keys: [], limit: 10 }))
    const wrapper = await mountView()
    const input = wrapper.get('[data-testid="account-keys-name"]')
    expect(input.attributes('maxlength')).toBe('64')
    await input.setValue('   ')
    expect(wrapper.get('[data-testid="account-keys-create"]').attributes('disabled')).toBeDefined()
  })

  it('shows the server sentence when a create is refused', async () => {
    stubFetch((_url, init) =>
      init?.method === 'POST'
        ? json({ detail: 'you already have 10 active API keys; revoke one first' }, 409)
        : json({ keys: [KEY_A], limit: 10 }),
    )
    const wrapper = await mountView()
    await wrapper.get('[data-testid="account-keys-name"]').setValue('one more')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[data-testid="account-keys-error"]').text()).toContain(
      'you already have 10 active API keys; revoke one first',
    )
    expect(wrapper.find('[data-testid="account-keys-secret"]').exists()).toBe(false)
  })
})

describe('the limit', () => {
  it('disables create at the limit and says why', async () => {
    stubFetch(() => json({ keys: [KEY_A, KEY_B], limit: 2 }))
    const wrapper = await mountView()
    expect(wrapper.get('[data-testid="account-keys-count"]').text()).toBe('2 of 2 keys')
    await wrapper.get('[data-testid="account-keys-name"]').setValue('third')
    expect(wrapper.get('[data-testid="account-keys-create"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="account-keys-at-limit"]').exists()).toBe(true)
  })
})

describe('revoke, confirmed inline', () => {
  it('asks first, sends nothing on Keep, and DELETEs then drops the row on Revoke', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    stubFetch((_url, init) =>
      init?.method === 'DELETE' ? new Response(null, { status: 204 }) : json({ keys: [KEY_A, KEY_B], limit: 10 }),
    )
    const wrapper = await mountView()
    const row = () => wrapper.get('[data-testid="account-key-key_a"]')

    await row().get('[data-testid="account-keys-revoke"]').trigger('click')
    expect(row().text()).toMatch(/Revoke\?/)
    await row().get('[data-testid="account-keys-revoke-cancel"]').trigger('click')
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    expect(row().find('[data-testid="account-keys-revoke-confirm"]').exists()).toBe(false)

    await row().get('[data-testid="account-keys-revoke"]').trigger('click')
    await row().get('[data-testid="account-keys-revoke-confirm"]').trigger('click')
    await flushPromises()

    const del = calls.find((call) => call.method === 'DELETE')!
    expect(del.url).toBe('/api/account/api-keys/key_a')
    expect(wrapper.find('[data-testid="account-key-key_a"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="account-keys-count"]').text()).toBe('1 of 10 keys')
    // No browser dialog, ever.
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('keeps the row and shows the server sentence when a revoke is refused', async () => {
    stubFetch((_url, init) =>
      init?.method === 'DELETE' ? json({ detail: 'API key not found' }, 404) : json({ keys: [KEY_A], limit: 10 }),
    )
    const wrapper = await mountView()
    await wrapper.get('[data-testid="account-keys-revoke"]').trigger('click')
    await wrapper.get('[data-testid="account-keys-revoke-confirm"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="account-keys-error"]').text()).toContain('API key not found')
    expect(wrapper.find('[data-testid="account-key-key_a"]').exists()).toBe(true)
  })
})
