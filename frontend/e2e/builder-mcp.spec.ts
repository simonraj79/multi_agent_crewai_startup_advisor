import { expect, test, type Locator, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

/**
 * 07 criterion 9 - an MCP server added, discovered and attached, in the browser.
 *
 * Plan 07's Status recorded this `partial`: *"The panel is built and
 * unit-proved; the browser is not."* This is the browser, and the discovery it
 * drives is REAL - a live loopback MCP server, `MCPToolResolver`, a socket -
 * not an injected `Resolver` and not a stubbed route.
 *
 * That distinction earned its keep the moment it was tried. Every prior test
 * injected a fake resolver, which is the seam's whole purpose and is also why
 * nothing had ever constructed the real one: `_default_resolver` called
 * `MCPToolResolver()` with no arguments, and discovery against ANY real server
 * answered `status: error` with a Python `TypeError` in the sentence where an
 * author expected to read why their server would not connect. Fixed on the
 * backend package's branch, found here.
 *
 * ## Running it - the fixture server is a second process
 *
 * `playwright.config.ts` deliberately starts no Python, so the fixture is
 * started by hand and named through the environment. It is
 * `tests/service/mcp_fixture_server.py`, which serves two tools over streamable
 * HTTP on loopback and gives one of them an injection phrase ON PURPOSE, so the
 * suspicious rule is testing the real pattern list:
 *
 *   # 1. the fixture server, from the worktree root
 *   python -c "import sys; sys.path.insert(0,'tests/service'); \
 *     from mcp_fixture_server import build_server; \
 *     build_server(port=8791).run(transport='streamable-http')"
 *
 *   # 2. the free backend, with loopback dialling allowed
 *   SYNTHETIC=1 PORT=8094 MCP_ALLOW_INSECURE_LOCAL=1 CREDENTIALS_MASTER_KEY=... serve.exe
 *
 *   # 3. this suite
 *   E2E_MCP_URL=http://127.0.0.1:8791/mcp E2E_API_TARGET=http://127.0.0.1:8094 \
 *     E2E_UI_PORT=5278 npx playwright test e2e/builder-mcp.spec.ts
 *
 * `MCP_ALLOW_INSECURE_LOCAL` is not optional and its absence does not look like
 * a missing flag: `refuse_private_target` answers *"is not https, and only https
 * targets are dialled"*, which reads like a rule about the fixture rather than
 * about the deployment. The flag's own docstring names this fixture.
 *
 * WITHOUT `E2E_MCP_URL` the file SKIPS rather than stubbing. A stubbed discovery
 * would have passed against the broken resolver above, which is the whole
 * argument: a double that diverges from its subject certifies nothing.
 */

const MCP_URL = process.env.E2E_MCP_URL ?? ''

const ALLOWED_CONSOLE_ERROR: RegExp | null = null

function watchConsole(page: Page): string[] {
  const unexpected: string[] = []
  const record = (text: string): void => {
    if (ALLOWED_CONSOLE_ERROR?.test(text)) return
    unexpected.push(text)
  }
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text())
  })
  page.on('pageerror', (error) => record(`uncaught: ${error.message}`))
  return unexpected
}

const canvas = (page: Page): Locator => page.locator('.builder-flow')
const nodes = (page: Page): Locator => page.locator('.vue-flow__node:has(.workflow-node)')
const inspector = (page: Page): Locator => page.locator('[data-testid="inspector-rail"]')
const paletteTile = (page: Page, hotkey: string): Locator =>
  page.locator(`.builder-tile[aria-keyshortcuts="${hotkey}"]`)
const agentCard = (page: Page): Locator =>
  page.locator('.vue-flow__node:has(.workflow-node.is-kind-agent)').first()

async function clearDocuments(page: Page): Promise<void> {
  const listed = await page.request.get('/api/builder/workflows')
  if (!listed.ok()) return
  for (const entry of (await listed.json()) as { id: string }[]) {
    await page.request.delete(`/api/builder/workflows/${entry.id}`)
  }
}

/** Every server row this caller owns. The store is per-user and shared per run. */
async function clearServers(page: Page): Promise<void> {
  const listed = await page.request.get('/api/builder/mcp/servers')
  if (!listed.ok()) return
  const body = (await listed.json()) as { servers: { id: string }[] }
  for (const server of body.servers) {
    await page.request.delete(`/api/builder/mcp/servers/${server.id}`)
  }
}

/**
 * One capture for the judge, into `benchmarks/ours/07/`.
 *
 * PNGs are gitignored and the spec is not: `benchmarks/README.md` says why -
 * they are pictures of a build, regenerated on demand, and a round's defects
 * live in the ledger rather than in its pixels. Taken at the END of a passing
 * test, so a capture can never be of a state the assertions rejected.
 */
async function capture(page: Page, name: string): Promise<void> {
  const out = path.resolve(process.cwd(), '..', 'benchmarks', 'ours', '07')
  mkdirSync(out, { recursive: true })
  await page.screenshot({ path: path.join(out, `07-${name}-1440x900-dark.png`) })
}

