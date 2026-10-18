---
id: plan_alerting-and-monitoring
title: Alerting and monitoring
type: plan
status: done
priority: high
created: 2026-10-17
started: 2026-10-17
completed: 2026-10-17
progress: 100
epic: epic_alerting
owner: null
claimed_at: null
lease_until: null
blocked_by: []
parallel_safe: true
worktree: null
---

# Plan: Alerting and monitoring

## Objetivo
Alarms by email (SNS → daniel.serrano@griddo.io) when production fails, a key-metrics dashboard, the saved Logs
Insights queries, and the MCP-vs-API latency measured. Reproducible from `infra/monitoring/` with
`scripts/setup_monitoring.sh`, not clicked.

## Contexto
Nobody hears about it when production fails. ROADMAP 6.4 required alerting before the Shlink cutover; it never happened.
The groundwork exists:
- every request logs a single-line JSON `http.request` on stderr (`main.py:48-57`, `server/utils/event_log.py:18-25`), with `status`, `path`, `host`, `duration_ms`;
- the web app reports `client.error`; rate-limit store failures log `rate_limit.store_failed`; MCP calls log `mcp.tool_call`;
- DEPLOYMENT.md § Error alerting (1277-1320) already fixes the filter patterns and thresholds, and the queries to save live in DEPLOYMENT.md (1322-1346, 848, 1138, 1399) and mcp_server/README.md (472-511).

AWS today: no SNS topic, no metric filters, no dashboard, no saved queries. Three alarms exist, all ECS-managed (autoscaling, canary rollback): untouched.

Decided with the user (2026-10-17): Amazon SNS email, to **daniel.serrano@griddo.io**; ~0–1 $/month.

## Design
Reproducible, not clicked: definitions as JSON in `infra/monitoring/`, applied by an idempotent `scripts/setup_monitoring.sh` (dry run by default, `--for-real` with typed confirmation, like `scripts/run_promote_domain.sh`), tested against a fake `aws` (like `tests/test_run_shlink_import.py`).

- **SNS topic** `shurly-alerts`, email subscription (AWS sends a confirmation email the user must accept once).
- **Metric filters** on `/aws/ecs/default/shurly-api-5fdb`, namespace `Shurly`, value 1, default 0:
  - `shurly-5xx`, from `{ $.event = "http.request" && $.status >= 500 }`;
  - `shurly-rate-limit-store`, from `{ $.event = "rate_limit.store_failed" }`;
  - `shurly-client-errors`, from `{ $.event = "client.error" }`;
  - `shurly-mcp-tool-errors`, from `{ $.event = "mcp.tool_call" && $.outcome = "error" }`, for the dashboard only.
