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

# ─── 2. Build + push for linux/arm64 ────────────────────────────────────────
echo ""
echo -e "${YELLOW}2. Build (linux/arm64) + push${NC}"
echo "   Image: $IMAGE_URI"

aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin "$ECR_URI" >/dev/null

# buildx with --push avoids loading the manifest into the local Docker daemon
# (which can get confused on multi-arch). Requires the buildx builder to
# support linux/arm64 — on Apple Silicon hosts it's native; on x86 hosts the
# Docker driver has to use QEMU emulation but still works for one platform.
docker buildx build \
    --platform linux/arm64 \
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

# Build the env array as a JSON list. Sensible defaults filled here; override
# any of them by exporting before running this script.
read -r -d '' CONTAINER_JSON <<EOF || true
{
    "image": "${IMAGE_URI}",
    "containerPort": 8000,
    "environment": [
        {"name": "DB_HOST",                "value": "${DB_HOST}"},
        {"name": "DB_PORT",                "value": "${DB_PORT:-5432}"},
        {"name": "DB_USER",                "value": "${DB_USER:-shurly}"},
        {"name": "DB_PASSWORD",            "value": "${DB_PASSWORD}"},
        {"name": "DB_NAME",                "value": "${DB_NAME:-shurly}"},
        {"name": "DB_SSL_MODE",            "value": "${DB_SSL_MODE:-require}"},
        {"name": "JWT_SECRET_KEY",         "value": "${JWT_SECRET_KEY}"},
        {"name": "JWT_ALGORITHM",          "value": "${JWT_ALGORITHM:-HS256}"},
        {"name": "JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "value": "${JWT_ACCESS_TOKEN_EXPIRE_MINUTES:-10080}"},
        {"name": "API_TITLE",              "value": "Shurly API"},
        {"name": "API_VERSION",            "value": "0.1.0"},
        {"name": "CORS_ORIGINS",           "value": "${CORS_ORIGINS:-[\"https://shurl.griddo.io\"]}"},
        {"name": "ANONYMIZE_REMOTE_ADDR",  "value": "${ANONYMIZE_REMOTE_ADDR:-true}"},
        {"name": "TRUSTED_PROXIES",        "value": "${TRUSTED_PROXIES:-[\"172.31.0.0/16\"]}"},
        {"name": "DISABLE_TRACK_PARAM",    "value": "${DISABLE_TRACK_PARAM:-nostat}"},
        {"name": "SHORT_URL_MODE",         "value": "${SHORT_URL_MODE:-loose}"},
        {"name": "DEFAULT_DOMAIN",         "value": "${DEFAULT_DOMAIN:-s.griddo.io}"},
        {"name": "REDIRECT_STATUS_CODE",   "value": "${REDIRECT_STATUS_CODE:-302}"},
        {"name": "REDIRECT_CACHE_LIFETIME","value": "${REDIRECT_CACHE_LIFETIME:-0}"}
    ]
}
EOF

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
