// Links: API actions + client-side rendering shared by the dashboard and details page.

import { apiDelete, apiGet, apiPatch, apiPost, qs } from './api';
import { formatNumber, formatDate, hashIndex, hostname, initials, linkStatus, linkTitle, parseDate, prettyUrl } from './format';
import { html, raw, safeUrl, type RawHTML } from './html';
import { icon } from './icons';
import { tagPill } from './tags';
import { openDialog } from './ui';
import type { CreateLinkRequest, LinkListResponse, LinkMetadata, ShortLink, Tag, UpdateLinkRequest, URLType } from './types';

export const linkHref = (code: string) => `/dashboard/link/?code=${encodeURIComponent(code)}`;
export const campaignHref = (id: string) => `/dashboard/campaign/?id=${encodeURIComponent(id)}`;

/** Display form of a short link: host/code without protocol. */
export function shortDisplay(link: Pick<ShortLink, 'short_url' | 'short_code'>): string {
  return link.short_url ? prettyUrl(link.short_url) : link.short_code;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export interface LinkQuery {
  q?: string;
  types?: URLType[];
  tags?: string[];
  match?: 'any' | 'all';
  skip?: number;
  limit?: number;
}

export function listLinks(query: LinkQuery = {}): Promise<LinkListResponse> {
  return apiGet<LinkListResponse>(
    `/api/v1/urls${qs({
      q: query.q?.trim() || undefined,
      url_type: query.types,
      tags: query.tags?.length ? query.tags.join(',') : undefined,
      tag_filter: query.tags && query.tags.length > 1 ? query.match ?? 'any' : undefined,
      skip: query.skip ?? 0,
      limit: query.limit ?? 20,
    })}`,
  );
}

export const getLink = (code: string) => apiGet<ShortLink>(`/api/v1/urls/${encodeURIComponent(code)}`);

export function createLink(data: CreateLinkRequest): Promise<ShortLink> {
  const { custom_code, ...rest } = data;
  return custom_code
    ? apiPost<ShortLink>('/api/v1/urls/custom', { ...rest, custom_code })
    : apiPost<ShortLink>('/api/v1/urls', rest);
}

export const updateLink = (code: string, data: UpdateLinkRequest) =>
  apiPatch<ShortLink>(`/api/v1/urls/${encodeURIComponent(code)}`, data);

export const setLinkTags = (code: string, tagIds: string[]) =>
  apiPatch<{ short_code: string; tags: Tag[] }>(`/api/v1/urls/${encodeURIComponent(code)}/tags`, { tag_ids: tagIds });

export const bulkTagLinks = (codes: string[], tagIds: string[]) =>
  apiPost<{ updated: number; failed: unknown[] }>('/api/v1/urls/bulk/tags', { short_codes: codes, tag_ids: tagIds });

export const deleteLink = (code: string) => apiDelete(`/api/v1/urls/${encodeURIComponent(code)}`);

export const fetchMetadata = (url: string) => apiPost<LinkMetadata>('/api/v1/urls/fetch-metadata', { url });

/** Show the QR modal (components/app/QrModal.astro) for a link. */
export function openQr(link: Pick<ShortLink, 'short_url' | 'short_code'>): void {
  if (!link.short_url) return;
  window.dispatchEvent(new CustomEvent('shurly:qr', { detail: { url: link.short_url, code: link.short_code } }));
  openDialog(document.getElementById('qr-modal') as HTMLDialogElement | null);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

const TINTS = [
  'bg-orange-100 text-orange-800',
  'bg-sky-100 text-sky-800',
  'bg-violet-100 text-violet-800',
  'bg-emerald-100 text-emerald-800',
  'bg-pink-100 text-pink-800',
  'bg-amber-100 text-amber-800',
];

/** Square thumbnail: the OG image when there is one, otherwise a tinted monogram. */
export function linkThumb(link: Pick<ShortLink, 'og_image_url' | 'original_url'>, size = 'size-11'): RawHTML {
  const host = hostname(link.original_url) || '?';
  const tint = TINTS[hashIndex(host, TINTS.length)];
  const monogram = html`<span class="grid ${size} shrink-0 place-items-center rounded-xl font-display text-lg font-medium ${tint}">${initials(host)}</span>`;
  if (!link.og_image_url) return monogram;
  return html`<span class="relative block ${size} shrink-0 overflow-hidden rounded-xl bg-ink-100 ring-1 ring-ink-200">
    <img src="${safeUrl(link.og_image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" class="size-full object-cover" data-fallback />
  </span><template>${monogram}</template>`;
}

/** Only exceptions get a badge: standard, active, forwarding links stay clean. */
export function linkBadges(link: ShortLink, { withType = true } = {}): RawHTML {
  const out: RawHTML[] = [];
  if (withType && link.url_type === 'custom') out.push(html`<span class="badge badge-outline">${icon('pencil', 'size-3')}Custom</span>`);
  if (withType && link.url_type === 'campaign')
    out.push(
      link.campaign_id
        ? html`<a class="badge badge-info hover:border-sky-400" href="${campaignHref(link.campaign_id)}">${icon('megaphone', 'size-3')}Campaign</a>`
        : html`<span class="badge badge-info">${icon('megaphone', 'size-3')}Campaign</span>`,
    );
  const status = linkStatus(link);
  if (status === 'scheduled') out.push(html`<span class="badge badge-info" title="Goes live ${formatDate(link.valid_since)}">${icon('calendar-clock', 'size-3')}Scheduled</span>`);
  if (status === 'expired') out.push(html`<span class="badge badge-danger" title="Expired ${formatDate(link.valid_until)}">${icon('ban', 'size-3')}Expired</span>`);
  if (status === 'capped') out.push(html`<span class="badge badge-warn">${icon('ban', 'size-3')}Click limit reached</span>`);
  if (status === 'active' && link.valid_until) {
    const until = parseDate(link.valid_until);
    const days = until ? (until.getTime() - Date.now()) / 86_400_000 : Infinity;
    if (days < 7) out.push(html`<span class="badge badge-warn" title="Expires ${formatDate(link.valid_until)}">${icon('timer', 'size-3')}Expires soon</span>`);
  }
  if (!link.forward_parameters && link.url_type !== 'campaign')
    out.push(html`<span class="badge badge-neutral" title="Query parameters on the short link are not passed to the destination">${icon('ban', 'size-3')}No param forwarding</span>`);
  return html`${out}`;
}

export interface CardOptions {
  selected?: boolean;
  fresh?: boolean;
}

export function renderLinkCard(link: ShortLink, opts: CardOptions = {}): RawHTML {
  const title = linkTitle(link);
  const short = shortDisplay(link);
  const menuId = `menu-${link.id}`;
  const canDelete = link.url_type !== 'campaign';
  const shortUrl = link.short_url ?? '';

  return html`<li class="card card-interactive group relative flex gap-3 p-4 sm:gap-4 sm:p-5 ${opts.fresh ? 'animate-flash' : ''}" data-link="${link.short_code}">
    <label class="absolute top-5 -left-3 hidden size-6 place-items-center rounded-md bg-white shadow-sm ring-1 ring-ink-200 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 sm:grid ${opts.selected ? 'opacity-100' : 'opacity-0 [.selecting_&]:opacity-100'}">
      <input type="checkbox" class="checkbox" data-select="${link.short_code}" ${opts.selected ? raw('checked') : ''} aria-label="Select ${title}" />
    </label>

    <a href="${linkHref(link.short_code)}" class="shrink-0 rounded-xl" tabindex="-1" aria-hidden="true">${linkThumb(link)}</a>

    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
        <a href="${linkHref(link.short_code)}" class="min-w-0 truncate font-semibold text-ink-950 hover:underline decoration-ink-300 underline-offset-4">${title}</a>
        ${linkBadges(link)}
      </div>
      <div class="mt-1 flex min-w-0 items-center gap-1.5">
        <a href="${safeUrl(shortUrl)}" target="_blank" rel="noopener" class="shortlink truncate text-[13.5px] text-ink-950 hover:text-brand-800 hover:underline decoration-brand-400 decoration-2 underline-offset-4">${short}</a>
      </div>
      <p class="mt-1 flex min-w-0 items-center gap-1.5 text-[13px] text-ink-500">
        ${icon('corner-down-right', 'size-3.5 shrink-0')}
        <a href="${safeUrl(link.original_url)}" target="_blank" rel="noopener noreferrer" class="truncate hover:text-ink-800" title="${link.original_url}">${prettyUrl(link.original_url)}</a>
      </p>
      ${link.tags.length ? html`<div class="mt-2.5 flex flex-wrap gap-1.5">${link.tags.map((t) => tagPill(t, { href: `/dashboard/?tags=${t.id}` }))}</div>` : ''}
      <p class="mt-3 flex items-center gap-3 text-[13px] text-ink-500 sm:hidden">
        <span><b class="font-semibold text-ink-900">${formatNumber(link.click_count)}</b> ${link.click_count === 1 ? 'click' : 'clicks'}</span>
        <span aria-hidden="true">·</span>
        <span>${link.last_click_at ? html`Last <time data-relative datetime="${link.last_click_at}"></time>` : 'No clicks yet'}</span>
      </p>
    </div>

    <div class="hidden w-28 shrink-0 flex-col items-end justify-center text-right sm:flex">
      <p class="text-2xl leading-none font-semibold tracking-tight text-ink-950">${formatNumber(link.click_count)}</p>
      <p class="mt-1 text-xs text-ink-500">${link.click_count === 1 ? 'click' : 'clicks'}</p>
      <p class="mt-2 text-xs text-ink-500">${link.last_click_at ? html`<time data-relative datetime="${link.last_click_at}"></time>` : 'No clicks yet'}</p>
    </div>

    <div class="flex shrink-0 flex-col items-end gap-2 sm:flex-row sm:items-center">
      <button type="button" class="btn btn-secondary btn-sm" data-copy="${shortUrl}" aria-label="Copy ${short}">
        <span data-copy-icon>${icon('copy')}</span><span data-copy-label class="hidden md:inline">Copy</span>
      </button>
      <button type="button" class="btn btn-ghost btn-sm btn-icon" popovertarget="${menuId}" aria-label="More actions for ${title}">${icon('more')}</button>
      <div id="${menuId}" popover class="menu" data-align="end">
        <a class="menu-item" href="${linkHref(link.short_code)}">${icon('chart')}View details</a>
        ${canDelete
          ? html`<button type="button" class="menu-item" data-action="edit" data-code="${link.short_code}">${icon('pencil')}Edit</button>`
          : html`<a class="menu-item" href="${link.campaign_id ? campaignHref(link.campaign_id) : '/dashboard/campaigns/'}">${icon('megaphone')}Open campaign</a>`}
        <button type="button" class="menu-item" data-action="qr" data-code="${link.short_code}">${icon('qr')}QR code</button>
        <a class="menu-item" href="${safeUrl(shortUrl)}" target="_blank" rel="noopener">${icon('external-link')}Open short link</a>
        <div class="menu-sep"></div>
        ${canDelete
          ? html`<button type="button" class="menu-item" data-danger data-action="delete" data-code="${link.short_code}">${icon('trash')}Delete</button>`
          : html`<span class="menu-item" aria-disabled="true" title="Campaign links are deleted together with their campaign">${icon('lock')}Delete via campaign</span>`}
      </div>
    </div>
  </li>`;
}


export function renderLinkSkeleton(count = 4): RawHTML {
  return html`${Array.from({ length: count }, () => html`<li class="card flex gap-4 p-5" aria-hidden="true">
      <span class="skeleton size-11 shrink-0 rounded-xl"></span>
      <div class="flex-1 space-y-2.5 py-0.5">
        <span class="skeleton block h-4 w-2/5"></span>
        <span class="skeleton block h-3.5 w-1/4"></span>
        <span class="skeleton block h-3 w-3/5"></span>
      </div>
      <div class="hidden w-24 space-y-2 sm:block"><span class="skeleton ml-auto block h-6 w-12"></span><span class="skeleton ml-auto block h-3 w-16"></span></div>
    </li>`)}`;
}
