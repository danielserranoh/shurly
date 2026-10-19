// Phase 10.1 — service accounts (_pm/spec_service_accounts.md), on the Organization page (/dashboard/organization/):
// - the owner makes one and its token; the token shows once, with Copy and "you won't see it again", and after
//   Done only its prefix is left;
// - the service, with that token, makes a link for the member (X-Shurly-On-Behalf-Of): its page and its card
//   say "Created by <member> via <service>";
// - Phase 10.3: the service manages that link: it's in the service's tab on the links list (from an older
//   "Made via" address too, and from "Its links"), read-only, and not under Links;
// - Phase 10.2: the token form asks what it may do (every scope to start with, at least one), where from (IP
//   ranges, one per line, a bad one refused on its field) and when it expires (a year from today, or No expiry);
//   the token's line says them, and "Expires soon" when it does, with the avatar's dot; a renewal starts from them;
//   the API holds the token to its scopes; Activity lists what the account did, for whom and by whom, with Load more;
// - a member doesn't see the section;
// - axe finds no moderate, serious or critical issue, with the list and with the token dialog open, on a
//   desktop and on a phone (390 px).

import AxeBuilder from '@axe-core/playwright';
import { devices, type APIRequestContext, type Page } from '@playwright/test';

import { API_URL, MEMBER, MEMBER_STATE } from './env';
import { expect, test } from './fixtures';
import { pick } from './helpers';

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

/** A service account made straight through the API, the owner responsible: for what a test needs, not tests. */
async function makeAccount(ownerApi: APIRequestContext, name: string): Promise<Account> {
  const me = (await (await ownerApi.get('/api/v1/auth/me')).json()) as { id: string };
  const made = await ownerApi.post('/api/v1/service-accounts', { data: { display_name: name, responsible_user_id: me.id, role: 'member' } });
  expect(made.status()).toBe(201);
  return (await made.json()) as Account;
}

