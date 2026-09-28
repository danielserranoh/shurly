// Phase 3.17 — the campaign's recipients table: how it sorts (its headers, and "Sort by" on phones), the query
// it sends (the API filters, searches, sorts and pages: ROADMAP 3.17.1), and how a recipient reads.
// No imports, so tests/recipients-view.test.mjs runs it as is; recipients.ts renders it.

export type RecipientSort = 'clicks' | 'opens' | 'last_click' | 'code';
export type SortOrder = 'asc' | 'desc';
/** Clicked: their link, at least once. Opened: the email's tracking image. None: neither yet. */
export type RecipientFilter = 'all' | 'clicked' | 'opened' | 'none';

export interface SortState {
  sort: RecipientSort;
  order: SortOrder;
}

export const PAGE_SIZE = 50;
export const DEFAULT_SORT: SortState = { sort: 'clicks', order: 'desc' };

/** What a sortable header does when pressed: the most first (the link: A to Z), then the other way. */
export function nextSort(current: SortState, sort: RecipientSort): SortState {
  if (current.sort === sort) return { sort, order: current.order === 'desc' ? 'asc' : 'desc' };
  return { sort, order: sort === 'code' ? 'asc' : 'desc' };
}

/** A header's `aria-sort`. */
export function ariaSort(column: RecipientSort, state: SortState): 'ascending' | 'descending' | 'none' {
  if (column !== state.sort) return 'none';
  return state.order === 'asc' ? 'ascending' : 'descending';
}

/** "Sort by" on phones, where there are no headers: the headers' first press each. */
export const SORT_CHOICES: ReadonlyArray<SortState & { label: string; value: string }> = [
  { sort: 'clicks', order: 'desc', label: 'Most clicks', value: 'clicks:desc' },
  { sort: 'opens', order: 'desc', label: 'Most opens', value: 'opens:desc' },
  { sort: 'last_click', order: 'desc', label: 'Latest click', value: 'last_click:desc' },
  { sort: 'code', order: 'asc', label: 'Link, A to Z', value: 'code:asc' },
];

/** The phone's choice for a sort, when there's one (a header can also sort fewest first). */
export function sortChoice(state: SortState) {
  return SORT_CHOICES.find((c) => c.sort === state.sort && c.order === state.order);
}

export interface RecipientsRequest extends SortState {
  filter: RecipientFilter;
  q: string;
  page: number;
  pageSize?: number;
}

/** The query of `/recipients` (and of its CSV, without the page). */
export function recipientsQuery({ filter, q, sort, order, page, pageSize = PAGE_SIZE }: RecipientsRequest): string {
  const params = new URLSearchParams({ filter });
  const search = q.trim();
  if (search) params.set('q', search);
  params.set('sort', sort);
  params.set('order', order);
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  return params.toString();
}

const filled = (data: Record<string, string>, columns: readonly string[]) => {
  const ordered = [...columns, ...Object.keys(data).filter((key) => !columns.includes(key))];
  return ordered.map((key) => (data[key] ?? '').trim()).filter(Boolean);
};

/** A recipient's name: the first filled column, in the CSV's order. */
export function personLabel(data: Record<string, string>, columns: readonly string[]): string {
  return filled(data ?? {}, columns)[0] ?? 'Recipient';
}

/** What follows the name on a phone: the next two filled columns. */
export function secondaryLabel(data: Record<string, string>, columns: readonly string[]): string {
  return filled(data ?? {}, columns).slice(1, 3).join(' · ');
}

const number = new Intl.NumberFormat('en-US');
const count = (n: number, one: string, many: string) => `${number.format(n)} ${n === 1 ? one : many}`;

/** "12 clicks · 3 opens", on a phone's row. */
export function activityLine({ clicks, opens }: { clicks: number; opens: number }): string {
  if (!clicks && !opens) return 'No clicks or opens yet';
  return `${count(clicks, 'click', 'clicks')} · ${count(opens, 'open', 'opens')}`;
}

/** "1–50 of 312": the rows shown out of those that match; nothing when none do. */
export function pageRange(page: number, pageSize: number, total: number, shown: number): string {
  if (!shown) return '';
  const first = (page - 1) * pageSize + 1;
  return `${number.format(first)}–${number.format(first + shown - 1)} of ${number.format(total)}`;
}

const EMPTY: Record<RecipientFilter, string> = {
  all: 'This campaign has no recipients.',
  clicked: 'Nobody has clicked their link yet.',
  opened: 'Nobody has opened the email yet.',
  none: 'Everyone has clicked or opened. Nice.',
};

/** Why the table is empty: the search, when there is one, else the filter. */
export function EMPTY_MESSAGE(filter: RecipientFilter, q: string): string {
  return q.trim() ? 'No recipients match your search.' : EMPTY[filter];
}
