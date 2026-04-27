"""
CLI entry point for the Shurly MCP server.

Usage:
    python -m mcp_server                # default: stdio transport
    python -m mcp_server --http          # streamable-HTTP on :9000
    python -m mcp_server --http --port 8765

Phase 5.1 supports stdio (for local dev under Claude Code) and Streamable
HTTP (for the eventual deployed surface). The transports share the same
underlying tool set; the difference is only how the client talks to us.
"""

from __future__ import annotations

import argparse
import sys

from mcp_server.server import mcp_server


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mcp_server",
        description="Run the Shurly MCP server.",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use Streamable HTTP transport instead of stdio.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP bind host (default: 0.0.0.0). Ignored without --http.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9000,
        help="HTTP bind port (default: 9000). Ignored without --http.",
    )
    args = parser.parse_args()

    if args.http:
        # Streamable HTTP — what production deploys (Phase 5.5) will use.
        mcp_server.run(transport="http", host=args.host, port=args.port)
    else:
        # Stdio — what Claude Code expects when launching us as a subprocess.
        mcp_server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
