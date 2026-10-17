# Service accounts (ROADMAP 10.1)

Decided 2026-10-16 with the user, from Propuestas Griddo's proposal (`propuestas.griddo.io`, the first consumer:
its MCP hosts a proposal, builds a tokenized URL with UTMs, and asks Shurly for the short link). This is the
version to build; where it departs from that proposal, the reason is given.

## The problem

The API authenticates only with a person's API key. An integration that uses one:

- **attributes every link to that person**, whoever the link was for;
- **breaks** when that person regenerates their key or leaves the organization;
- **can't be told apart** from the person.

A fake person is no way out either: accounts come from Google Workspace sign-in (3.13), so a made-up user can't
sign in to generate a key, and nobody would own it.

## What v1 does

1. **A service account** belongs to the organization. It has a name (e.g. "Propuestas Griddo"), a description, a
   person responsible for it and a role (`member` or `admin`). It never signs in.
2. **One token per service account.** It's shown once when created and kept only as a hash. It can be renewed and
   revoked.
3. **The person the service acts for is the link's creator.** The service names them by email in
   `X-Shurly-On-Behalf-Of`. Shurly keeps which service account and which token created the link.
4. **The organization's owner** creates service accounts and their tokens, renews and revokes them, in Settings →
   Organization. Admins see the list but can't change it.

## Decisions, and why

| Decision | Why |
| --- | --- |
| A service account is a **user row marked as a service** (`users.kind = 'service'`), with an organization membership and role, and no Google identity or password | Authentication, the organization's rules and every route already work from "the current user". A separate entity would mean revisiting each route. Being a user doesn't let it sign in: Google sign-in, password login, setting a password, the MCP's Google sign-in and the members list all refuse or leave out `kind = 'service'` |
| **The person is the creator** (`urls.created_by` = their user) | `created_by` is required, and it decides who changes a link and who sees a personal one (`server/utils/access.py`). The person sees the link as theirs and can change it. The proposal had the service account as creator and the person as "on behalf of" only, which would have meant reworking access for every route |
| The person is named **by email** | The integrating service knows its user's Google email. It doesn't know Shurly's internal ids |
| **A person who isn't a Shurly user yet** gets a **422** (`on_behalf_of_unknown`) | They sign in to Shurly with Google once, then it works. Decided over attributing the link to the service and handing it over at their first sign-in |
| **No "channel"** (ui / api / mcp) | It answers no useful question, and an honest version would need ui, mcp, personal key and service account. What matters is the creator, and the service account when there was one. An empty service account means the person did it with their own credentials |
| **The token's reference**, never the token | The link keeps the token's row id. The token itself is only ever a hash. The link page shows "via Propuestas Griddo", never the token. The reference is there to answer "which links did this token create?" when a token leaks |
| **One token per account, with a 24-hour overlap on renewal** | Renewing makes a new token, and the old one keeps working for 24 hours (or until "Revoke the old one now") so the service can switch without failing requests. Revoking ends a token at once. The proposal's several tokens per account would do the same with more to manage |
| **Expiry optional** in v1 | Without warnings before it (v2), a required expiry would bring the integration down silently on the day. The token's last use is visible instead |
| **Acting on behalf grants nothing** | The service always acts with its own account's role. The header only decides whom the link is attributed to. A `member` service acting for an owner still can't change other people's links |
| **The service account that created a link can change it** | The creator is the person, so without this a `member` service couldn't later set the expiry or revoke the links it made, which Propuestas does (`set_expiry`, `revoke_link`). With it, Propuestas doesn't need `admin` |
| **Its links are the organization's**, never personal | A personal link is seen only by its creator, the person, so the service couldn't find its own link again |
| **The header only works with a service token** | With a person's API key or session it's a 403 (`on_behalf_of_not_allowed`). Otherwise anyone could attribute links to someone else |
| **The existing event log** for v1, not an audit table | Events go to CloudWatch, kept 60 days. A queryable two-year audit table with its API is v2 |
| **Owner-only management** | The user's call. The proposal also allowed admins |

## The data

**`users`**

