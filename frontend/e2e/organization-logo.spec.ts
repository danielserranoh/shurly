// Phase 3.14.4, 3.14.6 — the organization's logo. For the owner, the logo in Settings → Organization is a button,
// with a camera badge, that opens the "Organization logo" dialog: a logo picked there is positioned and saved as a
// square PNG with its transparency, shown as a circle there and in the account menu, next to the organization's
// name, and still after a reload; removing it brings the initial back. A member sees the logo with no button, no
// badge, and nothing they drop goes anywhere. axe finds no moderate, serious or critical issue in any state, on a
// desktop and on a phone (390 px).

import type { Page } from '@playwright/test';

import { MEMBER_STATE } from './env';
import { expect, test } from './fixtures';
import { DEVICES, expectNoIssues, png, readImage, TRANSPARENT_LOGO } from './photos';

const LOGO = '/api/v1/organization/logo';

/** A 240×80 PNG, transparent around a blue square and a yellow bar: a logo from before 3.14.6, not square. */
const WIDE_LOGO = png(240, 80, (x, y) => (x >= 20 && x < 80 && y >= 10 && y < 70 ? [80, 87, 255, 255] : x >= 100 && x < 220 && y >= 30 && y < 50 ? [255, 209, 102, 255] : [0, 0, 0, 0]));

async function openOrganization(page: Page) {
  await page.goto('/dashboard/settings/#organization');
  const panel = page.getByRole('tabpanel', { name: 'Organization' });
  const block = panel.locator('[data-logo-block]');
  const dialog = page.getByRole('dialog', { name: 'Organization logo' });
  return { panel, block, dialog, frame: dialog.locator('[data-picker-frame]') };
}

