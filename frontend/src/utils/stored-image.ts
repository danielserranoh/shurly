// Phase 3.12, 3.14.4 — an image the API keeps, on the frontend: the avatar and the organization's
// logo. The API wants the bearer header, which a plain <img src> can't send, so the image is
// fetched through the API client and shown from an object URL. Its URL carries the version
// (`?v=`), immutable in the browser's cache, so each version is fetched once, then comes from the
// cache (server/utils/stored_image.py).

import { apiFetch } from './api';

const urls = new Map<string, Promise<string | null>>();

/** An object URL for this version of the image at `path`; null without one, or when it can't be loaded. */
export function storedImageUrl(path: string, version: string | null | undefined): Promise<string | null> {
  if (!version) return Promise.resolve(null);
  const key = `${path}?v=${encodeURIComponent(version)}`;
  let url = urls.get(key);
  if (!url) {
    url = apiFetch<Blob>(key, {
      method: 'GET',
      requiresAuth: true,
      responseType: 'blob',
      headers: { Accept: 'image/*' },
    }).then(
      (blob) => URL.createObjectURL(blob),
      () => {
        urls.delete(key); // let a later call try again
        return null;
      },
    );
    urls.set(key, url);
  }
  return url;
}

/** Save `image` at `path`, as the request body; answers what the API does (with the new version). */
export function uploadStoredImage<T>(path: string, image: Blob): Promise<T> {
  return apiFetch<T>(path, {
    method: 'PUT',
    requiresAuth: true,
    body: image,
    headers: { 'Content-Type': image.type || 'application/octet-stream' },
  });
}

export function removeStoredImage(path: string): Promise<void> {
  return apiFetch<void>(path, { method: 'DELETE', requiresAuth: true });
}
