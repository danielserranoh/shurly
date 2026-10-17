// Phase 6.1 — the styleguide, signed out, under the harness's rules: it runs much of the app's own code (charts,
// dialogs, the recipients table). Its Pager specimen pages through a list as the links' and campaigns' lists do. Its
// Photo and logo specimens open the photo dialog (3.12.10) on drawn samples.

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

test('the Photo and logo specimens open the photo dialog on the drawn samples, and Save shows the result', async ({ page }) => {
  await page.goto('/styleguide/');
  const buttons = page.getByRole('list', { name: 'Photo and logo buttons' });
  await expect(buttons.locator('[data-photo-badge]')).toHaveCount(3); // the member's logo has none

  const sample = buttons.getByRole('button', { name: 'Change the sample photo' });
  await sample.click();
  const photo = page.getByRole('dialog', { name: 'Profile photo' });
  await expect(photo.locator('[data-picker-frame]')).toHaveAttribute('data-shows', 'current');
  await photo.getByRole('button', { name: 'Remove photo' }).click();
  await photo.getByRole('button', { name: 'Save photo' }).click();
  await expect(page.getByText('Photo removed')).toBeVisible();
  await expect(sample.locator('[data-sg-photo-initial]')).toBeVisible();

  await buttons.getByRole('button', { name: 'Change the sample logo' }).click();
  const logo = page.getByRole('dialog', { name: 'Organization logo' });
  await expect(logo.locator('[data-picker-frame]')).toHaveAttribute('data-shows', 'current');
  await logo.getByRole('button', { name: 'Cancel' }).click();
  await expect(logo).toBeHidden();
});
