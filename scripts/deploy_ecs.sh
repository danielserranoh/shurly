#!/bin/bash
# Build the Shurly container image, push it to ECR, and create or update the
# ECS Express service in eu-south-2.
#
# Mirrors Shlink's deploy guide Phase 5 with Shurly-specific values.
#
# Run with the griddo-main SSO profile:
#   AWS_PROFILE=griddo-main ./scripts/deploy_ecs.sh
#
# Required env (or .env file in cwd):
#   DB_HOST, DB_PASSWORD, JWT_SECRET_KEY, CORS_ORIGINS
#
# Optional env (sensible defaults below):
#   IMAGE_TAG (default: short git sha)
#   SERVICE_NAME (default: shurly-api)
#   ECR_REPO (default: shurly-api)
#   REGION (default: eu-south-2)

set -euo pipefail

REGION="${REGION:-eu-south-2}"
SERVICE_NAME="${SERVICE_NAME:-shurly-api}"
ECR_REPO="${ECR_REPO:-shurly-api}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo "manual-$(date +%s)")}"
CLUSTER="${CLUSTER:-default}"

# Load .env file if present so the user doesn't need to export everything by
# hand. Variables already set in the shell win — that's the standard precedence.
if [ -f .env ]; then
    set -a; source .env; set +a
fi

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ─── Pre-flight ─────────────────────────────────────────────────────────────
echo -e "${YELLOW}Pre-flight checks${NC}"
for var in DB_HOST DB_PASSWORD JWT_SECRET_KEY; do
    if [ -z "${!var:-}" ]; then
        echo -e "${RED}Missing required env var: $var${NC}"
        echo "Set it in your shell or in a .env file in the project root."
        exit 1
    fi
done

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo -e "${GREEN}✓ AWS account: $AWS_ACCOUNT_ID${NC}"
echo -e "${GREEN}✓ Region:      $REGION${NC}"
echo -e "${GREEN}✓ Image tag:   $IMAGE_TAG${NC}"

# ─── 1. ECR repository ──────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}1. ECR repository${NC}"
if ! aws ecr describe-repositories --region "$REGION" \
    --repository-names "$ECR_REPO" >/dev/null 2>&1; then
    aws ecr create-repository --region "$REGION" \
        --repository-name "$ECR_REPO" \
        --image-scanning-configuration scanOnPush=true \
        --image-tag-mutability IMMUTABLE >/dev/null
    echo -e "${GREEN}✓ Created repository $ECR_REPO${NC}"
else
    echo -e "${GREEN}✓ Repository $ECR_REPO exists${NC}"
fi

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
IMAGE_URI="${ECR_URI}:${IMAGE_TAG}"

# ─── 2. Build + push as a multi-arch manifest (amd64 + arm64) ──────────────
# ECS Express Mode runs on x86_64 Fargate by default; an arm64-only image
# fails to pull with "Manifest does not contain descriptor matching platform
# 'linux/amd64'". Building both architectures keeps the manifest portable so
# the same image works on either Fargate runtime, and on developer Macs
# (Apple Silicon = arm64) for local docker run testing.
echo ""
echo -e "${YELLOW}2. Build (linux/amd64,linux/arm64) + push${NC}"
echo "   Image: $IMAGE_URI"

aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin "$ECR_URI" >/dev/null

# buildx --push uploads the multi-arch manifest directly to ECR. ECR honors
# the manifest list and Fargate picks the matching architecture at pull time.
# On x86 hosts the arm64 layer is built via QEMU emulation, slower but works.
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag "$IMAGE_URI" \
    --push \
    --progress=plain \
    .

echo -e "${GREEN}✓ Pushed $IMAGE_URI${NC}"

# ─── 3. Service create or update ────────────────────────────────────────────
echo ""
echo -e "${YELLOW}3. ECS Express service${NC}"

EXEC_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole"
INFRA_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsInfrastructureRoleForExpressServices"

# Build the container JSON via jq. Doing this with a bash heredoc previously
# mangled values containing quotes (notably CORS_ORIGINS='["https://..."]'
# arrived at the task as [https://...] with quotes stripped, breaking
# Pydantic's JSON decode and crashloop'ing the container). jq's --arg takes
# raw shell strings and emits valid JSON, sidestepping the entire quoting
# mess. Requires jq (already a dependency on macOS via brew, install on
# Linux runners with apt-get install -y jq).
if ! command -v jq >/dev/null 2>&1; then
    echo -e "${RED}jq is required (brew install jq / apt-get install -y jq)${NC}"
    exit 1
fi

