// Phase 10.3 — links managed by their service account, on the links list (src/utils/links.ts):
// - the tabs: Links | Campaign links | one per account managing links; what each asks the API, the address it
//   keeps, and the older addresses (`?type=all`, `?via_service_account=`) mapped onto them;
// - a managed link's card: "Managed by <name>", its destination as the API gives it (a mask isn't a link), and no
//   Edit or Delete; its tag pills keep the tab.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is). The module hooks stand in for Vite,
// as in link-badges.test.mjs: the `.ts` extension is added, and `import.meta.env` is an empty object.

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

const {
  LINKS_TAB,
  isMaskedDestination,
  linkBadges,
  listHref,
  managerLabel,
  renderLinkCard,
  settleTab,
  tabFromParams,
  tabFromValue,
  tabParams,
  tabQuery,
  tabValue,
} = await import('../src/utils/links.ts');
const { icon } = await import('../src/utils/icons.ts');

const ACCOUNT = '6f1c2a9e-0d4b-4c1e-9a7f-3b2d1e0c9a8b';
const PROPUESTAS = { id: ACCOUNT, display_name: 'Propuestas Griddo' };

const LINK = {
  id: 'l1',
  short_code: 'k3x9pa',
  short_url: 'https://go.griddo.io/k3x9pa',
  domain: 'go.griddo.io',
  original_url: 'https://www.acme.com/catalogue',
  url_type: 'standard',
  title: 'Catalogue',
  forward_parameters: true,
  visibility: 'organization',
  valid_since: null,
  valid_until: null,
  max_visits: null,
  click_count: 0,
  last_click_at: null,
  campaign_id: null,
  tags: [],
  created_by_email: 'ana@griddo.io',
  managed_by: null,
};
const MANAGED = {
  ...LINK,
  id: 'l2',
  original_url: 'https://propuestas.griddo.io/…',
  via_service_account: PROPUESTAS,
  managed_by: PROPUESTAS,
  tags: [{ id: 't1', name: 'Deal', color: 'blue' }],
};

const tabOf = (search) => tabFromParams(new URLSearchParams(search));

describe('the tabs', () => {
  test('each asks the API for its links: Links leaves the managed ones to their own tab', () => {
    assert.deepEqual(tabQuery(LINKS_TAB), { types: ['standard', 'custom'], managed: 'exclude' });
    assert.deepEqual(tabQuery({ kind: 'campaign' }), { types: ['campaign'] });
    assert.deepEqual(tabQuery({ kind: 'managed', id: ACCOUNT }), { managedBy: ACCOUNT });
  });

  test('the address names the tab, and reads back as it', () => {
    for (const tab of [LINKS_TAB, { kind: 'campaign' }, { kind: 'managed', id: ACCOUNT }]) {
      assert.deepEqual(tabFromParams(new URLSearchParams(tabParams(tab))), tab);
      assert.deepEqual(tabFromValue(tabValue(tab)), tab);
    }
    assert.deepEqual(tabParams(LINKS_TAB), {});
    assert.deepEqual(tabParams({ kind: 'campaign' }), { type: 'campaign' });
    assert.deepEqual(tabParams({ kind: 'managed', id: ACCOUNT }), { managed_by: ACCOUNT });
  });

  test('older addresses: ?type=all lands on Links, ?via_service_account= on that account’s tab', () => {
    assert.deepEqual(tabOf('type=all'), LINKS_TAB);
    assert.deepEqual(tabOf('type=links'), LINKS_TAB);
    assert.deepEqual(tabOf('type=nonsense'), LINKS_TAB);
    assert.deepEqual(tabOf(''), LINKS_TAB);
    assert.deepEqual(tabOf(`type=all&via_service_account=${ACCOUNT}`), { kind: 'managed', id: ACCOUNT });
    assert.deepEqual(tabOf(`managed_by=${ACCOUNT}&type=campaign`), { kind: 'managed', id: ACCOUNT });
  });

  test('an account’s tab only while it manages links the viewer sees; Links otherwise', () => {
    const tab = { kind: 'managed', id: ACCOUNT };
    assert.deepEqual(settleTab(tab, [{ ...PROPUESTAS, link_count: 3 }]), tab);
    assert.deepEqual(settleTab(tab, [{ ...PROPUESTAS, link_count: 0 }]), LINKS_TAB);
    assert.deepEqual(settleTab(tab, [{ id: 'another', display_name: 'Other', link_count: 2 }]), LINKS_TAB);
    assert.deepEqual(settleTab(tab, []), LINKS_TAB);
    assert.deepEqual(settleTab(tab, null), tab, 'without the list, the API decides');
    assert.deepEqual(settleTab({ kind: 'campaign' }, []), { kind: 'campaign' });
  });

  test('a tag pill keeps the tab', () => {
    assert.equal(listHref(LINKS_TAB, ['t1']), '/dashboard/?tags=t1');
    assert.equal(listHref({ kind: 'campaign' }, ['t1']), '/dashboard/?type=campaign&tags=t1');
    assert.equal(listHref({ kind: 'managed', id: ACCOUNT }, ['t1', 't2']), `/dashboard/?managed_by=${ACCOUNT}&tags=t1%2Ct2`);
    assert.equal(listHref(LINKS_TAB), '/dashboard/');
  });

  test('an account without a name still gets a tab', () => {
    assert.equal(managerLabel(PROPUESTAS), 'Propuestas Griddo');
    assert.equal(managerLabel({ display_name: null }), 'Service account');
    assert.equal(managerLabel({ display_name: '  ' }), 'Service account');
  });
});

