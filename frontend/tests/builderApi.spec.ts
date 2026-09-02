import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  BUILDER_API_PREFIX,
  BuilderApi,
  BuilderConflictError,
  BuilderPublishRefusedError,
  readPublishRefusal,
  type BuilderApiLike,
  type BuilderLifecycleApiLike,
} from '../src/services/builderApi'
import { VOCABULARY_PATH } from '../src/data/builderVocabulary'
import { clearAccessToken, setSessionActive } from '../src/services/authClient'
import { BUILDER_SCHEMA_ID, documentId, edgeId, nodeId } from '../src/types/builder'
import type { BuilderDocument } from '../src/types/builder'

/**
 * The four contract behaviours that live in `builderApi.ts` and nowhere else.
 *
 * Each one is a place where doing the obvious thing is wrong, and wrong
 * silently: reading a `Location` header that is unreadable cross-origin,
 * sending a document `id` to a handler that feeds it straight into a 422,
 * sending a string version to a handler that refuses it by hand, and rendering
 * publish's object-shaped `detail` through the string path so the author sees
 * an envelope instead of the problem list inside it. Three of the four work
 * perfectly behind the Vite dev proxy and fail only in production.
 *
 * Where a claim about the server can be checked, it is checked against the
 * Python at run time rather than transcribed - the route table, the prefix and
 * the conflict sentence are all read out of `src/brief_crew/` below. A mirror
 * that merely looked right on the day it was written is what this repo's
 * counts went wrong five times doing.
 */

/**
 * A python source file, read at test time.
 *
 * The path is built into a variable BEFORE it reaches `new URL`, and that is
 * not style: Vite treats `new URL(\`./x/${v}\`, import.meta.url)` as a dynamic
 * asset glob and tries to transform every `.py` under the directory, which
 * fails the suite with `Denied ID .../__init__.py?url`. A variable argument is
 * left alone. `builderTypes.spec.ts` does the same thing for the same reason.
 */
function PY(relative: string): string {
  const path = `../../src/brief_crew/${relative}`
  return readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf-8')
}

/**
 * The smallest document the API client cares about.
 *
 * Deliberately NOT a valid graph - `builderTypes.spec.ts` owns the fixture that
 * the real `validate_document` returned zero problems for. Nothing in this file
 * asks the server for a judgement; every test here is about what leaves the
 * client and what it does with the answer.
 */
const DOCUMENT: BuilderDocument = {
  schema: BUILDER_SCHEMA_ID,
  id: documentId('ug_0a1b2c3d'),
  name: 'Clinic scheduling brief',
  version: 7,
  input_field: nodeId('idea'),
  nodes: [
    {
      id: nodeId('idea'),
      kind: 'input',
      label: 'Idea',
      position: { x: 0, y: 0 },
      config: { field: nodeId('idea'), label: null, max_chars: 2000, required: true },
    },
    {
      id: nodeId('report'),
      kind: 'output',
      label: 'Report',
      position: { x: 200, y: 0 },
      config: { body_key: 'markdown_body', source: '${state.out__idea}' },
    },
  ],
  edges: [
    {
      id: edgeId('e1'),
      source: nodeId('idea'),
      source_port: 'out',
      target: nodeId('report'),
      target_port: 'in',
    },
  ],
  joins: {},
  budget: null,
}

/** The plan 15 D1 envelope, as `GET .../export` answers it and `POST .../import` takes it. */
const ENVELOPE = {
  export: 'builder.flow/v1' as const,
  exported_at: '2026-09-02T10:14:00Z',
  name: 'Clinic scheduling brief',
  source_version: 7,
  needs_credentials: ['search'],
  document: { name: 'Clinic scheduling brief', nodes: [], edges: [], joins: {}, input_field: 'idea' },
}

