# Shurly on AWS ECS Express — Operational Playbook

> **Audience:** anyone deploying, operating, or debugging Shurly in production.
> **Scope:** ECS Express on Fargate in `griddo-main` (eu-south-2), serving `s.griddo.io`.
>
> This document is a complement to [`DEPLOYMENT.md`](../DEPLOYMENT.md), not a replacement:
> - `DEPLOYMENT.md` is the **step-by-step walkthrough** for deploying from scratch.
> - This file is the **playbook**: lessons from the first rollout, troubleshooting catalog, operational runbook, and decision log.
>
> When you hit a problem, read this first. When you need to deploy fresh, read `DEPLOYMENT.md`.

---

## Quick reference

```
┌────────────────────────────────────────────────────────────────────┐
│  Production: s.griddo.io                                           │
│  Account:    griddo-main (686255983646)  /  Region: eu-south-2     │
│                                                                    │
│  ECS service:        shurly-api  (cluster: default)                │
│  ECR repo:           686255983646.dkr.ecr.eu-south-2.amazonaws...  │
│  RDS instance:       shurly-db  (db.t4g.micro, postgres 17)        │
│  ALB:                ecs-express-gateway-alb-d37ca364              │
│  Listener:           …8d6cb22fed5c0e8b/f182b836d7cff456            │
│  Express priority:   4         (auto-managed by Express Mode)      │
│  Custom rule:        priority 12  → s.griddo.io                    │
│  Lambda rule-sync:   ecs-alb-rule-sync                             │
│  CloudWatch logs:    /aws/ecs/default/shurly-api-5fdb              │
│                                                                    │
│  DNS zone:           griddo.io  in griddo-production               │
│                      (zone Z0999097TJGECCBKJOY1)                   │
└────────────────────────────────────────────────────────────────────┘
```

| Need | Command |
|---|---|
| Deploy from local | `AWS_PROFILE=griddo-main ./scripts/deploy_ecs.sh` |
| Deploy from CI | `git push origin main` (auto via GitHub Actions) |
| View logs | `aws logs tail /aws/ecs/default/shurly-api-5fdb --follow --region eu-south-2 --profile griddo-main` |
| Force redeploy | `aws ecs update-express-gateway-service --service-arn $(aws ecs list-services ... --query "serviceArns[?contains(@,'shurly-api')] \| [0]" -o text) --force-new-deployment` |
| Trigger Lambda sync | `aws lambda invoke --function-name ecs-alb-rule-sync --payload '{}' /dev/stdout` |
| Smoke health | `curl https://s.griddo.io/api/v1/health` |

---

## Architecture in one diagram

