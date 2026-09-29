// Phase 6.1 — the rules every test runs under (fixtures.ts) do catch what they're for: each is broken here once,
// with `enforceRules` off, and must show up in `broken`.

import { API_URL } from './env';
import { expect, test } from './fixtures';

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

  test('a Content-Security-Policy violation', async ({ page, broken }) => {
    await page.evaluate(() => fetch('https://example.com/e2e').catch(() => null));
    await expect.poll(() => broken).toEqual([expect.stringMatching(/^a connect-src violation: https:\/\/example\.com\/e2e /)]);
  });

  test('a Trusted Types violation', async ({ page, broken }) => {
    const thrown = await page.evaluate(() => {
      try {
        document.body.innerHTML = '<p>untrusted</p>';
        return null;
      } catch (error) {
        return (error as Error).name;
      }
    });
    expect(thrown).toBe('TypeError');
    await expect.poll(() => broken).toEqual([expect.stringMatching(/^a require-trusted-types-for violation: trusted-types-sink \(Element innerHTML\|<p>untrusted/)]);
  });

  test('an uncaught error in the page', async ({ page, broken }) => {
    await page.evaluate(() => {
      setTimeout(() => {
        throw new Error('thrown by harness.spec.ts');
      });
    });
    await expect.poll(() => broken).toEqual(['an uncaught error: thrown by harness.spec.ts']);
  });

  test('a 5xx from the API', async ({ page, broken }) => {
    await page.route(`${API_URL}/api/v1/health`, (route) => route.fulfill({ status: 503, headers: { 'access-control-allow-origin': '*' }, body: '{}' }));
    await page.evaluate((url) => fetch(url).catch(() => null), `${API_URL}/api/v1/health`);
    await expect.poll(() => broken).toEqual([`the API's 503: GET ${API_URL}/api/v1/health`]);
  });
});
