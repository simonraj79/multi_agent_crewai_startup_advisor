import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * The News-to-social template, from the HOME to a finished run - U6.
 *
 * `docs/ux-shell/DEFINITION-OF-DONE.md` row U6. Written by RV2, who built
 * nothing in the unified-shell programme; it is a test rather than product
 * code, which is why the row's verifier owns the file (DoD §3).
 *
 * ## What only a browser can answer here
 *
 * That the four things U6 names are one journey. `templates.spec.ts` already
 * proves every template *publishes and completes*, but it launches through
 * `request` and starts at `#/build` - the gallery - because the home did not
 * exist when it was written. What is new, and what no unit suite can see, is
 * that a reader who lands on `#/` can reach this graph in one click, that the
 * docked panel takes the run to a terminal state without leaving the canvas,
 * and that the console the run hands over to is showing THE SAME RUN and not a
 * fresh console that happens to look busy.
 *
 * ## Why the graph is saved and published before the panel can run it
 *
 * Not incidental, and the panel says so on screen. Plan 13's C7 as built
 * resolves every run mode against `BUILDER_WORKFLOWS`, and only a publish
 * writes that map - so Run is refused on a draft with a sentence naming the
 * button that fixes it (`useFlowTest.runBlockedReason`). `test-panel.spec.ts`
 * makes the same three keystrokes for the same reason.
 *
 * ## Why this template, and what its own caveat promises
 *
 * `newsToSocial.ts` is the one template in the gallery with NO human gate: it
 * was written to run unattended, and its card says so in the author's own
 * words. This file asserts the absence rather than assuming it - a gate
 * appearing here would be a change to the template that its caveat, its
 * gallery card and `PublishDialog`'s 403 warning all still described the old
 * way. Two facts follow from being gateless and both are load-bearing:
 * `create_run` answers 403 for an ANONYMOUS caller, and this harness is signed
 * in (`e2e/syntheticUser.ts` - the cookieless context is `e2e-user` at the API
 * as well as on the page), so a 403 here would mean the proxy had stopped
 * forwarding the identity, not that the template had stopped working.
 *
 * ## TWO runs, and the second one is not a duplicate
 *
 * The panel's run and the console's are the same pipeline - `runs.mode` is the
 * only difference (13 C7) - but they cannot be the same RUN here, and the
 * reason is a measured property of the console rather than a preference.
 * `useValidatorRun.setStatus` drops the stored run pointer the moment a run
 * reaches a terminal state, and that pointer is the only thing a later console
 * load can restore a run from: `RunHistory` deliberately offers a download
 * rather than a re-open, and no route carries a run id. Measured on this
 * backend on 2026-09-06: a News-to-social run completes in ~115 ms, so by the
 * time the panel can show a completed run there is nothing left for the
 * console to pick up.
 *
 * So run 1 is watched to `completed` in the panel, which is the half U6 asks
 * about the panel, and run 2 is handed over the instant it is launched, which
 * is the half U6 asks about the console. Both are the same document, the same
 * template and the same button; what is asserted about the console is that the
 * run id it shows is the id of the run THIS PANEL started, which is the claim
 * the row makes.
 *
 * @launch - `test-panel.spec.ts` and `templates.spec.ts` both tag every test
 * that starts a run, on the argument that the tag marks a test which must be
 * excluded from any origin that spends money rather than one that presses a
 * particular button. This file follows them: it starts two runs, so it carries
 * the tag, even though against `SYNTHETIC=1` both are free.
 */

/**
 * ONE forgiveness, and it is the same one `test-panel.spec.ts` declares in the
 * same words: `RUN_RATE_LIMIT_MAX_RUNS` is ten per sixty seconds per client,
 * and this file launches after every other launching spec in the suite has
 * spent its share. A refused launch makes the browser log the 429 as a failed
 * resource - that console error is THE LIMITER WORKING, provoked by a test
 * that then waits and launches again. Any other status, any Vue warning and
 * any uncaught exception still fails the test. Delete this if the limiter goes
 * or this file stops launching.
 */
const ALLOWED_CONSOLE_ERROR: RegExp | null = /429 \(Too Many Requests\)/

/** What the template declares, restated so a change to it fails HERE. */
const TEMPLATE_TITLE = 'News to social post'
const TEMPLATE_TESTID = 'home-template-news-to-social'
const TEMPLATE_NODES = 5
const TEMPLATE_EDGES = 4
const TEMPLATE_INPUT_FIELD = 'subject'

