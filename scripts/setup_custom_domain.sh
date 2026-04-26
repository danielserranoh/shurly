#!/bin/bash
# Wire s.griddo.io to the ECS Express ALB.
#
# Mirrors Shlink Phase 6. Three manual steps Express Mode does NOT do for
# custom domains:
#
#   1. Add the ACM cert to the ALB's HTTPS listener.
#   2. Create a routing rule (priority 12, the next free slot after Shlink's
#      10/11) that matches host-header s.griddo.io and forwards to Shurly's
#      target group.
#   3. Create the Route 53 alias from the griddo-production account.
#
# Prerequisites:
#   * Run AFTER ./scripts/deploy_ecs.sh succeeds and the service is healthy.
#   * Run AFTER ACM cert for s.griddo.io is requested AND validated.
#   * Two profiles configured locally:
#       - griddo-main          (service account, eu-south-2)
#       - griddo-production    (DNS account, global Route 53)
#
# Usage:
#   ./scripts/setup_custom_domain.sh
#
# Override the priority if 12 is somehow taken:
#   RULE_PRIORITY=13 ./scripts/setup_custom_domain.sh

set -euo pipefail

REGION="${REGION:-eu-south-2}"
DOMAIN="${DOMAIN:-s.griddo.io}"
SERVICE_NAME="${SERVICE_NAME:-shurly-api}"
RULE_PRIORITY="${RULE_PRIORITY:-12}"
PROFILE_MAIN="${PROFILE_MAIN:-griddo-main}"
PROFILE_DNS="${PROFILE_DNS:-griddo-production}"
GRIDDO_IO_ZONE_ID="${GRIDDO_IO_ZONE_ID:-Z0999097TJGECCBKJOY1}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}Custom domain setup for $DOMAIN${NC}"
echo ""

# ─── 0. ACM certificate ─────────────────────────────────────────────────────
# Find a validated cert that matches the domain. If none exists or it's not
# yet validated, exit with a clear message — we don't want to silently create
# a rule that points to an empty target.
echo -e "${YELLOW}0. Locating validated ACM certificate for $DOMAIN${NC}"
CERT_ARN=$(aws acm list-certificates --region "$REGION" --profile "$PROFILE_MAIN" \
    --certificate-statuses ISSUED \
    --query "CertificateSummaryList[?DomainName=='$DOMAIN'].CertificateArn | [0]" \
    --output text)

if [ -z "$CERT_ARN" ] || [ "$CERT_ARN" = "None" ]; then
    echo -e "${RED}No ISSUED certificate found for $DOMAIN.${NC}"
    echo ""
    echo "Request one with:"
    echo "  aws acm request-certificate --region $REGION --profile $PROFILE_MAIN \\"
    echo "      --domain-name $DOMAIN --validation-method DNS"
    echo ""
    echo "Then validate by writing the CNAME from describe-certificate to Route 53:"
    echo "  aws route53 change-resource-record-sets --hosted-zone-id $GRIDDO_IO_ZONE_ID \\"
    echo "      --profile $PROFILE_DNS --change-batch file://validation.json"
    echo ""
    echo "Wait for validation:"
    echo "  aws acm wait certificate-validated --region $REGION --profile $PROFILE_MAIN \\"
    echo "      --certificate-arn <ARN>"
    exit 1
fi
echo -e "${GREEN}✓ Cert: $CERT_ARN${NC}"

# ─── 1. ALB + listener + Shurly target group ────────────────────────────────
echo ""
echo -e "${YELLOW}1. Locating shared Express Mode ALB${NC}"
ALB_ARN=$(aws elbv2 describe-load-balancers --region "$REGION" --profile "$PROFILE_MAIN" \
    --query "LoadBalancers[?contains(LoadBalancerName, 'express')].LoadBalancerArn | [0]" \
    --output text)

if [ -z "$ALB_ARN" ] || [ "$ALB_ARN" = "None" ]; then
    echo -e "${RED}No Express Mode ALB found in $REGION. Did the ECS deploy finish?${NC}"
    exit 1
fi

ALB_DNS=$(aws elbv2 describe-load-balancers --region "$REGION" --profile "$PROFILE_MAIN" \
    --load-balancer-arns "$ALB_ARN" \
    --query "LoadBalancers[0].DNSName" --output text)
ALB_ZONE=$(aws elbv2 describe-load-balancers --region "$REGION" --profile "$PROFILE_MAIN" \
    --load-balancer-arns "$ALB_ARN" \
    --query "LoadBalancers[0].CanonicalHostedZoneId" --output text)
LISTENER_ARN=$(aws elbv2 describe-listeners --region "$REGION" --profile "$PROFILE_MAIN" \
    --load-balancer-arn "$ALB_ARN" \
    --query "Listeners[?Port==\`443\`].ListenerArn | [0]" --output text)

echo -e "${GREEN}✓ ALB DNS: $ALB_DNS${NC}"
echo -e "${GREEN}✓ Listener (443): $LISTENER_ARN${NC}"

# Find Shurly's active target group. Express Mode uses two target groups for
# blue/green and routes traffic via weighted forwarding; we want the one
# currently receiving 100% of the weight in the auto-generated rule.
SHURLY_TG_ARN=""
EXPRESS_PRIORITIES=$(aws elbv2 describe-rules --region "$REGION" --profile "$PROFILE_MAIN" \
    --listener-arn "$LISTENER_ARN" \
    --query "Rules[?Priority!='default'].Priority" --output text)

