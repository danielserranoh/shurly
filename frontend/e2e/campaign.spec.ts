// Phase 6.1 — a campaign from its CSV to who clicked (3.17): made with the wizard from five recipients, one of
// them clicks, and its page counts them: Clicked 20% and each filter's count, a header's sort, the Clicked filter,
// two recipients' links copied at once, and the recipients' CSV. Then the campaigns' list, a page of 20 at a time,
// and a campaign link's page, which names its campaign.

import { expect, test } from './fixtures';
import { clickLink, csvLines, pick } from './helpers';

// One campaign for the whole file, made by the first test.
test.describe.configure({ mode: 'serial' });
const stamp = Date.now();
const name = `E2E campaign ${stamp}`;
const destination = `https://example.com/e2e-campaign/${stamp}`;
const PEOPLE = ['Ana', 'Ben', 'Cai', 'Dee', 'Eve'];
const CSV = ['firstName,company', ...PEOPLE.map((person) => `${person},${person} & Co`)].join('\n');
let campaignPage = '';

test("the wizard makes a link for each of the CSV's five recipients", async ({ page }) => {
  await page.goto('/dashboard/campaigns/create/');
  await page.getByLabel('Campaign name').fill(name);
  await page.getByLabel('Destination').fill(destination);
  await page.getByRole('button', { name: 'Continue' }).click();

  await page.locator('[data-file]').setInputFiles({ name: 'recipients.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) });
  await expect(page.locator('[data-file-meta]')).toHaveText('5 recipients · 2 columns');
  await page.getByRole('button', { name: 'Review' }).click();
  await page.getByRole('button', { name: 'Create 5 links' }).click();

  await expect(page).toHaveURL(/\/dashboard\/campaign\/\?id=/);
  campaignPage = new URL(page.url()).pathname + new URL(page.url()).search;
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
  await expect(page.locator('[data-stat="recipients"]')).toHaveText('5');
  await expect(page.locator('[data-stat="clicked"]')).toHaveText('0%');
  await expect(page.locator('[data-recipients] tbody tr')).toHaveCount(5);
});

test('a recipient who clicks counts: Clicked 20%, and in the filters', async ({ page, request }) => {
  await page.goto(campaignPage);
  const ana = page.locator('[data-recipients]').getByRole('row', { name: /\bAna\b/ });
  const code = (await ana.locator('a.shortlink').textContent())?.split('/').pop() ?? '';
  // The link goes on to the destination, with Ana's row of the CSV.
  expect(await clickLink(request, code)).toContain(destination);

  await page.reload();
  await expect(page.locator('[data-stat="clicked"]')).toHaveText('20%');
  await expect(page.locator('[data-stat="clicks"]')).toHaveText('1');
  for (const [filter, count] of [['all', '5'], ['clicked', '1'], ['opened', '0'], ['none', '4']]) {
    await expect(page.locator(`[data-count="${filter}"]`), filter).toHaveText(count);
  }
});

test('a header sorts the recipients, and the Clicked filter keeps who clicked', async ({ page }) => {
  await page.goto(campaignPage);
  const recipients = page.locator('[data-recipients]');
  const rows = recipients.locator('tbody tr');
  await expect(rows).toHaveCount(5);
  await expect(rows.first()).toContainText('Ana'); // the most clicks first

  const header = recipients.getByRole('columnheader', { name: 'Short link' });
  await header.getByRole('button').click();
  await expect(recipients.getByRole('columnheader', { name: 'Short link' })).toHaveAttribute('aria-sort', 'ascending');
  const ascending = await rows.locator('a.shortlink').allTextContents();
  expect(ascending).toEqual([...ascending].sort());
  await recipients.getByRole('columnheader', { name: 'Short link' }).getByRole('button').click();
  await expect(recipients.getByRole('columnheader', { name: 'Short link' })).toHaveAttribute('aria-sort', 'descending');
  expect(await rows.locator('a.shortlink').allTextContents()).toEqual([...ascending].reverse());

  await pick(page.getByRole('radio', { name: /^Clicked\b/ }));
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText('Ana');
});

test("the search keeps to the API's 200 characters, so a long paste still searches", async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(campaignPage);
  await expect(page.locator('[data-recipients] tbody tr')).toHaveCount(5);
  const search = page.getByRole('searchbox', { name: 'Search recipients' });
  await page.evaluate((text) => navigator.clipboard.writeText(text), 'x'.repeat(250));
  await search.focus();
  const [answer] = await Promise.all([page.waitForResponse((r) => r.url().includes('/recipients?') && r.url().includes('q=x')), page.keyboard.press('ControlOrMeta+V')]);
  expect(answer.status()).toBe(200); // not a 422: the API takes up to 200
  await expect(search).toHaveValue('x'.repeat(200));
});

test('ticking two recipients copies their two links', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(campaignPage);
  const recipients = page.locator('[data-recipients]');
  await expect(recipients.locator('tbody tr')).toHaveCount(5);
  const codeOf = async (person: string) => (await recipients.getByRole('row', { name: new RegExp(`\\b${person}\\b`) }).locator('a.shortlink').textContent())?.split('/').pop();

  await recipients.getByRole('checkbox', { name: 'Select Ben' }).check();
  await recipients.getByRole('checkbox', { name: 'Select Cai' }).check();
  await expect(page.locator('[data-selected-count]')).toHaveText('2');
  await page.getByRole('button', { name: 'Copy their links' }).click();
  await expect(page.getByText('2 links copied')).toBeVisible();

  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied.split('\n').map((link) => link.split('/').pop())).toEqual([await codeOf('Ben'), await codeOf('Cai')]);
});

