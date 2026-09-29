# Personal data: what each route returns, and to whom

Reviewed on 2026-09-29. **Update this table in the same PR as any route change.**
`tests/test_personal_data_inventory.py` fails when:
- a route or MCP tool has no row, or a row names none;
- a row's guard isn't in its code;
- its MCP column doesn't match the tools.

So a new route can't widen who sees people's data without saying so here.

This is about what goes *out*: what a route returns, not what Shurly records. What a visit records is in
`server/core/models/visitor.py`. The IPs are anonymized when stored (`ANONYMIZE_REMOTE_ADDR`).

## People's data

| Category | What |
|---|---|
| **recipients' rows** | A campaign recipient's row of its CSV (`user_data`): names, emails, whatever the CSV had |
| **recipients' activity** | What one recipient did: their clicks and opens, and when |
| **visits** | Visits, counted or one by one: time, kind, country, browser, OS, device, referrer host. Never an IP. On a campaign link, a link's visits are one recipient's |
| **addresses** | Anonymized IPs, with user agents and referrers |
| **accounts** | Other people's accounts: emails, names, roles |
| **own account** | The caller's own: email, profile, photo, tokens, API key |

## Guards

A route's guard is the function that decides who gets an answer. The test finds it in the route's code, or in a helper
of the same module that the route calls.

| Guard | Who gets an answer |
|---|---|
| public | Anyone, signed in or not |
| `get_current_user` | Any signed-in account: a session token (JWT) or an API key |
| `get_signed_in_session` | A session token only: an API key gets a 403 |
| `sees` | A list, filtered to what the caller can see: their organization's, and their own personal ones (`Viewer.sees`, `server/utils/access.py`) |
| `visible_url_or_404`, `visible_campaign_or_404` | One link or campaign the caller can see, else 404. When a route changes it, one they can change, else 403: its creator, or an organization admin or owner (`server/utils/access.py`) |
| `find_urls`, `find_url`, `can_change` | The same rules, where the MCP's curated tools and bulk tagging apply them |
| `viewer` | The caller's organization, for something they create |
| `_my_membership` | A member of the caller's organization |
| `change_role`, `remove_member`, `transfer_ownership`, `removed_members`, `adopt_personal_links` | The organization's roles (`server/utils/organization.py`) |
| `RequireAuthMiddleware` | The MCP: an account's token or API key |

## Routes

