import { expect, type Locator, type Page } from '@playwright/test'

/**
 * Answering a durable gate, and knowing when the answer landed.
 *
 * Shared by `cast.spec.ts` and `cast-perf.spec.ts` rather than written twice —
 * the same helper failed in both files on 2026-09-05 and a copy would have had
 * to be fixed twice, which is the drift this repository keeps recording about
 * mirrored constants. It lives beside `syntheticUser.ts` for the same reason
 * that file exists: a non-spec module in `e2e/` is shared code, and Playwright's
 * default `testMatch` only collects `*.spec.ts`, so nothing here is registered
 * as a test.
 *
 * ## The mistake this module exists to correct
 *
 * The first version waited for `.gate-card` to reach count 0 after a Revise
 * reply, on the theory that the card unmounts when `pending_gate` is nulled and
 * remounts when the next gate opens. Measured, that gap does not exist: the
 * server emits `gate_closed` and `gate_open` back to back, Vue coalesces both
 * into one render, and `pendingGate` goes from gate A straight to gate B with
 * no frame in between where it is null. The card is patched in place. So the
 * assertion watched for a hole that is never there — 121 polls, `resolved to 1
 * element` every time, 60 s, and seven evidence artifacts lost behind it.
 *
 * Anything derived from the ELEMENT is therefore useless here: the element is
 * the same element. Even a marker written onto its dataset survives the patch.
 * What is needed is a value that differs between gate A and gate B.
 *
 * ## What is used instead, and why it is the right signal
 *
 * The gate node's PASS COUNT, off its own `aria-label`.
 *
 * `useValidatorRun` counts a node's transitions into an active state in
 * `nodeVisits`, and a gate node reaches `waiting` once per opening — so a
 * re-opened gate increments it, by construction, once per re-open. It appears
 * in the card's accessible name as `, pass N` from the second pass
 * (`WorkflowNode.vue::ariaLabel`), which `studio.spec.ts` already pins on the
 * revise journey and which is green today.
 *
 * Three properties make it the correct instrument rather than merely an
 * available one:
 *
 *  - it is **per opening**, not per gate id or per element, so it cannot be
 *    satisfied by the gate that was just answered;
 *  - it is **client-side**, so it says the console has APPLIED the new gate —
 *    asking the server would answer sooner than the page could act on, and a
 *    click into that window replies with the previous gate's id and takes a 409;
 *  - it is **the product's own claim**. The lap counters exist because "a second
 *    pass that looks identical to the first is indistinguishable from a stuck
 *    run". A test that waits on them is waiting on the thing the console was
 *    built to say.
 */

/** The gate card on screen, whichever gate it is. */
export function gateCard(page: Page): Locator {
  return page.locator('.gate-card')
}

/** The canvas node for a gate, addressed by the gate's own title. */
export function gateNode(page: Page, title: string): Locator {
  return page.locator(`.workflow-node[aria-label^="${title},"]`).first()
}

/**
 * Which pass this gate is on, counting from 1.
 *
 * The suffix appears from the second pass only — `×1` on every card of every run
 * is noise — so an absent `pass N` means one, and that is a fact about the
 * label rather than a fallback for a missing element.
 */
export async function gatePass(page: Page, title: string): Promise<number> {
  const label = (await gateNode(page, title).getAttribute('aria-label')) ?? ''
  return Number(/,\s*pass\s+(\d+)/.exec(label)?.[1] ?? 1)
}

/** Wait until the gate has re-opened for a pass later than `before`. */
export async function waitForGateReopen(
  page: Page,
  title: string,
  before: number,
): Promise<void> {
  await expect
    .poll(() => gatePass(page, title), {
      timeout: 90_000,
      message:
        `the ${title} gate never re-opened after a Revise reply: its node is still on pass ` +
        `${before}. The reply is taken by the server and the gate re-opens within a frame, so ` +
        'this is either the revise loop not looping or the lap counter not counting.',
    })
    .toBeGreaterThan(before)

  await expect(gateCard(page).locator('h2')).toHaveText(title, { timeout: 30_000 })
  await expect(gateCard(page).getByRole('button', { name: /^Approve/ })).toBeEnabled()
}

/**
 * Send a gate back for a revision and return when the SAME gate is open again,
 * on a later pass, with the console bound to it.
 *
 * The feedback note is located as `form textarea` rather than by its label: the
 * scope gate offers five fields of which feedback is the only textarea, and the
 * verdict gate prunes every field but that one. One selector, both gates, and no
 * dependence on the copy — which matters, because T1 sentence-cased those labels
 * and broke two assertions in `studio.spec.ts` that did depend on it.
 */
export async function reviseGate(page: Page, title: string, note: string): Promise<void> {
  const before = await gatePass(page, title)
  await gateCard(page).locator('form textarea').first().fill(note)
  await gateCard(page).getByRole('button', { name: /^Revise/ }).click()
  await waitForGateReopen(page, title, before)
}

/**
 * Approve the gate on screen and wait for it to go away.
 *
 * An approve genuinely does leave a gap — the scope gate hands off to a fifteen
 * second fan-out and the verdict gate to the report — so waiting for the card to
 * detach is correct HERE and wrong for a revise. The asymmetry is the whole
 * point of having two functions.
 */
export async function approveGate(page: Page): Promise<void> {
  await gateCard(page).getByRole('button', { name: /^Approve/ }).click()
  await expect(gateCard(page), 'the gate did not take the Approve reply').toHaveCount(0, {
    timeout: 60_000,
  })
}
