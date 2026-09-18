import { expect, test } from '@playwright/test'

/** Runs against the isolated seeded backend, never launches an agent.
 * Start: python -m tests.service.governance_fixture
 * E2E_API_TARGET=http://127.0.0.1:8109 npx playwright test governance-insights
 */
test('mines real stored evidence, filters workflows and opens a supporting run', async ({ page, request }) => {
  const who = await request.get('/api/admin/whoami')
  test.skip(!(await who.json()).admin, 'Requires the synthetic admin fixture.')
  const answer = await request.get('/api/admin/insights?workflow_id=evidence-review')
  test.skip(!answer.ok(), 'Requires the Governance Insights API.')
  const evidence = await answer.json()
  test.skip(!evidence.findings?.length, 'Start tests.service.governance_fixture for seeded evidence.')
  const unexpected: string[] = []
  page.on('pageerror', error => unexpected.push(error.message))
  page.on('console', message => { if (message.type() === 'error') unexpected.push(message.text()) })

  await page.goto('/#/admin')
  await page.getByTestId('admin-tab-insights').click()
  const panel = page.locator('#admin-panel-insights')
  await expect(panel.getByTestId('admin-insight-findings')).toBeVisible()
  await expect(panel.getByTestId('admin-insights-small-sample')).toContainText('sparse-review')
  await expect(panel.getByTestId('admin-insights-coverage')).toContainText('7')
  await panel.getByTestId('admin-insights-workflow').selectOption('evidence-review')
  await expect(panel.getByTestId('admin-insight-findings')).toContainText('2 / 3')
  await expect(panel).toContainText(/estimate/i)
  await expect(panel).toContainText(/sequence|frame/i)
  await panel.getByTestId('admin-insight-run-evidence-review-0').first().click()
  const drawer = page.locator('.admin-drawer')
  await expect(drawer).toBeVisible()
  await expect(drawer).toContainText('evidence-review')
  await expect(drawer).toContainText('Add sources before approval')
  await expect(drawer).not.toContainText('unknown')
  await page.getByRole('button', { name: /close/i }).last().click()

  await panel.getByTestId('admin-insights-workflow').selectOption('quiet-review')
  await expect(panel.getByTestId('admin-insights-empty')).toBeVisible()
  await panel.getByTestId('admin-insights-workflow').selectOption('sparse-review')
  await expect(panel.getByTestId('admin-insights-small-sample')).toContainText('1 of 3')
  await panel.getByTestId('admin-insights-workflow').selectOption('')
  await panel.getByTestId('admin-insights-refresh').click()
  await expect(panel.getByTestId('admin-insight-findings')).toBeVisible()

  await page.screenshot({ path: 'test-results/governance-insights-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(panel.getByRole('heading', { name: 'Governance insights' })).toBeVisible()
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
  expect(fits).toBe(true)
  await page.screenshot({ path: 'test-results/governance-insights-mobile.png', fullPage: true })
  expect(unexpected).toEqual([])
})
