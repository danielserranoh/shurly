// Phase 8.4 — a visit's country is stored as its ISO 3166-1 alpha-2 code ("ES"): the page
// shows its English name, from the browser's own list (Intl.DisplayNames). A value that isn't
// a code is shown as it is. No imports, so tests/country.test.mjs can run it as is.

const names = new Intl.DisplayNames(['en'], { type: 'region' });

export function countryName(value: string | null | undefined): string {
  if (!value) return 'Unknown';
  if (/^[A-Za-z]{2}$/.test(value)) {
    const code = value.toUpperCase();
    try {
      const name = names.of(code);
      if (name && name !== code) return name;
    } catch {
      // not a region code: shown as it is
    }
  }
  return value;
}
