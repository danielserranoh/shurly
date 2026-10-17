// Phase 3.12.10, 3.14.6 — what the photo dialog's specs share (profile-photo.spec.ts, organization-logo.spec.ts):
// images drawn here as PNGs (RGBA, so with transparency where a pixel says so), a read of what an <img> shows,
// axe on the page, and the two screens they run on.

import { crc32, deflateSync } from 'node:zlib';

import AxeBuilder from '@axe-core/playwright';
import { devices, expect, type Locator, type Page } from '@playwright/test';

/** Every impact but minor, as a11y.spec.ts. */
const IMPACTS = ['moderate', 'serious', 'critical'];

export async function expectNoIssues(page: Page, name: string) {
  const { violations } = await new AxeBuilder({ page }).analyze();
  const found = violations
    .filter((v) => IMPACTS.includes(v.impact ?? ''))
    .flatMap((v) => v.nodes.map((node) => ({ rule: v.id, impact: v.impact, target: node.target.join(' '), summary: node.failureSummary ?? v.help })));
  expect(found, `axe on ${name}: ${IMPACTS.join(', ')} issues`).toEqual([]);
}

const { defaultBrowserType: _browser, ...pixel } = devices['Pixel 7'];
/** A desktop (1440 px) and a phone (390 px). */
export const DEVICES = [
  { device: 'desktop', options: {} },
  { device: 'phone', options: { ...pixel, viewport: { width: 390, height: 844 } } },
];

type Pixel = [r: number, g: number, b: number, a: number];

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

/** A `width`×`height` PNG, each pixel as `pixel(x, y)` says. */
export function png(width: number, height: number, pixel: (x: number, y: number) => Pixel): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.set([8, 6, 0, 0, 0], 8); // 8 bits, RGBA, deflate, no filter method, no interlace
  const rows = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    const row = y * (width * 4 + 1); // each row starts with its filter: none
    for (let x = 0; x < width; x++) rows.set(pixel(x, y), row + 1 + x * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(rows)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

/** A 300×200 photo: sky blue, a yellow sun in the middle. Not square, so the dialog has something to position. */
export const PHOTO = png(300, 200, (x, y) => (Math.hypot(x - 150, y - 100) < 50 ? [255, 209, 102, 255] : [29, 59, 138, 255]));

/** A 300×200 logo: a navy disc in the middle, transparent around it. */
export const TRANSPARENT_LOGO = png(300, 200, (x, y) => (Math.hypot(x - 150, y - 100) < 60 ? [2, 41, 88, 255] : [0, 0, 0, 0]));

/** What an <img> shows: its natural size, and the RGBA of the pixels at (x, y), each a fraction of its sides. */
export function readImage(img: Locator, points: Array<[number, number]>) {
  return img.evaluate(async (el: HTMLImageElement, at) => {
    await el.decode();
    const canvas = document.createElement('canvas');
    [canvas.width, canvas.height] = [el.naturalWidth, el.naturalHeight];
    const context = canvas.getContext('2d')!;
    context.drawImage(el, 0, 0);
    return {
      size: [el.naturalWidth, el.naturalHeight],
      pixels: at.map(([fx, fy]) => [...context.getImageData(Math.floor(fx * (el.naturalWidth - 1)), Math.floor(fy * (el.naturalHeight - 1)), 1, 1).data]),
    };
  }, points);
}
