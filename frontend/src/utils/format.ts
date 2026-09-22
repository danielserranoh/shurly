// Formatting helpers for numbers, dates and URLs.

import type { ShortLink } from './types';

const LOCALE = 'en-US';

/** The API returns naive UTC timestamps for some columns ("2025-11-09T10:00:00"). Treat them as UTC. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  const d = new Date(hasZone || value.length <= 10 ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatNumber(n: number | null | undefined): string {
  return new Intl.NumberFormat(LOCALE).format(n ?? 0);
}

export function formatCompact(n: number | null | undefined): string {
  const value = n ?? 0;
  if (value < 10_000) return formatNumber(value);
  return new Intl.NumberFormat(LOCALE, { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function formatPercent(n: number, digits = 0): string {
  return `${n.toFixed(digits)}%`;
}

export function formatDate(value: string | Date | null | undefined, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' }): string {
  const d = value instanceof Date ? value : parseDate(value);
  return d ? d.toLocaleDateString(LOCALE, opts) : '—';
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const d = value instanceof Date ? value : parseDate(value);
  return d
    ? d.toLocaleString(LOCALE, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
    : '—';
}

/** "just now", "5m ago", "3h ago", "yesterday", "4d ago", then an absolute date. */
export function formatRelative(value: string | Date | null | undefined, now = Date.now()): string {
  const d = value instanceof Date ? value : parseDate(value);
  if (!d) return 'never';
  const diff = Math.round((now - d.getTime()) / 1000);
  const future = diff < 0;
  const s = Math.abs(diff);
  const suffix = (t: string) => (future ? `in ${t}` : `${t} ago`);
  if (s < 45) return future ? 'in a moment' : 'just now';
  if (s < 3600) return suffix(`${Math.max(1, Math.round(s / 60))}m`);
  if (s < 86_400) return suffix(`${Math.round(s / 3600)}h`);
  const days = Math.round(s / 86_400);
  if (days === 1) return future ? 'tomorrow' : 'yesterday';
  if (days < 7) return suffix(`${days}d`);
  if (days < 30) return suffix(`${Math.round(days / 7)}w`);
  return formatDate(d);
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatNumber(count)} ${count === 1 ? singular : plural}`;
}

export function hostname(url: string | null | undefined): string {
  if (!url) return '';
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/** URL without protocol and trailing slash, for display. */
export function prettyUrl(url: string | null | undefined): string {
  if (!url) return '';
  return url.replace(/^https?:\/\//, '').replace(/\/$/, '');
}

/** Human title for a link: explicit title → OG title → destination host. */
export function linkTitle(link: Pick<ShortLink, 'title' | 'og_title' | 'original_url'>): string {
  return link.title?.trim() || link.og_title?.trim() || hostname(link.original_url) || 'Untitled link';
}

export type LinkStatus = 'active' | 'scheduled' | 'expired' | 'capped';

export function linkStatus(link: Pick<ShortLink, 'valid_since' | 'valid_until' | 'max_visits' | 'click_count'>, now = Date.now()): LinkStatus {
  const since = parseDate(link.valid_since);
  const until = parseDate(link.valid_until);
  if (since && since.getTime() > now) return 'scheduled';
  if (until && until.getTime() <= now) return 'expired';
  if (link.max_visits != null && (link.click_count ?? 0) >= link.max_visits) return 'capped';
  return 'active';
}

/** Deterministic pick from a small palette, e.g. for monogram tiles. */
export function hashIndex(input: string, modulo: number): number {
  let h = 0;
  for (let i = 0; i < input.length; i++) h = (h * 31 + input.charCodeAt(i)) >>> 0;
  return h % modulo;
}

export function initials(text: string): string {
  const clean = text.replace(/^www\./, '').trim();
  return (clean[0] ?? '?').toUpperCase();
}

/** Value for <input type="datetime-local"> from an ISO string (local time). */
export function toLocalInput(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** ISO string (UTC) from a datetime-local input value, or null when empty. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Mirrors the API's rule (server/utils/url.py): http(s), a host, at most 2048 characters. */
export function isValidHttpUrl(value: string): boolean {
  const v = value.trim();
  if (!v || v.length > 2048) return false;
  try {
    const u = new URL(v);
    return (u.protocol === 'http:' || u.protocol === 'https:') && Boolean(u.hostname);
  } catch {
    return false;
  }
}

/** Accept "example.com/page" by assuming https://. */
export function normalizeUrlInput(value: string): string {
  const v = value.trim();
  if (!v) return v;
  if (/^https?:\/\//i.test(v)) return v;
  if (/^[\w-]+(\.[\w-]+)+/.test(v)) return `https://${v}`;
  return v;
}
