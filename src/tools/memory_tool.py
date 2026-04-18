"""Memory tools. Currently just ``remember_fact``.

Recall is not a tool: the last 7 days and full facts.md are injected into
the system prompt, so Claude can reference them directly."""

from __future__ import annotations

from claude_agent_sdk import tool

from .state import get


@tool(
    "remember_fact",
    "Save a durable fact about the user to facts.md so it persists across sessions.",
    {"key": str, "value": str},
)
async def remember_fact(args):
    state = get()
    if state.memory is None:
        return {"content": [{"type": "text", "text": "memory not initialised"}]}
    state.memory.append_fact(args["key"], args["value"])
    return {"content": [{"type": "text", "text": "remembered"}]}
