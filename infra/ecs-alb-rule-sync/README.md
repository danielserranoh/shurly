# ecs-alb-rule-sync

Keeps the custom-domain rules on the shared ALB (`ecs-express-gateway-alb-d37ca364`,
griddo-main / `eu-south-2`) in step with the rules ECS Express manages.

**Shared infrastructure.** It serves three services, not just Shurly:

| Express rule | Custom rule | Domains | Service |
|---|---|---|---|
| 1 | 10 | none: deleted at the cutover (2026-10-02), skipped | shlink-api |
| 3 | 11 | `links.griddo.io` | shlink-web |
| 4 | 12 | `shurly.griddo.io`, `go.griddo.io` | shurly-api |

A change here changes routing for all three.

## Why it exists

Express Mode shifts traffic between two target groups on its own rules (priority
1–5). The custom-domain rules (priority 10+) are ours, and Express doesn't touch
them, so something has to copy the weights across.

## When it runs

EventBridge rule `ecs-deploy-alb-sync`, on `ECS Deployment State Change`:

| Event | What the Lambda does |
|---|---|
| `SERVICE_DEPLOYMENT_IN_PROGRESS` | Follows the deployment: syncs every 5 s until ECS reports it no longer `IN_PROGRESS`, then one final pass. If the 900 s timeout nears first, it re-invokes itself asynchronously to keep following (up to 4 hand-offs, ~75 min) |
| `SERVICE_DEPLOYMENT_COMPLETED` / `_FAILED` | One pass (safety net) |
| Manual `--payload '{}'` | One pass |

Each pass syncs all three mappings and is idempotent. Log lines show the
weights applied and their share, e.g. `weights 950/50 = 95%/5%`. ALB weights are
relative, not percentages: Express uses 950/50 during the canary.

**Why it hands off.** 900 s is Lambda's hard ceiling, and a canary rollout
already used 613 s of it (27 Sep 2026). If a rollout ever outlived one
invocation, the follower would stop before the final shift and the ~1 min 503
would return. The hand-off carries a hop counter (`_follow_hop`), so the chain
can't run forever.

**Why it follows the deployment.** Until 27 Sep 2026 it ran only on `COMPLETED`.
ECS stops the old task about a minute *before* emitting that event, so the custom
rule pointed at an empty target group and the ALB returned 503 (Shurly's custom
domain, 00:16:20 → 00:17:16). The custom domains also never got the canary: they stayed
100% on the old image for the whole rollout.

## Permissions

Role `ecs-alb-rule-sync-lambda`, inline policy `alb-rule-sync`:

- `elasticloadbalancing:DescribeRules`, `elasticloadbalancing:ModifyRule`
- `ecs:DescribeServices` on `service/default/*`, to know when a deployment ends
- `lambda:InvokeFunction` on its own ARN only, for the hand-off

## Deploy

```bash
cd infra/ecs-alb-rule-sync
zip -X /tmp/alb-rule-sync.zip alb-rule-sync.py
AWS_PROFILE=griddo-main aws lambda update-function-code --region eu-south-2 \
    --function-name ecs-alb-rule-sync --zip-file fileb:///tmp/alb-rule-sync.zip
```

Then verify. With everything in sync this should print `["No changes needed"]`:

```bash
AWS_PROFILE=griddo-main aws lambda invoke --region eu-south-2 \
    --function-name ecs-alb-rule-sync --payload '{}' \
    --cli-binary-format raw-in-base64-out /dev/stdout
```

The Lambda timeout must stay at **900 s**: a canary rollout takes ~10–12 min.

## Roll back

The previous version is the parent commit of the fix:

```bash
git show e3a59e6:infra/ecs-alb-rule-sync/alb-rule-sync.py > /tmp/alb-rule-sync.py
# zip + update-function-code as above
AWS_PROFILE=griddo-main aws events put-rule --region eu-south-2 --name ecs-deploy-alb-sync \
    --event-pattern '{"source":["aws.ecs"],"detail-type":["ECS Deployment State Change"],"detail":{"eventName":["SERVICE_DEPLOYMENT_COMPLETED"]}}'
```

The old code doesn't need the extra IAM permission or the longer timeout, but
leaving them in place is harmless.

## Tests

`tests/test_alb_rule_sync.py` drives the handler with fake ELB/ECS/Lambda
clients: manual runs, the canary being followed until completion, stopping when
the deployment disappears, handing off before the timeout (and the hop cap),
the percentages in the log, and the other two services' mappings still being
synced.
