"""MCP server factory + allowed-tool list for FRIDAY.

Phase 6: full tool roster."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import (
    alarm_tool,
    briefing_tool,
    memory_tool,
    notes_tool,
    spotify_tool,
    util_tool,
)


ALLOWED_TOOL_NAMES = [
    "mcp__friday__get_time",
    "mcp__friday__play_spotify",
    "mcp__friday__pause_spotify",
    "mcp__friday__resume_spotify",
    "mcp__friday__skip_track",
    "mcp__friday__set_volume",
    "mcp__friday__write_note",
    "mcp__friday__read_briefing",
    "mcp__friday__set_alarm",
    "mcp__friday__cancel_alarm",
    "mcp__friday__list_alarms",
    "mcp__friday__remember_fact",
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
            alarm_tool.set_alarm,
            alarm_tool.cancel_alarm,
            alarm_tool.list_alarms,
            memory_tool.remember_fact,
        ],
    )
