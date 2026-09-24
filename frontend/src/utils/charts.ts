// Lightweight, dependency-free charts rendered as SVG/HTML.
// Specs (design/DESIGN_SYSTEM.md → Data viz): single series in brand-400, Griddo blue (5.1:1 on white),
// bars ≤ 24px with 4px rounded data-ends and square baselines, hairline solid grid,
// one selective direct label (the max), hover/focus tooltip per column, table-view twin.

import { escapeHtml, html, setHTML, type RawHTML } from './html';
import { formatCompact, formatNumber } from './format';

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

  const grid = ticks
    .map(
      (t) => `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(t)}" y2="${y(t)}" stroke="${t === 0 ? BASELINE : GRID}" stroke-width="1" shape-rendering="crispEdges"/>
      <text x="${pad.left - 8}" y="${y(t) + 4}" text-anchor="end" class="fill-ink-500 num" font-size="11">${escapeHtml(formatCompact(t))}</text>`,
    )
    .join('');

  const cols = data
    .map((d, i) => {
      const cx = pad.left + slot * i + slot / 2;
      const h = (d.value / top) * plotH;
      const x = cx - barW / 2;
      const label = `${d.title}: ${formatNumber(d.value)} ${d.value === 1 ? one : many}`;
      const tip =
        i === maxIndex
          ? `<text x="${cx}" y="${y(d.value) - 7}" text-anchor="middle" class="fill-ink-700 num" font-size="11" font-weight="600">${escapeHtml(formatNumber(d.value))}</text>`
          : '';
      return `<g class="chart-col outline-none" tabindex="0" role="listitem" aria-label="${escapeHtml(label)}" data-i="${i}">
        <rect x="${pad.left + slot * i}" y="${pad.top}" width="${slot}" height="${plotH}" fill="transparent"/>
        <path class="chart-bar" d="${columnPath(x, y(d.value), barW, h, 4)}" fill="${SERIES}"/>
        ${d.value === 0 ? `<rect x="${x}" y="${y(0) - 2}" width="${barW}" height="2" rx="1" fill="${BASELINE}"/>` : ''}
        ${tip}
        <text x="${cx}" y="${height - 8}" text-anchor="middle" class="fill-ink-500" font-size="11">${escapeHtml(d.label)}</text>
      </g>`;
    })
    .join('');

  container.style.position = 'relative';
  container.innerHTML = `
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(opts.ariaLabel)}" class="block overflow-visible">
      ${grid}
      <g role="list">${cols}</g>
    </svg>
    <div data-chart-tip hidden class="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg bg-ink-950 px-2.5 py-1.5 text-center shadow-lg"></div>
    ${max === 0 ? `<p class="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center text-sm font-medium text-ink-500">${escapeHtml(opts.emptyMessage ?? 'No clicks in this period yet')}</p>` : ''}`;

  const tipEl = container.querySelector<HTMLElement>('[data-chart-tip]')!;
  const show = (g: SVGGElement) => {
    const d = data[Number(g.dataset.i)];
    tipEl.innerHTML = `<p class="text-sm font-semibold text-white num">${escapeHtml(formatNumber(d.value))} <span class="font-normal text-ink-300">${escapeHtml(d.value === 1 ? one : many)}</span></p><p class="text-xs text-ink-400">${escapeHtml(d.title)}</p>`;
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

/** Table twin for any single-series chart (accessibility + exact values). */
export function dataTable(rows: { label: string; value: number }[], headers: [string, string]): RawHTML {
  return html`<table class="table">
    <thead><tr><th scope="col">${headers[0]}</th><th scope="col" class="text-right">${headers[1]}</th></tr></thead>
    <tbody>${rows.map((r) => html`<tr><td>${r.label}</td><td class="num text-right font-medium">${formatNumber(r.value)}</td></tr>`)}</tbody>
  </table>`;
}

export interface BarListItem {
  label: string;
  value: number;
  href?: string;
  sublabel?: string;
}

/** Ranked horizontal bars (countries, top links). Value sits at the bar tip. */
export function barList(items: BarListItem[], unit: [string, string] = ['click', 'clicks']): RawHTML {
  const max = Math.max(1, ...items.map((i) => i.value));
  return html`<ol class="grid gap-3">
    ${items.map((item) => {
      const pct = Math.max(1.5, (item.value / max) * 100);
      const label = item.href
        ? html`<a class="truncate font-medium text-ink-900 hover:underline" href="${item.href}">${item.label}</a>`
        : html`<span class="truncate font-medium text-ink-900">${item.label}</span>`;
      return html`<li class="grid grid-cols-[minmax(0,11rem)_1fr] items-center gap-4 text-sm max-sm:grid-cols-1 max-sm:gap-1.5">
        <div class="flex min-w-0 flex-col">${label}${item.sublabel ? html`<span class="truncate text-xs text-ink-500">${item.sublabel}</span>` : ''}</div>
        <div class="flex items-center gap-2.5" aria-label="${formatNumber(item.value)} ${item.value === 1 ? unit[0] : unit[1]}">
          <span class="h-2.5 rounded-r-[4px] bg-brand-400" style="width:${pct.toFixed(1)}%"></span>
          <span class="num shrink-0 text-xs font-semibold text-ink-700">${formatNumber(item.value)}</span>
        </div>
      </li>`;
    })}
  </ol>`;
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
