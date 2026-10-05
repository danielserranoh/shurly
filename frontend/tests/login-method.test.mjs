// The login page's password block (src/utils/login-method.ts): closed unless the address asks for it, or the
// password was chosen earlier this session. Run: `npm test` (node --test; Node 22.18+ runs the TypeScript as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { asksForPassword, PASSWORD_CHOSEN_KEY, passwordChosen, rememberPasswordChoice } from '../src/utils/login-method.ts';

/** A sessionStorage stand-in. */
function memory() {
  const items = new Map();
  return {
    getItem: (key) => (items.has(key) ? items.get(key) : null),
    setItem: (key, value) => void items.set(key, String(value)),
    removeItem: (key) => void items.delete(key),
    items,
  };
}

/** A browser whose storage is off (a private window, blocked site data): reading it throws. */
const blocked = () => {
  throw new DOMException('The operation is insecure.', 'SecurityError');
};

describe('asksForPassword', () => {
  test('?method=password asks for it', () => {
    assert.equal(asksForPassword('?method=password', ''), true);
    assert.equal(asksForPassword('?next=%2Fdashboard%2F&method=password', ''), true);
  });

  test('so does #password', () => {
    assert.equal(asksForPassword('', '#password'), true);
  });

  test('an email to fill in does too: the field it fills is in the block', () => {
    assert.equal(asksForPassword('?email=ana%40griddo.io', ''), true);
  });

  test('nothing else does', () => {
    for (const [search, hash] of [
      ['', ''],
      ['?next=%2Fdashboard%2F', ''],
      ['?reason=expired', ''],
      ['?method=google', ''],
      ['?email=', ''],
      ['', '#code=abc'],
      ['', '#error=access_denied'],
    ]) {
      assert.equal(asksForPassword(search, hash), false, `${search}${hash}`);
    }
  });
});

describe('the choice, for the session', () => {
  test('opening it is remembered, closing it forgets it', () => {
    const storage = memory();
    assert.equal(passwordChosen(() => storage), false);
    rememberPasswordChoice(() => storage, true);
    assert.equal(passwordChosen(() => storage), true);
    assert.ok(PASSWORD_CHOSEN_KEY.startsWith('shurly_'));
    assert.equal(storage.items.get(PASSWORD_CHOSEN_KEY), '1');
    rememberPasswordChoice(() => storage, false);
    assert.equal(passwordChosen(() => storage), false);
    assert.equal(storage.items.size, 0);
  });

  test('without storage, it stays closed and nothing throws', () => {
    assert.equal(passwordChosen(blocked), false);
    assert.doesNotThrow(() => rememberPasswordChoice(blocked, true));
    const throwing = { getItem: blocked, setItem: blocked, removeItem: blocked };
    assert.equal(passwordChosen(() => throwing), false);
    assert.doesNotThrow(() => rememberPasswordChoice(() => throwing, true));
    assert.doesNotThrow(() => rememberPasswordChoice(() => throwing, false));
  });
});
