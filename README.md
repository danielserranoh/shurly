# Shurly - Modern URL Shortener

A modern, full-stack URL shortener with analytics and campaign management, built with FastAPI and Astro.

## Features

- **URL Shortening**: Auto-generated 6-char codes, custom slugs, or campaign bulk
- **Validity windows & visit caps**: `valid_since`, `valid_until`, `max_visits` per URL
- **Dynamic redirect rules**: device / language / query-param / date / browser conditions, priority-ordered
- **Multi-domain ready**: same code can live on multiple hosts (`(domain_id, short_code)` UNIQUE)
- **Email tracking pixel**: `GET /{code}/track` — 1×1 GIF logged with `is_pixel=true`
- **Analytics**: daily/weekly/geo stats, top performers, campaign timelines — bots filtered by default
- **GDPR by default**: visitor IPs truncated to /24 (IPv4) or /64 (IPv6) at insert time
- **CSV export**: `?format=csv` on most analytics endpoints (streamed)
- **Orphan visit tracking**: catches typo'd codes leaked into print/QR campaigns
- **Open Graph previews**: social-media crawlers see rich preview pages with og:tags
- **Versioned API**: stable contract under `/api/v1/`; root path serves redirects

## Tech Stack

### Backend
- **FastAPI** — async web framework with OpenAPI/Swagger out of the box
- **Pydantic v2** — schema validation
- **SQLAlchemy 2.0 + PostgreSQL** — `psycopg2-binary` driver
- **python-jose** + **passlib (bcrypt<5)** — JWT + password hashing
- **uv** + **ruff** + **pytest** — packaging, linting, testing (285 tests)

### Frontend
- **Astro 6** with the **`@astrojs/node`** adapter (three dashboard routes are SSR)
- **Tailwind CSS 4** via **`@tailwindcss/vite`** (CSS-first config in `src/styles/global.css`)
- **TypeScript** + **Vite 7**

## Prerequisites

