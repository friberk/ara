import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5180', trace: 'retain-on-failure', screenshot: 'only-on-failure', video: 'retain-on-failure' },
  // The research journey saves the fixture paper through the UI, so it must run on a fresh database
  // before specs that save the same paper through the API in their setup.
  projects: [
    { name: 'research', testMatch: /research\.spec\.ts/, use: { ...devices['Desktop Chrome'] } },
    { name: 'chromium', testIgnore: /research\.spec\.ts/, dependencies: ['research'], use: { ...devices['Desktop Chrome'] } },
  ],
})
