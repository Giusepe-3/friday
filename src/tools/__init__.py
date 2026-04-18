"""MCP server factory + allowed-tool list for FRIDAY.

Tools are added progressively across the build phases. The allowed-tool name
format is ``mcp__friday__<tool_name>`` — this is the convention the Agent
SDK uses to address tools inside a named MCP server."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import util_tool


ALLOWED_TOOL_NAMES = [
    "mcp__friday__get_time",
]


def build_server():
    return create_sdk_mcp_server(
        name="friday",
        version="1.0.0",
        tools=[
            util_tool.get_time,
        ],
    )
