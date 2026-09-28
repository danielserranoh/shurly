// Phase 6.3 — the Content-Security-Policy: the checks every built page must pass
// (scripts/csp-rules.mjs), and the inline guards it allows (src/inline-scripts.mjs).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import vm from 'node:vm';

import { checkPage, parsePolicy, sha256 } from '../scripts/csp-rules.mjs';
import { GUEST_GUARD, PROTECTED_GUARD } from '../src/inline-scripts.mjs';

const BASE = "default-src 'self'; connect-src 'self' https://shurly.griddo.io; img-src 'self' https: data: blob:; object-src 'none'; base-uri 'self'; form-action 'self'";
const policy = (scriptSrc = "'self'") => `${BASE}; script-src ${scriptSrc}; style-src 'self'`;
const meta = (content) => `<meta http-equiv="content-security-policy" content="${content}">`;
const page = ({ head = '', body = '', csp = meta(policy()) } = {}) =>
  `<!DOCTYPE html><html><head><meta charset="utf-8"><title>t</title>${head}${csp}<link rel="stylesheet" href="/_astro/a.css"></head><body>${body}</body></html>`;
const problems = (html) => checkPage(html).problems;

describe('checkPage', () => {
  test('a page with the policy first and hashed inline scripts passes', () => {
    const body = `<script>${PROTECTED_GUARD}</script><script type="module" src="/_astro/x.js"></script>`;
    const result = checkPage(page({ body, csp: meta(policy(`'self' ${sha256(PROTECTED_GUARD)}`)) }));
    assert.deepEqual(result.problems, []);
    assert.equal(result.inlineScripts, 1);
  });

  test('the policy must come before every script and preload', () => {
    assert.deepEqual(problems(page({ head: '<script src="/_astro/x.js"></script>' })), ['a <script> comes before the CSP <meta>']);
    assert.deepEqual(problems(page({ head: '<link rel="preload" as="font" href="/_astro/f.woff2">' })), ['a preload <link> comes before the CSP <meta>']);
    assert.deepEqual(problems(page({ head: '<link rel="modulepreload" href="/_astro/m.js">' })), ['a preload <link> comes before the CSP <meta>']);
  });

  test('an inline script must be covered by its hash', () => {
    assert.match(problems(page({ body: '<script>alert(1)</script>' }))[0], /inline script not covered/);
  });

  test('an inline <style> must be covered by its hash', () => {
    const css = 'body{color:red}';
    assert.match(problems(page({ body: `<style>${css}</style>` }))[0], /inline <style> not covered/);
    const covered = `${BASE}; script-src 'self'; style-src 'self' ${sha256(css)}`;
    assert.deepEqual(problems(page({ body: `<style>${css}</style>`, csp: meta(covered) })), []);
  });

  test('no inline event handlers and no javascript: URLs', () => {
    assert.match(problems(page({ body: '<img src="/x.png" onerror="alert(1)">' }))[0], /inline event handler/);
    assert.match(problems(page({ body: '<a href="javascript:alert(1)">x</a>' }))[0], /javascript: URL/);
    // Text that only looks like one is fine: data-on-…, "onboarding", code inside a script.
    const body = `<p data-onboarding="x">onboarding=done</p><script>${PROTECTED_GUARD}</script>`;
    assert.deepEqual(problems(page({ body, csp: meta(policy(`'self' ${sha256(PROTECTED_GUARD)}`)) })), []);
  });

  test('the policy keeps its directives, and scripts stay strict', () => {
    assert.ok(problems(page({ csp: meta("script-src 'self'") })).includes("object-src lacks 'none'"));
    assert.ok(problems(page({ csp: meta(policy("'self' 'unsafe-inline'")) })).includes("script-src allows 'unsafe-inline'"));
    assert.deepEqual(problems(page({ csp: '' })), ['expected one CSP <meta>, found 0']);
  });

  test('HTML-escaped quotes in the policy read the same', () => {
    assert.deepEqual(parsePolicy("script-src &#39;self&#39;; img-src https:"), { 'script-src': ["'self'"], 'img-src': ['https:'] });
  });

  test('Astro’s redirect pages are skipped', () => {
    const redirect = '<!doctype html><title>Redirecting to: /login/</title><meta http-equiv="refresh" content="0;url=/login/">';
    assert.equal(checkPage(redirect).skipped, true);
  });
});

describe('the guards', () => {
  /** Run a guard with a session token (or none) at a given address; returns where it sent the browser. */
  const run = (guard, { token = null, pathname = '/dashboard/', search = '', hash = '' } = {}) => {
    const sent = [];
    vm.runInNewContext(guard, {
      encodeURIComponent,
      localStorage: { getItem: (key) => (key === 'shurly_auth_token' ? token : null) },
      location: { pathname, search, hash, replace: (to) => sent.push(to) },
    });
    return sent;
  };

  test('a protected page without a session goes to the login page, with the way back', () => {
    assert.deepEqual(run(PROTECTED_GUARD, { pathname: '/dashboard/link/', search: '?code=abc' }), ['/login/?next=%2Fdashboard%2Flink%2F%3Fcode%3Dabc']);
    assert.deepEqual(run(PROTECTED_GUARD, { token: 'jwt' }), []);
  });

  test('a sign-in page with a session goes to the dashboard, unless Google’s answer is for it', () => {
    assert.deepEqual(run(GUEST_GUARD, { token: 'jwt', pathname: '/login/' }), ['/dashboard/']);
    assert.deepEqual(run(GUEST_GUARD, { token: 'jwt', pathname: '/login/', hash: '#code=x' }), []);
    assert.deepEqual(run(GUEST_GUARD, { token: 'jwt', pathname: '/login/', hash: '#error=denied' }), []);
    assert.deepEqual(run(GUEST_GUARD, { pathname: '/login/' }), []);
  });
});
