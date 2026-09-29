// Phase 3.16/3.17 — the Analytics section of a link's page and of a campaign's (AnalyticsSection.astro): the
// period (7, 30 or 90 days, or Custom, kept in the address), the tabs (in the hash), and what they show, from
// the source the page passes: a link's routes (3.16.1) or a campaign's (3.17.1). Each tab loads when it opens,
// and again after the period changes; the timeseries always loads, as it also says which days were counted.

import { errorMessage } from './api';
import { barList, bindChartTableToggle, bindShowNumbers, columnChart, dataTable, donutChart, donutTable } from './charts';
import {
  bucketRows,
  dayOfWeekRows,
  defaultGroupBy,
  deviceLabel,
  hourRows,
  PERIOD_CHOICES,
  periodFromParams,
  periodLabel,
  rangeLabel,
  rangeProblem,
  setPeriodParams,
  visitTime,
  type GroupBy,
  type Period,
  type Series,
} from './analytics-view';
import { countryName } from './country';
import { todayIn } from './days';
import { formatNumber, pluralize } from './format';
import { html, setHTML, type RawHTML } from './html';
import { icon } from './icons';
import { initTabs, type Tabs } from './tabs';
import { positionMenu, setLoading, toast } from './ui';
import { showDaysZoneHint } from './viewer';
import type { Breakdown, BreakdownEntry, CountedRange, LinkVisit, Timeseries, VisitType, Visits } from './types';

/** Where the section's numbers come from: a link's routes or a campaign's. */
export interface AnalyticsSource {
  timeseries(period: Period, groupBy: GroupBy): Promise<Timeseries>;
  /** Clicks only: the section's context and location count clicks. */
  breakdown(period: Period): Promise<Breakdown>;
  /** The Visits tab: a link's only. */
  visits?(period: Period, type: VisitType, page: number): Promise<Visits>;
  /** Export CSV: the period's visits, a link's only. `counted` is the range last counted, for its name. */
  exportVisits?(period: Period, counted: CountedRange | null): Promise<void>;
}

export interface AnalyticsControls {
  /** Whether there are any email opens at all: the "Clicks | Email opens" switch shows only then. */
  setOpens(any: boolean): void;
  /** The zone of the all-time numbers, for "today" until a period's response names one. */
  setZone(timezone: string): void;
}

const $ = <T extends HTMLElement = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

