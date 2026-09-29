# Environment variables

Every variable Shurly reads, with its default and what it does. **Defaults and meanings only.** Production's values
live on the ECS service (see [DEPLOYMENT.md](../DEPLOYMENT.md)), never in this repository.

Reviewed on 2026-09-29. **Update this reference in the same PR as any new or changed setting.**
`tests/test_environment_reference.py` fails when:
- a setting has no row, or a row names none;
- a setting's default differs from its row;
- a variable read anywhere else (with `os.getenv`, or `PUBLIC_*` in the frontend) has no row.

## How the backend reads them

`server/core/config.py` (pydantic-settings):
- A setting's variable is its name in capitals: `rate_limit_login_per_ip` is `RATE_LIMIT_LOGIN_PER_IP`. Case doesn't
  matter.
- A `.env` file in the working directory is read too. The environment wins.
- A list takes JSON (`["a", "b"]`) or, for `CORS_ORIGINS`, `TRUSTED_PROXIES`, `MCP_OAUTH_ALLOWED_REDIRECT_URIS` and
  `CLOUDFRONT_ORIGIN_SECRETS`, comma-separated values.
- A secret is marked as one. Settings never log or echo one.

## Backend settings

### Database

| Variable | Default | What it does |
|---|---|---|
| `DB_HOST` | `localhost` | PostgreSQL's host |
| `DB_PORT` | `5432` | PostgreSQL's port |
| `DB_USER` | `postgres` | The database user |
| `DB_PASSWORD` | (empty) | That user's password. A secret |
| `DB_NAME` | `shurly` | The database |
| `DB_SSL_MODE` | `prefer` | libpq's `sslmode`: `require` on RDS |
| `DB_POOL_SIZE` | `10` | Connections each task keeps open |
| `DB_MAX_OVERFLOW` | `20` | Connections each task may open beyond the pool, under load |
| `DB_POOL_RECYCLE` | `3600` | Seconds before a pooled connection is replaced |

### Sessions

| Variable | Default | What it does |
|---|---|---|
| `JWT_SECRET_KEY` | `your-secret-key-change-in-production` | Signs session tokens. A long random secret in production: whoever has it can sign in as anyone |
| `JWT_ALGORITHM` | `HS256` | The tokens' signature algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `10080` | How long a session lasts: 7 days |

### API

| Variable | Default | What it does |
|---|---|---|
| `API_TITLE` | `Shurly API` | The OpenAPI document's title |
| `API_VERSION` | `0.1.0` | Its version |
| `API_DESCRIPTION` | `A modern URL shortener API` | Its description |
| `CORS_ORIGINS` | `["http://localhost:4321", "http://localhost:4232", "http://localhost:3000"]` | The origins a browser may call the API from: the frontend's development servers. In production the frontend and the API share an origin |
| `CORS_ALLOW_CREDENTIALS` | `false` | The frontend sends a bearer token, never cookies |
| `CORS_ALLOW_METHODS` | `["GET", "POST", "PUT", "PATCH", "DELETE"]` | The methods the API uses |
| `CORS_ALLOW_HEADERS` | `["Authorization", "Content-Type", "X-Request-Id"]` | The request headers the API reads |
| `CORS_EXPOSE_HEADERS` | `["Retry-After", "X-Request-Id"]` | The response headers the frontend reads |

### Client addresses and privacy

| Variable | Default | What it does |
|---|---|---|
| `ANONYMIZE_REMOTE_ADDR` | `true` | Truncate a visit's IP before storing it: IPv4 to /24, IPv6 to /64. Off only after a legal review |
| `TRUSTED_PROXIES` | (empty) | The CIDRs whose `X-Forwarded-For` is believed: the ALB's. Empty: never believed, and each per-IP rate limit becomes one limit for everybody behind the ALB |
| `CLOUDFRONT_ORIGIN_SECRETS` | (empty) | Behind CloudFront, the value its custom origin header carries, proving `CloudFront-Viewer-Address` is CloudFront's. Two while rotating, each at least 32 characters. A secret |
| `CLOUDFRONT_ORIGIN_HEADER` | `X-Origin-Verify` | That header's name |
| `GEOIP_DATABASE` | `data/GeoLite2-City.mmdb` | MaxMind's GeoLite2 City, which gives a visit its country (the image build fetches it, with MaxMind's credentials). Empty turns lookups off |
| `GEOIP_FALLBACK_DATABASE` | `data/dbip-country-lite.mmdb` | DB-IP's country database, used when `GEOIP_DATABASE`'s file isn't there. The image build fetches it too |

