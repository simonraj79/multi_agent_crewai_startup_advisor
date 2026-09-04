import type { CredentialKind } from '../types/builder'

/**
 * Which fields each credential kind needs, and what to call the kind.
 *
 * THIS IS A MIRROR of `config.CREDENTIAL_FIELDS` (`src/brief_crew/config.py`),
 * restated here because the create form has to render the right inputs before
 * anything is posted, and the server's answer to a wrong shape is a 422 about a
 * field the author never saw. Spec R7 admits a client mirror only when a
 * Python-generated fixture pins it and a Python test asserts the fixture is
 * fresh - the way `builderProblemCodes.json` and `builderBackEdges.json` are.
 * That generator is not built here: `tests/credentialPicker.spec.ts` reads
 * `config.py` at run time and asserts every kind and field below agrees, which
 * is the `serverLimits.ts` idiom and enough to turn a drift into a failing test
 * rather than a surprising 422. Whether to promote it to a generated fixture
 * is the Integrator's call.
 *
 * `secret` names the fields that are credentials rather than names: an
 * `http_header` has a `name` that is fine to see and a `header_value` that is
 * not.
 * The form renders a secret field as `type="password"`, which is a courtesy
 * to whoever is looking over the author's shoulder and nothing more - the
 * value goes to the server in the POST body and is never read back.
 */
export interface CredentialKindSpec {
  /** What the picker calls it. */
  label: string
  /** `config.CREDENTIAL_FIELDS[kind]`, in the server's order. */
  fields: readonly string[]
  /** The subset of `fields` that is a secret. */
  secret: readonly string[]
}

export const CREDENTIAL_KINDS: Record<CredentialKind, CredentialKindSpec> = {
  openrouter: { label: 'OpenRouter', fields: ['api_key'], secret: ['api_key'] },
  firecrawl: { label: 'Firecrawl', fields: ['api_key'], secret: ['api_key'] },
  serper: { label: 'Serper', fields: ['api_key'], secret: ['api_key'] },
  tavily: { label: 'Tavily', fields: ['api_key'], secret: ['api_key'] },
  exa: { label: 'Exa', fields: ['api_key'], secret: ['api_key'] },
  brave: { label: 'Brave Search', fields: ['api_key'], secret: ['api_key'] },
  github: { label: 'GitHub', fields: ['token'], secret: ['token'] },
  postgres: { label: 'PostgreSQL', fields: ['dsn'], secret: ['dsn'] },
  // `header_value`, not `value`: the server renamed the secret half so that
  // `events/redaction.py` covers it by name (D-01-6). Mirrored here because
  // this file IS the mirror; `credentialPicker.spec.ts` reads `config.py` and
  // fails if the two ever part company.
  http_header: { label: 'HTTP header', fields: ['name', 'header_value'], secret: ['header_value'] },
  mcp_header: { label: 'MCP header', fields: ['name', 'header_value'], secret: ['header_value'] },
  e2b: { label: 'E2B', fields: ['api_key'], secret: ['api_key'] },
}

/** The kinds in `config.py`'s own order. */
export const CREDENTIAL_KIND_ORDER = Object.keys(CREDENTIAL_KINDS) as CredentialKind[]

/** How a field is captioned on the form: `api_key` -> `API key`. */
export function fieldLabel(field: string): string {
  const named: Record<string, string> = {
    api_key: 'API key',
    token: 'Token',
    dsn: 'Connection string',
    name: 'Header name',
    header_value: 'Header value',
  }
  return named[field] ?? field.replaceAll('_', ' ')
}
