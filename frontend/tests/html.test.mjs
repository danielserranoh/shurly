// Phase 6.3 — the escaping that every dynamic piece of markup goes through (src/utils/html.ts).

import assert from 'node:assert/strict';
import { before, describe, test } from 'node:test';

import { escapeHtml, html, raw, safeUrl, setHTML } from '../src/utils/html.ts';

before(() => {
  globalThis.window = { location: { origin: 'https://s.griddo.io' } };
});

describe('html', () => {
  test('escapes what it interpolates, in text and in attributes', () => {
    const title = '<img src=x onerror=alert(1)>';
    const quoted = '" onmouseover="alert(1)';
    assert.equal(html`<p title="${quoted}">${title}</p>`.value, '<p title="&quot; onmouseover=&quot;alert(1)">&lt;img src=x onerror=alert(1)&gt;</p>');
    assert.equal(escapeHtml(`'&`), '&#39;&amp;');
  });

  test('nests html results and raw() as markup, and nothing else', () => {
    const inner = html`<b>${'<i>'}</b>`;
    assert.equal(html`<p>${inner}${raw('<br>')}</p>`.value, '<p><b>&lt;i&gt;</b><br></p>');
    assert.equal(html`${[html`<li>${'a&b'}</li>`, '<li>']}`.value, '<li>a&amp;b</li>&lt;li&gt;');
  });

  test('renders null, undefined and false as nothing, but keeps 0', () => {
    assert.equal(html`${null}${undefined}${false}${0}`.value, '0');
  });
});

describe('safeUrl', () => {
  test('keeps http and https', () => {
    assert.equal(safeUrl('https://example.com/a?b=1#c'), 'https://example.com/a?b=1#c');
    assert.equal(safeUrl('http://example.com/'), 'http://example.com/');
  });

  test('turns every other scheme into #, however it is written', () => {
    for (const url of [
      'javascript:alert(1)',
      'JaVaScRiPt:alert(1)',
      ' javascript:alert(1)',
      'java\tscript:alert(1)',
      'java\nscript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'file:///etc/passwd',
    ]) {
      assert.equal(safeUrl(url), '#', JSON.stringify(url));
    }
  });

  test('nothing, or garbage, is #', () => {
    for (const url of [null, undefined, '', 'http://[bad']) assert.equal(safeUrl(url), '#', JSON.stringify(url));
  });

  test('a path is resolved on this site', () => {
    assert.equal(safeUrl('/dashboard/'), 'https://s.griddo.io/dashboard/');
  });
});

describe('setHTML', () => {
  test('puts markup from html in as markup', () => {
    const el = { innerHTML: '' };
    setHTML(el, html`<b>${'<i>'}</b>`);
    assert.equal(el.innerHTML, '<b>&lt;i&gt;</b>');
  });

  test('escapes a string, and anything that only looks like markup from html', () => {
    const el = { innerHTML: '' };
    setHTML(el, '<img src=x onerror=alert(1)>');
    assert.equal(el.innerHTML, '&lt;img src=x onerror=alert(1)&gt;');
    setHTML(el, { value: '<img src=x onerror=alert(1)>' }); // a look-alike, not RawHTML
    assert.equal(el.innerHTML, '[object Object]');
  });
});

describe('Trusted Types', () => {
  test('the markup goes through the one policy, shurly-html, made once', async () => {
    const made = [];
    globalThis.trustedTypes = {
      createPolicy(name, rules) {
        made.push(name);
        return { createHTML: (markup) => ({ trusted: rules.createHTML(markup) }) };
      },
    };
    try {
      // A fresh copy of the module, made while the browser "has" Trusted Types.
      const fresh = await import('../src/utils/html.ts?trusted-types');
      const el = { innerHTML: '' };
      fresh.setHTML(el, fresh.html`<b>${'<i>'}</b>`);
      fresh.setHTML(el, fresh.html`<p>again</p>`);
      assert.deepEqual(el.innerHTML, { trusted: '<p>again</p>' });
      assert.deepEqual(made, ['shurly-html']);
      assert.equal(Object.keys(fresh).some((name) => /polic/i.test(name)), false, 'the policy stays in the module');
    } finally {
      delete globalThis.trustedTypes;
    }
  });
});
