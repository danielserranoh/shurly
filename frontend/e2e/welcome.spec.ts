// A new member's welcome on the dashboard (src/utils/welcome.ts): the run's owner signed up minutes ago, so they
// get it, with where to start, until they dismiss it; then it stays away, on this browser.

import { OWNER } from './env';
import { expect, test } from './fixtures';

test('a new member is welcomed, with where to start, until they dismiss it', async ({ page }) => {
  await page.goto('/dashboard/');
  const welcome = page.getByRole('region', { name: 'Welcome to Shurly. Here’s where to start.' });
  await expect(welcome).toBeVisible();
  await expect(welcome).toContainText('Links you make belong to Griddo'); // the organization, by its name
  await expect(welcome.getByRole('link', { name: 'Track a campaign' })).toHaveAttribute('href', '/dashboard/campaigns/create/');
  await expect(welcome.getByRole('link', { name: 'Connect Claude' })).toHaveAttribute('href', '/dashboard/settings/#api');

  await welcome.getByRole('button', { name: 'Dismiss' }).click();
  await expect(welcome).toBeHidden();
  await expect(page.getByLabel('Long link')).toBeFocused(); // where the first step is

  await page.reload();
  // Once the page knows who's looking (the header shows it), it has decided about the card.
  await expect(page.locator('[data-user-email]').first()).toHaveText(OWNER);
  await expect(page.locator('#welcome')).toBeHidden();
});
