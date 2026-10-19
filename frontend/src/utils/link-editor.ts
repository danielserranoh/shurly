// Behaviour for components/app/EditLinkModal.astro, and (Phase 10.3) components/app/OverrideDeleteModal.astro.

import { apiPost } from './api';
import { applyApiError, clearErrors, revealFirstError, setFieldError } from './forms';
import { fromLocalInput, isValidHttpUrl, normalizeUrlInput, toLocalInput } from './format';
import { linkApi, type LinkAddress } from './link-address';
import { isMaskedDestination, setLinkTags, updateLink } from './links';
import { serviceName } from './people';
import { mountTagInput, type TagInputHandle } from './tag-input';
import { closeDialog, openDialog, setLoading, toast } from './ui';
import type { ShortLink, UpdateLinkRequest } from './types';

// ---------------------------------------------------------------------------
// Pure rules (tests/managed-link-page.test.mjs)
// ---------------------------------------------------------------------------

/**
 * Phase 10.3 — what the editor changes: everything, or only the tags of a link a service account manages
 * (`PATCH …/tags`, the one change people make to it). Its other fields, and a masked destination, aren't touched.
 */
export type EditorMode = 'full' | 'tags';
export const editorMode = (link: Pick<ShortLink, 'managed_by'>): EditorMode => (link.managed_by ? 'tags' : 'full');

/** The editor's fields as typed, for `fieldProblems`. */
export interface EditorValues {
  /** The destination, normalised (`normalizeUrlInput`). */
  original_url: string;
  og_image_url: string;
  max_visits: string;
  /** ISO, from `fromLocalInput`; null when empty. */
  valid_since: string | null;
  valid_until: string | null;
}

/**
 * The problem with each field, by name; empty when there's none. In `tags` mode there's nothing to check: the
 * fields aren't sent, and a managed link's destination may be masked (`https://host/…`), which isn't a link.
 */
export function fieldProblems(values: EditorValues, mode: EditorMode = 'full'): Partial<Record<keyof EditorValues, string>> {
  if (mode === 'tags') return {};
  const out: Partial<Record<keyof EditorValues, string>> = {};
  // A mask is never saved as a destination, though it parses as one.
  if (!isValidHttpUrl(values.original_url) || isMaskedDestination(values.original_url))
    out.original_url = 'Enter a full link starting with http:// or https://';
  if (values.og_image_url && !isValidHttpUrl(values.og_image_url)) out.og_image_url = 'Use a full image link starting with https://';
  if (values.max_visits && (!/^\d+$/.test(values.max_visits) || Number(values.max_visits) < 1))
    out.max_visits = 'Use a whole number of 1 or more, or leave it empty.';
  if (values.valid_since && values.valid_until && new Date(values.valid_until) <= new Date(values.valid_since))
    out.valid_until = 'The expiry needs to be after the go-live date.';
  return out;
}

/** Phase 10.3 — the override's reason, as the API counts it (surrounding whitespace ignored): 10 to 500 characters. */
export const REASON_MIN = 10;
export const REASON_MAX = 500;

export const reasonLength = (raw: string) => raw.trim().length;

/** What's wrong with an override's reason, or null. Same bounds as the API's `URLOverrideDelete`. */
export function reasonProblem(raw: string): string | null {
  const n = reasonLength(raw);
  if (n === 0) return 'Say why you’re deleting it.';
  if (n < REASON_MIN) return `Say a little more: at least ${REASON_MIN} characters.`;
  if (n > REASON_MAX) return `Keep it to ${REASON_MAX} characters; it’s ${n}.`;
  return null;
}

/** The live count under the reason. */
export const reasonCount = (raw: string) => `${reasonLength(raw)} / ${REASON_MAX}`;

// ---------------------------------------------------------------------------
// The editor
// ---------------------------------------------------------------------------

type Saved = (link: ShortLink) => void;

let initialized = false;
let current: ShortLink | null = null;
let onSaved: Saved = () => {};
let tagInput: TagInputHandle;

