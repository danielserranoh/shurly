// Phase 3.12 — the avatar, on the frontend. The API wants the bearer header, which a plain
// <img src> can't send, so the image is fetched through the API client and shown from an
// object URL. Its URL carries the version (`?v=`), immutable in the browser's cache, so
// each version is fetched once, then comes from the cache.

import { apiFetch } from './api';
import type { Profile } from './types';

const AVATAR = '/api/v1/auth/me/avatar';

/** What the file picker and the drop zone take, before the crop. The API checks again. */
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

/** Why `file` can't be an avatar, in the page's words; null when it can. */
export function avatarFileProblem(file: Pick<File, 'type' | 'size'>): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return 'Use a JPEG, PNG or WebP image.';
  if (file.size > MAX_FILE_BYTES) return 'That image is over 10 MB. Try a smaller one.';
  return null;
}

const urls = new Map<string, Promise<string | null>>();

/** An object URL for this version of the avatar; null without one, or when it can't be loaded. */
export function avatarUrl(version: string | null | undefined): Promise<string | null> {
  if (!version) return Promise.resolve(null);
  let url = urls.get(version);
  if (!url) {
    url = apiFetch<Blob>(`${AVATAR}?v=${encodeURIComponent(version)}`, {
      method: 'GET',
      requiresAuth: true,
      responseType: 'blob',
      headers: { Accept: 'image/*' },
    }).then(
      (blob) => URL.createObjectURL(blob),
      () => {
        urls.delete(version); // let a later call try again
        return null;
      },
    );
    urls.set(version, url);
  }
  return url;
}

/** Save `image` (the cropped square) as the avatar; answers the profile, with its new version. */
export function uploadAvatar(image: Blob): Promise<Profile> {
  return apiFetch<Profile>(AVATAR, {
    method: 'PUT',
    requiresAuth: true,
    body: image,
    headers: { 'Content-Type': image.type || 'application/octet-stream' },
  });
}

export function removeAvatar(): Promise<void> {
  return apiFetch<void>(AVATAR, { method: 'DELETE', requiresAuth: true });
}
