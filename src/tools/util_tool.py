"""Utility tools for FRIDAY. Currently: ``get_time``."""

from __future__ import annotations

from datetime import datetime

from claude_agent_sdk import tool


@tool("get_time", "Return the current local time in ISO 8601 format.", {})
async def get_time(_args):
    now = datetime.now().isoformat(timespec="seconds")
    return {"content": [{"type": "text", "text": now}]}
