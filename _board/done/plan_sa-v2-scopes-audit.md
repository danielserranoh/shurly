---
id: plan_sa-v2-scopes-audit
title: Service accounts v2: scopes, limits, IP ranges, warnings, audit
type: plan
status: done
priority: low
created: 2026-10-19
started: 2026-10-19
completed: 2026-10-19
progress: 100
origin: epic_service-accounts-v2
owner: null
claimed_at: null
lease_until: null
blocked_by: []
parallel_safe: true
worktree: null
---

# Plan: Service accounts v2: scopes, limits, IP ranges, warnings, audit

## Objetivo
Close service accounts: per-token scopes, a rate limit per service account, allowed IP ranges, in-app warnings
(expiry, 90 days unused) and an audit table of what service accounts do, kept 2 years. Also drop `urls.og_fetched_at`
(`epic_drop-og-fetched-at`), now safe.

## Contexto
v1 shipped 2026-10-17. Propuestas uses it in production. Its first day, 17 Oct, saw the account and token created, 5 links created (1 on behalf of a person) and 8 updates; on 18 Oct there was 1 link on behalf of a person and 1 update. That meets the epic's premise ("wait until Propuestas has used it"). The user wants the topic closed.

Decided with the user (2026-10-19):
- **Warnings appear in the app now:** in the service-accounts section and as a dot in the menu for owners and admins. Email comes later, with `epic_invitations-email`.
- **Scopes are per token and inherited on renewal:** `urls:read`, `urls:write`, `urls:delete`, `tags:write`, `analytics:read`, `act_on_behalf`. Campaigns and redirect rules sit under `urls:*`. The existing Propuestas token gets all of them.
- **Audit covers service-account actions:** what they do (links, campaigns, tags, rules, and on whose behalf) plus account and token events. It is kept 2 years. Owners and admins read it, the same people who see the list.
- **Handing old links over is out of scope:** links Propuestas made earlier with a person's API key can't be told apart from links that person made by hand.

My decisions, within the user's v1 rules (expiry optional, owner-only management):
- **Default expiry:** the form preselects 1 year and "No expiry" stays available. Existing tokens are left as they are, and the API without `expires_at` still means no expiry.
- **Warnings:** a token that expires within 14 days, and one unused for 90 days (`last_used_at`, or `created_at` if never used).
- **Rate limit:** one fixed 1-minute window per **service account**, so the old and new tokens share it during the 24 h overlap.
  - Stored in the existing `rate_limits` table.
  - Set by `SERVICE_ACCOUNT_RATE_LIMIT_PER_MINUTE`, default 120.
  - Every service response carries `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`. A refusal is a 429 with `Retry-After`, and these headers are added to `cors_expose_headers`.
- **Allowed IP ranges:** a CIDR list per token, IPv4 and IPv6. An empty list means any IP, and the list is copied on renewal.
  - Checked against `client_ip(request)`, which is CloudFront-verified (`server/utils/network.py:167-193`). A mismatch gets a 403.
  - It's configuration, not an observed IP. So `service_token.py:43` ("No IP is kept") gets a clarification, plus a line in PERSONAL_DATA.
- **Audit storage:** ids only, following the event-log rule (`event_log.py:9-10`). Emails are resolved when the table is read, and a deleted person shows as "deleted".
- **MCP is unaffected:** it refuses service tokens (`mcp_server/auth.py:84-100`), and `/api/v1/service-accounts/*` is already excluded from it (`mcp_server/server.py:100-103`). The audit route lives under that prefix.
- **`urls.og_fetched_at` is dropped here (T1):** the release in production (a9aec24) no longer maps it, so the drop is now safe. That closes `epic_drop-og-fetched-at`, and its migration takes 0018; v2's takes 0019.

Checked against the repo rules (memory: check plans against repo rules):
- every migration is additive: new columns carry server defaults, and the drop is safe as explained above;
- the API only gains optional fields and routes;
- each new route gets a PERSONAL_DATA row;
- the new setting goes in ENVIRONMENT.md;
- the code must also run on Python 3.10, as in CI.

## Tareas

### T1 — Drop `urls.og_fetched_at` (migration 0018)
files: server/migrations/versions/0018_drop_og_fetched_at.py, tests/test_phase3141_migrations.py
depends_on:
verify: TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:55432/postgres uv run pytest tests/test_phase3141_migrations.py
- [x] Write 0018 as `epic_drop-og-fetched-at` describes. The downgrade re-adds the column, nullable and empty.
- [x] Remove `_PENDING_DROP`, `_not_a_pending_drop`, `_what` and their two tests.