test.describe('an MCP server, added and discovered for real', () => {
  test.skip(
    MCP_URL === '',
    'set E2E_MCP_URL to a running tests/service/mcp_fixture_server.py - see this file’s header',
  )

  test.beforeEach(async ({ page }) => {
    await clearDocuments(page)
    await clearServers(page)
  })

  test.afterEach(async ({ page }) => {
    await clearDocuments(page)
    await clearServers(page)
  })

  test('adds a server by URL, discovers it, checks two tools and shows each preview', async ({
    page,
  }) => {
    const errors = watchConsole(page)
    await page.goto('/#/build')
    await page.locator('.template-card').filter({ hasText: 'Minimal gated agent' }).click()
    await expect(canvas(page)).toBeVisible()
    await expect(nodes(page)).toHaveCount(4)

    // An MCP node hung off the agent, so the panel is reached from the node
    // that will carry the server rather than from a settings page elsewhere.
    await paletteTile(page, 'M').dragTo(agentCard(page))
    await expect(nodes(page)).toHaveCount(5)
    await expect(inspector(page)).toBeVisible()

    /*
     * DOCKED, never a modal (R15). Asserted as an absence, because "no modal"
     * is a property a screenshot cannot show and a `role=dialog` count can.
     *
     * The disclosure is OPENED, not TOGGLED. `McpForm` opens it itself when the
     * caller has no servers yet - which is the right behaviour and is exactly
     * the state this test starts in, so a blind click would shut the panel and
     * the failure would read as a missing component.
     */
    const panel = inspector(page).locator('[data-testid="mcp-panel"]')
    if ((await panel.count()) === 0) {
      await inspector(page).locator('[data-testid="mcp-manage"]').click()
    }
    await expect(panel).toBeVisible()
    expect(await page.locator('[role="dialog"]').count(), 'a dialog opened').toBe(0)

    await inspector(page).locator('[data-testid="mcp-add"]').click()
    await inspector(page).locator('[data-testid="mcp-label"]').fill('Probe')
    await inspector(page).locator('[data-testid="mcp-transport"]').selectOption('http')
    await inspector(page).locator('[data-testid="mcp-url"]').fill(MCP_URL)
    await inspector(page).locator('[data-testid="mcp-save"]').click()

    const row = inspector(page).locator('[data-testid="mcp-row"]').first()
    await expect(row).toBeVisible()
    // The URL is MASKED in the list, because plenty of hosted MCP servers put a
    // token in the path and a panel showing the whole URL publishes a
    // credential to anyone who can see the screen.
    await expect(row.locator('[data-testid="mcp-masked-url"]')).toBeVisible()

    // Discovery: a real socket to a real server. The row's status is the
    // server's own answer, not a hope.
    await row.locator('[data-testid="mcp-discover"]').click()
    const discovered = row.locator('[data-testid="mcp-tool"]')
    await expect(discovered).toHaveCount(2, { timeout: 30_000 })
    await expect(row.locator('[data-testid="mcp-row-error"]')).toHaveCount(0)
    await expect(row.locator('[data-testid="mcp-status"]')).toContainText(/authorized/i)

    /*
     * The suspicious one is STILL SELECTABLE, and is marked (decision 8,
     * provisional). `act as` and `ignore previous instructions` are ordinary
     * English as often as they are an attack, and a picker that quietly dropped
     * rows would be the quietly-divergent double this repository keeps warning
     * about - with the added twist that the author would never learn the tool
     * existed.
     */
    const flagged = discovered.filter({ has: page.locator('[data-testid="mcp-suspicious"]') })
    await expect(flagged).toHaveCount(1)
    await expect(flagged.locator('input[type="checkbox"]')).toBeEnabled()

    // Both tools, by the names the server gave them - read off the panel rather
    // than written here, because CrewAI prefixes a discovered name with the
    // server's own address and that prefix is not this test's business.
    const names = await discovered
      .locator('input[type="checkbox"]')
      .evaluateAll((els) => els.map((el) => el.getAttribute('data-tool')!))
    expect(names).toHaveLength(2)
    for (const name of names) {
      await row.locator(`input[type="checkbox"][data-tool="${name}"]`).check()
    }

    // The read-only parameter preview, per checked tool. Read-only because the
    // AGENT supplies the arguments at run time - a form here would be a form
    // whose values nothing reads.
    await expect(row.locator('[data-testid="mcp-params"]')).toHaveCount(2)
    await expect(row.locator('[data-testid="mcp-params"]').first()).toContainText(':')

    await row.locator('[data-testid="mcp-attach"]').click()

    // The node now names the server and its two tools, in the form...
    await expect(inspector(page).locator('[data-testid="mcp-server-summary"]')).toBeVisible()
    await expect(inspector(page).locator('[data-testid="mcp-count"]')).toContainText('2')
    await expect(inspector(page).locator('[data-testid="mcp-tools"]')).toContainText(names[0])
    // ...and the same two previews are in the FORM, which is the surface an
    // author returns to rather than the panel they added the server from.
    await expect(inspector(page).locator('[data-testid="mcp-form-params"]')).toHaveCount(2)

    // ...and on the canvas: the pill says which server and how many tools, and
    // the agent wears the avatar that says it has these hands (03 D6).
    const pill = page.locator('.workflow-node.is-kind-mcp')
    await expect(pill).toContainText('2 tools')
    const agentId = (await agentCard(page).getAttribute('data-id'))!
    await expect(
      page.locator(
        `.vue-flow__node[data-id="${agentId}"] .builder-attach-avatar[data-attachment-kind="mcp"]`,
      ),
    ).toHaveCount(1)

await capture(page, 'server-discovered-attached')

    expect(errors).toEqual([])
  })
})
