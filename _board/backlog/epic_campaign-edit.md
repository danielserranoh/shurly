---
id: epic_campaign-edit
title: Campaign edit screen
type: epic
status: backlog
priority: medium
created: 2026-10-18
---

# Epic: Campaign edit screen

## Descripción
A campaign can't be changed once it's created: only its tags (`PATCH …/tags`). A typo in a recipient's name, a
forgotten batch of recipients or a wrong campaign name means deleting it and starting again, and its analytics go
with it. ROADMAP 3.11 left "campaign edit screen" open; scope decided with the user on 2026-10-18.

## Requisitos
- [ ] **Rename** a campaign.
- [ ] **Add recipients:** upload a CSV of new rows, with the campaign's columns. Each row makes a new link, as at
  creation (`server/utils/campaign.py` `validate_csv` / `generate_campaign_urls`), and the new links get the page
  preview (`store_page_preview_on_links`, after the commit).
- [ ] **Edit a recipient's data** (e.g. a misspelled name), from the recipients table.
- [ ] **Delete a recipient's link**, with a confirmation that says its visits go with it.
- [ ] **Where:** an "Edit" action on the campaign's page (`/dashboard/campaign/?id=…`) opening a dialog, like the
  link editor (`EditLinkModal.astro`, `utils/link-editor.ts`). No new page. Per-row edit and delete in the recipients
  table. Locked (`lockControl`) for people who can't change the campaign.
- [ ] Guards as today: `visible_campaign_or_404(…, to_change=True)` (creator, admin or owner). A row per route in
  `docs/PERSONAL_DATA.md` (rows carry recipients' data); MCP tools named or excluded (`test_phase52_mcp_tools.py`).
- [ ] The counts on the page (`url_count`, the delete confirmation's text) refresh after a change.
- [ ] Copy: `link.astro:65` says a campaign link "can't be edited or deleted on its own"; the manual's
  `make-a-campaign.md`; CHANGELOG.

## Fuera de alcance
- Changing the destination of all the campaign's links (decided: no).
- Validity window or visit cap for the whole campaign (decided: no).
- Pro billing (the other half of the old ROADMAP line): no epic, pricing undecided.

## Notas
How campaigns work today (analysis 2026-10-18):
- **A row's data is the recipient's landing query string.** Each link stores its row whole in `URL.user_data`, keeps
  the campaign's `original_url`, and the redirect appends `user_data` as query params on every visit
  (`server/app/urls.py:1398-1405`). So editing a row changes where that recipient lands, with no stored URL to
  rewrite, and the change applies to links already sent.
- Short codes: random 6 characters, unique per domain (`uq_urls_domain_code`). No row cap; duplicates allowed;
  `validate_csv` only rejects empty headers and missing values.
- `DELETE` and `PATCH /api/v1/urls/{code}` refuse campaign links (400, pinned by
  `tests/test_urls.py::test_delete_campaign_url_forbidden`). Deleting a link must be `db.delete(obj)`: its visits and
  rules go by ORM cascade; `visitors.url_id` has no `ondelete`, so a bulk `query.delete()` would leave them.
- The recipients table reads `/analytics/campaigns/{id}/recipients` (`RecipientRow`), which has `short_code` and
  `domain` but no link `id`.
- Analytics count live (`analytics.py:1252`, `_campaign_visits`): adding or removing links shifts the rates, and a
  deleted link's visits leave every total. Nothing to migrate.
- A second creation path, `mcp_server/curated.py` `create_campaign_from_rows`, repeats the steps; adding rows should
  share one helper with both.

**To decide when planning (recommendation first):**
1. Rows added with other columns: refuse; they must match `csv_columns` exactly. *Or* extend the columns.
2. A row identical to an existing recipient: warn and allow, as creation does. *Or* refuse.
3. Editing a row: values only, not its keys.
4. Routes address a recipient by link `id` (add `id` to `RecipientRow`), under `/campaigns/{id}/recipients/…`;
   `/urls` keeps refusing campaign links.
5. Who creates the added links: the person adding them (`created_by`), as with any link; the campaign keeps its
   creator. Service accounts can add rows on someone's behalf as at creation.
6. MCP: rename and add rows as tools; editing and deleting a recipient excluded (destructive, and an LLM has no
   confirmation dialog). *Or* all four.
7. Deleting the last recipient: refused ("delete the campaign instead"), so no campaign is left empty.
8. A cap on rows added at once, e.g. the same as creation would get. None exists today; worth adding to both.

## Log
- 2026-10-18T17:56:40Z Daniel Serrano created
