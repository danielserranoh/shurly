// Phase 4.10 — the CloudFront Function in front of the static build
// (infra/cloudfront/static-paths.js), run here the way CloudFront runs it: a plain script
// that defines handler(event), no modules.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, test } from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../infra/cloudfront/static-paths.js', import.meta.url), 'utf8');
const context = {};
vm.runInNewContext(source, context);
const { handler } = context;

/** A viewer request: `query` as CloudFront passes it ({name: {value, multiValue?}}). */
const run = (uri, querystring = {}) => handler({ version: '1.0', context: { eventType: 'viewer-request' }, request: { method: 'GET', uri, querystring, headers: {}, cookies: {} } });
const location = (result) => result.headers?.location?.value;

describe('pages get their index.html', () => {
  for (const [uri, expected] of [
    ['/', '/index.html'],
    ['/dashboard/', '/dashboard/index.html'],
    ['/manual/install-mcp/', '/manual/install-mcp/index.html'],
    ['/manual/v1.2/', '/manual/v1.2/index.html'],
  ]) {
    test(uri, () => assert.equal(run(uri).uri, expected));
  }

  test('the query stays with the request', () => {
    const result = run('/dashboard/link/', { code: { value: 'abc123' } });
    assert.equal(result.uri, '/dashboard/link/index.html');
    assert.deepEqual(result.querystring, { code: { value: 'abc123' } });
  });
});

describe('a dot in the last segment means a file', () => {
  for (const uri of ['/_astro/app.1a2b3c.js', '/favicon.svg', '/site.webmanifest', '/brand/shurly-logo-horizontal.svg', '/404.html', '/manual/v1.2']) {
    test(uri, () => {
      const result = run(uri);
      assert.equal(result.uri, uri);
      assert.equal(result.statusCode, undefined);
    });
  }
});

describe('a page without its slash gets a 301 to it', () => {
  test('/login', () => {
    const result = run('/login');
    assert.equal(result.statusCode, 301);
    assert.equal(location(result), '/login/');
  });

  test('keeps the query, repeated names and bare flags included', () => {
    const query = {
      code: { value: 'abc123' },
      tags: { value: 'a', multiValue: [{ value: 'a' }, { value: 'b%20c' }] },
      debug: { value: '' },
    };
    assert.equal(location(run('/dashboard/link', query)), '/dashboard/link/?code=abc123&tags=a&tags=b%20c&debug');
  });

  test('never to another site', () => {
    for (const uri of ['//evil', '///evil', '/\\evil', '/\\/evil', '//evil/path']) {
      const target = location(run(uri));
      assert.ok(target.startsWith('/') && !target.startsWith('//') && !target.includes('\\'), `${uri} → ${target}`);
      assert.equal(new URL(target, 'https://shurly.griddo.io').origin, 'https://shurly.griddo.io', `${uri} → ${target}`);
    }
  });
});

test('it is a plain script, as CloudFront Functions take it', () => {
  assert.doesNotMatch(source, /^\s*(import|export)\b/m);
  assert.doesNotMatch(source, /\brequire\(/);
});
