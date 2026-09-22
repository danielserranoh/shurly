// Tags: color mapping, cached list, pill rendering.

import { apiGet, apiPost } from './api';
import { html, type RawHTML } from './html';
import { icon } from './icons';
import type { Tag, TagListResponse } from './types';

/** Predefined categories arrive as Tailwind-style names ("blue-500"); user tags are "gray-500". */
const COLOR_FAMILIES: Record<string, string> = {
  blue: 'blue',
  sky: 'blue',
  indigo: 'purple',
  green: 'green',
  emerald: 'green',
  teal: 'green',
  purple: 'purple',
  violet: 'purple',
  orange: 'orange',
  amber: 'amber',
  yellow: 'amber',
  pink: 'pink',
  rose: 'pink',
  red: 'red',
  lime: 'lime',
};

/** Returns attributes for a `.tag` element: a data-color family or an inline dot color. */
export function tagColorAttrs(color: string): { family?: string; style?: string } {
  if (color.startsWith('#')) return { style: `--tag-dot:${color}` };
  const family = COLOR_FAMILIES[color.split('-')[0]];
  return family ? { family } : {};
}

/** Human names for the predefined categories (keyed by color family). */
export const CATEGORY_LABELS: Record<string, string> = {
  blue: 'Channel',
  green: 'Intent',
  purple: 'Content type',
  orange: 'Audience',
  pink: 'Lifecycle',
};

export function tagPill(tag: Pick<Tag, 'display_name' | 'color' | 'id'>, opts: { href?: string; removable?: boolean; pressed?: boolean; button?: boolean } = {}): RawHTML {
  const { family, style } = tagColorAttrs(tag.color);
  const inner = html`<span>${tag.display_name}</span>${
    opts.removable
      ? html`<span class="tag-remove" role="button" tabindex="0" data-remove-tag="${tag.id}" aria-label="Remove ${tag.display_name}">${icon('x')}</span>`
      : ''
  }`;
  if (opts.href) {
    return html`<a class="tag" href="${opts.href}" data-color="${family ?? ''}" style="${style ?? ''}">${inner}</a>`;
  }
  if (opts.button) {
    return html`<button type="button" class="tag" data-tag-id="${tag.id}" aria-pressed="${opts.pressed ? 'true' : 'false'}" data-color="${family ?? ''}" style="${style ?? ''}">${inner}</button>`;
  }
  return html`<span class="tag" data-color="${family ?? ''}" style="${style ?? ''}">${inner}</span>`;
}

let cache: Promise<Tag[]> | null = null;

export function loadTags(force = false): Promise<Tag[]> {
  if (!cache || force) {
    cache = apiGet<TagListResponse>('/api/v1/tags')
      .then((r) => r.tags)
      .catch((err) => {
        cache = null;
        throw err;
      });
  }
  return cache;
}

export async function createTag(name: string): Promise<Tag> {
  const tag = await apiPost<Tag>('/api/v1/tags', { name });
  cache = null;
  return tag;
}

export function invalidateTags(): void {
  cache = null;
}
