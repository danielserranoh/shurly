// Phase 3.12 — drives the avatar crop dialog (components/ui/AvatarCropper.astro): drag or
// arrow keys to move, wheel, pinch, slider or + and − to zoom, and the saved square drawn
// on a canvas. What's allowed is decided by src/utils/avatar-crop.ts.

import { errorMessage } from './api';
import { initialCrop, panBy, sliderFor, sourceSquare, zoomFor, zoomTo, type Crop, type Frame } from './avatar-crop';
import { closeDialog, openDialog, setLoading } from './ui';

/** The side of the saved square. The API stores 512×512 whatever it gets. */
const OUTPUT = 512;
/** Arrow keys move this many pixels (five times as many with Shift). */
const STEP = 8;
/** + and − zoom by this factor. */
const ZOOM_STEP = 1.1;
const SLIDER_MAX = 1000;

/** Ends the crop still open, if any: a new one never shares the dialog with it. */
let endOpenCrop: (() => void) | null = null;

/**
 * Open the dialog on `image`. Save hands the square to `onSave` with the dialog still open:
 * if it throws, its message shows there. True once saved; false when cancelled. Rejects
 * when the image can't be opened.
 */
export async function cropAvatar(image: Blob, onSave: (square: Blob) => Promise<void>): Promise<boolean> {
  endOpenCrop?.();
  const dialog = document.querySelector<HTMLDialogElement>('#avatar-cropper');
  if (!dialog) throw new Error('The crop dialog is missing from this page.');
  const frameEl = dialog.querySelector<HTMLElement>('[data-crop-frame]')!;
  const img = dialog.querySelector<HTMLImageElement>('[data-crop-image]')!;
  const slider = dialog.querySelector<HTMLInputElement>('[data-crop-zoom]')!;
  const save = dialog.querySelector<HTMLButtonElement>('[data-crop-save]')!;
  const error = dialog.querySelector<HTMLElement>('[data-crop-error]')!;

  const url = URL.createObjectURL(image);
  try {
    // `load`, not decode(): browsers hold decode() back while the tab is hidden.
    await new Promise<void>((resolve, reject) => {
      img.onload = () => (img.naturalWidth && img.naturalHeight ? resolve() : reject(new Error('empty')));
      img.onerror = () => reject(new Error('unreadable'));
      img.src = url;
    });
  } catch {
    URL.revokeObjectURL(url);
    img.removeAttribute('src');
    throw new Error('That image can’t be opened. Try another one.');
  } finally {
    img.onload = null;
    img.onerror = null;
  }

  error.hidden = true;
  openDialog(dialog);
  // Measured once open: the frame's side on this screen.
  const frame: Frame = { width: img.naturalWidth, height: img.naturalHeight, size: frameEl.clientWidth };
  let crop = initialCrop(frame);
  const show = (next: Crop) => {
    crop = next;
    img.style.width = `${frame.width}px`;
    img.style.height = `${frame.height}px`;
    img.style.transform = `translate(${crop.x}px, ${crop.y}px) scale(${crop.zoom})`;
    slider.value = String(Math.round(sliderFor(crop.zoom, frame) * SLIDER_MAX));
  };
  show(crop);
  frameEl.focus();

  return new Promise<boolean>((resolve) => {
    const listening = new AbortController();
    const on = { signal: listening.signal };
    let finished = false;
    const finish = (saved: boolean) => {
      if (finished) return;
      finished = true;
      endOpenCrop = null;
      listening.abort();
      // After the closing animation, so the photo doesn't vanish while it plays.
      const cleanUp = () => {
        img.removeAttribute('src');
        URL.revokeObjectURL(url);
      };
      if (dialog.open) void closeDialog(dialog).then(cleanUp);
      else cleanUp();
      resolve(saved);
    };
    const pointAt = (e: { clientX: number; clientY: number }) => {
      const box = frameEl.getBoundingClientRect();
      return { x: e.clientX - box.left, y: e.clientY - box.top };
    };

    // Drag with one pointer, pinch with two.
    const pointers = new Map<number, { x: number; y: number }>();
    frameEl.addEventListener('pointerdown', (e) => {
      frameEl.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, pointAt(e));
    }, on);
    frameEl.addEventListener('pointermove', (e) => {
      const before = pointers.get(e.pointerId);
      if (!before) return;
      const now = pointAt(e);
      if (pointers.size === 1) {
        show(panBy(crop, now.x - before.x, now.y - before.y, frame));
      } else {
        const other = [...pointers].find(([id]) => id !== e.pointerId)?.[1];
        if (other) {
          const spread = (a: { x: number; y: number }) => Math.hypot(a.x - other.x, a.y - other.y);
          if (spread(before) > 0) {
            show(zoomTo(crop, crop.zoom * (spread(now) / spread(before)), frame, (now.x + other.x) / 2, (now.y + other.y) / 2));
          }
        }
      }
      pointers.set(e.pointerId, now);
    }, on);
    const lift = (e: PointerEvent) => pointers.delete(e.pointerId);
    frameEl.addEventListener('pointerup', lift, on);
    frameEl.addEventListener('pointercancel', lift, on);

    frameEl.addEventListener('wheel', (e) => {
      e.preventDefault();
      const at = pointAt(e);
      show(zoomTo(crop, crop.zoom * Math.exp(-e.deltaY * 0.0015), frame, at.x, at.y));
    }, { ...on, passive: false });

    frameEl.addEventListener('keydown', (e) => {
      const step = e.shiftKey ? STEP * 5 : STEP;
      // The photo moves the way the arrow points, as when dragged.
      const move = ({ ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] } as const)[
        e.key as 'ArrowLeft'
      ];
      if (move) show(panBy(crop, move[0], move[1], frame));
      else if (e.key === '+' || e.key === '=') show(zoomTo(crop, crop.zoom * ZOOM_STEP, frame));
      else if (e.key === '-' || e.key === '_') show(zoomTo(crop, crop.zoom / ZOOM_STEP, frame));
      else return;
      e.preventDefault();
    }, on);

    slider.addEventListener('input', () => show(zoomTo(crop, zoomFor(Number(slider.value) / SLIDER_MAX, frame), frame)), on);

    save.addEventListener('click', async () => {
      error.hidden = true;
      setLoading(save, true, 'Saving…');
      try {
        await onSave(await drawSquare(img, crop, frame));
      } catch (err) {
        setLoading(save, false);
        error.textContent = errorMessage(err);
        error.hidden = false;
        return;
      }
      setLoading(save, false);
      finish(true);
    }, on);

    // Cancel or the close button, Esc, or anything else that closes it. Not the close event
    // alone: a hidden tab holds it back.
    endOpenCrop = () => finish(false);
    dialog.addEventListener('click', (e) => {
      if ((e.target as HTMLElement).closest('[data-dialog-close]')) finish(false);
    }, on);
    dialog.addEventListener('cancel', () => finish(false), on);
    dialog.addEventListener('close', () => finish(false), on);
  });
}

/** The square the frame shows, OUTPUT pixels a side: a WebP where the browser can make one, else a PNG. */
function drawSquare(img: HTMLImageElement, crop: Crop, frame: Frame): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = OUTPUT;
  canvas.height = OUTPUT;
  const context = canvas.getContext('2d');
  if (!context) return Promise.reject(new Error('This browser can’t crop images.'));
  context.imageSmoothingQuality = 'high';
  const square = sourceSquare(crop, frame);
  context.drawImage(img, square.x, square.y, square.size, square.size, 0, 0, OUTPUT, OUTPUT);
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('The photo couldn’t be saved. Try again.'))), 'image/webp', 0.9),
  );
}
