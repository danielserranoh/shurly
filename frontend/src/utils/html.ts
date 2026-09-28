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

// Trusted Types (Phase 6.3). Every built page's CSP requires TrustedHTML at the DOM's HTML
// sinks (`require-trusted-types-for 'script'`) and allows one policy, this one. Its createHTML
// returns its input unchanged, and that's safe only because of this module's invariant:
// nothing reaches it but markup `html` built (every interpolation escaped; `raw()` only on
// our own markup, as tests/no-raw-html.test.mjs checks) or `escapeHtml` output. setHTML and
// toElement are its only callers, and they escape anything that isn't RawHTML. The policy
// stays in this module: not exported, not on window. Without Trusted Types (older browsers,
// Node), markup stays a plain string.
interface HtmlPolicy {
  createHTML(markup: string): unknown;
}
interface TrustedTypesFactory {
  createPolicy(name: string, rules: { createHTML(markup: string): string }): HtmlPolicy;
}
const htmlPolicy: HtmlPolicy | null =
  (globalThis as { trustedTypes?: TrustedTypesFactory }).trustedTypes?.createPolicy('shurly-html', {
    createHTML: (markup) => markup,
  }) ?? null;

/** Markup for an HTML sink: TrustedHTML where the browser enforces Trusted Types. */
function trusted(markup: string): string {
  // TrustedHTML is what the sink wants; TypeScript's DOM types only know strings.
  return (htmlPolicy ? htmlPolicy.createHTML(markup) : markup) as string;
}

/** RawHTML's markup as it is; anything else, a string included, escaped. */
function markupOf(markup: RawHTML | string): string {
  return isRaw(markup) ? markup.value : escapeHtml(markup);
}

/** Replace an element's children with rendered markup. */
export function setHTML(el: Element | null, markup: RawHTML | string): void {
  if (!el) return;
  el.innerHTML = trusted(markupOf(markup));
}

/** Parse rendered markup into a single element (the first element child). */
export function toElement<T extends Element = HTMLElement>(markup: RawHTML): T {
  const template = document.createElement('template');
  template.innerHTML = trusted(markupOf(markup).trim());
  return template.content.firstElementChild as T;
}
