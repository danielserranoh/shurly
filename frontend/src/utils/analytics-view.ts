// Phase 3.16 — the link's analytics page (ROADMAP 3.16.1, the contract): its period, kept in the address and
// sent as the API's query; the custom range's checks, which are the API's 422s said before asking; and the
// labels of its charts. No imports, so tests/analytics-view.test.mjs runs it as is.

/** The last N local days, today included, or a custom range of local dates (both inclusive). */
export type Period = { days: number } | { from: string; to: string };
export type GroupBy = 'day' | 'week' | 'month';
export type Series = 'clicks' | 'opens';

export const PERIOD_CHOICES = [7, 30, 90] as const;
export const DEFAULT_PERIOD: Period = { days: 30 };
/** The API's limit for `period` and for a custom range. */
export const MAX_DAYS = 731;

const DAY_MS = 86_400_000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** A local date (`YYYY-MM-DD`) as the UTC midnight that names it, so no zone shifts it. */
function utc(date: string): Date {
  const [y, m, d] = date.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

const isDate = (value: string | null): value is string => Boolean(value && DATE.test(value) && !Number.isNaN(utc(value).getTime()));
const spanDays = (from: string, to: string) => Math.round((utc(to).getTime() - utc(from).getTime()) / DAY_MS) + 1;
const fmt = (date: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { ...options, timeZone: 'UTC' }).format(utc(date));

/** Why a custom range can't be counted (the API's 422s), or null. A `to` after today is fine: it's clipped. */
export function rangeProblem(from: string, to: string, today: string): string | null {
  if (!isDate(from) || !isDate(to)) return 'Pick both dates.';
  if (from > to) return 'The start date comes after the end date.';
  if (from > today) return 'The range starts after today.';
  if (spanDays(from, to) > MAX_DAYS) return 'Pick a range of two years or less.';
  return null;
}

/** The page's period from its address: `?period=N`, or `?from=…&to=…`; anything the API would refuse, the default. */
export function periodFromParams(params: URLSearchParams, today: string): Period {
  const days = params.get('period');
  const from = params.get('from');
  const to = params.get('to');
  if (days !== null && from === null && to === null) {
    const n = Number(days);
    return Number.isInteger(n) && n >= 1 && n <= MAX_DAYS ? { days: n } : DEFAULT_PERIOD;
  }
  if (days === null && from !== null && to !== null && rangeProblem(from, to, today) === null) return { from, to };
  return DEFAULT_PERIOD;
}

/** Write the period into the page's address, replacing the other form. */
export function setPeriodParams(params: URLSearchParams, period: Period): void {
  for (const key of ['period', 'from', 'to']) params.delete(key);
  if ('days' in period) params.set('period', String(period.days));
  else {
    params.set('from', period.from);
    params.set('to', period.to);
  }
}

/** The API's query for a period. */
export function periodQuery(period: Period): string {
  return 'days' in period ? `period=${period.days}` : `from=${period.from}&to=${period.to}`;
}

/** How many days the period covers, both ends included. */
export function periodDays(period: Period): number {
  return 'days' in period ? period.days : spanDays(period.from, period.to);
}

/** The grouping a period starts with: by day up to a month, by week beyond. */
export function defaultGroupBy(period: Period): GroupBy {
  return periodDays(period) <= 31 ? 'day' : 'week';
}

/** A range of local dates to read: "Sep 1 – Sep 28, 2026", the years both said when they differ. */
export function rangeLabel(from: string, to: string): string {
  if (from === to) return fmt(from, { month: 'short', day: 'numeric', year: 'numeric' });
  const sameYear = from.slice(0, 4) === to.slice(0, 4);
  const start = fmt(from, sameYear ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' });
  return `${start} – ${fmt(to, { month: 'short', day: 'numeric', year: 'numeric' })}`;
}

/** The period as the page names it: "Last 30 days", "Today", or its dates. */
export function periodLabel(period: Period): string {
  if ('days' in period) return period.days === 1 ? 'Today' : `Last ${period.days} days`;
  return rangeLabel(period.from, period.to);
}

// ---------------------------------------------------------------------------
// Chart rows: { label (the axis), title (tooltip and table), value }
// ---------------------------------------------------------------------------

export interface Bucket {
  start: string;
  end: string;
  clicks: number;
  opens: number;
}

export interface ChartRow {
  label: string;
  title: string;
  value: number;
}

const lastOfMonth = (date: string) => {
  const d = utc(date);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).toISOString().slice(0, 10);
};

/**
 * The timeseries' buckets as chart rows. Days read as weekdays within a week ("Today" for today) and as
 * dates beyond; weeks and months by where they start, with their real ends (the first and last are
 * clipped to the range) in the title.
 */
export function bucketRows(stats: Bucket[], groupBy: GroupBy, series: Series, today: string): ChartRow[] {
  const short = { month: 'short', day: 'numeric' } as const;
  return stats.map((b) => {
    const value = b[series];
    if (groupBy === 'day') {
      const title = fmt(b.start, { weekday: 'long', month: 'short', day: 'numeric' });
      const label = stats.length <= 7 ? (b.start === today ? 'Today' : fmt(b.start, { weekday: 'short' })) : fmt(b.start, short);
      return { label, title, value };
    }
    if (groupBy === 'month') {
      const whole = b.start.endsWith('-01') && b.end === lastOfMonth(b.start);
      return { label: fmt(b.start, { month: 'short' }), title: whole ? fmt(b.start, { month: 'long', year: 'numeric' }) : `${fmt(b.start, short)} – ${fmt(b.end, short)}`, value };
    }
    return { label: fmt(b.start, short), title: `${fmt(b.start, short)} – ${fmt(b.end, short)}`, value };
  });
}

const hourName = (hour: number) => new Intl.DateTimeFormat('en-US', { hour: 'numeric', timeZone: 'UTC' }).format(Date.UTC(2000, 0, 1, hour % 24));

/** The 24 hours of the day (local time), "12 AM" to "11 PM". */
export function hourRows(hours: Array<{ hour: number; clicks: number; opens: number }>, series: Series): ChartRow[] {
  return hours.map((h) => ({ label: hourName(h.hour), title: `${hourName(h.hour)} – ${hourName(h.hour + 1)}`, value: h[series] }));
}

// 2024-01-01 was a Monday: day 1 (ISO) is its date.
const weekday = (day: number, width: 'short' | 'long') => new Intl.DateTimeFormat('en-US', { weekday: width, timeZone: 'UTC' }).format(Date.UTC(2024, 0, day));

/** The days of the week, Monday (1) to Sunday (7). */
export function dayOfWeekRows(days: Array<{ day: number; clicks: number; opens: number }>, series: Series): ChartRow[] {
  return days.map((d) => ({ label: weekday(d.day, 'short'), title: weekday(d.day, 'long'), value: d[series] }));
}

/**
 * A visit's moment as the API gives it (ISO 8601 with the viewer's zone offset), read as it is: the page shows
 * the zone the API counted in, whatever the browser's.
 */
export function visitTime(value: string): { short: string; long: string } {
  const [date, rest = '00:00'] = value.split('T');
  const [hh, mm] = rest.split(':').map(Number);
  const hour = `${hh % 12 || 12}:${String(mm).padStart(2, '0')} ${hh < 12 ? 'AM' : 'PM'}`;
  return {
    short: `${fmt(date, { month: 'short', day: 'numeric' })}, ${hour}`,
    long: `${fmt(date, { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' })}, ${hour}`,
  };
}

const DEVICES: Record<string, string> = { desktop: 'Desktop', mobile: 'Mobile', tablet: 'Tablet', other: 'Other devices' };

/** A device class as a word; anything new as it comes. */
export function deviceLabel(name: string): string {
  return DEVICES[name] ?? name;
}
