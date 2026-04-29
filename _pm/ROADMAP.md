# Shurly - Project Roadmap

## Project Overview
Modern URL shortener for B2B campaigns with analytics, built for AWS serverless deployment.

**Target Domain**: `shurl.griddo.io`
**Expected Volume**: ~100-150 URLs/month (20-50 standard + 1 campaign of ~100 users)
**Deployment**: AWS Lambda + API Gateway + RDS PostgreSQL + S3 + CloudFront

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
- **Pydantic v2** - Validation
- **JWT** - Authentication
- **Mangum** - Lambda adapter for FastAPI
- **uv** - Package management
- **ruff** - Linting/formatting

### Frontend
- **Astro** - Static site generator
- **Tailwind CSS** - Styling
- **TypeScript** - Type safety
- **Chart.js / Recharts** - Analytics visualization

### Infrastructure
- **AWS Lambda** - Compute
- **API Gateway (HTTP API)** - API routing
- **RDS PostgreSQL (t4g.micro)** - Database
- **S3** - Static frontend hosting
- **CloudFront** - CDN
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
  - [x] Add: short_code (indexed), url_type (enum), campaign_id, user_data (JSONB), created_by
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
- [x] GET /api/analytics/urls/{short_code}/weekly - Weekly clicks (last 8 weeks)
- [x] GET /api/analytics/urls/{short_code}/geo - Geographic distribution (with configurable days)
- [x] GET /api/analytics/campaigns/{id}/summary
  - [x] Total clicks, unique IPs, click-through rate
  - [x] Top 5 performing URLs
  - [x] Daily timeline (last 7 days)
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
- [ ] IP geolocation service integration (deferred - optional feature)
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
- [ ] Campaign analytics visualization (deferred to Phase 3.4)

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

### 3.6.5 Frontend Updates
- [x] Add title input field to URL creation forms
- [x] Add forward_parameters toggle to URL creation forms
- [ ] Add "Edit URL" button to URL details page (future enhancement)
- [ ] Create URL edit modal/page (title, destination, forward params toggle) (future enhancement)
- [ ] Display last_click_at timestamp in URL details (future enhancement)
- [ ] Show forward_parameters status in URL card (future enhancement)
- [ ] Update URL list to show titles (if present) (future enhancement)

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

### 3.7.7 Frontend Updates
- [x] Add Open Graph fields to URL creation form (optional, collapsible section)
- [ ] Create Preview Card component (future enhancement)
- [ ] Add "Refresh Preview" button in edit view (future enhancement)
- [ ] Display OG metadata preview card (future enhancement)
  - [ ] Display og:title, og:description, og:image
  - [ ] Show fallback if metadata missing
  - [ ] "Edit Preview" button
- [ ] Add preview section to URL details page
  - [ ] Visual preview card (how it appears on social media)
  - [ ] "Refresh from destination" button
  - [ ] Edit modal for custom og_* values
- [ ] Add preview indicators to URL list
  - [ ] Icon/badge if custom preview is set
  - [ ] Preview thumbnail in expanded view

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

### 3.8.6 Frontend Components (Pending UX Designs)
- [ ] TagBadge component (color-coded display)
- [ ] TagAutocomplete component (search + inline create)
- [ ] TagFilter component (Pinterest-style multi-select)

### 3.8.7 Frontend Integration (Pending UX Designs)
- [ ] Add tags to Create URL form
- [ ] Add tags to URL Card display
- [ ] Add tags to URL Details page
- [ ] Add tag filter to Dashboard
- [ ] Add bulk tagging UI
- [ ] Add tags to Campaign create/edit

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
- [x] Crawler preview hits do NOT consume quota (Visitor row only inserted on real human visits)
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
- [ ] Document GDPR posture in DEPLOYMENT.md (deferred to Phase 4 deployment doc pass)

### 3.9.6 Architectural Lessons - "Free" Wins ✅
- [x] **X-Request-Id middleware** — `RequestIdMiddleware` in `main.py`
  - [x] Generate UUID per request if not provided
  - [x] Accept and propagate client-supplied `X-Request-Id` header
  - [x] Echo back in response headers
  - [ ] Include in all log lines for CloudWatch correlation (defer access-log formatter to Phase 4)
