---
id: plan_secrets-in-parameter-store
title: Secrets in Parameter Store
type: plan
status: done
priority: high
created: 2026-10-17
started: 2026-10-17
completed: 2026-10-17
progress: 100
epic: epic_secrets-manager
owner: null
claimed_at: null
lease_until: null
blocked_by: []
parallel_safe: true
worktree: null
---

# Plan: Secrets in Parameter Store

## Objetivo
Take the five secrets (`DB_PASSWORD`, `JWT_SECRET_KEY`, `GOOGLE_CLIENT_SECRET`, `MCP_OAUTH_SIGNING_KEY`,
`CLOUDFRONT_ORIGIN_SECRETS`) out of the `shurly-api` service's plain environment into SSM Parameter Store
(SecureString, standard tier, free) under `/shurly/production/<NAME>`, injected through the container's `secrets`.
Rotate the JWT and MCP keys on the way, and delete the old task-definition revisions that hold the values in plain text.

## Contexto
Decided with the user on 2026-10-17: Parameter Store, not Secrets Manager; rotate JWT and MCP only; delete old revisions.
- No app change: every secret is read once as an env var at startup (`server/core/config.py:297`), which is how ECS
  injects `secrets`.
- The deploy workflow sends the live container back with only `.image` changed, so `secrets` survive
  (`.github/workflows/deploy-backend.yml:176-207`). Its guard needs a non-empty `environment`, which stays true.
- The one-off scripts already copy `secrets: ($app.secrets // [])` (`scripts/run_*.sh`). Untested.
- `scripts/deploy_ecs.sh` (create only) still writes `DB_PASSWORD` and `JWT_SECRET_KEY` into `environment`.
- Execution role `ecsTaskExecutionRole` (shared) has only `AmazonECSTaskExecutionRolePolicy`: it needs
  `ssm:GetParameters` on `/shurly/production/*`.
- Neither rotated key takes two values: a JWT change signs everyone out and resets the rate-limit counters
  (`server/utils/rate_limit.py:87`). An MCP key change signs every MCP client out and leaves old `mcp_oauth_store`
  rows unreadable (`mcp_server/oauth_store.py:112-124`). The ~10-minute canary mixes old and new keys; accepted.
- `CLOUDFRONT_ORIGIN_SECRETS` stays a JSON array string (`config.py:240-268`); a single quoted value stops the app.

## Tareas

### T1 — Tests: the one-off scripts carry `secrets`
files: tests/test_run_shlink_import.py, tests/test_run_backfill_places.py, tests/test_run_backfill_previews.py, tests/test_run_promote_domain.py, tests/test_run_retire_domain.py
depends_on:
verify: uv run pytest tests/test_run_shlink_import.py tests/test_run_backfill_places.py tests/test_run_backfill_previews.py tests/test_run_promote_domain.py tests/test_run_retire_domain.py
- [x] `LIVE` gains `secrets: [{name, valueFrom: arn:aws:ssm:eu-south-2:…:parameter/shurly/production/…}]`
- [x] each script's test asserts the registered definition keeps `secrets` unchanged, and nothing of it is printed

### T2 — Tests: a deploy keeps `secrets`
files: tests/test_deploy_workflow.py
depends_on:
verify: uv run pytest tests/test_deploy_workflow.py
- [x] run the "Roll out new image to ECS Express" step against a fake `aws` whose container has `environment` and `secrets`; the `--primary-container` sent back keeps `secrets` and changes only `image`
- [x] the guard still refuses an empty `environment`

### T3 — `deploy_ecs.sh` creates the service with secrets from Parameter Store
files: scripts/deploy_ecs.sh, tests/test_deploy_ecs_script.py, .env.production.example
depends_on:
verify: uv run pytest tests/test_deploy_ecs_script.py
- [x] the five go into `secrets` (`valueFrom` = the parameter ARN), never into `environment`; the script checks they exist (`aws ssm get-parameters --names`, names only) instead of reading `DB_PASSWORD` / `JWT_SECRET_KEY` from `.env`
- [x] `.env.production.example`: the five say they live in Parameter Store

