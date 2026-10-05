// Phase 3.13.7 — the login page leads with Google: the password form waits behind a closed disclosure, which opens
// when someone chooses it (and focuses the email), when the address asks for it, or when they chose it earlier this
// session. Signing in with Google doesn't care whether it's open.

import type { Page } from '@playwright/test';

import { expect, test } from './fixtures';

test.use({ storageState: { cookies: [], origins: [] } });

const block = (page: Page) => page.locator('details[data-password-login]');
const toggle = (page: Page) => page.locator('details[data-password-login] > summary');
const email = (page: Page) => page.getByLabel('Work email');

test('the password form is closed at first, under Google', async ({ page }) => {
  await page.goto('/login/');
  const google = page.getByRole('button', { name: 'Sign in with Google' });
  await expect(google).toBeVisible();
  await expect(toggle(page)).toHaveText('Log in with email and password');
  await expect(block(page)).not.toHaveAttribute('open');
  await expect(email(page)).toBeHidden();
  await expect(page.getByLabel('Password', { exact: true })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Log in', exact: true })).toBeHidden();
  // Google comes first, for the eye and for the keyboard.
  const [googleTop, toggleTop] = await Promise.all([google.boundingBox(), toggle(page).boundingBox()]);
  expect(googleTop!.y).toBeLessThan(toggleTop!.y);
  await google.focus();
  await page.keyboard.press('Tab');
  await expect(toggle(page)).toBeFocused();
});

test('choosing it opens the form on the email', async ({ page }) => {
  await page.goto('/login/');
  await toggle(page).click();
  await expect(block(page)).toHaveAttribute('open');
  await expect(email(page)).toBeFocused();
  await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Forgot password?' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Log in', exact: true })).toBeVisible();
  // The form still posts: a submit before the script loads can't put the password in the address.
  await expect(page.locator('#login-form')).toHaveAttribute('method', 'post');
  await expect(email(page)).toHaveAttribute('autocomplete', 'email');
  await expect(page.getByLabel('Password', { exact: true })).toHaveAttribute('autocomplete', 'current-password');
});

test('the keyboard opens and closes it', async ({ page }) => {
  await page.goto('/login/');
  await toggle(page).focus();
  await page.keyboard.press('Enter');
  await expect(email(page)).toBeFocused();
  await toggle(page).focus();
  await page.keyboard.press('Space');
  await expect(block(page)).not.toHaveAttribute('open');
  await expect(email(page)).toBeHidden();
});

for (const address of ['/login/?method=password', '/login/#password', '/login/?email=ana%40griddo.io']) {
  test(`${address} opens it`, async ({ page }) => {
    await page.goto(address);
    await expect(block(page)).toHaveAttribute('open');
    await expect(email(page)).toBeVisible();
  });
}

test('?email= fills the email in, with the form open on the password', async ({ page }) => {
  await page.goto('/login/?email=ana%40griddo.io');
  await expect(email(page)).toHaveValue('ana@griddo.io');
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused();
});

test('it stays the way it was left, for the session', async ({ page }) => {
  await page.goto('/login/');
  await toggle(page).click();
  await expect(email(page)).toBeFocused();
  await page.reload();
  await expect(block(page)).toHaveAttribute('open');
  await toggle(page).click();
  await expect(block(page)).not.toHaveAttribute('open');
  await page.reload();
  await expect(email(page)).toBeHidden();
});

test("a password manager's fill opens it", async ({ page }) => {
  await page.goto('/login/');
  // What a password manager does: set the value and say so, on a field the person can't see yet.
  await email(page).evaluate((input: HTMLInputElement) => {
    input.value = 'ana@griddo.io';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect(block(page)).toHaveAttribute('open');
  await expect(email(page)).toHaveValue('ana@griddo.io');
});

test('a failed password login shows why, with the form still open', async ({ page }) => {
  await page.goto('/login/?method=password');
  // An address with no account, its own each run: the failures per account stay with it.
  await email(page).fill(`nobody.${Date.now()}@griddo.io`);
  await page.getByLabel('Password', { exact: true }).fill('not the password');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('Incorrect email or password');
  await expect(block(page)).toHaveAttribute('open');
  await expect(email(page)).toBeVisible();
  await expect(page).toHaveURL(/\/login\/\?method=password$/);
});

test('an empty submit shows the fields that need filling, in the open form', async ({ page }) => {
  await page.goto('/login/');
  await toggle(page).click();
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('[data-error-for="email"]')).toHaveText('Enter your email.');
  await expect(page.locator('[data-error-for="password"]')).toHaveText('Enter your password.');
  await expect(email(page)).toBeFocused();
  await expect(block(page)).toHaveAttribute('open');
});

test('Google signs you in with the password form open too', async ({ page }) => {
  await page.goto('/login/?method=password');
  await expect(email(page)).toBeVisible();
  await page.getByRole('button', { name: 'Sign in with Google' }).click();
  await expect(page).toHaveURL('/dashboard/');
});
