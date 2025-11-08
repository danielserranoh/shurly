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

## Deployment Steps

### Step 1: Create RDS PostgreSQL Database

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
- Phase 5: Testing & Optimization
- Phase 6: Documentation & Handoff
