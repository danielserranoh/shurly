---
id: plan_managed-links-propuestas
title: Links managed by their service account (Propuestas)
type: plan
status: done
priority: high
created: 2026-10-19
started: 2026-10-19
completed: 2026-10-19
progress: 100
origin: epic_service-managed-links
owner: null
claimed_at: null
lease_until: null
blocked_by: []
parallel_safe: true
worktree: null
---

# Plan: Links managed by their service account (Propuestas)

## Objetivo
Links made through a service account are managed by it: read-only for people (tags aside), deletable only by the
account or an owner's audited override, destination masked for all but owners and the account, shown in their own tab.

## Contexto
Griddo Propuestas creates a short link per proposal recipient through its service account. Today any member can delete or edit those links in Shurly without Propuestas knowing (dead links, `revoke_link` failing on manual copies), and anyone can read the destination, which carries the proposal's access token. The epic makes such links **managed by their service account**: read-only for people (tags aside), deletable only by the account or an owner's audited override, destination masked, shown in their own tab. Propuestas' side is a separate ticket (`_exchange/issue-shurly-managed-links.md`).

**User decisions:**
- **Which links:** a link made through a service account is managed by it. This is derived from `urls.via_service_account_id`, so there is no new column and no migration. The 3 Propuestas links in production already qualify.
- **Tabs:** `Links | Campaign links | <service account name>`, with no "All" and no "Made via" dropdown.
- **Full destination:** owners and the managing service account see it; everyone else sees a mask.
- **Override:** owners only, with a required reason stored in the audit.
- **Delete only:** the override deletes; it doesn't edit.
- **Edits:** people may change tags and nothing else.
- **Campaign links** made by a service account stay campaign links, not managed.
- **`GET /urls` with no filter** still returns everything, managed links masked, because the API is versioned. The app asks for "exclude managed" or "only account X".

**My calls, within those decisions:**
- **Managed** means `via_service_account_id IS NOT NULL AND url_type != campaign`.
  - The **owner** is an owner of the link's organization.
  - The **manager** is the caller whose id equals `via_service_account_id`.
  - A **removed** service account's links stay managed, so only the override deletes them.
- **The mask** keeps the scheme and host and hides the path and query: `https://propuestas.griddo.io/…`.
  - It applies to every surface that returns a destination: the link responses, the overview's `top_urls`, the curated `get_url_analytics_summary`, the admin-only `GET /service-accounts/{id}/links`, and redirect-rule targets.
  - Search (`q`) doesn't match the destination of a link whose destination the caller can't see.
- **The override** is a dedicated `POST /api/v1/urls/{code}/override-delete {reason}`:
  - owner only; refused to service tokens; excluded from the MCP, so an assistant can't be talked into it;
  - it writes an audit row: `service_account_id` = the manager, `actor_id` = the owner, `target_type` url, action `url.deleted`, detail `{override: true, reason}`. The reason is the one free-text exception to the audit's ids-only rule, documented in PERSONAL_DATA.
- **Tabs are built from a new `GET /api/v1/urls/managers`:** the service accounts managing links the caller can see, with their counts. Members need it too, since they can't list service accounts.
  - A tab shows only when its count is above 0.
  - The tabs are the existing `.segmented` radiogroup, scrolling sideways at narrow widths, as analytics already does.
- **List params:** a new optional `managed=exclude|only` and `managed_by=<id>`.
  - Legacy `?type=all` lands on Links, and `?via_service_account=<id>` opens that tab.
  - The dashboard KPIs keep counting managed links and clicks, and `loadStats` no longer mislabels them as campaign links.

Checked against the repo rules: there's no migration, and the API changes are additive (new optional params, a new field `managed_by`, new routes). Each new route gets its PERSONAL_DATA row, its `service_scopes` entry, and its MCP name or exclusion. The new 403 `managed_link_protected` only reaches people. The service account keeps everything it does today (Propuestas' ticket).

## Tareas

### T1 — The rule, in one place
files: server/utils/managed.py, server/utils/access.py, server/utils/errors.py, tests/test_phase103_managed_rule.py
depends_on:
verify: uv run pytest tests/test_phase103_managed_rule.py tests/test_urls.py tests/test_phase101_service_accounts.py
- [x] `managed.py` provides:
  - `is_managed(url)` and `manager_id(url)`;
  - `sees_destination(viewer, url)`: true for an owner of the link's organization or the manager;
  - `masked(url_str)`: scheme and host, then `…`;
  - `ensure_may_change(viewer, url)`, which raises 403 `managed_link_protected` with a message pointing to the integration;
  - also `is_manager`, `destination_for(viewer, url)`, `protected_error(url)` / `protected_message(url)`, and the SQL `managed_clause()` / `not_managed_clause()`.
