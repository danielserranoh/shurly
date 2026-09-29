#!/usr/bin/env bash
# Phase 8.4, decision B — Shlink's links into production's database: the import
# (`python -m server.tools.shlink import`) as a one-off ECS task, from the live service's own
# image, environment and network. DEPLOYMENT.md § Moving Shlink's links has the runbook, and the
# bucket and the IAM this needs, made once by hand.
#
# The task has two containers sharing a volume:
#   fetch   the AWS CLI's image: copies the snapshot and the review from the private bucket, with
#           the task role `shurly-shlink-import`, which reads that one prefix and nothing else;
#   import  Shurly's image: the import, from those files. `--dry-run` unless --for-real.
# Their output goes to the service's CloudWatch log group, in streams `shlink-import/…`.
#
# The task definition is made for the run from the live one, and deleted at the end, whatever
# happens. It carries the service's environment, secrets included: they go to AWS, never here.
#
#   scripts/run_shlink_import.sh --bucket B --prefix P --as owner@griddo.io [--visits] [--for-real]
#       [--snapshot snapshot.json] [--review review.csv]
#
# AWS_PROFILE (griddo-main), AWS_REGION (eu-south-2), CLUSTER (default), SERVICE (shurly-api),
# IMPORT_ROLE (shurly-shlink-import) and AWS_CLI_IMAGE can be set in the environment.

set -euo pipefail
umask 077

AWS_PROFILE=${AWS_PROFILE:-griddo-main}
AWS_REGION=${AWS_REGION:-eu-south-2}
CLUSTER=${CLUSTER:-default}
SERVICE=${SERVICE:-shurly-api}
IMPORT_ROLE=${IMPORT_ROLE:-shurly-shlink-import}
AWS_CLI_IMAGE=${AWS_CLI_IMAGE:-public.ecr.aws/aws-cli/aws-cli:2.17.52}

usage() {
    echo "usage: $0 --bucket B --prefix P --as OWNER_EMAIL [--visits] [--for-real]" >&2
    echo "          [--snapshot snapshot.json] [--review review.csv]" >&2
    exit 2
}

die() {
    echo "✗ $*" >&2
    exit 1
}

BUCKET="" PREFIX="" OWNER="" SNAPSHOT="snapshot.json" REVIEW="review.csv" VISITS=false FOR_REAL=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --bucket | --prefix | --as | --snapshot | --review)
            [[ $# -ge 2 && -n "$2" ]] || usage
            case "$1" in
                --bucket) BUCKET=$2 ;;
                --prefix) PREFIX=${2%/} ;;
                --as) OWNER=$2 ;;
                --snapshot) SNAPSHOT=$2 ;;
                --review) REVIEW=$2 ;;
            esac
            shift 2
            ;;
        --visits) VISITS=true; shift ;;
        --for-real) FOR_REAL=true; shift ;;
        *) usage ;;
    esac
done
[[ -n "$BUCKET" && -n "$PREFIX" && -n "$OWNER" && -n "$SNAPSHOT" && -n "$REVIEW" ]] || usage
command -v jq >/dev/null || die "jq is required (brew install jq / apt-get install -y jq)"

