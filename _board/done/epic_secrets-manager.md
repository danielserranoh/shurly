---
id: epic_secrets-manager
title: Secrets in Secrets Manager
type: epic
status: done
priority: high
created: 2026-10-17
completed: 2026-10-17
---

# Epic: Secrets in Secrets Manager

## Descripción
The DB password, the JWT secret, the Google OAuth client secret, the MCP OAuth signing key and the CloudFront origin
secret are plain environment variables on the ECS service: anyone who can read the task definition reads them.

## Requisitos
- Move them to Secrets Manager (`secrets` in the container definition, read by the execution role), one by one, with no downtime
- Rotate the JWT secret and the MCP signing key on the way (both runbooks exist in DEPLOYMENT.md)
- The deploy keeps working: it only swaps the image (memory: production settings live on the live ECS service)
- DEPLOYMENT.md: where each secret lives and how to rotate it

## Notas
From ROADMAP 6.3 (Environment secrets audit, the Google client secret). Production change: needs the user's go-ahead.

## Log
- 2026-10-17T17:51:45Z Daniel Serrano moved backlog -> done
- 2026-10-17T17:20:42Z Daniel Serrano created
