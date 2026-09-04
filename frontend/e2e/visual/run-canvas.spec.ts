import { expect, test, type Locator, type Page } from '@playwright/test'

/**
 * The WP-A gate: proof that extracting the node card's shell out of
 * `WorkflowNode.vue`'s scoped block changed nothing about the run canvas.
 *
 * The extraction's whole payoff is that the build-time card and the run-time
 * card become byte-identical because they read one stylesheet. The risk is that
 * "verbatim" is not enough on its own: a rule that leaves a `<style scoped>`
 * block LOSES the `[data-v-...]` attribute selector Vue compiles into it, so it
 * drops one class of specificity AND moves earlier in the cascade (a global
 * sheet imported from `studio.css` is parsed before any SFC style). Two rules
 * that used to be settled by source order can therefore swap winners without a
 * character of either one changing. That is not a hypothetical - see the
 * `.quarantine-count` case below, which this file caught.
 *
 * So the gate is two instruments, not one, because neither alone is sufficient:
 *
 *   1. THREE PIXEL BASELINES of the canvas - idle, running, gate-waiting. They
 *      catch anything visible, including things nobody thought to assert.
 *   2. A COMPUTED-STYLE AUDIT of the exact properties the cascade analysis
 *      flagged as at risk. Each row names the rule it is watching. This is the
 *      half that would still fail if the pixels happened to round the same way,
 *      and it is scale-independent.
 *
 * The audit also covers `animation-name`, which the pixel baselines physically
 * cannot: Playwright's `toHaveScreenshot` disables animations by default and
 * cancels infinite ones to their initial state, so a card whose glow stopped
 * working entirely would screenshot identically to one whose glow is fine.
 *
 * ## Running it
 *
 * Start the no-cost backend yourself, from the repository root, and give it the
 * branch delay - the `running` baseline is the one state the console will not
 * hold still for on its own:
 *
 *   SYNTHETIC=1 PORT=8099 SYNTHETIC_BRANCH_DELAY_SECONDS=5 ./.venv/Scripts/serve.exe
 *   npx playwright test e2e/visual
 *
 * `SYNTHETIC_BRANCH_DELAY_SECONDS` is the runner's own documented knob for
 * exactly this ("the ONLY way to reproduce the slow-branch case at zero cost").
 * Without it the three research branches complete in single-digit milliseconds
 * and there is no running node to photograph. The assertion that needs it says
 * so in its own failure message rather than timing out anonymously.
 *
 * Killing that backend needs `Stop-Process -Name serve -Force` in PowerShell,
 * NOT `pkill` - a stale process keeps answering `/healthz` from old code and
 * has cost this repository time twice (gotchas 25 and 26).
 */

/** `--text-muted: #b3b3b3`, resolved. */
const TEXT_MUTED = 'rgb(179, 179, 179)'

/**
 * Every screenshot masks the elapsed clock.
 *
 * `WorkflowNode` ticks it once a second while a call is in flight - that is the
 * card's one honest liveness signal and removing it would be a product change -
 * but it means the running canvas is never twice the same picture. The mask is
 * a solid box over the element's own bounds, and the digits inside a five
 * second window are always two characters wide, so the box itself is stable.
 */
function elapsedClock(page: Page): Locator {
  return page.locator('[data-testid="node-active-elapsed"]')
}

function canvas(page: Page): Locator {
  return page.locator('.validator-flow')
}

/**
 * The handoff tokens, masked for the same reason the clock is.
 *
 * A token's position is rewritten every animation frame while it walks its
 * edge, so two consecutive captures of the running canvas never agree - and
 * `toHaveScreenshot` retries until they do, burning its whole 15s budget and
 * then photographing a canvas whose fan-out has meanwhile finished. Measured:
 * the count assertion above the screenshot passed and the animation assertions
 * twenty lines below it timed out on a card that had simply completed.
 *
 * Masking is the established answer here, not a new one - the elapsed clock has
 * been masked since this file was written, for the same "never twice the same
 * picture" reason. What is lost is the token's pixels, which
 * `e2e/visual/choreography.spec.ts` measures directly and a still could not
 * have shown moving anyway.
 */