CONTAINER_JSON=$(jq -n \
    --arg image          "$IMAGE_URI" \
    --argjson port       8000 \
    --arg db_host        "$DB_HOST" \
    --arg db_port        "${DB_PORT:-5432}" \
    --arg db_user        "${DB_USER:-shurly}" \
    --arg db_password    "$DB_PASSWORD" \
    --arg db_name        "${DB_NAME:-shurly}" \
    --arg db_ssl_mode    "${DB_SSL_MODE:-require}" \
    --arg jwt_secret     "$JWT_SECRET_KEY" \
    --arg jwt_algorithm  "${JWT_ALGORITHM:-HS256}" \
    --arg jwt_expire     "${JWT_ACCESS_TOKEN_EXPIRE_MINUTES:-10080}" \
    --arg api_title      "Shurly API" \
    --arg api_version    "0.1.0" \
    --arg cors_origins   "${CORS_ORIGINS:-[\"https://shurl.griddo.io\"]}" \
    --arg anonymize      "${ANONYMIZE_REMOTE_ADDR:-true}" \
    --arg trusted_proxies "${TRUSTED_PROXIES:-[\"172.31.0.0/16\"]}" \
    --arg disable_track  "${DISABLE_TRACK_PARAM:-nostat}" \
    --arg short_url_mode "${SHORT_URL_MODE:-loose}" \
    --arg default_domain "${DEFAULT_DOMAIN:-s.griddo.io}" \
    --arg redirect_status "${REDIRECT_STATUS_CODE:-302}" \
    --arg redirect_cache "${REDIRECT_CACHE_LIFETIME:-0}" \
    '{
        image: $image,
        containerPort: $port,
        environment: [
            {name: "DB_HOST",                            value: $db_host},
            {name: "DB_PORT",                            value: $db_port},
            {name: "DB_USER",                            value: $db_user},
            {name: "DB_PASSWORD",                        value: $db_password},
            {name: "DB_NAME",                            value: $db_name},
            {name: "DB_SSL_MODE",                        value: $db_ssl_mode},
            {name: "JWT_SECRET_KEY",                     value: $jwt_secret},
            {name: "JWT_ALGORITHM",                      value: $jwt_algorithm},
            {name: "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",    value: $jwt_expire},
            {name: "API_TITLE",                          value: $api_title},
            {name: "API_VERSION",                        value: $api_version},
            {name: "CORS_ORIGINS",                       value: $cors_origins},
            {name: "ANONYMIZE_REMOTE_ADDR",              value: $anonymize},
            {name: "TRUSTED_PROXIES",                    value: $trusted_proxies},
            {name: "DISABLE_TRACK_PARAM",                value: $disable_track},
            {name: "SHORT_URL_MODE",                     value: $short_url_mode},
            {name: "DEFAULT_DOMAIN",                     value: $default_domain},
            {name: "REDIRECT_STATUS_CODE",               value: $redirect_status},
            {name: "REDIRECT_CACHE_LIFETIME",            value: $redirect_cache}
        ]
    }')

# Optional debug: uncomment to inspect the generated JSON before sending.
# echo "$CONTAINER_JSON" | jq .

# Check whether the service already exists. ECS Express's "describe" command is
# different from regular ECS — we look up the ARN by listing services first.
SERVICE_ARN=$(aws ecs list-services --region "$REGION" --cluster "$CLUSTER" \
    --query "serviceArns[?contains(@, '${SERVICE_NAME}')] | [0]" \
    --output text 2>/dev/null || echo "")

if [ -n "$SERVICE_ARN" ] && [ "$SERVICE_ARN" != "None" ]; then
    # Update path: rolling deploy with the new image. Express Mode handles the
    # blue/green between target groups automatically; the ALB rule sync Lambda
    # follows the active TG (Phase 4.7).
    echo -e "${YELLOW}Service exists — updating to $IMAGE_TAG${NC}"
    aws ecs update-express-gateway-service --region "$REGION" \
        --service-arn "$SERVICE_ARN" \
        --primary-container "$CONTAINER_JSON" >/dev/null
    echo -e "${GREEN}✓ Update started${NC}"
else
    # Create path: first deploy. --monitor-resources can timeout per Shlink
    # lesson #2 — that's fine, we verify with describe-express-gateway-service
    # afterwards.
    echo -e "${YELLOW}Creating new service $SERVICE_NAME${NC}"
    aws ecs create-express-gateway-service --region "$REGION" \
        --service-name "$SERVICE_NAME" \
        --execution-role-arn "$EXEC_ROLE_ARN" \
        --infrastructure-role-arn "$INFRA_ROLE_ARN" \
        --primary-container "$CONTAINER_JSON" \
        --cpu 256 \
        --memory 512 \
        --health-check-path "/api/v1/health" \
        --scaling-target '{"minTaskCount": 1, "maxTaskCount": 2}' \
        --tags "key=Project,value=Shurly" "key=ManagedBy,value=deploy_ecs.sh" \
        || echo -e "${YELLOW}!  create returned non-zero (expected: --monitor-resources may timeout)${NC}"

    echo -e "${YELLOW}Verifying with describe-express-gateway-service...${NC}"
    SERVICE_ARN=$(aws ecs list-services --region "$REGION" --cluster "$CLUSTER" \
        --query "serviceArns[?contains(@, '${SERVICE_NAME}')] | [0]" \
        --output text)
    aws ecs describe-express-gateway-service --region "$REGION" \
        --service-arn "$SERVICE_ARN" \
        --query "service.{status:status,desiredCount:desiredCount,runningCount:runningCount}" \
        --output table
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Deploy initiated.${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Service ARN: $SERVICE_ARN"
echo "  Image:       $IMAGE_URI"
echo ""
echo "Next steps:"
echo "  • Wait ~1-2 min, then probe the auto-generated host:"
echo "      curl https://${SERVICE_NAME}.ecs.${REGION}.on.aws/api/v1/health"
echo "  • Once healthy: ./scripts/setup_custom_domain.sh"
echo ""
