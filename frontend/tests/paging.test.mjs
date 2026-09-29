// Phase 6.3 — a list's `?page=`, as a page the API takes (src/utils/paging.ts): the rows it skips stay
// within the API's bound, or it's page 1. And the pager under the links' and the campaigns' lists.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';

import { MAX_SKIP, pageFromQuery, renderPager, showing } from '../src/utils/paging.ts';

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

describe('showing', () => {
  test('the rows on this page, out of all of them', () => {
    assert.equal(showing(1, 20, 21, 20), 'Showing 1–20 of 21');
    assert.equal(showing(2, 20, 21, 1), 'Showing 21–21 of 21');
    assert.equal(showing(3, 20, 1234, 20), 'Showing 41–60 of 1,234');
  });
});

describe('renderPager', () => {
  /** The pager's parts, as components/ui/Pager.astro has them. */
  const pager = () => {
    const parts = { '[data-range]': { textContent: '' }, '[data-prev]': { disabled: false }, '[data-next]': { disabled: false } };
    return { hidden: true, parts, querySelector: (selector) => parts[selector] };
  };

  test('hidden while the list fits one page', () => {
    for (const total of [0, 1, 20]) {
      const nav = pager();
      renderPager(nav, 1, 20, total, total);
      assert.equal(nav.hidden, true, `${total} rows`);
    }
  });

  test('from the second page on: Previous on the first page is off, Next on the last', () => {
    const first = pager();
    renderPager(first, 1, 20, 21, 20);
    assert.deepEqual(
      [first.hidden, first.parts['[data-range]'].textContent, first.parts['[data-prev]'].disabled, first.parts['[data-next]'].disabled],
      [false, 'Showing 1–20 of 21', true, false],
    );

    const last = pager();
    renderPager(last, 2, 20, 21, 1);
    assert.deepEqual(
      [last.hidden, last.parts['[data-range]'].textContent, last.parts['[data-prev]'].disabled, last.parts['[data-next]'].disabled],
      [false, 'Showing 21–21 of 21', false, true],
    );
  });
});
