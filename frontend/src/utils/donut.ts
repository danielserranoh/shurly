// The donut chart's data and geometry: which slices, in which colours, and the arcs that draw them.
// No imports, so node's tests load it as is (tests/donut.test.mjs); charts.ts renders it.
//
// One hue, per the chart rule (design/DESIGN_SYSTEM.md → Charts): the brand ramp, alternating light
// and dark so neighbouring slices never look alike (and nothing depends on telling red from green),
// with the tail in grey. White gaps between slices do the rest.

export interface DonutItem {
  label: string;
  value: number;
}

export interface DonutSlice extends DonutItem {
  /** 0–1 of the total. */
  share: number;
  /** Whole percent, the same the table gives the item (roundedPercents over every item); Other's is the
   *  sum of its members', so the legend adds up to 100 and never disagrees with the table. */
  percent: number;
  /** Where the slice starts and ends, in turns: 0 is 12 o'clock, clockwise. */
  start: number;
  end: number;
  color: string;
  /** How many items the "Other" slice stands for; 0 for a named one. */
  others: number;
}

/** Slices at most: four blues, then a grey tail. */
export const MAX_SLICES = 5;
export const OTHER_LABEL = 'Other';
export const SLICE_COLORS = ['var(--color-brand-400)', 'var(--color-brand-800)', 'var(--color-brand-300)', 'var(--color-brand-600)'];
export const TAIL_COLOR = 'var(--color-ink-400)';

/** Items ranked by value (the name breaking ties), without empty ones. */
export function rankItems(items: DonutItem[]): DonutItem[] {
  return items.filter((i) => i.value > 0).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
}

/**
 * The slices for `items`: the top four in blue, and a grey fifth that is either the fifth item or,
 * with more, "Other" for everything after the top four.
 */
export function donutSlices(items: DonutItem[]): DonutSlice[] {
  const ranked = rankItems(items);
  const total = ranked.reduce((sum, i) => sum + i.value, 0);
  if (total === 0) return [];
  const percents = roundedPercents(ranked.map((i) => i.value));
  const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
  const named = ranked.length > MAX_SLICES ? ranked.slice(0, MAX_SLICES - 1) : ranked;
  const rest = ranked.slice(named.length);
  const parts: Array<DonutItem & { others: number; percent: number }> = named.map((i, index) => ({ ...i, others: 0, percent: percents[index] }));
  if (rest.length) {
    const tail = { value: sum(rest.map((i) => i.value)), percent: sum(percents.slice(named.length)) };
    parts.push({ label: OTHER_LABEL, ...tail, others: rest.length });
  }

  let turn = 0;
  return parts.map((part, index) => {
    const start = turn;
    turn = index === parts.length - 1 ? 1 : turn + part.value / total;
    const tail = index === MAX_SLICES - 1;
    return { ...part, share: part.value / total, start, end: turn, color: tail ? TAIL_COLOR : SLICE_COLORS[index] };
  });
}

/** Whole percents that add up to 100 (largest remainder), so a table's shares always sum right. */
export function roundedPercents(values: number[]): number[] {
  const total = values.reduce((sum, v) => sum + v, 0);
  if (total <= 0) return values.map(() => 0);
  const exact = values.map((v) => (v / total) * 100);
  const floors = exact.map(Math.floor);
  let missing = 100 - floors.reduce((sum, v) => sum + v, 0);
  const byRemainder = exact.map((e, i) => ({ i, r: e - floors[i] })).sort((a, b) => b.r - a.r || a.i - b.i);
  for (const { i } of byRemainder) {
    if (missing-- <= 0) break;
    floors[i] += 1;
  }
  return floors;
}

const n = (value: number) => String(Number(value.toFixed(2)) + 0);

function point(cx: number, cy: number, r: number, turn: number): string {
  const angle = turn * 2 * Math.PI - Math.PI / 2;
  return `${n(cx + r * Math.cos(angle))},${n(cy + r * Math.sin(angle))}`;
}

/**
 * The ring segment between `start` and `end` (turns), `r` the outer radius and `inner` the hole's.
 * A whole turn is drawn as a ring (two circles, filled even-odd) so it has no seam.
 */
export function arcPath(cx: number, cy: number, r: number, inner: number, start: number, end: number): string {
  if (end - start >= 1) {
    const half = start + 0.5;
    return (
      `M${point(cx, cy, r, start)}A${r},${r} 0 1 1 ${point(cx, cy, r, half)}A${r},${r} 0 1 1 ${point(cx, cy, r, start)}Z` +
      `M${point(cx, cy, inner, start)}A${inner},${inner} 0 1 0 ${point(cx, cy, inner, half)}A${inner},${inner} 0 1 0 ${point(cx, cy, inner, start)}Z`
    );
  }
  const large = end - start > 0.5 ? 1 : 0;
  return (
    `M${point(cx, cy, r, start)}A${r},${r} 0 ${large} 1 ${point(cx, cy, r, end)}` +
    `L${point(cx, cy, inner, end)}A${inner},${inner} 0 ${large} 0 ${point(cx, cy, inner, start)}Z`
  );
}
