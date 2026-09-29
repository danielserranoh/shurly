// Phase 6.3 — a list's page from its address (`?page=`), as a page the API takes: the rows it
// skips stay within MAX_SKIP, past which the API answers 422 (server/utils/bounds.py).

/** The most rows a list may skip. */
export const MAX_SKIP = 1_000_000_000;

/** `?page=N` for pages of `pageSize` rows. Anything the API would refuse is page 1: no number, a fraction, below 1, or too far. */
export function pageFromQuery(value: string | null, pageSize: number): number {
  const page = Number(value);
  if (!Number.isInteger(page) || page < 1 || (page - 1) * pageSize > MAX_SKIP) return 1;
  return page;
}
