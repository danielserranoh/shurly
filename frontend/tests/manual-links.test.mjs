// Phase 7.1 — the manual's links go somewhere: another page of the manual (and its heading, when one is named,
// slugged as Astro does), a page of the app, or a Settings tab. A broken one fails here, not in front of a reader.
// Run: `npm test`.

import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

import GithubSlugger from 'github-slugger';

const MANUAL = new URL('../src/content/manual/', import.meta.url);
const PAGES = new URL('../src/pages/', import.meta.url);
const read = (url) => readFileSync(url, 'utf8');
const withoutCode = (markdown) => markdown.replace(/```[\s\S]*?```/g, '');

/** A manual page's heading ids, as Astro gives them. */
function headingIds(slug) {
  const slugger = new GithubSlugger();
  return [...withoutCode(read(new URL(`${slug}.md`, MANUAL))).matchAll(/^#{2,6}\s+(.+)$/gm)].map((m) => slugger.slug(m[1].trim()));
}

/** Where an app path is built from: dashboard/settings/ → dashboard/settings.astro or …/settings/index.astro. */
function appPageExists(pathname) {
  const path = pathname.replace(/^\/|\/$/g, '');
  const candidates = path ? [`${path}.astro`, `${path}/index.astro`] : ['index.astro'];
  return candidates.some((file) => existsSync(new URL(file, PAGES)));
}

const pages = readdirSync(MANUAL).filter((file) => file.endsWith('.md'));

test('the manual has pages to check', () => {
  assert.ok(pages.length >= 3, pages.join(', '));
});

for (const file of pages) {
  test(`${file}: every link inside it resolves`, () => {
    const links = [...withoutCode(read(new URL(file, MANUAL))).matchAll(/\]\((\/[^)\s]*)\)/g)].map((m) => m[1]);
    for (const href of links) {
      const url = new URL(href, 'https://shurly.test');
      if (url.pathname.startsWith('/manual/')) {
        const slug = url.pathname.split('/')[2];
        if (slug) assert.ok(existsSync(new URL(`${slug}.md`, MANUAL)), `${href}: no manual page "${slug}"`);
        if (url.hash) assert.ok(headingIds(slug).includes(url.hash.slice(1)), `${href}: no heading "${url.hash}" there`);
      } else {
        assert.ok(appPageExists(url.pathname), `${href}: no page in src/pages`);
        if (url.pathname === '/dashboard/settings/' && url.hash) {
          assert.match(read(new URL('dashboard/settings.astro', PAGES)), new RegExp(`key: '${url.hash.slice(1)}'`), `${href}: no such Settings tab`);
        }
      }
    }
  });
}
