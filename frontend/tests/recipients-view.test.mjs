// Phase 3.17 — the campaign's recipients table: its sorting (headers and the phone's "Sort by"), the query it
// sends (the API filters, searches, sorts and pages), and how a recipient reads (src/utils/recipients-view.ts).
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  DEFAULT_SORT,
  EMPTY_MESSAGE,
  SORT_CHOICES,
  activityLine,
  ariaSort,
  nextSort,
  pageRange,
  personLabel,
  recipientsExportQuery,
  recipientsQuery,
  secondaryLabel,
  sortChoice,
} from '../src/utils/recipients-view.ts';

describe('sorting', () => {
  test('starts with the most clicks', () => {
    assert.deepEqual(DEFAULT_SORT, { sort: 'clicks', order: 'desc' });
  });

  test('a header sorts from the most, then flips; another header starts over', () => {
    let state = DEFAULT_SORT;
    state = nextSort(state, 'clicks');
    assert.deepEqual(state, { sort: 'clicks', order: 'asc' });
    state = nextSort(state, 'clicks');
    assert.deepEqual(state, { sort: 'clicks', order: 'desc' });
    state = nextSort(state, 'last_click');
    assert.deepEqual(state, { sort: 'last_click', order: 'desc' });
    state = nextSort(state, 'opens');
    assert.deepEqual(state, { sort: 'opens', order: 'desc' });
  });

  test('the link sorts A to Z first', () => {
    assert.deepEqual(nextSort(DEFAULT_SORT, 'code'), { sort: 'code', order: 'asc' });
    assert.deepEqual(nextSort({ sort: 'code', order: 'asc' }, 'code'), { sort: 'code', order: 'desc' });
  });

  test('headers say how they sort, for screen readers', () => {
    assert.equal(ariaSort('clicks', { sort: 'clicks', order: 'desc' }), 'descending');
    assert.equal(ariaSort('clicks', { sort: 'clicks', order: 'asc' }), 'ascending');
    assert.equal(ariaSort('opens', { sort: 'clicks', order: 'desc' }), 'none');
  });

  test('the phone offers the same sorts by name, and finds the current one', () => {
    assert.deepEqual(
      SORT_CHOICES.map((c) => c.label),
      ['Most clicks', 'Most opens', 'Latest click', 'Link, A to Z'],
    );
    assert.equal(sortChoice({ sort: 'opens', order: 'desc' }).label, 'Most opens');
    assert.equal(sortChoice({ sort: 'opens', order: 'asc' }), undefined); // only a header gives fewest first
  });
});

describe('the query', () => {
  test('sends the filter, the sort and the page, and the search only when there is one', () => {
    assert.equal(recipientsQuery({ filter: 'all', q: '', sort: 'clicks', order: 'desc', page: 1 }), 'filter=all&sort=clicks&order=desc&page=1&page_size=50');
    assert.equal(recipientsQuery({ filter: 'opened', q: ' Ana & Co ', sort: 'last_click', order: 'asc', page: 3 }), 'filter=opened&q=Ana+%26+Co&sort=last_click&order=asc&page=3&page_size=50');
  });

  test('the CSV takes the same filter, search and sort, and every page', () => {
    assert.equal(recipientsExportQuery({ filter: 'clicked', q: 'acme', sort: 'opens', order: 'desc', page: 4 }), 'filter=clicked&q=acme&sort=opens&order=desc');
  });
});

describe('a recipient', () => {
  const columns = ['firstName', 'company', 'region', 'email'];

  test('is named by the first filled column, in the CSV\'s order', () => {
    assert.equal(personLabel({ firstName: 'Ana', company: 'Acme' }, columns), 'Ana');
    assert.equal(personLabel({ firstName: '', company: 'Acme' }, columns), 'Acme');
    assert.equal(personLabel({}, columns), 'Recipient');
  });

  test('then by the next two filled columns', () => {
    assert.equal(secondaryLabel({ firstName: 'Ana', company: 'Acme', region: '', email: 'ana@acme.test' }, columns), 'Acme · ana@acme.test');
    assert.equal(secondaryLabel({ firstName: 'Ana' }, columns), '');
  });

  test("says how much they've done", () => {
    assert.equal(activityLine({ clicks: 12, opens: 3 }), '12 clicks · 3 opens');
    assert.equal(activityLine({ clicks: 1, opens: 1 }), '1 click · 1 open');
    assert.equal(activityLine({ clicks: 0, opens: 0 }), 'No clicks or opens yet');
    assert.equal(activityLine({ clicks: 1200, opens: 0 }), '1,200 clicks · 0 opens');
  });
});

describe('the list', () => {
  test('counts the rows shown out of those that match', () => {
    assert.equal(pageRange(1, 50, 312, 50), '1–50 of 312');
    assert.equal(pageRange(7, 50, 312, 12), '301–312 of 312');
    assert.equal(pageRange(1, 50, 0, 0), '');
  });

  test('says why it is empty, a search first', () => {
    assert.equal(EMPTY_MESSAGE('clicked', ''), 'Nobody has clicked their link yet.');
    assert.equal(EMPTY_MESSAGE('opened', ''), 'Nobody has opened the email yet.');
    assert.equal(EMPTY_MESSAGE('none', ''), 'Everyone has clicked or opened. Nice.');
    assert.equal(EMPTY_MESSAGE('all', ''), 'This campaign has no recipients.');
    assert.equal(EMPTY_MESSAGE('clicked', 'ana'), 'No recipients match your search.');
  });
});
