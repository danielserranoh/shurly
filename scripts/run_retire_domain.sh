#!/usr/bin/env bash
# Phase 8.5 — retiring a domain (ROADMAP 8.5): deletes a domain's row and its links, with their
# visits, redirect rules and tag associations, in production's database
# (`python -m server.tools.domains retire`), as a one-off ECS task from the live service's own
# image, environment and network (scripts/one_off_task.sh). DEPLOYMENT.md § The cutover.
#
# One container, `retire`, with no task role: it reads nothing from AWS. A dry run unless
# --for-real, which needs the domain typed back. The tool refuses the default domain and one that
# isn't there, and the script fails then. Its output goes to the service's log group, in streams
# `retire-domain/…`. It doesn't touch the load balancer, the certificate or DNS.
#
#   scripts/run_retire_domain.sh DOMAIN [--for-real]      e.g. old.example.com
#
# AWS_PROFILE (griddo-main), AWS_REGION (eu-south-2), CLUSTER (default) and SERVICE (shurly-api)
# can be set in the environment.

set -euo pipefail
umask 077

# shellcheck source=scripts/one_off_task.sh
source "$(dirname "${BASH_SOURCE[0]}")/one_off_task.sh"

usage() {
    echo "usage: $0 DOMAIN [--for-real]    e.g. $0 old.example.com" >&2
    exit 2
}

FOR_REAL=false
DOMAIN=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --for-real) FOR_REAL=true; shift ;;
        -*) usage ;;
        *) [[ -z "$DOMAIN" ]] || usage; DOMAIN=$1; shift ;;
    esac
done
# A domain name, as the tool reads one: labels of letters, digits and hyphens, at least two.
DOMAIN=$(printf '%s' "$DOMAIN" | tr '[:upper:]' '[:lower:]')
LABEL='[a-z0-9]([a-z0-9-]*[a-z0-9])?'
DOMAIN_NAME="^${LABEL}(\.${LABEL})+\$"
[[ "$DOMAIN" =~ $DOMAIN_NAME ]] || usage
command -v jq >/dev/null || die "jq is required (brew install jq / apt-get install -y jq)"

if $FOR_REAL; then
    echo "This deletes ${DOMAIN} in production (${SERVICE}): its row, its links, their visits,"
    echo "redirect rules and tag associations. No redirect is kept, and there's no undo."
    read -r -p "Type ${DOMAIN} to go on: " typed
    [[ "$typed" == "$DOMAIN" ]] || die "Not confirmed: nothing was run."
fi

read_live_service

jq '
    .containerDefinitions[0] as $app
    | {
        family: "shurly-retire-domain",
        executionRoleArn: .executionRoleArn,
        networkMode: "awsvpc",
        requiresCompatibilities: ["FARGATE"],
        cpu: "256",
        memory: "512",
        runtimePlatform: .runtimePlatform,
        containerDefinitions: [
            {
                name: "retire",
                image: $app.image,
                essential: true,
                environment: ($app.environment // []),
                secrets: ($app.secrets // []),
                logConfiguration:
                    ($app.logConfiguration | .options["awslogs-stream-prefix"] = "retire-domain")
            }
        ]
    }
    | with_entries(select(.value != null))' "$WORK/live.json" >"$WORK/retire.json"

RETIRE_COMMAND=(python -m server.tools.domains retire "$DOMAIN")
$FOR_REAL && RETIRE_COMMAND+=(--for-real)
OVERRIDES=$(command_overrides retire "${RETIRE_COMMAND[@]}")

echo "Service:  ${SERVICE_ARN}"
echo "Image:    $(jq -r '.containerDefinitions[0].image' "$WORK/live.json")"
echo "Retire:   ${RETIRE_COMMAND[*]}"
$FOR_REAL && echo "Mode:     FOR REAL" || echo "Mode:     dry run: everything checked, nothing written"

run_one_off "$WORK/retire.json" "$OVERRIDES" retire-domain retire retire
[[ "$EXIT_CODE" == 0 ]] || die "The retirement exited with ${EXIT_CODE}: see its output above."
echo "✓ The retirement finished$($FOR_REAL || echo ' (dry run: nothing written)')."
