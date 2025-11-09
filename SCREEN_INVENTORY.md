# Shurly - Screen & Process Inventory
**Version:** 1.0
**Date:** January 2025
**Purpose:** Complete inventory for UX/UI redesign brief

---

## Table of Contents
1. [Public Screens](#1-public-screens)
2. [Authentication Screens](#2-authentication-screens)
3. [Dashboard Screens](#3-dashboard-screens)
4. [URL Management Screens](#4-url-management-screens)
5. [Campaign Management Screens](#5-campaign-management-screens)
6. [Analytics Screens](#6-analytics-screens)
7. [Settings Screens](#7-settings-screens)
8. [Components](#8-reusable-components)
9. [User Flows](#9-user-flows)
10. [Phase 3.6/3.7 Gaps](#10-phase-3637-feature-gaps)

---

## 1. Public Screens

### 1.1 Landing Page (`/`)
**File:** `frontend/src/pages/index.astro`

**Current State:** ✅ Complete
- Hero section with branding
- Value propositions (Fast & Easy, Analytics, Custom URLs)
- CTA buttons (Sign Up Free, Sign In)

**Design Elements:**
- Gradient background (blue-50 to indigo-100)
- Feature cards with icons (blue, green, purple)
- Large typography (h1: 6xl)
- Shadow effects on cards

**User Actions:**
- Navigate to `/register`
- Navigate to `/login`

**Notes:** Generic marketing page, needs Shurly branding identity

---

## 2. Authentication Screens

### 2.1 Registration (`/register`)
**File:** `frontend/src/pages/register.astro`

**Current State:** ✅ Functional
- Email + password fields
- Validation states
- Error messaging
- Success redirect to dashboard

**Design Elements:**
- White form card on gradient background
- Blue CTA button
- Link to login page

**User Flow:**
```
Landing → Register → Dashboard (auto-login)
```

### 2.2 Login (`/login`)
**File:** `frontend/src/pages/login.astro`

**Current State:** ✅ Functional
- Email + password fields
- Error handling
- Success redirect to dashboard

**User Flow:**
```
Landing/Any Page → Login → Dashboard
```

---

## 3. Dashboard Screens

### 3.1 Main Dashboard (`/dashboard`)
**File:** `frontend/src/pages/dashboard/index.astro`

**Current State:** ✅ Functional, ❌ Missing Phase 3.6 features

**Components:**
- **Navbar** (dynamic with user email)
- **Stats Overview Cards** (3 cards)
  - Total URLs
  - Total Clicks
  - Custom URLs
- **URL List** (URLCard components)
  - Short URL display
  - Original URL
  - Click count
  - URL type badge
  - Created date
  - View Details button
  - Delete button (non-campaign only)
- **Empty State**
- **Loading State**

**Current Display Fields:**
```
URLCard shows:
✅ Short URL
✅ Original URL
✅ Click count
✅ URL type
✅ Created date
❌ Title/Name (Phase 3.6)
❌ Last click timestamp (Phase 3.6)
❌ Forward parameters status (Phase 3.6)
```

**User Actions:**
- Create new URL
- View URL details
- Delete URL
- Copy short URL
- Navigate to create page

**Missing (Phase 3.6):**
- Title/name display prominently on each card
- Last activity timestamp
- Forward parameters indicator

---

## 4. URL Management Screens

### 4.1 Create URL (`/dashboard/create`)
**File:** `frontend/src/pages/dashboard/create.astro`

**Current State:** ✅ Backend complete, ✅ Basic frontend complete

**Form Fields:**
- **Standard Mode:**
  - ✅ Original URL (required)
  - ✅ Title (optional, Phase 3.6)
  - ✅ Forward Parameters toggle (Phase 3.6, defaults true)
  - ✅ Open Graph fields - collapsible (Phase 3.7)
    - OG Title
    - OG Description
    - OG Image URL

- **Custom Mode:**
  - ✅ Original URL (required)
  - ✅ Custom short code (required)
  - ✅ Title (optional, Phase 3.6)
  - ✅ Forward Parameters toggle (Phase 3.6)
  - ✅ Open Graph fields (Phase 3.7)

**Features:**
- Toggle between Standard/Custom
- Collapsible "Social Media Preview (Advanced)" section
- Success state with copy button
- Error/warning messaging
- "Create Another" flow

**Design Notes:**
- OG fields use accordion pattern
- Chevron rotation animation
- Border-left accent for OG section

**Missing UI:**
- ❌ Live preview card (like Rebrandly shows)
- ❌ Visual OG metadata preview

### 4.2 URL Details (`/dashboard/urls/[short_code]`)
**File:** `frontend/src/pages/dashboard/urls/[short_code].astro`

**Current State:** ✅ Analytics complete, ❌ Missing Phase 3.6/3.7 UI

**Current Sections:**
1. **Header**
   - Short code (h1)
   - URL type badge
   - Original URL
   - Created date
   - Copy button
   - Delete button

2. **Stats Cards (3 cols)**
   - Total clicks
   - Clicks (7 days)
   - Unique visitors

3. **Charts**
   - Click Activity (7-day bar chart)
   - Geographic Distribution (horizontal bars)

4. **Campaign Info** (if applicable)
   - Campaign link
   - User data tags

**Current Display:**
```
✅ Short code
✅ Original URL
✅ Type badge
✅ Created date
✅ Click analytics
✅ Geographic data
❌ Title/Name (Phase 3.6)
❌ Last click timestamp (Phase 3.6)
❌ Forward parameters status (Phase 3.6)
❌ Link Preview card (Phase 3.7)
❌ Edit button (Phase 3.6/3.7)
```

**Missing (Per Rebrandly Design):**
- ❌ **Link Preview Section**
  - OG image display
  - OG title
  - OG description
  - Edit preview button
  - "Refresh Preview" action
- ❌ **Edit URL Modal/Panel**
  - Edit title
  - Edit destination URL
  - Toggle forward_parameters
  - Edit OG metadata
- ❌ **URL Metadata Display**
  - Title prominently shown
  - Last click: "X hours ago"
  - Forward params: ON/OFF badge

**User Actions Available:**
- Copy URL
- Delete URL
- View analytics

**User Actions Missing:**
- ❌ Edit URL
- ❌ Refresh OG preview
- ❌ View/edit link preview

---

## 5. Campaign Management Screens

### 5.1 Campaigns List (`/dashboard/campaigns`)
**File:** `frontend/src/pages/dashboard/campaigns/index.astro`

**Current State:** ✅ Complete

**Components:**
- Header with "New Campaign" button
- Campaign cards (CampaignCard component)
  - Name
  - Original URL
  - URL count
  - Total clicks
  - Created date
  - View Details button
  - Delete button
- Empty state
- Loading state

**User Actions:**
- Create new campaign
- View campaign details
- Delete campaign

### 5.2 Create Campaign (`/dashboard/campaigns/create`)
**Current State:** ✅ Complete

**Steps:**
1. Campaign name
2. Destination URL
3. CSV upload (with user data)
4. Validation & preview
5. Success confirmation

**Features:**
- CSV parsing
- Column detection
- Preview before creation
- Error handling

### 5.3 Campaign Details (`/dashboard/campaigns/[id]`)
**File:** `frontend/src/pages/dashboard/campaigns/[id].astro`

**Current State:** ✅ Complete (includes Phase 3.6/3.7 analytics)

**Sections:**
1. **Header**
   - Campaign name
   - Destination URL
   - Export CSV button
   - Delete button

2. **Stats Cards**
   - Total URLs
   - CSV Columns count
   - Created date

3. **Analytics (Phase 3.6/3.7)**
   - Total clicks
   - Unique visitors
   - CTR
   - Avg clicks/URL

4. **Charts (Phase 3.6/3.7)**
   - Click Timeline (7 days)
   - Top Performers

5. **CSV Columns Display**

6. **URLs Table**
   - Short URL
   - User data columns (dynamic)
   - Click count
   - Copy buttons

**User Actions:**
- Export campaign data
- Delete campaign
- Copy individual URLs
- View URL analytics

---

## 6. Analytics Screens

### 6.1 Overview Analytics (`/dashboard/analytics`)
**File:** `frontend/src/pages/dashboard/analytics.astro`

**Current State:** ✅ Complete

**Sections:**
1. **Summary Stats (4 cards)**
   - Total URLs
   - Total Campaigns
   - Total Clicks
   - Unique Visitors

2. **Top Performing URLs**
   - Short URL
   - Original URL
   - Click count
   - CTR

3. **Recent Activity Timeline**

4. **Geographic Overview**

**User Actions:**
- View overall performance
- Click through to URL details

---

## 7. Settings Screens

### 7.1 Account Settings (`/dashboard/settings`)
**File:** `frontend/src/pages/dashboard/settings.astro`

**Current State:** ✅ Basic implementation

**Sections:**
1. **Profile Information**
   - Email (read-only)
   - Account created date (read-only)

2. **Change Password**
   - Current password
   - New password
   - Confirm password

3. **Danger Zone**
   - Delete account option

**User Actions:**
- Change password
- Delete account

---

## 8. Reusable Components

### 8.1 Navbar
**File:** `frontend/src/components/Navbar.astro`

**Variants:**
- Public (with auth buttons)
- Authenticated (with user email, logout)

**Navigation Items:**
- Dashboard
- Campaigns
- Analytics
- Settings

### 8.2 URLCard
**File:** `frontend/src/components/URLCard.astro`

**Current Display:**
```
┌─────────────────────────────────┐
│ Short URL                       │
│ http://localhost:8000/abc123    │
│ [Copy]                          │
│                                 │
│ Original URL                    │
│ https://example.com/long/url    │
│                                 │
│ 👁 X clicks  🏷 standard  📅 Date│
│ [View Details] [Delete]         │
└─────────────────────────────────┘
```

**Missing (Phase 3.6):**
```
┌─────────────────────────────────┐
│ Title/Name: My Marketing Link   │ ← MISSING
│ http://localhost:8000/abc123    │
│                                 │
│ → https://example.com/page      │
│                                 │
│ 👁 X clicks  ⏰ 2h ago  ⚡️ Fwd ON│ ← MISSING
│ [Edit] [Analytics] [Delete]     │ ← Edit MISSING
└─────────────────────────────────┘
```

### 8.3 CampaignCard
**File:** `frontend/src/components/CampaignCard.astro`

**Current Display:**
- Campaign name
- Destination URL
- URL count
- Total clicks
- Created date
- View/Delete actions

### 8.4 ProtectedRoute
**File:** `frontend/src/components/ProtectedRoute.astro`

**Function:** JWT authentication check, redirect to login if not authenticated

---

## 9. User Flows

### 9.1 Standard URL Creation Flow
```
Dashboard → Create URL →
  ├─ Enter URL
  ├─ [Optional] Add title
  ├─ [Optional] Toggle forward params
  ├─ [Optional] Expand OG fields
  │   ├─ Add OG title
  │   ├─ Add OG description
  │   └─ Add OG image URL
  └─ Submit → Success →
      ├─ Copy URL
      ├─ Create Another
      └─ Back to Dashboard
```

### 9.2 Custom URL Creation Flow
```
Dashboard → Create URL → Switch to Custom →
  ├─ Enter URL
  ├─ Enter custom code
  ├─ [Optional] Add title
  ├─ [Optional] Toggle forward params
  ├─ [Optional] Add OG fields
  └─ Submit → Success/Warning
```

### 9.3 URL Management Flow (INCOMPLETE)
```
Dashboard → URL Card → View Details →
  ✅ View analytics
  ✅ Copy URL
  ✅ Delete URL
  ❌ Edit URL (MISSING)
  ❌ View preview card (MISSING)
  ❌ Refresh OG data (MISSING)
```

### 9.4 Campaign Flow
```
Dashboard → Campaigns → Create →
  ├─ Enter name & URL
  ├─ Upload CSV
  ├─ Review columns
  └─ Create → Campaign Details →
      ├─ View analytics
      ├─ Export CSV
      ├─ Copy URLs
      └─ Delete campaign
```

### 9.5 Social Media Sharing Flow (Backend Only)
```
User shares short URL on Twitter/Facebook/LinkedIn →
  ├─ Crawler requests URL
  ├─ Backend detects crawler User-Agent
  ├─ Serves HTML preview page with OG tags
  └─ Platform displays rich preview card

Regular user clicks URL →
  ├─ Backend detects browser User-Agent
  ├─ 302 redirect to destination
  └─ [Optional] Append query params if forward_parameters=true
```

---

## 10. Phase 3.6/3.7 Feature Gaps

### Backend: ✅ 100% Complete
- All endpoints functional
- 26 tests passing
- Phase 3.6: title, forward_parameters, last_click_at, PATCH endpoint
- Phase 3.7: OG metadata, preview endpoints, crawler detection

### Frontend Gaps by Screen:

#### Dashboard (`/dashboard`)
**Missing:**
- [ ] Display `title` prominently on URL cards
- [ ] Show `last_click_at` timestamp ("2 hours ago")
- [ ] Display `forward_parameters` status badge (ON/OFF)
- [ ] "Edit" button on URL cards

#### URL Details (`/dashboard/urls/[short_code]`)
**Missing:**
- [ ] Title display in header
- [ ] Last click timestamp
- [ ] Forward parameters ON/OFF badge
- [ ] **Link Preview Card Section:**
  - [ ] OG image display (1200x630)
  - [ ] OG title
  - [ ] OG description
  - [ ] Edit preview button
  - [ ] Auto-fetch timestamp display
- [ ] **Edit URL Modal/Panel:**
  - [ ] Edit title
  - [ ] Edit destination URL
  - [ ] Toggle forward_parameters
  - [ ] Edit OG title/description/image
  - [ ] "Refresh Preview" button (re-fetch OG)
  - [ ] Save/Cancel actions

#### Create URL (`/dashboard/create`)
**Implemented but Could Enhance:**
- [x] Title field
- [x] Forward params toggle
- [x] OG fields (collapsible)
- [ ] Live preview card (like Rebrandly)
- [ ] Visual preview of OG metadata as you type

---

## 11. Design System Needs

### Current Colors (Inconsistent)
- **Primary Blue:** blue-600 (#2563EB)
- **Gradients:** blue-50 to indigo-100
- **Success:** green-600
- **Error:** red-600
- **Warning:** yellow-600
- **Purple (campaigns):** purple-600
- **Orange:** orange-600

### Typography
- **Headings:** font-bold
  - H1: text-3xl to text-6xl
  - H2: text-2xl
  - H3: text-lg
- **Body:** text-sm to text-base
- **Labels:** text-xs uppercase tracking-wide

### Spacing
- Cards: p-6, p-8
- Gaps: gap-4, gap-6
- Margins: mb-6, mb-8

### Components Needing Design
1. **Link Preview Card** (new, Phase 3.7)
2. **Edit URL Modal** (new, Phase 3.6)
3. **URL Card Enhancement** (Phase 3.6)
4. **Badges** (forward params, url type, etc.)
5. **Empty States**
6. **Loading States**
7. **Success/Error States**

### Icons Currently Used
- **Heroicons** (inline SVG)
- Mix of outline and filled
- Sizes: w-4, w-5, w-6, w-8, w-12

---

## 12. Screen States Inventory

### Loading States
- **Full page:** Spinner + text
- **Inline:** Spinner only
- **Skeleton:** Not used (could implement)

### Empty States
- **No URLs:** Icon + message + CTA
- **No Campaigns:** Icon + message + CTA
- **No Analytics:** Text only

### Error States
- **Form errors:** Inline red text
- **API errors:** Red banner with message
- **404:** Custom error page (not inventoried)

### Success States
- **URL Created:** Green card with URL + copy button
- **Toast:** Not implemented (could add)

---

## 13. Interaction Patterns

### Buttons
- **Primary:** bg-blue-600 hover:bg-blue-700
- **Secondary:** border-gray-300 hover:bg-gray-50
- **Danger:** border-red-300 text-red-700 hover:bg-red-50

### Forms
- **Input:** border-gray-300 focus:ring-blue-500
- **Checkbox:** Custom styled
- **Toggle:** Not used (needed for forward_parameters)

### Cards
- **Shadow:** shadow-md hover:shadow-lg
- **Border:** border-gray-200
- **Hover:** transition-shadow

### Modals
- **Delete confirmation:** Overlay + centered card
- **Edit (missing):** Needs design

---

## 14. Responsive Breakpoints

### Used Throughout
- **sm:** 640px
- **md:** 768px
- **lg:** 1024px

### Grid Patterns
- 1 col mobile → 2-3 cols tablet → 3-4 cols desktop
- Dashboard uses max-w-7xl container

---

## 15. Priority for Redesign

### Critical (Core User Flow)
1. **Dashboard URL List** - Primary screen, needs title display
2. **URL Details Page** - Missing link preview card entirely
3. **Create URL Form** - Works but could use live preview
4. **Edit URL Modal** - Completely missing

### Important (User Delight)
5. **Link Preview Card Component** - New, needs design
6. **Badges & Status Indicators** - Forward params, last click
7. **Empty/Loading States** - Improve consistency

### Nice to Have
8. **Landing Page** - Rebrand
9. **Settings Page** - Basic functionality exists
10. **Toast Notifications** - Not implemented

---

## 16. Technical Notes for Designer

### Frontend Stack
- **Framework:** Astro (mostly static)
- **Styling:** Tailwind CSS
- **Icons:** Heroicons (inline SVG)
- **State:** Client-side JS (no React/Vue)
- **API:** REST endpoints (documented in ROADMAP.md)

### Backend API Fields Available
```typescript
interface URL {
  short_code: string
  original_url: string
  url_type: 'standard' | 'custom' | 'campaign'

  // Phase 3.6
  title?: string
  forward_parameters: boolean
  last_click_at?: string
  updated_at: string

  // Phase 3.7
  og_title?: string
  og_description?: string
  og_image_url?: string
  og_fetched_at?: string

  // Analytics
  click_count: number
  created_at: string
  created_by: string
}
```

### PATCH Endpoint Available
- Update title, destination, forward_parameters, OG fields
- Returns updated URL object

### Preview Endpoints
- GET `/api/urls/{code}/preview` - Get OG metadata
- POST `/api/urls/{code}/refresh-preview` - Re-fetch OG data

---

## 17. Questions for UX Brief

### Brand Identity
1. What visual style for Shurly? (Modern SaaS, Playful, Enterprise, Minimalist)
2. Primary brand colors?
3. Logo/wordmark design?
4. Tone: Professional, Friendly, Technical?

### Key Design Decisions Needed
1. **Link Preview Card:** Where should it appear? (Details page, modal, both?)
2. **Edit URL:** Modal overlay or inline panel?
3. **Live Preview:** Show in create form or only after creation?
4. **Forward Params Toggle:** Switch component or checkbox?
5. **Last Click:** Relative time or timestamp format?
6. **Title Display:** How prominent on cards? Above URL or below?

### User Experience
1. Should OG fields auto-fetch preview as user types URL?
2. Show skeleton loading or spinner?
3. Toast notifications for actions or inline messages?
4. Confirm before delete or undo action?

### Mobile Experience
1. Mobile-first design or desktop priority?
2. Hamburger menu or bottom nav?
3. Cards stack or scroll horizontally?

---

## Appendix A: File Reference

```
frontend/src/
├── pages/
│   ├── index.astro                      # Landing
│   ├── login.astro                      # Login
│   ├── register.astro                   # Register
│   └── dashboard/
│       ├── index.astro                  # URL List
│       ├── create.astro                 # Create URL ✅ Phase 3.6/3.7
│       ├── analytics.astro              # Overview Analytics
│       ├── settings.astro               # Account Settings
│       ├── urls/
│       │   └── [short_code].astro       # URL Details ❌ Missing UI
│       └── campaigns/
│           ├── index.astro              # Campaign List
│           ├── create.astro             # Create Campaign
│           └── [id].astro               # Campaign Details ✅ Has analytics
├── components/
│   ├── Navbar.astro                     # Navigation
│   ├── URLCard.astro                    # URL List Item ❌ Missing fields
│   ├── CampaignCard.astro               # Campaign List Item
│   └── ProtectedRoute.astro             # Auth Guard
└── layouts/
    └── Layout.astro                     # Base layout
```

---

**End of Inventory**
