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
