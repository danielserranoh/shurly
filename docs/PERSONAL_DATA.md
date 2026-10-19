# Personal data: what each route returns, and to whom

Reviewed on 2026-09-29. **Update this table in the same PR as any route change.**
`tests/test_personal_data_inventory.py` fails when:
- a route or MCP tool has no row, or a row names none;
- a row's guard isn't in its code;
- its MCP column doesn't match the tools.

So a new route can't widen who sees people's data without saying so here.

`tests/test_personal_data_access.py` checks the table at runtime, for every GET whose row returns recipients' rows,
their activity, or visits:
- an outsider, signed in from another organization, gets a 404, and never sees the organization's data in a list;
- a plain member gets it;
- someone's personal campaign stays theirs.

It reads the routes from this table, so a new row is checked as soon as it says what its route returns.

This is about what goes *out*: what a route returns, not what Shurly records. What a visit records is in
`server/core/models/visitor.py`. The IPs are anonymized when stored (`ANONYMIZE_REMOTE_ADDR`).

## People's data

| Category | What |
|---|---|
| **recipients' rows** | A campaign recipient's row of its CSV (`user_data`): names, emails, whatever the CSV had |
| **recipients' activity** | What one recipient did: their clicks and opens, and when |
| **visits** | Visits, counted or one by one: time, kind, country, browser, OS, device, referrer host. Their city only counted, never one by one (§ Cities). Never an IP. On a campaign link, a link's visits are one recipient's |
| **addresses** | Anonymized IPs, with user agents and referrers |
| **accounts** | Other people's accounts: emails, names, roles. A service account's name, description and person responsible (10.1) |
| **own account** | The caller's own: email, profile, photo, tokens, API key |
| **prospects** | The waitlist's entries (9.1): people outside Griddo, with their email, name, whether they came as an individual or for a company, the company's name and size, their role, what they'd use Shurly for and how they heard of it |

## Guards

A route's guard is the function that decides who gets an answer. The test finds it in the route's code, or in a helper
of the same module that the route calls.

| Guard | Who gets an answer |
|---|---|
| public | Anyone, signed in or not |
| `get_current_user` | Any signed-in account: a session token (JWT), an API key or a service token (10.1). A service token only on the routes its scopes allow, from its allowed IP ranges (10.2, `server/utils/service_scopes.py`, checked where it authenticates): elsewhere a 403 |
| `get_signed_in_session` | A session token only: an API key gets a 403, a service token a 403 with `code: service_account_not_allowed` |
| `sees` | A list, filtered to what the caller can see: their organization's, and their own personal ones (`Viewer.sees`, `server/utils/access.py`) |
| `visible_url_or_404`, `visible_campaign_or_404` | One link or campaign the caller can see, else 404. When a route changes it, one they can change, else 403: its creator, or an organization admin or owner (`server/utils/access.py`). A link a service account manages (10.3, `server/utils/managed.py`): only that account changes it, anyone else gets a 403 `managed_link_protected`; its tags change by the rule before |
| `find_urls`, `find_url`, `can_change`, `can_change_tags` | The same rules, where the MCP's curated tools and bulk tagging apply them |
| `_ensure_may_override` | A person who owns the link's organization, for a link a service account manages (10.3): anyone else gets a 403, an unmanaged link a 400 (`server/app/urls.py`) |
| `viewer` | The caller's organization, for something they create |
| `_my_membership` | A member of the caller's organization |
| `change_role`, `remove_member`, `transfer_ownership`, `removed_members`, `adopt_personal_links` | The organization's roles (`server/utils/organization.py`) |
| `editable_organization` | An owner or admin of the caller's organization, for its logo: a member gets a 403, someone outside it a 404 (`server/utils/organization.py`) |
| `ensure_owner_or_admin` | An owner or admin of the caller's organization: a member, or an account outside any organization, gets a 403 (`server/utils/organization.py`) |
| `ensure_reader` | An owner or admin of the caller's organization, a person, for its service accounts: anyone else gets a 403 (`server/utils/service_accounts.py`) |
| `create_account`, `update_account`, `remove_account`, `issue_token`, `revoke_tokens` | The organization's owner, a person: anyone else gets a 403, a service account that isn't the organization's a 404 (`server/utils/service_accounts.py`) |
| `RequireAuthMiddleware` | The MCP: an account's token or API key |

## Routes

