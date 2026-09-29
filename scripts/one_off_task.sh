# Phase 8.4 — what the one-off ECS tasks share (scripts/run_shlink_import.sh,
# scripts/run_backfill_places.sh): a task made for the run from the live service's own image,
# environment and network, run once, its output shown from CloudWatch, and its task definition
# deleted at the end, whatever happens. Sourced by them; never run on its own.
#
# The live task definition carries the service's environment, secrets included: it goes to AWS,
# and into a private temporary directory, never to the terminal.
#
# AWS_PROFILE (griddo-main), AWS_REGION (eu-south-2), CLUSTER (default) and SERVICE (shurly-api)
# can be set in the environment.

AWS_PROFILE=${AWS_PROFILE:-griddo-main}
AWS_REGION=${AWS_REGION:-eu-south-2}
CLUSTER=${CLUSTER:-default}
SERVICE=${SERVICE:-shurly-api}

die() {
    echo "✗ $*" >&2
    exit 1
}

aws() { command aws --profile "$AWS_PROFILE" --region "$AWS_REGION" "$@"; }

# The live service: sets ACCOUNT, SERVICE_ARN, NETWORK and WORK, a private temporary directory
# holding its task definition as live.json. WORK, and the task definition run_one_off registers,
# are deleted on exit.
read_live_service() {
    ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    SERVICE_ARN=$(aws ecs list-services --cluster "$CLUSTER" \
        --query "serviceArns[?contains(@, '${SERVICE}')] | [0]" --output text)
    [[ "$SERVICE_ARN" == arn:* ]] || die "No service ${SERVICE} in the cluster ${CLUSTER}."

    WORK=$(mktemp -d)
    NEW_TD=""
    trap delete_one_off EXIT

    aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE_ARN" \
        --query 'services[0]' --output json >"$WORK/service.json"
    local live_td
    live_td=$(jq -r '.taskDefinition' "$WORK/service.json")
    NETWORK=$(jq -c '.networkConfiguration // .deployments[0].networkConfiguration' "$WORK/service.json")
    [[ "$NETWORK" != null ]] || die "The service has no network configuration to run the task in."

    aws ecs describe-task-definition --task-definition "$live_td" \
        --query taskDefinition --output json >"$WORK/live.json"
    jq -e '.containerDefinitions[0].logConfiguration.logDriver == "awslogs"' "$WORK/live.json" \
        >/dev/null || die "The service's container doesn't log to CloudWatch (awslogs): its output would be lost."
}

delete_one_off() {
    if [[ -n "${NEW_TD:-}" ]]; then
        aws ecs deregister-task-definition --task-definition "$NEW_TD" >/dev/null || true
        aws ecs delete-task-definitions --task-definitions "$NEW_TD" >/dev/null || true
        echo "The one-off task definition is deleted."
    fi
    rm -rf "${WORK:-}"
}

# A command, one argument a line, as the overrides that run it in CONTAINER: jq's --args would
# read "-m" and "--as" as its own options.
command_overrides() {
    local container=$1
    shift
    printf '%s\n' "$@" |
        jq -cRn --arg name "$container" '{containerOverrides: [{name: $name, command: [inputs]}]}'
}

# run_one_off DEFINITION OVERRIDES PREFIX MAIN CONTAINER...
# Registers DEFINITION (a file), runs it once in the service's network with OVERRIDES, waits for
# it to stop, and shows each CONTAINER's output from CloudWatch (streams PREFIX/CONTAINER/task).
# Sets EXIT_CODE, MAIN's exit code.
run_one_off() {
    local definition=$1 overrides=$2 prefix=$3 main=$4
    shift 4
    NEW_TD=$(aws ecs register-task-definition --cli-input-json "file://${definition}" \
        --query 'taskDefinition.taskDefinitionArn' --output text)
    local task
    task=$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE --task-definition "$NEW_TD" \
        --network-configuration "$NETWORK" --overrides "$overrides" \
        --query 'tasks[0].taskArn' --output text)
    [[ "$task" == arn:* ]] || die "The task didn't start."
    local task_id=${task##*/}
    echo "Task:     ${task_id}: waiting for it to finish…"

    while [[ "$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" \
        --query 'tasks[0].lastStatus' --output text)" != STOPPED ]]; do
        sleep 10
    done

    local group container
    group=$(jq -r '.containerDefinitions[0].logConfiguration.options["awslogs-group"]' "$WORK/live.json")
    for container in "$@"; do
        echo "── ${container} (CloudWatch ${group}, ${prefix}/${container}/${task_id})"
        aws logs tail "$group" --log-stream-names "${prefix}/${container}/${task_id}" --since 1d || true
    done

    EXIT_CODE=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" \
        --query "tasks[0].containers[?name=='${main}'] | [0].exitCode" --output text)
}
