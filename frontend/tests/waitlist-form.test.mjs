// Phase 9.1 — the waitlist's form (src/utils/waitlist-form.ts): what it checks before sending, and what it sends.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { COMPANY_SIZES, LIMITS, waitlistBody, waitlistErrors } from '../src/utils/waitlist-form.ts';

const filled = (overrides = {}) => ({
  email: 'ada@example.com',
  name: 'Ada',
  kind: 'individual',
  company: '',
  company_size: '',
  role: '',
  use_case: '',
  source: '',
  consent: true,
  website: '',
  ...overrides,
});

describe('waitlistErrors', () => {
  test('a filled-in form has none', () => {
    assert.deepEqual(waitlistErrors(filled()), {});
  });

  test('email, name, kind and consent are required', () => {
    const errors = waitlistErrors(filled({ email: ' ', name: '', kind: '', consent: false }));
    assert.deepEqual(Object.keys(errors).sort(), ['consent', 'email', 'kind', 'name']);
    assert.equal(errors.email, 'Enter your email.');
  });

  test('an email has to look like one', () => {
    assert.equal(waitlistErrors(filled({ email: 'ada@' })).email, 'That doesn’t look like an email address.');
  });

  test('a company needs its name, an individual doesn’t', () => {
    assert.equal(waitlistErrors(filled({ kind: 'company' })).company, 'Enter the company’s name.');
    assert.deepEqual(waitlistErrors(filled({ kind: 'company', company: 'Acme' })), {});
  });

  test('every text keeps to its column', () => {
    const errors = waitlistErrors(filled({ name: 'n'.repeat(LIMITS.name + 1), use_case: 'u'.repeat(LIMITS.use_case + 1) }));
    assert.equal(errors.name, 'Keep it under 200 characters.');
    assert.equal(errors.use_case, 'Keep it under 1,000 characters.');
  });
});

describe('waitlistBody', () => {
  test('trims, and empty answers are null', () => {
    assert.deepEqual(waitlistBody(filled({ email: ' ada@example.com ', name: ' Ada ', role: '  ' })), {
      email: 'ada@example.com',
      name: 'Ada',
      kind: 'individual',
      company: null,
      company_size: null,
      role: null,
      use_case: null,
      source: null,
      consent: true,
      website: null,
    });
  });

  test('an individual sends no company, even one typed before switching', () => {
    const body = waitlistBody(filled({ company: 'Acme', company_size: '1-10' }));
    assert.equal(body.company, null);
    assert.equal(body.company_size, null);
  });

  test('a company sends its name and size', () => {
    const body = waitlistBody(filled({ kind: 'company', company: ' Acme ', company_size: '51-200' }));
    assert.deepEqual([body.kind, body.company, body.company_size], ['company', 'Acme', '51-200']);
  });

  test('the honeypot goes as it is, for the API to drop', () => {
    assert.equal(waitlistBody(filled({ website: 'spam' })).website, 'spam');
  });
});

test('the sizes are the API’s', () => {
  assert.deepEqual(
    COMPANY_SIZES.map((size) => size.value),
    ['1-10', '11-50', '51-200', '201-1000', '1000+'],
  );
});