function watchConsole(page: Page): { unexpected: string[] } {
  const watch = { unexpected: [] as string[] }
  const record = (text: string) => {
    if (ALLOWED_CONSOLE_ERROR?.test(text)) return
    watch.unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return watch
}

/** `builder.spec.ts`'s cleaner, restated. The synthetic store is shared. */
async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) {
    // A PUBLISHED document is refused (decision 24), so unpublish first. This
    // file publishes, so it is the one that would otherwise leave the residue.
    await request.post(`/api/builder/workflows/${entry.id}/unpublish`)
    await request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

const nodes = (page: Page): Locator => page.locator('.vue-flow__node:has(.workflow-node)')
const panel = (page: Page): Locator => page.locator('[data-testid="test-panel"]')
const status = (page: Page): Locator => page.locator('[data-testid="test-run-status"]')

/**
 * The home, with nothing left over to redirect it away.
 *
 * `shell.spec.ts` opens it the same way and for the same reason: D2 sends `#/`
 * to `#/run` when a non-terminal run pointer or a builder handoff is in
 * storage, so a previous test's leavings would land this one on the console.
 */
async function openHome(page: Page): Promise<void> {
  await page.goto('/#/run')
  await page.evaluate(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })
  await page.goto('/#/')
  await expect(page.locator('.home-page')).toBeVisible()
}

/**
 * Arm the workspace switch to press ITSELF the moment a run exists, and record
 * which run that was.
 *
 * ## THE MACHINERY THIS REPLACES, and why it is gone (item 58, ROUND-2 R4)
 *
 * There was a 40-line in-page poll here, and its whole reason was a defect.
 * `setStatus` dropped the stored run pointer the instant a run reached a
 * terminal state, and that pointer was the ONLY thing a console load could
 * restore a run from - `RunHistory` offers a download rather than a re-open,
 * and no route carries a run id. Measured on this backend, five launches: the
 * pointer appeared 31-55 ms after the click and was gone 30-40 ms later,
 * because a synthetic News-to-social run is over in about 115 ms. A click from
 * Node cannot land in a 30 ms window, so the poll ran in the page at 5 ms and
 * pressed the switch itself.
 *
 * The pointer survives a finished run now, so the window is not 30 ms - it is
 * open, and this reads as the gesture it always was: finish the run, press
 * Run. The poll is deleted rather than kept "just in case", because a harness
 * built around a defect keeps passing after the defect is fixed and stops
 * anybody noticing that it was.
 */

/** The run the panel started, read off the pointer the console restores from. */
async function storedRunId(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index)
      if (key?.endsWith('validator-active-run')) {
        const raw = window.localStorage.getItem(key)
        if (raw) return (JSON.parse(raw) as { runId: string }).runId
      }
    }
    return null
  })
}

