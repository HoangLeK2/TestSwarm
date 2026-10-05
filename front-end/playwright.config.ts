import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.ADL_E2E_PORT ?? 3310);
const baseURL = process.env.ADL_E2E_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  // All cases share one Next dev server. A single worker keeps cold dynamic
  // route compilation deterministic instead of timing out while workers
  // contend for the same compiler.
  workers: 1,
  reporter: [
    ['line'],
    ['html', { outputFolder: 'test-results/ai-device-lab-html', open: 'never' }]
  ],
  outputDir: 'test-results/ai-device-lab-artifacts',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 5_000,
    navigationTimeout: 30_000
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] }
    }
  ],
  webServer: process.env.ADL_E2E_BASE_URL
    ? undefined
    : {
        command: `pnpm exec next dev --hostname 127.0.0.1 --port ${port}`,
        url: baseURL,
        reuseExistingServer: true,
        timeout: 120_000
      }
});
