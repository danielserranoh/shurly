// Phase 3.16 — after `astro build`, fail if a built script carries development-only code
// (dev-only-rules.mjs). `npm run build` runs it, so CI, the deploy and local builds all do.

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { checkDevOnly } from './dev-only-rules.mjs';

const dist = new URL('../dist/', import.meta.url).pathname;
const scripts = readdirSync(dist, { recursive: true })
  .filter((file) => file.endsWith('.js'))
  .map((file) => ({ name: file, source: readFileSync(join(dist, file), 'utf8') }));

const problems = scripts.length ? checkDevOnly(scripts) : ['no scripts to check: run it after `astro build`'];
if (problems.length) {
  console.error(`Dev-only check failed:\n${problems.join('\n')}`);
  process.exit(1);
}
console.log(`Dev-only check: ${scripts.length} scripts, none with development-only code.`);
