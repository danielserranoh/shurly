// Phase 3.14.7 — the organization's own page (/dashboard/organization/), a tab in Settings until then: its logo, the
// members and roles, the service accounts (owners and admins) and what each role can do, under its own heading. The
// account menu's organization row is a link to it, in the menu's keyboard order. And the header: 20 px between New
// link and the avatar, on a desktop and on phones from 320 px, with nothing wrapping or scrolling sideways.

import { devices } from '@playwright/test';

import { expect, test } from './fixtures';

test("the page has the organization's logo, members, service accounts and roles, under its own heading", async ({ page, ownerApi }) => {
  const { name } = (await (await ownerApi.get('/api/v1/organization')).json()) as { name: string };
  await page.goto('/dashboard/organization/');
  await expect(page).toHaveTitle(/^Organization/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Organization');
  const main = page.getByRole('main');
  await expect(main.locator('[data-org-name]')).toHaveText(name);
  for (const section of ['Logo', 'Members', 'Service accounts', 'Roles']) {
    await expect(main.getByRole('region', { name: new RegExp(`^${section}`) })).toBeVisible();
  }
  await expect(main.locator('[data-org-summary]')).toContainText('You’re an owner.');
  await expect(main.getByRole('tab')).toHaveCount(0); // a page, not a tab
});

test('the account menu links to it: the organization row, next in the keyboard order after the avatar', async ({ page, ownerApi }) => {
  const { name } = (await (await ownerApi.get('/api/v1/organization')).json()) as { name: string };
  await page.goto('/dashboard/');
  const avatar = page.getByRole('button', { name: 'Account menu' });
  const menu = page.locator('#user-menu');
  const link = menu.getByRole('link', { name: `Organization ${name}` });

  await avatar.focus();
  await page.keyboard.press('Enter');
  await expect(menu).toBeVisible();
  await expect(link).toHaveAttribute('href', '/dashboard/organization/');
  await page.keyboard.press('Tab');
  await expect(link).toBeFocused();
  await expect(link).toHaveCSS('background-color', 'rgb(240, 243, 248)'); // the menu items' focus (ink-100)
  await page.keyboard.press('Tab');
  await expect(menu.getByRole('link', { name: 'Settings' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/dashboard\/organization\/$/);

  // There, the row says it's the page you're on.
  await page.getByRole('button', { name: 'Account menu' }).click();
  await expect(link).toHaveAttribute('aria-current', 'page');
});

/** The space between New link (whichever shows) and the avatar, and whether the header holds. */
function measureHeader() {
  const newLink = [...document.querySelectorAll<HTMLElement>('header [data-new-link]')].find((a) => a.offsetParent !== null)!;
  const avatar = document.querySelector<HTMLElement>('header [data-user-initial]')!;
  const header = document.querySelector<HTMLElement>('header > div')!;
  const label = newLink.getBoundingClientRect();
  return {
    gap: avatar.getBoundingClientRect().left - label.right,
    newLinkHeight: label.height,
    headerHeight: header.getBoundingClientRect().height,
    fits: document.documentElement.scrollWidth <= window.innerWidth,
    inside: [...header.querySelectorAll<HTMLElement>(':scope > *, :scope > div > *')]
      .filter((el) => el.offsetParent !== null)
      .every((el) => el.getBoundingClientRect().right <= window.innerWidth),
  };
}

const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
for (const width of [1440, 390, 360, 320]) {
  test.describe(`at ${width} px`, () => {
    test.use(width === 1440 ? { viewport: { width, height: 900 } } : { ...pixel, viewport: { width, height: 800 } });

    test('the header keeps 20 px between New link and the avatar, on one line', async ({ page }) => {
      await page.goto('/dashboard/');
      await expect(page.getByRole('button', { name: 'Account menu' })).toBeVisible();
      const shown = await page.evaluate(measureHeader);
      expect(shown.gap).toBe(20);
      expect(shown.newLinkHeight).toBe(32); // btn-sm: one line, no wrap
      expect(shown.headerHeight).toBe(64);
      expect(shown.fits).toBe(true);
      expect(shown.inside).toBe(true);
    });
  });
}
