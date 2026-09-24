// Safe HTML templating for client-rendered UI.
//
// Link titles, Open Graph data scraped from third-party pages, tag names and campaign
// CSV values are all untrusted. `html` escapes every interpolation unless it is wrapped
// in `raw()` (only for markup we produced ourselves, e.g. icons or nested `html` results).

const RAW = Symbol('raw');

export interface RawHTML {
  [RAW]: true;
  value: string;
}

export function raw(value: string): RawHTML {
  return { [RAW]: true, value };
}

function isRaw(v: unknown): v is RawHTML {
  return typeof v === 'object' && v !== null && (v as RawHTML)[RAW] === true;
}

export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

type Interpolation = unknown;

function render(v: Interpolation): string {
  if (v === null || v === undefined || v === false) return '';
  if (Array.isArray(v)) return v.map(render).join('');
  if (isRaw(v)) return v.value;
  return escapeHtml(v);
}

/** Tagged template: `html\`<p>${userText}</p>\`` → RawHTML with userText escaped. */
export function html(strings: TemplateStringsArray, ...values: Interpolation[]): RawHTML {
  let out = strings[0];
  values.forEach((v, i) => {
    out += render(v) + strings[i + 1];
  });
  return raw(out);
}

/** Only allow http(s) URLs in href/src attributes; anything else becomes "#". */
export function safeUrl(url: string | null | undefined): string {
  if (!url) return '#';
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : '#';
  } catch {
    return '#';
  }
}

/** Replace an element's children with rendered markup. */
export function setHTML(el: Element | null, markup: RawHTML | string): void {
  if (!el) return;
  el.innerHTML = typeof markup === 'string' ? escapeHtml(markup) : markup.value;
}

/** Parse rendered markup into a single element (the first element child). */
export function toElement<T extends Element = HTMLElement>(markup: RawHTML): T {
  const template = document.createElement('template');
  template.innerHTML = markup.value.trim();
  return template.content.firstElementChild as T;
}
