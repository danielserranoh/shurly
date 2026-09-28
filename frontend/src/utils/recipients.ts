// Phase 3.17 — a campaign's recipients: a table on wide screens and stacked rows on phones, one page of them at
// a time (the API sorts, filters, searches and pages: ROADMAP 3.17.1). The logic is in recipients-view.ts.
//
// The page wires what these render: `[data-sort]` headers (nextSort), the phone's `[data-sort-select]`,
// `[data-select]` / `[data-select-all]` checkboxes, and `[data-qr]` buttons. `[data-copy]` works on its own
// (ui.ts). Every recipient has two checkboxes, the table's and the phone row's: `syncSelection` keeps them alike.

import { formatDateTime, formatNumber, prettyUrl } from './format';
import { html, raw, type RawHTML } from './html';
import { icon } from './icons';
import { linkHref } from './link-address';
import { activityLine, ariaSort, personLabel, secondaryLabel, sortChoice, SORT_CHOICES, type RecipientSort, type SortState } from './recipients-view';

/** A row of `/recipients`: one per personalized link, all time. */
export interface Recipient {
  short_code: string;
  short_url: string;
  domain: string | null;
  user_data: Record<string, string>;
  clicks: number;
  opens: number;
  last_click_at: string | null;
  last_open_at: string | null;
}

export interface RecipientsOptions {
  /** The campaign's CSV columns, in order: the table shows each, the first as the name. */
  columns: readonly string[];
  sort: SortState;
  selected: ReadonlySet<string>;
}

const checked = (on: boolean) => (on ? raw('checked') : '');

function sortHeader(label: string, column: RecipientSort, sort: SortState, align: 'left' | 'right' = 'left'): RawHTML {
  const state = ariaSort(column, sort);
  const arrow = state === 'none' ? '' : icon('chevron-down', `size-3.5 ${state === 'ascending' ? 'rotate-180' : ''}`);
  return html`<th scope="col" aria-sort="${state}" class="${align === 'right' ? 'text-right' : ''}">
    <button type="button" class="inline-flex items-center gap-1 rounded-md hover:text-ink-950 ${state === 'none' ? '' : 'text-ink-950'}" data-sort="${column}">${label}${arrow}</button>
  </th>`;
}

function linkActions(r: Recipient, name: string): RawHTML {
  return html`<button type="button" class="btn btn-ghost btn-sm btn-icon" data-copy="${r.short_url}" aria-label="Copy link for ${name}"><span data-copy-icon>${icon('copy')}</span></button>
    <button type="button" class="btn btn-ghost btn-sm btn-icon" data-qr="${r.short_code}" aria-label="QR code for ${name}">${icon('qr')}</button>`;
}

function lastClick(r: Recipient): RawHTML {
  if (!r.last_click_at) return html`<span class="badge badge-outline">Not yet</span>`;
  return html`<span class="inline-flex items-center gap-1.5"><span class="status-dot text-brand-600"></span><time data-relative datetime="${r.last_click_at}" title="${formatDateTime(r.last_click_at)}"></time></span>`;
}

