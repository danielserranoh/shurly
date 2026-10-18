#!/usr/bin/env bash
# Phase 6.4 — alerting and monitoring in production: applies the definitions in infra/monitoring/
# (metric filters, alarms, the `shurly` dashboard, the saved Logs Insights queries) and the SNS
# topic that emails the alarms. DEPLOYMENT.md § Error alerting; infra/monitoring/README.md.
#
# Idempotent: the topic is created or found, the email subscribed only when it isn't already
# (pending included), the filters, alarms and dashboard are upserts, and a saved query is updated
# by its id when one with its name exists. A second run creates nothing new.
#
# The definitions name no account-specific resource: the ALB, the service's two target groups
# (Express blue/green), the account and the RDS instance are looked up first, read-only, and any
# lookup that fails stops the script before it writes anything.
#
# A dry run unless --for-real, which needs the region typed back: the dry run does the same
# lookups, then lists what it would create or update, and calls nothing but describe, list, get
# and sts.
#
#   scripts/setup_monitoring.sh [--for-real]
#   scripts/setup_monitoring.sh --test-alarm NAME [--for-real]
#
# --test-alarm NAME sets one alarm of infra/monitoring/alarms.json to ALARM (set-alarm-state),
# so its email arrives, and nothing else; the alarm goes back to OK at its next evaluation, which
# sends the OK email. It's a dry run too without --for-real, which asks for the region the same way.
#
# AWS_PROFILE (griddo-main), AWS_REGION (eu-south-2), ALERT_EMAIL (daniel.serrano@griddo.io),
# LOG_GROUP (/aws/ecs/default/shurly-api-5fdb), SERVICE (shurly-api), DB (shurly-db),
# TOPIC_NAME (shurly-alerts) and APP_HOST (shurly.griddo.io) can be set in the environment.

set -euo pipefail
umask 077

AWS_PROFILE=${AWS_PROFILE:-griddo-main}
AWS_REGION=${AWS_REGION:-eu-south-2}
ALERT_EMAIL=${ALERT_EMAIL:-daniel.serrano@griddo.io}
LOG_GROUP=${LOG_GROUP:-/aws/ecs/default/shurly-api-5fdb}
SERVICE=${SERVICE:-shurly-api}
DB=${DB:-shurly-db}
TOPIC_NAME=${TOPIC_NAME:-shurly-alerts}
APP_HOST=${APP_HOST:-shurly.griddo.io}
DASHBOARD=shurly
QUERY_FOLDER=shurly/
# The shared ALB ECS Express made for the account's services.
ALB_PREFIX=ecs-express-gateway-alb-

DEFS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/infra/monitoring"

usage() {
    echo "usage: $0 [--for-real]" >&2
    echo "       $0 --test-alarm NAME [--for-real]    e.g. $0 --test-alarm shurly-api-5xx" >&2
    exit 2
}

die() {
    echo "✗ $*" >&2
    exit 1
}

