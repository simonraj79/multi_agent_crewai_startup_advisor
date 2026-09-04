import { readErrorDetail, retryAfterSentence } from '../data/serverLimits'
import type {
  BuilderToolCatalogueEntry,
  CustomToolDraft,
  CustomToolRow,
  McpDiscovery,
  McpServerDraft,
  McpServerRow,
  SkillDetail,
  SkillSummary,
} from '../types/builder'
import { BUILDER_API_PREFIX } from './builderApi'
import { authedFetch, fetchJson } from './httpCore'

/**
 * The sixteen `/api/builder` routes plans 06, 07 and 08 add: the tool
 * catalogue and the caller's own custom HTTP tools, MCP servers and discovery,
 * and skill packs.
 *
 * A separate module from `builderApi.ts` rather than sixteen more exports on
 * it, for the reason that file gives for being separate from `StudioApi`:
 * nothing here edits a DOCUMENT. These are the caller's own stored things, and
 * a graph references them by id - so the version conflict, the export envelope
 * and the publish lifecycle that make `builderApi.ts` what it is have no
 * meaning for any of them. They ride the same `httpCore`, which is where the
 * bearer token and the single 401 retry live, and the same `BUILDER_API_PREFIX`.
 *
 * **There is no mock transport here either.** A fabricated tool catalogue would
 * offer tools the compiler has never heard of, and a fabricated skill list
 * would show an author packs they do not own - both are the silent-mock defect
 * (gotchas 2) pointed at the author's own data.
 *
 * Every function answers with the server's own sentence on a refusal. Three of
 * them matter enough to name: a **404** is absent-or-not-yours, collapsed on
 * the server so a stranger's probe learns nothing; a **409** is a name already
 * taken; and a **422** carries either a plain sentence or, for the two
 * policy refusals, an object with a `code` beside it.
 */

const TOOLS_PATH = `${BUILDER_API_PREFIX}/tools`
const CUSTOM_PATH = `${TOOLS_PATH}/custom`
const MCP_PATH = `${BUILDER_API_PREFIX}/mcp/servers`
const SKILLS_PATH = `${BUILDER_API_PREFIX}/skills`

/**
 * A refusal that carried a machine-readable code beside its sentence.
 *
 * Two routes answer this shape - a disallowed MCP transport and a skill archive
 * carrying scripts - because both are POLICY rather than validation, and a
 * panel that wants to say something specific about "this deployment is
 * remote-only" needs to recognise it without matching on prose.
 */
export class AttachmentPolicyError extends Error {
  readonly code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'AttachmentPolicyError'
    this.code = code
  }
}

/** The server's sentence, with its code when it sent one. */
async function refusal(response: Response): Promise<Error> {
  const body = await response.text().catch(() => '')
  try {
    const parsed = JSON.parse(body) as { detail?: unknown }
    const detail = parsed.detail
    if (detail && typeof detail === 'object' && 'code' in detail) {
      const row = detail as { code?: unknown; message?: unknown }
      if (typeof row.code === 'string' && row.code) {
        return new AttachmentPolicyError(row.code, String(row.message ?? row.code))
      }
    }
  } catch {
    // Not JSON, or not the coded shape. `readErrorDetail` handles both, and it
    // is what every other client in this app already shows.
  }
  let message = readErrorDetail(body, response.status)
  if (response.status === 429) message += retryAfterSentence(response.headers.get('Retry-After'))
  return new Error(message)
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authedFetch(path, init)
  if (!response.ok) throw await refusal(response)
  return (await response.json()) as T
}

/**
 * 204 with no body, so nothing is parsed. `.json()` on an empty body throws,
 * and that turns a delete that fully succeeded into an error the author would
 * retry against a row that is already gone.
 */
async function sendNoContent(path: string): Promise<void> {
  const response = await authedFetch(path, { method: 'DELETE' })
  if (response.ok) return
  throw await refusal(response)
}

const json = (body: unknown): RequestInit => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

/* --- 06: the catalogue and the caller's own tools ------------------------ */

/**
 * This deployment's builtins, then the caller's own custom tools.
 *
 * The same list `GET /api/builder/vocabulary` carries, and deliberately so: a
 * palette that has the vocabulary already needs no second request, and a panel
 * that wants the caller's own tools folded in asks here.
 */
export async function listTools(): Promise<BuilderToolCatalogueEntry[]> {
  const body = await fetchJson<{ tools: BuilderToolCatalogueEntry[] }>(TOOLS_PATH)
  return body.tools
}

export async function createCustomTool(draft: CustomToolDraft): Promise<CustomToolRow> {
  return send<CustomToolRow>(CUSTOM_PATH, { method: 'POST', ...json(draft) })
}

