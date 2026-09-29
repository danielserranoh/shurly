// Phase 8.4 — cities on the Location tab: a link's, a campaign's (which says its "Other cities" rule), and none for a
// campaign link, whose visits are one recipient's. A test run has no GeoLite data, so every city is Unknown here; the
// order and the labels ("Valencia, Spain") are tests/analytics-view.test.mjs's.

import { expect, test } from './fixtures';
import { clickLink } from './helpers';

test("a link's Location tab has its cities", async ({ page, ownerApi, request }) => {
  const made = await ownerApi.post('/api/v1/urls', { data: { url: `https://example.com/e2e-cities/${Date.now()}` } });
  const { short_code: code } = (await made.json()) as { short_code: string };
  await clickLink(request, code);

  await page.goto(`/dashboard/link/?code=${code}`);
  await page.getByRole('tab', { name: 'By location' }).click();
  const cities = page.getByRole('region', { name: 'Cities' });
  await expect(cities).toContainText('Unknown');
  await expect(cities).toContainText('GeoLite data by MaxMind');
  await expect(cities).not.toContainText('Other cities'); // a link's cities are never grouped
});

test("a campaign's has them with its rule, and a recipient's link page has none", async ({ page, ownerApi, request }) => {
  const made = await ownerApi.post('/api/v1/campaigns', {
    data: { name: `E2E cities ${Date.now()}`, original_url: 'https://example.com/e2e-cities', csv_data: 'firstName\nAna\nBen' },
  });
  const { id } = (await made.json()) as { id: string };
  const listed = await ownerApi.get(`/api/v1/analytics/campaigns/${id}/recipients`);
  const { recipients } = (await listed.json()) as { recipients: Array<{ short_code: string }> };
  await clickLink(request, recipients[0].short_code);

  await page.goto(`/dashboard/campaign/?id=${id}`);
  await page.getByRole('tab', { name: 'By location' }).click();
  const cities = page.getByRole('region', { name: 'Cities' });
  await expect(cities).toContainText('Unknown');
  await expect(cities).toContainText('Other cities: those fewer than 5 recipients clicked from');

  // A recipient's link: the countries render, and with them the decision that there are no cities to show.
  await page.goto(`/dashboard/link/?code=${recipients[0].short_code}`);
  await page.getByRole('tab', { name: 'By location' }).click();
  await expect(page.getByRole('region', { name: 'Countries' })).toContainText('Unknown');
  await expect(page.locator('[data-cities]')).toBeHidden();
});
