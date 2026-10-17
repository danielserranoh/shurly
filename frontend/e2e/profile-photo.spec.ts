// Phase 3.12.10 — the photo in Settings → Account is a button, with a camera badge, and opens the "Profile photo"
// dialog: the saved photo shown read-only, or the initial; Change photo positions a new one (keys, + and −), and
// Save uploads it; Remove photo shows the initial, and Save deletes it; Cancel and Esc keep what there was. A file
// dropped on the photo opens the dialog with it. axe finds no moderate, serious or critical issue in any state, on
// a desktop and on a phone (390 px).

import type { APIRequestContext, Page } from '@playwright/test';

import { expect, test } from './fixtures';
import { DEVICES, expectNoIssues, PHOTO, readImage } from './photos';

const AVATAR = '/api/v1/auth/me/avatar';

async function avatarVersion(api: APIRequestContext): Promise<string | null> {
  const me = (await (await api.get('/api/v1/auth/me')).json()) as { profile?: { avatar_version?: string | null } };
  return me.profile?.avatar_version ?? null;
}

async function setPhoto(api: APIRequestContext) {
  expect((await api.put(AVATAR, { data: PHOTO, headers: { 'Content-Type': 'image/png' } })).ok()).toBe(true);
}

async function openAccount(page: Page) {
  await page.goto('/dashboard/settings/');
  const block = page.locator('[data-avatar-block]');
  const button = block.getByRole('button', { name: 'Change your photo' });
  await expect(button).toBeEnabled(); // once the account has loaded
  const dialog = page.getByRole('dialog', { name: 'Profile photo' });
  return { block, button, dialog, frame: dialog.locator('[data-picker-frame]') };
}

