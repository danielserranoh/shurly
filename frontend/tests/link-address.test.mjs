// A link is its code and its domain (Phase 8.3): every path to it names both, and a link
// without a domain (an old bookmark) keeps the plain path, which the API answers with the
// default domain's link.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { analyticsApi, linkApi, linkHref, withDomain } from '../src/utils/link-address.ts';

test('the link page names the domain', () => {
  assert.equal(linkHref('promo', 'go.griddo.io'), '/dashboard/link/?code=promo&domain=go.griddo.io');
});

test('without a domain, the plain path: the default domain’s link answers', () => {
  assert.equal(linkHref('promo'), '/dashboard/link/?code=promo');
  assert.equal(linkHref('promo', null), '/dashboard/link/?code=promo');
  assert.equal(linkApi({ short_code: 'promo' }), '/api/v1/urls/promo');
});

test('the API paths of a link and what hangs off it', () => {
  const link = { short_code: 'promo', domain: 'go.griddo.io' };
  assert.equal(linkApi(link), '/api/v1/urls/promo?domain=go.griddo.io');
  assert.equal(linkApi(link, '/rules/r1'), '/api/v1/urls/promo/rules/r1?domain=go.griddo.io');
  assert.equal(analyticsApi(link, 'geo?days=30'), '/api/v1/analytics/urls/promo/geo?days=30&domain=go.griddo.io');
});

test('the code and the domain are escaped', () => {
  assert.equal(linkApi({ short_code: 'a b/c', domain: 'x&y' }), '/api/v1/urls/a%20b%2Fc?domain=x%26y');
  assert.equal(withDomain('/p?q=1', 'd e'), '/p?q=1&domain=d%20e');
});
