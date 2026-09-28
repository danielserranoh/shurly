// Visits store a country as its ISO 3166-1 alpha-2 code (Phase 8.4): the page shows its name.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { countryName } from '../src/utils/country.ts';

test('a code becomes its English name', () => {
  assert.equal(countryName('ES'), 'Spain');
  assert.equal(countryName('US'), 'United States');
  assert.equal(countryName('es'), 'Spain');
});

test('anything else is shown as it is', () => {
  assert.equal(countryName('Spain'), 'Spain');
  assert.equal(countryName('Unknown'), 'Unknown');
  assert.equal(countryName(''), 'Unknown');
  assert.equal(countryName(null), 'Unknown');
});
