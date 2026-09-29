// Phase 3.12 — the avatar, on the frontend: fetched, saved and removed as any image the API keeps
// (stored-image.ts), checked before the crop as image-file.ts says.

import { removeStoredImage, storedImageUrl, uploadStoredImage } from './stored-image';
import type { Profile } from './types';

export { avatarFileProblem } from './image-file';

const AVATAR = '/api/v1/auth/me/avatar';

/** An object URL for this version of the avatar; null without one, or when it can't be loaded. */
export const avatarUrl = (version: string | null | undefined) => storedImageUrl(AVATAR, version);

/** Save `image` (the cropped square) as the avatar; answers the profile, with its new version. */
export const uploadAvatar = (image: Blob) => uploadStoredImage<Profile>(AVATAR, image);

export const removeAvatar = () => removeStoredImage(AVATAR);
