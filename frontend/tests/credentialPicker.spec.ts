import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CredentialPicker from '../src/components/builder/CredentialPicker.vue'
import BillableForm from '../src/components/builder/inspectors/BillableForm.vue'
import { CREDENTIAL_KINDS, CREDENTIAL_KIND_ORDER, fieldLabel } from '../src/data/credentialKinds'
import {
  BUILDER_API_PREFIX,
  CREDENTIALS_PATH,
  createCredential,
  credentialApi,
  deleteCredential,
  listCredentials,
  testCredential,
  type CredentialApiLike,
} from '../src/services/builderApi'
import { clearAccessToken, setSessionActive } from '../src/services/authClient'
import { CREDENTIAL_ID_PATTERN } from '../src/types/builder'
import type { CredentialKind, CredentialSummary } from '../src/types/builder'
import type { InspectorCommit } from '../src/components/builder/commit'
import {
  agentNode,
  crewNode,
  documentFixture,
  problemsProvide,
  vocabularyFixture,
} from './builderInspectorFixtures'

/**
 * The credential picker (plan 01 D9, criterion 10).
 *
 * Four claims, and the third is the one this file exists for:
 *
 *  1. It lists `{kind, label}` rows filtered by the field's kind, and offers
 *     "create new" - docked in the inspector row, never a modal (R15).
 *  2. It reads `GET /api/builder/credentials` through `authedFetch`: bearer
 *     token attached, one 401 retry, the server's sentence rather than the
 *     envelope.
 *  3. It NEVER renders a field value, even when the API hands it one. The
 *     server is specified never to return a field, but a client that would
 *     render one if it arrived is one server bug away from showing a key on
 *     screen - so the fake API here deliberately leaks, in every shape a leak
 *     could take, and the markup is searched for the secret.
 *  4. The kinds and fields it renders a form for are `config.py`'s, read at
 *     test time, so a kind added on the Python side fails here rather than as
 *     a 422 naming a field the author never saw.
 *
 * `api` is a prop typed `CredentialApiLike`, so the double below is
 * compiler-forced to match the four calls it stands in for. A double that
 * diverges from its subject certifies nothing - which is why the leak is
 * written INTO the double rather than left to a mocked `fetch`.
 */

const SECRET = 'sk-or-v1-THIS-MUST-NEVER-BE-RENDERED'
const OTHER_SECRET = 'ghp_ANOTHER-VALUE-THAT-MUST-NOT-APPEAR'

function row(overrides: Partial<CredentialSummary> & { id: string; kind: CredentialKind; label: string }): CredentialSummary {
  return {
    created_at: '2026-09-03T00:00:00Z',
    updated_at: '2026-09-03T00:00:00Z',
    last_used_at: null,
    ...overrides,
  }
}

/**
 * A server that LEAKS. Every row carries a field value in three shapes - the
 * vault's own `fields` object, the field flattened onto the row, and a second
 * field name - because the property under test is that none of them has
 * anywhere in the component to land. `as unknown as` because the honest type
 * has no slot for a secret, and that is the point of the type.
 */
function leakyRows(): CredentialSummary[] {
  return [
    { ...row({ id: 'cr_0000aaaa', kind: 'openrouter', label: 'Work key' }), fields: { api_key: SECRET }, api_key: SECRET },
    { ...row({ id: 'cr_0000bbbb', kind: 'github', label: 'GitHub token' }), fields: { token: OTHER_SECRET }, token: OTHER_SECRET },
    { ...row({ id: 'cr_0000cccc', kind: 'openrouter', label: 'Personal key' }), fields: { api_key: OTHER_SECRET } },
  ] as unknown as CredentialSummary[]
}

interface Double extends CredentialApiLike {
  calls: { create: Parameters<typeof createCredential>[0][]; test: string[]; delete: string[] }
}

