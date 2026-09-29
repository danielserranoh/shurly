// The API's dates (src/utils/format.ts): UTC with `Z` since the MCP fix, local with an offset in the 3.16/3.17
// analytics, and naive UTC before. parseDate reads each as the same moment, and adds `Z` only when there's no zone.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { formatDate, parseDate, toLocalInput } from '../src/utils/format.ts';

const MOMENT = Date.UTC(2026, 8, 29, 22, 4, 42, 82);

describe('parseDate', () => {
  test('UTC with Z, as the API writes it', () => {
    assert.equal(parseDate('2026-09-29T22:04:42.082199Z').getTime(), MOMENT);
  });

  test('naive, as the API wrote it before: taken as UTC', () => {
    assert.equal(parseDate('2026-09-29T22:04:42.082199').getTime(), MOMENT);
  });

  test("a local time with its zone's offset: the same moment, never a second Z", () => {
    assert.equal(parseDate('2026-09-30T03:34:42.082+05:30').getTime(), MOMENT);
    assert.equal(parseDate('2026-09-29T22:04:42.082+00:00').getTime(), MOMENT);
  });

  test('a date alone, and nothing', () => {
    assert.equal(parseDate('2026-09-29').getTime(), Date.UTC(2026, 8, 29));
    assert.equal(parseDate(null), null);
    assert.equal(parseDate(''), null);
    assert.equal(parseDate('not a date'), null);
  });
});

describe('formatDate', () => {
  test('"Sep 29, 2026" from either form', () => {
    // Midday UTC: the same calendar day in every zone a test machine could be in.
    assert.equal(formatDate('2026-09-29T12:00:00.5Z'), 'Sep 29, 2026');
    assert.equal(formatDate('2026-09-29T12:00:00.5'), 'Sep 29, 2026');
  });
});

describe('toLocalInput', () => {
  test('the same value for the datetime-local input with Z or without', () => {
    assert.equal(toLocalInput('2026-09-29T22:04:42Z'), toLocalInput('2026-09-29T22:04:42'));
  });
});