```
            ┌──────────────────────────────────────────┐
            │                                          │
   user ────►  https://s.griddo.io/<short_code>        │
   (any HTTP client; browser, curl, MCP, ...)         │
            │                                          │
            │   DNS (Route 53 in griddo-production):   │
            │     s.griddo.io  ALIAS A  →  shared ALB  │
            │                                          │
            └────────────────┬─────────────────────────┘
                             │
                             ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Shared ALB (eu-south-2, griddo-main)                       │
   │  ecs-express-gateway-alb-d37ca364                           │
   │                                                             │
   │  HTTPS listener (port 443):                                 │
   │   • cert *.ecs.eu-south-2.on.aws  (auto from Express Mode)  │
   │   • cert s.griddo.io               (manual, ACM)            │
   │   • cert go.griddo.io              (Shlink — coexists)      │
   │   • cert links.griddo.io           (Shlink web client)      │
   │                                                             │
   │  Rules:                                                     │
   │   priority 1   sh-<hex>.ecs.…  → shlink-api active TG       │
   │   priority 3   sh-<hex>.ecs.…  → shlink-web active TG       │
   │   priority 4   sh-<hex>.ecs.…  → shurly-api active TG ◄──┐  │
   │   priority 10  go.griddo.io    → shlink-api active TG    │  │
   │   priority 11  links.griddo.io → shlink-web active TG    │  │
   │   priority 12  s.griddo.io     → shurly-api active TG    │  │  follows priority 4
   │                                                          │  │  via ecs-alb-rule-sync
   │  Default rule: 404                                       │  │  Lambda
   └──────────────────────────────────────────────────────────┼──┘
                                                              │
                  Lambda ecs-alb-rule-sync (EventBridge        │
                  fires on SERVICE_DEPLOYMENT_COMPLETED)        │
                  Reads weights of priority 4, replicates ──────┘
                  to priority 12 so blue/green keeps
                  s.griddo.io healthy through deploys.
                             │
                             ▼ (the active TG points to)
            ┌─────────────────────────────────────────────────┐
            │  ECS Express service: shurly-api                │
            │  Cluster: default                               │
            │  Launch type: Fargate (1.4.0)                   │
            │                                                 │
            │  Task spec (from current task definition):      │
            │   • CPU 256, Memory 512                         │
            │   • Architecture: linux/amd64                   │
            │   • Image: <ECR>/shurly-api:<sha>-<timestamp>   │
            │   • Container: 1 (Main)                         │
            │   • Port: 8000 (uvicorn)                        │
            │                                                 │
            │  Scaling: minTaskCount=1, maxTaskCount=2        │
            │  Health check: GET /api/v1/health → 200         │
            └────────────────────────┬────────────────────────┘
                                     │ uses
                                     ▼
            ┌─────────────────────────────────────────────────┐
            │  RDS PostgreSQL: shurly-db                      │
            │  db.t4g.micro, gp3 20GB, no public access       │
            │  master user: shurly  /  db name: shurly        │
            │  Network: default VPC (172.31.0.0/16)           │
            │  SG:      shurly-db-sg (5432 open within VPC)   │
            └─────────────────────────────────────────────────┘
```

Two AWS accounts:

| Account | Profile | Region | Owns |
|---|---|---|---|
| Griddo Main (686255983646) | `griddo-main` | eu-south-2 | ECS, RDS, ECR, ACM, ALB, IAM, the rule-sync Lambda |
| Griddo Production (253490783612) | `griddo-production` | global | Route 53 zone for `griddo.io` (Z0999097TJGECCBKJOY1) |

---

## Lessons learned (Phase 4 first deploy, 2026-04-27)

These are listed roughly in the order we hit them. Each is a *real* trap — anything you might be tempted to skim past is here because it bit us.

### 1. ECS Express auto-host is opaque, not service-named

The Shlink guide implied auto-generated hosts followed `<service-name>.ecs.<region>.on.aws`. They don't. They're `sh-<32-hex-chars>.ecs.<region>.on.aws`. Our setup script used to grep for `shurly-api.` in the host-header conditions; it never matched. The fix in `setup_custom_domain.sh` is to identify Shurly's TG by elimination (the Express Mode rule whose active TG isn't already bound to a custom-domain rule) or by explicit `EXPRESS_PRIORITY=N` env override.

### 2. JMESPath projections eat filter expressions

Inside a projection (`.Actions[0].ForwardConfig.TargetGroups`), a subsequent `[?Weight==`100`]` runs in projection context and silently returns nothing. The fix is to break out with `| [0]` first, then re-enter:

```
Rules[?Priority=='4'] | [0].Actions[0].ForwardConfig.TargetGroups[?Weight==`100`].TargetGroupArn | [0]
```

Don't trust query strings that "should work but return None"; inspect the raw JSON and trace projection vs. scalar context.

### 3. ECS Express runs on x86_64 Fargate

Building the image `--platform linux/arm64` only saves cost in theory. The Fargate runtime ECS Express provisions defaults to x86_64, and an arm64-only manifest fails to pull with:

```
CannotPullContainerError: image Manifest does not contain descriptor matching platform 'linux/amd64'
```

Build multi-arch (`linux/amd64,linux/arm64`) so the manifest list keeps both options open. Buildx + `--push` uploads the manifest list to ECR; Fargate selects the matching arch at pull time.

### 4. ECS deployment circuit breaker can strand the service

After 3 task-launch failures in a row, ECS sets `desiredCount=0` and stops trying. New deploys don't unstick it automatically. Symptom: `rolloutState=FAILED`, `desired=0`, no tasks running, no events. Fix:

