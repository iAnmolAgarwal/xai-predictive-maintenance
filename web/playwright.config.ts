import { defineConfig, devices } from '@playwright/test';

// The Phase-3 smoke runs against the MSW-backed production-shaped build, so it
// needs no API container, no broker and no trained model.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : '50%',
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
  },
  // 1440 px is the wireframe reference width, where the alert rail is docked
  // rather than an overlay drawer (R8).
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
  // PLAYWRIGHT_BASE_URL points the suite at an already-running server (the
  // compose stack in Phase 5); otherwise the suite builds and previews the
  // MSW-backed bundle itself.
  ...(process.env.PLAYWRIGHT_BASE_URL
    ? {}
    : {
        webServer: {
          command: 'pnpm build:mock && pnpm preview:mock --host 127.0.0.1 --port 4173',
          url: 'http://127.0.0.1:4173',
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
        },
      }),
});
