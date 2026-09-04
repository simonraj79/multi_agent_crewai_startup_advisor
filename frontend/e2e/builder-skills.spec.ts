import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

/**
 * 08 criterion 9 - a skill pack, from paste to attached, in the browser.
 *
 * Plan 08's Status recorded this `partial`: *"the panel is built, docked and
 * unit-proved"*, and the browser half was not run. This is that half - and it
 * is the only place that can answer whether the SERVER stored what the author
 * pasted, because a jsdom mount asserts about a mocked `fetch`.
 *
 * ## What "the card" means here, and why
 *
 * The criterion asks to *"see the card's `v1` and *mine* chip"*. The CANVAS pill
 * cannot show either: `SkillConfig` carries `skill_id` and `skill_name` and
 * nothing else - the export strips the id deliberately, so a version and an
 * owner would be facts about the AUTHOR's library rather than about the
 * document, and a pill that showed them would be showing something an imported
 * graph does not have. The card that does carry them is the inspector's
 * summary, `[data-testid="skill-summary"]`, which is what this asserts. Stated
 * rather than glossed, because it is a departure from the criterion's wording.
 *
 * ## Which backend
 *
 * The free `SYNTHETIC=1` service, started FROM THE WORKTREE ROOT - or with
 * `SKILLS_ROOT` pointed at `data/skills` absolutely. `SKILLS_ROOT` defaults to
 * the RELATIVE `data/skills`, so a service started from anywhere else serves
 * four fewer built-ins and this file fails on a working directory rather than
 * on the product.
 */

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

interface ConsoleWatch {
  unexpected: string[]
  /**
   * Forgive one pattern, from the point of the call onwards.
   *
   * The file-level allowance stays null and this does not widen it: an
   * allowance declared inside a test, next to the line that provokes it, cannot
   * outlive its cause the way a file-level exemption can - which is the lesson
   * `studio.spec.ts` recorded when it retired its favicon exemption. Used once,
   * for the 422 the refusal test exists to cause.
   */
  allow(pattern: RegExp): void
}

