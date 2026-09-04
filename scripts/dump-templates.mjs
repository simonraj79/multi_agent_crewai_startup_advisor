/**
 * Write every gallery template out exactly as the frontend would POST it.
 *
 *     node scripts/dump-templates.mjs
 *     node scripts/dump-templates.mjs --check
 *
 * WHY THIS EXISTS. The template documents are TypeScript, and the thing that
 * proves a template is a template - `validate_document` and `estimate_budget` -
 * is Python. Something has to carry a document across that line, and the two
 * obvious answers are both worse than this one: writing the documents twice
 * makes a template a thing that can disagree with itself, and having Python
 * shell out to node inside a unit test makes the Python CI job depend on
 * `frontend/node_modules`, which it does not have.
 *
 * So this script is the bridge, and its output is COMMITTED:
 * `frontend/tests/fixtures/templates/documents.json` is the four-plus-four
 * documents in `forValidate` form, and it is what
 * `scripts/emit_builder_fixtures.py --target templates` reads.
 *
 * BOTH ENDS OF THE BRIDGE ARE GATED, which is the only thing that makes a
 * committed intermediate honest:
 *
 *   frontend/tests/templates.spec.ts     TypeScript === documents.json
 *   tests/builder/test_client_fixtures.py  fixtures === regenerate(documents.json)
 *
 * Edit a template and forget to run this, and the Vitest side goes red naming
 * this command. Run it and forget the Python emitter, and the Python side goes
 * red naming that one. Neither can be satisfied by the other.
 *
 * NO NEW DEPENDENCY, deliberately. Node 24 strips TypeScript types natively, so
 * the only thing missing is that the app's imports are extensionless - which a
 * six-line resolve hook supplies. `tsx`, `vite-node` and a Vite SSR server were
 * all considered and all of them are a package install to run a script that
 * reads two modules.
 *
 * MODEL ROLES ARE RESOLVED HERE, against the committed
 * `frontend/tests/fixtures/models.json` rather than against a live roster: the
 * fixture is itself generated from `config.MODEL_REGISTRY` and byte-compared,
 * so resolving against it is resolving against the server, and the dump does
 * not need a running service to be reproducible.
 */

import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(HERE, '..')
const FRONTEND = path.join(REPO, 'frontend')
const OUT = path.join(FRONTEND, 'tests', 'fixtures', 'templates', 'documents.json')
const RESOLVER = path.join(HERE, 'ts-extension-resolver.mjs')

/**
 * Re-exec under the resolve hook when we are not already running with it.
 *
 * `module.register` cannot be called after the importing module graph has been
 * loaded, so the hook has to be installed before the first `import` of a `.ts`
 * file - which means before this file's own top-level await. Re-running the
 * script with `--import` is the least surprising way to get that, and it keeps
 * the invocation a plain `node scripts/dump-templates.mjs`.
 */
if (!process.env.BUILDER_TEMPLATE_DUMP_HOOKED) {
  const result = execFileSync(
    process.execPath,
    ['--import', pathToFileURL(RESOLVER).href, fileURLToPath(import.meta.url), ...process.argv.slice(2)],
    { env: { ...process.env, BUILDER_TEMPLATE_DUMP_HOOKED: '1' }, stdio: 'inherit' },
  )
  void result
  process.exit(0)
}

const templates = await import(
  pathToFileURL(path.join(FRONTEND, 'src', 'data', 'builderTemplates.ts')).href
)
const serialize = await import(
  pathToFileURL(path.join(FRONTEND, 'src', 'utils', 'builderSerialize.ts')).href
)
const modelRoster = await import(
  pathToFileURL(path.join(FRONTEND, 'src', 'data', 'modelRoster.ts')).href
)
const roles = await import(
  pathToFileURL(path.join(FRONTEND, 'src', 'data', 'templates', 'modelRoles.ts')).href
)

const rosterPath = path.join(FRONTEND, 'tests', 'fixtures', 'models.json')
const roster = JSON.parse(readFileSync(rosterPath, 'utf8'))
// The module singleton the app fills from `GET /api/builder/models`. Set here
// so `documentFromTemplate` resolves exactly as it does in a browser.
modelRoster.roster.value = roster

const resolved = roles.resolvedRoles(roster)
for (const [role, id] of Object.entries(resolved)) {
  if (!id) throw new Error(`the committed roster answers no model for the ${role} role`)
}

const payload = {
  _source: 'scripts/dump-templates.mjs, from frontend/src/data/builderTemplates.ts',
  schema: 'builder.templates/v1',
  // What each role token resolved to, recorded so the Python side can assert
  // the two halves agree rather than merely both existing.
  roles: resolved,
  order: templates.BUILDER_TEMPLATES.map((entry) => entry.id),
  more: templates.MORE_BUILDER_TEMPLATES.map((entry) => entry.id),
  documents: Object.fromEntries(
    templates.ALL_BUILDER_TEMPLATES.map((entry) => [
      entry.id,
      serialize.forValidate(templates.documentFromTemplate(entry)),
    ]),
  ),
  cards: Object.fromEntries(
    templates.ALL_BUILDER_TEMPLATES.map((entry) => [
      entry.id,
      {
        title: entry.title,
        blurb: entry.blurb,
        teaches: entry.teaches,
        modifyFirst: entry.modifyFirst,
        caveat: entry.caveat ?? null,
      },
    ]),
  ),
}

// LF and a trailing newline, always. `core.autocrlf` is true here, so a byte
// comparison against the checkout would otherwise report the platform rather
// than the drift - the rule `emit_builder_fixtures.py` already states.
const rendered = `${JSON.stringify(payload, null, 2)}\n`.replace(/\r\n/g, '\n')

if (process.argv.includes('--check')) {
  let current = ''
  try {
    current = readFileSync(OUT, 'utf8').replace(/\r\n/g, '\n')
  } catch {
    current = ''
  }
  if (current !== rendered) {
    console.error(
      `${path.relative(REPO, OUT)} is stale. Regenerate with:\n` +
        '    node scripts/dump-templates.mjs',
    )
    process.exit(1)
  }
  console.log(`${path.relative(REPO, OUT)} is current`)
  process.exit(0)
}

mkdirSync(path.dirname(OUT), { recursive: true })
writeFileSync(OUT, rendered, 'utf8')
console.log(`wrote ${path.relative(REPO, OUT)} (${payload.order.length + payload.more.length} templates)`)
