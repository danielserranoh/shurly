// Phase 3.14.4 — the organization's logo: the owner uploads one in Settings → Organization, it shows there and in
// the account menu, next to the organization's name, and still after a reload; removing it brings the initial
// back. axe finds no moderate, serious or critical issue with the logo in, on a desktop and on a phone (390 px).

import AxeBuilder from '@axe-core/playwright';
import { devices, type Page } from '@playwright/test';

import { expect, test } from './fixtures';

/** A 240×80 PNG, transparent around a blue square and a yellow bar: a logo that isn't square. */
const LOGO_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAPAAAABQCAYAAAAnSfh8AAAA40lEQVR42u3cQQ2AMAyG0ZbsPEXIQsZkoWgGigcOsMB7Ev7kS2/NflQFt82RaQXespkABAwIGBAwCBgQMCBgQMAgYEDAgIBBwICAAQEDAgYBAwIGBAwIGL6hmWAtdYYfZbjAIGBAwICAAQGDgAEBAwIGAQMCBgQMCBgEDAgYEDAgYBAwIGBAwCBgQMCAgAEBg4ABAQMCBgQMAgYEDAgYBAwIGBAwIGAQMCBgQMAgYEDAwLOaCdaSe6QVcIFBwICAAQEDAgYBAwIGBAwCBgQMCBgQMAgYEDAgYEDAIGBAwICA4WcuxGUHpGKx95UAAAAASUVORK5CYII=',
  'base64',
);

/** Every impact but minor, as a11y.spec.ts. */
const IMPACTS = ['moderate', 'serious', 'critical'];

async function expectNoIssues(page: Page, name: string) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const found = violations
    .filter((v) => IMPACTS.includes(v.impact ?? ''))
    .flatMap((v) => v.nodes.map((node) => ({ rule: v.id, impact: v.impact, target: node.target.join(' '), summary: node.failureSummary ?? v.help })));
  expect(found, `axe on ${name}: ${IMPACTS.join(', ')} issues`).toEqual([]);
}

const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
const DEVICES = [
  { device: 'desktop', options: {} },
  { device: 'phone', options: { ...pixel, viewport: { width: 390, height: 844 } } },
];

for (const { device, options } of DEVICES) {
  test.describe(`on a ${device}`, () => {
    test.use(options);

    test('the owner uploads a logo, it shows next to the name, and removing it brings the initial back', async ({ page, ownerApi }) => {
      // From no logo, whatever an earlier run left.
      await ownerApi.delete('/api/v1/organization/logo');
      const { name } = (await (await ownerApi.get('/api/v1/organization')).json()) as { name: string };

      await page.goto('/dashboard/settings/#organization');
      const panel = page.getByRole('tabpanel', { name: 'Organization' });
      const block = panel.locator('[data-logo-block]');
      const preview = block.getByRole('img', { name: 'The organization’s logo' });
      await expect(block.getByRole('button', { name: 'Upload logo' })).toBeVisible();
      await expect(block.getByRole('button', { name: 'Remove' })).toBeHidden();
      await expect(block.locator('[data-org-initial]')).toHaveText(name[0].toUpperCase());

      await block.locator('[data-logo-file]').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: LOGO_PNG });
      await expect(page.getByText('Logo saved')).toBeVisible();
      await expect(preview).toBeVisible();
      await expect(preview).toHaveAttribute('src', /^blob:/);
      // Its shape kept: 240×80 is stored as it is (fits within 512), never cropped to a square.
      expect(await preview.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight])).toEqual([240, 80]);
      await expect(block.getByRole('button', { name: 'Remove' })).toBeVisible();
      await expectNoIssues(page, 'settings, organization with a logo');

      // The account menu shows it next to the name, then and after a reload.
      const menu = page.locator('#user-menu');
      for (const reload of [false, true]) {
        if (reload) await page.reload();
        await page.getByRole('button', { name: 'Account menu' }).click();
        await expect(menu).toBeVisible();
        await expect(menu.locator('[data-user-org-name]')).toHaveText(name);
        await expect(menu.locator('img[data-org-logo]')).toBeVisible();
        await expect(menu.locator('img[data-org-logo]')).toHaveAttribute('src', /^blob:/);
        await expectNoIssues(page, 'account menu with a logo');
        await page.keyboard.press('Escape');
        await expect(menu).toBeHidden();
      }
      await expect(preview).toBeVisible();

      await block.getByRole('button', { name: 'Remove' }).click();
      await expect(page.getByText('Logo removed')).toBeVisible();
      await expect(preview).toBeHidden();
      await expect(block.locator('[data-org-initial]')).toBeVisible();
      await page.getByRole('button', { name: 'Account menu' }).click();
      await expect(menu.locator('img[data-org-logo]')).toBeHidden();
      await expect(menu.locator('[data-org-initial]')).toHaveText(name[0].toUpperCase());
    });

    test('a file that isn’t a JPEG, PNG or WebP is refused before it’s sent', async ({ page }) => {
      await page.goto('/dashboard/settings/#organization');
      const block = page.getByRole('tabpanel', { name: 'Organization' }).locator('[data-logo-block]');
      await expect(block.getByRole('button', { name: 'Upload logo' })).toBeVisible();

      await block.locator('[data-logo-file]').setInputFiles({ name: 'logo.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>') });
      await expect(block.getByRole('alert')).toHaveText('Use a JPEG, PNG or WebP image.');
    });
  });
}
