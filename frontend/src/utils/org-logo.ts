// Phase 3.14.4 — the organization's logo, on the frontend: fetched, saved and removed as any image
// the API keeps (stored-image.ts), and shown in an organization mark, the name's initial until the
// logo has loaded. Owners and admins change it (image-file.ts `canChangeLogo`); every member sees it.

import { removeStoredImage, storedImageUrl, uploadStoredImage } from './stored-image';
import type { Organization } from './types';
import { initialOf } from './viewer';

export { canChangeLogo, logoFileProblem } from './image-file';

const LOGO = '/api/v1/organization/logo';

/** An object URL for this version of the logo; null without one, or when it can't be loaded. */
export const logoUrl = (version: string | null | undefined) => storedImageUrl(LOGO, version);

/** Save `image` as the logo, as picked (the API fits it within 512×512); answers the organization. */
export const uploadLogo = (image: Blob) => uploadStoredImage<Organization>(LOGO, image);

export const removeLogo = () => removeStoredImage(LOGO);

/** What a mark shows: the name, for its initial, and the logo's version. */
export type Marked = Pick<Organization, 'name' | 'logo_version'>;

const painting = new WeakMap<HTMLElement, number>();

/**
 * Paint an organization mark (`[data-org-mark]`, with a `[data-org-initial]` and an
 * `img[data-org-logo]` inside): the name's initial, replaced by the logo once it has loaded. No
 * logo, or one that fails: the initial. The mark carries `data-has-logo` while the logo shows, for
 * its background. Resolves once painted.
 */
export async function paintOrgMark(mark: HTMLElement, org: Marked): Promise<void> {
  const run = (painting.get(mark) ?? 0) + 1;
  painting.set(mark, run);
  const initial = mark.querySelector<HTMLElement>('[data-org-initial]')!;
  const logo = mark.querySelector<HTMLImageElement>('img[data-org-logo]')!;
  initial.textContent = initialOf(org.name);
  const url = await logoUrl(org.logo_version);
  if (painting.get(mark) !== run) return; // a newer paint came meanwhile
  if (url) logo.src = url;
  else logo.removeAttribute('src');
  logo.hidden = !url;
  initial.hidden = Boolean(url);
  mark.toggleAttribute('data-has-logo', Boolean(url));
}