/** Wide screens: the CSV's columns, the link, clicks, opens and the last click; the last four sort. */
export function recipientTable(rows: Recipient[], { columns, sort, selected }: RecipientsOptions): RawHTML {
  const all = rows.length > 0 && rows.every((r) => selected.has(r.short_code));
  return html`<table class="table">
    <thead>
      <tr>
        <th class="w-10"><input type="checkbox" class="checkbox" data-select-all ${checked(all)} aria-label="Select all on this page" /></th>
        ${columns.map((c) => html`<th scope="col">${c}</th>`)}
        ${sortHeader('Short link', 'code', sort)}
        ${sortHeader('Clicks', 'clicks', sort, 'right')}
        ${sortHeader('Opens', 'opens', sort, 'right')}
        ${sortHeader('Last click', 'last_click', sort)}
      </tr>
    </thead>
    <tbody>${rows.map((r) => {
      const name = personLabel(r.user_data, columns);
      return html`<tr>
        <td><input type="checkbox" class="checkbox" data-select="${r.short_code}" ${checked(selected.has(r.short_code))} aria-label="Select ${name}" /></td>
        ${columns.map((c, i) => html`<td class="whitespace-nowrap ${i === 0 ? 'font-medium text-ink-950' : ''}">${r.user_data[c] || html`<span class="text-ink-500">—</span>`}</td>`)}
        <td class="whitespace-nowrap"><div class="flex items-center gap-1"><a class="shortlink text-[13px] text-ink-900 hover:underline" href="${linkHref(r.short_code, r.domain)}">${prettyUrl(r.short_url)}</a>${linkActions(r, name)}</div></td>
        <td class="num text-right ${r.clicks ? 'font-semibold text-ink-950' : 'text-ink-500'}">${formatNumber(r.clicks)}</td>
        <td class="num text-right ${r.opens ? 'font-semibold text-ink-950' : 'text-ink-500'}">${formatNumber(r.opens)}</td>
        <td class="whitespace-nowrap text-ink-500">${lastClick(r)}</td>
      </tr>`;
    })}</tbody>
  </table>`;
}

/** Phones: the name and what they did, the next two columns, then clicks, opens and the last click. */
export function recipientRows(rows: Recipient[], { columns, selected }: RecipientsOptions): RawHTML {
  return html`<ul class="divide-y divide-line">${rows.map((r) => {
    const name = personLabel(r.user_data, columns);
    const more = secondaryLabel(r.user_data, columns);
    return html`<li class="flex items-start gap-3 px-4 py-3">
      <input type="checkbox" class="checkbox mt-0.5" data-select="${r.short_code}" ${checked(selected.has(r.short_code))} aria-label="Select ${name}" />
      <div class="min-w-0 flex-1">
        <div class="flex min-w-0 flex-wrap items-center gap-1.5">
          <a class="truncate font-medium text-ink-950 hover:underline" href="${linkHref(r.short_code, r.domain)}">${name}</a>
          ${r.clicks ? html`<span class="badge badge-brand">Clicked</span>` : ''}${r.opens ? html`<span class="badge badge-info">Opened</span>` : ''}
        </div>
        ${more ? html`<p class="truncate text-sm text-ink-600">${more}</p>` : ''}
        <p class="mt-0.5 text-[13px] text-ink-500">${activityLine(r)}${r.last_click_at ? html` · <time data-relative datetime="${r.last_click_at}" title="${formatDateTime(r.last_click_at)}"></time>` : ''}</p>
      </div>
      <div class="-mr-2 flex shrink-0">${linkActions(r, name)}</div>
    </li>`;
  })}</ul>`;
}

/** Both, each for its screens. */
export function recipientsView(rows: Recipient[], opts: RecipientsOptions): RawHTML {
  return html`<div class="max-md:hidden">${recipientTable(rows, opts)}</div><div class="md:hidden">${recipientRows(rows, opts)}</div>`;
}

/** The phone's "Sort by": the headers' first press each; "Custom order" while a header sorts fewest first. */
export function sortSelect(sort: SortState): RawHTML {
  const current = sortChoice(sort)?.value ?? '';
  return html`<label class="flex items-center gap-2 text-sm text-ink-600"><span class="shrink-0">Sort by</span>
    <select class="select" data-sort-select>
      ${current ? '' : html`<option value="" selected disabled>Custom order</option>`}
      ${SORT_CHOICES.map((c) => html`<option value="${c.value}" ${c.value === current ? raw('selected') : ''}>${c.label}</option>`)}
    </select></label>`;
}

/** Tick or untick every checkbox of a recipient (the table's and the phone row's). */
export function syncSelection(container: ParentNode, code: string, on: boolean): void {
  container.querySelectorAll<HTMLInputElement>('[data-select]').forEach((box) => {
    if (box.dataset.select === code) box.checked = on;
  });
}
