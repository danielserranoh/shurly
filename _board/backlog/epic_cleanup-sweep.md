---
id: epic_cleanup-sweep
title: Cleanup sweep
type: epic
status: backlog
priority: medium
created: 2026-10-17
---

# Epic: Cleanup sweep

## Descripción
Small, well-understood leftovers from earlier phases. Each can be a chore of its own once planned.

## Requisitos
- Drop `urls.og_fetched_at` (unused since migration 0015; several releases since, so the previous release no longer writes it) (8.7)
- Delete waitlist entries past 12 months by themselves: a startup or scheduled job (9.1)
- Delete expired links: the deferred `delete-expired` job (3.9.2)
- Campaign links fetch their page's preview when the campaign is made (8.7)
- Re-fetch stale page previews now and then (8.7)
- A custom-preview badge on link cards (3.7.7, 3.10.8)
- MCP: an MCP round-trip test for the auto-generated tools (5.2, 5.7), "how to add a tool" in mcp_server/README.md, and a CHANGELOG entry for the MCP surface (5.7)
- `docs/ENVIRONMENT.md` says list settings (`CORS_ORIGINS`, `TRUSTED_PROXIES`, `MCP_OAUTH_ALLOWED_REDIRECT_URIS`, `CLOUDFRONT_ORIGIN_SECRETS`) take comma-separated values; from an environment variable pydantic-settings parses JSON first and raises `SettingsError` (found 2026-10-17). Fix the code or the doc
- `scripts/create_rds.sh` prints the generated DB password to the terminal and says to save it in Secrets Manager: write it straight to Parameter Store (`/shurly/production/DB_PASSWORD`) instead (found 2026-10-17)
- `scripts/deploy_ecs.sh` prints `curl https://${SERVICE_NAME}.ecs.${REGION}.on.aws/api/v1/health` as its next step; Express hosts are opaque (`sh-<hex>…`): read it from `describe-express-gateway-service` as DEPLOYMENT.md § 4 now does (found 2026-10-18)
- `tests/test_client_ip_source.py` points to "DEPLOYMENT.md § Monitoring", which doesn't exist (found 2026-10-18)

## Notas
From ROADMAP 3.7.7, 3.9.2, 3.10.8, 5.2, 5.7, 8.7 and 9.1.

## Log
- 2026-10-17T17:20:42Z Daniel Serrano created
