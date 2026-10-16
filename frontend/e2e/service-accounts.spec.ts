// Phase 10.1 — service accounts (_pm/spec_service_accounts.md), in Settings → Organization:
// - the owner makes one and its token; the token shows once, with Copy and "you won't see it again", and after
//   Done only its prefix is left;
// - the service, with that token, makes a link for the member (X-Shurly-On-Behalf-Of): its page and its card
//   say "Created by <member> via <service>", and the links list filters by the service;
// - a member doesn't see the section;
// - axe finds no moderate, serious or critical issue, with the list and with the token dialog open, on a
//   desktop and on a phone (390 px).

import AxeBuilder from '@axe-core/playwright';
import { devices, type APIRequestContext, type Page } from '@playwright/test';

import { API_URL, MEMBER, MEMBER_STATE } from './env';
import { expect, test } from './fixtures';

const IMPACTS = ['moderate', 'serious', 'critical'];

async function expectNoIssues(page: Page, name: string) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const found = violations
    .filter((v) => IMPACTS.includes(v.impact ?? ''))
    .flatMap((v) => v.nodes.map((node) => ({ rule: v.id, impact: v.impact, target: node.target.join(' '), summary: node.failureSummary ?? v.help })));
  expect(found, `axe on ${name}: ${IMPACTS.join(', ')} issues`).toEqual([]);
}

interface Account {
  id: string;
  display_name: string;
}

/** Whatever an earlier run left: this spec's service accounts go, so the list starts clean. */
async function removeEarlier(ownerApi: APIRequestContext) {
  const accounts = (await (await ownerApi.get('/api/v1/service-accounts')).json()) as Account[];
  for (const account of accounts.filter((a) => a.display_name.startsWith('Propuestas E2E'))) {
    await ownerApi.delete(`/api/v1/service-accounts/${account.id}`);
  }
}

const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
const DEVICES = [
  { device: 'desktop', options: {} },
  { device: 'phone', options: { ...pixel, viewport: { width: 390, height: 844 } } },
];