```bash
aws ecs update-express-gateway-service \
    --service-arn $SERVICE_ARN \
    --scaling-target '{"minTaskCount": 1, "maxTaskCount": 2}'
```

This forces a new deployment which resets the circuit breaker.

### 5. AWS API tag conventions are inconsistent across services

ECS expects `key=K,value=V` (lowercase). RDS expects `Key=K,Value=V` (uppercase). Both are documented. Both bite you if you assume one or the other. Symptom for ECS:

```
Unknown parameter in tags[0]: "Key", must be one of: key, value
```

Use the right case per service or factor out into the SDK (which normalizes).

### 6. AWS rejects non-ASCII in resource descriptions

`CreateSecurityGroup --description "...PostgreSQL — VPC-only..."` fails with:

```
InvalidParameterValue: Character sets beyond ASCII are not supported.
```

Em-dashes, accented characters, anything UTF-8 outside ASCII trips this. Stick to ASCII (`-` instead of `—`) in any string passed to AWS APIs. Comments in your shell script can have whatever you want — only the strings sent to AWS matter.

### 7. ECR `IMAGE_TAG_MUTABILITY=IMMUTABLE` blocks re-pushes

Defensive choice for production hygiene; pain during the iteration loop when you re-run `deploy_ecs.sh` against the same commit. The script now defaults `IMAGE_TAG=<sha>-<timestamp>`, producing a unique tag every time while staying traceable to the source commit. Override `IMAGE_TAG=...` explicitly when you want to pin a specific build (e.g., promoting dev to prod).

### 8. `bash source` mangles unquoted JSON values

A `.env` line like `CORS_ORIGINS=["a", "b"]` makes bash try to execute `"a", "b"]` as a command. Even when bash silently absorbs partial assignments, the inner quotes get stripped: `CORS_ORIGINS=[a]` instead of `["a"]`. JSON-decode at runtime fails. Single-quote the entire value:

```
CORS_ORIGINS='["https://shurl.griddo.io","http://localhost:4232"]'
```

The single quotes prevent any shell expansion or quote-stripping. The application sees a valid JSON string and parses it correctly.

### 9. Bash heredoc + JSON template = quoting hell

Trying to assemble an ECS container definition by interpolating shell variables into a JSON heredoc:

```bash
cat <<EOF
{"value": "$CORS_ORIGINS"}
EOF
```

…works fine for plain strings but mangles values containing quotes, backslashes, or `$`. Two layers of escaping (shell + JSON) compound. Use **`jq`** instead:

```bash
jq -n --arg v "$CORS_ORIGINS" '{value: $v}'
```

`jq` takes raw shell strings and emits valid JSON with proper escaping. The deploy script uses this pattern.

### 10. RDS master username can't be changed without recreate

If your `.env` has the wrong `DB_USER`, you don't fix it by editing `.env`. The RDS-side username is fixed at instance creation. Symptom:

```
psycopg2.OperationalError: FATAL: password authentication failed for user "postgres"
```

…even after you reset the password. Postgres returns the same message for "user doesn't exist" and "wrong password". **Always verify against the source of truth**: `aws rds describe-db-instances --query "DBInstances[0].MasterUsername"`.

This bit us. The `.env` had `DB_USER=postgres` (a guess based on RDS defaults) but the actual RDS was created with `--master-username shurly`. Fix was to update the `.env` to match RDS, not the other way around.

### 11. ECS Express service describe is sparse

`describe-express-gateway-service` returns a much smaller object than regular ECS `describe-services`. Fields like `runningCount`, `desiredCount`, `events` aren't there in the same shape. Use:

```bash
aws ecs describe-services --cluster default --services shurly-api  # full info
```

…even though ECS Express is the deploy abstraction. The underlying service is still queryable via the regular ECS API.

### 12. Manual ALB rules drift after every blue/green deploy

Express Mode rotates active/standby target groups during deploys. The custom-domain rule (priority 12) you created with `setup_custom_domain.sh` points at a specific TG ARN. After Express Mode flips, that TG goes from 100% weight to 0% and your custom domain returns 503.