aws() { command aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

FOR_REAL=false
TEST_ALARM=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --for-real) FOR_REAL=true; shift ;;
        --test-alarm)
            [[ $# -ge 2 && -n "$2" && "$2" != -* && -z "$TEST_ALARM" ]] || usage
            TEST_ALARM=$2
            shift 2
            ;;
        *) usage ;;
    esac
done
command -v jq >/dev/null || die "jq is required (brew install jq / apt-get install -y jq)"
for definition in metric-filters alarms dashboard queries; do
    jq empty "$DEFS/$definition.json" 2>/dev/null || die "$DEFS/$definition.json is missing or isn't JSON."
done

if [[ -n "$TEST_ALARM" ]]; then
    jq -e --arg name "$TEST_ALARM" 'any(.[]; .AlarmName == $name)' "$DEFS/alarms.json" >/dev/null ||
        die "No alarm ${TEST_ALARM} in infra/monitoring/alarms.json. The alarms: $(jq -r '[.[].AlarmName] | join(", ")' "$DEFS/alarms.json")."
fi

if $FOR_REAL; then
    if [[ -n "$TEST_ALARM" ]]; then
        echo "This sets the alarm ${TEST_ALARM} to ALARM in ${AWS_REGION} (profile ${AWS_PROFILE}): its email goes to the topic's subscribers."
    else
        echo "This creates or updates Shurly's alerting in ${AWS_REGION} (profile ${AWS_PROFILE}): SNS topic, filters, alarms, dashboard, queries."
    fi
    read -r -p "Type ${AWS_REGION} to go on: " typed || typed=""
    [[ "$typed" == "$AWS_REGION" ]] || die "Not confirmed: nothing was run."
fi

W=$(mktemp -d)
trap 'rm -rf "${W:?}"' EXIT

ACCOUNT=$(aws sts get-caller-identity --output json | jq -r '.Account // empty')
[[ "$ACCOUNT" =~ ^[0-9]{12}$ ]] || die "Couldn't read the AWS account (profile ${AWS_PROFILE}): is the SSO session logged in?"
echo "Account:        ${ACCOUNT} (profile ${AWS_PROFILE}, region ${AWS_REGION})"

# --- Testing an alarm: only set-alarm-state, on an alarm the script made ---------------------------

if [[ -n "$TEST_ALARM" ]]; then
    aws cloudwatch describe-alarms --alarm-names "$TEST_ALARM" --output json >"$W/alarm.json" ||
        die "Couldn't read the alarm ${TEST_ALARM}."
    jq -e --arg name "$TEST_ALARM" 'any((.MetricAlarms // [])[]; .AlarmName == $name)' "$W/alarm.json" >/dev/null ||
        die "The alarm ${TEST_ALARM} doesn't exist in AWS yet: run $0 --for-real first."
    if ! $FOR_REAL; then
        echo "Would set ${TEST_ALARM} to ALARM (dry run: nothing written; --for-real to send the email)."
        exit 0
    fi
    aws cloudwatch set-alarm-state --alarm-name "$TEST_ALARM" --state-value ALARM \
        --state-reason "Test from setup_monitoring.sh" >/dev/null
    echo "✓ ${TEST_ALARM} is in ALARM: its email should arrive in a minute or two. At its next evaluation it goes back to OK, and that sends the OK email."
    exit 0
fi

# --- Discovery (read-only) ------------------------------------------------------------------------

aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --output json >"$W/log-groups.json" ||
    die "Couldn't list the log groups."
jq -e --arg g "$LOG_GROUP" 'any((.logGroups // [])[]; .logGroupName == $g)' "$W/log-groups.json" >/dev/null ||
    die "No log group ${LOG_GROUP}: set LOG_GROUP to the service's (its task definition's awslogs-group)."
echo "Log group:      ${LOG_GROUP}"

aws rds describe-db-instances --db-instance-identifier "$DB" --output json >"$W/db.json" ||
    die "No RDS instance ${DB}: set DB to its identifier."
jq -e --arg db "$DB" 'any((.DBInstances // [])[]; .DBInstanceIdentifier == $db)' "$W/db.json" >/dev/null ||
    die "No RDS instance ${DB}: set DB to its identifier."
echo "Database:       ${DB}"

aws elbv2 describe-load-balancers --output json >"$W/albs.json" || die "Couldn't list the load balancers."
jq -r --arg p "$ALB_PREFIX" '[(.LoadBalancers // [])[] | select(.LoadBalancerName | startswith($p))]
    | map(.LoadBalancerArn) | .[]' "$W/albs.json" >"$W/alb-arns"
[[ $(wc -l <"$W/alb-arns" | tr -d ' ') == 1 ]] ||
    die "Expected one load balancer named ${ALB_PREFIX}*, found $(wc -l <"$W/alb-arns" | tr -d ' ')."
ALB_ARN=$(cat "$W/alb-arns")
ALB="app/${ALB_ARN##*:loadbalancer/app/}"
[[ "$ALB" =~ ^app/[^/]+/[^/]+$ ]] || die "The load balancer's ARN doesn't look like an ALB's: ${ALB_ARN}"
echo "Load balancer:  ${ALB}"

# The service's target groups: those the ALB's rules for APP_HOST (the custom domain's, rule 12)
# and for the service's Express host (SERVICE.ecs.REGION.on.aws, Express's own rule) forward to.
# Express deploys blue/green between two, so there must be exactly two.
aws elbv2 describe-listeners --load-balancer-arn "$ALB_ARN" --output json >"$W/listeners.json" ||
    die "Couldn't list the load balancer's listeners."
echo '[]' >"$W/rules.json"
for listener in $(jq -r '(.Listeners // [])[].ListenerArn' "$W/listeners.json"); do
    aws elbv2 describe-rules --listener-arn "$listener" --output json >"$W/listener-rules.json" ||
        die "Couldn't read the rules of ${listener}."
    jq -s '.[0] + (.[1].Rules // [])' "$W/rules.json" "$W/listener-rules.json" >"$W/rules.next.json"
    mv "$W/rules.next.json" "$W/rules.json"
done
jq -r --arg app "$APP_HOST" --arg express "${SERVICE}.ecs.${AWS_REGION}.on.aws" '
    def ours: ascii_downcase as $h | $h == $app or $h == $express;
    [ .[]
      | select(any((.Conditions // [])[];
            .Field == "host-header" and any(((.HostHeaderConfig.Values // .Values // [])[]); ours)))
      | (.Actions // [])[]
      | select(.Type == "forward")
      | (.TargetGroupArn // empty), ((.ForwardConfig.TargetGroups // [])[].TargetGroupArn)
    ] | unique | .[]' "$W/rules.json" >"$W/tg-arns"
TG_COUNT=$(wc -l <"$W/tg-arns" | tr -d ' ')
[[ "$TG_COUNT" == 2 ]] ||
    die "Expected the service's 2 target groups (rules for ${APP_HOST} and ${SERVICE}.ecs.${AWS_REGION}.on.aws), found ${TG_COUNT}."
TG_1="targetgroup/$(sed -n 1p "$W/tg-arns" | sed 's|.*:targetgroup/||')"
TG_2="targetgroup/$(sed -n 2p "$W/tg-arns" | sed 's|.*:targetgroup/||')"
for tg in "$TG_1" "$TG_2"; do
    [[ "$tg" =~ ^targetgroup/[^/]+/[^/]+$ ]] || die "A target group's ARN doesn't look like one: ${tg}"
done
echo "Target groups:  ${TG_1}, ${TG_2}"

# What exists already, to say create or update.
aws sns list-topics --output json >"$W/topics.json" || die "Couldn't list the SNS topics."
EXPECTED_TOPIC_ARN="arn:aws:sns:${AWS_REGION}:${ACCOUNT}:${TOPIC_NAME}"
TOPIC_EXISTS=false
jq -e --arg arn "$EXPECTED_TOPIC_ARN" 'any((.Topics // [])[]; .TopicArn == $arn)' "$W/topics.json" >/dev/null &&
    TOPIC_EXISTS=true

# The subscription to ALERT_EMAIL in the topic: "" (none), "confirmed" or "pending".
subscription_state() {
    aws sns list-subscriptions-by-topic --topic-arn "$1" --output json >"$W/subscriptions.json" ||
        die "Couldn't list the topic's subscriptions."
    jq -r --arg email "$ALERT_EMAIL" '
        [(.Subscriptions // [])[]
         | select(.Protocol == "email" and ((.Endpoint // "") | ascii_downcase) == ($email | ascii_downcase))]
        | if length == 0 then ""
          elif any(.[]; .SubscriptionArn | startswith("arn:")) then "confirmed"
          else "pending" end' "$W/subscriptions.json"
}
SUBSCRIPTION=""
$TOPIC_EXISTS && SUBSCRIPTION=$(subscription_state "$EXPECTED_TOPIC_ARN")

aws logs describe-metric-filters --log-group-name "$LOG_GROUP" --output json >"$W/filters-now.json" ||
    die "Couldn't list the log group's metric filters."
ALARM_NAMES=()
while IFS= read -r name; do ALARM_NAMES+=("$name"); done < <(jq -r '.[].AlarmName' "$DEFS/alarms.json")
aws cloudwatch describe-alarms --alarm-names "${ALARM_NAMES[@]}" --output json >"$W/alarms-now.json" ||
    die "Couldn't list the alarms."
aws cloudwatch list-dashboards --dashboard-name-prefix "$DASHBOARD" --output json >"$W/dashboards-now.json" ||
    die "Couldn't list the dashboards."
# AWS refuses a prefix ending in "/" (InvalidParameterException), so "shurly", not "shurly/"; queries are
# matched by their exact name below.
aws logs describe-query-definitions --query-definition-name-prefix "${QUERY_FOLDER%/}" --max-results 1000 \
    --output json >"$W/queries-now.json" || die "Couldn't list the saved queries."

# --- The definitions, with the discovered values -------------------------------------------------

TOPIC_ARN=$EXPECTED_TOPIC_ARN

# fill FILE: FILE with each ${PLACEHOLDER} replaced, in every string, by its value (literally:
# split and join, no regex, no sed); stops if one is left.
fill() {
    jq --arg LOG_GROUP "$LOG_GROUP" --arg TOPIC_ARN "$TOPIC_ARN" --arg ALB "$ALB" \
        --arg TG_1 "$TG_1" --arg TG_2 "$TG_2" --arg DB "$DB" '
        def fill:
            reduce ({"${LOG_GROUP}": $LOG_GROUP, "${TOPIC_ARN}": $TOPIC_ARN, "${ALB}": $ALB,
                     "${TG_1}": $TG_1, "${TG_2}": $TG_2, "${DB}": $DB} | to_entries[]) as $p
                (.; split($p.key) | join($p.value));
        walk(if type == "string" then fill else . end)' "$1" >"$W/filled.json"
    if jq -e '[.. | strings | select(contains("${"))] | length > 0' "$W/filled.json" >/dev/null; then
        die "$1 has a placeholder the script doesn't know: $(jq -r '[.. | strings | select(contains("${"))][0]' "$W/filled.json")"
    fi
    cat "$W/filled.json"
}

fill "$DEFS/metric-filters.json" >"$W/filters.json"
fill "$DEFS/alarms.json" >"$W/alarms.json"
fill "$DEFS/dashboard.json" >"$W/dashboard.json"
jq --arg g "$LOG_GROUP" 'map({name, queryString, logGroupNames: [$g]})' "$DEFS/queries.json" >"$W/queries.json"

# exists FILE JQ_FILTER NAME: whether NAME is among the names the filter lists from FILE.
exists() {
    jq -e --arg n "$3" "any($2; . == \$n)" "$1" >/dev/null
}
action() { if exists "$@"; then echo update; else echo create; fi; }

# --- The plan, then (for real) the changes -------------------------------------------------------

if $FOR_REAL; then
    echo "Mode:           FOR REAL"
else
    echo "Mode:           dry run: everything looked up, nothing written"
fi
done_or_would() { if $FOR_REAL; then echo "✓"; else echo "would"; fi; }
MARK=$(done_or_would)

if $FOR_REAL; then
    TOPIC_ARN=$(aws sns create-topic --name "$TOPIC_NAME" --output json | jq -r '.TopicArn // empty')
    [[ "$TOPIC_ARN" == arn:aws:sns:* ]] || die "create-topic returned no topic ARN."
    if [[ "$TOPIC_ARN" != "$EXPECTED_TOPIC_ARN" ]]; then
        # Not expected, but the alarms must point at the topic that exists.
        fill "$DEFS/alarms.json" >"$W/alarms.json"
    fi
fi
if $TOPIC_EXISTS; then
    echo "${MARK} topic ${TOPIC_NAME}: exists (${TOPIC_ARN})"
else
    echo "${MARK} topic ${TOPIC_NAME}: create (${TOPIC_ARN})"
fi

if $FOR_REAL; then SUBSCRIPTION=$(subscription_state "$TOPIC_ARN"); fi
case "$SUBSCRIPTION" in
    confirmed) echo "${MARK} subscription ${ALERT_EMAIL}: exists, confirmed" ;;
    pending) echo "${MARK} subscription ${ALERT_EMAIL}: exists, pending confirmation: accept the email AWS sent" ;;
    *)
        if $FOR_REAL; then
            aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email \
                --notification-endpoint "$ALERT_EMAIL" --output json >/dev/null
        fi
        echo "${MARK} subscription ${ALERT_EMAIL}: create (AWS emails a confirmation link to accept once)"
        ;;
esac

COUNT=$(jq length "$W/filters.json")
for ((i = 0; i < COUNT; i++)); do
    jq ".[$i]" "$W/filters.json" >"$W/filter-$i.json"
    name=$(jq -r '.filterName' "$W/filter-$i.json")
    verb=$(action "$W/filters-now.json" '(.metricFilters // [])[].filterName' "$name")
    if $FOR_REAL; then aws logs put-metric-filter --cli-input-json "file://$W/filter-$i.json"; fi
    echo "${MARK} metric filter ${name}: ${verb}"
done

COUNT=$(jq length "$W/alarms.json")
for ((i = 0; i < COUNT; i++)); do
    jq ".[$i]" "$W/alarms.json" >"$W/alarm-$i.json"
    name=$(jq -r '.AlarmName' "$W/alarm-$i.json")
    verb=$(action "$W/alarms-now.json" '(.MetricAlarms // [])[].AlarmName' "$name")
    if $FOR_REAL; then aws cloudwatch put-metric-alarm --cli-input-json "file://$W/alarm-$i.json"; fi
    echo "${MARK} alarm ${name}: ${verb}"
done

verb=$(action "$W/dashboards-now.json" '(.DashboardEntries // [])[].DashboardName' "$DASHBOARD")
if $FOR_REAL; then
    aws cloudwatch put-dashboard --dashboard-name "$DASHBOARD" --dashboard-body "file://$W/dashboard.json" \
        --output json >"$W/dashboard-result.json"
    jq -e '(.DashboardValidationMessages // []) | length == 0' "$W/dashboard-result.json" >/dev/null ||
        echo "  the dashboard was saved with warnings: $(jq -c '.DashboardValidationMessages' "$W/dashboard-result.json")"
fi
echo "${MARK} dashboard ${DASHBOARD}: ${verb}"

COUNT=$(jq length "$W/queries.json")
for ((i = 0; i < COUNT; i++)); do
    name=$(jq -r ".[$i].name" "$W/queries.json")
    id=$(jq -r --arg n "$name" '[(.queryDefinitions // [])[] | select(.name == $n) | .queryDefinitionId][0] // empty' \
        "$W/queries-now.json")
    if [[ -n "$id" ]]; then
        verb=update
        jq --arg id "$id" ".[$i] + {queryDefinitionId: \$id}" "$W/queries.json" >"$W/query-$i.json"
    else
        verb=create
        jq ".[$i]" "$W/queries.json" >"$W/query-$i.json"
    fi
    if $FOR_REAL; then
        aws logs put-query-definition --cli-input-json "file://$W/query-$i.json" --output json >/dev/null
    fi
    echo "${MARK} saved query ${name}: ${verb}"
done

if $FOR_REAL; then
    echo "✓ Done. Test an alarm's email with: $0 --test-alarm shurly-api-5xx --for-real"
else
    echo "Dry run: nothing written. Run again with --for-real to apply."
fi
