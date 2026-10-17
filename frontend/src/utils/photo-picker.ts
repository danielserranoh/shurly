// Phase 3.12.10, 3.14.6 — drives the photo dialog (components/ui/PhotoPicker.astro), for the avatar and the
// organization's logo. What the circle shows, the buttons and what Save does: src/utils/photo-picker-state.ts.
// Positioning a new photo (drag or arrow keys to move; wheel, pinch, slider or + and − to zoom), with the
// circle always covered: src/utils/avatar-crop.ts. The positioned square is drawn on a canvas and encoded as
// `exportFor` says: the avatar a WebP, the logo a PNG with its transparency.

import { errorMessage } from './api';
import { initialCrop, panBy, sliderFor, sourceSquare, zoomFor, zoomTo, type Crop, type Frame } from './avatar-crop';
import { exportFor, openPicker, pickerView, pickNew, removePhoto, saveAction, type PickerKind } from './photo-picker-state';
import { closeDialog, openDialog, setLoading } from './ui';

/** Arrow keys move this many pixels (five times as many with Shift). */
const STEP = 8;
/** + and − zoom by this factor. */
const ZOOM_STEP = 1.1;
const SLIDER_MAX = 1000;

export interface PhotoPickerOptions {
  /** The dialog: a `ui/PhotoPicker` on the page. */
  dialog: HTMLDialogElement;
  kind: PickerKind;
  /** There's a photo saved now. */
  hasCurrent: boolean;
  /** Its URL (a blob: URL from the API's cache, never revoked here); null while it can't be shown. */
  currentUrl: string | null;
  /** The pseudo-avatar's letter, for no photo. */
  initial: string;
  /** Why a picked or dropped file can't be used, in the page's words; null when it can. */
  fileProblem: (file: File) => string | null;
  /** Dropped on the trigger: opened in the dialog for positioning, or its problem shown there. */
  file?: File;
  /** Save after Change: send the positioned square. A throw shows its message in the dialog, which stays open. */
  upload: (square: Blob) => Promise<void>;
  /** Save after Remove: delete the saved photo. A throw shows its message too. */
  remove: () => Promise<void>;
}

/** What Save did; null when the dialog was closed without saving (Cancel, Esc, the close button). */
export type PickResult = 'uploaded' | 'removed' | null;

/** Ends the dialog still open, if any: a new one never shares it with it. */
let endOpenPicker: (() => void) | null = null;