export async function updateCustomTool(
  id: string,
  draft: CustomToolDraft,
): Promise<CustomToolRow> {
  return send<CustomToolRow>(`${CUSTOM_PATH}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    ...json(draft),
  })
}

export async function deleteCustomTool(id: string): Promise<void> {
  return sendNoContent(`${CUSTOM_PATH}/${encodeURIComponent(id)}`)
}

/**
 * Run the call once and hand back the envelope, billed to nobody.
 *
 * It goes through the same `_run` the agent's tool would, so the SSRF refusal,
 * the redirect refusal and the response cap an author sees here are the real
 * ones rather than a preview of them.
 */
export async function testCustomTool(
  id: string,
  args: Record<string, unknown>,
): Promise<{ envelope: Record<string, unknown> }> {
  return send(`${CUSTOM_PATH}/${encodeURIComponent(id)}/test`, {
    method: 'POST',
    ...json({ args }),
  })
}

/* --- 07: MCP servers ----------------------------------------------------- */

export async function listMcpServers(): Promise<McpServerRow[]> {
  const body = await fetchJson<{ servers: McpServerRow[] }>(MCP_PATH)
  return body.servers
}

/**
 * Add a server. A transport this deployment will not dial is a 422 carrying
 * `mcp-transport-disallowed`, which is why this can throw an
 * `AttachmentPolicyError` where the other creates throw a plain one.
 */
export async function createMcpServer(draft: McpServerDraft): Promise<McpServerRow> {
  return send<McpServerRow>(MCP_PATH, { method: 'POST', ...json(draft) })
}

export async function updateMcpServer(
  id: string,
  draft: McpServerDraft,
): Promise<McpServerRow> {
  return send<McpServerRow>(`${MCP_PATH}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    ...json(draft),
  })
}

export async function deleteMcpServer(id: string): Promise<void> {
  return sendNoContent(`${MCP_PATH}/${encodeURIComponent(id)}`)
}

/**
 * Connect, list the tools, sanitise them, store them.
 *
 * **A failure is a 200 with `status: "error"` and one sentence, not a throw.**
 * The author needs the sentence in the panel; a rejected promise would put a
 * stack trace in a toast and tell them nothing they can act on. The only thing
 * that throws here is a transport failure or a 404 - the server being
 * unreachable, or the row not being theirs.
 */
export async function discoverMcpServer(id: string): Promise<McpDiscovery> {
  return send<McpDiscovery>(`${MCP_PATH}/${encodeURIComponent(id)}/discover`, {
    method: 'POST',
  })
}

/* --- 08: skill packs ----------------------------------------------------- */

/** The four built-ins, then the caller's own. Built-ins first: a fresh account
 * has nothing else, and a palette whose first row is empty teaches an author
 * that the feature is empty. */
export async function listSkills(): Promise<SkillSummary[]> {
  const body = await fetchJson<{ skills: SkillSummary[] }>(SKILLS_PATH)
  return body.skills
}

/** One pack WITH its `SKILL.md` text. */
export async function getSkill(id: string): Promise<SkillDetail> {
  return fetchJson<SkillDetail>(`${SKILLS_PATH}/${encodeURIComponent(id)}`)
}

export async function createSkill(body: string): Promise<SkillDetail> {
  return send<SkillDetail>(SKILLS_PATH, { method: 'POST', ...json({ body }) })
}

/** A `PUT` bumps `metadata.version` in the file, which is where a version lives. */
export async function updateSkill(id: string, body: string): Promise<SkillDetail> {
  return send<SkillDetail>(`${SKILLS_PATH}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    ...json({ body }),
  })
}

export async function deleteSkill(id: string): Promise<void> {
  return sendNoContent(`${SKILLS_PATH}/${encodeURIComponent(id)}`)
}

/**
 * Import a pack from a zip holding one `SKILL.md`.
 *
 * Sent as a raw `application/zip` body rather than multipart. The server takes
 * both; this is the shorter one and it needs no `FormData`, which jsdom
 * implements unevenly. An archive carrying a `scripts/` entry is refused with
 * `skill-contains-scripts` - a nested `code`, so this can throw an
 * `AttachmentPolicyError` the panel recognises.
 */
export async function importSkill(archive: Blob): Promise<SkillDetail> {
  return send<SkillDetail>(`${SKILLS_PATH}/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/zip' },
    body: archive,
  })
}

/**
 * What the three panels depend on, and nothing else.
 *
 * The narrow surface `CredentialApiLike` already establishes: a spec hands a
 * component a double checked by the compiler against exactly the calls it
 * stands in for, so a double that has quietly stopped matching its subject is
 * a type error rather than a green test.
 */
export interface AttachmentsApiLike {
  listTools: typeof listTools
  createCustomTool: typeof createCustomTool
  updateCustomTool: typeof updateCustomTool
  deleteCustomTool: typeof deleteCustomTool
  testCustomTool: typeof testCustomTool
  listMcpServers: typeof listMcpServers
  createMcpServer: typeof createMcpServer
  updateMcpServer: typeof updateMcpServer
  deleteMcpServer: typeof deleteMcpServer
  discoverMcpServer: typeof discoverMcpServer
  listSkills: typeof listSkills
  getSkill: typeof getSkill
  createSkill: typeof createSkill
  updateSkill: typeof updateSkill
  deleteSkill: typeof deleteSkill
  importSkill: typeof importSkill
}

export const attachmentsApi: AttachmentsApiLike = {
  listTools,
  createCustomTool,
  updateCustomTool,
  deleteCustomTool,
  testCustomTool,
  listMcpServers,
  createMcpServer,
  updateMcpServer,
  deleteMcpServer,
  discoverMcpServer,
  listSkills,
  getSkill,
  createSkill,
  updateSkill,
  deleteSkill,
  importSkill,
}
