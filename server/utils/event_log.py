"""
Phase 5.6.0 — structured event log: one JSON object per line on stderr.

CloudWatch Logs stores each line as an event and Logs Insights discovers the
JSON fields by itself, so queries can filter and aggregate on them (the saved
queries are in `mcp_server/README.md`). Stderr, not stdout: under the MCP stdio
transport, stdout is the JSON-RPC channel, and a stray line there breaks it.

Never pass values a user typed (tool arguments, query strings, request bodies):
campaign rows carry names, companies and emails.
"""

import json
import sys
from datetime import datetime, timezone


def log_event(event: str, **fields) -> None:
    """Write one line: `ts` (UTC, ISO 8601), `event`, then `fields` in order."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    sys.stderr.write(json.dumps(record, default=str) + "\n")
