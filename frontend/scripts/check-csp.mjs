// Phase 6.3 — after `astro build`, check every page against the rules in csp-rules.mjs: one
// CSP <meta>, first in line, covering every inline script; and that one built script defines
// the Trusted Types policy. `npm run build` runs it, so CI, the deploy and local builds all do.

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { checkPage, checkPolicyChunks } from './csp-rules.mjs';

const dist = new URL('../dist/', import.meta.url).pathname;
const files = readdirSync(dist, { recursive: true });
const pages = files.filter((file) => file.endsWith('.html'));

const problems = [];
let checked = 0;
let inlineScripts = 0;
for (const page of pages) {
  const result = checkPage(readFileSync(join(dist, page), 'utf8'));
  if (result.skipped) continue;
  checked++;
  inlineScripts += result.inlineScripts;
  problems.push(...result.problems.map((problem) => `${page}: ${problem}`));
}

if (!checked) problems.push('no pages to check: run it after `astro build`');
const scripts = files.filter((file) => file.endsWith('.js')).map((file) => ({ name: file, source: readFileSync(join(dist, file), 'utf8') }));
problems.push(...checkPolicyChunks(scripts));
if (problems.length) {
  console.error(`CSP check failed:\n${problems.join('\n')}`);
  process.exit(1);
}
console.log(`CSP check: ${checked} pages, ${inlineScripts} inline scripts, all covered by the policy; one chunk defines the Trusted Types policy.`);
