// Phase 3.14.5 — what a member sees, before the dogfood's members arrive (5.6.1). The organization's links and
// campaigns are everyone's to see, but only their creator, an admin or an owner changes them: for a member the owner's
// are locked, saying why, and a click sends nothing, while their own they change. Bulk tagging skips what isn't theirs
// and says so. The members card has no role menus for them, and the welcome greets them. axe on each page, on a
// desktop and on a phone (390 px).

import AxeBuilder from '@axe-core/playwright';
import { devices, type APIRequestContext, type Locator, type Page } from '@playwright/test';

import { MEMBER, MEMBER_STATE, OWNER } from './env';
import { expect, test } from './fixtures';

test.use({ storageState: MEMBER_STATE });

/** Who may change a link or campaign, in the API's words (server/utils/access.py). A locked control's click says
 * the API's 403 instead of acting, and its tooltip the same, shorter (src/utils/viewer.ts). */
const WHO = 'Only its creator, or an admin or owner,';
const LOCKED_LINK = `${WHO} can change this link.`;
const LOCKED_CAMPAIGN = `${WHO} can change this campaign.`;
const LOCK_TIP = `${WHO} can change it`;
/** A locked control is aria-disabled, which Playwright won't click, but a person can: their click is what says why.
 * Forced, so first a hover, which waits for it to hold still (a menu that's opening still moves). */
async function clickLocked(control: Locator) {
  await control.hover();
  await control.click({ force: true });
}

/** Every impact but minor, as a11y.spec.ts. */
const IMPACTS = ['moderate', 'serious', 'critical'];

async function expectNoIssues(page: Page, name: string) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const found = violations
    .filter((v) => IMPACTS.includes(v.impact ?? ''))
    .flatMap((v) => v.nodes.map((node) => ({ rule: v.id, impact: v.impact, target: node.target.join(' '), summary: node.failureSummary ?? v.help })));
  expect(found, `axe on ${name}: ${IMPACTS.join(', ')} issues`).toEqual([]);
}

/** What the page asks the API to change: anything but a read. */
function watchChanges(page: Page): string[] {
  const changes: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      changes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });
  return changes;
}

interface Link {
  id: string;
  short_code: string;
}

/** A link of the owner's and one of the member's, both the organization's. */
async function twoLinks(ownerApi: APIRequestContext, memberApi: APIRequestContext) {
  const stamp = Date.now();
  const make = async (api: APIRequestContext, whose: string) => {
    const made = await api.post('/api/v1/urls', { data: { url: `https://example.com/e2e-member/${stamp}/${whose}`, title: `E2E ${whose} ${stamp}` } });
    expect(made.status()).toBe(201);
    return (await made.json()) as Link;
  };
  return { stamp, owners: await make(ownerApi, 'owner'), mine: await make(memberApi, 'member') };
}

async function ownersCampaign(ownerApi: APIRequestContext) {
  const name = `E2E owner's campaign ${Date.now()}`;
  const made = await ownerApi.post('/api/v1/campaigns', { data: { name, original_url: 'https://example.com/e2e-member', csv_data: 'firstName\nAna' } });
  expect(made.ok()).toBe(true);
  return { name, id: ((await made.json()) as { id: string }).id };
}

test("the owner's link is locked for them, saying why, and a click sends nothing; their own isn't", async ({ page, ownerApi, memberApi }) => {
  const { owners, mine } = await twoLinks(ownerApi, memberApi);
  const changes = watchChanges(page);

  await page.goto('/dashboard/');
  const theirs = page.locator(`[data-link="${owners.id}"]`);
  const own = page.locator(`[data-link="${mine.id}"]`);
  await expect(theirs).toContainText('Created by');
  await expect(theirs).not.toContainText('Created by you');
  await expect(own).toContainText('Created by you');

  await theirs.getByRole('button', { name: /^More actions for/ }).click();
  for (const action of ['edit', 'delete']) {
    await expect(theirs.locator(`[data-action="${action}"]`)).toHaveAttribute('aria-disabled', 'true');
    await expect(theirs.locator(`[data-action="${action}"]`)).toHaveAttribute('title', LOCK_TIP);
  }
  await clickLocked(theirs.locator('[data-action="delete"]'));
  await expect(page.getByText(LOCKED_LINK)).toBeVisible();
  await expect(page.getByRole('dialog')).toBeHidden(); // no "Delete this link?" to answer
  await expect(theirs).toBeVisible();

  await own.getByRole('button', { name: /^More actions for/ }).click();
  for (const action of ['edit', 'delete']) await expect(own.locator(`[data-action="${action}"]`)).not.toHaveAttribute('aria-disabled', 'true');
  expect(changes).toEqual([]);
});

test("on the owner's link page every change is locked; on their own, they edit and save", async ({ page, ownerApi, memberApi }) => {
  const { stamp, owners, mine } = await twoLinks(ownerApi, memberApi);
  const changes = watchChanges(page);

  await page.goto(`/dashboard/link/?code=${owners.short_code}`);
  const edit = page.locator('[data-edit]');
  await expect(edit).toHaveAttribute('aria-disabled', 'true');
  await expect(edit).toHaveAttribute('data-tooltip', LOCK_TIP);
  await expect(page.locator('[data-add-rule]')).toHaveAttribute('aria-disabled', 'true');
  await clickLocked(edit);
  await expect(page.getByText(LOCKED_LINK).first()).toBeVisible();
  await expect(page.locator('#edit-link')).toBeHidden();
  await page.getByRole('button', { name: 'More actions' }).click();
  await expect(page.locator('#link-menu [data-delete]')).toHaveAttribute('aria-disabled', 'true');
  await clickLocked(page.locator('#link-menu [data-delete]'));
  await expect(page.getByRole('dialog')).toBeHidden();
  expect(changes).toEqual([]);

  await page.goto(`/dashboard/link/?code=${mine.short_code}`);
  await expect(page.locator('[data-edit]')).not.toHaveAttribute('aria-disabled', 'true');
  await page.locator('[data-edit]').click();
  await page.locator('#edit-link').getByLabel('Title', { exact: true }).fill(`E2E renamed by its member ${stamp}`);
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('Changes saved')).toBeVisible();
  await expect(page.locator('[data-title]')).toHaveText(`E2E renamed by its member ${stamp}`);
});

