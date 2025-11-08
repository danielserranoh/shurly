#!/bin/bash
# Test connection to RDS PostgreSQL database

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ $# -lt 1 ]; then
    echo "Usage: ./scripts/test_db_connection.sh <db_endpoint> [db_password]"
    echo ""
    echo "Example:"
    echo "  ./scripts/test_db_connection.sh shurly-dev-db.xxx.rds.amazonaws.com"
    exit 1
fi

DB_ENDPOINT=$1
DB_NAME="${2:-shurly}"
DB_USER="${3:-postgres}"

echo -e "${YELLOW}Testing connection to RDS PostgreSQL...${NC}"
echo ""
echo "  Endpoint: $DB_ENDPOINT"
echo "  Database: $DB_NAME"
echo "  Username: $DB_USER"
echo ""

# Prompt for password if not provided
if [ $# -lt 4 ]; then
    read -sp "Enter database password: " DB_PASSWORD
    echo ""
else
    DB_PASSWORD=$4
fi

echo ""
echo -e "${YELLOW}Test 1: Network connectivity (port 5432)...${NC}"

# Test if port 5432 is reachable
if command -v nc &> /dev/null; then
    if nc -zv -w5 $DB_ENDPOINT 5432 2>&1 | grep -q succeeded; then
        echo -e "${GREEN}✓ Port 5432 is reachable${NC}"
    else
        echo -e "${RED}✗ Cannot reach port 5432${NC}"
        echo "  Check security group rules"
        exit 1
    fi
elif command -v telnet &> /dev/null; then
    timeout 5 telnet $DB_ENDPOINT 5432 &> /dev/null && echo -e "${GREEN}✓ Port 5432 is reachable${NC}" || echo -e "${RED}✗ Cannot reach port 5432${NC}"
else
    echo -e "${YELLOW}⚠ nc/telnet not found, skipping port check${NC}"
fi

echo ""
echo -e "${YELLOW}Test 2: PostgreSQL connection...${NC}"

# Test connection with psql if available
if command -v psql &> /dev/null; then
    PGPASSWORD=$DB_PASSWORD psql \
        -h $DB_ENDPOINT \
        -p 5432 \
        -U $DB_USER \
        -d $DB_NAME \
        -c "SELECT version();" \
        2>&1 | grep -q PostgreSQL && \
        echo -e "${GREEN}✓ Successfully connected to PostgreSQL${NC}" || \
        { echo -e "${RED}✗ Connection failed${NC}"; exit 1; }
else
    echo -e "${YELLOW}⚠ psql not found${NC}"
    echo "  Using Python test instead..."

    # Test with Python
    python3 << EOF
import sys
try:
    import psycopg2
    conn = psycopg2.connect(
        host="$DB_ENDPOINT",
        port=5432,
        database="$DB_NAME",
        user="$DB_USER",
        password="$DB_PASSWORD",
        sslmode="require",
        connect_timeout=10
    )
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"\033[0;32m✓ Successfully connected to PostgreSQL\033[0m")
    print(f"  Version: {version.split(',')[0]}")
    cur.close()
    conn.close()
except ImportError:
    print("\033[0;31m✗ psycopg2 not installed\033[0m")
    print("  Install with: pip install psycopg2-binary")
    sys.exit(1)
except Exception as e:
    print(f"\033[0;31m✗ Connection failed: {e}\033[0m")
    sys.exit(1)
EOF
fi

echo ""
echo -e "${YELLOW}Test 3: Database exists...${NC}"

if command -v psql &> /dev/null; then
    PGPASSWORD=$DB_PASSWORD psql \
        -h $DB_ENDPOINT \
        -p 5432 \
        -U $DB_USER \
        -d postgres \
        -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" \
        2>&1 | grep -q 1 && \
        echo -e "${GREEN}✓ Database '$DB_NAME' exists${NC}" || \
        { echo -e "${RED}✗ Database '$DB_NAME' not found${NC}"; exit 1; }
else
    python3 << EOF
import sys
try:
    import psycopg2
    conn = psycopg2.connect(
        host="$DB_ENDPOINT",
        port=5432,
        database="postgres",
        user="$DB_USER",
        password="$DB_PASSWORD",
        sslmode="require"
    )
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", ("$DB_NAME",))
    if cur.fetchone():
        print("\033[0;32m✓ Database '$DB_NAME' exists\033[0m")
    else:
        print("\033[0;31m✗ Database '$DB_NAME' not found\033[0m")
        sys.exit(1)
    cur.close()
    conn.close()
except Exception as e:
    print(f"\033[0;31m✗ Error: {e}\033[0m")
    sys.exit(1)
EOF
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}All tests passed!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Connection string:"
echo "  postgresql://$DB_USER:<password>@$DB_ENDPOINT:5432/$DB_NAME"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Initialize database: python scripts/init_database.py $DB_ENDPOINT <password>"
echo "  2. Deploy Lambda: sam deploy --guided"
echo ""
