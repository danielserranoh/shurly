// "Today" on the analytics charts is today in the zone the API counted the days in.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { todayIn } from '../src/utils/days.ts';

const NOW = new Date('2026-10-26T10:00:00Z');

test('today where the days were counted', () => {
  assert.equal(todayIn('Etc/UTC', NOW), '2026-10-26');
  assert.equal(todayIn('Europe/Madrid', NOW), '2026-10-26');
  assert.equal(todayIn('Pacific/Kiritimati', NOW), '2026-10-27'); // +14:00
  assert.equal(todayIn('Pacific/Pago_Pago', NOW), '2026-10-25'); // −11:00
});

test("UTC's when the zone is missing or unknown", () => {
  assert.equal(todayIn(undefined, NOW), '2026-10-26');
  assert.equal(todayIn(null, new Date('2026-10-26T23:30:00Z')), '2026-10-26');
  assert.equal(todayIn('Mars/Olympus_Mons', NOW), '2026-10-26');
});
