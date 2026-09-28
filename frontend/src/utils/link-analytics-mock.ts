// Development only: made-up answers in the shape of the analytics contract (ROADMAP 3.16.1), for building the
// link's page before its routes are deployed. Loaded by link-analytics.ts when the address has `&mock`, and
// never in a production build. The numbers follow a seed, so a reload shows the same ones.

import { saveBlob } from './api';
import { periodDays, type GroupBy, type Period } from './analytics-view';
import { todayIn } from './days';
import type { LinkAddress } from './link-address';
import type { BreakdownEntry, LinkBreakdown, LinkTimeseries, LinkTotals, LinkVisit, LinkVisits, VisitKind, VisitType } from './types';

// scripts/dev-only-rules.mjs looks for this in production builds, where it must never be: keep it in use.
const DEV_ONLY_MARKER = 'shurly-dev-only';
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const DAY = 86_400_000;
const iso = (t: number) => new Date(t).toISOString().slice(0, 10);
const utc = (date: string) => Date.parse(`${date}T00:00:00Z`);

function seeded(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return ((s >>> 0) % 10_000) / 10_000;
  };
}

function range(link: LinkAddress, period: Period) {
  const today = todayIn(TZ);
  const to = 'days' in period ? today : period.to > today ? today : period.to;
  const from = 'days' in period ? iso(utc(today) - (period.days - 1) * DAY) : period.from;
  return { short_code: link.short_code, domain: link.domain ?? null, from, to, timezone: TZ };
}

/** Clicks and opens per local day of the range, the same for a given link and day. */
function days(link: LinkAddress, from: string, to: string) {
  const out: Array<{ date: string; clicks: number; opens: number }> = [];
  for (let t = utc(from); t <= utc(to); t += DAY) {
    const rand = seeded(t / DAY + link.short_code.length * 7919);
    const weekday = new Date(t).getUTCDay();
    const busy = weekday === 0 || weekday === 6 ? 0.4 : 1;
    out.push({ date: iso(t), clicks: Math.floor(rand() * 7 * busy), opens: Math.floor(rand() * 3 * busy) });
  }
  return out;
}

export function mockTotals(link: LinkAddress): LinkTotals {
  return { short_code: link.short_code, domain: link.domain ?? null, timezone: TZ, clicks: 342, opens: 118, countries: 9, last_click_at: new Date(Date.now() - 3 * 3600_000).toISOString() };
}

export function mockTimeseries(link: LinkAddress, period: Period, groupBy: GroupBy): LinkTimeseries {
  const r = range(link, period);
  const perDay = days(link, r.from, r.to);
  const buckets = new Map<string, { start: string; end: string; clicks: number; opens: number }>();
  for (const d of perDay) {
    const date = new Date(`${d.date}T00:00:00Z`);
    const key =
      groupBy === 'day' ? d.date : groupBy === 'month' ? d.date.slice(0, 7) : iso(utc(d.date) - ((date.getUTCDay() + 6) % 7) * DAY);
    const b = buckets.get(key) ?? { start: d.date, end: d.date, clicks: 0, opens: 0 };
    b.end = d.date;
    b.clicks += d.clicks;
    b.opens += d.opens;
    buckets.set(key, b);
  }
  const stats = [...buckets.values()];
  const rand = seeded(periodDays(period) * 31 + link.short_code.length);
  const hour_of_day = Array.from({ length: 24 }, (_, hour) => {
    const office = hour >= 8 && hour <= 19 ? 1 : 0.15;
    return { hour, clicks: Math.floor(rand() * 20 * office), opens: Math.floor(rand() * 8 * office) };
  });
  const day_of_week = Array.from({ length: 7 }, (_, i) => ({ day: i + 1, clicks: Math.floor(rand() * (i < 5 ? 40 : 12)), opens: Math.floor(rand() * 15) }));
  const clicks = stats.reduce((s, b) => s + b.clicks, 0);
  const opens = stats.reduce((s, b) => s + b.opens, 0);
  return { ...r, group_by: groupBy, clicks, opens, stats, hour_of_day, day_of_week };
}

const share = (entries: Array<[string, number]>): BreakdownEntry[] => {
  const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
  return entries.map(([name, count]) => ({ name, count, share: Math.round((count / total) * 10_000) / 10_000 }));
};

