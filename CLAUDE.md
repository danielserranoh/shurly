# Claude Onboarding Guide

Welcome to **Shurly**, a modern B2B URL shortener with campaign management and analytics.

## Philosophy & Development Approach

This project follows a **pragmatic, TDD-driven** development philosophy:

- **Test-Driven Development**: Write tests first, then implement features. All 104 tests must pass.
- **Incremental Progress**: Complete features end-to-end before moving to the next
- **Clear Documentation**: Code is the truth, docs explain the why
- **Production-Ready**: Every commit should maintain a working application
- **User-Centric**: Focus on solving real B2B marketing use cases

## Quick Start - What to Read First

### 1. **Project Overview** (5 min)
Read [README.md](README.md) to understand:
- Tech stack (FastAPI + Astro + PostgreSQL)
- Project structure
- API endpoints
- How to run locally

### 2. **Development Roadmap** (10 min)
Review [ROADMAP.md](ROADMAP.md) for:
- **Current Status**: Phase 3 complete - all backend + frontend done, 104 tests passing
- Use cases (standard URLs, custom URLs, campaigns)
- Phase 1-3 completion status (✅)
- Phase 4-6 next steps (AWS deployment, testing, docs)

### 3. **Testing Guide** (as needed)
Check [TESTING.md](TESTING.md) when you need to:
- Set up the local environment
- Test specific features
- Verify functionality works

## Project Architecture at a Glance

```
Backend (FastAPI)          Frontend (Astro)
├── /api/v1/auth/*           ├── /login, /register
├── /api/v1/urls/*           ├── /dashboard (URL management)
├── /api/v1/campaigns/*      ├── /dashboard/campaigns/*
└── /api/v1/analytics/*      └── /dashboard/analytics
```

**Database**: PostgreSQL with 4 models (User, URL, Campaign, Visitor)

**Key Features**:
- URL shortening (standard 6-char, custom codes, or campaign bulk)
- Campaign system with CSV import → personalized query params
- Analytics (daily/weekly/geo stats, top performers)
- JWT authentication with protected routes

## Development Workflow

### When Making Changes

1. **Understand the context**: Check related code and tests first
2. **Write tests**: Add/update tests before implementing (TDD)
3. **Implement**: Make changes to pass the tests
4. **Verify**: Run `uv run pytest` - all 104 tests must pass
5. **Commit**: Use clear, descriptive commit messages

### Code Conventions

- **Backend**: Located in `server/` directory
  - Models: `server/core/models/`
  - Endpoints: `server/app/`
  - Tests: `tests/`
  - Format: `uv run ruff format .`

- **Frontend**: Located in `frontend/` directory
  - Pages: `frontend/src/pages/`
  - Components: `frontend/src/components/`
  - Utils: `frontend/src/utils/`
  - Build: `npm run dev` (port 4232)

- **Testing**:
  - Backend runs on port 8000
  - All tests use in-memory SQLite for isolation
  - Integration tests verify API contracts

### Key Files to Know

- `main.py` - FastAPI app entry point, CORS config
- `server/core/config.py` - Settings with JSON CORS parser
- `server/core/models/` - SQLAlchemy models (User, URL, Campaign, Visitor)
- `server/app/` - All API endpoints by domain
- `frontend/src/utils/api.ts` - API client with auth
- `docker-compose.yml` - Local dev environment

## Common Tasks

### Adding a New API Endpoint
1. Add test in `tests/test_*.py`
2. Create endpoint in `server/app/*.py`
3. Update schemas in `server/schemas/*.py` if needed
4. Run tests: `uv run pytest`

### Adding a Frontend Page
1. Create page in `frontend/src/pages/*.astro`
2. Use `apiGet/apiPost` from `@/utils/api` for backend calls
3. Add to navigation in `Navbar.astro` if needed

### Running Tests
```bash
# All tests (should show 104 passed)
uv run pytest

# With coverage
uv run pytest --cov=server --cov-report=html

# Specific test file
uv run pytest tests/test_campaigns.py
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

### Current Issues
- **CORS Config**: Frontend on port 4232 (not 4321). CORS uses JSON parser in `config.py:42-52`
- **Frontend Connection**: User reports network errors on registration - CORS issue likely needs container rebuild
- **Campaign Analytics**: Just completed in commit `f304e35` - includes timeline chart and top performers

### Git Workflow
- **Branch**: `claude/url-shortener-setup-011CUtxRK3RkihMw7gxT3jkq`
- **Always pull first**: `git pull origin <branch>`
- **Commit often**: Clear messages describing what, not how
- **Push when done**: `git push -u origin <branch>`

### Testing Status
- ✅ 104 backend tests passing (100% coverage of core features)
- ⏳ Manual testing started by user (registration has issues)
- ⏳ Frontend-backend integration needs verification

## What the User is Currently Working On

The user is **transitioning to local development in VS Code** to debug frontend-backend connection issues. They're focusing on testing rather than new features.

**Your Role**: Help them with:
- Bug fixes and debugging
- Code explanations
- Test verification
- Documentation improvements
- AWS deployment prep (Phase 4 when ready)

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
| Check lint | `uv run ruff check .` |
| View API docs | http://localhost:8000/docs |
| View frontend | http://localhost:4232 |

**Questions?** Check the inline code comments, test files, or ask the user for context.
