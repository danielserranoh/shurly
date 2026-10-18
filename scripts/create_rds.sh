#!/bin/bash
# Create RDS PostgreSQL instance for Shurly in the griddo-main account.
#
# Mirrors the Shlink deploy guide (Phase 2) with Shurly-specific names. Key
# departures from naive defaults:
#
#   * No --engine-version pin. AWS picks the latest stable Postgres available
#     in eu-south-2; pinning bit us once with a version that wasn't available.
#   * --no-publicly-accessible. The DB only needs to be reachable from
#     Fargate tasks inside the VPC; opening 5432 to the internet would be a
#     gift to bot scanners.
#   * Security group ingress restricted to the default VPC CIDR (172.31.0.0/16),
#     not 0.0.0.0/0. Fargate tasks live in this CIDR.
#   * Reuses the shlink-db-subnets subnet group when present (we share the
#     default VPC across services). Falls back to creating a fresh
#     shurly-db-subnets group if not.
#   * The master password is generated only when the instance is created, and goes
#     straight to SSM Parameter Store as a SecureString, ${SSM_PREFIX}/DB_PASSWORD
#     (default /shurly/production/DB_PASSWORD), where deploy_ecs.sh and the container
#     read it. It is never printed, and reaches put-parameter through a 0600 file,
#     removed at once, not its command line (DEPLOYMENT.md § Secrets, "Writing a
#     value"); create-db-instance still takes it as --master-user-password. A re-run
#     against an existing instance generates and writes nothing.
#
# Requires jq.
#
# Run with the griddo-main SSO profile:
#   AWS_PROFILE=griddo-main ./scripts/create_rds.sh

set -euo pipefail

REGION="${REGION:-eu-south-2}"
DB_INSTANCE_ID="${DB_INSTANCE_ID:-shurly-db}"
DB_INSTANCE_CLASS="db.t4g.micro"
DB_ENGINE="postgres"
DB_NAME="shurly"
DB_USER="shurly"
DB_ALLOCATED_STORAGE="20"
DB_BACKUP_RETENTION="7"
DB_SUBNET_GROUP_NAME="${DB_SUBNET_GROUP_NAME:-shurly-db-subnets}"
DB_SG_NAME="${DB_SG_NAME:-shurly-db-sg}"
SSM_PREFIX="${SSM_PREFIX:-/shurly/production}"
SSM_PREFIX="/${SSM_PREFIX#/}"
SSM_PREFIX="${SSM_PREFIX%/}"
DB_PASSWORD_PARAMETER="${SSM_PREFIX}/DB_PASSWORD"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Shurly RDS PostgreSQL setup (region: $REGION)${NC}"
echo ""

if ! command -v jq >/dev/null 2>&1; then
    echo -e "${RED}jq is required (brew install jq / apt-get install -y jq)${NC}"
    exit 1
fi

# The parameter's JSON, holding the password, lives in a 0700 directory for the
# few moments put-parameter needs it. The trap removes it on any exit.
SECRET_DIR=""
remove_secret_dir() {
    if [ -n "$SECRET_DIR" ]; then
        rm -f "${SECRET_DIR:?}/parameter.json"
        rmdir "${SECRET_DIR:?}" 2>/dev/null || true
        SECRET_DIR=""
    fi
}
trap remove_secret_dir EXIT

# Write $DB_PASSWORD to $DB_PASSWORD_PARAMETER (SecureString, overwriting), the way
# DEPLOYMENT.md § Secrets' put_secret does: through a 0600 file passed with
# --cli-input-json, so the value is on no command line. Prints the new version only.
store_db_password() {
    local version
    SECRET_DIR=$(mktemp -d)   # mode 0700
    ( umask 077
      printf '%s\n' "$DB_PASSWORD" | jq -Rn --arg name "$DB_PASSWORD_PARAMETER" \
          '{Name: $name, Type: "SecureString", Overwrite: true, Value: input}' \
          > "${SECRET_DIR:?}/parameter.json" )
    version=$(aws ssm put-parameter --region "$REGION" \
        --cli-input-json "file://${SECRET_DIR:?}/parameter.json" \
        --query Version --output text)
    shred -u "${SECRET_DIR:?}/parameter.json" 2>/dev/null || true   # macOS has no shred
    remove_secret_dir
    echo -e "${GREEN}✓ Stored the master password in SSM $DB_PASSWORD_PARAMETER (SecureString, version $version)${NC}"
}

# ─── 1. Default VPC ─────────────────────────────────────────────────────────
echo -e "${YELLOW}1. Locating default VPC...${NC}"
VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" \
    --filters "Name=isDefault,Values=true" \
    --query "Vpcs[0].VpcId" --output text)

if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ]; then
    echo -e "${RED}No default VPC in $REGION. Run 'aws ec2 create-default-vpc --region $REGION' or pick a different region.${NC}"
    exit 1
fi
echo -e "${GREEN}✓ VPC: $VPC_ID${NC}"

VPC_CIDR=$(aws ec2 describe-vpcs --region "$REGION" \
    --vpc-ids "$VPC_ID" \
    --query "Vpcs[0].CidrBlock" --output text)
echo -e "${GREEN}✓ VPC CIDR: $VPC_CIDR${NC}"