- **`kind`:** `person` (default, every existing row) or `service`.
- **For a service:** `display_name` (e.g. "Propuestas Griddo"), `description` and `responsible_user_id` (a person
  in the organization).
- **Its email:** a placeholder that can't be a Google account, e.g. `<name>@service.invalid`. Lists of people show
  the display name instead.
- **Disabling one:** a revoked token, or the account removed from the organization. Nothing new is needed.

**`service_tokens`**, a new table

| Field | Notes |
| --- | --- |
| `id`, `service_account_id` | |
| `prefix` | The first characters after `shsa_`, shown in the UI to tell tokens apart |
| `token_hash` | A SHA-256 hash, as for API keys (`server/core/models/user.py`, `hash_api_key`) |
| `expires_at` | Optional |
| `last_used_at` | Updated when it authenticates, at most once a minute |
| `created_by_user_id`, `created_at` | The owner who made it |
| `replaced_at` | Set when renewed. It still authenticates until `replaced_at + 24h` |
| `revoked_at`, `revoked_by_user_id` | Ends it at once |

Only one token per account is active (not replaced, not revoked), plus at most one in its 24-hour overlap.

**`urls`**

- **`via_service_account_id`** (nullable): the service account that created the link. Shown on the link's page and
  in the API.
- **`via_token_id`** (nullable): the token it used. Internal only: not in the link's API response or its page. It
  answers "which links did this token create?" on the Organization page and in the event log.

Links created before this have both empty, meaning created by the person, whatever the tool.

## Authentication

- **The token's shape:** `shsa_<prefix>_<secret>`, with at least 32 random bytes. The `shsa_` start lets secret
  scanners recognize a leaked one.
- **How it's sent:** `Authorization: Bearer shsa_…`, as API keys are. `get_current_user` tells it from a JWT or a
  person's API key by its start, and the current user becomes the service account.
- **Unauthorized:** the same 401 for an unknown, revoked, expired or past-its-overlap token.
- **Not interactive:** service accounts can't generate personal API keys, set passwords or manage tokens. Those
  routes give a 403, as they already do for a person's API key.

## Acting on behalf of a person

`X-Shurly-On-Behalf-Of: ana.garcia@griddo.io` on a request that creates a link (`POST /api/v1/urls`,
`/urls/custom`).

| Situation | Answer |
| --- | --- |
| A service token, the email a member of its organization | The link's `created_by` is that person; `via_service_account_id` and `via_token_id` are set; the link belongs to the organization |
| A service token, the email not a user of its organization | 422 `on_behalf_of_unknown` |
| A service token, no header | The link's creator is the service account itself (for jobs that act for nobody, e.g. Propuestas' daily reconciliation) |
| A person's API key or session, with the header | 403 `on_behalf_of_not_allowed` |

On changes (`PATCH`, `DELETE`, tags), the header is accepted and goes into the event, but it doesn't change the
creator. Permission is always the service account's own:

- it can change the links it created (`via_service_account_id` is itself);
- with role `admin`, it can change the organization's links too.

## Managing them

These are for the organization's owner, signed in (a session, not an API key or a service token). Admins can read
them. None of them is an MCP tool.

| Route | Does |
| --- | --- |
| `GET /api/v1/service-accounts` | The organization's accounts, with each active token's prefix, `created_at`, `expires_at` and `last_used_at` |
| `POST /api/v1/service-accounts` | Creates one (`display_name`, `description`, `responsible_user_id`, `role`) |
| `PATCH /api/v1/service-accounts/{id}` | Changes the display name, description, person responsible or role |
| `DELETE /api/v1/service-accounts/{id}` | Revokes its tokens and removes it from the organization. Its links stay, with the account named |
| `POST /api/v1/service-accounts/{id}/token` | Creates the token, or renews it (the old one stays valid for 24 hours). Optional `expires_at`. Returns the secret this once |
| `DELETE /api/v1/service-accounts/{id}/token` | Revokes every token of the account at once. `?old_only=true` ends just the one still in its overlap |
| `GET /api/v1/service-accounts/{id}/links` | The links it created, filterable by `token_id`: what a leaked token touched |

`GET /api/v1/urls` gains `?via_service_account=<id>`.

