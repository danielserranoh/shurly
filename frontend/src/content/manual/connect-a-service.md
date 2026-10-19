---
title: Connect another service
description: For owners. Let another system, such as Propuestas Griddo, make links for your organization with a token of its own.
order: 4
---

Some systems make links for you: Propuestas Griddo, for example, shortens the link of every proposal it hosts. Give each one a **service account**: a token of its own, so its links say which person they’re for and which service made them, and nothing breaks when someone regenerates their API key or leaves.

Only owners make and change service accounts. Admins see them, and what they did, on the [Organization page](/dashboard/organization/); members don’t.

## Make one

1. On the [Organization page](/dashboard/organization/) (in the account menu, choose your organization’s name), under **Service accounts**, choose **New service account**.
2. Give it the system’s name (“Propuestas Griddo”), say what it’s for, and pick the **person responsible**: who to ask about it.
3. Pick its **role**. A **member** changes only the links it made, which is what most services need. An **admin** changes all the organization’s links: give it only to a service that has to.
4. Choose **Create service account**. The dialog to make its token opens:
   - **What it may do**: every permission is checked to start with. Uncheck what the service doesn’t need. Campaigns and redirect rules go with links, and the service needs **Act for people in the organization** to make links for someone.
   - **Expires**: a year from today, to start with. Pick another day, or **No expiry**. Shurly warns you before it comes (see [When a token needs attention](#when-a-token-needs-attention)).
   - **Allowed IP ranges** (optional): the addresses the service calls from, one range per line, such as `203.0.113.0/24` or `2001:db8::/32`. From anywhere else its token is refused. Leave it empty to allow any address.

   Then choose **Create token**.
5. Copy the token and put it in the service’s settings straight away. **You won’t see it again**: Shurly keeps only a fingerprint of it, and shows how it starts, `shsa_` and eight characters, to tell tokens apart.

The token’s line shows what it may do (“All permissions”, or the ones it has), and where from when it has IP ranges.

A service account never signs in, with Google or a password. It only uses its token.

## What the service sends

The token goes in every request, like an API key:

```
Authorization: Bearer shsa_…
```

To make a link for someone, the service names them by their work email:

```
X-Shurly-On-Behalf-Of: ana.garcia@griddo.io
```

That person becomes the link’s creator: it’s theirs to see and change, it belongs to the organization, and its page says “Created by Ana García via Propuestas Griddo”. They need to have signed in to Shurly once: until then, the service gets an error and no link is made. Without the header, the service account is the creator, for jobs that act for nobody.

Naming someone gives the service none of their rights. It still acts with its own role: a member service can’t change an owner’s links by naming the owner.

### When Shurly refuses a request

The answer says why, in `code`:

- `scope_missing` (403): the token doesn’t have the permission this needs, and the message names it, such as `urls:delete`. Naming someone needs `act_on_behalf`.
- `ip_not_allowed` (403): the request came from outside the token’s allowed IP ranges.
- `service_account_not_allowed` (403): only people do this, such as managing service accounts.
- A **429** means too many requests: by default 120 a minute for the service account, all its tokens together. `Retry-After` says how many seconds to wait. Every answer to the service says where it stands, in `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`.

## Renew the token without downtime

Renew a token when it may have leaked, or as a routine:

1. Choose **Renew token** next to the service account. The dialog starts from what the current token may do and its IP ranges, and an expiry a year from today. Change them if you need to, choose **Renew token**, then copy the new one.
2. Put the new token in the service’s settings. The old one keeps working for **24 hours**, so the service doesn’t fail while you switch.
3. Once the service uses the new one, choose **End it now** on the previous token, or let the 24 hours run out.

**Last used** tells you whether the service is still using a token.

## When a token needs attention

A token’s line gets a badge when:

- **Expires soon**: it stops working within 14 days. Renew it before then: an expired token is refused.
- **Unused for 90 days**: nothing has used it in the last 90 days. If the service is gone, remove its account.

Owners and admins also see a dot on their avatar, at the top right, and the account menu says how many service tokens need attention. Shurly doesn’t send an email about it yet.

## Revoke or remove

- **Revoke** ends the service’s tokens at once: its next request is refused. Make it a new token to let it back in.
- **Remove service account** revokes its tokens and takes it out of the organization. The links it made keep working, and keep its name.

To see what a service made, choose **Its links**: the links list shows only that service’s. To see what one token made, choose **Links made with it** next to the token: what to check when a token may have leaked, before you renew it.

## See what a service did

Choose **Activity** next to the service account (owners find it, with **Its links**, in its menu: the button with three dots). It lists, newest first, what the service did with links, campaigns, tags and redirect rules, and on whose behalf, and what was done to it and its token, by whom. **Load more** shows older activity. Shurly keeps it for 2 years.
