"""Daily briefing reader — returns the text of ~/friday/today.md."""

from __future__ import annotations

from claude_agent_sdk import tool

from .state import get


@tool(
    "read_briefing",
    "Read today's briefing from ~/friday/today.md so FRIDAY can speak it.",
    {},
)
async def read_briefing(_args):
    state = get()
    path = state.cfg.paths.today
    if not path.exists():
        return {"content": [{"type": "text", "text": "no briefing for today"}]}
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        return {"content": [{"type": "text", "text": "briefing file is empty"}]}
    return {"content": [{"type": "text", "text": body}]}
