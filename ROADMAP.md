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

## Phase 4: AWS Deployment Preparation

### 4.1 Lambda Adaptation ✅
- [x] Install Mangum adapter
- [x] Create Lambda handler (`lambda_handler.py`)
- [x] Environment variable configuration (Lambda-specific settings)
- [x] Database connection pooling for Lambda (configurable pool sizes)
- [x] Create deployment documentation (DEPLOYMENT.md)
- [ ] Test locally with Lambda emulator (AWS SAM or LocalStack) - deferred to 4.2

### 4.2 Infrastructure as Code
- [ ] Create AWS SAM template or CDK stack
  - [ ] Lambda function definition
  - [ ] API Gateway HTTP API
  - [ ] RDS PostgreSQL instance
  - [ ] S3 bucket for frontend
  - [ ] CloudFront distribution
  - [ ] IAM roles and permissions
- [ ] Environment configuration (dev/staging/prod)

### 4.3 Database Setup
- [ ] RDS PostgreSQL instance creation guide
- [ ] Security group configuration
- [ ] VPC setup (if needed)
- [ ] Connection string management (Secrets Manager)
- [ ] Migration scripts for production

### 4.4 CI/CD Pipeline
- [ ] GitHub Actions workflow (optional)
  - [ ] Run tests
  - [ ] Lint with ruff
  - [ ] Deploy Lambda function
  - [ ] Deploy frontend to S3
  - [ ] Invalidate CloudFront cache
- [ ] Deployment documentation

### 4.5 Custom Domain Setup
- [ ] Route 53 hosted zone for griddo.io
- [ ] SSL certificate (ACM) for shurl.griddo.io
- [ ] CloudFront custom domain configuration
- [ ] API Gateway custom domain (api.shurl.griddo.io or same domain with /api)

---

## Phase 5: Testing & Optimization

### 5.1 Testing
- [ ] Unit tests (pytest)
  - [ ] URL shortening logic
  - [ ] Campaign CSV parsing
  - [ ] Auth token generation
- [ ] Integration tests
  - [ ] API endpoints
  - [ ] Database operations
- [ ] E2E tests (optional)
  - [ ] Frontend flows

### 5.2 Performance Optimization
- [ ] Database indexes review
- [ ] Query optimization for analytics
- [ ] CloudFront caching strategy
- [ ] Lambda cold start optimization (provisioned concurrency if needed)

### 5.3 Security Hardening
- [ ] Rate limiting (API Gateway usage plans)
- [ ] Input validation review
- [ ] SQL injection prevention check
- [ ] XSS prevention in frontend
- [ ] CORS configuration review
- [ ] Environment secrets audit

### 5.4 Monitoring & Logging
- [ ] CloudWatch Logs setup
- [ ] Error alerting (SNS/email)
- [ ] Key metrics dashboard
  - [ ] Lambda invocations
  - [ ] API Gateway errors
  - [ ] RDS connections
  - [ ] Redirect latency

---

## Phase 6: Documentation & Handoff

### 6.1 Documentation
- [ ] API documentation (OpenAPI/Swagger) - auto-generated by FastAPI
- [ ] Deployment guide
- [ ] User manual for dashboard
- [ ] Architecture diagram
- [ ] Database schema diagram
- [ ] Environment variables reference

### 6.2 Operational Runbook
- [ ] How to add new users
- [ ] How to investigate issues
- [ ] How to scale if needed
- [ ] Backup and recovery procedures
- [ ] Cost monitoring guide

---

## Current Status: Phase 3 Complete - Ready for AWS Deployment!

**Last Updated**: 2025-11-08

**Completed**:
- ✅ Phase 1.1: CAPTCHA removed, PostgreSQL migration complete
- ✅ Phase 1.2: All data models created (User, URL, Campaign, Visitor)
- ✅ Phase 1.3: Authentication system with JWT fully implemented
- ✅ Phase 1.4: Core URL endpoints (standard, custom, redirect, list) - **13 integration tests passing**
- ✅ Phase 1.5: Campaign system (create, list, details, export, delete) - **42 tests passing (15 unit + 27 integration)**
- ✅ Phase 2.1: Analytics endpoints (URL stats, campaign stats, overview) - **12 integration tests passing**
- ✅ Phase 2.2: User agent parsing utilities - **18 unit tests passing**
- ✅ Phase 3.1: Frontend authentication UI (login, register, protected routes)
- ✅ Phase 3.2: Frontend URL management (dashboard, create form, URL cards, details page, delete)
- ✅ Phase 3.3: Campaign management UI (list, create wizard, details, export, delete)
- ✅ Phase 3.4: Analytics dashboard UI (overview, charts, geo distribution, CSV export)
- ✅ Phase 3.5: User settings (profile, password change, API key management)
- ✅ Fixed critical database session management bug
- ✅ Test-driven development approach with **104 tests passing (100%)**

**Test Coverage**:
- 13 unit tests for URL utilities (code generation, validation)
- 19 integration tests for URL endpoints (added 6 delete tests)
- 15 unit tests for campaign utilities (CSV parsing, validation)
- 27 integration tests for campaign endpoints
- 12 integration tests for analytics endpoints
- 18 unit tests for user agent parsing
- Total: **104 tests, 0 failures**

**Backend Features**:
- Complete URL shortening (standard, custom, campaign)
- Full campaign system with CSV support
- Comprehensive analytics API:
  * Daily/weekly stats per URL
  * Geographic distribution
  * Campaign performance metrics
  * User dashboard overview
- User agent parsing (browser, OS, device detection)

**Frontend Features**:
- Complete authentication flow (register, login, logout)
- URL management (create standard/custom URLs, list, copy to clipboard, details page with analytics, delete with confirmation)
- Campaign management (create wizard with CSV upload, list, details table, export CSV, delete)
- URL details page with:
  * Statistics cards (total clicks, recent clicks, unique visitors)
  * Bar chart visualization (last 7 days)
  * Geographic distribution (country list with horizontal bars)
  * Campaign info display with user data tags
  * Copy and delete actions
- Analytics dashboard (/dashboard/analytics):
  * Overview stats (total URLs, campaigns, clicks, unique visitors)
  * Interactive timeline chart (daily activity last 7 days)
  * Top 5 performing URLs with rankings
  * CSV export for all analytics data
- User settings (/dashboard/settings):
  * Profile information display (email, account creation date)
  * Password change with current password verification
  * API key generation, display, copy, and revocation
  * Security warnings and confirmation dialogs
- Responsive Tailwind design with protected routes
- Consistent loading states and error handling

**Next Steps**:
1. AWS deployment preparation (Phase 4)
2. Testing & optimization (Phase 5)
3. Documentation & handoff (Phase 6)

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
