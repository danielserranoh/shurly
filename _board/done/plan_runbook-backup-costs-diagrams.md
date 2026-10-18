---
id: plan_runbook-backup-costs-diagrams
title: Runbook: backup, recovery, costs and diagrams
type: plan
status: done
priority: medium
created: 2026-10-18
started: 2026-10-18
completed: 2026-10-18
progress: 100
epic: epic_runbook
owner: null
claimed_at: null
lease_until: null
blocked_by: []
parallel_safe: true
worktree: null
---

# Plan: Runbook: backup, recovery, costs and diagrams

## Objetivo
A tested way back if the database is lost, Shurly's real monthly cost with a budget alert, and the architecture and
database-schema diagrams.

## Contexto
There's no tested way back if the database is lost, and no view of what Shurly costs. Found while planning (read-only,
2026-10-18):
- **The database:** `shurly-db` (db.t4g.micro, PostgreSQL 17.9, 20 GB gp3, encrypted, private).
  - Automated backups: 7 days, window 06:43–07:13 UTC, point-in-time restore available.
  - **Deletion protection is off**: a mistaken delete would also take the automated backups with it.
  - `CopyTagsToSnapshot` is off.
  - Its DB subnet group is named **`shlink-db-subnets`** (inherited from Shlink): it must not be deleted when cleaning Shlink leftovers.
- **Costs:**
  - `griddo-main` is the organization's management account and hosts much more than Shurly: about 3,800 $ a month across EC2, EKS, Amplify and more.
  - Shurly's share can't be read today. Tags are inconsistent (`Project=Shurly` on RDS and ECS, `service=shurly` on S3, none on CloudFront or the ALB), and no cost-allocation tag is active.
  - DEPLOYMENT.md § Cost estimation (941) says ~17 $, which is out of date: it counts the ALB as shared with Shlink. My estimate today is ~55–65 $.
- **Diagrams:** none beyond the ASCII sketches in DEPLOYMENT.md § Architecture and docs/AWS_ECS_DEPLOYMENT.md. There's a precedent for a generated doc kept honest by a test: `scripts/generate_timezones.py` with `tests/test_phase312_profile.py:225`.

Decided with the user (2026-10-18):
- a budget alert at **80 $/month**;
- backup retention **stays 7 days**.

## Tareas

### T1 — Database schema diagram, generated
files: scripts/generate_schema_diagram.py, docs/DATABASE_SCHEMA.md, tests/test_schema_diagram.py
depends_on:
verify: uv run pytest tests/test_schema_diagram.py
- [x] the script renders a Mermaid `erDiagram` from SQLAlchemy's metadata (`server/core/models`): tables, columns with type and PK/FK/nullable marks, and relationships from the foreign keys
- [x] `docs/DATABASE_SCHEMA.md`: a short intro, the generated diagram between markers, and how to regenerate it
- [x] the test fails when the committed diagram differs from what the models generate (like the timezones test)

### T2 — Architecture diagram
files: docs/ARCHITECTURE.md
depends_on:
verify: none
- [x] a Mermaid diagram, with one short paragraph per box:
  - DNS (Route 53 in griddo-production);
  - CloudFront → S3 frontend and → ALB for the API;
  - the shared ALB with its rules (shurly.griddo.io, go.griddo.io, links.griddo.io redirect);
  - ECS Express `shurly-api` (Fargate);
  - RDS `shurly-db`;
  - SSM Parameter Store (secrets);
  - CloudWatch logs, alarms, dashboard and SNS;
  - ECR;
  - GitHub Actions (OIDC deploy roles);
  - Google OAuth;
  - MCP clients (claude.ai, Claude Code)
- [x] the request paths: a short-link redirect, the web app, the API and the MCP

### T3 — The runbook in DEPLOYMENT.md
files: DEPLOYMENT.md, README.md
depends_on:
verify: none
- [x] § Backup and recovery:
  - what's backed up and for how long;
  - point-in-time restore as copy-paste steps, to a new instance in the same subnet group and security group;
  - checking the restored data with a one-off psql task;
  - two ways back: point the service at the restored instance (`DB_HOST`, then a redeploy), or rename;
  - deleting the test instance;
  - the measured times, filled in by T4;
  - a warning that `shlink-db-subnets` is in use
- [x] § Cost estimation, rewritten:
  - the real components (the ALB and its 3 public IPv4s are Shurly's alone now; CloudFront and S3 frontend; Parameter Store free; alarms);
  - how to read Shurly's real cost (the `Project=Shurly` tag in Cost Explorer);
  - the budget and its alerts;
  - what the tag can't capture (shared data transfer)
- [x] links to docs/ARCHITECTURE.md and docs/DATABASE_SCHEMA.md from DEPLOYMENT.md § Architecture and from README.md

### T4 — Production (the coordinator, with the user's go-ahead)
files: _pm/ROADMAP.md
depends_on: T1, T2, T3
verify: none
- [x] `shurly-db`: turn on deletion protection and copy tags to snapshots (`modify-db-instance --apply-immediately`, no downtime)
- [x] tag every Shurly resource `Project=Shurly`: the CloudFront distribution, the S3 frontend bucket, the ALB and its target groups, the ECR repo, the log group, the SNS topic, the SSM parameters and the alarms
- [x] activate `Project` as a cost-allocation tag (Cost Explorer; data starts from activation, up to 24 h)
- [x] AWS Budgets `shurly-monthly`: 80 $ a month filtered on `Project=Shurly`, emailing daniel.serrano@griddo.io at 80 % actual and at 100 % forecasted
- [x] **restore rehearsal:**
  - point-in-time restore to `shurly-db-restore-test`;
  - check row counts against production with a one-off psql task;
  - time each step;
  - delete it with no final snapshot
- [x] DEPLOYMENT.md gets the measured times; ROADMAP 7.1 and 7.2 record it

## Verificación global
- [x] `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` green
- [x] production: deletion protection on, tags and budget in place, a restore rehearsed and timed

## Notas
- **Cost of the rehearsal:** a few hours of a db.t4g.micro, cents.
- **Cost of the budget:** the first 2 budgets are free.
- **What doesn't change:** none of T4's changes touch the running service or need a redeploy.
- **Retention:** stays 7 days, the user's call.
- T2, T3 and T4 have `verify: none`: docs, and AWS work checked by hand.

## Log
- 2026-10-18T00:25:08Z Daniel Serrano moved wip -> done
- 2026-10-18T00:25:08Z Daniel Serrano released
- 2026-10-18T00:25:08Z Daniel Serrano T4 in production 2026-10-17/18: deletion protection and copy-tags on shurly-db; Project=Shurly on every resource; Project active as cost-allocation tag; budget shurly-monthly 80 USD; restore rehearsal usable in 8m19s, data identical, deleted. Times in DEPLOYMENT § Backup and recovery
- 2026-10-17T23:29:10Z Daniel Serrano wave 1 done (T1-T3) plus stale-passage fixes in DEPLOYMENT, AWS_ECS_DEPLOYMENT and ARCHITECTURE; T4 waits for the user's go-ahead
- 2026-10-17T23:12:40Z Daniel Serrano moved todo -> wip
- 2026-10-17T23:12:39Z Daniel Serrano claimed (lease 480m)
- 2026-10-17T23:12:39Z Daniel Serrano created
