// Lightweight, dependency-free charts rendered as SVG/HTML.
// Specs (design/DESIGN_SYSTEM.md → Data viz): single series in brand-400, Griddo blue (5.1:1 on white),
// bars ≤ 24px with 4px rounded data-ends and square baselines, hairline solid grid,
// one selective direct label (the max), hover/focus tooltip per column, table-view twin.

import { html, setHTML, type RawHTML } from './html';
import { formatCompact, formatNumber } from './format';
import { arcPath, donutSlices, rankItems, roundedPercents, type DonutItem } from './donut';

export interface ColumnDatum {
  /** Short axis label, e.g. "Tue" */
  label: string;
  value: number;
  /** Tooltip / table heading, e.g. "Tuesday, Nov 4" */
  title: string;
}

export interface ColumnChartOptions {
  height?: number;
  unit?: [singular: string, plural: string];
  ariaLabel: string;
  emptyMessage?: string;
}

const SERIES = 'var(--color-brand-400)';
const GRID = 'var(--color-ink-100)';
const BASELINE = 'var(--color-ink-200)';

function niceStep(raw: number): number {
  if (raw <= 1) return 1;
  const pow = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (m * pow >= raw) return m * pow;
  return 10 * pow;
}

function columnPath(x: number, y: number, w: number, h: number, r: number): string {
  if (h <= 0) return '';
  const rr = Math.min(r, h, w / 2);
  const bottom = y + h;
  return `M${x},${bottom}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${bottom}Z`;
}

const observers = new WeakMap<HTMLElement, ResizeObserver>();

/** Render (and keep responsive) a single-series column chart into `container`. */
export function columnChart(container: HTMLElement, data: ColumnDatum[], opts: ColumnChartOptions): void {
  const draw = () => drawColumns(container, data, opts);
  draw();
  observers.get(container)?.disconnect();
  let lastWidth = container.clientWidth;
  const ro = new ResizeObserver(() => {
    if (Math.abs(container.clientWidth - lastWidth) > 1) {
      lastWidth = container.clientWidth;
      draw();
    }
  });
  ro.observe(container);
  observers.set(container, ro);
}