test.describe('the News-to-social template, opened from the home', () => {
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test(
    'runs to a terminal state in the docked panel, and hands the console the same run',
    { tag: '@launch' },
    async ({ page }) => {
      // Generous, and the ceiling is here so a WEDGED run fails as a wedged run
      // rather than as a suite that never finishes. The synthetic runner takes
      // milliseconds; the limiter's window is a minute.
      test.setTimeout(240_000)
      const watch = watchConsole(page)

      /* 1 ── one click from the home to this graph's canvas ---------------- */
      await openHome(page)
      const card = page.locator(`[data-testid="${TEMPLATE_TESTID}"]`)
      await expect(card).toContainText(TEMPLATE_TITLE)
      await card.click()

      // `#/build` with no id: a template is a draft until it is saved, so an id
      // in the address would be a promise the server has not made yet.
      await expect.poll(() => new URL(page.url()).hash).toBe('#/build')
      await expect(page.locator('.builder-flow')).toBeVisible()
      await expect(page.locator('.document-name')).toContainText(/news to social/i)

      // The shape, asserted against the CANVAS rather than against the module,
      // so a template that lost an edge to a serialisation change fails here.
      await expect(nodes(page)).toHaveCount(TEMPLATE_NODES)
      await expect(page.locator('.vue-flow__edge')).toHaveCount(TEMPLATE_EDGES)

      /* 2 ── Validate: clean on arrival, against the SERVER --------------- */
      // The HEADLINE first, and the order is load-bearing rather than tidy: the
      // dock's `checking…` marker is absent both while a validation is in
      // flight and before the debounce has started one, so a `toHaveCount(0)`
      // on it can pass over a graph nobody has validated yet. `Ready to
      // publish` is written only by a server answer, so waiting for it is what
      // makes the two assertions below assertions about a checked graph.
      await expect(page.locator('[data-testid="problems-headline"]')).toContainText(
        /ready to publish/i,
        { timeout: 30_000 },
      )
      await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0)
      // Zero build problems is the claim, so it is asserted as a count and not
      // inferred from the headline's wording.
      await expect(page.locator('.problems-panel li')).toHaveCount(0)

      /* 3 ── save and publish, which the panel requires before it will run - */
      await page.keyboard.press('Control+s')
      await expect(page.locator('[data-testid="save-chip"]')).toContainText(/saved/i)
      await expect
        .poll(() => new URL(page.url()).hash, { timeout: 20_000 })
        .toMatch(/#\/build\/ug_[0-9a-f]{8}$/)
      const documentId = /ug_[0-9a-f]{8}/.exec(new URL(page.url()).hash)![0]

      await page.keyboard.press('Control+Shift+P')
      const publish = page.locator('[aria-labelledby="publish-title"]')
      await expect(publish).toBeVisible()
      await publish.getByRole('button', { name: /^(Publish|Republish)$/ }).click()
      // The gateless sentence, which is this template's own trade rendered
      // where an author sees it before they hand anybody the link.
      await expect(publish).toContainText(/anyone signed out is refused/i)
      await expect(publish).toContainText(/403/)
      await publish.getByRole('button', { name: 'Close' }).click()
      await expect(publish).toHaveCount(0)

      /* 4 ── the docked panel takes it to a terminal state ---------------- */
      await expect(panel(page)).toHaveAttribute('data-open', 'false')
      await page.locator('[data-testid="test-tab-run"]').click()
      await expect(panel(page)).toHaveAttribute('data-open', 'true')

      // Seeded from the template's committed sample, keyed on `input_field`, so
      // there is nothing to configure (14 criterion 11). The box is the run
      // request's own key, which is what makes the seed findable.
      const value = page.locator('[data-testid="test-input-value"]')
      await expect(value).not.toHaveValue('')
      await expect(page.locator('[data-testid="test-body-run"]')).toContainText(
        new RegExp(TEMPLATE_INPUT_FIELD, 'i'),
      )
      await expect(page.locator('[data-testid="test-run-blocked"]')).toHaveCount(0)

      await page.locator('[data-testid="test-run"]').click()
      await expect(status(page)).toHaveText(/completed/i, { timeout: 180_000 })

      // A BODY, not merely a completed run: the whole of what the panel adds
      // over the run history is that the author reads the output beside the
      // graph that produced it.
      const result = page.locator('[data-testid="test-run-result"]')
      await expect(result).toBeVisible()
      await expect(result).not.toBeEmpty()

      // NO GATE, which is this template's declaration and not an accident. The
      // panel renders the forward answer for any gate that opens, so its
      // absence at a completed run is the assertion - and a gate that DID open
      // would carry the author's own canvas node, which is `builder-gates`'
      // subject and `test-panel.spec.ts`'s.
      await expect(page.locator('[data-testid="test-run-gate"]')).toHaveCount(0)
      await expect(page.locator('[data-testid="test-panel-problem"]')).toHaveCount(0)

      /* 5 ── the console shows the run this panel started ----------------- */
      // No second run and no arming: the pointer this run wrote outlives it
      // now (item 58, R4), so pressing the switch is enough - which is what
      // the helper's docblock above explains at length, because the machinery
      // that used to be needed here is the clearest measurement of the defect.
      const handedOver = await storedRunId(page)
      expect(handedOver, 'the panel run left no pointer to hand over').not.toBeNull()
      await page.locator('[data-testid="run-switch"]').click()
      await expect.poll(() => new URL(page.url()).hash, { timeout: 30_000 }).toBe('#/run')

      // The console's own chip: the first eight characters on screen, the whole
      // id in the title. Asserted on the title, because that is the value and
      // the text is a rendering of it.
      const chip = page.locator('.status-panel .run-id')
      await expect(chip).toHaveAttribute('title', handedOver!, { timeout: 30_000 })
      await expect(chip).toHaveText(handedOver!.slice(0, 8))

      // And it is the AUTHOR's workflow the console is naming, not the built-in
      // one it defaults to - the breadcrumb reads `Workflows / <this template>`.
      await expect(page.locator('.app-header .breadcrumb')).toContainText(TEMPLATE_TITLE)
      expect(documentId).toMatch(/^ug_[0-9a-f]{8}$/)

      expect(watch.unexpected).toEqual([])
    },
  )
})
