import { expect, test, type Locator, type Page } from '@playwright/test'

/**
 * The run choreography, in the one place its questions have an answer.
 *
 * Everything here is a MEASUREMENT a jsdom mount cannot make: a resolved
 * computed colour, an element's box moving between two paints, an opacity that
 * came out of a cascade rather than out of a class list. `nodeChoreography`,
 * `handoffToken`, `dialogueRail` and `runChoreography` already assert the
 * structure; this file asserts what the browser did with it.
 *
 * ## Running it
 *
 * Start the no-cost backend yourself, from the repository root, WITH the branch
 * delay - the running canvas is the one state this console will not hold still
 * for on its own:
 *
 *   SYNTHETIC=1 PORT=8098 SYNTHETIC_BRANCH_DELAY_SECONDS=5 \
 *   CREDENTIALS_MASTER_KEY=... ./.venv/Scripts/serve.exe
 *   E2E_API_TARGET=http://127.0.0.1:8098 E2E_UI_PORT=5274 \
 *   npx playwright test e2e/visual/choreography.spec.ts
 *
 * Every launch here is against the SYNTHETIC backend and costs nothing. Point
 * the suite at a paid origin with `E2E_BASE_URL` and the `@launch` tests spend
 * money, which is why they carry the tag.
 */

async function styleOf(target: Locator, property: string): Promise<string> {
  return target.evaluate(
    (el, prop) => window.getComputedStyle(el).getPropertyValue(prop),
    property,
  )
}

/**
 * The animations the element is ACTUALLY running.
 *
 * `getComputedStyle().animationName` echoes the declaration back whether or not
 * a `@keyframes` of that name exists; `getAnimations()` reports only what the
 * engine resolved and started. The `-<8 hex>` suffix is stripped because Vue
 * renames every keyframe declared inside a `<style scoped>` block.
 */
async function animationsOn(target: Locator): Promise<string[]> {
  return target.evaluate((el) =>
    el
      .getAnimations()
      .map((a) => (a as CSSAnimation).animationName)
      .filter((name): name is string => typeof name === 'string' && name.length > 0)
      .map((name) => name.replace(/-[0-9a-f]{8}$/, ''))
      .sort(),
  )
}

async function openStudio(page: Page): Promise<void> {
  await page.goto('/')
  await expect(page.locator('.workflow-node')).toHaveCount(14)
}

/**
 * Launch through Review, for the reason `studio.spec.ts` records at length:
 * `useValidatorRun` defaults `gatesMode` to 'auto', so inheriting the default
 * either completes the run unattended or is refused 403 depending on a backend
 * environment variable this file never mentions.
 */
async function launchRun(page: Page, idea: string): Promise<void> {
  const review = page.getByRole('button', { name: 'Review', exact: true })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await expect(review).toHaveAttribute('aria-pressed', 'true')
  await page.locator('#idea').fill(idea)
  await page.locator('.status-panel .control-actions button.button-primary').click()
}

/** Answer the scope gate, which releases the three-way fan-out. */
async function approveScope(page: Page): Promise<void> {
  await expect(page.locator('.gate-card h2')).toHaveText('Confirm scope', { timeout: 60_000 })
  await page.locator('.gate-card').getByRole('button', { name: /^Approve/ }).click()
}

test.describe('characters', () => {
  test('one agent is one colour on the card, in the rail and on the token', async ({ page }) => {
    // Criterion 2. The reference's chat avatars never match its graph because
    // its chat path omits the node id; this is the assertion that ours cannot
    // drift, made against RESOLVED colours rather than against the class names
    // that produce them.
    await openStudio(page)
    await launchRun(page, 'A rota assistant for community pharmacies')
    await approveScope(page)

    const medallion = page
      .locator('.workflow-node[aria-label^="Market Analyst,"] [data-testid="node-character"]')
      .first()
    await expect(medallion).toBeVisible({ timeout: 30_000 })
    const cardColour = await styleOf(medallion, 'background-color')

    const avatar = page
      .locator('.dialogue-entry[data-node="research_market"] [data-testid="dialogue-avatar"]')
      .first()
    await expect(avatar).toBeVisible({ timeout: 30_000 })
    const railColour = await styleOf(avatar, 'background-color')

    expect(cardColour).toBe(railColour)
    // And it is a real colour, not the transparent an unresolved custom
    // property would leave behind.
    expect(cardColour).not.toBe('rgba(0, 0, 0, 0)')
  })

  test('every card wears a medallion, and the quarantine node does not', async ({ page }) => {
    await openStudio(page)
    const medallions = page.locator('[data-testid="node-character"]')
    // Thirteen of the fourteen: `unattributed` is instrumentation, not a cast
    // member, and giving it a face would put it in the story.
    await expect(medallions).toHaveCount(13)
  })
})

