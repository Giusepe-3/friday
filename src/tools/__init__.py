"""MCP server factory + allowed-tool list for FRIDAY.

Phase 9+: adds research tools behind a try/except so a broken research module
leaves the core 12 tools fully functional."""

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


CORE_TOOLS = [
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
]

CORE_ALLOWED = [
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

try:
    from src.research import tools as _research_tools
    RESEARCH_TOOLS = [
        _research_tools.note_research,
        _research_tools.paper_queue_add,
        _research_tools.fetch_and_summarize_paper,
        _research_tools.weekly_research_review,
        _research_tools.daily_standup,
        _research_tools.log_prediction,
        _research_tools.check_predictions,
        _research_tools.resolve_prediction,
    ]
    RESEARCH_ALLOWED = [f"mcp__friday__{t.name}" for t in RESEARCH_TOOLS]
except Exception as _e:
    print(f"[tools] research module unavailable — core FRIDAY will still run: {_e}")
    RESEARCH_TOOLS = []
    RESEARCH_ALLOWED = []


ALLOWED_TOOL_NAMES = CORE_ALLOWED + RESEARCH_ALLOWED


def build_server():
    return create_sdk_mcp_server(
        name="friday",
        version="1.0.0",
        tools=CORE_TOOLS + RESEARCH_TOOLS,
    )
