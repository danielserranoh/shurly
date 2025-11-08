#!/bin/bash
# Test execution script for Shurly URL Shortener

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Shurly URL Shortener - Test Suite${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Set CORS_ORIGINS environment variable for tests
export CORS_ORIGINS='["http://localhost:4321"]'

# Parse command line arguments
if [ "$1" == "coverage" ]; then
    echo -e "${YELLOW}Running tests with coverage report...${NC}"
    uv run pytest --cov=server --cov-report=html --cov-report=term -v
    echo ""
    echo -e "${GREEN}Coverage report generated in htmlcov/index.html${NC}"
elif [ "$1" == "fast" ]; then
    echo -e "${YELLOW}Running tests (quiet mode)...${NC}"
    uv run pytest -q
elif [ "$1" == "auth" ]; then
    echo -e "${YELLOW}Running authentication tests only...${NC}"
    uv run pytest tests/test_auth.py -v
elif [ "$1" == "urls" ]; then
    echo -e "${YELLOW}Running URL tests only...${NC}"
    uv run pytest tests/test_urls.py -v
elif [ "$1" == "campaigns" ]; then
    echo -e "${YELLOW}Running campaign tests only...${NC}"
    uv run pytest tests/test_campaigns.py -v
elif [ "$1" == "analytics" ]; then
    echo -e "${YELLOW}Running analytics tests only...${NC}"
    uv run pytest tests/test_analytics.py -v
else
    echo -e "${YELLOW}Running all tests...${NC}"
    uv run pytest -v
fi

# Capture exit code
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
else
    echo -e "${RED}✗ Some tests failed${NC}"
fi

exit $EXIT_CODE
