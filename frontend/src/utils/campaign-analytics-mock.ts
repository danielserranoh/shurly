// Development only: made-up answers in the shape of the campaign analytics contract (ROADMAP 3.17.1), for building
// the campaign's page before its routes are deployed. Loaded by campaign-analytics.ts when the address has
// `&mock`, and never in a production build. The recipients are the campaign's own links, with invented numbers
// that follow each code, so a reload shows the same ones.

import { saveBlob } from './api';
import type { GroupBy, Period } from './analytics-view';
import { mockBreakdown, mockTimeseries } from './link-analytics-mock';
import type { RecipientsRequest } from './recipients-view';
import type { Campaign, CampaignBreakdown, CampaignRecipient, CampaignRecipients, CampaignTimeseries, CampaignTotals } from './types';

// scripts/dev-only-rules.mjs looks for this in production builds, where it must never be: keep it in use.
const DEV_ONLY_MARKER = 'shurly-dev-only';
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const identity = (c: Campaign) => ({ campaign_id: c.id, campaign_name: c.name });
const asLink = (c: Campaign) => ({ short_code: `campaign-${c.id.slice(0, 8)}`, domain: null });

function hash(text: string): number {
  let h = 2166136261;
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return h >>> 0;
}

/** Each recipient's all-time numbers, following their code. */
function recipients(c: Campaign): CampaignRecipient[] {
  return (c.urls ?? []).map((u) => {
    const h = hash(u.short_code);
    const roll = (h % 100) / 100;
    const opens = roll < 0.6 ? 1 + (h % 4) : 0;
    const clicks = roll < 0.38 ? 1 + ((h >>> 3) % 6) : 0;
    const daysAgo = 2 + (h % 40);
    const at = (hours: number) => new Date(Date.now() - daysAgo * 86_400_000 + hours * 3_600_000).toISOString();
    return {
      short_code: u.short_code,
      short_url: u.short_url ?? '',
      domain: null,
      user_data: u.user_data ?? {},
      clicks,
      opens,
      first_click_at: clicks ? at(1) : null,
      last_click_at: clicks ? at(1 + clicks * 19) : null,
      last_open_at: opens ? at(opens * 7) : null,
    };
  });
}

export function mockCampaignTotals(c: Campaign): CampaignTotals {
  const all = recipients(c);
  const n = all.length;
  const clicked = all.filter((r) => r.clicks).length;
  const opened = all.filter((r) => r.opens).length;
  const last = all.map((r) => r.last_click_at).filter((t): t is string => Boolean(t)).sort().at(-1) ?? null;
  const rate = (k: number) => (n ? Math.round((k / n) * 10_000) / 10_000 : 0);
  return {
    ...identity(c),
    timezone: TZ,
    recipients: n,
    clicks: all.reduce((s, r) => s + r.clicks, 0),
    opens: all.reduce((s, r) => s + r.opens, 0),
    clicked,
    opened,
    click_rate: rate(clicked),
    open_rate: rate(opened),
    countries: 6,
    last_click_at: last,
  };
}

export function mockCampaignTimeseries(c: Campaign, period: Period, groupBy: GroupBy): CampaignTimeseries {
  const { short_code: _code, domain: _domain, ...rest } = mockTimeseries(asLink(c), period, groupBy);
  return { ...rest, ...identity(c) };
}

export function mockCampaignBreakdown(c: Campaign, period: Period): CampaignBreakdown {
  const { short_code: _code, domain: _domain, ...rest } = mockBreakdown(asLink(c), period, 'clicks');
  return { ...rest, ...identity(c) };
}

const MATCH: Record<RecipientsRequest['filter'], (r: CampaignRecipient) => boolean> = {
  all: () => true,
  clicked: (r) => r.clicks > 0,
  opened: (r) => r.opens > 0,
  none: (r) => !r.clicks && !r.opens,
};

/** Filter, search, sort (ties: the latest click, then the code) and page, as the API does. */
function query(c: Campaign, req: RecipientsRequest) {
  const q = req.q.trim().toLowerCase();
  const searched = recipients(c).filter((r) => !q || r.short_code.includes(q) || Object.values(r.user_data).some((v) => String(v).toLowerCase().includes(q)));
  const counts = { all: searched.length, clicked: 0, opened: 0, none: 0 };
  searched.forEach((r) => {
    if (r.clicks) counts.clicked++;
    if (r.opens) counts.opened++;
    if (!r.clicks && !r.opens) counts.none++;
  });
  const key = (r: CampaignRecipient): number | string => ({ clicks: r.clicks, opens: r.opens, last_click: r.last_click_at ?? '', code: r.short_code })[req.sort];
  const sign = req.order === 'asc' ? 1 : -1;
  const rows = searched.filter(MATCH[req.filter]).sort((a, b) => {
    if (req.sort === 'last_click' && Boolean(a.last_click_at) !== Boolean(b.last_click_at)) return a.last_click_at ? -1 : 1; // no click: last
    const x = key(a);
    const y = key(b);
    const primary = x < y ? -sign : x > y ? sign : 0;
    return primary || (b.last_click_at ?? '').localeCompare(a.last_click_at ?? '') || a.short_code.localeCompare(b.short_code);
  });
  return { rows, counts };
}

export function mockCampaignRecipients(c: Campaign, req: RecipientsRequest): CampaignRecipients {
  const { rows, counts } = query(c, req);
  const size = req.pageSize ?? 50;
  return {
    ...identity(c),
    timezone: TZ,
    filter: req.filter,
    q: req.q,
    sort: req.sort,
    order: req.order,
    total: rows.length,
    page: req.page,
    page_size: size,
    pages: Math.max(1, Math.ceil(rows.length / size)),
    recipients: rows.slice((req.page - 1) * size, req.page * size),
    counts,
  };
}

export async function mockCampaignDownload(c: Campaign, req: RecipientsRequest, filename: string): Promise<void> {
  const { rows } = query(c, req);
  const columns = c.csv_columns;
  const lines = [
    `# ${DEV_ONLY_MARKER}: made-up numbers`,
    [...columns, 'short_code', 'short_url', 'clicks', 'opens', 'first_click_at', 'last_click_at', 'last_open_at'].join(','),
    ...rows.map((r) => [...columns.map((k) => r.user_data[k] ?? ''), r.short_code, r.short_url, r.clicks, r.opens, r.first_click_at ?? '', r.last_click_at ?? '', r.last_open_at ?? ''].join(',')),
  ];
  saveBlob(new Blob([lines.join('\n')], { type: 'text/csv' }), filename);
}
