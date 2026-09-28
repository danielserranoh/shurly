# Shurly - Project Roadmap

## Project Overview
Modern URL shortener for B2B campaigns with analytics, running on AWS.

**Hosts**: `shurly.griddo.io` for the web, the app, the API and the MCP; `go.griddo.io` for short links, once
Shurly replaces Shlink there (Phase 8). Until then test links live on `s.griddo.io`, deleted at the cutover.
**Expected Volume**: ~100-150 URLs/month (20-50 standard + 1 campaign of ~100 users)
**Deployment**: ECS Express (Fargate, behind the shared ALB) + RDS PostgreSQL for the API and the MCP;
S3 + CloudFront for the frontend (4.10, pending).

---

## Next up (updated 2026-09-28)

Order agreed in the 2026-09-27 review; confirm each item before starting it.

1. **MCP usage log** (5.6.0): without it the dogfood produces no numbers. Code done, and the log group keeps
   60 days (set 2026-09-28). Left: saving the Logs Insights queries in CloudWatch, an AWS step.
2. ✅ **Organization and roles** (3.14): links belong to the organization by default; owner, admin and member.
   Done: API, MCP and frontend (Settings → Organization, the personal toggle, who created each link, removed
   people). Left: two owners from day one, once people have signed up.
3. **Frontend hosting** (4.10): S3 + CloudFront; AWS steps run with SSO. The deploy workflow is ready and runs on
   merges to `main` that touch the frontend, but skips until the AWS side exists (`FRONTEND_BUCKET` unset), as it
   did for release #81.
