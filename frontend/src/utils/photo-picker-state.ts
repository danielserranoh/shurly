// Phase 3.12.10, 3.14.6 — the photo dialog's rules, as data: what the circle shows, which buttons
// there are, and what Save does. Shared by the avatar ("Profile photo") and the organization's logo
// ("Organization logo"); src/utils/photo-picker.ts draws it. No imports, so the unit tests run it as is.
//
// Nothing changes until Save: Change and Remove only say what Save will do, and Cancel (or Esc)
// leaves the photo there was.

/** What Save will do: upload a new, positioned photo, or delete the current one. Null: nothing yet. */
export type Pending = 'new' | 'removed' | null;

export interface PickerState {
  /** There's a photo saved now (the avatar, or the logo). */
  hasCurrent: boolean;
  pending: Pending;
}

/** What the circle shows: the saved photo (read-only), the initial, or a new photo being positioned. */
export type Shown = 'current' | 'initials' | 'new';

export interface PickerView {
  shows: Shown;
  /** The new photo can be dragged and zoomed, and the zoom control shows. */
  positioning: boolean;
  /** "Remove photo" is there: hidden with nothing to remove (no saved photo, no new one). */
  canRemove: boolean;
  /** "Save photo" is enabled: only once something would change. */
  canSave: boolean;
}

/** The dialog as it opens: the photo there is, or the initial. Nothing to save. */
export function openPicker(hasCurrent: boolean): PickerState {
  return { hasCurrent, pending: null };
}

/** A photo was picked or dropped (and opened): it's positioned in the circle. */
export function pickNew(state: PickerState): PickerState {
  return { ...state, pending: 'new' };
}

/**
 * Remove photo: the initial shows, and Save deletes the saved photo. Without one, removing the new
 * photo only goes back to how the dialog opened.
 */
export function removePhoto(state: PickerState): PickerState {
  return { ...state, pending: state.hasCurrent ? 'removed' : null };
}

/** Save would change something. */
export function hasChanges(state: PickerState): boolean {
  return state.pending === 'new' || (state.pending === 'removed' && state.hasCurrent);
}

/** What Save does: upload the positioned square, delete the saved photo, or nothing. */
export function saveAction(state: PickerState): 'upload' | 'delete' | null {
  if (state.pending === 'new') return 'upload';
  if (state.pending === 'removed' && state.hasCurrent) return 'delete';
  return null;
}

export function pickerView(state: PickerState): PickerView {
  const shows: Shown = state.pending === 'new' ? 'new' : state.pending === 'removed' || !state.hasCurrent ? 'initials' : 'current';
  return {
    shows,
    positioning: shows === 'new',
    canRemove: shows !== 'initials',
    canSave: hasChanges(state),
  };
}

/** What a picker is for: the avatar keeps its format; the logo keeps its transparency, losslessly. */
export type PickerKind = 'avatar' | 'logo';

/** The side of the saved square: the API stores an avatar at 512×512, and fits a logo within 512×512. */
export const OUTPUT_SIDE = 512;

export interface Export {
  /** The type asked of the canvas. Never JPEG, which has no transparency. */
  type: 'image/webp' | 'image/png';
  /** For a lossy type; undefined for a lossless one. */
  quality?: number;
  /** The saved square's side, in pixels. */
  side: number;
}

/**
 * How the positioned square is drawn and encoded, given the side of the source square it shows (in
 * the image's own pixels).
 *
 * - The avatar, as before: a 512 px WebP at 0.9 (a PNG where the browser can't make WebP). WebP keeps
 *   any transparency too, and the API re-encodes it as a 512 px WebP anyway.
 * - The logo: a PNG, lossless and with its alpha, so sharp edges and transparency reach the API as they
 *   are (it keeps both, server/utils/logo.py). Never enlarged, as the API never enlarges one: a small
 *   logo stays small rather than blurred. At most 512 px, so a PNG of about 1 MB at worst, under the
 *   API's 2 MB.
 */
export function exportFor(kind: PickerKind, sourceSide: number): Export {
  if (kind === 'avatar') return { type: 'image/webp', quality: 0.9, side: OUTPUT_SIDE };
  return { type: 'image/png', side: Math.max(1, Math.min(OUTPUT_SIDE, Math.round(sourceSide))) };
}
