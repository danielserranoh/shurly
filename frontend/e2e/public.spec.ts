// Phase 6.1 — the public pages, signed out: each renders its heading, under the harness's rules (no CSP or
// Trusted Types violation, no uncaught error, nothing from another host); an unknown address gets the 404 page.

import { expect, test } from './fixtures';

test.use({ storageState: { cookies: [], origins: [] } });

const PAGES: Array<[path: string, heading: string | RegExp]> = [
  ['/', /^Send the link\./],
  ['/login/', 'Welcome back'],
  ['/manual/', 'User manual'],
  ['/manual/install-mcp/', 'Connect Claude to Shurly'],
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
