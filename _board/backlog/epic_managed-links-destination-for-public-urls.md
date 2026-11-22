---
id: epic_managed-links-destination-for-public-urls
title: Idea — show the destination of managed links whose URL carries no credential
type: epic
status: backlog
priority: low
created: 2026-11-22
---

# Epic: Idea — show the destination of managed links whose URL carries no credential

> **An idea, not a commitment.** Before planning anything, confirm that the hidden destination is a
> real usability problem for the people who use Content Factory's links. If nobody misses it, close this card.

## Descripción
Phase 10.3 (`epic_service-managed-links`, R5) hides the destination of a managed link from everyone
except owners and the managing service account. That is right for Propuestas: its destination
carries the proposal's access token, a credential.

Since content-factory 1.44.0, Content Factory also creates links with a service account, on behalf
of the person who owns the LinkedIn channel. The link goes in the first comment of a post. Its
destination is a public Journal URL with UTMs, with nothing secret in it. Those links are managed
too, so the person they were made for (and anyone who isn't an owner) sees the short link but not
where it goes.

## Requisitos
- First, evidence: someone in the team needed to see where a Content Factory link goes and
  couldn't (for example, to check the UTMs, or to tell two links apart).
- Only if that's confirmed: the destination of a managed link is visible to the organization when
  it carries no credential. Propuestas' links stay masked.

## Fuera de alcance
- Changing how Propuestas' links are protected (masking, edit lock, owner override).
- The edit lock (R3) on Content Factory's links: hiding the destination is the only thing in question.

## Notas
- Possible shapes, to decide only if this goes ahead:
  - a setting on the service account (`mask_destination`);
  - or a flag the client sends when it creates the link.
  Per service account is simpler and matches how each integration behaves.
- Content Factory side: `app/api/cfapi/shortener.py` (`POST /urls` with `X-Shurly-On-Behalf-Of`).
- Daniel Serrano, 22/11/2026: note it as an idea. No new development until we've seen whether it's a
  real usability problem.

## Log
- 2026-11-22T17:42:05Z Daniel Serrano created