| Route | People's data it returns | Who sees it | Guard | MCP |
|---|---|---|---|---|
| `GET /` | none | anyone | public | excluded |
| `GET /api/v1/analytics/campaigns/{campaign_id}/breakdown` | **visits**, counted over all its recipients. A city only when at least 5 of its links' visits came from it; the rest are "Other cities" | who can see the campaign | `visible_campaign_or_404` | `get_campaign_breakdown` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/recipients` | **recipients' rows** and **recipients' activity**: every recipient's `user_data`, clicks, opens, first and last click and last open | who can see the campaign | `visible_campaign_or_404` | `list_campaign_recipients` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/recipients.csv` | **recipients' rows** and **recipients' activity**: the list's, as a CSV | who can see the campaign | `visible_campaign_or_404` | excluded |
| `GET /api/v1/analytics/campaigns/{campaign_id}/summary` | **recipients' rows** and **recipients' activity**: the top 5 recipients' `user_data` and clicks | who can see the campaign | `visible_campaign_or_404` | `get_campaign_summary` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/timeseries` | **visits**, counted over all its recipients | who can see the campaign | `visible_campaign_or_404` | `get_campaign_timeseries` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/totals` | **visits**, counted over all its recipients | who can see the campaign | `visible_campaign_or_404` | `get_campaign_totals` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/users` | **recipients' rows** and **recipients' activity**: every recipient's `user_data`, clicks and last click | who can see the campaign | `visible_campaign_or_404` | `get_campaign_users` |
| `GET /api/v1/analytics/orphan-visits` | **addresses**: the anonymized IP, user agent and referrer of each hit on an unknown code | any signed-in account: they belong to no organization. **Kept (2026-09-29):** the IPs are shown, to revisit after the dogfood | `get_current_user` | `get_orphan_visits` |
| `GET /api/v1/analytics/orphan-visits/grouped` | none: the paths tried on unknown codes, counted, their first and last hit, and the links each may have meant. With `typos_only` (3.10.8), only the hits a person could have mistyped, and how many hits and paths that left out: a hit's user agent decides whether it's a bot's, and isn't returned. Never an IP, a user agent or a referrer | any signed-in account: they belong to no organization. The links suggested are the caller's to see | `get_current_user`, `viewer` | excluded |
| `GET /api/v1/analytics/overview` | **visits**, counted: totals, and the top links by code (a campaign link's clicks are one recipient's). A top link a service account manages (10.3) has its destination masked (`https://host/…`) for everyone but that account and the organization's owners; it still counts in every total | the links the caller can see | `sees` | `get_overview_stats` |
| `GET /api/v1/analytics/urls/{short_code}/breakdown` | **visits**, counted, cities included. On a campaign link, one recipient's, and no cities | who can see the link | `visible_url_or_404` | `get_url_breakdown` |
| `GET /api/v1/analytics/urls/{short_code}/daily` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_daily_stats` |
| `GET /api/v1/analytics/urls/{short_code}/geo` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_geo_stats` |
| `GET /api/v1/analytics/urls/{short_code}/timeseries` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_timeseries` |
| `GET /api/v1/analytics/urls/{short_code}/totals` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_totals` |
| `GET /api/v1/analytics/urls/{short_code}/visits` | **visits**, one by one: time, kind, country, browser, OS, device, referrer host. Never an IP, a user agent or a full referrer | who can see the link. **Kept (2026-09-29):** a campaign link's, one recipient's, are listed too, to revisit after the dogfood | `visible_url_or_404` | `list_url_visits` |
| `GET /api/v1/analytics/urls/{short_code}/visits.csv` | **visits**, one by one, as the list, plus each visit's user agent. Never an IP | who can see the link. **Kept (2026-09-29):** a campaign link's, one recipient's, are listed too, to revisit after the dogfood | `visible_url_or_404` | excluded |
| `GET /api/v1/analytics/urls/{short_code}/weekly` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_weekly_stats` |
| `DELETE /api/v1/auth/api-key` | none | the caller | `get_current_user` | excluded |
| `POST /api/v1/auth/api-key/generate` | **own account**: a new API key, shown once | the caller, signed in (not with an API key) | `get_signed_in_session` | excluded |
| `POST /api/v1/auth/change-password` | none | the caller, signed in (not with an API key) | `get_signed_in_session` | excluded |
| `GET /api/v1/auth/google/callback` | **own account**: a one-time code, in the redirect back to the frontend | the person Google signed in | public | excluded |
| `POST /api/v1/auth/google/exchange` | **own account**: a session token | whoever holds the one-time code | public | excluded |
| `GET /api/v1/auth/google/start` | none: a redirect to Google | anyone | public | excluded |
| `POST /api/v1/auth/login` | **own account**: a session token | anyone with the account's password | public | excluded |
| `GET /api/v1/auth/me` | **own account**: email, names, how it signs in, whether it has an API key and its prefix | the caller | `get_current_user` | `get_current_user_info` |
| `DELETE /api/v1/auth/me/avatar` | none | the caller | `get_current_user` | excluded |
| `GET /api/v1/auth/me/avatar` | **own account**: the photo | the caller | `get_current_user` | excluded |
| `PUT /api/v1/auth/me/avatar` | **own account**: the profile, with the new photo's version | the caller | `get_current_user` | excluded |
| `PATCH /api/v1/auth/me/profile` | **own account**: the profile | the caller | `get_current_user` | `update_my_profile` |
| `DELETE /api/v1/auth/password` | none | the caller, signed in (not with an API key) | `get_signed_in_session` | excluded |
| `PUT /api/v1/auth/password` | none | the caller, signed in (not with an API key) | `get_signed_in_session` | excluded |
| `POST /api/v1/auth/register` | **own account**: the new account. Off unless `ALLOW_PASSWORD_SIGNUP` | anyone, when it's on | public | excluded |
| `GET /api/v1/campaigns` | **accounts**: each campaign's creator's email and names | the campaigns the caller can see: their organization's, and their own | `sees` | `list_campaigns` |
| `POST /api/v1/campaigns` | **own account**: the new campaign, the caller as its creator. With a service token and `X-Shurly-On-Behalf-Of` (10.1), **accounts**: the person named, as on `POST /api/v1/urls` | any signed-in account. The header only from a service token | `get_current_user`, `acting_for` | `create_campaign` |
| `DELETE /api/v1/campaigns/{campaign_id}` | none | who can change the campaign | `visible_campaign_or_404` | `delete_campaign` |
| `GET /api/v1/campaigns/{campaign_id}` | **recipients' rows**: every recipient's `user_data`. **accounts**: the creator's email and names | who can see the campaign | `visible_campaign_or_404` | `get_campaign` |
| `GET /api/v1/campaigns/{campaign_id}/export` | **recipients' rows**: every recipient's `user_data`, as a CSV | who can see the campaign | `visible_campaign_or_404` | `export_campaign` |
| `PATCH /api/v1/campaigns/{campaign_id}/tags` | none | who can change the campaign | `visible_campaign_or_404` | `update_campaign_tags` |
| `POST /api/v1/client-errors` | none: it logs a browser's error report as a `client.error` line and answers nothing. The line keeps the page's path, never its query or the IP; the account's id when signed in | anyone, limited per IP | public | excluded |
| `GET /api/v1/health` | none | anyone | public | excluded |
| `GET /api/v1/health/db` | none | anyone | public | excluded |
| `GET /api/v1/organization` | **own account**: the organization, the caller's role, and for owners and admins how many service tokens need attention (a count) | a member | `_my_membership` | `get_organization` |
| `POST /api/v1/organization/adopt-personal-links` | none: counts | an owner | `adopt_personal_links` | excluded |
| `DELETE /api/v1/organization/logo` | none | an owner or admin | `editable_organization` | excluded |
| `GET /api/v1/organization/logo` | none: the organization's logo | a member | `_my_membership` | excluded |
| `PUT /api/v1/organization/logo` | **own account**: the organization, and the caller's role, with the new logo's version | an owner or admin | `editable_organization` | excluded |
| `GET /api/v1/organization/members` | **accounts**: every member's email, names, role and join date | any member; a service token only with the `act_on_behalf` scope (10.2): the people it may name | `_my_membership` | `list_organization_members` |
| `DELETE /api/v1/organization/members/{user_id}` | none | an admin or owner, as `remove_member` allows | `remove_member` | excluded |
| `PATCH /api/v1/organization/members/{user_id}` | **accounts**: that member's email, names and role | an admin or owner, as `change_role` allows | `change_role` | excluded |
| `GET /api/v1/organization/removed-members` | **accounts**: removed people's emails and names, and how many links and campaigns each still owns | an owner | `removed_members` | excluded |
| `POST /api/v1/organization/transfer-ownership` | **accounts**: the new owner's email, names and role | the owner | `transfer_ownership` | excluded |
| `GET /api/v1/service-accounts` | **accounts**: the organization's service accounts, each one's name, description, role and person responsible (email and names), and its tokens' prefix, creation, expiry, last use, scopes, warnings and allowed IP ranges (10.2: an allowlist the owner set, never an address seen). Never a token or its hash, never an IP it was used from | an owner or admin, signed in | `get_signed_in_session`, `ensure_reader` | excluded |
| `POST /api/v1/service-accounts` | **accounts**: the new service account, with its person responsible | the owner, signed in | `get_signed_in_session`, `create_account` | excluded |
| `GET /api/v1/service-accounts/audit` | **accounts** (10.2): the audit of the organization's service accounts, newest first. Each event's time, action, target id (a link's short code while it exists and the reader sees it), the service account's id and name, the token's id, and the email and name of the person who made it (an owner) or the service acted for, looked up when read: someone deleted shows as deleted, by id. Ids and field names only, never the values changed, never an IP. The one exception (10.3): an owner's override of a managed link carries the reason they typed (§ The audit of service accounts) | an owner or admin, signed in | `get_signed_in_session`, `ensure_reader` | excluded |
| `DELETE /api/v1/service-accounts/{account_id}` | none: it revokes the account's tokens and removes it | the owner, signed in | `get_signed_in_session`, `remove_account` | excluded |
| `PATCH /api/v1/service-accounts/{account_id}` | **accounts**: the service account, with its person responsible | the owner, signed in | `get_signed_in_session`, `update_account` | excluded |
| `GET /api/v1/service-accounts/{account_id}/links` | **recipients' rows** and **recipients' activity**: a campaign link's, as `GET /api/v1/urls`. **accounts**: each link's creator's email and names. The links the account made, `?token_id=` those one token made. The ones it manages (10.3) have their destination masked for admins: only owners read it here | an owner or admin, signed in | `get_signed_in_session`, `ensure_reader`, `sees` | excluded |
| `DELETE /api/v1/service-accounts/{account_id}/token` | none | the owner, signed in | `get_signed_in_session`, `revoke_tokens` | excluded |
| `POST /api/v1/service-accounts/{account_id}/token` | **accounts**: the service account, with its person responsible, and its new token, shown this once, with its scopes and allowed IP ranges (10.2: an allowlist the owner set, never an address seen) | the owner, signed in | `get_signed_in_session`, `issue_token` | excluded |
| `GET /api/v1/tags` | none: tags are names shared by everyone | any signed-in account | `get_current_user` | `list_tags` |
| `POST /api/v1/tags` | none | any signed-in account | `get_current_user` | `create_tag` |
| `DELETE /api/v1/tags/{tag_id}` | none | any signed-in account | `get_current_user` | `delete_tag` |
| `PATCH /api/v1/tags/{tag_id}` | none | any signed-in account | `get_current_user` | `update_tag` |
| `GET /api/v1/urls` | **recipients' rows** and **recipients' activity**: a campaign link's `user_data`, clicks and last click. **accounts**: each link's creator's email and names, and the service account that made it, `{id, display_name}` (10.1; never its token), and the one managing it, `managed_by` (10.3). `?via_service_account=`, `?managed=` and `?managed_by=` filter by them. On a link a service account manages (10.3), the destination is masked (`https://host/…`) for everyone but that account and the organization's owners, since it can carry a credential; `q` doesn't match a destination the caller reads masked | the links the caller can see: their organization's, and their own | `sees` | `list_urls` |
| `GET /api/v1/urls/managers` | **accounts**: the service accounts managing links the caller can see (10.3), each one's id, name and how many of those links | the links the caller can see: their organization's, and their own | `sees` | `list_link_managers` |
| `POST /api/v1/urls` | **own account**: the new link, the caller as its creator. With a service token and `X-Shurly-On-Behalf-Of` (10.1), **accounts**: the person named becomes its creator, with their email and names; an email nobody in the organization has is a 422 that says no more | any signed-in account. The header only from a service token | `get_current_user`, `acting_for` | `create_short_url` |
| `POST /api/v1/urls/bulk/tags` | none: counts | the links whose tags the caller can change: also a link a service account manages (10.3) | `find_urls`, `can_change_tags` | `bulk_tag_urls` |
| `POST /api/v1/urls/custom` | **own account**: the new link, the caller as its creator. With a service token and `X-Shurly-On-Behalf-Of` (10.1), **accounts**: the person named becomes its creator, with their email and names | any signed-in account. The header only from a service token | `get_current_user`, `acting_for` | `create_custom_url` |
| `POST /api/v1/urls/fetch-metadata` | none: a page's Open Graph tags | any signed-in account | `get_current_user` | `fetch_url_metadata` |
| `DELETE /api/v1/urls/{short_code}` | none | who can change the link: a link a service account manages, only that account (10.3) | `visible_url_or_404` | `delete_url` |
| `GET /api/v1/urls/{short_code}` | **recipients' rows** and **recipients' activity**, for a campaign link. **accounts**: the creator's email and names, and the service account managing it (10.3). On a link a service account manages (10.3), the destination is masked (`https://host/…`) for everyone but that account and the organization's owners, since it can carry a credential | who can see the link | `visible_url_or_404` | `get_url` |
| `POST /api/v1/urls/{short_code}/override-delete` | none. It writes the service account's audit row (10.3): the owner who deleted, the link's id, and the reason they typed, the audit's one free text | an owner of the link's organization, a person, for a link a service account manages. Never a service token | `get_current_user`, `visible_url_or_404`, `_ensure_may_override` | excluded |
| `PATCH /api/v1/urls/{short_code}` | **recipients' rows** and **recipients' activity**, for a campaign link. **accounts**: the creator's email and names | who can change the link: a link a service account manages, only that account (10.3) | `visible_url_or_404` | `update_url` |
| `GET /api/v1/urls/{short_code}/preview` | none: the destination's Open Graph tags and icon, and the overrides typed for the link | who can see the link | `visible_url_or_404` | `get_url_preview` |
| `POST /api/v1/urls/{short_code}/refresh-preview` | none | who can change the link: a link a service account manages, only that account (10.3) | `visible_url_or_404` | `refresh_url_preview` |
| `GET /api/v1/urls/{short_code}/rules` | none. On a link a service account manages (10.3), each rule's target is masked as its destination is | who can see the link | `visible_url_or_404` | `list_redirect_rules` |
| `POST /api/v1/urls/{short_code}/rules` | none | who can change the link: a link a service account manages, only that account (10.3) | `visible_url_or_404` | `create_redirect_rule` |
| `DELETE /api/v1/urls/{short_code}/rules/{rule_id}` | none | who can change the link: a link a service account manages, only that account (10.3) | `visible_url_or_404` | `delete_redirect_rule` |
| `PATCH /api/v1/urls/{short_code}/rules/{rule_id}` | none | who can change the link: a link a service account manages, only that account (10.3) | `visible_url_or_404` | `update_redirect_rule` |
| `PATCH /api/v1/urls/{short_code}/tags` | none | who can change the link's tags: its creator, the service account that made it, an admin or owner; on a link a service account manages too (10.3) | `visible_url_or_404` | `update_url_tags` |
| `DELETE /api/v1/waitlist/{entry_id}` | none: it removes the entry, when its person asks (§ The waitlist) | an owner or admin | `ensure_owner_or_admin` | excluded |
| `GET /api/v1/waitlist` | **prospects**: every entry, newest first and paged, with the counts by kind and by company size | an owner or admin | `ensure_owner_or_admin` | excluded |
| `GET /api/v1/waitlist/export` | **prospects**: every entry, as a CSV | an owner or admin | `ensure_owner_or_admin` | excluded |
| `POST /api/v1/waitlist` | none: the same answer for every sign-up, whether the email was listed or not, and nothing typed echoed back | anyone, limited per IP | public | excluded |
| `DELETE /mcp` | none: a redirect to `/mcp/`, on the app's host only (8.4) | anyone | public | excluded |
| `GET /mcp` | none: a redirect to `/mcp/`, on the app's host only (8.4) | anyone | public | excluded |
| `POST /mcp` | none: a redirect to `/mcp/`, on the app's host only (8.4) | anyone | public | excluded |
| `GET /favicon.ico` | none: a 204 | anyone | public | excluded |
| `GET /robots.txt` | none | anyone | public | excluded |
| `GET /{short_code}` | **recipients' rows**: a campaign link adds its recipient's `user_data` to the destination's query, for people (personalization). A social crawler never gets it: neither in its redirect (8.7: a link whose preview isn't rewritten) nor in the preview page (finding 1, fixed) | anyone with the link (by design) | public | excluded |
| `GET /{short_code}/track` | none | anyone | public | excluded |

