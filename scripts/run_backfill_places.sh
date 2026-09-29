#!/usr/bin/env bash
# Phase 8.4 — the countries and cities of the visits saved without them, filled in production's
# database (`python -m server.tools.backfill_places`), as a one-off ECS task from the live
# service's own image, environment and network (scripts/one_off_task.sh). The image's
# geolocation databases are the ones it looks them up in. DEPLOYMENT.md § Geolocation data.
#
# One container, `backfill`, with no task role: it reads nothing from AWS. A dry run unless
# --for-real, which needs the service's name typed back. It only fills what's empty, so running
# it twice is harmless. Its output goes to the service's log group, in streams
# `backfill-places/…`.
#
#   scripts/run_backfill_places.sh [--for-real]
#
# AWS_PROFILE (griddo-main), AWS_REGION (eu-south-2), CLUSTER (default) and SERVICE (shurly-api)
# can be set in the environment.

set -euo pipefail
umask 077

# shellcheck source=scripts/one_off_task.sh
source "$(dirname "${BASH_SOURCE[0]}")/one_off_task.sh"

usage() {
    echo "usage: $0 [--for-real]" >&2
    exit 2
}

FOR_REAL=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --for-real) FOR_REAL=true; shift ;;
        *) usage ;;
    esac
done
command -v jq >/dev/null || die "jq is required (brew install jq / apt-get install -y jq)"

if $FOR_REAL; then
    echo "This fills in the empty countries and cities of ${SERVICE}'s visits, in production."
    read -r -p "Type ${SERVICE} to go on: " typed
    [[ "$typed" == "$SERVICE" ]] || die "Not confirmed: nothing was run."
fi

read_live_service

jq '
    .containerDefinitions[0] as $app
    | {
        family: "shurly-backfill-places",
        executionRoleArn: .executionRoleArn,
        networkMode: "awsvpc",
        requiresCompatibilities: ["FARGATE"],
        cpu: "256",
        memory: "1024",
        runtimePlatform: .runtimePlatform,
        containerDefinitions: [
            {
                name: "backfill",
                image: $app.image,
                essential: true,
                environment: ($app.environment // []),
                secrets: ($app.secrets // []),
                logConfiguration:
                    ($app.logConfiguration | .options["awslogs-stream-prefix"] = "backfill-places")
            }
        ]
    }
    | with_entries(select(.value != null))' "$WORK/live.json" >"$WORK/backfill.json"

BACKFILL_COMMAND=(python -m server.tools.backfill_places)
$FOR_REAL || BACKFILL_COMMAND+=(--dry-run)
OVERRIDES=$(command_overrides backfill "${BACKFILL_COMMAND[@]}")

echo "Service:  ${SERVICE_ARN}"
echo "Image:    $(jq -r '.containerDefinitions[0].image' "$WORK/live.json")"
echo "Backfill: ${BACKFILL_COMMAND[*]}"
$FOR_REAL && echo "Mode:     FOR REAL" || echo "Mode:     dry run: everything looked up, nothing written"

run_one_off "$WORK/backfill.json" "$OVERRIDES" backfill-places backfill backfill
[[ "$EXIT_CODE" == 0 ]] || die "The backfill exited with ${EXIT_CODE}: see its output above."
echo "✓ The backfill finished$($FOR_REAL || echo ' (dry run: nothing written)')."
