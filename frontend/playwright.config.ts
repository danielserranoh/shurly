// Phase 6.1 — the end-to-end tests (e2e/): the production build, served by `astro preview`, in Chromium, the
// browser that enforces the pages' Trusted Types; against the real API, with a fake Google (tests/e2e/app.py), on
// a throwaway PostgreSQL. `npm run e2e`; docs/TESTING.md has the setup.

import { defineConfig, devices } from '@playwright/test';

import { API_URL, OWNER_STATE, WEB_URL } from './e2e/env';

const CI = Boolean(process.env.CI);
const port = (url: string) => new URL(url).port;
// The API's log, a JSON line per request: in a file, not in the test run's output.
const API_LOG = 'frontend/e2e/.logs/api.log';

export default defineConfig({
  testDir: 'e2e',
  // One database, and specs that share its owner: one test at a time.
  workers: 1,
  fullyParallel: false,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    ...devices['Desktop Chrome'],
    // E2E_CHANNEL=chrome runs the installed Google Chrome instead of Playwright's Chromium.
    channel: process.env.E2E_CHANNEL || undefined,
    baseURL: WEB_URL,
    viewport: { width: 1440, height: 900 },
    locale: 'en-US',
    timezoneId: 'Europe/Madrid',
    reducedMotion: 'reduce',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /\.setup\.ts$/ },
    { name: 'chromium', testMatch: /\.spec\.ts$/, dependencies: ['setup'], use: { storageState: OWNER_STATE } },
  ],
  webServer: [
    {
      name: 'API',
      // E2E=1 for the wrapper's guard; DB_HOST and the rest of the database come from the environment.
      command: `mkdir -p ${API_LOG.replace(/\/[^/]+$/, '')} && uv run uvicorn tests.e2e.app:app --host 127.0.0.1 --port ${port(API_URL)} --no-access-log 2> ${API_LOG} || { tail -n 25 ${API_LOG} >&2; exit 1; }`,
      cwd: '..',
      url: `${API_URL}/api/v1/health/db`,
      env: { E2E: '1', E2E_API_URL: API_URL, E2E_WEB_URL: WEB_URL },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      name: 'Web',
      // The production build, pointed at the test API, then served as it will be.
      command: `npx astro build --config e2e/astro.config.mjs && npx astro preview --config e2e/astro.config.mjs --host 127.0.0.1 --port ${port(WEB_URL)} --ignore-lock`,
      url: `${WEB_URL}/login/`,
      env: { PUBLIC_API_URL: API_URL },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
