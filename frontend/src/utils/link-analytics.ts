// Phase 3.16 — a link's analytics, from the routes of the contract (ROADMAP 3.16.1): the all-time totals,
// and for a period the timeseries, the breakdown, the visits and their CSV.
//
// In development only, `&mock` in the page's address answers from made-up numbers (link-analytics-mock.ts),
// for building the page before the routes are deployed. Production builds drop that branch and its module.

import { apiDownload, apiGet } from './api';
import { periodQuery, type GroupBy, type Period } from './analytics-view';
import { analyticsApi, type LinkAddress } from './link-address';
import type { LinkBreakdown, LinkTimeseries, LinkTotals, LinkVisits, VisitType } from './types';

// `import.meta.env.DEV` stays at each `if`, so a production build folds the branch away, import and all.
const mockOn = () => new URLSearchParams(location.search).has('mock');

export async function getTotals(link: LinkAddress): Promise<LinkTotals> {
  if (import.meta.env.DEV && mockOn()) return (await import('./link-analytics-mock')).mockTotals(link);
  return apiGet<LinkTotals>(analyticsApi(link, 'totals'));
}

export async function getTimeseries(link: LinkAddress, period: Period, groupBy: GroupBy): Promise<LinkTimeseries> {
  if (import.meta.env.DEV && mockOn()) return (await import('./link-analytics-mock')).mockTimeseries(link, period, groupBy);
  return apiGet<LinkTimeseries>(analyticsApi(link, `timeseries?${periodQuery(period)}&group_by=${groupBy}`));
}

export async function getBreakdown(link: LinkAddress, period: Period, type: VisitType = 'clicks'): Promise<LinkBreakdown> {
  if (import.meta.env.DEV && mockOn()) return (await import('./link-analytics-mock')).mockBreakdown(link, period, type);
  return apiGet<LinkBreakdown>(analyticsApi(link, `breakdown?${periodQuery(period)}&type=${type}`));
}

export async function getVisits(link: LinkAddress, period: Period, type: VisitType, page: number, pageSize = 20): Promise<LinkVisits> {
  if (import.meta.env.DEV && mockOn()) return (await import('./link-analytics-mock')).mockVisits(link, period, type, page, pageSize);
  return apiGet<LinkVisits>(analyticsApi(link, `visits?${periodQuery(period)}&type=${type}&page=${page}&page_size=${pageSize}`));
}

/** Every visit of the period as CSV (`type=all` by default: the kind is a column). */
export async function downloadVisits(link: LinkAddress, period: Period, filename: string, type: VisitType = 'all'): Promise<void> {
  if (import.meta.env.DEV && mockOn()) return (await import('./link-analytics-mock')).mockDownload(link, period, type, filename);
  return apiDownload(analyticsApi(link, `visits.csv?${periodQuery(period)}&type=${type}`), filename);
}