### T4 — Docs
files: DEPLOYMENT.md, docs/ENVIRONMENT.md, docs/AWS_ECS_DEPLOYMENT.md, docs/setup_google_app.md
depends_on:
verify: uv run pytest tests/test_environment_reference.py
- [x] DEPLOYMENT.md § Secrets: the five parameters, the execution role's inline policy (JSON), how to read the live config (`environment` and `secrets`)
- [x] rotation runbooks for Parameter Store (`put-parameter --overwrite`, then a forced redeploy): JWT, a new MCP-key runbook, CloudFront's three steps, Google, DB
- [x] fix the old JWT runbook and the Shlink-import note that says the task definition carries `DB_PASSWORD`
- [x] docs/ENVIRONMENT.md: each secret's row says it's injected from Parameter Store; docs/AWS_ECS_DEPLOYMENT.md's commands show `secrets`

### T5 — Production (the coordinator, with the user's go-ahead)
files: _pm/ROADMAP.md
depends_on: T1, T2, T3, T4
verify: none
- [x] save the live container privately (`_exchange/`, 0600) for rollback; never print a value
- [x] create the five SecureString parameters: the three kept values copied through a 0600 temp file, the JWT and MCP keys generated with `openssl rand -hex 32` straight into the parameter
- [x] inline policy `shurly-read-parameters` on `ecsTaskExecutionRole` (`ssm:GetParameters` on `parameter/shurly/production/*`; `kms:Decrypt` via SSM if needed)
- [x] one `update-express-gateway-service` from the current container: the five move from `environment` to `secrets`; dry run with names only, refusing any other removal; wait for the rollout
- [x] `describe-express-gateway-service` shows `secrets` (ARNs) and the five aren't in `environment`
- [x] smoke: health, `go.griddo.io` links, `/mcp` 308/401, `client_ip_source` cloudfront in `http.request` lines (the user signing in again and reconnecting the MCP is theirs, after this)
- [x] deregister and delete every `default-shurly-api` revision but the active one
- [x] the next release's deploy keeps `secrets`; ROADMAP 6.3 records it all

## Verificación global
- [x] `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` green (2171 passed, PR #239)
- [x] production: `describe-express-gateway-service` has the five in `secrets` and none in `environment`; the app answers; old revisions gone

## Notas
- T5 has `verify: none`: it's AWS work checked by hand (the smoke above), not by a command in the repo.
- Rollback: put the five back in `environment` from the container saved in `_exchange/`, in one update. The rotated keys can't go back; everyone signs in again either way.
- Not Secrets Manager: no automatic rotation would be used (the app reads secrets only at startup), so Parameter Store does the same for free.

## Log
- 2026-10-17T19:38:28Z Daniel Serrano moved wip -> done
- 2026-10-17T19:38:28Z Daniel Serrano released
- 2026-10-17T19:38:28Z Daniel Serrano release #241 deployed td 48 (image d4ac5b06): the five stayed in secrets, none in environment; smoke green
- 2026-10-17T18:38:29Z Daniel Serrano T5 in production 2026-10-17: 5 SecureString parameters, shurly-read-parameters on ecsTaskExecutionRole, switch to secrets (td 47), smoke green (0 5xx, client_ip_source cloudfront), revisions 1-46 deleted. Left: the next release keeps secrets; the user signs in again and reconnects the MCP
- 2026-10-17T18:14:31Z Daniel Serrano wave 1 (T1-T4) done: 2171 passed, ruff clean; T5 (production) waits for the user's go-ahead after the PR merges
- 2026-10-17T17:51:53Z Daniel Serrano moved todo -> wip
- 2026-10-17T17:51:53Z Daniel Serrano claimed (lease 480m)
- 2026-10-17T17:51:09Z Daniel Serrano created
