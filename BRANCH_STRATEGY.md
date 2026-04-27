# Branch Strategy

> Effective from Phase 4 onwards (when ECS Express went live in production).

`main` mirrors what's running in production. Every merge to `main` auto-deploys to ECS Express in `griddo-main` (eu-south-2) via the `Deploy Backend to ECS` workflow. There is no separate "release" step.

```
feat/*                        ← feature branches
   │  PR + Tests pass
   ▼
 dev                           ← integration; no auto-deploy
   │  PR + Tests pass
   ▼
 main                          ← production; auto-deploys on merge
   │
   ▼
 ECS Express @ s.griddo.io
```

## Branches

### `main` — production
- **What's there is what's running.** No drift.
- **Protected**: PR required, `test-summary` status check required, strict (must be up-to-date with base), no force-pushes, no deletions.
- **Approvals required**: 0. The one-dev project doesn't get value from self-approval theatre. Real gate = tests + diff self-review at PR open.
- **Admin bypass**: enabled for emergency repairs only. If you bypass, document why in the commit message.
- **Auto-deploy**: every push to `main` fires `.github/workflows/deploy-backend.yml`, which builds + pushes the image to ECR and rolls out the ECS Express service.

### `dev` — integration
- Long-lived branch where feature branches land before production.
- **Not auto-deployed.** Lets you accumulate changes and ship as a coherent batch.
- Protection: not enforced today. If multiple contributors arrive, add the same status-check rule.

### `feat/<phase>-<short-name>` — feature branches
- Branched from `dev`, merged back via PR.
- Naming convention: `feat/phase-X.Y-<descriptor>` for roadmap-tracked work; anything else for ad-hoc.
- Squash-merge or merge-commit are both fine; the existing history uses regular merge commits.

### `hotfix/<short-name>` — emergency fix path
- For when something is on fire and the dev → main route is too slow.
- **Branched from `main`** (not `dev`).
- PR straight to `main`. Tests must still pass — the protection rule applies.
- After merging to `main`, also merge back to `dev` so the fix isn't lost when `dev` next promotes to `main`.
- Use sparingly. Most "urgent" things can wait the extra 5 minutes for the normal flow.

## Deploy semantics

### What "auto-deploy on `main` merge" actually does
1. Push lands on `main`.
2. `Deploy Backend to ECS` workflow fires.
3. Tests run (yes, again — they ran on the PR but we re-verify on the merged code).
4. Docker image built for `linux/amd64,linux/arm64`, tagged `<sha>-<timestamp>`, pushed to ECR.
5. `update-express-gateway-service` rolls out the new image.
6. The `ecs-alb-rule-sync` Lambda follows the active TG so `s.griddo.io` stays up.
7. Smoke test against `s.griddo.io/api/v1/health` from the workflow.

### Rollback
- **Preferred**: `git revert` the offending commit, PR back to `main`, merge. Re-fires the deploy with the previous code. Keeps history honest.
- **Fast rollback**: trigger the workflow manually with a previous git SHA via `workflow_dispatch`. Useful when the offender is unclear and you just want last-known-good back fast.
- **Don't**: `git push --force` to `main` (blocked by protection) or revert in the AWS console (drifts the deployed state from `main` HEAD).

### Skipping a deploy
Any commit message containing `[skip ci]` skips the workflow. Use sparingly for docs-only commits that genuinely don't change runtime behavior.

## Status checks

The required check is `test-summary` (the aggregate job in `.github/workflows/test.yml`). It only succeeds when both `test (3.10)` and `test (3.11)` matrix legs pass. Adding it as the single required check covers both Python versions without listing each one.

The `Lint with ruff` step is `continue-on-error: true` for now (35 pre-existing errors). Once we ship the cleanup PR, flip lint to blocking.

## What we deliberately don't do (yet)

- **Multi-environment deploys**: there's no separate `staging` ECS service. When we need one, add a second ECS Express service + a `staging` branch + a separate workflow input. Until then, `main` = the single environment.
- **Tag-based releases / SemVer**: the deployed image's commit SHA is the version. If marketing or external integrations need stable references, we add tags later.
- **CODEOWNERS**: with one dev, every owner is the same person. Add when the team grows.
- **Required signed commits**: not enforced. Add when audit requires it.

## Decision log

- **2026-04-27** — Adopted this model after Phase 4 deploy. Previously `main` was loosely "where releases get cut" with manual deploys and no enforcement. The shift to ECS Express + `s.griddo.io` made the link concrete: `main` = prod, full stop.
