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
        Fargate task (ARM64, 0.25 vCPU / 0.5 GB)
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
- Python 3.10+, `uv`, and the project deps installed locally for the test step inside `scripts/deploy_ecs.sh`.
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
CORS_ORIGINS=["https://shurly.griddo.io"]
EOF
chmod 600 .env  # avoid accidental git add
```

Then deploy:

```bash
AWS_PROFILE=griddo-main ./scripts/deploy_ecs.sh
```

The script:
- Creates the ECR repository `shurly-api` if needed (with image scanning + immutable tags).
- Builds the container for `linux/arm64` and pushes by SHA.
- Calls `aws ecs create-express-gateway-service` with all Phase 3.9/3.10 settings as env vars, `--cpu 256 --memory 512`, healthcheck `/api/v1/health`, scaling 1–2 tasks, and Shlink's existing IAM roles.
- Tolerates the documented `--monitor-resources` timeout (Shlink lesson #2) and verifies via `describe-express-gateway-service`.
- On subsequent runs, the script detects the service exists and calls `update-express-gateway-service` instead — Express Mode handles the blue/green target group rotation.

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
    "1": "10",   # shlink-api  → go.griddo.io
    "3": "11",   # shlink-web  → links.griddo.io
    "<N>": "12", # shurly-api  → s.griddo.io   ← NEW (use the priority printed by setup_custom_domain.sh)
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
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:sub": "repo:danielserranoh/shurly:*"
      }
    }
  }]
}
EOF

aws iam create-role --profile griddo-main \
    --role-name github-actions-shurly-deploy \
    --assume-role-policy-document file://trust-policy.json
```

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

`deploy-backend.yml` is `workflow_dispatch`-only by default. Once the first manual deploy works end-to-end, optionally re-enable `push: branches: [main]` to get continuous delivery.

---

## Frontend hosting (Phase 4.10)

The static build (`frontend/dist/`) lives in a private S3 bucket behind **one CloudFront distribution for
`shurly.griddo.io`**, which also carries the API and the MCP to the ALB. The app and the API then share one
origin, so the browser makes no cross-origin calls. Prepared in the repo: the deploy workflow, the CloudFront
Function and this section. The AWS resources below are still to be created (ROADMAP 4.10).

### The distribution

| Path pattern | Origin | Cache policy | Origin request policy | Function |
|---|---|---|---|---|
| `/api/*` | the ALB | CachingDisabled | AllViewer | — |
| `/mcp*` | the ALB | CachingDisabled | AllViewer | — |
| `/.well-known/*` | the ALB | CachingDisabled | AllViewer | — |
| `/docs*`, `/redoc`, `/openapi.json` | the ALB | CachingDisabled | AllViewer | — |
| Default (`*`) | the S3 bucket, with Origin Access Control | CachingOptimized | — | `static-paths`, viewer request |

- **ALB behaviours:** all HTTP methods (the API takes `POST`, `PUT`, `PATCH`, `DELETE`). AllViewer forwards the `Host`
  header (`shurly.griddo.io`), so the ALB's host rule (priority 12) and its certificate match as they do today.
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

The Content-Security-Policy is a separate item: the inline sign-in guards in `BaseLayout.astro` need hashes
computed at build time.

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

What the workflow does, on merges to `main` that touch `frontend/**` and by hand:

- While `FRONTEND_BUCKET` is unset, it logs `frontend deploy skipped: FRONTEND_BUCKET unset` and stops.
- Otherwise it runs `npm ci`, `npm test` and `npm run build` with the production values:
  - `PUBLIC_API_URL=https://shurly.griddo.io`
  - `PUBLIC_SITE_URL=https://shurly.griddo.io`
  - `PUBLIC_SHORT_DOMAIN=s.griddo.io` (`go.griddo.io` from Phase 8)
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

### Client IPs behind CloudFront: an open decision

Once `shurly.griddo.io` goes through CloudFront, two paths reach the ALB:

- **direct**, for `s.griddo.io` and later `go.griddo.io`;
- **through CloudFront**, for `shurly.griddo.io`: the API and the MCP.

Through CloudFront, the ALB's peer is a CloudFront edge, and the last address in `X-Forwarded-For` is that edge's.
The resolver (§ Trusted-Proxy Configuration) takes the rightmost address that isn't a trusted proxy. It would
therefore record, and rate-limit, CloudFront's edges instead of people. The options are backend and AWS work,
not done here:

1. **Trust CloudFront's edge ranges** in `TRUSTED_PROXIES` (`ip-ranges.json`, `service=CLOUDFRONT`). It's a large
   list, and it changes, so it needs refreshing.
