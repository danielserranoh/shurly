// Phase 6.1 — every end-to-end test runs under these rules, and fails on breaking any, whatever it asserts:
// - a Content-Security-Policy or Trusted Types violation (the built pages enforce both);
// - an uncaught error in a page;
// - a 5xx from the API;
// - a request to a host other than this machine (fonts, analytics, anything): it's blocked, and reported.
// harness.spec.ts breaks each once, with `enforceRules` off, to show they're caught.

import { readFile } from 'node:fs/promises';

import { test as base, expect, type APIRequest, type APIRequestContext } from '@playwright/test';

import { TOKEN_KEY } from '../src/utils/auth';
import { API_URL, MEMBER_STATE, OWNER_STATE, WEB_URL } from './env';

interface Violation {
  directive: string;
  blocked: string;
  sample: string;
  source: string;
  line: number;
}

declare global {
  interface Window {
    __e2eViolation?: (violation: Violation) => void;
  }
}

interface StorageState {
  origins: Array<{ origin: string; localStorage: Array<{ name: string; value: string }> }>;
}

const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]']);

/** The API as whoever a setup project saved the session of. */
async function apiAs(request: APIRequest, statePath: string): Promise<APIRequestContext> {
  const state = JSON.parse(await readFile(statePath, 'utf8')) as StorageState;
  const token = state.origins.find((o) => o.origin === WEB_URL)?.localStorage.find((item) => item.name === TOKEN_KEY)?.value;
  if (!token) throw new Error(`No session in ${statePath}: the setup project saves it`);
  return request.newContext({ baseURL: API_URL, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
}
const isLocal = (url: URL) => !/^(https?|wss?):$/.test(url.protocol) || LOCAL_HOSTS.has(url.hostname);

export const test = base.extend<{ enforceRules: boolean; broken: string[]; ownerApi: APIRequestContext; memberApi: APIRequestContext }>({
  /** Fail the test on a broken rule: off only in harness.spec.ts, which reads `broken` instead. */
  enforceRules: [true, { option: true }],
  /** The rules broken so far, one line each. */
  broken: [
    async ({ context, enforceRules }, use) => {
      const broken: string[] = [];
      await context.route(
        (url) => !isLocal(url),
        async (route) => {
          broken.push(`a request to another host: ${route.request().method()} ${route.request().url()}`);
          await route.abort('blockedbyclient');
        },
      );
      await context.exposeFunction('__e2eViolation', (v: Violation) => {
        broken.push(`a ${v.directive} violation: ${v.blocked || 'inline'}${v.sample ? ` (${v.sample})` : ''} at ${v.source}:${v.line}`);
      });
      await context.addInitScript(() => {
        window.addEventListener('securitypolicyviolation', (e) =>
          window.__e2eViolation?.({ directive: e.effectiveDirective, blocked: e.blockedURI, sample: e.sample, source: e.sourceFile, line: e.lineNumber }),
        );
      });
      context.on('weberror', (error) => broken.push(`an uncaught error: ${error.error().message}`));
      context.on('response', (response) => {
        if (response.url().startsWith(API_URL) && response.status() >= 500) {
          broken.push(`the API's ${response.status()}: ${response.request().method()} ${response.url()}`);
        }
      });
      await use(broken);
      if (enforceRules) expect(broken, 'the pages broke a rule of the harness (e2e/fixtures.ts)').toEqual([]);
    },
    { auto: true },
  ],
  /** The API as the owner, with auth.setup.ts's session: for what a spec needs made, not what it tests. */
  ownerApi: async ({ playwright }, use) => {
    const api = await apiAs(playwright.request, OWNER_STATE);
    await use(api);
    await api.dispose();
  },
  /** The same as the member, with member.setup.ts's session: what's theirs, made as they would. */
  memberApi: async ({ playwright }, use) => {
    const api = await apiAs(playwright.request, MEMBER_STATE);
    await use(api);
    await api.dispose();
  },
});

export { expect };