function drawColumns(container: HTMLElement, data: ColumnDatum[], opts: ColumnChartOptions): void {
  const [one, many] = opts.unit ?? ['click', 'clicks'];
  const width = Math.max(container.clientWidth, 240);
  const height = opts.height ?? 220;
  const pad = { top: 26, right: 4, bottom: 28, left: 34 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const max = Math.max(0, ...data.map((d) => d.value));
  // ~3 intervals of a "nice" integer step, with the top tick snug above the max.
  const step = niceStep(max / 3);
  const top = max === 0 ? 2 : Math.ceil(max / step) * step;
  const ticks = Array.from({ length: Math.round(top / (max === 0 ? 1 : step)) + 1 }, (_, i) => i * (max === 0 ? 1 : step));
  const slot = plotW / Math.max(data.length, 1);
  const barW = Math.min(24, Math.max(6, slot * 0.56));
  const maxIndex = max > 0 ? data.findIndex((d) => d.value === max) : -1;
  const y = (v: number) => pad.top + plotH - (v / top) * plotH;

  const grid = ticks.map(
    (t) => html`<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(t)}" y2="${y(t)}" stroke="${t === 0 ? BASELINE : GRID}" stroke-width="1" shape-rendering="crispEdges"/>
      <text x="${pad.left - 8}" y="${y(t) + 4}" text-anchor="end" class="fill-ink-500 num" font-size="11">${formatCompact(t)}</text>`,
  );

  const cols = data.map((d, i) => {
      const cx = pad.left + slot * i + slot / 2;
      const h = (d.value / top) * plotH;
      const x = cx - barW / 2;
      const label = `${d.title}: ${formatNumber(d.value)} ${d.value === 1 ? one : many}`;
      const tip =
        i === maxIndex
          ? html`<text x="${cx}" y="${y(d.value) - 7}" text-anchor="middle" class="fill-ink-700 num" font-size="11" font-weight="600">${formatNumber(d.value)}</text>`
          : '';
      return html`<g class="chart-col outline-none" tabindex="0" role="listitem" aria-label="${label}" data-i="${i}">
        <rect x="${pad.left + slot * i}" y="${pad.top}" width="${slot}" height="${plotH}" fill="transparent"/>
        <path class="chart-bar" d="${columnPath(x, y(d.value), barW, h, 4)}" fill="${SERIES}"/>
        ${d.value === 0 ? html`<rect x="${x}" y="${y(0) - 2}" width="${barW}" height="2" rx="1" fill="${BASELINE}"/>` : ''}
        ${tip}
        <text x="${cx}" y="${height - 8}" text-anchor="middle" class="fill-ink-500" font-size="11">${d.label}</text>
      </g>`;
  });

  container.style.position = 'relative';
  setHTML(
    container,
    html`
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${opts.ariaLabel}" class="block overflow-visible">
      ${grid}
      <g role="list">${cols}</g>
    </svg>
    <div data-chart-tip hidden class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg bg-ink-950 px-2.5 py-1.5 text-center shadow-lg"></div>
    ${max === 0 ? html`<p class="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-sm font-medium text-ink-500">${opts.emptyMessage ?? 'No clicks in this period yet'}</p>` : ''}`,
  );

  const tipEl = container.querySelector<HTMLElement>('[data-chart-tip]')!;
  const show = (g: SVGGElement) => {
    const d = data[Number(g.dataset.i)];
    setHTML(tipEl, html`<p class="text-sm font-semibold text-white num">${formatNumber(d.value)} <span class="font-normal text-ink-300">${d.value === 1 ? one : many}</span></p><p class="text-xs text-ink-400">${d.title}</p>`);
    const i = Number(g.dataset.i);
    const cx = pad.left + slot * i + slot / 2;
    tipEl.style.left = `${Math.min(Math.max(cx, 60), width - 60)}px`;
    tipEl.style.top = `${Math.max(y(d.value) - 10, 8)}px`;
    tipEl.hidden = false;
  };
  const hide = () => (tipEl.hidden = true);
  container.querySelectorAll<SVGGElement>('.chart-col').forEach((g) => {
    g.addEventListener('pointerenter', () => show(g));
    g.addEventListener('pointerleave', hide);
    g.addEventListener('focus', () => show(g));
    g.addEventListener('blur', hide);
  });
}

/**
 * Table twin for any single-series chart (accessibility + exact values). With `share`, a third column
 * gives each row's whole percent of the total, adding up to 100.
 */
export function dataTable(rows: { label: string; value: number }[], headers: [string, string], opts: { share?: boolean } = {}): RawHTML {
  const percents = opts.share ? roundedPercents(rows.map((r) => r.value)) : [];
  return html`<table class="table">
    <thead><tr><th scope="col">${headers[0]}</th><th scope="col" class="text-right">${headers[1]}</th>${opts.share ? html`<th scope="col" class="text-right">Share</th>` : ''}</tr></thead>
    <tbody>${rows.map(
      (r, i) =>
        html`<tr><td>${r.label}</td><td class="num text-right font-medium">${formatNumber(r.value)}</td>${opts.share ? html`<td class="num text-right text-ink-600">${percents[i]}%</td>` : ''}</tr>`,
    )}</tbody>
  </table>`;
}

// ---------------------------------------------------------------------------
// Donut: shares of one total (operating systems, browsers, devices)
// ---------------------------------------------------------------------------

export interface DonutChartOptions {
  unit?: [singular: string, plural: string];
  emptyMessage?: string;
  /** The legend's counts and percents start visible (the "Show numbers" switch). */
  showNumbers?: boolean;
}

const DONUT = { size: 160, r: 78, inner: 50 };

/**
 * Render a donut and its legend into `container`: up to four slices in blue and a grey tail
 * ("Other" past five), the total in the hole (src/utils/donut.ts). The legend is what screen readers
 * read, numbers included even while they're hidden; the SVG is decoration. Hovering a slice or a key,
 * or focusing a key, lights it up and puts its share in the hole. The table twin lists every item:
 * `donutTable()`.
 */
export function donutChart(container: HTMLElement, items: DonutItem[], opts: DonutChartOptions = {}): void {
  const [one, many] = opts.unit ?? ['click', 'clicks'];
  const units = (v: number) => (v === 1 ? one : many);
  const slices = donutSlices(items);
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const percents = slices.map((s) => s.percent);
  const c = DONUT.size / 2;
  const names = slices.map((s) => (s.others ? `${s.label} (${formatNumber(s.others)})` : s.label));

  const rings = slices.length
    ? slices.map(
        (s, i) =>
          html`<path d="${arcPath(c, c, DONUT.r, DONUT.inner, s.start, s.end)}" fill="${s.color}" fill-rule="evenodd" stroke="var(--color-surface)" stroke-width="2" stroke-linejoin="round" data-i="${i}" class="transition-[opacity,transform] duration-150 motion-reduce:transition-none"/>`,
      )
    : html`<path d="${arcPath(c, c, DONUT.r, DONUT.inner, 0, 1)}" fill="var(--color-ink-100)" fill-rule="evenodd"/>`;

  const legend = slices.length
    ? html`<p class="sr-only">Total: ${formatNumber(total)} ${units(total)}.</p>
      <ul class="grid min-w-0 content-center gap-0.5">
        ${slices.map(
          (s, i) => html`<li tabindex="0" data-i="${i}" class="flex min-w-0 items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition-colors duration-150 data-active:bg-ink-50 motion-reduce:transition-none">
            <svg class="size-2.5 shrink-0" viewBox="0 0 10 10" aria-hidden="true"><circle cx="5" cy="5" r="5" fill="${s.color}"/></svg>
            <span class="min-w-0 truncate text-ink-900" title="${names[i]}">${names[i]}</span>
            <span class="num ml-auto shrink-0 pl-2 text-xs text-ink-600 group-data-[numbers=off]:hidden" aria-hidden="true">${formatNumber(s.value)} · ${percents[i]}%</span>
            <span class="sr-only">: ${formatNumber(s.value)} ${units(s.value)}, ${percents[i]}%</span>
          </li>`,
        )}
      </ul>`
    : html`<p class="text-sm font-medium text-ink-500">${opts.emptyMessage ?? 'No clicks in this period yet'}</p>`;

  setHTML(
    container,
    html`<div class="group @container" data-donut data-numbers="${opts.showNumbers ? 'on' : 'off'}">
      <div class="grid grid-cols-1 items-center gap-4 @min-[20rem]:grid-cols-[auto_minmax(0,1fr)] @min-[20rem]:gap-6">
      <svg viewBox="0 0 ${DONUT.size} ${DONUT.size}" class="mx-auto size-36 overflow-visible @min-[20rem]:mx-0 @min-[24rem]:size-40" aria-hidden="true">
        ${rings}
        <text x="${c}" y="${c + 2}" text-anchor="middle" class="num fill-ink-950" font-size="24" font-weight="600" data-donut-value>${formatNumber(total)}</text>
        <text x="${c}" y="${c + 20}" text-anchor="middle" class="fill-ink-500" font-size="12" data-donut-caption>${units(total)}</text>
      </svg>
      <div class="min-w-0">${legend}</div>
      </div>
    </div>`,
  );
  if (!slices.length) return;

  const paths = [...container.querySelectorAll<SVGPathElement>('path[data-i]')];
  const keys = [...container.querySelectorAll<HTMLElement>('li[data-i]')];
  const value = container.querySelector<SVGTextElement>('[data-donut-value]')!;
  const caption = container.querySelector<SVGTextElement>('[data-donut-caption]')!;
  // The lit slice steps out 3px along its middle; the others fade.
  const nudge = slices.map((s) => {
    const angle = (s.start + s.end) * Math.PI - Math.PI / 2;
    return `translate(${(3 * Math.cos(angle)).toFixed(2)}px, ${(3 * Math.sin(angle)).toFixed(2)}px)`;
  });
  const light = (i: number) => {
    paths.forEach((p, j) => {
      p.style.opacity = j === i ? '' : '0.2';
      p.style.transform = j === i && slices.length > 1 ? nudge[i] : '';
    });
    keys.forEach((k, j) => k.toggleAttribute('data-active', j === i));
    value.textContent = `${percents[i]}%`;
    caption.textContent = `${formatNumber(slices[i].value)} ${units(slices[i].value)}`;
  };
  const reset = () => {
    paths.forEach((p) => {
      p.style.opacity = '';
      p.style.transform = '';
    });
    keys.forEach((k) => k.removeAttribute('data-active'));
    value.textContent = formatNumber(total);
    caption.textContent = units(total);
  };
  [...paths, ...keys].forEach((el) => {
    const i = Number(el.dataset.i);
    el.addEventListener('pointerenter', () => light(i));
    el.addEventListener('pointerleave', reset);
  });
  keys.forEach((k) => {
    k.addEventListener('focus', () => light(Number(k.dataset.i)));
    k.addEventListener('blur', reset);
  });
}

/** The donut's table twin: every item, not grouped into "Other", with its share. */
export function donutTable(items: DonutItem[], headers: [string, string]): RawHTML {
  return dataTable(rankItems(items), headers, { share: true });
}

/** Show or hide the counts and percents in a donut's legend (they stay for screen readers). */
export function setDonutNumbers(container: HTMLElement, on: boolean): void {
  container.querySelector<HTMLElement>('[data-donut]')?.setAttribute('data-numbers', on ? 'on' : 'off');
}

/** Wire a "Show numbers" switch to one or more donuts; they follow it, redrawn or not. */
export function bindShowNumbers(input: HTMLInputElement, ...containers: HTMLElement[]): void {
  const apply = () => containers.forEach((c) => setDonutNumbers(c, input.checked));
  input.addEventListener('change', apply);
  apply();
}

// ---------------------------------------------------------------------------
// Bar list: ranked counts with long labels (countries, referrers, top links)
// ---------------------------------------------------------------------------

export interface BarListItem {
  label: string;
  value: number;
  href?: string;
  sublabel?: string;
}

let barLists = 0;

/**
 * Ranked horizontal bars (countries, referrers, top links). The value sits at the bar tip. With
 * `limit`, the rest wait behind "Show all N" (the button is wired in ui.ts).
 */
export function barList(items: BarListItem[], unit: [string, string] = ['click', 'clicks'], opts: { limit?: number } = {}): RawHTML {
  const max = Math.max(1, ...items.map((i) => i.value));
  const limit = opts.limit && items.length > opts.limit ? opts.limit : items.length;
  const id = `bar-list-${++barLists}`;
  const more = `Show all ${formatNumber(items.length)}`;
  return html`<ol class="grid gap-3" id="${id}">
    ${items.map((item, index) => {
      const pct = Math.max(1.5, (item.value / max) * 100);
      const label = item.href
        ? html`<a class="truncate font-medium text-ink-900 hover:underline" href="${item.href}" title="${item.label}">${item.label}</a>`
        : html`<span class="truncate font-medium text-ink-900" title="${item.label}">${item.label}</span>`;
      return html`<li class="grid grid-cols-[minmax(0,11rem)_1fr] items-center gap-4 text-sm max-sm:grid-cols-1 max-sm:gap-1.5" ${index >= limit ? html`data-extra hidden` : ''}>
        <div class="flex min-w-0 flex-col">${label}${item.sublabel ? html`<span class="truncate text-xs text-ink-500">${item.sublabel}</span>` : ''}</div>
        <div class="flex items-center gap-2.5">
          <span class="h-2.5 rounded-r-[4px] bg-brand-400" style="width:${pct.toFixed(1)}%" aria-hidden="true"></span>
          <span class="num shrink-0 text-xs font-semibold text-ink-700">${formatNumber(item.value)}<span class="sr-only"> ${item.value === 1 ? unit[0] : unit[1]}</span></span>
        </div>
      </li>`;
    })}
  </ol>
  ${limit < items.length ? html`<button type="button" class="btn btn-ghost btn-sm mt-3 -ml-2" data-show-all aria-controls="${id}" aria-expanded="false" data-more="${more}">${more}</button>` : ''}`;
}

/** Ratio against a limit, e.g. click-through. Track is a lighter step of the same ramp. */
export function meter(value: number, max: number, label: string): RawHTML {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return html`<div role="meter" aria-label="${label}" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${value}" class="h-2 w-full overflow-hidden rounded-full bg-brand-100">
    <div class="h-full rounded-full bg-brand-400 transition-[width] duration-700 ease-snappy" style="width:${pct.toFixed(1)}%"></div>
  </div>`;
}

/** 2px sparkline in the de-emphasis hue; the latest point in the accent. */
export function sparkline(values: number[], width = 96, height = 28): RawHTML {
  if (values.length < 2) return html``;
  const max = Math.max(1, ...values);
  const stepX = (width - 6) / (values.length - 1);
  const pts = values.map((v, i) => [3 + i * stepX, height - 3 - (v / max) * (height - 6)] as const);
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
  const [lx, ly] = pts[pts.length - 1];
  return html`<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true" class="overflow-visible">
    <path d="${d}" fill="none" stroke="var(--color-ink-300)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="4" fill="var(--color-brand-400)" stroke="#fff" stroke-width="2"/>
  </svg>`;
}

/** Swap a chart card between chart and table views. */
export function bindChartTableToggle(button: HTMLButtonElement, chart: HTMLElement, table: HTMLElement): void {
  button.addEventListener('click', () => {
    const showTable = table.hidden;
    table.hidden = !showTable;
    chart.hidden = showTable;
    button.setAttribute('aria-pressed', String(showTable));
    const label = button.querySelector('[data-label]');
    if (label) label.textContent = showTable ? 'Chart' : 'Table';
  });
}

export { setHTML };