The `ecs-alb-rule-sync` Lambda solves this: triggered by the EventBridge `SERVICE_DEPLOYMENT_COMPLETED` event, it reads the current weights of the Express Mode rule (priority 4) and replicates them onto the custom rule (priority 12). The mapping lives in `RULE_SYNC_MAP` in `alb-rule-sync.py` (in the Shlink repo); update it whenever you wire a new service.

For Shurly: `"4": "12"` is the entry. Lambda confirmed working with `["Synced priority 12 with 4"]`.

### 13. Schema bootstrap had no production path

`Base.metadata.create_all()` runs in `conftest.py` (tests) and `scripts/init_database.py` (manual). Neither runs in production. First deploy connected to RDS successfully but crashed at the startup hook:

```
psycopg2.errors.UndefinedTable: relation "tags" does not exist
```

Added `Base.metadata.create_all(bind=engine)` to the FastAPI startup event. Idempotent — only creates missing tables, never drops or alters. Safe on every container start. **This is acceptable for greenfield; not acceptable once we ship a non-additive schema change.** When that happens, swap for Alembic and remove the `create_all` call.

---

## Troubleshooting catalog

Symptom-driven. When something breaks, search this section by error message or symptom.

### ALB returns 503 Service Temporarily Unavailable

Three causes, usually one of:

**A. Target group has no healthy targets.** The task isn't running, or it's running but failing health checks.

```bash
# Check task status
aws ecs list-tasks --region eu-south-2 --profile griddo-main --cluster default --service-name shurly-api
aws elbv2 describe-target-health --region eu-south-2 --profile griddo-main \
    --target-group-arn <active-TG-ARN> \
    --query "TargetHealthDescriptions[].{state:TargetHealth.State,reason:TargetHealth.Reason}"
```

If state is `unhealthy`, `unused`, or empty: dig into the task. If state is `healthy` but you still get 503: skip to (B).

**B. Custom rule (priority 12) points at the wrong TG.** Express Mode flipped target groups during a deploy and the rule didn't follow.

```bash
# Compare priority 4 (active TG) vs priority 12 (custom rule TG)
LISTENER_ARN="arn:aws:elasticloadbalancing:eu-south-2:686255983646:listener/app/ecs-express-gateway-alb-d37ca364/8d6cb22fed5c0e8b/f182b836d7cff456"
aws elbv2 describe-rules --region eu-south-2 --profile griddo-main \
    --listener-arn "$LISTENER_ARN" \
    --query "Rules[?Priority=='4' || Priority=='12'].{p:Priority,tgs:Actions[0].ForwardConfig.TargetGroups[].{tg:TargetGroupArn,w:Weight}}"
```

If priority 4 has weight 100 on TG-A but priority 12 has weight 100 on TG-B: rule-sync Lambda is out of date. Force it:

```bash
aws lambda invoke --region eu-south-2 --profile griddo-main \
    --function-name ecs-alb-rule-sync --payload '{}' /dev/stdout
```

Expected output: `["Synced priority 12 with 4"]` or `["No changes needed"]`.

**C. DNS hasn't propagated.** Less common but possible right after `setup_custom_domain.sh`.

```bash
dig s.griddo.io +short  # should return the ALB's IPs
```

If empty, wait 60s and try again. Route 53 propagation is normally <30s but can spike.

### Container won't start (CrashLoopBackOff equivalent)

Symptoms: tasks cycle every 30-60s, deployment shows `failedTasks` count incrementing, `rolloutState: FAILED`.

```bash
# Find the latest task arn (running or stopped)
aws ecs list-tasks --region eu-south-2 --profile griddo-main \
    --cluster default --service-name shurly-api --desired-status STOPPED --max-results 1

# Read its log stream
LATEST_STREAM=$(aws logs describe-log-streams --region eu-south-2 --profile griddo-main \
    --log-group-name /aws/ecs/default/shurly-api-5fdb \
    --order-by LastEventTime --descending --limit 1 \
    --query "logStreams[0].logStreamName" --output text)

aws logs get-log-events --region eu-south-2 --profile griddo-main \
    --log-group-name /aws/ecs/default/shurly-api-5fdb \
    --log-stream-name "$LATEST_STREAM" \
    --start-from-head --query "events[].message" --output text
```

