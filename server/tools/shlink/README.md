# Moving Shlink's links to Shurly (Phase 8.4)

Three steps, run by an operator, each from the previous one's file. Shlink is only
read: it stays intact as the rollback.

1. **Export** Shlink's REST API into a raw JSON snapshot.
2. **Review** the snapshot as a CSV, and decide `keep`, `archive` or `drop` for each link.
3. **Import** the snapshot and the decisions into Shurly.

> **The snapshot can hold personal data.** With `--visits` it holds every visit's
> user agent, referer and location. Even without, it holds every link the company has
> made. Keep it in `_exchange/` (git-ignored) or an encrypted store, **never in the
> repository**. `*.snapshot.json` and `*.review.csv` are git-ignored as a safety net,
> and both files are written readable by their owner only.

## Export

```bash
export SHLINK_URL=https://go.griddo.io
export SHLINK_API_KEY=…   # a Shlink API key; read-only use
uv run python -m server.tools.shlink export [--visits] [--out-dir _exchange]
```

- **Output:** `_exchange/shlink-<host>-<UTC time>.snapshot.json`. An existing file is
  never overwritten.
- **What it reads:** every page of `GET /rest/v3/short-urls`, then, for each link:
  - `…/redirect-rules` when Shlink says it has some;
  - every page of `…/visits`, with `--visits`.
  - `GET /rest/health` gives Shlink's version.
- **The API key** travels only in the `X-Api-Key` header. It never goes in the snapshot
  or its name, and is never printed, errors included.
- **At the end** it prints how many links it exported, how many links' visits came whole (and how many
  of those have any), and the codes of the links whose visits Shlink failed on, each with what was
  recovered and the ranges lost.

The snapshot:

```json
{
  "format": "shurly.shlink-snapshot/1",
  "exported_at": "2026-09-28T10:15:00+00:00",
  "shlink": {"url": "https://go.griddo.io", "version": "4.2.1"},
  "links": [
    {
      "short_url": {"…": "as Shlink's API returned it"},
      "redirect_rules": {"…": "only if it has some"},
      "visits": ["… only with --visits"]
    },
    {
      "short_url": {"shortCode": "23q4griddo", "…": "…"},
      "visits": ["… the ones recovered by date"],
      "visits_error": {"status": 500, "detail": "An unknown error occurred."},
      "visits_gaps": [{"start": "2025-03-04T10:00:07+00:00", "end": "2025-03-04T10:00:07+00:00"}]
    }
  ],
  "visits_failed": ["23q4griddo"]
}
```

### When Shlink fails on a link's visits

Production's Shlink (4.x) answers `500 An unknown error occurred.` to `…/visits` for a few links, whatever
the parameters, while the link itself answers fine. Shlink's log says why:

```
Typed property Shlinkio\Shlink\Core\Visit\Entity\VisitLocation::$regionName must not be accessed before
initialization (VisitLocation.php:67)
```

Some `visit_locations` rows have a NULL `region_name`. The column is nullable, but the PHP property is a
non-null `string`, so Shlink can't serialize a visit with that location, and any page holding one fails
whole. `country_code`, `country_name`, `city_name` and `timezone` are mapped the same way and would fail
the same way.

**The fix is in Shlink's data, and it's the operator's call** (the export never writes to Shlink). Applied
before the real export, every visit comes:

```sql
-- How many, per column (PostgreSQL and MySQL alike):
SELECT SUM(CASE WHEN region_name  IS NULL THEN 1 ELSE 0 END) AS region_name,
       SUM(CASE WHEN country_code IS NULL THEN 1 ELSE 0 END) AS country_code,
       SUM(CASE WHEN country_name IS NULL THEN 1 ELSE 0 END) AS country_name,
       SUM(CASE WHEN city_name    IS NULL THEN 1 ELSE 0 END) AS city_name,
       SUM(CASE WHEN timezone     IS NULL THEN 1 ELSE 0 END) AS timezone
FROM visit_locations;

-- The fix: Shlink stores '' for a region it doesn't know.
UPDATE visit_locations SET region_name = '' WHERE region_name IS NULL;
-- …and the same for any other column the count found.
```

Take Shlink's RDS snapshot first: Shlink is the rollback.

