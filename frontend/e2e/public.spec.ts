// Phase 6.1 — the public pages, signed out: each renders its heading, under the harness's rules (no CSP or
// Trusted Types violation, no uncaught error, nothing from another host); an unknown address gets the 404 page.

import { expect, test } from './fixtures';

test.use({ storageState: { cookies: [], origins: [] } });

const PAGES: Array<[path: string, heading: string | RegExp]> = [
  ['/', /^Send the link\./],
  ['/login/', 'Welcome back'],
  ['/manual/', 'User manual'],
  ['/manual/install-mcp/', 'Connect Claude to Shurly'],
  ['/manual/make-a-campaign/', 'Make a campaign from a CSV'],
  ['/manual/read-your-analytics/', 'Read your analytics'],
];

for (const [path, heading] of PAGES) {
  test(`${path} renders`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(heading);
  });
}

test('an unknown address gets the 404 page', async ({ page }) => {
  const response = await page.goto('/no-such-page/');
  expect(response?.status()).toBe(404);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('This page took a wrong turn.');
});

test("the landing's mock is Griddo's proposal for Tufts, told the same way throughout", async ({ page }) => {
  await page.goto('/');
  const hero = page.locator('[data-hero]');
  // Griddo's logo, from this site: the harness fails the test on anything from another host or against the CSP.
  const logo = hero.locator('img[src="/logos/logo-griddo-g-s-w.svg"]');
  await expect(logo).toBeVisible();
  await expect.poll(() => logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(hero).toContainText('Q4 proposal — Tufts University');
  await expect(hero).toContainText('/q4-tufts');
  await expect(page.locator('body')).not.toContainText(/acme/i);
});