test("Export CSV downloads the recipients, their CSV's columns first", async ({ page }) => {
  await page.goto(campaignPage);
  await expect(page.locator('[data-recipients] tbody tr')).toHaveCount(5);
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Export CSV' }).click()]);
  expect(download.suggestedFilename()).toBe(`e2e-campaign-${stamp}-recipients.csv`);

  const [header, ...rows] = await csvLines(download);
  expect(header).toBe('firstName,company,short_code,short_url,clicks,opens,first_click_at,last_click_at,last_open_at');
  expect(rows).toHaveLength(5);
});

test('the campaigns page shows 20 at a time: the first of 21 made is on page 2', async ({ page, ownerApi }) => {
  // The newest 21 campaigns: page 1 holds the last 20 made, newest first, and page 2 starts with the first.
  const names = Array.from({ length: 21 }, (_, i) => `E2E paged ${stamp} ${String(i + 1).padStart(2, '0')}`);
  const ids: string[] = [];
  for (const campaign of names) {
    const made = await ownerApi.post('/api/v1/campaigns', { data: { name: campaign, original_url: destination, csv_data: 'firstName\nAna' } });
    expect(made.ok(), campaign).toBeTruthy();
    ids.push(((await made.json()) as { id: string }).id);
  }
  const cards = page.locator('#campaign-list [data-campaign]');
  const range = page.locator('#pagination [data-range]');

  await page.goto('/dashboard/campaigns/');
  await expect(cards).toHaveCount(20);
  await expect(cards.first()).toContainText(names[20]);
  await expect(cards.last()).toContainText(names[1]);
  await expect(range).toHaveText(/^Showing 1–20 of \d+$/);
  await expect(page.getByRole('button', { name: 'Previous', exact: true })).toBeDisabled();

  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard\/campaigns\/\?page=2$/);
  await expect(cards.first()).toContainText(names[0]);
  await expect(range).toHaveText(/^Showing 21–\d+ of \d+$/);

  // The address keeps the page, and Previous goes back to the first.
  await page.reload();
  await expect(cards.first()).toContainText(names[0]);
  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard\/campaigns\/$/);
  await expect(cards.first()).toContainText(names[20]);

  // Its recipient's link names it, from the link itself (`campaign_name`), whichever campaign it is.
  const listed = await ownerApi.get(`/api/v1/analytics/campaigns/${ids[0]}/recipients`);
  const { recipients } = (await listed.json()) as { recipients: Array<{ short_code: string }> };
  await page.goto(`/dashboard/link/?code=${recipients[0].short_code}`);
  await expect(page.locator('[data-campaign-link]')).toHaveText(names[0]);
});
