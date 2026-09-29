// Phase 6.1 — Settings: the profile's name and time zone are saved, and the header's initial follows the name;
// the tabs work from the keyboard, and the address follows them (the first tab's is the page's own).

import { expect, test } from './fixtures';

test("saving the profile keeps its name and time zone, and the header's initial follows", async ({ page }) => {
  await page.goto('/dashboard/settings/');
  const form = page.locator('[data-profile-form]');
  const save = form.getByRole('button', { name: 'Save profile' });
  await expect(save).toBeEnabled(); // once the account has loaded

  // Other values than the saved ones, so that every run changes them.
  const [first, zone] = (await form.getByLabel('First name').inputValue()) === 'Olivia' ? ['Zoe', 'Atlantic/Madeira'] : ['Olivia', 'Atlantic/Azores'];
  await form.getByLabel('First name').fill(first);
  await form.getByLabel('Last name').fill('Tester');
  await form.getByLabel('Country').selectOption('PT');
  await form.getByLabel('Time zone').selectOption(zone);
  await save.click();
  await expect(page.getByText('Profile saved')).toBeVisible();
  const avatar = page.getByRole('button', { name: 'Account menu' });
  await expect(avatar).toHaveText(first[0]);

  await page.reload();
  await expect(save).toBeEnabled();
  await expect(form.getByLabel('First name')).toHaveValue(first);
  await expect(form.getByLabel('Country')).toHaveValue('PT');
  await expect(form.getByLabel('Time zone')).toHaveValue(zone);
  await expect(avatar).toHaveText(first[0]);
});

test('the tabs work from the keyboard, and the address follows', async ({ page }) => {
  await page.goto('/dashboard/settings/');
  const tab = (name: string) => page.getByRole('tab', { name });
  async function expectOn(name: string, hash: string) {
    await expect(tab(name)).toBeFocused();
    await expect(tab(name)).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByRole('tabpanel', { name })).toBeVisible();
    await expect(page).toHaveURL(hash ? new RegExp(`/dashboard/settings/#${hash}$`) : /\/dashboard\/settings\/$/);
  }

  await tab('Account').focus();
  await page.keyboard.press('ArrowRight');
  await expectOn('Organization', 'organization');
  await page.keyboard.press('End');
  await expectOn('Plan', 'plan');
  await page.keyboard.press('ArrowRight'); // round to the first
  await expectOn('Account', '');
  await page.keyboard.press('ArrowLeft'); // and back to the last
  await expectOn('Plan', 'plan');
  await page.keyboard.press('Home');
  await expectOn('Account', '');
  await expect(tab('Plan')).toHaveAttribute('tabindex', '-1'); // one tab stop: the selected tab
});