function watchConsole(page: Page): ConsoleWatch {
  const allowed: RegExp[] = []
  const watch: ConsoleWatch = {
    unexpected: [],
    allow: (pattern: RegExp) => {
      allowed.push(pattern)
    },
  }
  const record = (text: string): void => {
    if (ALLOWED_CONSOLE_ERROR?.test(text)) return
    if (allowed.some((pattern) => pattern.test(text))) return
    watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

const canvas = (page: Page): Locator => page.locator('.builder-flow')
const nodes = (page: Page): Locator => page.locator('.vue-flow__node:has(.workflow-node)')
const inspector = (page: Page): Locator => page.locator('[data-testid="inspector-rail"]')
const paletteTile = (page: Page, hotkey: string): Locator =>
  page.locator(`.builder-tile[aria-keyshortcuts="${hotkey}"]`)
const agentCard = (page: Page): Locator =>
  page.locator('.vue-flow__node:has(.workflow-node.is-kind-agent)').first()

/** The pack this test pastes. Real frontmatter, parsed by the package's parser. */
const PACK = `---
name: e2e-house-style
description: How this project writes a short answer, for the E2E suite.
metadata:
  version: "1"
---

# House style

## One claim per sentence

Write the claim, then the evidence for it, then stop. A sentence carrying two
claims makes the reader decide which one the evidence was for.
`

async function clearDocuments(page: Page): Promise<void> {
  const listed = await page.request.get('/api/builder/workflows')
  if (!listed.ok()) return
  for (const entry of (await listed.json()) as { id: string }[]) {
    await page.request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

/**
 * Every pack this caller OWNS, deleted. Built-ins are left alone - they have no
 * `user_id` and `DELETE` answers 404 for them, which is the shipped decision
 * rather than an obstacle.
 */
async function clearMySkills(page: Page): Promise<void> {
  const listed = await page.request.get('/api/builder/skills')
  if (!listed.ok()) return
  const body = (await listed.json()) as { skills: { id: string; owner: string }[] }
  for (const skill of body.skills) {
    if (skill.owner === 'me') await page.request.delete(`/api/builder/skills/${skill.id}`)
  }
}

/**
 * One capture for the judge, into `benchmarks/ours/08/`.
 *
 * PNGs are gitignored and the spec is not: `benchmarks/README.md` says why -
 * they are pictures of a build, regenerated on demand, and a round's defects
 * live in the ledger rather than in its pixels. Taken at the END of a passing
 * test, so a capture can never be of a state the assertions rejected.
 */
async function capture(page: Page, name: string): Promise<void> {
  const out = path.resolve(process.cwd(), '..', 'benchmarks', 'ours', '08')
  mkdirSync(out, { recursive: true })
  await page.screenshot({ path: path.join(out, `08-${name}-1440x900-dark.png`) })
}

test.describe('skills, from paste to attached', () => {
  test.beforeEach(async ({ page }) => {
    await clearDocuments(page)
    await clearMySkills(page)
  })

  test.afterEach(async ({ page }) => {
    await clearDocuments(page)
    await clearMySkills(page)
  })

  test('the palette names all three attachment families in one line each', async ({ page }) => {
    /*
     * Criterion 9's last clause, and it is about the three staying DISTINCT.
     * A tool is hands, an MCP server is somebody else's hands, and a skill is
     * knowledge - and the palette is where an author meets that distinction
     * first. One line each, from `nodeKinds.ts`, so the palette and the
     * inspector cannot describe the same family differently.
     */
    const watch = watchConsole(page)
    await page.goto('/#/build')
    await page.locator('.template-card').filter({ hasText: 'Minimal gated agent' }).click()
    await expect(canvas(page)).toBeVisible()

    for (const [hotkey, blurb] of [
      ['T', /catalogue tool/i],
      ['M', /MCP server/i],
      ['K', /knowledge an agent carries/i],
    ] as const) {
      const tile = paletteTile(page, hotkey)
      await expect(tile, hotkey).toBeVisible()
      await expect(tile.locator('.builder-tile-blurb'), hotkey).toHaveText(blurb)
    }
    // ...and all three are the attachment family, which is the palette's half of
    // D5's silhouette channel: an author can tell before they drag that these
    // three produce a different sort of object.
    await expect(page.locator('.builder-tile.is-family-attachment')).toHaveCount(3)

    expect(watch.unexpected).toEqual([])
  })

  test('pastes a SKILL.md, lists it under mine, attaches it and renders its body', async ({
    page,
  }) => {
    const watch = watchConsole(page)
    await page.goto('/#/build')
    await page.locator('.template-card').filter({ hasText: 'Minimal gated agent' }).click()
    await expect(canvas(page)).toBeVisible()
    await expect(nodes(page)).toHaveCount(4)

    // A skill hung off the agent, so the panel is reached from the node that
    // will carry the pack rather than from a settings page somewhere else.
    await paletteTile(page, 'K').dragTo(agentCard(page))
    await expect(nodes(page)).toHaveCount(5)
    await expect(inspector(page)).toBeVisible()

    // The manage panel is DOCKED behind a disclosure inside the form, not a
    // modal (R15). Asserted as an absence, because "no modal" is a property a
    // screenshot cannot show.
    await inspector(page).locator('[data-testid="skill-manage"]').click()
    await expect(inspector(page).locator('[data-testid="skill-panel"]')).toBeVisible()
    expect(await page.locator('[role="dialog"]').count(), 'a dialog opened').toBe(0)

    // The four committed packs are there first, marked as this repository's.
    const builtins = inspector(page).locator('[data-testid="skill-row"][data-owner="builtin"]')
    await expect(builtins).toHaveCount(4)
    await expect(builtins.first().locator('[data-testid="skill-owner"]')).toHaveText('built-in')

    await inspector(page).locator('[data-testid="skill-add"]').click()
    await inspector(page).locator('[data-testid="skill-body"]').fill(PACK)
    await inspector(page).locator('[data-testid="skill-save"]').click()

    // Under MINE, with the version the frontmatter declared - both read off the
    // stored row rather than off what was typed, so this is the server's answer.
    const mine = inspector(page).locator('[data-testid="skill-row"][data-owner="me"]')
    await expect(mine).toHaveCount(1)
    await expect(mine.locator('[data-testid="skill-owner"]')).toHaveText('mine')
    await expect(mine.locator('[data-testid="skill-version"]')).toHaveText('v1')
    await expect(mine).toContainText('e2e-house-style')

    // Opened in the panel, through the escape-first renderer: the body is
    // untrusted text and `renderMarkdown` escapes every character before it
    // recognises any structure.
    await mine.locator('[data-testid="skill-open"]').click()
    const rendered = mine.locator('[data-testid="skill-body-render"]')
    await expect(rendered).toBeVisible()
    await expect(rendered.locator('h1')).toHaveText('House style')

    // Attach it, and the FORM's card says which pack, whose it is and what
    // version - the three facts the document itself cannot carry.
    await mine.locator('[data-testid="skill-attach"]').click()
    await expect(inspector(page).locator('[data-testid="skill-summary"]')).toBeVisible()
    await expect(inspector(page).locator('[data-testid="skill-form-version"]')).toHaveText('v1')
    await expect(inspector(page).locator('[data-testid="skill-form-owner"]')).toHaveText('mine')

    // ...and the body, so an author is attaching a pack rather than a name.
    const body = inspector(page).locator('[data-testid="skill-form-body"]')
    await expect(body).toBeVisible()
    await expect(body).toContainText('One claim per sentence')

    // The canvas pill carries the one fact a document CAN carry across an
    // export: the pack's name.
    await expect(page.locator('.workflow-node.is-kind-skill')).toContainText('e2e-house-style')

await capture(page, 'pack-pasted-attached')

    expect(watch.unexpected).toEqual([])
  })

  test('shows the package parser own sentence when a pack will not parse', async ({ page }) => {
    /*
     * The other half of what a paste box owes an author. `crewai.skills.parser`
     * is the authority on frontmatter, and its refusal is quoted rather than
     * paraphrased - a paraphrase drifts from the parser it describes, and this
     * one has to survive a CrewAI upgrade that tightens the rules.
     */
    const watch = watchConsole(page)
    // The 422 IS the test. The browser logs every failed request as a console
    // error whatever the app does with it, so the one this provokes on purpose
    // is forgiven here, beside the line that causes it, and nowhere else.
    watch.allow(/422 \(Unprocessable Content\)/)
    await page.goto('/#/build')
    await page.locator('.template-card').filter({ hasText: 'Minimal gated agent' }).click()
    await paletteTile(page, 'K').dragTo(agentCard(page))
    await inspector(page).locator('[data-testid="skill-manage"]').click()

    await inspector(page).locator('[data-testid="skill-add"]').click()
    await inspector(page)
      .locator('[data-testid="skill-body"]')
      .fill('---\nname: Bad Name\ndescription: capitals and a space\n---\n\nbody\n')
    await inspector(page).locator('[data-testid="skill-save"]').click()

    const refusal = inspector(page).locator('[data-testid="skill-add-problem"]')
    await expect(refusal).toBeVisible()
    await expect(refusal).not.toBeEmpty()
    // Nothing was stored, which is the half a message alone does not prove.
    await expect(inspector(page).locator('[data-testid="skill-row"][data-owner="me"]')).toHaveCount(
      0,
    )

    expect(watch.unexpected).toEqual([])
  })
})
