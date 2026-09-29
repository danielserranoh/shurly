// Phase 6.4 — what a browser error report says (error-reporter.ts sends it; the API logs it: server/app/client_errors.py).
// Short and on one line, with no query or fragment in any URL, and nothing a person typed or stored: the message, the
// script and where in it, and the page's path.

export type ErrorKind = 'error' | 'rejection' | 'csp';

export interface ErrorReport {
  kind: ErrorKind;
  message: string;
  source: string;
  page: string;
}

/** Reports a page load sends at most; the API limits them per IP as well. */
export const MAX_REPORTS = 5;
// The API's caps.
const MAX_MESSAGE = 500;
const MAX_SOURCE = 300;
const MAX_PAGE = 300;

// Control characters (a NUL among them) become spaces: one line, which no log or proxy refuses.
const CONTROL = /[\u0000-\u001f\u007f]/g;
// A URL's query and fragment, up to where the URL ends in running text.
const URL_TAIL = /(https?:\/\/[^\s?#]+)[?#][^\s,;)\]'"]*/g;

/** One line, without control characters or any URL's query and fragment, cut to `max`. */
export function clean(text: string, max: number): string {
  return text.replace(CONTROL, ' ').replace(URL_TAIL, '$1').replace(/\s+/g, ' ').trim().slice(0, max);
}

/** Where in a script: our own by their path, without a query, with line and column when known. */
export function sourceOf(file: string | undefined, line: number, col: number, origin: string): string {
  if (!file) return '';
  let where = file.split(/[?#]/)[0];
  if (where.startsWith(`${origin}/`)) where = where.slice(origin.length);
  return clean(line ? `${where}:${line}${col ? `:${col}` : ''}` : where, MAX_SOURCE);
}

/** A rejected promise's reason: an error by its name and message, text as it is, anything else by its type only. */
export function describeReason(reason: unknown): string {
  if (reason instanceof Error) return `${reason.name}: ${reason.message}`;
  if (typeof reason === 'string') return reason;
  return reason === undefined ? 'undefined' : Object.prototype.toString.call(reason);
}

/** A CSP or Trusted Types block: the directive, and what it blocked, by its origin only. */
export function cspMessage(directive: string, blocked: string): string {
  let what = blocked || 'inline';
  try {
    if (/^https?:/.test(what)) what = new URL(what).origin;
  } catch {
    // Not a URL after all: say it as it is.
  }
  return `${directive} blocked ${what}`;
}

/** Errors that aren't ours: a browser extension's, and a cross-origin script's bare "Script error.". */
export function isForeign(message: string, file: string | undefined): boolean {
  if (/^(Uncaught )?Script error\.?$/i.test(message.trim())) return true;
  return /^(chrome|moz|safari|safari-web|ms-browser)-extension:/i.test(file ?? '');
}

/** The report to send, or null when there's nothing to say. The page by its path only. */
export function report(kind: ErrorKind, message: string, source: string, page: string): ErrorReport | null {
  const text = clean(message, MAX_MESSAGE);
  if (!text) return null;
  return { kind, message: text, source, page: clean(page.split(/[?#]/)[0], MAX_PAGE) || '/' };
}

/** Lets through MAX_REPORTS reports a page load at most, each once. */
export function reportGate(max = MAX_REPORTS): (report: ErrorReport | null) => boolean {
  const seen = new Set<string>();
  return (r) => {
    if (!r) return false;
    const key = `${r.kind}|${r.message}|${r.source}`;
    if (seen.size >= max || seen.has(key)) return false;
    seen.add(key);
    return true;
  };
}
