// Phase 6.3 — what every built page must satisfy under the Content-Security-Policy that Astro
// writes into it (astro.config.mjs → security.csp). Used by scripts/check-csp.mjs after each
// build, and unit-tested in tests/csp.test.mjs.

import { createHash } from 'node:crypto';

const CSP_META = /<meta\s+http-equiv="content-security-policy"\s+content="([^"]*)"\s*\/?>/gi;
const INLINE_SCRIPT = /<script(?![^>]*\bsrc\s*=)([^>]*)>([\s\S]*?)<\/script>/gi;
const REQUIRED = {
  'default-src': ["'self'"],
  'object-src': ["'none'"],
  'base-uri': ["'self'"],
  'form-action': ["'self'"],
  'script-src': ["'self'"],
  'img-src': ['https:'],
  'connect-src': ["'self'"],
  // Trusted Types: TrustedHTML at every HTML sink, from the one policy (src/utils/html.ts).
  'require-trusted-types-for': ["'script'"],
  'trusted-types': ['shurly-html'],
};
const FORBIDDEN_IN_SCRIPT_SRC = ["'unsafe-inline'", "'unsafe-eval'"];
// A default policy would catch every sink; more policies, or duplicates, more ways to mint TrustedHTML.
const FORBIDDEN_IN_TRUSTED_TYPES = ["'default'", 'default', '*', "'allow-duplicates'"];

const decode = (text) => text.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&');

/** "a b; c d" → {a: ['b'], c: ['d']} */
export function parsePolicy(policy) {
  const directives = {};
  for (const part of decode(policy).split(';')) {
    const [name, ...values] = part.trim().split(/\s+/);
    if (name) directives[name.toLowerCase()] = values;
  }
  return directives;
}

export const sha256 = (source) => `'sha256-${createHash('sha256').update(source).digest('base64')}'`;

/**
 * @param {string} html a built page
 * @returns {{ skipped: boolean, problems: string[], inlineScripts: number }}
 */
export function checkPage(html) {
  // Astro's redirect pages (a <meta http-equiv="refresh">, no layout) load nothing to govern.
  if (/<meta\s+http-equiv="refresh"/i.test(html)) return { skipped: true, problems: [], inlineScripts: 0 };

  const problems = [];
  const metas = [...html.matchAll(CSP_META)];
  if (metas.length !== 1) {
    return { skipped: false, problems: [`expected one CSP <meta>, found ${metas.length}`], inlineScripts: 0 };
  }
  const meta = metas[0];

  // A CSP <meta> only governs what comes after it: nothing may load or run before it.
  const firstScript = html.search(/<script\b/i);
  const firstPreload = html.search(/<link\b[^>]*\brel="(?:modulepreload|preload)"/i);
  if (firstScript !== -1 && firstScript < meta.index) problems.push('a <script> comes before the CSP <meta>');
  if (firstPreload !== -1 && firstPreload < meta.index) problems.push('a preload <link> comes before the CSP <meta>');

  const policy = parsePolicy(meta[1]);
  for (const [directive, values] of Object.entries(REQUIRED)) {
    for (const value of values) {
      if (!policy[directive]?.includes(value)) problems.push(`${directive} lacks ${value}`);
    }
  }
  for (const value of FORBIDDEN_IN_SCRIPT_SRC) {
    if (policy['script-src']?.includes(value)) problems.push(`script-src allows ${value}`);
  }
  for (const value of FORBIDDEN_IN_TRUSTED_TYPES) {
    if (policy['trusted-types']?.includes(value)) problems.push(`trusted-types allows ${value}`);
  }

  let inlineScripts = 0;
  for (const [, attrs, body] of html.matchAll(INLINE_SCRIPT)) {
    if (/type\s*=\s*"application\/(?:ld\+)?json"/i.test(attrs)) continue; // data, not run
    inlineScripts++;
    if (!policy['script-src']?.includes(sha256(body))) {
      problems.push(`inline script not covered by script-src (add it to src/inline-scripts.mjs): ${body.trim().slice(0, 60)}…`);
    }
  }

  // <style> elements keep their hashes: only style attributes may be inline (style-src-attr).
  if (!policy['style-src']?.includes("'unsafe-inline'")) {
    for (const [, body] of html.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)) {
      if (!policy['style-src']?.includes(sha256(body))) problems.push(`inline <style> not covered by style-src: ${body.trim().slice(0, 60)}…`);
    }
  }

  // Outside script and style bodies: no inline event handlers, no javascript: URLs.
  const markup = html.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, '');
  const handler = markup.match(/<[a-z][^>]*?\son[a-z]+\s*=/i);
  if (handler) problems.push(`inline event handler: ${handler[0].slice(0, 80)}`);
  const jsUrl = markup.match(/\b(?:href|src|action|formaction)\s*=\s*["']?\s*javascript:/i);
  if (jsUrl) problems.push(`javascript: URL: ${jsUrl[0]}`);

  return { skipped: false, problems, inlineScripts };
}