function fakeApi(rows: CredentialSummary[] = leakyRows(), overrides: Partial<CredentialApiLike> = {}): Double {
  const calls: Double['calls'] = { create: [], test: [], delete: [] }
  let minted = 0
  const double: Double = {
    calls,
    listCredentials: async () => rows,
    createCredential: async (draft) => {
      calls.create.push(draft)
      minted += 1
      // The 201 answers with the same row shape the list uses - and this one
      // leaks the field straight back, which the picker must also ignore.
      return {
        ...row({ id: `cr_0000ff0${minted}`, kind: draft.kind, label: draft.label }),
        fields: draft.fields,
      } as unknown as CredentialSummary
    },
    deleteCredential: async (id) => {
      calls.delete.push(id)
    },
    testCredential: async (id) => {
      calls.test.push(id)
      return { ok: true, detail: 'Key is valid (rate limit 100/min).' }
    },
    ...overrides,
  }
  return double
}

function mountPicker(props: Partial<InstanceType<typeof CredentialPicker>['$props']> = {}, api: CredentialApiLike = fakeApi()) {
  return mount(CredentialPicker, {
    props: { kind: 'openrouter', modelValue: null, api, ...props },
  })
}

function optionTexts(wrapper: ReturnType<typeof mountPicker>): string[] {
  return wrapper.findAll('option').map((option) => option.text())
}

function optionValues(wrapper: ReturnType<typeof mountPicker>): string[] {
  return wrapper.findAll('option').map((option) => option.attributes('value') ?? '')
}

function lastEmitted(wrapper: ReturnType<typeof mountPicker>): string | null | undefined {
  const emitted = wrapper.emitted('update:modelValue')
  return emitted ? (emitted[emitted.length - 1][0] as string | null) : undefined
}

