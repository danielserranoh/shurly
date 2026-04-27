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
   └─ priority 12 → shurly-api      → s.griddo.io
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
| `s.griddo.io` | Shurly API + redirect path | 4 (this guide) |
| `shurl.griddo.io` (or `shurly.griddo.io`) | Future frontend | 7 |

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
CORS_ORIGINS=["https://shurl.griddo.io"]
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

The `ecs-alb-rule-sync` Lambda (created during the Shlink deploy, see Shlink Phase 10) already handles this for Shlink. To extend it for Shurly, edit its `RULE_SYNC_MAP`:

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
zip alb-rule-sync.zip alb-rule-sync.py
aws lambda update-function-code --region eu-south-2 --profile griddo-main \
    --function-name ecs-alb-rule-sync \
    --zip-file fileb://alb-rule-sync.zip
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
curl https://s.griddo.io/api/v1/health
```

### 7. Smoke checklist

```bash
# Liveness
curl https://s.griddo.io/api/v1/health
# Readiness (DB connectivity)
curl https://s.griddo.io/api/v1/health/db

# Register a test user
curl -X POST https://s.griddo.io/api/v1/auth/register \
    -H "Content-Type: application/json" \
    -d '{"email":"smoke@griddo.io","password":"smoke-test-1234"}'

# Login → JWT
TOKEN=$(curl -s -X POST https://s.griddo.io/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"smoke@griddo.io","password":"smoke-test-1234"}' | jq -r .access_token)

# Create a short URL
curl -X POST https://s.griddo.io/api/v1/urls \
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
    https://s.griddo.io/api/v1/analytics/orphan-visits
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

If your privacy policy permits storing full IPs, set `ANONYMIZE_REMOTE_ADDR=false` — but document the decision.

## Trusted-Proxy Configuration

`X-Forwarded-For` is **never** trusted by default — anyone can spoof it. Once the ALB sits in front of the API (which it does), set `TRUSTED_PROXIES` to the CIDRs that may legitimately set the header.

For the shared ALB inside the default VPC, the right value is the VPC's CIDR:

```bash
TRUSTED_PROXIES='["172.31.0.0/16"]'
```

The resolver (`server/utils/network.py::resolve_client_ip`) checks the request's source against every CIDR; only when it matches does it honor the leftmost `X-Forwarded-For` entry. Outside the allowlist the socket address wins.

If you ever front the ALB with CloudFront, append the CloudFront edge CIDRs from <https://ip-ranges.amazonaws.com/ip-ranges.json> (filter `service=CLOUDFRONT`).

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
- 🟡 Phase 4.3 — `scripts/create_rds.sh` ready; **execute manually**
- 🟡 Phase 4.4 — TLS cert; **execute manually** (commands above)
- 🟡 Phase 4.5 — `scripts/deploy_ecs.sh` ready; **execute manually**
- 🟡 Phase 4.6 — `scripts/setup_custom_domain.sh` ready; **execute manually**
- 🟡 Phase 4.7 — Lambda `ecs-alb-rule-sync` `RULE_SYNC_MAP` extension; **edit + redeploy manually** (instructions above)
- ✅ Phase 4.8 — `.github/workflows/deploy-backend.yml` rewritten for OIDC + ECR + ECS
- ⏳ Phase 4.9 — First real deploy (the steps above, executed end-to-end)