Common boot failures:

| Error | Cause | Fix |
|---|---|---|
| `password authentication failed for user "X"` | DB_USER wrong OR password wrong | `aws rds describe-db-instances ... --query MasterUsername` to verify; reset password via `modify-db-instance` if needed |
| `relation "X" does not exist` | Schema not bootstrapped | Should be impossible after Phase 4.2; if it happens, check the startup event in `main.py` is running and has `Base.metadata.create_all()` |
| `error parsing value for field "X" from source "EnvSettingsSource"` | env var mangled (usually JSON list) | Inspect via `describe-task-definition` and compare to `.env`; if different, fix the deploy script's quoting |
| `CannotPullContainerError: ... 'linux/amd64'` | image is arm64-only | rebuild multi-arch with `--platform linux/amd64,linux/arm64` |

### `update-express-gateway-service` returns 503 from auto-host

Same as ALB 503 — the auto-host (`sh-<hex>.ecs.eu-south-2.on.aws`) goes through the same listener and rules.

### Deployment marked FAILED, no new tasks starting

Circuit breaker tripped (3 task failures in a row). Reset:

```bash
SERVICE_ARN=$(aws ecs list-services --region eu-south-2 --profile griddo-main --cluster default \
    --query "serviceArns[?contains(@, 'shurly-api')] | [0]" --output text)
aws ecs update-express-gateway-service --region eu-south-2 --profile griddo-main \
    --service-arn "$SERVICE_ARN" \
    --scaling-target '{"minTaskCount": 1, "maxTaskCount": 2}'
```

This creates a new deployment with the latest task definition and `desiredCount=1`.

### Lambda rule-sync fails or doesn't fire

Check it has the right `RULE_SYNC_MAP`:

```bash
aws lambda get-function --function-name ecs-alb-rule-sync \
    --region eu-south-2 --profile griddo-main \
    --query "Code.Location" --output text
# (download via the URL, unzip, inspect alb-rule-sync.py)
```

Should include `"4": "12"` for Shurly. If missing, edit and redeploy:

```bash
cd ~/Documents/Cowork/Griddo/Marketing\ \&\ Comms/WebAnalytics/ga-gtm
zip alb-rule-sync.zip alb-rule-sync.py
aws lambda update-function-code --region eu-south-2 --profile griddo-main \
    --function-name ecs-alb-rule-sync --zip-file fileb://alb-rule-sync.zip
```

### Auto-deploy from GitHub Actions failed

```bash
gh run list --workflow=deploy-backend.yml --limit 3
gh run view <RUN_ID> --log-failed
```

Common: AWS_DEPLOY_ROLE_ARN secret missing or pointing at a deleted role; OIDC trust policy doesn't match the repo+branch pattern; tests failed (the workflow runs them again post-merge as a safety net).

---

## Operational runbook

### Deploy from local

```bash
AWS_PROFILE=griddo-main ./scripts/deploy_ecs.sh
```

The script handles the entire build → push → roll-out cycle. Run it from the project root with a populated `.env` (see `.env.production.example`).

### Deploy from CI

Push to `main`. Branch protection requires PR + passing tests, so the pipeline is:

```
PR opened → Tests run → PR merged to main → deploy-backend.yml fires →
build multi-arch → push to ECR → update-express-gateway-service → smoke /api/v1/health
```

No manual step. The auto-deploy uses the `AWS_DEPLOY_ROLE_ARN` GitHub secret to assume an IAM role via OIDC (no long-lived AWS keys).

### Deploy a specific image (rollback)

```bash
# Trigger workflow with explicit env (deploys main HEAD; no SHA pinning yet)
gh workflow run deploy-backend.yml --field environment=prod
```

For a true rollback, revert the offending commit on `main` via PR. The auto-deploy then ships the reverted code.

### Tail logs in real time

```bash
aws logs tail /aws/ecs/default/shurly-api-5fdb \
    --region eu-south-2 --profile griddo-main --follow
```

Add `--since 10m` to start from 10 minutes ago. `--filter-pattern ERROR` to see only errors.

### View specific request by X-Request-Id