describe('the picker lists the credentials of the field kind', () => {
  it('shows the platform key first, then only the rows of its kind, by label', async () => {
    const wrapper = mountPicker()
    await flushPromises()
    expect(optionTexts(wrapper)).toEqual(['Platform key', 'Work key', 'Personal key'])
    expect(optionValues(wrapper)).toEqual(['', 'cr_0000aaaa', 'cr_0000cccc'])
    // The github row exists in the answer and is simply not this field's kind.
    expect(wrapper.text()).not.toContain('GitHub token')
  })

  it('re-filters when the kind changes, from the same list', async () => {
    let asked = 0
    const api = fakeApi(leakyRows(), {
      listCredentials: async () => {
        asked += 1
        return leakyRows()
      },
    })
    const wrapper = mountPicker({}, api)
    await flushPromises()
    expect(asked).toBe(1)
    await wrapper.setProps({ kind: 'github' })
    await flushPromises()
    expect(optionTexts(wrapper)).toEqual(['Platform key', 'GitHub token'])
    // Filtered on the CLIENT: the endpoint lists everything the caller owns, so
    // one request serves every picker on the rail rather than one per row.
    expect(asked).toBe(2)
  })

  it('disables the select while loading and re-enables it after', async () => {
    let release!: (rows: CredentialSummary[]) => void
    const api = fakeApi([], {
      listCredentials: () => new Promise<CredentialSummary[]>((resolve) => (release = resolve)),
    })
    const wrapper = mountPicker({}, api)
    await flushPromises()
    expect(wrapper.get('[data-testid="credential-select"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Loading your credentials')
    release([])
    await flushPromises()
    expect(wrapper.get('[data-testid="credential-select"]').attributes('disabled')).toBeUndefined()
  })

  it('renders the server sentence, as an alert, when the list is refused', async () => {
    const api = fakeApi([], {
      listCredentials: async () => {
        throw new Error('credential vault is not configured')
      },
    })
    const wrapper = mountPicker({}, api)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('credential vault is not configured')
    expect(optionTexts(wrapper)).toEqual(['Platform key'])
  })

  it('keeps a stored id the list does not carry, marked, rather than silently rewriting the document', async () => {
    const wrapper = mountPicker({ modelValue: 'cr_0000dead' })
    await flushPromises()
    const select = wrapper.get<HTMLSelectElement>('[data-testid="credential-select"]')
    expect(select.element.value).toBe('cr_0000dead')
    expect(optionTexts(wrapper).at(-1)).toContain('not among your credentials')
    // And nothing was emitted: seeing an orphan is not a decision about it.
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('emits the chosen id, and null for the platform key', async () => {
    const wrapper = mountPicker()
    await flushPromises()
    await wrapper.get('[data-testid="credential-select"]').setValue('cr_0000cccc')
    expect(lastEmitted(wrapper)).toBe('cr_0000cccc')
    await wrapper.setProps({ modelValue: 'cr_0000cccc' })
    await wrapper.get('[data-testid="credential-select"]').setValue('')
    expect(lastEmitted(wrapper)).toBeNull()
  })
})

describe('never a field value', () => {
  it('renders no field value from a list that carries them, in any shape', async () => {
    const wrapper = mountPicker()
    await flushPromises()
    const html = wrapper.html()
    expect(html).not.toContain(SECRET)
    expect(html).not.toContain(OTHER_SECRET)
    // Not merely hidden: the component holds only `{id, kind, label}` per row,
    // so the secret is not in its state either. `summarise` is the property.
    expect(JSON.stringify((wrapper.vm as unknown as { rows: unknown }).rows)).not.toContain(SECRET)
    expect(JSON.stringify((wrapper.vm as unknown as { rows: unknown }).rows)).not.toContain('fields')
  })

  it('renders nothing from a 201 that echoes the field back, and clears the typed secret', async () => {
    const api = fakeApi()
    const wrapper = mountPicker({}, api)
    await flushPromises()
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    await wrapper.get('[data-testid="credential-label"]').setValue('New key')
    await wrapper.get('[data-testid="credential-field-api_key"]').setValue(SECRET)
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    // The secret left in the POST body and nowhere else.
    expect(api.calls.create).toEqual([{ kind: 'openrouter', label: 'New key', fields: { api_key: SECRET } }])
    expect(wrapper.html()).not.toContain(SECRET)
    expect(wrapper.find('[data-testid="credential-form"]').exists()).toBe(false)
    expect(optionTexts(wrapper)).toContain('New key')
    // Reopening the form starts blank: the draft was dropped, not hidden.
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    expect(wrapper.get<HTMLInputElement>('[data-testid="credential-field-api_key"]').element.value).toBe('')
    expect(wrapper.get<HTMLInputElement>('[data-testid="credential-label"]').element.value).toBe('')
  })

  it('drops a typed secret on cancel, whether or not it was sent', async () => {
    const api = fakeApi()
    const wrapper = mountPicker({}, api)
    await flushPromises()
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    await wrapper.get('[data-testid="credential-field-api_key"]').setValue(SECRET)
    await wrapper.get('[data-testid="credential-cancel"]').trigger('click')
    expect(api.calls.create).toEqual([])
    expect(wrapper.find('[data-testid="credential-form"]').exists()).toBe(false)
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    expect(wrapper.get<HTMLInputElement>('[data-testid="credential-field-api_key"]').element.value).toBe('')
  })

  it('types every secret field as a password and every name field as text', async () => {
    const wrapper = mountPicker({ kind: 'http_header' })
    await flushPromises()
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    expect(wrapper.get('[data-testid="credential-field-name"]').attributes('type')).toBe('text')
    expect(wrapper.get('[data-testid="credential-field-header_value"]').attributes('type')).toBe('password')
    expect(wrapper.text()).toContain(fieldLabel('name'))
    expect(wrapper.text()).toContain(fieldLabel('header_value'))
  })
})

describe('create new, docked', () => {
  it('offers a create button naming the kind, and opens an inline form with no dialog', async () => {
    const wrapper = mountPicker()
    await flushPromises()
    const button = wrapper.get('[data-testid="credential-new"]')
    expect(button.text()).toContain('Add a OpenRouter key')
    await button.trigger('click')
    const form = wrapper.get('[data-testid="credential-form"]')
    // Docked, never modal (R15): the form is a child of the picker, inside the
    // inspector row, and nothing anywhere carries a dialog role.
    expect(form.element.closest('.credential-picker')).toBe(wrapper.element)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.find('dialog').exists()).toBe(false)
    expect(wrapper.find('.modal-overlay').exists()).toBe(false)
    expect(form.attributes('aria-label')).toBe('New OpenRouter credential')
    // One input per field the kind needs, plus the label.
    expect(wrapper.findAll('[data-testid^="credential-field-"]')).toHaveLength(1)
    expect(wrapper.find('[data-testid="credential-new"]').exists()).toBe(false)
  })

  it('cannot save until the label and every field are filled', async () => {
    const wrapper = mountPicker()
    await flushPromises()
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    const save = wrapper.get('[data-testid="credential-save"]')
    expect(save.attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="credential-label"]').setValue('Only a label')
    expect(save.attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="credential-field-api_key"]').setValue('   ')
    expect(save.attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="credential-field-api_key"]').setValue('sk-anything')
    expect(save.attributes('disabled')).toBeUndefined()
  })

  it('selects what it just created, trimmed, so the row the author opened it from uses it', async () => {
    const api = fakeApi()
    const wrapper = mountPicker({}, api)
    await flushPromises()
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    await wrapper.get('[data-testid="credential-label"]').setValue('  Team key  ')
    await wrapper.get('[data-testid="credential-field-api_key"]').setValue('sk-team')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.calls.create[0].label).toBe('Team key')
    expect(lastEmitted(wrapper)).toBe('cr_0000ff01')
    expect(optionValues(wrapper)).toContain('cr_0000ff01')
  })

  it('keeps the form open with the server sentence when the create is refused', async () => {
    const api = fakeApi([], {
      createCredential: async () => {
        throw new Error('a credential of kind openrouter needs api_key')
      },
    })
    const wrapper = mountPicker({}, api)
    await flushPromises()
    await wrapper.get('[data-testid="credential-new"]').trigger('click')
    await wrapper.get('[data-testid="credential-label"]').setValue('Bad')
    await wrapper.get('[data-testid="credential-field-api_key"]').setValue('x')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-testid="credential-form"]').exists()).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toBe('a credential of kind openrouter needs api_key')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})

describe('the probe', () => {
  it('is disabled with nothing chosen, and reports the provider sentence for a choice', async () => {
    const api = fakeApi()
    const wrapper = mountPicker({}, api)
    await flushPromises()
    expect(wrapper.get('[data-testid="credential-test"]').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ modelValue: 'cr_0000aaaa' })
    expect(wrapper.get('[data-testid="credential-test"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="credential-test"]').trigger('click')
    await flushPromises()
    expect(api.calls.test).toEqual(['cr_0000aaaa'])
    const probe = wrapper.get('[data-testid="credential-probe"]')
    expect(probe.classes()).toContain('is-ok')
    expect(probe.text()).toContain('Key is valid (rate limit 100/min).')
  })

  it('renders a failed probe as failed, and a refused probe as an alert', async () => {
    const failing = fakeApi(leakyRows(), {
      testCredential: async () => ({ ok: false, detail: 'OpenRouter answered 401: invalid key' }),
    })
    const wrapper = mountPicker({ modelValue: 'cr_0000aaaa' }, failing)
    await flushPromises()
    await wrapper.get('[data-testid="credential-test"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="credential-probe"]').classes()).toContain('is-failed')
    expect(wrapper.text()).toContain('OpenRouter answered 401: invalid key')

    const refusing = fakeApi(leakyRows(), {
      testCredential: async () => {
        throw new Error('too many runs from this client; wait and try again Try again in 30s.')
      },
    })
    const refused = mountPicker({ modelValue: 'cr_0000aaaa' }, refusing)
    await flushPromises()
    await refused.get('[data-testid="credential-test"]').trigger('click')
    await flushPromises()
    expect(refused.find('[data-testid="credential-probe"]').exists()).toBe(false)
    expect(refused.get('[role="alert"]').text()).toContain('too many runs from this client')
  })
})

/* --- the transport: through authedFetch (D9) ------------------------------ */

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

describe('the credential calls ride authedFetch', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    setSessionActive(false)
    clearAccessToken()
    vi.unstubAllGlobals()
  })

  it('names the builder prefix, once', () => {
    expect(CREDENTIALS_PATH).toBe(`${BUILDER_API_PREFIX}/credentials`)
    expect(CREDENTIALS_PATH).toBe('/api/builder/credentials')
    expect(credentialApi).toEqual({ listCredentials, createCredential, deleteCredential, testCredential })
  })

  it('reads the list with the bearer attached, and retries a 401 exactly once', async () => {
    const tokenCalls: string[] = []
    const listCalls: RequestInit[] = []
    let refusedOnce = false
    fetchMock.mockImplementation((url: unknown, init?: RequestInit) => {
      if (String(url).includes('/api/auth/token')) {
        tokenCalls.push(String(url))
        return Promise.resolve(jsonResponse({ token: 'not-a-real-token' }))
      }
      expect(String(url)).toBe('/api/builder/credentials')
      listCalls.push(init ?? {})
      if (!refusedOnce) {
        refusedOnce = true
        return Promise.resolve(jsonResponse({ detail: 'sign in to use this endpoint' }, 401))
      }
      return Promise.resolve(jsonResponse(leakyRows()))
    })

    // Without an active session `getAccessToken` returns null, no token is ever
    // attached, and the retry cannot fire - the test would pass with the wiring
    // absent. See section 13's `getAccessToken` bullet for how that was found.
    setSessionActive(true)
    clearAccessToken()
    const rows = await listCredentials()

    expect(rows.map((entry) => entry.id)).toEqual(['cr_0000aaaa', 'cr_0000bbbb', 'cr_0000cccc'])
    expect(listCalls).toHaveLength(2)
    expect(new Headers(listCalls[0].headers).get('Authorization')).toBe('Bearer not-a-real-token')
    expect(new Headers(listCalls[1].headers).get('Authorization')).toBe('Bearer not-a-real-token')
    expect(tokenCalls).toHaveLength(2)
  })

  it('surfaces the server sentence, not the envelope, when a call is refused', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: 'credential vault is not configured' }, 503)),
    )
    await expect(listCredentials()).rejects.toThrow('credential vault is not configured')
    await expect(testCredential('cr_0000aaaa')).rejects.toThrow('credential vault is not configured')
    await expect(deleteCredential('cr_0000aaaa')).rejects.toThrow('credential vault is not configured')
  })

  it('posts the fields once, and parses no body from the 204 a delete answers', async () => {
    const seen: Array<{ url: string; init: RequestInit }> = []
    fetchMock.mockImplementation((url: unknown, init?: RequestInit) => {
      seen.push({ url: String(url), init: init ?? {} })
      if ((init?.method ?? 'GET') === 'DELETE') return Promise.resolve(new Response(null, { status: 204 }))
      if (String(url).endsWith('/test')) return Promise.resolve(jsonResponse({ ok: true, detail: 'fine' }))
      return Promise.resolve(jsonResponse(row({ id: 'cr_0000ff01', kind: 'github', label: 'CI' }), 201))
    })

    const created = await createCredential({ kind: 'github', label: 'CI', fields: { token: SECRET } })
    expect(created.id).toBe('cr_0000ff01')
    expect(seen[0].url).toBe('/api/builder/credentials')
    expect(seen[0].init.method).toBe('POST')
    expect(JSON.parse(String(seen[0].init.body))).toEqual({ kind: 'github', label: 'CI', fields: { token: SECRET } })

    await expect(deleteCredential('cr_0000ff01')).resolves.toBeUndefined()
    expect(seen[1]).toMatchObject({ url: '/api/builder/credentials/cr_0000ff01', init: { method: 'DELETE' } })

    await expect(testCredential('cr_0000ff01')).resolves.toEqual({ ok: true, detail: 'fine' })
    expect(seen[2]).toMatchObject({ url: '/api/builder/credentials/cr_0000ff01/test', init: { method: 'POST' } })
  })

  it('adds the 429 Retry-After sentence to a refused delete, like every other call', async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: 'slow down' }, 429, { 'Retry-After': '30' })),
    )
    await expect(deleteCredential('cr_0000aaaa')).rejects.toThrow('slow down Try again in 30s.')
  })
})

