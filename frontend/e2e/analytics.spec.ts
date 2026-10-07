// ROADMAP 3.10.4 — the analytics page's "Typos & broken links": someone mistypes a link's code, and the page lists
// what they tried, with the link they meant (the API's "did you mean", against every link). Ten paths at a time.
// The API's own order is the reference, so a database used before doesn't change what's checked.

import type { APIRequestContext } from '@playwright/test';

import { expect, test } from './fixtures';
import { API_URL, BROWSER_UA } from './env';

interface Groups {
  groups: Array<{ attempted_path: string; visits: number }>;
  hidden_visits: number;
}

/** A page of the paths tried in the last 30 days, as the section asks for it: typos only (3.10.8), or everything. */
async function grouped(ownerApi: APIRequestContext, page: number, size = 10, typosOnly = true): Promise<Groups> {
  const response = await ownerApi.get(`/api/v1/analytics/orphan-visits/grouped?period=30&page=${page}&page_size=${size}&typos_only=${typosOnly}`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as Groups;
}

/** Someone asks for a code that's no link: a 404, and an orphan visit. */
async function tryPath(request: APIRequestContext, path: string, userAgent = BROWSER_UA): Promise<void> {
  const tried = await request.get(`${API_URL}/${path}`, { headers: { 'User-Agent': userAgent }, maxRedirects: 0 });
  expect(tried.status(), `/${path} is no link`).toBe(404);
}

test('a mistyped code shows under "Typos & broken links", with the link it meant', async ({ page, ownerApi, request }) => {
  const made = await ownerApi.post('/api/v1/urls', { data: { url: `https://example.com/e2e-typo/${Date.now()}` } });
  expect(made.ok()).toBeTruthy();
  const { short_code: code } = (await made.json()) as { short_code: string };
  const typo = code.slice(0, -1); // one character short
  // Tried once more than the most tried so far, so it's first on the first page.
  const hits = ((await grouped(ownerApi, 1, 1)).groups[0]?.visits ?? 0) + 1;
  for (let hit = 0; hit < hits; hit++) await tryPath(request, typo);

  await page.goto('/dashboard/analytics/');
  const row = page.locator('[data-orphans] li').filter({ has: page.locator('p.shortlink', { hasText: new RegExp(`^/${typo}$`) }) });
  await expect(row).toContainText(hits === 1 ? '1 try' : `${hits} tries`);
  await expect(row.getByRole('link', { name: `/${code}`, exact: true })).toHaveAttribute('href', new RegExp(`^/dashboard/link/\\?code=${code}(&|$)`));
});

test('ten paths at a time, with Next and Previous', async ({ page, ownerApi, request }) => {
  const stamp = Date.now();
  for (let i = 0; i < 11; i++) await tryPath(request, `e2e-${stamp}-${i}`); // a second page, at least
  const first = (await grouped(ownerApi, 1)).groups[0].attempted_path;
  const second = (await grouped(ownerApi, 2)).groups[0].attempted_path;
  const paths = page.locator('[data-orphans] li p.shortlink');
  const range = page.locator('#pagination [data-range]');

  await page.goto('/dashboard/analytics/');
  await expect(paths.first()).toHaveText(first);
  await expect(paths).toHaveCount(10);
  await expect(range).toHaveText(/^Showing 1–10 of \d+$/);

  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(paths.first()).toHaveText(second);
  await expect(range).toHaveText(/^Showing 11–\d+ of \d+$/);

  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(paths.first()).toHaveText(first);
});

test('scanners and bots aren’t typos: the list leaves them out, says how many, and shows them on request', async ({ page, ownerApi, request }) => {
  // A scanner's probe, the most tried of everything, so it's first once shown; and a bot on a path shaped like a code.
  const probe = `.env-e2e-${Date.now()}`;
  const hits = ((await grouped(ownerApi, 1, 1, false)).groups[0]?.visits ?? 0) + 1;
  for (let hit = 0; hit < hits; hit++) await tryPath(request, probe);
  await tryPath(request, `e2e-bot-${Date.now()}`, 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)');
  const hidden = (await grouped(ownerApi, 1)).hidden_visits;
  expect(hidden).toBeGreaterThanOrEqual(hits + 1);

  await page.goto('/dashboard/analytics/');
  const typos = page.getByRole('region', { name: 'Typos & broken links' });
  const paths = typos.locator('[data-orphans] li p.shortlink');
  const line = typos.locator('[data-orphans-hidden]');
  await expect(line).toHaveText(`${hidden.toLocaleString('en-US')} hits from scanners and bots aren’t shown. Show them`);
  await expect(paths.filter({ hasText: probe })).toHaveCount(0);

  await typos.getByRole('button', { name: 'Show them' }).click();
  await expect(paths.first()).toHaveText(`/${probe}`);
  await expect(line).toHaveText('Hits from scanners and bots are shown too. Hide them');
  await expect(typos.getByRole('button', { name: 'Hide them' })).toBeFocused();

  await typos.getByRole('button', { name: 'Hide them' }).click();
  await expect(line).toContainText('aren’t shown.');
  await expect(paths.filter({ hasText: probe })).toHaveCount(0);
});

test("each section says its window, and the Pro card promises only what isn't built", async ({ page }) => {
  await page.goto('/dashboard/analytics/');
  // The range row scopes the summary and the chart; "Typos & broken links" keeps 30 days of its own.
  const typos = page.getByRole('region', { name: 'Typos & broken links' });
  await expect(typos.getByText('Last 30 days', { exact: true })).toBeVisible();
  await expect(typos).toContainText('The range above doesn’t change this list.');

  // Paywall rule 1 (DESIGN_SYSTEM.md): what a link's page already has, free, is never "coming with Pro".
  const card = page.locator('section', { hasText: 'Go deeper' });
  await expect(card).toContainText('Each link’s page already has the last 30 or 90 days, dates you pick, and its visits as a CSV.');
  await expect(card.getByRole('link', { name: 'Links', exact: true })).toHaveAttribute('href', '/dashboard/');
  // What isn't built is "Coming soon", and says what Pro adds (rule 2).
  await expect(card.locator('p', { has: page.locator('.badge-pro') })).toHaveText('Coming soon Longer ranges across all your links, and live stats, come with Pro.');
});