### T2 — Data model (migration 0019)
files: server/migrations/versions/0019_service_accounts_v2.py, server/core/models/service_token.py, server/core/models/audit_event.py, server/core/models/__init__.py, docs/DATABASE_SCHEMA.md, tests/test_phase102_models.py
depends_on: T1
verify: uv run pytest tests/test_phase102_models.py tests/test_schema_diagram.py && TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:55432/postgres uv run pytest tests/test_phase3141_migrations.py
- [x] `service_tokens`:
  - `scopes` JSON, not null, with a server default of every scope, which also covers existing rows;
  - `allowed_ip_ranges` JSON, nullable, where null means any IP.
- [x] `audit_events`: id, at, organization_id, service_account_id, token_id, on_behalf_of_id, action, target_type, target_id, and a small `detail` JSON (ids and field names, never values). Index on (organization_id, at) and on service_account_id.
- [x] Regenerate the schema diagram, and add a round-trip test.

### T3 — Enforcement on every service request
files: server/core/auth.py, server/utils/service_scopes.py, server/utils/rate_limit.py, server/core/config.py, docs/ENVIRONMENT.md, tests/test_phase102_token_enforcement.py
depends_on: T2
verify: uv run pytest tests/test_phase102_token_enforcement.py tests/test_phase101_service_accounts.py tests/test_phase63_rate_limiting.py tests/test_environment_reference.py
- [x] `service_scopes.py` holds one map from (method, route template) to scope, read from `request.scope["route"]` inside `get_service_token`. Any `/api/v1` route not in the map is refused to service tokens. A test walks `app.routes`, so a new route can't go unmapped.
- [x] `X-Shurly-On-Behalf-Of` without `act_on_behalf` gets a 403.
- [x] The IP check against `allowed_ip_ranges` returns a 403 when the address is outside them.
- [x] Rate limit per service account, with the headers and the 429 described above. Reuse `Limit`, `hit` and `refusal` from `rate_limit.py`.
- [x] `_user_from_bearer`'s three callers pass `request`.

### T4 — Audit writes and retention
files: server/utils/audit.py, server/app/urls.py, server/app/campaigns.py, server/app/tags.py, server/utils/housekeeping.py, tests/test_phase102_audit.py, tests/test_housekeeping.py
depends_on: T2
verify: uv run pytest tests/test_phase102_audit.py tests/test_housekeeping.py tests/test_phase101_service_accounts.py tests/test_urls.py tests/test_campaigns.py
- [x] `record(db, acting, action, target)` writes an `AuditEvent` in the caller's transaction, only when a service account acts.
- [x] Call sites:
  - next to every existing `_log_service_change` and `campaign.created`;
  - the gaps: tags, redirect rules, campaign delete and tags, bulk tags.
- [x] A housekeeping job, `audit`, deletes events older than 2 years (`_a_year_before` twice) and logs the count.

### T5 — API: token settings, warnings, audit read
files: server/schemas/service_account.py, server/app/service_accounts.py, server/utils/service_accounts.py, docs/PERSONAL_DATA.md, tests/test_phase102_service_api.py, server/schemas/organization.py, server/app/organization.py, tests/test_phase102_audit.py
depends_on: T3, T4
verify: uv run pytest tests/test_phase102_service_api.py tests/test_phase101_service_accounts.py tests/test_personal_data_inventory.py
- [x] Token creation and renewal take optional `scopes` (validated against `service_scopes`) and `allowed_ip_ranges` (CIDR validated). `issue_token` inherits both on renewal.
- [x] `ServiceTokenInfo` returns `scopes`, `allowed_ip_ranges` and `warnings` (`expires_soon`, `unused`).
- [x] Account and token events (`service_accounts.py:206-362`) also call `audit.record`.
- [x] `GET /api/v1/service-accounts/audit?account=&before=&limit=`:
  - guarded by `ensure_reader`;
  - newest first, paginated by time;
  - people's emails resolved at read time.
- [x] An `attention` count of tokens with a warning, owners and admins only, for the nav dot. It goes on a payload the layout already loads, so there's no extra request per page.
  - T5: `service.attention_count(db, organization_id)` is written and tested. It belongs on
    `GET /api/v1/organization` (the layout loads it on every page and it carries the role), as
    `service_accounts_attention`, which needs `server/app/organization.py` and
    `server/schemas/organization.py`: outside T5's files, so left for the coordinator.