test("tagging both in bulk tags their own, skips the owner's, and says why", async ({ page, ownerApi, memberApi }) => {
  const { owners, mine } = await twoLinks(ownerApi, memberApi);

  await page.goto('/dashboard/');
  for (const link of [owners, mine]) {
    const card = page.locator(`[data-link="${link.id}"]`);
    await card.hover();
    await card.locator(`[data-select="${link.id}"]`).check();
  }
  await page.locator('[data-bulk-tag]').click();
  const dialog = page.locator('#bulk-tag');
  await dialog.getByRole('combobox').fill('email');
  await dialog.getByRole('combobox').press('Enter');
  await dialog.getByRole('button', { name: 'Add tags' }).click();
  await expect(page.getByText('Tags added to 1 link')).toBeVisible();
  await expect(page.getByText('1 link skipped: only its creator, or an admin or owner, can change a link.')).toBeVisible();

  const tagsOf = async (link: Link) => {
    const read = await ownerApi.get(`/api/v1/urls/${link.short_code}`);
    return ((await read.json()) as { tags: Array<{ name: string }> }).tags.map((t) => t.name);
  };
  expect(await tagsOf(mine)).toContain('email');
  expect(await tagsOf(owners)).not.toContain('email');
});

test("the owner's campaign is locked for them, on its page and in the list", async ({ page, ownerApi }) => {
  const { name, id } = await ownersCampaign(ownerApi);
  const changes = watchChanges(page);

  await page.goto(`/dashboard/campaign/?id=${id}`);
  await page.getByRole('button', { name: 'More actions' }).click();
  const remove = page.locator('#campaign-menu [data-delete]');
  await expect(remove).toHaveAttribute('aria-disabled', 'true');
  await clickLocked(remove);
  await expect(page.getByText(LOCKED_CAMPAIGN)).toBeVisible();
  await expect(page.getByRole('dialog')).toBeHidden();

  await page.goto('/dashboard/campaigns/');
  const row = page.locator(`[data-campaign="${id}"]`);
  await row.getByRole('button', { name: `More actions for ${name}` }).click();
  await expect(row.locator('[data-action="delete"]')).toHaveAttribute('aria-disabled', 'true');
  await expect(row.locator('[data-action="delete"]')).toHaveAttribute('title', LOCK_TIP);
  expect(changes).toEqual([]);
});

test('the members card has no role menus for them, and the welcome greets them', async ({ page }) => {
  await page.goto('/dashboard/settings/#organization');
  const panel = page.getByRole('tabpanel', { name: 'Organization' });
  const members = panel.locator('[data-members]');
  await expect(members).toContainText(MEMBER);
  await expect(members).toContainText(OWNER);
  await expect(panel.locator('[data-org-summary]')).toContainText('You’re a member.');
  await expect(panel.locator('[data-member-menu]')).toHaveCount(0);
  await expect(panel.locator('[data-removed-section]')).toBeHidden();

  // They signed up minutes ago: the welcome, saying links they make are the team's.
  await page.goto('/dashboard/');
  const welcome = page.getByRole('region', { name: 'Welcome to Shurly. Here’s where to start.' });
  await expect(welcome).toBeVisible();
  await expect(welcome.locator('[data-welcome-sharing]')).toContainText('Links you make belong to');
});

const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
const DEVICES = [
  { device: 'desktop', options: {} },
  { device: 'phone', options: { ...pixel, viewport: { width: 390, height: 844 } } },
];

for (const { device, options } of DEVICES) {
  test.describe(`axe, as a member, on a ${device}`, () => {
    test.use(options);

    test('the pages a member uses, with the owner’s things locked', async ({ page, ownerApi, memberApi }) => {
      const { owners } = await twoLinks(ownerApi, memberApi);
      const { id } = await ownersCampaign(ownerApi);

      await page.goto('/dashboard/');
      await expect(page.locator(`[data-link="${owners.id}"]`)).toBeVisible();
      await expectNoIssues(page, 'links, as a member');

      await page.goto(`/dashboard/link/?code=${owners.short_code}`);
      await expect(page.locator('[data-edit]')).toHaveAttribute('aria-disabled', 'true');
      await expectNoIssues(page, "the owner's link, as a member");

      await page.goto(`/dashboard/campaign/?id=${id}`);
      await expect(page.locator('#campaign-menu [data-delete]')).toHaveAttribute('aria-disabled', 'true');
      await expectNoIssues(page, "the owner's campaign, as a member");

      await page.goto('/dashboard/campaigns/');
      await expect(page.locator(`[data-campaign="${id}"]`)).toBeVisible();
      await expectNoIssues(page, 'campaigns, as a member');

      await page.goto('/dashboard/settings/#organization');
      await expect(page.getByRole('tabpanel', { name: 'Organization' }).locator('[data-members]')).toContainText(MEMBER);
      await expectNoIssues(page, 'settings, organization, as a member');
    });
  });
}
