---
id: epic_invitations-email
title: Invitations and email
type: epic
status: backlog
priority: medium
created: 2026-10-17
---

# Epic: Invitations and email

## Descripción
Today the only way in is Google Workspace sign-in for griddo.io. Inviting someone, resetting a forgotten password
by email, and telling the waitlist there's a place all need email.

## Requisitos
- Amazon SES in `griddo-main`: verify the sender domain (DKIM in the `griddo.io` zone, `griddo-production`), agree the sender with Griddo's mail admin (SPF/DMARC), request production access; a task role with `ses:SendEmail`
- `server/utils/email.py` with a `console` backend for dev and tests; Jinja2 templates
- Invitations: an owner or admin invites an email → a single-use link (≥32 random bytes, stored hashed, with an expiry); opening it changes nothing, so mail scanners can't activate it
- Password reset by email, on the same tokens
- Rate limits on invitations, resends and resets
- Decide the role an external gets, and what they see (maybe a guest role)
- Tell the people on the waitlist when there's a place (9.1)

## Notas
From ROADMAP 3.14.7 (Externals) and 9.1. Without SES, the ROADMAP lists two fallbacks: a copyable invitation link, or opening Google sign-in to external accounts with an allow-list.

## Log
- 2026-10-17T17:20:42Z Daniel Serrano created
