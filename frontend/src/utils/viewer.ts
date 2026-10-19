// Who's looking (Phase 3.14): the signed-in account and its role in the organization.
// Lists and record pages use it to show who created each link or campaign, and to lock
// the controls the viewer can't use. The API still decides: a locked control is a hint,
// and a 403 that gets through is shown like any other error.

import { ApiError, apiGet } from './api';
import { html, setHTML, type RawHTML } from './html';
import { icon } from './icons';
import { createdBy, isServiceEmail, personName, serviceName, type ServiceAccountRef } from './people';
import { toast } from './ui';
import type { Organization, OrgRole, User, Visibility } from './types';

let me: Promise<User> | null = null;
let organization: Promise<Organization | null> | null = null;

/** GET /api/v1/auth/me, fetched once per page. */
export function getMe(): Promise<User> {
  me ??= apiGet<User>('/api/v1/auth/me').catch((err) => {
    me = null; // let a later call try again
    throw err;
  });
  return me;
}

/**
 * Fetch /auth/me again, e.g. after the password or the profile changed. The app header
 * repaints from it (`shurly:me`).
 */
export async function refreshMe(): Promise<User> {
  me = null;
  const user = await getMe();
  window.dispatchEvent(new CustomEvent<User>('shurly:me', { detail: user }));
  return user;
}

/**
 * Under a chart of days: when the viewer has no time zone, say the days are in UTC and where
 * to set one. The API counts days in the profile's zone (server/utils/local_days.py).
 */
export async function showDaysZoneHint(el: HTMLElement | null): Promise<void> {
  if (!el) return;
  const me = await getMe().catch(() => null);
  const inUtc = me !== null && !me.profile?.timezone;
  if (inUtc) setHTML(el, html`Days are in UTC. Set your time zone in <a class="link" href="/dashboard/settings/#account">Settings → Account</a>.`);
  el.hidden = !inUtc;
}

/** The letter in the avatar circle: the first name's, or the email's without one. */
export function initialOf(email: string, firstName?: string | null): string {
  const [first] = [...(firstName?.trim() || email)];
  return (first ?? '?').toUpperCase();
}

/** The viewer's organization, or null when they don't belong to one (a 404). Fetched once per page. */
export function getMyOrganization(): Promise<Organization | null> {
  organization ??= apiGet<Organization>('/api/v1/organization').catch((err) => {
    if (err instanceof ApiError && err.status === 404) return null;
    organization = null;
    throw err;
  });
  return organization;
}

/** Drop the cached organization, e.g. after the viewer's own role changed. */
export function forgetOrganization(): void {
  organization = null;
}

/**
 * The organization changed (its logo, 3.14.4), as `org`: kept as this page's, and the app header
 * repaints from it (`shurly:organization`).
 */
export function organizationChanged(org: Organization): void {
  organization = Promise.resolve(org);
  window.dispatchEvent(new CustomEvent<Organization>('shurly:organization', { detail: org }));
}

/**
 * Run `fn` after the API refused a change (a 403): the role the page knew was out of date,
 * so the cached organization goes and the page can check again what the viewer may change.
 */
export function onForbidden(fn: () => void): void {
  window.addEventListener('shurly:forbidden', () => {
    forgetOrganization();
    fn();
  });
}

export interface Viewer {
  email: string;
  organization: Organization | null;
  role: OrgRole | null;
}

