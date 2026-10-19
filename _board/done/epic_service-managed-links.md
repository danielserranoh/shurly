---
id: epic_service-managed-links
title: Links managed by their service account (Propuestas)
type: epic
status: done
priority: high
created: 2026-10-19
completed: 2026-10-19
---

# Epic: Links managed by their service account (Propuestas)

## Descripción
Griddo Propuestas creates one short link per recipient of a commercial proposal, through its service account. Today
any member can delete or edit those links in Shurly without Propuestas knowing. The tests of 2026-10-17 showed:
- **A deleted link stays "active" in Propuestas:** the recipient gets a dead link, and nobody notices.
- **`create_links` with `reused: true` returns the old short link** even when it no longer exists in Shurly.
- **Recreating a link by hand with the same code** loses its type, tag, preview and ownership. The service account
  isn't its creator, so `revoke_link` then fails with a 403, and the two systems stay out of step for good.
- **Anyone in the organization can read the destination:** it carries the proposal's access token (a credential),
  through `get_url`.
- **Sync goes one way only:** revoking in Propuestas deletes the link in Shurly, but not the other way round.

A proposal's short link belongs to Propuestas. Treating it as an ordinary Shurly link, free to edit and delete, is
the root cause. Written by Daniel Serrano (2026-10-19); restructured for the board the same day, with the decisions
below.

**The rule: a link made through a service account is managed by that service account.** Shurly already records it
on every link (`urls.via_service_account_id`, ROADMAP 10.1). So the mark needs no new field, no request change in
Propuestas, and no user can change it. It is generic: a future integration's links behave the same way.

## Requisitos
- [ ] **R1. Managed links:** a link with `via_service_account_id` is managed by that account. The API exposes it
  read-only (`managed_by: {id, display_name}` or null), and nothing a person does can change it.
- [ ] **R2. Delete protection,** enforced in the backend, so the app, REST and MCP are all covered:
  - only the managing service account deletes a managed link, or an owner through R4;
  - anyone else gets a 403 `managed_link_protected`, with a message pointing to Propuestas;
  - admins, and the person the link was made for, lose the delete they have today. Tell them before the release.
- [ ] **R3. Edit protection:** for people, the destination, the short code, the validity window and visit cap, the
  redirect rules and the visibility are locked. Tags stay editable, for analysis.
  - The managing service account keeps every change it makes today. Propuestas' `set_expiry` writes the expiry
    through it.
- [ ] **R4. Emergency override, owners only:** an owner can delete or edit a managed link by giving a reason, which
  is required.
  - Uses: a GDPR request (`forget_recipient`), a leaked token, orphaned links after a failure.
  - It writes a `managed_link.override` row to the audit table (`audit_events`, 10.2) with the owner (`actor_id`),
    the link, the action and the reason. The reason is stored as text, the one exception to that table's "ids only"
    rule. Record that in PERSONAL_DATA.
- [ ] **R5. The destination is hidden:** for a managed link, the API and the app mask the destination (e.g.
  `https://propuestas.griddo.io/p/…`) for everyone except owners and the managing service account. That includes
  the person the link was made for.
  - It covers every surface that returns the destination: `get_url`, `list_urls`, previews, exports, the link page,
    and the MCP, which goes through REST.
  - The masking stops people browsing the dashboard, not someone who follows the short link.
- [ ] **R6. Their own tab:**
  - The list header becomes `Links | Campaign links | <service account name>`, e.g. "Griddo Propuestas": one tab per
    service account that has links.
  - **There is no "All" tab any more:** the user doesn't want every link seen together.
  - The "Made via" dropdown goes; its URL parameter can stay for links that point to it.
  - The managed tab is read-only: title, recipient (on behalf of), status (expired, visit cap), clicks, last visit,
    the link to its analytics. No delete, and edits only to tags. It says the links are managed from Propuestas.
  - Search works inside the selected tab.
- [ ] **R7. Analytics and totals:** a managed link's analytics stay as they are. The dashboard's KPIs and totals still
  count its clicks.
- [ ] **R8. Existing links:**
  - In production, 3 links point to `propuestas.griddo.io` (checked 2026-10-19). All 3 have
    `via_service_account_id`, 0 have the service account as creator (they were made on behalf of a person or
    reassigned by hand), and 0 are manual copies. So they become managed with no migration.
  - Check after the release that the 3 show in the tab and that their totals are unchanged.

## Fuera de alcance
- Changing Shurly's click-analytics model.
- Protecting against infrastructure data loss (outages, restoring a backup): Propuestas' daily reconciliation covers it.
- **Links made earlier with a person's API key:** they can't be told apart from links that person made by hand
  (decided in 10.2), so they stay ordinary links.
- **Things the original draft listed that Shurly doesn't have:** an active/inactive status, bulk delete, and adding
  an existing link to a campaign. Deleting a campaign only deletes its own campaign links, and Propuestas' links are
  standard ones.

### Coordinated work in Propuestas (a dependency, not Shurly's)
1. **Self-healing in `create_links`:** if a recipient's link exists in Propuestas but not in Shurly, it recreates it
   through the service account with the same short code, and says so in its response.
2. **Daily reconciliation:** it detects a missing short link or a diverging expiry and tells the proposal's owner.
   It never revokes anything automatically because of something that happened in Shurly.
3. **`set_expiry` and `revoke_link`** stay the only way to change these links, and reflect the expiry in Shurly.
4. **Handling the new 403 `managed_link_protected`:** it only reaches people, never the service account.

A ticket for Propuestas could go in `_exchange/`, like `issue-shurly-onbehalf.md`.

## Notas
Decided with the user (2026-10-19):
- **Tabs:** one per managing service account, named after it, and no "All".
- **The mark:** derived from `via_service_account_id`; no new field.
- **Who sees the full destination:** owners and the managing service account only.
- **The override:** owners only, with a required reason stored in the audit.

Checked against the code (2026-10-19):
- Roles are owner, admin and member, plus service accounts (`kind = 'service'`).
- Change permission today is `ensure_can_change`: the creator, an admin or an owner (`server/utils/access.py`). R2
  and R3 add the managed rule on top of it, in one place.
- The MCP's generated tools call the REST routes, so a backend rule covers them. `create_campaign_from_rows` is
  curated, but makes campaign links, not managed ones.
- A link's analytics don't depend on the list it appears in.
- The list header today: a segmented control `Links | Campaign links | All` plus a "Made via" `<select>` (Phase
  10.1) in `frontend/src/pages/dashboard/index.astro:85-109`.

Acceptance criteria (from the original draft, adjusted):
- [ ] A member, an admin, or the person the link was made for gets a 403 `managed_link_protected` when deleting from
  the app, REST or MCP, and the link stays.
- [ ] An owner deletes it only with a reason, and `managed_link.override` is in the audit.
- [ ] The service account creates its links, changes their expiry and deletes them without errors; Propuestas'
  `revoke_link` returns `shurly_synced: true`.
- [ ] Editing the destination, code, validity, cap, rules or visibility is blocked for people; tags can be edited.
- [ ] `get_url` and `list_urls` mask the destination for a member, an admin and the person the link was made for,
  and show it to an owner and to the service account.
- [ ] The "Links" tab doesn't show managed links. The service account's tab does, with clicks and last visit and no
  delete button. There's no "All".
- [ ] The 3 existing links show in the tab, and their click totals are the same before and after.
## Log
- 2026-10-19T18:22:31Z Daniel Serrano moved backlog -> done
- 2026-10-19T15:45:09Z Daniel Serrano created
