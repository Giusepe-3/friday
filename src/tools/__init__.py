"""MCP server factory + allowed-tool list for FRIDAY.

Phase 4: adds Spotify, notes, briefing tools."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import briefing_tool, notes_tool, spotify_tool, util_tool


ALLOWED_TOOL_NAMES = [
    "mcp__friday__get_time",
    "mcp__friday__play_spotify",
    "mcp__friday__pause_spotify",
    "mcp__friday__resume_spotify",
    "mcp__friday__skip_track",
    "mcp__friday__set_volume",
    "mcp__friday__write_note",
    "mcp__friday__read_briefing",
]


def build_server():
    return create_sdk_mcp_server(
        name="friday",
        version="1.0.0",
        tools=[
            util_tool.get_time,
            spotify_tool.play_spotify,
            spotify_tool.pause_spotify,
            spotify_tool.resume_spotify,
            spotify_tool.skip_track,
            spotify_tool.set_volume,
            notes_tool.write_note,
            briefing_tool.read_briefing,
        ],
    )
