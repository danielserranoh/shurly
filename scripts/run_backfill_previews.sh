#!/usr/bin/env bash
# Phase 8.7 — previews from the page, for the links made before them: every link's destination
# fetched (each distinct URL once) and its own preview and icon cached on the link, the old og_*
# copies of the page's cleared (`python -m server.tools.previews backfill`), in production's
# database, as a one-off ECS task from the live service's own image, environment and network
# (scripts/one_off_task.sh). DEPLOYMENT.md § Previews from the page.
#
# One container, `backfill`, with no task role: it reads nothing from AWS. It needs outbound
# internet to fetch the pages, which the service's network has (the API fetches previews too). A
# dry run unless --for-real, which needs the service's name typed back. Running it twice is
# harmless: the second run refreshes the pages' values and clears nothing new. Its output, counts
# and never a destination, goes to the service's log group, in streams `backfill-previews/…`.
#
#   scripts/run_backfill_previews.sh [--for-real]
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
    echo "This fetches every link's destination and writes its preview and icon on ${SERVICE}'s"
    echo "links, in production, clearing the old preview fields that copy the page's."
    read -r -p "Type ${SERVICE} to go on: " typed
    [[ "$typed" == "$SERVICE" ]] || die "Not confirmed: nothing was run."
fi

read_live_service

jq '
    .containerDefinitions[0] as $app
    | {
        family: "shurly-backfill-previews",
        executionRoleArn: .executionRoleArn,
        networkMode: "awsvpc",
        requiresCompatibilities: ["FARGATE"],
        cpu: "256",
        memory: "512",
        runtimePlatform: .runtimePlatform,
        containerDefinitions: [
            {
                name: "backfill",
                image: $app.image,
                essential: true,
                environment: ($app.environment // []),
                secrets: ($app.secrets // []),
                logConfiguration:
                    ($app.logConfiguration | .options["awslogs-stream-prefix"] = "backfill-previews")
            }
        ]
    }
    | with_entries(select(.value != null))' "$WORK/live.json" >"$WORK/backfill.json"

BACKFILL_COMMAND=(python -m server.tools.previews backfill)
$FOR_REAL && BACKFILL_COMMAND+=(--for-real)
OVERRIDES=$(command_overrides backfill "${BACKFILL_COMMAND[@]}")

echo "Service:  ${SERVICE_ARN}"
echo "Image:    $(jq -r '.containerDefinitions[0].image' "$WORK/live.json")"
echo "Backfill: ${BACKFILL_COMMAND[*]}"
$FOR_REAL && echo "Mode:     FOR REAL" || echo "Mode:     dry run: everything fetched, nothing written"

run_one_off "$WORK/backfill.json" "$OVERRIDES" backfill-previews backfill backfill
[[ "$EXIT_CODE" == 0 ]] || die "The backfill exited with ${EXIT_CODE}: see its output above."
echo "✓ The backfill finished$($FOR_REAL || echo ' (dry run: nothing written)')."
