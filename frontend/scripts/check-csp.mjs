// Phase 6.3 — after `astro build`, check every page against the rules in csp-rules.mjs: one
// CSP <meta>, first in line, covering every inline script. `npm run build` runs it, so CI,
// the deploy and local builds all do.

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { checkPage } from './csp-rules.mjs';

const dist = new URL('../dist/', import.meta.url).pathname;
const pages = readdirSync(dist, { recursive: true }).filter((file) => file.endsWith('.html'));

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
if (problems.length) {
  console.error(`CSP check failed:\n${problems.join('\n')}`);
  process.exit(1);
}
console.log(`CSP check: ${checked} pages, ${inlineScripts} inline scripts, all covered by the policy.`);