- [x] `access.py`:
  - `Viewer.can_change` / `ensure_can_change` and `visible_url_or_404(to_change=…)` learn the managed rule. Only the manager changes a managed link's locked fields.
  - A separate tags path keeps today's rule (creator, admin, owner, the manager): `can_change_tags`, `ensure_can_change_tags`, `visible_url_or_404(to_change="tags")`.
- [x] `errors.py`: the code.
- [x] Unit tests for each role (member, creator, admin, owner, manager, another service account), a removed manager, and campaign links not managed.

### T2 — Routes: enforcement, masking, list, override
files: server/app/urls.py, server/schemas/url.py, server/utils/audit.py, server/utils/service_scopes.py, mcp_server/server.py, tests/test_phase52_mcp_tools.py, docs/PERSONAL_DATA.md, tests/test_phase103_managed_api.py, tests/test_phase101_service_accounts.py, tests/test_mcp_output_dates.py, server/utils/url.py, tests/test_phase84_app_paths.py
depends_on: T1
verify: uv run pytest tests/test_phase103_managed_api.py tests/test_phase101_service_accounts.py tests/test_phase102_token_enforcement.py tests/test_phase102_audit.py tests/test_urls.py tests/test_personal_data_inventory.py tests/test_phase52_mcp_tools.py tests/test_mcp_roundtrip.py --require-mcp
- [x] **Enforcement:** DELETE, PATCH, the rules (create, update, delete) and refresh-preview use the locked path. PATCH tags and bulk tags use the tags path; bulk tags reports skipped links if any.
- [x] **Responses:**
  - `URLResponse` gains `managed_by: {id, display_name} | null`;
  - `_to_url_response` takes the viewer and masks `original_url` when it must;
  - rule `target_url`s are masked too;
  - search `q` skips masked destinations.
- [x] **The list** gets `managed=exclude|only` and `managed_by=<uuid>`. No filter means everything, as today.
- [x] **`GET /api/v1/urls/managers`:** declared before `/{short_code}`; the scope `urls:read`; an MCP name or exclusion; a PERSONAL_DATA row.
- [x] **`POST /api/v1/urls/{short_code}/override-delete` `{reason}`:**
  - reason 10–500 characters;
  - owner only, refused to service tokens (`NOT_FOR_SERVICES`), excluded from the MCP, a PERSONAL_DATA row;
  - `audit.record_override(...)` writes the row in the same transaction;
  - `db.delete(link)`, so visits cascade.
- [x] **Tests:** every role on every route, masking per role, the list params, the managers counts, the override and its audit row, and the Propuestas-like account still doing everything it did in v1.

### T3 — The other surfaces that show a destination
files: server/app/analytics.py, server/app/service_accounts.py, mcp_server/curated.py, tests/test_phase103_managed_surfaces.py
depends_on: T1
verify: uv run pytest tests/test_phase103_managed_surfaces.py tests/test_phase53_curated_tools.py tests/test_phase101_service_accounts.py --require-mcp
- [x] Mask the overview's `top_urls`, the admin `GET /service-accounts/{id}/links`, and the curated `get_url_analytics_summary`.
- [x] The curated `add_redirect_rule` respects the locked path.
- [x] The KPI totals still count managed links and clicks; add a test that they're unchanged.

### T4 — The list: tabs, cards
files: frontend/src/pages/dashboard/index.astro, frontend/src/utils/links.ts, frontend/src/utils/types.ts, frontend/src/components/settings/ServiceAccountsSection.astro, frontend/tests/managed-links.test.mjs, frontend/e2e/service-accounts.spec.ts
depends_on: T2, T3
verify: cd frontend && npm test && npm run build
- [x] **Tabs:**
  - `Links | Campaign links | <account>…` from `/urls/managers`; no "All"; the "Made via" select removed;
  - legacy params mapped;
  - the Links tab sends `managed=exclude`, and an account tab sends `managed_by`;
  - it scrolls at 390 px;
  - search, tag chips and the pager work within a tab;
  - a tab's empty state says the links are managed from that integration.
- [x] **`loadStats`:** managed links are counted as links, not as campaign links.
- [x] **The card:**
  - a "Managed by <name>" badge;
  - the destination as the API gives it;
  - no delete and no edit, only tags;
  - the tag pills keep the current tab.
- [x] **Types:** `managed_by`.
- [x] **ServiceAccountsSection's "its links" link** opens the account's tab.
- [x] **The e2e** that used "Made via" and `type=all` is updated.