/* --- the kinds mirror config.py --------------------------------------------- */

/**
 * The path goes through a variable BEFORE `new URL`, for the reason
 * `builderApi.spec.ts` gives: Vite treats a template literal there as a dynamic
 * asset glob and tries to transform every `.py` in the directory.
 */
function pythonSource(relative: string): string {
  const path = `../../src/brief_crew/${relative}`
  return readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf-8')
}

const CONFIG = pythonSource('config.py')

/** `"kind": ("field", ...)` pairs of `CREDENTIAL_FIELDS`, in `config.py`'s order. */
function configCredentialFields(): Array<[string, string[]]> {
  const block = /^CREDENTIAL_FIELDS[^=]*= \{([\s\S]*?)\n\}/m.exec(CONFIG)
  if (!block) throw new Error('config.py declares no readable CREDENTIAL_FIELDS')
  // `[a-z0-9_]`, not `[a-z_]`: `e2b` carries a digit, and a class that missed
  // it would silently report ten kinds for eleven - the exact drift this
  // reader exists to catch.
  return [...block[1].matchAll(/^ {4}"([a-z0-9_]+)": \(([^)]*)\),?$/gm)].map((match) => [
    match[1],
    [...match[2].matchAll(/"([a-z0-9_]+)"/g)].map((field) => field[1]),
  ])
}

