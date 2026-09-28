// Who's looking (Phase 3.14): the signed-in account and its role in the organization.
// Lists and record pages use it to show who created each link or campaign, and to lock
// the controls the viewer can't use. The API still decides: a locked control is a hint,
// and a 403 that gets through is shown like any other error.

import { ApiError, apiGet } from './api';
import { html, type RawHTML } from './html';
import { icon } from './icons';
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

/** Fetch /auth/me again, e.g. after the password was set or removed. */
export function refreshMe(): Promise<User> {
  me = null;
  return getMe();
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
}

export function isCreator(item: Owned, viewer: Viewer | null): boolean {
  return Boolean(viewer && item.created_by_email && item.created_by_email.toLowerCase() === viewer.email.toLowerCase());
}

/**
 * The API's rule (server/utils/access.py): the creator changes their own, and admins and
 * owners change the organization's. Someone else's personal item never reaches the viewer.
 */
export function canChange(item: Owned, viewer: Viewer | null): boolean {
  if (!viewer || isCreator(item, viewer)) return true;
  return item.visibility === 'organization' && (viewer.role === 'admin' || viewer.role === 'owner');
}

/** "you", or the creator's email; null when the API didn't say. */
export function creatorName(item: Owned, viewer: Viewer | null): string | null {
  if (!item.created_by_email) return null;
  return isCreator(item, viewer) ? 'you' : item.created_by_email;
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

const LOCK_TOOLTIP = 'Only its creator or an admin can change it';

/** Same words as the API's 403. */
export const lockReason = (noun: Noun) => `Only its creator, or an admin or owner, can change this ${noun}.`;

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
 */
export function lockControl(el: HTMLElement | null, noun: Noun, align: 'center' | 'start' | 'end' = 'end'): void {
  if (!el) return;
  el.setAttribute('aria-disabled', 'true');
  el.dataset.locked = lockReason(noun);
  if (el.classList.contains('menu-item')) {
    el.title = LOCK_TOOLTIP;
  } else {
    el.dataset.tooltip = LOCK_TOOLTIP;
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
