---
id: epic_runbook
title: Runbook: backup, recovery and costs
type: epic
status: backlog
priority: medium
created: 2026-10-17
---

# Epic: Runbook: backup, recovery and costs

## Descripción
There's no tested way back if the database is lost, and no view of what Shurly costs.

## Requisitos
- Backup and recovery: RDS automated backups (7 days), a point-in-time restore rehearsed on a throwaway instance, and the steps written down
- Cost monitoring: what Shurly costs a month (ECS, RDS, ALB and its public IPs, CloudFront, CloudWatch), and a budget alert
- An architecture diagram and a database schema diagram (7.1)

## Notas
From ROADMAP 7.1 and 7.2. Shlink was removed on 2026-10-17, so its costs are gone (8.6).

## Log
- 2026-10-17T17:20:42Z Daniel Serrano created
