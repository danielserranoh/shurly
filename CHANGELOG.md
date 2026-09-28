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
