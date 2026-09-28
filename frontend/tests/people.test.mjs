// People in Settings → Organization go by their name, and by their email without one.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { accountLine, hasName, personName } from '../src/utils/people.ts';

const email = 'ana@griddo.io';

test('the full name, or the one given', () => {
  assert.equal(personName({ email, first_name: 'Ana', last_name: 'García' }), 'Ana García');
  assert.equal(personName({ email, first_name: 'Ana', last_name: null }), 'Ana');
  assert.equal(personName({ email, first_name: null, last_name: 'García' }), 'García');
  assert.equal(personName({ email, first_name: '  Ana ', last_name: ' ' }), 'Ana');
});

test('the email without a name, or from an API older than the profile', () => {
  assert.equal(personName({ email, first_name: null, last_name: null }), email);
  assert.equal(personName({ email, first_name: '  ', last_name: '' }), email);
  assert.equal(personName({ email }), email);
  assert.equal(hasName({ email }), false);
});

test('a dialog says which account a name means', () => {
  assert.equal(accountLine({ email, first_name: 'Ana' }), 'Their account is ana@griddo.io. ');
  assert.equal(accountLine({ email }), '');
});