for PRI in $EXPRESS_PRIORITIES; do
    # The rules Express Mode creates carry an Action with ForwardConfig and
    # multiple TargetGroups (active + standby). The "active" TG is the one
    # with Weight=100; the standby has Weight=0.
    HOSTS=$(aws elbv2 describe-rules --region "$REGION" --profile "$PROFILE_MAIN" \
        --listener-arn "$LISTENER_ARN" \
        --query "Rules[?Priority=='$PRI'].Conditions[?Field=='host-header'].Values[]" \
        --output text 2>/dev/null || true)
    # Match the auto-generated host: <service>.ecs.<region>.on.aws
    if echo "$HOSTS" | grep -q "${SERVICE_NAME}\."; then
        SHURLY_TG_ARN=$(aws elbv2 describe-rules --region "$REGION" --profile "$PROFILE_MAIN" \
            --listener-arn "$LISTENER_ARN" \
            --query "Rules[?Priority=='$PRI'].Actions[0].ForwardConfig.TargetGroups[?Weight==\`100\`].TargetGroupArn | [0][0]" \
            --output text)
        SHURLY_EXPRESS_PRIORITY="$PRI"
        break
    fi
done

if [ -z "$SHURLY_TG_ARN" ] || [ "$SHURLY_TG_ARN" = "None" ]; then
    echo -e "${RED}Could not locate Shurly's active target group.${NC}"
    echo "Check that ./scripts/deploy_ecs.sh completed and the service is healthy."
    exit 1
fi
echo -e "${GREEN}✓ Active TG: $SHURLY_TG_ARN${NC}"
echo -e "${GREEN}✓ Express Mode priority: $SHURLY_EXPRESS_PRIORITY${NC}"
echo -e "${YELLOW}  → Add this entry to ecs-alb-rule-sync's RULE_SYNC_MAP:${NC}"
echo -e "${YELLOW}    \"$SHURLY_EXPRESS_PRIORITY\": \"$RULE_PRIORITY\",${NC}"

# ─── 2. Add cert to listener ────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}2. Attach cert to HTTPS listener (idempotent)${NC}"
aws elbv2 add-listener-certificates --region "$REGION" --profile "$PROFILE_MAIN" \
    --listener-arn "$LISTENER_ARN" \
    --certificates "CertificateArn=$CERT_ARN" >/dev/null
echo -e "${GREEN}✓ Cert attached${NC}"

# ─── 3. Create / update routing rule ───────────────────────────────────────
echo ""
echo -e "${YELLOW}3. Routing rule at priority $RULE_PRIORITY${NC}"
EXISTING_RULE_ARN=$(aws elbv2 describe-rules --region "$REGION" --profile "$PROFILE_MAIN" \
    --listener-arn "$LISTENER_ARN" \
    --query "Rules[?Priority=='$RULE_PRIORITY'].RuleArn | [0]" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_RULE_ARN" ] && [ "$EXISTING_RULE_ARN" != "None" ]; then
    echo -e "${YELLOW}!  Rule at priority $RULE_PRIORITY already exists. Updating to forward to Shurly's TG.${NC}"
    aws elbv2 modify-rule --region "$REGION" --profile "$PROFILE_MAIN" \
        --rule-arn "$EXISTING_RULE_ARN" \
        --conditions "Field=host-header,Values=$DOMAIN" \
        --actions "Type=forward,ForwardConfig={TargetGroups=[{TargetGroupArn=$SHURLY_TG_ARN,Weight=100}]}" >/dev/null
else
    aws elbv2 create-rule --region "$REGION" --profile "$PROFILE_MAIN" \
        --listener-arn "$LISTENER_ARN" \
        --priority "$RULE_PRIORITY" \
        --conditions "Field=host-header,Values=$DOMAIN" \
        --actions "Type=forward,ForwardConfig={TargetGroups=[{TargetGroupArn=$SHURLY_TG_ARN,Weight=100}]}" >/dev/null
    echo -e "${GREEN}✓ Created rule at priority $RULE_PRIORITY${NC}"
fi

# ─── 4. Route 53 alias from griddo-production ──────────────────────────────
echo ""
echo -e "${YELLOW}4. Route 53 A-alias from $PROFILE_DNS${NC}"
CHANGE_BATCH=$(cat <<EOF
{
    "Changes": [{
        "Action": "UPSERT",
        "ResourceRecordSet": {
            "Name": "$DOMAIN",
            "Type": "A",
            "AliasTarget": {
                "HostedZoneId": "$ALB_ZONE",
                "DNSName": "$ALB_DNS",
                "EvaluateTargetHealth": true
            }
        }
    }]
}
EOF
)

aws route53 change-resource-record-sets --profile "$PROFILE_DNS" \
    --hosted-zone-id "$GRIDDO_IO_ZONE_ID" \
    --change-batch "$CHANGE_BATCH" >/dev/null

echo -e "${GREEN}✓ DNS alias UPSERTed${NC}"

# ─── Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Custom domain wired.${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Verify in ~30s (DNS propagation):"
echo "  dig $DOMAIN +short"
echo "  curl https://$DOMAIN/api/v1/health"
echo ""
echo "Don't forget to update the ecs-alb-rule-sync Lambda's RULE_SYNC_MAP:"
echo "  Express priority $SHURLY_EXPRESS_PRIORITY → custom priority $RULE_PRIORITY"
echo ""
