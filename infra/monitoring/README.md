# Monitoring definitions

Shurly's alerting and dashboard in production (griddo-main, `eu-south-2`), as files. They're applied by
`scripts/setup_monitoring.sh`, which is idempotent, so a change here goes to AWS by running the script again,
not by clicking in the console. The runbook, the cost and the operator's permissions are in
`DEPLOYMENT.md` § Error alerting.

`tests/test_monitoring_definitions.py` checks these files: the filter patterns against sample log lines, each
alarm's threshold, period and actions, the dashboard's metrics, the saved queries' names.

## The files

| File | What it is | How the script applies it |
|---|---|---|
| `metric-filters.json` | The four metric filters on the task's log group. Each counts matching log lines as a metric in namespace `Shurly`: value `1` per line, `0` when none | Each object is `aws logs put-metric-filter --cli-input-json` |
| `alarms.json` | The six alarms. Each emails the SNS topic `shurly-alerts` when it fires (ALARM) and when it recovers (OK); missing data doesn't breach | Each object is `aws cloudwatch put-metric-alarm --cli-input-json` |
| `dashboard.json` | The dashboard `shurly`: ECS, ALB, RDS, the four `Shurly` metrics, and three Logs Insights widgets (redirect latency on `go.griddo.io`, MCP tool calls vs API requests, top 5xx paths) | The whole file is the `--dashboard-body` of `aws cloudwatch put-dashboard --dashboard-name shurly` |
| `queries.json` | The saved Logs Insights queries, `{name, queryString}`, in folder `shurly/` | One `aws logs put-query-definition` each, on the log group; by its id when one with the same name exists |

The metric filters:

| Filter | Pattern | Metric | Alarm |
|---|---|---|---|
| `shurly-5xx` | `{ $.event = "http.request" && $.status >= 500 }` | `ApiErrors5xx` | `shurly-api-5xx` |
| `shurly-rate-limit-store` | `{ $.event = "rate_limit.store_failed" }` | `RateLimitStoreFailures` | `shurly-rate-limit-store` |
| `shurly-client-errors` | `{ $.event = "client.error" }` | `ClientErrors` | `shurly-client-errors` |
| `shurly-mcp-tool-errors` | `{ $.event = "mcp.tool_call" && $.outcome = "error" }` | `McpToolErrors` | none: it counts invalid input too, a 4xx, so it's on the dashboard only |

The alarms:

| Alarm | Fires when |
|---|---|
| `shurly-api-5xx` | `ApiErrors5xx` sums ≥ 5 in 5 minutes |
| `shurly-rate-limit-store` | `RateLimitStoreFailures` sums ≥ 1 in 5 minutes |
| `shurly-client-errors` | `ClientErrors` sums ≥ 10 in 15 minutes |
| `shurly-alb-5xx` | the ALB's own `HTTPCode_ELB_5XX_Count` sums ≥ 5 in 5 minutes. The ALB is shared, so this counts the whole ALB |
| `shurly-no-healthy-target` | `SUM([tg1, tg2])` of the two target groups' `HealthyHostCount` (each the minute's maximum) is < 1 for 3 one-minute periods in a row. Express deploys blue/green between those two, so either can be the live one |
| `shurly-db-storage-low` | RDS `FreeStorageSpace` (the 5 minutes' minimum) is < 2 GiB, 2147483648 bytes |

Each alarm's description, in Spanish, says what it means and what to check first, and ends with
"Runbook: DEPLOYMENT.md § Error alerting": it's the text of the email.

The queries are copied as they are from `mcp_server/README.md` § Usage log and `DEPLOYMENT.md` (§ Error alerting,
§ What the web app is used for, the client IP source, § Geolocation data, the sign-in events). When one changes
there, change it here too.

## Placeholders

The files name no account-specific resource. The script finds each one, then replaces the placeholder before it
calls AWS. A lookup that finds nothing stops the script.

| Placeholder | What it becomes | Used in |
|---|---|---|
| `${LOG_GROUP}` | The task's log group, `/aws/ecs/default/shurly-api-5fdb` | the filters' `logGroupName`, the dashboard's Logs Insights widgets (`SOURCE '${LOG_GROUP}'`) |
| `${TOPIC_ARN}` | The ARN of the SNS topic `shurly-alerts`, created or found by the script | every alarm's `AlarmActions` and `OKActions` |
| `${ALB}` | The ALB's dimension value, `app/<name>/<id>` (the end of its ARN) | `shurly-alb-5xx`, `shurly-no-healthy-target`, the dashboard's ALB widgets |
| `${TG_1}`, `${TG_2}` | The service's two target groups' dimension values, `targetgroup/<name>/<id>` | `shurly-no-healthy-target`, the dashboard's target-group widgets |
| `${DB}` | The RDS instance identifier | `shurly-db-storage-low`, the dashboard's RDS widgets |

No other placeholder may appear: the test fails on one.

## Changing a threshold

1. Change it in `alarms.json`: `Threshold`, and `Period` / `EvaluationPeriods` / `DatapointsToAlarm` for the
   window (for `shurly-no-healthy-target`, the `Period` inside each `MetricStat`).
2. Change the same numbers in the `ALARMS` table of `tests/test_monitoring_definitions.py`, the alarm's
   description if it quotes them, the dashboard's label or annotation that quotes them, and the tables in this
   README and in `DEPLOYMENT.md` § Error alerting.
3. `uv run pytest tests/test_monitoring_definitions.py`.
4. Run `scripts/setup_monitoring.sh` (a dry run lists what would change), then with `--for-real`.
   `put-metric-alarm` replaces the alarm in place, keeping its name.

A new filter or alarm goes the same way: the file, the test's tables, this README, then the script. Keep the
alarms within CloudWatch's free 10.
