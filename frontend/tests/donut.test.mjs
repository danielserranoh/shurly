// The donut chart's data and geometry (src/utils/donut.ts): which slices, in which colours, and the
// arcs that draw them. The rendering around it lives in charts.ts.
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { arcPath, donutSlices, MAX_SLICES, OTHER_LABEL, roundedPercents, SLICE_COLORS, TAIL_COLOR } from '../src/utils/donut.ts';

const items = (...pairs) => pairs.map(([label, value]) => ({ label, value }));

describe('donutSlices', () => {
  test('ranks the items by value, the name breaking ties, and drops empty ones', () => {
    const slices = donutSlices(items(['Safari', 5], ['Chrome', 21], ['Edge', 0], ['Firefox', 5]));
    assert.deepEqual(
      slices.map((s) => [s.label, s.value]),
      [
        ['Chrome', 21],
        ['Firefox', 5],
        ['Safari', 5],
      ],
    );
  });

  test('turns go round once, in order, from the top', () => {
    const slices = donutSlices(items(['a', 1], ['b', 2], ['c', 1]));
    assert.equal(slices[0].start, 0);
    for (let i = 1; i < slices.length; i++) assert.equal(slices[i].start, slices[i - 1].end);
    assert.equal(slices.at(-1).end, 1);
    assert.deepEqual(
      slices.map((s) => s.share),
      [0.5, 0.25, 0.25],
    );
  });

  test('up to five slices keep their names; the fifth, the tail, is grey', () => {
    const slices = donutSlices(items(['a', 9], ['b', 8], ['c', 7], ['d', 6], ['e', 5]));
    assert.equal(slices.length, MAX_SLICES);
    assert.deepEqual(
      slices.map((s) => s.label),
      ['a', 'b', 'c', 'd', 'e'],
    );
    assert.deepEqual(
      slices.map((s) => s.color),
      [...SLICE_COLORS, TAIL_COLOR],
    );
    assert.ok(slices.every((s) => s.others === 0));
  });

  test('past five, the tail is "Other": everything after the top four, and how many that is', () => {
    const slices = donutSlices(items(['a', 9], ['b', 8], ['c', 7], ['d', 6], ['e', 5], ['f', 4], ['g', 1]));
    assert.equal(slices.length, MAX_SLICES);
    const other = slices.at(-1);
    assert.equal(other.label, OTHER_LABEL);
    assert.equal(other.value, 10);
    assert.equal(other.others, 3);
    assert.equal(other.color, TAIL_COLOR);
  });

  test('neighbouring blues alternate light and dark, so no two neighbours look alike', () => {
    assert.deepEqual(SLICE_COLORS, ['var(--color-brand-400)', 'var(--color-brand-800)', 'var(--color-brand-300)', 'var(--color-brand-600)']);
    assert.equal(TAIL_COLOR, 'var(--color-ink-400)');
  });

  test("a slice's percent is the table's for that item, and Other's is the sum of its members'", () => {
    const list = items(['Chrome', 21], ['Safari', 8], ['Edge', 4], ['Firefox', 2], ['Samsung Internet', 1], ['Opera', 1], ['DuckDuckGo', 1]);
    const slices = donutSlices(list);
    // The table (every item): 55, 21, 10, 5, 3, 3, 3. Rounding the five slices alone would give Edge 11%.
    assert.deepEqual(
      slices.map((s) => s.percent),
      [55, 21, 10, 5, 9],
    );
    assert.equal(
      slices.reduce((sum, s) => sum + s.percent, 0),
      100,
    );
  });

  test('nothing to show gives no slices', () => {
    assert.deepEqual(donutSlices([]), []);
    assert.deepEqual(donutSlices(items(['a', 0])), []);
  });
});

describe('roundedPercents', () => {
  test('whole percents that add up to 100, the largest remainders rounded up', () => {
    assert.deepEqual(roundedPercents([1, 1, 1]), [34, 33, 33]);
    assert.deepEqual(roundedPercents([21, 8, 4, 1]), [62, 23, 12, 3]);
    assert.equal(
      roundedPercents([3, 3, 3, 3, 3, 3, 3]).reduce((a, b) => a + b, 0),
      100,
    );
  });

  test('all zeros stay zeros', () => {
    assert.deepEqual(roundedPercents([0, 0]), [0, 0]);
    assert.deepEqual(roundedPercents([]), []);
  });
});

describe('arcPath', () => {
  const numbers = (d) => d.match(/-?\d+(\.\d+)?/g).map(Number);

  test('a quarter from the top: out along the rim, back along the hole', () => {
    const d = arcPath(80, 80, 78, 48, 0, 0.25);
    assert.match(d, /^M80,2A78,78 0 0 1 158,80L128,80A48,48 0 0 0 80,32Z$/);
  });

  test('more than half a turn takes the large arc', () => {
    const d = arcPath(80, 80, 78, 48, 0, 0.75);
    assert.match(d, /A78,78 0 1 1 /);
    assert.match(d, /A48,48 0 1 0 /);
  });

  test('a whole turn is a ring: two half circles out, two back, and no seam', () => {
    const d = arcPath(80, 80, 78, 48, 0, 1);
    assert.equal((d.match(/A/g) ?? []).length, 4);
    assert.equal((d.match(/M/g) ?? []).length, 2);
    assert.ok(numbers(d).every((n) => Number.isFinite(n)));
  });
});
