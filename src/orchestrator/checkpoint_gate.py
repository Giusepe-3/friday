"""Build the `can_use_tool` callback the worker passes to ClaudeAgentOptions.

Halt rules (first match wins):
  1. Bash command matches `bash_regex` (per-task config).
  2. Bash command matches `universal_regex` (always-on, cannot be disabled).
  3. File-write tool (Write/Edit) targets a path outside `scope_files` if scope_files set.

Halt path: write checkpoint to bus.checkpoints/, poll inbox for matching
checkpoint_decision, archive on resolution. Timeout → deny + error.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from .bus import WorkerBus


CanUseToolFn = Callable[[str, dict, Any], Awaitable[Any]]

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}


def _bash_command(tool_input: dict) -> str:
    return str(tool_input.get("command", ""))


def _write_target(tool_name: str, tool_input: dict) -> str | None:
    if tool_name not in WRITE_TOOLS:
        return None
    return tool_input.get("file_path") or tool_input.get("notebook_path")


def build_checkpoint_gate(
    bus: WorkerBus,
    bash_regex: list[str],
    universal_regex: list[str],
    scope_files: list[str] | None = None,
    task_id: str | None = None,
    decision_poll_interval_s: float = 1.0,
    decision_timeout_s: float = 3600.0,
) -> CanUseToolFn:
    """Construct the `can_use_tool` callback for one worker task.

    `task_id` is captured in closure (the SDK's context dict does not carry
    a worker-side task id — we know it because we built the gate inside
    _run_task with the active task_id in scope).
    """
    extra_compiled = [re.compile(p) for p in bash_regex]
    universal_compiled = [re.compile(p) for p in universal_regex]
    scope_set = set(scope_files) if scope_files else None
    captured_task_id = task_id

    async def can_use_tool(tool_name: str, tool_input: dict, context: Any) -> Any:
        reason: str | None = None
        if tool_name == "Bash":
            cmd = _bash_command(tool_input)
            if any(p.search(cmd) for p in universal_compiled):
                reason = "universal-trigger"
            elif any(p.search(cmd) for p in extra_compiled):
                reason = "configured-trigger"
        if reason is None:
            wt = _write_target(tool_name, tool_input)
            if wt is not None and scope_set is not None and wt not in scope_set:
                reason = "out-of-scope-write"
        if reason is None:
            return PermissionResultAllow(updated_input=tool_input)

        # Halt and request approval
        ck_id = f"ck-{uuid.uuid4()}"
        ctx_repr: dict[str, Any] = {}
        if context is not None:
            # ToolPermissionContext is a dataclass; also tolerate plain dict (tests).
            if isinstance(context, dict):
                ctx_repr = dict(context)
            else:
                for attr in ("tool_use_id", "agent_id", "suggestions"):
                    val = getattr(context, attr, None)
                    if val is not None:
                        ctx_repr[attr] = str(val) if attr != "suggestions" else [str(s) for s in (val or [])]
        bus.write_checkpoint({
            "id": ck_id,
            "task_id": captured_task_id,
            "tool": tool_name,
            "command": _bash_command(tool_input) if tool_name == "Bash" else None,
            "file_path": _write_target(tool_name, tool_input),
            "reason": reason,
            "context": ctx_repr,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        decision = await _await_decision(
            bus, ck_id,
            poll_interval_s=decision_poll_interval_s,
            timeout_s=decision_timeout_s,
        )
        if decision is None:
            bus.archive_checkpoint(ck_id, decision="deny", reason="timeout")
            return PermissionResultDeny(message=f"checkpoint timeout after {decision_timeout_s}s")
        verdict, message = decision
        bus.archive_checkpoint(ck_id, decision=verdict, reason=message)
        if verdict == "approve":
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=message or "denied")

    return can_use_tool


async def _await_decision(
    bus: WorkerBus,
    ck_id: str,
    poll_interval_s: float,
    timeout_s: float,
) -> tuple[str, str] | None:
    """Poll inbox for checkpoint_decision matching ck_id. Returns (verdict, reason) or None on timeout."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        msg = bus.pop_inbox(allowed_types={"checkpoint_decision"})
        if msg is not None and msg.get("checkpoint_id") == ck_id:
            body = (msg.get("body") or "").strip()
            verdict_line, _, rest = body.partition("\n")
            verdict = verdict_line.strip().lower()
            if verdict not in {"approve", "deny"}:
                verdict = "deny"
            return verdict, rest.strip()
        if msg is not None:
            # Wrong ckpt id — push back to inbox END so we don't lose it
            bus.append_inbox({k: v for k, v in msg.items() if k != "body"}, body=msg.get("body", ""))
        await asyncio.sleep(poll_interval_s)
    return None
