// Phase 7.1 — the manual, from where it's needed: Help in the account menu, "How to read this" in a link's and a
// campaign's analytics (to their section), and "How campaigns work" in the campaign wizard. And Send feedback (5.6.1),
// an email to the team with the page's path, never its query.

import { devices } from '@playwright/test';

import { expect, test } from './fixtures';

test('Help in the account menu opens the manual', async ({ page }) => {
  await page.goto('/dashboard/');
  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.locator('#user-menu').getByRole('link', { name: 'Help' }).click();
  await expect(page).toHaveURL('/manual/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('User manual');
});

test("a link's analytics link to how to read them", async ({ page, ownerApi }) => {
  const made = await ownerApi.post('/api/v1/urls', { data: { url: `https://example.com/e2e-help/${Date.now()}` } });
  const { short_code: code } = (await made.json()) as { short_code: string };
  await page.goto(`/dashboard/link/?code=${code}`);
  await page.getByRole('link', { name: 'How to read this' }).click();
  await expect(page).toHaveURL('/manual/read-your-analytics/#a-links-page');
  await expect(page.locator('#a-links-page')).toHaveText('A link’s page');
});

test("a campaign's analytics link to how to read them", async ({ page, ownerApi }) => {
  const made = await ownerApi.post('/api/v1/campaigns', {
    data: { name: `E2E help ${Date.now()}`, original_url: 'https://example.com/e2e-help', csv_data: 'firstName\nAna' },
  });
  const { id } = (await made.json()) as { id: string };
  await page.goto(`/dashboard/campaign/?id=${id}`);
  await page.getByRole('link', { name: 'How to read this' }).click();
  await expect(page).toHaveURL('/manual/read-your-analytics/#a-campaigns-page');
  await expect(page.locator('#a-campaigns-page')).toHaveText('A campaign’s page');
});

test('the campaign wizard links to how campaigns work, where the CSV comes in', async ({ page }) => {
  await page.goto('/dashboard/campaigns/create/');
  await page.getByLabel('Campaign name').fill('E2E help');
  await page.getByLabel('Destination').fill('https://example.com/e2e-help');
  await page.getByRole('button', { name: 'Continue' }).click();
  // In a new tab: the wizard keeps what's typed so far.
  const [manual] = await Promise.all([page.context().waitForEvent('page'), page.getByRole('link', { name: 'How campaigns work' }).click()]);
  await expect(manual).toHaveURL(/\/manual\/make-a-campaign\/$/);
  await expect(manual.getByRole('heading', { level: 1 })).toHaveText('Make a campaign from a CSV');
  await expect(page.getByLabel('Campaign name')).toHaveValue('E2E help');
});

/** The mailto: link's parts: the address, the subject and the body. */
function mailOf(href: string | null) {
  const mail = new URL(href ?? '');
  return { protocol: mail.protocol, to: mail.pathname, subject: mail.searchParams.get('subject'), body: mail.searchParams.get('body') ?? '' };
}

test('Send feedback in the account menu writes to the team, with the page but never its query', async ({ page, ownerApi }) => {
  const made = await ownerApi.post('/api/v1/urls', { data: { url: `https://example.com/e2e-feedback/${Date.now()}` } });
  const { short_code: code } = (await made.json()) as { short_code: string };
  await page.goto(`/dashboard/link/?code=${code}`);
  await page.getByRole('button', { name: 'Account menu' }).click();

  const href = await page.locator('#user-menu').getByRole('link', { name: 'Send feedback' }).getAttribute('href');
  expect(mailOf(href)).toMatchObject({ protocol: 'mailto:', to: 'support@griddo.io', subject: 'Shurly feedback' });
  expect(mailOf(href).body).toContain('Page: /dashboard/link/');
  expect(href).not.toContain(code);
});

test.describe('on a phone', () => {
  const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
  test.use({ ...pixel, viewport: { width: 390, height: 844 } });

  test("the menu's Send feedback too", async ({ page }) => {
    await page.goto('/dashboard/settings/');
    await page.getByRole('button', { name: 'Open menu' }).click();
    const href = await page.getByRole('dialog', { name: 'Menu' }).getByRole('link', { name: 'Send feedback' }).getAttribute('href');
    expect(mailOf(href)).toMatchObject({ protocol: 'mailto:', to: 'support@griddo.io', subject: 'Shurly feedback' });
    expect(mailOf(href).body).toContain('Page: /dashboard/settings/');
  });
});
