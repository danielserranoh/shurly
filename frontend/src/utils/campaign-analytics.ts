// Phase 3.17 — a campaign's analytics, from the routes of the contract (ROADMAP 3.17.1): the all-time totals,
// the period's timeseries and breakdown over all its links, and its recipients (all time) and their CSV.
//
// In development only, `&mock` in the page's address answers from made-up numbers (campaign-analytics-mock.ts),
// until the routes are deployed. `import.meta.env.DEV` stays at each `if`, so a production build folds the branch
// away, import and all; scripts/check-dev-only.mjs fails the build otherwise.

import { apiDownload, apiGet } from './api';
import { periodQuery, type GroupBy, type Period } from './analytics-view';
import { recipientsExportQuery, recipientsQuery, type RecipientsRequest } from './recipients-view';
import type { Campaign, CampaignBreakdown, CampaignRecipients, CampaignTimeseries, CampaignTotals } from './types';

const mockOn = () => new URLSearchParams(location.search).has('mock');
const route = (campaign: Pick<Campaign, 'id'>, path: string) => `/api/v1/analytics/campaigns/${encodeURIComponent(campaign.id)}/${path}`;

export async function getCampaignTotals(campaign: Campaign): Promise<CampaignTotals> {
  if (import.meta.env.DEV && mockOn()) return (await import('./campaign-analytics-mock')).mockCampaignTotals(campaign);
  return apiGet<CampaignTotals>(route(campaign, 'totals'));
}

export async function getCampaignTimeseries(campaign: Campaign, period: Period, groupBy: GroupBy): Promise<CampaignTimeseries> {
  if (import.meta.env.DEV && mockOn()) return (await import('./campaign-analytics-mock')).mockCampaignTimeseries(campaign, period, groupBy);
  return apiGet<CampaignTimeseries>(route(campaign, `timeseries?${periodQuery(period)}&group_by=${groupBy}`));
}

export async function getCampaignBreakdown(campaign: Campaign, period: Period): Promise<CampaignBreakdown> {
  if (import.meta.env.DEV && mockOn()) return (await import('./campaign-analytics-mock')).mockCampaignBreakdown(campaign, period);
  return apiGet<CampaignBreakdown>(route(campaign, `breakdown?${periodQuery(period)}&type=clicks`));
}

/** A page of recipients, all time: the API filters, searches, sorts and pages. */
export async function getCampaignRecipients(campaign: Campaign, request: RecipientsRequest): Promise<CampaignRecipients> {
  if (import.meta.env.DEV && mockOn()) return (await import('./campaign-analytics-mock')).mockCampaignRecipients(campaign, request);
  return apiGet<CampaignRecipients>(route(campaign, `recipients?${recipientsQuery(request)}`));
}

/** Every recipient that matches the list's filter and search, in its order, as CSV. */
export async function downloadCampaignRecipients(campaign: Campaign, request: RecipientsRequest, filename: string): Promise<void> {
  if (import.meta.env.DEV && mockOn()) return (await import('./campaign-analytics-mock')).mockCampaignDownload(campaign, request, filename);
  return apiDownload(route(campaign, `recipients.csv?${recipientsExportQuery(request)}`), filename);
}