4. **Identity**: sign in with Google Workspace, for the web (3.13) and the MCP (5.8). One Google project covers
   both. The code of both is done (3.13's backend and frontend, 5.8), and in production since release #81
   (2026-09-28) on `shurly.griddo.io`, which the deploy's smoke test checks. The MCP's Google sign-in is live.
   Left: the web's sign-in, which needs the hosted frontend (the sign-in ends on its `/login/`, 4.10), and the
   end-to-end checks (3.13.6, 5.8).
5. ✅ **MCP install guide**, in the app and in the user manual (5.9): `/manual/install-mcp/` and Settings → API &
   MCP. Its address comes from the build: `https://shurly.griddo.io/mcp/` once 4.10's production build sets
   `PUBLIC_API_URL`.
6. **Internal dogfood** with the frontend and the MCP (5.6).
7. **Replace Shlink on `go.griddo.io`** (Phase 8): after the dogfood and error alerting (6.4). Done on `dev`: a
   link is its code and its domain (8.3); exporting, reviewing and importing Shlink's links and visits, and a
   visit's country (8.4). Left: how the import runs in production (8.4, decision B), the `go.griddo.io` domain
   row and switching the default to it (8.3), error alerting (6.4), and the cutover (8.5).

Also landed on 2026-09-28, outside this list: the account profile (3.12: name, country, time zone and a photo;
people by name in Settings → Organization and "Created by"), analytics days in the viewer's time zone (3.12.8),
and a Content-Security-Policy and Trusted Types on every page (6.3). Release #81 took #65–#80; everything merged
since (#82 on) is on `dev`, for the next release.

Tasks marked 🔎 were not in the original plan. Each one points to an entry in the
[retro log](#retro-log--work-we-did-not-see-coming) at the end of this file.

---

## Use Cases

### 1. Standard URL Shortening
User provides a URL → System generates unique short code → Returns short URL

### 2. Custom Short URL
User provides URL + custom short code → System checks uniqueness:
- **Available**: Creates with custom code
- **Taken**: Appends random characters, warns user, returns modified code

### 3. Campaign URLs (Bulk)
User provides:
- Original URL
- Campaign name
- CSV with user data (flexible columns: firstName, lastName, company, region, etc.)

System creates:
- One short URL per user
- Each short code maps to user data
- On click: redirects to `original_url?firstName=John&lastName=Doe&company=Acme...`

---

## Technical Stack

### Backend
- **FastAPI** - API framework
- **PostgreSQL** - Database (RDS)
- **SQLAlchemy 2.0** - ORM
- **Alembic** - Schema migrations, run at startup (3.14.1)
- **Pydantic v2** - Validation
- **JWT** - Authentication
- **uvicorn** - ASGI server, in a container (`dockerfile`)
- **fastmcp** - The MCP server, in the same container (Phase 5)
- **uv** - Package management
- **ruff** - Linting/formatting

### Frontend
- **Astro 7** - Static site generator (static output, no adapter)
- **Tailwind CSS 4** - Styling
- **TypeScript** - Type safety
- **SVG charts** - Analytics visualization, no chart library (`frontend/src/utils/charts.ts`)

### Infrastructure
- **ECS Express Mode (Fargate)** - Compute: the API, the redirects and the MCP (`griddo-main`, eu-south-2)
- **Shared ALB** - Routing by host (rule 12), kept on the active target group by the `ecs-alb-rule-sync` Lambda
- **ECR** - Container images
- **RDS PostgreSQL (db.t4g.micro)** - Database
- **S3 + CloudFront** - Static frontend hosting (4.10, pending)
- **Route 53** - DNS

---

## Phase 1: Backend Foundation ✅ COMPLETED

### 1.1 Cleanup & Database Migration ✅
- [x] Remove CAPTCHA functionality
  - [x] Delete `server/utils/code.py`
  - [x] Delete `server/app/code.py`
  - [x] Remove captcha from dependencies
  - [x] Remove CAPTCHA routes from router
- [x] Migrate to PostgreSQL
  - [x] Update dependencies (add psycopg2-binary)
  - [x] Update database connection URL format
  - [x] Test connection

### 1.2 Data Models ✅
- [x] Create User model (authentication)
  - [x] id, email, password_hash, api_key, created_at, is_active
- [x] Update URL model
  - [x] Add: short_code (indexed), url_type (enum), campaign_id, user_data (JSON — planned as JSONB; PostgreSQL can't GROUP BY `json`, see the 2026-09-28 campaign-summary fix), created_by
  - [x] Remove: old short_url field if needed
- [x] Create Campaign model
  - [x] id, name, original_url, csv_columns, created_by, created_at
- [x] Update Visitor model
  - [x] Add: short_code (denormalized), user_agent, referer
  - [x] Update: country format
- [x] Fix database session management (was creating engine per request!)

### 1.3 Authentication System ✅
- [x] Install dependencies (python-jose, passlib, python-multipart)
- [x] Create auth utilities
  - [x] Password hashing (bcrypt)
  - [x] JWT token generation/validation
  - [x] Get current user dependency
- [x] Create auth endpoints
  - [x] POST /api/auth/register
  - [x] POST /api/auth/login
  - [x] GET /api/auth/me
- [x] Add authentication middleware

### 1.4 Core URL Endpoints ✅
- [x] POST /api/urls - Standard URL shortening
  - [x] Generate random short code (6 chars)
  - [x] Validate URL format
  - [x] Check uniqueness
  - [x] Store in database
  - [x] Return short URL
- [x] POST /api/urls/custom - Custom short code
  - [x] Validate custom code (alphanumeric, 3-20 chars)
  - [x] Check availability
  - [x] If taken: append random chars + warn user
  - [x] Store and return
- [x] GET /{short_code} - Redirect endpoint
  - [x] Lookup short_code in database
  - [x] If campaign URL: decode user_data JSON → build query params
  - [x] Log visit (synchronous for now)
  - [x] Return 302 redirect with params
- [x] GET /api/urls - List user's URLs (paginated)
- [x] DELETE /api/urls/{id} - Delete URL (via cascade from campaign)

### 1.5 Campaign System ✅
- [x] Create campaign utilities
  - [x] CSV parser (handle flexible columns)
  - [x] Batch short code generator
  - [x] User data validator
- [x] POST /api/campaigns - Create campaign
  - [x] Accept: name, original_url, CSV file/data
  - [x] Parse CSV columns dynamically
  - [x] Generate unique short code per row
  - [x] Store campaign + all URLs with user_data JSON
  - [x] Return campaign summary
- [x] GET /api/campaigns - List user's campaigns
- [x] GET /api/campaigns/{id} - Campaign details + URLs
- [x] GET /api/campaigns/{id}/export - Export campaign URLs as CSV
- [x] DELETE /api/campaigns/{id} - Delete campaign (cascades to URLs)

---

## Phase 2: Analytics Enhancement ✅

### 2.1 Update Analytics Endpoints ✅
- [x] Refactor existing statistics utilities for new schema
- [x] GET /api/analytics/urls/{short_code}/daily - Daily clicks (last 7 days)
      → today included, in the viewer's time zone since 3.12.8
- [x] GET /api/analytics/urls/{short_code}/weekly - Weekly clicks (last 8 weeks)
      → 8 seven-day weeks ending today (they ended yesterday until 3.12.8)
- [x] GET /api/analytics/urls/{short_code}/geo - Geographic distribution (with configurable days)
- [x] GET /api/analytics/campaigns/{id}/summary
  - [x] Total clicks, unique IPs, click-through rate
  - [x] Top 5 performing URLs
  - [x] Daily timeline (last 7 days) → in the viewer's time zone since 3.12.8
- [x] GET /api/analytics/campaigns/{id}/users
  - [x] List all campaign users with detailed click stats
  - [x] Clicks, unique IPs, last clicked timestamp
- [x] GET /api/analytics/overview - User's overall dashboard stats
  - [x] Total URLs, campaigns, clicks, unique visitors
  - [x] Recent clicks (7 days)
  - [x] Top 5 URLs by clicks
  - [x] Daily activity timeline

### 2.2 Enhanced Visitor Tracking ✅
- [x] User agent parsing utilities (browser, OS, device type detection)
- [x] Referer tracking (already in Visitor model)
- [x] IP geolocation service integration (deferred - optional feature) → wanted before the Shlink cutover: see 8.4
      → done there: DB-IP's country database, in process
- [ ] Background task for async logging (deferred - visitor logging is synchronous)

---

## Phase 3: Frontend Dashboard

### 3.1 Authentication UI ✅
- [x] Login page
- [x] Registration page
- [x] Protected route wrapper
- [x] JWT token management (localStorage)
- [x] Navbar with logout functionality

### 3.2 URL Management ✅
- [x] Dashboard home (list all URLs)
- [x] Create URL form (standard + custom toggle)
- [x] URL card component with statistics
- [x] Copy short URL button
- [x] URL details page with mini analytics
- [x] Delete URL confirmation

### 3.3 Campaign Management ✅
- [x] Campaigns list page
- [x] Create campaign wizard
  - [x] Step 1: Campaign info (name, original URL)
  - [x] Step 2: Upload CSV (paste + preview)
  - [x] Step 3: Review and create
- [x] Campaign details page
  - [x] Summary stats cards
  - [x] URLs table with user data
  - [x] Export campaign URLs button (CSV download)
  - [x] Delete campaign functionality
- [x] Campaign analytics visualization — summary stat cards + clicks-per-day chart on `dashboard/campaign.astro` (Phase 3.11)

### 3.4 Analytics Dashboard ✅
- [x] Overview page (aggregate stats)
- [x] Charts integration (pure CSS, no heavy libraries)
  - [x] Timeline charts (daily activity bar chart)
  - [x] Geographic distribution (country list with horizontal bars)
  - [x] Top performing URLs section
- [ ] Date range selector (deferred - optional feature)
- [x] Export analytics data (CSV)

### 3.5 User Settings ✅
- [x] Profile page (email, account creation date display)
- [x] Password change functionality
- [x] API key management (generate, revoke, copy)

---

## Phase 3.6: Pre-AWS Quick Wins (Rebrandly Feature Parity)

**Goal:** Add critical missing features identified in competitive analysis before AWS deployment.
**Duration:** 2-3 hours total
**Reference:** See IMPLEMENTATION_TASKS.md

### 3.6.1 Database Schema Updates ✅
- [x] Add `title` field to URL model (VARCHAR 255, nullable)
- [x] Add `last_click_at` field to URL model (TIMESTAMP, nullable)
- [x] Add `forward_parameters` field to URL model (BOOLEAN, default true)
- [x] Add `updated_at` field to URL model (TIMESTAMP, auto-update)
- ~~Create database migration script~~ (SQLAlchemy auto-creates schema)
- ~~Test migration on local PostgreSQL~~ (No migration needed)

### 3.6.2 API Endpoint Updates ✅
- [x] Update POST /api/urls to accept optional `title` and `forward_parameters` fields
- [x] Update POST /api/urls/custom to accept optional `title` and `forward_parameters` fields
- [x] Implement PATCH /api/urls/{code} endpoint
  - [x] Allow updating: title, original_url, forward_parameters, og_* fields
  - [x] Keep short_code immutable
  - [x] Update `updated_at` timestamp (automatic via model)
  - [x] Return 404 if URL not found
  - [x] Verify ownership (current user)
  - [x] Block updates to campaign URLs
- [x] Update redirect handler to use forward_parameters
  - [x] Campaign user_data: ALWAYS append (personalization)
  - [x] Query params: Only if forward_parameters=true (attribution tracking)
- [x] Update visitor logging to set last_click_at timestamp

### 3.6.3 Schema Updates ✅
- [x] Create URLUpdate schema (title, original_url, forward_parameters, og_* fields)
- [x] Update URLResponse schema to include new fields
- [x] Add validation rules for title (max 255 chars)
- [x] Add extra="forbid" to prevent updating immutable fields

### 3.6.4 Testing ✅
- ~~Write tests~~ (Tests already exist in TEST_COVERAGE_REPORT.md)
- [x] Verify existing tests still pass (123/132 pass, 9 bcrypt edge case failures unrelated)

### 3.6.5 Frontend Updates ✅ (Phase 3.11)
- [x] Add title input field to URL creation forms
- [x] Add forward_parameters toggle to URL creation forms
- [x] Add "Edit URL" button to URL details page
- [x] Create URL edit modal/page (`EditLinkModal`: title, destination, forward params, OG, schedule, cap, crawlable, tags)
- [x] Display last_click_at timestamp in URL details (relative + absolute)
- [x] Show forward_parameters status in URL card (badge only when off)
- [x] Update URL list to show titles (title → OG title → destination host)

---

## Phase 3.7: Social Media Link Preview (Open Graph)

**Goal:** Add Open Graph metadata support for rich social media previews
**Duration:** 8-10 days
**Priority:** 🔴 CRITICAL - Most short links are shared on social media
**Reference:** See IMPLEMENTATION_TASKS.md Gap #1, design/Rebrandly-*.png

### 3.7.1 Database Schema Updates ✅
- [x] Add `og_title` field to URL model (VARCHAR 255, nullable)
- [x] Add `og_description` field to URL model (TEXT, nullable)
- [x] Add `og_image_url` field to URL model (TEXT, nullable)
- [x] Add `og_fetched_at` field to track metadata freshness (TIMESTAMP)
- ~~Create database migration script~~ (SQLAlchemy auto-creates schema)
- ~~Test migration on local PostgreSQL~~ (No migration needed)

### 3.7.2 Open Graph Metadata Fetching ✅
- [x] Install HTML parsing libraries (httpx, beautifulsoup4, jinja2)
- [x] Create metadata fetcher utility (`server/utils/opengraph.py`)
  - [x] Fetch destination URL HTML with httpx AsyncClient
  - [x] Parse og:title, og:description, og:image meta tags
  - [x] Fallback to standard meta tags if OG tags missing
  - [x] Handle missing/malformed metadata gracefully
  - [x] Set timeout (5 seconds max)
  - [x] Return structured OpenGraphMetadata class
  - [x] is_social_media_crawler() User-Agent detection
- [x] Add async metadata fetching on URL creation (auto-fetch if no custom OG provided)
- [x] Add manual "Refresh Preview" endpoint (POST /{code}/refresh-preview)

### 3.7.3 Preview Endpoint ✅
- [x] Create preview.html template
  - [x] Render HTML page with Open Graph and Twitter Card meta tags
  - [x] Include og:url pointing to short URL
  - [x] Add "Continue to destination" button (2-second auto-redirect)
  - [x] Handle missing metadata (fallback to URL/title)
  - [x] Mobile-responsive design with gradient background
- [x] Update main redirect to check User-Agent
  - [x] Social media crawlers → serve preview page (200 HTML)
  - [x] Regular browsers → direct redirect (302)
  - [x] Detect: Twitterbot, facebookexternalhit, LinkedInBot, WhatsApp, Slack, Discord, Telegram, Skype, Pinterest, Reddit
  - [x] 5-minute cache for preview pages

### 3.7.4 API Endpoint Updates ✅
- [x] Update POST /api/urls to accept og_* fields and auto-fetch
- [x] Update POST /api/urls/custom to accept og_* fields and auto-fetch
- [x] Update PATCH /api/urls/{code} to allow editing og_* fields
- [x] Add GET /api/urls/{code}/preview endpoint (fetch current OG data)
- [x] Add POST /api/urls/{code}/refresh-preview (re-fetch from destination)

### 3.7.5 Schema Updates ✅
- [x] Update URLCreate schema (optional og_title, og_description, og_image_url)
- [x] Update URLCustomCreate schema (same OG fields)
- [x] Update URLUpdate schema (include og_* fields)
- [x] Update URLResponse schema to include og_* fields and og_fetched_at
- [x] Add OpenGraphMetadataResponse schema for preview endpoint response
- [x] Add validation rules (og_title max 255, og_image_url valid URL)

### 3.7.6 Testing ✅
- ~~Write tests~~ (Tests already exist in TEST_COVERAGE_REPORT.md per TDD philosophy)
- [x] Verify all existing tests still pass (123/132 pass, 9 bcrypt edge case failures unrelated)

### 3.7.7 Frontend Updates (Phase 3.11)
- [x] Add Open Graph fields to URL creation form (optional, collapsible section)
- [x] Create Preview Card component (live preview in Create, auto-fetched on paste)
- [x] Add "Refresh Preview" button in edit view (details page + "Fetch preview" in the editor)
- [x] Display OG metadata preview card
  - [x] Display og:title, og:description, og:image
  - [x] Show fallback if metadata missing
  - [x] "Edit Preview" button
- [x] Add preview section to URL details page
  - [x] Visual preview card (how it appears on social media)
  - [x] "Refresh from destination" button
  - [x] Edit modal for custom og_* values
- [ ] Add preview indicators to URL list
  - [ ] Icon/badge if custom preview is set
  - [x] Preview thumbnail on every card

---

## Phase 3.8: Tags Feature

**Goal:** Global tag system for organizing URLs and campaigns
**Duration:** 5-7 days
**Priority:** 🟡 MEDIUM - Organizational feature for growing teams
**Reference:** See IMPLEMENTATION_TAGS.md for detailed plan

### 3.8.1 Backend - Database & Models ✅
- [x] Create Tag model (name, display_name, color, is_predefined)
- [x] Create url_tags association table (many-to-many)
- [x] Create campaign_tags association table
- [x] Add relationships to URL and Campaign models
- [x] Create database migration

### 3.8.2 Backend - Configuration & Initialization ✅
- [x] Add PREDEFINED_TAGS config (5 marketing categories)
- [x] Create tag initialization utility (server/utils/tags.py)
- [x] Add startup event to initialize predefined tags

### 3.8.3 Backend - API Endpoints (TDD) ✅
- [x] Tag Management
  - [x] GET /api/tags (list all with search/filter, includes usage_count)
  - [x] POST /api/tags (create user tag)
  - [x] PATCH /api/tags/{id} (rename user tag)
  - [x] DELETE /api/tags/{id} (delete + cascade)
- [x] URL Tagging
  - [x] PATCH /api/urls/{code}/tags (update URL tags)
  - [x] POST /api/urls/bulk/tags (bulk tag multiple URLs, additive)
  - [x] Update GET /api/urls to support tag filtering (`?tags=ids&tag_filter=any|all`)
- [x] Campaign Tagging
  - [x] PATCH /api/campaigns/{id}/tags (tag campaign + cascade to URLs)

### 3.8.4 Backend - Schemas ✅
- [x] Create server/schemas/tag.py (TagCreate, TagUpdate, TagResponse, etc.)
- [x] Update URLResponse to include tags list
- [x] Update CampaignResponse to include tags list

### 3.8.5 Testing (TDD - Write First) ✅
- [x] Tag CRUD tests (20+ test cases)
- [x] Tag initialization tests
- [x] URL tagging tests (single + bulk)
- [x] Tag filtering tests (AND/OR logic)
- [x] Campaign tagging tests
- [x] Verify all existing tests still pass (189/199; 9 pre-existing bcrypt + 1 network-flaky OG test, all unrelated)

### 3.8.6 Frontend Components ✅ (Phase 3.11)
- [x] TagBadge component (color-coded display): `.tag[data-color]` + `tagPill()` in `utils/tags.ts`
- [x] TagAutocomplete component (search + inline create): `mountTagInput()` in `utils/tag-input.ts`
- [x] TagFilter component (Pinterest-style multi-select): chips on the Links page, any/all match

### 3.8.7 Frontend Integration ✅ (Phase 3.11)
- [x] Add tags to Create URL form
- [x] Add tags to URL Card display
- [x] Add tags to URL Details page
- [x] Add tag filter to Dashboard
- [x] Add bulk tagging UI
- [x] Add tags to Campaign create (campaigns have no edit screen yet)
- [x] Tag management in Settings (rename/delete your tags)

---

## Phase 3.9: Shlink Lessons - Pre-Launch Hardening

**Goal:** Adopt high-priority gaps and "free" non-obvious architectural lessons from Shlink before AWS launch
**Duration:** ~1.5 days
**Priority:** 🔴 HIGH - Pre-launch debt that compounds if deferred
**Reference:** Shlink analysis (https://github.com/shlinkio/shlink) — CHANGELOG 4.0–5.0.2, docs at shlink.io/documentation/
**Rationale:** Items here are either bloqueantes (API versioning), GDPR-relevant (IP anonymization), or so cheap that skipping them is irrational (X-Request-Id, charset fallback)

### 3.9.1 API Versioning (BLOCKING) ✅
- [x] Mount all routes under `/api/v1/` prefix
- [x] Update frontend `apiGet/apiPost` base path (all dashboard pages)
- [x] Update Lambda + SAM template if any hardcoded paths (none required — `/{proxy+}` catch-all)
- [x] Document versioning policy (Keep-a-Changelog format) — see `CHANGELOG.md`
- [x] Update CORS / docs / OpenAPI title accordingly (CORS unchanged; README.md and CLAUDE.md endpoint references updated)
- [x] Fix `tests/conftest.py` to set `TESTING=1` so startup event is skipped (was failing to honor the gate)

### 3.9.2 URL Expiration & Visit Caps ✅
- [x] Add `valid_until` (TIMESTAMP timezone-aware, nullable) to URL model
- [x] Add `valid_since` (TIMESTAMP timezone-aware, nullable) to URL model
- [x] Add `max_visits` (INTEGER, nullable, ge=1) to URL model
- [x] Enforce in redirect handler: 410 Gone if expired, 410 Gone if max_visits reached, 404 if not yet valid
- [x] Expose fields in URLCreate / URLCustomCreate / URLUpdate / URLResponse schemas
- [x] Tests for expiry edge cases (9 new tests covering boundary, nullable, validity window, quota consumption)
- [x] Only clicks use up the cap, as `click_count` counts them: crawler previews aren't logged, and bot hits
  and pixel opens are logged but don't count (2026-09-28: the cap had counted every Visitor row)
- [ ] Future CLI / scheduled Lambda for `delete-expired` (deferred to Phase 6 — bundled with the post-launch optimization sweep)

### 3.9.3 Bot Detection in Analytics ✅
- [x] Add `is_bot` (BOOLEAN, default false) to Visitor model
- [x] UA-based detection at log time (reuse social crawler list + common scrapers)
- [x] Default analytics endpoints to filter `is_bot=false`
- [x] Add optional `?include_bots=true` query param for raw counts
- [x] Tests for bot vs human classification (`tests/test_analytics.py::TestBotFiltering`)

### 3.9.4 Crawlability & robots.txt ✅
- [x] Add `crawlable` (BOOLEAN, default false) to URL model
- [x] Add GET `/robots.txt` endpoint (default deny short URLs, allow only `crawlable=true`)
- [x] Expose `crawlable` field in URL schemas
- [x] Default-deny posture documented in `CHANGELOG.md`

### 3.9.5 GDPR - IP Anonymization ✅
- [x] Truncate IPv4 to `/24` (zero last octet) at insert time in Visitor logging
- [x] Truncate IPv6 to `/64` at insert time
- [x] Config flag `ANONYMIZE_REMOTE_ADDR` (default true)
- [x] Tests verifying no full IPs are persisted (`tests/test_network.py`)
- [x] Document GDPR posture in DEPLOYMENT.md — "GDPR posture" section

### 3.9.6 Architectural Lessons - "Free" Wins ✅
- [x] **X-Request-Id middleware** — `RequestIdMiddleware` in `main.py`
  - [x] Generate UUID per request if not provided
  - [x] Accept and propagate client-supplied `X-Request-Id` header
  - [x] Echo back in response headers
  - [x] Include in all log lines for CloudWatch correlation → 5.6.0: every `http.request` and `mcp.tool_call` line carries `request_id` (other lines, e.g. warnings and fastmcp's own errors, don't)
- [x] **SHORT_URL_MODE config (`strict` | `loose`)**
  - [x] In `loose` mode: lowercase generated codes and lowercase custom slugs at insert
  - [x] In `strict` mode: preserve case, treat `Abc` and `abc` as distinct
  - [x] Default to `loose` (~~Shlink's default~~: Shlink defaults to `strict`, and its `loose` also matches
        case-insensitively, which Shurly's doesn't 🔎 R6)
- [x] **Short-code collision retry**
  - [x] Verified existing 10-attempt retry loop in `create_short_url`
  - [x] Explicit retry-on-conflict test (`TestShortCodeCollisionRetry`)
- [x] **OG fetcher charset fallback** (Shlink fix #2564)
  - [x] Fall back to `<meta charset>` when Content-Type charset is missing/wrong
  - [x] Final fallback to UTF-8 with replacement so malformed pages can't crash creation
  - [x] Tests covering meta-charset decode and irrecoverable bytes
- [x] **TRUSTED_PROXIES configuration** (Shlink #2522)
  - [x] Do NOT auto-trust `X-Forwarded-For`
  - [x] `TRUSTED_PROXIES` env var (CIDR list)
  - [x] Only honor `X-Forwarded-For` when source IP matches a trusted proxy
  - [x] Document deployment guidance in DEPLOYMENT.md — "Trusted-Proxy Configuration" section; prod runs `TRUSTED_PROXIES=["172.31.0.0/16"]`
- [x] **DISABLE_TRACK_PARAM**
  - [x] Config: query param name (default `nostat`) that suppresses visit logging
  - [x] Tests confirming the redirect still happens but no Visitor row is inserted
- [x] **API key scoping (data model only, single scope at launch)**
  - [x] `User.api_key_scope` enum + `User.api_key_constraints` JSON column
  - [x] Enum: `FULL_ACCESS` (only enforced value at launch); reserved `READ_ONLY`, `CREATE_ONLY`, `DOMAIN_SPECIFIC`
  - [x] Tests for current `FULL_ACCESS` behavior unchanged
  - [x] Generate-key endpoint returns `{api_key, scope}`

### 3.9.7 Verification ✅
- [x] All existing tests pass after refactors (240 passing)
- [x] OpenAPI/Swagger reflects new schemas under `/api/v1/`
- [x] Manual smoke (settings load, app import, dev server, robots.txt) verified
- [x] CHANGELOG.md updated with the full Phase 3.9 entry following Keep-a-Changelog format

---

## Phase 3.10: Shlink Lessons - Medium Priority Enhancements

**Goal:** Adopt medium-priority Shlink features that strengthen B2B positioning without blocking launch
**Duration:** ~3-4 days
**Priority:** 🟡 MEDIUM - Schedule after 3.9 / 3.8, before or in parallel with Phase 4.5
**Reference:** Shlink analysis (gaps marked Medium); some items are model-only at this stage to avoid future migrations

### 3.10.1 Multi-Domain Foundation (model-only at launch) ✅
- [x] Create Domain model (id, hostname, is_default, created_at)
- [x] Add `domain_id` (FK, nullable) to URL model
- [x] Replace UNIQUE constraint on `short_code` with UNIQUE `(domain_id, short_code)`
- [x] Seed default domain row at startup (`shurl.griddo.io` from `default_domain` setting)
- [x] Update redirect resolver to match by `(host header → domain_id, code)`
- [ ] Frontend / domain management UI deferred (single-domain at launch — model-only)
- [x] Tests verifying same code can exist on different domains (`tests/test_phase310_multidomain.py`)

### 3.10.2 Dynamic Redirect Rules ✅
- [x] Create RedirectRule model (id, url_id, priority, conditions JSON, target_url, created_at)
- [x] Condition types: `device` (ios/android/desktop/linux/windows/macos), `language`, `query_param`, `before_date`, `after_date`, `browser`
- [x] Ordered evaluation by priority (first match wins)
- [x] Endpoints: GET/POST/PATCH/DELETE `/api/v1/urls/{code}/rules`
- [x] Update redirect handler to evaluate rules before default URL
- [x] Compatible with existing campaign personalization (rules evaluated first, then params injected)
- [x] Tests for each condition type + priority ordering (`tests/test_phase3102_redirect_rules.py`)

### 3.10.3 Email Tracking Pixel ✅
- [x] Endpoint GET `/{code}/track` returning 1×1 transparent GIF (Cache-Control: no-store)
- [x] Logs as Visitor row with `is_pixel=true` flag
- [x] Pixel hits excluded from click analytics by default
- [x] Tests for pixel response (correct content-type, 43-byte GIF89a, visit logged) (`tests/test_phase3103_pixel.py`)

### 3.10.4 Orphan Visits Tracking ✅
- [x] Add OrphanVisit model (id, type enum, attempted_path, ip, ua, referer, created_at)
- [x] Type enum: `base_url`, `invalid_short_url`, `regular_404` (`regular_404` reserved for future global 404 handler)
- [x] Catch-all handler logs orphan visits before returning 404
- [x] Endpoint GET `/api/v1/analytics/orphan-visits`
- [x] Tests for orphan logging + listing endpoint (`tests/test_phase3104_orphan_visits.py`)

### 3.10.5 CSV Export for Analytics ✅
- [x] Add `?format=csv` to visit / analytics endpoints
- [x] Use FastAPI `StreamingResponse` + `csv.writer`
- [x] Applied to: URL daily/weekly stats, geo distribution, campaign users (with flattened `user_data`)
- [x] Tests verifying CSV structure and headers (`tests/test_phase3105_csv.py`)

### 3.10.6 Configurable Redirect Behavior ✅
- [x] `REDIRECT_STATUS_CODE` config (302 default; supports 301/307/308) with validation
- [x] `REDIRECT_CACHE_LIFETIME` config + `Cache-Control` header (default `private, max-age=0`)
- [x] Tradeoff documented in `server/core/config.py` comment block
- [x] Tests for each status code + cache header (`tests/test_phase3106_redirect_config.py`)

### 3.10.7 Verification ✅
- [x] All existing tests still pass — **285 passing**
- [x] Redirect path performance: rules eval is O(n) per URL with n typically <10
- [x] Frontend remains compatible (no UI changes required for 3.10.1–3.10.4)

---

## Phase 3.11: Brand & Frontend Redesign ✅

**Goal:** Implement the UX/UI brief (`design/Shurly-Brief.zip`): identity, design system, every screen.
**Docs:** `design/DESIGN_SYSTEM.md` (tokens, voice, patterns, paywall, brief Q1–Q10), `design/brand/README.md`, `/styleguide/`

- [x] Brand: wordmark + "s." isotype with the lime click dot, lockups, favicon pack, OG card (SVG + PNG 1x/2x/3x)
- [x] Design system: Tailwind 4 `@theme` tokens, component classes, 11 line illustrations, living styleguide
- [x] Screens: landing + pricing, login/register, 404, links dashboard, create, link details, campaigns
      list / 4-step wizard / details, analytics, settings (account, API & MCP, tags, notifications, plan)
- [x] Static build (dropped `@astrojs/node`; record pages use `?code=` / `?id=`)
- [x] API support (TDD, `tests/test_phase311_ui_api.py`): `GET /urls/{code}`, `POST /urls/fetch-metadata`,
      list `q` + repeatable `url_type`, `click_count` / `campaign_id` / `user_data` on URLs,
      `short_url` + `title` in overview `top_urls`, tags on campaign detail
- [x] Verified: 336 tests, `astro check` clean, e2e smoke of 14 core flows, 1440 px + 390 px layouts
- [x] Astro 7.3.4 upgrade (Vite 8): rendered text + screenshots match the Astro 6 build
- [ ] Custom-preview badge on link cards; campaign edit screen; Pro billing (pricing TBD)

---

## Phase 3.12: Account Profile & Avatar

**Goal:** Give users a profile they manage from **Settings → Account**: first name, last name, country,
timezone, and an avatar uploaded with a crop step. Name and timezone also lay the groundwork for anything
scheduled later (sends, reports, digests) — which needs to know the user's local time.
**Priority:** 🟢 LOW - UX polish; no dependency on Phase 4/5
**Today:** built. Names, country and time zone (3.12.1–3.12.2), and the avatar (3.12.3–3.12.6), all in
`user_profiles`. The app header and Settings → Account show the photo, or the first name's initial (the
email's without one). Left: trying touch pan and pinch on a real phone (3.12.7).
**Note (2026-09-27):** with sign-in through Google (3.13), the ID token already carries the name and a photo URL.
Pre-fill the profile from them; the upload and crop below remain for changing the photo. → names done: the web
sign-in asks for the `profile` scope (the MCP's doesn't), and `given_name`/`family_name` start the profile of an
account without one; an existing profile is never touched, cleared names included
(`server/utils/google_sign_in.py`). The photo is left out (decided 2026-09-28).

### 3.12.1 Data model — new `user_profiles` table ✅ decided
Storage is the database, not S3 (the Phase 4.5/4.6 bucket + CloudFront doesn't exist yet). And it's a
**new table rather than new columns on `users`**:
- ~~No migrations~~ → out of date: Alembic runs migrations at startup since 3.14.1, and columns would be
  fine. The table came with migration 0008 (a new table only, so the previous release is unaffected).
- **`users` is read on every request.** `server/core/auth.py` loads `User` on every authenticated call
  (JWT and API key); keeping profile and image out of it keeps that path lean.

```
user_profiles
  user_id              UUID  PK, FK -> users.id  ON DELETE CASCADE   (1:1)
  first_name           String(100)  nullable
  last_name            String(100)  nullable
  country              String(2)    nullable   ISO 3166-1 alpha-2 ("ES", "MX", …)
  timezone             String(64)   nullable   IANA name ("Europe/Madrid", "Atlantic/Canary", …)
  avatar               LargeBinary  nullable   the final cropped square; SQLAlchemy deferred()
  avatar_content_type  String(32)   nullable   e.g. "image/webp"
  avatar_updated_at    DateTime     nullable   cache-busting version for the image
  updated_at           DateTime
```
- [x] Model `server/core/models/user_profile.py`, registered in `__init__.py`; `User.profile` relationship
      (`uselist=False`, `back_populates`) — lazy, never joined into the auth query
- [x] `avatar` column mapped with `deferred()`, so reading names/country/timezone never loads the image bytes
      → migration 0009; tested for reading and saving the profile, and for a 304
- [x] Row created lazily on first save; existing users simply have no row and read as an empty profile
- [x] All fields nullable — nothing is required to keep using the product

**Timezone is its own field, not derived from country.** A country does not determine a timezone:
Spain alone has two (`Europe/Madrid`, `Atlantic/Canary`), and Mexico, Brazil, the US, Canada, Russia and
Australia have several. So store `country` *and* `timezone`:
- Store the **IANA name, never a GMT/UTC offset** — offsets change twice a year with DST, the name doesn't.
  Scheduling code stores instants in UTC and converts with `zoneinfo` at the edges.
- Pre-fill from the browser (`Intl.DateTimeFormat().resolvedOptions().timeZone`); use `country` to narrow
  the timezone picker, and auto-select when the country has a single zone
- Validate server-side against `zoneinfo.available_timezones()`; validate `country` against ISO 3166-1
  → against the `tzdata` package instead (a dependency, `server/utils/timezones.py`): the production image's
  database (Debian) has 486 zones and none of the legacy names browsers still report (`Asia/Calcutta`, from
  Chrome in India). Countries come from its `iso3166.tab`. A legacy name is stored as the current one
  (`Asia/Kolkata`); the names zone.tab gives a country stay (`Europe/Stockholm`). The picker's lists are
  `frontend/src/data/timezones.json`, generated from the same package (`scripts/generate_timezones.py`)

### 3.12.2 Profile fields (frontend + API)
- [x] Account section: first name, last name, country (select), timezone (select, filtered by country,
      pre-filled from the browser) → Settings → Account → Profile; a country with one zone picks it
- [x] `PATCH /api/v1/auth/me/profile` — partial update; `GET /api/v1/auth/me` returns the profile
      (names, country, timezone, avatar version) alongside the existing fields → `profile` on /auth/me
      (additive), and the MCP tool `update_my_profile`; the avatar version comes with the avatar
- [x] Header initial comes from `first_name` when set, falling back to the email as today

### 3.12.3 Avatar picker (frontend)
- [x] Avatar block at the top of `AccountPanel.astro`: current avatar (or initial placeholder) + change / remove
- [x] Two ways in: **drag & drop** an image onto the avatar area, or **select a file** from the computer
- [x] Accept JPEG, PNG, WebP; reject anything else and oversized files with an inline error (limit TBD, e.g. 5 MB)
      → 10 MB before the crop (`avatarFileProblem`, `src/utils/avatar.ts`); an image that won't open says so too

### 3.12.4 Avatar crop: zoom + pan before saving
- [x] Preview the image inside the same circle the avatar is shown in
- [x] **Zoom** (slider + wheel/pinch) and **pan** (drag) the image under the circle
- [x] **Hard constraint — the circle is always fully covered.** No part of the circle may ever show the
      placeholder behind it:
  - minimum zoom = the scale at which the image's **shorter side** equals the circle's diameter ("cover");
    zooming out stops there
  - pan is clamped so no image edge can cross into the circle, at every zoom level (re-clamp on zoom)
  - initial state: minimum zoom, centred
  → `src/utils/avatar-crop.ts`: the frame is the circle's bounding square, and covering it covers the circle
    and the saved square alike
- [x] Keyboard access: arrow keys pan, +/- zoom; Save / Cancel; Esc cancels
- [x] Follow `design/DESIGN_SYSTEM.md` (tokens, `Modal`, copy voice) and add the component to `/styleguide/`
      → `ui/AvatarCropper` (markup) and `src/utils/avatar-cropper.ts` (`cropAvatar(file, onSave)`); Forms → Photo

### 3.12.5 Avatar save (backend)
- [x] Crop **client-side** and upload the final square only (e.g. 512×512 WebP, ~30–80 KB), so the server
      never handles originals or crop maths → a 512 px WebP (PNG where the browser can't make WebP); the
      server still re-encodes whatever it gets (below)
- [x] `PUT /api/v1/auth/me/avatar` (upload), `DELETE /api/v1/auth/me/avatar` (back to the initial),
      `GET /api/v1/auth/me/avatar` (serves the bytes with `Cache-Control` + an ETag from `avatar_updated_at`)
      → the PUT's body is the image (2 MB, refused as it streams in). GET: 404 without one; immutable only
      for the `?v=` URL of the current version, `private, no-cache` otherwise; 304 on If-None-Match;
      nosniff. None of it is an MCP tool (`server/app/avatar.py`)
- [x] Server-side validation regardless of the client: real image type (magic bytes, not just
      `Content-Type`), dimensions, size cap → and re-encoded for GDPR: decoded with only the decoder the magic
      bytes name, 4096 px a side at most (checked before the pixels load, and Pillow's `MAX_IMAGE_PIXELS`
      set to match), turned by its EXIF orientation, stored as a 512 px WebP without EXIF (GPS), XMP or
      ICC (`server/utils/avatar.py`). Pillow parses untrusted input here: keep it up to date
- [x] **Watch out:** the API authenticates with a bearer header, which a plain `<img src>` cannot send.
      The frontend must fetch the avatar through the authenticated client and display it via an object URL
      (keyed on the avatar version, so it's only re-fetched when it changes) → `avatarUrl(version)`,
      `src/utils/avatar.ts`; after the first load, the browser's cache answers

### 3.12.6 Show it everywhere
- [x] Replace the initial with the avatar in the app header (`AppLayout.astro`) and in Account
- [x] Fall back to the initial when there is no avatar or the image fails to load

### 3.12.7 Verification
- [x] Backend tests (TDD): profile round-trip through `db_session`; `PATCH` partial updates; country and
      timezone validation (reject unknown ISO codes and non-IANA zones, accept `Atlantic/Canary`);
      user without a profile row reads as empty; deleting a user cascades to the profile
      → `tests/test_phase312_profile.py`; the pre-fill from Google in `tests/test_phase3132_google_sign_in.py`
- [x] Avatar tests: upload, replace, delete, type/size rejection, auth required, ETag/cache headers, and
      that loading the profile does **not** load the avatar bytes (deferred) → `tests/test_phase312_avatar.py`,
      with the metadata strip (a photo with GPS), EXIF orientation, 4096 px and decompression bombs
- [x] Crop-logic unit tests for the cover constraint: min zoom, pan clamping at every zoom, re-clamp on
      zoom-out, portrait / landscape / square / very small images → `frontend/tests/avatar-crop.test.mjs`
- [ ] Manual check on desktop (drop + picker) and mobile (picker + touch pan/pinch), 1440 px and 390 px
      → done at 1440 (picker, drop, drag, wheel, keys, a refused upload, cancel, remove) and the layout at
      390; left: touch pan and pinch on a real phone

### 3.12.8 Analytics days where the viewer is ✅
Every day was a UTC calendar day, whatever the viewer's zone: in Madrid, clicks from 00:00 to 02:00 counted
for the day before. Now a day is local to the viewer (`server/utils/local_days.py`).
- [x] The zone: `?tz=` (an IANA name, the profile's rules, 422 otherwise), else the profile's, else UTC. `tz`
      changes only how visits are grouped into days, never which count. Responses say it (`timezone`)
- [x] A day runs from local midnight to local midnight: aware in the zone, converted to naive UTC like
      `visited_at`. DST days last 23 or 25 hours; a day can start at 18:30 UTC (Asia/Kolkata)
- [x] One query per series, bounded by the whole range before a sum per day. No database time zone
      functions, and no SQL `date()`, which returns a string on SQLite and hid wrong counts from the tests
- [x] Link daily and weekly, the overview's recent activity, the campaign summary's timeline, and the MCP's
      `get_url_analytics_summary`: the app and the MCP give the same numbers
- [x] Fixed: the weekly stats left today out (their 8 weeks ended yesterday)
- [x] Changed: the overview's `recent_clicks_7d` is the sum of its 7 local days, so it matches the chart
      (it was a rolling 168 hours)
- [x] The charts' "Today" is today in that zone; without a zone in the profile, a hint links to
      Settings → Account
- [ ] An index on `visits` for these queries: there are single-column ones (`url_id`, `short_code`,
      `visited_at`), no composite `(url_id, visited_at)` or `(short_code, visited_at)`. Measure on real
      volumes before adding one


### 3.12.9 Names where people are listed
- [x] Settings → Organization: members and removed people by name, the email under it (the email alone
      without a name). `GET /organization/members` and `/removed-members` gain `first_name` and `last_name`,
      and so does the MCP's `list_organization_members`; the profiles load with the list, not one per person.
      Dialogs name the account too ("Their account is …"), as two people can share a name
- [x] "Created by" on links and campaigns by name: `created_by_email` across the URL and campaign responses
      → `created_by_first_name` and `created_by_last_name` next to the email, on campaigns and links; the
      cards and the campaign and link pages by name, the email as tooltip. Each list loads its creators'
      profiles in one query, pinned by `tests/test_phase312_creator_names.py`
- [ ] Photos in the members list: needs an endpoint that serves another member's avatar

---

## Phase 3.13: Sign in with Google (Workspace), with an optional password 🔎 R1 · 🔎 R11

**Goal:** people at Griddo get in with their Griddo Google account. An account can also have a password, set by
its owner once signed in, and both lead to the same account.
**Priority:** 🔴 HIGH — before the dogfood. `POST /api/v1/auth/register` has accepted any email since the first
deploy (2026-04-27): no domain check, no confirmation, no rate limit. Anyone who finds `s.griddo.io` can create
links on a Griddo domain, which is how URL shorteners end up on phishing blocklists.
**Decided (2026-09-27):** Griddo's mail runs on Google Workspace. Accounts are created only by signing in with
Google (`@griddo.io`); a password is optional. This replaces the email-confirmation design, which moved to 3.15
for external users. No email sending needed here.

Why both can live together: after either login Shurly issues its own JWT, as today, so the API, the dashboard and
the MCP's API keys don't care how someone signed in. Changing methods later (enforcing SSO, or leaving Google)
logs nobody out: JWTs keep working until they expire (7 days in `deploy_ecs.sh`), API keys until revoked.

### ~~3.13.1 Stopgap: close sign-up in production now~~ (dropped 2026-09-27)
Not needed: production has no users and no frontend yet, and 3.13 locks sign-up down before anyone is invited.
Until then `POST /auth/register` stays reachable through the public API and its `/docs` page.

### 3.13.2 Google sign-in
- [x] Google Cloud project inside the griddo.io organization, OAuth consent screen **Internal** (only Griddo
      accounts can sign in), a web OAuth client with the redirect URIs of the web sign-in and of the MCP proxy
      (5.8). Done by whoever administers Workspace → created by the user; its redirect URIs (the web's, local
      and the MCP's) verified 2026-09-28. Its client secret in Secrets Manager is an open line under 6.3
- [x] `GET /api/v1/auth/google/start` → Google (OpenID Connect, `state` + PKCE, `hd=griddo.io` as a hint) →
      `GET /api/v1/auth/google/callback` → `server/app/google_auth.py`, whose docstring is the frontend's
      contract. The state is hashed, single use and 10 minutes, and bound to the browser by a cookie
- [x] Verify the ID token server-side: signature, `aud`, `iss`, `exp`, `email_verified`, and `hd` equal to the
      organization's domain (the `hd` parameter sent to Google is only a hint) → google-auth for the first
      four, `server/utils/google_oidc.py` for the last two
- [x] New table `user_identities` (user_id, provider, subject, email, created_at; unique provider + subject): an
      account is recognised by Google's `sub`, which survives an email rename → migration `0004`
- [x] The first sign-in creates the user and adds them to the organization as a member (3.14); later ones match
      by `sub` → `server/utils/google_sign_in.py`. An address whose account is linked to another `sub` is
      refused (`account_conflict`), never linked
- [x] Hand the session to the static frontend with a one-time code that the page exchanges by `POST` for the JWT,
      so the JWT never travels in a URL → `{FRONTEND_URL}/login/#code=…`, then
      `POST /api/v1/auth/google/exchange`; the code is hashed, single use and 60 seconds
- [x] `auth.login` line in the event log with the method (`google` | `password`), needed before enforcing SSO
- [x] With Google as the only way in, `POST /auth/register` goes, and with it the MCP `register` tool
      (`tests/test_phase52_mcp_tools.py` pins the surface). `POST /auth/login` stays, for passwords → 404
      unless `ALLOW_PASSWORD_SIGNUP` (local development and tests only)

### 3.13.3 Optional password, set by the account's owner
- [x] Settings → Account: set, change or remove a password, only while signed in, so it's always set by someone
      who already proved they own the account → API done: `PUT`/`DELETE /api/v1/auth/password`, JWT sessions
      only, and without the current password a sign-in at most 10 minutes old (`reauth_required`);
      `/auth/me` says `has_password` and `has_google`. The page is 3.13.5: a `reauth_required` offers "Sign in
      with Google again" and comes back to Settings
- [x] Never link a Google identity to a password nobody verified. That's account pre-hijacking: someone
      registers `ana@griddo.io` with a password before Ana, Ana later signs in with Google, and the attacker keeps
      a way in. With accounts created only through Google, the path doesn't exist → for accounts from before
      3.13, the first Google sign-in links them but clears the password, revokes the API key and ends every
      session (`users.sessions_valid_from`), and logs `auth.identity_linked`
- [x] Forgot the password → sign in with Google and set a new one; no reset email 🔎 R2 → API done (the
      `PUT /api/v1/auth/password` above, right after signing in with Google); the page is 3.13.5, and the login
      page's "Forgot password?" says so

### 3.13.4 Changing methods without disruption
- [ ] Setting to turn password login off for the organization's domain (SSO enforced), keeping one break-glass
      account in case Google fails or is misconfigured. Before turning it off, the `auth.login` lines show who
      still uses a password
- [ ] Leaving Google some day: everyone sets a password while Google still works, then Google sign-in goes off
- [ ] Offboarding checklist: suspending someone in Google blocks their Google sign-in, but a Shurly password and
      their API key keep working until the account is deactivated in Shurly. MCP sign-ins with Google (5.8):
      deactivating refuses them at once (requests and refreshes); a Google suspension bites within 60 s (the
      cached check); their Google tokens stay in `mcp_oauth_store`, encrypted and unusable, until they expire

### 3.13.5 Frontend
- [x] "Sign in with Google" on the login page; the register page goes
- [x] Settings → Account: the password section of 3.13.3
- [ ] Needs the frontend hosted (4.10)

### 3.13.6 Verification
- [x] Tests (TDD) against a faked Google: `hd` and `email_verified` enforced, `state` checked, first sign-in
      creates the user and the membership, matching by `sub` after an email change, one-time code single use and
      short-lived, passwords set only while signed in, register gone → `tests/test_phase3132_google_sign_in.py`
      and `tests/test_phase3133_passwords.py`, on `tests/fake_google.py` (real RS256 tokens, no network)
- [ ] End to end against the real Google project with a Griddo account

---

## Phase 3.14: Organization and roles — links belong to the organization by default 🔎 R7

**Goal:** everyone at Griddo sees and works on the same links, as with Shlink today, and three roles decide who
may change what. A personal link is possible, but only when someone chooses it on purpose.
**Decided (2026-09-27):**
- Links and campaigns belong to the organization by default; personal ones are opt-in.
- An **organization** entity (the "team" of earlier drafts) with three roles: **owner**, **admin**, **member**.
- Admins can edit and delete the organization's links. Owners promote members to admin and demote them.
- An admin can't demote an owner. An owner stops being one by stepping down or handing the role over, and the
  only owner must hand it over first.
- The rest of 3.14.2 and 3.14.3 (the permissions table, the role-change rule, the first owner from
  configuration, two owners, personal links of people who leave) was proposed in review and accepted the same day.

**Priority:** 🔴 HIGH — before the dogfood. With no users yet, nothing has to be migrated.
**Today:** every link, campaign and stat is scoped to its creator. Some 20 queries filter by `created_by`
(`server/app/urls.py`, `campaigns.py`, `analytics.py`, `mcp_server/curated.py`), so each person sees only their
own links. Tags are already global.

### 3.14.1 Schema: adopt Alembic first
- [x] Alembic, with a baseline of the current schema (`0001`, identical to what `create_all()` built). `create_all()`
      only creates missing tables, and this phase adds columns to `urls` and `campaigns` (4.3 planned the switch
      "before the first non-additive change"; adding a column to an existing table already needs it)
- [x] Migrations run at startup under a Postgres advisory lock, so tasks that boot together don't race
      (`server/core/migrations.py`); production gets stamped at the baseline. Tested on PostgreSQL in CI
- [x] `organizations` (id, name, google_domain, created_at) and `organization_members` (organization_id, user_id,
      role: `owner` | `admin` | `member`, joined_at)
- [x] `urls.organization_id` and `campaigns.organization_id`, nullable: set = organization link, NULL = personal.
      Migration `0003` gives the organization every existing link and campaign, and creates the organization when
      the app hasn't yet 🔎 R12
- [x] Update "Adding a New Model" in `CLAUDE.md` with the migration step

### 3.14.2 Roles
| | member | admin | owner |
|---|:-:|:-:|:-:|
| See the organization's links, campaigns and stats | ✓ | ✓ | ✓ |
| Create links and campaigns (organization or personal) | ✓ | ✓ | ✓ |
| Edit and delete the ones they created | ✓ | ✓ | ✓ |
| Edit and delete anyone's organization links and campaigns | | ✓ | ✓ |
| Remove members from the organization | | ✓ | ✓ |
| Promote members to admin, demote admins | | | ✓ |
| Make other owners, step down, hand the role over | | | ✓ |

- [x] Rule: nobody changes the role of someone whose role is equal to or above theirs, and nobody grants a role
      above their own. So an admin can't demote an owner, nor another admin (otherwise two admins could strip
      each other)
- [x] At least one owner, always: the last owner can't step down, leave, be demoted or be deactivated until
      another owner exists. Checked in one transaction, so two owners demoting each other at once can't leave none
- [x] "Hand the role over" = make someone owner and step down, in one action
- [x] The first owner comes from configuration (`BOOTSTRAP_OWNER_EMAIL`), not from whoever signs in first
- [ ] Two owners from day one (yours to do after the first sign-ups; the break-glass is in place): if the only owner leaves Griddo and their Google account is suspended,
      nobody can manage roles. Break-glass: changing `BOOTSTRAP_OWNER_EMAIL` restores an owner
- [x] Every role change writes an `org.role_changed` line to the event log (who, whom, from, to)
- [x] Only accounts on `ORGANIZATION_DOMAIN` (default `griddo.io`) join: exact, case-insensitive match, so
      `evilgriddo.io`, `griddo.io.evil.com` and `eu.griddo.io` stay out; empty = anyone. An outsider keeps an
      account with personal links only, and each refused join logs `org.join_refused` (user id, no email) 🔎 R13

### 3.14.3 Behaviour
- [x] One organization at launch, "Griddo", with `google_domain = griddo.io`: whoever signs in with a Griddo
      Google account joins as a member (3.13) → the settings' defaults, seeded at startup
      (`test_at_launch_it_is_griddo_on_griddo_io`), and the first Google sign-in joins it as a member
      (`test_the_first_sign_in_makes_the_account_and_joins_the_organization`)
- [x] New links and campaigns belong to the organization unless the request asks for `visibility: "personal"`:
      API field, MCP tool argument, and a UI toggle that starts off: the "Personal" switch on quick create, the
      full editor and the campaign wizard (`components/app/VisibilityToggle.astro`). An account outside any
      organization gets a note instead, since everything it creates is personal
- [x] Every read scoped to "my organization's links + my personal links", and every write checked against the
      role: link CRUD, bulk tags, redirect rules, campaigns, analytics (overview, per link, per campaign, CSV) and
      the curated MCP tools. An API key acts with its user's role. `server/utils/access.py`: a link you can't see
      is a 404, one you can see but not change is a 403
- [x] `created_by` stays, so lists can show who created each link (`created_by_email` in the responses). The
      frontend shows "Created by …" ("you" for your own) and a "Personal" badge on link and campaign lists and
      pages, and locks edit/delete where the viewer's role can't change the item (`utils/viewer.ts`)
- [x] Someone leaves: their personal links keep redirecting, and an owner can move them to the
      organization so someone can still manage them (`POST /api/v1/organization/adopt-personal-links`). The UI
      offers it to an owner right after they remove someone in Settings → Organization; skipping is safe
- [x] One organization per user at launch (the membership table allows more later). Tags stay global while
      there's a single organization; scope them per organization before a second one
- [x] Settings → Organization: members, roles, remove, hand the role over. Each row offers only what the
      viewer's role allows; the API's 403/409 message is shown as is (`components/settings/OrganizationPanel.astro`)
- [x] Removed people list in Settings → Organization, so an owner who skipped the move at removal time can still
      move someone's personal links later → `GET /api/v1/organization/removed-members` (owners only; closed
      accounts on the organization's domain, with what they still own; not an MCP tool)

### 3.14.4 Verification
- [x] Tests (TDD): visibility matrix (A sees B's organization links, not B's personal ones), organization by
      default and personal only on request; the roles table row by row, through the API and the MCP; the
      last-owner invariant (step down, demote, deactivate, two owners demoting each other); analytics and CSV
      follow the same scope (`tests/test_phase3142_organization_roles.py`,
      `tests/test_phase3143_organization_links.py`)
- [x] Migrations run against PostgreSQL (docker-compose), not only the in-memory SQLite of the test suite → PostgreSQL 17 service in CI (`--require-postgres`)

---

## Phase 3.15: External users by invitation (later)

**Goal:** people outside Griddo's Google Workspace (agencies, freelancers) get an account when someone invites
them.
**Priority:** 🟢 LOW — no external users yet (2026-09-27). Build it when the first one arrives.
**Needs email sending**: an invitation that reaches the person's mailbox is what proves the address is theirs, and
without Workspace behind them a forgotten password can only be recovered by email.

- [ ] Invitation: an owner or admin invites an email → email with a single-use link (≥32 random bytes, stored as
      a SHA-256 hash, with an expiry) → the page asks for a password and creates the account. Opening the link
      changes nothing, so mail security scanners that open links by themselves can't activate anything
- [ ] Password reset by email, on the same token machinery
- [ ] Amazon SES (`griddo-main`, eu-south-2): verify the sender domain (DKIM CNAMEs in the `griddo.io` zone in
      `griddo-production`), agree the sender with whoever runs Griddo's mail so SPF/DMARC stay valid, and
      **request production access**: the sandbox only delivers to verified domains (AWS usually answers within a
      day). ECS task role with `ses:SendEmail`, so no SMTP password to store
- [ ] `server/utils/email.py` with a `console` backend for dev and tests; templates with Jinja2
- [ ] Rate limits on invitations, resends and resets, since each one sends an email
- [ ] The role an external gets, and whether they see every organization link (maybe a guest role that only
      sees what's shared with them)
- Without SES, if externals stay few: (a) a copyable invitation link sent by the inviter's own means; it works
  for whoever holds it, and resets are manual; (b) externals with their own Google account sign in with it: the
  consent screen moves from Internal to External and Shurly admits only the organization's domain or invited
  emails; no SES, but no help for people on Microsoft 365 or other mail

---

## Phase 3.16: Per-link analytics, as on Shlink's link page

**Goal:** a link's page answers what Shlink's did, for a period:
- when: a chart by day, week or month, and the counts by hour of day and day of week;
- from what: OS, browser, device and referrer;
- from where: countries;
- which visits: a list and its CSV.

Clicks and email opens are shown separately. The page today has 7 days, 8 weeks and top countries. Shlink's
screens are `design/shlink-*.png` (local only, not in git: they show a real link's visits).

**Split (2026-09-29):** the API is Agent 1's, the page Agent 2's, built in parallel against the contract below,
which follows Agent 2's approved layout. Cities wait for the user's decision and aren't designed here.

### 3.16.1 The contract

**Kinds of visit.** Every visit is exactly one kind:

| Kind | Which visits |
|---|---|
| `click` | Not a pixel hit, not a bot: what every other count calls a click (`_exclude_bots`) |
| `open` | A hit on the email pixel (`/{code}/track`), not a bot |
| `bot` | Any visit whose user agent was a bot's, pixel hits included |

Opens overcount: Apple Mail Privacy Protection loads the pixel, like every image, when a message arrives, read or
not. The page says so next to them, and so do the API docs.

`/breakdown`, `/visits` and `/visits.csv` filter by kind with `type=clicks|opens|bots|all`. `/timeseries` gives
clicks and opens side by side.

Every route below:
- is under `/api/v1/analytics/urls/{short_code}/`, takes `?domain=` like the others (8.3), and a JWT or an API key;
- answers only for a link the caller can see (`find_url`, `viewer`), and 404 otherwise;
- except `/totals`, takes one period:

| Param | Meaning |
|---|---|
| `period` | The last N local days, today included: an integer from 1 to 731 (the page uses 7, 30 and 90). Default 30 |
| `from`, `to` | A custom range: local dates, `YYYY-MM-DD`, both inclusive. Give both or neither, and not with `period`. At most 731 days. A `to` after today counts up to today |
| `tz` | As now: an IANA zone, else the profile's, else UTC. Its rules set the days, the weeks and the hours |

Each of these answers 422:
- a `period` outside 1 to 731;
- `from` after `to`, or a range longer than 731 days;
- a range that starts after today;
- `period` together with `from`/`to`, or `from` or `to` alone;
- an unknown `tz`, `type` or `group_by`.

Every response starts with the same fields. `from` and `to` are the range counted, after `period` or clipping,
for the page to show:

```json
{"short_code": "ia-bcn-griddo", "domain": "go.griddo.io", "from": "2026-07-01", "to": "2026-09-28",
 "timezone": "Europe/Madrid"}
```

Missing values have labels, not nulls: `"Unknown"` (a country, OS, browser or device), and `"Direct"` (no referrer).
Dates are local: dates as `YYYY-MM-DD`, and moments as ISO 8601 with the zone's offset.

**`GET …/totals`**: the header's all-time numbers. Takes only `domain` and `tz`.

```json
{"short_code": "ia-bcn-griddo", "domain": "go.griddo.io", "timezone": "Europe/Madrid",
 "clicks": 34, "opens": 12, "countries": 5, "last_click_at": "2026-09-27T23:54:12+02:00"}
```

- `clicks` is the link's `click_count`.
- `countries` is how many distinct countries its clicks came from; "Unknown" isn't one.
- `last_click_at` is the latest click, or null. It isn't `URL.last_click_at`, which bots and crawler previews
  also update.

**`GET …/timeseries?group_by=day|week|month`** (default `day`)

```json
{...the common fields..., "group_by": "week", "clicks": 34, "opens": 12,
 "stats": [{"start": "2026-07-01", "end": "2026-07-05", "clicks": 2, "opens": 0},
           {"start": "2026-07-06", "end": "2026-07-12", "clicks": 0, "opens": 1}, …],
 "hour_of_day": [{"hour": 0, "clicks": 1, "opens": 0}, …, {"hour": 23, "clicks": 3, "opens": 1}],
 "day_of_week": [{"day": 1, "clicks": 6, "opens": 2}, …, {"day": 7, "clicks": 1, "opens": 0}]}
```

- Clicks and opens are both in every bucket, so the page switches between them without asking again.
- `stats` covers the local days, ISO weeks (from Monday) or months of the range, oldest first, with zeros. `end`
  is inclusive, and the first and last buckets are clipped to the range, like the first week above.
- `hour_of_day` has 24 entries (0 to 23) and `day_of_week` 7 (1 is Monday), counted on local time over the range.
  On the day DST ends, both 02:00s count in hour 2.

**`GET …/breakdown?type=clicks`** (`clicks`, `opens`, `bots` or `all`)

```json
{...the common fields..., "type": "clicks", "total": 34,
 "os":        [{"name": "Windows", "count": 14, "share": 0.4118}, …, {"name": "Unknown", "count": 1, "share": 0.0294}],
 "browsers":  [{"name": "Chrome", "count": 20, "share": 0.5882}, …],
 "devices":   [{"name": "desktop", "count": 25, "share": 0.7353}, …],
 "referrers": [{"name": "www.linkedin.com", "count": 18, "share": 0.5294}, {"name": "Direct", "count": 15, "share": 0.4412}, …],
 "countries": [{"name": "ES", "count": 25, "share": 0.7353}, …, {"name": "Unknown", "count": 2, "share": 0.0588}]}
```

- Every value is listed, by count and then name. `share` is the count over `total`, from 0 to 1 with 4 decimals,
  so each dimension adds up to 1, give or take the rounding.
- OS and browser are families, parsed from the user agent at query time (`server/utils/user_agent.py`):
  - OS: Windows, macOS, iOS, Android, Linux, Chrome OS;
  - browser: Chrome, Safari, Firefox, Edge, Opera, Internet Explorer, Bot.

  New names can appear, so the page shows any string it gets.
- Device is `desktop`, `mobile`, `tablet` or `other` (a bot's), from the parser's `device_type`. The redirect
  rules read the same parser, but their `device` condition gives OS families (ios, android…), not a device class.
- A referrer is its host, lowercased: `www.linkedin.com`, or `com.linkedin.android` for the app
  (`android-app://…`). Never its path or query.
- A country is an ISO code, as elsewhere; the page shows its name.

**`GET …/visits?type=clicks&page=1&page_size=20`**

```json
{...the common fields..., "type": "clicks", "total": 34, "page": 1, "page_size": 20, "pages": 2,
 "visits": [{"visited_at": "2026-09-27T23:54:12+02:00", "kind": "click", "country": "ES", "browser": "Chrome",
             "os": "Windows", "device": "desktop", "referrer": "www.linkedin.com"}, …]}
```

- Newest first. `page_size` is 1 to 100, default 20. `total` is for "1–20 of N". A page past the last is an empty
  list, not an error.
- **No IP, anonymized or not, no user agent and no full referrer.**

**`GET …/visits.csv?type=all`**: every visit of the period, streamed, with no pages.
- The columns are the list's, plus the raw user agent: `visited_at,kind,country,browser,os,device,referrer,user_agent`.
  Still no IP.
- `type` defaults to `all` here. Pass the list's `type` to export only what it shows.
- Every cell is spreadsheet-safe (`stream_csv`): a user agent or a referrer comes from anyone.
- A route of its own, not `?format=csv`, so the MCP can list visits a page at a time but can't pull the whole file
  into an assistant's context.

**Unchanged:** `/daily`, `/weekly` and `/geo`, with `include_bots`, for existing clients and the MCP
(`get_url_daily_stats`, `get_url_weekly_stats`, `get_url_geo_stats`, and the curated `get_url_analytics_summary`).
The page moves to the routes above. The link response (`URLResponse`) doesn't grow: the list endpoint shares it,
and every link on it would pay for the header's numbers.

**MCP:** the new routes become tools (`get_url_totals`, `get_url_timeseries`, `get_url_breakdown`,
`list_url_visits`). `/visits.csv` is excluded.

### 3.16.2 API (Agent 1)
- [x] The period params, one dependency for every route: `period`, `from`/`to`, clipping, the 422s, `tz`
      (`Period`, `server/utils/local_days.py`)
- [x] The kinds (`click`, `open`, `bot`) as one filter, next to `_exclude_bots`, which stays what a click is
      (`_of_type`; `kind_of` in `server/utils/visit_facets.py` draws the same lines)
- [x] `/totals`
- [x] `/timeseries`: the range's visits read once (`visited_at` and the kind), then bucketed in Python on local
      time: the days, weeks, months, hours and weekdays
- [x] `/breakdown`: grouped in SQL by user agent, referrer and country, each distinct user agent parsed once
- [x] `/visits`: paged in SQL, each page's user agents parsed. `/visits.csv`, streamed
- [x] MCP: the tool names, `/visits.csv` excluded, `EXPECTED_TOOLS`
- [x] README endpoints, CHANGELOG
- [x] How long it takes on PostgreSQL (2026-09-29), a link with 10k visits in 90 days among 90k on 200 others:
      a 90-day `/breakdown` in 9 ms (40 ms if nearly every visit has its own user agent), `/timeseries` 12 ms,
      `/totals` 6 ms. So nothing is stored
- [ ] Only if a link's volume makes parsing at query time slow: store the parsed fields on `visits` (browser,
      OS, device, referrer host), with a migration and a backfill. The contract stays the same

### 3.16.3 Page (Agent 2)
- [x] Agent 2's approved layout: the period, the header's numbers, By time, By context, By location, the list and
      its export. Broken down below; built against the contract, with a development-only mock (`&mock`,
      `src/utils/link-analytics-mock.ts`, left out of production builds) until the routes are deployed
- [x] Components: a donut with Show numbers and a table twin with shares, and bar lists with Show all (#115)
- [x] The period: 7, 30 or 90 days, or Custom (two dates, checked as the API's 422s before asking), kept in the
      address; the tab in the hash (`src/utils/analytics-view.ts`, `src/utils/tabs.ts`, tested)
- [x] The header's all-time numbers from `/totals`: clicks, email opens (with Apple Mail's automatic opens noted),
      countries, last click
- [x] By time: clicks or email opens by day, week or month, and by hour and weekday, each with its table
- [x] By context: OS, browser and device donuts, and referrers (top 10, then Show all). By location: countries,
      Unknown last
- [x] Visits: clicks, email opens, bots or all; a table on wide screens, stacked rows on phones; 20 a page
- [x] Export CSV: `/visits.csv` for the period, every kind
- [x] Check it against the real routes once Agent 1's two PRs land, at 1440 and 390 px, empty periods included
      → on seeded data: 95 days of clicks, opens and bots, a link with only opens, one with nothing; Europe/Madrid
      and UTC; the CSV downloaded from the page, with formula-like user agents and referrers quoted as text

---

## Phase 3.17: Per-campaign analytics

**Goal:** since 3.16, a link's page answers when, from what and from where its visits came, for a period. A
campaign's page should answer the same over all its recipients' links, plus the numbers an email campaign is judged
by: how many recipients opened, and how many clicked. Today it has:
- all-time totals;
- a 7-day timeline;
- the top 5;
- each recipient's all-time clicks.

It has no opens and no period.

**Split (2026-09-29):** the API is Agent 1's, the page Agent 2's, both built against the contract below, as in 3.16.

### 3.17.1 The contract

A campaign has one link per recipient: a row of its CSV, kept as the link's `user_data`. Everything below counts the
visits of those links, with 3.16.1's definitions:
- the kinds: click, open, bot;
- the period params: `period`, or `from` and `to`, with `tz`;
- the labels: "Unknown" and "Direct";
- the caveat on opens: Apple Mail loads the pixel on its own, so opens overcount, and so does the open rate.

Every route below:
- is under `/api/v1/analytics/campaigns/{campaign_id}/`, and takes a JWT or an API key;
- answers for exactly the campaigns `/users` answers for today (`viewer().sees(Campaign)`):
  - the viewer's organization's campaigns, whatever their role;
  - the viewer's own personal ones;
  - otherwise 404, or 400 for an id that isn't a UUID.

  `/recipients` shows each recipient's `user_data`, names and emails included, as `/users` does: to the same people,
  and no one else;
- takes a period, as in 3.16.1, except `/totals`.

Every response starts with the same fields. `/totals` has no `from` or `to`:

```json
{"campaign_id": "3f2c…", "campaign_name": "Q4 webinar", "from": "2026-07-01", "to": "2026-09-28",
 "timezone": "Europe/Madrid"}
```

**`GET …/totals`**: the header's all-time numbers. Takes only `tz`.

```json
{"campaign_id": "3f2c…", "campaign_name": "Q4 webinar", "timezone": "Europe/Madrid",
 "recipients": 250, "clicks": 180, "opens": 410, "clicked": 96, "opened": 170,
 "click_rate": 0.384, "open_rate": 0.68, "countries": 7, "last_click_at": "2026-09-27T23:54:12+02:00"}
```

- `recipients` is the number of links.
- `clicked` and `opened` count the recipients with at least one click, or at least one open.
- `click_rate` is clicked ÷ recipients, and `open_rate` opened ÷ recipients: 0 to 1, with 4 decimals, and 0 when the
  campaign has no recipients.
- `countries` and `last_click_at` are as for a link.

**`GET …/timeseries?group_by=day|week|month`** and **`GET …/breakdown?type=…`** have a link's shapes (3.16.1), over
all the campaign's links.

**`GET …/recipients?page=1&page_size=20&sort=clicks`**

```json
{...the common fields..., "total": 250, "page": 1, "page_size": 20, "pages": 13, "sort": "clicks",
 "recipients": [{"user_data": {"name": "Ana", "email": "ana@example.com"}, "short_code": "q4-ana",
                 "domain": "shurl.griddo.io", "clicks": 3, "opens": 5,
                 "first_click_at": "2026-09-20T10:02:11+02:00", "last_click_at": "2026-09-27T23:54:12+02:00"}, …]}
```

- Every recipient is listed, with zeros if need be. Each shows their clicks and opens in the period, and their first
  and last click in it (null without one). Bots don't count.
- `sort`, with the short code breaking ties:
  - `clicks`: the default, most first, then most opens;
  - `opens`;
  - `last`: latest click first, recipients without one last;
  - `code`.
- `page_size` is 1 to 100, default 20.

**`GET …/recipients.csv`**: every recipient for the period, streamed.
- The columns are the recipient's `user_data`, flattened as in `/users`' CSV, then
  `short_code,clicks,opens,first_click_at,last_click_at`.
- Every cell is spreadsheet-safe.
- Not an MCP tool, like `/visits.csv`.

**No list of visits at campaign level, on purpose: privacy.** A campaign's visits tied to its recipients' rows would
be a timeline of what each named person did, when, and from where (country and device). Per-recipient totals answer
what a campaign is judged by, and that's all `/users` gives today.

**Open, for the user to decide:** a campaign's link is still a link, so 3.16's `/visits` already lists one recipient's
visits, on that link's page. If the line is "no per-visit data tied to a person", then `/visits` and `/visits.csv`
should refuse campaign links, and the link page should hide its Visits tab for them. Until the user decides, 3.16 stays
as it is.

**Unchanged:** `/summary` and `/users`, for existing clients and the MCP (`get_campaign_summary`, `get_campaign_users`).
Their `click_through_rate` stays a percentage, 0 to 100.

**MCP:** the new routes become the tools `get_campaign_totals`, `get_campaign_timeseries`, `get_campaign_breakdown` and
`list_campaign_recipients`. `/recipients.csv` is excluded.

### 3.17.2 API (Agent 1)
- [ ] 3.16's routes become functions over a query of visits: a link's, or a campaign's links', joined on
      `urls.campaign_id` rather than a list of ids
- [ ] PR 1: `/totals`, `/timeseries` and `/breakdown`
- [ ] PR 2: `/recipients` and `/recipients.csv`. One grouped query per period: each link's clicks, opens, and first
      and last click. Every recipient is kept with zeros, then sorted and paged
- [ ] MCP: the tool names, `/recipients.csv` excluded, `EXPECTED_TOOLS`. README endpoints and CHANGELOG
- [ ] Timings on PostgreSQL: a campaign of 2,000 recipients with 20k visits

### 3.17.3 Page (Agent 2)
- [ ] Agent 2 breaks it down:
  - the period;
  - the header: recipients, open rate, click rate…;
  - the charts, as a link's;
  - the recipients table and its export.

---

## Phase 4: AWS Deployment (ECS Express on griddo-main) — backend ✅ · frontend pending (4.10)

**Status:** live at `https://s.griddo.io` since **2026-04-27** (first deploy, PRs #7–#11). `main` is
production: every merge auto-deploys through `deploy-backend.yml`. The lessons from the rollout, the
troubleshooting catalog and the runbook are in [`docs/AWS_ECS_DEPLOYMENT.md`](../docs/AWS_ECS_DEPLOYMENT.md);
the from-scratch walkthrough is [`DEPLOYMENT.md`](../DEPLOYMENT.md). The checklists below record the plan as
written, with notes where reality differed.

**Architecture decision**: Pivoted from AWS Lambda to **ECS Express Mode** (Fargate-backed, ALB-fronted, replacement for App Runner). Rationale:

- The Phase 5 MCP server prefers a long-lived process (cold-start-free, persistent connection pool to RDS, native fit for Streamable HTTP).
- Redirect path latency: containers don't have cold starts; Lambda does.
- Reuse of existing infrastructure in `griddo-main`: shared ALB, IAM roles, default VPC, and the `ecs-alb-rule-sync` Lambda are already provisioned for the Shlink stack.
- Cost trade-off: ~$15-20/mo extra over Lambda (Fargate task + RDS) but the ALB cost amortizes across services that share it.

**Reference**: Mirrors the Shlink ECS Express deploy pattern documented at `~/Documents/Cowork/Griddo/Marketing & Comms/WebAnalytics/shlink-deploy-guide.md`. Phases below cite the corresponding Shlink phase where the steps overlap; only Shurly-specific details are reproduced here.

**AWS account layout**:
| Account | Profile | Region | Owns |
|---|---|---|---|
| Griddo Main (686255983646) | `griddo-main` | eu-south-2 | ECS, RDS, ECR, ACM, ALB |
| Griddo Production (253490783612) | `griddo-production` | global | Route 53 zone for `griddo.io` |

**Hostnames**:
- `s.griddo.io` — Shurly API + redirect path (short, optimized for printing/QR — short URLs benefit from short hosts).
- `shurly.griddo.io` — the web, the app, the API and the MCP (decided 2026-09-28): served whole by the API
  through rule 12 until the frontend is hosted (4.10), then split by path (`/api/*`, `/mcp*`,
  `/.well-known/oauth-*` to the API, the rest to the frontend), so the frontend calls its own origin.

**Existing reusable infrastructure** (created during the Shlink deploy):
- VPC `vpc-01b31e19aa032bcff` (default)
- Shared ALB `ecs-express-gateway-alb-d37ca364-224022788.eu-south-2.elb.amazonaws.com` (zone `Z0956581394HF5D5LXGAP`)
- IAM roles `ecsTaskExecutionRole`, `ecsInfrastructureRoleForExpressServices`
- Route 53 zone for `griddo.io`: `Z0999097TJGECCBKJOY1` (in `griddo-production`)
- Lambda `ecs-alb-rule-sync` + EventBridge rule (just needs `RULE_SYNC_MAP` extended for Shurly)
- ALB priorities **1-3 reserved** by Express Mode auto-rules; **10, 11 used by shlink-api / shlink-web**; Shurly will use **12**.

---

### 4.1 Cleanup of Lambda/SAM artifacts ✅
Replace the Lambda-oriented setup that landed in earlier prep commits with the ECS-oriented one. No production code changes — only build artifacts and infrastructure-as-code files.
- [x] Remove `lambda_handler.py` (Mangum entry point — not needed; uvicorn is the server now)
- [x] Remove `template.yaml`, `samconfig.toml`, `build_lambda.sh` (SAM-specific)
- [x] Remove `requirements.txt` (was auto-generated for SAM build; the project uses `pyproject.toml` + `uv.lock`)
- [x] Remove `.env.lambda.example` (replaced in 4.2 by `.env.production.example`)
- [x] Remove `mangum` dependency from `pyproject.toml`
- [x] Verify `uv run pytest` still passes (285 tests)

### 4.2 Container image ready for Fargate ✅
- [x] Audit existing `dockerfile`: confirm uvicorn entrypoint, exposed port, multi-stage build to keep image small, and that it builds for `linux/arm64` (Fargate ARM64 is ~20% cheaper than x86).
  - Reality: ECS Express runs **x86_64** Fargate and an arm64-only manifest fails to pull, so the image is built **multi-arch** (`linux/amd64,linux/arm64`). See playbook lesson #3.
- [x] Add `GET /api/v1/health` endpoint that returns `{"status": "ok"}` without touching the database. ECS Express will hit this via the ALB target group health check; we don't want every health check to consume an RDS connection.
- [x] Optional: a `GET /api/v1/health/db` endpoint that does touch the DB — used for synthetic monitoring, not for the ALB.
- [x] Replace `.env.lambda.example` with `.env.production.example`. Same settings (`ANONYMIZE_REMOTE_ADDR`, `TRUSTED_PROXIES`, `DEFAULT_DOMAIN=s.griddo.io`, `REDIRECT_STATUS_CODE`, `REDIRECT_CACHE_LIFETIME`, etc.) but oriented at ECS task env vars instead of Lambda env.
- [x] Local smoke: `docker build -t shurly:dev . && docker run --env-file .env shurly:dev` should boot uvicorn and answer the health check. (Superseded by the real deploy; the image also carries a `HEALTHCHECK`.)

### 4.3 Database (mirrors Shlink Phase 2) ✅
Adapt `scripts/create_rds.sh` for Shurly. Reusing concepts from the Shlink deploy guide; specifics:
- [x] DB SG: either reuse Shlink's `sg-0336fc12dcb7cad06` (lowest friction) or create `shurly-db-sg`. Decision: separate SG so we can revoke independently if needed. → `shurly-db-sg` (5432 open within the VPC).
- [x] Subnet group: reuse `shlink-db-subnets` (covers default VPC subnets — same VPC).
- [x] DB instance `shurly-db`, `db.t4g.micro`, 20 GB gp3, `--no-publicly-accessible`, 7-day backup retention.
- [x] **No `--engine-version` pin** (per Shlink lesson #6). → AWS picked PostgreSQL 17.
- [x] Master user `shurly`, DB name `shurly`. Password from `openssl rand -base64 24` — captured for the env, not committed.
- [x] Schema bootstrap: `Base.metadata.create_all()` runs at startup (idempotent, additive only). Swap for Alembic before the first non-additive schema change (playbook lesson #13).

### 4.4 TLS certificate (mirrors Shlink Phase 3) ✅
- [x] `aws acm request-certificate --domain-name s.griddo.io --validation-method DNS` (`griddo-main`, eu-south-2)
- [x] Capture validation CNAME, write it to Route 53 from **`griddo-production`** profile (zone `Z0999097TJGECCBKJOY1`)
- [x] `aws acm wait certificate-validated`

### 4.5 ECS Express service (mirrors Shlink Phase 5) ✅
- [x] Create ECR repository `shurly-api` in `griddo-main` (tags are IMMUTABLE, so images are tagged `<sha>-<timestamp>`)
- [x] `docker buildx build --platform linux/amd64,linux/arm64 --tag <account>.dkr.ecr.eu-south-2.amazonaws.com/shurly-api:<sha>-<timestamp> .` (multi-arch, see 4.2)
- [x] ECR login + push
- [x] `aws ecs create-express-gateway-service --service-name shurly-api`:
  - Reuses `ecsTaskExecutionRole` + `ecsInfrastructureRoleForExpressServices`
  - `--cpu 256 --memory 512` (Fargate units, **not** decimal — per Shlink lesson #1)
  - `--health-check-path /api/v1/health`
  - `--scaling-target {minTaskCount: 1, maxTaskCount: 2}`
  - Env vars: full set from `.env.production.example`, with `DB_HOST` from RDS endpoint and `DB_PASSWORD`/`JWT_SECRET_KEY` from prompts (or Secrets Manager later)
- [x] `--monitor-resources` may timeout; verify with `describe-express-gateway-service` (Shlink lesson #2)
- [x] Smoke against the auto-generated host: `curl https://shurly-api.ecs.eu-south-2.on.aws/api/v1/health`
  - Reality: the auto-host is opaque (`sh-<32-hex>.ecs.eu-south-2.on.aws`), not service-named (playbook lesson #1).

### 4.6 Custom domain `s.griddo.io` (mirrors Shlink Phase 6) ✅
- [x] `aws elbv2 add-listener-certificates` — add the `s.griddo.io` ACM cert to the shared ALB's HTTPS listener (Shlink lesson #3)
- [x] `aws elbv2 create-rule --priority 12 --conditions host-header=s.griddo.io` pointing to Shurly's active target group (the one with weight 100 — Shlink lesson #7 about priority headroom for Express Mode)
- [x] `aws route53 change-resource-record-sets` from **`griddo-production`** profile: A-alias `s.griddo.io` → ALB
- [x] `dig s.griddo.io && curl https://s.griddo.io/api/v1/health` to verify

### 4.7 ALB rule sync — extend the existing Lambda ✅
ECS Express does blue/green deploys by alternating target group weights. Manual ALB rules (priority 12 in our case) need to follow the active TG or the service drops. The `ecs-alb-rule-sync` Lambda already handles this for Shlink; we extend it.
- [x] Identify Shurly's Express Mode rule priority (the one Express Mode auto-creates between 1-5) → **4**
- [x] PR against the Lambda's `RULE_SYNC_MAP`: add `<shurly-express-priority>: "12"` mapping → `"4": "12"`
- [x] Test: `aws lambda invoke --function-name ecs-alb-rule-sync` returns "No changes needed" or syncs correctly → `["Synced priority 12 with 4"]`
- [x] Force a redeploy via `update-express-gateway-service --force-new-deployment` and verify `s.griddo.io` keeps responding without manual intervention

### 4.8 CI/CD with OIDC + ECR + ECS ✅
Replaces the SAM-based GitHub Actions workflow.
- [x] **One-time setup in `griddo-main`** (documented in DEPLOYMENT.md, executed manually with SSO):
  - GitHub OIDC provider (`token.actions.githubusercontent.com`)
  - IAM role `github-actions-shurly-deploy` with trust policy scoped to `repo:danielserranoh/shurly:*`
  - Permissions: ECR push (scoped to the `shurly-api` repo), ECS update-express-gateway-service (scoped to the Shurly service ARN), CloudWatch Logs read for verification
- [x] Rewrite `.github/workflows/deploy-backend.yml`:
  - `permissions: id-token: write` for OIDC
  - `aws-actions/configure-aws-credentials@v4` with `role-to-assume`, no access keys
  - `docker buildx build --platform linux/amd64,linux/arm64 --push` (multi-arch, see 4.2)
  - `aws ecs update-express-gateway-service --force-new-deployment`, then a smoke of `/api/v1/health` on the public host
  - Trigger: `workflow_dispatch` only until first manual deploy succeeds; then optionally re-enable `push` to `main` → done: `push` to `main` is on, `main` is branch-protected (PR + passing tests), `workflow_dispatch` kept for rollbacks
- [x] No `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` secrets — only `AWS_DEPLOY_ROLE_ARN`, `DB_HOST`, `JWT_SECRET_KEY`, etc.

### 4.9 First real deploy + smoke ✅ (2026-04-27)
End-to-end run with the user driving SSO locally:
- [x] `./scripts/create_rds.sh` (one-time)
- [x] Request ACM cert + validate
- [x] `./scripts/deploy_ecs.sh` (build + push + service create)
- [x] `./scripts/setup_custom_domain.sh` (cert, rule, DNS)
- [x] Update Lambda `RULE_SYNC_MAP`
- [ ] Smoke checklist — only `/api/v1/health` (checked by CI on every deploy) and the forced redeploy are on record; re-run the rest against production and tick them here:
  - `login` → returns JWT (register is gone since 3.13.2: sign in with Google, or with a password set
    afterwards)
  - `POST /api/v1/urls` creates a short URL bound to `s.griddo.io`
  - `GET /<code>` returns 302 to destination
  - `GET /<code>/track` returns 43-byte GIF
  - `GET /robots.txt` returns default-deny
  - `GET /api/v1/analytics/orphan-visits` after a typo'd `GET /xyzabc` shows the orphan
  - Force `update-express-gateway-service --force-new-deployment` → verify `s.griddo.io` stays up
- [x] Capture findings → the 13 lessons in `docs/AWS_ECS_DEPLOYMENT.md`, fixed in the `fix(scripts)` / `hotfix` commits of PRs #7–#10

### 4.10 Frontend hosting 🔎 R3
The Lambda-era plan hosted the frontend on S3 + CloudFront ("Phase 4.6"). The ECS rewrite of this phase
(2026-04-26) dropped both and sent the frontend to "Phase 7", which is Documentation & Handoff. The frontend
has been finished since 3.11 with nowhere to run: `deploy-frontend.yml` is manual-only and points at
buckets that no doc says were created.

**Decided (2026-09-27): one private S3 bucket behind CloudFront**, for the public pages (landing,
pricing, sign-in) and the dashboard alike. The build is static on purpose: 3.11 dropped the Node adapter
for this.
- *One hosting is enough.* The dashboard's HTML/JS holds no data and no secrets; every record comes from the
  API, behind a JWT or an API key. The privacy of the dashboard lives in the API.
- *Cheapest.* The traffic fits CloudFront's always-free tier (1 TB and 10M requests a month) and S3 storage
  costs cents. A container means a Fargate task running around the clock (a second Express service, as
  shlink-web does), or frontend releases tied to backend deploys (served from the API container, where the
  root path belongs to short codes).
- *Safest.* No server to patch; the bucket stays private behind Origin Access Control (OAC); HSTS comes from a
  CloudFront response-headers policy, and the CSP from the build itself, a `<meta>` on every page (6.3). CSP matters
  here: the JWT lives in `localStorage` (3.1).

- [x] Choose the hostname → **`shurly.griddo.io`** (decided 2026-09-28), for the web, the app, the API and the
      MCP, split by path; `go.griddo.io` is for short links only. `links.griddo.io` retires with Shlink (Phase 8)
- [ ] S3 bucket (Block Public Access on) + CloudFront distribution with OAC
- [ ] ACM certificate in **us-east-1**: CloudFront only takes certificates from N. Virginia (the ALB's is in
      eu-south-2). DNS validation in `griddo-production`
- [x] CloudFront Function rewriting `/dashboard/` → `/dashboard/index.html`: a private bucket is reached through
      the S3 REST endpoint, which doesn't resolve directory indexes. The comment in `astro.config.mjs` saying no
      CDN rewrites are needed only holds for the public website endpoint → `infra/cloudfront/static-paths.js`, with tests;
      attach it to the default behaviour when the distribution is created
- [ ] Error response: 404 → `/404.html` → an open decision now that the API shares the distribution: custom error
      responses apply to the whole distribution and would replace the API's own 403/404 (DEPLOYMENT.md § Frontend
      hosting, "Error pages")
- [ ] Route 53 alias record, from `griddo-production`
- [x] Rewrite `deploy-frontend.yml`: OIDC role as in 4.8 (it still uses access keys), the real bucket, the
      production build values below, `PUBLIC_SITE_URL`; re-enable `push` on `frontend/**`. Its header still
      points at the Lambda-era "Phase 4.5/4.6"
- [x] Production build values: `PUBLIC_API_URL=https://shurly.griddo.io` and `PUBLIC_SHORT_DOMAIN=s.griddo.io`
      (`go.griddo.io` from Phase 8). Without `PUBLIC_SHORT_DOMAIN` the app shows short links on the API's host
      (`shurly.griddo.io/abc`). The MCP address in the manual and Settings then derives as
      `https://shurly.griddo.io/mcp/` (`PUBLIC_MCP_URL` only to override it)
- [ ] `CORS_ORIGINS` in the task → `'[]'` once the frontend is hosted, as it shares the API's host (DEPLOYMENT.md
      § CORS). `deploy_ecs.sh` and `.env.production.example` default to it; production keeps
      `["http://localhost:4232"]` until then (6.3)
- [x] Update the hostnames table in `DEPLOYMENT.md` (it still says "Future frontend | 7") → done in #74
- [x] CI builds the frontend (`npm ci`, `npm test`, `npm run build` in the Tests workflow), so a PR can't break the
      deploy unseen
- [x] Client IPs through CloudFront: decide how the API gets the viewer's address once `shurly.griddo.io` goes
      through the distribution → `CloudFront-Viewer-Address`, believed only on a request carrying the
      distribution's secret origin header (`CLOUDFRONT_ORIGIN_SECRETS`, two values to rotate) and matching the
      address CloudFront appended to X-Forwarded-For; otherwise X-Forwarded-For as before. One `client_ip` for the
      rate limits and the visit log
      (`tests/test_phase63_cloudfront_client_ip.py`)
  - [ ] AWS, with the distribution: the custom origin header, HTTPS to the origin, the origin request policy
        AllViewerAndCloudFrontHeaders-2022-06 and the task's `CLOUDFRONT_ORIGIN_SECRETS` (DEPLOYMENT.md § Frontend
        hosting); optionally the per-host ALB rules

---

## Phase 5: MCP Server over Streamable HTTP

**Goal:** Expose the existing API as an MCP server so internal users (and Claude Code / Claude Desktop) can drive Shurly without a frontend. Pilot for the broader "MCP-as-product" thesis: capture how people actually use the service via natural language, and use those signals to prioritize frontend features.
**Duration:** ~1.5–2 weeks
**Priority:** 🟡 MEDIUM — Runs after Phase 4 (deploy). It was planned to run before the frontend existed; 3.11 built the frontend first, so the dogfood now feeds the frontend backlog. Backend-only stack already has 3.9 + 3.10 hardening, so this exposes a stable surface.
**Reference:** [Model Context Protocol spec](https://modelcontextprotocol.io/), Anthropic Python SDK (`mcp`), FastMCP (https://github.com/jlowin/fastmcp). Decision rationale recorded in conversation thread (PR review).

**Sequencing:**
- Phase 4 (deploy) must complete first — MCP runs against the same backend; we don't want to debug Lambda cold starts and MCP transports simultaneously.
- Internal dogfood window of ~2–4 weeks. Findings feed the frontend backlog.

### 5.1 Foundation & framework choice ✅
- [x] Decision recorded: start with **`fastmcp` standalone** for fast prototyping (auto-generates tools from FastAPI), reserve the option to migrate to `mcp.server.fastmcp` (official SDK) if upstream divergence becomes a real risk.
- [x] Add `fastmcp` to `pyproject.toml` `mcp` optional-extra group (so it doesn't bloat the Lambda bundle when not needed). → `fastmcp>=4,<5`
- [x] Create `mcp_server/` sub-package or sibling module — keep it isolated from `server/` so the API can run standalone.
- [x] Pick transport: **Streamable HTTP** (single endpoint, request/response, Lambda-friendly). Stdio for local dev only.
- [x] Document the chosen framework + transport in `mcp_server/README.md` with the 3-option comparison rationale (so a future maintainer doesn't relitigate the decision).

### 5.2 Auto-generated tools from FastAPI
- [x] Bootstrap: `FastMCP.from_fastapi(app)` (or equivalent) — generate the first cut of tools automatically. (47 raw tools)
- [x] Audit the generated tool list: for each `/api/v1/...` endpoint, verify the tool name, description, schema, and return shape are LLM-friendly. → `MCP_TOOL_NAMES` strips the `_api_v1_<path>_<method>` suffix from operationIds; `tests/test_phase52_mcp_tools.py` pins the surface (40 tools today)
- [x] Filter out endpoints that should NOT be MCP tools: legacy `statistics.py`, internal-only routes, anything that handles file uploads (campaign CSV — see 5.3). → `EXCLUDED_ROUTE_MAPS` drops `/api/v1/stats/*` and the health probes (the legacy stats routes were removed on 2026-09-29, and their exclusion with them). No route takes a file upload: `create_campaign` takes the CSV as a string and stays a tool, with `create_campaign_from_rows` (5.3) as the LLM-friendly variant
- [x] Verify the OG-preview, robots.txt, redirect path, and tracking pixel routes are excluded (they're public unversioned routes, not management API). → `/`, `/robots.txt`, `/{short_code}` and `/{short_code}/track` are excluded. The OG-preview routes (`/api/v1/urls/{code}/preview`, `…/refresh-preview`, `fetch-metadata`) are authenticated management API, so they **stay** as tools
- [ ] Tests: each auto-generated tool round-trips through the MCP server and produces the same output as the underlying endpoint. → open: only `get_current_user_info` is called through the MCP layer (`tests/test_phase54_mcp_auth.py`); the other generated tools are covered by their REST tests, not through MCP

### 5.3 Hand-curated tools (where auto-gen is awkward) ✅
- [x] **`create_campaign_from_rows`** — accepts `rows: list[dict]`, serialises to CSV in-memory, reuses the existing campaign generator.
- [x] **`get_url_analytics_summary`** — composes totals + daily series + top countries in one call (default 7-day window, bot/pixel filtering aligned with regular analytics endpoints).
- [x] **`add_redirect_rule`** — sugar over `POST /urls/{code}/rules` with named condition args (device/language/browser/query_param[+value]/before_date/after_date), at least one condition required.
- [x] **`list_orphan_visits_grouped`** — clusters by `attempted_path`, returns top-N groups with capped sample list (3 per group) and overall totals.
- [x] Logic in `mcp_server/curated.py` (testable with explicit `db`+`user`); MCP wrappers in `mcp_server/server.py` (auth stub raises until 5.4 lands).
- [x] Tests in `tests/test_phase53_curated_tools.py` cover registration, happy paths, validation, scoping, bot/pixel toggle.

### 5.4 Authentication & per-user scoping ✅
- [x] FastAPI `get_current_user` accepts both JWTs and API keys (token-shape dispatch — JWTs have dots, API keys don't). Single dependency, single test surface.
- [x] `ShurlyTokenVerifier` validates the inbound MCP bearer as an API key (by its hash since 6.3), populating `AccessToken.claims` with user id + email + scope.
- [x] `forward_bearer_auth` hook re-attaches the inbound bearer to the outbound FastAPI call so auto-generated tools resolve the same user as the MCP layer.
- [x] Curated-tool wrappers swap the Phase 5.3 `NotImplementedError` stub for `resolve_current_user(db)` reading from the AccessToken context.
- [x] `MCP_DISABLE_AUTH=1` escape hatch for local stdio dev (never to be set in prod).
- [x] `ApiKeyScope` enum surfaced on the AccessToken claims — only `FULL_ACCESS` is enforced today; the rest stay reserved for a future scope-policy phase.
- [x] Tests: 14 cases covering token-shape dispatch, API-key auth on FastAPI routes (200 / 401), inactive-user rejection, JWT regression, verifier accept/reject, and `resolve_current_user` failure when no token is bound.
- [x] Documented the API-key mint/rotate/revoke flow in `mcp_server/README.md`.

### 5.5 Deploy & operational integration ✅

**Decision (2026-04-28):** Same ECS task as the FastAPI app, MCP mounted on `/mcp`. Single Docker image, single deployment, shared RDS connection pool. Split into a separate ECS service only if MCP traffic patterns later force independent scaling.

- [x] Mounted FastMCP app on `main.app` at `/mcp` (Streamable HTTP transport). Lifespan forwarded so the MCP session manager starts/stops with the host.
- [x] Resolved a `main → mcp_server.server → main` circular import via PEP 562 lazy `__getattr__` on the module-level `mcp_server` symbol + an explicit `build_mcp_for_app(app)` helper used by the in-process mount.
- [x] Same ECS Express service, same ALB target group — `/mcp` is just another path on `s.griddo.io`. No new ALB rule, no new TG, no new CloudWatch alarms.
- [x] Dockerfile bumped to `uv sync --no-dev --frozen --extra mcp` so the prod image carries fastmcp; `mcp_server/` directory copied into the image.
- [x] `MCP_DISABLE_MOUNT=1` runtime escape hatch — skips the mount without rebuilding (incident response).
- [x] `RequestIdMiddleware` runs at the FastAPI layer, before the mount, so MCP requests inherit the same `x-request-id` correlation as `/api/v1/*`.
- [x] CI workflows (`test.yml`, `deploy-backend.yml`) install with `--extra mcp` so the Phase 5 tests don't get silently skipped.
- [x] Local stdio server (`scripts/run_mcp_local.sh`) stays as the dev workflow — not replaced by the deploy.
- [x] Documented the dev/prod split, registration, and escape hatches in `mcp_server/README.md`.

**Follow-ups after the mount** (shipped; the first was committed as "Phase 5.6", which is not the 5.6 below):
- [x] **Stateless transport** (MCP 2026-07-28): `stateless_http=True` on the mount, so no `Mcp-Session-Id` is minted. Without it, calls failed with "Missing session ID" once the service scales to 2 tasks or a blue/green deploy replaces them. Tests: `tests/test_phase56_mcp_stateless.py` (PR #25).
- [x] **`/mcp/` advertised with the slash**, and the bare `/mcp` answers with a **308** to it so a POST keeps its JSON-RPC body (PRs #32, #33).
- [x] **Reserved short codes**: custom codes `mcp`, `docs`, `redoc` get a suffixed code, as for a taken one (PR #35).

### 5.6 Internal dogfood + signal capture
**Prerequisites:** the usage log (5.6.0), the organization and roles (3.14), the hosted frontend (4.10), Google
sign-in and OAuth (3.13, 5.8) and the install guide (5.9). **Decided (2026-09-27):** the dogfood runs with the frontend too.

#### 5.6.0 Usage log (prerequisite) 🔎 R4 — code ✅, AWS setup pending
In the access log every MCP call is a `POST /mcp/`: the tool name travels inside the JSON-RPC body, so nothing
records which tools get used, how often, or how they fail.
- [x] One JSON line per tool call (`mcp.tool_call`: tool, argument names, user, outcome, error type, HTTP status,
      duration, request id). On **stderr**, not stdout: under the stdio transport stdout is the JSON-RPC channel
- [x] Hooked as a fastmcp middleware (`on_call_tool`, `mcp_server/usage.py`), so auto-generated and curated tools
      are covered alike
- [x] Never log argument values: campaign rows carry names, companies and emails (GDPR). Argument names only
  - [x] Nor in fastmcp's own line for a failed call 🔎 R10: for an API error it printed the response body, and a 422
        echoes the invalid values (the whole request body, CSV rows included, when a field is missing). Now it keeps
        the tool and the status, without the body or the traceback (`ApiErrorLogFilter`, `mcp_server/usage.py`).
        Other exceptions keep their traceback. Production never runs `FASTMCP_LOG_LEVEL=DEBUG`, which logs arguments
  - [x] Nor in a database error's message, for any request 🔎 R10: SQLAlchemy ends it with the statement's
        parameters, and the traceback kept for real errors prints it. The engine hides them (`hide_parameters=True`;
        `tests/test_db_error_messages.py`). PostgreSQL's own detail for a constraint violation still names the value
  - [x] Nor in the link-preview fetcher's warnings 🔎 R10: a refused, timed-out or failed fetch logged the whole
        destination URL (a tool argument of `create_short_url`), whose path or query can carry personal data. They
        keep its origin only (`url_origin`, `server/utils/url.py`; tests in `tests/test_opengraph_ssrf.py`)
- [x] Same JSON format for the HTTP request line (`http.request`, from `RequestIdMiddleware`), with `request_id`;
      uvicorn's access log is off in the image. A generated tool's call into the API carries the MCP request's id
- [x] Logs Insights queries (calls, errors and latency per tool, daily users, one request end to end) documented
      in `mcp_server/README.md` § Usage log
- [x] Retention on the log group: **60 days** (decided and set 2026-09-28)
- [ ] Save those queries in CloudWatch: commands in the same section, to run once with SSO
- [x] Tests: `tests/test_phase560_usage_log.py` (14)

#### 5.6.1 Rollout and signal capture
- [ ] Roll out to the Griddo team: 3–5 internal users, with the frontend and the MCP.
- [ ] Capture for 2–4 weeks: tool invocation counts (which tools get used vs ignored), tool error rates, average call duration.
- [ ] Capture qualitatively: which workflows feel smooth in chat, which feel awkward (e.g. CSV import, charts).
- [ ] Output: a "frontend feature priority" list backed by real signal, fed into the frontend backlog.

### 5.7 Verification
- [ ] All auto-generated + curated tools have at least one happy-path test. → curated tools: yes (`tests/test_phase53_curated_tools.py`); auto-generated: see the open item in 5.2
- [ ] MCP endpoint responds within the same SLO as the regular API. → same task and ALB rule, but never measured
- [x] No regression in existing tests (backend behavior unchanged). → 465 passing (2026-09-26)
- [ ] `mcp_server/README.md` exists and covers: architecture, framework choice, auth, deployment, how to add a new tool. → everything but "how to add a new tool"
- [ ] CHANGELOG.md entry under "Added" describing the MCP surface. → missing: the CHANGELOG only mentions MCP in passing (fixes and the Phase 3.11 tools)

### 5.8 OAuth 2.1 sign-in for the MCP, alongside API keys 🔎 R8
**Decided (2026-09-27):** MCP clients can sign in with OAuth 2.1; API keys keep working. claude.ai's custom
connectors only authenticate with OAuth (their form has no field for a bearer token), so without it Shurly can't be
added there; Claude Code gets by with `--header`.
- [x] **Authorization server: Google Workspace** (decided 2026-09-27), through fastmcp's OAuth proxy
      (`GoogleProvider`, in fastmcp 4.0.10), which also handles client registration (Dynamic Client Registration,
      Client ID Metadata Documents). Same Google project as the web sign-in (3.13.2)
- [x] Add the MCP proxy's redirect URI to the Google OAuth client of 3.13.2 → `{MCP_PUBLIC_URL}/auth/callback`,
      → `https://shurly.griddo.io/mcp/auth/callback` (docs/setup_google_app.md, step 9); verified in the
      Google client 2026-09-28
- [x] Protected-resource metadata (RFC 9728), and 401s carrying `WWW-Authenticate: Bearer resource_metadata="…"`
      (answers the open question at the end of this phase) → at `/.well-known/oauth-protected-resource/mcp/`,
      with the authorization server's metadata at `/.well-known/oauth-authorization-server/mcp`
- [x] Map the Google identity to the Shurly user through `user_identities` (3.13.2): organization domain only,
      member of the organization (3.14) → the web's rules (`verify_id_token`, `sign_in_with_google`) when the
      client redeems its code; the account by `sub`, and closed ones refused, on every request and refresh
      (`mcp_server/google_oauth.py`)
- [x] API keys keep working: the verifier accepts either an API key or an OAuth access token. Check this first:
      fastmcp takes a single auth provider, so it likely needs a small one wrapping `GoogleProvider` and
      `ShurlyTokenVerifier` → fastmcp's `MultiAuth`, with `required_scopes=[]` (otherwise API keys get 403
      for Google's scopes)
- [x] No collisions with short codes: auth routes served at the root (`/authorize`, `/token`, `/register`,
      `/.well-known/…`) get reserved like `mcp`, `docs` and `redoc` (PR #35), or live under `/mcp/` → the
      OAuth endpoints are under `/mcp/`; at the root only the multi-segment `/.well-known/…/mcp` paths
- [x] State that survives two tasks and every deploy: the proxy's registrations, sign-ins in progress, codes
      and Google's tokens in `mcp_oauth_store` (migration `0005`), encrypted; its tokens signed with
      `MCP_OAUTH_SIGNING_KEY`, never the Google secret
- [x] Only the clients we target can register (consent phishing): `MCP_OAUTH_ALLOWED_REDIRECT_URIS`, by
      default claude.ai's and claude.com's callbacks and loopback on any port (Claude Code)
- [x] Pick the canonical MCP host (`s.griddo.io` or `go.griddo.io`) before people install it: OAuth ties the
      client's configuration to the resource URL → **`shurly.griddo.io`** (decided 2026-09-28), with the web,
      the app and the API; `go.griddo.io` is for short links only. `MCP_PUBLIC_URL=https://shurly.griddo.io/mcp`
- [x] Tests: metadata documents, the 401 header, both token types, user mapping, non-griddo identities refused
      → `tests/test_phase58_mcp_oauth.py`, against a fake Google, including two app instances completing one
      sign-in
- [ ] Check it end to end: Claude Code (`claude mcp add --transport http …`, sign-in in the browser) and a
      claude.ai custom connector → in production (2026-09-28) the metadata documents and the 401 with
      `resource_metadata` are verified; nobody has completed a sign-in from claude.ai or Claude Code yet

### 5.9 MCP install guide, in the app and in the user manual 🔎 R9
**Decided (2026-09-27):** the app explains how to install the MCP, and the user manual carries the same instructions.
**Today:** Settings → API & MCP shows the API key and a `curl` example, nothing about installing the MCP. The steps
live in `mcp_server/README.md`, written for developers. There is no user manual (7.1).
- [x] One source for both: the manual as Markdown inside the frontend (e.g. an Astro content collection under
      `frontend/src/content/manual/`, published at `/manual/`), and Settings → API & MCP renders the same MCP page,
      so the two can't drift → `frontend/src/content/manual/install-mcp.md`, rendered by `ManualArticle.astro` in both
- [x] Steps per client: Claude Code and claude.ai / Claude Desktop (custom connector), plus any other client the
      team uses. OAuth sign-in (5.8) first, the API key as the alternative
- [x] In the app, the user's own values filled in (endpoint URL, and their key if they take that route) → the
      address from `PUBLIC_MCP_URL` at build time; "Copy with my key" builds the command when clicked, never in the page
- [x] Voice and patterns from `design/DESIGN_SYSTEM.md`
- [x] Written once 5.8 lands, since OAuth changes the steps

### Open questions (resolve during 5.1)
- Does `fastmcp.from_fastapi()` produce useful tool descriptions, or do we need to enrich them via Pydantic `Field(..., description=...)` everywhere first? (Likely yes — most of our schemas already have descriptions; sweep the gaps.) → still open: nobody has done the sweep
- ~~Should pixel/redirect endpoints be exposed as tools at all?~~ **Resolved:** no — excluded in `EXCLUDED_ROUTE_MAPS` (5.2).
- ~~Per-user MCP config in Claude Code: how does the team add their personal API key without committing it?~~ **Resolved:** `claude mcp add --transport http shurly https://shurly.griddo.io/mcp/ --header "Authorization: Bearer <api_key>"`, documented in `mcp_server/README.md`.
- Authorization discovery: we publish no RFC 9728 protected-resource metadata. All four `.well-known` paths 404, and the 401 carries a bare `WWW-Authenticate: Bearer` with no `resource_metadata=` pointer, so MCP clients cannot auto-discover how to authenticate and must be handed an API key. Not a flag we can flip — it needs our own authorization server or delegation to an IdP (fastmcp ships providers for Auth0, Azure, Clerk, Google, Keycloak, WorkOS, …). A product decision, not a technical one. **Decided 2026-09-27:** yes, OAuth 2.1 alongside API keys → 5.8. **Built (2026-09-28):** the metadata at `/.well-known/oauth-protected-resource/mcp/` and a 401 pointing at it, once the 5.8 settings are set.

---

## Phase 6: Testing & Optimization

> Phases 4 and 5 moved the stack from Lambda + API Gateway to ECS Express behind a shared ALB; the items below
> were rewritten for that stack on 2026-09-26.

### 6.1 Testing
- [x] Unit tests (pytest) — 465 tests, run on every PR by `test.yml` (with `--extra mcp`)
  - [x] URL shortening logic
  - [x] Campaign CSV parsing
  - [x] Auth token generation
- [x] Integration tests (FastAPI `TestClient` against in-memory SQLite)
  - [x] API endpoints
  - [x] Database operations
- [ ] E2E tests (optional)
  - [ ] Frontend flows (Phase 3.11 ran a manual smoke of 14 core flows; nothing automated)

### 6.2 Performance Optimization
- [ ] Database indexes review
- [ ] Query optimization for analytics
  - [x] Multi-URL endpoints run a constant number of SQL statements (N+1 removed) and list pagination is capped at 100 (PR #26)
- [ ] Caching strategy for the redirect path (CloudFront in front of the ALB, or none)
- [ ] ~~Lambda cold start optimization~~ — not applicable on ECS; containers have no cold start

### 6.3 Security Hardening
- [x] Rate limiting — no API Gateway on this stack, so it needs app-level limiting or AWS WAF on the shared ALB (first slice: invitations and resets in 3.15, since each one sends an email) → app-level, in the database so both tasks share the counts (`server/utils/rate_limit.py`, migration `0006`): the password login per IP and failed logins per address, the Google and MCP sign-in per IP. Invitations and resets (3.15) take a limit of their own when they arrive; WAF stays an AWS option
- [x] Input validation review → request fields stored in a bounded column carry a `max_length` within it
      (pinned by `tests/test_input_lengths.py`); values from outside a schema (a fetched page's title,
      an address from `X-Forwarded-For`) are cut to their column instead of failing with a PostgreSQL 500;
      the MCP's `create_campaign_from_rows` checks its name like the API
  - [x] CSV formula injection: the exports quote cells that start like a formula, and the CSV import unquotes them
        (`spreadsheet_safe`, `server/utils/csv_export.py`)
- [x] SQL injection prevention check → the API binds every value (ORM and Core); the raw SQL left is static or
      takes `:name` parameters. The one finding was a LIKE pattern, not an injection: the tag search let `%` and `_`
      act as wildcards (fixed with `autoescape=True`, as the links search had). `tests/test_sql_safety.py` reads
      `server/`, `mcp_server/` and `main.py` and fails on SQL built from strings or an unescaped LIKE on a column
- [x] Content-Security-Policy → a `<meta>` on every built page, written by Astro (`security.csp`): scripts only from
      this site or by hash (the inline ones live in `frontend/src/inline-scripts.mjs`), no `'unsafe-inline'` or
      `'unsafe-eval'` for scripts; `'unsafe-inline'` only for style attributes. `npm run build` fails on a page it
      doesn't cover (`frontend/scripts/check-csp.mjs`); DEPLOYMENT.md § Frontend hosting
- [x] Trusted Types (`require-trusted-types-for 'script'`): every HTML sink through a policy. The next step up from the
      CSP; `setHTML` and `toElement` would become that policy → done: `trusted-types shurly-html`, one policy in
      `src/utils/html.ts` that passes through only markup from `html` or `escapeHtml` (anything else is escaped). A
      sweep of the built bundles and every page found no other sink: Astro and the libraries ship none. The build
      fails without the directives or with `default`/`*`/`'allow-duplicates'` (`scripts/csp-rules.mjs`)
- [x] XSS prevention in frontend (dynamic HTML goes through the escaping `html` tag from `@/utils/html`; audit the remaining raw `innerHTML` uses) → audited: data goes through `html`/`setHTML`, URLs through `safeUrl`; two raw sinks left, documented; `frontend/tests/no-raw-html.test.mjs` fails on new ones
- [x] CORS configuration review → no credentials, only the methods and headers the API uses, `Retry-After`
      and `X-Request-Id` exposed (`tests/test_cors.py`). Production needs no cross-origin entry once the
      frontend shares the API's origin (4.10). At release #81 (2026-09-28) its `CORS_ORIGINS` became
      `["http://localhost:4232"]`: `https://shurl.griddo.io`, a host that doesn't exist, is gone, and
      localhost stays for running the frontend locally against production until 4.10
- [ ] Environment secrets audit (DB password and JWT secret are plain task env vars; Secrets Manager is the planned move)
  - [ ] The Google OAuth client's secret (3.13.2, `GOOGLE_CLIENT_SECRET`) in Secrets Manager
- [x] SSRF guard on the Open Graph fetcher (PR #21, see CHANGELOG § Security)
- [x] Campaign-link takeover via custom codes (see CHANGELOG § Security)
- [x] API keys stored as a hash → SHA-256 and the first 12 characters (migration `0007`), shown once when
      generated; `/auth/me`, and so the MCP's `get_current_user_info`, no longer returns the key; new keys
      start with `shurly_` (`tests/test_phase63_api_keys.py`)
  - [x] Stop mapping the emptied `users.api_key`: the ORM names every mapped column in its SELECTs and INSERTs,
        so dropping it while a task of that release serves fails every user query mid-rollout. A test drops it by
        hand and runs this release against it: signing in, an API key, `/me`, the MCP, revoking
        (`tests/test_phase63_api_keys.py`)
  - [ ] Migration `0010` drops `users.api_key` and `ix_users_api_key`, and the drift test's `_PENDING_DROP` goes:
        **only after the release that stopped mapping it is in production**, since until then a running task still
        names the column. It takes `0010`, after `0009` (the avatar, 3.12)
  - [x] The MCP can't generate or revoke a key: talked into it by untrusted text, an assistant would get
        the new key in its context. Nor `login` or `change_password`: no password or JWT passes through an
        assistant (`EXCLUDED_ROUTE_MAPS`, pinned by `tests/test_phase52_mcp_tools.py`)
- [x] `scripts/deploy_ecs.sh` can't overwrite production's settings 🔎 R14: run against the live service, its
      update path replaced the whole environment with the 20 variables it builds, dropping every setting added
      on the service since (sign in with Google, the MCP's OAuth, …) → it only creates the service, and stops
      before building anything once it exists; a failed lookup stops it too. Images go out with the deploy
      workflow, settings change on the live service (`tests/test_deploy_ecs_script.py`, on stubbed `aws` and
      `docker`)

### 6.4 Monitoring & Logging
- [x] CloudWatch Logs setup → `/aws/ecs/default/shurly-api-5fdb`; `X-Request-Id` correlates requests
- [ ] Error alerting (SNS/email) — required before the Shlink cutover (8.5)
  - [x] What to count, and a runbook stub: `DEPLOYMENT.md` § Error alerting. No code: `http.request` lines already
        carry the status, so a metric filter on 5xx does it
  - [ ] AWS: the metric filters, the alarms and an SNS topic with an email subscription
- [ ] Key metrics dashboard
  - [ ] ECS task count / CPU / memory
  - [ ] ALB 5xx and target health
  - [ ] RDS connections
  - [ ] Redirect latency

---

## Phase 7: Documentation & Handoff

### 7.1 Documentation
- [x] API documentation (OpenAPI/Swagger) - auto-generated by FastAPI (`/docs`, `/redoc`)
- [x] Deployment guide → `DEPLOYMENT.md` (walkthrough) + `docs/AWS_ECS_DEPLOYMENT.md` (playbook)
- [x] User manual for dashboard: starts with the MCP install page (5.9), which lives in the frontend → `/manual/`, Markdown in `frontend/src/content/manual/`
- [ ] Architecture diagram
- [ ] Database schema diagram
- [ ] Environment variables reference

### 7.2 Operational Runbook
- [ ] How to add new users → self-service sign-up for `@griddo.io`: signing in with Google makes the account
      (3.13.2); the Google project is done. Left: writing it down here
- [x] How to investigate issues → troubleshooting catalog in `docs/AWS_ECS_DEPLOYMENT.md`
- [x] How to scale if needed → "Scale up/down" in the same runbook
- [ ] Backup and recovery procedures
- [ ] Cost monitoring guide

---

## Phase 8: Replace Shlink on go.griddo.io 🔎 R5

**Goal:** Shurly takes over `go.griddo.io` and the Shlink stack is retired (shlink-api, shlink-web on
`links.griddo.io`, and its RDS). Every link already in circulation keeps working.
**Priority:** 🟡 MEDIUM — after the dogfood (5.6), the organization and roles (3.14) and error alerting (6.4): from the
cutover on, links printed and emailed over the years depend on Shurly.

**Can both coexist?** They already do: the shared ALB routes by hostname (`go.griddo.io` → Shlink,
`s.griddo.io` → Shurly). Each hostname points at one service at a time, so the cutover moves `go.griddo.io`
with one ALB change, and rolling back restores it. Shurly resolves links by (Host → domain, code) since
3.10.1, so one instance can serve both hostnames.

### 8.1 Decisions first
- [x] Hostname for new links after the cutover: **`go.griddo.io`** (decided 2026-09-27). A new address for links
      would confuse people. Until the cutover `go.griddo.io` still points at Shlink, so test links made in Shurly
      live on `s.griddo.io`
- [x] `s.griddo.io` is deleted entirely at the cutover, with no redirects kept (decided 2026-09-28): nothing was
      ever published on it. The app, API and MCP are on `shurly.griddo.io` before then
- [x] Shared or personal links 🔎 R7: **the organization's by default, personal only on purpose** (decided
      2026-09-27) → 3.14
- [x] Owner of the migrated links: the Griddo organization (3.14)
- [x] Visit history: import it as `Visitor` rows (no schema change, but Shlink exposes no IPs, so unique-visitor
      counts won't cover it) or archive Shlink's export and start counting at the cutover → **decided
      2026-09-28: imported**, with the import's `--visits`: ip "unknown" (which tells imported visits apart), the
      country, user agent and referer, bots and the `/track` pixel as Shlink flagged them. Unique-visitor counts
      cover the cutover onward only

### 8.2 Case sensitivity 🔎 R6
Shlink defaults to `SHORT_URL_MODE=strict`: case-sensitive lookups and mixed-case generated codes. Shurly's
`loose` lowercases codes when they are created but matches the path exactly; Shlink's `loose` also matches
case-insensitively.
- [ ] Check which mode `go.griddo.io` runs
- [x] `strict` → import codes verbatim (skip `normalize_short_code`); Shurly's exact-match resolver already
      behaves like Shlink's strict mode. Pin it with a test so lookups never get lowercased by accident → the
      import keeps codes verbatim; `test_answers_on_its_domain_with_its_exact_code` pins the redirect
- [ ] `loose` → case-insensitive lookup on that domain before the cutover

### 8.3 Finish multi-domain (3.10.1 shipped the model only)
- [ ] `Domain` row for `go.griddo.io`
- [x] `build_short_url()` uses the link's own domain; today it always builds on the default one, so a migrated
      link would be shown as `s.griddo.io/<code>` → `link_short_url` everywhere a link's short URL is shown:
      responses, campaigns and their CSV, the overview, previews. BASE_URL still moves only the default domain's
- [ ] Make `go.griddo.io` the default domain at the cutover. Changing `DEFAULT_DOMAIN` alone won't do it:
      `get_or_create_default_domain()` keeps the row already marked default (`s.griddo.io`), so new links would
      still be created there (and, until the previous item lands, shown on `go.griddo.io`). Demote `s.` and
      promote `go.` explicitly, with a test
- [ ] No per-link domain choice needed: every new link goes on `go.griddo.io`
- [x] A link's analytics count its own visits: keyed on `visits.url_id`, never on the code, which can name
      links on both domains while Shlink's are imported next to the test links (`tests/test_visits_per_link.py`)
- [x] The API finds a link by its code alone (`/urls/{code}`, its analytics, rules…): the first of the links
      the viewer sees. With one code on both domains, both visible, which one answers is arbitrary. Before the
      import: a domain qualifier (`?domain=`), or a rule such as the default domain first → both: `?domain=`
      on every route and MCP tool that takes a code, read like a request's Host; without it, the default
      domain's link, then by hostname (`find_url`). Bulk tagging takes `links`. The dashboard passes the
      domain; a bookmark without one still works (`tests/test_phase83_link_domains.py`)

### 8.4 Export → clean → import
Clean in the export, not in Shlink: Shlink stays intact as the rollback, every decision is written down, and
the import can be re-run.
- [x] Export script over Shlink's REST API (`/rest/v3/short-urls`, `…/redirect-rules`, `…/visits`) with an API
      key → raw JSON snapshot, archived untouched → `python -m server.tools.shlink export`
      (`server/tools/shlink/README.md`). The snapshot can hold personal data: `_exchange/` or an encrypted store,
      never the repo
- [x] Review sheet (CSV), one row per link: code, domain, destination, title, tags, created, visits, last visit,
      expired/capped, destination HTTP status, duplicate-of, and a `decision` column: `keep`, `archive` or `drop`
      → `… review`, plus the redirect-rule conditions Shurly lacks and codes that differ only in case (8.2). The
      destination status goes through the link previews' SSRF guard
- [x] Default to `keep`: a kept link costs a row; a dropped one that turns out to be on a poster, a QR code or a
      PDF breaks for good. `archive` = migrate with a `legacy` tag the dashboard can hide; `drop` only for tests
      and duplicates → the sheet fills `keep`; the import applies the rest
- [x] Field mapping: long URL, title, tags, valid since/until, max visits, crawlable, `forwardQuery` →
      `forward_parameters`, redirect rules. Conditions Shurly lacks (e.g. IP or geolocation) go in the report;
      nothing is dropped silently → a rule with one leaves whole, reported; `language en-US` becomes `en` and
      `valueless-query-param` a presence match, reported as approximated
- [x] Import (idempotent, `--dry-run` first): exact code, original domain and creation date; fails on a
      conflict instead of suffixing like the custom-code path does → `python -m server.tools.shlink import`
      (`server/tools/shlink/README.md`): owned by the organization, as an owner; a link Shurly can't take stops
      it too, unless the review drops it; a later snapshot adds only newer visits (the cutover's delta)
  - [ ] How it runs in production: it writes to the private RDS. Decision B, with the user: a one-off ECS task
        (recommended) or ECS Exec (needs an ECS task role with SSM permissions; `deploy_ecs.sh` sets none)
- [x] Fill `Visitor.country` for Shurly's own visits (geolocation: 2.x's deferred "IP geolocation service
      integration"). Nothing fills it today, so once Shlink's history is imported the geo view shows only that
      history, and would mislead → the ISO code, from DB-IP's IP to Country Lite (CC BY 4.0, no account),
      looked up in process from the stored, anonymized address (`server/utils/geo.py`). The image build fetches
      the file, and the deploy job warns without it. The Shlink import stores codes too; the page shows names

### 8.5 Cutover
- [ ] Freeze link creation in Shlink; final delta export + import
- [ ] ALB: add `go.griddo.io` to the host condition of rule 12 (Shurly), then delete rule 10 (Shlink). Rollback:
      recreate rule 10. Update `RULE_SYNC_MAP` in `infra/ecs-alb-rule-sync/`. The `go.griddo.io` certificate is
      already on the listener
- [ ] Switch the default domain to `go.griddo.io` (8.3) in the same window
- [ ] Delete `s.griddo.io` entirely: out of rule 12's host condition, its certificate off the listener and deleted,
      its Route 53 record (griddo-production), its `Domain` row and test links; the docs and scripts that still
      name it
- [ ] Smoke on `go.griddo.io` with a sample of migrated codes, mixed case included
- [ ] Watch orphan visits on `go.griddo.io` for 2–4 weeks: hits on dropped codes show what was still in use →
      re-import them from the raw export

### 8.6 Decommission
- [ ] Shlink stopped but restorable during the rollback window; final RDS snapshot
- [ ] Delete shlink-api and shlink-web, ALB rules 10/11, their `RULE_SYNC_MAP` entries and Shlink's RDS
- [ ] Point `links.griddo.io` at the Shurly frontend, if 4.10 chooses it

---

## Development Strategy: TDD + Parallel Agents

### Test-Driven Development (TDD)
We're adopting a TDD approach for core functionality:
1. **Write tests first** - Define expected behavior through tests
2. **Implement functionality** - Write code to make tests pass
3. **Refactor** - Clean up while tests ensure correctness
4. **Benefits**: Higher code quality, living documentation, confidence in refactoring

### Parallel Development with Agents
To maximize velocity, we'll use specialized agents:

**Backend Agent** (general-purpose):
- Focus: API endpoints, business logic, database operations
- Tasks: URL shortening, campaign creation, analytics
- Output: Tested, working endpoints

**Frontend Agent** (general-purpose):
- Focus: Dashboard UI, forms, charts, user experience
- Tasks: URL management UI, campaign creation wizard, analytics dashboard
- Output: Responsive, accessible frontend components

**Orchestration**:
- Main session coordinates agents and ensures integration
- Agents work independently on their domains
- Regular sync points to ensure API contracts match
- Integration tests to verify frontend-backend communication

### When to Use Parallel Agents
- ✅ When frontend and backend tasks are clearly separated
- ✅ When API contracts are well-defined (OpenAPI/Swagger)
- ✅ For large features (e.g., campaign system = backend API + frontend wizard)
- ❌ Not for tightly coupled changes requiring iteration

---

## Notes & Decisions

### Database Choice: PostgreSQL ✅
- JSON for flexible campaign user data (planned as JSONB; the columns are `json`)
- Better AWS integration
- Native UUID support
- Superior analytics query performance

### Authentication: JWT ✅
- Stateless, Lambda-friendly
- Standard industry practice
- Easy to implement with python-jose

### ~~Serverless Architecture: AWS Lambda~~ → superseded by ECS Express (2026-04-26)
- Original choice: cost-effective for low traffic, auto-scaling, 1-2s cold start acceptable, ~$20-35/month
- Replaced by ECS Express on Fargate: the MCP server wants a long-lived process, the redirect path shouldn't
  pay cold starts, and the RDS pool stays warm. See Phase 4 and the decision log in `docs/AWS_ECS_DEPLOYMENT.md`.

### Campaign URL Approach: Lookup Token ✅
- Short code maps to JSON user_data
- Privacy-friendly (no PII in URLs)
- Flexible (any CSV columns)
- Server-side parameter injection on redirect

---

## Retro log — work we did not see coming

Every task that joined the plan late, or turned out to be missing, gets an entry here and a 🔎 R<n> marker
where the task lives. Kinds: **missed** (should have been planned), **new scope** (decided later), **wrong
record** (the docs said something the code or the source didn't). This log feeds the final retro: what to
check earlier in the next project.

### R1 — Sign-up open to anyone in production · missed · found 2026-09-27
- **What:** `POST /api/v1/auth/register` took any email, unconfirmed and unthrottled, from the first deploy
  (2026-04-27) → 3.13
- **How it surfaced:** reviewing the pending work before the dogfood
- **Why it slipped:** Phase 1.3 built open sign-up as the default, and the pre-launch hardening (3.9) covered
  the redirect path but never asked who may sign up
- **Lesson:** before going public, list every unauthenticated endpoint and decide who may call it. Who can
  sign up is a product decision to make explicitly
- **Decision:** the stopgap (3.13.1) was dropped on 2026-09-27, since production has no users and no frontend yet
- **Later the same day:** 3.14.2 + 3.14.3 made the open sign-up worse — any new account joined the organization
  and could read and export every campaign, recipients' names and emails included → closed by the domain gate
  in 3.14.2 (R13). Sign-up itself stays open until 3.13
- **Closed (2026-09-28):** 3.13.2 turns `POST /auth/register` off (404 unless `ALLOW_PASSWORD_SIGNUP`, local
  development only). Accounts come from signing in with Google

### R2 — No password reset · missed · found 2026-09-27
- **What:** a user who forgets the password has no way back → 3.13.3 (sign in with Google and set a new one;
  external users get a reset email in 3.15)
- **How it surfaced:** designing the confirmation email for R1
- **Why it slipped:** with no email sending in the stack, every flow that needs a mailbox stayed invisible
- **Lesson:** settle "can the app send email?" early; confirmation, reset and notifications all depend on it

### R3 — Frontend hosting fell out of the plan · missed · found 2026-09-27
- **What:** the ECS rewrite of Phase 4 (2026-04-26, `eb0efd6`) dropped the S3 + CloudFront items and pointed
  the frontend at "Phase 7", which is Documentation. The frontend was finished (3.11) with nowhere to run → 4.10
- **How it surfaced:** asking why the redesign had no public URL
- **Why it slipped:** the pivot rewrote the phase around the backend, and nobody compared the deliverables of
  the old plan with the new one
- **Lesson:** after a pivot, diff the deliverables of the old plan against the new one: each one gets a home or
  an explicit "dropped"

### R4 — The dogfood had nothing to measure with · missed · found 2026-09-27
- **What:** 5.6 asks for per-tool counts, errors and durations, and nothing logs them → 5.6.0
- **How it surfaced:** checking what 5.6 needs before starting it
- **Why it slipped:** the goal named the measurement but not the task that produces the data
- **Lesson:** every "measure X" goal gets its instrumentation task, done before the measuring window opens

### R5 — Replace Shlink · new scope · decided 2026-09-27
- **What:** Shurly reused Shlink's infrastructure, but the plan never said whether it would replace it.
  Decided: it will, migrating its links → Phase 8
- **Lesson:** when a new system overlaps an existing one, write down its fate on day one (coexist, replace or
  absorb): it shapes the data model (R7) and the migration

### R6 — Shlink's defaults recorded wrong · wrong record · found 2026-09-27
- **What:** 3.9.6 says `loose` is Shlink's default; it's `strict`. And Shurly's `loose` only lowercases codes
  on create, while Shlink's also matches case-insensitively → 8.2
- **How it surfaced:** reading Shlink's docs to plan the migration
- **Why it slipped:** the setting was borrowed by name, without checking its default or behaviour at the source
- **Lesson:** when a design copies a reference system, cite the source for each default and behaviour it copies

### R7 — Links belong to a person; Shlink's belong to the team · missed · found 2026-09-27
- **What:** every Shurly query filters by `created_by`; replacing a shared Shlink needs shared links or a team
  model → 8.1. Decided: links belong to the organization by default, personal ones on purpose, with three
  roles (owner, admin, member) → 3.14
- **How it surfaced:** deciding who would own the migrated links
- **Why it slipped:** the use cases at the top of this file are one person's flows; a team sharing links never
  was one
- **Lesson:** in B2B tools, decide early whether data belongs to the person or to the team: cheap on day one,
  a migration later

### R8 — API keys don't fit every MCP client we targeted · missed · found 2026-09-27
- **What:** Phase 5 named Claude Desktop among its clients but only built API-key auth. claude.ai's custom
  connectors only authenticate with OAuth: their form has no field for a bearer token → 5.8
- **How it surfaced:** planning how people would install the MCP
- **Why it slipped:** the server's auth was chosen without checking how each target client authenticates
- **Lesson:** for any integration, list the target clients first and check how each one authenticates

### R9 — No install guide for the people who would use the MCP · missed · found 2026-09-27
- **What:** the install steps live only in `mcp_server/README.md`, written for developers; the app's "API & MCP"
  tab shows an API key and a `curl` example. The dogfood targets the Griddo team → 5.9
- **How it surfaced:** the product owner asked for in-app instructions, mirrored in the user manual
- **Why it slipped:** "document it" was read as developer docs; nobody pictured the people who'd install it
- **Lesson:** onboarding docs for the real audience are part of a feature's definition of done

### R10 — fastmcp's error line logged tool arguments · missed · found 2026-09-27
- **What:** the usage log (5.6.0) logs argument names only, but fastmcp logs each failed call itself, with a
  traceback. For a generated tool the error carries the API's response body, and a 422 body echoes the invalid
  values: the whole request body, a campaign's CSV rows included, when a field is missing. So argument values
  could reach CloudWatch. So could any request's input through a database error, whose message SQLAlchemy ends
  with the statement's parameters, and a destination URL through the link-preview fetcher's own warnings → 5.6.0
- **How it surfaced:** probing the usage log's test harness: a `create_short_url` call with an invalid URL put the
  value on stderr. Then checking what the traceback kept for real errors prints turned up the SQL parameters, and
  a pass over the app's own log calls the fetcher's
- **Why it slipped:** "never log argument values" was checked against the lines the usage log writes; the test
  read only those JSON lines, not everything the process wrote, and the older log calls were never checked
  against the new rule
- **Lesson:** test a "never log X" rule against the whole of stderr for a call that carries X, failures included:
  frameworks log on their own, libraries put data in their exception messages, and old log lines predate the
  rule

### R11 — Sign-up designed before asking which identity provider the company runs · missed · found 2026-09-27
- **What:** 3.13 was first planned as email confirmation over SES, with our own password reset. Griddo runs Google
  Workspace, and signing in with it covers the domain check, email verification, MFA and resets → 3.13
  rewritten; the email flow moved to 3.15, for external users
- **How it surfaced:** planning OAuth for the MCP (5.8), which needed an identity provider anyway
- **Why it slipped:** sign-up was designed from the app outwards, not from the accounts the company already has
- **Lesson:** for an internal tool, ask first which identity provider the company runs; signing in with it
  usually replaces sign-up, verification and password resets

### R12 — A data migration counted on a row the app makes after migrating · missed · found 2026-09-27
- **What:** migration `0003` gives the organization every existing link, but the app creates the organization at
  startup, after the migrations. With `0002` and `0003` in one deploy it found none and left every link personal
  → `0003` creates the organization itself (3.14.1)
- **How it surfaced:** re-reading the diff before pushing. The test passed because it inserted the organization
  by hand before migrating
- **Why it slipped:** the test built the state the migration expected, not the one a deploy starts from
- **Lesson:** test a data migration from what a real deploy starts with: the last release's schema and data, and
  every pending revision in one run

### R13 — Joining the organization didn't check the email domain · missed · found 2026-09-28
- **What:** 3.14.2 put every new account in the organization, and 3.14.3 let every member see the organization's
  links and campaigns, CSV exports included. With sign-up still open (R1), anyone could register with any
  address and read the team's campaigns, recipients' personal data included → domain gate in 3.14.2
- **How it surfaced:** reviewing #57 and #58 against each other, not one at a time; each was right on its own
- **Why it slipped:** the domain setting existed (`ORGANIZATION_DOMAIN`, for Google sign-in in 3.13), so it read
  as already enforced; 3.14 assumed 3.13 would land first, and the stopgap that would have covered the gap had
  been dropped (3.13.1)
- **Lesson:** when a change widens what a role can see, re-check who can get that role today, not after the
  planned phases land. A setting that names a boundary isn't the boundary until something enforces it

### R14 — The first-deploy script could wipe production's settings · missed · found 2026-09-29
- **What:** `scripts/deploy_ecs.sh` created the service, and on later runs updated it with the container it built.
  That container's environment holds 20 variables; since 3.13 production also carries settings added on the
  live service (sign in with Google, the MCP's OAuth, `FRONTEND_URL`, …), and an update would have dropped
  them all. The playbook still offered it as "Deploy from local" → the script only creates (6.3)
- **How it surfaced:** the docs sweep, following why the script's `CORS_ORIGINS` default mattered at all
- **Why it slipped:** the GitHub deploy moved to swapping only the image, and settings moved to the live service,
  but the local script kept its create-or-update path; the rule "it's first-create only" lived in people's
  heads and one doc line, not in the script
- **Lesson:** when the source of truth for a setting moves, check every tool that still writes it. A rule about
  when not to run a script belongs in the script