- Python 3.10 or higher
- Node.js 20.19+ or 22.12+ (Astro 6 requirement)
- PostgreSQL database (14 or higher recommended)
- [uv](https://github.com/astral-sh/uv) (Python package installer)

## Getting Started

### Quick Start with Docker (Recommended)

The fastest way to test Shurly locally:

```bash
# Start the entire stack (PostgreSQL + FastAPI)
docker compose up -d

# View logs
docker compose logs -f api

# Stop when done
docker compose down
```

- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Frontend**: Start separately (see Frontend Setup below)

For comprehensive testing instructions, see **[TESTING.md](TESTING.md)**.

### Manual Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd shurly
```

### 2. Database Setup

Create a PostgreSQL database:

```bash
psql -U postgres
CREATE DATABASE shurly;
\q
```

### 3. Backend Setup

#### Install Dependencies

```bash
uv sync
```

This will create a virtual environment and install all Python dependencies.

#### Configure Environment

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Edit `.env` with your database credentials and JWT secret:

```env
# Database Configuration (PostgreSQL)
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password_here
DB_NAME=shurly

# JWT Configuration
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=10080

# API Configuration
API_TITLE=Shurly API
API_VERSION=0.1.0
API_DESCRIPTION=A modern URL shortener API

# CORS Configuration (JSON array string or single origin)
CORS_ORIGINS=["http://localhost:4232","http://localhost:3000"]

# Phase 3.9 / 3.10 settings (all optional, sensible defaults shown)
ANONYMIZE_REMOTE_ADDR=true                 # Truncate IPv4→/24, IPv6→/64
TRUSTED_PROXIES=[]                         # CIDR allowlist for X-Forwarded-For
DISABLE_TRACK_PARAM=nostat                 # Query string that suppresses logging
SHORT_URL_MODE=loose                       # "loose" lowercases codes/slugs
DEFAULT_DOMAIN=shurl.griddo.io             # Seeded at startup
REDIRECT_STATUS_CODE=302                   # 301 / 302 / 307 / 308
REDIRECT_CACHE_LIFETIME=0                  # Seconds; 0 = no-cache
```

#### Initialize the Database

The database tables will be created automatically when you start the application. SQLAlchemy will create all necessary tables based on the models.

#### Run the Backend

```bash
uv run uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

- API Documentation: `http://localhost:8000/docs`
- Alternative API Docs: `http://localhost:8000/redoc`

### 4. Frontend Setup

#### Install Dependencies

```bash
cd frontend
npm install
```

#### Run the Development Server

```bash
npm run dev
```

The frontend will be available at `http://localhost:4232`

## Development

### Backend Development

#### Format Code with Ruff

```bash
uv run ruff format .
```

#### Check for Linting Issues

```bash
uv run ruff check .
```

#### Auto-fix Linting Issues

```bash
uv run ruff check --fix .
```

#### Run Tests

```bash
uv run pytest
```

#### Run Tests with Coverage

```bash
uv run pytest --cov=server --cov-report=html
```

#### Run Specific Test Markers

```bash
# Unit tests only
uv run pytest -m unit

# Integration tests only
uv run pytest -m integration
```

### Frontend Development

#### Build for Production

```bash
cd frontend
npm run build
```

#### Preview Production Build

```bash
npm run preview
```

#### Type Check

```bash
npm run astro check
```

## Project Structure

```
shurly/
├── server/
│   ├── app/                       # FastAPI routers (one per domain)
│   │   ├── auth.py                # Register / login / API keys
│   │   ├── urls.py                # URL CRUD + redirect + /robots.txt + tracking pixel
│   │   ├── campaigns.py           # Campaign CRUD + CSV upload
│   │   ├── analytics.py           # Stats endpoints (daily / weekly / geo / overview / orphans)
│   │   ├── tags.py                # Tag CRUD + URL tagging
│   │   └── statistics.py          # Legacy (deprecated)
│   ├── core/
│   │   ├── auth.py                # JWT + bcrypt helpers (with 72-byte truncation shim)
│   │   ├── config.py              # Settings: CORS, GDPR, redirect, multi-domain, …
│   │   └── models/                # SQLAlchemy models
│   │       ├── user.py            # User + ApiKeyScope enum
│   │       ├── url.py             # URL (standard/custom/campaign) + composite UNIQUE
│   │       ├── visitor.py         # Visitor (with is_bot, is_pixel)
│   │       ├── campaign.py        # Campaign with CSV column metadata
│   │       ├── domain.py          # Phase 3.10.1 multi-domain
│   │       ├── redirect_rule.py   # Phase 3.10.2 conditional redirects
│   │       ├── orphan_visit.py    # Phase 3.10.4 typo'd / unknown codes
│   │       └── tag.py             # Tag + URL_tags association
│   ├── schemas/                   # Pydantic request/response schemas
│   ├── templates/preview.html     # OG preview page for social crawlers
│   └── utils/
│       ├── url.py                 # Code generation, slug normalization, URL validation
│       ├── user_agent.py          # Browser/OS/device + bot classification
│       ├── opengraph.py           # OG fetcher with charset fallback
│       ├── network.py             # IP anonymization + trusted-proxy resolution
│       ├── domain.py              # Default-domain seeding + Host header → Domain
│       ├── redirect_rules.py      # Conditional redirect evaluator
│       ├── csv_export.py          # Streaming CSV writer
│       └── tags.py                # Predefined tag seeding
├── frontend/                      # Astro 6 + Tailwind 4
│   ├── src/
│   │   ├── styles/global.css      # @import "tailwindcss"
│   │   ├── layouts/Layout.astro
│   │   ├── pages/
│   │   │   ├── index.astro
│   │   │   ├── login.astro
│   │   │   ├── register.astro
│   │   │   └── dashboard/
│   │   │       ├── index.astro            # Dashboard home (static)
│   │   │       ├── analytics.astro        # Analytics view
│   │   │       ├── create.astro           # Create URL
│   │   │       ├── settings.astro
│   │   │       ├── campaigns/
│   │   │       │   ├── index.astro
│   │   │       │   ├── create.astro
│   │   │       │   └── [id].astro         # SSR (prerender = false)
│   │   │       └── urls/
│   │   │           └── [short_code].astro # SSR (prerender = false)
│   │   ├── components/
│   │   └── utils/                 # api.ts, auth.ts, types.ts
│   └── astro.config.mjs           # Includes @astrojs/node adapter
├── tests/                         # 285 passing
│   ├── conftest.py                # In-memory SQLite fixtures
│   ├── test_auth.py / _urls.py / _campaigns.py / _analytics.py / _tags.py
│   ├── test_user_agent.py / _utils.py / _network.py
│   ├── test_phase396_free_wins.py     # X-Request-Id / SHORT_URL_MODE / OG charset / API key scope
│   ├── test_phase310_multidomain.py   # Phase 3.10.1
│   ├── test_phase3102_redirect_rules.py
│   ├── test_phase3103_pixel.py
│   ├── test_phase3104_orphan_visits.py
│   ├── test_phase3105_csv.py
│   └── test_phase3106_redirect_config.py
├── main.py                        # FastAPI app + RequestIdMiddleware + startup seeding
├── pyproject.toml
├── docker-compose.yml / dockerfile
└── README.md / CHANGELOG.md / DEPLOYMENT.md / CLAUDE.md
```

## API Endpoints

The HTTP API is versioned under `/api/v1/`. The redirect path (`/{short_code}`),
`/{short_code}/track` and `/robots.txt` are deliberately unversioned — they're
public-facing and must remain stable. See [CHANGELOG.md](CHANGELOG.md) for the
full versioning policy.

### Authentication
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/change-password`
- `POST /api/v1/auth/api-key/generate` — returns `{api_key, scope}` (Phase 3.9.6)
- `DELETE /api/v1/auth/api-key`

### URL Shortening
- `POST /api/v1/urls` — auto-generated 6-char code
- `POST /api/v1/urls/custom` — user-supplied slug
- `GET /api/v1/urls` — list (supports `tags=`, `tag_filter=any|all`, pagination)
- `PATCH /api/v1/urls/{short_code}`
- `DELETE /api/v1/urls/{short_code}`
- `GET /api/v1/urls/{short_code}/preview` — OG metadata
- `POST /api/v1/urls/{short_code}/refresh-preview`
- `PATCH /api/v1/urls/{short_code}/tags`
- `POST /api/v1/urls/bulk/tags`

### Redirect Rules (Phase 3.10.2)
- `GET /api/v1/urls/{short_code}/rules`
- `POST /api/v1/urls/{short_code}/rules` — `{priority, conditions, target_url}`
- `PATCH /api/v1/urls/{short_code}/rules/{rule_id}`
- `DELETE /api/v1/urls/{short_code}/rules/{rule_id}`

### Campaigns
- `POST /api/v1/campaigns`
- `GET /api/v1/campaigns`
- `GET /api/v1/campaigns/{campaign_id}`
- `GET /api/v1/campaigns/{campaign_id}/export` — CSV of generated URLs
- `POST /api/v1/campaigns/{campaign_id}/upload` — CSV → personalized URLs
- `DELETE /api/v1/campaigns/{campaign_id}` — cascades

### Tags
- `GET /api/v1/tags` — predefined + user-created
- `POST /api/v1/tags`
- `PATCH /api/v1/tags/{id}`
- `DELETE /api/v1/tags/{id}`

### Analytics
All analytics endpoints exclude bot and pixel hits by default. Pass
`?include_bots=true` to count bot visits; pass `?format=csv` for a streamed CSV.

- `GET /api/v1/analytics/overview` — totals + 7-day timeline + top URLs
- `GET /api/v1/analytics/urls/{short_code}/daily` — last 7 days
- `GET /api/v1/analytics/urls/{short_code}/weekly` — last 8 weeks
- `GET /api/v1/analytics/urls/{short_code}/geo` — by country
- `GET /api/v1/analytics/campaigns/{campaign_id}/summary` — totals + top performers
- `GET /api/v1/analytics/campaigns/{campaign_id}/users` — per-URL stats (CSV-friendly)
- `GET /api/v1/analytics/orphan-visits` — typo'd / unknown codes (Phase 3.10.4)

### Public / unversioned
- `GET /{short_code}` — Redirect (302 by default; honors validity window, max-visits, redirect rules)
- `GET /{short_code}/track` — Email tracking pixel (43-byte transparent GIF, `Cache-Control: no-store`)
- `GET /robots.txt` — Default-deny short URLs; `Allow: /<code>` per `crawlable=true` URL

## URL Types

Shurly supports three types of URLs:

1. **Standard**: Auto-generated 6-character short codes
2. **Custom**: User-defined short codes (3-20 alphanumeric characters and hyphens)
3. **Campaign**: Generated from CSV imports with personalized user data

Each URL can also carry: validity window (`valid_since`/`valid_until`), visit cap
(`max_visits`), crawlability flag (`crawlable`), Open Graph metadata, tags, and
zero or more priority-ordered redirect rules.

## Testing

### Automated Tests

The project includes a comprehensive test suite with **285 passing tests**:

- **Unit tests**: UA parsing, IP anonymization, redirect-rule evaluator, OG charset decoding
- **Integration tests**: API contracts, redirect path, multi-domain, bot filtering, CSV export, orphan visits, redirect rules, tracking pixel

Run the full test suite:
```bash
uv run pytest
```

Tests use an in-memory SQLite database for fast execution and isolation.

### Manual Testing

For comprehensive functional and UX testing before deployment, see the complete testing guide:

📋 **[TESTING.md](TESTING.md)** - Step-by-step instructions for:
- Local setup (Docker or manual)
- Functional testing checklist (all features)
- UX testing scenarios (user journeys)
- API testing with Swagger UI
- Edge cases and error handling
- Performance testing

The testing guide includes sample data, test templates, and success criteria to ensure the application is production-ready.

## Docker Support

Build and run with Docker:

```bash
docker build -t shurly .
docker run -p 8000:8000 shurly
```

Note: Update the Docker configuration with environment variables for production deployment.

## Security & Privacy

- **Password hashing**: bcrypt (4.x; 72-byte input shim for forward-compat with bcrypt 5)
- **JWT tokens**: HS256, 7-day default lifetime, configurable
- **CORS protection**: configurable allowed origins (JSON array string)
- **SQL injection**: SQLAlchemy ORM, parameterized queries throughout
- **Authorization**: user-scoped resources for URLs / campaigns / tags
- **GDPR by default**: visitor IPs anonymized at insert (`/24` IPv4, `/64` IPv6); toggle with `ANONYMIZE_REMOTE_ADDR`
- **Trusted-proxy allowlist**: `X-Forwarded-For` is **never** trusted unless the request source is in `TRUSTED_PROXIES` (CIDRs)
- **Default-deny crawlability**: short URLs are excluded from `/robots.txt` unless explicitly marked `crawlable=true`
- **Bot-aware analytics**: visits classified at log time; bots excluded from click counts
- **X-Request-Id correlation**: every response carries a request id (echoed if supplied) for log tracing

## Production Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full AWS Lambda + RDS guide. Pre-flight
checklist:

1. Set a strong `JWT_SECRET_KEY` (`openssl rand -hex 32`)
2. Configure CORS origins as a JSON array string
3. **Configure `TRUSTED_PROXIES`** with your ALB / CloudFront / API Gateway source CIDRs — without it, `X-Forwarded-For` is ignored and visit IPs will be the proxy's
4. Confirm `ANONYMIZE_REMOTE_ADDR=true` matches your privacy policy (default ON)
5. Pick `REDIRECT_STATUS_CODE` (302 = analytics-friendly; 301 = SEO-friendly but cached)
6. Pick `REDIRECT_CACHE_LIFETIME` (0 = every hit reaches backend; >0 = `Cache-Control: public, max-age=N`)
7. Set `DEFAULT_DOMAIN` to your real short-link host
8. Set up PostgreSQL with restricted user permissions
9. Configure HTTPS/TLS at the edge
10. Configure log aggregation (CloudWatch picks up the `X-Request-Id` header automatically)
11. Set up automated database backups

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests to ensure everything passes (`uv run pytest`)
4. Format your code (`uv run ruff format .`)
5. Commit your changes (`git commit -m 'Add some amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## License

MIT
