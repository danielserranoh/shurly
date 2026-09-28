// Phase 3.12 — the avatar crop, as numbers: zoom and pan an image under a square frame
// (the circle's bounding box) that must always be covered. Covering the square covers the
// circle, and the saved avatar is that square, so no corner can come out empty.
//
// Screen pixels throughout, except where a function says image pixels.

export interface Frame {
  /** The image's natural size. */
  width: number;
  height: number;
  /** The frame's side: the circle's diameter. */
  size: number;
}

export interface Crop {
  /** Screen pixels per image pixel. */
  zoom: number;
  /** Where the image's top-left corner sits, from the frame's top-left. Never positive. */
  x: number;
  y: number;
}

/** How far in the zoom goes, from the smallest one. */
export const MAX_ZOOM_FACTOR = 4;

/** The smallest zoom: the image's shorter side fills the frame ("cover"). */
export function minZoom({ width, height, size }: Frame): number {
  return size / Math.min(width, height);
}

export function maxZoom(frame: Frame): number {
  return minZoom(frame) * MAX_ZOOM_FACTOR;
}

/** The crop the dialog opens with: the smallest zoom, centred. */
export function initialCrop(frame: Frame): Crop {
  const zoom = minZoom(frame);
  return clampCrop({ zoom, x: (frame.size - frame.width * zoom) / 2, y: (frame.size - frame.height * zoom) / 2 }, frame);
}

/** `crop`, made to cover: zoom within its range, and no image edge inside the frame. */
export function clampCrop(crop: Crop, frame: Frame): Crop {
  const zoom = Math.min(Math.max(crop.zoom, minZoom(frame)), maxZoom(frame));
  // Between "right/bottom edge on the frame's" and "left/top edge on the frame's".
  const axis = (offset: number, length: number) => Math.min(0, Math.max(frame.size - length * zoom, offset));
  return { zoom, x: axis(crop.x, frame.width), y: axis(crop.y, frame.height) };
}

/** Moved by (dx, dy). */
export function panBy(crop: Crop, dx: number, dy: number, frame: Frame): Crop {
  return clampCrop({ zoom: crop.zoom, x: crop.x + dx, y: crop.y + dy }, frame);
}

/** Zoomed to `zoom`, keeping the image point under (atX, atY) where it is: the frame's centre unless given. */
export function zoomTo(crop: Crop, zoom: number, frame: Frame, atX = frame.size / 2, atY = frame.size / 2): Crop {
  const target = Math.min(Math.max(zoom, minZoom(frame)), maxZoom(frame));
  const imageX = (atX - crop.x) / crop.zoom;
  const imageY = (atY - crop.y) / crop.zoom;
  return clampCrop({ zoom: target, x: atX - imageX * target, y: atY - imageY * target }, frame);
}

/** The zoom slider's position for `zoom`, 0 to 1. Logarithmic: each step zooms by the same ratio. */
export function sliderFor(zoom: number, frame: Frame): number {
  return Math.log(zoom / minZoom(frame)) / Math.log(MAX_ZOOM_FACTOR);
}

/** The zoom for a slider position, 0 to 1. */
export function zoomFor(position: number, frame: Frame): number {
  return minZoom(frame) * MAX_ZOOM_FACTOR ** Math.min(Math.max(position, 0), 1);
}

/** The square of the image the frame shows, in image pixels: what the saved avatar is drawn from. */
export function sourceSquare(crop: Crop, frame: Frame): { x: number; y: number; size: number } {
  return { x: -crop.x / crop.zoom, y: -crop.y / crop.zoom, size: frame.size / crop.zoom };
}