/** Open the dialog. Resolves once it closes, with what was saved. */
export function pickPhoto(options: PhotoPickerOptions): Promise<PickResult> {
  endOpenPicker?.();
  const { dialog, kind } = options;
  const $ = <T extends HTMLElement = HTMLElement>(selector: string) => dialog.querySelector<T>(selector)!;
  const frameEl = $('[data-picker-frame]');
  const initialEl = $('[data-picker-initial]');
  const currentImg = $<HTMLImageElement>('[data-picker-current]');
  const cropImg = $<HTMLImageElement>('[data-picker-crop]');
  const help = $('[data-picker-help]');
  const zoomRow = $('[data-picker-zoom-row]');
  const slider = $<HTMLInputElement>('[data-picker-zoom]');
  const change = $<HTMLButtonElement>('[data-picker-change]');
  const remove = $<HTMLButtonElement>('[data-picker-remove]');
  const fileInput = $<HTMLInputElement>('[data-picker-file]');
  const error = $('[data-picker-error]');
  const save = $<HTMLButtonElement>('[data-picker-save]');

  let state = openPicker(options.hasCurrent);
  /** The new photo, while there's one: its object URL, its size and where it sits. */
  let fresh: { url: string; frame: Frame; crop: Crop } | null = null;
  let finished = false;

  const showError = (message: string | null) => {
    error.textContent = message ?? '';
    error.hidden = !message;
  };

  const render = () => {
    const view = pickerView(state);
    const currentShown = view.shows === 'current' && Boolean(options.currentUrl);
    frameEl.dataset.shows = view.shows;
    initialEl.hidden = view.shows === 'new' || currentShown;
    currentImg.hidden = !currentShown;
    cropImg.hidden = view.shows !== 'new';
    frameEl.toggleAttribute('data-positioning', view.positioning);
    if (view.positioning) frameEl.tabIndex = 0;
    else frameEl.removeAttribute('tabindex');
    frameEl.setAttribute('aria-label', (view.positioning ? frameEl.dataset.labelPositioning : frameEl.dataset.labelIdle) ?? '');
    help.textContent = (view.positioning ? help.dataset.positioning : help.dataset.idle) ?? '';
    zoomRow.hidden = !view.positioning;
    remove.hidden = !view.canRemove;
    save.disabled = !view.canSave;
  };

  /** Moves the new photo to `crop`. */
  const place = (crop: Crop) => {
    if (!fresh) return;
    fresh.crop = crop;
    cropImg.style.width = `${fresh.frame.width}px`;
    cropImg.style.height = `${fresh.frame.height}px`;
    cropImg.style.transform = `translate(${crop.x}px, ${crop.y}px) scale(${crop.zoom})`;
    slider.value = String(Math.round(sliderFor(crop.zoom, fresh.frame) * SLIDER_MAX));
  };

  const dropFresh = () => {
    if (!fresh) return;
    cropImg.removeAttribute('src');
    URL.revokeObjectURL(fresh.url);
    fresh = null;
  };

  /** A file picked or dropped: checked, opened, and positioned in the circle. The one before stays if it can't be. */
  const take = async (file: File | undefined) => {
    showError(null);
    if (!file) return;
    const problem = options.fileProblem(file);
    if (problem) {
      showError(problem);
      return;
    }
    const url = URL.createObjectURL(file);
    let size: { width: number; height: number };
    try {
      size = await opened(url);
    } catch {
      URL.revokeObjectURL(url);
      showError('That image can’t be opened. Try another one.');
      return;
    }
    if (finished) {
      URL.revokeObjectURL(url);
      return;
    }
    dropFresh();
    cropImg.src = url;
    // Measured now the dialog is open: the circle's side on this screen.
    const frame: Frame = { ...size, size: frameEl.clientWidth };
    fresh = { url, frame, crop: initialCrop(frame) };
    state = pickNew(state);
    render();
    place(fresh.crop);
    frameEl.focus();
  };

  frameEl.dataset.shows = 'initials';
  initialEl.textContent = options.initial;
  if (options.currentUrl) currentImg.src = options.currentUrl;
  else currentImg.removeAttribute('src');
  showError(null);
  render();
  openDialog(dialog);
  change.focus();

  return new Promise<PickResult>((resolve) => {
    const listening = new AbortController();
    const on = { signal: listening.signal };
    const finish = (result: PickResult) => {
      if (finished) return;
      finished = true;
      endOpenPicker = null;
      listening.abort();
      setLoading(save, false);
      // After the closing animation, so the photo doesn't vanish while it plays.
      const cleanUp = () => {
        dropFresh();
        currentImg.removeAttribute('src'); // the API's cache keeps its URL: not revoked
        frameEl.removeAttribute('data-dragging');
      };
      if (dialog.open) void closeDialog(dialog).then(cleanUp);
      else cleanUp();
      resolve(result);
    };
    const pointAt = (e: { clientX: number; clientY: number }) => {
      const box = frameEl.getBoundingClientRect();
      return { x: e.clientX - box.left, y: e.clientY - box.top };
    };

    // Drag with one pointer, pinch with two: only a new photo moves.
    const pointers = new Map<number, { x: number; y: number }>();
    frameEl.addEventListener('pointerdown', (e) => {
      if (!fresh) return;
      frameEl.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, pointAt(e));
    }, on);
    frameEl.addEventListener('pointermove', (e) => {
      const before = pointers.get(e.pointerId);
      if (!before || !fresh) return;
      const { frame, crop } = fresh;
      const now = pointAt(e);
      if (pointers.size === 1) {
        place(panBy(crop, now.x - before.x, now.y - before.y, frame));
      } else {
        const other = [...pointers].find(([id]) => id !== e.pointerId)?.[1];
        if (other) {
          const spread = (a: { x: number; y: number }) => Math.hypot(a.x - other.x, a.y - other.y);
          if (spread(before) > 0) {
            place(zoomTo(crop, crop.zoom * (spread(now) / spread(before)), frame, (now.x + other.x) / 2, (now.y + other.y) / 2));
          }
        }
      }
      pointers.set(e.pointerId, now);
    }, on);
    const lift = (e: PointerEvent) => pointers.delete(e.pointerId);
    frameEl.addEventListener('pointerup', lift, on);
    frameEl.addEventListener('pointercancel', lift, on);

    frameEl.addEventListener('wheel', (e) => {
      if (!fresh) return;
      e.preventDefault();
      const at = pointAt(e);
      place(zoomTo(fresh.crop, fresh.crop.zoom * Math.exp(-e.deltaY * 0.0015), fresh.frame, at.x, at.y));
    }, { ...on, passive: false });

    frameEl.addEventListener('keydown', (e) => {
      if (!fresh) return;
      const { frame, crop } = fresh;
      const step = e.shiftKey ? STEP * 5 : STEP;
      // The photo moves the way the arrow points, as when dragged.
      const move = ({ ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] } as const)[
        e.key as 'ArrowLeft'
      ];
      if (move) place(panBy(crop, move[0], move[1], frame));
      else if (e.key === '+' || e.key === '=') place(zoomTo(crop, crop.zoom * ZOOM_STEP, frame));
      else if (e.key === '-' || e.key === '_') place(zoomTo(crop, crop.zoom / ZOOM_STEP, frame));
      else return;
      e.preventDefault();
    }, on);

    slider.addEventListener('input', () => {
      if (fresh) place(zoomTo(fresh.crop, zoomFor(Number(slider.value) / SLIDER_MAX, fresh.frame), fresh.frame));
    }, on);

    // Change: the file picker. A file dropped anywhere on the dialog loads too (never opened by the browser).
    change.addEventListener('click', () => fileInput.click(), on);
    fileInput.addEventListener('change', () => {
      const file = fileInput.files?.[0];
      fileInput.value = ''; // the same file can be picked again
      void take(file);
    }, on);
    const dragging = (yes: boolean) => frameEl.toggleAttribute('data-dragging', yes);
    dialog.addEventListener('dragover', (e) => {
      if (!e.dataTransfer?.types.includes('Files')) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      dragging(true);
    }, on);
    dialog.addEventListener('dragleave', (e) => {
      if (!dialog.contains(e.relatedTarget as Node | null)) dragging(false);
    }, on);
    dialog.addEventListener('drop', (e) => {
      if (!e.dataTransfer?.types.includes('Files')) return;
      e.preventDefault();
      dragging(false);
      void take(e.dataTransfer.files[0]);
    }, on);

    // Remove: the initial shows, and Save deletes. Focus moves on, as the button hides.
    remove.addEventListener('click', () => {
      showError(null);
      state = removePhoto(state);
      if (state.pending !== 'new') dropFresh();
      render();
      change.focus();
    }, on);

    save.addEventListener('click', async () => {
      const action = saveAction(state);
      if (!action) return;
      showError(null);
      setLoading(save, true, 'Saving…');
      try {
        if (action === 'upload') await options.upload(await drawSquare(cropImg, fresh!, kind));
        else await options.remove();
      } catch (err) {
        setLoading(save, false);
        showError(errorMessage(err));
        return;
      }
      finish(action === 'upload' ? 'uploaded' : 'removed');
    }, on);

    // Cancel or the close button, Esc, or anything else that closes it: nothing changes. Not the close
    // event alone: a hidden tab holds it back.
    endOpenPicker = () => finish(null);
    dialog.addEventListener('click', (e) => {
      if ((e.target as HTMLElement).closest('[data-dialog-close]')) finish(null);
    }, on);
    dialog.addEventListener('cancel', () => finish(null), on);
    dialog.addEventListener('close', () => finish(null), on);

    if (options.file) void take(options.file);
  });
}

