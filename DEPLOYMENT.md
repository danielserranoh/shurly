# Shurly AWS Deployment Guide (ECS Express on griddo-main)

This guide walks the operator through deploying Shurly to AWS ECS Express
Mode in `eu-south-2`, with DNS in the separate `griddo-production` account.

It is structured to mirror — and reuse — the patterns established by the
sibling Shlink deploy in the same account. For shared concepts (IAM roles,
shared ALB, ALB rule-sync Lambda, default VPC) the canonical reference is:

> `~/Documents/Cowork/Griddo/Marketing & Comms/WebAnalytics/shlink-deploy-guide.md`

## Architecture

```
Internet
   ↓
shared ALB (eu-south-2) — created by ECS Express for Shlink, reused for Shurly
   ↓
   ├─ priority 10 → shlink-api      → go.griddo.io
   ├─ priority 11 → shlink-web      → links.griddo.io
   └─ priority 12 → shurly-api      → shurly.griddo.io (the app, API, MCP), s.griddo.io (interim, until Phase 8)
        ↓
        Fargate task (x86_64, 0.25 vCPU / 0.5 GB)
        FastAPI + uvicorn  ⇄  RDS PostgreSQL t4g.micro
                                 (private inside the default VPC)
```

Two AWS accounts:

| Account | ID | SSO profile | Owns |
|---|---|---|---|
| Griddo Main | 686255983646 | `griddo-main` | ECS, RDS, ECR, ACM, ALB, IAM |
| Griddo Production | 253490783612 | `griddo-production` | Route 53 zone for `griddo.io` |

Hostnames:

| Host | Service | Phase |
|---|---|---|
| `shurly.griddo.io` | The web, the app (`/dashboard/`), the API (`/api/v1/*`) and the MCP (`/mcp/`) | 4; the frontend at 4.10 |
| `go.griddo.io` | Short links only | Shlink until Phase 8, then Shurly |
| `s.griddo.io` | Interim: the API and test links until Phase 8, then deleted entirely | 4 |

Decided 2026-09-28. Nothing was published on `s.griddo.io`, so it goes at the Phase 8 cutover with no redirects kept.

## Prerequisites

- AWS CLI configured with two SSO profiles (`griddo-main`, `griddo-production`).
- Docker (BuildKit + buildx). On Apple Silicon, `linux/arm64` builds are native; on x86_64 hosts buildx falls back to QEMU emulation, which works but is slower.
- Python 3.10+ and `uv`, to run the tests before the first deploy: `scripts/deploy_ecs.sh` doesn't run them
  (the deploy workflow does, before every later one).
- Existing infrastructure already provisioned in `griddo-main` for the Shlink deploy (we reuse it):
  - Default VPC `vpc-01b31e19aa032bcff`
  - IAM roles `ecsTaskExecutionRole` and `ecsInfrastructureRoleForExpressServices`
  - Shared Express Mode ALB (located by name pattern; the script reads its DNS / zone / listener at runtime)
  - Lambda `ecs-alb-rule-sync` + EventBridge rule

If any of those are missing, run the corresponding section of the Shlink deploy guide first — they're tenant-wide infrastructure shared across services.

---

## End-to-end deploy walkthrough

The full first-deploy sequence, top to bottom:

### 1. RDS PostgreSQL

```bash
AWS_PROFILE=griddo-main ./scripts/create_rds.sh
```

The script:
- Locates the default VPC.
- Reuses the `shlink-db-subnets` subnet group when present (same VPC, fewer moving parts) or creates `shurly-db-subnets`.
- Creates `shurly-db-sg` with VPC-only ingress on 5432.
- Creates `shurly-db` (db.t4g.micro, gp3, 20 GB, encrypted, no public access, no multi-AZ for dev cost).
- Generates a random master password and prints it once. Save it to AWS Secrets Manager and your password manager.

The instance takes ~5–10 minutes to become available. The script blocks until it does.

### 2. ACM certificate for `s.griddo.io`

```bash
# 2.1 Request the cert from griddo-main
aws acm request-certificate --region eu-south-2 --profile griddo-main \
    --domain-name s.griddo.io \
    --validation-method DNS

# Capture its ARN
CERT_ARN=$(aws acm list-certificates --region eu-south-2 --profile griddo-main \
    --query "CertificateSummaryList[?DomainName=='s.griddo.io'].CertificateArn" \
    --output text)

# 2.2 Inspect the validation CNAME
aws acm describe-certificate --region eu-south-2 --profile griddo-main \
    --certificate-arn "$CERT_ARN" \
    --query "Certificate.DomainValidationOptions[0].ResourceRecord"
```

Take the `Name` and `Value` from the previous output and write them to Route 53 **from the `griddo-production` profile** (zone `Z0999097TJGECCBKJOY1`):

```bash
aws route53 change-resource-record-sets --profile griddo-production \
    --hosted-zone-id Z0999097TJGECCBKJOY1 \
    --change-batch '{
        "Changes": [{
            "Action": "UPSERT",
            "ResourceRecordSet": {
                "Name": "<validation-name-from-above>",
                "Type": "CNAME",
                "TTL": 300,
                "ResourceRecords": [{"Value": "<validation-value-from-above>"}]
            }
        }]
    }'

aws acm wait certificate-validated --region eu-south-2 --profile griddo-main \
    --certificate-arn "$CERT_ARN"
```

### 3. JWT secret

```bash
JWT_SECRET_KEY=$(openssl rand -hex 32)
echo "JWT_SECRET_KEY=$JWT_SECRET_KEY"
# Save it. You'll feed it into deploy_ecs.sh on first run.
```

### 4. ECS Express service

Create a `.env` file in the project root with the credentials gathered above:

```bash
cat > .env <<EOF
DB_HOST=<from create_rds.sh output>
DB_PASSWORD=<from create_rds.sh output>
JWT_SECRET_KEY=<from step 3>
EOF
chmod 600 .env  # avoid accidental git add
```

`CORS_ORIGINS` is left out: the script defaults it to `'[]'`, as the frontend shares the API's host (§ CORS).
To set one, single-quote the JSON (`CORS_ORIGINS='["http://localhost:4232"]'`), or `source` mangles it.

Then deploy:

```bash
AWS_PROFILE=griddo-main ./scripts/deploy_ecs.sh
```

The script:
- Creates the ECR repository `shurly-api` if needed (with image scanning + immutable tags).
- Builds the container for `linux/amd64` and `linux/arm64` (Fargate runs the first) and pushes it tagged
  `<sha>-<timestamp>`.