Every response carries `X-Request-Id`. To correlate logs:

```bash
aws logs filter-log-events \
    --log-group-name /aws/ecs/default/shurly-api-5fdb \
    --filter-pattern '"<request-id-uuid>"' \
    --region eu-south-2 --profile griddo-main
```

(Once we add structured logging that includes the request id in every line, this becomes more useful. Today only the response header carries it.)

### ECS Exec into a running task (psql or shell)

```bash
TASK_ARN=$(aws ecs list-tasks --region eu-south-2 --profile griddo-main \
    --cluster default --service-name shurly-api --query 'taskArns[0]' --output text)

aws ecs execute-command --region eu-south-2 --profile griddo-main \
    --cluster default --task "$TASK_ARN" \
    --interactive --command "/bin/sh"

# Inside the container:
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME
# OR poke at the running app:
curl http://localhost:8000/api/v1/health
```

`execute-command` requires `enableExecuteCommand=true` on the service (set at create time) AND the task role must have SSM permissions. If it fails, `enableExecuteCommand` may have been false; the fix is `update-service --enable-execute-command` then force-redeploy.

### Force a redeploy (no code change)

```bash
SERVICE_ARN=$(aws ecs list-services --region eu-south-2 --profile griddo-main \
    --cluster default --query "serviceArns[?contains(@,'shurly-api')] | [0]" --output text)
aws ecs update-express-gateway-service --region eu-south-2 --profile griddo-main \
    --service-arn "$SERVICE_ARN" --force-new-deployment
```

Useful for re-applying env vars after `update-express-gateway-service --primary-container ...`, recycling stale connections, or testing the rule-sync Lambda.

### Rotate the JWT secret

1. `JWT_SECRET_KEY=$(openssl rand -hex 32)` — new value.
2. Update the env var in the `.env` AND the ECS service's primary container env.
3. `./scripts/deploy_ecs.sh` (or push to main).
4. **All existing JWTs become invalid.** Clients must log in again.

For zero-downtime rotation, you'd need to support two keys briefly — not implemented today.

### Rotate the DB password

```bash
NEW_PASS=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)

aws rds modify-db-instance --region eu-south-2 --profile griddo-main \
    --db-instance-identifier shurly-db \
    --master-user-password "$NEW_PASS" --apply-immediately

aws rds wait db-instance-available --region eu-south-2 --profile griddo-main \
    --db-instance-identifier shurly-db
```

Then update `.env` and redeploy. Existing tasks die when their connections are reset; new tasks pick up the new password.

### Scale up/down

```bash
aws ecs update-express-gateway-service --region eu-south-2 --profile griddo-main \
    --service-arn "$SERVICE_ARN" \
    --scaling-target '{"minTaskCount": 2, "maxTaskCount": 4}'
```

Express Mode currently doesn't expose target-tracking autoscaling (CPU/memory thresholds). For Shurly's volume, manual scaling is fine.

### View the current task definition env

```bash
TD=$(aws ecs describe-services --region eu-south-2 --profile griddo-main \
    --cluster default --services shurly-api \
    --query "services[0].taskDefinition" --output text)
# (note: this returns "None" for Express Mode services — workaround:)

LATEST_TD=$(aws ecs list-task-definitions --region eu-south-2 --profile griddo-main \
    --family-prefix default-shurly-api --status ACTIVE --sort DESC --max-items 1 \
    --query "taskDefinitionArns[0]" --output text)

aws ecs describe-task-definition --region eu-south-2 --profile griddo-main \
    --task-definition "$LATEST_TD" \
    --query "taskDefinition.containerDefinitions[0].environment" --output json
```

---

## Decision log

### Why ECS Express over Lambda?

Decided in this conversation, 2026-04-26. Three reasons:

1. **Phase 5 (MCP server) prefers a long-lived process.** Streamable HTTP transports work on Lambda but cold starts and 30s timeouts hurt; on a container they're native.
2. **Cold-start latency on the redirect path.** Users click a short URL and expect <100ms. Lambda cold start on first hit is 200-800ms.
3. **RDS connection pool churn.** Lambda execution contexts recycle every ~15 min; container keeps the pool warm.

