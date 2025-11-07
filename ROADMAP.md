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

### 1.4 Core URL Endpoints
- [ ] POST /api/urls - Standard URL shortening
  - [ ] Generate random short code (6 chars)
  - [ ] Validate URL format
  - [ ] Check uniqueness
  - [ ] Store in database
  - [ ] Return short URL
- [ ] POST /api/urls/custom - Custom short code
  - [ ] Validate custom code (alphanumeric, 3-20 chars)
  - [ ] Check availability
  - [ ] If taken: append random chars + warn user
  - [ ] Store and return
- [ ] GET /{short_code} - Redirect endpoint
  - [ ] Lookup short_code in database
  - [ ] If campaign URL: decode user_data JSONB → build query params
  - [ ] Log visit (async/background task)
  - [ ] Return 301/302 redirect with params
- [ ] GET /api/urls - List user's URLs (paginated)
- [ ] DELETE /api/urls/{id} - Delete URL

### 1.5 Campaign System
- [ ] Create campaign utilities
  - [ ] CSV parser (handle flexible columns)
  - [ ] Batch short code generator
  - [ ] User data validator
- [ ] POST /api/campaigns - Create campaign
  - [ ] Accept: name, original_url, CSV file/data
  - [ ] Parse CSV columns dynamically
  - [ ] Generate unique short code per row
  - [ ] Store campaign + all URLs with user_data JSONB
  - [ ] Return campaign summary
- [ ] GET /api/campaigns - List user's campaigns
- [ ] GET /api/campaigns/{id} - Campaign details + URLs
- [ ] GET /api/campaigns/{id}/export - Export campaign URLs as CSV

---

## Phase 2: Analytics Enhancement

### 2.1 Update Analytics Endpoints
- [ ] Refactor existing statistics utilities for new schema
- [ ] GET /api/analytics/urls/{short_code}/daily - Daily clicks (last 7 days)
- [ ] GET /api/analytics/urls/{short_code}/weekly - Weekly clicks (last 8 weeks)
- [ ] GET /api/analytics/urls/{short_code}/geo - Geographic distribution
- [ ] GET /api/analytics/campaigns/{id}/summary
  - [ ] Total clicks, unique IPs, click-through rate per user
  - [ ] Top performing users
  - [ ] Timeline chart data
- [ ] GET /api/analytics/campaigns/{id}/users
  - [ ] List all campaign users with click counts
- [ ] GET /api/analytics/overview - User's overall stats

### 2.2 Enhanced Visitor Tracking
- [ ] Extract user agent parsing
- [ ] Add referer tracking
- [ ] IP geolocation service integration (optional: ipapi.co, ip-api.com)
- [ ] Background task for async logging

---

## Phase 3: Frontend Dashboard

### 3.1 Authentication UI
- [ ] Login page
- [ ] Registration page
- [ ] Protected route wrapper
- [ ] JWT token management (localStorage/cookies)

### 3.2 URL Management
- [ ] Dashboard home (list all URLs)
- [ ] Create URL form (standard + custom toggle)
- [ ] URL details page with mini analytics
- [ ] Copy short URL button
- [ ] Delete URL confirmation

### 3.3 Campaign Management
- [ ] Campaigns list page
- [ ] Create campaign wizard
  - [ ] Step 1: Campaign info (name, original URL)
  - [ ] Step 2: Upload CSV (drag-drop + preview)
  - [ ] Step 3: Review and create
- [ ] Campaign details page
  - [ ] Summary stats cards
  - [ ] Users table with click counts
  - [ ] Export campaign URLs button
- [ ] Campaign analytics visualization

### 3.4 Analytics Dashboard
- [ ] Overview page (aggregate stats)
- [ ] Charts integration (Chart.js or Recharts)
  - [ ] Timeline charts (daily/weekly)
  - [ ] Geographic map or country list
  - [ ] Top performing URLs/campaigns
- [ ] Date range selector
- [ ] Export analytics data (CSV)

### 3.5 User Settings
- [ ] Profile page (email, password change)
- [ ] API key management
- [ ] Account settings

---

## Phase 4: AWS Deployment Preparation

### 4.1 Lambda Adaptation
- [ ] Install Mangum adapter
- [ ] Create Lambda handler (`lambda_handler.py`)
- [ ] Test locally with Lambda emulator (AWS SAM or LocalStack)
- [ ] Environment variable configuration
- [ ] Database connection pooling for Lambda

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

## Current Status: Phase 1.4 - Core URL Endpoints

**Last Updated**: 2025-11-07

**Completed**:
- ✅ Phase 1.1: CAPTCHA removed, PostgreSQL migration complete
- ✅ Phase 1.2: All data models created (User, URL, Campaign, Visitor)
- ✅ Phase 1.3: Authentication system with JWT fully implemented
- ✅ Fixed critical database session management bug

**Next Steps** (TDD + Parallel Development):
1. Write tests for URL shortening logic (TDD approach)
2. Implement core URL endpoints (POST /api/urls, POST /api/urls/custom, GET /{short_code})
3. Implement campaign system (POST /api/campaigns)
4. Run frontend and backend agents in parallel for dashboard development

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
