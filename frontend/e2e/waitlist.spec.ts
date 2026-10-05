// Phase 9.1 — the waitlist. Someone outside Griddo finds it from the landing's and the login page's buttons, signs up
// as an individual or for a company, and sees that it worked on the same page. The organization's owners see who signed
// up, how many of each and the companies by size, export them and remove one; a member sees neither the page nor its
// link. axe on each page, on a desktop and on a phone (390 px).

import AxeBuilder from '@axe-core/playwright';
import { devices, type APIRequestContext, type Page } from '@playwright/test';

import { API_URL, MEMBER_STATE } from './env';
import { expect, test } from './fixtures';
import { csvLines } from './helpers';

/** Every impact but minor, as a11y.spec.ts. */
const IMPACTS = ['moderate', 'serious', 'critical'];

async function expectNoIssues(page: Page, name: string) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const found = violations
    .filter((v) => IMPACTS.includes(v.impact ?? ''))
    .flatMap((v) => v.nodes.map((node) => ({ rule: v.id, impact: v.impact, target: node.target.join(' '), summary: node.failureSummary ?? v.help })));
  expect(found, `axe on ${name}: ${IMPACTS.join(', ')} issues`).toEqual([]);
}

/** Someone signs up through the API, without a page: what the owner's specs need on the list. */
async function signUp(request: APIRequestContext, data: Record<string, unknown>) {
  const response = await request.post(`${API_URL}/api/v1/waitlist`, { data: { consent: true, ...data } });
  expect(response.status()).toBe(201);
}

const stamp = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;

// A phone's context (touch, mobile viewport), as a11y.spec.ts has it.
const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
const DEVICES = [
  { device: 'desktop', options: {} },
  { device: 'phone', options: { ...pixel, viewport: { width: 390, height: 844 } } },
];

test.describe('signed out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("the landing's and the login page's buttons lead to the waitlist, and Log in stays the login", async ({ page }) => {
    await page.goto('/');
    const header = page.locator('#site-header');
    await expect(header.getByRole('link', { name: 'Get started' })).toHaveAttribute('href', '/waitlist/');
    await expect(page.getByRole('link', { name: 'Join the waitlist' })).toHaveCount(5); // the hero, both plans, the last call, the footer
    for (const link of await page.getByRole('link', { name: 'Join the waitlist' }).all()) await expect(link).toHaveAttribute('href', '/waitlist/');
    await expect(page.locator('body')).not.toContainText('it’s free');
    await expect(page.getByRole('link', { name: 'I already have an account' })).toHaveAttribute('href', '/login/');

    await page.goto('/login/');
    await page.getByRole('link', { name: 'Join the waitlist' }).click();
    await expect(page).toHaveURL('/waitlist/');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Shurly is invite-only, for now.');
  });

  test('an empty form says what each field needs, and focuses the first', async ({ page }) => {
    await page.goto('/waitlist/');
    await page.getByRole('button', { name: 'Join the waitlist' }).click();

    await expect(page.getByLabel('Name', { exact: true })).toBeFocused();
    await expect(page.getByLabel('Name', { exact: true })).toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('[data-error-for="name"]')).toHaveText('Enter your name.');
    await expect(page.locator('[data-error-for="email"]')).toHaveText('Enter your email.');
    await expect(page.locator('[data-error-for="kind"]')).toHaveText('Choose whether you’re signing up for yourself or for a company.');
    await expect(page.locator('[data-error-for="consent"]')).toHaveText('Agree to be contacted about Shurly to join the waitlist.');

    // Typing in a field takes its error away.
    await page.getByLabel('Name', { exact: true }).fill('Ada');
    await expect(page.locator('[data-error-for="name"]')).toBeHidden();
  });

  test('a company signs up, and the page says so', async ({ page }) => {
    const email = `grace.${stamp()}@example.com`;
    await page.goto('/waitlist/');
    await expect(page.getByLabel('Company name')).toBeHidden();

    await page.getByLabel('Name', { exact: true }).fill('Grace Hopper');
    await page.getByLabel('Email', { exact: true }).fill(email);
    await page.getByLabel('For a company').check();
    await expect(page.getByLabel('Company name')).toBeVisible();
    // A company needs its name: the API's rule too.
    await page.getByLabel('I agree to be contacted about Shurly.').check();
    await page.getByRole('button', { name: 'Join the waitlist' }).click();
    await expect(page.locator('[data-error-for="company"]')).toHaveText('Enter the company’s name.');
    await expect(page.getByLabel('Company name')).toBeFocused();

    await page.getByLabel('Company name').fill('Northwind');
    await page.getByLabel('Company size (optional)').selectOption('51-200');
    await page.getByLabel('Your role (optional)').fill('Head of marketing');
    await page.getByLabel('How did you find us? (optional)').selectOption('LinkedIn');
    await page.getByLabel('What would you use Shurly for? (optional)').fill('Proposals to universities.');
    const sent = page.waitForRequest((r) => r.url().endsWith('/api/v1/waitlist') && r.method() === 'POST');
    await page.getByRole('button', { name: 'Join the waitlist' }).click();

    expect((await sent).headers().authorization).toBeUndefined(); // no account needed
    await expect(page.getByRole('heading', { name: 'You’re on the list' })).toBeFocused();
    await expect(page.locator('#waitlist-done')).toContainText(email);
    await expect(page.locator('#waitlist-form')).toBeHidden();
    await expect(page).toHaveURL('/waitlist/');
  });

  for (const { device, options } of DEVICES) {
    test.describe(`on a ${device}`, () => {
      test.use(options);

      test('axe: the form, its errors and its success', async ({ page }) => {
        await page.goto('/waitlist/');
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
        await expectNoIssues(page, 'waitlist');

        await page.getByLabel('For a company').check();
        await page.getByRole('button', { name: 'Join the waitlist' }).click();
        await expect(page.locator('[data-error-for="email"]')).toBeVisible();
        await expectNoIssues(page, 'waitlist, with errors');

        await page.getByLabel('Name', { exact: true }).fill('Ada Lovelace');
        await page.getByLabel('Email', { exact: true }).fill(`ada.${stamp()}@example.com`);
        await page.getByLabel('An individual').check();
        await page.getByLabel('I agree to be contacted about Shurly.').check();
        await page.getByRole('button', { name: 'Join the waitlist' }).click();
        await expect(page.getByRole('heading', { name: 'You’re on the list' })).toBeVisible();
        await expectNoIssues(page, 'waitlist, joined');
      });
    });
  }
});

