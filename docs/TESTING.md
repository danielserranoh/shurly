# Shurly - Local Testing Guide

This guide provides comprehensive instructions for testing the Shurly URL shortener application locally before AWS deployment.

## Table of Contents

1. [Local Setup](#local-setup)
2. [The backend's tests](#the-backends-tests)
3. [End-to-end tests](#end-to-end-tests)
4. [Functional Testing Checklist](#functional-testing-checklist)
5. [UX Testing Scenarios](#ux-testing-scenarios)
6. [API Testing](#api-testing)
7. [Edge Cases & Error Handling](#edge-cases--error-handling)
8. [Performance Testing](#performance-testing)

---

## Local Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL 14+ (or use Docker)
- [uv](https://github.com/astral-sh/uv) installed

### Option 1: Using Docker Compose (Recommended)

The easiest way to test locally is using Docker Compose, which sets up both the database and API:

```bash
# Start the entire stack (PostgreSQL + FastAPI)
docker compose up -d

# View logs
docker compose logs -f api

# Stop when done
docker compose down
```

The API will be available at `http://localhost:8000`

### Option 2: Manual Setup

#### 1. Start PostgreSQL

```bash
# Using Docker for PostgreSQL only
docker run -d \
  --name shurly-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=shurly \
  -p 5432:5432 \
  postgres:14-alpine

# Or use your local PostgreSQL installation
createdb shurly
```

#### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
# For local testing, the defaults should work:
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=shurly
JWT_SECRET_KEY=dev-secret-key-change-in-production
CORS_ORIGINS=http://localhost:4321,http://localhost:3000
# Phase 3.13: accounts come from signing in with Google, so POST /auth/register is
# off. Turn it on to make local accounts with a password (never in production):
ALLOW_PASSWORD_SIGNUP=true
```

#### 3. Start Backend

```bash
# Install dependencies: exactly uv.lock's, with the tests' and the MCP's
uv sync --extra dev --extra mcp

# Run backend server
uv run uvicorn main:app --reload

# Backend will be at http://localhost:8000
# API docs at http://localhost:8000/docs
```

#### 4. Start Frontend

```bash
# In a new terminal
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev

# Frontend will be at http://localhost:4232
```

#### 5. Verify Setup

- Backend: http://localhost:8000/docs (should show Swagger UI)
- Frontend: http://localhost:4232 (should show landing page)

---

## The backend's tests

`uv run pytest` runs the suite on an in-memory SQLite database: fast, and the default. PostgreSQL, which
production runs, refuses things SQLite takes (a `GROUP BY` on a `json` column, a NUL character in text), so CI
runs the suite on it too. Locally, on any PostgreSQL server (`docker compose up -d db`):

```bash
# The migration and PostgreSQL tests, which skip without a server
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/postgres uv run pytest

# The whole suite on PostgreSQL (CI's `test-postgres` job): a database made for the run, dropped at its end
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/postgres TEST_SUITE_ON_POSTGRES=1 uv run pytest
```

A run that's killed rather than ended leaves its `shurly_suite_…` database behind: drop it by hand.

---

## End-to-end tests

Phase 6.1. Playwright drives the production build of the frontend in Chromium, against the real API on a real
PostgreSQL. CI runs them on every push and pull request (the `e2e` job of `.github/workflows/test.yml`).

- **The API** is `tests/e2e/app.py`: the app, with the pytest suite's fake Google (`tests/fake_google.py`) in
  place of Google's page and endpoints, and no link previews fetched. Signing in goes through the real flow
  (`/auth/google/start`, the callback, the one-time code); the fake's page answers at once, for
  `e2e.owner@griddo.io`, the organization's first account and so its owner. The wrapper refuses to start without
  `E2E=1` (Playwright sets it) or with a `DB_HOST` other than `localhost`, `127.0.0.1` or `::1`. It isn't in
  `main.py`, and the image never copies `tests/` (`tests/test_e2e_guard.py` checks the dockerfile).
- **The pages** are built into `frontend/dist-e2e/` with `PUBLIC_API_URL` pointing at the test API, so they carry
  the production Content-Security-Policy and Trusted Types. Chromium only: it's the browser that enforces
  Trusted Types.
- **Every test fails** on a CSP or Trusted Types violation, an uncaught error in a page, a 5xx from the API, or a
  request to any host but this machine: fonts, analytics, anything (`frontend/e2e/fixtures.ts`).
  `harness.spec.ts` breaks each rule once to show it's caught, and that the page reports it to the API.

To run them, on a throwaway database:

```bash
docker run -d --name shurly-e2e-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=shurly_e2e \
  -p 127.0.0.1:55433:5432 postgres:17
cd frontend
npx playwright install chromium   # once; or set E2E_CHANNEL=chrome to use your Google Chrome
DB_HOST=127.0.0.1 DB_PORT=55433 DB_USER=postgres DB_PASSWORD=postgres DB_NAME=shurly_e2e npm run e2e
```

Playwright builds the pages, starts the API on `127.0.0.1:18000` and the pages on `127.0.0.1:14321` (both
ports must be free), signs in once as the owner and once as a member (`e2e/auth.setup.ts`, `e2e/member.setup.ts`),
runs `e2e/*.spec.ts` one at a time, and stops both servers. The API's log is `frontend/e2e/.logs/api.log`; a failed test leaves a screenshot in
`frontend/test-results/`. Add `--headed` or `--ui` to watch.

Writing a spec: import `test` and `expect` from `e2e/fixtures.ts`, never from `@playwright/test`, so the rules
apply. Make what the spec tests the way a person would; make what it only needs through the API, as the owner
(the `ownerApi` fixture). `e2e/helpers.ts` has a person's click and email open (straight to the API, with a
browser's user agent), picking an option of a segmented control, and a downloaded CSV's lines. Wait on what the
page shows, never on time, and give each spec data of its own: a run shares one database.

Specs run as the owner. To be a member instead, a second account on the Workspace domain, add
`test.use({ storageState: MEMBER_STATE })` (from `e2e/env.ts`); the `memberApi` fixture makes what's theirs. `e2e/member.setup.ts` signs them in with the cookie
`e2e_as=member`, which tells the fake Google page who it is (`tests/e2e/identities.py`); nothing but the harness
reads it (`tests/test_e2e_guard.py`).

Accessibility: `e2e/a11y.spec.ts` runs axe on the landing, login, dashboard, link, campaign and Settings pages and
the manual, once their content is in, on a desktop and on a phone (390 px, where the menu is a dialog, checked
open). A moderate, serious or critical issue fails the test (`IMPACTS`); a minor one doesn't. Fix what it finds, or
add it to the spec's `ALLOWED` list with a reason and the issue that will fix it; never turn a rule off. axe leaves
some contrast undecided (text over a gradient, a translucent panel or a scroll fade, SVG text, anything under a
dialog): check those by hand against the design system's inks.

---

## Functional Testing Checklist

### 1. Authentication Flow

**Accounts** (Phase 3.13): there's no sign-up page. An account comes from signing in with Google, or,
locally, from `POST /api/v1/auth/register` with `ALLOW_PASSWORD_SIGNUP=true` (see API Testing below).
- [ ] http://localhost:4232/register/ → lands on the login page
- [ ] Without the Google settings, "Sign in with Google" comes back to the login page with "Google sign-in
      isn't available right now…"
- [ ] With them (DEPLOYMENT.md § Sign in with Google), signing in lands on the dashboard, or on the page
      that sent you to the login page

**Password** (Settings → Account, Phase 3.13.3):
- [ ] Signed in with Google and no password: "Set password" works right after signing in, and the section then
      says you sign in with Google or with your email and this password
- [ ] "Remove password" asks first, then leaves Google only
- [ ] With Google and a password, the current password is optional: with it, a change works at any time
- [ ] More than 10 minutes after signing in, changing it without the current password, or removing it, offers
      "Sign in with Google again", which comes back to Settings → Account
- [ ] `/login/?next=/%09/evil.com` (or `?next=//evil.com`) lands on the dashboard after logging in, never on
      another site. The unit tests cover the rest: `cd frontend && npm test`
- [ ] An account with a password and no Google identity: the current password is asked, and "Remove password"
      is locked, saying why

**Login:**
- [ ] Navigate to http://localhost:4321/login
- [ ] Try logging in with wrong password → Should show error
- [ ] Try logging in with non-existent user → Should show error
- [ ] Login with correct credentials → Should redirect to dashboard
- [ ] Verify navbar shows email and navigation links

**Logout:**
- [ ] Click "Logout" button in navbar
- [ ] Verify redirect to login page
- [ ] Try accessing /dashboard → Should redirect to login

**Protected Routes:**
- [ ] Log out, try accessing /dashboard directly → Should redirect to login
- [ ] Try accessing /dashboard/campaigns → Should redirect to login
- [ ] Try accessing /dashboard/analytics → Should redirect to login

### 2. URL Shortening

**Standard URLs:**
- [ ] Login and navigate to dashboard
- [ ] Click "Create New URL" button
- [ ] Select "Standard" tab
- [ ] Enter a valid URL (e.g., https://www.google.com)
- [ ] Click "Create Short URL"
- [ ] Verify short URL is generated (6-character code)
- [ ] Verify URL appears in the list
- [ ] Copy short URL and paste in browser → Should redirect to original URL

**Custom Short URLs:**
- [ ] Click "Create New URL"
- [ ] Select "Custom" tab
- [ ] Enter a valid URL (e.g., https://github.com)
- [ ] Enter custom code (e.g., "github")
- [ ] Click "Create Short URL"
- [ ] Verify custom short URL is created
- [ ] Try creating another URL with same custom code → Should show warning about modification
- [ ] Copy custom URL and test redirect

**Invalid URLs:**
- [ ] Try creating URL without http/https → Should show error
- [ ] Try invalid custom code (e.g., "a" - too short) → Should show error
- [ ] Try custom code with spaces → Should show error

### 3. URL Management

**URL List:**
- [ ] Verify dashboard shows all created URLs
- [ ] Check that URL cards display: short code, original URL, type, created date, click count
- [ ] Verify "Copy" button copies short URL to clipboard
- [ ] Verify copy button shows "Copied!" feedback

**URL Details:**
- [ ] Click "View Details" on any URL
- [ ] Verify details page shows:
  - Short code and type badge
  - Original URL
  - Total clicks, recent clicks (7 days), unique visitors
  - Click activity chart (last 7 days)
  - Geographic distribution (if clicks exist)
  - Created date
- [ ] Test "Copy Link" button
- [ ] Test "Delete" button → Should show confirmation modal
- [ ] Cancel delete → Modal should close
- [ ] Confirm delete → Should redirect to dashboard, URL should be gone

### 4. Campaign Management

**Create Campaign:**
- [ ] Navigate to /dashboard/campaigns
- [ ] Click "Create New Campaign"
- [ ] Step 1: Enter campaign name (e.g., "Q1 2024 Campaign") and original URL
- [ ] Click "Next"
- [ ] Step 2: Paste sample CSV data:
  ```
  firstName,lastName,company,email
  John,Doe,Acme Inc,john@acme.com
  Jane,Smith,Tech Corp,jane@tech.com
  Bob,Johnson,StartupXYZ,bob@startup.com
  ```
- [ ] Verify preview table shows 3 rows
- [ ] Click "Next"
- [ ] Step 3: Review campaign details
- [ ] Click "Create Campaign"
- [ ] Verify campaign appears in list
- [ ] Verify "3 URLs" count is shown

**Campaign Details:**
- [ ] Click on campaign name
- [ ] Verify campaign details page shows:
  - Campaign name, original URL, created date
  - Summary stats (total clicks, unique visitors, click-through rate)
  - URLs table with user data
- [ ] Verify each row shows: short URL, user data tags, click count
- [ ] Click "Copy" on a campaign URL
- [ ] Paste in browser → Verify redirect has query parameters (e.g., ?firstName=John&lastName=Doe...)
- [ ] Click "Export URLs (CSV)" → Verify CSV file downloads
- [ ] Open CSV → Verify all data is present

**Delete Campaign:**
- [ ] On campaign details page, click "Delete Campaign"
- [ ] Verify confirmation modal appears
- [ ] Cancel → Modal should close
- [ ] Click delete again and confirm
- [ ] Verify redirect to campaigns list
- [ ] Verify campaign and all its URLs are deleted

### 5. Analytics Dashboard

**Overview Page:**
- [ ] Navigate to /dashboard/analytics
- [ ] Verify stats cards show:
  - Total URLs
  - Total Campaigns
  - Total Clicks
  - Unique Visitors
- [ ] Verify "Recent Activity (Last 7 Days)" section shows click count
- [ ] Verify timeline chart displays daily activity bars
- [ ] Hover over bars → Should show exact click counts
- [ ] Verify "Top Performing URLs" shows up to 5 URLs ranked
- [ ] Click on a top URL → Should navigate to URL details

**CSV Export:**
- [ ] Click "Export Analytics CSV" button
- [ ] Verify CSV file downloads with timestamp
- [ ] Open CSV → Verify it contains:
  - Summary stats
  - Daily timeline data
  - Top URLs data

**Geographic Distribution:**
- [ ] Navigate to any URL details page
- [ ] Scroll to "Geographic Distribution" section
- [ ] If no clicks yet, should show "No geographic data available"
- [ ] After clicking the short URL from different locations (can simulate with VPN or just test with "Unknown" location)
- [ ] Verify countries appear with horizontal bars
- [ ] Verify click counts are shown

### 6. User Settings

**Profile Information:**
- [ ] Navigate to /dashboard/settings
- [ ] Verify email address is displayed (read-only)
- [ ] Verify account creation date is shown

**Change Password:**
- [ ] Enter incorrect current password → Should show error
- [ ] Enter correct current password
- [ ] Enter new password (< 8 chars) → Should show validation error
- [ ] Enter new password and different confirmation → Should show error
- [ ] Enter valid new password with matching confirmation
- [ ] Click "Change Password"
- [ ] Verify success message appears
- [ ] Logout and login with new password → Should work
- [ ] Try old password → Should fail

**API Key Management:**
- [ ] Verify "No API key yet" message if none exists
- [ ] Click "Generate API Key"
- [ ] Verify API key appears in masked input
- [ ] Verify success message with warning to copy
- [ ] Click "Copy" → Should copy to clipboard
- [ ] Click "Regenerate API Key" → Should show confirmation
- [ ] Confirm → Should generate new key
- [ ] Click "Revoke API Key" → Should show confirmation
- [ ] Confirm → Key should be removed, show "No API key" message

---

## UX Testing Scenarios

### Scenario 1: New User Journey

**Goal:** Test the complete flow from registration to creating first URL

1. Open http://localhost:4321 in incognito/private window
2. Click "Get started"
3. Sign in with Google, or make a local account through the API (API Testing below)
4. Note: the login page opens
5. Sign in with Google, or log in with the local account's email and password
6. Note: Should redirect to empty dashboard
7. Click "Create New URL" button
8. Create a standard short URL for https://example.com
9. Copy the generated short URL
10. Open in new tab → Verify redirect works
11. Return to dashboard → Verify URL appears in list with click count = 1

**Expected UX:**
- Clear call-to-action buttons
- Helpful validation messages
- Smooth redirects
- Immediate feedback on actions
- No confusion about next steps

### Scenario 2: Campaign Manager Workflow

**Goal:** Test the campaign creation flow for marketing team

1. Login to dashboard
2. Navigate to Campaigns
3. Click "Create New Campaign"
4. Follow wizard:
   - Step 1: Name: "Holiday Sale 2024", URL: https://myshop.com/sale
   - Step 2: Upload CSV with 10 customers
   - Step 3: Review and create
5. Navigate to campaign details
6. Copy 3 different campaign URLs
7. Open each in separate tabs → Verify personalized query params
8. Return to campaign details → Verify click counts updated
9. Export campaign CSV → Verify all data present

**Expected UX:**
- Step-by-step wizard is clear and intuitive
- Preview table helps verify data before creation
- Easy to copy individual URLs
- Stats update in real-time after clicks
- Export provides usable data

### Scenario 3: Analytics Review

**Goal:** Review performance data for decision-making

1. Login to dashboard
2. Create 5 different standard URLs
3. Click each short URL 2-3 times (vary the times)
4. Navigate to Analytics dashboard
5. Review overview stats
6. Identify top performing URL
7. Click on top URL → View detailed analytics
8. Review geographic distribution
9. Export analytics CSV for reporting

**Expected UX:**
- Analytics are easy to understand
- Charts provide quick visual insights
- Top performers are clearly highlighted
- Drill-down to details is seamless
- Export provides actionable data

### Scenario 4: Account Security

**Goal:** Manage account security settings

1. Login to dashboard
2. Navigate to Settings
3. Change password to a new secure password
4. Generate API key
5. Copy API key to password manager
6. Test API key is shown correctly
7. Logout and login with new password
8. Navigate to Settings → Verify API key still present
9. Revoke API key
10. Verify it's removed

**Expected UX:**
- Password change requires current password (security)
- Clear warnings about API key security
- Confirmation dialogs for destructive actions
- Success messages provide confidence
- No lost data on page refresh

---

## API Testing

### Using Swagger UI (Recommended)

Navigate to http://localhost:8000/docs for interactive API testing:

**Authentication Flow** (register needs `ALLOW_PASSWORD_SIGNUP=true` since Phase 3.13):
1. POST /api/auth/register
2. POST /api/auth/login → Copy access_token
3. Click "Authorize" button → Enter token as "Bearer {token}"
4. GET /api/auth/me → Should return user info

**URL Endpoints:**
- POST /api/urls (create standard URL)
- POST /api/urls/custom (create custom URL)
- GET /api/urls (list URLs)
- DELETE /api/urls/{short_code}
- GET /{short_code} (redirect - test in browser)

**Campaign Endpoints:**
- POST /api/campaigns (create campaign)
- GET /api/campaigns (list campaigns)
- GET /api/campaigns/{id}
- DELETE /api/campaigns/{id}

**Analytics Endpoints:**
- GET /api/analytics/overview
- GET /api/analytics/urls/{short_code}/daily
- GET /api/analytics/urls/{short_code}/weekly
- GET /api/analytics/urls/{short_code}/geo
- GET /api/analytics/campaigns/{id}/summary

### Using cURL

```bash
# Register (needs ALLOW_PASSWORD_SIGNUP=true since Phase 3.13)
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}'

# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}'

# Create URL (replace TOKEN with JWT from login)
curl -X POST http://localhost:8000/api/urls \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"url":"https://example.com"}'
```

---

## Edge Cases & Error Handling

### Authentication Edge Cases

- [ ] Login with malformed email → Clear error message
- [ ] Register with existing email → "Email already registered" error
- [ ] Access protected route without token → Redirect to login
- [ ] Use expired/invalid JWT token → 401 Unauthorized

### URL Creation Edge Cases

- [ ] Create URL with very long original URL (1000+ chars) → Should work
- [ ] Create custom code with special characters → Should reject
- [ ] Create custom code that's already taken → Should modify and warn
- [ ] Create custom code `mcp` (or `docs`) → Should modify and warn that it's reserved
- [ ] Create URL without protocol → Should show error
- [ ] Create URL with localhost/internal IP → Should work (for testing)

### Campaign Edge Cases

- [ ] Upload CSV with missing columns → Should show error
- [ ] Upload CSV with extra columns → Should handle gracefully
- [ ] Upload CSV with 100+ rows → Should process all
- [ ] Upload CSV with duplicate data → Should create unique URLs
- [ ] Create campaign with very long URL → Should work
- [ ] Delete campaign with 50+ URLs → Should cascade delete all

### Analytics Edge Cases

- [ ] View analytics for URL with 0 clicks → Should show empty state
- [ ] View analytics for newly created URL → Should show 0s
- [ ] Export analytics with no data → Should still generate valid CSV
- [ ] View geo stats before any visits → Should show "No data available"

### Settings Edge Cases

- [ ] Change password with spaces → Should trim/handle
- [ ] Generate API key multiple times → Should replace
- [ ] Revoke non-existent API key → Should handle gracefully
- [ ] Change password to same as current → Should work

---

## Performance Testing

### Load Testing (Optional)

Create 100 URLs and verify performance:

```bash
# Run tests with pytest
uv run pytest

# All 104 tests should pass in < 2 seconds
```

### Browser Performance

- [ ] Dashboard loads with 50+ URLs → Should be responsive
- [ ] Campaign details with 100 URLs → Should render quickly
- [ ] Analytics chart with 7 days of data → Should render smoothly
- [ ] Navigate between pages → Should be instant (client-side routing)

---

## Test Data Templates

### Sample URLs for Testing

```
https://www.github.com
https://www.google.com
https://www.wikipedia.org
https://www.youtube.com
https://www.stackoverflow.com
https://www.reddit.com
https://www.twitter.com
https://www.facebook.com
https://www.linkedin.com
https://www.instagram.com
```

### Sample Campaign CSV

```csv
firstName,lastName,company,email,region
Alice,Anderson,Acme Corp,alice@acme.com,North
Bob,Brown,Beta LLC,bob@beta.com,South
Carol,Chen,Gamma Inc,carol@gamma.com,East
David,Davis,Delta Co,david@delta.com,West
Eve,Evans,Epsilon Ltd,eve@epsilon.com,North
Frank,Fisher,Zeta Corp,frank@zeta.com,South
Grace,Garcia,Eta LLC,grace@eta.com,East
Henry,Harris,Theta Inc,henry@theta.com,West
Iris,Ivanov,Iota Co,iris@iota.com,North
Jack,Jackson,Kappa Ltd,jack@kappa.com,South
```

---

## Reporting Issues

If you encounter any issues during testing:

1. **Check the console** (browser dev tools and terminal)
2. **Check logs**: `docker-compose logs api` or terminal output
3. **Verify database**: Check if tables exist and have data
4. **Check environment variables**: Ensure .env is configured correctly
5. **Restart services**: `docker-compose restart` or restart terminals

### Common Issues

**Issue: Frontend can't connect to backend**
- Verify backend is running on port 8000
- Check CORS_ORIGINS in .env includes http://localhost:4321
- Check browser console for CORS errors

**Issue: Database connection error**
- Verify PostgreSQL is running: `docker ps` or `pg_isready`
- Check DB credentials in .env match database
- Verify database exists: `psql -l | grep shurly`

**Issue: URLs not redirecting**
- Verify short code exists in database
- Check backend logs for errors
- Ensure URL has http:// or https:// protocol

---

## Success Criteria

The application is ready for deployment when:

- ✅ All functional tests pass
- ✅ All UX scenarios complete smoothly
- ✅ All edge cases handled gracefully
- ✅ No console errors in browser or terminal
- ✅ All 104 backend tests pass (`uv run pytest`)
- ✅ API documentation accessible at /docs
- ✅ Performance is acceptable (< 1s page loads)
- ✅ Mobile responsive (test on phone or resize browser)

---

## Next Steps After Testing

Once testing is complete:
1. Document any bugs found and fix them
2. Consider adding more tests for found edge cases
3. Review ROADMAP.md for Phase 4 (AWS Deployment)
4. Prepare production environment variables
5. Plan database migration strategy for production