- Calls `aws ecs create-express-gateway-service` with all Phase 3.9/3.10 settings as env vars, `--cpu 256 --memory 512`, healthcheck `/api/v1/health`, scaling 1–2 tasks, and Shlink's existing IAM roles.
- Tolerates the documented `--monitor-resources` timeout (Shlink lesson #2) and verifies via `describe-express-gateway-service`.
- **Creates only.** Once the service exists, the script stops before building anything: an update would send
  the container it builds, whose environment holds only the variables above, and drop every setting added on
  the service since. Later images go out with the deploy workflow (§ CI/CD with OIDC), which changes only the
  image; settings change on the live service (§ Settings, under Sign in with Google).

Smoke the auto-generated host:

```bash
curl https://shurly-api.ecs.eu-south-2.on.aws/api/v1/health
# {"status":"ok"}
```

### 5. Custom domain `s.griddo.io`

```bash
AWS_PROFILE=griddo-main ./scripts/setup_custom_domain.sh
```

This wires the three things ECS Express does NOT handle for custom domains:

1. Adds the validated ACM cert to the shared ALB's HTTPS listener.
2. Creates a routing rule at priority **12** (next free after Shlink's 10 / 11) that matches `host-header=s.griddo.io` and forwards to Shurly's currently-active target group.
3. Writes the Route 53 A-alias from `griddo-production` (cross-account boundary).

The script prints the **Express Mode rule priority** that points at Shurly's auto-generated host. **Note that priority** — you need it for the next step.

### 6. Extend the ALB rule-sync Lambda

Express Mode flips traffic between two target groups for blue/green deploys. Manual rules (priority 12) need to follow the active TG; otherwise, after each rollout, `s.griddo.io` would point at an inactive TG and 503.

The `ecs-alb-rule-sync` Lambda (created during the Shlink deploy, see Shlink Phase 10) already handles this for Shlink. Its source now lives in [infra/ecs-alb-rule-sync/](infra/ecs-alb-rule-sync/README.md), which documents its triggers, permissions, deploy and rollback. Since 27 Sep 2026 it follows each rollout from `IN_PROGRESS` instead of syncing only on `COMPLETED`, which removed a ~1 min 503 per deploy. To add a service, edit its `RULE_SYNC_MAP`:

```python
# In the Lambda code (deployed in griddo-main):
RULE_SYNC_MAP = {
    "1": "10",  # shlink-api  → go.griddo.io
    "3": "11",  # shlink-web  → links.griddo.io
    "<N>": "12",  # shurly-api  → s.griddo.io   ← NEW (use the priority printed by setup_custom_domain.sh)
}
```

Repackage and update:

```bash
cd infra/ecs-alb-rule-sync
zip -X /tmp/alb-rule-sync.zip alb-rule-sync.py
aws lambda update-function-code --region eu-south-2 --profile griddo-main \
    --function-name ecs-alb-rule-sync \
    --zip-file fileb:///tmp/alb-rule-sync.zip
```

Verify:

```bash
aws lambda invoke --region eu-south-2 --profile griddo-main \
    --function-name ecs-alb-rule-sync \
    --payload '{}' \
    /dev/stdout
# Expect ["No changes needed"] or a "Synced priority 12 with N" entry.
```

Force a redeploy and confirm `s.griddo.io` stays up:

```bash
SERVICE_ARN=$(aws ecs list-services --region eu-south-2 --profile griddo-main \
    --cluster default \
    --query "serviceArns[?contains(@, 'shurly-api')] | [0]" --output text)

aws ecs update-express-gateway-service --region eu-south-2 --profile griddo-main \
    --service-arn "$SERVICE_ARN" --force-new-deployment

# Wait ~2 min, then:
curl https://shurly.griddo.io/api/v1/health
```

### 7. Smoke checklist

```bash
# Liveness
curl https://shurly.griddo.io/api/v1/health
# Readiness (DB connectivity)
curl https://shurly.griddo.io/api/v1/health/db

# Sign in with Google, once configured: /start redirects to accounts.google.com
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' https://shurly.griddo.io/api/v1/auth/google/start

# Login → JWT. There's no sign-up with a password in production since 3.13: the smoke
# account predates it, and keeps its password until someone signs in with Google as it.
TOKEN=$(curl -s -X POST https://shurly.griddo.io/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"smoke@griddo.io","password":"smoke-test-1234"}' | jq -r .access_token)

# Create a short URL
curl -X POST https://shurly.griddo.io/api/v1/urls \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"url":"https://griddo.io"}'

# Redirect (302)
curl -I https://s.griddo.io/<short-code-from-above>

# Tracking pixel (43-byte GIF, no-store)
curl -I https://s.griddo.io/<short-code>/track

# robots.txt (default-deny)
curl https://s.griddo.io/robots.txt

# Orphan visit logging
curl https://s.griddo.io/typoXYZ
curl -H "Authorization: Bearer $TOKEN" \
    https://shurly.griddo.io/api/v1/analytics/orphan-visits
```

---

## CI/CD with OIDC

GitHub Actions deploys via OIDC, not access keys. SSO-managed accounts don't issue long-lived access keys, so OIDC is the right fit anyway: GitHub presents an identity token to AWS STS, AWS lets the workflow assume an IAM role.

### One-time setup in `griddo-main`

```bash
# 1. Register GitHub as an OIDC provider (skip if it already exists for Shlink)
aws iam create-open-id-connect-provider --profile griddo-main \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. Trust policy that scopes assumption to this exact repo + branch pattern
cat > trust-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::686255983646:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:danielserranoh/shurly:environment:production"
      }
    }
  }]
}
EOF

aws iam create-role --profile griddo-main \
    --role-name github-actions-shurly-deploy \
    --assume-role-policy-document file://trust-policy.json
```

The subject is the GitHub environment, not a branch: the deploy job runs in `production` (Settings →
Environments), whose deployment branch policy allows `main` only. Together, only a workflow on `main` can
assume the role. Until 2026-09-29 the trust was `repo:danielserranoh/shurly:*` (any branch, any environment).

### Permissions policy

The role needs the minimum to push images and update the service:

```bash
cat > deploy-policy.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrLoginAndPush",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchGetImage",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": [
        "arn:aws:ecr:eu-south-2:686255983646:repository/shurly-api",
        "*"
      ]
    },
    {
      "Sid": "EcsExpressDeploy",
      "Effect": "Allow",
      "Action": [
        "ecs:ListServices",
        "ecs:DescribeExpressGatewayService",
        "ecs:UpdateExpressGatewayService"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-role-policy --profile griddo-main \
    --role-name github-actions-shurly-deploy \
    --policy-name shurly-deploy \
    --policy-document file://deploy-policy.json
```

> **Note**: the `ecr:GetAuthorizationToken` action requires `Resource: "*"` (it's a service-level operation, not a resource-level one). The asterisk on the ECR block is for that single action; the layer/image actions are scoped to the specific repository.

### Wire the role ARN into GitHub Secrets

In the repo's **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::686255983646:role/github-actions-shurly-deploy` |

That's the only secret needed. No `AWS_ACCESS_KEY_ID`, no `AWS_SECRET_ACCESS_KEY`.

### Workflow trigger

`deploy-backend.yml` deploys on every push to `main`. `main` is branch-protected (a PR with passing tests), so a commit that lands there has already passed that gate. It also runs by hand from the Actions tab (`workflow_dispatch`), for a rollback or a redeploy.

**Dependencies are pinned** by the committed `uv.lock`.
- The deploy job runs `uv sync --locked`, and the image `uv sync --frozen`, so a release installs what its PR's CI
  tested.
- The Monday rebuild (§ Geolocation data) changes no Python dependency, and a rollback rebuilds what shipped.
- New versions arrive only through Dependabot's weekly PR against `dev` (`.github/dependabot.yml`: uv and the
  workflows' actions, minor and patch grouped), which is QA'd and released like any other.

**So is what builds them.**
- The dockerfile pins `python:3.11-slim` by digest. Dependabot's docker PR moves the digest weekly, but never
  to a new Python.
- `astral-sh/setup-uv` is pinned by commit in the workflows, and Dependabot bumps it with the other actions.
- uv itself is one version, the one that reads `uv.lock`: `UV_VERSION` in both workflows, and the dockerfile's
  `ghcr.io/astral-sh/uv:<version>@<digest>`. `tests/test_dependency_lock.py` checks they agree. Dependabot
  leaves uv alone.
- **To bump uv:**
  1. Update your own (`uv self update <version>`) and run `uv lock`.
  2. Change the dockerfile's uv image, both its tag and its digest (`docker buildx imagetools inspect
     ghcr.io/astral-sh/uv:<version>`).
  3. Change `UV_VERSION` in `test.yml` and `deploy-backend.yml`.
  4. Put all of it in one PR.

---

## Frontend hosting (Phase 4.10)

**Live since 2026-09-29.** Distribution `EJDA8EMBWVGDG` (`d1e7o4qkz3x60l.cloudfront.net`), bucket
`shurly-frontend-686255983646` (eu-south-2), OAC `shurly-frontend-oac`, response-headers policy
`shurly-security-headers`, function `shurly-static-paths`, certificate in us-east-1 for `shurly.griddo.io`, deploy role
`github-actions-shurly-frontend-deploy` (repo secret `AWS_FRONTEND_DEPLOY_ROLE_ARN`, variables `FRONTEND_BUCKET` and
`CLOUDFRONT_DISTRIBUTION_ID`). The task has `CLOUDFRONT_ORIGIN_SECRETS`, `FRONTEND_URL=https://shurly.griddo.io` and
`CORS_ORIGINS='[]'`. No custom error responses. The secret origin header's value is in `_exchange/credentials.md`.

The static build (`frontend/dist/`) lives in a private S3 bucket behind **one CloudFront distribution for
`shurly.griddo.io`**, which also carries the API and the MCP to the ALB. The app and the API then share one
origin, so the browser makes no cross-origin calls. Prepared in the repo: the deploy workflow, the CloudFront
Function and this section. The AWS resources below are still to be created (ROADMAP 4.10).

### The distribution

| Path pattern | Origin | Cache policy | Origin request policy | Function |
|---|---|---|---|---|
| `/api/*` | the ALB | CachingDisabled | AllViewerAndCloudFrontHeaders-2022-06 | — |
| `/mcp*` | the ALB | CachingDisabled | AllViewerAndCloudFrontHeaders-2022-06 | — |
| `/.well-known/*` | the ALB | CachingDisabled | AllViewerAndCloudFrontHeaders-2022-06 | — |
| `/docs*`, `/redoc`, `/openapi.json` | the ALB | CachingDisabled | AllViewerAndCloudFrontHeaders-2022-06 | — |
| Default (`*`) | the S3 bucket, with Origin Access Control | CachingOptimized | — | `static-paths`, viewer request |

The client IP assumes the ALB's X-Forwarded-For processing mode is **append**, its default
(`routing.http.xff_header_processing.mode`): the edge's address goes after the one CloudFront appended (§ Client IPs
behind CloudFront).

- **ALB behaviours:** all HTTP methods (the API takes `POST`, `PUT`, `PATCH`, `DELETE`). The origin request policy
  forwards the `Host` header (`shurly.griddo.io`), so the ALB's host rule (priority 12) and its certificate match as
  they do today, and it adds `CloudFront-Viewer-Address`, the client IP (§ Client IPs behind CloudFront). Not plain
  AllViewer: under it, any `CloudFront-*` header that reaches the app is the viewer's own.
- **The ALB origin:** HTTPS only, with the custom origin header `X-Origin-Verify` (§ Client IPs behind CloudFront).
- **What each path is:** `/mcp*` covers the bare `/mcp` (the API's 308 to `/mcp/`), the MCP itself and its OAuth
  endpoints (`/mcp/authorize`, `/mcp/token`, …). `/.well-known/*` carries the OAuth metadata (5.8).
- **Short links:** they live on `s.griddo.io` and later `go.griddo.io`, which keep going straight to the ALB. On
  `shurly.griddo.io`, a path that isn't listed above is a page, not a short code.

### The function

`infra/cloudfront/static-paths.js` (runtime `cloudfront-js-2.0`) goes on the default behaviour only, as a viewer
request function. Astro writes each page as `<path>/index.html`, and a private bucket reached through the S3 REST
endpoint doesn't resolve directory indexes. So the function applies three rules:

- a path ending in `/` gets `index.html`;
- **a dot in the last segment means a file** (`/_astro/…`, `/favicon.svg`), left as is;
- anything else gets a `301` to the path with its slash, keeping the query.

A page whose last segment has a dot (`/manual/v1.2/`) therefore has to be linked with its trailing slash. The tests
are in `frontend/tests/cloudfront-static-paths.test.mjs`, including redirects that can't leave the site
(`//host`, `/\host`).

### Error pages: an open decision

The build has `/404.html`, but CloudFront's custom error responses apply to the whole distribution. Mapping 403 or
404 to `/404.html` would also replace the API's own 403 and 404 answers, which the app reads (`reauth_required`,
role checks, unknown links, the MCP's errors). Behind OAC, S3 answers 403 for a missing object, unless the
distribution may list the bucket, and then it's 404. The options:

1. **No custom error responses.** An unknown page shows S3's XML error. It's simple, and rare, since the app only
   links to pages that exist.
2. **A Lambda@Edge origin-response function on the default behaviour only**, turning S3's 403 or 404 into
   `/404.html` with status 404. It's per behaviour, so the API is untouched, but it adds a Lambda in us-east-1.

### Response headers

Add a response-headers policy on the default behaviour with:

- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-Frame-Options: DENY`

### Content-Security-Policy (Phase 6.3)

The Content-Security-Policy is not in this headers policy: **it ships with the build.** Every page carries
`<meta http-equiv="content-security-policy">`, written by Astro (`security.csp` in `astro.config.mjs`) with the
hashes of the scripts it emits. Those hashes change whenever the code does, so they belong with the pages, not in a
CloudFront setting that would need updating on every deploy. The policy:

| Directive | Value | Why |
|---|---|---|
| `script-src` | `'self'` plus hashes | Bundled scripts, and the inline ones in `src/inline-scripts.mjs`: the sign-in guards and the Settings tab picker. No `'unsafe-inline'`, no `'unsafe-eval'` |
| `style-src` | `'self'` plus hashes | `<style>` elements only by hash |
| `style-src-attr` | `'unsafe-inline'` | Style attributes are set from data (chart widths, tag colours), and no hash can cover an attribute |
| `img-src` | `'self' https: data: blob:` | Link previews from any site, small assets the build inlines, the QR code's PNG export |
| `font-src` | `'self' data:` | The build inlines one small font |
| `connect-src` | `'self'` plus the origin of `PUBLIC_API_URL` | The API: the same origin in production |
| `default-src`, `base-uri`, `form-action` | `'self'` | |
| `object-src` | `'none'` | |
| `require-trusted-types-for` | `'script'` | The DOM's HTML sinks (`innerHTML` and the like) take TrustedHTML only, not strings |
| `trusted-types` | `shurly-html` | The one policy allowed: `src/utils/html.ts`, behind `setHTML` and `toElement` |

- **Trusted Types:** the only way to put markup into the page is `setHTML` or `toElement` (`src/utils/html.ts`).
  They pass it through the one policy, `shurly-html`, and escape anything that isn't markup from the escaping
  `html` tag.
  - A raw `el.innerHTML = '…'` anywhere else throws, and so does creating any other policy or a second one.
  - Browsers without Trusted Types ignore both directives, and the markup stays a string.
  - `frontend/tests/no-raw-html.test.mjs` fails on a `createPolicy` outside `html.ts`.
- **What a `<meta>` policy can't do:** it can't set `frame-ancestors`. `X-Frame-Options: DENY` above covers
  framing.
- **Placement:** a `<meta>` policy only governs what comes after it. Astro writes it at the end of `<head>`, so the
  inline guards run first in `<body>`, still before anything paints.
- **The build check:** `npm run build` ends with `scripts/check-csp.mjs`, and the build fails if any page:
  - lacks the policy;
  - has a script or preload before it;
  - has an inline script or `<style>` its hashes don't cover;
  - has an inline event handler or a `javascript:` URL;
  - lacks `require-trusted-types-for 'script'` or `trusted-types shurly-html`, or allows `default`, `*` or
    `'allow-duplicates'`.

  It also fails unless exactly one built script chunk defines the policy. Two chunks would mean `html.ts` was
  bundled twice, and a page loading both would throw at the second `createPolicy`.

  Then `scripts/check-dev-only.mjs` fails the build if a script carries development-only code: the link
  analytics' mock (`&mock` under `astro dev`, Phase 3.16), found by its marker or its chunk's name.
- **Local testing:** `astro dev` has no CSP (an Astro limitation). To see it, run `npm run build` and then
  `npx astro preview`, with `PUBLIC_API_URL` pointing at a running API.

### Certificate

CloudFront only takes ACM certificates from **us-east-1**. The certificate issued for `shurly.griddo.io` on
2026-09-28 is in eu-south-2, for the ALB, and stays there. Request a new one in `griddo-main`, and validate it by
DNS in the `griddo-production` zone as in § 2:

```bash
aws acm request-certificate --profile griddo-main --region us-east-1 \
    --domain-name shurly.griddo.io --validation-method DNS
```

### The bucket

The bucket is private: Block Public Access on, no static website hosting. The distribution reads it through
Origin Access Control. The bucket policy (the console offers it when you pick OAC) lets only that distribution
`s3:GetObject`, with `AWS:SourceArn` set to the distribution's ARN.

### The deploy role

`deploy-frontend.yml` assumes its own role with least privilege: it writes to that one bucket and invalidates
that one distribution. The GitHub OIDC provider already exists (§ CI/CD with OIDC). The trust policy allows only
`main`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::686255983646:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:danielserranoh/shurly:ref:refs/heads/main"
      }
    }
  }]
}
```

The permissions policy, with the bucket name and distribution id filled in:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListTheSiteBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>"
    },
    {
      "Sid": "WriteTheSite",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::<bucket>/*"
    },
    {
      "Sid": "InvalidateTheSite",
      "Effect": "Allow",
      "Action": "cloudfront:CreateInvalidation",
      "Resource": "arn:aws:cloudfront::686255983646:distribution/<distribution-id>"
    }
  ]
}
```

```bash
aws iam create-role --profile griddo-main \
    --role-name github-actions-shurly-frontend-deploy \
    --assume-role-policy-document file://frontend-trust-policy.json
aws iam put-role-policy --profile griddo-main \
    --role-name github-actions-shurly-frontend-deploy \
    --policy-name shurly-frontend-deploy \
    --policy-document file://frontend-deploy-policy.json
```

In the repo's **Settings → Secrets and variables → Actions**:

| Kind | Name | Value |
|---|---|---|
| Secret | `AWS_FRONTEND_DEPLOY_ROLE_ARN` | `arn:aws:iam::686255983646:role/github-actions-shurly-frontend-deploy` |
| Variable | `FRONTEND_BUCKET` | the bucket's name |
| Variable | `CLOUDFRONT_DISTRIBUTION_ID` | the distribution's id |
| Variable | `PUBLIC_SHORT_DOMAIN` | unset until the cutover, which sets `go.griddo.io` (§ The cutover) |

What the workflow does, on merges to `main` that touch `frontend/**` and by hand:

- While `FRONTEND_BUCKET` is unset, it logs `frontend deploy skipped: FRONTEND_BUCKET unset` and stops.
- Otherwise it runs `npm ci`, `npm test` and `npm run build` with the production values:
  - `PUBLIC_API_URL=https://shurly.griddo.io`
  - `PUBLIC_SITE_URL=https://shurly.griddo.io`
  - `PUBLIC_SHORT_DOMAIN`: the variable's value, `s.griddo.io` while it's unset
- It uploads `_astro/` first, with `max-age=31536000, immutable`: those names carry a hash, and old files are
  kept for pages still open in someone's browser.
- It uploads everything else with `max-age=0, must-revalidate`, and removes pages that are gone.
- It sets the manifest's content type, and invalidates `/*`.

### Cutover and rollback

Today `shurly.griddo.io` is a Route 53 alias to the ALB, in the `griddo-production` zone. Going live changes that
alias to the distribution, once the distribution is deployed with the certificate. Before switching, test through
CloudFront with the real host name:

```bash
EDGE=$(dig +short d111111abcdef8.cloudfront.net | head -1)   # the distribution's domain name
curl -s --resolve shurly.griddo.io:443:$EDGE https://shurly.griddo.io/api/v1/health
curl -sI --resolve shurly.griddo.io:443:$EDGE https://shurly.griddo.io/dashboard/
```

After the switch, set `FRONTEND_URL=https://shurly.griddo.io` in the task, and set `CORS_ORIGINS='[]'`, since the
app and the API are now the same origin (§ CORS).

**Rollback:** point the alias back to the ALB. Its host rule and its certificate stay in place, so the API
answers as before. The pages come back with the next attempt.

### Client IPs behind CloudFront (Phase 6.3)

Two paths reach the ALB: **directly**, for `s.griddo.io` and later `go.griddo.io`, and **through CloudFront**, for
`shurly.griddo.io` (the API and the MCP). Through CloudFront, the ALB's peer is an edge, and the last address in
`X-Forwarded-For` is the edge's: the rate limits would count edges instead of people.

So the app takes the client IP from `CloudFront-Viewer-Address`, but only on a request that proves it came through
the distribution by carrying a secret that the distribution adds as a custom origin header (`client_ip`,
`server/utils/network.py`). The ALB is shared and reachable directly: anyone can send `CloudFront-Viewer-Address`, but
not the secret. Without the secret, and when the header is missing or doesn't parse, the client IP comes from
`X-Forwarded-For` as before (§ Trusted-Proxy Configuration). The rate limits and the visit log both use it.

The app also checks the address against the one CloudFront appended to `X-Forwarded-For`: second from the right,
before the edge the ALB appends (its "append" mode, above). CloudFront writes both from the same connection, so they
differ only when one isn't CloudFront's: an origin request policy that doesn't add CloudFront's headers, or an ALB
that no longer appends. Then `X-Forwarded-For` decides, as without the secret. It would take both of those going
wrong at once to believe a forged address.

**How each request's IP was found** is on its `http.request` line, as `client_ip_source`, next to its `host`. The IP
itself never is. `cloudfront` is the viewer address; `xff` is `X-Forwarded-For`, from a trusted proxy; `socket` is
the connection's peer (`client_ip_and_source`). In Logs Insights:
```
filter event = "http.request" and path != "/api/v1/health"
| stats count(*) as requests by host, client_ip_source
| sort requests desc
```
- **`shurly.griddo.io` should read `cloudfront` only.** `xff` there means the viewer address isn't used, and the rate
  limits count CloudFront's edges. The origin request policy doesn't add `CloudFront-Viewer-Address`, the task's
  secret isn't the distribution's, or the ALB stopped appending.
- **`s.griddo.io`, and later `go.griddo.io`, should read `xff`.** `socket` there means `TRUSTED_PROXIES` doesn't name
  the ALB, so every client looks like the ALB.
- The health checks, left out above, read `socket`: the ALB asks them itself.

**The distribution:**

- On the ALB origin, the custom origin header `X-Origin-Verify` with a random value of at least 32 characters
  (`openssl rand -hex 32`). CloudFront overwrites a header of that name sent by a viewer.
- Origin protocol **HTTPS only**, so the secret never crosses to the ALB in clear.
- The origin request policy **AllViewerAndCloudFrontHeaders-2022-06** on every ALB behaviour (the table above), so
  that CloudFront adds `CloudFront-Viewer-Address`. Under plain AllViewer, a `CloudFront-Viewer-Address` that reaches
  the app is whatever the viewer sent, next to a genuine secret.

**The task:**

- `CLOUDFRONT_ORIGIN_SECRETS='["<value>"]'`, a JSON array. Until the secrets move to Secrets Manager (ROADMAP 6.3)
  it's an ECS environment variable like the others. Its name contains `SECRET`, so the deploy log masks it. The app
  never logs it, and printed settings show `**********`.
- Each value needs at least 32 characters, or the app doesn't start.
- `CLOUDFRONT_ORIGIN_HEADER` names the header: `X-Origin-Verify` by default.

**Rotating the secret:**

1. Give the task both values, `CLOUDFRONT_ORIGIN_SECRETS='["<new>","<old>"]'`, and deploy.
2. Set the distribution's custom header to the new value, and wait for the distribution to deploy.
3. Take the old value out of the task, and deploy.

**Defence in depth, at the ALB (optional):** the ALB can refuse requests for `shurly.griddo.io` that skip
CloudFront, so they never reach the app. The app doesn't depend on it. It has to be per host: the ALB is shared,
priority 12 also serves `s.griddo.io`, and `s.griddo.io` and `go.griddo.io` are reached directly. So neither a
condition on priority 12 nor a security group limited to CloudFront's origin-facing prefix list
(`com.amazonaws.global.cloudfront.origin-facing`) will do. Instead:

- A rule for `shurly.griddo.io` ahead of priority 12, with an `http-header` condition on `X-Origin-Verify` (both
  values during a rotation), forwarding to Shurly. It must follow the active target group, so it goes in the rule-sync
  Lambda's `RULE_SYNC_MAP` too (§ 6). The Lambda only changes a rule's actions, so the condition stays.
- After it, a rule for `shurly.griddo.io` answering a fixed `403`.
- Priority 12 then serves only `s.griddo.io`.

### Check after the first deploy

- `/` and `/manual/install-mcp/` load.
- `/dashboard/` sends you to the login page.
- `/login` answers `301` to `/login/`.
- `/api/v1/health` answers with JSON, through CloudFront.
- `/mcp/` answers `401` with `WWW-Authenticate`.
- A forged client IP is ignored: 21 failed `POST /api/v1/auth/login` through CloudFront, each with another email
  and another `CloudFront-Viewer-Address: 6.6.6.N:1`, and the 21st answers `429` (`RATE_LIMIT_LOGIN_PER_IP` is 20).
  From one client that can't tell your IP from the edge's, since CloudFront reuses its connections to the ALB.
  The next check can. A request straight to the ALB for `shurly.griddo.io` without the secret gets `403` if the
  ALB rule is in place.
- The client IP is yours, not the edge's: `shurly.griddo.io`'s `http.request` lines read `client_ip_source`
  `cloudfront` (§ Client IPs behind CloudFront has the query).
- An `_astro/` file's `Cache-Control` is `immutable`, and a page's is `max-age=0`.

## Cost estimation (eu-south-2, monthly)

| Component | Cost |
|---|---|
| RDS PostgreSQL t4g.micro (20 GB gp3, encrypted) | ~$8 |
| ECS Fargate task (0.25 vCPU, 0.5 GB) | ~$9 |
| ALB (shared with Shlink) | $0 marginal |
| ECR (one image, ~200 MB) | <$0.10 |
| CloudWatch Logs (60-day retention) | ~$0.50 |
| Route 53 query traffic | ~$0.20 |
| ACM certificate | $0 |
| Lambda + EventBridge for ALB rule sync | $0 (free tier) |
| **Total** | **~$17 / month** |

Standalone (no shared ALB): add ~$16 for a dedicated ALB. Sharing with Shlink amortizes that across services.

Mitigations if cost ever pinches:
- Switch the Fargate task to Spot (~70% off, with eviction risk).
- Add an autoscaling schedule that drops to 0 tasks during off-hours.
- Move read-heavy endpoints behind CloudFront with a non-zero `REDIRECT_CACHE_LIFETIME` (trades analytics fidelity for compute reduction).

---

## GDPR posture

Visitor logging is privacy-first by default, configured via env vars (every variable, with its default and meaning:
[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)):

- **`ANONYMIZE_REMOTE_ADDR=true`** (default): IPv4 truncated to `/24`, IPv6 to `/64` at insert time. Truncation happens in `server/utils/network.py::anonymize_ip` before the `Visitor` row is committed — full addresses never reach Postgres. The client IP is resolved first and truncated after (`visit_ip`), for orphan visits too.
- **A visit's country and city (Phase 8.4)** are looked up from the address that's stored: the anonymized one when `ANONYMIZE_REMOTE_ADDR` is on. The lookup never sees more than what's kept. Only the country, an ISO code, and the city, its English name, are stored: no region, postcode or coordinates. The lookup runs in process against a file, with no network call (§ Geolocation data).
  - The cost of looking up the `/24`, measured on GeoLite2 City (2026-09-25): another city for 0.38% of IPv4 addresses, another country for 0.04%, and none for IPv6, which it doesn't split finer than a `/64`. GeoLite2 knows a city for 45% of the IPv4 address space; the rest get a country only. A city is where the network is registered or routed, not where the person is: an approximation, and MaxMind's free data is less accurate than its paid data.
  - MaxMind's licence forbids using the data to identify or locate a person, a household or a street address (GeoLite EULA §5). So a city only goes out counted, never visit by visit, never for a campaign link (one named recipient's), and a campaign's only from 5 of its recipients (`docs/PERSONAL_DATA.md` § Cities).
- Bots and email tracking pixels share the `visits` table but carry `is_bot` / `is_pixel` flags so click analytics exclude them by default.
- Tracking pixel responses set `Cache-Control: no-store` so HTML email clients re-fetch on every open.
- The `User.api_key_scope` enum is in place so post-launch role rollouts (`READ_ONLY`, `CREATE_ONLY`, `DOMAIN_SPECIFIC`) ship without a destructive migration; only `FULL_ACCESS` is enforced today.
- The `RequestIdMiddleware` echoes `X-Request-Id` on every response (or generates a UUID if absent), enabling log correlation in CloudWatch without leaking PII.
- MCP tool arguments stay out of the logs: the usage log records argument names only, and fastmcp's own line for a failed API call leaves out the response body, which can echo them (`mcp_server/README.md` § Usage log). Never set `FASTMCP_LOG_LEVEL=DEBUG` in production: at that level fastmcp logs every tool call's arguments in full.
- Database errors leave the SQL parameters out of their message (`hide_parameters=True` in `server/core/__init__.py`), so a traceback in the logs doesn't print what the user sent. PostgreSQL's own detail for a constraint violation still names the value: `Key (email)=(…) already exists`, or the whole row for a `NOT NULL` violation.
- Link-preview failures log the destination URL's origin (scheme, host, port), never its path or query string (`url_origin` in `server/utils/url.py`). App warnings reach CloudWatch without any log configuration: Python's last-resort handler prints them to stderr.

If your privacy policy permits storing full IPs, set `ANONYMIZE_REMOTE_ADDR=false` — but document the decision.

## Trusted-Proxy Configuration

`X-Forwarded-For` is **never** trusted by default — anyone can spoof it. Once the ALB sits in front of the API (which it does), set `TRUSTED_PROXIES` to the CIDRs that may legitimately set the header.

For the shared ALB inside the default VPC, the right value is the VPC's CIDR:

```bash
TRUSTED_PROXIES='["172.31.0.0/16"]'
```

The resolver (`server/utils/network.py::resolve_client_ip`) checks the request's source against every CIDR; only when it matches does it read `X-Forwarded-For`, and then from the right: each proxy appends the address it saw, so the first entry from the right that isn't a trusted proxy is the client. The left end is whatever the client sent, so it's never trusted (before Phase 6.3 it was, and a client could choose the address the visit was recorded under). Outside the allowlist the socket address wins.

Behind CloudFront (`shurly.griddo.io`, Phase 4.10) the client IP comes from `CloudFront-Viewer-Address` instead, on requests that prove they came through the distribution: § Frontend hosting, "Client IPs behind CloudFront". Don't add CloudFront's ranges here.

**uvicorn's proxy headers stay off** (`--no-proxy-headers` in the dockerfile's CMD). They're on by default, and they replace the connection's address before the app sees the request. Until 2026-09-29 the image ran them with `--forwarded-allow-ips "*"`, which takes the leftmost `X-Forwarded-For` entry, the one the client writes. So on `s.griddo.io` anyone could choose their address: the per-IP rate limits counted it, and visits stored it, with its country and city. Never turn them back on, and don't add `--forwarded-allow-ips`. The app reads `X-Forwarded-Proto` itself, from `TRUSTED_PROXIES` only (`ForwardedProtoMiddleware`), so what Starlette builds from the scheme, like a trailing-slash redirect, stays `https` behind the ALB. `tests/test_phase63_forwarded_headers.py` runs the real uvicorn with the CMD's flags.

## Rate limits (Phase 6.3)

What anyone can call is limited per client IP, counted in the database (`rate_limits`) so both tasks share the counts: the password login (every attempt runs a bcrypt check, on the tasks that also serve redirects) and the Google and MCP sign-in endpoints (each request writes a row). Redirects, anything signed in and CORS preflights are never limited.

- **`TRUSTED_PROXIES` must name the ALB** (`["172.31.0.0/16"]` in production): the limits key on the client IP it resolves. Unset, every request seems to come from the ALB, and each per-IP limit becomes one limit for everybody. Behind CloudFront, `CLOUDFRONT_ORIGIN_SECRETS` too (§ Frontend hosting), or everyone behind the same edge shares one count.
- Settings, per minute unless said otherwise; `0` turns one off:

  | Variable | Default | Limits |
  |---|---|---|
  | `RATE_LIMIT_LOGIN_PER_IP` | `20` | `POST /api/v1/auth/login` |
  | `RATE_LIMIT_LOGIN_FAILURES_PER_ACCOUNT` | `10` | Failed password checks per address, per 15 minutes: logins, and the current password given to `POST /api/v1/auth/change-password` or `PUT /api/v1/auth/password` |
  | `RATE_LIMIT_SIGN_IN_PER_IP` | `30` | Google's sign-in (`/api/v1/auth/google/*`), the MCP's sign-in pages (`/mcp/authorize`, `/mcp/consent`, `/mcp/auth/callback`) and `POST /auth/register` |
  | `RATE_LIMIT_MCP_CLIENTS_PER_IP` | `60` | `/mcp/register` and `/mcp/token`, which claude.ai calls from Anthropic's addresses, shared by everybody |

- **Per account, only failed attempts count**, so the right password isn't counted with a guesser's. That also means anyone can lock an address's password login for 15 minutes by failing on purpose; signing in with Google stays open, so that's accepted. The address needn't have an account, so a 429 tells nothing about who has one.
- Over a limit: `429` with `Retry-After`; Google's sign-in, a browser navigation, goes back to `{FRONTEND_URL}/login/#error=rate_limited` instead. The event log records `http.rate_limited {path, limit}`, never the IP or the address.
- If the database can't count, requests go through and `rate_limit.store_failed` is logged: the limits protect, they mustn't become an outage.
- AWS WAF on the shared ALB would add limiting before the app; that's an AWS decision, not in this code.

## CORS (Phase 6.3)

The frontend calls the API with a bearer token, never cookies, so CORS allows no credentials, only the
methods (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) and request headers (`Authorization`, `Content-Type`,
`X-Request-Id`) the API uses, and exposes `Retry-After` and `X-Request-Id` to the frontend.

- **Production needs no cross-origin entry** once the frontend is hosted (4.10): it and the API share one
  host (the Hostnames table under Architecture), so the browser makes no cross-origin calls. Set
  `CORS_ORIGINS='[]'` then, unless the frontend is served from another origin.
- **Production's value since release #81 (2026-09-28) is `["http://localhost:4232"]`.** It listed
  `https://shurl.griddo.io`, a host that doesn't exist, until then. Localhost stays for running the frontend
  locally against production until 4.10.
- Locally the defaults cover the dev server (`http://localhost:4232`) on another port, so the middleware
  stays.

## API keys (Phase 6.3)

An API key is kept as its SHA-256 hash and its first 12 characters (`users.api_key_hash`,
`users.api_key_prefix`), never as itself: it's shown once, when it's generated. New keys start with
`shurly_`; keys made before keep working.

- **API keys 401 during 0007's rollout.** Migration `0007` moves every key to its hash and empties
  `users.api_key`, where the previous release looks keys up: while its task still serves, an API key
  gets a 401 from it. The same key works again once the rollout ends. JWTs and signing in with Google
  aren't affected.
- `users.api_key`, empty from then on, is no longer mapped from the release after `0007`'s: the ORM named it in every
  SELECT and INSERT of a user. The release after that drops it (`0014`). Not sooner: a task still running the
  previous release would fail every user query mid-rollout.
- A downgrade past `0007` can't give the keys back: everyone generates a new one.

## Sign in with Google (Phase 3.13)

Accounts come from signing in with a Google Workspace account of `ORGANIZATION_DOMAIN` (`griddo.io`).
A password is optional: its owner sets it once signed in. Either way the API issues its own JWT, as
before, so API keys and the MCP don't change.

### Prerequisite: the Google Cloud project

Done once, by whoever administers Google Workspace (ROADMAP 3.13.2). Step by step:
[docs/setup_google_app.md](docs/setup_google_app.md).

1. A Google Cloud project inside the griddo.io organization.
2. OAuth consent screen **Internal**, so only Griddo accounts can sign in. Scopes: `openid`, `email` and
   `profile`: the web sign-in asks for `profile` to name a new account (3.12); the MCP's, for the first two.
3. An OAuth client of type **Web application**, with the authorized redirect URI
   `https://shurly.griddo.io/api/v1/auth/google/callback` (the MCP proxy's joins it in 5.8).
4. The client secret goes to Secrets Manager (6.3), never into the repo or a task definition in clear.

### Settings

| Variable | Example | Notes |
|---|---|---|
| `GOOGLE_CLIENT_ID` | `1234-abc.apps.googleusercontent.com` | The OAuth client's id |
| `GOOGLE_CLIENT_SECRET` | from Secrets Manager | Never logged |
| `GOOGLE_REDIRECT_URI` | `https://shurly.griddo.io/api/v1/auth/google/callback` | Exactly as registered with the client |
| `FRONTEND_URL` | the frontend's origin | After Google, the browser goes to `{FRONTEND_URL}/login/` |
| `ORGANIZATION_DOMAIN` | `griddo.io` (default) | Only ID tokens whose `hd` claim is this domain get in |
| `ALLOW_PASSWORD_SIGNUP` | `false` (default) | `POST /auth/register`, for local development and tests. **Never** `true` in production; the app logs `auth.password_signup_enabled` at startup when it is |

- Until the first four and `ORGANIZATION_DOMAIN` are set, sign in with Google is off:
  `/api/v1/auth/google/start` and `/callback` send the browser to
  `{FRONTEND_URL}/login/#error=google_unavailable`, or answer `503` when `FRONTEND_URL` isn't set
  either. The rest of the app works as before, password logins included. An empty
  `ORGANIZATION_DOMAIN` keeps it off: it would let any Google account in, Gmail included.
- The page `POST`s the one-time code to `/api/v1/auth/google/exchange`. In production that's the same origin
  (`shurly.griddo.io`), so `CORS_ORIGINS` needs no entry for it (§ CORS); a frontend served from another origin
  needs its origin listed.
- **Where they go:** the GitHub deploy keeps the live service's environment and swaps only the image,
  so add these variables to the live ECS config ([docs/setup_google_app.md](docs/setup_google_app.md),
  step 7). Changing it starts a deployment. `scripts/deploy_ecs.sh` only creates the service, and stops once
  it exists.
- To rotate the client secret: add a new secret to the OAuth client, update Secrets Manager, redeploy,
  then delete the old secret in Google Cloud.

### The flow, and the frontend's contract

`GET /api/v1/auth/google/start` → Google → `GET /api/v1/auth/google/callback` →
`{FRONTEND_URL}/login/#code=…` → `POST /api/v1/auth/google/exchange` → the JWT. The code works once,
within 60 seconds, and the JWT never travels in a URL. The state cookie, the fragment's error codes and
the password endpoints' `reauth_required` answer are specified in the docstring of
`server/app/google_auth.py`, the one reference for the backend and the frontend.

### What the event log records

- `auth.login` `{method: google | password, user_id}` on every sign-in. Before turning password logins
  off for the domain (3.13.4), this shows who still uses one:
  `filter event = "auth.login" | stats count() by method`
- `auth.google_refused` `{reason}`: a refused Google sign-in (another domain, cancelled, …).
- `auth.identity_linked`: a Google sign-in took over an account made by the open sign-up before 3.13.
  Nobody verified that account's address, so its password, API key and sessions were revoked.
- `auth.password_set`, `auth.password_removed`.

None of them carries an email address, a token or a code.

### The MCP (Phase 5.8)

MCP clients (claude.ai custom connectors, Claude Code) can sign in with Google too, through fastmcp's
OAuth proxy, alongside API keys, which keep working unchanged. It's on once these are set, besides the
Google client and `ORGANIZATION_DOMAIN` above:

| Variable | Example | Notes |
|---|---|---|
| `MCP_PUBLIC_URL` | `https://shurly.griddo.io/mcp` | The MCP endpoint as clients reach it, without the slash. People connect to `{MCP_PUBLIC_URL}/`, with it: the metadata's `resource` has to match what they enter |
| `MCP_OAUTH_SIGNING_KEY` | `openssl rand -hex 32` | Signs the MCP's tokens and, derived, encrypts what the proxy stores. High entropy (it goes through HKDF, not a password hash), the same on every task, never the Google secret. Changing it signs every MCP client out. Masked in the deploy logs like any `*KEY*` |
| `MCP_OAUTH_ALLOWED_REDIRECT_URIS` | the default | Who may register as an MCP client. Default: `https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback` (where Anthropic says it may move) and loopback on any port (`http://localhost:*`, `http://127.0.0.1:*`, Claude Code). A JSON array to change it; any other client is refused |

- **Google:** add `{MCP_PUBLIC_URL}/auth/callback` (`https://shurly.griddo.io/mcp/auth/callback`) as a
  second authorized redirect URI of the same OAuth client ([docs/setup_google_app.md](docs/setup_google_app.md),
  step 9).
- **State:** client registrations, sign-ins in progress, codes and Google's tokens (refresh tokens
  included) live in the `mcp_oauth_store` table (migration `0005`), encrypted, so both tasks and every
  deploy share them.
- **Offboarding:** closing an account in Shurly refuses its MCP sign-ins at once, on the next request
  and on any refresh. A suspension at Google takes up to 60 seconds to bite, because a successful check
  with Google is kept that long. The Google tokens stored for a closed account stay, encrypted, until
  they expire, and can't be used.
- **Discovery:** `/.well-known/oauth-protected-resource/mcp/` and
  `/.well-known/oauth-authorization-server/mcp` at the root, and a 401 pointing at the former; the
  OAuth endpoints are under `/mcp/`. The event log's `auth.login` and `auth.google_refused` carry
  `surface: "mcp"` for these sign-ins.

#### The MCP's sign-in pages

fastmcp's OAuth proxy renders its own pages, as FastMCP's, with its logo loaded from `gofastmcp.com`,
and has no supported way to change them: the consent page, its errors, the errors after Google and
"not registered". `mcp_server/pages.py` points its four renderers at Shurly's
(`server/templates/mcp_consent.html` and `mcp_error.html`), once, when the Google provider is built.
fastmcp keeps the flow: the CSRF token, the cookies and the redirect checks.

- **Upgrades.** `uv.lock` pins fastmcp, and a new version arrives in Dependabot's weekly PR. The pages
  were checked against 4.0.6 to 4.0.10.
  - If a later version renames or moves a renderer, `tests/test_phase58_mcp_pages.py` fails in that PR's
    CI, before anything is merged.
  - If it gets past that, the app refuses to start (`check_fastmcp`), rather than show FastMCP's pages.
  - Either way, update `pages.py` for that version.
- **Consent every time.** `require_authorization_consent` keeps fastmcp's default, so no answer is
  remembered.
- **An error page shows a reason from a fixed set, never text from the request.** fastmcp's put the
  URL's `error_description` on screen, so anyone could make a link that shows their words under our
  domain.
- **Headers,** on every HTML page under `/mcp/` (`PageHeaders`). JSON and event streams are left alone.
  - A CSP that allows only the two templates' `<style>` blocks, by hash, and images as `data:`, with
    `frame-ancestors 'none'`.
  - `X-Frame-Options: DENY`, `Cache-Control: no-store` (the consent page carries a CSRF token),
    `Referrer-Policy: no-referrer` (its address carries the sign-in's id), `nosniff` and `noindex`.
- **No `form-action` in the CSP, on purpose. Don't add it.** Chrome applies it to every redirect after
  the consent form: Google, `/mcp/auth/callback`, then the client's callback, which can be
  `http://localhost:…` or a `claude://` app link. A `form-action` would break the sign-in. fastmcp
  leaves it out for the same reason, and a test fails if it's added.
- **What went wrong** is logged as `mcp.sign_in_error`, with the `page` and the `reason`. It also
  carries Google's error code (`google_error`) or, when the exchange with Google failed, a scrubbed
  `detail`: never a token or a code.
  ```
  filter event = "mcp.sign_in_error"
  | stats count(*) as times by page, reason
  | sort times desc
  ```

---

## People: joining, roles and leaving (Phase 3.14)

For the rollout to the team (ROADMAP 5.6.1). People join by themselves, and an owner manages roles and removals in the
app, in Settings → Organization. Only bringing back someone who was removed needs the database.

### Before anyone joins

- **Sign in with Google is set up** (§ Sign in with Google): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REDIRECT_URI`, `FRONTEND_URL` and `ORGANIZATION_DOMAIN`.
- **`ORGANIZATION_DOMAIN`** is the Google Workspace domain whose accounts get in (`griddo.io`), and
  **`ORGANIZATION_NAME`** is what the app calls the organization (`Griddo`).
- **`BOOTSTRAP_OWNER_EMAIL`** names the first owner. That account becomes owner when it joins an organization without
  one, and at every start of the app, if no owner is left, it's made owner again (break-glass). Set it to whoever runs
  the rollout, and have them sign in first.
- **`ALLOW_PASSWORD_SIGNUP` stays off**: accounts come from Google.

### Joining

There's no invitation list: anyone with an account on the domain who has the address can sign in. Send people the
app's `/login/` page, and they choose Sign in with Google with their work account.

- **Google vouches for them:** the address has to be verified, and the account's Workspace domain (`hd`) has to be
  `ORGANIZATION_DOMAIN`. Otherwise the login page says only the organization's accounts can sign in, or that Google
  hasn't verified the address.
- **The first sign-in makes the account** and adds it to the organization as a **member**, with the names Google has
  for them as their profile.
- **An account made before sign-in with Google** (with a password) is linked the first time its owner signs in with
  Google, and loses its password, its API key and its other sessions: nobody had verified that address.
- For their first 14 days, the dashboard opens with a welcome: where to start, and connecting Claude.

### Roles

| Role | Can |
|---|---|
| member | Make links and campaigns, see the organization's, and change what they made |
| admin | Also change and delete anyone's organization links and campaigns, and remove members |
| owner | Also change roles, hand the role over, see who was removed and move their personal links to the organization |

- **Owners change roles**, in Settings → Organization: anyone's but another owner's, to member, admin or owner. Nobody
  raises their own role; anyone can lower it. Owners step down themselves.
- **Hand over ownership** makes someone owner and the person handing it over an admin, in one change.
- **There's always an owner:** the last one can't step down, and owners can't be removed. Make a second owner early
  (ROADMAP: two owners from day one).
- **Personal links and campaigns** stay their maker's: nobody else sees them, admins and owners included.

### Leaving

- **An admin or an owner removes someone below their role**: Settings → Organization, then Remove from organization.
  Nobody removes themselves.
- **Removing closes the account.** They can't sign in again, their API key is gone, and their sessions and the MCP's
  sign-ins stop working at their next request. Their links keep working for whoever has them.
- **What they made:** their organization links and campaigns stay the organization's. Their personal ones stay theirs,
  seen by nobody, until an owner moves them to the organization from Removed people (Move to Griddo), then or later.
- **Bringing someone back isn't in the app.** It's a database change, `users.is_active` back to true. The app's next
  start makes them a member again: their role and their API key don't come back.

### The rollout, step by step

1. The first owner (`BOOTSTRAP_OWNER_EMAIL`) signs in, and Settings → Organization shows them as owner.
2. Send each person the app's address, the manual (`/manual/`) and, for Claude, `/manual/install-mcp/`.
3. As they sign in, they appear in Settings → Organization as members. Make a second owner.
4. Watch the signal: § What the web app is used for, `client.error` in § Error alerting, and the MCP's `mcp.tool_call`
   queries (`mcp_server/README.md` § Usage log). What people say arrives at support@griddo.io: Send feedback, in the
   account menu, writes there from their own mail app, with the page they were on.

## Error alerting (Phase 6.4)

The app writes one JSON line per request (`http.request`: its `method`, `host`, `path`, `status`, `duration_ms`
and `client_ip_source`) to the task's log group,
`/aws/ecs/default/shurly-api-5fdb`. A generated MCP tool calls the API in-process, so its failures get a line too.
Alerting therefore needs no code: a CloudWatch metric filter counts the errors, an alarm watches the count, and SNS
sends the email. None of it is set up yet (ROADMAP 6.4).

| Metric filter | Pattern | Alarm |
|---|---|---|
| `shurly-5xx` | `{ $.event = "http.request" && $.status >= 500 }` | Sum ≥ 5 in 5 minutes |
| `shurly-rate-limit-store` | `{ $.event = "rate_limit.store_failed" }` | Sum ≥ 1 in 5 minutes: the limits are letting everything through |
| `shurly-client-errors` | `{ $.event = "client.error" }` | Sum ≥ 10 in 15 minutes: the web app is breaking in people's browsers |

- Each filter publishes a metric in namespace `Shurly`, value `1`, default `0`. The alarms notify an SNS topic with
  an email subscription.
- The ALB's `HTTPCode_Target_5XX_Count` and `HTTPCode_ELB_5XX_Count` catch a task that doesn't answer at all.
- MCP tool errors (`{ $.event = "mcp.tool_call" && $.outcome = "error" }`) include invalid input, a 4xx. They belong
  on a dashboard, not an alarm (`mcp_server/README.md` § Usage log).
- **Browser errors** are `client.error` lines: the web app reports an uncaught error, a rejected promise, or a CSP or
  Trusted Types block (`POST /api/v1/client-errors`, `server/app/client_errors.py`). Each has its `kind`, `message`,
  `source` (script:line:column) and `page` (the path, never its query), and the account's `user_id` when signed in.
  Never an IP. A page sends 5 at most; `RATE_LIMIT_CLIENT_ERRORS_PER_IP` caps an address. Which ones, most first:
  ```
  filter event = "client.error"
  | stats count(*) as reports, count_distinct(user_id) as people by kind, message, page
  | sort reports desc
  ```

### When it fires (runbook stub)

1. **Which requests fail.** In Logs Insights:
   ```
   filter event = "http.request" and status >= 500
   | stats count(*) as errors by path, status
   | sort errors desc
   ```
   Then follow one `request_id`: `filter request_id = "…"` shows its `http.request` line, the `mcp.tool_call` line if
   it came through the MCP, and the traceback next to them.
2. **Did a deploy just happen?** Check the service's events and the last backend deploy. If the errors started with
   it, roll back by redeploying the previous image (§ Workflow trigger).
3. **Is the database there?** `GET /api/v1/health/db`, then RDS's connections and CPU.
4. **Write it down** in the troubleshooting catalog (`docs/AWS_ECS_DEPLOYMENT.md`): the symptom, the cause and the
   fix.

### What the web app is used for (the dogfood, ROADMAP 5.6.1)

The MCP's usage is in `mcp.tool_call` lines (`mcp_server/README.md` § Usage log). The web app's is in the API's
`http.request` lines, one per call it makes, with the path and the status: no user, so they count uses, not people.

- Calls per part of the API:
  ```
  filter event = "http.request" and status < 400 and path like /^\/api\/v1\//
  | parse path /^\/api\/v1\/(?<area>[a-z-]+)/
  | stats count(*) as calls by method, area
  | sort calls desc
  ```
- Links and campaigns made, by week:
  ```
  filter event = "http.request" and method = "POST" and status = 201 and (path = "/api/v1/urls" or path = "/api/v1/campaigns")
  | stats count(*) as made by path, bin(7d)
  ```
- A link's and a campaign's analytics, tab by tab (`timeseries` is By time; `breakdown` By context and By location;
  `visits` and `recipients` their lists), and the CSVs downloaded:
  ```
  filter event = "http.request" and status < 400 and path like /^\/api\/v1\/analytics\/(urls|campaigns)\//
  | parse path /\/(?<what>totals|timeseries|breakdown|visits|visits\.csv|recipients|recipients\.csv)$/
  | stats count(*) as calls by what
  | sort calls desc
  ```

## Geolocation data (Phase 8.4)

A visit's country and city come from MaxMind's GeoLite2 City, at `/app/data/GeoLite2-City.mmdb` (`GEOIP_DATABASE`).
When that file isn't there, the country comes from DB-IP's IP to Country Lite, at `/app/data/dbip-country-lite.mmdb`
(`GEOIP_FALLBACK_DATABASE`, countries only), and there's no city. Both are looked up in process, from the stored
address (§ GDPR posture). An empty `GEOIP_DATABASE` turns lookups off. GeoLite2 City adds about 65 MB to the image.

- **The build fetches both** (`scripts/fetch_geoip.py`, the dockerfile's `geoip` stage). Each is installed only if it
  opens and places 8.8.8.8 in the US. GeoLite2's must also match MaxMind's SHA-256 and be less than 25 days old.
  DB-IP's is this month's file, or last month's until this month's is out. Both are asked with the script's own
  User-Agent, because DB-IP answers Python's default with a 403.
- **MaxMind's credentials** are the GitHub secrets `MAXMIND_ACCOUNT_ID` and `MAXMIND_LICENSE_KEY`. They can be the
  repository's, or the `dev` environment's, which is where the deploy job runs for a push and for the weekly run.
  - The job hands them to the build as BuildKit secrets, mounted for the fetch alone. They're in no image layer,
    build argument or log line, and the running task never has them.
  - The key goes to MaxMind only, over HTTPS. It isn't forwarded to the storage MaxMind redirects the download to.
- **The licence, the [GeoLite EULA](https://www.maxmind.com/en/geolite2/eula):**
  - §6.3: stop using and destroy an old copy within 30 days of MaxMind releasing an update. Hence the weekly run
    and ECR's lifecycle rule, below.
  - §6.1: the database mustn't reach a third party. The image stays in the private ECR repository, and nothing
    uploads the file (no build artifact, no public registry).
  - §5: it must never be used to identify or locate a person, a household or a street address. The lookup gets the
    anonymized address, only the country and the city are kept, and a city only goes out counted (§ GDPR posture).
  - §3: the attribution, "This product includes GeoLite Data created by MaxMind, available from
    https://www.maxmind.com". It's in `NOTICE`, the README, and on the pages that show countries, next to DB-IP's
    (CC BY 4.0).
- **Every Monday at 05:00 UTC** (`schedule:` in `deploy-backend.yml`), the deploy job rebuilds main's current
  commit with that week's databases and deploys it. GitHub runs a schedule from the default branch, main, so it
  starts once this workflow is on main.
  - One deploy runs at a time (`concurrency`). A push to main during the weekly run waits, then deploys its commit.
  - The smoke test waits for `/api/v1/health` to report both the commit and the run's `build`. The weekly image has
    the same commit as the one it replaces, so the commit alone can't tell them apart.
  - Weekly leaves three retries within MaxMind's 30 days. When a weekly run fails, GitHub emails whoever last
    changed the `schedule:` line. Running the workflow by hand (workflow_dispatch) retries.
  - GitHub turns off a public repository's schedules after 60 days without activity. The Actions tab turns them
    back on.
- **The deploy job checks what the build fetched** (the `Geolocation data` step), and the push build reuses exactly
  that, from the same run's builder cache:
  - MaxMind's key is set but there's no GeoLite2 City: the job fails (`No GeoLite2 City`) and deploys nothing, so
    the running image keeps serving. The fetch's lines above the error say why: a 401 is the account ID or the key,
    a 429 is MaxMind's download limit.
  - No key: a warning (`No MaxMind credentials`), and countries come from DB-IP only.
  - No DB-IP file: a warning (`No DB-IP fallback`).
- **At startup the app logs what it opened.**
  - `geo.database_opened`: its path, type, build date and age in days. When it fell back to DB-IP, it also logs
    `primary` and `primary_error`.
  - `geo.database_missing`: neither file opened.
  - `geo.database_stale`: a GeoLite2 copy is more than 25 days old, so no weekly run has deployed for three weeks.
    Act on it before day 30.

  In CloudWatch Logs Insights:
  ```
  filter event like /^geo\.database/
  | fields @timestamp, event, path, database_type, built, age_days, primary_error
  | sort @timestamp desc
  ```
- **ECR's lifecycle rule destroys the old copies.** Each image holds its week's copy of GeoLite2, so images pushed
  more than 30 days ago are expired. Applied to `shurly-api` on 2026-09-29, after a preview: it expired 48 of 105
  images, the newest from 2026-04-28, and none serving or recent. It isn't applied from here: to apply it again,
  preview it first (`aws ecr start-lifecycle-policy-preview`), and check that it expires the per-platform images
  along with their index:
  ```json
  {
    "rules": [
      {
        "rulePriority": 1,
        "description": "GeoLite EULA 6.3: no image, nor its GeoLite2 copy, older than 30 days",
        "selection": {
          "tagStatus": "any",
          "countType": "sinceImagePushed",
          "countUnit": "days",
          "countNumber": 30
        },
        "action": { "type": "expire" }
      }
    ]
  }
  ```
  ```bash
  aws ecr put-lifecycle-policy --repository-name shurly-api --region eu-south-2 --profile griddo-main \
      --lifecycle-policy-text file://ecr-lifecycle.json
  ```
  A rollback to any image of the last 30 days keeps working. If the weekly run failed four weeks running, the rule
  would expire the image that's serving, and a new task couldn't start. `geo.database_stale` fires first, on day 25.
- **Filling in older visits:** the visits saved before cities, or while an image had no database, have neither.
  `scripts/run_backfill_places.sh` runs `python -m server.tools.backfill_places` as a one-off ECS task, from the
  live service's image, environment and network, the way the Shlink import runs (`scripts/one_off_task.sh`).
  - It looks each up as the redirect does, from the stored address, and fills only what's empty. A city goes only
    where the visit's country is empty or agrees. It skips Shlink's imported visits, which have no address.
  - A dry run first, which reports counts and writes nothing. Then `--for-real`, typing the service's name back.
    Running it twice is harmless. Not during a rollout: the script stops until there's one deployment.
  - It needs no task role, since it reads nothing from AWS. Its output goes to the service's log group, in
    streams `backfill-places/…`, and the task definition made for it is deleted at the end.
  - Run it after the release that brings cities, once GeoLite2 City is in the image: with DB-IP's file only, it
    fills countries and no city.
- **Locally:** `uv run python scripts/fetch_geoip.py` puts DB-IP's file in `data/` (git-ignored), plus GeoLite2 City
  when `MAXMIND_ACCOUNT_ID` and `MAXMIND_LICENSE_KEY` are set. The 30 days apply to a developer's copy too:
  delete `data/GeoLite2-City.mmdb` within 30 days, or fetch it again. Without either file, countries are null.

## Moving Shlink's links (Phase 8.4)

Three commands, `python -m server.tools.shlink export | review | import`, each from the previous one's file
(`server/tools/shlink/README.md`). Snapshots can hold personal data: keep them in `_exchange/` or an encrypted
store, never in the repository.

- **The import writes to the database the `DB_*` settings name.** Always run it with `--dry-run` first.
- **In production it runs as a one-off ECS task** (decision B): `scripts/run_shlink_import.sh`, below.
- **With `--visits`,** imported visits carry ip "unknown". Unique-visitor counts cover the cutover onward only.

### The import as a one-off ECS task (decision B)

`scripts/run_shlink_import.sh` runs the import in production's network, against the private RDS, with the live
service's own image and environment. It makes a task definition for the run from the live one, and deletes it at
the end, whatever happened.
- The live one is the service's PRIMARY deployment's: ECS Express leaves the service's own `taskDefinition`
  empty. While a rollout is in progress there are two deployments, and the script stops: run it once the
  rollout is done (`scripts/one_off_task.sh`, shared with the backfill).

The task has two containers, sharing a volume:

- **`fetch`**, the AWS CLI's image (`public.ecr.aws/aws-cli/aws-cli`), copies the snapshot and the review from a
  private bucket into the volume. It uses the task role `shurly-shlink-import`, which can read that one prefix
  and nothing else. The app's image stays as it is, without an AWS SDK.
- **`import`**, Shurly's image, runs `python -m server.tools.shlink import` from those files, once `fetch` has
  succeeded. It's a **dry run** unless the script is given `--for-real`, and then you type the owner's email to
  confirm.
- **Output:** both write to the service's CloudWatch log group (`/aws/ecs/default/shurly-api-5fdb`, kept 60
  days), in the streams `shlink-import/fetch/<task>` and `shlink-import/import/<task>`. The script waits for the
  task and prints both. The import's report carries counts, codes and destinations, not visits.
- **Secrets:** the task definition carries the service's environment, `DB_PASSWORD` included, as the live one
  does. The script sends it to AWS and never prints it; its local copy lives in a private temporary directory
  that's removed at the end.

**Made once, by hand** (the script creates nothing lasting): a private bucket, and the task role.

The bucket, e.g. `shurly-imports-<account id>` in `eu-south-2`: Block Public Access on (all four), default
encryption SSE-S3, no versioning, so that an expired object is gone. Its policy refuses anything but TLS:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "TlsOnly", "Effect": "Deny", "Principal": "*", "Action": "s3:*",
    "Resource": ["arn:aws:s3:::shurly-imports-<account id>", "arn:aws:s3:::shurly-imports-<account id>/*"],
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }]
}
```

And a lifecycle rule, since snapshots hold personal data:

```json
{"Rules": [{"ID": "ExpireSnapshots", "Status": "Enabled", "Filter": {"Prefix": ""}, "Expiration": {"Days": 7}}]}
```

The task role `shurly-shlink-import`. Its trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole",
    "Condition": {"StringEquals": {"aws:SourceAccount": "<account id>"}}
  }]
}
```

Its only permissions, on the one prefix (`shlink/` here: the script's `--prefix` goes under it):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::shurly-imports-<account id>",
     "Condition": {"StringLike": {"s3:prefix": ["shlink/*"]}}},
    {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::shurly-imports-<account id>/shlink/*"}
  ]
}
```

Whoever runs the script needs, besides reading the service (`ecs:ListServices`, `ecs:DescribeServices`,
`ecs:DescribeTaskDefinition`): `ecs:RegisterTaskDefinition`, `ecs:DeregisterTaskDefinition`,
`ecs:DeleteTaskDefinitions`, `ecs:RunTask`, `ecs:DescribeTasks`; `iam:PassRole` on `shurly-shlink-import` and on
the service's execution role (`ecsTaskExecutionRole`); `s3:PutObject` and `s3:ListBucket` on the prefix, to upload;
and `logs:FilterLogEvents` on the log group. The task needs the internet, for `public.ecr.aws`, which the
service's own network already has. If it ever reaches ECR through VPC endpoints only, copy the AWS CLI image into
the account's ECR and set `AWS_CLI_IMAGE`.

**A run:**

```bash
# 1. The files, from `export` and `review` (server/tools/shlink/README.md)
aws s3 cp _exchange/shlink-go.griddo.io-….snapshot.json \
    s3://shurly-imports-<account id>/shlink/2026-10-01/snapshot.json --profile griddo-main
aws s3 cp _exchange/shlink-go.griddo.io-….review.csv \
    s3://shurly-imports-<account id>/shlink/2026-10-01/review.csv --profile griddo-main

# 2. A dry run: everything, the report, then rolled back
scripts/run_shlink_import.sh --bucket shurly-imports-<account id> --prefix shlink/2026-10-01 \
    --as owner@griddo.io --visits

# 3. Read the report. Then for real (it asks for the owner's email)
scripts/run_shlink_import.sh --bucket shurly-imports-<account id> --prefix shlink/2026-10-01 \
    --as owner@griddo.io --visits --for-real

# 4. The files go: now, or in 7 days by the lifecycle rule
aws s3 rm --recursive s3://shurly-imports-<account id>/shlink/2026-10-01/ --profile griddo-main
```

The script checks both files are there before it makes anything. `tests/test_run_shlink_import.py` runs it
against a fake `aws`. On the first real run, read the dry run's report before going on.

## The cutover (Phase 8.5)

ROADMAP 8.5 has the steps, in one window. The default domain switches to `go.griddo.io` once the ALB sends
`go.griddo.io` to Shurly: new links go on the default domain, so it has to lead to Shurly first.

### The default domain

Three settings name it, and all three move in the window:

- **The database's default domain** decides the domain of new links (the API's, a campaign's, the MCP's), which
  link a code names when the API isn't told the domain, and where a request on a host Shurly doesn't know looks.
  `scripts/run_promote_domain.sh` moves it, at once, with no redeploy. `DEFAULT_DOMAIN` alone doesn't: at
  startup, the row already marked default wins.
- **`DEFAULT_DOMAIN`**, on the service, decides which links `BASE_URL` moves, and the domain of a link from before
  domains. The live service sets no `BASE_URL` (checked 2026-10-01), so there's no `BASE_URL` step.
- **`PUBLIC_SHORT_DOMAIN`**, the repository variable the frontend deploy builds with, is the host the create page
  shows before a new link's code. Unset, it's `s.griddo.io`.

A link keeps its domain: `s.griddo.io`'s keep resolving there until it's deleted. Delete its `Domain` row only
after this: until then it's the default.

`scripts/run_promote_domain.sh` runs `python -m server.tools.domains promote` as a one-off ECS task, like the
backfill (`scripts/one_off_task.sh`): the live service's image, environment and network, one container,
`promote`, and no task role. It makes the domain's row if it's missing, marks it the default and unmarks the one
that was, in one transaction. A dry run unless `--for-real`, which needs the domain typed back; a second run finds
nothing to do. Its output goes to the service's log group, in streams `promote-domain/…`.

```bash
# 1. A dry run: the domains, their links, and what changes
scripts/run_promote_domain.sh go.griddo.io

# 2. For real (it asks for the domain again)
scripts/run_promote_domain.sh go.griddo.io --for-real

# 3. DEFAULT_DOMAIN=go.griddo.io on the service, from its current container (§ Rotate the JWT secret has
#    how), and a redeploy

# 4. The frontend: the variable, then its deploy by hand, with no release
gh variable set PUBLIC_SHORT_DOMAIN --body go.griddo.io --repo danielserranoh/shurly
gh workflow run deploy-frontend.yml --ref main --repo danielserranoh/shurly
```

- **If the dry run says `go.griddo.io` "isn't a domain here yet", stop.** The Shlink import makes its row, with its
  links: either the import didn't run on this database, or the name is wrong.
- **Rollback:** `scripts/run_promote_domain.sh s.griddo.io --for-real` while it exists, `DEFAULT_DOMAIN` back, and
  `gh variable delete PUBLIC_SHORT_DOMAIN` with another run of the frontend deploy. Links made in between stay on
  `go.griddo.io`, which Shlink doesn't know, if the ALB goes back to it too.

`tests/test_run_promote_domain.py` runs the script against the import's fake `aws`, and
`tests/test_phase83_promote_domain.py` pins what the switch moves and what it leaves.

## Routine operations

### View logs

```bash
aws logs tail /aws/ecs/default/shurly-api-5fdb --follow --region eu-south-2 --profile griddo-main
```

The log group keeps **60 days** (set 2026-09-28; `mcp_server/README.md` § Usage log has the command).

### Force a redeploy (e.g. after Lambda rule-sync change)

```bash
SERVICE_ARN=$(aws ecs list-services --region eu-south-2 --profile griddo-main \
    --cluster default \
    --query "serviceArns[?contains(@, 'shurly-api')] | [0]" --output text)

aws ecs update-express-gateway-service --region eu-south-2 --profile griddo-main \
    --service-arn "$SERVICE_ARN" --force-new-deployment
```

### Open a psql shell from a Fargate task (ECS Exec)

```bash
TASK_ARN=$(aws ecs list-tasks --region eu-south-2 --profile griddo-main \
    --cluster default --service-name shurly-api \
    --query 'taskArns[0]' --output text)

aws ecs execute-command --region eu-south-2 --profile griddo-main \
    --cluster default --task "$TASK_ARN" \
    --interactive --command "/bin/sh"

# Inside the container:
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME
```

### Rotate the JWT secret

1. `JWT_SECRET_KEY=$(openssl rand -hex 32)`
2. Update the env var in the ECS service (console or `aws ecs update-express-gateway-service`). With the CLI,
   start from the service's current container, as the deploy workflow does: `--primary-container` replaces
   the whole environment, so one built from scratch drops every other setting.
3. Force a redeploy. Existing JWTs will become invalid; clients will need to re-authenticate.

---

## Troubleshooting

### `--monitor-resources` timed out during deploy

Expected per Shlink lesson #2 — not an error. Verify with:

```bash
aws ecs describe-express-gateway-service --region eu-south-2 --profile griddo-main \
    --service-arn "$SERVICE_ARN" \
    --query "service.{status:status,runningCount:runningCount,desiredCount:desiredCount}"
```

### `s.griddo.io` returns 503 / "no healthy upstream" after a deploy

The ALB rule at priority 12 is pointing at the inactive target group. Either:
- The Lambda `ecs-alb-rule-sync`'s `RULE_SYNC_MAP` is missing Shurly's mapping. Add it (see step 6 above).
- Or invoke the Lambda manually: `aws lambda invoke --function-name ecs-alb-rule-sync --payload '{}' /dev/stdout`.

### ACM cert stuck in `PENDING_VALIDATION`

The CNAME wasn't written to Route 53, or it was written to the wrong account. Validation records for `*.griddo.io` always live in `griddo-production`'s zone `Z0999097TJGECCBKJOY1`.

### Visit IPs all show `172.31.x.0` (the ALB's IP)

`TRUSTED_PROXIES` isn't configured. Set it to `["172.31.0.0/16"]` in the task definition env vars and redeploy.

---

## Phase status

- ✅ Phase 4.1 — Cleanup of Lambda/SAM artifacts
- ✅ Phase 4.2 — Container image + health endpoint + production env template
- ✅ Phase 4.3 — RDS `shurly-db` created with `scripts/create_rds.sh`
- ✅ Phase 4.4 — TLS cert for `s.griddo.io` issued and validated
- ✅ Phase 4.5 — ECS Express service `shurly-api` created with `scripts/deploy_ecs.sh`
- ✅ Phase 4.6 — `s.griddo.io` wired with `scripts/setup_custom_domain.sh` (ALB rule priority 12)
- ✅ Phase 4.7 — Lambda `ecs-alb-rule-sync` `RULE_SYNC_MAP` extended with `"4": "12"`
- ✅ Phase 4.8 — `.github/workflows/deploy-backend.yml` rewritten for OIDC + ECR + ECS
- ✅ Phase 4.9 — First real deploy, 2026-04-27. Lessons learned in [`docs/AWS_ECS_DEPLOYMENT.md`](docs/AWS_ECS_DEPLOYMENT.md)
