---
id: epic_alerting
title: Alerting and monitoring
type: epic
status: backlog
priority: high
created: 2026-10-17
---

# Epic: Alerting and monitoring

## Descripción
Nobody hears about it when production fails. ROADMAP 6.4 required error alerting before the Shlink cutover (8.5);
the cutover happened on 2026-10-02 without it. The groundwork is done: `http.request` lines carry the status, the
web app reports its errors as `client.error` lines, and `DEPLOYMENT.md` § Error alerting describes what to count.

## Requisitos
- CloudWatch metric filters on the service's log group (`/aws/ecs/default/shurly-api-5fdb`): 5xx `http.request` lines, `client.error` lines
- Alarms on them, plus ALB 5xx and unhealthy targets, to an SNS topic with an email subscription (the address is the user's call)
- A key metrics dashboard: ECS task count, CPU and memory; ALB 5xx and target health; RDS connections; redirect latency
- Save the dogfood's CloudWatch Logs Insights queries (5.6, the commands in DEPLOYMENT.md)
- Measure the MCP endpoint's latency against the API's (5.7: same task and ALB rule, never measured)
- DEPLOYMENT.md § Error alerting: from runbook stub to the real setup, and how to test an alarm

## Notas
From ROADMAP 6.4 (Error alerting, Key metrics dashboard), 5.6 (save the queries) and 5.7 (MCP SLO). AWS changes need the user's go-ahead, as every production change.

## Log
- 2026-10-17T17:20:13Z Daniel Serrano created
