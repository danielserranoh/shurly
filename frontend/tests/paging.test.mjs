// Phase 6.3 — the links page's `?page=`, as a page the API takes (src/utils/paging.ts): the rows it
// skips stay within the API's bound, or it's page 1.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import { MAX_SKIP, pageFromQuery } from '../src/utils/paging.ts';

describe('pageFromQuery', () => {
  test('a page number is that page', () => {
    assert.equal(pageFromQuery('1', 20), 1);
    assert.equal(pageFromQuery('3', 20), 3);
  });

  test('anything but a whole number from 1 is page 1', () => {
    for (const value of [null, '', 'next', '0', '-2', '2.5', 'NaN', 'Infinity']) {
      assert.equal(pageFromQuery(value, 20), 1, `?page=${value}`);
    }
  });

  test('a page past what the API skips is page 1', () => {
    const last = MAX_SKIP / 20 + 1; // skips exactly MAX_SKIP rows

    assert.equal(pageFromQuery(String(last), 20), last);
    assert.equal(pageFromQuery(String(last + 1), 20), 1);
    assert.equal(pageFromQuery('1e20', 20), 1);
  });

  test("MAX_SKIP is the API's", () => {
    const bounds = readFileSync(new URL('../../server/utils/bounds.py', import.meta.url), 'utf8');
    const api = bounds.match(/^MAX_SKIP = ([\d_]+)/m);

    assert.ok(api, 'server/utils/bounds.py names MAX_SKIP');
    assert.equal(Number(api[1].replaceAll('_', '')), MAX_SKIP);
  });
});
