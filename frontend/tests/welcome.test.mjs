// The dashboard's welcome card (src/utils/welcome.ts): an account in its first 14 days sees it, until it's
// dismissed. Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { shouldWelcome, WELCOME_DAYS, welcomeDismissedKey } from '../src/utils/welcome.ts';

const now = Date.parse('2026-09-29T12:00:00Z');
const daysAgo = (days) => new Date(now - days * 86_400_000).toISOString();

describe('shouldWelcome', () => {
  test('a new account sees it', () => {
    assert.equal(shouldWelcome(daysAgo(0), false, now), true);
  });

  test('through its first 14 days, and not after', () => {
    assert.equal(WELCOME_DAYS, 14);
    assert.equal(shouldWelcome(daysAgo(13.9), false, now), true);
    assert.equal(shouldWelcome(daysAgo(14), false, now), false);
    assert.equal(shouldWelcome(daysAgo(400), false, now), false);
  });

  test('not once dismissed', () => {
    assert.equal(shouldWelcome(daysAgo(1), true, now), false);
  });

  test('a date a little ahead of this clock is still new', () => {
    assert.equal(shouldWelcome(new Date(now + 60_000).toISOString(), false, now), true);
  });

  test('not without a date it can read', () => {
    for (const createdAt of [null, undefined, '', 'yesterday']) {
      assert.equal(shouldWelcome(createdAt, false, now), false, String(createdAt));
    }
  });
});

test('the dismissal is kept per account, so someone else on this browser is still welcomed', () => {
  assert.notEqual(welcomeDismissedKey('a1'), welcomeDismissedKey('b2'));
  assert.match(welcomeDismissedKey('a1'), /^shurly_/);
});
