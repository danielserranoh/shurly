// Phase 6.3 — a list's page from its address (`?page=`), as a page the API takes: the rows it
// skips stay within MAX_SKIP, past which the API answers 422 (server/utils/bounds.py). And its
// pager's (components/ui/Pager.astro): the links' and the campaigns' lists.

/** The most rows a list may skip. */
export const MAX_SKIP = 1_000_000_000;

/** `?page=N` for pages of `pageSize` rows. Anything the API would refuse is page 1: no number, a fraction, below 1, or too far. */
export function pageFromQuery(value: string | null, pageSize: number): number {
  const page = Number(value);
  if (!Number.isInteger(page) || page < 1 || (page - 1) * pageSize > MAX_SKIP) return 1;
  return page;
}

const number = new Intl.NumberFormat('en-US'); // formatNumber's, without its imports: node --test runs this file

/** "Showing 21–40 of 312": the rows on this page, out of all of them. */
export function showing(page: number, pageSize: number, total: number, shown: number): string {
  const first = (page - 1) * pageSize + 1;
  return `Showing ${number.format(first)}–${number.format(Math.min(total, first + shown - 1))} of ${number.format(total)}`;
}

/** Brings a list's pager (components/ui/Pager.astro) to the page shown: hidden while there's only one. */
export function renderPager(nav: HTMLElement, page: number, pageSize: number, total: number, shown: number): void {
  const pages = Math.ceil(total / pageSize);
  nav.hidden = pages <= 1;
  nav.querySelector('[data-range]')!.textContent = showing(page, pageSize, total, shown);
  nav.querySelector<HTMLButtonElement>('[data-prev]')!.disabled = page <= 1;
  nav.querySelector<HTMLButtonElement>('[data-next]')!.disabled = page >= pages;
}