describe('a managed link’s card', () => {
  test('its badge says who manages it, quiet: outline, with the plug', () => {
    const out = linkBadges(MANAGED).value;
    assert.match(out, /^<span class="badge badge-outline" title="Only Propuestas Griddo changes or deletes it; people can change its tags\.">/);
    assert.ok(out.includes(`${icon('plug', 'size-3').value}Managed by Propuestas Griddo</span>`), out);
    assert.doesNotMatch(linkBadges(LINK).value, /Managed by/);
    assert.doesNotMatch(linkBadges(MANAGED, { withManager: false }).value, /Managed by/);
  });

  test('no Edit and no Delete: the menu says where they happen', () => {
    const card = renderLinkCard(MANAGED).value;
    assert.doesNotMatch(card, /data-action="edit"/);
    assert.doesNotMatch(card, /data-action="delete"/);
    assert.match(card, /aria-disabled="true" title="Managed by Propuestas Griddo: change it from there\.[^"]*">.*Edit via Propuestas Griddo<\/span>/s);
    assert.match(card, /aria-disabled="true" title="Managed by Propuestas Griddo: delete it from there">.*Delete via Propuestas Griddo<\/span>/s);
    assert.match(card, /data-action="qr"/, 'the QR code stays');
  });

  test('a link that isn’t managed keeps both', () => {
    const card = renderLinkCard(LINK).value;
    assert.match(card, /data-action="edit"/);
    assert.match(card, /data-action="delete"/);
    assert.doesNotMatch(card, /via Propuestas/);
  });

  test('its masked destination shows as the API gives it, and isn’t a link', () => {
    assert.ok(isMaskedDestination(MANAGED.original_url));
    assert.ok(!isMaskedDestination(LINK.original_url));
    const card = renderLinkCard(MANAGED).value;
    assert.match(card, /<span class="truncate" title="Only Propuestas Griddo and the organization’s owners see the full destination">propuestas\.griddo\.io\/…<\/span>/);
    assert.doesNotMatch(card, /<a [^>]*title="https:\/\/propuestas\.griddo\.io\/…"/);
  });

  test('an owner sees the destination, a link to open', () => {
    const card = renderLinkCard({ ...MANAGED, original_url: 'https://propuestas.griddo.io/p/abc?t=secret' }).value;
    // safeUrl needs a page's origin; under node every href is "#", so the anchor is told by its title.
    assert.match(card, /<a href="[^"]*" target="_blank" rel="noopener noreferrer" class="truncate hover:text-ink-800" title="https:\/\/propuestas\.griddo\.io\/p\/abc\?t=secret">/);
  });

  test('its tag pills lead to the list in its tab', () => {
    const tab = { kind: 'managed', id: ACCOUNT };
    const card = renderLinkCard(MANAGED, { tagHref: (id) => listHref(tab, [id]) }).value;
    assert.ok(card.includes(`href="/dashboard/?managed_by=${ACCOUNT}&amp;tags=t1"`), card);
    assert.ok(renderLinkCard(MANAGED).value.includes('href="/dashboard/?tags=t1"'), 'by default, the Links tab');
  });
});