function configIdPattern(): string {
  const declaration = /^CREDENTIAL_ID_PATTERN = r"(.+)"$/m.exec(CONFIG)
  if (!declaration) throw new Error('config.py declares no readable CREDENTIAL_ID_PATTERN')
  return declaration[1]
}

describe('the client mirror of config.py', () => {
  it('names every kind config.py names, in its order, and no other', () => {
    const served = configCredentialFields()
    expect(served.length).toBeGreaterThan(0)
    expect(CREDENTIAL_KIND_ORDER).toEqual(served.map(([kind]) => kind))
    expect(Object.keys(CREDENTIAL_KINDS)).toEqual(served.map(([kind]) => kind))
  })

  it('asks for exactly the fields config.py requires of each kind', () => {
    for (const [kind, fields] of configCredentialFields()) {
      expect(CREDENTIAL_KINDS[kind as CredentialKind].fields, kind).toEqual(fields)
      // A secret is always one of the fields, and every kind has at least one -
      // a kind with no secret would be a label, not a credential.
      const secret = CREDENTIAL_KINDS[kind as CredentialKind].secret
      expect(secret.length, kind).toBeGreaterThan(0)
      for (const name of secret) expect(fields, `${kind}.${name}`).toContain(name)
    }
  })

  it('spells the id pattern exactly as config.py does', () => {
    expect(CREDENTIAL_ID_PATTERN.source).toBe(configIdPattern())
    expect(CREDENTIAL_ID_PATTERN.test('cr_0123abcd')).toBe(true)
    expect(CREDENTIAL_ID_PATTERN.test('cred_0123abcd0123abcd')).toBe(false)
    expect(CREDENTIAL_ID_PATTERN.test('ug_0123abcd')).toBe(false)
  })

  it('renders a form for every kind without a hole', async () => {
    // Every kind mounts, opens its form and renders one input per field. A kind
    // declared in config.py but missing from `CREDENTIAL_KINDS` is a compile
    // error (the record is total over `CredentialKind`); this is the runtime
    // half, that each entry actually produces a form an author can fill.
    for (const kind of CREDENTIAL_KIND_ORDER) {
      const wrapper = mountPicker({ kind }, fakeApi([]))
      await flushPromises()
      await wrapper.get('[data-testid="credential-new"]').trigger('click')
      expect(wrapper.findAll('[data-testid^="credential-field-"]'), kind).toHaveLength(
        CREDENTIAL_KINDS[kind].fields.length,
      )
      wrapper.unmount()
    }
  })
})

