# Claude Onboarding Guide

Welcome to **Shurly**, a modern B2B URL shortener with campaign management,
analytics, and Shlink-inspired hardening (multi-domain, redirect rules, GDPR).

## Philosophy & Development Approach

This project follows a **pragmatic, TDD-driven** development philosophy:

- **Test-Driven Development**: Write tests first, then implement features. **All 285 tests must pass.**
- **Incremental Progress**: Complete features end-to-end before moving to the next.
- **Clear Documentation**: Code is the truth, docs explain the why.
- **Production-Ready**: Every commit should maintain a working application.
- **User-Centric**: Focus on solving real B2B marketing use cases.

## Quick Start - What to Read First

### 1. **Project Overview** (5 min)
Read [README.md](README.md) to understand:
- Tech stack (FastAPI + Astro 6 + PostgreSQL)
- Project structure
- API endpoints (versioned under `/api/v1/`)
- How to run locally

### 2. **Development Roadmap** (10 min)
Review [_pm/ROADMAP.md](_pm/ROADMAP.md) for:
- **Current Status**: Phase 3 + 3.8 + 3.9 + 3.10 complete (285 tests passing)
- Use cases (standard URLs, custom URLs, campaigns, multi-domain)
- Phase 1–3.10 completion status (✅)
- Phase 4–6 next steps (AWS Lambda + RDS, deployment hardening, docs)

### 3. **Testing Guide** (as needed)
Check [docs/TESTING.md](docs/TESTING.md) when you need to:
- Set up the local environment
- Test specific features
- Verify functionality works

### 4. **Changelog**
Read [CHANGELOG.md](CHANGELOG.md) — Keep-a-Changelog formatted, lists every
behavior change since the v0.1 baseline including the API versioning policy.

## Project Architecture at a Glance

```
Backend (FastAPI)               Frontend (Astro 6 + Tailwind 4)
├── /api/v1/auth/*              ├── /login, /register
├── /api/v1/urls/*              ├── /dashboard (URL management)
│   └── /rules                  ├── /dashboard/campaigns/*
├── /api/v1/campaigns/*         └── /dashboard/analytics
├── /api/v1/tags/*
├── /api/v1/analytics/*
│   └── /orphan-visits
└── (unversioned, public)
    /{code}        — redirect (302; rules eval first)
    /{code}/track  — email tracking pixel (1×1 GIF)
    /robots.txt    — default-deny short URLs
```

