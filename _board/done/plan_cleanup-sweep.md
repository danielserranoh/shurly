---
id: plan_cleanup-sweep
title: Cleanup sweep
type: plan
status: done
priority: medium
created: 2026-10-18
started: 2026-10-18
completed: 2026-10-18
progress: 100
epic: epic_cleanup-sweep
owner: null
claimed_at: null
lease_until: null
blocked_by: []
parallel_safe: true
worktree: null
---

# Plan: Cleanup sweep

## Objetivo
The leftovers of earlier phases and the fixes found since, as one tested increment: daily housekeeping inside the app,
`og_fetched_at` dropped, campaign previews, the custom-preview badge, list settings from the environment, two scripts,
and the MCP's round-trip test and "how to add a tool".

## Contexto
Small leftovers from earlier phases, plus fixes found while doing the last epics. The analysis (2026-10-18) found two that matter more than they looked:
- **List settings can't be set as plain text.** Any non-JSON value of `CORS_ORIGINS`, `TRUSTED_PROXIES`, `MCP_OAUTH_ALLOWED_REDIRECT_URIS` or `CLOUDFRONT_ORIGIN_SECRETS` from the environment raises `SettingsError` when `server/core/config.py` loads, so the app won't start.
  - This covers a single bare value and an empty `TRUSTED_PROXIES=`.
  - `parse_string_list` (config.py:240-260) never sees the value: pydantic-settings 2.15 JSON-decodes it first.
  - docs/ENVIRONMENT.md:18-19 promises comma-separated values.
  - The tests build `Settings(...)` from kwargs, so they hide it.
- **Dropping `urls.og_fetched_at` rewrites the previews backfill.** `server/tools/previews.py:82,91` reads and clears it to separate old copies from overrides; that job is done in production.

Decided with the user (2026-10-18):
- **expired links are not deleted:** they keep answering 410 with their analytics, and the 3.9.2 item is dropped;
- **periodic work runs inside the app:** a daily background loop, with a PostgreSQL advisory lock so only one task runs it.

Facts the tasks rely on:
- **The waitlist** stores the latest sign-up as `consent_at`, not null (`server/core/models/waitlist.py:47`), so the purge is `consent_at < now − 12 months`.
- **Previews:** `fetch_all` (bounded concurrency) and `store_page_preview` (`server/utils/previews.py:34-47`) exist. A failed fetch leaves `page_fetched_at` unchanged.
- **Campaign creation:** `create_campaign` (`server/app/campaigns.py:44`, a sync `def`) and the curated `create_campaign_from_rows` (`mcp_server/curated.py:65-145`) give every link the same `original_url`, so one fetch serves all its links. Nothing fetches today.
- **Link cards:** they get `has_custom_preview` (`server/schemas/url.py:260`); the badges live in `frontend/src/utils/links.ts:122-145`.
- **MCP:** `tests/test_mcp_output_dates.py` already calls every tool through the in-process MCP, but never compares a result with the REST response. mcp_server/README.md has no "how to add a tool", and the CHANGELOG has no entry for the MCP surface.
- **Scripts:**
  - `scripts/create_rds.sh:156` prints the generated password, and `:160` says to save it in Secrets Manager;
  - `scripts/deploy_ecs.sh:261` prints a wrong health URL (Express hosts are opaque);
  - `tests/test_client_ip_source.py:11-12` cites a non-existent "§ Monitoring".
- **The next migration** is 0018 (`down_revision = "0017"`), on the pattern of `0014_drop_users_api_key.py`.

## Tareas

