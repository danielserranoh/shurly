// Campaigns: API actions and card rendering.

import { apiDelete, apiDownload, apiGet, apiPatch, apiPost } from './api';
import { formatDate, prettyUrl } from './format';
import { html, safeUrl, type RawHTML } from './html';
import { icon } from './icons';
import { campaignHref } from './links';
import { tagPill } from './tags';
import type { Campaign, CampaignListResponse, CampaignSummary, CampaignUsersResponse, CreateCampaignRequest, Tag } from './types';

export const listCampaigns = () => apiGet<CampaignListResponse>('/api/v1/campaigns?limit=100');
export const getCampaign = (id: string) => apiGet<Campaign>(`/api/v1/campaigns/${encodeURIComponent(id)}`);
export const createCampaign = (data: CreateCampaignRequest) => apiPost<Campaign>('/api/v1/campaigns', data);
export const deleteCampaign = (id: string) => apiDelete(`/api/v1/campaigns/${encodeURIComponent(id)}`);
export const setCampaignTags = (id: string, tagIds: string[]) =>
  apiPatch<{ campaign_id: string; tags: Tag[] }>(`/api/v1/campaigns/${encodeURIComponent(id)}/tags`, { tag_ids: tagIds });
export const campaignSummary = (id: string) => apiGet<CampaignSummary>(`/api/v1/analytics/campaigns/${encodeURIComponent(id)}/summary`);
export const campaignRecipients = (id: string) => apiGet<CampaignUsersResponse>(`/api/v1/analytics/campaigns/${encodeURIComponent(id)}/users`);

export const exportCampaignLinks = (c: Pick<Campaign, 'id' | 'name'>) =>
  apiDownload(`/api/v1/campaigns/${encodeURIComponent(c.id)}/export`, `${slug(c.name)}-links.csv`);
export const exportCampaignReport = (c: Pick<Campaign, 'id' | 'name'>) =>
  apiDownload(`/api/v1/analytics/campaigns/${encodeURIComponent(c.id)}/users?format=csv`, `${slug(c.name)}-clicks.csv`);

function slug(name: string): string {
  return name.toLowerCase().normalize('NFKD').replace(/[^\w]+/g, '-').replace(/^-|-$/g, '') || 'campaign';
}

/** "firstName · company · region" chips for the personalization columns. */
export function columnChips(columns: string[], max = 4): RawHTML {
  const shown = columns.slice(0, max);
  return html`${shown.map((c) => html`<span class="inline-flex h-6 items-center rounded-md border border-line bg-white px-2 font-mono text-xs text-ink-700">${c}</span>`)}${
    columns.length > max ? html`<span class="inline-flex h-6 items-center px-1 text-xs text-ink-500">+${columns.length - max} more</span>` : ''
  }`;
}

export function renderCampaignCard(c: Campaign): RawHTML {
  const menuId = `campaign-menu-${c.id}`;
  return html`<li class="card card-interactive flex flex-col gap-4 p-5" data-campaign="${c.id}">
    <div class="flex items-start gap-3">
      <span class="grid size-10 shrink-0 place-items-center rounded-xl bg-ink-950 text-brand-400">${icon('megaphone', 'size-5')}</span>
      <div class="min-w-0 flex-1">
        <a href="${campaignHref(c.id)}" class="block truncate font-semibold text-ink-950 hover:underline decoration-ink-300 underline-offset-4">${c.name}</a>
        <p class="mt-0.5 flex min-w-0 items-center gap-1.5 text-[13px] text-ink-500">${icon('corner-down-right', 'size-3.5 shrink-0')}
          <a class="truncate hover:text-ink-800" href="${safeUrl(c.original_url)}" target="_blank" rel="noopener noreferrer">${prettyUrl(c.original_url)}</a></p>
      </div>
      <button type="button" class="btn btn-ghost btn-sm btn-icon -mt-1 -mr-2" popovertarget="${menuId}" aria-label="More actions for ${c.name}">${icon('more')}</button>
      <div id="${menuId}" popover class="menu" data-align="end">
        <a class="menu-item" href="${campaignHref(c.id)}">${icon('chart')}View campaign</a>
        <button type="button" class="menu-item" data-action="export" data-id="${c.id}">${icon('download')}Export links (CSV)</button>
        <div class="menu-sep"></div>
        <button type="button" class="menu-item" data-danger data-action="delete" data-id="${c.id}">${icon('trash')}Delete campaign</button>
      </div>
    </div>

    <dl class="grid grid-cols-3 gap-2 rounded-xl bg-ink-50 px-4 py-3">
      <div><dt class="text-xs text-ink-500">Recipients</dt><dd class="mt-0.5 text-lg font-semibold text-ink-950">${c.url_count}</dd></div>
      <div><dt class="text-xs text-ink-500">Clicks</dt><dd class="mt-0.5 text-lg font-semibold text-ink-950" data-clicks><span class="skeleton inline-block h-5 w-8 align-middle"></span></dd></div>
      <div><dt class="text-xs text-ink-500">Opened</dt><dd class="mt-0.5 text-lg font-semibold text-ink-950" data-ctr><span class="skeleton inline-block h-5 w-10 align-middle"></span></dd></div>
    </dl>
    <div data-meter class="-mt-1"></div>

    <div class="flex flex-wrap items-center gap-1.5">
      <span class="mr-1 text-xs text-ink-500">Personalized with</span>${columnChips(c.csv_columns)}
    </div>
    ${c.tags?.length ? html`<div class="flex flex-wrap gap-1.5">${c.tags.map((t) => tagPill(t))}</div>` : ''}

    <div class="mt-auto flex items-center justify-between border-t border-line pt-3 text-xs text-ink-500">
      <span>Created ${formatDate(c.created_at)}</span>
      <a class="inline-flex items-center gap-1 font-semibold text-ink-900 hover:text-ink-950" href="${campaignHref(c.id)}">View campaign ${icon('arrow-right', 'size-3.5')}</a>
    </div>
  </li>`;
}
