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
 * A node's single inbound handle.
 *
 * An edge lands on a PORT, not on a card: Vue Flow completes a connection only
 * when the pointer is released on a handle (or inside `connectionRadius` of
 * one), and the centre of a 240px card is nowhere near the 9px handle at its
 * top edge. Dragging to `.workflow-node` therefore never connected anything -
 * it just held the gesture open until the hover timed out.
 */
function targetPort(page: Page, nodeId: string): Locator {
  return page.locator(`.vue-flow__handle.target[data-nodeid="${nodeId}"]`)
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

  test('walks to a problem from the panel, fixes it, publishes, and the graph launches', async ({
    page,
    request,
  }) => {
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
  })

  test('never presents an unchecked document as ready to publish', async ({ page }) => {
    /*
     * Spec section 6.2's named failure, on the first screen a visitor meets.
     *
     * "Blank canvas" hands over the same document `useBuilderDocument` is seeded
     * with, so its fingerprint never moved, the validation watcher never fired,
     * and ZERO `/api/builder/validate` requests were sent - measured with a
     * request spy. Over that the dock read `Ready to publish`, the publish
     * checklist ticked `Validation is current` and `No errors`, and the server
     * answers the same bytes with `no-input-node`. Every other template differs
     * from the seed and validated by accident, which is why this was invisible
     * anywhere except the one card a first-time visitor is most likely to click.
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

    await expect.poll(() => validates.length).toBeGreaterThan(before)
    await validationSettles(page)
    await expect(headline(page)).not.toContainText(/ready to publish/i)
    await expect(problemRow(page, 'no-input-node')).toBeVisible()

    // And the dialog refuses it, with the server's count rather than a tick.
    await page.keyboard.press('Control+Shift+P')
    const publish = page.locator('[aria-labelledby="publish-title"]')
    await expect(publish).toBeVisible()
    await expect(publish).toContainText(/error must be fixed|errors must be fixed/)
    await expect(publish.getByRole('button', { name: /^Publish$/ })).toBeDisabled()

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
