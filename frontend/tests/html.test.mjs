// Phase 6.3 — the escaping that every dynamic piece of markup goes through (src/utils/html.ts).

import assert from 'node:assert/strict';
import { before, describe, test } from 'node:test';

import { escapeHtml, html, raw, safeUrl } from '../src/utils/html.ts';

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