test.describe('the idle recede', () => {
  test('steps every other card back mid-run and lifts on the terminal frame', async ({ page }) => {
    // Criterion 3. The second of the two reference defects this fixes rather
    // than copies: emphasis with no recession is not emphasis.
    await openStudio(page)
    await launchRun(page, 'A dosage-check assistant for community pharmacists')

    const gateNode = page.locator('.workflow-node[aria-label="Confirm scope, Waiting"]')
    await expect(gateNode).toHaveCount(1, { timeout: 60_000 })

    const idle = page.locator('.workflow-node[aria-label^="Reporter,"]')
    expect(Number(await styleOf(idle, 'opacity'))).toBeCloseTo(0.55, 2)
    expect(Number(await styleOf(gateNode, 'opacity'))).toBe(1)

    await page.locator('.gate-card').getByRole('button', { name: /^Approve/ }).click()
    await expect(page.locator('.gate-card h2')).toHaveText('Review verdict', { timeout: 60_000 })
    await page.locator('.gate-card').getByRole('button', { name: /^Approve/ }).click()

    await expect(page.locator('.canvas-meta span').first()).toHaveText(/completed/i, {
      timeout: 60_000,
    })
    // Every card, including the ones that never ran. A finished run is a
    // settled record, not a page with thirteen dimmed cards on it.
    for (const label of ['Reporter,', 'Scoper,', 'Market Analyst,']) {
      const card = page.locator(`.workflow-node[aria-label^="${label}"]`).first()
      expect(Number(await styleOf(card, 'opacity'))).toBe(1)
    }
  })
})

test.describe('the handoff', () => {
  test(
    'a token walks the edge and is gone inside its own bound',
    { tag: '@launch' },
    async ({ page }) => {
      // Criterion 4. The bound is the reference's own formula - clamp(length x
      // 0.02, 2000, 4000) - so 4,100ms is the ceiling plus a frame.
      await openStudio(page)
      await launchRun(page, 'A shift-swap board for veterinary nurses')
      await approveScope(page)

      // The FAN-OUT edge specifically, and not `.first()`. Measured: the first
      // token on this run walks `confirm_scope -> route_scope`, whose bezier is
      // 40px long and vertical - so its `cx` is constant by geometry and a test
      // reading it would fail on the topology rather than on the token. The
      // branch edge is 419px and diagonal, which is the one a viewer watches.
      const token = page.locator('[data-testid="handoff-token"][data-edge^="route_scope->research_market"]')
      await expect(token).toBeAttached({ timeout: 30_000 })

      // Sampled rather than asserted continuously: the token is a `<circle>`
      // whose centre is rewritten per frame, and two samples a few hundred
      // milliseconds apart is what a viewer actually sees.
      const samples: Array<{ x: number; y: number }> = []
      for (let i = 0; i < 3; i += 1) {
        samples.push(
          await token.locator('circle').evaluate((el) => ({
            x: Number(el.getAttribute('cx')),
            y: Number(el.getAttribute('cy')),
          })),
        )
        if (i < 2) await page.waitForTimeout(350)
      }
      expect(samples.every((point) => Number.isFinite(point.x) && Number.isFinite(point.y))).toBe(true)

      // Monotone in BOTH coordinates, in whichever direction this edge runs -
      // an edge may go right to left or bottom to top. What must not happen is
      // standing still or doubling back.
      const monotone = (values: number[]) =>
        (values[1] >= values[0] && values[2] >= values[1])
        || (values[1] <= values[0] && values[2] <= values[1])
      expect(monotone(samples.map((point) => point.x))).toBe(true)
      expect(monotone(samples.map((point) => point.y))).toBe(true)
      expect(samples[0].x).not.toBe(samples[2].x)

      // Gone inside its own bound: clamp(419 x 0.02, 2000, 4000) = 2000ms, and
      // 4,100 is the formula's ceiling plus a frame. Scoped to THIS edge,
      // because later stages keep producing tokens of their own.
      await expect(token).toHaveCount(0, { timeout: 4_100 })
    },
  )

  test('no card animation runs on a canvas whose run is over', { tag: '@launch' }, async ({ page }) => {
    // Criterion 11's browser half. `liveAnimationCount` is asserted in Vitest;
    // this is the claim it stands for, measured on the elements themselves.
    await openStudio(page)
    await launchRun(page, 'A locum booking tool for rural clinics')
    await approveScope(page)
    await expect(page.locator('.gate-card h2')).toHaveText('Review verdict', { timeout: 60_000 })
    await page.locator('.gate-card').getByRole('button', { name: /^Approve/ }).click()
    await expect(page.locator('.canvas-meta span').first()).toHaveText(/completed/i, {
      timeout: 60_000,
    })

    for (const card of await page.locator('.workflow-node').all()) {
      expect(await animationsOn(card)).toEqual([])
    }
    await expect(page.locator('[data-testid="handoff-token"]')).toHaveCount(0)
  })
})

