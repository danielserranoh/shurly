// A link card's badges flag the exceptions (src/utils/links.ts → linkBadges). A social preview set for the link,
// over the page's own, gets a quiet "Custom preview" badge; a link showing the page's preview gets none.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).
//
// links.ts is browser code: its imports leave out the `.ts` extension (Vite resolves them) and api.ts reads
// `import.meta.env` (Vite fills it). Two module hooks stand in for Vite here, so the test runs the real
// linkBadges: the extension is added, and `import.meta.env` is an empty object.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register(
  'data:text/javascript,' +
    encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if (specifier.startsWith('.') && !/\\.[a-z]+$/i.test(specifier)) return next(specifier + '.ts', context);
  return next(specifier, context);
}
export async function load(url, context, next) {
  const result = await next(url, context);
  if (url.endsWith('.ts') && result.source != null)
    return { ...result, source: String(result.source).replaceAll('import.meta.env', '({})') };
  return result;
}`),
);

const { linkBadges } = await import('../src/utils/links.ts');
const { icon } = await import('../src/utils/icons.ts');

// A standard, active, forwarding link: no badge at all.
const LINK = {
  id: 'l1',
  short_code: 'k3x9pa',
  original_url: 'https://www.acme.com/catalogue',
  url_type: 'standard',
  forward_parameters: true,
  visibility: 'organization',
  valid_since: null,
  valid_until: null,
  max_visits: null,
  click_count: 0,
  campaign_id: null,
};

const badges = (link) => linkBadges(link).value;

describe('the custom-preview badge', () => {
  test('a link with a preview set for it shows it, quiet: outline, with the image icon', () => {
    const out = badges({ ...LINK, has_custom_preview: true });
    assert.match(out, /^<span class="badge badge-outline" title="[^"]+">/);
    assert.ok(out.endsWith(`${icon('image', 'size-3').value}Custom preview</span>`), out);
  });

  test('a link showing the page’s own preview doesn’t', () => {
    assert.equal(badges({ ...LINK, has_custom_preview: false }), '');
    assert.doesNotMatch(badges({ ...LINK }), /Custom preview/); // a card from an API older than the field
  });

  test('it joins the other exceptions, after them', () => {
    const out = badges({ ...LINK, url_type: 'custom', forward_parameters: false, has_custom_preview: true });
    const order = ['>Custom<', 'No param forwarding', 'Custom preview'].map((label) => out.indexOf(label));
    assert.ok(order.every((at) => at >= 0), out);
    assert.deepEqual([...order].sort((a, b) => a - b), order);
  });

  test('the type badges can be left out, the preview badge stays', () => {
    const out = linkBadges({ ...LINK, url_type: 'custom', has_custom_preview: true }, { withType: false }).value;
    assert.doesNotMatch(out, />Custom</);
    assert.match(out, /Custom preview/);
  });
});
