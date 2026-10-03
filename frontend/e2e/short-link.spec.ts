// ROADMAP 3.9.2 — someone opens a short link that doesn't lead anywhere: the API answers their browser with a page,
// not JSON, with the same status. And a social network's crawler gets the redirect, or, for a link whose preview is
// rewritten (8.7), the link's preview page. The harness fails on
// anything a page's CSP blocks or any request to another host, so each page's hashed style and its lack of other
// requests are checked here too.

import { expect, test } from './fixtures';
import { API_URL, WEB_URL } from './env';
import { clickLink } from './helpers';

test("a code that doesn't exist: the page, with its 404", async ({ page }) => {
  const response = await page.goto(`${API_URL}/e2e-nope-${Date.now()}`);

  expect(response?.status()).toBe(404);
  await expect(page).toHaveTitle('This link doesn’t lead anywhere');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('This link doesn’t lead anywhere');
});

test('a link whose visits are used up: its own page, with its 410', async ({ page, ownerApi, request }) => {
  const made = await ownerApi.post('/api/v1/urls', { data: { url: 'https://example.com/e2e-used-up', max_visits: 1 } });
  expect(made.ok()).toBeTruthy();
  const { short_code: code } = (await made.json()) as { short_code: string };
  await clickLink(request, code); // its one visit

  const response = await page.goto(`${API_URL}/${code}`);

  expect(response?.status()).toBe(410);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('This link has reached its limit');
});

test.describe("a social network's crawler", () => {
  test.use({ userAgent: 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)' });

  test('of a link whose preview is the page’s own: the redirect, to read it there', async ({ page, ownerApi }) => {
    // Phase 8.7 — the destination is one on this machine, so the harness allows it.
    const made = await ownerApi.post('/api/v1/urls', { data: { url: `${WEB_URL}/styleguide/` } });
    expect(made.ok()).toBeTruthy();
    const { short_code: code } = (await made.json()) as { short_code: string };

    await page.goto(`${API_URL}/${code}`);

    await expect(page).toHaveURL(`${WEB_URL}/styleguide/`);
  });

  test('of a link whose preview is rewritten: the preview page, styled within its CSP', async ({ page, ownerApi }) => {
    // Its refresh goes on to the destination: one on this machine, so the harness allows it.
    const made = await ownerApi.post('/api/v1/urls', { data: { url: `${WEB_URL}/`, og_title: 'Our own title' } });
    expect(made.ok()).toBeTruthy();
    const { short_code: code } = (await made.json()) as { short_code: string };

    const response = await page.goto(`${API_URL}/${code}`);

    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Our own title');
    await expect(page.getByRole('link', { name: /Continue to destination/ })).toBeVisible();
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundImage)).toContain('linear-gradient');
  });
});