- [x] PERSONAL_DATA rows for the new route. The MCP column says excluded.

### T6 — Frontend
files: frontend/src/components/settings/ServiceAccountsSection.astro, frontend/src/utils/service-accounts.ts, frontend/src/utils/types.ts, frontend/src/layouts/AppLayout.astro, frontend/src/pages/styleguide.astro, frontend/tests/service-accounts.test.mjs, frontend/e2e/service-accounts.spec.ts
depends_on: T5
verify: cd frontend && npm test && npm run build
- [x] The token form:
  - scope checkboxes (`fieldset`/`.checkbox`, styleguide :1303), all checked by default;
  - allowed IP ranges, CIDR, one per line;
  - expiry preselected at 1 year, with "No expiry" still available.
- [x] On the token line, `badge-warn` badges "Expires soon" and "Unused for 90 days". The dot in the menu for owners and admins.
- [x] An "Activity" dialog per service account reading the audit route, with "Load more".
- [x] Replace the copy "Nothing warns before it expires" (:80).
  - T6: the pure logic (scope labels and summary, the IP ranges' parsing, the default expiry, the audit's
    sentences) is in a new `frontend/src/utils/service-accounts.ts`, which the section, AppLayout, the styleguide
    and `tests/service-accounts.test.mjs` share. The dot sits on the avatar (the Organization page is in the account
    menu) and the menu's organization row says "N service tokens need attention".

### T7 — Docs and records
files: CHANGELOG.md, DEPLOYMENT.md, _pm/spec_service_accounts.md, _pm/ROADMAP.md, frontend/src/content/manual/connect-a-service.md, docs/PERSONAL_DATA.md, server/utils/errors.py, design/DESIGN_SYSTEM.md
depends_on: T1, T2, T3, T4, T5, T6
verify: uv run pytest tests/test_personal_data_inventory.py tests/test_environment_reference.py
- [x] CHANGELOG:
  - Added: scopes, rate limit, IP ranges, warnings, audit;
  - Removed: the `urls.og_fetched_at` column.
- [x] DEPLOYMENT § Service accounts: the limit and its setting, the headers, IP ranges behind CloudFront, how to read the audit.
- [x] Mark the spec's v2 items done, and say the handover is dropped by decision.
- [x] ROADMAP 10.x; the manual's step 4; PERSONAL_DATA § the audit table, kept 2 years, read by owners and admins.
  - T7: also `server/utils/errors.py`'s list of codes and DESIGN_SYSTEM's TypeScript modules. The ROADMAP links
    both epics under `_board/done/`: `epic_drop-og-fetched-at` is still in `backlog/` until the plan closes it.

## Verificación global
- [x] `uv run pytest --require-mcp` (2505 passed, 27 skipped), ruff, frontend `npm test` (295) && `npm run build`; `npm run e2e` 140 passed (T6)
- [x] migration tests on a throwaway postgres:17 (5); T2–T5 suites with `TEST_SUITE_ON_POSTGRES=1` (212)

## Notas
- Waves: T1 → T2 → T3 ∥ T4 → T5 → T6 → T7. Agents are general-purpose (kanban-implementer fails for this
  organization). Each brief: write only your files; a conflict with a repo rule means stop and report.
- Out of scope by decision: handing over links Propuestas made with a person's API key; email warnings (wait for
  `epic_invitations-email`).
- After the release: Propuestas keeps working unchanged (all scopes, no IP list), `RateLimit-*` headers on its
  requests, audit rows from its next action, `housekeeping.run` shows the `audit` job.
- The plan's name differs from the epic's on purpose (board.sh resolves same-name cards wrongly).

## Log
- 2026-10-19T11:27:14Z Daniel Serrano moved wip -> done
- 2026-10-19T11:27:14Z Daniel Serrano released
- 2026-10-19T11:27:14Z Daniel Serrano released in #251 (36c10d2, td 52): alembic 0019, og_fetched_at gone, Propuestas token with all 6 scopes and no ranges, audit_events empty until its next action; housekeeping.run 11:20Z with audit_deleted 0, no failed jobs; 0 5xx
- 2026-10-19T10:10:32Z Daniel Serrano T1-T7 done and verified: 2505 passed, PostgreSQL 212 + migrations 5, frontend 295 + e2e 140; PR to dev
- 2026-10-19T09:03:39Z Daniel Serrano moved todo -> wip
- 2026-10-19T09:03:39Z Daniel Serrano claimed (lease 120m)
- 2026-10-19T09:03:16Z Daniel Serrano created