/** Whatever an earlier run left: this spec's service accounts go, so the list starts clean. */
async function removeEarlier(ownerApi: APIRequestContext) {
  // Phase 10.3 — a removed account keeps managing its links, and its tab with them: delete
  // earlier runs' managed links first (an owner's override), or their tabs pile up by name.
  const managers = (await (await ownerApi.get('/api/v1/urls/managers')).json()) as Account[];
  for (const manager of managers.filter((m) => m.display_name?.startsWith('Propuestas E2E'))) {
    const { urls } = (await (await ownerApi.get(`/api/v1/urls?managed_by=${manager.id}&limit=100`)).json()) as {
      urls: { short_code: string; domain: string }[];
    };
    for (const link of urls) {
      const gone = await ownerApi.post(`/api/v1/urls/${link.short_code}/override-delete?domain=${encodeURIComponent(link.domain)}`, {
        data: { reason: 'Clean-up after an end-to-end run' },
      });
      expect(gone.status()).toBe(204);
    }
  }
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

      await page.goto('/dashboard/organization/');
      const panel = page.getByRole('main');
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

      // Phase 10.3 — its links are managed by it: in its own tab on the links list, not under Links. An older
      // address (the "Made via" filter's) opens that tab.
      const accountId = link.via_service_account.id;
      await page.goto(`/dashboard/?type=all&via_service_account=${accountId}`);
      await expect(page).toHaveURL(new RegExp(`/dashboard/\\?managed_by=${accountId}$`));
      const tab = page.getByRole('radio', { name, exact: true });
      await expect(tab).toBeChecked();
      await expect(page.getByRole('heading', { name: new RegExp(`^Links from ${name}`) })).toBeVisible();
      await expect(page.getByText(`Managed by ${name}. Its links are read-only here`)).toBeVisible();
      const cards = page.locator('#link-list > li');
      await expect(cards).toHaveCount(1);
      await expect(cards.first()).toContainText(`Created by ${MEMBER} via ${name}`);
      await expect(cards.first()).toContainText(`Managed by ${name}`);
      // Read-only: no Edit and no Delete, only where they happen.
      await cards.first().getByRole('button', { name: /^More actions for/ }).click();
      const menu = cards.first().locator('[popover]');
      await expect(menu.locator('[data-action="edit"], [data-action="delete"]')).toHaveCount(0);
      await expect(menu.getByText(`Delete via ${name}`)).toHaveAttribute('aria-disabled', 'true');
      await page.keyboard.press('Escape');
      await expectNoIssues(page, `a service account's tab, ${device}`);
      if (device === 'phone') {
        // Its tab among the others scrolls sideways; the page doesn't.
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      }

      // Links leaves it out.
      await pick(page.getByRole('radio', { name: 'Links', exact: true }));
      await expect(page).toHaveURL(/\/dashboard\/$/);
      await expect(cards.filter({ hasText: `Proposal ${device}` })).toHaveCount(0);

      // "Its links", on the Organization page, opens the same tab.
      await page.goto('/dashboard/organization/');
      await row.getByRole('button', { name: `More actions for ${name}` }).click();
      await row.getByRole('link', { name: 'Its links' }).click();
      await expect(page).toHaveURL(new RegExp(`/dashboard/\\?managed_by=${accountId}$`));
      await expect(tab).toBeChecked();
      await expect(cards).toHaveCount(1);

      // Its last use shows, and revoking it locks it out at once.
      await page.goto('/dashboard/organization/');
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

    test('a token says what it may do, where from and when it ends; it warns, and Activity says what it did', async ({ page, ownerApi, playwright }) => {
      test.setTimeout(90_000);
      await removeEarlier(ownerApi);
      const name = `Propuestas E2E scopes ${device}`;
      const account = await makeAccount(ownerApi, name);

      await page.goto('/dashboard/organization/');
      const section = page.getByRole('main').getByRole('region', { name: /Service accounts/ });
      const row = section.getByRole('listitem').filter({ hasText: name });
      await row.getByRole('button', { name: 'Create token' }).click();
      const tokenDialog = page.getByRole('dialog', { name: `Create the token of ${name}` });
      await expect(tokenDialog).toBeVisible();

      // Every scope to start with, a year from today, anywhere.
      const scopes = tokenDialog.getByRole('group', { name: 'What it may do' }).getByRole('checkbox');
      await expect(scopes).toHaveCount(6);
      for (const box of await scopes.all()) await expect(box).toBeChecked();
      const expires = tokenDialog.getByLabel('Expires', { exact: true });
      await expect(expires).toHaveValue(new RegExp(`^${new Date().getFullYear() + 1}-\\d{2}-\\d{2}$`));
      await expect(tokenDialog.getByText('This page warns 14 days before it expires')).toBeVisible();
      const ranges = tokenDialog.getByLabel(/Allowed IP ranges/);
      await expect(ranges).toHaveValue('');
      await expectNoIssues(page, `the token form, ${device}`);

      // At least one.
      for (const box of await scopes.all()) await box.uncheck();
      await tokenDialog.getByRole('button', { name: 'Create token' }).click();
      await expect(tokenDialog.getByText('Pick at least one thing it may do.')).toBeVisible();
      await expect(scopes.first()).toBeFocused();

      // A range that isn't one: the API's 422, on its field.
      await tokenDialog.getByRole('checkbox', { name: /^See links, campaigns and tags/ }).check();
      await tokenDialog.getByRole('checkbox', { name: /^Make and change links/ }).check();
      await tokenDialog.getByRole('checkbox', { name: /^Act for people/ }).check();
      await ranges.fill('127.0.0.0/8\nnot-a-range');
      await tokenDialog.getByRole('button', { name: 'Create token' }).click();
      await expect(tokenDialog.locator('[data-error-for="allowed_ip_ranges"]')).toContainText('an IP range (CIDR)');
      await expect(ranges).toHaveAttribute('aria-invalid', 'true');
      await expectNoIssues(page, `the token form with an error, ${device}`);

      // Fixed, and no expiry: made.
      await ranges.fill('127.0.0.0/8\n::1/128');
      await tokenDialog.getByRole('checkbox', { name: 'No expiry' }).check();
      await expect(expires).toBeDisabled();
      await tokenDialog.getByRole('button', { name: 'Create token' }).click();
      await expect(tokenDialog.getByText('you won’t see it again')).toBeVisible();
      const token = (await tokenDialog.locator('[data-token-value]').textContent())?.trim() ?? '';
      expect(token).toMatch(/^shsa_/);
      await tokenDialog.getByRole('button', { name: 'Done' }).click();
      await expect(row).toContainText('See links, change links, act for people');
      await expect(row).toContainText('From 127.0.0.0/8 and ::1/128');
      await expect(row).toContainText('Doesn’t expire');
      await expect(row.locator('.badge-warn')).toHaveCount(0);

      // The API holds it to them: it makes a link for the member, and may not delete it.
      const service = await playwright.request.newContext({
        baseURL: API_URL,
        extraHTTPHeaders: { Authorization: `Bearer ${token}`, 'X-Shurly-On-Behalf-Of': MEMBER },
      });
      const made = await service.post('/api/v1/urls', { data: { url: 'https://example.com/scoped', title: `Scoped ${device}` } });
      expect(made.status()).toBe(201);
      const { short_code: code } = (await made.json()) as { short_code: string };
      const refused = await service.delete(`/api/v1/urls/${code}`);
      expect(refused.status()).toBe(403);
      expect(((await refused.json()) as { code: string }).code).toBe('scope_missing');

      // Renewed to end within a week: it warns, on its line and on the avatar. The rest is inherited.
      const renewed = await ownerApi.post(`/api/v1/service-accounts/${account.id}/token`, {
        data: { expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString() },
      });
      expect(renewed.status()).toBe(201);
      await page.reload();
      await expect(row.locator('.badge-warn')).toHaveText('Expires soon');
      await expect(row).toContainText('From 127.0.0.0/8 and ::1/128');
      const avatar = page.getByRole('button', { name: /^Account menu, \d+ service tokens? needs? attention$/ });
      await expect(avatar).toBeVisible();
      await expect(page.locator('[data-attention-dot]')).toBeVisible();
      await expectNoIssues(page, `a token that warns, ${device}`);

      // Renewing in the page starts from what the token may do, and where from.
      await row.getByRole('button', { name: 'Renew token' }).click();
      const renewDialog = page.getByRole('dialog', { name: `Renew the token of ${name}` });
      await expect(renewDialog.getByRole('checkbox', { name: /^See links, campaigns and tags/ })).toBeChecked();
      await expect(renewDialog.getByRole('checkbox', { name: /^Delete links/ })).not.toBeChecked();
      await expect(renewDialog.getByLabel(/Allowed IP ranges/)).toHaveValue('127.0.0.0/8\n::1/128');
      await renewDialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(renewDialog).toBeHidden();

      // On a desktop, enough links for a second page of activity.
      const extra = device === 'desktop' ? 48 : 0;
      for (let i = 0; i < extra; i++) {
        expect((await service.post('/api/v1/urls', { data: { url: `https://example.com/scoped/${i}` } })).status()).toBe(201);
      }
      await service.dispose();

      // Activity: what it did and for whom, what was done to it and by whom.
      await row.getByRole('button', { name: `More actions for ${name}` }).click();
      await row.getByRole('button', { name: 'Activity' }).click();
      const activity = page.getByRole('dialog', { name: `Activity of ${name}` });
      const events = activity.getByRole('listitem');
      await expect(activity).toContainText('Newest first.');
      if (extra) {
        await expect(events).toHaveCount(50);
        await expectNoIssues(page, `the activity dialog, ${device}`);
        await activity.getByRole('button', { name: 'Load more' }).click();
        await expect(events).toHaveCount(52); // made, its token, 49 links, renewed
        await expect(activity.getByRole('button', { name: 'Load more' })).toBeHidden();
      } else {
        await expect(events).toHaveCount(4);
        await expectNoIssues(page, `the activity dialog, ${device}`);
      }
      await expect(events.filter({ hasText: `Created link ${code}` })).toContainText('On behalf of');
      await expect(events.filter({ hasText: 'Renewed its token' })).toContainText('By ');
      await expect(events.filter({ hasText: 'Created its token' })).toHaveCount(1);
      await expect(events.last()).toContainText('Created the service account');
      await activity.getByRole('button', { name: 'Close' }).last().click();
      await expect(activity).toBeHidden();

      await removeEarlier(ownerApi);
    });

    test('“How to connect one” opens the manual’s page for owners', async ({ page }) => {
      await page.goto('/dashboard/organization/');
      await page.getByRole('main').getByRole('link', { name: 'How to connect one' }).click();
      await expect(page).toHaveURL('/manual/connect-a-service/');
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Connect another service');
      await expectNoIssues(page, `the manual's service accounts page, ${device}`);
    });

    test.describe('as a member', () => {
      test.use({ storageState: MEMBER_STATE });

      test('the section isn’t there', async ({ page }) => {
        await page.goto('/dashboard/organization/');
        const panel = page.getByRole('main');
        await expect(panel.getByRole('heading', { name: 'Members' })).toBeVisible();
        await expect(panel.getByRole('heading', { name: 'Service accounts' })).toBeHidden();
      });
    });
  });
}
