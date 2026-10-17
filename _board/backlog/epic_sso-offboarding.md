---
id: epic_sso-offboarding
title: SSO-only login and offboarding
type: epic
status: backlog
priority: low
created: 2026-10-17
---

# Epic: SSO-only login and offboarding

## Descripción
Suspending someone in Google stops their Google sign-in, but a Shurly password and an API key keep working until
the account is deactivated in Shurly.

## Requisitos
- A setting to turn password login off for the organization (SSO enforced), keeping one break-glass account; the `auth.login` lines show who still uses a password
- An offboarding checklist: deactivate in Shurly, revoke the API key, what happens to MCP sign-ins and service accounts the person is responsible for
- Leaving Google some day: everyone sets a password while Google works, then Google sign-in goes off (document only)

## Notas
From ROADMAP 3.13.4.

## Log
- 2026-10-17T17:20:42Z Daniel Serrano created
