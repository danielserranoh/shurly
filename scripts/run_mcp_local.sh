#!/bin/bash
# Local MCP server entry point — used by Claude Code's MCP config to launch
# Shurly's MCP transport over stdio. Wraps the `python -m mcp_server` invocation
# so the registered command in `~/.claude.json` stays short.
#
# Why TESTING=1: main.py's startup event calls Base.metadata.create_all() and
# seeds predefined tags + the default domain row. All three need a live DB
# connection. The RDS instance lives inside a private VPC, so a local stdio
# server can't reach it. TESTING=1 short-circuits the startup hook (same gate
# the test suite uses), letting the MCP server boot purely against the route
# graph for tool listing. Tool *invocation* against real data needs a live DB
# and is wired up in Phase 5.4 (auth + per-user scoping against the deployed
# API at s.griddo.io).
#
# Register with Claude Code:
#   claude mcp add shurly-local -- /Users/<you>/Tools/shurly/scripts/run_mcp_local.sh
#
# Then in any Claude Code session, `/mcp` lists `shurly-local` with its tools.

set -euo pipefail

# Resolve the project root from this script's location, so the path doesn't
# need hard-coding into the user's MCP config.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# TESTING=1 short-circuits the FastAPI startup event (no DB connection
# attempts). Pass --extra mcp so uv installs fastmcp into the venv.
exec env TESTING=1 \
    uv run --extra mcp python -m mcp_server "$@"