/** The image at `url`'s natural size, once it has loaded. `load`, not decode(): browsers hold decode() back in a hidden tab. */
function opened(url: string): Promise<{ width: number; height: number }> {
  const probe = new Image();
  return new Promise((resolve, reject) => {
    probe.onload = () => (probe.naturalWidth && probe.naturalHeight ? resolve({ width: probe.naturalWidth, height: probe.naturalHeight }) : reject(new Error('empty')));
    probe.onerror = () => reject(new Error('unreadable'));
    probe.src = url;
  });
}

/** The square the circle shows, drawn and encoded as `exportFor(kind)` says. A canvas starts transparent, so a logo's alpha stays. */
function drawSquare(img: HTMLImageElement, { crop, frame }: { crop: Crop; frame: Frame }, kind: PickerKind): Promise<Blob> {
  const square = sourceSquare(crop, frame);
  const out = exportFor(kind, square.size);
  const canvas = document.createElement('canvas');
  canvas.width = out.side;
  canvas.height = out.side;
  const context = canvas.getContext('2d');
  if (!context) return Promise.reject(new Error('This browser can’t crop images.'));
  context.imageSmoothingQuality = 'high';
  context.drawImage(img, square.x, square.y, square.size, square.size, 0, 0, out.side, out.side);
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('That couldn’t be saved. Try again.'))), out.type, out.quality),
  );
}
