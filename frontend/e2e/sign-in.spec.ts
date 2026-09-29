// Phase 6.1 — signing in and out: the dashboard asks for a session, Google (the fake one) gives one and brings you
// back where you were going, and logging out ends it on this browser.

import { OWNER } from './env';
import { expect, test } from './fixtures';

test.describe('signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('the dashboard asks you to log in first', async ({ page }) => {
    await page.goto('/dashboard/');
    await expect(page).toHaveURL(/\/login\/\?/);
    expect(new URL(page.url()).searchParams.get('next')).toBe('/dashboard/');
    await expect(page.getByRole('button', { name: 'Sign in with Google' })).toBeVisible();
  });

  test('Google signs you in and brings you back where you were going', async ({ page }) => {
    await page.goto('/dashboard/campaigns/');
    await expect(page).toHaveURL(/\/login\/\?/);
    await page.getByRole('button', { name: 'Sign in with Google' }).click();
    await expect(page).toHaveURL('/dashboard/campaigns/');
    await page.getByRole('button', { name: 'Account menu' }).click();
    await expect(page.locator('#user-menu')).toContainText(OWNER);
  });
});

test('logging out ends the session on this browser', async ({ page }) => {
  await page.goto('/dashboard/');
  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('button', { name: 'Log out' }).click();
  await expect(page).toHaveURL('/login/?reason=signed-out');
  await page.goto('/dashboard/');
  await expect(page).toHaveURL(/\/login\/\?/);
});