/** Null when it can't be loaded: then every control stays on and the API decides. */
export async function getViewer(): Promise<Viewer | null> {
  try {
    const [user, org] = await Promise.all([getMe(), getMyOrganization()]);
    return { email: user.email, organization: org, role: org?.role ?? null };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Links and campaigns: whose they are, and who may change them
// ---------------------------------------------------------------------------

interface Owned {
  visibility: Visibility;
  created_by_email: string | null;
  /** Phase 3.12: the creator's name, where the response carries it (campaigns; links later). */
  created_by_first_name?: string | null;
  created_by_last_name?: string | null;
  /** Phase 10.1: the service account that made it (links only); null when a person did. */
  via_service_account?: ServiceAccountRef | null;
  /** Phase 10.3: the service account managing it (links only); null or absent when none does. */
  managed_by?: ServiceAccountRef | null;
}

export function isCreator(item: Owned, viewer: Viewer | null): boolean {
  return Boolean(viewer && item.created_by_email && item.created_by_email.toLowerCase() === viewer.email.toLowerCase());
}

/**
 * The API's rule (server/utils/access.py): the creator changes their own, and admins and
 * owners change the organization's. Someone else's personal item never reaches the viewer.
 * Phase 10.3: nobody in the app changes a link a service account manages: only that account does,
 * and it never signs in. Its tags are the exception (`canChangeTags`).
 */
export function canChange(item: Owned, viewer: Viewer | null): boolean {
  if (item.managed_by) return false;
  return canChangeTags(item, viewer);
}

/**
 * Phase 10.3 — may change its tags: the rule from before managed links, for every link (the API's
 * `can_change_tags`). The creator, and the organization's admins and owners.
 */
export function canChangeTags(item: Owned, viewer: Viewer | null): boolean {
  if (!viewer || isCreator(item, viewer)) return true;
  return item.visibility === 'organization' && (viewer.role === 'admin' || viewer.role === 'owner');
}

/**
 * Phase 10.3 — may delete a managed link past its service account (`POST …/override-delete`): an owner of the
 * organization it belongs to, saying why. Never for a link no service account manages.
 */
export function canOverrideDelete(item: Owned, viewer: Viewer | null): boolean {
  return Boolean(item.managed_by) && item.visibility === 'organization' && viewer?.role === 'owner';
}

/**
 * "you", the creator's name, or their email without one; null when the API didn't say. Phase 10.1:
 * "… via Propuestas Griddo" when a service account made it for them, or the service's name alone.
 */
export function creatorName(item: Owned, viewer: Viewer | null): string | null {
  if (!item.created_by_email) return null;
  const who = isCreator(item, viewer)
    ? 'you'
    : personName({ email: item.created_by_email, first_name: item.created_by_first_name, last_name: item.created_by_last_name });
  return createdBy(who, item.created_by_email, item.via_service_account);
}

/** The creator's email when `creatorName` shows their name instead: for a tooltip. Never a service's placeholder. */
export function creatorEmailBehindName(item: Owned, viewer: Viewer | null): string | null {
  if (!item.created_by_email || isServiceEmail(item.created_by_email) || isCreator(item, viewer)) return null;
  const name = personName({ email: item.created_by_email, first_name: item.created_by_first_name, last_name: item.created_by_last_name });
  return name !== item.created_by_email ? item.created_by_email : null;
}

/** What the create form's "Personal" switch (components/app/VisibilityToggle.astro) asks for. */
export function visibilityOf(root: ParentNode): Visibility {
  return root.querySelector<HTMLInputElement>('[data-visibility] input[name="personal"]')?.checked ? 'personal' : 'organization';
}

/** Only personal items get a badge: the organization's are the default. */
export function personalBadge(item: Owned): RawHTML | '' {
  return item.visibility === 'personal'
    ? html`<span class="badge badge-outline" data-tooltip="Only you can see it">${icon('lock', 'size-3')}Personal</span>`
    : '';
}

// ---------------------------------------------------------------------------
// Locked controls
// ---------------------------------------------------------------------------

type Noun = 'link' | 'campaign';

/** Who may change an organization's link or campaign, in the API's words (server/utils/access.py). */
const WHO_CHANGES = 'Only its creator, or an admin or owner,';

/** On hover or focus: the rule, shorter. */
const LOCK_TOOLTIP = `${WHO_CHANGES} can change it`;

/** Same words as the API's 403. */
export const lockReason = (noun: Noun) => `${WHO_CHANGES} can change this ${noun}.`;

/** Phase 10.3 — a managed link's tags: the people who could change the whole link before. */
export const TAGS_LOCK_REASON = `${WHO_CHANGES} can change its tags.`;
const TAGS_LOCK_TOOLTIP = `${WHO_CHANGES} can change its tags`;

/** Phase 10.3 — why a managed link can't be changed here: the API's 403 `managed_link_protected`, in its words. */
export const managedLockReason = (manager: ServiceAccountRef) =>
  `This link is managed by ${serviceName(manager)}. Change or delete it from there.`;
const managedLockTooltip = (manager: ServiceAccountRef) => `Managed by ${serviceName(manager)}: change it from there`;

/** What a locked control says: on click (`reason`) and on hover (`tooltip`). */
export interface Lock {
  reason: string;
  tooltip: string;
}

/**
 * Why the viewer can't use a control that changes `item`, in the API's words: on a managed link (Phase 10.3), its
 * manager's name; otherwise the creator-or-admin rule. `tags` for the control that changes only its tags.
 */
export function lockFor(item: Owned, noun: Noun, what: 'change' | 'tags' = 'change'): Lock {
  if (what === 'tags') return { reason: TAGS_LOCK_REASON, tooltip: TAGS_LOCK_TOOLTIP };
  if (item.managed_by) return { reason: managedLockReason(item.managed_by), tooltip: managedLockTooltip(item.managed_by) };
  return { reason: lockReason(noun), tooltip: LOCK_TOOLTIP };
}

/**
 * Attributes that lock a menu item rendered with `html` (see `lockControl`). Popover menus
 * clip CSS tooltips (`overflow: auto`), so menu items say why in a native `title`.
 */
export function lockedMenuAttrs(noun: Noun): RawHTML {
  return html`aria-disabled="true" data-locked="${lockReason(noun)}" title="${LOCK_TOOLTIP}"`;
}

/**
 * Lock a control the viewer can't use. It stays focusable and dims (`aria-disabled`),
 * says why on hover or focus, and a click explains instead of acting (`installLockedControls`).
 * `align` places the tooltip of a button; menu items get a `title` (see `lockedMenuAttrs`).
 * `lock` words it otherwise (`lockFor`: a managed link names its manager); the noun's rule by default.
 */
export function lockControl(el: HTMLElement | null, noun: Noun, align: 'center' | 'start' | 'end' = 'end', lock?: Lock): void {
  if (!el) return;
  const { reason, tooltip } = lock ?? { reason: lockReason(noun), tooltip: LOCK_TOOLTIP };
  el.setAttribute('aria-disabled', 'true');
  el.dataset.locked = reason;
  if (el.classList.contains('menu-item')) {
    el.title = tooltip;
  } else {
    el.dataset.tooltip = tooltip;
    if (align !== 'center') el.dataset.tooltipAlign = align;
    else delete el.dataset.tooltipAlign;
  }
}

let lockedInstalled = false;

/** Once per page: a click on a locked control says why, instead of reaching its handler. */
export function installLockedControls(): void {
  if (lockedInstalled) return;
  lockedInstalled = true;
  document.addEventListener(
    'click',
    (e) => {
      const el = (e.target as HTMLElement).closest<HTMLElement>('[data-locked]');
      if (!el) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      el.closest<HTMLElement>('[popover]')?.hidePopover();
      toast(el.dataset.locked!, 'info');
    },
    true,
  );
}
