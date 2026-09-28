// Phase 3.12 — the profile's country and time zone pickers. The lists come from
// src/data/timezones.json, made from the `tzdata` package the API checks against
// (scripts/generate_timezones.py), so the picker only offers what the API keeps as is.

export interface TimezoneData {
  /** ISO 3166-1 alpha-2 codes. */
  countries: string[];
  /** Country → the zones zone.tab gives it. A country without any (BV, HM) is missing. */
  zones: Record<string, string[]>;
  /** Offered whatever the country: UTC. */
  anyCountry: string[];
  /** Legacy name → the name the API keeps for it ("Asia/Calcutta" → "Asia/Kolkata"). */
  aliases: Record<string, string>;
}

/** Every zone the picker offers, sorted. */
export function allZones(data: TimezoneData): string[] {
  return [...new Set([...Object.values(data.zones).flat(), ...data.anyCountry])].sort();
}

/** What to offer for `country`: its zones, then UTC. Every zone without a country, or for one without zones. */
export function zonesFor(data: TimezoneData, country: string | null): string[] {
  const own = country ? data.zones[country] : undefined;
  if (!own?.length) return allZones(data);
  return [...own, ...data.anyCountry.filter((zone) => !own.includes(zone))];
}

/** The zone to pick for `country` when it has just one; null otherwise. */
export function onlyZone(data: TimezoneData, country: string | null): string | null {
  const own = country ? data.zones[country] : undefined;
  return own?.length === 1 ? own[0] : null;
}

/** The picker's name for a zone the browser reports, which may be a legacy one; null when it isn't offered. */
export function pickerZone(data: TimezoneData, zone: string | null | undefined): string | null {
  if (!zone) return null;
  const name = data.aliases[zone] ?? zone;
  return allZones(data).includes(name) ? name : null;
}

/** "Atlantic/Canary" → "Atlantic/Canary (GMT+1)": the name and its offset at `now`. UTC is just "UTC". */
export function zoneLabel(zone: string, now: Date = new Date()): string {
  if (zone === 'Etc/UTC') return 'UTC';
  const name = zone.replaceAll('_', ' ');
  const offset = offsetAt(zone, now);
  return offset ? `${name} (${offset})` : name;
}

function offsetAt(zone: string, now: Date): string | null {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'shortOffset' }).formatToParts(now);
    const offset = parts.find((part) => part.type === 'timeZoneName')?.value;
    // Some ICU versions write a zero offset "GMT+0", others "GMT".
    return offset ? offset.replace(/^GMT[+-]0(?::00)?$/, 'GMT') : null;
  } catch {
    return null; // a zone this browser doesn't know yet
  }
}

/** [code, name] for each country, by name. Names come from the browser; the code stands in without one. */
export function countryOptions(data: TimezoneData, locale = 'en'): [string, string][] {
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames([locale], { type: 'region' });
  } catch {
    names = null;
  }
  return data.countries
    .map((code): [string, string] => [code, names?.of(code) ?? code])
    .sort((a, b) => a[1].localeCompare(b[1], locale));
}
