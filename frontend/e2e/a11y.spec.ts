// Phase 6.1 — accessibility: axe on the pages people use most, once their content is in: moderate, serious and
// critical issues, on a desktop and on a phone (390 px, where the menu is a dialog). What it finds gets fixed, or
// allowed below with a reason and the issue that will fix it: never a rule turned off.

import AxeBuilder from '@axe-core/playwright';
import { devices, type APIRequestContext, type Page } from '@playwright/test';

import { expect, test } from './fixtures';
import { clickLink, openEmail } from './helpers';

interface Allowed {
  page: string;
  rule: string;
  /** The element, as axe names it. */
  target: string;
  reason: string;
  issue: string;
}

/** Known issues, each until its issue is fixed. */
const ALLOWED: Allowed[] = [];

/** Every impact but minor: moderate takes in landmarks, headings' order and the like. */
const IMPACTS = ['moderate', 'serious', 'critical'];

async function expectNoIssues(page: Page, name: string) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const found = violations
    .filter((v) => IMPACTS.includes(v.impact ?? ''))
    .flatMap((v) => v.nodes.map((node) => ({ rule: v.id, impact: v.impact, target: node.target.join(' '), summary: node.failureSummary ?? v.help })))
    .filter((f) => !ALLOWED.some((a) => a.page === name && a.rule === f.rule && a.target === f.target));
  expect(found, `axe on ${name}: ${IMPACTS.join(', ')} issues`).toEqual([]);
}

// A phone's context (touch, mobile viewport), as phone.spec.ts has it, minus the browser choice: the project's is Chromium.
const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
const DEVICES = [
  { device: 'desktop', options: {} },
  { device: 'phone', options: { ...pixel, viewport: { width: 390, height: 844 } } },
];

for (const { device, options } of DEVICES) {
  test.describe(`on a ${device}`, () => {
    test.use(options);

    test.describe('signed out', () => {
      test.use({ storageState: { cookies: [], origins: [] } });

      test('the landing page', async ({ page }) => {
        await page.goto('/');
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
        await expectNoIssues(page, 'landing');
      });

      test('the login page', async ({ page }) => {
        await page.goto('/login/');
        await expect(page.getByRole('button', { name: 'Sign in with Google' })).toBeVisible();
        await expectNoIssues(page, 'login');
      });

      test('the manual', async ({ page }) => {
        await page.goto('/manual/');
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('User manual');
        await expectNoIssues(page, 'manual');
        await page.goto('/manual/read-your-analytics/');
        await expect(page.getByRole('heading', { level: 1 })).toHaveText('Read your analytics');
        await expectNoIssues(page, 'manual page');
      });
    });

    test.describe('signed in', () => {
      // What each page shows is made first, through the API: numbers, charts and rows, not empty states.
      async function aLinkWithVisits(ownerApi: APIRequestContext, request: APIRequestContext) {
        const made = await ownerApi.post('/api/v1/urls', { data: { url: `https://example.com/e2e-a11y/${Date.now()}` } });
        const { short_code: code } = (await made.json()) as { short_code: string };
        await clickLink(request, code);
        await openEmail(request, code);
        return code;
      }

      test('the dashboard', async ({ page, ownerApi, request }) => {
        await aLinkWithVisits(ownerApi, request);
        await page.goto('/dashboard/');
        await expect(page.locator('li[data-link]').first()).toBeVisible();
        await expectNoIssues(page, 'dashboard');
      });

      test("a link's page", async ({ page, ownerApi, request }) => {
        const code = await aLinkWithVisits(ownerApi, request);
        await page.goto(`/dashboard/link/?code=${code}`);
        await expect(page.locator('[data-range]')).toContainText('1 click');
        await expectNoIssues(page, 'link');
      });

      test("a campaign's page", async ({ page, ownerApi, request }) => {
        const made = await ownerApi.post('/api/v1/campaigns', {
          data: { name: `E2E a11y ${Date.now()}`, original_url: 'https://example.com/e2e-a11y', csv_data: 'firstName,company\nAna,Acme\nBen,Bolt' },
        });
        const { id } = (await made.json()) as { id: string };
        const listed = await ownerApi.get(`/api/v1/analytics/campaigns/${id}/recipients`);
        const { recipients } = (await listed.json()) as { recipients: Array<{ short_code: string }> };
        await clickLink(request, recipients[0].short_code);

        await page.goto(`/dashboard/campaign/?id=${id}`);
        await expect(page.locator('[data-recipients] tbody tr')).toHaveCount(2);
        await expect(page.locator('[data-stat="clicks"]')).toHaveText('1');
        await expectNoIssues(page, 'campaign');
      });

      test('Settings', async ({ page }) => {
        await page.goto('/dashboard/settings/');
        await expect(page.getByRole('button', { name: 'Save profile' })).toBeEnabled();
        await expectNoIssues(page, 'settings');
      });

      if (device === 'phone') {
        test('the menu', async ({ page }) => {
          await page.goto('/dashboard/');
          await page.getByRole('button', { name: 'Open menu' }).click();
          await expect(page.getByRole('dialog', { name: 'Menu' })).toBeVisible();
          await expectNoIssues(page, 'menu');
        });
      }
    });
  });
}
