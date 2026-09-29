// Development-only code never reaches a production build: the link analytics' mock (`&mock`, Phase 3.16)
// carries a marker, and `npm run build` fails if any built script does (scripts/check-dev-only.mjs).

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import { DEV_ONLY_MARKER, checkDevOnly } from '../scripts/dev-only-rules.mjs';

const chunk = (name, source) => ({ name, source });

describe('checkDevOnly', () => {
  test('passes a build without development-only code', () => {
    assert.deepEqual(checkDevOnly([chunk('_astro/link.a1.js', 'getTotals(link)'), chunk('_astro/ui.b2.js', 'setHTML(el,x)')]), []);
  });

  test('fails on a script that carries the marker, whatever its name', () => {
    assert.deepEqual(checkDevOnly([chunk('_astro/index.c3.js', `ua:"Mozilla/5.0 (${DEV_ONLY_MARKER})"`)]), [
      `_astro/index.c3.js: development-only code (${DEV_ONLY_MARKER}) in a production build`,
    ]);
  });

  test('fails on a chunk named after the mock, even minified to nothing recognisable', () => {
    assert.deepEqual(checkDevOnly([chunk('_astro/link-analytics-mock.Zi_UD9uu.js', 'export{a as b}')]), [
      '_astro/link-analytics-mock.Zi_UD9uu.js: development-only code (link-analytics-mock) in a production build',
    ]);
  });
});

test('the mocks carry the marker, so the check can find them', () => {
  for (const mock of ['link-analytics-mock.ts', 'campaign-analytics-mock.ts']) {
    const source = readFileSync(new URL(`../src/utils/${mock}`, import.meta.url), 'utf8');
    assert.ok(source.includes(DEV_ONLY_MARKER), mock);
  }
});

test("a campaign mock's chunk fails the build too", () => {
  assert.equal(checkDevOnly([chunk('_astro/campaign-analytics-mock.x1.js', 'export{a as b}')]).length, 1);
});
