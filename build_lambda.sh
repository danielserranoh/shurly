#!/bin/bash
# Build script for AWS Lambda deployment package

set -e  # Exit on error

echo "Building Shurly Lambda deployment package..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Clean previous build
echo -e "${YELLOW}Cleaning previous build...${NC}"
rm -rf .aws-sam
rm -f shurly-lambda.zip

# Build with SAM
echo -e "${YELLOW}Building with AWS SAM...${NC}"
sam build --use-container

echo -e "${GREEN}✓ Build complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Deploy to AWS:  sam deploy --guided"
echo "  2. Test locally:   sam local start-api"
echo "  3. Invoke locally: sam local invoke ShurlyFunction -e events/test-event.json"
