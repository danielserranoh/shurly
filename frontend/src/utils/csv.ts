// Minimal RFC 4180 CSV parsing for the campaign wizard preview and validation.
// The backend re-parses and validates authoritatively; this gives instant feedback.

export interface ParsedCsv {
  headers: string[];
  rows: string[][];
  /** Human-readable problems that would make the backend reject the file. */
  errors: string[];
  /** Non-blocking notices. */
  warnings: string[];
}

export function parseCsv(text: string): string[][] {
  const out: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  const src = text.replace(/^﻿/, '');
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (quoted) {
      if (c === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i++;
        } else quoted = false;
      } else field += c;
      continue;
    }
    if (c === '"' && field === '') quoted = true;
    else if (c === ',') {
      row.push(field);
      field = '';
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && src[i + 1] === '\n') i++;
      row.push(field);
      out.push(row);
      row = [];
      field = '';
    } else field += c;
  }
  if (field !== '' || row.length) {
    row.push(field);
    out.push(row);
  }
  return out.filter((r) => r.some((f) => f.trim() !== ''));
}

export function analyzeCsv(text: string): ParsedCsv {
  const all = parseCsv(text);
  const errors: string[] = [];
  const warnings: string[] = [];
  if (all.length === 0) return { headers: [], rows: [], errors: ['The file is empty.'], warnings };

  const headers = all[0].map((h) => h.trim());
  const rows = all.slice(1).map((r) => r.map((f) => f.trim()));

  if (headers.some((h) => h === '')) errors.push('Every column in the header row needs a name.');
  const dupes = headers.filter((h, i) => h && headers.indexOf(h) !== i);
  if (dupes.length) errors.push(`Column names must be unique (repeated: ${[...new Set(dupes)].join(', ')}).`);
  if (rows.length === 0) errors.push('Add at least one row below the header — each row becomes one link.');

  const badRows = rows.map((r, i) => (r.length !== headers.length ? i + 2 : 0)).filter(Boolean);
  if (badRows.length) {
    const sample = badRows.slice(0, 5).join(', ');
    errors.push(`${badRows.length === 1 ? 'Row' : 'Rows'} ${sample}${badRows.length > 5 ? '…' : ''} ${badRows.length === 1 ? "doesn't" : "don't"} have ${headers.length} columns like the header.`);
  }

  const sensitive = headers.filter((h) => /e-?mail|phone|tel|dni|passport|ssn/i.test(h));
  if (sensitive.length) {
    warnings.push(`"${sensitive.join('", "')}" will be added to the destination URL as a query parameter. Only include personal data you're comfortable exposing in links.`);
  }
  return { headers, rows, errors, warnings };
}

export function toCsv(rows: (string | number | null | undefined)[][]): string {
  return rows
    .map((r) =>
      r
        .map((v) => {
          const s = String(v ?? '');
          return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        })
        .join(','),
    )
    .join('\n');
}

export const SAMPLE_CSV = `firstName,company,region
Ana,Acme Corp,Madrid
Luis,Northwind,Barcelona
Marta,Globex,Valencia`;