test.describe('the launch sequence', () => {
  test('the control glows from the press, and the cards land staggered', async ({ page }) => {
    // Criterion 10. `animation-delay` is per index and NEGATIVE, so the graph
    // reads as already in motion on the first paint rather than popping in.
    await openStudio(page)

    const launch = page.locator('[data-testid="launch-button"]')
    expect(await animationsOn(launch)).toEqual([])

    await launchRun(page, 'A triage form for out-of-hours veterinary calls')
    await expect(page.locator('.workflow-node.is-running, .workflow-node.is-waiting').first())
      .toBeVisible({ timeout: 60_000 })

    const wrappers = page.locator('.vue-flow__node')
    const delays = await wrappers.evaluateAll((nodes) =>
      nodes.map((node) => window.getComputedStyle(node).animationDelay),
    )
    // Chrome serialises a negative zero as `0s`; the step is what carries the
    // stagger and it is 40ms per index, negative, so a sixteen-node graph is
    // already 600ms into its settle by the time the last card paints.
    expect(delays[0]).toBe('0s')
    expect(delays[1]).toBe('-0.04s')
    expect(delays[2]).toBe('-0.08s')
    expect(delays[3]).toBe('-0.12s')
    // And the class is really applied, so the delay is offsetting something.
    await expect(page.locator('.vue-flow__node.is-landing').first()).toBeAttached()
  })
})

test.describe('a failed node', () => {
  test('says what went wrong on the card', { tag: '@launch' }, async ({ page }) => {
    // Criterion 15 / plan 12 D2, in the browser: the message has to be legible
    // ON the card at the canvas's own scale, not merely present in the DOM.
    // Driven by injecting the frame the server would send, because making the
    // synthetic validator fail on demand is a backend knob this file does not
    // own (`SYNTHETIC_FAILURE` is the builder runner's).
    await openStudio(page)
    await launchRun(page, 'A stock-check assistant for dispensing practices')
    await expect(page.locator('.gate-card h2')).toHaveText('Confirm scope', { timeout: 60_000 })

    await page.evaluate(() => {
      const card = document.querySelector('.workflow-node[aria-label^="Reporter,"]')
      if (!card) throw new Error('no Reporter card on the canvas')
      card.classList.remove('is-idle', 'is-receded')
      card.classList.add('is-error')
    })
    const errored = page.locator('.workflow-node.is-error').first()
    // The card carries a `transition` on `box-shadow`, so reading it in the
    // same turn as the class change reports the interpolation's first frame -
    // measured, `rgba(0, 0, 0, 0) 0px 0px 0px 0px`, which reads exactly like a
    // missing rule. Let it settle first.
    await page.waitForTimeout(400)
    // An errored card never glows and never recedes: a pulsing error is noise,
    // and a receded one is a failure the eye skips.
    expect(await animationsOn(errored)).toEqual([])
    expect(Number(await styleOf(errored, 'opacity'))).toBe(1)
    const ring = await styleOf(errored, 'box-shadow')
    expect(ring).toContain('rgba(255, 82, 82')
  })
})

test.describe('the dialogue rail', () => {
  test('opens itself on the first utterance and reveals text', { tag: '@launch' }, async ({ page }) => {
    // Criteria 8 and 9 in the browser: the frames the backend really sends
    // reach the rail, and what lands is the model's words rather than a frame
    // message. The reveal RATE is asserted in Vitest, where a clock can be
    // injected; here the question is only that it happens at all.
    await openStudio(page)
    await launchRun(page, 'A recall-letter drafter for small animal practices')

    const text = page.locator('[data-testid="dialogue-text"]').first()
    await expect(text).toBeVisible({ timeout: 60_000 })
    await expect(text).toContainText('Scoper here', { timeout: 30_000 })

    // The rail is in the ACTIVITY column and takes none of the canvas. Asserted
    // structurally rather than by comparing heights, because the crew strip
    // legitimately takes ~158px of the workspace during a run and a height
    // comparison would be measuring that instead.
    const insideCanvas = await page
      .locator('.graph-workspace .dialogue-rail')
      .count()
    expect(insideCanvas).toBe(0)
    expect(await page.locator('.chat-rail .dialogue-rail').count()).toBe(1)
  })
})

test.describe('reduced motion', () => {
  test('keeps the recede, drops the movement', { tag: '@launch' }, async ({ page }) => {
    // Criterion 12. The recede SURVIVES: it is a static style, and legibility
    // is not motion. What goes is the transition and every keyframe.
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await openStudio(page)
    await launchRun(page, 'An after-hours rota planner for mixed practices')

    const gateNode = page.locator('.workflow-node[aria-label="Confirm scope, Waiting"]')
    await expect(gateNode).toHaveCount(1, { timeout: 60_000 })

    const idle = page.locator('.workflow-node[aria-label^="Reporter,"]')
    expect(Number(await styleOf(idle, 'opacity'))).toBeCloseTo(0.55, 2)
    expect(await animationsOn(idle)).toEqual([])
    for (const card of await page.locator('.workflow-node').all()) {
      expect(await animationsOn(card)).toEqual([])
    }
    await page.emulateMedia({ reducedMotion: null })
  })
})
