---
id: epic_service-accounts-v2
title: Service accounts v2
type: epic
status: backlog
priority: low
created: 2026-10-17
---

# Epic: Service accounts v2

## Descripción
v1 shipped on 2026-10-17 (ROADMAP 10.1, `_pm/spec_service_accounts.md`). These wait until Propuestas has used it.

## Requisitos
- A queryable audit table with its API, kept 2 years (and its docs/PERSONAL_DATA.md entry)
- Fine-grained scopes (`urls:read`, `urls:write`, `urls:delete`, `tags:write`, `analytics:read`, `act_on_behalf`)
- A rate limit per token, with `RateLimit-*` headers and 429 `Retry-After`
- Warnings before a token expires and after 90 days unused; then a default expiry
- Allowed IP ranges per token
- Hand links Propuestas made with a person's API key over to its service account

## Notas
From ROADMAP 10.1 and the spec's "v2, not now".

## Log
- 2026-10-17T17:20:42Z Daniel Serrano created
