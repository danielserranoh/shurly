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
# happens (scripts/one_off_task.sh). It carries the service's environment, secrets included: they
# go to AWS, never here.
#
#   scripts/run_shlink_import.sh --bucket B --prefix P --as owner@griddo.io [--visits] [--for-real]
#       [--snapshot snapshot.json] [--review review.csv]
#
# AWS_PROFILE (griddo-main), AWS_REGION (eu-south-2), CLUSTER (default), SERVICE (shurly-api),
# IMPORT_ROLE (shurly-shlink-import) and AWS_CLI_IMAGE can be set in the environment.

set -euo pipefail
umask 077

# shellcheck source=scripts/one_off_task.sh
source "$(dirname "${BASH_SOURCE[0]}")/one_off_task.sh"

IMPORT_ROLE=${IMPORT_ROLE:-shurly-shlink-import}
AWS_CLI_IMAGE=${AWS_CLI_IMAGE:-public.ecr.aws/aws-cli/aws-cli:2.17.52}

usage() {
    echo "usage: $0 --bucket B --prefix P --as OWNER_EMAIL [--visits] [--for-real]" >&2
    echo "          [--snapshot snapshot.json] [--review review.csv]" >&2
    exit 2
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

SOURCE="s3://${BUCKET}/${PREFIX}/"
for file in "$SNAPSHOT" "$REVIEW"; do
    aws s3 ls "${SOURCE}${file}" >/dev/null || die "${SOURCE}${file} isn't there: upload it first"
done

if $FOR_REAL; then
    echo "This imports for real into production's database, as ${OWNER}."
    read -r -p "Type ${OWNER} to go on: " typed
    [[ "$typed" == "$OWNER" ]] || die "Not confirmed: nothing was run."
fi

read_live_service

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
OVERRIDES=$(command_overrides import "${IMPORT_COMMAND[@]}")

echo "Service:  ${SERVICE_ARN}"
echo "Image:    $(jq -r '.containerDefinitions[0].image' "$WORK/live.json")"
echo "Files:    ${SOURCE}{${SNAPSHOT},${REVIEW}}"
echo "Import:   ${IMPORT_COMMAND[*]}"
$FOR_REAL && echo "Mode:     FOR REAL" || echo "Mode:     dry run: everything, then rolled back"

run_one_off "$WORK/import.json" "$OVERRIDES" shlink-import import fetch import
[[ "$EXIT_CODE" == 0 ]] || die "The import exited with ${EXIT_CODE}: see its output above."
echo "✓ The import finished$($FOR_REAL || echo ' (dry run: rolled back)')."
