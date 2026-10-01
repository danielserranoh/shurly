// A custom back-half, as the API takes one (server/utils/url.py): 3 to 64 letters, numbers,
// hyphens or underscores. 64 since Phase 8.4: Shlink's imported codes run to 44 characters.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isValidCustomCode, MAX_CODE_LENGTH } from '../src/utils/short-code.ts';

test('up to 64 characters, as the API takes', () => {
  assert.equal(MAX_CODE_LENGTH, 64);
  assert.ok(isValidCustomCode('jane-doe-acme-corp-2026-q4-outreach-followup')); // 44
  assert.ok(isValidCustomCode('a'.repeat(64)));
  assert.ok(!isValidCustomCode('a'.repeat(65)));
});

test('at least 3, of letters, numbers, hyphens and underscores', () => {
  assert.ok(isValidCustomCode('abc'));
  assert.ok(isValidCustomCode('Q4_promo-2'));
  for (const code of ['', 'ab', 'my code', 'promo!', 'a/b', 'café']) {
    assert.ok(!isValidCustomCode(code), code);
  }
});
