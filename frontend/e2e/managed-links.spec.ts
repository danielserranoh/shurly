// Phase 10.3 — links managed by their service account (_board/plan_managed-links-propuestas.md). A service, with its
// token, makes two links for the member (X-Shurly-On-Behalf-Of), and then:
// - the member, the person they're for, finds them only in the service's tab, not under Links; on the link's page the
//   destination is masked, there's no Edit or Delete, only "Edit tags", which saves a tag; the API refuses their
//   DELETE with 403 `managed_link_protected`, and their search doesn't match the hidden destination;
// - an admin sees it masked too, and can't delete it;
// - the owner sees the whole destination, and deletes one with "Delete anyway…": a short reason is refused on its
//   field, a good one deletes it and lands on the service's tab; the account's Activity shows the override, by the
//   owner, with the reason;
// - the service's own token still changes the other one's expiry and deletes it;
// - axe finds no moderate, serious or critical issue on the managed link's page and in the override dialog.
// Serial: each step starts from the one before. The service accounts it makes, and their links, go at the start and
// the end, and the member is a member again.

import AxeBuilder from '@axe-core/playwright';
import type { APIRequestContext, Page } from '@playwright/test';

import { API_URL, MEMBER, MEMBER_STATE } from './env';
import { expect, test } from './fixtures';
import { pick } from './helpers';

test.describe.configure({ mode: 'serial' });

const IMPACTS = ['moderate', 'serious', 'critical'];

async function expectNoIssues(page: Page, name: string) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const found = violations
    .filter((v) => IMPACTS.includes(v.impact ?? ''))
    .flatMap((v) => v.nodes.map((node) => ({ rule: v.id, impact: v.impact, target: node.target.join(' '), summary: node.failureSummary ?? v.help })));
  expect(found, `axe on ${name}: ${IMPACTS.join(', ')} issues`).toEqual([]);
}

const PREFIX = 'Managed E2E';
const NAME = `${PREFIX} Propuestas`;
/** What the destination hides: a credential, as Propuestas' access token. */
const SECRET = 'e2e-access-token-7f3a';
const REASON = 'The recipient asked us to delete their data';

interface Account {
  id: string;
  display_name: string;
}
interface Link {
  id: string;
  short_code: string;
  domain: string;
  original_url: string;
  managed_by: Account | null;
}
interface Member {
  user_id: string;
  email: string;
  role: string;
}

/** What one step leaves the next. */
const made: { account?: Account; token?: string; deleted?: Link; kept?: Link } = {};
const linkPage = (link: Link) => `/dashboard/link/?code=${link.short_code}&domain=${link.domain}`;

async function setMemberRole(ownerApi: APIRequestContext, role: 'member' | 'admin') {
  const members = (await (await ownerApi.get('/api/v1/organization/members')).json()) as Member[];
  const member = members.find((m) => m.email === MEMBER);
  expect(member, `${MEMBER} is in the organization`).toBeTruthy();
  if (member!.role === role) return;
  const changed = await ownerApi.patch(`/api/v1/organization/members/${member!.user_id}`, { data: { role } });
  expect(changed.status(), `${MEMBER} made ${role}`).toBe(200);
}

/** Whatever a run left: the member a member again, this spec's managed links deleted (by the owner's override, the
 * only way past their service account), and its service accounts removed. */
async function cleanUp(ownerApi: APIRequestContext) {
  await setMemberRole(ownerApi, 'member');
  const managers = (await (await ownerApi.get('/api/v1/urls/managers')).json()) as Account[];
  for (const manager of managers.filter((m) => m.display_name?.startsWith(PREFIX))) {
    const { urls } = (await (await ownerApi.get(`/api/v1/urls?managed_by=${manager.id}&limit=100`)).json()) as { urls: Link[] };
    for (const link of urls) {
      const gone = await ownerApi.post(`/api/v1/urls/${link.short_code}/override-delete?domain=${encodeURIComponent(link.domain)}`, {
        data: { reason: 'Clean-up after an end-to-end run' },
      });
      expect(gone.status()).toBe(204);
    }
  }
  const accounts = (await (await ownerApi.get('/api/v1/service-accounts')).json()) as Account[];
  for (const account of accounts.filter((a) => a.display_name.startsWith(PREFIX))) {
    await ownerApi.delete(`/api/v1/service-accounts/${account.id}`);
  }
}

