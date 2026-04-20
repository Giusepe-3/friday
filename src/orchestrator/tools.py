"""FRIDAY-side orchestrator tool implementations.

Each `*_impl` function is a pure-logic helper over WorkerBus and (for
spawn/kill) WorkerManager. The MCP wrappers in the next task call these
and serialize results to JSON for FRIDAY's brain.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from .bus import WorkerBus
from .models import resolve_effort, resolve_model


def _bus_for(cfg: dict, project: str) -> WorkerBus:
    if project not in cfg:
        raise KeyError(f"unknown project: {project!r}")
    return WorkerBus(Path(cfg[project]["repo"]) / ".friday")


def dispatch_task_impl(
    cfg: dict, manager, project: str, task: str,
    model: str | None = None, effort: str | None = None,
    scope_files: list[str] | None = None,
) -> dict:
    bus = _bus_for(cfg, project)
    if not manager.is_running(project):
        manager.spawn(project)
    resolved_model = resolve_model(model) if model else resolve_model(cfg[project]["default_model"])
    resolved_effort = resolve_effort(effort) if effort else resolve_effort(cfg[project]["default_effort"])
    task_id = f"task-{uuid.uuid4()}"
    header = {
        "id": task_id,
        "type": "task",
        "model": resolved_model,
        "effort": resolved_effort,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if scope_files:
        header["scope_files"] = list(scope_files)
    bus.append_inbox(header, body=task.strip() + "\n")
    return {"task_id": task_id, "project": project, "model": resolved_model, "effort": resolved_effort}


def query_worker_impl(cfg: dict, project: str, recent_limit: int = 5) -> dict:
    bus = _bus_for(cfg, project)
    state = bus.read_state()
    events = bus.tail_outbox(limit=recent_limit)
    return {"project": project, "state": state, "recent_events": events}


def list_workers_impl(cfg: dict) -> dict:
    out = []
    for project in cfg.keys():
        bus = WorkerBus(Path(cfg[project]["repo"]) / ".friday")
        state = bus.read_state()
        if not state:
            out.append({"project": project, "status": "not_running"})
        else:
            out.append({
                "project": project,
                "status": state.get("status", "unknown"),
                "current_task": state.get("current_task"),
                "last_pulse_at": state.get("last_pulse_at"),
            })
    return {"workers": out}


def pop_checkpoint_request_impl(cfg: dict, project: str | None) -> dict:
    """If project is None, scan all projects and return the oldest checkpoint."""
    candidates: list[tuple[str, dict]] = []
    targets = [project] if project else list(cfg.keys())
    for p in targets:
        if p not in cfg:
            continue
        bus = WorkerBus(Path(cfg[p]["repo"]) / ".friday")
        for ck in bus.list_pending_checkpoints():
            candidates.append((p, ck))
    if not candidates:
        return {"checkpoint": None, "project": None}
    candidates.sort(key=lambda t: t[1].get("created_at", ""))
    p, ck = candidates[0]
    return {"project": p, "checkpoint": ck}


def approve_checkpoint_impl(
    cfg: dict, project: str, checkpoint_id: str,
    decision: str, reason: str = "",
) -> dict:
    if decision not in {"approve", "deny"}:
        raise ValueError(f"decision must be approve|deny, got {decision!r}")
    bus = _bus_for(cfg, project)
    body = decision + ("\n" + reason if reason else "")
    bus.append_inbox(
        {"id": f"dec-{uuid.uuid4()}", "type": "checkpoint_decision", "checkpoint_id": checkpoint_id},
        body=body,
    )
    return {"acknowledged": True, "project": project, "checkpoint_id": checkpoint_id, "decision": decision}


def recent_outbox_impl(
    cfg: dict, project: str, limit: int = 10, types: list[str] | None = None,
) -> dict:
    bus = _bus_for(cfg, project)
    return {"project": project, "events": bus.tail_outbox(limit=limit, types=types)}


def pause_worker_impl(cfg: dict, project: str) -> dict:
    bus = _bus_for(cfg, project)
    bus.append_inbox({"id": f"pause-{uuid.uuid4()}", "type": "pause"}, body="")
    return {"acknowledged": True, "project": project}


def resume_worker_impl(cfg: dict, project: str) -> dict:
    bus = _bus_for(cfg, project)
    bus.append_inbox({"id": f"resume-{uuid.uuid4()}", "type": "resume"}, body="")
    return {"acknowledged": True, "project": project}


def kill_worker_impl(cfg: dict, manager, project: str) -> dict:
    if project not in cfg:
        raise KeyError(f"unknown project: {project!r}")
    manager.kill(project)
    return {"acknowledged": True, "project": project}
