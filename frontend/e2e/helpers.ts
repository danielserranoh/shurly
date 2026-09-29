// Phase 6.1 — what the specs share: a person's visits to a link, the pages' segmented controls, dates and CSVs.

import { readFile } from 'node:fs/promises';

import { expect, type APIRequestContext, type Download, type Locator } from '@playwright/test';

import { API_URL, BROWSER_UA } from './env';

/** Someone clicks a short link: straight to the API, as their browser would, without following it. */
export async function clickLink(request: APIRequestContext, code: string): Promise<string> {
  const response = await request.get(`${API_URL}/${code}`, { headers: { 'User-Agent': BROWSER_UA }, maxRedirects: 0 });
  expect(response.status(), `a click on ${code}`).toBe(302);
  return response.headers().location;
}

/** Their email client loads the link's tracking pixel: an email open. */
export async function openEmail(request: APIRequestContext, code: string): Promise<void> {
  const response = await request.get(`${API_URL}/${code}/track`, { headers: { 'User-Agent': BROWSER_UA } });
  expect(response.headers()['content-type'], `an open of ${code}`).toBe('image/gif');
}

/** Picks an option of a segmented control as a person does, on its label: the radio itself sits under it. */
export async function pick(radio: Locator): Promise<void> {
  await radio.locator('xpath=..').click();
  await expect(radio).toBeChecked();
}

/** A YYYY-MM-DD date `days` after `date` (before, when negative). */
export const shift = (date: string, days: number) => new Date(Date.parse(`${date}T00:00:00Z`) + days * 86_400_000).toISOString().slice(0, 10);

/** A downloaded CSV's lines, its header first, without the byte-order mark or empty lines. */
export async function csvLines(download: Download): Promise<string[]> {
  const text = await readFile(await download.path(), 'utf8');
  return text
    .replace(/^﻿/, '')
    .split(/\r?\n/)
    .filter(Boolean);
}
