import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Audit L4: every `uses:` in the CI workflow named a mutable tag.
 *
 * A tag is a pointer somebody else controls. `actions/checkout@v4` is whatever
 * that repository decides `v4` means at the moment a runner fetches it, and
 * `astral-sh/setup-uv` is a third party besides. This workflow holds no secret
 * and runs with `contents: read`, so a moved tag poisons a build rather than
 * leaking a credential - but the green tick on that build is the only evidence
 * anybody has that the suite passes on a clean checkout with no keys, which is
 * a claim the README makes in public.
 *
 * WHY THIS TEST IS IN THE FRONTEND SUITE: the same ownership reason as
 * `platformFirecrawlDefault.spec.ts`. Four branches are being integrated in
 * parallel and the Python suite is not this change's to touch; moving it later
 * is a one-file change.
 */

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'))
const REPO = path.resolve(HERE, '../..')

const WORKFLOW = readFileSync(path.join(REPO, '.github/workflows/ci.yml'), 'utf8')
const WORKFLOW_LINES = WORKFLOW.split(/\r?\n/)

/** Every `uses:` line, without its indentation. */
const USES = WORKFLOW_LINES.map((line) => line.trim()).filter((line) => line.startsWith('uses:'))

describe('L4: every action is pinned to a commit SHA', () => {
  it('finds the workflow and its steps at all', () => {
    // A test that silently found nothing would pass over a deleted workflow,
    // which is gotcha 20's failure mode.
    expect(USES.length).toBeGreaterThanOrEqual(8)
  })

  it('names a 40-character SHA rather than a tag, everywhere', () => {
    for (const line of USES) {
      expect(line, line).toMatch(/^uses: [\w.-]+\/[\w.-]+@[0-9a-f]{40}\b/)
    }
  })

  it('carries the version each SHA was resolved from, in a trailing comment', () => {
    // Without this a reader cannot tell v4.4.0 from v4.0.0 without a network
    // call, and Dependabot rewrites the comment with the SHA, so the two
    // cannot drift.
    for (const line of USES) {
      expect(line, line).toMatch(/@[0-9a-f]{40}\s+#\s*v\d+\.\d+(\.\d+)?/)
    }
  })

  it('does not persist the job token into .git/config on any checkout', () => {
    // actions/checkout writes GITHUB_TOKEN into .git/config as an
    // http.extraheader by default, where every later step can read it. Nothing
    // in this workflow pushes, tags or calls the API.
    const checkouts = WORKFLOW_LINES.map((line, index) => ({ line: line.trim(), index }))
      .filter(({ line }) => line.startsWith('uses: actions/checkout@'))
    expect(checkouts.length).toBeGreaterThan(0)
    for (const { index } of checkouts) {
      const following = WORKFLOW_LINES.slice(index + 1, index + 4).map((line) => line.trim())
      expect(following, `checkout at line ${index + 1}`).toContain('persist-credentials: false')
    }
  })
})

describe('L4: a pin without an update channel is a decision to never update', () => {
  const CONFIG = path.join(REPO, '.github/dependabot.yml')

  it('declares a Dependabot configuration', () => {
    expect(existsSync(CONFIG)).toBe(true)
  })

  it('covers the three ecosystems this repository actually has, weekly', () => {
    const text = readFileSync(CONFIG, 'utf8')
    for (const ecosystem of ['github-actions', 'pip', 'npm']) {
      expect(text, ecosystem).toContain(`package-ecosystem: ${ecosystem}`)
    }
    // One `interval:` per ecosystem and all of them weekly.
    const intervals = text.split(/\r?\n/).map((line) => line.trim()).filter((line) => line.startsWith('interval:'))
    expect(intervals).toEqual(['interval: weekly', 'interval: weekly', 'interval: weekly'])
  })

  it('points npm at frontend/, which is the only package.json in the repository', () => {
    const text = readFileSync(CONFIG, 'utf8')
    const npmAt = text.indexOf('package-ecosystem: npm')
    expect(npmAt).toBeGreaterThan(-1)
    expect(text.slice(npmAt, npmAt + 200)).toContain('directory: "/frontend"')
    expect(existsSync(path.join(REPO, 'frontend/package.json'))).toBe(true)
    expect(existsSync(path.join(REPO, 'package.json'))).toBe(false)
  })
})