## The MCP's own routes

On the app's host only (Phase 8.4: the host of `MCP_PUBLIC_URL`, else of `FRONTEND_URL`). On a short domain these
routes and the OAuth metadata at the root don't answer, and `/mcp` is a link's code, `GET /{short_code}` above.

| Route | People's data it returns | Who sees it | Guard | MCP |
|---|---|---|---|---|
| `POST /mcp/` | the tools: the MCP column above, and the curated tools below | an account's token or API key | `RequireAuthMiddleware` | n/a |
| `DELETE /mcp/` | none: ends the session | an account's token or API key | `RequireAuthMiddleware` | n/a |
| `GET /mcp/.well-known/oauth-authorization-server` | none | anyone | public | n/a |
| `GET /mcp/.well-known/oauth-protected-resource/mcp/` | none | anyone | public | n/a |
| `GET /mcp/authorize` | none: starts a sign-in | anyone | public | n/a |
| `POST /mcp/authorize` | none: starts a sign-in | anyone | public | n/a |
| `GET /mcp/auth/callback` | **own account**: Google's answer for the person signing in | the person signing in | public | n/a |
| `GET /mcp/consent` | **own account**: which client asks, for the person signing in | the person signing in | public | n/a |
| `POST /mcp/consent` | **own account**: the answer, for the person signing in | the person signing in | public | n/a |
| `POST /mcp/token` | **own account**: the client's tokens | the client that holds the code | public | n/a |
| `POST /mcp/register` | none: a client registers | anyone (rate-limited) | public | n/a |