test('a service makes two links for the member: managed by it', async ({ ownerApi, playwright }) => {
  await cleanUp(ownerApi);
  const me = (await (await ownerApi.get('/api/v1/auth/me')).json()) as { id: string };
  const created = await ownerApi.post('/api/v1/service-accounts', { data: { display_name: NAME, responsible_user_id: me.id, role: 'member' } });
  expect(created.status()).toBe(201);
  made.account = (await created.json()) as Account;
  const issued = await ownerApi.post(`/api/v1/service-accounts/${made.account.id}/token`, { data: {} });
  expect(issued.status()).toBe(201);
  made.token = ((await issued.json()) as { token: string }).token;

  const service = await playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: { Authorization: `Bearer ${made.token}`, 'X-Shurly-On-Behalf-Of': MEMBER },
  });
  const make = async (title: string, path: string) => {
    const res = await service.post('/api/v1/urls', { data: { url: `https://example.com/p/${path}?t=${SECRET}`, title } });
    expect(res.status()).toBe(201);
    const link = (await res.json()) as Link;
    // The service reads its own links whole.
    expect(link.original_url).toContain(SECRET);
    expect(link.managed_by?.id).toBe(made.account!.id);
    return link;
  };
  made.deleted = await make('Managed E2E proposal for Ana', 'ana');
  made.kept = await make('Managed E2E proposal for Luis', 'luis');
  await service.dispose();
});

