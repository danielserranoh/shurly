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

### Changed — Griddo palette and type (trial)
- Brand colour is Griddo blue `#5057ff` (was lime `#b8f03e`): new `brand-50…950`
  scale with the signature at `brand-400`. Brand fills now carry white text,
  brand text/icons on ink use `brand-300`, charts draw in `brand-400`. Logo dot,
  favicons, app icons and the OG card are regenerated in blue.
- Page canvas is warm off-white `#faf9f6` (was `#f5f6f8`).
- Interface typeface is Figtree (was Inter). Headlines use Logical, Griddo's
  typeface, when available and fall back to Figtree until its web font files are
  added (was Bricolage Grotesque, which the wordmark SVG still uses).

### Security
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