**Without the fix, the export doesn't stop.** For each link:

1. A 5xx is asked again twice, after 0.5 s and 1 s. Any other error status still stops the export, and so
   does a failing list of short URLs: without it there's nothing to export.
2. If it still fails, the link gets `visits_error` (Shlink's status and detail), its code goes in
   `visits_failed`, and its visits are recovered by date range.
3. **The recovery** uses what Shlink's spec offers for a link's visits (`getShortUrlVisits`):
   `startDate` and `endDate` (ISO 8601), `page`, `itemsPerPage` and `excludeBots`. There is no visit id or
   cursor to narrow it by. Shlink compares both dates inclusively, to the second, lists the newest first,
   and fails on a page past the last one. So:
   - it asks for 1970 to now, and cuts a range that fails in two, newer half first, down to a single second;
   - a second that fails is read one visit per page (`itemsPerPage=1`), keeping each visit Shlink can
     serialize. Only the bad visit is lost, unless two in a row fail before a page says how many there are;
   - a second where a visit failed becomes a **gap**: `visits_gaps`, `{start, end}`, both ends included, to
     the second. The recovered visits keep Shlink's order, newest first.
   - A link's recovery makes at most 600 requests. Past that, the ranges it hadn't tried become gaps as they
     are, wider than a second, so a link Shlink can't answer for at all can't take a request per second.
   - If every range answered but Shlink counts more visits than came (`visitsSummary.total`), the gap has
     no ends (`{"start": null, "end": null}`): visits no date range reaches.
   - It costs a failing link about 130 requests and under a minute, mostly the retries' waits. It prints
     each as it starts on it.

The review's `visits_export` and `visits_lost` columns, and the import's report, carry the gaps on: no
visit is made up for a gap.

## Review

```bash
uv run python -m server.tools.shlink review _exchange/shlink-go.griddo.io-….snapshot.json \
    [--check-destinations] [--out review.csv]
```

It writes one row per link, next to the snapshot (`….review.csv`) unless `--out` says
otherwise. It never overwrites a sheet, which may already hold decisions. Every cell is
spreadsheet-safe: a title that starts like a formula gets a leading quote.

| Column | What |
|---|---|
| `code`, `domain` | The link. `domain` is the host, Shlink's default domain included |
| `destination`, `title`, `tags`, `created` | As in Shlink |
| `visits`, `non_bot_visits` | Shlink's counts |
| `last_visit` | The latest visit's date, when the snapshot has visits |
| `visits_export` | Empty without visits in the snapshot. `complete`; `recovered` when Shlink failed on them but the date ranges brought them all; `partial` when some ranges were lost; `failed` when none came |
| `visits_lost` | The ranges lost (`visits_gaps`), as ISO 8601 intervals `start/end`, both ends included; `…` for an end there isn't. `last_visit` and `capped_in_shurly` only count the visits that came |
| `expired`, `capped` | `yes` when `validUntil` has passed, or `visits` reached `maxVisits` (Shlink's rule: every visit counts) |
| `capped_in_shurly` | `yes` when the link arrives capped from an import with `--visits`: its clicks reach `maxVisits`, bots and pixel opens aside (Shurly's rule, see Visits below). Without visits in the snapshot, no link does |
| `redirect_rules`, `rules_to_check` | How many rules, and the conditions Shurly has no equivalent for (IP address, geolocation) |
| `destination_status` | The destination's HTTP status, with `--check-destinations` |
| `duplicate_of` | The oldest link on the same domain with the same destination |
| `case_collision` | Codes on the same domain that differ only in case. They matter if Shlink runs `loose` mode (ROADMAP 8.2) |
| `decision` | `keep`, by default |

**`decision`:** a kept link costs a row. A dropped one that turns out to be on a poster, a
QR code or a PDF breaks for good. So `drop` is for tests and duplicates, and `archive`
migrates a link with a `legacy` tag the dashboard can hide. The import reads only
`code`, `domain` and `decision` back.

**`--check-destinations`** fetches each distinct destination:
- through the link previews' SSRF guard (`guarded_request`, `server/utils/opengraph.py`),
  so only http(s) URLs whose host resolves to public addresses;
- connected to the checked address, with redirects followed by hand and each hop checked;
- at most `--concurrency` (8) at a time, `--timeout` (5) seconds each;
- `HEAD` first, then `GET` if the server refuses `HEAD`.

The status is the final one after redirects:
- `refused: …` when the guard refused the URL;
- `timeout`;
- `error: <type>` when the request failed.

`OG_FETCH_ALLOW_PRIVATE=true` lets it check internal addresses too.

## Import

```bash
uv run python -m server.tools.shlink import _exchange/shlink-go.griddo.io-….snapshot.json \
    _exchange/shlink-go.griddo.io-….review.csv --as owner@griddo.io [--visits] [--dry-run]
```

It writes to the database the `DB_*` settings name. **Run it with `--dry-run` first:** it does everything,
prints the report, and rolls back. Against production's private RDS it runs as a one-off ECS task:
`scripts/run_shlink_import.sh` (DEPLOYMENT.md § The import as a one-off ECS task). A rehearsal runs locally
against a restored copy.

**Each link the review keeps** (`keep`, `archive`, or left out of the review) arrives with:
- its exact code, never lowercased, so `AbC` and `abc` stay two links, as in Shlink's default `strict` mode;
- its domain: `shortUrl`'s host, with a Domain row made for it if there's none. Nothing is made the default;
- its creation date;
- the organization of `--as` as its owner, and `--as` as its creator. It must be an owner of the organization.

**What maps:**
- the destination, title, tags, validity window, visit cap, `crawlable`, and `forwardQuery` →
  `forward_parameters`;
- tags are matched by name, the predefined ones included, and made when missing. `archive` adds a
  `legacy` tag;
- redirect rules, condition by condition:
  - a rule with a condition Shurly has no equivalent for (IP address, geolocation) is left out whole,
    because dropping that condition alone would widen it;
  - `language en-US` becomes `en`, since Shurly compares the primary subtag;
  - `valueless-query-param` becomes a presence match, which also matches `?key=value`.

The report lists every rule left out or approximated. Nothing is dropped silently.

**Running it again** is safe:
- a link already there with the same destination is left as it is, Shurly-side edits included;
- a link there with another destination is a conflict. So is a link Shurly can't take: a code longer than 20
  characters, one of Shurly's own paths (`docs`, `redoc`, `mcp`), or a destination that isn't http(s). Either
  stops the import before anything is written, unless the review drops that link. The exit status is `1`.

**Visits, with `--visits`** (decision A, 2026-09-28): each of Shlink's visits becomes a Visitor row.
- **`ip` is `"unknown"`**: Shlink exposes no addresses. That's how imported visits are told apart: a visit
  Shurly records has an address, unless it couldn't read one. An unknown address never counts as a visitor, so
  **unique-visitor counts only cover the cutover onward**.
- A link's last click is its latest imported click: neither Shlink's potential bots nor opens move it.
- The country is `visitLocation.countryCode`, an ISO code as Shurly stores one: providers name some countries
  differently. The city is `visitLocation.cityName`, the English name, as Shurly keeps one; the latitude and
  longitude aren't kept. The user agent, referer and date come as they were.
- A bot is what Shlink flagged as `potentialBot`. The `/track` pixel is a visit Shlink didn't redirect
  (`redirectUrl` null), so the pixel's opens don't count as clicks.
- **They count toward the link's visit cap (`max_visits`) as Shurly's own do: clicks only.** A bot or a pixel
  open doesn't use it up. Shlink counted every visit, so a link Shlink had capped can have clicks left here:
  the review's `capped_in_shurly` says which stay capped.
  Without `--visits`, a link's cap starts again from zero.
- A run imports only the visits newer than the link's last imported one. The cutover's final snapshot
  therefore adds what happened since the first import. A second visit in the very same second as that last
  one would be missed.
- **A link whose visits Shlink failed on** (When Shlink fails on a link's visits, above) brings the visits the
  export recovered, and no more. The report names each of its lost ranges. Since a later run only adds newer
  visits, a gap stays a gap: to fill it, fix Shlink's data and export again before the first import.
- Shurly's own visits get their country and city from MaxMind's GeoLite2 City, as Shlink's do, else their
  country from DB-IP's database (`server/utils/geo.py`). The same codes and names, so the geo view counts
  imported and new visits together.
