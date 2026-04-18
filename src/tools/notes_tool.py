"""Dictation notes — append-only markdown with ``HH:MM`` timestamps."""

from __future__ import annotations

from datetime import datetime

from claude_agent_sdk import tool

from .state import get


@tool(
    "write_note",
    "Append a timestamped note to ~/friday/notes.md.",
    {"content": str},
)
async def write_note(args):
    state = get()
    content = args["content"].strip()
    if not content:
        return {"content": [{"type": "text", "text": "empty note, skipped"}]}
    now = datetime.now()
    line = f"- [{now.strftime('%H:%M')}] {content}\n"
    path = state.cfg.paths.notes
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    return {"content": [{"type": "text", "text": "noted"}]}