## The MCP's curated tools

Each also runs behind `POST /mcp/`, the MCP's sign-in.

| Route | People's data it returns | Who sees it | Guard | MCP |
|---|---|---|---|---|
| MCP `get_url_analytics_summary` | **visits**, counted, and how many distinct addresses. On a campaign link, one recipient's. On a link a service account manages (10.3), the destination is masked for everyone but that account and the organization's owners | who can see the link | `find_url` | curated |
| MCP `list_orphan_visits_grouped` | **addresses**: the anonymized IPs, user agents and referrers of each path's newest 3 hits on unknown codes, with the paths' counts, first and last hit, and the links each may have meant. With `typos_only` (3.10.8), only the hits a person could have mistyped, samples included, and how many hits and paths that left out | any account: they belong to no organization. The links suggested are the caller's to see. **Kept (2026-09-29):** the IPs are shown, to revisit after the dogfood | `RequireAuthMiddleware`, `viewer` | curated |
| MCP `create_campaign_from_rows` | **own account**: the new campaign | any account | `viewer` | curated |
| MCP `add_redirect_rule` | none | who can change the link | `find_url`, `can_change` | curated |

## Service accounts (10.1, decided 2026-10-16)

Another system, such as Propuestas Griddo, makes links for the organization with its own token
(`_pm/spec_service_accounts.md`). What Shurly keeps:
- **The account:** a `users` row with `kind = 'service'`, its display name, description and person responsible
  (`responsible_user_id`), and a placeholder email at `service.invalid`, which is nobody's. Lists of people (the members,
  the removed people) leave it out.
