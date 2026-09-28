// Phase 6.3 — no new way for API or user data to reach the page as markup.
//
// Dynamic HTML goes through the escaping `html` tag and `setHTML` (src/utils/html.ts).
// This test reads the source and fails on:
// - a raw HTML sink (innerHTML, outerHTML, insertAdjacentHTML, …) that isn't in ALLOWED_SINKS
//   below, each with its reason, and each with a `// static:` comment just above it;
// - `raw(…)` on anything but a string literal (the icon helper aside);
// - an href or src built from a URL that doesn't go through `safeUrl` (http and https only:
//   a `javascript:` link is an XSS even when escaped).
// An entry in an allowlist that no longer matches anything fails too, so the lists stay true.

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { test } from 'node:test';

const ROOT = new URL('..', import.meta.url).pathname;
const SRC = join(ROOT, 'src');

const files = readdirSync(SRC, { recursive: true })
  .filter((f) => /\.(astro|ts|js|mjs)$/.test(f))
  .map((f) => {
    const path = join(SRC, f);
    return { name: relative(ROOT, path), lines: readFileSync(path, 'utf8').split('\n') };
  });

function* occurrences(pattern) {
  for (const file of files) {
    for (const [i, line] of file.lines.entries()) {
      if (pattern.test(line)) yield { file: file.name, line: i + 1, text: line.trim(), above: file.lines[i - 1]?.trim() ?? '' };
    }
  }
}

const where = (o) => `${o.file}:${o.line}  ${o.text}`;

/** Every allowed occurrence: [file, a unique part of the line, why it's safe]. */
function check(found, allowed, extra = () => null) {
  const unused = new Set(allowed);
  const problems = [];
  for (const o of found) {
    const entry = allowed.find(([file, part]) => o.file === file && o.text.includes(part));
    if (!entry) {
      problems.push(where(o));
      continue;
    }
    unused.delete(entry);
    const issue = extra(o, entry);
    if (issue) problems.push(`${where(o)}  (${issue})`);
  }
  for (const [file, part] of unused) problems.push(`allowlisted but gone: ${file}  ${part}`);
  return problems;
}

const ALLOWED_SINKS = [
  ['src/utils/html.ts', 'el.innerHTML = typeof markup', 'setHTML itself: escapes strings, and RawHTML only comes from `html`'],
  ['src/utils/html.ts', 'template.innerHTML = markup.value', 'toElement itself: RawHTML only'],
  ['src/components/app/QrModal.astro', 'preview.innerHTML = qrSvg(url)', 'numbers and fixed colours; no text from the URL'],
];

test('raw HTML sinks are only the allowlisted, static ones', () => {
  const sink = /\.(?:innerHTML|outerHTML)\s*[+]?=(?!=)|\binsertAdjacentHTML\s*\(|\bdocument\.write(?:ln)?\s*\(|\bcreateContextualFragment\s*\(|\bsrcdoc\s*=/;
  const problems = check(occurrences(sink), ALLOWED_SINKS, (o) =>
    o.file === 'src/utils/html.ts' || o.above.startsWith('// static:') ? null : 'needs a `// static: why` comment above it',
  );
  assert.deepEqual(problems, [], 'Render with setHTML(el, html`…`) or textContent instead:\n' + problems.join('\n'));
});

test('raw() only wraps string literals, or an icon', () => {
  const allowed = [['src/utils/icons.ts', 'return raw(iconSvg(name, className, strokeWidth))', 'the icon helper: our own SVG']];
  const calls = [...occurrences(/\braw\(/)].filter((o) => o.file !== 'src/utils/html.ts');
  const literal = /\braw\((['"])[^'"$]*\1\)/g;
  const loose = calls.filter((o) => o.text.replace(literal, '').match(/\braw\(/));
  const problems = check(loose, allowed);
  assert.deepEqual(problems, [], 'raw() on data is an XSS: interpolate it into html`…` instead:\n' + problems.join('\n'));
});

test('href and src built from a URL go through safeUrl', () => {
  // Interpolated into markup: href="${…}", src="${…}".
  const attr = /\b(?:href|src)="\$\{(?!safeUrl\()[^}]*(?:url|image)[^}]*\}/i;
  // Set on an element: a.href = …, img.src = ….
  const prop = /\.(?:href|src)\s*=(?!\s*safeUrl\()[^;]*(?:url|image)/i;
  const allowed = [['src/utils/qr.ts', 'img.src = url;', 'a blob: URL from URL.createObjectURL, for the PNG export']];
  const problems = check([...occurrences(attr), ...occurrences(prop)], allowed);
  assert.deepEqual(problems, [], 'Wrap it in safeUrl(…): http and https only.\n' + problems.join('\n'));
});

test('set:html is build-time only, with our own markup', () => {
  const allowed = [
    ['src/components/ui/Icon.astro', 'set:html={iconSvg(name, className, strokeWidth)}', 'icons, at build time'],
    ['src/pages/styleguide.astro', 'set:html={pill(', 'specimens with literal tag names, at build time'],
  ];
  // The styleguide has many specimens: one entry covers them all.
  const found = [...occurrences(/set:html/)];
  const problems = check(found, allowed);
  assert.deepEqual(problems, [], 'set:html renders raw markup:\n' + problems.join('\n'));
});
