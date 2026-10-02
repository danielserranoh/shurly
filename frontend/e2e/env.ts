// Phase 6.1 — where an end-to-end run serves the pages and the API. tests/e2e/app.py reads the same variables.

import { fileURLToPath } from 'node:url';

export const API_URL = process.env.E2E_API_URL ?? 'http://127.0.0.1:18000';
export const WEB_URL = process.env.E2E_WEB_URL ?? 'http://127.0.0.1:14321';

/** Who the fake Google signs in: the organization's first account, so its owner. */
export const OWNER = 'e2e.owner@griddo.io';
/** The owner's session, saved by auth.setup.ts for the specs to start from. */
export const OWNER_STATE = fileURLToPath(new URL('./.auth/owner.json', import.meta.url));

/** Who it signs in when the browser carries this cookie, `member`: a second account, which joins as a member. As
 * tests/e2e/identities.py has them. */
export const IDENTITY_COOKIE = 'e2e_as';
export const MEMBER = 'e2e.member@griddo.io';
/** The member's session, saved by member.setup.ts: `test.use({ storageState: MEMBER_STATE })` to be them. */
export const MEMBER_STATE = fileURLToPath(new URL('./.auth/member.json', import.meta.url));

/** What a person's browser says it is, for the visits the specs make without a page. */
export const BROWSER_UA =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';