for (const { device, options } of DEVICES) {
  test.describe(`on a ${device}`, () => {
    test.use(options);

    test('without a photo: the button shows the initial, the name and email; Change positions one and Save uploads it', async ({ page, ownerApi }) => {
      await ownerApi.delete(AVATAR);
      const me = (await (await ownerApi.get('/api/v1/auth/me')).json()) as { email: string };
      const { block, button, dialog, frame } = await openAccount(page);

      // The photo is the button: the initial, a camera badge always there, and the email next to it.
      await expect(block.locator('[data-avatar-initial]')).toBeVisible();
      await expect(button.locator('[data-photo-badge]')).toBeVisible();
      await expect(block).toContainText(me.email);
      await expect(block.getByRole('button', { name: 'Upload photo' })).toHaveCount(0);
      await expect(block.getByRole('button', { name: 'Remove' })).toHaveCount(0);

      // Focus shows the overlay, and a focus ring.
      await button.focus();
      await expect(button.locator('[data-photo-overlay]')).toHaveCSS('opacity', '1');
      expect(await button.evaluate((el) => getComputedStyle(el).outlineStyle)).not.toBe('none');

      await button.click();
      await expect(dialog).toBeVisible();
      await expect(frame).toHaveAttribute('data-shows', 'initials');
      await expect(frame.locator('[data-picker-initial]')).toBeVisible();
      await expect(dialog.getByText('Choose a photo to position it in the frame')).toBeVisible();
      await expect(dialog.getByText('JPEG, PNG or WebP, up to 10 MB.')).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'Remove photo' })).toBeHidden();
      await expect(dialog.getByRole('slider', { name: 'Zoom' })).toBeHidden();
      await expect(dialog.getByRole('button', { name: 'Save photo' })).toBeDisabled();
      await expectNoIssues(page, 'the photo dialog, without a photo');

      // Change photo: picked, then positioned.
      await dialog.locator('[data-picker-file]').setInputFiles({ name: 'me.png', mimeType: 'image/png', buffer: PHOTO });
      await expect(frame).toHaveAttribute('data-shows', 'new');
      await expect(frame).toBeFocused();
      await expect(dialog.getByRole('slider', { name: 'Zoom' })).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'Remove photo' })).toBeVisible();
      await expect(dialog.getByRole('button', { name: 'Save photo' })).toBeEnabled();
      const crop = frame.locator('[data-picker-crop]');
      const before = await crop.evaluate((img: HTMLImageElement) => img.style.transform);
      await page.keyboard.press('ArrowLeft');
      await expect.poll(() => crop.evaluate((img: HTMLImageElement) => img.style.transform)).not.toBe(before);
      const zoomBefore = await dialog.getByRole('slider', { name: 'Zoom' }).inputValue();
      await page.keyboard.press('+');
      await expect(dialog.getByRole('slider', { name: 'Zoom' })).not.toHaveValue(zoomBefore);
      await expectNoIssues(page, 'the photo dialog, positioning');

      // Save: the square goes up as a WebP, and the photo shows, here and in the header.
      const upload = page.waitForRequest((r) => r.url().includes(AVATAR) && r.method() === 'PUT');
      await dialog.getByRole('button', { name: 'Save photo' }).click();
      expect((await upload).headers()['content-type']).toBe('image/webp');
      await expect(page.getByText('Photo saved')).toBeVisible();
      await expect(dialog).toBeHidden();
      const image = block.locator('img[data-avatar-image]');
      await expect(image).toBeVisible();
      await expect(image).toHaveAttribute('src', /^blob:/);
      expect((await readImage(image, [])).size).toEqual([512, 512]);
      await expect(block.locator('[data-avatar-initial]')).toBeHidden();
      await expect(page.getByRole('button', { name: 'Account menu' }).locator('img')).toHaveAttribute('src', /^blob:/);
      expect(await avatarVersion(ownerApi)).not.toBeNull();
    });

    test('with a photo: the dialog shows it read-only, and Remove then Save goes back to the initial', async ({ page, ownerApi }) => {
      await setPhoto(ownerApi);
      const { block, button, dialog, frame } = await openAccount(page);
      await expect(block.locator('img[data-avatar-image]')).toBeVisible();

      await button.click();
      await expect(frame).toHaveAttribute('data-shows', 'current');
      const current = frame.getByRole('img', { name: 'Your current photo' });
      await expect(current).toBeVisible();
      await expect(current).toHaveAttribute('src', /^blob:/);
      // Read-only: nothing to move or zoom, and nothing to save yet.
      await expect(frame).not.toHaveAttribute('tabindex');
      await expect(dialog.getByRole('slider', { name: 'Zoom' })).toBeHidden();
      await expect(frame.locator('[data-picker-crop]')).toBeHidden();
      const box = (await frame.boundingBox())!;
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 + 30);
      await page.mouse.up();
      expect(await current.evaluate((img: HTMLImageElement) => img.style.transform)).toBe('');
      await expect(dialog.getByRole('button', { name: 'Save photo' })).toBeDisabled();
      await expectNoIssues(page, 'the photo dialog, with a photo');

      // Remove photo: the initial, and Save deletes it.
      await dialog.getByRole('button', { name: 'Remove photo' }).click();
      await expect(frame).toHaveAttribute('data-shows', 'initials');
      await expect(frame.locator('[data-picker-initial]')).toBeVisible();
      await expect(current).toBeHidden();
      await expect(dialog.getByRole('button', { name: 'Remove photo' })).toBeHidden();
      await expect(dialog.getByRole('button', { name: 'Change photo' })).toBeFocused();
      await expect(dialog.getByRole('button', { name: 'Save photo' })).toBeEnabled();
      await expectNoIssues(page, 'the photo dialog, removed but not saved');

      await dialog.getByRole('button', { name: 'Save photo' }).click();
      await expect(page.getByText('Photo removed')).toBeVisible();
      await expect(dialog).toBeHidden();
      await expect(block.locator('img[data-avatar-image]')).toBeHidden();
      await expect(block.locator('[data-avatar-initial]')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Account menu' }).locator('img')).toHaveCount(0);
      expect(await avatarVersion(ownerApi)).toBeNull();
    });

    test('Cancel and Esc keep the photo there was', async ({ page, ownerApi }) => {
      await setPhoto(ownerApi);
      const version = await avatarVersion(ownerApi);
      const sent: string[] = [];
      page.on('request', (r) => {
        if (r.url().includes(AVATAR) && r.method() !== 'GET') sent.push(r.method());
      });
      const { block, button, dialog, frame } = await openAccount(page);

      // Remove, then Cancel.
      await button.click();
      await dialog.getByRole('button', { name: 'Remove photo' }).click();
      await expect(frame).toHaveAttribute('data-shows', 'initials');
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(dialog).toBeHidden();
      await expect(block.locator('img[data-avatar-image]')).toBeVisible();

      // Opened again: the photo, as it was.
      await button.click();
      await expect(frame).toHaveAttribute('data-shows', 'current');
      await expect(dialog.getByRole('button', { name: 'Save photo' })).toBeDisabled();

      // Change, then Esc.
      await dialog.locator('[data-picker-file]').setInputFiles({ name: 'me.png', mimeType: 'image/png', buffer: PHOTO });
      await expect(frame).toHaveAttribute('data-shows', 'new');
      await page.keyboard.press('Escape');
      await expect(dialog).toBeHidden();
      await expect(block.locator('img[data-avatar-image]')).toBeVisible();

      expect(sent).toEqual([]);
      expect(await avatarVersion(ownerApi)).toBe(version);
    });

    test('a file dropped on the photo opens the dialog with it, ready to position; one that isn’t an image says so there', async ({ page, ownerApi }) => {
      await ownerApi.delete(AVATAR);
      const { button, dialog, frame } = await openAccount(page);

      const drop = async (base64: string, name: string, type: string) => {
        const data = await page.evaluateHandle(
          ([bytes, fileName, fileType]) => {
            const transfer = new DataTransfer();
            transfer.items.add(new File([Uint8Array.from(atob(bytes), (c) => c.charCodeAt(0))], fileName, { type: fileType }));
            return transfer;
          },
          [base64, name, type],
        );
        await button.dispatchEvent('dragover', { dataTransfer: data });
        await expect(button).toHaveAttribute('data-dragging');
        await expect(button.locator('[data-photo-overlay]')).toHaveCSS('opacity', '1');
        await button.dispatchEvent('drop', { dataTransfer: data });
      };

      await drop(PHOTO.toString('base64'), 'me.png', 'image/png');
      await expect(dialog).toBeVisible();
      await expect(frame).toHaveAttribute('data-shows', 'new');
      await expect(button).not.toHaveAttribute('data-dragging');
      await expect(dialog.getByRole('button', { name: 'Save photo' })).toBeEnabled();
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(dialog).toBeHidden();

      await drop(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>').toString('base64'), 'me.svg', 'image/svg+xml');
      await expect(dialog).toBeVisible();
      await expect(dialog.getByRole('alert')).toHaveText('Use a JPEG, PNG or WebP image.');
      await expect(frame).toHaveAttribute('data-shows', 'initials');
      await expect(dialog.getByRole('button', { name: 'Save photo' })).toBeDisabled();
      await expectNoIssues(page, 'the photo dialog, with a file refused');
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      expect(await avatarVersion(ownerApi)).toBeNull();
    });
  });
}