- **Its tokens** (`service_tokens`): the prefix shown to tell them apart and a SHA-256 of the token, never the token;
  who made and who revoked each one, when, its expiry, and its last use to the minute. **No IP it was used from**,
  ever.
- **What each token may do, and from where** (10.2): its `scopes`, and its `allowed_ip_ranges`, CIDRs the owner
  types to restrict where the token works (an integration's own servers). That's configuration, not an address
  Shurly observed: a request from outside the ranges is refused and logged (`service_token.refused`) without its
  address. The owners and admins see the ranges with the token.
- **On a link:** `urls.via_service_account_id`, the service account that made it, shown with its name ("via
  Propuestas Griddo"), and `urls.via_token_id`, the token it used. The token's reference is internal: it's never in
  a link's response or page, only in what the owners and admins read on the Organization page (`…/links?token_id=`),
  to answer "which links did this token create?" when a token leaks.
- **Whom a link is for:** `X-Shurly-On-Behalf-Of` names a person by email; they become the link's creator, as if
  they'd made it. The email itself isn't kept or logged: the event log has their user id (`on_behalf_of`).

Who sees it: the accounts and their tokens' prefixes, the organization's owners and admins; a link's service account,
whoever sees the link. None of the management routes is an MCP tool, and the MCP never takes a service token or the
header.

**The people a service may name** (10.2): `GET /api/v1/organization/members` lists every member's email. A service
token reads it only with the `act_on_behalf` scope, the one it needs to name a person in `X-Shurly-On-Behalf-Of`
(v1 let every token read it; every v1 token has that scope).

## The audit of service accounts (10.2, decided 2026-10-19)

What service accounts do, and what's done to them, kept longer than the event log's 60 days
(`audit_events`, `server/core/models/audit_event.py`, written by `server/utils/audit.py`):
- **A row for each change a service account makes** to a link, a campaign, a tag or a redirect rule, with the token
  it used and the person it acted for (`on_behalf_of_id`); and **one for each event on an account or its token**
  (made, changed, removed; token made, renewed, revoked), with the owner who made it (`actor_id`). A person's
  changes to links, campaigns, tags and rules write none.
- **Ids only**, as the event log: the service account, the token, the people and the target by id, the action, and
  in `detail` ids and the names of the fields changed, never their values. No email, no IP, no short code or title
  (a slug can be someone's name). The ids have no foreign keys, so a row outlives what it names, and deleting a
  person isn't held up by it. One exception, below: an override's reason (10.3).
- **An owner's override (10.3)**, deleting a link a service account manages past it (`POST
  /api/v1/urls/{short_code}/override-delete`, § Links managed by a service account): a `url.deleted` row on the
  manager, with the owner as `actor_id` and `detail` `{"override": true, "reason": …}`. **The reason is the audit's
  one free-text field**: what the owner typed to say why, 10 to 500 characters, required, since it's the point of
  the row. It's the owner's own words, meant to say why ("the recipient asked us to delete their data", "a leaked
  access token"); the dialog doesn't ask for anyone's name or email, but nothing stops one being typed, so it's read
  as possibly personal. It's kept with the row (2 years, below), read by the same owners and admins as the rest
  (each account's **Activity** shows it under the event), and never written to the event log, whose
  `url.override_deleted` has ids only.
- **People are looked up when it's read:** `GET /api/v1/service-accounts/audit` gives the email and name of the
  person acted for or the owner who acted, as they are then, and someone deleted shows as deleted, with their id
  only. A link shows its short code while it exists and the reader sees it.

Who sees it: the organization's owners and admins, signed in (`ensure_reader`), the same people who see the service
accounts: on the Organization page (each account's **Activity**) and through the API. Members get a 403. Not an MCP
tool, like every route under `/api/v1/service-accounts`.

**Retention:** 2 years from each event. The daily housekeeping (`server/utils/housekeeping.py`, DEPLOYMENT.md
§ Daily housekeeping) deletes the older rows, and logs how many (`audit_deleted`), never which.

## Links managed by a service account (10.3, decided 2026-10-19)

A link made through a service account, other than a campaign link, is **managed** by it (`server/utils/managed.py`;
derived from `urls.via_service_account_id`, no new column). Only that account changes or deletes it; people change
its tags. Its destination can carry a credential: Propuestas' links end in the proposal's access token. So:
- **Who reads the destination whole:** the managing service account, and the owners of the link's organization.
  Everyone else, the person the link was made for and the admins included, reads it masked: its scheme and host, and
  `…` for the rest (`https://propuestas.griddo.io/…`; a `user:pass@` in the address is dropped). A removed service
  account's links stay managed and masked.
- **Where:** every route that returns a link's destination: `GET /api/v1/urls` and `GET /api/v1/urls/{short_code}`
  (and so the MCP's `list_urls` and `get_url`), the link the create and change routes answer with, the targets of its
  redirect rules (`GET …/rules`), the overview's top links (`GET /api/v1/analytics/overview`), the admins' list of
  an account's links (`GET /api/v1/service-accounts/{account_id}/links`), and the curated
  `get_url_analytics_summary`. The app shows the mask as plain text, titled "Only <service> and the organization's
  owners see the full destination".
- **Search:** `q` on `GET /api/v1/urls` doesn't match the destination of a link whose destination the caller reads
  masked, so a search can't find what the mask hides (it still matches its title and code).
- **What it doesn't stop:** whoever follows the short link reaches the destination. The mask keeps the credential
  out of the dashboard, the API and the MCP's context, not away from the recipient.
- **`managed_by`** (`{id, display_name}`) names the managing account on each link, and `GET /api/v1/urls/managers`
  lists the accounts managing links the caller sees, with how many: names of service accounts, no people.
- **Deleting one past its service account** is an owner's override, with a reason, kept in the audit (§ The audit
  of service accounts). It isn't an MCP tool, and a service token can't call it.

## The waitlist (9.1, decided 2026-10-05)

People outside Griddo can't sign in (accounts come from Google Workspace, 3.13), so `/waitlist/` asks those who'd
like Shurly to leave their details. `waitlist_entries` (`server/core/models/waitlist.py`) keeps:
- **What they typed:** email (lowercased, one entry per email), name, individual or company, the company's name and
  size, role, what they'd use Shurly for, how they heard of it. Signing up again with the same email updates the
  entry, and the answer never says whether it was listed.
- **When:** the sign-up (`created_at`), the latest one (`updated_at`), and when they agreed to be contacted
  (`consent_at`). Consent is required: the form says what's stored and that they can ask to be removed at
  support@griddo.io.
- **Never their connection:** no IP, anonymized or not, and no user agent. The rate limit counts an HMAC of the IP
  (`rate_limits`, gone within the hour), and the event log's `waitlist.joined` has the kind and the company size only.

Who sees it: the organization's owners and admins, in the dashboard (`/dashboard/waitlist/`) and its CSV. Members get
a 403. It's not in the MCP: the entries are strangers' free text, and an assistant with write tools shouldn't read
them as its context.

**Retention** (confirmed by the user 2026-10-05): until the person asks to be removed (an owner or admin removes the
entry in the dashboard, `DELETE /api/v1/waitlist/{entry_id}`), or 12 months after their latest sign-up
(`consent_at`), whichever comes first. The 12 months are enforced since 2026-10-18: the daily housekeeping
(`server/utils/housekeeping.py`, DEPLOYMENT.md § Daily housekeeping) deletes the entries whose `consent_at` is older,
and logs how many (`waitlist_deleted`), never who.

## Cities (8.4, decided 2026-09-29)

A visit's city (`visits.city`) is looked up from the anonymized address, from MaxMind's GeoLite2 City, whose licence
forbids using it to locate a person or a household (EULA §5). It goes out only counted, in the breakdowns:
- **Never one by one:** `/visits` and its CSV have no city.
- **Never a campaign link's:** its breakdown's `cities` is null, since its visits are one named recipient's.
- **A campaign's names a city only when its visits in the period came from at least 5 of its links**, 5 recipients.
  The rest are summed as "Other cities". Otherwise a day on which one recipient clicked, which `/recipients` shows,
  would name their city (`CAMPAIGN_CITY_MIN_LINKS`, `tests/test_phase84_cities.py`).
- **Countries aren't held to that.** They're coarse, and a campaign link's visits list them one by one (kept, below).

## Decisions kept, to revisit

These were questions for the user. On 2026-09-29 both were kept as they are, to revisit after the dogfood:
- **A campaign link's visits, one by one** (`/visits`, `/visits.csv`). A campaign link is one recipient's, so its visits
  are what one named person did, when, and from where. The campaign-level routes never list visits (3.17.1), but a
  campaign link's own do, like any link's.
- **Orphan visits' IPs** (`/analytics/orphan-visits`, and the MCP's `get_orphan_visits` and
  `list_orphan_visits_grouped`). They're anonymized, and shown to any signed-in account, since orphan visits belong
  to no organization. With external users (3.15), that would include them.

## Findings

1. **A crawler's preview of a campaign link carried its recipient's data. Fixed on 2026-09-29.**
   - `GET /{short_code}` answers a social crawler with a preview page. Its refresh URL was the destination, and for a
     campaign link that destination had the recipient's `user_data` in its query.
   - So when a recipient shared their link, the social network's crawler received their name or email.
   - Now the preview's refresh target is the destination the rules pick, with only what the shared address itself
     forwards. People still get their personalized redirect, unchanged
     (`tests/test_campaign_link_preview.py`).
   - Since 8.7 a crawler gets the preview page only for a link whose preview is rewritten; otherwise it gets the
     redirect, to read the page's own preview. That redirect is the same destination: no `user_data` either.
2. **A client could choose the address its visits were stored under, on the path straight to the ALB. Fixed on
   2026-09-29.**
   - uvicorn ran with `--forwarded-allow-ips "*"`, and replaced the connection's address with the leftmost
     `X-Forwarded-For` entry, which the client writes, before the app's own resolution ran.
   - So on the path straight to the ALB, a visit's and an orphan visit's IP, and so their country and city, were
     whatever the client sent. A visitor behind a corporate proxy that adds the header was stored under their
     internal address. The per-IP rate limits could be dodged the same way.
   - Now the app alone reads the header, from the right, and only from `TRUSTED_PROXIES` (DEPLOYMENT.md §
     Trusted-Proxy Configuration). Visits stored before keep what they have.
   - Verified in production on 2026-09-29, after hotfix #174:
     - 22 bad logins on the short domain, straight to the ALB, each with a new forged `X-Forwarded-For`, and the
       21st is a `429`: the limit counts the real address;
     - CloudWatch shows `client_ip_source` reading `xff` there, where it had read `socket`.
3. **`PATCH /api/v1/campaigns/{campaign_id}/tags` answers a malformed id with another 400 message**
   (`Invalid campaign ID: …`, where the others say `Invalid campaign ID format`). It's left as it is: this audit
   changes no behaviour.