function els() {
  const dialog = document.getElementById('edit-link') as HTMLDialogElement;
  const form = document.getElementById('edit-link-form') as HTMLFormElement;
  const field = <T extends HTMLElement = HTMLInputElement>(name: string) => form.elements.namedItem(name) as unknown as T;
  return { dialog, form, field };
}

// Phase 8.7 — each preview field is an override of the page's own, which shows as its placeholder.
const PAGE_FIELDS = { og_title: 'page_og_title', og_description: 'page_og_description', og_image_url: 'page_og_image_url' } as const;
type OverrideField = keyof typeof PAGE_FIELDS;
const OVERRIDE_FIELDS = Object.keys(PAGE_FIELDS) as OverrideField[];

/** What an empty preview field falls back to: the page's own, unless the destination is being changed. */
function pageValue(name: OverrideField): string {
  const { field } = els();
  if (!current || normalizeUrlInput(field('original_url').value) !== current.original_url) return '';
  return current[PAGE_FIELDS[name]]?.trim() ?? '';
}

function summaries() {
  const { form, field } = els();
  const moved = Boolean(current) && normalizeUrlInput(field('original_url').value) !== current!.original_url;
  let og = 0;
  for (const name of OVERRIDE_FIELDS) {
    const input = field<HTMLInputElement>(name);
    const typed = Boolean(input.value.trim());
    if (typed) og += 1;
    const page = pageValue(name);
    input.placeholder = page || (name === 'og_image_url' ? 'https://…/image.jpg' : '');
    form.querySelector(`[data-og-source-for="${name}"]`)!.textContent = typed
      ? '· yours'
      : moved
        ? '· the new page’s, read when you save'
        : page
          ? '· the page’s'
          : '· the page has none';
  }
  form.querySelector('[data-og-summary]')!.textContent = og ? '· Custom' : '· The page’s';
  const adv: string[] = [];
  if (field<HTMLInputElement>('valid_since').value) adv.push('scheduled');
  if (field<HTMLInputElement>('valid_until').value) adv.push('expires');
  if (field<HTMLInputElement>('max_visits').value) adv.push('click limit');
  form.querySelector('[data-advanced-summary]')!.textContent = adv.length ? `· ${adv.join(', ')}` : '';
}

