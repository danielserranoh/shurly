---
id: epic_redirect-performance
title: Redirect and analytics performance
type: epic
status: backlog
priority: low
created: 2026-10-17
---

# Epic: Redirect and analytics performance

## Descripción
Nothing is slow today. These are the measurements and options to revisit once volumes grow.

## Requisitos
- Measure the analytics queries on real volumes and decide on a composite index on `visits` (`(url_id, visited_at)`) (3.12.8, 6.2)
- Database indexes review (6.2)
- A caching strategy for the redirect path: CloudFront in front of the ALB, or none (6.2)
- Only if parsing at query time gets slow: store parsed user-agent fields on `visits`, with a backfill (3.16.2)

## Notas
From ROADMAP 3.12.8, 3.16.2 and 6.2. Measured 2026-09-29: 6–12 ms per link at 10k visits, no index needed then.

## Log
- 2026-10-17T17:20:42Z Daniel Serrano created
