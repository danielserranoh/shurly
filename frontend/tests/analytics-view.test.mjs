// Phase 3.16 — the link's analytics page: its period (in the address, and as the API's query), the custom
// range's checks (the API's 422s, said before asking), and the labels of its charts (src/utils/analytics-view.ts).
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  DEFAULT_PERIOD,
  bucketRows,
  dayOfWeekRows,
  defaultGroupBy,
  deviceLabel,
  hourRows,
  periodDays,
  periodFromParams,
  periodLabel,
  periodQuery,
  rangeLabel,
  rangeProblem,
  setPeriodParams,
  visitTime,
} from '../src/utils/analytics-view.ts';

const TODAY = '2026-09-29';
const params = (query) => new URLSearchParams(query);

describe('the period', () => {
  test('comes from the address: ?period=N or ?from=…&to=…, else 30 days', () => {
    assert.deepEqual(periodFromParams(params('code=abc&period=7'), TODAY), { days: 7 });
    assert.deepEqual(periodFromParams(params('code=abc&from=2026-09-01&to=2026-09-10'), TODAY), { from: '2026-09-01', to: '2026-09-10' });
    assert.deepEqual(periodFromParams(params('code=abc'), TODAY), DEFAULT_PERIOD);
    assert.deepEqual(DEFAULT_PERIOD, { days: 30 });
  });

  test('anything the API would refuse falls back to the default', () => {
    for (const query of ['period=0', 'period=732', 'period=abc', 'from=2026-09-10', 'from=2026-09-10&to=2026-09-01', 'from=2026-10-01&to=2026-10-02', 'from=2024-01-01&to=2026-09-01']) {
      assert.deepEqual(periodFromParams(params(query), TODAY), DEFAULT_PERIOD, query);
    }
  });

  test('goes to the API as period= or from= and to=', () => {
    assert.equal(periodQuery({ days: 90 }), 'period=90');
    assert.equal(periodQuery({ from: '2026-09-01', to: '2026-09-10' }), 'from=2026-09-01&to=2026-09-10');
  });

  test('replaces the other form in the address, and leaves the rest alone', () => {
    const p = params('code=abc&domain=go.griddo.io&period=7');
    setPeriodParams(p, { from: '2026-09-01', to: '2026-09-10' });
    assert.equal(p.toString(), 'code=abc&domain=go.griddo.io&from=2026-09-01&to=2026-09-10');
    setPeriodParams(p, { days: 90 });
    assert.equal(p.toString(), 'code=abc&domain=go.griddo.io&period=90');
  });

  test('counts its days, both ends included', () => {
    assert.equal(periodDays({ days: 30 }), 30);
    assert.equal(periodDays({ from: '2026-09-01', to: '2026-09-30' }), 30);
    assert.equal(periodDays({ from: '2026-03-28', to: '2026-03-30' }), 3); // across a DST change
  });

  test('starts by day up to 31 days, by week beyond', () => {
    assert.equal(defaultGroupBy({ days: 7 }), 'day');
    assert.equal(defaultGroupBy({ days: 30 }), 'day');
    assert.equal(defaultGroupBy({ from: '2026-08-01', to: '2026-08-31' }), 'day');
    assert.equal(defaultGroupBy({ days: 90 }), 'week');
  });

  test('reads as "Last 30 days", or as its dates', () => {
    assert.equal(periodLabel({ days: 30 }), 'Last 30 days');
    assert.equal(periodLabel({ days: 1 }), 'Today');
    assert.equal(periodLabel({ from: '2026-09-01', to: '2026-09-28' }), 'Sep 1 – Sep 28, 2026');
    assert.equal(rangeLabel('2025-12-20', '2026-01-10'), 'Dec 20, 2025 – Jan 10, 2026');
    assert.equal(rangeLabel('2026-09-28', '2026-09-28'), 'Sep 28, 2026');
  });
});

