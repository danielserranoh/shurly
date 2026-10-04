// Phase 6.1 — the styleguide, signed out, under the harness's rules: it runs much of the app's own code (charts,
// dialogs, the recipients table). Its Pager specimen pages through a list as the links' and campaigns' lists do.

import { expect, test } from './fixtures';

test.use({ storageState: { cookies: [], origins: [] } });

test('the Link thumbnails specimen: an image with its icon, the icon, the monogram, and a broken image giving way', async ({ page }) => {
  await page.goto('/styleguide/');
  const thumbs = page.getByRole('list', { name: 'Link thumbnails' }).getByRole('listitem');
  await thumbs.last().scrollIntoViewIfNeeded(); // the images load lazily

  await expect(thumbs.nth(0).locator('[data-thumb-kind="image"] img')).toHaveCount(2); // the image and its icon badge
  await expect(thumbs.nth(1).locator('[data-thumb-kind="favicon"]')).toBeVisible();
  await expect(thumbs.nth(2).locator('[data-thumb-kind]')).toHaveCount(0);
  await expect(thumbs.nth(2)).toContainText('A'); // the monogram
  await expect(thumbs.nth(3).locator('[data-thumb-kind="favicon"]')).toBeVisible();
  await expect(thumbs.nth(3).locator('[data-thumb-kind="image"]')).toHaveCount(0);
});

test('the Pager specimen pages through 57 links, 20 at a time', async ({ page }) => {
  await page.goto('/styleguide/');
  const pager = page.getByRole('navigation', { name: 'Pagination' });
  const previous = pager.getByRole('button', { name: 'Previous' });
  const next = pager.getByRole('button', { name: 'Next' });

  await expect(pager).toContainText('Showing 1–20 of 57');
  await expect(previous).toBeDisabled();
  await next.click();
  await expect(pager).toContainText('Showing 21–40 of 57');
  await expect(previous).toBeEnabled();
  await next.click();
  await expect(pager).toContainText('Showing 41–57 of 57');
  await expect(next).toBeDisabled();
  await previous.click();
  await expect(pager).toContainText('Showing 21–40 of 57');
});