### Short links and redirects

| Variable | Default | What it does |
|---|---|---|
| `DEFAULT_DOMAIN` | `shurl.griddo.io` | The default short-link host, seeded at startup |
| `BASE_URL` | (empty) | The base of every short URL the API writes, when the short-link host isn't the one `DEFAULT_DOMAIN` gives. Rare |
| `SHORT_URL_MODE` | `loose` | `loose` lowercases generated codes and custom slugs; `strict` keeps their case |
| `DISABLE_TRACK_PARAM` | `nostat` | A query parameter that makes a redirect log no visit: for QA |
| `REDIRECT_STATUS_CODE` | `302` | `301`, `302`, `307` or `308`. `301` is cached by browsers, so visits go uncounted |
| `REDIRECT_CACHE_LIFETIME` | `0` | Seconds a redirect may be cached. `0` sends `private, max-age=0`, so every visit reaches the API |
| `INVALID_SHORT_URL_REDIRECT` | (empty) | Where a short link that doesn't lead anywhere sends everyone: no such code, not live yet, expired or used up. Shlink's setting of the same name. An absolute http(s) URL, or the app won't start. A 302 that isn't cached; an unknown code is still an orphan visit. Empty: a page for people, JSON for the rest, with the 404 or 410 |
| `OG_FETCH_ALLOW_PRIVATE` | `false` | Let link previews fetch private and loopback addresses. Local development only: it opens the preview fetcher to SSRF |

### Organization and sign-in

| Variable | Default | What it does |
|---|---|---|
| `ORGANIZATION_NAME` | `Griddo` | The organization seeded at startup |
| `ORGANIZATION_DOMAIN` | `griddo.io` | The Google Workspace domain whose accounts may sign in. Empty would let any Google account in |
| `BOOTSTRAP_OWNER_EMAIL` | (empty) | The first owner: the account that becomes owner when it joins an organization without one. At startup, it's also made owner again if none is left |
| `GOOGLE_CLIENT_ID` | (empty) | The Google OAuth client. Until it, the secret, the redirect URI, `FRONTEND_URL` and `ORGANIZATION_DOMAIN` are set, Google's endpoints answer 503 |
| `GOOGLE_CLIENT_SECRET` | (empty) | Its secret. A secret |
| `GOOGLE_REDIRECT_URI` | (empty) | This API's `/api/v1/auth/google/callback`, as registered with the client |
| `FRONTEND_URL` | (empty) | The frontend: after Google, the browser goes to its `/login/` with a one-time code |
| `ALLOW_PASSWORD_SIGNUP` | `false` | Turns `POST /api/v1/auth/register` on. Local development and tests only |

### MCP

| Variable | Default | What it does |
|---|---|---|
| `MCP_PUBLIC_URL` | (empty) | The MCP endpoint as clients reach it, without the trailing slash. With the Google client, `ORGANIZATION_DOMAIN` and the signing key, it turns on sign-in with Google for MCP clients |
| `MCP_OAUTH_SIGNING_KEY` | (empty) | Signs the MCP's OAuth tokens and encrypts what it stores. The same on every task; changing it signs every MCP client out. A secret |
| `MCP_OAUTH_ALLOWED_REDIRECT_URIS` | `["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback", "http://localhost:*", "http://127.0.0.1:*"]` | The redirect URIs an MCP client may register: claude.ai's, and Claude Code's loopback. Nothing else can ask a person to consent |

### Rate limits

Each is a count per window, and `0` turns it off. The per-IP ones need `TRUSTED_PROXIES`.

| Variable | Default | What it does |
|---|---|---|
| `RATE_LIMIT_LOGIN_PER_IP` | `20` | `POST /api/v1/auth/login` per client IP, per minute |
| `RATE_LIMIT_LOGIN_FAILURES_PER_ACCOUNT` | `10` | Failed password checks per address, per 15 minutes: logins, and the current password given to change or set one |
| `RATE_LIMIT_SIGN_IN_PER_IP` | `30` | Google's and the MCP's sign-in pages and endpoints, per client IP, per minute |
| `RATE_LIMIT_MCP_CLIENTS_PER_IP` | `60` | `/mcp/register` and `/mcp/token` per client IP, per minute: claude.ai calls them from shared addresses |
| `RATE_LIMIT_CLIENT_ERRORS_PER_IP` | `30` | Browser error reports (`POST /api/v1/client-errors`) per client IP, per minute: the web app sends 5 at most per page |