2. **Read `CloudFront-Viewer-Address`**, which CloudFront adds when the origin request policy includes it. It can
   only be trusted on requests that provably came through CloudFront.
3. **Prove that a request came through CloudFront.** Give the distribution a secret origin header that the API
   (or the ALB rule for `shurly.griddo.io`) requires. Optionally, restrict that traffic to CloudFront's
   origin-facing prefix list, `com.amazonaws.global.cloudfront.origin-facing`. With this in place, option 2 is
   safe. The ALB is shared and still serves `s.griddo.io` and `go.griddo.io` directly, so the restriction has to
   be per host, not a security group on the whole ALB.

### Check after the first deploy

- `/` and `/manual/install-mcp/` load.
- `/dashboard/` sends you to the login page.
- `/login` answers `301` to `/login/`.
- `/api/v1/health` answers with JSON, through CloudFront.
- `/mcp/` answers `401` with `WWW-Authenticate`.
- An `_astro/` file's `Cache-Control` is `immutable`, and a page's is `max-age=0`.

## Cost estimation (eu-south-2, monthly)

| Component | Cost |
|---|---|
| RDS PostgreSQL t4g.micro (20 GB gp3, encrypted) | ~$8 |
| ECS Fargate task (0.25 vCPU, 0.5 GB) | ~$9 |
| ALB (shared with Shlink) | $0 marginal |
| ECR (one image, ~200 MB) | <$0.10 |
| CloudWatch Logs (30-day retention) | ~$0.50 |
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

Visitor logging is privacy-first by default, configured via env vars:

- **`ANONYMIZE_REMOTE_ADDR=true`** (default): IPv4 truncated to `/24`, IPv6 to `/64` at insert time. Truncation happens in `server/utils/network.py::anonymize_ip` before the `Visitor` row is committed — full addresses never reach Postgres.
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

Behind CloudFront (`shurly.griddo.io`, Phase 4.10) this needs a decision first: see § Frontend hosting, "Client IPs behind CloudFront".

## Rate limits (Phase 6.3)

What anyone can call is limited per client IP, counted in the database (`rate_limits`) so both tasks share the counts: the password login (every attempt runs a bcrypt check, on the tasks that also serve redirects) and the Google and MCP sign-in endpoints (each request writes a row). Redirects, anything signed in and CORS preflights are never limited.

- **`TRUSTED_PROXIES` must name the ALB** (`["172.31.0.0/16"]` in production): the limits key on the client IP it resolves. Unset, every request seems to come from the ALB, and each per-IP limit becomes one limit for everybody.
- Settings, per minute unless said otherwise; `0` turns one off:

  | Variable | Default | Limits |
  |---|---|---|
  | `RATE_LIMIT_LOGIN_PER_IP` | `20` | `POST /api/v1/auth/login` |
  | `RATE_LIMIT_LOGIN_FAILURES_PER_ACCOUNT` | `10` | Failed password logins per address, per 15 minutes |
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
- **Today's production value lists `https://shurl.griddo.io`, a host that doesn't exist.** It's harmless
  (no browser comes from there) but wrong; it gets corrected at the release.
- Locally the defaults cover the dev server (`http://localhost:4232`) on another port, so the middleware
  stays.

## Sign in with Google (Phase 3.13)

Accounts come from signing in with a Google Workspace account of `ORGANIZATION_DOMAIN` (`griddo.io`).
A password is optional: its owner sets it once signed in. Either way the API issues its own JWT, as
before, so API keys and the MCP don't change.

### Prerequisite: the Google Cloud project

Done once, by whoever administers Google Workspace (ROADMAP 3.13.2). Step by step:
[docs/setup_google_app.md](docs/setup_google_app.md).

1. A Google Cloud project inside the griddo.io organization.
2. OAuth consent screen **Internal**, so only Griddo accounts can sign in. Scopes: `openid`, `email`.
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
- `CORS_ORIGINS` must include the frontend's origin: the page `POST`s the one-time code to
  `/api/v1/auth/google/exchange`.
- **Where they go:** the GitHub deploy keeps the live service's environment and swaps only the image,
  so add these variables to the live ECS config ([docs/setup_google_app.md](docs/setup_google_app.md),
  step 7). `scripts/deploy_ecs.sh` only builds the environment when the service is first created.
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

---

## Routine operations

### View logs

```bash
aws logs tail /ecs/shurly-api --follow --region eu-south-2 --profile griddo-main
```

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
2. Update the env var in the ECS service (console or `aws ecs update-express-gateway-service`).
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
