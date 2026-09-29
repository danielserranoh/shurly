# syntax=docker/dockerfile:1.7
# Multi-stage build for a small production image. Built for linux/arm64 in the
# deploy pipeline (Fargate ARM64 is ~20% cheaper than x86) but the Dockerfile
# itself stays platform-agnostic so it also runs on developer Macs (arm64) and
# Linux x86 hosts.

# Base images by digest (Phase 6.3): a build installs what was tested, and Dependabot's weekly PR
# moves the digest (.github/dependabot.yml). uv is one version, the lock's, here and in CI
# (UV_VERSION in the workflows): bump both together, and re-lock (tests/test_dependency_lock.py).

# ─── Geolocation data (Phase 8.4) ───────────────────────────────────────────
# MaxMind's GeoLite2 City (its EULA: replaced within 30 days, so the image is rebuilt weekly),
# and DB-IP's IP to Country Lite (CC BY 4.0, https://db-ip.com), the fallback. Fetched and
# checked by scripts/fetch_geoip.py. MaxMind's account ID and licence key are build secrets:
# mounted for that one step, in no layer. On the build platform only, since the data is the
# same for every platform. It never fails the build; the deploy job does, without GeoLite2.
FROM --platform=$BUILDPLATFORM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e AS geoip
RUN pip install --no-cache-dir "maxminddb>=3.2,<4"
COPY scripts/fetch_geoip.py /fetch_geoip.py
# A new value each run, so no cache ever serves last week's databases.
ARG GEOIP_REFRESH=""
RUN --mount=type=secret,id=maxmind_account_id --mount=type=secret,id=maxmind_license_key \
    echo "refresh: ${GEOIP_REFRESH}" && python /fetch_geoip.py /geoip

# Just the data: what the image copies, and what the deploy job checks
# (`--target geoip-data --output type=local`).
FROM scratch AS geoip-data
COPY --from=geoip /geoip/ /

FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e AS builder

# uv for fast, deterministic installs from the lockfile.
COPY --from=ghcr.io/astral-sh/uv:0.11.1@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce /uv /usr/local/bin/uv

WORKDIR /app

# Copy only the files needed to resolve and install deps. Keeping these in a
# separate layer lets Docker reuse the install layer when only application code
# changes.
COPY pyproject.toml uv.lock README.md ./

# `--no-dev` skips the [dev] extra (ruff, pytest); `--frozen` enforces uv.lock.
# `--extra mcp` installs fastmcp so the Streamable HTTP transport at /mcp
# (Phase 5.5) is available. Set `MCP_DISABLE_MOUNT=1` at runtime to opt out
# without rebuilding (e.g. incident response).
RUN uv sync --no-dev --frozen --extra mcp

# ─── Runtime image ──────────────────────────────────────────────────────────

FROM python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

# libpq5 is required by psycopg2-binary at runtime. ca-certificates ensures
# httpx's OG fetcher can validate TLS for upstream targets. curl is included so
# the Docker HEALTHCHECK has a tiny dependency-free way to probe the app.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Bring the prebuilt virtualenv from the builder stage.
COPY --from=builder /app/.venv /app/.venv

# Application code. `server/` includes templates/preview.html (used by the
# social-media crawler preview path) and all the SQLAlchemy models registered
# in server/core/models/__init__.py. `mcp_server/` exposes the API as MCP
# tools and is mounted at `/mcp` by `main.py` when fastmcp is installed.
COPY server ./server
COPY mcp_server ./mcp_server
COPY main.py ./

# Phase 8.4 — the geolocation databases, where GEOIP_DATABASE and GEOIP_FALLBACK_DATABASE look
# by default. Either may be absent (the fetch never fails the build): without both, no country.
COPY --from=geoip-data / ./data/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Source commit, reported by GET /api/v1/health so the deploy pipeline can tell
# the new image from the old one. Declared late so changing it doesn't
# invalidate the dependency layers above. Defaults to "unknown" for local builds.
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA
# Phase 8.4 — and the deploy run that built it: the weekly rebuild keeps the commit, so the
# smoke test tells the images apart by this.
ARG BUILD_ID=unknown
ENV BUILD_ID=$BUILD_ID

EXPOSE 8000

# Container healthcheck (used by `docker ps` and local orchestration). ECS uses
# the ALB target group health check separately, configured to hit /api/v1/health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent --show-error http://localhost:8000/api/v1/health || exit 1

# Single uvicorn worker is plenty for the per-task concurrency we need; ECS
# Express scales horizontally by adding tasks, not by adding workers per task.
# `--proxy-headers` lets uvicorn honor X-Forwarded-* set by the ALB; the actual
# trust decision still goes through TRUSTED_PROXIES in server/utils/network.py.
# `--no-access-log`: RequestIdMiddleware writes each request's `http.request`
# JSON line (Phase 5.6.0), so uvicorn's own line would only duplicate it.
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--no-access-log"]
