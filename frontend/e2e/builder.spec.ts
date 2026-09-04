import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test'

/**
 * End-to-end coverage of the flow builder, in a real browser against a real
 * backend.
 *
 * This is the only test in the repository that drives the PRODUCT rather than a
 * part of it: it places nodes from the palette, wires them, edits one in the
 * inspector, watches validation go red and then green, undoes, saves, resolves a
 * conflict, publishes, and then launches what it published. Every unit spec in
 * `frontend/tests/` asserts about one composable's answer; none of them can see
 * whether that answer reached the screen. Two of the three most expensive
 * defects this repository has recorded - the console that never rendered a
 * finished run's report, and the `RUN_STATE` frame whose `status` no test had
 * ever seen - were invisible for exactly that reason, and both would have been
 * caught by a test shaped like this one.
 *
 * ## Which backend
 *
 * `playwright.config.ts` starts `e2e/vite.e2e.config.ts`, which proxies `/api`
 * to `127.0.0.1:8099` and stubs the Better Auth origin with a signed-in session.
 * Start the free backend yourself from the repository root FIRST:
 *
 *   SYNTHETIC=1 PORT=8099 ./.venv/Scripts/serve.exe
 *
 * `SYNTHETIC=1` selects `synthetic_builder_runner` (`service/app.py`), so the
 * launch at the end of this file executes a real compiled builder flow through
 * the real registry with stub crew factories: real gates, real frames, real
 * persistence, no model call and no money. The paid backend on :8000 is not
 * reachable from here, by design - `vite.config.ts`'s proxy is the one this
 * suite deliberately does not use.
 *
 * ## Zero console errors
 *
 * `ALLOWED_CONSOLE_ERROR` is null and stays null. `studio.spec.ts` retired its
 * one exemption - a favicon 404 whose fix was one line of `index.html` - and
 * recorded why: an exemption that outlives its cause widens silently. A builder
 * that logs a Vue warning while drawing a graph has a reactivity defect, and
 * this is the only place that would notice.
 *
 * ## What this file assumes about markup, and why each assumption
 *
 * Selectors come from things the spec FIXES rather than from whatever the
 * components happen to render:
 *
 *   `.workflow-node`, `.is-kind-<kind>`,   spec §5.1 - the design tenancy's own
 *   `.has-error`, `.has-warning`,          CSS selectors, so a rename here is a
 *   `.is-tier-escalation`                  rename of the shipped stylesheet
 *   `.builder-flow`                        spec §5.4's field-dimming selector
 *   `.vue-flow__node[data-id]`,            Vue Flow's own, library-owned and
 *   `.vue-flow__handle[data-nodeid]`       read straight out of its source
 *   `role="log"` on ProblemsPanel          spec §2
 *   keys 1-7, Ctrl+Z, Ctrl+S, Ctrl+Shift+P, Delete, Escape   spec §4.1, §4.4, §4.6
 *
 * and from `data-testid`s the components already ship:
 * `save-chip`, `problems-headline`, `problems-checking`, `problem-<code>`,
 * `conflict-keep`. Those are read out of the components rather than demanded of
 * them.
 *
 * Node ids are DERIVED from the kind class rather than assumed, because the
 * template's ids are a literal in `data/builderTemplates.ts` and a test that
 * hard-coded `gate_1` would be asserting about `newNode`'s minting rule over a
 * document `newNode` never touched.
 *
 * Two additions the spec fixes behaviour for but no markup:
 * `[data-testid="inspector-rail"]` and `[data-testid="restore-bar"]`. Both are
 * named in the handover report as a contract WP-E and WP-B have to honour.
 */

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

/**
 * Palette order is `vocabulary.node_kinds`, which `builder_api.py::_vocabulary`
 * writes as literals in this order and the palette renders unsorted (§2, WP-D).
 * `frontend/tests/clientMirrors.spec.ts` asserts that order against the handler,
 * so this table cannot drift without a unit test failing first.
 */
const KIND_KEY = {
  input: '1',
  agent: '2',
  crew: '3',
  gate: '4',
  router: '5',
  transform: '6',
  output: '7',
} as const

interface ConsoleWatch {
  unexpected: string[]
  /**
   * Forgive one pattern, from the point of the call onwards.
   *
   * The file-level `ALLOWED_CONSOLE_ERROR` stays null and this does not widen
   * it: an allowance declared inside a test, next to the line that provokes it,
   * cannot outlive its cause the way a file-level exemption can - which is the
   * lesson `studio.spec.ts` recorded when it retired its favicon exemption.
   * Used once, for the 409 the conflict test exists to cause.
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
  const record = (text: string) => {
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
const edges = (page: Page): Locator => page.locator('.vue-flow__edge')
const problems = (page: Page): Locator => page.getByRole('log')
const headline = (page: Page): Locator => page.locator('[data-testid="problems-headline"]')
/**
 * The gallery card, scoped to `.template-card`.
 *
 * A bare `getByRole('button', { name: /Minimal gated agent/ })` was a strict
 * mode violation the moment anything was saved: the library list renders an
 * open button and a delete button carrying the same name, so the locator
 * resolved to three elements and every test after the first save failed on a
 * name collision rather than on anything the builder did. `.template-card` is
 * the gallery's own class and cannot collide with a saved document's row.
 */
const templateCard = (page: Page): Locator =>
  page.locator('.template-card').filter({ hasText: 'Minimal gated agent' })

/** One problem row, addressed by the code its mono chip carries. */
function problemRow(page: Page, code: string): Locator {
  return page.locator(`[data-testid="problem-${code}"]`)
}
const saveChip = (page: Page): Locator => page.locator('[data-testid="save-chip"]')
const inspector = (page: Page): Locator => page.locator('[data-testid="inspector-rail"]')

/** The card of the first node of a kind, and its id, read off Vue Flow's wrapper. */
async function firstOfKind(page: Page, kind: string): Promise<{ id: string; card: Locator }> {
  const wrapper = page.locator(`.vue-flow__node:has(.workflow-node.is-kind-${kind})`).first()
  await expect(wrapper, `no ${kind} node on the canvas`).toBeVisible()
  const id = await wrapper.getAttribute('data-id')
  return { id: id!, card: wrapper.locator('.workflow-node') }
}

/** A node's source handle by port name - `approve`, `revise`, a branch label, `out`. */
function port(page: Page, nodeId: string, portId: string): Locator {
  return page.locator(
    `.vue-flow__handle.source[data-nodeid="${nodeId}"][data-handleid="${portId}"]`,
  )
}

/**
 * A node's inbound FLOW handle - the `in` port at the top of the card.
 *
 * An edge lands on a PORT, not on a card: Vue Flow completes a connection only
 * when the pointer is released on a handle (or inside `connectionRadius` of
 * one), and the centre of a 240px card is nowhere near the 12px disc at its top
 * edge. Dragging to `.workflow-node` therefore never connected anything - it
 * just held the gesture open until the hover timed out.
 *
 * `data-handleid` is now load-bearing and was not before 2026-09-04: a card no
 * longer has ONE target handle. 02-canvas.md D1 puts `attach` on an agent's and
 * a crew's left edge and `member` on a crew's, so an unqualified
 * `.target[data-nodeid=...]` is a strict-mode violation on every agent - which
 * is the right failure, because the two ports mean categorically different
 * things and a test that took whichever came first would be asserting about
 * whichever the card happened to render first.
 */
function targetPort(page: Page, nodeId: string, portId = 'in'): Locator {
  return page.locator(
    `.vue-flow__handle.target[data-nodeid="${nodeId}"][data-handleid="${portId}"]`,
  )
}

/** Drag from one locator's centre to another's, the way a person draws an edge. */
async function dragTo(page: Page, from: Locator, to: Locator): Promise<void> {
  await from.hover()
  await page.mouse.down()
  await to.hover()
  await to.hover() // a second move, so Vue Flow's connection line has a frame to track
  await page.mouse.up()
}

async function openBuilder(page: Page): Promise<void> {
  await page.goto('/#/build')
  // The gallery is the empty state and also the proof the route resolved:
  // `#/build` with no document id renders it, `#/` renders the run console.
  await expect(templateCard(page)).toBeVisible()
}

/**
 * Seed the canvas from the smallest launchable template.
 *
 * `MINIMAL_GATED_AGENT` rather than `BLANK`, because every later step needs a
 * graph that already validates: a blank document carries `no-input-node` and
 * `no-output-node` from its first frame, and "watch the problem count fall to
 * zero" cannot be asserted from a state that was never clean.
 */
async function startFromMinimalTemplate(page: Page): Promise<void> {
  await templateCard(page).click()
  await expect(canvas(page)).toBeVisible()
  // input -> gate -> agent -> output. Four is the template's own shape, and
  // asserting it here means every count below is anchored to something real.
  await expect(nodes(page)).toHaveCount(4)
}

/** Drop a kind at the pointer with the number keys (§4.1), and settle. */
async function placeKind(page: Page, kind: keyof typeof KIND_KEY): Promise<void> {
  const before = await nodes(page).count()
  await canvas(page).click({ position: { x: 520, y: 430 } })
  await page.keyboard.press(KIND_KEY[kind])
  await expect(nodes(page)).toHaveCount(before + 1)
}

/**
 * Wait for the validation loop to settle: the 400ms debounce plus a round trip.
 *
 * Waiting on the RENDERED `stale` state rather than on a timer. `phase` is
 * `'stale'` while a request is in flight and the header reads `checking…`,
 * and that state is rendered precisely so an author - and therefore a test - can
 * tell "not yet" from "nothing wrong". A stale error list presented as current
 * is ChatDev's defining failure (§6.2); a test that read one would be
 * reproducing it.
 */
async function validationSettles(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="problems-checking"]')).toHaveCount(0, {
    timeout: 20_000,
  })
}