/** What `POST /workflows` answers, trimmed to the keys these tests read. */
const STORED = {
  id: 'ug_0a1b2c3d',
  document: DOCUMENT,
  status: 'draft',
  version: 1,
  head_version: 1,
  created_at: '2026-09-02T00:00:00Z',
  updated_at: '2026-09-02T00:00:00Z',
  problems: [],
  budget: {
    static_cost_usd: 0,
    floor_cost_usd: 0,
    modelled_calls: 0,
    billable_nodes: 0,
    escalation_nodes: 0,
    cycles: 0,
    unpriced_models: [],
    over_ceiling: false,
    ceiling_usd: 10,
  },
  graph: { workflow_id: 'ug_0a1b2c3d', version: 'abc', nodes: [], edges: [] },
  published: false,
}

describe('the builder API client', () => {
  let api: BuilderApi
  let fetchMock: ReturnType<typeof vi.fn>
  let originalFetch: typeof globalThis.fetch

  const jsonResponse = (body: unknown, status = 200, headers: Headers = new Headers()) => ({
    ok: status >= 200 && status < 300,
    status,
    headers,
    json: async () => body,
    text: async () => JSON.stringify(body),
  })

  const refusal = (status: number, detail: unknown, headers: Headers = new Headers()) => ({
    ok: false,
    status,
    statusText: 'Refused',
    headers,
    text: async () => JSON.stringify({ detail }),
    json: async () => ({ detail }),
  })

  /** The parsed body of the nth `fetch` call. */
  const sentBody = (call = 0): Record<string, unknown> =>
    JSON.parse(String((fetchMock.mock.calls[call][1] as RequestInit).body)) as Record<string, unknown>

  const sentDocument = (call = 0): Record<string, unknown> =>
    sentBody(call).document as Record<string, unknown>

  beforeEach(() => {
    api = new BuilderApi()
    fetchMock = vi.fn()
    originalFetch = globalThis.fetch
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  describe('it asks the routes the server actually declares', () => {
    it('spells the prefix the way the router does', () => {
      // Drift in a duplicated constant is the whole hazard, so it is a test
      // rather than a comment. `BUILDER_API_PREFIX` in service/builder_api.py.
      const declared = /^BUILDER_API_PREFIX = "([^"]+)"$/m.exec(PY('service/builder_api.py'))
      expect(declared?.[1]).toBe(BUILDER_API_PREFIX)
      expect(BUILDER_API_PREFIX).toBe('/api/builder')

      /*
       * `VOCABULARY_PATH` is the same constant restated a third time, in the
       * one module that does not import it - and it had no agreement test at
       * all while its neighbours did. It is the URL a palette with no
       * vocabulary asks for, and a drift there disables the palette with a
       * 404 sentence about the API being down.
       */
      expect(VOCABULARY_PATH).toBe(`${declared?.[1]}/vocabulary`)
    })

    it('calls only paths the python declares, by the method it declares them with', async () => {
      /*
       * Read the decorator table rather than trusting eight string literals.
       * A route renamed on the server is otherwise a 404 that nothing on this
       * side disagrees with until somebody opens the builder.
       */
      const declared = new Set(
        [...PY('service/builder_api.py').matchAll(/@router\.(get|post|put|delete)\(\s*\n?\s*"([^"]+)"/g)].map(
          (match) => `${match[1].toUpperCase()} ${match[2]}`,
        ),
      )
      /*
       * Eight routes, and the client reaches every one of them. A ninth
       * appearing here with no caller is a capability nothing can use.
       *
       * Plan 15 adds four (`s1/15-api`), and this client already calls them
       * (`s1/15-ui`). The two land on `main` separately, so which world this
       * test is in is READ off the python rather than assumed: before the API
       * branch merges the table says eight and the four are not walked;
       * after, it says twelve and they are - and a client route the python
       * does not declare is still a failure either way.
       */
      const planFifteen = [
        'GET /workflows/{document_id}/export',
        'POST /workflows/import',
        'POST /workflows/{document_id}/duplicate',
        'GET /workflows/{document_id}/versions',
      ]
      const planFifteenLanded = planFifteen.every((route) => declared.has(route))
      expect(declared.size).toBe(planFifteenLanded ? 12 : 8)

      /*
       * Seven of the eight are this class's. The eighth - `GET /vocabulary` -
       * is asked for by `data/builderVocabulary.ts`, which owns the session
       * cache and the payload check that make it safe, so `BuilderApi` has no
       * method for it and this leg is proved from `VOCABULARY_PATH` instead.
       *
       * That keeps the property TOTAL, which is the only property worth having
       * here: an unreached declared route is still a failure, it is just no
       * longer a failure this class can fix by growing a second answer.
       */
      const vocabularyRoute = `GET ${VOCABULARY_PATH.slice(BUILDER_API_PREFIX.length)}`
      expect(VOCABULARY_PATH.startsWith(`${BUILDER_API_PREFIX}/`)).toBe(true)
      expect(declared).toContain(vocabularyRoute)

      fetchMock.mockResolvedValue(jsonResponse(STORED))
      await api.list(20)
      await api.create(DOCUMENT)
      await api.get('ug_0a1b2c3d', 4)
      await api.save('ug_0a1b2c3d', DOCUMENT, 7)
      await api.remove('ug_0a1b2c3d')
      await api.validate(DOCUMENT)
      await api.publish('ug_0a1b2c3d')
      if (planFifteenLanded) {
        await api.exportWorkflow('ug_0a1b2c3d')
        await api.importWorkflow(ENVELOPE)
        await api.duplicateWorkflow('ug_0a1b2c3d')
        await api.listVersions('ug_0a1b2c3d')
      }

      const asked = fetchMock.mock.calls.map(([url, init]) => {
        const path = String(url).split('?')[0].slice(BUILDER_API_PREFIX.length)
        const method = ((init as RequestInit | undefined)?.method ?? 'GET').toUpperCase()
        return `${method} ${path.replace('ug_0a1b2c3d', '{document_id}')}`
      })

      expect(asked).toEqual([
        'GET /workflows',
        'POST /workflows',
        'GET /workflows/{document_id}',
        'PUT /workflows/{document_id}',
        'DELETE /workflows/{document_id}',
        'POST /validate',
        'POST /workflows/{document_id}/publish',
        ...(planFifteenLanded ? planFifteen : []),
      ])
      for (const route of asked) expect(declared).toContain(route)
      expect(new Set([...asked, vocabularyRoute]).size).toBe(declared.size)
    })

    it('passes limit and version as the query parameters the handlers take', async () => {
      fetchMock.mockResolvedValue(jsonResponse(STORED))
      await api.list(20)
      await api.get('ug_0a1b2c3d', 4)
      await api.publish('ug_0a1b2c3d', 4)

      expect(String(fetchMock.mock.calls[0][0])).toBe(`${BUILDER_API_PREFIX}/workflows?limit=20`)
      expect(String(fetchMock.mock.calls[1][0])).toBe(
        `${BUILDER_API_PREFIX}/workflows/ug_0a1b2c3d?version=4`,
      )
      expect(String(fetchMock.mock.calls[2][0])).toBe(
        `${BUILDER_API_PREFIX}/workflows/ug_0a1b2c3d/publish?version=4`,
      )
    })

    it('omits an absent limit or version rather than sending undefined', async () => {
      // `?version=undefined` meets `ge=1` as a 422, which is a refusal about a
      // parameter the author never chose.
      fetchMock.mockResolvedValue(jsonResponse(STORED))
      await api.list()
      await api.get('ug_0a1b2c3d')
      await api.publish('ug_0a1b2c3d')

      for (const [url] of fetchMock.mock.calls) expect(String(url)).not.toContain('?')
    })
  })

  describe('create reads the id off the body, never off Location', () => {
    /*
     * `Location` is not a CORS-safelisted response header, and
     * `CORS_EXPOSE_HEADERS` names only ETag and Retry-After - so cross-origin,
     * which is the deployed shape, `headers.get('Location')` answers null with
     * nothing raised anywhere. It works behind the dev proxy and fails in
     * production.
     */
    it('does not touch the response headers at all', async () => {
      const headers = new Headers({ Location: `${BUILDER_API_PREFIX}/workflows/ug_deadbeef` })
      const spy = vi.spyOn(headers, 'get')
      fetchMock.mockResolvedValueOnce(jsonResponse(STORED, 201, headers))

      const created = await api.create(DOCUMENT)

      expect(created.id).toBe('ug_0a1b2c3d')
      expect(spy).not.toHaveBeenCalled()
    })

    it('takes the body id even when Location names a different document', async () => {
      const headers = new Headers({ Location: `${BUILDER_API_PREFIX}/workflows/ug_deadbeef` })
      fetchMock.mockResolvedValueOnce(jsonResponse({ ...STORED, id: 'ug_11112222' }, 201, headers))

      await expect(api.create(DOCUMENT)).resolves.toMatchObject({ id: 'ug_11112222' })
    })

    it('names the CORS decision that makes the header unreadable', () => {
      // The claim above is only as good as the config it rests on. If Location
      // is ever exposed, this test says so before somebody "simplifies" the
      // client into reading it.
      const exposed = /^CORS_EXPOSE_HEADERS = \(([^)]*)\)/m.exec(PY('config.py'))?.[1] ?? ''
      expect(exposed).toContain('"ETag"')
      expect(exposed).not.toContain('Location')
    })
  })

  describe('validate sends the shape the raw handler reads', () => {
    it('omits the document id', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ valid: true, problems: [], budget: STORED.budget }))

      await api.validate(DOCUMENT)

      expect(sentDocument()).not.toHaveProperty('id')
      expect(sentDocument().name).toBe('Clinic scheduling brief')
    })

    it('sends the version as a number, never as a string', async () => {
      /*
       * `/validate` is the only endpoint that reads a version off the request
       * BODY rather than off a typed field, so a non-numeric one is refused by
       * hand: `version must be a whole number; this document carries 'v7'`.
       * That is an error about a field the author never typed and cannot see,
       * and until 2026-09-02 it was worse - a bare `int(...)` raised
       * ValueError and answered **500**, which the canvas reads as
       * `unreachable`: a document that mysteriously would not validate,
       * pointing at the network rather than at anything.
       */
      const stringy = { ...DOCUMENT, version: '7' as unknown as number }
      fetchMock.mockResolvedValueOnce(jsonResponse({ valid: true, problems: [], budget: STORED.budget }))

      await api.validate(stringy)

      expect(sentDocument().version).toBe(7)
      expect(typeof sentDocument().version).toBe('number')
    })

    it('is answering the two raw-body reads the handler still performs', () => {
      /*
       * Both halves are read off the untyped mapping before any schema sees
       * it, which is what makes them the client's problem. Asserted against
       * the source because the server moved under this test once already: the
       * version read was a bare `int(...)` and a 500 until `_requested_version`
       * turned it into a 422. Sending a number means neither refusal can fire,
       * whichever status it would have carried.
       */
      const source = PY('service/builder_api.py')
      expect(source).toContain('version=_requested_version(request.document)')
      expect(source).toContain('str(request.document.get("id") or new_document_id())')
      // And the id read is still unguarded: a malformed one reaches
      // BUILDER_DOCUMENT_ID_PATTERN and comes back 422 naming `id`.
      expect(source).not.toContain('_requested_document_id')
    })

    it('carries an abort signal through to fetch', async () => {
      // The canvas revalidates on a 400ms debounce; an answer about a document
      // the author has edited past must be cancelled, not raced.
      const controller = new AbortController()
      fetchMock.mockResolvedValueOnce(jsonResponse({ valid: true, problems: [], budget: STORED.budget }))

      await api.validate(DOCUMENT, controller.signal)

      expect((fetchMock.mock.calls[0][1] as RequestInit).signal).toBe(controller.signal)
    })
  })

  describe('save is a compare-and-set, and its 409 is a typed refusal', () => {
    it('sends the expected version the caller was given, not the document own', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(STORED))

      // The document says 7; the server response said 5. The response wins,
      // because the server assigns the version on every write.
      await api.save('ug_0a1b2c3d', DOCUMENT, 5)

      expect(sentBody().expected_version).toBe(5)
      expect(sentDocument().version).toBe(7)
    })

    it('throws BuilderConflictError carrying the stored version', async () => {
      fetchMock.mockResolvedValueOnce(
        refusal(409, 'document ug_0a1b2c3d is at version 8, not 7; reload it before saving again'),
      )

      const error = await api.save('ug_0a1b2c3d', DOCUMENT, 7).catch((thrown: unknown) => thrown)

      expect(error).toBeInstanceOf(BuilderConflictError)
      const conflict = error as BuilderConflictError
      expect(conflict.storedVersion).toBe(8)
      // The sentence is rendered verbatim; the parse is an addition, never a
      // replacement.
      expect(conflict.detail).toBe(
        'document ug_0a1b2c3d is at version 8, not 7; reload it before saving again',
      )
    })

    it('reads the stored version and not the expected one', async () => {
      // The sentence names both. Taking the wrong number sends ConflictDialog
      // to re-fetch the author's own stale version, where it finds no changes.
      fetchMock.mockResolvedValueOnce(
        refusal(409, 'document ug_0a1b2c3d is at version 12, not 3; reload it before saving again'),
      )

      const error = (await api.save('ug_0a1b2c3d', DOCUMENT, 3).catch((thrown: unknown) => thrown)) as
        BuilderConflictError

      expect(error.storedVersion).toBe(12)
    })

    it('matches the sentence the python actually raises', () => {
      /*
       * The parse is a regex over prose, which is the fragile kind of coupling.
       * So the prose is read out of `store.py` and rendered here, rather than
       * transcribed - a reworded exception fails this test instead of silently
       * returning null forever.
       */
      const source = PY('builder/store.py')
      const template = /f"document \{document_id\} is at version \{(\w+)\}, not \{(\w+)\}; "\s*\n\s*"([^"]*)"/.exec(
        source,
      )
      expect(template).not.toBeNull()
      const rendered = `document ug_0a1b2c3d is at version 8, not 7; ${template?.[3]}`
      expect(/is at version (\d+)/.exec(rendered)?.[1]).toBe('8')
    })

    it('degrades to a null version when the sentence changes shape', async () => {
      // A null is handled by the caller with one extra GET of head. A wrong
      // number would not be handled at all.
      fetchMock.mockResolvedValueOnce(refusal(409, 'somebody else saved this document'))

      const error = (await api.save('ug_0a1b2c3d', DOCUMENT, 7).catch((thrown: unknown) => thrown)) as
        BuilderConflictError

      expect(error).toBeInstanceOf(BuilderConflictError)
      expect(error.storedVersion).toBeNull()
      expect(error.message).toBe('somebody else saved this document')
    })
  })

  describe('publish unwraps the one object-shaped detail on this router', () => {
    const PROBLEMS = [
      {
        code: 'no-input-node',
        severity: 'error',
        message: 'this graph has no input node, so a run has nothing to start from',
        node_id: null,
        edge_id: null,
      },
      {
        code: 'router-otherwise',
        severity: 'error',
        message: 'router route_scope needs exactly one otherwise branch',
        node_id: 'route_scope',
        edge_id: null,
      },
    ]

    it('throws BuilderPublishRefusedError carrying the problem list', async () => {
      fetchMock.mockResolvedValueOnce(
        refusal(422, { message: 'this graph cannot be compiled', problems: PROBLEMS }),
      )

      const error = await api.publish('ug_0a1b2c3d').catch((thrown: unknown) => thrown)

      expect(error).toBeInstanceOf(BuilderPublishRefusedError)
      const refused = error as BuilderPublishRefusedError
      expect(refused.message).toBe('this graph cannot be compiled')
      expect(refused.problems).toHaveLength(2)
      expect(refused.problems[1].node_id).toBe('route_scope')
    })

    it('never shows the author the raw envelope', async () => {
      /*
       * The defect this repo has already shipped once, in the other direction:
       * `new Error(await response.text())` put `{"detail":"..."}` in front of an
       * operator, braces and all (remaining-work item 11). An object detail run
       * through the string path is the same failure with more to lose.
       */
      fetchMock.mockResolvedValueOnce(
        refusal(422, { message: 'this graph cannot be compiled', problems: PROBLEMS }),
      )

      const error = (await api.publish('ug_0a1b2c3d').catch((thrown: unknown) => thrown)) as Error

      expect(error.message).not.toContain('{')
      expect(error.message).not.toContain('detail')
      expect(error.message).not.toContain('[object Object]')
    })

    it('leaves publish other refusals on the plain string path', async () => {
      // `_guarded` answers 404 and a string-detail 422 from the same route. Only
      // the compiler's refusal carries a problem list.
      fetchMock.mockResolvedValueOnce(refusal(404, 'document not found'))

      const error = await api.publish('ug_0a1b2c3d').catch((thrown: unknown) => thrown)

      expect(error).not.toBeInstanceOf(BuilderPublishRefusedError)
      expect((error as Error).message).toBe('document not found')
    })

    it('returns the contract the author now owns', async () => {
      const published = {
        workflow_id: 'ug_0a1b2c3d',
        graph_version: '0f1e2d3c4b5a6978',
        version: 4,
        input_field: 'idea',
        static_cost_usd: 0.42,
        gated_before_spend: true,
        reserved_input_keys: ['no_gates', 'sequential_branches'],
      }
      fetchMock.mockResolvedValueOnce(jsonResponse(published))

      await expect(api.publish('ug_0a1b2c3d')).resolves.toEqual(published)
    })
  })

  describe('readPublishRefusal keys on the shape, not on the caller', () => {
    it('refuses a string detail', () => {
      expect(readPublishRefusal('{"detail":"document not found"}')).toBeNull()
    })

    it('refuses pydantic list-of-errors', () => {
      expect(readPublishRefusal('{"detail":[{"msg":"field required"}]}')).toBeNull()
    })

    it('refuses an object with no problems array', () => {
      expect(readPublishRefusal('{"detail":{"message":"nope"}}')).toBeNull()
    })

    it('refuses a body that is not JSON at all', () => {
      expect(readPublishRefusal('<html>502 Bad Gateway</html>')).toBeNull()
      expect(readPublishRefusal('')).toBeNull()
      expect(readPublishRefusal('{not json')).toBeNull()
    })

    it('accepts an empty problem list, which is a compile error with no anchor', () => {
      expect(readPublishRefusal('{"detail":{"message":"nope","problems":[]}}')).toEqual({
        message: 'nope',
        problems: [],
      })
    })
  })

  describe('the ordinary refusals', () => {
    it('renders the server sentence rather than the envelope', async () => {
      fetchMock.mockResolvedValueOnce(refusal(422, 'nodes.3.config.max_iter: Input should be less than or equal to 8'))

      await expect(api.get('ug_0a1b2c3d')).rejects.toThrow(
        'nodes.3.config.max_iter: Input should be less than or equal to 8',
      )
    })

    it('adds the retry sentence a 429 exposes for exactly this reader', async () => {
      fetchMock.mockResolvedValueOnce(
        refusal(429, 'too many runs from this client; wait and try again', new Headers({ 'Retry-After': '30' })),
      )

      await expect(api.list()).rejects.toThrow(/wait and try again Try again in 30s\./)
    })

    it('reports a 413 about the document size as the server phrased it', async () => {
      fetchMock.mockResolvedValueOnce(
        refusal(413, 'a builder document is limited to 262144 bytes; this one is 262200'),
      )

      await expect(api.save('ug_0a1b2c3d', DOCUMENT, 7)).rejects.toThrow('262200')
    })
  })

  describe('the four plan 15 routes', () => {
    /*
     * Built against the route table in `.agent/plans/15-persistence.md` D1/D3
     * and ruling S1-7, on a branch whose python does not declare them yet. The
     * walk above proves them reached once the API branch lands; this proves
     * the exact path, method and body each one sends, so the two branches can
     * be checked against each other before they meet.
     */
    it('exports at head or at a named version, and reads the envelope off the body', async () => {
      fetchMock.mockResolvedValue(jsonResponse(ENVELOPE))
      await expect(api.exportWorkflow('ug_0a1b2c3d')).resolves.toEqual(ENVELOPE)
      await api.exportWorkflow('ug_0a1b2c3d', 4)

      expect(String(fetchMock.mock.calls[0][0])).toBe(`${BUILDER_API_PREFIX}/workflows/ug_0a1b2c3d/export`)
      expect(String(fetchMock.mock.calls[1][0])).toBe(
        `${BUILDER_API_PREFIX}/workflows/ug_0a1b2c3d/export?version=4`,
      )
      expect((fetchMock.mock.calls[0][1] as RequestInit | undefined)?.method ?? 'GET').toBe('GET')
      // `Content-Disposition` is not CORS-safelisted and not in
      // `CORS_EXPOSE_HEADERS`, so the name comes off the envelope, never the header.
      const exposed = /^CORS_EXPOSE_HEADERS = \(([^)]*)\)/m.exec(PY('config.py'))?.[1] ?? ''
      expect(exposed).not.toContain('Content-Disposition')
    })

    it('imports by POSTing the envelope itself, and reads needs_credentials off the 201', async () => {
      fetchMock.mockResolvedValueOnce(
        jsonResponse({ ...STORED, id: 'ug_9999beef', needs_credentials: ['search'] }, 201),
      )

      const imported = await api.importWorkflow(ENVELOPE)

      expect(String(fetchMock.mock.calls[0][0])).toBe(`${BUILDER_API_PREFIX}/workflows/import`)
      expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
      expect(sentBody()).toEqual(ENVELOPE)
      expect(imported.id).toBe('ug_9999beef')
      expect(imported.needs_credentials).toEqual(['search'])
    })

    it('duplicates with an empty POST, at head or at a named version', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ ...STORED, id: 'ug_c0c0c0c0' }, 201))
      await expect(api.duplicateWorkflow('ug_0a1b2c3d')).resolves.toMatchObject({ id: 'ug_c0c0c0c0' })
      await api.duplicateWorkflow('ug_0a1b2c3d', 4)

      expect(String(fetchMock.mock.calls[0][0])).toBe(`${BUILDER_API_PREFIX}/workflows/ug_0a1b2c3d/duplicate`)
      expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
      expect((fetchMock.mock.calls[0][1] as RequestInit).body).toBeUndefined()
      expect(String(fetchMock.mock.calls[1][0])).toBe(
        `${BUILDER_API_PREFIX}/workflows/ug_0a1b2c3d/duplicate?version=4`,
      )
    })

    it('lists versions with a GET and hands the rows back in the order they came', async () => {
      const rows = [
        { version: 7, status: 'draft', created_at: '2026-09-02T10:14:00Z', bytes: 2048 },
        { version: 3, status: 'draft', created_at: '2026-09-01T18:30:00Z', bytes: 640 },
      ]
      fetchMock.mockResolvedValueOnce(jsonResponse(rows))

      await expect(api.listVersions('ug_0a1b2c3d')).resolves.toEqual(rows)

      expect(String(fetchMock.mock.calls[0][0])).toBe(`${BUILDER_API_PREFIX}/workflows/ug_0a1b2c3d/versions`)
      expect((fetchMock.mock.calls[0][1] as RequestInit | undefined)?.method ?? 'GET').toBe('GET')
    })

    it('percent-encodes the id in all three id-bearing paths', async () => {
      fetchMock.mockResolvedValue(jsonResponse(ENVELOPE))
      await api.exportWorkflow('ug/../x')
      await api.duplicateWorkflow('ug/../x')
      await api.listVersions('ug/../x')
      for (const [url] of fetchMock.mock.calls) expect(String(url)).toContain('/workflows/ug%2F..%2Fx/')
    })

    it('is a second, narrower surface, so criterion 11 double keeps compiling', () => {
      /*
       * `BuilderLifecycleApiLike` is NOT folded into `BuilderApiLike`: the
       * persistence suite's double implements the seven-method Pick and must
       * pass unchanged (plan 15 criterion 11). A surface that calls these four
       * asks for this type instead, and its double is still compiler-forced to
       * match its subject.
       */
      const double: BuilderLifecycleApiLike = {
        exportWorkflow: async () => ENVELOPE,
        importWorkflow: async () => ({ ...STORED, needs_credentials: [] }) as never,
        duplicateWorkflow: async () => STORED as never,
        listVersions: async () => [],
      }
      expect(Object.keys(double).sort()).toEqual([
        'duplicateWorkflow',
        'exportWorkflow',
        'importWorkflow',
        'listVersions',
      ])
    })
  })

  describe('delete', () => {
    it('does not parse the 204 it is answered with', async () => {
      // `.json()` on an empty body throws, which would turn a delete that fully
      // succeeded into an error the author would retry against a document that
      // is already gone.
      const exploding = {
        ok: true,
        status: 204,
        headers: new Headers(),
        json: async () => {
          throw new SyntaxError('Unexpected end of JSON input')
        },
        text: async () => '',
      }
      fetchMock.mockResolvedValueOnce(exploding)

      await expect(api.remove('ug_0a1b2c3d')).resolves.toBeUndefined()
    })

    it('still reports a refusal', async () => {
      fetchMock.mockResolvedValueOnce(refusal(404, 'document not found'))

      await expect(api.remove('ug_deadbeef')).rejects.toThrow('document not found')
    })
  })

  describe('it rides the same transport as the run surface', () => {
    /*
     * The point of extracting `httpCore` from `studioApi.ts` rather than
     * writing a second fetch wrapper here. Two copies of a one-shot 401 retry
     * is how one of them quietly stops retrying, and the failure is invisible:
     * a revoked-then-renewed session would show the author "your session has
     * expired" on the builder and nothing at all on the run console.
     */
    it('attaches the bearer and retries a 401 exactly once, with a forced fresh mint', async () => {
      const tokenCalls: string[] = []
      const builderCalls: RequestInit[] = []
      let refusedOnce = false
      fetchMock.mockImplementation((url: unknown, init?: RequestInit) => {
        if (String(url).includes('/api/auth/token')) {
          tokenCalls.push(String(url))
          return Promise.resolve(jsonResponse({ token: 'not-a-real-token' }))
        }
        builderCalls.push(init ?? {})
        if (!refusedOnce) {
          refusedOnce = true
          return Promise.resolve(refusal(401, 'sign in to use this endpoint'))
        }
        return Promise.resolve(jsonResponse([]))
      })

      // Without an active session `getAccessToken` returns null, no token is
      // ever attached, and the retry cannot fire - the test would pass with the
      // wiring entirely absent. `studioApi.spec.ts` shipped in exactly that
      // state for one commit.
      setSessionActive(true)
      clearAccessToken()
      try {
        await expect(api.list()).resolves.toEqual([])
      } finally {
        setSessionActive(false)
      }

      expect(builderCalls).toHaveLength(2)
      expect(new Headers(builderCalls[0].headers).get('Authorization')).toBe('Bearer not-a-real-token')
      // Two mints: the cached one for the first attempt, and the forced one the
      // retry exists to obtain. The cache is the authority on `exp`; the API is
      // the authority on whether the session still exists.
      expect(tokenCalls).toHaveLength(2)
    })
  })

  describe('BuilderApiLike', () => {
    it('is satisfied by a double that implements all seven methods', () => {
      /*
       * The point of the Pick: this object is checked against the class, so a
       * method that changes signature breaks every double at compile time
       * rather than at whatever the double happened to return. A double that
       * diverges from its subject certifies nothing.
       *
       * Seven, not eight: `vocabulary` was removed once `builderVocabulary.ts`
       * owned that call. An uncalled method on a surface every double must
       * implement is a second answer waiting for a caller, and the caller it
       * eventually got would have skipped the payload check.
       */
      const double: BuilderApiLike = {
        list: async () => [],
        create: async () => STORED as never,
        get: async () => STORED as never,
        save: async () => STORED as never,
        remove: async () => undefined,
        validate: async () => ({ valid: true, problems: [], budget: STORED.budget }),
        publish: async () => {
          throw new Error('unused')
        },
      }

      expect(Object.keys(double).sort()).toEqual([
        'create',
        'get',
        'list',
        'publish',
        'remove',
        'save',
        'validate',
      ])
    })
  })
})