### Tags

| Variable | Default | What it does |
|---|---|---|
| `PREDEFINED_TAGS` | (see `config.py`) | The tag groups seeded at startup, as JSON: channels, intent, content type, audience, lifecycle |
| `USER_TAG_COLOR` | `gray-500` | A new tag's color |

## Backend, outside the settings

| Variable | Default | What it does |
|---|---|---|
| `GIT_SHA` | `unknown` | The source commit, reported by `GET /api/v1/health`. The image build sets it |
| `BUILD_ID` | `unknown` | The deploy run that built the image, reported by `GET /api/v1/health` too: the weekly rebuild keeps the commit, so the smoke test waits for this as well. The image build sets it |
| `MCP_DISABLE_MOUNT` | (unset) | `1` doesn't mount the MCP at `/mcp`, without a rebuild: for an incident |
| `MCP_DISABLE_AUTH` | (unset) | `1` runs the MCP without its sign-in. For local stdio development only, never in production |
| `MCP_SERVER_NAME` | `shurly` | The MCP server's name, as clients see it |
| `TESTING` | (unset) | Set by the tests (`tests/conftest.py`): the app skips its startup work (migrations, seeding) |

## Tools

| Variable | Default | What it does |
|---|---|---|
| `SHLINK_URL` | (unset) | The Shlink export's source: Shlink's address (`server/tools/shlink`) |
| `SHLINK_API_KEY` | (unset) | Its API key. Only ever sent in its header: never written or printed. A secret |
| `MAXMIND_ACCOUNT_ID` | (unset) | MaxMind's account ID, for `scripts/fetch_geoip.py` to download GeoLite2 City. The deploy job gives it to the image build as a BuildKit secret, from the GitHub secret of the same name |
| `MAXMIND_LICENSE_KEY` | (unset) | Its licence key, the same way. Sent to MaxMind only: never written or printed. A secret |

## Tests

| Variable | Default | What it does |
|---|---|---|
| `TEST_DATABASE_URL` | (unset) | A PostgreSQL server for the migration and PostgreSQL tests, which skip without it (fail, with `--require-postgres`) |
| `TEST_SUITE_ON_POSTGRES` | (unset) | `1` runs the whole suite on PostgreSQL instead of in-memory SQLite, as production runs: on a database made for the run on `TEST_DATABASE_URL`'s server, and dropped when it ends. CI's `test-postgres` job |
| `E2E` | (unset) | `1` lets the end-to-end tests' API start (`tests/e2e/app.py`; Playwright sets it). It signs anyone in through a fake Google, so it also needs `DB_HOST` to be `localhost`, `127.0.0.1` or `::1` |
| `E2E_API_URL` | `http://127.0.0.1:18000` | Where an end-to-end run serves that API (`tests/e2e/app.py`, `frontend/e2e/env.ts`) |
| `E2E_WEB_URL` | `http://127.0.0.1:14321` | Where it serves the pages, built for that API |
| `E2E_CHANNEL` | (unset) | `chrome` runs the end-to-end tests in the installed Google Chrome, instead of Playwright's Chromium |
| `CI` | (unset) | Set by GitHub Actions. The end-to-end tests then retry a failed test once, fail on a `.only`, and write an HTML report |

## Frontend

Astro reads these at build time: a build bakes them in.

| Variable | Default | What it does |
|---|---|---|
| `PUBLIC_API_URL` | `http://localhost:8000` | The API the frontend calls, and the origin its Content-Security-Policy allows |
| `PUBLIC_SITE_URL` | `http://localhost:4232` | The frontend's own address |
| `PUBLIC_SHORT_DOMAIN` | the API's host | The host shown before a link's code, when the short links live on another host than the API |
| `PUBLIC_MCP_URL` | `PUBLIC_API_URL` + `/mcp/` | The MCP endpoint the manual and Settings show |
| `PUBLIC_SOURCE_URL` | (empty) | The landing page's link to the source code. Hidden when empty |
| `PUBLIC_SPONSOR_URL` | (empty) | The landing page's sponsor link. Hidden when empty |
