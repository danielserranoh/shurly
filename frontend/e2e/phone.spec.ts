// Phase 6.1 — on a phone (390 × 844): a link's page and its tabs, and a campaign's recipients as rows, sorted from
// "Sort by". Neither page scrolls sideways. What they show is made through the API: the other specs make it by hand.

import { devices } from '@playwright/test';

import { expect, test } from './fixtures';
import { clickLink } from './helpers';

// A phone's context (touch, mobile viewport), minus the browser choice: the project runs Chromium.
const { defaultBrowserType: _browser, ...phone } = devices['Pixel 7'];
test.use({ ...phone, viewport: { width: 390, height: 844 } });

const fitsTheScreen = () => document.documentElement.scrollWidth <= window.innerWidth;

test("a link's page: every tab, one after another", async ({ page, ownerApi, request }) => {
  const made = await ownerApi.post('/api/v1/urls', { data: { url: `https://example.com/e2e-phone/${Date.now()}` } });
  expect(made.ok()).toBeTruthy();
  const { short_code: code } = (await made.json()) as { short_code: string };
  await clickLink(request, code);

  await page.goto(`/dashboard/link/?code=${code}`);
  await expect(page.locator('[data-stat="clicks"]')).toHaveText('1');
  for (const name of ['By context', 'By location', 'Visits', 'By time']) {
    await page.getByRole('tab', { name }).click();
    await expect(page.getByRole('tab', { name })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tabpanel', { name })).toBeVisible();
    if (name === 'Visits') await expect(page.locator('[data-visits-count]')).toHaveText('1–1 of 1');
  }
  expect(await page.evaluate(fitsTheScreen)).toBe(true);
});

test("a campaign's recipients: a row each, sorted from Sort by", async ({ page, ownerApi, request }) => {
  const made = await ownerApi.post('/api/v1/campaigns', {
    data: { name: `E2E phone ${Date.now()}`, original_url: 'https://example.com/e2e-phone', csv_data: 'firstName,company\nAna,Acme\nBen,Bolt\nCai,Core' },
  });
  expect(made.ok()).toBeTruthy();
  const { id } = (await made.json()) as { id: string };
  const listed = await ownerApi.get(`/api/v1/analytics/campaigns/${id}/recipients`);
  const { recipients } = (await listed.json()) as { recipients: Array<{ short_code: string; user_data: Record<string, string> }> };
  await clickLink(request, recipients.find((r) => r.user_data.firstName === 'Ben')!.short_code);

  await page.goto(`/dashboard/campaign/?id=${id}`);
  const rows = page.locator('[data-recipients] li');
  await expect(rows).toHaveCount(3);
  await expect(page.locator('[data-recipients] table')).toBeHidden();
  await expect(rows.first()).toContainText('Ben'); // the most clicks first
  await expect(rows.first()).toContainText('Clicked');

  const sortBy = page.getByRole('combobox', { name: 'Sort by' });
  await expect(sortBy).toHaveValue('clicks:desc');
  await Promise.all([page.waitForResponse((r) => r.url().includes('/recipients?') && r.url().includes('sort=code')), sortBy.selectOption('code:asc')]);
  const codes = () => rows.locator('a[href*="code="]').evaluateAll((links) => links.map((a) => new URL((a as HTMLAnchorElement).href).searchParams.get('code') ?? ''));
  await expect.poll(async () => {
    const shown = await codes();
    return shown.length === 3 && shown.join() === [...shown].sort().join();
  }).toBe(true);
  await expect(page.getByRole('combobox', { name: 'Sort by' })).toHaveValue('code:asc');
  expect(await page.evaluate(fitsTheScreen)).toBe(true);
});
