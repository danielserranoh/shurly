// Smart redirects (Phase 3.10.2 redirect rules): describe, render and create.

import { apiDelete, apiGet, apiPost } from './api';
import { formatDateTime, prettyUrl } from './format';
import { html, safeUrl, type RawHTML } from './html';
import { icon } from './icons';
import type { RedirectRule, RuleCondition, RuleConditionType } from './types';

export const DEVICES: Record<string, string> = {
  ios: 'iPhone or iPad',
  android: 'Android',
  windows: 'Windows',
  macos: 'Mac',
  linux: 'Linux',
};

export const BROWSERS = ['Chrome', 'Safari', 'Firefox', 'Edge', 'Opera'];

export const LANGUAGES: Record<string, string> = {
  en: 'English',
  es: 'Spanish',
  ca: 'Catalan',
  pt: 'Portuguese',
  fr: 'French',
  de: 'German',
  it: 'Italian',
  nl: 'Dutch',
  eu: 'Basque',
  gl: 'Galician',
};

export const CONDITION_LABELS: Record<RuleConditionType, string> = {
  device: 'Device',
  language: 'Browser language',
  browser: 'Browser',
  query_param: 'Link has parameter',
  after_date: 'On or after',
  before_date: 'Before',
};

export function describeCondition(c: RuleCondition): string {
  const v = String(c.value ?? '');
  switch (c.type) {
    case 'device':
      return `Device is ${DEVICES[v.toLowerCase()] ?? v}`;
    case 'language':
      return `Language is ${LANGUAGES[v.toLowerCase()] ?? v}`;
    case 'browser':
      return `Browser is ${v.charAt(0).toUpperCase()}${v.slice(1)}`;
    case 'query_param': {
      const name = String(c.param ?? c.name ?? '');
      return c.value === undefined || c.value === null || v === '' ? `Link has ?${name}` : `Link has ?${name}=${v}`;
    }
    case 'after_date':
      return `On or after ${formatDateTime(v)}`;
    case 'before_date':
      return `Before ${formatDateTime(v)}`;
    default:
      return `${c.type} ${v}`;
  }
}

const RULE_ICON: Record<RuleConditionType, Parameters<typeof icon>[0]> = {
  device: 'smartphone',
  language: 'languages',
  browser: 'globe',
  query_param: 'hash',
  after_date: 'calendar-clock',
  before_date: 'calendar-clock',
};

export function renderRule(rule: RedirectRule, index: number): RawHTML {
  const first = rule.conditions[0];
  return html`<li class="flex items-start gap-3 rounded-xl border border-line bg-white p-3.5" data-rule="${rule.id}">
    <span class="grid size-8 shrink-0 place-items-center rounded-lg bg-ink-100 text-ink-600">${icon(first ? RULE_ICON[first.type] ?? 'route' : 'route')}</span>
    <div class="min-w-0 flex-1 text-sm">
      <p class="font-medium text-ink-900">${rule.conditions.map(describeCondition).join(' and ')}</p>
      <p class="mt-0.5 flex min-w-0 items-center gap-1.5 text-ink-500">${icon('corner-down-right', 'size-3.5 shrink-0')}
        <a class="truncate hover:text-ink-900" href="${safeUrl(rule.target_url)}" target="_blank" rel="noopener noreferrer">${prettyUrl(rule.target_url)}</a></p>
    </div>
    <span class="badge badge-outline" title="Rules are checked top to bottom; the first match wins">#${index + 1}</span>
    <button type="button" class="btn btn-ghost btn-sm btn-icon" data-delete-rule="${rule.id}" aria-label="Delete rule">${icon('trash')}</button>
  </li>`;
}

export const listRules = (code: string) => apiGet<RedirectRule[]>(`/api/v1/urls/${encodeURIComponent(code)}/rules`);

export const createRule = (code: string, body: { priority: number; conditions: RuleCondition[]; target_url: string }) =>
  apiPost<RedirectRule>(`/api/v1/urls/${encodeURIComponent(code)}/rules`, body);

export const deleteRule = (code: string, id: string) => apiDelete(`/api/v1/urls/${encodeURIComponent(code)}/rules/${encodeURIComponent(id)}`);