Cost trade: ~$15-20/mo more than Lambda. ALB shared with Shlink amortizes the load-balancer cost across services so the marginal cost of adding Shurly was ~$17/mo total.

### Why multi-arch image (amd64 + arm64)?

ECS Express Fargate runs on x86_64 by default; an arm64-only image fails to pull. Building both keeps the manifest portable and works on developer Macs (Apple Silicon) for local Docker testing without changes. Tradeoff: ~2x build time on x86 hosts due to QEMU emulation. Acceptable for our deploy frequency.

### Why `Base.metadata.create_all()` in startup instead of Alembic?

Time vs. correctness for greenfield. We'd rather ship Phase 4 with a 6-line idempotent startup hook than block on a migration framework that has no value yet (no schema changes to migrate). The `create_all` is safe — only creates missing tables, never drops or alters.

When we make our first non-additive schema change (column rename, type change, drop), this assumption breaks. At that point: switch to Alembic, autogenerate migrations, and remove the startup `create_all`.

### Why two AWS accounts (service vs. DNS)?

Inherited from existing Griddo infrastructure. The `griddo.io` apex zone is in `griddo-production`. Service deployments live in `griddo-main`. Cross-account DNS via subdomain delegation OR per-record cross-account writes — we use the latter (each Route 53 write is an explicit `--profile griddo-production` call). It's slightly more friction per record but doesn't require setting up cross-account IAM roles.

### Why share the ALB with Shlink instead of a dedicated one?

~$16/mo savings per service. The shared ALB has multiple listeners and rules; Shurly's traffic doesn't impact Shlink's and vice versa. Operational cost: a deploy of either service may need the rule-sync Lambda to fire (it handles both). Acceptable.

### Why `auto-deploy on main merge` instead of a manual gate?

Single developer, no SLA. Adding a manual deploy step would only add friction without adding safety — the PR review IS the safety gate. When the team grows or we have customers who notice deploys, reconsider.

### Why no Alembic / SemVer tags / multi-environment / signed commits / CODEOWNERS?

Listed in `BRANCH_STRATEGY.md` § "What we deliberately don't do (yet)". All deferred until pain points justify them.

---

## Cross-references

- [`DEPLOYMENT.md`](../DEPLOYMENT.md) — step-by-step "how to deploy from scratch"
- [`BRANCH_STRATEGY.md`](../BRANCH_STRATEGY.md) — Git workflow, branch protection, release flow
- [`CHANGELOG.md`](../CHANGELOG.md) — what changed in each release
- [`_pm/ROADMAP.md`](../_pm/ROADMAP.md) — phase plan and where we are
- Shlink deploy guide (private, in `~/Documents/Cowork/Griddo/Marketing & Comms/WebAnalytics/shlink-deploy-guide.md`) — the original ECS Express playbook this one inherits from.

---

## Glossary

- **Express Mode / ECS Express** — AWS's simplified ECS service abstraction (replacement for App Runner). Bundles cluster, ALB, target groups, scaling, and IAM into one `aws ecs create-express-gateway-service` call.
- **TG (Target Group)** — ALB target group. Express Mode creates two per service for blue/green deploys.
- **Active TG** — the target group with weight=100 in the Express Mode rule. Receives all production traffic.
- **Standby TG** — the other one, weight=0. Used during blue/green to bring up the new version before switching weights.
- **Auto-host** — Express Mode auto-generated hostname `sh-<32-hex>.ecs.<region>.on.aws`. Reachable for testing without setting up a custom domain.
- **Custom rule** — manually-created ALB rule (priority 10+) that maps a custom domain to a service's active TG.
- **Rule-sync Lambda** — `ecs-alb-rule-sync`, fires on `SERVICE_DEPLOYMENT_COMPLETED`, replicates active TG weights from the Express Mode rule to the custom rule.
- **Circuit breaker** — ECS deployment safeguard that stops launching tasks after N consecutive failures, sets `desiredCount=0`. Reset by `update-express-gateway-service --scaling-target`.
- **Cross-account profile** — AWS CLI profile that resolves to a different account. Shurly uses `griddo-main` for service operations and `griddo-production` for DNS writes.
