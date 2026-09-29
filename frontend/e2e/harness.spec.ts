// Phase 6.1 — the rules every test runs under (fixtures.ts) do catch what they're for: each is broken here once,
// with `enforceRules` off, and must show up in `broken`. Phase 6.4: the page reports the same breakages to the API
// itself (src/utils/error-reporter.ts), which logs them: that's checked here too.

import type { Page } from '@playwright/test';

import { API_URL } from './env';
import { expect, test } from './fixtures';

/** What the page reports to the API (a POST it answers with 204) when `breakIt` breaks something. */
async function reportOf(page: Page, breakIt: () => Promise<unknown>): Promise<unknown> {
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url() === `${API_URL}/api/v1/client-errors` && r.request().method() === 'POST'),
    breakIt(),
  ]);
  expect(response.status()).toBe(204);
  return response.request().postDataJSON();
}

test.describe('the harness catches', () => {
  test.use({ enforceRules: false, storageState: { cookies: [], origins: [] } });

  test.beforeEach(async ({ page }) => {
    await page.goto('/login/');
  });

  test('a request to another host, and blocks it', async ({ page, broken }) => {
    await page.evaluate(() => {
      new Image().src = 'https://example.com/e2e.png';
    });
    await expect.poll(() => broken).toEqual(['a request to another host: GET https://example.com/e2e.png']);
  });

  test('a Content-Security-Policy violation, which the page reports', async ({ page, broken }) => {
    const sent = await reportOf(page, () => page.evaluate(() => fetch('https://example.com/e2e').catch(() => null)));
    await expect.poll(() => broken).toEqual([expect.stringMatching(/^a connect-src violation: https:\/\/example\.com\/e2e /)]);
    expect(sent).toMatchObject({ kind: 'csp', message: 'connect-src blocked https://example.com', page: '/login/' });
  });

  test('a Trusted Types violation, which the page reports', async ({ page, broken }) => {
    let thrown: string | null = null;
    const sent = await reportOf(page, async () => {
      thrown = await page.evaluate(() => {
        try {
          document.body.innerHTML = '<p>untrusted</p>';
          return null;
        } catch (error) {
          return (error as Error).name;
        }
      });
    });
    expect(thrown).toBe('TypeError');
    await expect.poll(() => broken).toEqual([expect.stringMatching(/^a require-trusted-types-for violation: trusted-types-sink \(Element innerHTML\|<p>untrusted/)]);
    expect(sent).toMatchObject({ kind: 'csp', message: 'require-trusted-types-for blocked trusted-types-sink', page: '/login/' });
  });

  test('an uncaught error in the page, which the page reports', async ({ page, broken }) => {
    const sent = await reportOf(page, () =>
      page.evaluate(() => {
        setTimeout(() => {
          throw new Error('thrown by harness.spec.ts');
        });
      }),
    );
    await expect.poll(() => broken).toEqual(['an uncaught error: thrown by harness.spec.ts']);
    expect(sent).toMatchObject({ kind: 'error', message: 'Error: thrown by harness.spec.ts', page: '/login/' });
  });

  test('a 5xx from the API', async ({ page, broken }) => {
    await page.route(`${API_URL}/api/v1/health`, (route) => route.fulfill({ status: 503, headers: { 'access-control-allow-origin': '*' }, body: '{}' }));
    await page.evaluate((url) => fetch(url).catch(() => null), `${API_URL}/api/v1/health`);
    await expect.poll(() => broken).toEqual([`the API's 503: GET ${API_URL}/api/v1/health`]);
  });
});