**Database (PostgreSQL)**: 8 models
- `User` (with `api_key_scope` enum + `api_key_constraints`)
- `Domain` (single-domain at launch; UNIQUE `(domain_id, short_code)` on URLs)
- `URL` (standard / custom / campaign + crawlable + validity window + visit cap)
- `Visitor` (with `is_bot`, `is_pixel` flags)
- `Campaign` (CSV-driven personalized URLs)
- `Tag` + `url_tags` association
- `RedirectRule` (priority + JSONB conditions)
- `OrphanVisit` (typo'd / unknown short codes)

**Key features**:
- URL shortening (standard 6-char, custom slugs, campaign bulk)
- Validity windows + max-visits caps (404/410 semantics)
- Dynamic redirect rules (device/lang/qparam/date/browser, AND-of-conditions, priority-ordered)
- Email tracking pixel
- Multi-domain foundation (model-only at launch)
- Analytics with bot + pixel filtering by default
- Orphan visit tracking
- CSV export from analytics
- GDPR IP anonymization at log time
- JWT authentication + API keys with scope enum
- X-Request-Id correlation middleware

## Development Workflow

### When Making Changes

1. **Understand the context**: Check related code and tests first.
2. **Write tests**: Add/update tests before implementing (TDD).
3. **Implement**: Make changes to pass the tests.
4. **Verify**: Run `uv run pytest` — all 285 tests must pass.
5. **Lint**: `uv run ruff check server tests main.py` (focus on the files you touched).
6. **Commit**: Use clear, descriptive commit messages following the existing pattern (`feat: Phase X.Y.Z — …`).

### Code Conventions

- **Backend** (`server/`):
  - Models: `server/core/models/<domain>.py` — register in `__init__.py`
  - Endpoints: `server/app/<domain>.py`
  - Schemas: `server/schemas/<domain>.py`
  - Utilities: `server/utils/<topic>.py`
  - Tests: `tests/test_<topic>.py` or `tests/test_phase<N>_<topic>.py`
  - Format: `uv run ruff format .`

- **Frontend** (`frontend/`):
  - Pages: `frontend/src/pages/`
  - Components: `frontend/src/components/`
  - Utils: `frontend/src/utils/`
  - Run dev: `npm run dev` on **port 4232**
  - Tailwind 4 CSS-first config in `src/styles/global.css`
  - Three dashboard dynamic routes use `prerender = false` (require `@astrojs/node`)

- **Testing**:
  - In-memory SQLite for isolation (`tests/conftest.py`)
  - `test_user` fixture creates a user with a freshly hashed password
  - Use `auth_headers` fixture for authenticated requests
  - For network-touching tests (OG fetcher), monkey-patch `fetch_opengraph_metadata`
  - When seeding URLs directly via ORM, set `domain_id=get_or_create_default_domain(db).id` so per-domain UNIQUE checks behave

### Key Files to Know

- `main.py` — FastAPI app, CORS, `RequestIdMiddleware`, startup seeders (default domain + predefined tags)
- `server/core/config.py` — All settings (CORS, GDPR, redirect, multi-domain, SHORT_URL_MODE, …)
- `server/core/models/` — SQLAlchemy models (8 files; register new ones in `__init__.py`)
- `server/app/urls.py` — URL CRUD, redirect resolver, robots.txt, tracking pixel, redirect-rule CRUD
- `server/app/analytics.py` — All analytics endpoints + `_exclude_bots` helper
- `server/utils/redirect_rules.py` — Conditional redirect evaluator
- `server/utils/network.py` — IP anonymization + trusted-proxy resolution
- `frontend/src/utils/api.ts` — API client with auth + JSON-array CORS-friendly fetch
- `docker-compose.yml` — Local dev environment

## Common Tasks

### Adding a New API Endpoint
1. Add a test in `tests/test_*.py`
2. Create the endpoint in `server/app/*.py`
3. Update schemas in `server/schemas/*.py` if needed
4. Run tests: `uv run pytest`

### Adding a New Model
1. Create `server/core/models/<name>.py` with the SQLAlchemy class
2. Register it in `server/core/models/__init__.py` (add to imports + `__all__`)
3. If it relates to URL/Visitor, add the relationship + `back_populates` on both sides
4. Add a unit test that round-trips through `db_session`

### Adding a Frontend Page
1. Create the page in `frontend/src/pages/*.astro`
2. If it's a dynamic route (`[id].astro`) and renders client-side, add `export const prerender = false;`
3. Use `apiGet/apiPost` from `@/utils/api` for backend calls
4. Add to navigation in `Navbar.astro` if needed

### Running Tests
```bash
# All tests (should show 285 passed)
uv run pytest

# With coverage
uv run pytest --cov=server --cov-report=html

# Specific test file
uv run pytest tests/test_phase3102_redirect_rules.py
```

### Local Development
```bash
# Backend (port 8000)
uv run uvicorn main:app --reload

# Frontend (port 4232)
cd frontend && npm run dev

# Or use Docker
docker compose up -d
```

## Important Notes

### Phase Status
- ✅ **Phase 1–3**: Backend + Frontend + Analytics + Tags
- ✅ **Phase 3.9**: API versioning, validity window, bot detection, robots.txt, GDPR, X-Request-Id, SHORT_URL_MODE, TRUSTED_PROXIES, OG charset, API key scope
- ✅ **Phase 3.10**: Multi-domain, redirect rules, tracking pixel, orphan visits, CSV export, configurable redirect
- ⏳ **Phase 4**: AWS Lambda + RDS deployment (next)

### Defaults Worth Knowing
- `SHORT_URL_MODE=loose` → all generated codes and custom slugs are lowercased
- `ANONYMIZE_REMOTE_ADDR=true` → IPv4 truncated to /24, IPv6 to /64
- `TRUSTED_PROXIES=[]` → **never trust** `X-Forwarded-For` until configured
- `DISABLE_TRACK_PARAM=nostat` → `?nostat` skips visit logging but still redirects
- `REDIRECT_STATUS_CODE=302` → `Cache-Control: private, max-age=0`
- `DEFAULT_DOMAIN=shurl.griddo.io` → seeded at startup; legacy NULL `domain_id` URLs are matched as a fallback

### Git Workflow
- **PRs target `dev`**; `main` is the release branch
- Phase 3.9 PR: stacked feature branches → `dev` (`feat/phase-3.9.3-3.9.6-shlink-hardening`)
- Phase 3.10 PR: stacked on the 3.9 branch (`feat/phase-3.10-shlink-medium`)
- Always `git pull origin dev` before starting new work
- Commit messages follow `feat: Phase X.Y.Z — short description` style

### Testing Status
- ✅ **285 backend tests passing**
- ✅ Frontend builds clean (`npm run build`); `npm audit` 0 vulnerabilities
- ⏳ Manual smoke testing for production deploy (Phase 4)

## Philosophy Summary

> "Build it right, test it thoroughly, document it clearly, ship it confidently."

- Prefer **existing solutions** over new ones
- Write **tests first** to define behavior
- Keep **documentation in sync** with code
- Value **working software** over perfect code
- Trust the **test suite** as the source of truth

---

## Quick Reference

| Need | Command |
|------|---------|
| Start backend | `uv run uvicorn main:app --reload` |
| Start frontend | `cd frontend && npm run dev` |
| Run all tests | `uv run pytest` |
| Format code | `uv run ruff format .` |
| Check lint | `uv run ruff check server tests main.py` |
| View API docs | http://localhost:8000/docs |
| View frontend | http://localhost:4232 |
| robots.txt | http://localhost:8000/robots.txt |
| Tracking pixel | http://localhost:8000/{code}/track |

**Questions?** Check the inline code comments, test files, `CHANGELOG.md`, or ask the user for context.
