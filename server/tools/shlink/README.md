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
    }
  ]
}
```

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
| `expired`, `capped` | `yes` when `validUntil` has passed, or the visits reached `maxVisits` |
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
prints the report, and rolls back. How it runs against production's private RDS is still to be decided
(ROADMAP 8.4, decision B). A rehearsal runs locally against a restored copy.

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
  Shurly records always has an address. It's also why **unique-visitor counts only cover the cutover onward**.
- The country comes from `visitLocation.countryName`, and the user agent, referer and date as they were.
- A bot is what Shlink flagged as `potentialBot`. The `/track` pixel is a visit Shlink didn't redirect
  (`redirectUrl` null), so the pixel's opens don't count as clicks.
- A run imports only the visits newer than the link's last imported one. The cutover's final snapshot
  therefore adds what happened since the first import. A second visit in the very same second as that last
  one would be missed.
- Shurly doesn't fill `Visitor.country` for its own visits yet (ROADMAP 8.4). Until it does, the geo view
  shows the imported history only.
