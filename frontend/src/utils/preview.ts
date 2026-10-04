// Phase 8.7 — a link's social preview: the destination page's own, unless someone rewrote a field.
//
// The API keeps two layers per link: og_* hold only what a person typed (the overrides), page_* what
// the page declares, its icon included. Each field shows the override, else the page's.

import type { ShortLink } from './types';

export type PreviewField = 'title' | 'description' | 'image';

type PreviewSource = Pick<ShortLink, 'og_title' | 'og_description' | 'og_image_url'> &
  Partial<Pick<ShortLink, 'page_og_title' | 'page_og_description' | 'page_og_image_url' | 'page_favicon_url'>>;

export interface LinkPreview {
  title: string | null;
  description: string | null;
  image: string | null;
  favicon: string | null;
  /** The fields a person rewrote. */
  overridden: Record<PreviewField, boolean>;
  /** Whether at least one field is rewritten. */
  custom: boolean;
}

const present = (value: string | null | undefined): string | null => (value?.trim() ? value : null);

export function linkPreview(link: PreviewSource): LinkPreview {
  const overridden = {
    title: Boolean(present(link.og_title)),
    description: Boolean(present(link.og_description)),
    image: Boolean(present(link.og_image_url)),
  };
  return {
    title: present(link.og_title) ?? present(link.page_og_title),
    description: present(link.og_description) ?? present(link.page_og_description),
    image: present(link.og_image_url) ?? present(link.page_og_image_url),
    favicon: present(link.page_favicon_url),
    overridden,
    custom: overridden.title || overridden.description || overridden.image,
  };
}

/** What a thumbnail tries, in order: its image, then its icon centred on a tile, then the monogram. */
export type ThumbStep = { kind: 'image'; src: string; badge: string | null } | { kind: 'favicon'; src: string } | { kind: 'monogram' };

export function thumbSteps(link: PreviewSource): ThumbStep[] {
  const { image, favicon } = linkPreview(link);
  const steps: ThumbStep[] = [];
  if (image) steps.push({ kind: 'image', src: image, badge: favicon });
  if (favicon) steps.push({ kind: 'favicon', src: favicon });
  steps.push({ kind: 'monogram' });
  return steps;
}
