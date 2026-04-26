# Shurly AWS Lambda Deployment Guide

This guide covers deploying Shurly to AWS Lambda with API Gateway and RDS PostgreSQL.

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI configured
- Python 3.10+ locally
- `uv` installed
- Docker (for building Lambda deployment package)

## Architecture Overview

```
Internet
   ↓
CloudFront (CDN) → S3 (Frontend static files)
   ↓
API Gateway (HTTP API)
   ↓
Lambda Function (FastAPI + Mangum)
   ↓
RDS PostgreSQL (Database)
```

## Phase 4.1: Lambda Adaptation ✅

The following changes have been made to make Shurly Lambda-compatible:

1. **Mangum Adapter**: Added to `pyproject.toml` to wrap FastAPI for Lambda
2. **Lambda Handler**: Created `lambda_handler.py` as the entry point
3. **Database Configuration**: Updated for Lambda-optimized connection pooling
4. **Environment Variables**: Added Lambda-specific settings

## Deployment Options

There are two ways to deploy Shurly to AWS:

1. **AWS SAM (Recommended)** - Infrastructure as Code, automated deployment
2. **Manual Deployment** - Step-by-step AWS CLI commands

---

## Option 1: Deploy with AWS SAM (Recommended)

AWS SAM (Serverless Application Model) provides Infrastructure as Code for serverless applications.

### Prerequisites

- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- [Docker](https://docs.docker.com/get-docker/) installed (for building)
- AWS CLI configured with credentials
- RDS PostgreSQL instance created (see manual steps below)

### Quick Start

1. **Install SAM CLI**:
   ```bash
   # macOS
   brew install aws-sam-cli

   # Linux
   pip install aws-sam-cli

   # Verify installation
   sam --version
   ```

2. **Build the Lambda package**:
   ```bash
   # Automated build script
   ./build_lambda.sh

   # Or manually with SAM
   sam build --use-container
   ```

3. **Deploy to AWS** (first time):
   ```bash
   sam deploy --guided
   ```

   You'll be prompted for:
   - **Stack name**: `shurly-prod` (or `shurly-dev`)
   - **AWS Region**: `us-east-1` (or your preferred region)
   - **Parameter Environment**: `prod`, `staging`, or `dev`
   - **Parameter DatabaseHost**: Your RDS endpoint (e.g., `xxx.rds.amazonaws.com`)
   - **Parameter DatabaseName**: `shurly`
   - **Parameter DatabaseUser**: `postgres`
   - **Parameter DatabasePassword**: Your RDS password
   - **Parameter JWTSecretKey**: Generate with `openssl rand -hex 32`
   - **Parameter CorsOrigins**: `["https://shurl.griddo.io"]`

4. **Subsequent Deployments**:
   ```bash
   # Build and deploy with saved config
   sam build --use-container && sam deploy
   ```

### SAM Template Structure

The `template.yaml` defines:
- **Lambda Function** (`ShurlyFunction`): FastAPI app with Mangum
- **API Gateway HTTP API** (`ShurlyHttpApi`): RESTful API endpoint
- **CloudWatch Logs** (`ShurlyLogGroup`): 30-day retention
- **IAM Roles**: Minimal permissions for Lambda execution

### Local Testing with SAM

Test the Lambda function locally before deploying:

```bash
# Start local API Gateway
sam local start-api

# API will be available at http://localhost:3000
# Test endpoints:
curl http://localhost:3000/api/auth/login

# Invoke function directly with test event
sam local invoke ShurlyFunction -e events/test-event.json
```

### Environment-Specific Deployments

Deploy to different environments using profiles:

```bash
# Development
sam deploy --config-env dev \
  --parameter-overrides \
    "Environment=dev \
     DatabaseHost=dev-db.xxx.rds.amazonaws.com \
     DatabasePassword=xxx \
     JWTSecretKey=xxx"

# Staging
sam deploy --config-env staging \
  --parameter-overrides \
    "Environment=staging \
     DatabaseHost=staging-db.xxx.rds.amazonaws.com \
     DatabasePassword=xxx \
     JWTSecretKey=xxx"

# Production
sam deploy --config-env prod \
  --parameter-overrides \
    "Environment=prod \
     DatabaseHost=prod-db.xxx.rds.amazonaws.com \
     DatabasePassword=xxx \
     JWTSecretKey=xxx"
```

### SAM Commands Reference

```bash
# Validate template
sam validate

# Build function
sam build --use-container

# Deploy with guided prompts
sam deploy --guided

# Deploy with saved config
sam deploy

# View logs
sam logs -n ShurlyFunction --stack-name shurly-prod --tail

# Delete stack
sam delete --stack-name shurly-prod

# List stacks
aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE
```

### Updating the Stack

After making code changes:

```bash
# 1. Build new package
sam build --use-container

# 2. Deploy update
sam deploy

# 3. View deployment progress
sam deploy --no-confirm-changeset --no-fail-on-empty-changeset
```

### Cost Estimation (with SAM)

The SAM deployment creates:
- Lambda Function: ~$0.20/month (5,000 requests)
- API Gateway HTTP API: ~$0.50/month
- CloudWatch Logs: ~$0.50/month (30-day retention)

**Note**: RDS PostgreSQL (~€10-12/month in eu-west-1) must be created separately.

---

## Phase 4.3: RDS PostgreSQL Database Setup

Before deploying the Lambda function, you need to create an RDS PostgreSQL database. This section provides automated scripts and manual instructions.

### Automated Setup (Recommended)

We provide a script that automates the entire RDS creation process:

```bash
./scripts/create_rds.sh
```

This script will:
1. ✅ Create RDS instance in **eu-west-1** (Ireland - cheapest EU region)
2. ✅ Configure security group for PostgreSQL access
3. ✅ Enable encryption at rest and SSL connections
4. ✅ Set up automated backups (7-day retention)
5. ✅ Wait for instance to become available
6. ✅ Return the database endpoint

**What you need**:
- AWS CLI configured with credentials
- A secure password (min 8 characters)
- ~10 minutes for RDS to become available

**Cost**: ~€10-12/month for db.t4g.micro

### Step-by-Step: Automated RDS Creation

1. **Run the creation script**:
   ```bash
   cd /path/to/shurly
   ./scripts/create_rds.sh
   ```

2. **Enter PostgreSQL password** when prompted:
   - Minimum 8 characters
   - Mix of letters, numbers, and symbols recommended
   - Save this password securely!

3. **Wait for completion** (~5-10 minutes):
   - The script will wait for the RDS instance to become available
   - You'll see progress updates

4. **Save the endpoint** from the output:
   ```
   Endpoint: shurly-dev-db.xxxxx.eu-west-1.rds.amazonaws.com
   ```

### Test Database Connection

After RDS creation, test the connection:

```bash
./scripts/test_db_connection.sh shurly-dev-db.xxxxx.eu-west-1.rds.amazonaws.com
```

This will verify:
- ✅ Network connectivity (port 5432)
- ✅ PostgreSQL authentication
- ✅ Database exists

### Initialize Database Tables

Option 1: **Automatic** (recommended):
- Tables are auto-created when Lambda first runs
- SQLAlchemy creates all tables on first database connection

Option 2: **Manual initialization**:
```bash
python scripts/init_database.py shurly-dev-db.xxxxx.eu-west-1.rds.amazonaws.com <your-password>
```

This creates all tables (users, urls, campaigns, visitors) before deployment.

### RDS Configuration Details

The automated script creates:
- **Instance**: db.t4g.micro (ARM-based, 2 vCPU, 1GB RAM)
- **Storage**: 20GB gp3 SSD
- **Engine**: PostgreSQL 14.10
- **Backup**: 7-day automated backups
- **Encryption**: At rest (default AWS encryption)
- **SSL**: Required for all connections
- **Performance Insights**: Enabled (7-day retention)
- **Deletion Protection**: Enabled
- **Public Access**: Yes (for dev - can be locked down later)

### Security Group Rules

The script creates a security group with:
- **Inbound**: PostgreSQL (5432) from 0.0.0.0/0 (open for dev)
- **Outbound**: All traffic

**For production**: Lock down to Lambda security group only.

### Troubleshooting RDS Setup

**Issue**: Connection timeout
- **Solution**: Wait 5-10 minutes after creation
- RDS instances take time to fully initialize

**Issue**: Authentication failed
- **Solution**: Double-check password
- Password is case-sensitive

**Issue**: Database not found
- **Solution**: The database name is `shurly` (created automatically)

**Issue**: SSL error
- **Solution**: Ensure `sslmode=require` in connection string

### Manual RDS Creation (Alternative)

If you prefer manual setup via AWS Console or CLI:

---

## Phase 4.4: CI/CD Pipeline (Optional)

For automated deployments with GitHub Actions, see the comprehensive guide:

📋 **[CI/CD Setup Guide](CI_CD_SETUP.md)**

The CI/CD pipeline provides:
- ✅ **Automated testing** on every push/PR
- ✅ **Automated backend deployment** to AWS Lambda
- ✅ **Automated frontend deployment** to S3/CloudFront
- ✅ **Environment-specific deployments** (dev, staging, prod)
- ✅ **Manual deployment triggers** via GitHub UI

### Quick Setup

1. **Add GitHub Secrets**:
   - Go to **Settings → Secrets and variables → Actions**
   - Add: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DB_HOST`, `DB_PASSWORD`, `JWT_SECRET_KEY`, `CORS_ORIGINS`

2. **Trigger Deployment**:
   ```bash
   git push origin main  # Automatic deployment
   ```

   Or use manual trigger in GitHub Actions tab.

### Workflows

- **Test** (`.github/workflows/test.yml`): Runs tests and linting
- **Deploy Backend** (`.github/workflows/deploy-backend.yml`): Deploys Lambda to AWS
- **Deploy Frontend** (`.github/workflows/deploy-frontend.yml`): Deploys to S3

See [CI_CD_SETUP.md](CI_CD_SETUP.md) for complete instructions.

---

## Option 2: Manual Deployment Steps

### Step 1: Create RDS PostgreSQL Database (Manual)

1. **Create RDS Instance**:
   ```bash
   # Using AWS CLI
   aws rds create-db-instance \
     --db-instance-identifier shurly-db \
     --db-instance-class db.t4g.micro \
     --engine postgres \
     --engine-version 14.9 \
     --master-username postgres \
     --master-user-password <YOUR_SECURE_PASSWORD> \
     --allocated-storage 20 \
     --vpc-security-group-ids <YOUR_SECURITY_GROUP> \
     --db-name shurly \
     --backup-retention-period 7 \
     --publicly-accessible false
   ```

2. **Configure Security Group**:
   - Allow inbound PostgreSQL (port 5432) from Lambda security group
   - Ensure Lambda and RDS are in the same VPC

3. **Initialize Database**:
   ```bash
   # Connect to RDS using psql or a database client
   # Tables will be auto-created by SQLAlchemy on first run
   ```

### Step 2: Build Lambda Deployment Package

Create a deployment package with all dependencies:

```bash
# Install dependencies in a temporary directory
mkdir -p lambda_package
uv pip install --target lambda_package -r <(uv pip freeze)

# Copy application code
cp -r server lambda_package/
cp main.py lambda_package/
cp lambda_handler.py lambda_package/

# Create ZIP file
cd lambda_package
zip -r ../shurly-lambda.zip .
cd ..
```

### Step 3: Create Lambda Function

1. **Create IAM Role**:
   ```bash
   # Create execution role with permissions for:
   # - CloudWatch Logs (AWSLambdaVPCAccessExecutionRole)
   # - VPC access (if RDS is in VPC)
   ```

2. **Create Lambda Function**:
   ```bash
   aws lambda create-function \
     --function-name shurly-api \
     --runtime python3.10 \
     --role arn:aws:iam::ACCOUNT_ID:role/shurly-lambda-role \
     --handler lambda_handler.lambda_handler \
     --zip-file fileb://shurly-lambda.zip \
     --timeout 30 \
     --memory-size 512 \
     --environment Variables="{
       DB_HOST=your-rds-endpoint.region.rds.amazonaws.com,
       DB_PORT=5432,
       DB_USER=postgres,
       DB_PASSWORD=<YOUR_PASSWORD>,
       DB_NAME=shurly,
       JWT_SECRET_KEY=<YOUR_JWT_SECRET>,
       IS_LAMBDA=true,
       DB_POOL_SIZE=5,
       DB_MAX_OVERFLOW=10,
       DB_SSL_MODE=require,
       CORS_ORIGINS='[\"https://shurl.griddo.io\"]'
     }"
   ```

3. **Configure VPC** (if RDS is in VPC):
   ```bash
   aws lambda update-function-configuration \
     --function-name shurly-api \
     --vpc-config SubnetIds=subnet-xxx,subnet-yyy,SecurityGroupIds=sg-xxx
   ```

### Step 4: Create API Gateway

1. **Create HTTP API**:
   ```bash
   aws apigatewayv2 create-api \
     --name shurly-api \
     --protocol-type HTTP \
     --target arn:aws:lambda:region:ACCOUNT_ID:function:shurly-api
   ```

2. **Create Integration**:
   ```bash
   aws apigatewayv2 create-integration \
     --api-id <API_ID> \
     --integration-type AWS_PROXY \
     --integration-uri arn:aws:lambda:region:ACCOUNT_ID:function:shurly-api \
     --payload-format-version 2.0
   ```

3. **Create Routes**:
   ```bash
   # Create catch-all route
   aws apigatewayv2 create-route \
     --api-id <API_ID> \
     --route-key '$default' \
     --target integrations/<INTEGRATION_ID>
   ```

4. **Deploy API**:
   ```bash
   aws apigatewayv2 create-stage \
     --api-id <API_ID> \
     --stage-name prod \
     --auto-deploy
   ```

### Step 5: Configure Custom Domain (Optional)

1. **Request SSL Certificate** (ACM):
   ```bash
   aws acm request-certificate \
     --domain-name shurl.griddo.io \
     --validation-method DNS
   ```

2. **Create Custom Domain**:
   ```bash
   aws apigatewayv2 create-domain-name \
     --domain-name shurl.griddo.io \
     --domain-name-configurations CertificateArn=arn:aws:acm:...
   ```

3. **Update Route 53**:
   - Create CNAME record pointing to API Gateway domain

### Step 6: Deploy Frontend to S3 + CloudFront

1. **Build Frontend**:
   ```bash
   cd frontend
   npm run build
   ```

2. **Create S3 Bucket**:
   ```bash
   aws s3 mb s3://shurl-griddo-io-frontend
   aws s3 website s3://shurl-griddo-io-frontend \
     --index-document index.html
   ```

3. **Upload Files**:
   ```bash
   aws s3 sync dist/ s3://shurl-griddo-io-frontend --acl public-read
   ```

4. **Create CloudFront Distribution**:
   - Origin: S3 bucket
   - SSL Certificate: Use ACM certificate
   - CNAME: shurl.griddo.io

## Environment Variables

See `.env.lambda.example` for all required Lambda environment variables.

**Critical Settings for Lambda**:
- `IS_LAMBDA=true` - Enables Lambda-specific optimizations
- `DB_POOL_SIZE=5` - Smaller pool for Lambda (vs 10 for local)
- `DB_MAX_OVERFLOW=10` - Reduced overflow
- `DB_SSL_MODE=require` - Force SSL for RDS connections
- `CORS_ORIGINS` - Must be JSON array string

### Phase 3.9 / 3.10 Settings

These have safe defaults but should be reviewed before exposing to real users.

| Setting | Default | When to override |
|---|---|---|
| `ANONYMIZE_REMOTE_ADDR` | `true` | **Keep ON** for GDPR. Visitor IPs are truncated to /24 (IPv4) or /64 (IPv6) **before** they hit Postgres — there is no second copy. Disable only if a legal review explicitly approves storing full addresses. |
| `TRUSTED_PROXIES` | `[]` | **Required when behind a proxy.** Without it, `X-Forwarded-For` is ignored and every visit IP becomes the proxy's address. Set to a JSON array of CIDRs covering your edge: see [Trusted-Proxy Configuration](#trusted-proxy-configuration) below. |
| `DISABLE_TRACK_PARAM` | `nostat` | The query string that suppresses visit logging while still redirecting. Useful for QA / synthetic monitoring without polluting analytics. Pick a token your real users won't generate. |
| `SHORT_URL_MODE` | `loose` | `loose` lowercases generated codes and custom slugs at insert time (Shlink default — fewer collisions, less user surprise). Set to `strict` to keep mixed case (legacy behavior). |
| `DEFAULT_DOMAIN` | `shurl.griddo.io` | Seeded as the default `Domain` row at startup. URLs without an explicit `domain_id` resolve here. **Set this to your real short-link host before launch.** |
| `REDIRECT_STATUS_CODE` | `302` | `301` is SEO-friendly but cached aggressively — every browser/intermediary may reuse the cached redirect, dropping analytics fidelity. `302` keeps every hit reaching the backend. `307`/`308` preserve the request method (rare for short URLs). The setting is validated up-front; only `301/302/307/308` are accepted. |
| `REDIRECT_CACHE_LIFETIME` | `0` | Seconds to cache the redirect at the edge. `0` emits `Cache-Control: private, max-age=0` (every hit logged). Positive values emit `Cache-Control: public, max-age=N` and trade analytics for latency. |

### GDPR Posture

Visitor logging is privacy-first by default:

- **IPv4 → `/24`** (zero last octet) and **IPv6 → `/64`** at insert time. The
  truncation happens in `server/utils/network.py::anonymize_ip` before the
  `Visitor` row is committed — full addresses never reach Postgres.
- Bots and email tracking pixels share the `visits` table but carry `is_bot`
  and `is_pixel` flags so click analytics exclude them by default.
- Tracking pixel responses are `Cache-Control: no-store` so HTML email clients
  re-fetch on every open.
- The `User.api_key_scope` enum is in place so post-launch role rollouts
  (`READ_ONLY`, `CREATE_ONLY`, `DOMAIN_SPECIFIC`) ship without a destructive
  migration; only `FULL_ACCESS` is enforced today.
- `X-Request-Id` middleware echoes the header on every response (or generates a
  UUID if absent), enabling log correlation in CloudWatch without leaking PII.

If your privacy policy permits storing full IPs, set
`ANONYMIZE_REMOTE_ADDR=false` — but keep this decision documented.

### Trusted-Proxy Configuration

`X-Forwarded-For` is **never** trusted by default — anyone can spoof it from
the open internet. Once you put a proxy in front of the API (which you will:
ALB / CloudFront / API Gateway / nginx), tell the app which source IPs are
allowed to set the header.

`TRUSTED_PROXIES` accepts a JSON array of CIDRs:

```bash
# Behind ALB inside a VPC
TRUSTED_PROXIES='["10.0.0.0/16"]'

