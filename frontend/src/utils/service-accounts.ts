// Phase 10.2 — a service account's token settings and its audit, in words (ServiceAccountsSection.astro, the
// styleguide). Pure: no DOM and no API, so tests/service-accounts.test.mjs runs it as is.
//
// - What a token may do (its scopes), as a form's checkboxes and as a short summary on its line.
// - Where it may be used from (allowed IP ranges): the form's textarea, one range per line.
// - Its expiry: a year from today unless changed.
// - Why it needs attention (warnings), and the menu's dot.
// - What the account did, or what was done to it (the audit), as a sentence and who for. Phase 10.3: an owner's
//   override (deleting a link the account manages) reads "Deleted a link anyway (owner override)", with the reason
//   they typed on a second line, escaped by the `html` tag: it's free text.

import { html, type RawHTML } from './html';
import type { AuditEvent, AuditPerson, ServiceScope, ServiceTokenWarning } from './types';

/** Every scope, in the API's order (server/core/models/service_token.py, SERVICE_SCOPES): the form's checkboxes. */
export const SCOPES: readonly { scope: ServiceScope; label: string; short: string }[] = [
  { scope: 'urls:read', label: 'See links, campaigns and tags', short: 'see links' },
  { scope: 'urls:write', label: 'Make and change links, campaigns and redirect rules', short: 'change links' },
  { scope: 'urls:delete', label: 'Delete links, campaigns and redirect rules', short: 'delete links' },
  { scope: 'tags:write', label: 'Make, rename and delete tags', short: 'manage tags' },
  { scope: 'analytics:read', label: 'See clicks and analytics', short: 'see analytics' },
  { scope: 'act_on_behalf', label: 'Act for people in the organization', short: 'act for people' },
];

export const ALL_SCOPES: readonly ServiceScope[] = SCOPES.map((s) => s.scope);

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/**
 * A token's scopes on its line: "All permissions" with every one, else the short names in the API's order,
 * "See links, change links". A scope this page doesn't know shows as it is.
 */
export function scopeSummary(scopes: readonly string[]): string {
  const known = SCOPES.filter((s) => scopes.includes(s.scope));
  if (known.length === SCOPES.length) return 'All permissions';
  const unknown = scopes.filter((scope) => !SCOPES.some((s) => s.scope === scope));
  const parts = [...known.map((s) => s.short), ...unknown];
  return parts.length ? capitalize(parts.join(', ')) : 'No permissions';
}

/** Where a token works from, on its line: '' for any address, the ranges when there are one or two, else a count. */
export function rangesSummary(ranges: readonly string[]): string {
  if (!ranges.length) return '';
  if (ranges.length === 1) return `From ${ranges[0]}`;
  if (ranges.length === 2) return `From ${ranges[0]} and ${ranges[1]}`;
  return `From ${ranges.length} IP ranges`;
}

/**
 * The allowed IP ranges typed in the form: one per line (commas and spaces split them too), blanks dropped, each
 * once. The API checks each is a CIDR and answers a 422 on `allowed_ip_ranges` when one isn't.
 */