function handoffTokens(page: Page): Locator {
  return page.locator('[data-testid="handoff-token"]')
}

/** One computed property off one element, as the browser finally resolved it. */
async function styleOf(target: Locator, property: string): Promise<string> {
  return target.evaluate(
    (el, prop) => window.getComputedStyle(el).getPropertyValue(prop),
    property,
  )
}

/**
 * The animations the element is ACTUALLY running, by name.
 *
 * `getComputedStyle(el).animationName` is the wrong instrument here: it echoes
 * back whatever the declaration said, whether or not a `@keyframes` of that
 * name exists anywhere. `getAnimations()` only reports animations the engine
 * resolved and started, so it is the one call that distinguishes "the rule is
 * still there" from "the rule still works".
 *
 * The `-<8 hex>` suffix is stripped because Vue's SFC compiler renames every
 * `@keyframes` declared inside a `<style scoped>` block - `node-glowing`
 * becomes `node-glowing-338bad55` - and rewrites the references in that same
 * block to match. Moving the keyframes into a global sheet is therefore
 * EXPECTED to change these names, and only these names. Comparing the stripped
 * form is what lets one assertion hold on both sides of the extraction, which
 * is the entire point of a before/after gate.
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
  await expect(page.locator('.vue-flow__node').first()).toBeVisible()
  // The canvas fits itself on init; photographing it mid-transition would make
  // the baseline a race rather than a contract.
  await expect(page.locator('.workflow-node')).toHaveCount(14)
}

/**
 * Launch through Review, for the reason `studio.spec.ts` records at length:
 * `useValidatorRun` defaults `gatesMode` to 'auto', so inheriting the default
 * either completes the run unattended or is refused 403, depending on a backend
 * environment variable this file never mentions.
 */
async function launchRun(page: Page, idea: string): Promise<void> {
  const review = page.getByRole('button', { name: 'Review', exact: true })
  if ((await review.getAttribute('aria-pressed')) !== 'true') await review.click()
  await expect(review).toHaveAttribute('aria-pressed', 'true')
  await page.locator('#idea').fill(idea)
  await page.locator('.status-panel .control-actions button.button-primary').click()
}

