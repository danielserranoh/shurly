// Build-time token reader for the styleguide. Values come straight from the
// `@theme` block in src/styles/global.css, so the page can't drift from the source.

import css from '@/styles/global.css?raw';

/** Body of the first `@theme { … }` block (brace-balanced, keyframes included). */
const theme = (() => {
  const at = css.indexOf('@theme');
  const open = css.indexOf('{', at);
  if (at < 0 || open < 0) return css;
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}' && --depth === 0) return css.slice(open + 1, i);
  }
  return css.slice(open + 1);
})();

export interface ColorToken {
  /** Token name without the `--color-` prefix, e.g. "ink-500". */
  name: string;
  /** Scale step ("500") or the surface name ("canvas"). */
  step: string;
  hex: string;
  /** Inline comment next to the token in global.css, if any. */
  note?: string;
}

const HEX = '#[0-9a-fA-F]{3,8}';

export function colorScale(scale: string): ColorToken[] {
  const re = new RegExp(`--color-${scale}-(\\d+):\\s*(${HEX})\\s*;[ \\t]*(?:/\\*\\s*(.*?)\\s*\\*/)?`, 'g');
  return [...theme.matchAll(re)].map((m) => ({ name: `${scale}-${m[1]}`, step: m[1], hex: m[2].toLowerCase(), note: m[3] || undefined }));
}

export function namedColors(names: string[]): ColorToken[] {
  return names.flatMap((name) => {
    const m = theme.match(new RegExp(`--color-${name}:\\s*(${HEX})\\s*;`));
    return m ? [{ name, step: name, hex: m[1].toLowerCase() }] : [];
  });
}

export function radii(): { name: string; rem: number; px: number }[] {
  return [...theme.matchAll(/--radius-([\w]+):\s*([\d.]+)rem\s*;/g)].map((m) => ({
    name: m[1],
    rem: parseFloat(m[2]),
    px: Math.round(parseFloat(m[2]) * 16 * 10) / 10,
  }));
}

export function shadows(): { name: string; value: string; layers: string[] }[] {
  return [...theme.matchAll(/--shadow-([\w]+):\s*([^;]+);/g)].map((m) => ({ name: m[1], value: m[2].trim(), layers: summarizeShadow(m[2]) }));
}

/** "0 16px 32px -8px rgb(9 13 19 / 0.16), …" → ["y16 blur 32 spread −8 16%", …] */
function summarizeShadow(value: string): string[] {
  return value
    .split(/,(?![^(]*\))/)
    .map((layer) => {
      const nums = [...layer.replace(/rgba?\([^)]*\)/, '').matchAll(/(-?[\d.]+)(?:px)?/g)].map((n) => parseFloat(n[1]));
      const alpha = layer.match(/\/\s*([\d.]+)\s*\)/);
      const [, y = 0, blur = 0, spread = 0] = nums;
      const parts = [`y${y}`, `blur ${blur}`];
      if (spread) parts.push(`spread ${String(spread).replace('-', '−')}`);
      if (alpha) parts.push(`${Math.round(parseFloat(alpha[1]) * 100)}%`);
      return parts.join(' ');
    });
}

export interface Easing {
  name: string;
  value: string;
  points: [number, number, number, number];
}

export function easings(): Easing[] {
  return [...theme.matchAll(/--ease-([\w-]+):\s*cubic-bezier\(([^)]+)\)\s*;/g)].map((m) => {
    const p = m[2].split(',').map((n) => parseFloat(n));
    return { name: m[1], value: `cubic-bezier(${p.join(', ')})`, points: [p[0], p[1], p[2], p[3]] };
  });
}

export function animations(): { name: string; value: string }[] {
  return [...theme.matchAll(/--animate-([\w-]+):\s*([^;]+);/g)].map((m) => ({
    name: m[1],
    value: m[2].trim().replace(/var\(--ease-([\w-]+)\)/g, '$1'),
  }));
}

/** First family of each font stack, without the "Variable" suffix. */
export function fontFamilies(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of theme.matchAll(/--font-([\w-]+):\s*"([^"]+)"/g)) out[m[1]] = m[2].replace(/\s+Variable$/, '');
  return out;
}

/** OpenType features switched on for body text, if any. */
export function bodyFeatures(): string[] {
  const m = css.match(/body\s*\{[^}]*font-feature-settings:\s*([^;]+);/);
  return m ? [...m[1].matchAll(/"([^"]+)"/g)].map((f) => f[1]) : [];
}

// ---------------------------------------------------------------------------
// WCAG 2 contrast
// ---------------------------------------------------------------------------

function channel(v: number): number {
  const c = v / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  let h = hex.replace('#', '');
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  const [r, g, b] = [0, 2, 4].map((i) => channel(parseInt(h.slice(i, i + 2), 16)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** "4.8:1" — one decimal, like the notes in global.css. */
export function ratio(a: string, b: string): string {
  return `${(Math.round(contrast(a, b) * 10) / 10).toFixed(1)}:1`;
}

export const WHITE = '#ffffff';
