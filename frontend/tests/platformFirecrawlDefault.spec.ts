import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Audit H4: `render.yaml` switched the platform Firecrawl key on for every
 * signed-in user, and the daily cap its own comment cited as the bound does
 * not exist.
 *
 * `BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` has exactly one occurrence in the
 * Python package - its own definition in `config.py`. No counter, no store, no
 * UTC reset. With `BUILDER_PLATFORM_FIRECRAWL_DEFAULT` on, an agent node
 * carrying `research_market_landscape` and no credential of its own scrapes on
 * the owner's Firecrawl account, and neither spend cap can see it:
 * `MAX_RUN_COST_USD` and `USER_SPEND_CAP_USD` are computed from LLM token
 * events, and a Firecrawl call raises none.
 *
 * WHY THIS TEST IS IN THE FRONTEND SUITE. It belongs beside
 * `tests/service/test_render_blueprint.py`, which already parses this
 * manifest. That file is not in this change's ownership, and four branches are
 * being integrated in parallel, so the test is written where it cannot
 * collide. Moving it is a one-file change and costs nothing.
 *
 * The assertion is CONDITIONAL on purpose: it demands "0" only while the cap
 * has no reader. Build the counter and this test stops objecting, which is the
 * only way a security default that exists to be lifted should be pinned.
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

describe('H4: the platform Firecrawl grant is off while its cap is a constant nobody reads', () => {
  it('finds the flag declared in the blueprint at all', () => {
    expect(envValue('BUILDER_PLATFORM_FIRECRAWL_DEFAULT')).not.toBeNull()
  })

  it('is off while BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP has no consumer', () => {
    const readers = occurrencesInSrc('BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP')
    // Its own definition spans two lines in config.py, so "no consumer" is
    // "every occurrence is in config.py", not "at most one line".
    const outsideConfig = readers.filter((hit) => !hit.startsWith('src\\brief_crew\\config.py') && !hit.startsWith('src/brief_crew/config.py'))
    if (outsideConfig.length > 0) {
      // Somebody built the counter. This test has done its job; flipping the
      // flag back on is now a decision rather than an unbounded grant.
      expect(outsideConfig.length).toBeGreaterThan(0)
      return
    }
    expect(
      envValue('BUILDER_PLATFORM_FIRECRAWL_DEFAULT'),
      'the cap has no reader outside its own definition, so the platform key must not be everyone\'s default',
    ).toBe('0')
  })

  it('still says in the manifest why it is off, so the next reader does not flip it back', () => {
    const at = BLUEPRINT.indexOf('- key: BUILDER_PLATFORM_FIRECRAWL_DEFAULT')
    expect(at).toBeGreaterThan(-1)
    const comment = BLUEPRINT.slice(Math.max(0, at - 2400), at)
    expect(comment).toContain('BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP')
    // Render snapshots a deploy's environment at deploy creation and the live
    // value was set through the API, so a manifest edit alone changes nothing.
    expect(comment.toUpperCase()).toContain('DASHBOARD')
  })
})