test.describe('the run canvas survives the node-card extraction', () => {
  test('looks the same idle, and the card shell resolves as authored', async ({ page }) => {
    await openStudio(page)

    await expect(canvas(page)).toHaveScreenshot('run-canvas-idle.png', {
      mask: [elapsedClock(page), handoffTokens(page)],
    })

    // --- the double-clip -------------------------------------------------
    // The card paints TWO backgrounds: an opaque `--bg-node` clipped to the
    // padding box, and the gradient clipped to the border box, showing through
    // a 2px transparent border. Lose any one of these four declarations and the
    // gradient rim either vanishes or floods the whole card.
    const card = page.locator('.workflow-node[aria-label^="Scoper,"]')
    // Two layers, so every one of these resolves as a two-entry list.
    expect(await styleOf(card, 'background-origin')).toBe('border-box, border-box')
    expect(await styleOf(card, 'background-clip')).toBe('padding-box, border-box')
    expect(await styleOf(card, 'border-top-width')).toBe('2px')
    expect(await styleOf(card, 'border-top-style')).toBe('solid')
    expect(await styleOf(card, 'border-top-color')).toBe('rgba(0, 0, 0, 0)')
    expect((await styleOf(card, 'background-image')).match(/linear-gradient/g)).toHaveLength(2)
    expect(await styleOf(card, 'width')).toBe('270px')
    expect(await styleOf(card, 'padding-top')).toBe('13px')

    // --- the anatomy rows ------------------------------------------------
    expect(await styleOf(card.locator('.node-icon'), 'width')).toBe('34px')
    expect(await styleOf(card.locator('.node-copy strong'), 'font-size')).toBe('15px')
    // The eyebrow row reserves the state chip's lane. Without the padding the
    // chip and a long eyebrow simply overlap, which is what happened before the
    // lap chip gave the row a second occupant.
    expect(await styleOf(card.locator('.node-eyebrow-row'), 'padding-right')).toBe('62px')
    expect(await styleOf(card.locator('.node-state'), 'color')).toBe(TEXT_MUTED)

    // --- the cascade inversion this file exists to catch ------------------
    // `.quarantine-count` and `.node-state` are on the SAME element and set the
    // same two properties at the same specificity; `.node-state` wins only
    // because it is written later. Extract `.node-state` alone and the scoped
    // `.quarantine-count` gains a `[data-v-...]` it does not lose, outranks it,
    // and the chip silently restyles. Both rules move together for this reason.
    const quarantine = page.locator('[data-testid="quarantine-count"]')
    expect(await styleOf(quarantine, 'color')).toBe(TEXT_MUTED)
    expect(await styleOf(quarantine, 'column-gap')).toBe('5px')

    // --- and the second inversion, which the same cut opens up -------------
    // `is-${kind}` and `is-${state}` are two independent classes the template
    // applies to the same element, and a gate node that is executing carries
    // both. `.workflow-node.is-gate` and `.workflow-node.is-running` set
    // `--node-gradient` at identical specificity, so which one a running gate
    // obeys is decided purely by source order - running, because it is written
    // second. Extract `is-running` (the reduced-motion block names it) and
    // leave `is-gate` scoped, and a running gate turns amber.
    //
    // The class is added here rather than waited for: the combination is
    // reachable by construction from the template, and the assertion is about
    // the CSS cascade, not about which frames the synthetic backend happens to
    // emit. Measured both ways before it was written - amber is what the
    // half-extraction actually produces.
    const runningGate = await page
      .locator('.workflow-node[aria-label^="Confirm scope,"]')
      .evaluate((el) => {
        el.classList.add('is-running')
        const value = getComputedStyle(el).backgroundImage
        el.classList.remove('is-running')
        return value
      })
    expect(runningGate).toContain('rgb(153, 234, 249)')
    expect(runningGate).not.toContain('rgba(255, 217, 122')
  })

  test(
    'looks the same with a branch in flight, and still animates',
    { tag: '@launch' },
    async ({ page }) => {
      await openStudio(page)
      await launchRun(page, 'A scheduling assistant for small veterinary clinics')

      await expect(page.locator('.gate-card h2')).toHaveText('Confirm scope', { timeout: 60_000 })
      await page.locator('.gate-card').getByRole('button', { name: /^Approve/ }).click()

      /*
       * WHICHEVER branch is in flight, not `Market Analyst` by name.
       *
       * The synthetic runner walks the three branches in sequence, five seconds
       * each, so naming one bounded every assertion below to that branch's own
       * five-second window - and the screenshot in the middle of them eats two
       * to three of it. It held until plan 11 added a handoff token, whose walk
       * is driven by `requestAnimationFrame` rather than by CSS, so
       * `toHaveScreenshot`'s "wait for the element to be stable" now has
       * something moving inside the canvas to wait out. Measured: the count
       * assertion passed and `animationsOn` timed out twenty lines later, on a
       * card that had simply finished.
       *
       * `.is-running` re-resolves at each use and there is always exactly one
       * such card across the fifteen-second fan-out, so this asserts the same
       * thing about the same kind of card without racing the screenshot.
       */
      const running = page.locator('.workflow-node.is-running').first()
      await expect(
        page.locator('.workflow-node.is-running'),
        'No branch stayed in flight. Start the backend with SYNTHETIC_BRANCH_DELAY_SECONDS=5 - see this file docblock.',
      ).toHaveCount(1, { timeout: 30_000 })

      /*
       * The animation audit runs BEFORE the screenshot, and the order is
       * load-bearing rather than tidy.
       *
       * `toHaveScreenshot` cancels every infinite CSS animation to its initial
       * state to capture, and what it restores afterwards is not something to
       * depend on: measured here, the CARD's `node-glowing`/`node-pulse` came
       * back and the state dot's `dot-pulse` did not, so the audit read `[]` on
       * an element whose rule was perfectly intact. That is precisely the false
       * negative this audit exists to avoid producing.
       *
       * Nothing about what is asserted changes - both halves are statements
       * about the same running canvas - and the screenshot below is no longer
       * competing with a five-second branch for the same window.
       */
      expect(await animationsOn(running)).toEqual(['node-glowing', 'node-pulse'])
      expect(await animationsOn(running.locator('.state-dot'))).toEqual(['dot-pulse'])
      expect(await animationsOn(running.locator('.node-crew-oar').first()))
        .toEqual(['node-oar-stroke'])
      expect(await animationsOn(running.locator('.node-crew-hull'))).toEqual(['node-hull-bob'])
      expect(await animationsOn(running.locator('.node-crew-rower').first()))
        .toEqual(['node-rower-pull'])
      expect(await animationsOn(running.locator('.node-active-dot')))
        .toEqual(['node-active-pulse'])

      await expect(canvas(page)).toHaveScreenshot('run-canvas-running.png', {
        mask: [elapsedClock(page), handoffTokens(page)],
      })

      // The card's own reduced-motion block, which lives in the same extracted
      // file as the keyframes it silences. If it were left behind while its
      // subjects moved out, it would lose the specificity race against them and
      // reduced motion would quietly stop working - a failure invisible to
      // every other test in this repository.
      await page.emulateMedia({ reducedMotion: 'reduce' })
      // Re-waited, because the screenshot above may have outlasted the branch
      // that was running when the audit ran. There is one running card at a
      // time across the fan-out, and this asserts about whichever it now is.
      await expect(page.locator('.workflow-node.is-running')).toHaveCount(1, { timeout: 30_000 })
      expect(await animationsOn(running)).toEqual([])
      expect(await animationsOn(running.locator('.node-crew-oar').first())).toEqual([])
      // The elapsed COUNT keeps advancing under reduced motion; only the dot
      // stops. That is deliberate and is asserted so it stays deliberate.
      expect(await animationsOn(running.locator('.node-active-dot'))).toEqual([])
      await expect(elapsedClock(page).first()).toBeVisible()
      await page.emulateMedia({ reducedMotion: null })
    },
  )

  test(
    'looks the same paused at a gate',
    { tag: '@launch' },
    async ({ page }) => {
      await openStudio(page)
      await launchRun(page, 'A dosage-check assistant for community pharmacists')

      await expect(page.locator('.gate-card h2')).toHaveText('Confirm scope', { timeout: 60_000 })
      // The run is genuinely stopped here, waiting on a human, so this is the
      // one multi-state picture on the canvas that holds still by itself:
      // Scoper completed, the gate node waiting, everything downstream idle.
      const waiting = page.locator('.workflow-node[aria-label="Confirm scope, Waiting"]')
      const completed = page.locator('.workflow-node[aria-label="Scoper, Completed"]')
      await expect(waiting).toHaveCount(1)
      await expect(completed).toHaveCount(1)

      await expect(canvas(page)).toHaveScreenshot('run-canvas-gate-waiting.png', {
        mask: [elapsedClock(page), handoffTokens(page)],
      })

      // The three state tenancies of `--node-gradient` that the extraction must
      // not merge: waiting is amber, completed is mint, and neither is the base
      // card's tri-colour. Running and completed shared one gradient once, and
      // "working" was indistinguishable from "done" for the whole of a run.
      const waitingBg = await styleOf(waiting, 'background-image')
      const completedBg = await styleOf(completed, 'background-image')
      expect(waitingBg).not.toBe(completedBg)
      expect(completedBg).toContain('rgb(170, 255, 205)')
      expect(waitingBg).toContain('rgb(255, 224, 130)')
      // Completed overrides the opaque under-layer too, so its inner fill is
      // green-tinted rather than `--bg-node`. That is a second declaration in
      // the same rule and a verbatim cut must carry it.
      expect(completedBg).toContain('rgba(38, 48, 43, 0.98)')
    },
  )
})