function init() {
  if (initialized) return;
  initialized = true;
  const { dialog, form, field } = els();
  tagInput = mountTagInput(document.getElementById('edit-tags')!);
  form.addEventListener('input', (e) => {
    const t = e.target as HTMLInputElement;
    if (t.name) setFieldError(form, t.name, null);
    summaries();
  });

  // Phase 8.7 — back to the page's own preview: the overrides go, and saving clears them.
  form.querySelector<HTMLButtonElement>('[data-reset-og]')!.addEventListener('click', () => {
    for (const name of OVERRIDE_FIELDS) {
      field<HTMLInputElement>(name).value = '';
      setFieldError(form, name, null);
    }
    summaries();
    field('og_title').focus();
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!current) return;
    clearErrors(form);
    const link = current;
    const mode = editorMode(link);
    const save = dialog.querySelector<HTMLButtonElement>('[data-save]')!;

    const dest = normalizeUrlInput(field('original_url').value);
    const ogImage = field('og_image_url').value.trim();
    const maxRaw = field('max_visits').value.trim();
    const since = fromLocalInput(field('valid_since').value);
    const until = fromLocalInput(field('valid_until').value);

    const problems = Object.entries(fieldProblems({ original_url: dest, og_image_url: ogImage, max_visits: maxRaw, valid_since: since, valid_until: until }, mode));
    if (problems.length) {
      for (const [name, message] of problems) setFieldError(form, name, message);
      revealFirstError(form);
      return;
    }

    const next: UpdateLinkRequest = {
      title: field('title').value.trim() || null,
      original_url: dest,
      forward_parameters: field('forward_parameters').checked,
      og_title: field('og_title').value.trim() || null,
      og_description: field<HTMLTextAreaElement>('og_description').value.trim() || null,
      og_image_url: ogImage || null,
      valid_since: since,
      valid_until: until,
      max_visits: maxRaw ? Number(maxRaw) : null,
      crawlable: field('crawlable').checked,
    };
    // Only send what changed; comparing via the same normalisation used to fill the form.
    const before: UpdateLinkRequest = {
      title: link.title,
      original_url: link.original_url,
      forward_parameters: link.forward_parameters,
      og_title: link.og_title,
      og_description: link.og_description,
      og_image_url: link.og_image_url,
      valid_since: fromLocalInput(toLocalInput(link.valid_since)),
      valid_until: fromLocalInput(toLocalInput(link.valid_until)),
      max_visits: link.max_visits,
      crawlable: link.crawlable,
    };
    // Phase 10.3 — on a managed link only the tags are sent: its other fields stay its service account's.
    const patch: UpdateLinkRequest = {};
    if (mode === 'full')
      for (const key of Object.keys(next) as (keyof UpdateLinkRequest)[]) {
        if ((next[key] ?? null) !== (before[key] ?? null)) (patch as Record<string, unknown>)[key] = next[key];
      }
    const tagIds = tagInput.getIds();
    const tagsChanged = tagIds.slice().sort().join() !== link.tags.map((t) => t.id).sort().join();

    if (!Object.keys(patch).length && !tagsChanged) {
      closeDialog(dialog);
      return;
    }

    setLoading(save, true, 'Saving…');
    try {
      let updated = link;
      if (Object.keys(patch).length) updated = await updateLink(link, patch);
      if (tagsChanged) {
        const res = await setLinkTags(link, tagIds);
        updated = { ...updated, tags: res.tags };
      }
      current = updated;
      closeDialog(dialog);
      toast(mode === 'tags' ? 'Tags saved' : 'Changes saved', 'success');
      onSaved(updated);
    } catch (err) {
      applyApiError(form, err);
    } finally {
      setLoading(save, false);
    }
  });
}

/**
 * Open the editor for a link; `saved` receives the updated link. Phase 10.3: a link a service account manages
 * opens on its tags alone (`editorMode`), saved through `PATCH …/tags`.
 */
export function openLinkEditor(link: ShortLink, saved: Saved, focus?: 'og'): void {
  init();
  current = link;
  onSaved = saved;
  const { dialog, form, field } = els();
  clearErrors(form);
  const tagsOnly = editorMode(link) === 'tags';
  form.querySelectorAll<HTMLElement>('[data-full-only]').forEach((el) => (el.hidden = tagsOnly));
  form.querySelector<HTMLElement>('[data-tags-only]')!.hidden = !tagsOnly;
  form.querySelector('[data-tags-only-text]')!.textContent = link.managed_by
    ? `Managed by ${serviceName(link.managed_by)}: everything else about this link changes there.`
    : '';
  document.getElementById('edit-link-title')!.textContent = tagsOnly ? 'Edit tags' : 'Edit link';
  const description = document.querySelector('#edit-link-title + p');
  if (description)
    description.textContent = tagsOnly ? 'Tags sort and filter your links. The link itself stays as it is.' : 'The short link stays the same — only what it does changes.';
  dialog.querySelector('[data-save]')!.textContent = tagsOnly ? 'Save tags' : 'Save changes';
  field('title').value = link.title ?? '';
  field('original_url').value = link.original_url;
  field('forward_parameters').checked = link.forward_parameters;
  field('og_title').value = link.og_title ?? '';
  field<HTMLTextAreaElement>('og_description').value = link.og_description ?? '';
  field('og_image_url').value = link.og_image_url ?? '';
  field('valid_since').value = toLocalInput(link.valid_since);
  field('valid_until').value = toLocalInput(link.valid_until);
  field('max_visits').value = link.max_visits ? String(link.max_visits) : '';
  field('crawlable').checked = link.crawlable;
  tagInput.setTags(link.tags);
  const og = form.querySelector<HTMLDetailsElement>('[data-og-section]')!;
  const adv = form.querySelector<HTMLDetailsElement>('[data-advanced-section]')!;
  og.open = focus === 'og';
  adv.open = Boolean(link.valid_since || link.valid_until || link.max_visits);
  summaries();
  openDialog(dialog);
  if (tagsOnly) document.querySelector<HTMLInputElement>('#edit-tags input')?.focus();
  else (focus === 'og' ? field('og_title') : field('title')).focus();
}

