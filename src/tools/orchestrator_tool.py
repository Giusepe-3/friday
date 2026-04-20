"""Orchestrator tools: thin MCP wrappers over `src.orchestrator.tools.*_impl`.

Registered with the `friday` MCP server as `mcp__friday__dispatch_task` etc.
Each wrapper pulls the worker-cfg dict and WorkerManager from `src.tools.state`
(populated by main at startup) and forwards to the pure-logic impl.

Phase 4 plumbs `state.cfg.workers` + `state.worker_manager`; until then the
`_require_orchestrator` guard returns a graceful error to the model."""

from __future__ import annotations

import dataclasses
import json

from claude_agent_sdk import tool

from src.orchestrator import tools as orchestrator_tools
from .state import get as state_get


def _require_orchestrator(need_manager: bool = False):
    """Return (workers_cfg, manager_or_None, None) or (None, None, error_payload)."""
    s = state_get()
    workers_cfg_raw = getattr(s.cfg, "workers", None) if s.cfg is not None else None
    if workers_cfg_raw is None:
        return None, None, {"content": [{"type": "text", "text": "orchestrator not initialised: workers config missing"}]}
    # Convert dataclass values (WorkerConfig) to plain dicts so Phase 3 impls can subscript.
    workers_cfg = {
        k: (dataclasses.asdict(v) if dataclasses.is_dataclass(v) and not isinstance(v, type) else v)
        for k, v in workers_cfg_raw.items()
    }
    if need_manager:
        manager = getattr(s, "worker_manager", None)
        if manager is None:
            return None, None, {"content": [{"type": "text", "text": "orchestrator not initialised: worker manager missing"}]}
        return workers_cfg, manager, None
    return workers_cfg, None, None


def _ok(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


@tool(
    "dispatch_task",
    "Dispatch a task to a project worker. Spawns the worker if not running. "
    "`model` and `effort` override per-project defaults; `scope_files` is an "
    "optional list of paths the worker is restricted to.",
    {"project": str, "task": str, "model": str, "effort": str, "scope_files": list},
)
async def dispatch_task(args):
    workers_cfg, manager, err = _require_orchestrator(need_manager=True)
    if err:
        return err
    try:
        out = orchestrator_tools.dispatch_task_impl(
            cfg=workers_cfg, manager=manager,
            project=args["project"], task=args["task"],
            model=args.get("model"), effort=args.get("effort"),
            scope_files=args.get("scope_files"),
        )
    except Exception as e:
        return _err(f"dispatch_task failed: {e}")
    return _ok(out)


@tool(
    "query_worker",
    "Return the current state and recent outbox events for a project worker.",
    {"project": str},
)
async def query_worker(args):
    workers_cfg, _, err = _require_orchestrator()
    if err:
        return err
    try:
        out = orchestrator_tools.query_worker_impl(cfg=workers_cfg, project=args["project"])
    except Exception as e:
        return _err(f"query_worker failed: {e}")
    return _ok(out)


@tool(
    "list_workers",
    "List all configured project workers with their current status.",
    {},
)
async def list_workers(_args):
    workers_cfg, _, err = _require_orchestrator()
    if err:
        return err
    try:
        out = orchestrator_tools.list_workers_impl(cfg=workers_cfg)
    except Exception as e:
        return _err(f"list_workers failed: {e}")
    return _ok(out)


@tool(
    "pop_checkpoint_request",
    "Return the oldest pending checkpoint request. If `project` is omitted, "
    "scan all projects and return the oldest overall.",
    {"project": str},
)
async def pop_checkpoint_request(args):
    workers_cfg, _, err = _require_orchestrator()
    if err:
        return err
    try:
        out = orchestrator_tools.pop_checkpoint_request_impl(
            cfg=workers_cfg, project=args.get("project"),
        )
    except Exception as e:
        return _err(f"pop_checkpoint_request failed: {e}")
    return _ok(out)


@tool(
    "approve_checkpoint",
    "Approve or deny a pending checkpoint request. `decision` must be "
    "'approve' or 'deny'; `reason` is an optional note back to the worker.",
    {"project": str, "checkpoint_id": str, "decision": str, "reason": str},
)
async def approve_checkpoint(args):
    workers_cfg, _, err = _require_orchestrator()
    if err:
        return err
    try:
        out = orchestrator_tools.approve_checkpoint_impl(
            cfg=workers_cfg,
            project=args["project"],
            checkpoint_id=args["checkpoint_id"],
            decision=args["decision"],
            reason=args.get("reason", ""),
        )
    except Exception as e:
        return _err(f"approve_checkpoint failed: {e}")
    return _ok(out)


@tool(
    "recent_outbox",
    "Return recent outbox events for a project worker. `limit` caps count; "
    "`types` optionally filters to listed event types (e.g. ['pulse','finding']).",
    {"project": str, "limit": int, "types": list},
)
async def recent_outbox(args):
    workers_cfg, _, err = _require_orchestrator()
    if err:
        return err
    try:
        out = orchestrator_tools.recent_outbox_impl(
            cfg=workers_cfg,
            project=args["project"],
            limit=int(args.get("limit") or 10),
            types=args.get("types"),
        )
    except Exception as e:
        return _err(f"recent_outbox failed: {e}")
    return _ok(out)


@tool(
    "pause_worker",
    "Send a pause signal to a project worker via its inbox.",
    {"project": str},
)
async def pause_worker(args):
    workers_cfg, _, err = _require_orchestrator()
    if err:
        return err
    try:
        out = orchestrator_tools.pause_worker_impl(cfg=workers_cfg, project=args["project"])
    except Exception as e:
        return _err(f"pause_worker failed: {e}")
    return _ok(out)


@tool(
    "resume_worker",
    "Send a resume signal to a paused project worker via its inbox.",
    {"project": str},
)
async def resume_worker(args):
    workers_cfg, _, err = _require_orchestrator()
    if err:
        return err
    try:
        out = orchestrator_tools.resume_worker_impl(cfg=workers_cfg, project=args["project"])
    except Exception as e:
        return _err(f"resume_worker failed: {e}")
    return _ok(out)


@tool(
    "kill_worker",
    "Terminate a project worker process immediately.",
    {"project": str},
)
async def kill_worker(args):
    workers_cfg, manager, err = _require_orchestrator(need_manager=True)
    if err:
        return err
    try:
        out = orchestrator_tools.kill_worker_impl(
            cfg=workers_cfg, manager=manager, project=args["project"],
        )
    except Exception as e:
        return _err(f"kill_worker failed: {e}")
    return _ok(out)


ORCHESTRATOR_TOOLS = [
    dispatch_task,
    query_worker,
    list_workers,
    pop_checkpoint_request,
    approve_checkpoint,
    recent_outbox,
    pause_worker,
    resume_worker,
    kill_worker,
]