describe('a custom range', () => {
  test('is fine within two years, ending today or earlier', () => {
    assert.equal(rangeProblem('2026-09-01', '2026-09-29', TODAY), null);
    assert.equal(rangeProblem('2024-09-28', '2026-09-28', TODAY), null); // 731 days, the most
  });

  test('says what the API would refuse, before asking', () => {
    assert.equal(rangeProblem('', '2026-09-10', TODAY), 'Pick both dates.');
    assert.equal(rangeProblem('2026-09-10', '2026-09-01', TODAY), 'The start date comes after the end date.');
    assert.equal(rangeProblem('2026-09-30', '2026-10-05', TODAY), 'The range starts after today.');
    assert.equal(rangeProblem('2024-09-27', '2026-09-28', TODAY), 'Pick a range of two years or less.'); // 732
  });

  test('may end after today: the API counts up to today', () => {
    assert.equal(rangeProblem('2026-09-20', '2026-10-20', TODAY), null);
  });
});

describe('the charts', () => {
  const stats = (...rows) => rows.map(([start, end, clicks, opens]) => ({ start, end, clicks, opens }));

  test('days: weekdays and "Today" in a week, dates beyond', () => {
    const week = bucketRows(stats(['2026-09-23', '2026-09-23', 1, 0], ['2026-09-29', '2026-09-29', 4, 2]), 'day', 'clicks', TODAY);
    assert.deepEqual(
      week.map((r) => [r.label, r.value, r.title]),
      [
        ['Wed', 1, 'Wednesday, Sep 23'],
        ['Today', 4, 'Tuesday, Sep 29'],
      ],
    );
    const month = bucketRows(stats(...Array.from({ length: 10 }, (_, i) => [`2026-09-${String(i + 1).padStart(2, '0')}`, `2026-09-${String(i + 1).padStart(2, '0')}`, i, 0])), 'day', 'clicks', TODAY);
    assert.equal(month[0].label, 'Sep 1');
  });

  test('weeks and months say where they start, and their clipped ends', () => {
    const weeks = bucketRows(stats(['2026-07-01', '2026-07-05', 2, 0], ['2026-07-06', '2026-07-12', 0, 1]), 'week', 'opens', TODAY);
    assert.deepEqual(
      weeks.map((r) => [r.label, r.value, r.title]),
      [
        ['Jul 1', 0, 'Jul 1 – Jul 5'],
        ['Jul 6', 1, 'Jul 6 – Jul 12'],
      ],
    );
    const months = bucketRows(stats(['2026-07-15', '2026-07-31', 3, 0], ['2026-08-01', '2026-08-31', 5, 0]), 'month', 'clicks', TODAY);
    assert.deepEqual(
      months.map((r) => [r.label, r.title]),
      [
        ['Jul', 'Jul 15 – Jul 31'],
        ['Aug', 'August 2026'],
      ],
    );
  });

  test('hours of the day and days of the week', () => {
    const hours = hourRows(Array.from({ length: 24 }, (_, hour) => ({ hour, clicks: hour, opens: 0 })), 'clicks');
    assert.equal(hours.length, 24);
    assert.deepEqual([hours[0].label, hours[0].title], ['12 AM', '12 AM – 1 AM']);
    assert.deepEqual([hours[14].label, hours[14].value], ['2 PM', 14]);
    const days = dayOfWeekRows(Array.from({ length: 7 }, (_, i) => ({ day: i + 1, clicks: 0, opens: i })), 'opens');
    assert.deepEqual(
      days.map((d) => d.label),
      ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    );
    assert.deepEqual([days[6].title, days[6].value], ['Sunday', 6]);
  });

  test('devices read as words, and anything new as it comes', () => {
    assert.deepEqual(
      ['desktop', 'mobile', 'tablet', 'other', 'Unknown', 'smart-tv'].map(deviceLabel),
      ['Desktop', 'Mobile', 'Tablet', 'Other devices', 'Unknown', 'smart-tv'],
    );
  });
});

describe('a visit', () => {
  test("reads at the time the API gives, in the viewer's zone, not the browser's", () => {
    assert.deepEqual(visitTime('2026-09-27T23:54:12+02:00'), { short: 'Sep 27, 11:54 PM', long: 'Sunday, Sep 27, 2026, 11:54 PM' });
    assert.deepEqual(visitTime('2026-01-05T00:07:00-05:00'), { short: 'Jan 5, 12:07 AM', long: 'Monday, Jan 5, 2026, 12:07 AM' });
  });
});
