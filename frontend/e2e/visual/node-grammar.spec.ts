import { expect, test, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

/**
 * 03 criterion 7 - the node grammar, photographed and asserted at working zoom.
 *
 * D5 gives a node three independent channels to say what it is: a SILHOUETTE
 * (card or pill), an ACCENT (the colour-filled squircle behind its icon) and an
 * EYEBROW (the kind's name in 11px mono). Three, rather than one, because each
 * one fails at a different moment - the eyebrow at 5.5px is unreadable, the
 * accent is a smear on a card whose whole body is tinted, and the silhouette
 * survives both. This file is the only place any of the three has an answer,
 * for the reason MISSION.md §9 trap 13 states: a jsdom mount asserts structure
 * and never asks how wide anything ended up, nor what colour it came out.
 *
 * ## Why zoom 0.5 specifically
 *
 * Not an arbitrary "zoomed out". It is the zoom at which D5's own argument
 * bites - `builder.css` sets the eyebrow at 11px, which is 5.5 rendered - and
 * it is the zoom `e2e/builder.spec.ts` already drags ports at, so the two files
 * are talking about the same canvas. A grammar that reads at 100% and dissolves
 * at 50% is a grammar for a screenshot rather than for an author.
 *
 * ## What is asserted and what is merely captured
 *
 * ASSERTED, per kind: the silhouette class, that the squircle's rendered
 * background is that kind's `accent` from `nodeKinds.ts`, and the eyebrow's
 * text. The accent is read as a COMPUTED colour off the live element, not as
 * the inline custom property that was written into it - a `--kind-accent` that
 * no rule consumes would pass the second reading and fail the eye.
 *
 * CAPTURED, and nothing more: the canvas at 0.5, the same canvas at 1.0 for a
 * critic who wants to read the labels, and one close-up per family. The PNGs go
 * to `benchmarks/ours/03/` and are NOT committed - `.gitignore`'s global `*.png`
 * covers them, and `benchmarks/README.md` says why: they are pictures of a
 * build, regenerated on demand, and a round's defects live in the ledger rather
 * than in its pixels. THIS FILE is the committed half.
 *
 * There is deliberately no `toHaveScreenshot` here. A pixel baseline for ten
 * cards would fail on a font hint and tell a reader nothing about the grammar;
 * `e2e/visual/builder-canvas.spec.ts` owns the sixteen baselines that ARE
 * comparisons, and this owns the assertions a picture cannot make.
 *
 * ## Running it
 *
 *   # from the WORKTREE ROOT, so `data/skills` and `output/` resolve
 *   SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8094 serve.exe
 *   E2E_API_TARGET=http://127.0.0.1:8094 E2E_UI_PORT=5278 \
 *     npx playwright test e2e/visual/node-grammar.spec.ts --project=chromium
 */

/** `benchmarks/ours/03/`, relative to `frontend/`. */
const OUT = path.resolve(process.cwd(), '..', 'benchmarks', 'ours', '03')

/**
 * D5's table, transcribed from `frontend/src/data/nodeKinds.ts`.
 *
 * TRANSCRIBED RATHER THAN IMPORTED, and that is the one duplication in this
 * file that earns its place. Importing `NODE_KINDS` would make the test assert
 * that the card renders whatever `nodeKinds.ts` currently says - which is true
 * by construction and proves nothing about D5. Written out, the spec is a
 * second statement of the plan's own table, and a change to either side has to
 * be a change somebody made on purpose.
 */
const GRAMMAR = [
  { kind: 'input', silhouette: 'is-card', accent: 'rgb(170, 255, 205)', eyebrow: 'INPUT' },
  { kind: 'agent', silhouette: 'is-card', accent: 'rgb(153, 234, 249)', eyebrow: 'AGENT' },
  { kind: 'crew', silhouette: 'is-card', accent: 'rgb(160, 196, 255)', eyebrow: 'CREW' },
  { kind: 'gate', silhouette: 'is-card', accent: 'rgb(255, 224, 130)', eyebrow: 'GATE' },
  { kind: 'router', silhouette: 'is-card', accent: 'rgb(125, 198, 255)', eyebrow: 'ROUTER' },
  { kind: 'transform', silhouette: 'is-card', accent: 'rgb(179, 179, 179)', eyebrow: 'TRANSFORM' },
  { kind: 'output', silhouette: 'is-card', accent: 'rgb(123, 223, 242)', eyebrow: 'OUTPUT' },
  { kind: 'tool', silhouette: 'is-pill', accent: 'rgb(195, 166, 255)', eyebrow: 'TOOL' },
  { kind: 'mcp', silhouette: 'is-pill', accent: 'rgb(213, 184, 255)', eyebrow: 'MCP' },
  { kind: 'skill', silhouette: 'is-pill', accent: 'rgb(224, 204, 255)', eyebrow: 'SKILL' },
] as const

/**
 * One node of each of the ten kinds, laid out in two rows.
 *
 * No edges. The subject is the card's own grammar, and a wire crossing a
 * silhouette is exactly the thing that would make a capture ambiguous. The
 * document therefore reports `node-unreachable` for nine of the ten, which is
 * correct and irrelevant - nothing here reads the problems dock, and a card's
 * error rim is drawn on the card's OWN tenancy of `--node-gradient`, which is
 * §5.1's documented ordering and would be a different capture.
 */
const NODES = [
  {
    id: 'n_input',
    kind: 'input',
    label: 'Idea',
    position: { x: 0, y: 0 },
    config: { field: 'idea', label: null, max_chars: 2000, required: true },
  },
  {
    id: 'n_agent',
    kind: 'agent',
    label: 'Scoper',
    position: { x: 300, y: 0 },
    config: {
      tier: 'cheap',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      agent_id: 'scoper',
      tools: [],
    },
  },
  {
    id: 'n_crew',
    kind: 'crew',
    label: 'Market crew',
    position: { x: 600, y: 0 },
    config: {
      tier: 'escalation',
      max_iter: 2,
      guardrail_max_retries: 2,
      prompt_inputs: {},
      crew_id: 'market',
    },
  },
  {
    id: 'n_gate',
    kind: 'gate',
    label: 'Confirm scope',
    position: { x: 900, y: 0 },
    config: {
      message: 'Review this step.',
      editable_fields: ['idea'],
      max_turns: 1,
      expiry_seconds: 1800,
    },
  },
  {
    id: 'n_router',
    kind: 'router',
    label: 'Route scope',
    position: { x: 1200, y: 0 },
    config: {
      branches: [
        { label: 'approve', op: 'eq', key: 'decision', value: 'approve' },
        { label: 'otherwise', op: 'otherwise', key: null, value: null },
      ],
    },
  },
  {
    id: 'n_transform',
    kind: 'transform',
    label: 'Shape it',
    position: { x: 0, y: 300 },
    config: { op: 'pick', args: { source: '${state.out__n_agent}', key: 'summary' } },
  },
  {
    id: 'n_output',
    kind: 'output',
    label: 'Result',
    position: { x: 300, y: 300 },
    config: { body_key: 'markdown_body', source: null },
  },
  {
    id: 'n_tool',
    kind: 'tool',
    label: 'Scrape',
    position: { x: 600, y: 300 },
    config: { tool_id: 'firecrawl_scrape', params: {}, credential_id: null },
  },
  {
    id: 'n_mcp',
    kind: 'mcp',
    label: 'Sandbox',
    position: { x: 900, y: 300 },
    config: { server_id: null, server_hint: null, tool_names: [], credential_id: null },
  },
  {
    id: 'n_skill',
    kind: 'skill',
    label: 'House style',
    position: { x: 1200, y: 300 },
    config: { skill_id: null, skill_name: 'house-style' },
  },
] as const

const canvas = (page: Page) => page.locator('.builder-flow')

/** The card of one kind, addressed by the class `builder.css` itself selects on. */
const cardOf = (page: Page, kind: string) => page.locator(`.workflow-node.is-kind-${kind}`)

/** Vue Flow's pane transform, which is where the real zoom lives. */
async function zoomLevel(page: Page): Promise<number> {
  return page
    .locator('.builder-flow .vue-flow__transformationpane')
    .evaluate((el) => new DOMMatrixReadOnly(window.getComputedStyle(el).transform).a)
}

/**
 * Wheel the pane to a zoom and report where it actually landed.
 *
 * d3-zoom scales by `2 ** (-deltaY / 500)`, so the delta for a ratio is
 * `-500 * log2(ratio)`. Computed rather than hunted for with the `+` button,
 * whose step has nothing to do with 0.5 - and READ BACK, because a wheel the
 * zoom limits clamped would otherwise be photographed as if it had worked.
 */
async function zoomTo(page: Page, target: number): Promise<number> {
  const from = await zoomLevel(page)
  const box = (await canvas(page).boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.wheel(0, -500 * Math.log2(target / from))
  await expect.poll(() => zoomLevel(page)).toBeCloseTo(target, 1)
  return zoomLevel(page)
}

/**
 * Wait out `BuilderCanvas`'s settling re-fits before photographing.
 *
 * §14 defect 4: the canvas fits its viewport before the budget meter and the
 * problems dock have taken their height, so a capture taken too early is a
 * photograph of an intermediate zoom - a baseline that will not reproduce and
 * that gets blamed on CSS.
 */
async function settle(page: Page): Promise<void> {
  await page.waitForTimeout(1600)
}

let documentId = ''

test.describe('the node grammar at working zoom', () => {
  test.beforeAll(async ({ request }) => {
    const created = await request.post('/api/builder/workflows', {
      data: {
        document: {
          schema: 'builder.flow/v1',
          name: 'Node grammar',
          version: 1,
          input_field: 'idea',
          nodes: NODES,
          edges: [],
          joins: {},
        },
        expected_version: null,
      },
    })
    expect(created.status(), await created.text()).toBe(201)
    documentId = ((await created.json()) as { id: string }).id
  })

  test.afterAll(async ({ request }) => {
    if (documentId) await request.delete(`/api/builder/workflows/${documentId}`)
  })

  test('draws all ten kinds with a distinct silhouette, accent and eyebrow at 0.5', async ({
    page,
  }) => {
    mkdirSync(OUT, { recursive: true })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(`/#/build/${documentId}`)
    await expect(page.locator('.vue-flow__node')).toHaveCount(10)
    await settle(page)

    const reached = await zoomTo(page, 0.5)
    // Recorded in the capture's name, so a picture taken at a clamped zoom
    // cannot be filed as if it were the one the criterion asked for.
    expect(reached, 'the pane did not reach 0.5').toBeCloseTo(0.5, 1)
    await page.screenshot({ path: path.join(OUT, '03-node-grammar-zoom050-1440x900-dark.png') })

    for (const entry of GRAMMAR) {
      const card = cardOf(page, entry.kind)
      await expect(card, `${entry.kind}: no card on the canvas`).toBeVisible()

      // 1. SILHOUETTE. `is-card` is written out rather than left as the absence
      //    of `is-pill`, so both halves of the channel are assertable.
      await expect(card, entry.kind).toHaveClass(new RegExp(`\\b${entry.silhouette}\\b`))
      const other = entry.silhouette === 'is-card' ? 'is-pill' : 'is-card'
      await expect(card, entry.kind).not.toHaveClass(new RegExp(`\\b${other}\\b`))

      // 2. ACCENT, read as the RESOLVED background of the squircle rather than
      //    as the custom property written into it. A `--kind-accent` no rule
      //    consumes would satisfy the inline reading and be invisible on screen.
      const squircle = card.locator('.builder-kind-squircle')
      await expect(squircle, entry.kind).toHaveCount(1)
      expect(
        await squircle.evaluate((el) => window.getComputedStyle(el).backgroundColor),
        `${entry.kind}: the squircle is not its own accent`,
      ).toBe(entry.accent)

      /*
       * 3. EYEBROW. §5.2 prefixes it with the node's 1-based document ORDER -
       *    `01 · INPUT` - so the assertion is on the shape rather than on the
       *    bare word: the position is a fact about this document's node list
       *    and would change if the fixture were reordered, while the kind name
       *    is what D5's channel is. This is the one channel that does NOT
       *    survive this zoom - 11px renders at 5.5 - which is the whole reason
       *    the other two exist.
       */
      expect(
        (await card.locator('.builder-eyebrow').innerText()).trim(),
        entry.kind,
      ).toMatch(new RegExp(String.raw`^\d+ · ${entry.eyebrow}$`))
    }

    // Every accent distinct, which is what makes the channel a channel. Ten
    // colours that happened to include a duplicate would pass every assertion
    // above and still leave two kinds indistinguishable.
    const accents = new Set(GRAMMAR.map((entry) => entry.accent))
    expect(accents.size, 'two kinds share an accent').toBe(GRAMMAR.length)
  })

  test('captures the same ten at 1.0 and one close-up per family', async ({ page }) => {
    /*
     * The reading capture. At 0.5 a critic can compare silhouettes and cannot
     * read a word, so the side-by-side against Flowise v2 needs both - and the
     * two close-ups are what make "a pill can never be mistaken for a step"
     * checkable by eye rather than by class name.
     */
    mkdirSync(OUT, { recursive: true })
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto(`/#/build/${documentId}`)
    await expect(page.locator('.vue-flow__node')).toHaveCount(10)
    await settle(page)

    await zoomTo(page, 1)
    await page.screenshot({ path: path.join(OUT, '03-node-grammar-zoom100-1440x900-dark.png') })

    await cardOf(page, 'agent').screenshot({
      path: path.join(OUT, '03-node-card-agent-1440x900-dark.png'),
    })
    await cardOf(page, 'tool').screenshot({
      path: path.join(OUT, '03-node-pill-tool-1440x900-dark.png'),
    })
  })
})
