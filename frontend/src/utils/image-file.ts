// Phase 3.12, 3.14.4 — the checks a picked or dropped image gets before it's sent: the avatar's
// and the organization logo's. The API checks again (server/utils/images.py): these only save a
// round trip, and say it in the page's words. No imports, so the unit tests run it as is.

/** What the file pickers and the drop zones take. No SVG: the API refuses it. */
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

/** The avatar is cropped in the browser first, which makes any photo small: 10 MB in. */
export const AVATAR_MAX_BYTES = 10 * 1024 * 1024;
/** The logo is sent as it is (never cropped), so the API's own limit: 2 MB. */
export const LOGO_MAX_BYTES = 2 * 1024 * 1024;

const megabytes = (bytes: number) => `${Math.round(bytes / (1024 * 1024))} MB`;

/** Why `file` can't be sent, in the page's words; null when it can. */
export function imageFileProblem(file: Pick<File, 'type' | 'size'>, maxBytes: number): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) return 'Use a JPEG, PNG or WebP image.';
  if (file.size > maxBytes) return `That image is over ${megabytes(maxBytes)}. Try a smaller one.`;
  return null;
}

/** Why `file` can't be an avatar; null when it can. */
export const avatarFileProblem = (file: Pick<File, 'type' | 'size'>) => imageFileProblem(file, AVATAR_MAX_BYTES);

/** Why `file` can't be the organization's logo; null when it can. */
export const logoFileProblem = (file: Pick<File, 'type' | 'size'>) => imageFileProblem(file, LOGO_MAX_BYTES);

/** Who may change the organization's logo (server/utils/organization.py): owners and admins. */
export function canChangeLogo(role: string | null | undefined): boolean {
  return role === 'owner' || role === 'admin';
}