for (const { device, options } of DEVICES) {
  test.describe(`on a ${device}`, () => {
    test.use(options);

    test('the owner’s logo is a button: a logo positioned in the dialog is saved square with its transparency, shows next to the name, and Remove brings the initial back', async ({ page, ownerApi }) => {
      // From no logo, whatever an earlier run left.
      await ownerApi.delete(LOGO);
      const { name } = (await (await ownerApi.get('/api/v1/organization')).json()) as { name: string };
      const { block, dialog, frame } = await openOrganization(page);
      const button = block.getByRole('button', { name: 'Change the organization’s logo' });

      await expect(button).toBeVisible();
      await expect(button.locator('[data-photo-badge]')).toBeVisible();
      await expect(block.locator('[data-logo-org-name]')).toHaveText(name);
      await expect(button.locator('[data-org-initial]')).toHaveText(name[0].toUpperCase());
      await expect(block.getByRole('button', { name: 'Upload logo' })).toHaveCount(0);

      await button.click();
      await expect(dialog).toBeVisible();
      await expect(frame).toHaveAttribute('data-shows', 'initials');
      await expect(frame.locator('[data-picker-initial]')).toHaveText(name[0].toUpperCase());
      await expect(dialog.getByText('Choose a logo to position it in the frame')).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'Remove logo' })).toBeHidden();
      await expect(dialog.getByRole('button', { name: 'Save logo' })).toBeDisabled();
      await expectNoIssues(page, 'the logo dialog, without a logo');

      await dialog.locator('[data-picker-file]').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: TRANSPARENT_LOGO });
      await expect(frame).toHaveAttribute('data-shows', 'new');
      await expect(dialog.getByRole('slider', { name: 'Zoom' })).toBeVisible();
      await expectNoIssues(page, 'the logo dialog, positioning');

      // Saved as a PNG (lossless, with its alpha), never enlarged: the 300×200 logo's 200 px square.
      const upload = page.waitForRequest((r) => r.url().includes(LOGO) && r.method() === 'PUT');
      await dialog.getByRole('button', { name: 'Save logo' }).click();
      expect((await upload).headers()['content-type']).toBe('image/png');
      await expect(page.getByText('Logo saved')).toBeVisible();
      await expect(dialog).toBeHidden();
      const shown = button.locator('img[data-org-logo]');
      await expect(shown).toBeVisible();
      await expect(shown).toHaveAttribute('src', /^blob:/);
      // What the API kept: square, transparent in the corners, the navy disc in the middle.
      const kept = await readImage(shown, [
        [0, 0],
        [0.5, 0.5],
      ]);
      expect(kept.size).toEqual([200, 200]);
      expect(kept.pixels[0][3]).toBe(0);
      expect(kept.pixels[1][3]).toBe(255);
      // On white in the circle, with a hairline ring.
      await expect(button.locator('[data-org-mark]')).toHaveAttribute('data-has-logo');
      await expect(button.locator('[data-org-mark]')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
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

      // The dialog shows it read-only; Remove, then Save.
      await button.click();
      await expect(frame).toHaveAttribute('data-shows', 'current');
      await expect(frame.getByRole('img', { name: 'The organization’s current logo' })).toHaveAttribute('src', /^blob:/);
      await expect(dialog.getByRole('slider', { name: 'Zoom' })).toBeHidden();
      await expect(dialog.getByRole('button', { name: 'Save logo' })).toBeDisabled();
      await expectNoIssues(page, 'the logo dialog, with a logo');
      await dialog.getByRole('button', { name: 'Remove logo' }).click();
      await expect(frame).toHaveAttribute('data-shows', 'initials');
      await expectNoIssues(page, 'the logo dialog, removed but not saved');
      await dialog.getByRole('button', { name: 'Save logo' }).click();
      await expect(page.getByText('Logo removed')).toBeVisible();
      await expect(shown).toBeHidden();
      await expect(button.locator('[data-org-initial]')).toBeVisible();
      await page.getByRole('button', { name: 'Account menu' }).click();
      await expect(menu.locator('img[data-org-logo]')).toBeHidden();
      await expect(menu.locator('[data-org-initial]')).toHaveText(name[0].toUpperCase());
    });

    test('a file that isn’t a JPEG, PNG or WebP is refused in the dialog, before it’s sent', async ({ page }) => {
      const { block, dialog } = await openOrganization(page);
      await block.getByRole('button', { name: 'Change the organization’s logo' }).click();
      await dialog.locator('[data-picker-file]').setInputFiles({ name: 'logo.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>') });
      await expect(dialog.getByRole('alert')).toHaveText('Use a JPEG, PNG or WebP image.');
      await expect(dialog.getByRole('button', { name: 'Save logo' })).toBeDisabled();
    });

    test('a logo saved before 3.14.6, not square, shows cut to the circle', async ({ page, ownerApi }) => {
      expect((await ownerApi.put(LOGO, { data: WIDE_LOGO, headers: { 'Content-Type': 'image/png' } })).ok()).toBe(true);
      const { block } = await openOrganization(page);
      const shown = block.locator('[data-logo-button] img[data-org-logo]');
      await expect(shown).toBeVisible();
      // The API kept its shape; the circle covers itself with it.
      expect((await readImage(shown, [])).size).toEqual([240, 80]);
      await expect(shown).toHaveCSS('object-fit', 'cover');
    });

    test.describe('as a member', () => {
      test.use({ storageState: MEMBER_STATE });

      test('they see the logo, with no button and no badge, and a file dropped or picked goes nowhere', async ({ page, ownerApi }) => {
        expect((await ownerApi.put(LOGO, { data: TRANSPARENT_LOGO, headers: { 'Content-Type': 'image/png' } })).ok()).toBe(true);
        const changes: string[] = [];
        page.on('request', (request) => {
          if (request.url().includes('/organization/logo') && request.method() !== 'GET') changes.push(`${request.method()} ${request.url()}`);
        });

        const { panel, block } = await openOrganization(page);
        const preview = block.getByRole('img', { name: 'The organization’s logo' });
        await expect(preview).toBeVisible();
        await expect(preview).toHaveAttribute('src', /^blob:/);
        await expect(block.getByRole('button')).toHaveCount(0);
        await expect(block.locator('[data-photo-badge]')).toBeHidden();
        await expect(block.locator('[data-logo-hint]')).toHaveText('Owners and admins can change it.');
        // Said once: the section's description doesn't repeat it.
        const section = panel.getByRole('region', { name: 'Logo' });
        expect((await section.innerText()).split('Owners and admins can').length - 1).toBe(1);

        // A file dropped on the logo: no outline, no dialog, nothing sent. Nor through the dialog's file input,
        // which nothing opens for them: the page checks the role first (the API's 403 is the guard; this keeps the
        // page quiet).
        const dropped = await page.evaluateHandle(() => {
          const data = new DataTransfer();
          data.items.add(new File(['not a logo'], 'logo.png', { type: 'image/png' }));
          return data;
        });
        const mark = block.locator('[data-logo-static]');
        await mark.dispatchEvent('dragover', { dataTransfer: dropped });
        await mark.dispatchEvent('drop', { dataTransfer: dropped });
        await page.locator('#logo-picker [data-picker-file]').setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: TRANSPARENT_LOGO });
        await page.waitForLoadState('networkidle');
        await expect(page.getByRole('dialog', { name: 'Organization logo' })).toBeHidden();
        expect(changes).toEqual([]);
        await expectNoIssues(page, 'settings, organization, as a member');

        // The account menu shows it too, next to the organization's name.
        await page.getByRole('button', { name: 'Account menu' }).click();
        await expect(page.locator('#user-menu img[data-org-logo]')).toBeVisible();
        await expectNoIssues(page, 'account menu with a logo, as a member');
      });

      test('without a logo, they see the initial and who can add one', async ({ page, ownerApi }) => {
        await ownerApi.delete(LOGO);
        const { name } = (await (await ownerApi.get('/api/v1/organization')).json()) as { name: string };

        const { block } = await openOrganization(page);
        await expect(block.locator('[data-logo-hint]')).toHaveText('No logo yet. Owners and admins can add one.');
        await expect(block.locator('[data-logo-static] [data-org-initial]')).toHaveText(name[0].toUpperCase());
        await expect(block.getByRole('button')).toHaveCount(0);
      });
    });
  });
}
