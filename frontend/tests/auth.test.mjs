// Where the login page sends someone after signing in (`?next=`, or the path kept in
// sessionStorage across the Google round trip). Both reach `location.replace`, so both
// must stay on this site. Checked with Node's WHATWG URL parser, the one browsers implement.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { beforeEach, describe, test } from 'node:test';

import { rememberNext, safeNext, takeNext } from '../src/utils/auth.ts';

const ORIGIN = 'https://s.griddo.io';
const FALLBACK = '/dashboard/';

const staysHere = (path) => path.startsWith('/') && !path.startsWith('//') && new URL(path, ORIGIN).origin === ORIGIN;

describe('safeNext', () => {
  const offsite = {
    'protocol-relative': '//evil.com',
    backslash: '/\\evil.com',
    'tab, dropped by browsers': '/\t/evil.com',
    'line feed': '/\n/evil.com',
    'carriage return': '/\r/evil.com',
    'another control character': '/\u0000/evil.com',
    'absolute URL': 'https://evil.com',
    'javascript: URL': 'javascript:alert(1)',
    'leading space': ' /x',
    'dot segment before //': '/.//evil.com',
    'double-dot segment before //': '/..//evil.com',
    'encoded dot segment before //': '/%2e//evil.com',
    'encoded double dot before //': '/%2E%2E//evil.com',
    'dot segment before a backslash': '/./\\evil.com',
  };
  for (const [name, next] of Object.entries(offsite)) {
    test(`refuses ${name}`, () => {
      assert.equal(safeNext(next, FALLBACK, ORIGIN), FALLBACK);
    });
  }

  test('an encoded slash stays a path on this site', () => {
    assert.ok(staysHere(safeNext('/%2F%2Fevil.com', FALLBACK, ORIGIN)));
  });

  test('keeps a path, its query and its fragment intact', () => {
    assert.equal(safeNext('/dashboard/settings/#account', FALLBACK, ORIGIN), '/dashboard/settings/#account');
    assert.equal(safeNext('/dashboard/link/?code=abc', FALLBACK, ORIGIN), '/dashboard/link/?code=abc');
  });

  test('nothing, or an empty string, gets the fallback', () => {
    for (const next of [null, undefined, '']) assert.equal(safeNext(next, FALLBACK, ORIGIN), FALLBACK);
    assert.equal(safeNext(null, '/dashboard/campaigns/', ORIGIN), '/dashboard/campaigns/');
  });

  test('whatever comes in, what comes out stays on this site', () => {
    const inputs = [...Object.values(offsite), '/%2F%2Fevil.com', '/a/../b', '/?next=//evil.com', '/#//evil.com', '/　/x', '/／evil.com'];
    for (const next of inputs) assert.ok(staysHere(safeNext(next, FALLBACK, ORIGIN)), JSON.stringify(next));
  });
});

describe('rememberNext and takeNext (sessionStorage)', () => {
  let store;
  beforeEach(() => {
    store = new Map();
    globalThis.window = { location: { origin: ORIGIN } };
    globalThis.sessionStorage = {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key),
    };
  });

  test('a kept path comes back once', () => {
    rememberNext('/dashboard/settings/#account');
    assert.equal(takeNext(), '/dashboard/settings/#account');
    assert.equal(takeNext(), FALLBACK);
  });

  test('an offsite path is never kept', () => {
    rememberNext('/\t/evil.com');
    assert.equal(takeNext(), FALLBACK);
  });

  test('a value planted in sessionStorage is checked again on the way out', () => {
    store.set('shurly_next', '/.//evil.com');
    assert.equal(takeNext('/dashboard/links/'), '/dashboard/links/');
    assert.equal(store.has('shurly_next'), false);
  });
});
