// Phase 3.12 — the profile's country and time zone pickers, on the real lists
// (src/data/timezones.json, from the tzdata package the API checks against).
// Run: `npm test` (node --test; Node 22.18+ runs the TypeScript module as is).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import data from '../src/data/timezones.json' with { type: 'json' };
import { allZones, countryOptions, onlyZone, pickerZone, zoneLabel, zonesFor } from '../src/utils/timezones.ts';

describe('zonesFor', () => {
  test("a country's zones, then UTC", () => {
    assert.deepEqual(zonesFor(data, 'ES'), ['Africa/Ceuta', 'Atlantic/Canary', 'Europe/Madrid', 'Etc/UTC']);
  });

  test('every zone without a country', () => {
    const zones = zonesFor(data, null);
    assert.deepEqual(zones, allZones(data));
    assert.ok(zones.includes('Europe/Stockholm') && zones.includes('Etc/UTC'));
    assert.deepEqual(zones, [...zones].sort());
  });

  test('every zone for a country without any', () => {
    assert.deepEqual(zonesFor(data, 'BV'), allZones(data));
  });
});

describe('onlyZone', () => {
  test('picks the zone of a country with one', () => {
    assert.equal(onlyZone(data, 'FR'), 'Europe/Paris');
    assert.equal(onlyZone(data, 'IN'), 'Asia/Kolkata');
  });

  test('leaves the choice when there are several, or no country', () => {
    assert.equal(onlyZone(data, 'ES'), null);
    assert.equal(onlyZone(data, null), null);
  });
});

describe('pickerZone', () => {
  test("keeps a name the picker offers, a country's own included", () => {
    assert.equal(pickerZone(data, 'Atlantic/Canary'), 'Atlantic/Canary');
    assert.equal(pickerZone(data, 'Europe/Stockholm'), 'Europe/Stockholm');
  });

  test('turns a legacy name from the browser into the current one', () => {
    assert.equal(pickerZone(data, 'Asia/Calcutta'), 'Asia/Kolkata'); // Chrome, in India
    assert.equal(pickerZone(data, 'Europe/Kiev'), 'Europe/Kyiv');
    assert.equal(pickerZone(data, 'UTC'), 'Etc/UTC');
  });

  test('null for anything else', () => {
    assert.equal(pickerZone(data, 'Mars/Olympus_Mons'), null);
    assert.equal(pickerZone(data, ''), null);
    assert.equal(pickerZone(data, undefined), null);
  });
});

describe('zoneLabel', () => {
  const winter = new Date('2026-01-15T12:00:00Z');
  const summer = new Date('2026-07-15T12:00:00Z');

  test('the name, spaced, with its offset at the time', () => {
    assert.equal(zoneLabel('Atlantic/Canary', winter), 'Atlantic/Canary (GMT)');
    assert.equal(zoneLabel('Atlantic/Canary', summer), 'Atlantic/Canary (GMT+1)');
    assert.equal(zoneLabel('America/Argentina/Buenos_Aires', winter), 'America/Argentina/Buenos Aires (GMT-3)');
    assert.equal(zoneLabel('Asia/Kolkata', winter), 'Asia/Kolkata (GMT+5:30)');
  });

  test('UTC is just UTC', () => {
    assert.equal(zoneLabel('Etc/UTC', winter), 'UTC');
  });

  test('without an offset for a zone the browser doesn’t know', () => {
    assert.equal(zoneLabel('Mars/Olympus_Mons', winter), 'Mars/Olympus Mons');
  });
});

describe('countryOptions', () => {
  test('every country, by name', () => {
    const options = countryOptions(data);
    assert.equal(options.length, data.countries.length);
    assert.deepEqual(options.find(([code]) => code === 'ES'), ['ES', 'Spain']);
    const names = options.map(([, name]) => name);
    assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b, 'en')));
  });
});
