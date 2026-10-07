// 3.10.8 — the line under "Typos & broken links" (src/utils/orphans.ts): how many hits from scanners and bots the
// list leaves out, and the button that shows them, or hides them again.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { hiddenHitsNote } from '../src/utils/orphans.ts';

describe('hiddenHitsNote', () => {
  test('nothing hidden, nothing said', () => {
    assert.equal(hiddenHitsNote(0, false), null);
  });

  test('how many hits are left out, and a button to show them', () => {
    assert.deepEqual(hiddenHitsNote(42, false), { text: '42 hits from scanners and bots aren’t shown.', action: 'Show them' });
    assert.deepEqual(hiddenHitsNote(1, false), { text: '1 hit from scanners and bots isn’t shown.', action: 'Show them' });
    assert.equal(hiddenHitsNote(12345, false)?.text, '12,345 hits from scanners and bots aren’t shown.');
  });

  test('once shown, it says so, and hides them again', () => {
    // The API hides nothing then, so the count is 0: the line stays, for the way back.
    assert.deepEqual(hiddenHitsNote(0, true), { text: 'Hits from scanners and bots are shown too.', action: 'Hide them' });
  });
});
