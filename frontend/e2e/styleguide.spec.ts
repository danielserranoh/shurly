// Phase 6.1 — the styleguide, signed out, under the harness's rules: it runs much of the app's own code (charts,
// dialogs, the recipients table). Its Pager specimen pages through a list as the links' and campaigns' lists do.

import { expect, test } from './fixtures';

test.use({ storageState: { cookies: [], origins: [] } });

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