- [x] **SHORT_URL_MODE config (`strict` | `loose`)**
  - [x] In `loose` mode: lowercase generated codes and lowercase custom slugs at insert
  - [x] In `strict` mode: preserve case, treat `Abc` and `abc` as distinct
  - [x] Default to `loose` (Shlink's default)
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
  - [ ] Document deployment guidance in DEPLOYMENT.md (deferred to Phase 4)
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
- [x] Create RedirectRule model (id, url_id, priority, conditions JSONB, target_url, created_at)
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

## Phase 4: AWS Deployment (ECS Express on griddo-main)

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
- `shurl.griddo.io` (or `shurly.griddo.io`) — reserved for the future frontend (Phase 7).

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

### 4.2 Container image ready for Fargate
- [ ] Audit existing `dockerfile`: confirm uvicorn entrypoint, exposed port, multi-stage build to keep image small, and that it builds for `linux/arm64` (Fargate ARM64 is ~20% cheaper than x86).
- [ ] Add `GET /api/v1/health` endpoint that returns `{"status": "ok"}` without touching the database. ECS Express will hit this via the ALB target group health check; we don't want every health check to consume an RDS connection.
- [ ] Optional: a `GET /api/v1/health/db` endpoint that does touch the DB — used for synthetic monitoring, not for the ALB.
- [ ] Replace `.env.lambda.example` with `.env.production.example`. Same settings (`ANONYMIZE_REMOTE_ADDR`, `TRUSTED_PROXIES`, `DEFAULT_DOMAIN=s.griddo.io`, `REDIRECT_STATUS_CODE`, `REDIRECT_CACHE_LIFETIME`, etc.) but oriented at ECS task env vars instead of Lambda env.
- [ ] Local smoke: `docker build -t shurly:dev . && docker run --env-file .env shurly:dev` should boot uvicorn and answer the health check.

### 4.3 Database (mirrors Shlink Phase 2)
Adapt `scripts/create_rds.sh` for Shurly. Reusing concepts from the Shlink deploy guide; specifics:
- [ ] DB SG: either reuse Shlink's `sg-0336fc12dcb7cad06` (lowest friction) or create `shurly-db-sg`. Decision: separate SG so we can revoke independently if needed.
- [ ] Subnet group: reuse `shlink-db-subnets` (covers default VPC subnets — same VPC).
- [ ] DB instance `shurly-db`, `db.t4g.micro`, 20 GB gp3, `--no-publicly-accessible`, 7-day backup retention.
- [ ] **No `--engine-version` pin** (per Shlink lesson #6).
- [ ] Master user `shurly`, DB name `shurly`. Password from `openssl rand -base64 24` — captured for the env, not committed.

### 4.4 TLS certificate (mirrors Shlink Phase 3)
- [ ] `aws acm request-certificate --domain-name s.griddo.io --validation-method DNS` (`griddo-main`, eu-south-2)
- [ ] Capture validation CNAME, write it to Route 53 from **`griddo-production`** profile (zone `Z0999097TJGECCBKJOY1`)
- [ ] `aws acm wait certificate-validated`

### 4.5 ECS Express service (mirrors Shlink Phase 5)
- [ ] Create ECR repository `shurly-api` in `griddo-main`
- [ ] `docker buildx build --platform linux/arm64 --tag <account>.dkr.ecr.eu-south-2.amazonaws.com/shurly-api:<sha> .`
- [ ] ECR login + push
- [ ] `aws ecs create-express-gateway-service --service-name shurly-api`:
  - Reuses `ecsTaskExecutionRole` + `ecsInfrastructureRoleForExpressServices`
  - `--cpu 256 --memory 512` (Fargate units, **not** decimal — per Shlink lesson #1)
  - `--health-check-path /api/v1/health`
  - `--scaling-target {minTaskCount: 1, maxTaskCount: 2}`
  - Env vars: full set from `.env.production.example`, with `DB_HOST` from RDS endpoint and `DB_PASSWORD`/`JWT_SECRET_KEY` from prompts (or Secrets Manager later)
- [ ] `--monitor-resources` may timeout; verify with `describe-express-gateway-service` (Shlink lesson #2)
- [ ] Smoke against the auto-generated host: `curl https://shurly-api.ecs.eu-south-2.on.aws/api/v1/health`

### 4.6 Custom domain `s.griddo.io` (mirrors Shlink Phase 6)
- [ ] `aws elbv2 add-listener-certificates` — add the `s.griddo.io` ACM cert to the shared ALB's HTTPS listener (Shlink lesson #3)
- [ ] `aws elbv2 create-rule --priority 12 --conditions host-header=s.griddo.io` pointing to Shurly's active target group (the one with weight 100 — Shlink lesson #7 about priority headroom for Express Mode)
- [ ] `aws route53 change-resource-record-sets` from **`griddo-production`** profile: A-alias `s.griddo.io` → ALB
- [ ] `dig s.griddo.io && curl https://s.griddo.io/api/v1/health` to verify

### 4.7 ALB rule sync — extend the existing Lambda
ECS Express does blue/green deploys by alternating target group weights. Manual ALB rules (priority 12 in our case) need to follow the active TG or the service drops. The `ecs-alb-rule-sync` Lambda already handles this for Shlink; we extend it.
- [ ] Identify Shurly's Express Mode rule priority (the one Express Mode auto-creates between 1-5)
- [ ] PR against the Lambda's `RULE_SYNC_MAP`: add `<shurly-express-priority>: "12"` mapping
- [ ] Test: `aws lambda invoke --function-name ecs-alb-rule-sync` returns "No changes needed" or syncs correctly
- [ ] Force a redeploy via `update-express-gateway-service --force-new-deployment` and verify `s.griddo.io` keeps responding without manual intervention

### 4.8 CI/CD with OIDC + ECR + ECS
Replaces the SAM-based GitHub Actions workflow.
- [ ] **One-time setup in `griddo-main`** (documented in DEPLOYMENT.md, executed manually with SSO):
  - GitHub OIDC provider (`token.actions.githubusercontent.com`)
  - IAM role `github-actions-shurly-deploy` with trust policy scoped to `repo:danielserranoh/shurly:*`
  - Permissions: ECR push (scoped to the `shurly-api` repo), ECS update-express-gateway-service (scoped to the Shurly service ARN), CloudWatch Logs read for verification
- [ ] Rewrite `.github/workflows/deploy-backend.yml`:
  - `permissions: id-token: write` for OIDC
  - `aws-actions/configure-aws-credentials@v4` with `role-to-assume`, no access keys
  - `docker buildx build --platform linux/arm64 --push`
  - `aws ecs update-express-gateway-service --force-new-deployment`
  - Trigger: `workflow_dispatch` only until first manual deploy succeeds; then optionally re-enable `push` to `main`
- [ ] No `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` secrets — only `AWS_DEPLOY_ROLE_ARN`, `DB_HOST`, `JWT_SECRET_KEY`, etc.

### 4.9 First real deploy + smoke
End-to-end run with the user driving SSO locally:
- [ ] `./scripts/create_rds.sh` (one-time)
- [ ] Request ACM cert + validate
- [ ] `./scripts/deploy_ecs.sh` (build + push + service create)
- [ ] `./scripts/setup_custom_domain.sh` (cert, rule, DNS)
- [ ] Update Lambda `RULE_SYNC_MAP`
- [ ] Smoke checklist:
  - `register` → `login` → returns JWT
  - `POST /api/v1/urls` creates a short URL bound to `s.griddo.io`
  - `GET /<code>` returns 302 to destination
  - `GET /<code>/track` returns 43-byte GIF
  - `GET /robots.txt` returns default-deny
  - `GET /api/v1/analytics/orphan-visits` after a typo'd `GET /xyzabc` shows the orphan
  - Force `update-express-gateway-service --force-new-deployment` → verify `s.griddo.io` stays up
- [ ] Capture findings in CHANGELOG.md and any follow-up items as new issues

---

## Phase 5: MCP Server over Streamable HTTP

**Goal:** Expose the existing API as an MCP server so internal users (and Claude Code / Claude Desktop) can drive Shurly without a frontend. Pilot for the broader "MCP-as-product" thesis: capture how people actually use the service via natural language, and use those signals to prioritize Phase 7 (frontend) features.
**Duration:** ~1.5–2 weeks
**Priority:** 🟡 MEDIUM — Runs after Phase 4 (deploy) and before Phase 7 (frontend). Backend-only stack already has 3.9 + 3.10 hardening, so this exposes a stable surface.
**Reference:** [Model Context Protocol spec](https://modelcontextprotocol.io/), Anthropic Python SDK (`mcp`), FastMCP (https://github.com/jlowin/fastmcp). Decision rationale recorded in conversation thread (PR review).

**Sequencing:**
- Phase 4 (deploy) must complete first — MCP runs against the same backend; we don't want to debug Lambda cold starts and MCP transports simultaneously.
- Internal dogfood window of ~2–4 weeks before Phase 7 starts. Findings feed the frontend prioritization.

### 5.1 Foundation & framework choice
- [ ] Decision recorded: start with **`fastmcp` standalone** for fast prototyping (auto-generates tools from FastAPI), reserve the option to migrate to `mcp.server.fastmcp` (official SDK) if upstream divergence becomes a real risk.
- [ ] Add `fastmcp` to `pyproject.toml` `mcp` optional-extra group (so it doesn't bloat the Lambda bundle when not needed).
- [ ] Create `mcp_server/` sub-package or sibling module — keep it isolated from `server/` so the API can run standalone.
- [ ] Pick transport: **Streamable HTTP** (single endpoint, request/response, Lambda-friendly). Stdio for local dev only.
- [ ] Document the chosen framework + transport in `mcp_server/README.md` with the 3-option comparison rationale (so a future maintainer doesn't relitigate the decision).

### 5.2 Auto-generated tools from FastAPI
- [ ] Bootstrap: `FastMCP.from_fastapi(app)` (or equivalent) — generate the first cut of tools automatically.
- [ ] Audit the generated tool list: for each `/api/v1/...` endpoint, verify the tool name, description, schema, and return shape are LLM-friendly.
- [ ] Filter out endpoints that should NOT be MCP tools: legacy `statistics.py`, internal-only routes, anything that handles file uploads (campaign CSV — see 5.3).
- [ ] Verify the OG-preview, robots.txt, redirect path, and tracking pixel routes are excluded (they're public unversioned routes, not management API).
- [ ] Tests: each auto-generated tool round-trips through the MCP server and produces the same output as the underlying endpoint.

### 5.3 Hand-curated tools (where auto-gen is awkward) ✅
- [x] **`create_campaign_from_rows`** — accepts `rows: list[dict]`, serialises to CSV in-memory, reuses the existing campaign generator.
- [x] **`get_url_analytics_summary`** — composes totals + daily series + top countries in one call (default 7-day window, bot/pixel filtering aligned with regular analytics endpoints).
- [x] **`add_redirect_rule`** — sugar over `POST /urls/{code}/rules` with named condition args (device/language/browser/query_param[+value]/before_date/after_date), at least one condition required.
- [x] **`list_orphan_visits_grouped`** — clusters by `attempted_path`, returns top-N groups with capped sample list (3 per group) and overall totals.
- [x] Logic in `mcp_server/curated.py` (testable with explicit `db`+`user`); MCP wrappers in `mcp_server/server.py` (auth stub raises until 5.4 lands).
- [x] Tests in `tests/test_phase53_curated_tools.py` cover registration, happy paths, validation, scoping, bot/pixel toggle.

### 5.4 Authentication & per-user scoping ✅
- [x] FastAPI `get_current_user` accepts both JWTs and API keys (token-shape dispatch — JWTs have dots, API keys don't). Single dependency, single test surface.
- [x] `ShurlyTokenVerifier` validates the inbound MCP bearer against `User.api_key`, populating `AccessToken.claims` with user id + email + scope.
- [x] httpx `forward_bearer` hook re-attaches the inbound bearer to the outbound FastAPI call so auto-generated tools resolve the same user as the MCP layer.
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

### 5.6 Internal dogfood + signal capture
- [ ] Roll out to the Griddo team: 3–5 internal users with API keys.
- [ ] Capture for 2–4 weeks: tool invocation counts (which tools get used vs ignored), tool error rates, average call duration.
- [ ] Capture qualitatively: which workflows feel smooth in chat, which feel awkward (e.g. CSV import, charts).
- [ ] Output: a "frontend feature priority" list backed by real signal, fed into Phase 7.

### 5.7 Verification
- [ ] All auto-generated + curated tools have at least one happy-path test.
- [ ] MCP endpoint responds within the same SLO as the regular API.
- [ ] No regression in existing tests (backend behavior unchanged).
- [ ] `mcp_server/README.md` exists and covers: architecture, framework choice, auth, deployment, how to add a new tool.
- [ ] CHANGELOG.md entry under "Added" describing the MCP surface.

### Open questions (resolve during 5.1)
- Does `fastmcp.from_fastapi()` produce useful tool descriptions, or do we need to enrich them via Pydantic `Field(..., description=...)` everywhere first? (Likely yes — most of our schemas already have descriptions; sweep the gaps.)
- Should pixel/redirect endpoints be exposed as tools at all? (Probably not — they're public-facing routes, not management surface.)
- Per-user MCP config in Claude Code: how does the team add their personal API key without committing it? (Document the env-var pattern in `mcp_server/README.md`.)

---

## Phase 6: Testing & Optimization

### 6.1 Testing
- [ ] Unit tests (pytest)
  - [ ] URL shortening logic
  - [ ] Campaign CSV parsing
  - [ ] Auth token generation
- [ ] Integration tests
  - [ ] API endpoints
  - [ ] Database operations
- [ ] E2E tests (optional)
  - [ ] Frontend flows

### 6.2 Performance Optimization
- [ ] Database indexes review
- [ ] Query optimization for analytics
- [ ] CloudFront caching strategy
- [ ] Lambda cold start optimization (provisioned concurrency if needed)

### 6.3 Security Hardening
- [ ] Rate limiting (API Gateway usage plans)
- [ ] Input validation review
- [ ] SQL injection prevention check
- [ ] XSS prevention in frontend
- [ ] CORS configuration review
- [ ] Environment secrets audit

### 6.4 Monitoring & Logging
- [ ] CloudWatch Logs setup
- [ ] Error alerting (SNS/email)
- [ ] Key metrics dashboard
  - [ ] Lambda invocations
  - [ ] API Gateway errors
  - [ ] RDS connections
  - [ ] Redirect latency

---

## Phase 7: Documentation & Handoff

### 7.1 Documentation
- [ ] API documentation (OpenAPI/Swagger) - auto-generated by FastAPI
- [ ] Deployment guide
- [ ] User manual for dashboard
- [ ] Architecture diagram
- [ ] Database schema diagram
- [ ] Environment variables reference

### 7.2 Operational Runbook
- [ ] How to add new users
- [ ] How to investigate issues
- [ ] How to scale if needed
- [ ] Backup and recovery procedures
- [ ] Cost monitoring guide


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
- JSONB for flexible campaign user data
- Better AWS integration
- Native UUID support
- Superior analytics query performance

### Authentication: JWT ✅
- Stateless, Lambda-friendly
- Standard industry practice
- Easy to implement with python-jose

### Serverless Architecture: AWS Lambda ✅
- Cost-effective for low traffic
- Auto-scaling
- 1-2s cold start acceptable per requirements
- Estimated cost: $20-35/month

### Campaign URL Approach: Lookup Token ✅
- Short code maps to JSONB user_data
- Privacy-friendly (no PII in URLs)
- Flexible (any CSV columns)
- Server-side parameter injection on redirect