### T1 — Daily housekeeping inside the app
files: server/utils/housekeeping.py, main.py, tests/test_housekeeping.py
depends_on:
verify: uv run pytest tests/test_housekeeping.py
- [x] a background loop started from the app's lifespan (not under `TESTING`):
  - it runs once a day (first run a few minutes after start, so a deploy isn't slowed);
  - each run takes `pg_try_advisory_lock`, so two tasks don't both run, and skips when it's held;
  - it logs `housekeeping.run` with counts only
- [x] job 1: delete waitlist entries with `consent_at` older than 12 months
- [x] job 2: re-fetch stale page previews (`page_fetched_at` null, or older than 30 days), at most 200 links a day, oldest first
  - reuse `fetch_all` and `store_page_preview`, deduping by destination;
  - don't edit `server/tools/previews.py` or `server/utils/previews.py` (another task owns them)
- [x] tests with an injected clock and fetcher: each job's selection and limits, the lock skipping, an exception in one job not stopping the other, and the loop not starting under TESTING

### T2 — Drop `urls.og_fetched_at`
files: tests/test_phase3141_migrations.py, server/core/models/url.py, server/schemas/url.py, server/app/urls.py, server/tools/previews.py, tests/test_phase87_backfill_previews.py, tests/test_phase87_previews.py, tests/test_urls.py, tests/test_mcp_output_dates.py, frontend/src/utils/types.ts, docs/DATABASE_SCHEMA.md
depends_on:
verify: uv run pytest tests/test_phase87_backfill_previews.py tests/test_phase87_previews.py tests/test_urls.py tests/test_mcp_output_dates.py tests/test_schema_diagram.py
- [x] ~~migration 0018 drops the column~~ → unmapped now, dropped next release (`epic_drop-og-fetched-at`): the old
  release's tasks still SELECT it mid-rollout. The drift test ignores exactly that column (`_PENDING_DROP`)
- [x] out of the model, the API (`URLResponse.og_fetched_at` and its mirror at urls.py:175) and the frontend type
- [x] the backfill keeps "fetch every destination, store `page_*`", without the old-copy separation; its tests rewritten
- [x] regenerate docs/DATABASE_SCHEMA.md; the migrations drift test needs PostgreSQL (`TEST_DATABASE_URL`, a throwaway postgres:17)

### T3 — Campaign links get their page's preview
files: server/app/campaigns.py, mcp_server/curated.py, mcp_server/server.py, server/utils/previews.py, tests/test_campaign_previews.py, tests/conftest.py
depends_on:
verify: uv run pytest tests/test_campaign_previews.py tests/test_phase53_curated_tools.py
- [x] creating a campaign, through the API or the curated MCP tool, fetches its destination once (SSRF-guarded, as today) and stores `page_*` on every link
  - a fetch that fails doesn't fail the campaign;
  - one shared helper in `server/utils/previews.py`
- [x] tests with the fetcher stubbed: one fetch per campaign, every link gets it, a failure still creates the campaign

### T4 — Custom-preview badge on link cards
files: frontend/src/utils/links.ts, frontend/src/pages/styleguide.astro, frontend/tests/link-badges.test.mjs
depends_on:
verify: cd frontend && npm test && npm run build
- [x] when `has_custom_preview` is set, a quiet badge (e.g. `badge-outline` with an image icon, "Custom preview") joins the exceptions in `linkBadges`
- [x] the styleguide shows it; the styleguide's `og_fetched_at` sample (line ~2345) is removed
- [x] a unit test for when the badge appears

### T5 — List settings from the environment
files: server/core/config.py, tests/test_config_list_settings.py, docs/ENVIRONMENT.md, pyproject.toml, uv.lock
depends_on:
verify: uv run pytest tests/test_config_list_settings.py tests/test_environment_reference.py tests/test_phase63_cloudfront_client_ip.py
- [x] mark the four list fields `NoDecode` (pydantic-settings ≥ 2.7), so `parse_string_list` gets the raw text: JSON, comma-separated, a single value and empty all work
- [x] tests through real env vars (`monkeypatch.setenv`, `Settings(_env_file=None)`): JSON, commas, single, empty, and CLOUDFRONT_ORIGIN_SECRETS' 32-character minimum still enforced
- [x] ENVIRONMENT.md says what now works

### T6 — Scripts and a stale pointer
files: scripts/create_rds.sh, scripts/deploy_ecs.sh, tests/test_deploy_ecs_script.py, tests/test_create_rds_script.py, tests/test_client_ip_source.py
depends_on:
verify: uv run pytest tests/test_deploy_ecs_script.py tests/test_create_rds_script.py tests/test_client_ip_source.py
- [x] `create_rds.sh` writes the generated password straight to SSM `/shurly/production/DB_PASSWORD` (SecureString, through a 0600 file, as DEPLOYMENT.md § Secrets does) and never prints it
  - on a re-run where the instance exists, it doesn't make a new one;
  - a test with a fake `aws`
- [x] `deploy_ecs.sh`'s "next step" reads the opaque host from `describe-express-gateway-service`, as DEPLOYMENT.md § 4 does; the test asserts it
- [x] `test_client_ip_source.py` points to "DEPLOYMENT.md § Client IPs behind CloudFront"

### T7 — MCP: round-trip test and "how to add a tool"
files: tests/test_mcp_roundtrip.py, mcp_server/README.md
depends_on:
verify: uv run pytest tests/test_mcp_roundtrip.py --require-mcp
- [x] for a representative set of auto-generated tools (read and write, e.g. `list_urls`, `get_url`, `create_short_url`, `update_url`, `get_url_totals`, `list_tags`), the MCP's `structured_content` equals the REST response for the same user and arguments
- [x] README: a "How to add a tool" section (generated: route, `MCP_TOOL_NAMES`/exclusions, `test_phase52`; curated: `curated.py` and the wrapper in `server.py`, PERSONAL_DATA rows); refresh the tool counts

### T8 — Docs and records
files: CHANGELOG.md, DEPLOYMENT.md, docs/PERSONAL_DATA.md, _pm/ROADMAP.md, scripts/run_backfill_previews.sh
depends_on: T1, T2, T3, T4, T5, T6, T7
verify: uv run pytest tests/test_personal_data_inventory.py
- [x] CHANGELOG under Unreleased:
  - Added: housekeeping, campaign previews, the badge, the MCP-surface entry the 5.7 item asked for;
  - Fixed: list settings, scripts;
  - Removed: `og_fetched_at`
- [x] DEPLOYMENT.md: the housekeeping loop (what it does, its log line, how to see it); § Previews no longer mentions `og_fetched_at`
- [x] PERSONAL_DATA § The waitlist: retention is enforced, no longer "proposed"
- [x] ROADMAP: tick the ⇢ cleanup items; 3.9.2 dropped (the user's call: expired links keep their analytics)

## Verificación global
- [x] `uv run pytest --require-mcp`, ruff, and frontend `npm test && npm run build` green; migration tests on PostgreSQL
  (2363 passed, 28 skipped; 274 frontend; migrations 7 on postgres:17)

## Notas
- 3.9.2 (deleting expired links) is dropped by the user's decision: expired links keep answering 410 with their analytics.
- `og_fetched_at` stays in the API as a deprecated copy of `page_fetched_at`: removing a field within /api/v1/ breaks
  the CHANGELOG's versioning policy. Only the model mapping goes; the column drop is `epic_drop-og-fetched-at`.
- Found in QA and fixed here: an array left in shell quotes (`'["…"]'`) in a list setting is refused at startup
  (it was read as one literal value, which passed CLOUDFRONT_ORIGIN_SECRETS' length check).
- Follow-ups, not done: dead pages hold the front of housekeeping's preview queue (needs a "last attempted" marker);
  no saved Logs Insights query for `housekeeping.run` yet; ROADMAP 3.11's "campaign edit screen; Pro billing"
  have no epic.
- T1 must not edit `server/tools/previews.py` or `server/utils/previews.py` (T2 and T3 own them); it only imports.

## Log
- 2026-10-18T18:16:00Z Daniel Serrano moved wip -> done (by hand: board.sh resolves this name to the epic)
- 2026-10-18T18:16:00Z Daniel Serrano released
- 2026-10-18T18:15:00Z Daniel Serrano released in #248 (merge a9aec24; push didn't trigger the deploy, dispatched by hand): td 49, 5 secrets kept; first housekeeping.run 18:09:06Z (waitlist 0, previews checked 2, failed 2); 0 5xx
- 2026-10-18T13:41:30Z Daniel Serrano T1-T8 done, verified: 2363 passed, frontend 274, migrations 7 on PostgreSQL; PR to dev
- 2026-10-18T13:41:30Z Daniel Serrano fixed: `progress plan_cleanup-sweep` and `log` resolved to the epic again (same name); undone by hand
- 2026-10-18T13:15:00Z Daniel Serrano fixed: `move epic_cleanup-sweep done` matched this plan (same name) and moved it to done; put back in WIP, not completed
- 2026-10-18T13:13:41Z Daniel Serrano claimed (lease 480m)
- 2026-10-18T13:13:40Z Daniel Serrano moved todo -> done
- 2026-10-18T13:13:40Z Daniel Serrano created