for (const { device, options } of DEVICES) {
  test.describe(`on a ${device}`, () => {
    test.use(options);

    test('the owner makes a service account and its token, shown once; its links say who they’re for', async ({ page, ownerApi, playwright, context }) => {
      await context.grantPermissions(['clipboard-read', 'clipboard-write']);
      await removeEarlier(ownerApi);
      const name = `Propuestas E2E ${device}`;

      await page.goto('/dashboard/settings/#organization');
      const panel = page.getByRole('tabpanel', { name: 'Organization' });
      const section = panel.getByRole('region', { name: /Service accounts/ });
      await expect(section).toBeVisible();
      await section.getByRole('button', { name: 'New service account' }).click();

      const form = page.getByRole('dialog', { name: 'New service account' });
      await form.getByLabel('Name').fill(name);
      await form.getByLabel(/What it’s for/).fill('Hosts proposals and shortens their links');
      await form.getByRole('button', { name: 'Create service account' }).click();

      // Straight on to its token.
      const tokenDialog = page.getByRole('dialog', { name: `Create the token of ${name}` });
      await expect(tokenDialog).toBeVisible();
      await expectNoIssues(page, `the token dialog, ${device}`);
      await tokenDialog.getByRole('button', { name: 'Create token' }).click();
      await expect(tokenDialog.getByText('you won’t see it again')).toBeVisible();
      const token = (await tokenDialog.locator('[data-token-value]').textContent())?.trim() ?? '';
      expect(token).toMatch(/^shsa_[0-9a-f]{8}_[\w-]{43,}$/);
      // Before Copy: its "Copied!" fades in, and axe would measure the colours halfway.
      await expectNoIssues(page, `the token, shown once, ${device}`);
      await tokenDialog.getByRole('button', { name: 'Copy token' }).click();
      await expect(tokenDialog.getByRole('button', { name: /Copied!/ })).toBeVisible();
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(token);
      await tokenDialog.getByRole('button', { name: 'Done' }).click();
      await expect(tokenDialog).toBeHidden();

      // Then only how it starts.
      const prefix = token.split('_').slice(0, 2).join('_');
      const row = section.getByRole('listitem').filter({ hasText: name });
      await expect(row).toContainText(`${prefix}…`);
      await expect(row).toContainText('Not used yet');
      expect(await page.content()).not.toContain(token);
      await expectNoIssues(page, `service accounts, ${device}`);

      // The service makes a link for the member.
      const service = await playwright.request.newContext({
        baseURL: API_URL,
        extraHTTPHeaders: { Authorization: `Bearer ${token}`, 'X-Shurly-On-Behalf-Of': MEMBER },
      });
      const made = await service.post('/api/v1/urls', { data: { url: 'https://example.com/proposal', title: `Proposal ${device}` } });
      expect(made.status()).toBe(201);
      const link = (await made.json()) as { short_code: string; domain: string; via_service_account: Account };
      expect(link.via_service_account.display_name).toBe(name);
      const unknown = await service.post('/api/v1/urls', {
        data: { url: 'https://example.com/proposal' },
        headers: { 'X-Shurly-On-Behalf-Of': 'nobody@griddo.io' },
      });
      expect(unknown.status()).toBe(422);
      expect(((await unknown.json()) as { code: string }).code).toBe('on_behalf_of_unknown');
      await service.dispose();

      await page.goto(`/dashboard/link/?code=${link.short_code}&domain=${link.domain}`);
      await expect(page.locator('[data-meta]')).toContainText(`by ${MEMBER} via ${name}`);

      // The links list, filtered by the service.
      await page.goto('/dashboard/?type=all');
      const via = page.getByLabel('Made via');
      await expect(via).toBeVisible();
      await via.selectOption({ label: name });
      await expect(page).toHaveURL(/via_service_account=/);
      const cards = page.locator('#link-list > li');
      await expect(cards).toHaveCount(1);
      await expect(cards.first()).toContainText(`Created by ${MEMBER} via ${name}`);
      await expectNoIssues(page, `links filtered by a service, ${device}`);

      // Its last use shows, and revoking it locks it out at once.
      await page.goto('/dashboard/settings/#organization');
      await expect(row).toContainText('Last used');
      // What the token made, for when it may have leaked.
      await row.getByRole('button', { name: /^Links made with it/ }).click();
      const madeWith = page.getByRole('dialog', { name: `Links made with ${prefix}…` });
      await expect(madeWith.getByRole('listitem')).toHaveCount(1);
      await expect(madeWith).toContainText(`${MEMBER} via ${name}`);
      await expectNoIssues(page, `the links a token made, ${device}`);
      await madeWith.getByRole('button', { name: 'Close' }).last().click();
      await expect(madeWith).toBeHidden();
      await row.getByRole('button', { name: 'Revoke' }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Revoke token' }).click();
      await expect(page.getByText('Token revoked')).toBeVisible();
      const revoked = await playwright.request.newContext({ baseURL: API_URL, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
      expect((await revoked.get('/api/v1/auth/me')).status()).toBe(401);
      await revoked.dispose();

      await removeEarlier(ownerApi);
    });

    test('“How to connect one” opens the manual’s page for owners', async ({ page }) => {
      await page.goto('/dashboard/settings/#organization');
      await page.getByRole('tabpanel', { name: 'Organization' }).getByRole('link', { name: 'How to connect one' }).click();
      await expect(page).toHaveURL('/manual/connect-a-service/');
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Connect another service');
      await expectNoIssues(page, `the manual's service accounts page, ${device}`);
    });

    test.describe('as a member', () => {
      test.use({ storageState: MEMBER_STATE });

      test('the section isn’t there', async ({ page }) => {
        await page.goto('/dashboard/settings/#organization');
        const panel = page.getByRole('tabpanel', { name: 'Organization' });
        await expect(panel.getByRole('heading', { name: 'Members' })).toBeVisible();
        await expect(panel.getByRole('heading', { name: 'Service accounts' })).toBeHidden();
      });
    });
  });
}
