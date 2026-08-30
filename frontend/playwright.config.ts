import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end configuration for Validator Studio.
 *
 * The suite is written to run unchanged against two very different targets:
 *
 *   1. A local Vite dev server proxying to the no-cost `SYNTHETIC=1` backend.
 *   2. A deployed origin (Render), where the API is served from the same host.
 *
 * `E2E_BASE_URL` is what switches between them. When it is set, nothing is
 * started locally - Playwright simply drives the URL it was given. When it is
 * unset, the `webServer` below starts the e2e Vite server described in
 * `e2e/vite.e2e.config.ts`.
 *
 * There is deliberately no `webServer` entry for the Python API. The default
 * dev proxy in `vite.config.ts` points at `127.0.0.1:8000`, which is the paid
 * backend; an automated suite must not be able to start or launch runs against
 * it. Start the free one yourself, from the repository root:
 *
 *   SYNTHETIC=1 PORT=8099 ./.venv/Scripts/serve.exe
 */
const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5273'
const usesLocalServer = !process.env.E2E_BASE_URL

export default defineConfig({
  testDir: './e2e',
  // A full journey drives two durable gate round trips through a real
  // WebSocket, so it is slower than a unit test but never slow enough to need
  // minutes. 90s is generous for the synthetic backend and still tight enough
  // that a hang fails rather than hangs the run.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // Runs share one backend and one browser profile's localStorage semantics;
  // serial execution keeps a stray run from another worker out of the picture.
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  outputDir: './test-results',

  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    // The deployed site is HTTPS with a real certificate; keep verification on.
    ignoreHTTPSErrors: false,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],

  ...(usesLocalServer
    ? {
        webServer: {
          command: 'npx vite --config e2e/vite.e2e.config.ts',
          url: baseURL,
          reuseExistingServer: true,
          timeout: 60_000,
          stdout: 'ignore',
          stderr: 'pipe',
        },
      }
    : {}),
})
