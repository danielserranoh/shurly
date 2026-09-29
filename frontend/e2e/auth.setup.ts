// Phase 6.1 — sign in once, with Google (the fake one of tests/e2e/app.py), as the organization's owner. The specs
// start from the session this saves.

import { OWNER, OWNER_STATE } from './env';
import { expect, test as setup } from './fixtures';

setup('sign in as the owner', async ({ page }) => {
  await page.goto('/login/');
  await page.getByRole('button', { name: 'Sign in with Google' }).click();
  await expect(page).toHaveURL('/dashboard/');
  await page.getByRole('button', { name: 'Account menu' }).click();
  await expect(page.locator('#user-menu')).toContainText(OWNER);
  await page.context().storageState({ path: OWNER_STATE });
});
