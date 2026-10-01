// Phase 6.1 — sign in once as a member: a second account on the organization's Workspace domain, which joins as a
// member. The cookie tells the fake Google of tests/e2e/app.py who signs in; it's dropped before the session is saved.

import { API_URL, IDENTITY_COOKIE, MEMBER, MEMBER_STATE } from './env';
import { expect, test as setup } from './fixtures';

setup('sign in as a member', async ({ page, context }) => {
  await context.addCookies([{ name: IDENTITY_COOKIE, value: 'member', url: API_URL }]);
  await page.goto('/login/');
  await page.getByRole('button', { name: 'Sign in with Google' }).click();
  await expect(page).toHaveURL('/dashboard/');
  await page.getByRole('button', { name: 'Account menu' }).click();
  await expect(page.locator('#user-menu')).toContainText(MEMBER);
  await context.clearCookies({ name: IDENTITY_COOKIE });
  await context.storageState({ path: MEMBER_STATE });
});
