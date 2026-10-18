---
id: epic_drop-og-fetched-at
title: Drop urls.og_fetched_at (migration 0018)
type: epic
status: backlog
priority: low
created: 2026-10-18
---

# Epic: Drop urls.og_fetched_at (migration 0018)

## Descripción
The cleanup sweep (2026-10-18) stopped mapping `urls.og_fetched_at`, unwritten since 8.7. The column itself
stays one more release: the app migrates at startup, and the previous release's tasks, still serving during
the rollout, name every mapped column in their SELECTs, so dropping it now would fail every link query,
redirects included. Same path as `users.api_key` (unmapped in c440652, dropped by 0014).

**Start only once a release with the cleanup sweep is in production.**

## Requisitos
- [ ] migration 0018 (`down_revision = "0017"`, or the head then): `op.drop_column("urls", "og_fetched_at")`;
  the downgrade re-adds it as `DateTime(timezone=True)`, nullable, empty. It has no index. 0014 is the pattern.
- [ ] `tests/test_phase3141_migrations.py`: delete `_PENDING_DROP`, `_not_a_pending_drop`, `_what`,
  `test_the_pending_drop_is_still_pending` and `test_the_drift_check_ignores_nothing_else`
  (`test_the_pending_drop_is_still_pending` fails on its own once the column is gone)
- [ ] the migration tests on PostgreSQL (`TEST_DATABASE_URL`) green; CHANGELOG "Removed"

## Notas
- Fits as a one-task chore; no other code reads the column.

## Log
- 2026-10-18T13:23:02Z Daniel Serrano created
