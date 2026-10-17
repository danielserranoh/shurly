// People on the Organization page go by their name, and by their email without one.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { accountLine, createdBy, hasName, isServiceEmail, personName, serviceName } from '../src/utils/people.ts';

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

// Phase 10.1 — a link a service account made: "Ana García via Propuestas Griddo", or the
// service's own name when it acted for nobody (its email is a placeholder, never shown).
const via = { id: 'svc-1', display_name: 'Propuestas Griddo' };

test('a link made for someone names them, then the service', () => {
  assert.equal(createdBy('Ana García', 'ana@griddo.io', via), 'Ana García via Propuestas Griddo');
  assert.equal(createdBy('you', 'ana@griddo.io', via), 'you via Propuestas Griddo');
  assert.equal(createdBy('Ana García', 'ana@griddo.io', null), 'Ana García');
  assert.equal(createdBy('Ana García', 'ana@griddo.io', undefined), 'Ana García');
});

test('a link the service made for nobody is the service’s', () => {
  assert.equal(createdBy('propuestas-1a2b3c4d@service.invalid', 'propuestas-1a2b3c4d@service.invalid', via), 'Propuestas Griddo');
  assert.equal(isServiceEmail('propuestas-1a2b3c4d@service.invalid'), true);
  assert.equal(isServiceEmail('ana@griddo.io'), false);
  assert.equal(isServiceEmail(null), false);
});

test('a service without a name still reads', () => {
  assert.equal(serviceName({ id: 'x', display_name: null }), 'a service account');
  assert.equal(serviceName({ id: 'x', display_name: '  ' }), 'a service account');
  assert.equal(serviceName(via), 'Propuestas Griddo');
});
