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

## Notas
From ROADMAP 3.7.7, 3.9.2, 3.10.8, 5.2, 5.7, 8.7 and 9.1.

## Log
- 2026-10-17T17:20:42Z Daniel Serrano created
