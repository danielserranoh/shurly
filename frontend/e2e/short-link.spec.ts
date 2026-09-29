// ROADMAP 3.9.2 — someone opens a short link that doesn't lead anywhere: the API answers their browser with a page,
// not JSON, with the same status. The harness fails on anything its CSP blocks or any request to another host, so
// the page's hashed style and its lack of other requests are checked here too.

import { expect, test } from './fixtures';
import { API_URL } from './env';
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
