// Phase 6.1 — the app's own config, built into dist-e2e/ for the end-to-end tests, so a run never replaces dist/.
// PUBLIC_API_URL (set by playwright.config.ts) points the pages, and the CSP's connect-src, at the test API.
import config from '../astro.config.mjs';

export default { ...config, outDir: './dist-e2e' };
