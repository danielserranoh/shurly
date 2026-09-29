// What a browser error report says (src/utils/error-report.ts): short, one line, no query or fragment in any URL,
// and five a page at most, one of each. Run: `npm test`.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { clean, cspMessage, describeReason, isForeign, MAX_REPORTS, report, reportGate, sourceOf } from '../src/utils/error-report.ts';

const ORIGIN = 'https://shurly.griddo.io';

describe('clean', () => {
  test('one line, without control characters: a NUL never leaves the browser', () => {
    assert.equal(clean('boom\n  at x\u0000y\t z', 500), 'boom at x y z');
  });

  test("a URL keeps its address, not its query or fragment", () => {
    assert.equal(
      clean('Failed to fetch https://shurly.griddo.io/api/v1/urls?q=ana%40acme.com#top, then retried', 500),
      'Failed to fetch https://shurly.griddo.io/api/v1/urls, then retried',
    );
  });

  test('cut to the size the API takes', () => {
    assert.equal(clean('x'.repeat(600), 500).length, 500);
  });
});

describe('sourceOf', () => {
  test("our own scripts by their path, with line and column", () => {
    assert.equal(sourceOf(`${ORIGIN}/_astro/link.Ab12cd.js?v=2`, 3, 1403, ORIGIN), '/_astro/link.Ab12cd.js:3:1403');
  });

  test('nothing to say without a file', () => {
    assert.equal(sourceOf('', 0, 0, ORIGIN), '');
    assert.equal(sourceOf(undefined, 3, 4, ORIGIN), '');
  });
});

describe('describeReason', () => {
  test("an error by its name and message", () => {
    assert.equal(describeReason(new TypeError('x is undefined')), 'TypeError: x is undefined');
  });

  test('text as it is, and anything else by its type, never its contents', () => {
    assert.equal(describeReason('timeout'), 'timeout');
    assert.equal(describeReason({ email: 'ana@acme.com' }), '[object Object]');
    assert.equal(describeReason(undefined), 'undefined');
  });
});

describe('cspMessage', () => {
  test("what was blocked, by its origin only", () => {
    assert.equal(cspMessage('connect-src', 'https://example.com/e2e?secret=1'), 'connect-src blocked https://example.com');
  });

  test('keywords as they are', () => {
    assert.equal(cspMessage('require-trusted-types-for', 'trusted-types-sink'), 'require-trusted-types-for blocked trusted-types-sink');
    assert.equal(cspMessage('script-src-elem', 'inline'), 'script-src-elem blocked inline');
    assert.equal(cspMessage('style-src-attr', ''), 'style-src-attr blocked inline');
  });
});

describe('isForeign', () => {
  test("a browser extension's errors, and cross-origin scripts' bare \"Script error.\", aren't ours", () => {
    assert.equal(isForeign('Uncaught TypeError: x', 'chrome-extension://abc/content.js'), true);
    assert.equal(isForeign('Script error.', ''), true);
  });

  test('our scripts, inline code and evaluated code are', () => {
    assert.equal(isForeign('Uncaught TypeError: x', `${ORIGIN}/_astro/link.js`), false);
    assert.equal(isForeign('Uncaught TypeError: x', ''), false);
    assert.equal(isForeign('Uncaught TypeError: x', '__playwright_evaluation_script__'), false);
    assert.equal(isForeign('Uncaught TypeError: x', 'moz-extension://abc/x.js'), true);
  });
});

describe('report', () => {
  test("the page's path only", () => {
    assert.deepEqual(report('error', 'boom', '/_astro/a.js:1:2', '/dashboard/link/?code=abc#visits'), {
      kind: 'error',
      message: 'boom',
      source: '/_astro/a.js:1:2',
      page: '/dashboard/link/',
    });
  });

  test('nothing to report without a message', () => {
    assert.equal(report('error', '  \n ', '', '/'), null);
  });
});

test('five reports a page at most, and one of each', () => {
  const allow = reportGate();
  const boom = report('error', 'boom', '', '/');
  assert.equal(MAX_REPORTS, 5);
  assert.equal(allow(boom), true);
  assert.equal(allow(boom), false);
  const others = [1, 2, 3, 4, 5].map((n) => allow(report('error', `boom ${n}`, '', '/')));
  assert.deepEqual(others, [true, true, true, true, false]);
});
