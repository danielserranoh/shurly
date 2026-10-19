// Phase 10.2 — a service account's token settings and its audit, in words (src/utils/service-accounts.ts): the
// scopes' summary on a token's line, the IP ranges typed one per line, the expiry the form starts from, the menu
// dot's label, and each audit event as a sentence with who it was for or by.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).
//
// The module imports only types, but its imports leave out the `.ts` extension (Vite resolves them): the hook
// adds it, as in link-badges.test.mjs.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register(
  'data:text/javascript,' +
    encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if (specifier.startsWith('.') && !/\\.[a-z]+$/i.test(specifier)) return next(specifier + '.ts', context);
  return next(specifier, context);
}`),
);

const sa = await import('../src/utils/service-accounts.ts');

describe('the scopes', () => {
  test('six, in the API’s order, each with a label in plain words', () => {
    assert.deepEqual(sa.ALL_SCOPES, ['urls:read', 'urls:write', 'urls:delete', 'tags:write', 'analytics:read', 'act_on_behalf']);
    for (const { label } of sa.SCOPES) assert.match(label, /^[A-Z][a-z]/, label); // sentence case
  });

  test('every scope reads “All permissions”, whatever the order', () => {
    assert.equal(sa.scopeSummary([...sa.ALL_SCOPES]), 'All permissions');
    assert.equal(sa.scopeSummary([...sa.ALL_SCOPES].reverse()), 'All permissions');
  });

  test('some read as a short list, in the API’s order, sentence case', () => {
    assert.equal(sa.scopeSummary(['urls:write', 'urls:read']), 'See links, change links');
    assert.equal(sa.scopeSummary(['act_on_behalf']), 'Act for people');
    assert.equal(sa.scopeSummary(['analytics:read', 'tags:write', 'urls:delete']), 'Delete links, manage tags, see analytics');
  });

  test('one this page doesn’t know shows as it is; none at all says so', () => {
    assert.equal(sa.scopeSummary(['urls:read', 'campaigns:send']), 'See links, campaigns:send');
    assert.equal(sa.scopeSummary([]), 'No permissions');
  });

  test('a 422 on one scope, by its index, lands on the scopes', () => {
    assert.deepEqual(sa.tokenErrorFields(['0', '3', 'allowed_ip_ranges']), { 0: 'scopes', 3: 'scopes' });
    assert.deepEqual(sa.tokenErrorFields(['scopes', 'expires_at']), {});
  });
});

describe('the allowed IP ranges', () => {
  test('one per line, blanks and repeats dropped, spaces trimmed', () => {
    assert.deepEqual(sa.parseRanges('203.0.113.0/24\n\n  2001:db8::/32  \r\n203.0.113.0/24\n'), ['203.0.113.0/24', '2001:db8::/32']);
  });

  test('commas and spaces split them too', () => {
    assert.deepEqual(sa.parseRanges('10.0.0.0/8, 192.168.1.0/24 172.16.0.0/12'), ['10.0.0.0/8', '192.168.1.0/24', '172.16.0.0/12']);
  });

  test('empty is any address: an empty list', () => {
    assert.deepEqual(sa.parseRanges(''), []);
    assert.deepEqual(sa.parseRanges(' \n \n'), []);
  });

  test('on the token’s line: nothing for any address, one or two named, more counted', () => {
    assert.equal(sa.rangesSummary([]), '');
    assert.equal(sa.rangesSummary(['203.0.113.0/24']), 'From 203.0.113.0/24');
    assert.equal(sa.rangesSummary(['203.0.113.0/24', '2001:db8::/32']), 'From 203.0.113.0/24 and 2001:db8::/32');
    assert.equal(sa.rangesSummary(['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']), 'From 3 IP ranges');
  });
});

describe('the expiry', () => {
  test('starts a year from today, as the date input’s value', () => {
    assert.equal(sa.defaultExpiryDay(new Date(2026, 9, 19, 15, 30)), '2027-10-19');
    assert.equal(sa.defaultExpiryDay(new Date(2026, 0, 5)), '2027-01-05');
  });

  test('a year from Feb 29 is Feb 28, not Mar 1', () => {
    assert.equal(sa.defaultExpiryDay(new Date(2028, 1, 29)), '2029-02-28');
  });

  test('just after midnight is still that local day', () => {
    assert.equal(sa.defaultExpiryDay(new Date(2026, 11, 31, 0, 5)), '2027-12-31');
    assert.equal(sa.localDay(new Date(2026, 11, 31, 23, 59)), '2026-12-31');
  });

  test('the day picked ends at its last second, local time', () => {
    const end = sa.endOfDay('2027-10-19');
    assert.deepEqual([end.getFullYear(), end.getMonth(), end.getDate(), end.getHours(), end.getMinutes(), end.getSeconds()], [2027, 9, 19, 23, 59, 59]);
  });
});

describe('the warnings', () => {
  test('a badge each, and the dot’s label counts the tokens', () => {
    assert.equal(sa.WARNING_LABELS.expires_soon, 'Expires soon');
    assert.equal(sa.WARNING_LABELS.unused, 'Unused for 90 days');
    assert.equal(sa.attentionLabel(1), '1 service token needs attention');
    assert.equal(sa.attentionLabel(2), '2 service tokens need attention');
  });
});

describe('the audit, in words', () => {
  const ANA = { id: 'u1', email: 'ana@griddo.io', name: 'Ana García', deleted: false };
  const event = (action, more = {}) => ({
    id: 'e1',
    at: '2026-10-19T09:00:00Z',
    action,
    target_type: action.split('.')[0],
    target_id: 't1',
    short_code: null,
    detail: null,
    service_account: { id: 's1', display_name: 'Propuestas Griddo', deleted: false },
    token_id: null,
    actor: null,
    on_behalf_of: null,
    ...more,
  });
  const say = (action, more) => sa.auditSentence(event(action, more));

  test('a link, by its code while it’s there and seen', () => {
    assert.equal(say('url.created', { short_code: 'ab12cd' }), 'Created link ab12cd');
    assert.equal(say('url.updated', { short_code: 'ab12cd', detail: { fields: ['title', 'tags'] } }), 'Changed link ab12cd');
    assert.equal(say('url.updated', { short_code: 'ab12cd', detail: { fields: ['tags'], tag_ids: ['x'] } }), 'Changed the tags of link ab12cd');
    assert.deepEqual(sa.auditWhat(event('url.created', { short_code: 'ab12cd' })), { text: 'Created link', code: 'ab12cd' });
  });

  test('a link that’s gone, or not seen, is “a link”', () => {
    assert.equal(say('url.deleted'), 'Deleted a link');
    assert.equal(say('url.created'), 'Created a link');
    assert.equal(say('url.updated', { detail: { fields: ['tags'] } }), 'Changed the tags of a link');
  });

  test('redirect rules, campaigns and tags', () => {
    assert.equal(say('redirect_rule.created', { detail: { url_id: 'x' } }), 'Added a redirect rule');
    assert.equal(say('redirect_rule.updated'), 'Changed a redirect rule');
    assert.equal(say('redirect_rule.deleted'), 'Deleted a redirect rule');
    assert.equal(say('campaign.created'), 'Created a campaign');
    assert.equal(say('campaign.updated', { detail: { fields: ['tags'] } }), 'Changed the tags of a campaign');
    assert.equal(say('campaign.deleted'), 'Deleted a campaign');
    assert.equal(say('tag.created'), 'Created a tag');
    assert.equal(say('tag.updated', { detail: { fields: ['name'] } }), 'Renamed a tag');
    assert.equal(say('tag.deleted'), 'Deleted a tag');
  });

  test('the account and its token', () => {
    assert.equal(say('service_account.created'), 'Created the service account');
    assert.equal(say('service_account.updated', { detail: { fields: ['role'] } }), 'Changed the service account');
    assert.equal(say('service_account.removed'), 'Removed the service account');
    assert.equal(say('service_token.created'), 'Created its token');
    assert.equal(say('service_token.renewed'), 'Renewed its token');
    assert.equal(say('service_token.revoked'), 'Revoked its token');
  });

  test('an action this page doesn’t know shows as it is', () => {
    assert.equal(say('campaign.sent'), 'campaign.sent');
    assert.equal(say('webhook.created'), 'webhook.created');
  });

  test('who: on behalf of a person, by the person who acted, or nobody', () => {
    assert.equal(sa.auditWho(event('url.created', { on_behalf_of: ANA })), 'On behalf of Ana García');
    assert.equal(sa.auditWho(event('url.created', { on_behalf_of: { ...ANA, name: null } })), 'On behalf of ana@griddo.io');
    assert.equal(sa.auditWho(event('service_token.renewed', { actor: ANA })), 'By Ana García');
    assert.equal(sa.auditWho(event('url.created')), '');
  });

  test('someone deleted shows as deleted', () => {
    const gone = { id: 'u2', email: null, name: null, deleted: true };
    assert.equal(sa.auditWho(event('url.created', { on_behalf_of: gone })), 'On behalf of a deleted person');
    assert.equal(sa.auditWho(event('service_account.created', { actor: gone })), 'By a deleted person');
  });
});
