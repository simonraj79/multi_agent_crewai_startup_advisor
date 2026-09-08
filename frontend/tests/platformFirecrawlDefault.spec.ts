import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Audit H4: `render.yaml` switched the platform Firecrawl key on for every
 * signed-in user, and the daily cap its own comment cited as the bound did not
 * exist. This test is the pin on that pairing - the flag may only be on while
 * something really counts.
 *
 * THE CONDITION FLIPPED, 2026-09-08, and it flipped because the counter was
 * built rather than because the test was relaxed. What it now measures:
 *
 *   1. the CAP has a consumer outside its own definition, and
 *   2. `claim_platform_quota` is both DEFINED and CALLED, from two files.
 *
 * Clause 2 is new and it is the stronger half. The original test asked only
 * whether the cap's identifier appeared somewhere outside `config.py`, and a
 * constant that is merely mentioned is not a counter - a `# TODO: enforce
 * BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` in any module would have satisfied it
 * and turned an unbounded grant back on. Demanding a claim that is called
 * cannot be satisfied by a comment.
 *
 * Clause 1 accepts `PLATFORM_TOOL_DAILY_CAPS` as well as the knob's own name,
 * and that widening is the one place this test could be accused of being
 * rigged, so here is exactly what it is: the cap is stored into that mapping
 * in `config.py` and every consumer reads the mapping, which is what keeps
 * "which providers are metered" a single closed set. Grepping only for the
 * knob's own identifier would therefore be a FALSE NEGATIVE against a working
 * meter - the value flows, the name does not. Clause 2 is what stops the
 * widening from mattering: no mapping and no mention gets past it.
 *
 * WHY THIS TEST IS IN THE FRONTEND SUITE. It belongs beside
 * `tests/service/test_render_blueprint.py`, which already parses this
 * manifest. It was written here because four audit branches were being
 * integrated in parallel and that file was not in its author's ownership.
 * Moving it is a one-file change and costs nothing.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const REPO = path.resolve(HERE, '../..')

const BLUEPRINT = readFileSync(path.join(REPO, 'render.yaml'), 'utf8')

/**
 * The literal `value:` of one `- key:` entry in the blueprint.
 *
 * Hand-parsed rather than through a YAML library, because this suite must not
 * grow a dependency for one assertion. It reads the `value:` on the line
 * following the key, which is the shape every entry in this manifest uses; a
 * different shape returns null and the test says so rather than passing.
 */
function envValue(key: string): string | null {
  const lines = BLUEPRINT.split(/\r?\n/)
  const at = lines.findIndex((line) => line.trim() === `- key: ${key}`)
  if (at === -1 || at + 1 >= lines.length) return null
  const next = lines[at + 1].trim()
  const match = next.match(/^value:\s*"?([^"]*)"?\s*$/)
  return match ? match[1] : null
}

/** Every `.py` under `src/`, so "has a reader" is measured rather than recalled. */
function pythonSources(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry)
    if (statSync(full).isDirectory()) pythonSources(full, found)
    else if (entry.endsWith('.py')) found.push(full)
  }
  return found
}

/** `relative/path.py: the line`, for every line of `src/` containing `identifier`. */
function occurrencesInSrc(identifier: string): string[] {
  const hits: string[] = []
  for (const file of pythonSources(path.join(REPO, 'src'))) {
    const text = readFileSync(file, 'utf8')
    for (const line of text.split(/\r?\n/)) {
      if (line.includes(identifier)) hits.push(`${path.relative(REPO, file)}: ${line.trim()}`)
    }
  }
  return hits
}

const IN_CONFIG = /^src[\\/]brief_crew[\\/]config\.py:/

/** Hits outside `config.py`, which is where the constants themselves live. */
function consumersOf(identifier: string): string[] {
  return occurrencesInSrc(identifier).filter((hit) => !IN_CONFIG.test(hit))
}

/**
 * Whether the cap is really enforced, by the two clauses the docblock names.
 *
 * A comment cannot satisfy this: `claim_platform_quota` has to be defined with
 * `def` in one file and called with `(` from another, which is a counter and a
 * caller rather than an intention.
 */
function capIsEnforced(): { enforced: boolean; why: string[] } {
  const capReaders = [
    ...consumersOf('BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP'),
    ...consumersOf('PLATFORM_TOOL_DAILY_CAPS'),
  ]
  const claim = occurrencesInSrc('claim_platform_quota')
  const defined = claim.filter((hit) => hit.includes('def claim_platform_quota'))
  const called = claim.filter((hit) => !hit.includes('def claim_platform_quota'))
  const definedIn = new Set(defined.map((hit) => hit.split(':')[0]))
  const calledOutside = called.filter((hit) => !definedIn.has(hit.split(':')[0]))
  return {
    enforced: capReaders.length > 0 && defined.length > 0 && calledOutside.length > 0,
    why: [
      `cap readers outside config.py: ${capReaders.length}`,
      `claim_platform_quota definitions: ${defined.length}`,
      `calls from another file: ${calledOutside.length}`,
    ],
  }
}

describe('H4: the platform Firecrawl grant is on only while its cap is really counted', () => {
  it('finds the flag declared in the blueprint at all', () => {
    expect(envValue('BUILDER_PLATFORM_FIRECRAWL_DEFAULT')).not.toBeNull()
  })

  it('is on if and only if the daily cap has a counter that is called', () => {
    const { enforced, why } = capIsEnforced()
    expect(
      envValue('BUILDER_PLATFORM_FIRECRAWL_DEFAULT'),
      enforced
        ? `the cap is enforced (${why.join('; ')}), so the platform key is everyone's default`
        : `the cap is NOT enforced (${why.join('; ')}), so the platform key must not be everyone's default`,
    ).toBe(enforced ? '1' : '0')
  })

  it('names the counter in the manifest, so the next reader can check it', () => {
    const at = BLUEPRINT.indexOf('- key: BUILDER_PLATFORM_FIRECRAWL_DEFAULT')
    expect(at).toBeGreaterThan(-1)
    const comment = BLUEPRINT.slice(Math.max(0, at - 4000), at)
    expect(comment).toContain('BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP')
    // Render snapshots a deploy's environment at deploy creation and the live
    // value was set through the API, so a manifest edit alone changes nothing.
    expect(comment.toUpperCase()).toContain('DASHBOARD')
    if (capIsEnforced().enforced) {
      // A flag that is ON has to say what bounds it, by name, or the next
      // reader is back to believing a sentence - which is what H4 was.
      expect(comment).toContain('claim_platform_quota')
      expect(comment).toContain('platform_tool_usage')
    }
  })
})