export function parseRanges(text: string): string[] {
  const ranges: string[] = [];
  for (const part of text.split(/[\s,;]+/)) {
    if (part && !ranges.includes(part)) ranges.push(part);
  }
  return ranges;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** A date as the date input's value, YYYY-MM-DD, in the viewer's time zone. */
export function localDay(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** The expiry the form starts from: a year from today (Feb 29 gives Feb 28). */
export function defaultExpiryDay(now: Date = new Date()): string {
  const year = now.getFullYear() + 1;
  const lastDay = new Date(year, now.getMonth() + 1, 0).getDate();
  return `${year}-${pad(now.getMonth() + 1)}-${pad(Math.min(now.getDate(), lastDay))}`;
}

/** The end of the day picked, in the viewer's time zone: when the token stops working. */
export function endOfDay(day: string): Date {
  return new Date(`${day}T23:59:59`);
}

/**
 * The form's fields for a 422's: the API names a bad scope by its index (`["body", "scopes", 0]`), which the
 * error parser keeps as "0". Only the scopes are checked one by one, so an index means them.
 */
export function tokenErrorFields(apiFields: Iterable<string>): Record<string, string> {
  const map: Record<string, string> = {};
  for (const field of apiFields) if (/^\d+$/.test(field)) map[field] = 'scopes';
  return map;
}

/** A warning's badge (server/utils/service_accounts.py, token_warnings). */
export const WARNING_LABELS: Record<ServiceTokenWarning, string> = {
  expires_soon: 'Expires soon',
  unused: 'Unused for 90 days',
};

/** What the menu's dot says. */
export function attentionLabel(count: number): string {
  return count === 1 ? '1 service token needs attention' : `${count} service tokens need attention`;
}

// ---------------------------------------------------------------- The audit

/**
 * What happened, as a sentence's start, and the link's code to show after it when there is one. `text` is plain
 * words, or markup (an override's, with its reason's line) built by the escaping `html` tag: either goes straight
 * into an `html` template.
 */
export interface AuditWhat {
  text: string | RawHTML;
  code: string | null;
}

const VERBS: Record<string, string> = { created: 'Created', updated: 'Changed', deleted: 'Deleted' };

function fieldsOf(event: AuditEvent): string[] {
  const fields = event.detail?.fields;
  return Array.isArray(fields) ? fields.map(String) : [];
}

/**
 * Phase 10.3 — an owner deleted a link the account manages, past it (`POST /api/v1/urls/{code}/override-delete`):
 * `url.deleted` with `detail: {override: true, reason}`, the owner as `actor`. The reason, trimmed ('' when there's
 * none); null for any other event.
 */
export function auditOverrideReason(event: AuditEvent): string | null {
  if (event.action !== 'url.deleted' || event.detail?.override !== true) return null;
  const reason = event.detail?.reason;
  return typeof reason === 'string' ? reason.trim() : '';
}

/** An override in words: the link's code when the reader still sees it (it's gone, so rarely), else "a link". */
const overrideWords = (event: AuditEvent) =>
  `Deleted ${event.short_code ? `link ${event.short_code}` : 'a link'} anyway (owner override)`;

/**
 * The event in plain words: "Created link ab12cd", "Changed the tags of a campaign", "Renewed its token". A link
 * that's gone, or that the reader doesn't see, is "a link". An action this page doesn't know shows as it is.
 * Phase 10.3: an owner's override is "Deleted a link anyway (owner override)", the reason quoted on a line below.
 */
export function auditWhat(event: AuditEvent): AuditWhat {
  const [type, verb] = event.action.split('.');
  const fields = fieldsOf(event);
  const tagsOnly = fields.length === 1 && fields[0] === 'tags';
  const plain = (text: string): AuditWhat => ({ text, code: null });
  const reason = auditOverrideReason(event);
  if (reason !== null) {
    if (!reason) return plain(overrideWords(event));
    return {
      text: html`${overrideWords(event)}<span class="mt-0.5 block whitespace-pre-line break-words text-ink-600" data-audit-reason>“${reason}”</span>`,
      code: null,
    };
  }
  switch (type) {
    case 'url': {
      const what = verb === 'updated' && tagsOnly ? 'Changed the tags of' : VERBS[verb];
      if (!what) break;
      return event.short_code ? { text: `${what} link`, code: event.short_code } : plain(`${what} a link`);
    }
    case 'redirect_rule':
      if (verb === 'created') return plain('Added a redirect rule');
      if (VERBS[verb]) return plain(`${VERBS[verb]} a redirect rule`);
      break;
    case 'campaign':
      if (verb === 'updated' && tagsOnly) return plain('Changed the tags of a campaign');
      if (VERBS[verb]) return plain(`${VERBS[verb]} a campaign`);
      break;
    case 'tag':
      if (verb === 'updated' && fields.length === 1 && fields[0] === 'name') return plain('Renamed a tag');
      if (VERBS[verb]) return plain(`${VERBS[verb]} a tag`);
      break;
    case 'service_account':
      if (verb === 'created') return plain('Created the service account');
      if (verb === 'updated') return plain('Changed the service account');
      if (verb === 'removed') return plain('Removed the service account');
      break;
    case 'service_token':
      if (verb === 'created') return plain('Created its token');
      if (verb === 'renewed') return plain('Renewed its token');
      if (verb === 'revoked') return plain('Revoked its token');
      break;
  }
  return plain(event.action);
}

/**
 * The whole sentence, as text: "Created link ab12cd". An override's reason follows on a second line, quoted:
 * "Deleted a link anyway (owner override)\n“The recipient asked us to delete their data”".
 */
export function auditSentence(event: AuditEvent): string {
  const reason = auditOverrideReason(event);
  if (reason !== null) return reason ? `${overrideWords(event)}\n“${reason}”` : overrideWords(event);
  const { text, code } = auditWhat(event);
  return code ? `${text} ${code}` : String(text);
}

/** A person the audit names: their name, else their email; someone deleted keeps only that. */
export function auditPersonName(person: AuditPerson): string {
  if (person.deleted) return 'a deleted person';
  return person.name?.trim() || person.email || 'someone';
}

/**
 * Who it was for or by: "On behalf of Ana García" when the service acted for a person, "By Ana García" for what
 * a person did to the account or its token, '' when the service acted for nobody.
 */
export function auditWho(event: AuditEvent): string {
  if (event.on_behalf_of) return `On behalf of ${auditPersonName(event.on_behalf_of)}`;
  if (event.actor) return `By ${auditPersonName(event.actor)}`;
  return '';
}
