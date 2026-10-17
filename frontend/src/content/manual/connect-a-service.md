---
title: Connect another service
description: For owners. Let another system, such as Propuestas Griddo, make links for your organization with a token of its own.
order: 4
---

Some systems make links for you: Propuestas Griddo, for example, shortens the link of every proposal it hosts. Give each one a **service account**: a token of its own, so its links say which person they’re for and which service made them, and nothing breaks when someone regenerates their API key or leaves.

Only owners make and change service accounts. Admins see them on the [Organization page](/dashboard/organization/); members don’t.

## Make one

1. On the [Organization page](/dashboard/organization/) (in the account menu, choose your organization’s name), under **Service accounts**, choose **New service account**.
2. Give it the system’s name (“Propuestas Griddo”), say what it’s for, and pick the **person responsible**: who to ask about it.
3. Pick its **role**. A **member** changes only the links it made, which is what most services need. An **admin** changes all the organization’s links: give it only to a service that has to.
4. Choose **Create service account**, then **Create token**. An expiry is optional; nothing warns before it comes, so leave it empty unless you’ll remember.
5. Copy the token and put it in the service’s settings straight away. **You won’t see it again**: Shurly keeps only a fingerprint of it, and shows how it starts, `shsa_` and eight characters, to tell tokens apart.

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

## Renew the token without downtime

Renew a token when it may have leaked, or as a routine:

1. Choose **Renew token** next to the service account, then copy the new one.
2. Put the new token in the service’s settings. The old one keeps working for **24 hours**, so the service doesn’t fail while you switch.
3. Once the service uses the new one, choose **End it now** on the previous token, or let the 24 hours run out.

**Last used** tells you whether the service is still using a token.

## Revoke or remove

- **Revoke** ends the service’s tokens at once: its next request is refused. Make it a new token to let it back in.
- **Remove service account** revokes its tokens and takes it out of the organization. The links it made keep working, and keep its name.

To see what a service made, choose **Its links**: the links list shows only that service’s. To see what one token made, choose **Links made with it** next to the token: what to check when a token may have leaked, before you renew it.