### T5 — The link page: read-only, tags, override
files: frontend/src/pages/dashboard/link.astro, frontend/src/utils/link-editor.ts, frontend/src/components/app/EditLinkModal.astro, frontend/src/utils/viewer.ts, frontend/src/components/app/OverrideDeleteModal.astro, frontend/tests/managed-link-page.test.mjs
depends_on: T4
verify: cd frontend && npm test && npm run build
- [x] **For a managed link:**
  - a banner: "Managed by <name>. Change or delete it from there; its tags can be changed here." The destination as
    given: a mask is plain text, titled "Only <name> and the organization's owners see the full destination"
    (rule targets too);
  - edit opens tags only ("Edit tags", the modal's `data-full-only` fields hidden), through PATCH tags, without
    validating the masked destination (`editorMode`, `fieldProblems` in link-editor.ts); creator, admins and owners
    (`canChangeTags`), locked for other members ("Only its creator, or an admin or owner, can change its tags.");
  - Add rule, rule delete, the preview's edit, refresh and reset, and Delete are hidden; the menu has a locked
    "Delete via <name>" saying the API's `managed_link_protected` words; tag pills and "← Links" lead to its tab;
  - `viewer.ts`: `canChange` false on a managed link for everyone, `canChangeTags` (the old rule),
    `canOverrideDelete` (owners), `lockFor` / `managedLockReason` naming the manager.
- [x] **Owners:** "Delete anyway…" (menu, danger) opens `OverrideDeleteModal.astro`: "Delete a link <name> manages?",
  the consequence (<name> keeps showing it as active, whoever has it reaches a dead link), a required Reason
  (10–500 after trimming, live count, inline errors, a 422 on the field), "Delete it"; then a toast and the account's
  tab. Unit tests: `frontend/tests/managed-link-page.test.mjs`.

### T6 — e2e, docs and records
files: frontend/e2e/managed-links.spec.ts, frontend/src/utils/service-accounts.ts, frontend/tests/service-accounts.test.mjs, docs/PERSONAL_DATA.md, frontend/src/content/manual/connect-a-service.md, CHANGELOG.md, DEPLOYMENT.md, design/DESIGN_SYSTEM.md, _pm/ROADMAP.md, _pm/spec_service_accounts.md
depends_on: T5
verify: cd frontend && npm run e2e -- managed-links.spec.ts service-accounts.spec.ts
- [x] **e2e:** a link via a service account on behalf of a member; the member sees it only in the account's tab, masked, with no delete; the owner sees the destination and deletes with a reason; the audit shows it.
  (`e2e/managed-links.spec.ts`: also an admin masked with no delete, the member's tags saved and DELETE 403, the
  service's PATCH and DELETE, axe on the page and the dialog. Activity shows the override with its reason:
  `auditWhat` in `service-accounts.ts`.)
- [x] **Docs:**
  - the manual, i.e. ":42" ("theirs to see and change") and ":79" on its links;
  - CHANGELOG (Added, plus "Changed": admins and creators lose delete on managed links);
  - DEPLOYMENT;
  - DESIGN_SYSTEM's locks;
  - ROADMAP 10.3;
  - the spec.

## Verificación global
- [x] `uv run pytest --require-mcp` (2707 passed), ruff; T1–T3 suites with `TEST_SUITE_ON_POSTGRES=1` (345, T2)
- [x] frontend `npm test` (328) && `npm run build`; `npm run e2e` 145 passed, and the service-account + managed specs twice on one database (15/15 each)

## Notas
- Waves: T1 → T2 ∥ T3 → T4 → T5 → T6. General-purpose agents; each brief: only your files, stop on a repo-rule conflict.
- Before the release: tell admins they lose delete on Propuestas links. Propuestas' side: `_exchange/issue-shurly-managed-links.md`.
- After the release: the 3 Propuestas links in their tab, masked for a member, click totals unchanged; Propuestas
  still creates, changes expiry and revokes.

## Log
- 2026-10-19T20:51:47Z Daniel Serrano moved wip -> done
- 2026-10-19T20:51:47Z Daniel Serrano released
- 2026-10-19T20:51:46Z Daniel Serrano released in #254 (7bccafb, td 53): no migration; the 3 managed links' visits unchanged (1, 2, 1); 0 5xx; tab and mask from a member's session and Propuestas' next create/revoke left for the user
- 2026-10-19T19:37:48Z Daniel Serrano T1-T6 done and verified: 2707 passed, frontend 328, e2e 145 (rerun-safe); PR to dev
- 2026-10-19T18:22:31Z Daniel Serrano moved todo -> wip
- 2026-10-19T18:22:31Z Daniel Serrano claimed (lease 120m)
- 2026-10-19T18:22:30Z Daniel Serrano created