/* --- in the inspector: one field on an agent, none on a crew -------------- */

describe('BillableForm offers the picker on an agent node, and only there', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        expect(String(input)).toBe('/api/builder/credentials')
        return jsonResponse(leakyRows())
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mountForm(node: ReturnType<typeof agentNode> | ReturnType<typeof crewNode>) {
    return mount(BillableForm, {
      props: { doc: documentFixture([node]), node, vocabulary: vocabularyFixture() },
      global: { provide: problemsProvide([]) },
    })
  }

  function lastCommit(wrapper: ReturnType<typeof mountForm>): InspectorCommit | undefined {
    const emitted = wrapper.emitted('commit')
    return emitted ? ((emitted as unknown[][])[emitted.length - 1][0] as InspectorCommit) : undefined
  }

  it('anchors the picker to the credential_id field on an agent', async () => {
    const wrapper = mountForm(agentNode())
    await flushPromises()
    const rowEl = wrapper.get('[data-field="credential_id"]')
    expect(rowEl.text()).toContain('OpenRouter key')
    expect(rowEl.find('[data-testid="credential-picker"]').exists()).toBe(true)
    // The label names the select, so `focusField` and a screen reader reach it.
    const select = rowEl.get('[data-testid="credential-select"]')
    expect(rowEl.get('label.field-label').attributes('for')).toBe(select.attributes('id'))
    expect(rowEl.text()).toContain('platform key')
    expect(wrapper.html()).not.toContain(SECRET)
  })

  it('renders no such field for a crew', async () => {
    const wrapper = mountForm(crewNode())
    await flushPromises()
    expect(wrapper.find('[data-field="credential_id"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="credential-picker"]').exists()).toBe(false)
  })

  it('commits the chosen id onto the node, as one labelled step', async () => {
    const wrapper = mountForm(agentNode())
    await flushPromises()
    await wrapper.get('[data-field="credential_id"] select').setValue('cr_0000cccc')
    const commit = lastCommit(wrapper)
    expect(commit?.label).toBe('Use your own OpenRouter key')
    const agent = commit?.next.nodes.find((entry) => entry.id === 'scoper')
    expect(agent?.kind).toBe('agent')
    expect((agent?.config as { credential_id?: string | null }).credential_id).toBe('cr_0000cccc')
  })

  it('commits null for the platform key, and nothing when that is already the case', async () => {
    const keyed = mountForm(agentNode('scoper', { credential_id: 'cr_0000aaaa' }))
    await flushPromises()
    expect(keyed.get('[data-field="credential_id"]').text()).toContain('your key')
    await keyed.get('[data-field="credential_id"] select').setValue('')
    const commit = lastCommit(keyed)
    expect(commit?.label).toBe('Use the platform OpenRouter key')
    const agent = commit?.next.nodes.find((entry) => entry.id === 'scoper')
    expect((agent?.config as { credential_id?: string | null }).credential_id).toBeNull()

    const bare = mountForm(agentNode())
    await flushPromises()
    await bare.get('[data-field="credential_id"] select').setValue('')
    // A fresh node carries no key at all; choosing "platform" changes nothing,
    // so nothing is committed and the document's wire shape is untouched.
    expect(bare.emitted('commit')).toBeUndefined()
  })
})