test.describe('the owner', () => {
  test('sees who signed up, the counts, exports them and removes one', async ({ page, request, ownerApi }) => {
    const id = stamp();
    await signUp(request, { email: `ind.${id}@example.com`, name: `Ind ${id}`, kind: 'individual', source: 'Search engine' });
    await signUp(request, { email: `co.${id}@example.com`, name: `Co ${id}`, kind: 'company', company: `Bolt ${id}`, company_size: '1000+', role: 'CMO' });

    await page.goto('/dashboard/');
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Waitlist' }).click();
    await expect(page).toHaveURL('/dashboard/waitlist/');

    const company = page.locator('tr', { hasText: `Co ${id}` });
    await expect(company).toContainText(`co.${id}@example.com`);
    await expect(company).toContainText(`Bolt ${id}`);
    await expect(company).toContainText('More than 1,000');
    await expect(page.locator('tr', { hasText: `Ind ${id}` })).toContainText('Individual');
    // The counts are the API's.
    const { counts } = (await (await ownerApi.get('/api/v1/waitlist?limit=1')).json()) as { counts: { total: number; company: number } };
    await expect(page.locator('[data-stat="total"]')).toHaveText(String(counts.total));
    await expect(page.locator('[data-stat="company"]')).toHaveText(String(counts.company));
    await expect(page.getByRole('region', { name: 'Companies by size' })).toContainText('More than 1,000');

    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export CSV' }).click();
    const lines = await csvLines(await downloading);
    expect(lines[0]).toBe('created_at,email,name,kind,company,company_size,role,use_case,source,consent_at');
    expect(lines.some((line) => line.includes(`co.${id}@example.com`))).toBe(true);

    await company.getByRole('button', { name: `Remove Co ${id} from the waitlist` }).click();
    const dialog = page.getByRole('dialog', { name: `Remove Co ${id} from the waitlist?` });
    await dialog.getByRole('button', { name: 'Remove from waitlist' }).click();
    await expect(page.getByText('Removed from the waitlist')).toBeVisible();
    await expect(company).toHaveCount(0);
  });

  for (const { device, options } of DEVICES) {
    test.describe(`on a ${device}`, () => {
      test.use(options);

      test('axe: the waitlist', async ({ page, request }) => {
        const id = stamp();
        await signUp(request, { email: `axe.${id}@example.com`, name: `Axe ${id}`, kind: 'company', company: 'Axe Co', use_case: 'A long answer. '.repeat(20) });
        await page.goto('/dashboard/waitlist/');
        await expect(page.locator('tr', { hasText: `Axe ${id}` })).toBeVisible();
        await expectNoIssues(page, 'dashboard waitlist');
        if (device === 'phone') {
          await page.getByRole('button', { name: 'Open menu' }).click();
          await expect(page.getByRole('dialog', { name: 'Menu' }).getByRole('link', { name: 'Waitlist' })).toBeVisible();
        }
      });
    });
  }
});

test.describe('a member', () => {
  test.use({ storageState: MEMBER_STATE });

  test('has no link to the waitlist, and its page says who sees it', async ({ page, memberApi }) => {
    await page.goto('/dashboard/');
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Links' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Waitlist' })).toHaveCount(0);

    await page.goto('/dashboard/waitlist/');
    await expect(page.getByRole('heading', { name: 'Only owners and admins see the waitlist' })).toBeVisible();
    await expect(page.locator('#content')).toBeHidden();
    await expect(page.getByRole('button', { name: 'Export CSV' })).toBeDisabled();
    await expectNoIssues(page, 'dashboard waitlist, a member');

    expect((await memberApi.get('/api/v1/waitlist')).status()).toBe(403);
    expect((await memberApi.get('/api/v1/waitlist/export')).status()).toBe(403);
  });
});