`URLResponse` gains `via_service_account`: `{id, display_name}` or null. It never includes the token.

## In the app

- **The Organization page (`/dashboard/organization/`; a Settings tab until 3.14.7) → Service accounts:**
  - the accounts (name, person responsible, role, its token's prefix, expiry and last use);
  - for the owner: create, edit, renew the token, revoke, and remove;
  - the secret shown once, with copy-to-clipboard and "you won't see it again";
  - admins see it without the buttons;
  - members don't see the section.
- **The link's page:** "Created by Ana García via Propuestas Griddo", or "Created by Propuestas Griddo" when it
  acted for nobody.
- **The links list:** a filter by service account.

## Events (the existing event log)

- `service_account.created`, `.updated`, `.removed`;
- `service_token.created`, `.renewed`, `.revoked`;
- `url.created` / `url.updated` / `url.deleted`, with `service_account_id`, `token_id` and `on_behalf_of` when a
  service did it.

Never a secret or a hash.

*Corrected when built:* there were no `url.*` events before, so v1 writes them only when a service did it (and
`campaign.created` for a campaign made with the header). `on_behalf_of` is the person's user id, never the email:
the event log never carries an address (server/utils/event_log.py).

## Errors

The current `{"detail": "…"}` stays. The new cases add a stable `code`: `on_behalf_of_unknown`,
`on_behalf_of_not_allowed` and `service_account_not_allowed`. Shurly already answers 401, 403, 404, 409, 422 and 429
with their message. When Propuestas reports every failure as an internal error, that's for its client to fix.

## Security

- **The secret:** shown once, kept as a hash, never logged. Its prefix is the only part shown again.
- **Management:** only the owner creates or revokes. Revoking is immediate.
- **Acting on behalf:** grants no permission (see above).
- **Sign-in:** `kind = 'service'` can't sign in, by Google or by password, nor reach the MCP's Google sign-in.
- **Personal data:** docs/PERSONAL_DATA.md gets the new routes and the `via_*` columns. The tokens' `last_used_at`
  carries no IP.

## Acceptance

- [ ] The owner creates "Propuestas Griddo" (role `member`, responsible: a person) and its token. The secret shows
      once, then only `shsa_<prefix>…`. An admin sees the account without the buttons; a member doesn't see the
      section.
- [ ] `POST /api/v1/urls` with the token and `X-Shurly-On-Behalf-Of: ana.garcia@griddo.io`:
  - the link's creator is Ana;
  - `via_service_account` is Propuestas Griddo;
  - it belongs to the organization;
  - its page says "Created by Ana García via Propuestas Griddo";
  - the response has no token.
- [ ] The same with an email that isn't a Shurly user gives 422 `on_behalf_of_unknown`, and no link is made.
- [ ] A person's API key sending the header gets 403 `on_behalf_of_not_allowed`.
- [ ] The `member` service account can `PATCH` (e.g. `valid_until`) and delete the links it created, but not
      another person's organization link (403).
- [ ] Renewing the token: the old one works for 24 hours and stops after; "revoke the old one now" ends it at once.
      Revoking: the next request is a 401.
- [ ] `GET /api/v1/service-accounts/{id}/links?token_id=…` lists what that token created.
- [ ] A service account can't sign in, generate an API key, set a password or manage service accounts.
- [ ] People's API keys and sessions work as before. Their links have no `via_service_account`.

## v2, not now

- A queryable audit table (`audit_events`) with its API, kept 2 years. It has to go in docs/PERSONAL_DATA.md, since
  it holds emails.
- Fine-grained scopes: `urls:read`, `urls:write`, `urls:delete`, `tags:write`, `analytics:read`, `act_on_behalf`.
  Today's API keys have a scope that nothing enforces.
- A rate limit per token, with `RateLimit-*` headers and 429 `Retry-After`. Propuestas expects about 60 a minute,
  with bursts of 10.
- Warnings before a token expires and after 90 days unused. Then a default expiry.
- Allowed IP ranges per token.
- Handing links Propuestas made with a person's API key, before this, over to its service account, from Propuestas'
  own record (a one-off tool, like `adopt-personal-links`).