# ─── 2. Subnet group ────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}2. Subnet group...${NC}"
if aws rds describe-db-subnet-groups --region "$REGION" \
    --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Reusing existing subnet group $DB_SUBNET_GROUP_NAME${NC}"
elif aws rds describe-db-subnet-groups --region "$REGION" \
    --db-subnet-group-name "shlink-db-subnets" >/dev/null 2>&1; then
    DB_SUBNET_GROUP_NAME="shlink-db-subnets"
    echo -e "${GREEN}✓ Reusing shlink-db-subnets (same VPC)${NC}"
else
    SUBNET_IDS=$(aws ec2 describe-subnets --region "$REGION" \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --query "Subnets[*].SubnetId" --output text)
    aws rds create-db-subnet-group --region "$REGION" \
        --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" \
        --db-subnet-group-description "Subnets for Shurly PostgreSQL" \
        --subnet-ids $SUBNET_IDS >/dev/null
    echo -e "${GREEN}✓ Created subnet group $DB_SUBNET_GROUP_NAME${NC}"
fi

# ─── 3. Security group ──────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}3. Security group...${NC}"
SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=group-name,Values=$DB_SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
    --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || true)

if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
    SG_ID=$(aws ec2 create-security-group --region "$REGION" \
        --group-name "$DB_SG_NAME" \
        --description "Security group for Shurly PostgreSQL - VPC-only ingress" \
        --vpc-id "$VPC_ID" \
        --query "GroupId" --output text)
    echo -e "${GREEN}✓ Created SG: $SG_ID${NC}"
else
    echo -e "${GREEN}✓ Reusing SG: $SG_ID${NC}"
fi

# Idempotent ingress rule: VPC-only on 5432
aws ec2 authorize-security-group-ingress --region "$REGION" \
    --group-id "$SG_ID" \
    --protocol tcp --port 5432 \
    --cidr "$VPC_CIDR" 2>/dev/null \
    && echo -e "${GREEN}✓ Allowed 5432 from $VPC_CIDR${NC}" \
    || echo -e "${GREEN}✓ Ingress rule already present${NC}"

# ─── 4. Create the instance ─────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}4. Creating RDS instance $DB_INSTANCE_ID (no engine-version pin)...${NC}"
echo "   This takes ~5-10 minutes."

if aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" >/dev/null 2>&1; then
    INSTANCE_CREATED=false
    echo -e "${YELLOW}!  $DB_INSTANCE_ID already exists — skipping creation. Continuing to wait for availability.${NC}"
    echo -e "${YELLOW}   No password generated, nothing written to SSM: $DB_PASSWORD_PARAMETER is left as it is.${NC}"
else
    INSTANCE_CREATED=true
    # A strong password, alphanumeric (no quoting surprises in a connection URL).
    # Stored before the instance is created: if the store fails, nothing is created
    # with a password nobody has; if the create fails, a re-run overwrites it.
    DB_PASSWORD="$(openssl rand -base64 48 | tr -d '/+=\n' | head -c 32)"
    store_db_password
    aws rds create-db-instance --region "$REGION" \
        --db-instance-identifier "$DB_INSTANCE_ID" \
        --db-instance-class "$DB_INSTANCE_CLASS" \
        --engine "$DB_ENGINE" \
        --master-username "$DB_USER" \
        --master-user-password "$DB_PASSWORD" \
        --allocated-storage "$DB_ALLOCATED_STORAGE" \
        --storage-type gp3 \
        --db-name "$DB_NAME" \
        --db-subnet-group-name "$DB_SUBNET_GROUP_NAME" \
        --vpc-security-group-ids "$SG_ID" \
        --no-publicly-accessible \
        --backup-retention-period "$DB_BACKUP_RETENTION" \
        --no-multi-az \
        --storage-encrypted \
        --tags "Key=Project,Value=Shurly" "Key=ManagedBy,Value=create_rds.sh" >/dev/null
    unset DB_PASSWORD
    echo -e "${GREEN}✓ Creation initiated${NC}"
fi

aws rds wait db-instance-available --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID"

DB_ENDPOINT=$(aws rds describe-db-instances --region "$REGION" \
    --db-instance-identifier "$DB_INSTANCE_ID" \
    --query "DBInstances[0].Endpoint.Address" --output text)

# ─── Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}RDS ready.${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  DB_HOST     = $DB_ENDPOINT"
echo "  DB_PORT     = 5432"
echo "  DB_NAME     = $DB_NAME"
echo "  DB_USER     = $DB_USER"
if [ "$INSTANCE_CREATED" = true ]; then
    echo "  DB_PASSWORD = in SSM $DB_PASSWORD_PARAMETER (SecureString, never printed)"
else
    echo "  DB_PASSWORD = unchanged: the instance existed, so none was generated or written"
fi
echo "  DB_SG       = $SG_ID"
echo ""
echo "Next steps:"
echo "  • Write the other secrets under $SSM_PREFIX/ (DEPLOYMENT.md § Secrets in Parameter Store)."
echo "    deploy_ecs.sh checks all five exist; the container reads them through its \`secrets\`."
echo "  • Put DB_HOST in .env, then run ./scripts/deploy_ecs.sh to build and deploy the container."
echo ""
