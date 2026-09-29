// Phase 8.3 — a link is its code and its domain: once Shlink's links are imported, one code
// can name links on two domains. The API picks one by `?domain=`; without it, the default
// domain's link answers, so an address without a domain (an old bookmark) still works.
// No imports, so tests/link-address.test.mjs can run it as is.

export interface LinkAddress {
  short_code: string;
  domain?: string | null;
}

/** `path` with `domain=` added to its query, when there's a domain. */
export function withDomain(path: string, domain?: string | null): string {
  if (!domain) return path;
  return `${path}${path.includes('?') ? '&' : '?'}domain=${encodeURIComponent(domain)}`;
}

/** The API path of a link, or of something under it: `linkApi(link, '/rules')`. */
export function linkApi(link: LinkAddress, suffix = ''): string {
  return withDomain(`/api/v1/urls/${encodeURIComponent(link.short_code)}${suffix}`, link.domain);
}

/** A link's analytics: `analyticsApi(link, 'geo?days=30')`. */
export function analyticsApi(link: LinkAddress, stats: string): string {
  return withDomain(`/api/v1/analytics/urls/${encodeURIComponent(link.short_code)}/${stats}`, link.domain);
}

/** The link's page in the dashboard. */
export function linkHref(code: string, domain?: string | null): string {
  return withDomain(`/dashboard/link/?code=${encodeURIComponent(code)}`, domain);
}