test.describe('as the member it was made for', () => {
  test.use({ storageState: MEMBER_STATE });

  test('it’s only in the service’s tab, masked, and only its tags change', async ({ page, memberApi }) => {
    const link = made.deleted!;
    // Not under Links, even searched for by its title.
    await page.goto(`/dashboard/?q=${encodeURIComponent('Managed E2E proposal')}`);
    await expect(page.getByRole('radio', { name: 'Links', exact: true })).toBeChecked();
    await expect(page.locator('#empty-filtered')).toBeVisible();
    await expect(page.locator(`[data-link="${link.id}"]`)).toHaveCount(0);

    // In the service's tab, masked.
    await page.goto('/dashboard/');
    await pick(page.getByRole('radio', { name: NAME, exact: true }));
    await expect(page).toHaveURL(new RegExp(`/dashboard/\\?managed_by=${made.account!.id}$`));
    const card = page.locator(`[data-link="${link.id}"]`);
    await expect(card).toContainText(`Managed by ${NAME}`);
    await expect(card).toContainText('example.com/…');
    expect(await page.content()).not.toContain(SECRET);

    // Its search doesn't match what it can't read.
    const searched = (await (await memberApi.get(`/api/v1/urls?q=${SECRET}`)).json()) as { total: number };
    expect(searched.total).toBe(0);

    // Its page: masked, a plain text, saying who sees it whole.
    await page.goto(linkPage(link));
    await expect(page.locator('[data-managed]')).toContainText(`Managed by ${NAME}. Change or delete it from there; its tags can be changed here.`);
    const destination = page.locator('[data-destination]');
    await expect(destination).toHaveText('example.com/…');
    expect(await destination.evaluate((el) => el.tagName)).toBe('SPAN');
    await expect(destination).toHaveAttribute('title', `Only ${NAME} and the organization’s owners see the full destination`);
    expect(await page.content()).not.toContain(SECRET);

    // No Edit and no Delete: Edit tags, and "Delete via" locked.
    const edit = page.locator('[data-edit]');
    await expect(edit).toHaveText('Edit tags');
    await expect(page.locator('[data-add-rule]')).toBeHidden();
    await page.getByRole('button', { name: 'More actions' }).click();
    await expect(page.locator('[data-delete]')).toBeHidden();
    await expect(page.locator('[data-override-delete]')).toBeHidden();
    const deleteVia = page.locator('[data-delete-via]');
    await expect(deleteVia).toHaveText(`Delete via ${NAME}`);
    await expect(deleteVia).toHaveAttribute('aria-disabled', 'true');
    await page.keyboard.press('Escape');
    await expectNoIssues(page, 'a managed link’s page, for the member');

    // Its tags: saved.
    await edit.click();
    const dialog = page.getByRole('dialog', { name: 'Edit tags' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel('Destination', { exact: true })).toBeHidden();
    // The predefined "email" tag, once the picker has the tags (before, it only offers to create one).
    const tags = dialog.getByRole('combobox');
    await expect(async () => {
      await tags.fill('');
      await tags.fill('email');
      await expect(dialog.getByRole('option').filter({ hasNotText: 'Create' }).first()).toBeVisible({ timeout: 500 });
    }).toPass();
    await tags.press('Enter');
    await dialog.getByRole('button', { name: 'Save tags' }).click();
    await expect(page.getByText('Tags saved')).toBeVisible();
    await expect(dialog).toBeHidden();
    await expect(page.locator('[data-tags]')).toContainText('email');

    // The API refuses their delete.
    const refused = await memberApi.delete(`/api/v1/urls/${link.short_code}?domain=${encodeURIComponent(link.domain)}`);
    expect(refused.status()).toBe(403);
    const body = (await refused.json()) as { code: string; detail: string };
    expect(body.code).toBe('managed_link_protected');
    expect(body.detail).toBe(`This link is managed by ${NAME}. Change or delete it from there.`);
  });
});

test.describe('as an admin', () => {
  test.use({ storageState: MEMBER_STATE });

  test('it’s masked, and there’s no delete', async ({ page, ownerApi, memberApi }) => {
    await setMemberRole(ownerApi, 'admin');
    try {
      const link = made.deleted!;
      await page.goto(linkPage(link));
      await expect(page.locator('[data-destination]')).toHaveText('example.com/…');
      expect(await page.content()).not.toContain(SECRET);
      await page.getByRole('button', { name: 'More actions' }).click();
      await expect(page.locator('[data-delete]')).toBeHidden();
      await expect(page.locator('[data-override-delete]')).toBeHidden();
      await expect(page.locator('[data-delete-via]')).toHaveAttribute('aria-disabled', 'true');
      await page.keyboard.press('Escape');

      const refused = await memberApi.delete(`/api/v1/urls/${link.short_code}?domain=${encodeURIComponent(link.domain)}`);
      expect(refused.status()).toBe(403);
      expect(((await refused.json()) as { code: string }).code).toBe('managed_link_protected');
    } finally {
      await setMemberRole(ownerApi, 'member');
    }
  });
});

test('the owner sees it whole, deletes it anyway with a reason, and Activity says so', async ({ page }) => {
  const link = made.deleted!;
  await page.goto(linkPage(link));
  const destination = page.locator('[data-destination]');
  await expect(destination).toContainText(`example.com/p/ana?t=${SECRET}`);
  expect(await destination.evaluate((el) => el.tagName)).toBe('A');
  await expect(page.locator('[data-edit]')).toHaveText('Edit tags');

  await page.getByRole('button', { name: 'More actions' }).click();
  await expect(page.locator('[data-delete]')).toBeHidden();
  await expect(page.locator('[data-delete-via]')).toBeHidden();
  await page.getByRole('button', { name: 'Delete anyway…' }).click();
  const dialog = page.getByRole('dialog', { name: `Delete a link ${NAME} manages?` });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(`${NAME} will keep showing it as active, and whoever has it will reach a dead link.`);
  const reason = dialog.getByLabel('Reason');
  await expect(reason).toBeFocused();
  await expectNoIssues(page, 'the override dialog');

  // Too short: refused on its field, and nothing sent.
  await reason.fill('Too short');
  await expect(dialog.locator('[data-reason-count]')).toHaveText('9 / 500');
  await dialog.getByRole('button', { name: 'Delete it' }).click();
  await expect(dialog.locator('[data-error-for="reason"]')).toHaveText('Say a little more: at least 10 characters.');
  await expect(reason).toHaveAttribute('aria-invalid', 'true');
  await expectNoIssues(page, 'the override dialog with an error');

  // A reason: deleted, and back on the service's tab, where the other link still is.
  await reason.fill(REASON);
  await expect(dialog.locator('[data-error-for="reason"]')).toBeHidden();
  await dialog.getByRole('button', { name: 'Delete it' }).click();
  await expect(page).toHaveURL(new RegExp(`/dashboard/\\?managed_by=${made.account!.id}$`));
  await expect(page.getByText('Link deleted')).toBeVisible();
  await expect(page.getByRole('radio', { name: NAME, exact: true })).toBeChecked();
  await expect(page.locator(`[data-link="${made.kept!.id}"]`)).toBeVisible();
  await expect(page.locator(`[data-link="${link.id}"]`)).toHaveCount(0);

  // The account's Activity: the override, by the owner, with the reason.
  await page.goto('/dashboard/organization/');
  const row = page.getByRole('main').getByRole('region', { name: /Service accounts/ }).getByRole('listitem').filter({ hasText: NAME });
  await row.getByRole('button', { name: `More actions for ${NAME}` }).click();
  await row.getByRole('button', { name: 'Activity' }).click();
  const activity = page.getByRole('dialog', { name: `Activity of ${NAME}` });
  const override = activity.getByRole('listitem').filter({ hasText: 'Deleted a link anyway (owner override)' });
  await expect(override).toHaveCount(1);
  await expect(override.locator('[data-audit-reason]')).toHaveText(`“${REASON}”`);
  await expect(override).toContainText('By ');
  await expectNoIssues(page, 'the activity, with an override');
});

test('the service’s token still changes its link’s expiry and deletes it', async ({ ownerApi, playwright }) => {
  const link = made.kept!;
  const service = await playwright.request.newContext({ baseURL: API_URL, extraHTTPHeaders: { Authorization: `Bearer ${made.token}` } });
  const at = `?domain=${encodeURIComponent(link.domain)}`;
  const until = new Date(Date.now() + 30 * 86_400_000).toISOString();
  const changed = await service.patch(`/api/v1/urls/${link.short_code}${at}`, { data: { valid_until: until } });
  expect(changed.status()).toBe(200);
  const body = (await changed.json()) as Link & { valid_until: string };
  expect(Date.parse(body.valid_until)).toBe(Date.parse(until));
  expect(body.original_url).toContain(SECRET);
  expect((await service.delete(`/api/v1/urls/${link.short_code}${at}`)).status()).toBe(204);
  expect((await service.get(`/api/v1/urls/${link.short_code}${at}`)).status()).toBe(404);
  await service.dispose();

  await cleanUp(ownerApi);
});
