// Phase 6.1 — a link from start to numbers: shortened on the dashboard, found in the list, clicked and opened, then
// its page (3.16): the all-time numbers, the tabs, the periods (a custom range refused, then applied) and the CSV
// of its visits.

import { expect, test } from './fixtures';
import { clickLink, csvLines, openEmail, pick, shift } from './helpers';

// One link for the whole file, made by the first test: the others read its numbers.
test.describe.configure({ mode: 'serial' });
let code = '';
const destination = `https://example.com/e2e/${Date.now()}`;

test('the dashboard shortens a link and lists it, and its page starts at zero', async ({ page }) => {
  await page.goto('/dashboard/');
  await page.getByLabel('Long link').fill(destination);
  await page.getByRole('button', { name: 'Shorten' }).click();
  const shortLink = page.locator('[data-result-link]');
  await expect(shortLink).toBeVisible();
  code = (await shortLink.textContent())?.split('/').pop() ?? '';
  expect(code).toMatch(/^[\w-]+$/);

  const card = page.locator('li[data-link]', { hasText: `/${code}` });
  await expect(card).toBeVisible();
  await card.getByRole('link', { name: 'example.com', exact: true }).click(); // its title: the destination's host
  await expect(page).toHaveURL(new RegExp(`/dashboard/link/\\?code=${code}\\b`));
  await expect(page.locator('[data-stat="clicks"]')).toHaveText('0');
  await expect(page.locator('[data-stat="opens"]')).toHaveText('0');
});

test('a click and an email open count, all time', async ({ page, request }) => {
  // Someone clicks it, and their email client loads its pixel.
  expect(await clickLink(request, code)).toBe(destination);
  await openEmail(request, code);

  await page.goto(`/dashboard/link/?code=${code}`);
  await expect(page.locator('[data-stat="clicks"]')).toHaveText('1');
  await expect(page.locator('[data-stat="opens"]')).toHaveText('1');
  await expect(page.locator('[data-range]')).toContainText('Last 30 days: ');
  await expect(page.locator('[data-range]')).toContainText('1 click · 1 email open');
});

test('the tabs show the period by time, by context, by location and visit by visit', async ({ page }) => {
  await page.goto(`/dashboard/link/?code=${code}`);
  await expect(page.getByRole('tab', { name: 'By time' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tabpanel', { name: 'By time' })).toBeVisible();

  await page.getByRole('tab', { name: 'By context' }).click();
  const context = page.getByRole('tabpanel', { name: 'By context' });
  await expect(context).toBeVisible();
  await expect(context).toContainText('Chrome');

  await page.getByRole('tab', { name: 'By location' }).click();
  const location = page.getByRole('tabpanel', { name: 'By location' });
  await expect(location).toBeVisible();
  await expect(location).toContainText('Unknown'); // no geolocation database in a test run

  await page.getByRole('tab', { name: 'Visits' }).click();
  const visits = page.getByRole('tabpanel', { name: 'Visits' });
  await expect(visits.locator('[data-visits-count]')).toHaveText('1–1 of 1');
  await pick(visits.getByRole('radio', { name: 'Email opens' }));
  await expect(visits.locator('[data-visits-count]')).toHaveText('1–1 of 1');
  await pick(visits.getByRole('radio', { name: 'Bots' }));
  await expect(visits.locator('[data-visits-count]')).toHaveText('');
});

test('the period: 7 or 90 days, or a custom range, refused until it makes sense', async ({ page }) => {
  await page.goto(`/dashboard/link/?code=${code}`);
  const range = page.locator('[data-range]');
  await expect(range).toContainText('1 click');

  await pick(page.getByRole('radio', { name: '7 days' }));
  await expect(range).toContainText('Last 7 days: ');
  await expect(page).toHaveURL(/[?&]period=7\b/);
  await pick(page.getByRole('radio', { name: '90 days' }));
  await expect(range).toContainText('Last 90 days: ');

  await page.getByRole('radio', { name: 'Custom' }).locator('xpath=..').click();
  const menu = page.locator('#range-menu');
  await expect(menu).toBeVisible();
  const today = await menu.getByLabel('To').inputValue(); // the page's today, where it counts
  await menu.getByLabel('From').fill(today);
  await menu.getByLabel('To').fill(shift(today, -1));
  await menu.getByRole('button', { name: 'Apply' }).click();
  await expect(menu.getByText('The start date comes after the end date.')).toBeVisible();

  const from = shift(today, -10);
  await menu.getByLabel('From').fill(from);
  await menu.getByLabel('To').fill(today);
  await menu.getByRole('button', { name: 'Apply' }).click();
  await expect(menu).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`[?&]from=${from}&to=${today}\\b`));
  await expect(range).toContainText('1 click · 1 email open');
  await expect(page.locator('[data-custom-label]')).not.toHaveText('Custom');
});

test("Export CSV downloads the period's visits", async ({ page }) => {
  await page.goto(`/dashboard/link/?code=${code}&period=7`);
  await expect(page.locator('[data-range]')).toContainText('1 click');
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Export CSV' }).click()]);
  expect(download.suggestedFilename()).toMatch(new RegExp(`^${code}-visits-\\d{4}-\\d{2}-\\d{2}-\\d{4}-\\d{2}-\\d{2}\\.csv$`));

  const [header, ...rows] = await csvLines(download);
  expect(header).toBe('visited_at,kind,country,browser,os,device,referrer,user_agent');
  expect(rows.map((row) => row.split(',')[1]).sort()).toEqual(['click', 'open']);
});
