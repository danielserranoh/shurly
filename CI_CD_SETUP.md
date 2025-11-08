# CI/CD Setup Guide

This guide explains how to set up automated deployment with GitHub Actions for Shurly.

## Overview

We have three GitHub Actions workflows:

1. **Test** (`test.yml`) - Runs on every push/PR
2. **Deploy Backend** (`deploy-backend.yml`) - Deploys Lambda to AWS
3. **Deploy Frontend** (`deploy-frontend.yml`) - Deploys frontend to S3/CloudFront

## Prerequisites

- AWS Account with appropriate permissions
- GitHub repository with Actions enabled
- AWS credentials (Access Key ID and Secret Access Key)

## Step 1: Create AWS IAM User for CI/CD

Create a dedicated IAM user for GitHub Actions deployments:

```bash
# Create IAM user
aws iam create-user --user-name github-actions-shurly

# Create access keys
aws iam create-access-key --user-name github-actions-shurly
```

**Save the credentials** - you'll need them for GitHub Secrets.

### Required IAM Permissions

Attach the following policies to the CI/CD user:

```bash
# Create policy file
cat > github-actions-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:*",
        "lambda:*",
        "apigateway:*",
        "iam:GetRole",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:PutRolePolicy",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:PassRole",
        "logs:*",
        "s3:*",
        "cloudfront:CreateInvalidation"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Create and attach policy
aws iam create-policy \
  --policy-name ShurlyGitHubActionsPolicy \
  --policy-document file://github-actions-policy.json

aws iam attach-user-policy \
  --user-name github-actions-shurly \
  --policy-arn arn:aws:iam::ACCOUNT_ID:policy/ShurlyGitHubActionsPolicy
```

## Step 2: Configure GitHub Secrets

Go to your GitHub repository: **Settings → Secrets and variables → Actions**

### Required Secrets

Add the following **Repository Secrets**:

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `AWS_ACCESS_KEY_ID` | AWS access key for CI/CD user | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key for CI/CD user | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| `DB_HOST` | RDS PostgreSQL endpoint | `shurly-dev-db.xxx.eu-west-1.rds.amazonaws.com` |
| `DB_PASSWORD` | PostgreSQL password | `your-secure-password` |
| `JWT_SECRET_KEY` | JWT secret for token generation | Generate with `openssl rand -hex 32` |
| `CORS_ORIGINS` | CORS allowed origins (JSON) | `["https://shurl.griddo.io"]` |

### Optional Secrets (for frontend deployment)

| Secret Name | Description | Example Value |
|-------------|-------------|---------------|
| `API_ENDPOINT` | Backend API URL | `https://xxx.execute-api.eu-west-1.amazonaws.com/dev` |

### Repository Variables

Add the following **Variables** (not secrets):

| Variable Name | Description | Example Value |
|---------------|-------------|---------------|
| `CLOUDFRONT_DISTRIBUTION_ID` | CloudFront distribution ID | `E1ABCDEFGHIJK` |

## Step 3: Configure GitHub Environments

Create environments for deployment protection:

1. Go to **Settings → Environments**
2. Create three environments:
   - `dev`
   - `staging`
   - `prod`

### Production Protection (Recommended)

For the `prod` environment:
1. Enable **Required reviewers** - add yourself or team members
2. Enable **Wait timer** - optional cooldown period
3. Set **Deployment branches** - only allow `main` or `production` branch

## Step 4: Using the Workflows

### Automated Deployments

**Test Workflow** - Runs automatically on:
- Every push to `main`, `develop`, or `claude/**` branches
- Every pull request to `main` or `develop`

**Backend Deployment** - Runs automatically on:
- Push to `main` or `production` branches
- Can also be triggered manually (see below)

**Frontend Deployment** - Runs automatically on:
- Push to `main` or `production` that modifies `frontend/**`
- Can also be triggered manually (see below)

### Manual Deployments

To manually trigger a deployment:

1. Go to **Actions** tab in GitHub
2. Select the workflow (e.g., "Deploy Backend to AWS")
3. Click **Run workflow**
4. Select the environment (`dev`, `staging`, or `prod`)
5. Click **Run workflow**

## Step 5: Monitoring Deployments

### View Workflow Runs

- Go to **Actions** tab
- Click on any workflow run to see details
- View logs for each step

### Deployment Status

Each workflow provides:
- ✅ Test results
- 📦 Build artifacts
- 🚀 Deployment confirmation
- 🔗 Deployed API endpoint

### CloudWatch Logs

View Lambda logs:
```bash
# View recent logs
aws logs tail /aws/lambda/shurly-api-dev --follow --region eu-west-1
```

## Workflow Details

### Test Workflow

**Triggers**: Push, Pull Request
**Duration**: ~2-3 minutes
**What it does**:
- Runs tests with pytest (Python 3.10 and 3.11)
- Checks code formatting with ruff
- Uploads coverage to Codecov (optional)

### Backend Deployment Workflow

**Triggers**: Push to main, Manual
**Duration**: ~5-7 minutes
**What it does**:
1. Runs tests and linting
2. Builds Lambda package with SAM
3. Deploys to AWS CloudFormation
4. Returns API endpoint URL
5. Tests the deployed API

**Required Secrets**:
- AWS credentials
- Database credentials
- JWT secret

### Frontend Deployment Workflow

**Triggers**: Push to main (frontend changes), Manual
**Duration**: ~2-3 minutes
**What it does**:
1. Builds Astro frontend
2. Uploads to S3 bucket
3. Invalidates CloudFront cache
4. Returns deployment URL

**Required Secrets**:
- AWS credentials
- API endpoint (for frontend config)

## Troubleshooting

### "Secrets not found" error

**Problem**: Workflow fails with missing secrets
**Solution**: Verify all secrets are added in GitHub Settings → Secrets

### "Insufficient permissions" error

**Problem**: AWS IAM user lacks permissions
**Solution**: Review and attach required IAM policies (see Step 1)

### "Stack already exists" error

**Problem**: CloudFormation stack name conflict
**Solution**: Delete existing stack or use different environment name

### "Tests failed" blocking deployment

**Problem**: Deployment blocked by test failures
**Solution**: Fix failing tests before deploying (this is by design!)

## Best Practices

### Branch Strategy

**Recommended approach**:
- `develop` - Development branch (auto-deploy to dev environment)
- `main` - Production-ready code (auto-deploy to prod environment)
- Feature branches - Create PRs to `develop`

### Environment Strategy

**Progressive deployment**:
1. Deploy to `dev` for testing
2. Deploy to `staging` for validation
3. Deploy to `prod` with approval

### Security

1. **Never commit secrets** - Use GitHub Secrets
2. **Rotate credentials** - Periodically update AWS access keys
3. **Enable protection** - Require reviews for production
4. **Monitor deployments** - Set up CloudWatch alarms

### Testing Before Deployment

Always ensure:
- ✅ All 104 tests pass locally
- ✅ Code formatted with `ruff format .`
- ✅ No linting errors with `ruff check .`

## Cost Considerations

GitHub Actions provides:
- **2,000 minutes/month** free for public repositories
- **500 MB storage** for artifacts

Each deployment uses:
- Test workflow: ~4 minutes (Python 3.10 + 3.11)
- Backend deployment: ~5-7 minutes
- Frontend deployment: ~2-3 minutes

**Total**: ~10-15 minutes per full deployment cycle

For private repositories on free tier, monitor usage to stay within limits.

## Next Steps

After setting up CI/CD:

1. **Test the workflows**:
   ```bash
   git add .
   git commit -m "test: Trigger CI/CD pipeline"
   git push origin main
   ```

2. **Monitor the Actions tab** to see workflows run

3. **Set up CloudWatch alarms** for production monitoring

4. **Configure custom domain** (Phase 4.5)

5. **Add frontend monitoring** (Google Analytics, etc.)

## Reference

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [AWS SAM CI/CD](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-deploying.html)
- [GitHub Environments](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