// ---------------------------------------------------------------------------
// Phase 10.3 — an owner deletes a managed link past its service account (components/app/OverrideDeleteModal.astro)
// ---------------------------------------------------------------------------

/** `POST …/override-delete`: owners only, on a managed link; the reason goes to the service account's audit. */
export const overrideDeleteLink = (link: LinkAddress, reason: string) => apiPost<void>(linkApi(link, '/override-delete'), { reason: reason.trim() });

/** The override dialog's title and body, naming the link's manager. */
export function overrideCopy(manager: NonNullable<ShortLink['managed_by']>): { title: string; body: string } {
  const name = serviceName(manager);
  const Name = name.charAt(0).toUpperCase() + name.slice(1);
  return {
    title: `Delete a link ${name} manages?`,
    body: `${Name} will keep showing it as active, and whoever has it will reach a dead link. Use this only for an emergency: a data-protection request, a leaked token, or a link left behind by a failure.`,
  };
}

let overrideReady = false;
let overriding: ShortLink | null = null;
let onOverridden: () => void = () => {};

function overrideEls() {
  const dialog = document.getElementById('override-delete') as HTMLDialogElement;
  const form = document.getElementById('override-delete-form') as HTMLFormElement;
  const reason = form.elements.namedItem('reason') as HTMLTextAreaElement;
  const count = form.querySelector<HTMLElement>('[data-reason-count]')!;
  return { dialog, form, reason, count };
}

function paintCount() {
  const { reason, count } = overrideEls();
  count.textContent = reasonCount(reason.value);
  count.classList.toggle('text-red-700', reasonLength(reason.value) > REASON_MAX);
}

function initOverride() {
  if (overrideReady) return;
  overrideReady = true;
  const { dialog, form, reason } = overrideEls();
  reason.addEventListener('input', () => {
    paintCount();
    // Once a problem shows, it follows the typing: gone as soon as the reason is good.
    if (reason.getAttribute('aria-invalid') === 'true') setFieldError(form, 'reason', reasonProblem(reason.value));
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!overriding) return;
    clearErrors(form);
    const problem = reasonProblem(reason.value);
    if (problem) {
      setFieldError(form, 'reason', problem);
      reason.focus();
      return;
    }
    const confirm = dialog.querySelector<HTMLButtonElement>('[data-confirm-override]')!;
    setLoading(confirm, true, 'Deleting…');
    try {
      await overrideDeleteLink(overriding, reason.value);
      await closeDialog(dialog);
      onOverridden();
    } catch (err) {
      applyApiError(form, err); // a 422 on the reason goes under it; anything else in the form's alert
    } finally {
      setLoading(confirm, false);
    }
  });
}

/** Open the override for a managed link; `deleted` runs once it's gone. Only for owners (`canOverrideDelete`). */
export function openOverrideDelete(link: ShortLink, deleted: () => void): void {
  if (!link.managed_by) return;
  initOverride();
  overriding = link;
  onOverridden = deleted;
  const { dialog, form, reason } = overrideEls();
  const copy = overrideCopy(link.managed_by);
  document.getElementById('override-delete-title')!.textContent = copy.title;
  form.querySelector('[data-override-body]')!.textContent = copy.body;
  form.reset();
  clearErrors(form);
  paintCount();
  openDialog(dialog);
  reason.focus();
}