/** The document id out of the hash, once a save has assigned one. */
async function documentIdFromRoute(page: Page): Promise<string> {
  await expect
    .poll(() => new URL(page.url()).hash, { timeout: 20_000 })
    .toMatch(/#\/build\/ug_[0-9a-f]{8}$/)
  return /ug_[0-9a-f]{8}/.exec(new URL(page.url()).hash)![0]
}

/**
 * Every document this suite creates, deleted before and after each test.
 *
 * Without it the suite poisons itself INSIDE one run: `templateCard` used to
 * collide with the library row a previous test had saved, and the last three
 * tests failed on a strict-mode violation rather than on anything the builder
 * did. It also could not be run twice - five `ug_*` documents had to be deleted
 * by hand between runs. A suite that leaves state behind is a suite whose
 * second run is measuring something else.
 *
 * The synthetic backend's store is shared, so this deletes EVERY document
 * rather than only the ones this file made: there is nothing else in it, and a
 * leftover from an earlier aborted run is exactly what breaks the next one.
 */
async function clearLibrary(request: APIRequestContext): Promise<void> {
  const listed = await request.get('/api/builder/workflows')
  if (!listed.ok()) return
  const documents = (await listed.json()) as { id: string }[]
  for (const entry of documents) await request.delete(`/api/builder/workflows/${entry.id}`)
}

/* ─── the three token colours these tests read back off the pixels ────────── */

/** `--accent-mint: #aaffcd`, resolved. A handle the drag will land on. */
const MINT = 'rgb(170, 255, 205)'
/** `--err-text: #ffcccc`, resolved. A handle that will refuse it. */
const ERR = 'rgb(255, 204, 204)'
/** `--warn-text: #ffe082`, resolved. A gate's `revise` branch. */
const WARN = 'rgb(255, 224, 130)'

/**
 * The colour of the VISIBLE disc, which is the handle's `::after`.
 *
 * 02-canvas.md D1 splits the port into two elements - a transparent 24x24 hit
 * target and a 12px disc drawn by `::after` - so the handle's own background is
 * `rgba(0, 0, 0, 0)` by design and reading it would answer the wrong question.
 * This is also the read jsdom cannot make at all: it logs "Not implemented" for
 * a pseudo-element and hands back the element's own style, which would pass.
 */
async function discColour(handle: Locator): Promise<string> {
  return handle.evaluate(
    (el) => window.getComputedStyle(el, '::after').backgroundColor,
  )
}

test.describe('Flow builder', () => {
  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test('places a node, wires it, and watches validation go red then green', async ({ page }) => {
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)
    await validationSettles(page)

    // The template is the flagship, so it starts clean. If this ever fails the
    // gallery is shipping a graph that errors before the author has touched it -
    // the hazard §8.2 item 10 names for the validator template, arriving on the
    // one card a first-time visitor is most likely to click.
    await expect(headline(page)).toContainText(/ready to publish/i)

    await placeKind(page, 'agent')

    /*
     * An unconnected node is UNREACHABLE, and that judgement is the server's -
     * `node-unreachable`, from `bounds._input_output_problems`. The client never
     * computes it (§6.1 tier 2), so seeing it here is end-to-end proof that an
     * edit reached `POST /api/builder/validate`, that the answer came back, and
     * that it was rendered. No unit test can establish any link in that chain.
     */
    await validationSettles(page)
    await expect(problemRow(page, 'node-unreachable')).toBeVisible()
    await expect(page.locator('.workflow-node.has-error')).toHaveCount(1)
    const errorsWhileOrphaned = await page.locator('.problem-row').count()

    // Wire it in, and the same round trip has to clear it.
    const gate = await firstOfKind(page, 'gate')
    const placed = nodes(page).last()
    const placedId = (await placed.getAttribute('data-id'))!
    await dragTo(page, port(page, gate.id, 'approve'), targetPort(page, placedId))

    await validationSettles(page)
    await expect(problemRow(page, 'node-unreachable')).toHaveCount(0)
    /*
     * The list gets SHORTER, rather than empty.
     *
     * A freshly-placed agent lands on the library's first `agent_id`, and the
     * server also reports `library-missing-prompt-input` against it - a real
     * error about a real gap that wiring the node cannot possibly close. The
     * original assertion here demanded a globally clean graph, which is a
     * different claim from the one this test is about and one the product never
     * made. What wiring OWNS is the unreachability, and that is asserted above
     * by name; this is the corroborating count.
     */
    await expect
      .poll(() => page.locator('.problem-row').count())
      .toBeLessThan(errorsWhileOrphaned)

    expect(watch.unexpected).toEqual([])
  })

  test('refuses a connection into the input node at the mouse, and commits nothing', async ({
    page,
  }) => {
    /*
     * One of the four Tier-1 refusals (§6.1): an `input` node renders no target
     * handle at all, and `isValidConnection` refuses the drop. This is the only
     * class of rule the client may enforce - they are the server's PARSE
     * refusals, 422s that must never be sent.
     *
     * The assertion that matters is not that the edge is rejected but that
     * nothing was COMMITTED. A refused gesture that still pushed a history entry
     * makes the next Ctrl+Z undo a non-event, which is the undo defect an author
     * can never diagnose: the graph does not change, so the key looks broken.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const input = await firstOfKind(page, 'input')
    const agent = await firstOfKind(page, 'agent')
    const edgesBefore = await edges(page).count()

    await expect(
      page.locator(`.vue-flow__handle.target[data-nodeid="${input.id}"]`),
      'an input node renders no inbound port at all (§5.3)',
    ).toHaveCount(0)

    await dragTo(page, port(page, agent.id, 'out'), input.card)

    await expect(edges(page)).toHaveCount(edgesBefore)
    /*
     * Nothing COMMITTED, read off the undo control rather than off the save
     * chip. The chip cannot answer this question: seeding a template is itself
     * an unsaved draft by design (§4.6), so it reads "unsaved changes · Ctrl+S"
     * from the moment the gallery card is clicked and would read that whether
     * the refused gesture committed or not. `applyTemplate` clears the history,
     * so Undo is disabled until something commits - which makes it the exact
     * instrument for "the refused gesture pushed no history entry".
     */
    await expect(page.getByRole('button', { name: 'Undo' })).toBeDisabled()

    expect(watch.unexpected).toEqual([])
  })

  test('creates a node and its edge from a port drag as ONE undo step', async ({ page }) => {
    /*
     * Spec §4.1: dragging from a port to empty canvas opens `PortMenu`, and
     * creation is ONE commit containing the node AND the edge. One undo removes
     * both.
     *
     * The failure this guards is not cosmetic. Two commits means an author who
     * changes their mind presses Ctrl+Z, watches the edge vanish, and is left
     * holding an orphan node they did not ask for - the graph is now in a state
     * no single gesture produced, and finding the node to delete is on them.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const gate = await firstOfKind(page, 'gate')
    const nodesBefore = await nodes(page).count()
    const edgesBefore = await edges(page).count()

    await port(page, gate.id, 'revise').hover()
    await page.mouse.down()
    await canvas(page).hover({ position: { x: 260, y: 470 } })
    await canvas(page).hover({ position: { x: 260, y: 470 } })
    await page.mouse.up()

    // The typeahead runs over the vocabulary - kinds, agent ids, crew ids,
    // transform ops - so typing a kind and picking the first option is the
    // shortest real path through the menu.
    // Scoped to the PortMenu's own input. A bare `getByRole('combobox')` is
    // ambiguous with the inspector's `Run input` select the moment anything is
    // selected, and it resolved to two elements here.
    const typeahead = page.locator('.builder-portmenu-input')
    await expect(typeahead).toBeFocused()
    await typeahead.fill('agent')
    await expect(page.getByRole('option').first()).toBeVisible()
    await page.keyboard.press('Enter')

    await expect(nodes(page)).toHaveCount(nodesBefore + 1)
    await expect(edges(page)).toHaveCount(edgesBefore + 1)

    await page.keyboard.press('Control+z')

    await expect(nodes(page)).toHaveCount(nodesBefore)
    await expect(edges(page)).toHaveCount(edgesBefore)

    expect(watch.unexpected).toEqual([])
  })

  test('aborts the port menu with Escape and leaves the history untouched', async ({ page }) => {
    // The other half of §4.1's contract, and the one a "one commit" test cannot
    // reach: Escape must leave the history exactly as it found it, so the next
    // Ctrl+Z undoes the author's last REAL edit rather than an abandoned menu.
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const gate = await firstOfKind(page, 'gate')
    const nodesBefore = await nodes(page).count()

    await port(page, gate.id, 'revise').hover()
    await page.mouse.down()
    await canvas(page).hover({ position: { x: 300, y: 490 } })
    await canvas(page).hover({ position: { x: 300, y: 490 } })
    await page.mouse.up()
    await page.keyboard.press('Escape')

    await expect(nodes(page)).toHaveCount(nodesBefore)
    // Undo, not the save chip: a seeded template is an unsaved draft by design,
    // so the chip says "unsaved" either way. `applyTemplate` clears the history,
    // so a disabled Undo is proof that the aborted menu committed nothing.
    await expect(page.getByRole('button', { name: 'Undo' })).toBeDisabled()

    expect(watch.unexpected).toEqual([])
  })

  test('deletes a router branch and its edge together, and one undo restores both', async ({
    page,
  }) => {
    /*
     * Spec §4.4 and §2's `RouterBranchEditor`: deleting a branch that has an edge
     * deletes the edge IN THE SAME COMMIT.
     *
     * A branch label IS the out-port name, so a branch removed without its edge
     * leaves an edge departing by a port that no longer exists -
     * `edge-unknown-port`, an error the author did not cause and cannot see the
     * cause of, on a node they were only tidying.
     *
     * A fresh router is born with `match` and `otherwise` (`nodeKinds.ts`), so
     * those port names are this build's own defaults rather than an assumption.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await placeKind(page, 'router')
    const router = await firstOfKind(page, 'router')
    const output = await firstOfKind(page, 'output')

    // Two branches on arrival, so it satisfies `router-branch-count` and
    // `router-otherwise` the moment it lands (§2, `builderDefaults.ts`).
    const routerPorts = page.locator(`.vue-flow__handle.source[data-nodeid="${router.id}"]`)
    await expect(routerPorts).toHaveCount(2)

    await dragTo(page, port(page, router.id, 'match'), targetPort(page, output.id))
    const edgesWired = await edges(page).count()

    await router.card.click()
    await expect(inspector(page)).toBeVisible()
    await inspector(page).getByRole('button', { name: /remove|delete/i }).first().click()

    // The port goes on the same tick as the row, and the edge goes with it.
    await expect(routerPorts).toHaveCount(1)
    await expect(edges(page)).toHaveCount(edgesWired - 1)

    await page.keyboard.press('Control+z')

    await expect(routerPorts).toHaveCount(2)
    await expect(edges(page)).toHaveCount(edgesWired)

    expect(watch.unexpected).toEqual([])
  })

  test('configures a node in the docked inspector and the card says so at once', async ({
    page,
  }) => {
    /*
     * The inspector is DOCKED, never a modal (R15), and the card is the mirror of
     * what it edits. ChatDev's defining failure is a stack of overlays hiding the
     * graph you are editing; this asserts the opposite property directly - an
     * edit made in the rail is visible on the canvas with nothing closed.
     *
     * `tier` is the field chosen because it is the one with a visual consequence
     * the stylesheet owns: §5.1 gives escalation a second inset ring, so only
     * spend shouts. It is also what the budget is computed from, which is why
     * the meter has to move too.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const agent = await firstOfKind(page, 'agent')
    await agent.card.click()
    await expect(inspector(page)).toBeVisible()
    await expect(agent.card).not.toHaveClass(/is-tier-escalation/)

    await inspector(page).getByRole('button', { name: /escalation/i }).click()

    await expect(agent.card).toHaveClass(/is-tier-escalation/)
    await expect(saveChip(page)).toContainText(/unsaved/i)

    // Both dollar figures, always (§6.4). The enforced one carries the nitro
    // margin and the floor is the comparable; showing the inflated one alone
    // reads as an error.
    await validationSettles(page)
    await expect(page.getByText(/enforced/i)).toBeVisible()

    expect(watch.unexpected).toEqual([])
  })

  test('aligns a marquee selection in exactly one undo step', async ({ page }) => {
    /*
     * Spec §4.3. Two properties, and the second is the one that is easy to get
     * wrong: the marquee INTERSECTS rather than contains - containment-only is
     * what makes wide cards finicky, and a 240px card is a wide card - and align
     * is ONE commit, so one Ctrl+Z puts every node back.
     *
     * NOTE FOR THE HANDOVER: §4.3 requires a floating `SelectionToolbar` above a
     * multi-selection and §2's file manifest never lists one. This test is
     * written to §4.3 and §7.4 step 6, which are normative for this package;
     * if the toolbar is not built, this is the row that says so rather than a
     * gap nobody notices.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    /*
     * Nudge one card out of line FIRST, because align-left cannot be observed
     * over a graph that is already left-aligned.
     *
     * `MINIMAL_GATED_AGENT` is authored as a straight vertical column - all four
     * nodes at x=300 - so "align left moved nothing" was a true report about the
     * template rather than about the toolbar. Displacing one node makes this
     * test a statement about align and one undo step, which is its subject, and
     * independent of any later re-authoring of the template's geometry.
     */
    const stray = await firstOfKind(page, 'agent')
    const strayBox = await stray.card.boundingBox()
    await page.mouse.move(strayBox!.x + strayBox!.width / 2, strayBox!.y + 12)
    await page.mouse.down()
    await page.mouse.move(strayBox!.x + strayBox!.width / 2 + 120, strayBox!.y + 12, { steps: 8 })
    await page.mouse.up()
    await expect
      .poll(async () => (await stray.card.boundingBox())!.x)
      .toBeGreaterThan(strayBox!.x + 40)

    const box = await canvas(page).boundingBox()
    await page.mouse.move(box!.x + 12, box!.y + 12)
    await page.mouse.down()
    await page.mouse.move(box!.x + box!.width - 12, box!.y + box!.height - 12, { steps: 12 })
    await page.mouse.up()

    // Vue Flow's own selected class, not one of ours: R2 rules that the library
    // owns marquee, selection and drag, so the library's flag is the honest
    // thing to read.
    await expect(page.locator('.vue-flow__node.selected')).not.toHaveCount(0)

    const before = await nodes(page).evaluateAll((elements) =>
      elements.map((element) => (element as HTMLElement).style.transform),
    )

    await page.getByRole('button', { name: /align left/i }).click()

    const aligned = await nodes(page).evaluateAll((elements) =>
      elements.map((element) => (element as HTMLElement).style.transform),
    )
    expect(aligned, 'align left moved nothing').not.toEqual(before)

    await page.keyboard.press('Control+z')

    await expect
      .poll(() =>
        nodes(page).evaluateAll((elements) =>
          elements.map((element) => (element as HTMLElement).style.transform),
        ),
      )
      .toEqual(before)

    expect(watch.unexpected).toEqual([])
  })

  test('resolves a save conflict without discarding the author work', async ({ page, request }) => {
    /*
     * Spec §4.6 and §2's `ConflictDialog`: a 409 NEVER auto-reloads.
     *
     * The second writer here is a direct API call rather than a second browser
     * context, deliberately: that is the shape a conflict actually takes in
     * production - the same author's other tab, or a redeploy-driven reload -
     * and it isolates the assertion to the compare-and-set rather than to two
     * browsers racing each other.
     *
     * "Keep mine" is the branch asserted because it is the one that can lose
     * work: it adopts head's version as `expected_version` and re-PUTs.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await placeKind(page, 'transform')
    await page.keyboard.press('Control+s')
    await expect(saveChip(page)).toContainText(/saved/i)

    const id = await documentIdFromRoute(page)
    const head = await request.get(`/api/builder/workflows/${id}`)
    expect(head.ok(), 'the document the canvas just saved is not readable').toBe(true)
    const stored = (await head.json()) as { document: Record<string, unknown>; version: number }

    /*
     * The 409 this test provokes is logged by the BROWSER, not by the app.
     *
     * Chromium writes "Failed to load resource: … 409 (Conflict)" to the console
     * for any non-2xx response, and the whole subject of this test is that the
     * client meets a 409 and handles it. The zero-console-errors rule exists to
     * catch defects the app produces; a deliberately provoked HTTP status that
     * the app then renders correctly is the opposite of one. Narrow enough that
     * an unhandled failure anywhere else in the test is still caught.
     */
    watch.allow(/Failed to load resource.*409/)

    const written = await request.put(`/api/builder/workflows/${id}`, {
      data: {
        document: { ...stored.document, name: 'Written by the other tab' },
        expected_version: stored.version,
      },
    })
    expect(written.ok(), 'the second writer could not write').toBe(true)

    // The open canvas is now one version behind, so the next save collides.
    await placeKind(page, 'transform')
    await page.keyboard.press('Control+s')

    const keepMine = page.locator('[data-testid="conflict-keep"]')
    await expect(keepMine).toBeVisible()
    // The chip has to say so too. Silence is never a state (§2, `SaveChip`).
    await expect(saveChip(page)).toContainText(/conflict/i)

    await keepMine.click()

    await expect(keepMine).toBeHidden()
    await expect(saveChip(page)).toContainText(/saved/i)
    // The author's second transform survived the resolution. That is the whole
    // point of the branch, and the only assertion here that could catch a
    // "resolution" that quietly loaded head.
    await expect(nodes(page)).toHaveCount(6)

    expect(watch.unexpected).toEqual([])
  })

  test(
    'walks to a problem from the panel, fixes it, publishes, and the graph launches',
    // 13 D6: every test that presses Launch carries the tag, so
    // `--grep-invert @launch` against a deployed origin presses nothing. This
    // one launches through `request` rather than a button, and the tag is about
    // what the test DOES, not about which control it uses - `AGENTS.md` called
    // the untagged version a live hole for exactly that reason.
    { tag: '@launch' },
    async ({ page, request }) => {
    /*
     * The whole arc, and the only test here that ends in a real run.
     *
     * Spec ruling R4 cut Run mode because no builder runner existed. It exists
     * now - `service/builder_runner.py`, threaded through `create_app`'s
     * `runner_factory`, with `synthetic_builder_runner` selected by `SYNTHETIC=1`
     * - so publish is checked against what publishing is FOR rather than against
     * the dialog that reports it. A publish contract that renders beautifully
     * over a workflow `POST /runs` refuses is exactly the failure this last
     * assertion exists to catch, and nothing short of launching it can.
     *
     * The launch goes through the API rather than a UI control because the
     * builder renders none: `StudioView` keeps the Run header toggle and the
     * builder never offers one, so a Launch button here would be markup no
     * package owns.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    // Break it in a way only the SERVER can name, then let the panel navigate.
    await placeKind(page, 'agent')
    await validationSettles(page)
    // The COUNT lives in the headline; `role="log"` holds the rows, whose text
    // is the server's sentences and need never contain the word "error".
    await expect(headline(page)).toContainText(/error/i)
    // The row itself lives in the panel's polite live region, so a problem that
    // appears while focus is elsewhere is announced rather than only drawn.
    await expect(problems(page)).toContainText('node-unreachable')
    await expect(problemRow(page, 'node-unreachable')).toBeVisible()

    await problemRow(page, 'node-unreachable').click()

    // Clicking a row selects the anchor, centres it and focuses the mapped field
    // (§6.3). The bound inspector is the observable half, and it is what makes
    // the row a repair rather than a report.
    await expect(inspector(page)).toBeVisible()

    // Repair by deleting it. There is no confirm dialog and there should not be
    // one: undo is the confirmation, which is precisely why enabling the key is
    // safe here and is not in ChatDev (§4.4).
    await page.keyboard.press('Delete')
    await validationSettles(page)
    await expect(headline(page)).toContainText(/ready to publish/i)

    await page.keyboard.press('Control+s')
    await expect(saveChip(page)).toContainText(/saved/i)
    const id = await documentIdFromRoute(page)

    await page.keyboard.press('Control+Shift+P')
    /*
     * Addressed by the id it labels itself with, not by role or by name.
     * `ConflictDialog` and `ShortcutSheet` are dialogs too, so a bare role
     * lookup goes ambiguous the moment two are mounted - and the accessible NAME
     * is no better here, because this dialog's own heading changes from
     * "Register this graph..." to "This graph is live" the instant it succeeds,
     * which is precisely the moment the assertions below need to still find it.
     */
    const publish = page.locator('[aria-labelledby="publish-title"]')
    await expect(publish).toBeVisible()
    await publish.getByRole('button', { name: /^(Publish|Republish)$/ }).click()

    /*
     * The contract the author now owns (§2, `PublishDialog`). `input_field` is
     * the key `POST /runs` must carry inside `inputs`, and `reserved_input_keys`
     * are the keys it will now REFUSE with a 422. Both are facts about an
     * endpoint, and rendering them is the difference between publishing a graph
     * and publishing an API nobody documented.
     */
    await expect(publish).toContainText('idea')
    /*
     * `__builder__` and `out__<node>`, NOT `no_gates` / `sequential_branches`.
     *
     * This row was asserting the validator flow's `RESERVED_RUN_INPUT_KEYS`
     * (`config.py`), which is a different mechanism with a different membership.
     * A builder graph's reserved set is computed per document by
     * `descriptor.build_builder_workflow`: every state key the COMPILED flow
     * declares, minus the input field, because CrewAI merges `inputs` into state
     * wholesale. `__builder__` (`runtime.BUILDER_STATE_KEY`) is in every
     * compiled flow; `out__idea` is this graph's own input node's output slot.
     * Asserting the real pair is what makes the contract checkable.
     */
    await expect(publish).toContainText('__builder__')
    await expect(publish).toContainText('out__idea')

    // A gate stops this graph before it spends anything, so the dialog must say
    // the link is safe to share rather than quoting the 403.
    await expect(publish).toContainText(/anyone with the link can launch it/i)

    // And it really is launchable. Synthetic runners, so this costs nothing.
    const launched = await request.post('/api/sessions/e2e-builder/runs', {
      data: { workflow_id: id, inputs: { idea: 'A scheduling assistant for clinics' } },
    })
    expect(
      launched.status(),
      'the published graph was refused by the endpoint it was published for',
    ).toBe(202)
    const run = (await launched.json()) as { run_id: string }
    expect(run.run_id).toBeTruthy()

    // Leave nothing running: a builder gate holds a durable row open, and the
    // next test in this serial file would inherit it.
    await request.post(`/api/runs/${run.run_id}/cancel`)

    /*
     * `Run it` is the dialog's own handover to the console, and it is the reason
     * R4 is lifted: with `builder_runner.py` wired there is a real destination,
     * so the control is a control rather than the stub the brief forbids. What
     * is asserted is that it LEAVES the builder and lands somewhere the graph
     * can actually be launched from - the idea box the studio has always had.
     */
    await publish.getByRole('button', { name: /run it/i }).click()
    await expect.poll(() => new URL(page.url()).hash).not.toMatch(/^#\/build/)
    /*
     * `textarea#idea`, not `#idea`.
     *
     * Vue Flow forwards a node's id onto its rendered root, so the published
     * graph's own input node lands on the run canvas as `<article id="idea">` -
     * next to the console's idea box, which has carried `id="idea"` since long
     * before the builder existed. Two elements, one id: a bare `#idea` is a
     * strict-mode violation and, more to the point, ambiguous about which of
     * them the test means. It means the box you type in.
     */
    await expect(page.locator('textarea#idea')).toBeVisible()

    expect(watch.unexpected).toEqual([])
    },
  )

  test('never presents an unchecked document as ready to publish', async ({ page }) => {
    /*
     * Spec section 6.2's named failure, on the first screen a visitor meets.
     *
     * "Blank canvas" hands over the same document `useBuilderDocument` is seeded
     * with, so its fingerprint never moved, the validation watcher never fired,
     * and ZERO `/api/builder/validate` requests were sent - measured with a
     * request spy. Over that the dock read `Ready to publish`, the publish
     * checklist ticked `Validation is current` and `No errors`, and the server
     * answered the same bytes with two errors. Every other template differs from
     * the seed and validated by accident, which is why this was invisible
     * anywhere except the one card a first-time visitor is most likely to click.
     *
     * REWRITTEN 2026-09-04, because the DOCUMENT changed and the defect did
     * not. 02-canvas.md D7 seeds the blank canvas with the run's two ends wired,
     * so it is now genuinely clean and "ready to publish" is the TRUE answer for
     * it - which means the old assertion would now pass for the wrong reason on
     * a build where the loop was broken again.
     *
     * So the test drives the loop instead of reading one frame of it: the
     * request has to fire on the very first show, and then deleting the output
     * node has to make the SERVER's own `no-output-node` appear and the headline
     * stop saying ready. Nothing in that chain can be satisfied by a client that
     * never asked - `no-output-node` is `bounds._input_output_problems`, and the
     * client computes no problem of any kind (§6.1 tier 2).
     */
    const watch = watchConsole(page)
    const validates: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('/api/builder/validate')) validates.push(request.url())
    })

    await openBuilder(page)
    const before = validates.length
    await page.locator('.template-card').filter({ hasText: 'Blank canvas' }).click()
    await expect(canvas(page)).toBeVisible()

    // The premise: choosing the card really sends the seed to the server. This
    // is the assertion the original defect failed, and it is unchanged.
    await expect.poll(() => validates.length).toBeGreaterThan(before)
    await validationSettles(page)

    // D7 and criterion 10: a new graph opens clean, with one input node.
    await expect(nodes(page)).toHaveCount(2)
    await expect(page.locator('.workflow-node.is-kind-input')).toHaveCount(1)
    await expect(page.locator('.problem-row')).toHaveCount(0)
    await expect(headline(page)).toContainText(/ready to publish/i)

    // Now break it, and the answer has to come back from the server.
    const output = page.locator('.vue-flow__node:has(.workflow-node.is-kind-output)').first()
    await output.locator('.workflow-node').click()
    await page.keyboard.press('Delete')
    await expect(nodes(page)).toHaveCount(1)

    await validationSettles(page)
    await expect(problemRow(page, 'no-output-node')).toBeVisible()
    await expect(headline(page)).not.toContainText(/ready to publish/i)

    expect(watch.unexpected).toEqual([])
  })

  test('ends the keyboard connect gesture it starts, and Escape keeps working after', async ({
    page,
  }) => {
    /*
     * `E` (section 4.1) used to arm the MOUSE's connect gesture and hand the
     * author nothing to finish it with. `connectDrag` is cleared only by
     * `onConnectEnd`, which a pointer fires, so the canvas kept `.is-connecting`
     * with two infinite `port-ready` animations running at rest - section 5.5
     * says the design canvas is STILL - and `escape()` stayed pinned on its
     * first rung, so Escape could never clear a selection again all session.
     *
     * Underneath it, a click on any card focused the title's `<strong>`
     * (`tabindex="-1"` is mouse-focusable in Chromium) whose
     * `@keydown.esc.stop.prevent` swallowed Escape before the window listener
     * ever saw it. Both halves are asserted here, because only a real browser
     * has either.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const gate = await firstOfKind(page, 'gate')
    await gate.card.click()
    await page.keyboard.press('e')

    await expect(page.locator('.builder-canvas')).toHaveClass(/is-connecting/)
    await expect(page.locator('[data-link-index]')).not.toHaveCount(0)

    await page.keyboard.press('Escape')

    await expect(page.locator('.builder-canvas')).not.toHaveClass(/is-connecting/)
    await expect(page.locator('[data-link-index]')).toHaveCount(0)
    // Nothing animates on an idle canvas.
    expect(
      await page.evaluate(() =>
        document
          .getAnimations()
          .map((animation) => (animation as unknown as { animationName?: string }).animationName)
          .filter(Boolean),
      ),
    ).toEqual([])

    // And the ladder's next rung still works, which it could not before.
    await gate.card.click()
    await expect(page.locator('.vue-flow__node.selected')).toHaveCount(1)
    await page.keyboard.press('Escape')
    await expect(page.locator('.vue-flow__node.selected')).toHaveCount(0)

    expect(watch.unexpected).toEqual([])
  })

  test('completes a keyboard link with Tab and Enter', async ({ page }) => {
    // The other half of section 4.1's `E`: candidates numbered, Tab cycles,
    // Enter connects. None of it existed - `E` opened a mode with no way out
    // and no way through.
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const edgesBefore = await edges(page).count()
    const gate = await firstOfKind(page, 'gate')
    await gate.card.click()
    await page.keyboard.press('e')
    await expect(page.locator('[data-link-index]')).not.toHaveCount(0)

    await page.keyboard.press('Tab')
    await page.keyboard.press('Enter')

    await expect(edges(page)).toHaveCount(edgesBefore + 1)
    await expect(page.locator('.builder-canvas')).not.toHaveClass(/is-connecting/)

    expect(watch.unexpected).toEqual([])
  })

  test('focuses the node filter with / and dims what does not match', async ({ page }) => {
    /*
     * Section 4.5. The binding existed, the shortcut sheet advertised it, and it
     * was wired to a selector that matched nothing anywhere in the app, whose
     * miss was swallowed by `?.`. There was no filter state, no input, no
     * dimming - and `NodePalette` contained no `<input>` at all.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await canvas(page).click({ position: { x: 40, y: 40 } })
    await page.keyboard.press('/')
    await expect(page.locator('.builder-filter-input')).toBeFocused()

    await page.keyboard.type('draft')

    await expect(page.locator('.workflow-node.is-filter-match')).not.toHaveCount(0)
    await expect(page.locator('.workflow-node.is-filter-dimmed')).not.toHaveCount(0)
    // Dimmed, never removed: the shape of the graph survives the search.
    await expect(nodes(page)).toHaveCount(4)

    expect(watch.unexpected).toEqual([])
  })

  test('lets a keyboard author out of the canvas', async ({ page }) => {
    /*
     * WCAG 2.1.2, which is a different criterion from the 2.1.1 argument
     * `requiresCanvasFocus` makes and was never covered by it. Sixty presses of
     * Tab from the canvas landed on the canvas sixty times, and every control
     * after it in DOM order - the whole inspector, the problems dock, the zoom
     * buttons, both rail toggles - was unreachable by keyboard for as long as
     * the view was mounted. `Shift+Escape` is the documented way out, and the
     * shortcut sheet renders it because the sheet renders the binding table.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await canvas(page).click({ position: { x: 40, y: 40 } })
    expect(
      await page.evaluate(() => document.activeElement?.closest('.builder-canvas') !== null),
    ).toBe(true)

    await page.keyboard.press('Shift+Escape')

    expect(
      await page.evaluate(() => document.activeElement?.closest('.builder-canvas') !== null),
    ).toBe(false)
    // And ordinary sequential navigation carries on from there rather than
    // dropping the author at the top of the document and back into the canvas.
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe('BODY')

    expect(watch.unexpected).toEqual([])
  })

  test('opens a prior version read-only, and Restore makes it the next head', async ({ page }) => {
    /*
     * Plan 15 D3, criterion 4's browser half. The unit suite proves the
     * store's lock, the composable's CAS and the component's rendering each
     * on their own; what only a browser can answer is whether the four agree
     * on screen - that the row the author clicks is the version the canvas
     * draws, that a Delete key over it lands nowhere, that the publish dialog
     * names the mismatch, and that Restore comes back as a NEW head with the
     * old one one undo away.
     *
     * Newest-first is asserted here and nowhere else on purpose: the
     * component renders the server's order and never sorts, so this is the
     * one place the contract is checked end to end.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await page.keyboard.press('Control+s')
    await expect(saveChip(page)).toContainText(/saved · v1/)
    await documentIdFromRoute(page)

    await placeKind(page, 'transform')
    await page.keyboard.press('Control+s')
    await expect(saveChip(page)).toContainText(/saved · v2/)
    await expect(nodes(page)).toHaveCount(5)

    await page.getByRole('button', { name: 'More actions' }).click()
    await page.getByRole('menuitem', { name: 'Versions' }).click()
    const browser = page.locator('[data-testid="version-browser"]')
    await expect(browser).toBeVisible()
    const rows = browser.locator('.version-row')
    await expect(rows).toHaveCount(2)
    await expect(rows.first()).toHaveAttribute('data-testid', 'version-row-2')
    await expect(rows.first()).toContainText('head')

    await page.locator('[data-testid="version-row-1"]').click()

    await expect(page.locator('[data-testid="version-viewing"]')).toContainText('Viewing v1 of v2')
    await expect(nodes(page)).toHaveCount(4)
    await expect(page.locator('.builder-canvas')).toHaveClass(/is-read-only/)
    // A gesture lands nowhere. Delete over a selected card commits nothing,
    // and the notice says why rather than the canvas looking broken.
    const agent = await firstOfKind(page, 'agent')
    await agent.card.click()
    await page.keyboard.press('Delete')
    await expect(nodes(page)).toHaveCount(4)
    await expect(page.getByRole('button', { name: 'Undo' })).toBeDisabled()
    await expect(page.locator('.builder-notice')).toContainText(/read-only/)

    // The precondition `PublishDialog` already enforces keeps refusing a non-head.
    await page.keyboard.press('Control+Shift+P')
    const publish = page.locator('[aria-labelledby="publish-title"]')
    await expect(publish).toContainText('you are viewing v1; publish works on head (v2)')
    await expect(publish.getByRole('button', { name: /^(Publish|Republish)$/ })).toBeDisabled()
    await page.keyboard.press('Escape')
    await expect(publish).toBeHidden()

    await page.locator('[data-testid="version-restore"]').click()

    // v3 with v1's content. v2 is still listed - history was appended to,
    // never rewritten - and head is one Ctrl+Z away.
    await expect(saveChip(page)).toContainText(/saved · v3/)
    await expect(page.locator('[data-testid="version-viewing"]')).toHaveCount(0)
    await expect(page.locator('.builder-canvas')).not.toHaveClass(/is-read-only/)
    await expect(nodes(page)).toHaveCount(4)
    await expect(rows).toHaveCount(3)
    await expect(rows.first()).toHaveAttribute('data-testid', 'version-row-3')
    await expect(rows.first()).toContainText('head')
    await expect(page.locator('[data-testid="version-row-2"]')).toBeVisible()

    await canvas(page).click({ position: { x: 40, y: 40 } })
    await page.keyboard.press('Control+z')
    await expect(nodes(page)).toHaveCount(5)

    expect(watch.unexpected).toEqual([])
  })

  test('recovers the open document across a reload without offering a stale draft', async ({
    page,
  }) => {
    /*
     * Spec §4.6: a localStorage draft is offered ONLY when its baseVersion still
     * equals head. Immediately after a save it does, so there is nothing to
     * restore - and the bar must not appear, because a restore bar over a
     * document that is already current invites an author to "recover" the
     * version they are looking at.
     *
     * The version chip is the positive half, and it is what makes the negative
     * half worth anything: a page that rendered nothing at all would satisfy
     * "no restore bar" perfectly.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await placeKind(page, 'output')
    await page.keyboard.press('Control+s')
    await expect(saveChip(page)).toContainText(/saved/i)
    const id = await documentIdFromRoute(page)

    await page.reload()

    await expect(nodes(page)).toHaveCount(5)
    await expect(saveChip(page)).toContainText(/saved/i)
    await expect(saveChip(page)).toContainText(/v\d+/)
    await expect(page.locator('[data-testid="restore-bar"]')).toHaveCount(0)
    expect(new URL(page.url()).hash).toContain(id)

    expect(watch.unexpected).toEqual([])
  })
})

/* ─── ports and edges in a real browser (02-canvas.md criteria 2, 3, 4) ───── */

/**
 * These four tests are the half of plan 02 that a jsdom mount cannot reach.
 *
 * `frontend/tests/builderPorts.spec.ts` proves the RULES - which connections
 * `isValidConnection` accepts, what `builder.css` declares - and it does that by
 * reading the real stylesheet, because jsdom does not implement
 * `getComputedStyle(el, '::after')` at all and would silently hand back the
 * element's own style instead. What it cannot ask is the question the rubric
 * actually scores: how big is the target, does the drag land, and what colour is
 * the disc under the pointer right now. Those have an answer only here.
 */

/** The pane's current zoom, off the transform matrix Vue Flow writes. */
async function zoomLevel(page: Page): Promise<number> {
  return page
    .locator('.builder-flow .vue-flow__transformationpane')
    .evaluate((el) => new DOMMatrixReadOnly(window.getComputedStyle(el).transform).a)
}

/**
 * Wheel the pane to a target zoom and report what it actually reached.
 *
 * d3-zoom's wheel handler scales by `2 ** (-deltaY / 500)`, so the delta for a
 * ratio is `-500 * log2(ratio)`. It is computed rather than hunted for by
 * clicking the `+` button, because the zoom-in control steps by a fixed factor
 * that has nothing to do with 50% or 150% and would land somewhere near them.
 * The number is READ BACK and asserted rather than assumed: a wheel that the
 * zoom limits clamped is exactly the failure criterion 7 exists for.
 */
async function zoomTo(page: Page, target: number): Promise<number> {
  const from = await zoomLevel(page)
  const box = (await canvas(page).boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -500 * Math.log2(target / from))
  await expect.poll(() => zoomLevel(page)).toBeCloseTo(target, 1)
  return zoomLevel(page)
}

test.describe('the canvas, in a browser', () => {
  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test('connects at 50 / 100 / 150 % zoom, ten times out of ten', async ({ page }) => {
    /*
     * Criterion 2, and rubric 3's whole subject.
     *
     * The port was a 9px disc with a 9px hit target until 2026-09-04 - hit
     * target equal to the visual, which is the shape of defect the rubric names
     * by example, and below Flowise's own 10px floor. At 50% zoom that is four
     * and a half pixels of target, and "the first attempt" stops being a
     * reasonable thing to ask for. It is now a 24px box around a 12px disc, so
     * the target survives the zoom the mark does not.
     *
     * TEN drags rather than one, because a hit target is a probability and a
     * single success proves nothing about it. Each one is followed by a Ctrl+Z,
     * so every attempt starts from the same document and the tenth is not
     * quietly easier than the first.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const gate = await firstOfKind(page, 'gate')
    const agent = await firstOfKind(page, 'agent')
    // The `revise` port is free on the template; `approve` already carries the
    // edge into the agent, and a duplicate triple is a Tier-1 refusal.
    const before = await edges(page).count()

    for (const target of [1, 0.5, 1.5]) {
      const reached = await zoomTo(page, target)
      for (let attempt = 1; attempt <= 10; attempt += 1) {
        await dragTo(page, port(page, gate.id, 'revise'), targetPort(page, agent.id))
        await expect(
          edges(page),
          `zoom ${reached.toFixed(2)}, attempt ${attempt}: the drag did not land`,
        ).toHaveCount(before + 1)
        await page.keyboard.press('Control+z')
        await expect(edges(page)).toHaveCount(before)
      }
    }

    expect(watch.unexpected).toEqual([])
  })

  test('paints the target handle green when it will take the edge and red when it will not', async ({
    page,
  }) => {
    /*
     * Criterion 3, and it is the FD4 class rules seen from the pointer's end.
     *
     * Vue Flow sets `vue-flow__handle-connecting` on whatever the pointer is
     * over and adds `vue-flow__handle-valid` when `isValidConnection` said yes -
     * exactly as React Flow does, which is why Flowise's two CSS rules
     * (`views/canvas/index.css:41-49`) transfer verbatim. Agentflow v2 dropped
     * its type check and its cycle rejection is SILENT: the drop just does
     * nothing. That is the failure this test exists to keep out.
     *
     * A tool is the sharpest case available. Its one port is a SOURCE, an agent
     * offers two target ports, and exactly one of them will take it: `attach`
     * yes, `in` no - because nothing an agent HAS is a step in the flow, and
     * `in` is the big obvious port at the top of every card.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await canvas(page).click({ position: { x: 260, y: 430 } })
    await page.keyboard.press('t')
    await expect(page.locator('.workflow-node.is-kind-tool')).toHaveCount(1)
    const tool = await firstOfKind(page, 'tool')
    const agent = await firstOfKind(page, 'agent')

    const attach = targetPort(page, agent.id, 'attach')
    const flow = targetPort(page, agent.id, 'in')

    // Hold one drag open across both hovers, so the two answers are the same
    // gesture rather than two gestures that happened to agree.
    await port(page, tool.id, 'attach').hover()
    await page.mouse.down()

    await attach.hover()
    await attach.hover()
    await expect(attach).toHaveClass(/vue-flow__handle-valid/)
    // POLLED, not read once. The disc carries `transition: background
    // var(--motion-fast)`, so a single read lands mid-ramp: this assertion
    // first failed at `rgb(190, 98, 98)`, which is 70% of the way from the
    // node's own fill to the refusal red. The end state is the claim.
    await expect.poll(() => discColour(attach)).toBe(MINT)

    await flow.hover()
    await flow.hover()
    await expect(flow).toHaveClass(/vue-flow__handle-connecting/)
    await expect(flow).not.toHaveClass(/vue-flow__handle-valid/)
    await expect.poll(() => discColour(flow)).toBe(ERR)

    await page.mouse.up()

    expect(watch.unexpected).toEqual([])
  })

  test('says no to a refused drop, and commits nothing when it does', async ({ page }) => {
    /*
     * The other half of criterion 3: "a refused drop leaves
     * `useBuilderDocument.depth` unchanged".
     *
     * `depth` is not reachable from a browser, so what is read is the thing the
     * author reads - the Undo button's own tooltip, which is `Undo: <the label
     * of the command at the top of the history>`. A commit lands first, so the
     * assertion is about the top of a NON-EMPTY history: a refusal that quietly
     * pushed an entry would change that string, and a disabled-button check
     * would not have noticed.
     *
     * And the refusal has to be VISIBLE. Flowise v2's does nothing at all, which
     * teaches an author that the canvas is broken rather than that the edge was.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    await canvas(page).click({ position: { x: 260, y: 430 } })
    await page.keyboard.press('t')
    const tool = await firstOfKind(page, 'tool')
    const agent = await firstOfKind(page, 'agent')

    const undo = page.getByRole('button', { name: 'Undo' })
    const label = await undo.getAttribute('title')
    expect(label).toMatch(/^Undo: /)
    const edgesBefore = await edges(page).count()

    // Onto the agent's `in` port, which refuses an attachment.
    await dragTo(page, port(page, tool.id, 'attach'), targetPort(page, agent.id, 'in'))

    await expect(edges(page)).toHaveCount(edgesBefore)
    expect(await undo.getAttribute('title')).toBe(label)
    // No `PortMenu`: it offers to CREATE a node, which is not the question the
    // author asked, and it would hide the refusal behind a menu.
    await expect(page.locator('.builder-portmenu')).toHaveCount(0)

    expect(watch.unexpected).toEqual([])
  })

  test('shows the port name on the dangling line while a gate branch is dragged', async ({
    page,
  }) => {
    /*
     * Criterion 4. Flowise previews the branch label and colour on its own
     * connection line and its notes say why: a drag from a two-branch node then
     * never lands on the wrong branch. A router here can have four ports and
     * they are four identical discs along one edge, so without this the author
     * finds out which one they grabbed by releasing.
     *
     * The label is read while the button is still DOWN, which is the only moment
     * it exists - and is why no unit test can ask this question.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    const gate = await firstOfKind(page, 'gate')
    const line = page.locator('.builder-connection-line')

    await port(page, gate.id, 'revise').hover()
    await page.mouse.down()
    const box = (await canvas(page).boundingBox())!
    await page.mouse.move(box.x + box.width / 2, box.y + box.height - 80)
    await page.mouse.move(box.x + box.width / 2, box.y + box.height - 90)

    await expect(line).toBeVisible()
    await expect(line.locator('.builder-connection-label')).toHaveText('revise')
    // Tinted by the port's class, not by a default: `revise` is `--warn-text`.
    // The project pins `colorScheme: 'dark'`, which is why a token value can be
    // written down here at all - see `playwright.config.ts`.
    await expect
      .poll(() => line.evaluate((el) => window.getComputedStyle(el).color))
      .toBe(WARN)

    await page.keyboard.press('Escape')
    await page.mouse.up()

    expect(watch.unexpected).toEqual([])
  })

  test('places the first node of a new graph in one click from the landing page', async ({
    page,
  }) => {
    /*
     * Criterion 10, rubric 1: landing -> first node placed is ONE click.
     *
     * The click is the gallery card, and what it opens is no longer empty. The
     * blank canvas used to open with nothing drawn and two errors against it,
     * so the first thing a new author saw was a red problems dock about a graph
     * they had not touched. It now opens with the run's two ends wired and the
     * dock silent - measured against this build's own validator, which answers
     * zero problems for exactly this document.
     */
    const watch = watchConsole(page)
    await openBuilder(page)

    await page.locator('.template-card').filter({ hasText: 'Blank canvas' }).click()

    await expect(nodes(page)).toHaveCount(2)
    await expect(page.locator('.workflow-node.is-kind-input')).toHaveCount(1)
    await validationSettles(page)
    await expect(page.locator('.problem-row')).toHaveCount(0)

    expect(watch.unexpected).toEqual([])
  })

  test('keeps the zoom limits the plan sets, and the port target inside them', async ({ page }) => {
    /*
     * Criterion 7's first half. The ceiling rose from 1.4 to Vue Flow's own
     * default 2.0, matching Flowise, so a 390px viewport can read an 11px port
     * label at 22px. The floor stays 0.2: the 16-node validator template fits at
     * 0.466 in a settled container, so a 48-node document needs roughly 0.3 and
     * the floor has to be under it.
     *
     * Asserted by driving the wheel PAST each limit and reading where it
     * stopped, because a `min-zoom` prop nobody exercises is a prop that can be
     * wrong.
     */
    await openBuilder(page)
    await startFromMinimalTemplate(page)
    const box = (await canvas(page).boundingBox())!
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)

    await page.mouse.wheel(0, -6000)
    await expect.poll(() => zoomLevel(page)).toBeCloseTo(2, 2)

    await page.mouse.wheel(0, 12000)
    await expect.poll(() => zoomLevel(page)).toBeCloseTo(0.2, 2)
  })
})

/* ═══ attachments, and the inspector (03 criterion 10; 04 criteria 2, 9, 10) ══ */

/**
 * The global Expert switch, set rather than toggled.
 *
 * A `.click()` on a checkbox flips whatever it currently is, and `expertMode`
 * is a `localStorage` singleton that survives a reload and every earlier test
 * in this file - so a toggle is a gesture whose outcome depends on the order
 * the suite ran in. Setting is the only form that means the same thing twice.
 */
async function setExpert(page: Page, on: boolean): Promise<void> {
  const box = inspector(page).locator('.expert-switch input')
  await expect(box).toHaveCount(1)
  if ((await box.isChecked()) !== on) await box.click()
  await expect(box).toBeChecked({ checked: on })
}

/** Type into one inspector control, addressed by the document path it edits. */
async function fillField(page: Page, field: string, value: string): Promise<void> {
  const control = inspector(page)
    .locator(`[data-field="${field}"] textarea, [data-field="${field}"] input[type="text"], [data-field="${field}"] input:not([type])`)
    .first()
  await expect(control, `no control for ${field}`).toBeVisible()
  await control.fill(value)
  // A prompt commits on input and coalesces; blurring settles the last one
  // before the next assertion reads the document.
  await control.blur()
}

/**
 * Every `POST /api/builder/validate` answer the APP itself received.
 *
 * Reading the app's own round trip rather than composing a request: a test that
 * validated a document it built would be asserting about its own copy, and the
 * question is whether what is ON THE CANVAS is what the server called valid.
 * A body that will not parse is skipped rather than recorded as false - the
 * failure this watches for is a clean-looking canvas over an invalid document,
 * not a network hiccup.
 */
function watchValidation(page: Page): boolean[] {
  const answers: boolean[] = []
  page.on('response', (response) => {
    if (!response.url().includes('/api/builder/validate')) return
    void response
      .json()
      .then((body: { valid?: boolean }) => {
        if (typeof body.valid === 'boolean') answers.push(body.valid)
      })
      .catch(() => undefined)
  })
  return answers
}

/** The palette tile for a kind, addressed by the key it announces (§4.1, D7). */
function paletteTile(page: Page, hotkey: string): Locator {
  return page.locator(`.builder-tile[aria-keyshortcuts="${hotkey}"]`)
}

/** One attachment avatar on a host card - 03 D6. */
const avatars = (page: Page, hostId: string): Locator =>
  page.locator(`.vue-flow__node[data-id="${hostId}"] .builder-attach-avatar`)

/**
 * Convert the template's LIBRARY agent into an AUTHORED one.
 *
 * 04's Status records that this is the only route to the authored arm:
 * `nodeKinds.defaultConfig` still builds the library arm, and no plan specifies
 * a palette tile for a fresh authored node. Every criterion below that is about
 * `llm.model`, the Expert tier or the 42 controls therefore starts here, and it
 * is one pointer action - which is also why the click budget in the last test
 * counts it.
 */
async function convertToAuthored(page: Page, card: Locator): Promise<void> {
  await card.click()
  await expect(inspector(page)).toBeVisible()
  await inspector(page)
    .getByRole('button', { name: /convert to an authored agent/i })
    .click()
  await expect(inspector(page).locator('[data-field="llm.model"]')).toBeVisible()
}

test.describe('attachments and the inspector', () => {
  test.beforeEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test.afterEach(async ({ request }) => {
    await clearLibrary(request)
  })

  test('attaches a tool by dropping it on an agent, in one undo step', async ({ page }) => {
    /*
     * 03 criterion 10, and 06 criterion 9's first half.
     *
     * D8's gesture: a tool dropped INSIDE an agent card is one commit carrying
     * the node AND the `attach` edge, so one Ctrl+Z removes both. Two commits
     * would leave an author who pressed undo once holding a pill they never
     * placed, hanging off nothing - the undo defect that cannot be diagnosed,
     * because the graph does not change and the key looks broken.
     *
     * A real HTML5 drag, not a synthetic call. `NodePalette` writes
     * `application/x-builder-kind` on `dragstart` and `BuilderCanvas` reads it
     * on `drop`; a test that called `dropKind` directly would prove the
     * composable and skip the two handlers where this has actually broken.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)
    await validationSettles(page)

    const agent = await firstOfKind(page, 'agent')
    const nodesBefore = await nodes(page).count()
    const edgesBefore = await edges(page).count()

    await paletteTile(page, 'T').dragTo(agent.card)

    // One node and one edge, and the card says so without being opened: D6's
    // avatar is the only place an agent admits what it has in its hands.
    await expect(nodes(page)).toHaveCount(nodesBefore + 1)
    await expect(edges(page)).toHaveCount(edgesBefore + 1)
    await expect(avatars(page, agent.id)).toHaveCount(1)

    // The pill carries the tool's own label, which is the other half of D6:
    // the avatar says the agent has hands, the pill says which.
    const pill = page.locator('.workflow-node.is-kind-tool')
    await expect(pill).toBeVisible()
    await expect(pill.locator('.builder-chip').first()).not.toBeEmpty()

    await page.keyboard.press('Control+z')
    await expect(nodes(page)).toHaveCount(nodesBefore)
    await expect(edges(page)).toHaveCount(edgesBefore)
    await expect(avatars(page, agent.id)).toHaveCount(0)

    expect(watch.unexpected).toEqual([])
  })

  test('leaves a tool dropped on empty canvas unattached, and says so', async ({ page }) => {
    /*
     * The other half of 03 criterion 10, and a decision rather than an
     * oversight: a drop on empty canvas is LEGAL and creates an unattached
     * node, because an author may be laying out before wiring. What makes that
     * survivable is that `bounds.py` says so in a sentence they can read -
     * `attachment-unattached`, a WARNING - where a refused drop would say
     * nothing at all.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)
    await validationSettles(page)

    const edgesBefore = await edges(page).count()
    await paletteTile(page, 'T').dragTo(canvas(page), {
      targetPosition: { x: 220, y: 470 },
    })

    await expect(page.locator('.workflow-node.is-kind-tool')).toBeVisible()
    // No edge: this is the branch of `dropKind` that did NOT find a host.
    await expect(edges(page)).toHaveCount(edgesBefore)

    await validationSettles(page)
    await expect(problemRow(page, 'attachment-unattached')).toBeVisible()
    // The dock's live region carries it too, so a warning that appears while
    // focus is elsewhere is announced rather than only drawn.
    await expect(problems(page)).toContainText('attachment-unattached')

    expect(watch.unexpected).toEqual([])
  })

  test('surfaces a problem that lives behind the Expert switch, and walks to its node', async ({
    page,
  }) => {
    /*
     * 04 criterion 2, the browser half - and it is TWO claims, only one of
     * which this build can make. This test is the half that holds; the
     * `test.fixme` below is the half that does not, with the change it needs.
     *
     * `llm.reasoning_effort` lives behind the global Expert switch, which is OFF
     * by default and renders its region ABSENT FROM THE DOM rather than hidden
     * with CSS. So a server problem anchored there is one the author is told
     * about and cannot see - the modal-stack failure R15 exists to prevent,
     * wearing a smaller hat.
     *
     * The problem is a REAL one from `registry.py`: `openai/gpt-4.1-nano`
     * genuinely does not reason, and `model-lacks-capability` carries C8's
     * optional `field` naming `llm.reasoning_effort` specifically - which is why
     * the code alone could not have anchored it, since the same code blames
     * `llm.response_format` on the next node.
     *
     * ORDER IS LOAD-BEARING. The effort is chosen while the model still
     * supports reasoning, because the segmented control DISABLES itself the
     * moment the model cannot honour it - so setting the model first would
     * leave nothing to click.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)
    await validationSettles(page)

    const agent = await firstOfKind(page, 'agent')
    await convertToAuthored(page, agent.card)

    // Expert is off, and the rail says how much is behind it rather than
    // leaving a gap: "this product cannot do that" and "you have that switched
    // off" look identical when the answer is empty space.
    await expect(inspector(page).locator('[data-tier="expert-hidden"]')).toBeVisible()
    await expect(inspector(page).locator('[data-field="llm.reasoning_effort"]')).toHaveCount(0)

    await setExpert(page, true)
    await inspector(page)
      .locator('[data-field="llm.reasoning_effort"]')
      .getByRole('button', { name: 'high', exact: true })
      .click()
    await inspector(page)
      .locator('[data-field="llm.model"] select')
      .selectOption('openai/gpt-4.1-nano')

    // Put it back out of sight. This is the state the criterion is about: a
    // real error, against a control that is not on screen.
    await setExpert(page, false)
    await expect(inspector(page).locator('[data-field="llm.reasoning_effort"]')).toHaveCount(0)

    await validationSettles(page)
    const row = problemRow(page, 'model-lacks-capability')
    await expect(row).toBeVisible()
    // The server's own sentence, verbatim, naming both the model and the
    // parameter - because the author's next action is to change one of the two.
    await expect(row).toContainText('gpt-4.1-nano')
    await expect(row).toContainText('reasoning_effort')

    await row.click()
    // What the row DOES do today: it selects the anchor and opens the rail on
    // it. That is a repair the author can act on - the sentence names
    // `llm.model`, which is in Essentials and on screen.
    await expect(inspector(page)).toBeVisible()
    await expect(agent.card).toHaveClass(/problem-anchor|is-flashing|has-error/)

    expect(watch.unexpected).toEqual([])
  })

  /*
   * The other half of 04 criterion 2, and it is CLOSED - the integration
   * closer of 2026-09-04 wired the dock's row click to the rail.
   *
   * `InspectorRail.focusField` always did everything the criterion asks: it
   * turns the global switch on for an Expert field, awaits the tick that
   * renders the region, flashes the row and focuses the control. What it
   * lacked was a second caller. The dock's row click went to
   * `onEdgeSelectFromPanel` -> `canvas.focusProblem`, which selects the node
   * and flashes the card and never mentions a field, so the walk stopped at
   * the node and a problem anchored behind the switch left the author looking
   * at a form that appears clean. `onEdgeSelectFromPanel` now asks
   * `problems.fieldFor(problem)` and hands the answer to the rail.
   *
   * `focusField` falls back to the ROW when every control in it is disabled,
   * which is this exact problem's state - `llm.reasoning_effort` is disabled
   * BECAUSE the model cannot honour it - so without that fallback the landing
   * would be silent. This test asserts the landing, not the mechanism.
   */
  test(
    'turns the Expert switch on and focuses the control a hidden problem blames',
    async ({ page }) => {
      const watch = watchConsole(page)
      await openBuilder(page)
      await startFromMinimalTemplate(page)
      await validationSettles(page)

      const agent = await firstOfKind(page, 'agent')
      await convertToAuthored(page, agent.card)
      await setExpert(page, true)
      await inspector(page)
        .locator('[data-field="llm.reasoning_effort"]')
        .getByRole('button', { name: 'high', exact: true })
        .click()
      await inspector(page)
        .locator('[data-field="llm.model"] select')
        .selectOption('openai/gpt-4.1-nano')
      await setExpert(page, false)
      await validationSettles(page)

      await problemRow(page, 'model-lacks-capability').click()

      // The switch is ON, not smuggled past: what is on screen and what is in
      // `localStorage` agree, so an author sent here once finds the rest of the
      // expert settings where they left them.
      await expect(inspector(page).locator('.expert-switch input')).toBeChecked()
      await expect(inspector(page).locator('[data-tier="expert"]')).toBeVisible()

      const row = inspector(page).locator('[data-field="llm.reasoning_effort"]')
      await expect(row).toBeVisible()
      await expect(row).toHaveClass(/problem-anchor/)
      expect(
        await page.evaluate(
          () =>
            (document.activeElement as HTMLElement | null)?.closest(
              '[data-field="llm.reasoning_effort"]',
            ) !== null,
        ),
        'focus did not land inside the row the sentence blames',
      ).toBe(true)

      expect(watch.unexpected).toEqual([])
    },
  )

  test('is fully keyboard reachable: every control of an authored agent, and the dock', async ({
    page,
  }) => {
    /*
     * 04 criterion 9. `@axe-core/playwright` is deliberately NOT added - zero
     * new dependencies - so this is a real Tab walk rather than an audit.
     *
     * WHAT IS ASSERTED is the property the criterion names: no control is
     * SKIPPED. Every focusable control the rail renders is stamped first, the
     * walk records what focus actually visited, and the two are compared. A
     * test that merely counted Tab presses would pass straight over a control
     * with `tabindex="-1"` sitting in the middle of the form.
     *
     * Both disclosures are opened first, because a control behind a shut
     * `<details>` is not skipped - it is not there, and D1 says so on purpose.
     *
     * THE DOCK IS REACHED BACKWARDS, with Shift+Tab, and that is a fact about
     * the layout rather than a convenience: `.graph-workspace` puts the
     * problems panel in grid row 5 and the rail is a sibling AFTER it
     * (`BuilderView`'s `<main>`), so from the top of the rail the dock is
     * behind you. Walking forwards from the canvas would go through every node
     * card and every port first, which measures Vue Flow rather than this rail.
     */
    const watch = watchConsole(page)
    await openBuilder(page)
    await startFromMinimalTemplate(page)

    // An orphan, so the dock has a row to be reached. `node-unreachable` is the
    // server's own judgement and needs no fixture.
    await placeKind(page, 'agent')
    await validationSettles(page)
    await expect(problemRow(page, 'node-unreachable')).toBeVisible()

    const agent = await firstOfKind(page, 'agent')
    await convertToAuthored(page, agent.card)

    // Everything on screen: Advanced open, Expert switched on.
    await inspector(page).locator('summary.tier-summary').first().click()
    await setExpert(page, true)
    await expect(inspector(page).locator('[data-tier="expert"]')).toBeVisible()

    const expected = await inspector(page).evaluate((rail) => {
      const selector =
        'input:not([type=hidden]), select, textarea, button, summary, [contenteditable="true"], [tabindex]:not([tabindex="-1"])'
      return Array.from(rail.querySelectorAll<HTMLElement>(selector))
        .filter((el) => !(el as HTMLInputElement).disabled)
        .filter((el) => el.offsetParent !== null || el.tagName === 'SUMMARY')
        .map((el, index) => {
          el.dataset.walkId = String(index)
          return String(index)
        })
    })
    /*
     * A FLOOR rather than an exact count. The rail renders 42 leaf controls
     * plus the region summaries, the tier chips and the attachment jumps, and
     * pinning the total here would fail for every future field. What this test
     * is about is that none of them is unreachable.
     */
    expect(expected.length, 'the rail rendered no focusable control').toBeGreaterThan(30)

    await inspector(page).locator('[data-walk-id="0"]').focus()
    const seen = new Set<string>(['0'])
    for (let step = 0; step < expected.length * 3; step += 1) {
      await page.keyboard.press('Tab')
      const id = await page.evaluate(
        () => (document.activeElement as HTMLElement | null)?.dataset?.walkId ?? null,
      )
      if (id !== null) seen.add(id)
      if (seen.size === expected.length) break
    }

    const missed = expected.filter((id) => !seen.has(id))
    expect(missed, `Tab never reached ${missed.length} of ${expected.length} controls`).toEqual([])

    // ...and back out of the rail into the dock, which is the other half of the
    // criterion: a keyboard author who has read the form has to be able to
    // reach the list of what is wrong with it, and a problem list reachable
    // only by mouse is a problem list they cannot act on.
    await inspector(page).locator('[data-walk-id="0"]').focus()
    let reachedDock = false
    for (let step = 0; step < 40 && !reachedDock; step += 1) {
      await page.keyboard.press('Shift+Tab')
      reachedDock = await page.evaluate(() =>
        Boolean((document.activeElement as HTMLElement | null)?.closest('[role="log"]')),
      )
    }
    expect(reachedDock, 'Shift+Tab out of the rail never reached the problems dock').toBe(true)

    expect(watch.unexpected).toEqual([])
  })

  test('configures an agent in nine pointer actions, ending valid', async ({ page }) => {
    /*
     * 04 criterion 10, rubric 4 - and the count is MEASURED here rather than
     * argued in prose. `pointer` is incremented at every click and every drag
     * and nowhere else; typing is free, exactly as D10 says ("8 pointer actions
     * plus typing five prompt fields"), because the prompts are the author's
     * content and no product can save them a keystroke.
     *
     * THE MEASURED COUNT IS NINE, not D10's eight, and every one of the five
     * differences is a fact about what shipped rather than a gesture anybody
     * chose to add:
     *
     *     8   D10's budget
     *    -1   the Blank card seeds an `output`, so its `palette 7` press is gone
     *    -1   `ModelPicker` is a native `<select>` (04's departure 6), so D10's
     *         "open + choose" is one gesture and not two
     *    +1   the authored arm is reached ONLY by converting a library agent
     *         (04's departure 9); no plan specifies a palette route to one
     *    +1   the Blank card also ships WIRED, so its own `idea -> result` edge
     *         has to go before the agent can sit between the two
     *    +1   a dropped tool lands on `nodeKinds`' placeholder `tool_id`, so
     *         WHICH tool is a separate choice; D10 assumed the drop carried it
     *    ═══
     *     9
     *
     * The number is asserted rather than described, so that a future gesture
     * added to this path fails a test instead of quietly making the product
     * worse at the thing rubric 4 scores.
     *
     * ORDER IS CHOSEN TO SPEND NOTHING ON RE-SELECTION. Every gesture either
     * leaves the node it needs next already selected (`createAt` and `attachTo`
     * both call `setSelection`) or is a drag that changes no selection at all.
     * A test that wandered would have to click back onto the agent twice and
     * would report ten.
     *
     * It ends on the SERVER's answer, read off the app's own last validate
     * round trip.
     */
    /** What the journey below costs, measured. See the arithmetic above. */
    const BUDGET = 9

    const watch = watchConsole(page)
    const validations = watchValidation(page)
    let pointer = 0
    await openBuilder(page)

    // 1. The Blank card. It seeds `input -> output`, which is why there is no
    //    separate press for the output node.
    await page.locator('.template-card').filter({ hasText: 'Blank canvas' }).click()
    pointer += 1
    await expect(canvas(page)).toBeVisible()
    await expect(nodes(page)).toHaveCount(2)

    /*
     * 2. The agent tile, DRAGGED to a spot rather than clicked.
     *
     * A palette click drops at the viewport centre (`BuilderView.placeKind`),
     * and at 1440x900 the centre puts the card's top `in` port under the budget
     * meter and its bottom `out` port under the minimap - both of which sit
     * over the pane and swallow the pointer. An author would then have to move
     * the node before they could wire it, which is a ninth action nobody
     * counted. Dragging is the gesture that has a destination.
     */
    const pane = (await canvas(page).boundingBox())!
    await paletteTile(page, '2').dragTo(canvas(page), {
      // Measured off the pane rather than a literal: the upper-right quadrant
      // is clear of the template's own `input -> output` column on the left,
      // of the budget meter above the canvas, and of the minimap in the
      // bottom-right corner. All three swallow a pointer, and a card that lands
      // under one of them cannot be wired until it is moved.
      targetPosition: { x: pane.width * 0.68, y: pane.height * 0.22 },
    })
    pointer += 1
    await expect(nodes(page)).toHaveCount(3)

    const input = await firstOfKind(page, 'input')
    const output = await firstOfKind(page, 'output')
    const agent = await firstOfKind(page, 'agent')

    // 3. Convert to the authored arm. The drop selected the node, so the rail
    //    is already open on it and this is one click rather than two.
    await expect(inspector(page)).toBeVisible()
    await inspector(page)
      .getByRole('button', { name: /convert to an authored agent/i })
      .click()
    pointer += 1
    await expect(inspector(page).locator('[data-field="llm.model"]')).toBeVisible()

    // The five prompt fields, typed. Free by D10's own accounting, and done
    // here because the rail is already on this node.
    await fillField(page, 'role', 'Research analyst')
    await fillField(page, 'goal', 'Answer the question that arrives, with sources.')
    await fillField(page, 'backstory', 'Years of turning a vague question into a sourced answer.')
    await fillField(page, 'task.description', 'Research the request and report what you find.')
    await fillField(page, 'task.expected_output', 'A short report with one cited source per claim.')

    // 4. A model, chosen rather than inherited.
    await inspector(page)
      .locator('[data-field="llm.model"] select')
      .selectOption('qwen/qwen3.7-flash')
    pointer += 1

    /*
     * 5. Remove the template's OWN `idea -> result` edge.
     *
     * The Blank card ships wired, and its `modifyFirst` line says so: "Drop an
     * agent between the two nodes and connect it." D10 costed an empty
     * document, so this action does not appear in its list - leaving the direct
     * edge in place would produce a graph where the result can arrive without
     * the agent ever running, which validates and is not the graph the
     * criterion describes.
     *
     * One click to select and `Delete` to remove it; the key is free, and undo
     * is the confirmation, which is why there is no dialog (§4.4).
     */
    await page.locator('.vue-flow__edge').first().click({ force: true })
    pointer += 1
    await page.keyboard.press('Delete')
    await expect(edges(page)).toHaveCount(0)

    // 6-7. Two drags: the flow in, and the flow out.
    await dragTo(page, port(page, input.id, 'out'), targetPort(page, agent.id))
    pointer += 1
    await dragTo(page, port(page, agent.id, 'out'), targetPort(page, output.id))
    pointer += 1
    await expect(edges(page)).toHaveCount(2)

    // 8. A tool, dragged onto the agent. One commit: node and edge.
    await paletteTile(page, 'T').dragTo(agent.card)
    pointer += 1
    await expect(avatars(page, agent.id)).toHaveCount(1)

    // 9. Which tool. A fresh tool node lands on the placeholder `tool_id` that
    //    `nodeKinds.defaultConfig` mints - deliberately unset, so the
    //    inspector's first control is the one that matters - and the drop
    //    already selected it, so this is the select and nothing else. The tool
    //    is one that needs no key, or the graph would be invalid for a reason
    //    that has nothing to do with the budget.
    await inspector(page)
      .locator('[data-field="tool_id"] select')
      .selectOption('analyze_community_sentiment')
    pointer += 1

    await validationSettles(page)
    await expect(headline(page)).toContainText(/ready to publish/i)

    /*
     * The SERVER's word, and specifically the app's own last validate response
     * rather than a request this test composed. "The headline says ready" is
     * the claim a canvas makes about itself; `valid` is the claim the thing
     * that refuses a publish makes, and reading the app's own round trip is the
     * only version of it that proves the document ON THE CANVAS is the document
     * that was checked.
     */
    expect(validations.length, 'the canvas never validated').toBeGreaterThan(0)
    expect(validations[validations.length - 1], 'the last validation was not clean').toBe(true)

    expect(pointer, 'the click budget moved').toBe(BUDGET)
    expect(watch.unexpected).toEqual([])
  })
})