| Route | People's data it returns | Who sees it | Guard | MCP |
|---|---|---|---|---|
| `GET /` | none | anyone | public | excluded |
| `GET /api/v1/analytics/campaigns/{campaign_id}/breakdown` | **visits**, counted over all its recipients | who can see the campaign | `visible_campaign_or_404` | `get_campaign_breakdown` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/recipients` | **recipients' rows** and **recipients' activity**: every recipient's `user_data`, clicks, opens, first and last click and last open | who can see the campaign | `visible_campaign_or_404` | `list_campaign_recipients` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/recipients.csv` | **recipients' rows** and **recipients' activity**: the list's, as a CSV | who can see the campaign | `visible_campaign_or_404` | excluded |
| `GET /api/v1/analytics/campaigns/{campaign_id}/summary` | **recipients' rows** and **recipients' activity**: the top 5 recipients' `user_data` and clicks | who can see the campaign | `visible_campaign_or_404` | `get_campaign_summary` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/timeseries` | **visits**, counted over all its recipients | who can see the campaign | `visible_campaign_or_404` | `get_campaign_timeseries` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/totals` | **visits**, counted over all its recipients | who can see the campaign | `visible_campaign_or_404` | `get_campaign_totals` |
| `GET /api/v1/analytics/campaigns/{campaign_id}/users` | **recipients' rows** and **recipients' activity**: every recipient's `user_data`, clicks and last click | who can see the campaign | `visible_campaign_or_404` | `get_campaign_users` |
| `GET /api/v1/analytics/orphan-visits` | **addresses**: the anonymized IP, user agent and referrer of each hit on an unknown code | any signed-in account: they belong to no organization. **Decision pending:** whether the IPs should be shown | `get_current_user` | `get_orphan_visits` |
| `GET /api/v1/analytics/overview` | **visits**, counted: totals, and the top links by code (a campaign link's clicks are one recipient's) | the links the caller can see | `sees` | `get_overview_stats` |
| `GET /api/v1/analytics/urls/{short_code}/breakdown` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_breakdown` |
| `GET /api/v1/analytics/urls/{short_code}/daily` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_daily_stats` |
| `GET /api/v1/analytics/urls/{short_code}/geo` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_geo_stats` |
| `GET /api/v1/analytics/urls/{short_code}/timeseries` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_timeseries` |
| `GET /api/v1/analytics/urls/{short_code}/totals` | **visits**, counted. On a campaign link, one recipient's | who can see the link | `visible_url_or_404` | `get_url_totals` |
| `GET /api/v1/analytics/urls/{short_code}/visits` | **visits**, one by one: time, kind, country, browser, OS, device, referrer host. Never an IP, a user agent or a full referrer | who can see the link. **Decision pending:** whether a campaign link's, one recipient's, should be listed | `visible_url_or_404` | `list_url_visits` |
| `GET /api/v1/analytics/urls/{short_code}/visits.csv` | **visits**, one by one, as the list, plus each visit's user agent. Never an IP | who can see the link. **Decision pending:** whether a campaign link's, one recipient's, should be listed | `visible_url_or_404` | excluded |
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
| `POST /api/v1/campaigns` | **own account**: the new campaign, the caller as its creator | any signed-in account | `get_current_user` | `create_campaign` |
| `DELETE /api/v1/campaigns/{campaign_id}` | none | who can change the campaign | `visible_campaign_or_404` | `delete_campaign` |
| `GET /api/v1/campaigns/{campaign_id}` | **recipients' rows**: every recipient's `user_data`. **accounts**: the creator's email and names | who can see the campaign | `visible_campaign_or_404` | `get_campaign` |
| `GET /api/v1/campaigns/{campaign_id}/export` | **recipients' rows**: every recipient's `user_data`, as a CSV | who can see the campaign | `visible_campaign_or_404` | `export_campaign` |
| `PATCH /api/v1/campaigns/{campaign_id}/tags` | none | who can change the campaign | `visible_campaign_or_404` | `update_campaign_tags` |
| `GET /api/v1/health` | none | anyone | public | excluded |
| `GET /api/v1/health/db` | none | anyone | public | excluded |
| `GET /api/v1/organization` | **own account**: the organization, and the caller's role | a member | `_my_membership` | `get_organization` |
| `POST /api/v1/organization/adopt-personal-links` | none: counts | an owner | `adopt_personal_links` | excluded |
| `GET /api/v1/organization/members` | **accounts**: every member's email, names, role and join date | any member | `_my_membership` | `list_organization_members` |
| `DELETE /api/v1/organization/members/{user_id}` | none | an admin or owner, as `remove_member` allows | `remove_member` | excluded |
| `PATCH /api/v1/organization/members/{user_id}` | **accounts**: that member's email, names and role | an admin or owner, as `change_role` allows | `change_role` | excluded |
| `GET /api/v1/organization/removed-members` | **accounts**: removed people's emails and names, and how many links and campaigns each still owns | an owner | `removed_members` | excluded |
| `POST /api/v1/organization/transfer-ownership` | **accounts**: the new owner's email, names and role | the owner | `transfer_ownership` | excluded |
| `GET /api/v1/tags` | none: tags are names shared by everyone | any signed-in account | `get_current_user` | `list_tags` |
| `POST /api/v1/tags` | none | any signed-in account | `get_current_user` | `create_tag` |
| `DELETE /api/v1/tags/{tag_id}` | none | any signed-in account | `get_current_user` | `delete_tag` |
| `PATCH /api/v1/tags/{tag_id}` | none | any signed-in account | `get_current_user` | `update_tag` |
| `GET /api/v1/urls` | **recipients' rows** and **recipients' activity**: a campaign link's `user_data`, clicks and last click. **accounts**: each link's creator's email and names | the links the caller can see: their organization's, and their own | `sees` | `list_urls` |
| `POST /api/v1/urls` | **own account**: the new link, the caller as its creator | any signed-in account | `get_current_user` | `create_short_url` |
| `POST /api/v1/urls/bulk/tags` | none: counts | the links the caller can change | `find_urls`, `can_change` | `bulk_tag_urls` |
| `POST /api/v1/urls/custom` | **own account**: the new link, the caller as its creator | any signed-in account | `get_current_user` | `create_custom_url` |
| `POST /api/v1/urls/fetch-metadata` | none: a page's Open Graph tags | any signed-in account | `get_current_user` | `fetch_url_metadata` |
| `DELETE /api/v1/urls/{short_code}` | none | who can change the link | `visible_url_or_404` | `delete_url` |
| `GET /api/v1/urls/{short_code}` | **recipients' rows** and **recipients' activity**, for a campaign link. **accounts**: the creator's email and names | who can see the link | `visible_url_or_404` | `get_url` |
| `PATCH /api/v1/urls/{short_code}` | **recipients' rows** and **recipients' activity**, for a campaign link. **accounts**: the creator's email and names | who can change the link | `visible_url_or_404` | `update_url` |
| `GET /api/v1/urls/{short_code}/preview` | none: the destination's Open Graph tags | who can see the link | `visible_url_or_404` | `get_url_preview` |
| `POST /api/v1/urls/{short_code}/refresh-preview` | none | who can change the link | `visible_url_or_404` | `refresh_url_preview` |
| `GET /api/v1/urls/{short_code}/rules` | none | who can see the link | `visible_url_or_404` | `list_redirect_rules` |
| `POST /api/v1/urls/{short_code}/rules` | none | who can change the link | `visible_url_or_404` | `create_redirect_rule` |
| `DELETE /api/v1/urls/{short_code}/rules/{rule_id}` | none | who can change the link | `visible_url_or_404` | `delete_redirect_rule` |
| `PATCH /api/v1/urls/{short_code}/rules/{rule_id}` | none | who can change the link | `visible_url_or_404` | `update_redirect_rule` |
| `PATCH /api/v1/urls/{short_code}/tags` | none | who can change the link | `visible_url_or_404` | `update_url_tags` |
| `DELETE /mcp` | none: a redirect to `/mcp/` | anyone | public | excluded |
| `GET /mcp` | none: a redirect to `/mcp/` | anyone | public | excluded |
| `POST /mcp` | none: a redirect to `/mcp/` | anyone | public | excluded |
| `GET /robots.txt` | none | anyone | public | excluded |
| `GET /{short_code}` | **recipients' rows**: a campaign link adds its recipient's `user_data` to the destination's query, for people (personalization). A crawler's preview page never carries it (finding 1, fixed) | anyone with the link (by design) | public | excluded |
| `GET /{short_code}/track` | none | anyone | public | excluded |

## The MCP's own routes

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
| MCP `get_url_analytics_summary` | **visits**, counted, and how many distinct addresses. On a campaign link, one recipient's | who can see the link | `find_url` | curated |
| MCP `list_orphan_visits_grouped` | **addresses**: the anonymized IPs, user agents and referrers of hits on unknown codes, grouped | any account: they belong to no organization. **Decision pending:** whether the IPs should be shown | `RequireAuthMiddleware` | curated |
| MCP `create_campaign_from_rows` | **own account**: the new campaign | any account | `viewer` | curated |
| MCP `add_redirect_rule` | none | who can change the link | `find_url`, `can_change` | curated |

## Decisions pending

These rows record a question for the user, not a verdict:
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
2. **`PATCH /api/v1/campaigns/{campaign_id}/tags` answers a malformed id with another 400 message**
   (`Invalid campaign ID: …`, where the others say `Invalid campaign ID format`). It's left as it is: this audit
   changes no behaviour.