aws() { command aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

SOURCE="s3://${BUCKET}/${PREFIX}/"
for file in "$SNAPSHOT" "$REVIEW"; do
    aws s3 ls "${SOURCE}${file}" >/dev/null || die "${SOURCE}${file} isn't there: upload it first"
done

if $FOR_REAL; then
    echo "This imports for real into production's database, as ${OWNER}."
    read -r -p "Type ${OWNER} to go on: " typed
    [[ "$typed" == "$OWNER" ]] || die "Not confirmed: nothing was run."
fi

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
SERVICE_ARN=$(aws ecs list-services --cluster "$CLUSTER" \
    --query "serviceArns[?contains(@, '${SERVICE}')] | [0]" --output text)
[[ "$SERVICE_ARN" == arn:* ]] || die "No service ${SERVICE} in the cluster ${CLUSTER}."

WORK=$(mktemp -d)
NEW_TD=""
cleanup() {
    if [[ -n "$NEW_TD" ]]; then
        aws ecs deregister-task-definition --task-definition "$NEW_TD" >/dev/null || true
        aws ecs delete-task-definitions --task-definitions "$NEW_TD" >/dev/null || true
        echo "The one-off task definition is deleted."
    fi
    rm -rf "$WORK"
}
trap cleanup EXIT

aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE_ARN" \
    --query 'services[0]' --output json >"$WORK/service.json"
LIVE_TD=$(jq -r '.taskDefinition' "$WORK/service.json")
NETWORK=$(jq -c '.networkConfiguration // .deployments[0].networkConfiguration' "$WORK/service.json")
[[ "$NETWORK" != null ]] || die "The service has no network configuration to run the task in."

# The live task definition holds the service's environment, secrets included: never printed.
aws ecs describe-task-definition --task-definition "$LIVE_TD" \
    --query taskDefinition --output json >"$WORK/live.json"
jq -e '.containerDefinitions[0].logConfiguration.logDriver == "awslogs"' "$WORK/live.json" >/dev/null ||
    die "The service's container doesn't log to CloudWatch (awslogs): its output would be lost."

jq --arg role "arn:aws:iam::${ACCOUNT}:role/${IMPORT_ROLE}" \
    --arg cli "$AWS_CLI_IMAGE" --arg source "$SOURCE" '
    .containerDefinitions[0] as $app
    | ($app.logConfiguration | .options["awslogs-stream-prefix"] = "shlink-import") as $logs
    | {
        family: "shurly-shlink-import",
        taskRoleArn: $role,
        executionRoleArn: .executionRoleArn,
        networkMode: "awsvpc",
        requiresCompatibilities: ["FARGATE"],
        cpu: "512",
        memory: "2048",
        runtimePlatform: .runtimePlatform,
        volumes: [{name: "import"}],
        containerDefinitions: [
            {
                name: "fetch",
                image: $cli,
                essential: false,
                command: ["s3", "cp", $source, "/import/", "--recursive", "--only-show-errors"],
                mountPoints: [{sourceVolume: "import", containerPath: "/import"}],
                logConfiguration: $logs
            },
            {
                name: "import",
                image: $app.image,
                essential: true,
                environment: ($app.environment // []),
                secrets: ($app.secrets // []),
                dependsOn: [{containerName: "fetch", condition: "SUCCESS"}],
                mountPoints: [{sourceVolume: "import", containerPath: "/import", readOnly: true}],
                logConfiguration: $logs
            }
        ]
    }
    | with_entries(select(.value != null))' "$WORK/live.json" >"$WORK/import.json"

IMPORT_COMMAND=(python -m server.tools.shlink import "/import/${SNAPSHOT}" "/import/${REVIEW}" --as "$OWNER")
$VISITS && IMPORT_COMMAND+=(--visits)
$FOR_REAL || IMPORT_COMMAND+=(--dry-run)
# One argument a line into a JSON array: jq's --args would read "-m" and "--as" as its own options.
OVERRIDES=$(printf '%s\n' "${IMPORT_COMMAND[@]}" |
    jq -cRn '{containerOverrides: [{name: "import", command: [inputs]}]}')

echo "Service:  ${SERVICE_ARN}"
echo "Image:    $(jq -r '.containerDefinitions[0].image' "$WORK/live.json")"
echo "Files:    ${SOURCE}{${SNAPSHOT},${REVIEW}}"
echo "Import:   ${IMPORT_COMMAND[*]}"
$FOR_REAL && echo "Mode:     FOR REAL" || echo "Mode:     dry run: everything, then rolled back"

NEW_TD=$(aws ecs register-task-definition --cli-input-json "file://${WORK}/import.json" \
    --query 'taskDefinition.taskDefinitionArn' --output text)
TASK=$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE --task-definition "$NEW_TD" \
    --network-configuration "$NETWORK" --overrides "$OVERRIDES" \
    --query 'tasks[0].taskArn' --output text)
[[ "$TASK" == arn:* ]] || die "The task didn't start."
TASK_ID=${TASK##*/}
echo "Task:     ${TASK_ID}: waiting for it to finish…"

while [[ "$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
    --query 'tasks[0].lastStatus' --output text)" != STOPPED ]]; do
    sleep 10
done

GROUP=$(jq -r '.containerDefinitions[0].logConfiguration.options["awslogs-group"]' "$WORK/live.json")
for container in fetch import; do
    echo "── ${container} (CloudWatch ${GROUP}, shlink-import/${container}/${TASK_ID})"
    aws logs tail "$GROUP" --log-stream-names "shlink-import/${container}/${TASK_ID}" --since 1d || true
done

EXIT_CODE=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK" \
    --query "tasks[0].containers[?name=='import'] | [0].exitCode" --output text)
[[ "$EXIT_CODE" == 0 ]] || die "The import exited with ${EXIT_CODE}: see its output above."
echo "✓ The import finished$($FOR_REAL || echo ' (dry run: rolled back)')."