/** Wire the page's AnalyticsSection to `source`, and load what's open. Call it once the link or campaign is known. */
export function initAnalytics(source: AnalyticsSource): AnalyticsControls {
  const hasVisits = Boolean(source.visits && document.getElementById('panel-visits'));
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  /** The zone of the all-time numbers, until a period's response names one. */
  let zone: string | null = null;
  let period: Period = periodFromParams(new URLSearchParams(location.search), todayIn(browserZone));
  let groupBy: GroupBy = defaultGroupBy(period);
  let series: Series = 'clicks';
  /** Set once the viewer picks clicks or opens; until then a period with only opens shows opens. */
  let seriesChosen = false;
  let visitType: VisitType = 'clicks';
  let visitPage = 1;
  let timeseries: Promise<Timeseries> | null = null;
  let breakdown: Promise<Breakdown> | null = null;
  let visitsShown = '';
  let counted: CountedRange | null = null;
  let tabs: Tabs | null = null;

  const CLICKS: [string, string] = ['click', 'clicks'];
  const OPENS: [string, string] = ['email open', 'email opens'];
  const panel = (key: string) => $(`#panel-${key}`);
  const panelBody = (key: string) => panel(key).querySelector<HTMLElement>('[data-panel-body]')!;
  const chartEl = (key: string) => $(`[data-chart="${key}"]`);
  const tableEl = (key: string) => $(`[data-table="${key}"]`);
  const skeleton = (height: string) => html`<div class="skeleton ${height} w-full rounded-xl"></div>`;
  const nothing = (message: string) =>
    html`<div class="flex items-start gap-3 rounded-xl bg-ink-50 p-4 text-sm text-ink-600"><span class="mt-0.5 text-ink-400">${icon('chart', 'size-4')}</span><p>${message}</p></div>`;

  /** Dim a panel while it reloads (the first load shows skeletons instead). */
  function busy(key: string, on: boolean) {
    panelBody(key).classList.toggle('opacity-60', on);
    panel(key).setAttribute('aria-busy', String(on));
  }

  /** Show a panel's content, or, with `error`, what went wrong and a way to try again. */
  function panelState(key: string, error?: unknown) {
    const box = panel(key).querySelector<HTMLElement>('[data-panel-error]')!;
    panelBody(key).hidden = error !== undefined;
    box.hidden = error === undefined;
    if (error === undefined) return;
    setHTML(
      box,
      html`<div class="flex flex-col items-start gap-3 rounded-xl bg-ink-50 p-4 text-sm text-ink-700" role="alert">
        <p class="flex items-start gap-2">${icon('circle-alert', 'mt-0.5 size-4 shrink-0 text-red-600')}<span>Couldn’t load these numbers. ${errorMessage(error)}</span></p>
        <button type="button" class="btn btn-secondary btn-sm" data-retry>${icon('refresh')}Try again</button>
      </div>`,
    );
    box.querySelector('[data-retry]')!.addEventListener('click', () => loadTab(key));
  }

  /** "Last 30 days: Aug 31 – Sep 29, 2026 · 34 clicks · 12 email opens": what the period counted. */
  function renderRange(ts: Timeseries) {
    counted = { from: ts.from, to: ts.to, timezone: ts.timezone };
    const when = 'days' in period ? `${periodLabel(period)}: ${rangeLabel(ts.from, ts.to)}` : rangeLabel(ts.from, ts.to);
    $('[data-range]').textContent = `${when} · ${pluralize(ts.clicks, 'click')} · ${pluralize(ts.opens, 'email open')}`;
  }

  // ---------------------------------------------------------------- By time
  async function loadTime() {
    const first = !chartEl('series').querySelector('svg');
    timeseries ??= source.timeseries(period, groupBy);
    const request = timeseries;
    if (first) ['series', 'hours', 'weekdays'].forEach((key) => setHTML(chartEl(key), skeleton(key === 'series' ? 'h-60' : 'h-48')));
    else busy('time', true);
    try {
      const ts = await request;
      if (request !== timeseries) return;
      panelState('time');
      renderRange(ts);
      if (!seriesChosen) {
        series = ts.clicks === 0 && ts.opens > 0 ? 'opens' : 'clicks';
        document.querySelectorAll<HTMLInputElement>('input[name="series"]').forEach((r) => (r.checked = r.value === series));
      }
      renderTime(ts);
    } catch (err) {
      if (request !== timeseries) return;
      timeseries = null;
      $('[data-range]').textContent = periodLabel(period);
      panelState('time', err);
    } finally {
      if (request === timeseries || timeseries === null) busy('time', false);
    }
  }

  function renderTime(ts: Timeseries) {
    const unit = series === 'clicks' ? CLICKS : OPENS;
    const what = series === 'clicks' ? 'Clicks' : 'Email opens';
    const empty = series === 'clicks' ? 'No clicks in this period' : 'No email opens in this period';
    const per = { day: 'Per day', week: 'Per week, from Monday', month: 'Per month' }[ts.group_by];
    const rows = bucketRows(ts.stats, ts.group_by, series, todayIn(ts.timezone));
    $('[data-series-title]').textContent = `${what} over time`;
    $('[data-series-sub]').textContent = per;
    columnChart(chartEl('series'), rows, { ariaLabel: `${what}, ${per.toLowerCase()}, ${rangeLabel(ts.from, ts.to)}. Total ${formatNumber(ts[series])}.`, height: 240, unit, emptyMessage: empty });
    setHTML(tableEl('series'), dataTable(rows.map((r) => ({ label: r.title, value: r.value })), [{ day: 'Day', week: 'Week', month: 'Month' }[ts.group_by], what]));

    const hours = hourRows(ts.hour_of_day, series);
    $('[data-hours-sub]').textContent = `${what} by hour, local time`;
    columnChart(chartEl('hours'), hours, { ariaLabel: `${what} by hour of the day.`, height: 200, unit, emptyMessage: empty });
    setHTML(tableEl('hours'), dataTable(hours.map((r) => ({ label: r.title, value: r.value })), ['Hour', what]));

    const weekdays = dayOfWeekRows(ts.day_of_week, series);
    $('[data-weekdays-sub]').textContent = `${what} by weekday`;
    columnChart(chartEl('weekdays'), weekdays, { ariaLabel: `${what} by day of the week.`, height: 200, unit, emptyMessage: empty });
    setHTML(tableEl('weekdays'), dataTable(weekdays.map((r) => ({ label: r.title, value: r.value })), ['Day', what]));

    $('[data-opens-note]').hidden = series !== 'opens';
    void showDaysZoneHint($('[data-days-hint]'));
  }

  // ---------------------------------------------------------------- By context, by location (one /breakdown)
  const entries = (list: BreakdownEntry[], label: (name: string) => string = (name) => name) => list.map((e) => ({ label: label(e.name), value: e.count }));
  const numbersOn = (key: string) => $<HTMLInputElement>(`[data-numbers="${key}"]`).checked;

  async function loadBreakdown(key: 'context' | 'location') {
    const first = !panelBody(key).dataset.loaded;
    breakdown ??= source.breakdown(period);
    const request = breakdown;
    if (first) {
      if (key === 'context') {
        ['os', 'browsers', 'devices'].forEach((k) => setHTML(chartEl(k), skeleton('h-36')));
        setHTML(chartEl('referrers'), skeleton('h-40'));
      } else setHTML(chartEl('countries'), skeleton('h-56'));
    } else busy(key, true);
    try {
      const b = await request;
      if (request !== breakdown) return;
      panelState(key);
      if (key === 'context') renderContext(b);
      else renderLocation(b);
      panelBody(key).dataset.loaded = 'true';
    } catch (err) {
      if (request !== breakdown) return;
      breakdown = null;
      panelState(key, err);
    } finally {
      busy(key, false);
    }
  }

  function renderContext(b: Breakdown) {
    const parts = { os: ['Operating system', entries(b.os)], browsers: ['Browser', entries(b.browsers)], devices: ['Device', entries(b.devices, deviceLabel)] } as const;
    for (const [key, [heading, items]] of Object.entries(parts)) {
      donutChart(chartEl(key), items, { unit: CLICKS, showNumbers: numbersOn(key), emptyMessage: 'No clicks in this period' });
      setHTML(tableEl(key), donutTable(items, [heading, 'Clicks']));
    }
    const referrers = entries(b.referrers);
    setHTML(chartEl('referrers'), referrers.length ? barList(referrers, CLICKS, { limit: 10 }) : nothing('No clicks in this period.'));
    setHTML(tableEl('referrers'), dataTable(referrers, ['Referrer', 'Clicks'], { share: true }));
  }

  function renderLocation(b: Breakdown) {
    // Unknown goes last, whatever its count: it isn't a place.
    const places = [...b.countries.filter((c) => c.name !== 'Unknown'), ...b.countries.filter((c) => c.name === 'Unknown')];
    const items = entries(places, (name) => (name === 'Unknown' ? 'Unknown' : countryName(name)));
    setHTML(chartEl('countries'), items.length ? barList(items, CLICKS, { limit: 10 }) : nothing('No clicks in this period.'));
    setHTML(tableEl('countries'), dataTable(items, ['Country', 'Clicks'], { share: true }));
  }

  // ---------------------------------------------------------------- Visits
  const KINDS: Record<LinkVisit['kind'], [string, string]> = { click: ['badge-brand', 'Click'], open: ['badge-info', 'Email open'], bot: ['badge-neutral', 'Bot'] };
  const NO_VISITS: Record<VisitType, string> = { clicks: 'No clicks in this period.', opens: 'No email opens in this period.', bots: 'No bots in this period.', all: 'No visits in this period.' };
  const known = (value: string) => value !== 'Unknown';

  async function loadVisits() {
    const key = `${JSON.stringify(period)}|${visitType}|${visitPage}`;
    if (key === visitsShown) return;
    visitsShown = key;
    if (!$('[data-visits]').firstElementChild) setHTML($('[data-visits]'), skeleton('h-72'));
    else busy('visits', true);
    try {
      const v = await source.visits!(period, visitType, visitPage);
      if (key !== visitsShown) return;
      panelState('visits');
      renderVisits(v);
    } catch (err) {
      if (key !== visitsShown) return;
      visitsShown = '';
      panelState('visits', err);
    } finally {
      busy('visits', false);
    }
  }

  function renderVisits(v: Visits) {
    const first = (v.page - 1) * v.page_size + 1;
    $('[data-visits-count]').textContent = v.visits.length ? `${formatNumber(first)}–${formatNumber(first + v.visits.length - 1)} of ${formatNumber(v.total)}` : '';
    $('[data-pager]').hidden = v.pages <= 1;
    $<HTMLButtonElement>('[data-page="newer"]').disabled = v.page <= 1;
    $<HTMLButtonElement>('[data-page="older"]').disabled = v.page >= v.pages;
    $('[data-page-of]').textContent = `Page ${formatNumber(v.page)} of ${formatNumber(v.pages)}`;
    if (!v.visits.length) {
      setHTML($('[data-visits]'), nothing(NO_VISITS[v.type]));
      return;
    }
    const withKind = v.type === 'all';
    const badge = (visit: LinkVisit) => html`<span class="badge ${KINDS[visit.kind][0]}">${KINDS[visit.kind][1]}</span>`;
    const when = (visit: LinkVisit): RawHTML => {
      const t = visitTime(visit.visited_at);
      return html`<time datetime="${visit.visited_at}" title="${t.long}">${t.short}</time>`;
    };
    const software = (visit: LinkVisit) =>
      known(visit.browser) && known(visit.os) ? `${visit.browser} on ${visit.os}` : known(visit.browser) ? visit.browser : known(visit.os) ? visit.os : '';
    const summary = (visit: LinkVisit) => [known(visit.country) ? countryName(visit.country) : '', software(visit), known(visit.device) ? deviceLabel(visit.device) : ''].filter(Boolean).join(' · ') || 'Unknown';
    setHTML(
      $('[data-visits]'),
      html`<div class="overflow-x-auto rounded-xl border border-line max-md:hidden">
          <table class="table">
            <thead>
              <tr><th scope="col">Date and time</th><th scope="col">Country</th><th scope="col">Browser</th><th scope="col">OS</th><th scope="col">Device</th><th scope="col">Referrer</th>${withKind ? html`<th scope="col">Type</th>` : ''}</tr>
            </thead>
            <tbody>${v.visits.map(
              (visit) => html`<tr>
                <td class="whitespace-nowrap">${when(visit)}</td>
                <td>${known(visit.country) ? countryName(visit.country) : 'Unknown'}</td>
                <td>${visit.browser}</td>
                <td>${visit.os}</td>
                <td>${deviceLabel(visit.device)}</td>
                <td class="max-w-[16rem] truncate" title="${visit.referrer}">${visit.referrer}</td>
                ${withKind ? html`<td>${badge(visit)}</td>` : ''}
              </tr>`,
            )}</tbody>
          </table>
        </div>
        <ul class="divide-y divide-line rounded-xl border border-line md:hidden">${v.visits.map(
          (visit) => html`<li class="grid gap-1 px-4 py-3 text-sm">
            <div class="flex items-center justify-between gap-3"><span class="font-medium text-ink-900">${when(visit)}</span>${withKind ? badge(visit) : ''}</div>
            <p class="text-ink-700">${summary(visit)}</p>
            <p class="truncate text-ink-500">${visit.referrer === 'Direct' ? 'Direct' : known(visit.referrer) ? `From ${visit.referrer}` : 'Unknown referrer'}</p>
          </li>`,
        )}</ul>`,
    );
  }

  // ---------------------------------------------------------------- Tabs and the period
  function loadTab(key: string) {
    if (key === 'time') void loadTime();
    else if (key === 'context' || key === 'location') void loadBreakdown(key);
    else if (hasVisits) void loadVisits();
  }

  const periodRadios = [...document.querySelectorAll<HTMLInputElement>('input[name="period"]')];
  const choice = (p: Period) => ('days' in p && (PERIOD_CHOICES as readonly number[]).includes(p.days) ? String(p.days) : 'custom');

  function syncPeriodControls() {
    periodRadios.forEach((r) => (r.checked = r.value === choice(period)));
    $('[data-custom-label]').textContent = choice(period) === 'custom' ? periodLabel(period) : 'Custom';
    document.querySelectorAll<HTMLInputElement>('input[name="group"]').forEach((r) => (r.checked = r.value === groupBy));
  }

  function setPeriod(next: Period) {
    period = next;
    const query = new URLSearchParams(location.search);
    setPeriodParams(query, period);
    history.replaceState(history.state, '', `${location.pathname}?${query}${location.hash}`);
    groupBy = defaultGroupBy(period);
    timeseries = null;
    breakdown = null;
    visitPage = 1;
    syncPeriodControls();
    void loadTime();
    if (tabs && tabs.current() !== 'time') loadTab(tabs.current());
  }

  // Custom: a popover with two dates, checked as the API would before asking it.
  const rangeMenu = $('#range-menu');
  const rangeForm = $<HTMLFormElement>('[data-range-form]');
  const rangeInput = (name: 'from' | 'to') => rangeForm.elements.namedItem(name) as HTMLInputElement;
  const localToday = () => todayIn(counted?.timezone ?? zone ?? browserZone);
  let rangeApplied = false;
  function openRangeMenu() {
    rangeApplied = false;
    const today = localToday();
    rangeInput('from').max = today;
    rangeInput('to').max = today;
    rangeInput('from').value = 'from' in period ? period.from : (counted?.from ?? '');
    rangeInput('to').value = 'to' in period ? period.to : (counted?.to ?? today);
    $('[data-range-error]').hidden = true;
    rangeMenu.showPopover();
    positionMenu(rangeMenu, $('[data-custom]'));
    rangeInput('from').focus();
  }
  periodRadios.forEach((r) => r.addEventListener('change', () => (r.value === 'custom' ? openRangeMenu() : setPeriod({ days: Number(r.value) }))));
  // "Custom" again while it's the period: change the dates.
  $('[data-custom]').addEventListener('click', (e) => {
    if (choice(period) === 'custom' && !rangeMenu.matches(':popover-open')) {
      e.preventDefault();
      openRangeMenu();
    }
  });
  rangeMenu.addEventListener('toggle', (e) => {
    if ((e as ToggleEvent).newState === 'closed' && !rangeApplied) syncPeriodControls();
  });
  $('[data-range-cancel]').addEventListener('click', () => rangeMenu.hidePopover());
  rangeForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const problem = rangeProblem(rangeInput('from').value, rangeInput('to').value, localToday());
    const error = $('[data-range-error]');
    error.hidden = !problem;
    if (problem) {
      error.textContent = problem;
      return;
    }
    rangeApplied = true;
    rangeMenu.hidePopover();
    setPeriod({ from: rangeInput('from').value, to: rangeInput('to').value });
  });

  document.querySelectorAll<HTMLInputElement>('input[name="group"]').forEach((r) =>
    r.addEventListener('change', () => {
      groupBy = r.value as GroupBy;
      timeseries = null;
      void loadTime();
    }),
  );
  document.querySelectorAll<HTMLInputElement>('input[name="series"]').forEach((r) =>
    r.addEventListener('change', () => {
      series = r.value as Series;
      seriesChosen = true;
      timeseries?.then(renderTime).catch(() => {});
    }),
  );
  if (hasVisits) {
    document.querySelectorAll<HTMLInputElement>('input[name="visit-type"]').forEach((r) =>
      r.addEventListener('change', () => {
        visitType = r.value as VisitType;
        visitPage = 1;
        void loadVisits();
      }),
    );
    $('[data-page="newer"]').addEventListener('click', () => {
      visitPage -= 1;
      void loadVisits();
    });
    $('[data-page="older"]').addEventListener('click', () => {
      visitPage += 1;
      void loadVisits();
    });
  }
  // Export CSV: a link's visits for the period (a campaign has no list of visits, on purpose).
  const exportButton = document.querySelector<HTMLButtonElement>('[data-export]');
  exportButton?.addEventListener('click', async () => {
    if (!source.exportVisits) return;
    setLoading(exportButton, true, '');
    try {
      await source.exportVisits(period, counted);
    } catch (err) {
      toast('Couldn’t export the visits', 'error', { description: errorMessage(err) });
    } finally {
      setLoading(exportButton, false);
    }
  });
  for (const key of ['series', 'hours', 'weekdays', 'os', 'browsers', 'devices', 'referrers', 'countries']) {
    bindChartTableToggle($<HTMLButtonElement>(`[data-table-toggle="${key}"]`), chartEl(key), tableEl(key));
  }
  for (const key of ['os', 'browsers', 'devices']) bindShowNumbers($<HTMLInputElement>(`[data-numbers="${key}"]`), chartEl(key));

  syncPeriodControls();
  tabs = initTabs($('[data-tablist]'), { hash: true, onSelect: loadTab });
  if (tabs.current() !== 'time') void loadTime();

  return {
    setOpens: (any) => ($('[data-series-picker]').hidden = !any),
    setZone: (timezone) => (zone = timezone),
  };
}