- **Alarms** (6, inside the free 10), each notifying on ALARM **and on OK** (recovery), with a Spanish description that says what it means and points to the runbook:

  | Alarm | Condition |
  |---|---|
  | `shurly-api-5xx` | ≥ 5 in 5 min |
  | `shurly-rate-limit-store` | ≥ 1 in 5 min |
  | `shurly-client-errors` | ≥ 10 in 15 min |
  | `shurly-alb-5xx` | ALB `HTTPCode_ELB_5XX_Count` ≥ 5 in 5 min (a task that doesn't answer) |
  | `shurly-no-healthy-target` | the sum of `HealthyHostCount` over the service's two target groups (Express blue/green) < 1 for 3 min |
  | `shurly-db-storage-low` | RDS `FreeStorageSpace` < 2 GB |

  Missing data is "not breaching". The script discovers the ALB, the target groups and the RDS id instead of hard-coding them.
- **Dashboard** `shurly`:
  - ECS CPU and memory;
  - ALB 5xx, healthy hosts and target response time;
  - RDS connections, CPU and free storage;
  - the four `Shurly` metrics;
  - Logs Insights widgets, with no extra metrics: redirect latency p50/p95 for `host = go.griddo.io`, and **MCP vs API latency** (path `/mcp/` against `/api/v1/`), which closes ROADMAP 5.7's "never measured".
- **Saved Logs Insights queries**, folder `shurly/`:
  - the 5 MCP usage queries;
  - the 3 web-app usage queries;
  - client errors;
  - 5xx by path;
  - client IP source per host;
  - geo database events;
  - logins by method.
- **Testing an alarm:** `--test-alarm <name>` runs `set-alarm-state ALARM`, so a real email arrives, and the alarm returns to OK at its next evaluation.

## Tareas

### T1 — Monitoring definitions
files: infra/monitoring/metric-filters.json, infra/monitoring/alarms.json, infra/monitoring/dashboard.json, infra/monitoring/queries.json, infra/monitoring/README.md, tests/test_monitoring_definitions.py
depends_on:
verify: uv run pytest tests/test_monitoring_definitions.py
- [x] the four files above, with placeholders for discovered values (`${ALB}`, `${TG_1}`, `${TG_2}`, `${DB}`, `${LOG_GROUP}`, `${TOPIC_ARN}`)
- [x] the test checks:
  - they're valid JSON;
  - filter patterns match real sample log lines (a matching and a non-matching one each);
  - each alarm's threshold, period and SNS actions (ALARM and OK);
  - every dashboard metric exists in some definition or is an AWS one;
  - query names are unique and under `shurly/`

### T2 — `scripts/setup_monitoring.sh`
files: scripts/setup_monitoring.sh, tests/test_setup_monitoring.py
depends_on: T1
verify: uv run pytest tests/test_setup_monitoring.py
- [x] idempotent:
  - create the topic, or find it;
  - subscribe the email only if not already subscribed;
  - `put-metric-filter`, `put-metric-alarm` and `put-dashboard` (upserts);
  - `put-query-definition`, updating by id when the name exists
- [x] dry run by default, listing what would change; `--for-real` asks to type the region; `--test-alarm NAME`; `ALERT_EMAIL` defaults to daniel.serrano@griddo.io
- [x] tests with a fake `aws` and credential isolation:
  - a dry run makes no write call;
  - a second run creates nothing new;
  - discovery feeds the dimensions;
  - a failed lookup stops the script

### T3 — Docs
files: DEPLOYMENT.md, mcp_server/README.md, docs/AWS_ECS_DEPLOYMENT.md
depends_on:
verify: none
- [x] DEPLOYMENT.md § Error alerting, from stub to the real setup:
  - the alarms table, what each means and what to do;
  - running the script;
  - testing an alarm;
  - the operator's IAM permissions;
  - the cost
- [x] mcp_server/README.md § Usage log: the queries are saved by the script; fix the example line (it lacks `host` and `client_ip_source`)
- [x] the troubleshooting catalog links the alarms' runbook

### T4 — Production (the coordinator, with the user's go-ahead)
files: _pm/ROADMAP.md
depends_on: T1, T2, T3
verify: none
- [x] dry run, then `--for-real`
- [x] the user confirms the SNS subscription email
- [x] `--test-alarm shurly-api-5xx`: the email arrives, then the OK one
- [x] the dashboard shows data; the saved queries run
- [x] ROADMAP 6.4, 5.6 and 5.7 record it

## Verificación global
- [x] `uv run pytest` and `uv run ruff check . && uv run ruff format --check .` green
- [x] production: a test alarm sends its email, and its OK email; the dashboard shows data

## Notas
- T3 has `verify: none` (docs), and T4 too (AWS work checked by hand, with a real test email).
- Cost ~0–1 $/month: 6 alarms and 4 custom metrics within the free tier, SNS email free under 1,000/month, 1 dashboard free.

## Log
- 2026-10-17T20:44:32Z Daniel Serrano moved wip -> done
- 2026-10-17T20:44:32Z Daniel Serrano released
- 2026-10-17T20:44:31Z Daniel Serrano T4 in production 2026-10-17: applied --for-real; subscription confirmed by the user; test alarm OK→ALARM→OK, three SNS actions sent; a second dry run creates nothing; MCP vs API measured (ROADMAP 5.7). 2259 passed (PR #243)
- 2026-10-17T20:24:58Z Daniel Serrano waves 1-2 done (T1, T3, T2): 2259 passed, ruff clean. Fixed by the coordinator: the MCP latency widget (http.request /mcp/ lines are written when the stream opens; now mcp.tool_call), and the query-prefix bug a real dry run found (AWS refuses a prefix ending in /). Real dry run green. T4 waits for the user's go-ahead
- 2026-10-17T20:07:01Z Daniel Serrano moved todo -> wip
- 2026-10-17T20:07:01Z Daniel Serrano claimed (lease 480m)
- 2026-10-17T20:07:00Z Daniel Serrano created
