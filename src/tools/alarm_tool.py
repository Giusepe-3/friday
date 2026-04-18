"""Alarm tools: set, cancel, list. Natural-language times via dateparser."""

from __future__ import annotations

import dateparser
from claude_agent_sdk import tool

from .state import get


def _require_scheduler():
    sch = get().scheduler
    if sch is None:
        return None, {"content": [{"type": "text", "text": "scheduler not running"}]}
    return sch, None


@tool(
    "set_alarm",
    (
        "Set an alarm. `when` accepts natural language such as "
        "'7:30 tomorrow' or 'in 15 minutes'. `label` is what FRIDAY will "
        "speak when the alarm fires."
    ),
    {"when": str, "label": str},
)
async def set_alarm(args):
    sch, err = _require_scheduler()
    if err:
        return err
    when_str = args["when"]
    label = args["label"].strip() or "alarm"
    dt = dateparser.parse(when_str, settings={"PREFER_DATES_FROM": "future"})
    if dt is None:
        return {
            "content": [
                {"type": "text", "text": f"could not parse time: {when_str}"}
            ]
        }
    aid = sch.set(dt, label)
    pretty = dt.strftime("%a %H:%M")
    return {
        "content": [
            {"type": "text", "text": f"alarm {aid} set for {pretty}: {label}"}
        ]
    }


@tool("cancel_alarm", "Cancel an alarm by its id.", {"id": str})
async def cancel_alarm(args):
    sch, err = _require_scheduler()
    if err:
        return err
    ok = sch.cancel(args["id"])
    return {
        "content": [
            {"type": "text", "text": "cancelled" if ok else "no alarm with that id"}
        ]
    }


@tool("list_alarms", "List all pending alarms.", {})
async def list_alarms(_args):
    sch, err = _require_scheduler()
    if err:
        return err
    items = sch.list()
    if not items:
        return {"content": [{"type": "text", "text": "no alarms"}]}
    lines = [
        f"{a['id']}: {a['when']} — {a['label']}" for a in items
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}
