// Phase 10.3 — a managed link's page (src/pages/dashboard/link.astro), its pure rules:
// - who changes what (src/utils/viewer.ts): nobody in the app changes a managed link, its tags keep the old rule
//   (creator, admin, owner), and only an owner deletes it past its service account;
// - the lock's words name the manager;
// - the editor opens on the tags alone and doesn't validate a masked destination (src/utils/link-editor.ts);
// - the override's reason: 10 to 500 characters, surrounding whitespace ignored, as the API counts it.
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

const { canChange, canChangeTags, canOverrideDelete, lockFor, lockReason, managedLockReason, TAGS_LOCK_REASON } = await import('../src/utils/viewer.ts');
const { editorMode, fieldProblems, overrideCopy, reasonCount, reasonProblem, REASON_MAX, REASON_MIN } = await import('../src/utils/link-editor.ts');

const PROPUESTAS = { id: '6f1c2a9e-0d4b-4c1e-9a7f-3b2d1e0c9a8b', display_name: 'Propuestas Griddo' };
const CREATOR = 'ana@griddo.io';

const ORDINARY = { visibility: 'organization', created_by_email: CREATOR, managed_by: null };
const MANAGED = { ...ORDINARY, via_service_account: PROPUESTAS, managed_by: PROPUESTAS };

const as = (role, email = 'someone@griddo.io') => ({ email, organization: { role }, role });
const VIEWERS = {
  creator: as('member', CREATOR),
  member: as('member'),
  admin: as('admin'),
  owner: as('owner'),
};

describe('who changes a link', () => {
  test('an ordinary link: its creator, admins and owners; not another member', () => {
    assert.deepEqual(
      Object.fromEntries(Object.entries(VIEWERS).map(([who, v]) => [who, canChange(ORDINARY, v)])),
      { creator: true, member: false, admin: true, owner: true },
    );
  });

  test('a managed link: nobody in the app, owners included (only its service account, which never signs in)', () => {
    for (const [who, v] of Object.entries(VIEWERS)) assert.equal(canChange(MANAGED, v), false, who);
    assert.equal(canChange(MANAGED, null), false, 'not even when the viewer couldn’t be loaded');
  });

  test('its tags keep the old rule, managed or not: creator, admin, owner', () => {
    for (const link of [ORDINARY, MANAGED])
      assert.deepEqual(
        Object.fromEntries(Object.entries(VIEWERS).map(([who, v]) => [who, canChangeTags(link, v)])),
        { creator: true, member: false, admin: true, owner: true },
      );
    assert.equal(canChangeTags(MANAGED, null), true, 'without a viewer the control stays on and the API decides');
  });

  test('an older API without `managed_by`: nothing changes', () => {
    const { managed_by, ...older } = ORDINARY;
    for (const v of Object.values(VIEWERS)) assert.equal(canChange(older, v), canChange(ORDINARY, v));
  });

  test('only an owner deletes a managed link past its service account; never an ordinary one', () => {
    assert.deepEqual(
      Object.fromEntries(Object.entries(VIEWERS).map(([who, v]) => [who, canOverrideDelete(MANAGED, v)])),
      { creator: false, member: false, admin: false, owner: true },
    );
    assert.equal(canOverrideDelete(ORDINARY, VIEWERS.owner), false);
    assert.equal(canOverrideDelete(MANAGED, null), false);
  });
});

describe('the lock’s words', () => {
  test('a managed link names its manager, in the API’s words (403 managed_link_protected)', () => {
    assert.equal(managedLockReason(PROPUESTAS), 'This link is managed by Propuestas Griddo. Change or delete it from there.');
    assert.deepEqual(lockFor(MANAGED, 'link'), {
      reason: 'This link is managed by Propuestas Griddo. Change or delete it from there.',
      tooltip: 'Managed by Propuestas Griddo: change it from there',
    });
  });

  test('a manager without a name is still named', () => {
    assert.match(lockFor({ ...MANAGED, managed_by: { id: 'x', display_name: null } }, 'link').reason, /managed by a service account\./);
  });

  test('its tags: the creator-or-admin rule; an ordinary link keeps today’s words', () => {
    assert.equal(lockFor(MANAGED, 'link', 'tags').reason, TAGS_LOCK_REASON);
    assert.equal(TAGS_LOCK_REASON, 'Only its creator, or an admin or owner, can change its tags.');
    assert.equal(lockFor(ORDINARY, 'link').reason, lockReason('link'));
    assert.equal(lockReason('link'), 'Only its creator, or an admin or owner, can change this link.');
  });
});

describe('the editor on a managed link', () => {
  const MASKED = 'https://propuestas.griddo.io/…';
  const values = (over = {}) => ({ original_url: 'https://acme.com/', og_image_url: '', max_visits: '', valid_since: null, valid_until: null, ...over });

  test('opens on its tags alone; an ordinary link on everything', () => {
    assert.equal(editorMode(MANAGED), 'tags');
    assert.equal(editorMode(ORDINARY), 'full');
    assert.equal(editorMode({}), 'full');
  });

  test('tags only: a masked destination isn’t validated, nor anything else', () => {
    assert.deepEqual(fieldProblems(values({ original_url: MASKED }), 'tags'), {});
    assert.deepEqual(fieldProblems(values({ original_url: '', max_visits: 'x' }), 'tags'), {});
  });

  test('everything: a mask is never accepted as a destination, though it parses as one', () => {
    assert.ok(fieldProblems(values({ original_url: MASKED })).original_url);
    assert.deepEqual(fieldProblems(values()), {});
  });

  test('everything: the checks it always had', () => {
    const out = fieldProblems(
      values({ original_url: 'acme', og_image_url: 'nope', max_visits: '0', valid_since: '2026-10-20T10:00:00Z', valid_until: '2026-10-19T10:00:00Z' }),
    );
    assert.deepEqual(Object.keys(out).sort(), ['max_visits', 'og_image_url', 'original_url', 'valid_until']);
  });
});

describe('the override’s reason', () => {
  test('10 to 500 characters, surrounding whitespace ignored', () => {
    assert.equal(REASON_MIN, 10);
    assert.equal(REASON_MAX, 500);
    assert.equal(reasonProblem('Data request'), null);
    assert.equal(reasonProblem('x'.repeat(10)), null);
    assert.equal(reasonProblem('x'.repeat(500)), null);
    assert.equal(reasonProblem(`   ${'x'.repeat(500)}   `), null, 'spaces around don’t count');
  });

  test('empty, short or long: each says what to do', () => {
    assert.equal(reasonProblem('   '), 'Say why you’re deleting it.');
    assert.equal(reasonProblem('too short'), 'Say a little more: at least 10 characters.');
    assert.equal(reasonProblem(`  ${'x'.repeat(9)}  `), 'Say a little more: at least 10 characters.', 'padding doesn’t make it long enough');
    assert.equal(reasonProblem('x'.repeat(501)), 'Keep it to 500 characters; it’s 501.');
  });

  test('the live count counts as the API does', () => {
    assert.equal(reasonCount(''), '0 / 500');
    assert.equal(reasonCount('  leaked token  '), '12 / 500');
  });

  test('the dialog names the manager and the consequence', () => {
    const copy = overrideCopy(PROPUESTAS);
    assert.equal(copy.title, 'Delete a link Propuestas Griddo manages?');
    assert.match(copy.body, /^Propuestas Griddo will keep showing it as active, and whoever has it will reach a dead link\./);
    assert.match(overrideCopy({ id: 'x', display_name: null }).body, /^A service account will keep showing it/);
  });
});