# Behind CloudFront → API Gateway (CloudFront's published edge IP ranges)
TRUSTED_PROXIES='["52.46.0.0/18","52.84.0.0/15","54.182.0.0/16","54.192.0.0/16","54.230.0.0/17","54.230.128.0/18","54.239.128.0/18","54.239.192.0/19","99.84.0.0/16","204.246.164.0/22","204.246.168.0/22","204.246.174.0/23","204.246.176.0/20","205.251.192.0/19","205.251.249.0/24","205.251.250.0/23","205.251.252.0/23","205.251.254.0/24","216.137.32.0/19"]'
```

The resolver (`server/utils/network.py::resolve_client_ip`) checks the
request's source address against every CIDR; only when it matches does it
honor the leftmost `X-Forwarded-For` entry. Outside the allowlist the socket
address wins — a defense against header spoofing if the proxy is somehow
bypassed.

For AWS edges, refresh the CloudFront ranges from the official source:
<https://ip-ranges.amazonaws.com/ip-ranges.json> (filter `service=CLOUDFRONT`).

## Testing the Deployment

1. **Test API Gateway URL**:
   ```bash
   curl https://YOUR_API_ID.execute-api.region.amazonaws.com/api/auth/me
   ```

2. **Test Custom Domain** (if configured):
   ```bash
   curl https://shurl.griddo.io/api/auth/me
   ```

3. **Test URL Redirect**:
   ```bash
   curl -I https://shurl.griddo.io/<short_code>
   ```

## Monitoring & Logs

### CloudWatch Logs

View Lambda logs:
```bash
aws logs tail /aws/lambda/shurly-api --follow
```

### Key Metrics to Monitor

- **Lambda Invocations**: Track API requests
- **Lambda Duration**: Monitor cold start times
- **Lambda Errors**: Track 4xx/5xx responses
- **RDS Connections**: Monitor database connection pool
- **API Gateway 4xx/5xx**: Track client/server errors

## Cost Estimation

Based on 100-150 URLs/month (~5,000 requests/month):

- **Lambda**: ~$0.20/month (first 1M requests free)
- **API Gateway**: ~$0.50/month (first 1M requests $1.00)
- **RDS t4g.micro**: ~$12-15/month
- **S3 + CloudFront**: ~$1-2/month
- **Route 53**: ~$1/month (hosted zone)

**Total**: ~$15-20/month

## Troubleshooting

### Lambda Cold Starts

- **Symptom**: First request takes 2-3 seconds
- **Solution**: Consider provisioned concurrency for critical paths (adds cost)

### Database Connection Issues

- **Symptom**: "Too many connections" error
- **Solution**: Reduce `DB_POOL_SIZE` to 2-3 for Lambda

### CORS Errors

- **Symptom**: Browser shows CORS error
- **Solution**: Ensure `CORS_ORIGINS` environment variable includes frontend domain

### VPC Timeout

- **Symptom**: Lambda times out connecting to RDS
- **Solution**: Verify Lambda and RDS are in same VPC, check security groups

## Updating the Lambda Function

To deploy code changes:

```bash
# Rebuild package
./build_lambda.sh  # Or manual steps from Step 2

# Update function code
aws lambda update-function-code \
  --function-name shurly-api \
  --zip-file fileb://shurly-lambda.zip
```

## Rollback Procedure

1. **List Previous Versions**:
   ```bash
   aws lambda list-versions-by-function --function-name shurly-api
   ```

2. **Update Alias to Previous Version**:
   ```bash
   aws lambda update-alias \
     --function-name shurly-api \
     --name prod \
     --function-version <PREVIOUS_VERSION>
   ```

## Next Steps

See [ROADMAP.md](ROADMAP.md) for:
- Phase 4.2: Infrastructure as Code (AWS SAM/CDK)
- Phase 4.3: CI/CD Pipeline
- **Phase 5: MCP Server over Streamable HTTP** (expose the API as a Model Context Protocol server for Claude Code / Claude Desktop; pilot for "MCP-as-product")
- Phase 6: Testing & Optimization
- Phase 7: Documentation & Handoff
