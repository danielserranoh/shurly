#!/bin/bash
# Create RDS PostgreSQL instance for Shurly in eu-west-1
# Simple setup with default VPC and public accessibility

set -e  # Exit on error

# Configuration
REGION="eu-west-1"
DB_INSTANCE_ID="shurly-dev-db"
DB_INSTANCE_CLASS="db.t4g.micro"  # ARM-based, cost-effective
DB_ENGINE="postgres"
DB_ENGINE_VERSION="14.10"
DB_NAME="shurly"
DB_USER="postgres"
DB_ALLOCATED_STORAGE="20"  # GB
DB_BACKUP_RETENTION="7"    # days

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Shurly RDS PostgreSQL Setup${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Prompt for password
read -sp "Enter PostgreSQL master password (min 8 chars): " DB_PASSWORD
echo ""
read -sp "Confirm password: " DB_PASSWORD_CONFIRM
echo ""

if [ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]; then
    echo -e "${RED}Passwords don't match!${NC}"
    exit 1
fi

if [ ${#DB_PASSWORD} -lt 8 ]; then
    echo -e "${RED}Password must be at least 8 characters!${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Region:          $REGION"
echo "  Instance ID:     $DB_INSTANCE_ID"
echo "  Instance Class:  $DB_INSTANCE_CLASS"
echo "  Engine:          $DB_ENGINE $DB_ENGINE_VERSION"
echo "  Database Name:   $DB_NAME"
echo "  Storage:         ${DB_ALLOCATED_STORAGE}GB"
echo ""

read -p "Proceed with RDS creation? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo -e "${YELLOW}Step 1: Getting default VPC...${NC}"

# Get default VPC
VPC_ID=$(aws ec2 describe-vpcs \
    --region $REGION \
    --filters "Name=is-default,Values=true" \
    --query "Vpcs[0].VpcId" \
    --output text)

if [ "$VPC_ID" == "None" ] || [ -z "$VPC_ID" ]; then
    echo -e "${RED}No default VPC found in $REGION!${NC}"
    echo "Please create a VPC or choose a different region."
    exit 1
fi

echo -e "${GREEN}✓ Default VPC: $VPC_ID${NC}"

echo ""
echo -e "${YELLOW}Step 2: Creating security group...${NC}"

# Create security group for RDS
SG_ID=$(aws ec2 create-security-group \
    --region $REGION \
    --group-name shurly-rds-sg \
    --description "Security group for Shurly RDS PostgreSQL" \
    --vpc-id $VPC_ID \
    --query 'GroupId' \
    --output text 2>/dev/null || \
    aws ec2 describe-security-groups \
        --region $REGION \
        --filters "Name=group-name,Values=shurly-rds-sg" \
        --query "SecurityGroups[0].GroupId" \
        --output text)

echo -e "${GREEN}✓ Security Group: $SG_ID${NC}"

echo ""
echo -e "${YELLOW}Step 3: Configuring security group rules...${NC}"

# Allow PostgreSQL from anywhere (we'll lock this down later)
aws ec2 authorize-security-group-ingress \
    --region $REGION \
    --group-id $SG_ID \
    --protocol tcp \
    --port 5432 \
    --cidr 0.0.0.0/0 \
    2>/dev/null || echo "  (Rule already exists)"

echo -e "${GREEN}✓ PostgreSQL port 5432 open${NC}"

echo ""
echo -e "${YELLOW}Step 4: Creating RDS instance (this takes ~5-10 minutes)...${NC}"

# Create RDS instance
aws rds create-db-instance \
    --region $REGION \
    --db-instance-identifier $DB_INSTANCE_ID \
    --db-instance-class $DB_INSTANCE_CLASS \
    --engine $DB_ENGINE \
    --engine-version $DB_ENGINE_VERSION \
    --master-username $DB_USER \
    --master-user-password "$DB_PASSWORD" \
    --allocated-storage $DB_ALLOCATED_STORAGE \
    --storage-type gp3 \
    --db-name $DB_NAME \
    --vpc-security-group-ids $SG_ID \
    --publicly-accessible \
    --backup-retention-period $DB_BACKUP_RETENTION \
    --storage-encrypted \
    --enable-performance-insights \
    --performance-insights-retention-period 7 \
    --deletion-protection \
    --tags Key=Project,Value=Shurly Key=Environment,Value=dev

echo ""
echo -e "${GREEN}✓ RDS instance creation initiated!${NC}"
echo ""
echo -e "${YELLOW}Waiting for RDS instance to become available...${NC}"
echo "(This typically takes 5-10 minutes. Feel free to grab a coffee ☕)"
echo ""

# Wait for instance to be available
aws rds wait db-instance-available \
    --region $REGION \
    --db-instance-identifier $DB_INSTANCE_ID

echo ""
echo -e "${GREEN}✓ RDS instance is now available!${NC}"

# Get endpoint
DB_ENDPOINT=$(aws rds describe-db-instances \
    --region $REGION \
    --db-instance-identifier $DB_INSTANCE_ID \
    --query "DBInstances[0].Endpoint.Address" \
    --output text)

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}RDS PostgreSQL Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Database Details:"
echo "  Endpoint:   $DB_ENDPOINT"
echo "  Port:       5432"
echo "  Database:   $DB_NAME"
echo "  Username:   $DB_USER"
echo "  Password:   (the one you entered)"
echo ""
echo "Connection String:"
echo "  postgresql://$DB_USER:<password>@$DB_ENDPOINT:5432/$DB_NAME"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Test connection: ./scripts/test_db_connection.sh $DB_ENDPOINT"
echo "  2. Save endpoint for SAM deployment"
echo "  3. Deploy Lambda: sam deploy --guided"
echo ""
echo -e "${YELLOW}Important:${NC}"
echo "  - Save your password securely (not stored anywhere)"
echo "  - Endpoint: $DB_ENDPOINT"
echo "  - Cost: ~€10-12/month"
echo ""
