// Phase 8.7 — previews from the page: a link's page says which parts of its social preview are the page's own and
// which were set for it, and "Use the page’s preview" drops what was set. (The e2e API reads no page: its fetcher
// answers with nothing, so the page's parts are "none" here.)

import { expect, test } from './fixtures';

test('a rewritten preview says so, and goes back to the page’s', async ({ page, ownerApi }) => {
  const made = await ownerApi.post('/api/v1/urls', {
    data: { url: `https://example.com/e2e/preview/${Date.now()}`, og_title: 'Our own title' },
  });
  expect(made.ok()).toBeTruthy();
  const { short_code: code } = (await made.json()) as { short_code: string };

  await page.goto(`/dashboard/link/?code=${code}`);
  const preview = page.getByRole('region', { name: 'Social preview' });
  const sources = preview.getByRole('list', { name: 'Where each part comes from' });
  await expect(preview).toContainText('Our own title');
  await expect(sources).toContainText('Title: yours');
  await expect(sources).toContainText('Image: none');

  await preview.getByRole('button', { name: 'Use the page’s preview' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Use the page’s preview' }).click();

  await expect(sources).toContainText('Title: none');
  await expect(preview.getByRole('button', { name: 'Use the page’s preview' })).toHaveCount(0);
  const link = await (await ownerApi.get(`/api/v1/urls/${code}`)).json();
  expect(link.og_title).toBeNull();
});

test('the editor shows each field’s source, and empties them to use the page’s', async ({ page, ownerApi }) => {
  const made = await ownerApi.post('/api/v1/urls', {
    data: { url: `https://example.com/e2e/editor/${Date.now()}`, og_description: 'Our own words' },
  });
  const { short_code: code } = (await made.json()) as { short_code: string };

  await page.goto(`/dashboard/link/?code=${code}`);
  await page.getByRole('button', { name: 'Edit preview' }).click();
  const dialog = page.getByRole('dialog', { name: 'Edit link' });
  await expect(dialog.getByText('· yours')).toBeVisible();
  await expect(dialog.getByLabel(/Preview description/)).toHaveValue('Our own words');

  await dialog.getByRole('button', { name: 'Use the page’s' }).click();
  await expect(dialog.getByLabel(/Preview description/)).toHaveValue('');
  await dialog.getByRole('button', { name: 'Save changes' }).click();

  await expect(dialog).toBeHidden();
  const link = await (await ownerApi.get(`/api/v1/urls/${code}`)).json();
  expect(link.og_description).toBeNull();
});
