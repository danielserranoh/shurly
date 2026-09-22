// QR codes rendered client-side (uqr encoder). Downloads as SVG or PNG.

import { encode } from 'uqr';
import { saveBlob } from './api';

export interface QrOptions {
  foreground?: string;
  background?: string;
  /** Quiet zone in modules (spec minimum is 4). */
  margin?: number;
}

export function qrSvg(text: string, opts: QrOptions = {}): string {
  const { foreground = '#090d13', background = '#ffffff', margin = 4 } = opts;
  const qr = encode(text, { ecc: 'M', border: 0 });
  const size = qr.size + margin * 2;
  let path = '';
  for (let y = 0; y < qr.size; y++) {
    for (let x = 0; x < qr.size; x++) {
      if (qr.data[y][x]) path += `M${x + margin},${y + margin}h1v1h-1z`;
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${size} ${size}" shape-rendering="crispEdges"><rect width="${size}" height="${size}" fill="${background}"/><path fill="${foreground}" d="${path}"/></svg>`;
}

export function downloadQrSvg(text: string, filename: string, opts?: QrOptions): void {
  saveBlob(new Blob([qrSvg(text, opts)], { type: 'image/svg+xml' }), filename);
}

export async function downloadQrPng(text: string, filename: string, px = 1024, opts?: QrOptions): Promise<void> {
  const svg = qrSvg(text, opts);
  const img = new Image();
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error('Could not render the QR code.'));
    img.src = url;
  });
  const canvas = document.createElement('canvas');
  canvas.width = px;
  canvas.height = px;
  const ctx = canvas.getContext('2d')!;
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(img, 0, 0, px, px);
  URL.revokeObjectURL(url);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
  if (!blob) throw new Error('Could not export the QR code.');
  saveBlob(blob, filename);
}
