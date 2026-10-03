// Behaviour for components/app/EditLinkModal.astro.

import { applyApiError, clearErrors, revealFirstError, setFieldError } from './forms';
import { fromLocalInput, isValidHttpUrl, normalizeUrlInput, toLocalInput } from './format';
import { setLinkTags, updateLink } from './links';
import { mountTagInput, type TagInputHandle } from './tag-input';
import { closeDialog, openDialog, setLoading, toast } from './ui';
import type { ShortLink, UpdateLinkRequest } from './types';

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
    const save = dialog.querySelector<HTMLButtonElement>('[data-save]')!;

    const dest = normalizeUrlInput(field('original_url').value);
    const ogImage = field('og_image_url').value.trim();
    const maxRaw = field('max_visits').value.trim();
    const since = fromLocalInput(field('valid_since').value);
    const until = fromLocalInput(field('valid_until').value);

    let ok = true;
    if (!isValidHttpUrl(dest)) {
      setFieldError(form, 'original_url', 'Enter a full link starting with http:// or https://');
      ok = false;
    }
    if (ogImage && !isValidHttpUrl(ogImage)) {
      setFieldError(form, 'og_image_url', 'Use a full image link starting with https://');
      ok = false;
    }
    if (maxRaw && (!/^\d+$/.test(maxRaw) || Number(maxRaw) < 1)) {
      setFieldError(form, 'max_visits', 'Use a whole number of 1 or more, or leave it empty.');
      ok = false;
    }
    if (since && until && new Date(until) <= new Date(since)) {
      setFieldError(form, 'valid_until', 'The expiry needs to be after the go-live date.');
      ok = false;
    }
    if (!ok) {
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
    const patch: UpdateLinkRequest = {};
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
      toast('Changes saved', 'success');
      onSaved(updated);
    } catch (err) {
      applyApiError(form, err);
    } finally {
      setLoading(save, false);
    }
  });
}

/** Open the editor for a link; `saved` receives the updated link. */
export function openLinkEditor(link: ShortLink, saved: Saved, focus?: 'og'): void {
  init();
  current = link;
  onSaved = saved;
  const { dialog, form, field } = els();
  clearErrors(form);
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
  (focus === 'og' ? field('og_title') : field('title')).focus();
}
