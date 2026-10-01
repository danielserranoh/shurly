"""
Phase 8.4 — the MCP's `create_custom_url` takes a code of up to 64 characters, as the API does
(tests/test_phase84_long_codes.py): the generated tool forwards to the same route. Called through
the in-process server, as tests/test_mcp_output_dates.py calls every tool.
"""

import pytest

pytest.importorskip("fastmcp")

from tests import test_mcp_output_dates as mcp_calls  # noqa: E402

# The fixtures, by assignment: imported by name, ruff reads their use as a redefinition (F811).
mcp_server = mcp_calls.mcp_server
bound = mcp_calls.bound
seeded = mcp_calls.seeded

LONG = "jane-doe-acme-corp-2026-q4-outreach-followup"  # 44 characters, as Shlink's longest


def test_create_custom_url_takes_a_44_character_code(mcp_server, seeded):
    output = mcp_calls._call(
        mcp_server,
        "create_custom_url",
        {"url": "https://example.com/outreach", "custom_code": LONG},
    )

    assert output.structured_content["short_code"] == LONG


def test_the_tool_says_64(mcp_server):
    tools = {tool.name: tool for tool in mcp_calls.asyncio.run(mcp_server.list_tools())}

    code = tools["create_custom_url"].parameters["properties"]["custom_code"]
    assert "3-64" in code["description"]