export function mockBreakdown(link: LinkAddress, period: Period, type: VisitType): LinkBreakdown {
  const r = range(link, period);
  const total = mockTimeseries(link, period, 'day').clicks;
  const scale = (n: number) => Math.max(0, Math.round((n / 100) * total));
  return {
    ...r,
    type,
    total,
    os: share([['Windows', scale(41)], ['iOS', scale(24)], ['macOS', scale(20)], ['Android', scale(12)], ['Unknown', scale(3)]]),
    browsers: share([['Chrome', scale(55)], ['Safari', scale(28)], ['Edge', scale(9)], ['Firefox', scale(5)], ['Samsung Internet', scale(2)], ['Opera', scale(1)]]),
    devices: share([['desktop', scale(62)], ['mobile', scale(33)], ['tablet', scale(5)]]),
    referrers: share([
      ['www.linkedin.com', scale(46)],
      ['Direct', scale(31)],
      ['com.linkedin.android', scale(8)],
      ['t.co', scale(5)],
      ['www.google.com', scale(4)],
      ['mail.google.com', scale(2)],
      ['outlook.office.com', scale(2)],
      ['duckduckgo.com', scale(1)],
      ['news.ycombinator.com', scale(1)],
      ['a-very-long-referrer-host.subdomain.example-company.co.uk', scale(0.5)],
      ['www.bing.com', scale(0.5)],
      ['slack.com', scale(0.4)],
    ]),
    countries: share([['ES', scale(62)], ['DE', scale(12)], ['IE', scale(6)], ['GB', scale(5)], ['PH', scale(4)], ['US', scale(4)], ['FR', scale(3)], ['PT', scale(2)], ['MX', scale(1)], ['NL', scale(0.5)], ['IT', scale(0.4)], ['Unknown', scale(1)]]),
  };
}

const PEOPLE: Array<Omit<LinkVisit, 'visited_at' | 'kind'>> = [
  { country: 'ES', browser: 'Chrome', os: 'Windows', device: 'desktop', referrer: 'www.linkedin.com' },
  { country: 'ES', browser: 'Safari', os: 'iOS', device: 'mobile', referrer: 'www.linkedin.com' },
  { country: 'PH', browser: 'Chrome', os: 'macOS', device: 'desktop', referrer: 'Direct' },
  { country: 'GB', browser: 'Safari', os: 'iOS', device: 'mobile', referrer: 'com.linkedin.android' },
  { country: 'DE', browser: 'Edge', os: 'Windows', device: 'desktop', referrer: 't.co' },
  { country: 'Unknown', browser: 'Firefox', os: 'Linux', device: 'desktop', referrer: 'Direct' },
];

function allVisits(link: LinkAddress, period: Period): LinkVisit[] {
  const r = range(link, period);
  const perDay = days(link, r.from, r.to);
  const visits: LinkVisit[] = [];
  for (const d of perDay) {
    const kinds: VisitKind[] = [...Array(d.clicks).fill('click'), ...Array(d.opens).fill('open'), ...(d.clicks > 4 ? ['bot' as const] : [])];
    kinds.forEach((kind, i) => {
      const person = PEOPLE[(i + d.date.length + Number(d.date.slice(-2))) % PEOPLE.length];
      const hour = String(8 + ((i * 5 + Number(d.date.slice(-2))) % 12)).padStart(2, '0');
      const minute = String((i * 17 + 3) % 60).padStart(2, '0');
      visits.push({ ...person, ...(kind === 'bot' ? { browser: 'Bot', device: 'other', os: 'Unknown' } : {}), kind, visited_at: `${d.date}T${hour}:${minute}:00+02:00` });
    });
  }
  return visits.sort((a, b) => b.visited_at.localeCompare(a.visited_at));
}

const KIND: Record<VisitType, VisitKind | null> = { clicks: 'click', opens: 'open', bots: 'bot', all: null };

export function mockVisits(link: LinkAddress, period: Period, type: VisitType, page: number, pageSize: number): LinkVisits {
  const kind = KIND[type];
  const matching = allVisits(link, period).filter((v) => !kind || v.kind === kind);
  const pages = Math.max(1, Math.ceil(matching.length / pageSize));
  return { ...range(link, period), type, total: matching.length, page, page_size: pageSize, pages, visits: matching.slice((page - 1) * pageSize, page * pageSize) };
}

export async function mockDownload(link: LinkAddress, period: Period, type: VisitType, filename: string): Promise<void> {
  const kind = KIND[type];
  const rows = allVisits(link, period).filter((v) => !kind || v.kind === kind);
  const header = 'visited_at,kind,country,browser,os,device,referrer,user_agent';
  const lines = rows.map((v) => [v.visited_at, v.kind, v.country, v.browser, v.os, v.device, v.referrer, `Mozilla/5.0 (${DEV_ONLY_MARKER})`].join(','));
  saveBlob(new Blob([[header, ...lines].join('\n')], { type: 'text/csv' }), filename);
}
