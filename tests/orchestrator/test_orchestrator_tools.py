"""Unit tests for orchestrator MCP tool *implementations* (not MCP wiring).

Each tool is a thin function over WorkerBus / WorkerManager. Tests use
real WorkerBus on tmp dirs, plus a fake WorkerManager that records calls
without spawning subprocesses.
"""
from pathlib import Path

import pytest

from src.orchestrator.bus import WorkerBus
from src.orchestrator.tools import (
    dispatch_task_impl, query_worker_impl, list_workers_impl,
    pop_checkpoint_request_impl, approve_checkpoint_impl, recent_outbox_impl,
    pause_worker_impl, resume_worker_impl, kill_worker_impl,
)


class FakeManager:
    def __init__(self, cfg: dict, running: set[str] | None = None) -> None:
        self.cfg = cfg
        self.running = running or set()
        self.spawn_calls: list[str] = []
        self.kill_calls: list[str] = []

    def is_running(self, project: str) -> bool:
        return project in self.running

    def spawn(self, project: str) -> None:
        self.spawn_calls.append(project)
        self.running.add(project)

    def kill(self, project: str) -> None:
        self.kill_calls.append(project)
        self.running.discard(project)


@pytest.fixture
def two_worker_cfg(tmp_path: Path) -> dict:
    return {
        "alpha": {"repo": tmp_path / "alpha", "default_model": "claude-opus-4-7", "default_effort": "high"},
        "beta": {"repo": tmp_path / "beta", "default_model": "claude-opus-4-7", "default_effort": "high"},
    }


def test_dispatch_task_writes_inbox_and_returns_id(two_worker_cfg) -> None:
    mgr = FakeManager(two_worker_cfg, running={"alpha"})
    out = dispatch_task_impl(
        cfg=two_worker_cfg, manager=mgr,
        project="alpha", task="do thing", model="opus", effort="max",
    )
    assert "task_id" in out
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    msg = bus.pop_inbox()
    assert msg["type"] == "task"
    assert msg["model"] == "claude-opus-4-7"
    assert msg["effort"] == "max"
    assert msg["body"].strip() == "do thing"


def test_dispatch_task_spawns_if_not_running(two_worker_cfg) -> None:
    mgr = FakeManager(two_worker_cfg, running=set())
    dispatch_task_impl(cfg=two_worker_cfg, manager=mgr, project="alpha", task="x")
    assert mgr.spawn_calls == ["alpha"]


def test_dispatch_unknown_project_raises(two_worker_cfg) -> None:
    mgr = FakeManager(two_worker_cfg)
    with pytest.raises(KeyError):
        dispatch_task_impl(cfg=two_worker_cfg, manager=mgr, project="ghost", task="x")


def test_query_worker_returns_state_and_recent_events(two_worker_cfg) -> None:
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    bus.write_state(project="alpha", status="working", current_task="x", last_log_line="line1")
    bus.append_outbox({"type": "ack", "task_id": "t1"})
    bus.append_outbox({"type": "pulse", "status": "working"})
    out = query_worker_impl(cfg=two_worker_cfg, project="alpha")
    assert out["state"]["status"] == "working"
    assert out["state"]["last_log_line"] == "line1"
    assert len(out["recent_events"]) >= 2


def test_list_workers_returns_one_line_per_project(two_worker_cfg) -> None:
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    bus.write_state(project="alpha", status="idle")
    out = list_workers_impl(cfg=two_worker_cfg)
    assert len(out["workers"]) == 2
    statuses = {w["project"]: w["status"] for w in out["workers"]}
    assert statuses["alpha"] == "idle"
    assert statuses["beta"] in ("not_running", "idle")


def test_pop_checkpoint_request_specific_project(two_worker_cfg) -> None:
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    bus.write_checkpoint({
        "id": "ck1", "task_id": "t", "tool": "Bash",
        "command": "git commit", "reason": "x", "created_at": "2026-04-19T01:00:00",
    })
    out = pop_checkpoint_request_impl(cfg=two_worker_cfg, project="alpha")
    assert out["checkpoint"]["id"] == "ck1"
    assert out["project"] == "alpha"


def test_pop_checkpoint_any_project(two_worker_cfg) -> None:
    busb = WorkerBus(two_worker_cfg["beta"]["repo"] / ".friday")
    busb.write_checkpoint({
        "id": "ckb", "task_id": "t", "tool": "Bash",
        "command": "git commit", "reason": "x", "created_at": "2026-04-19T01:00:00",
    })
    out = pop_checkpoint_request_impl(cfg=two_worker_cfg, project=None)
    assert out["checkpoint"]["id"] == "ckb"
    assert out["project"] == "beta"


def test_pop_checkpoint_none_when_no_pending(two_worker_cfg) -> None:
    out = pop_checkpoint_request_impl(cfg=two_worker_cfg, project=None)
    assert out["checkpoint"] is None


def test_approve_checkpoint_writes_inbox(two_worker_cfg) -> None:
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    bus.write_checkpoint({
        "id": "ck1", "task_id": "t", "tool": "Bash",
        "command": "git commit", "reason": "x", "created_at": "2026-04-19T01:00:00",
    })
    out = approve_checkpoint_impl(
        cfg=two_worker_cfg, project="alpha", checkpoint_id="ck1",
        decision="approve", reason="looks good",
    )
    assert out["acknowledged"] is True
    msg = bus.pop_inbox(allowed_types={"checkpoint_decision"})
    assert msg["type"] == "checkpoint_decision"
    assert msg["checkpoint_id"] == "ck1"
    assert msg["body"].startswith("approve")
    assert "looks good" in msg["body"]


def test_recent_outbox_filters_by_type(two_worker_cfg) -> None:
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    bus.append_outbox({"type": "ack", "task_id": "a"})
    bus.append_outbox({"type": "pulse"})
    bus.append_outbox({"type": "task_complete", "task_id": "a", "summary": "done"})
    out = recent_outbox_impl(cfg=two_worker_cfg, project="alpha", limit=10, types=["task_complete"])
    assert len(out["events"]) == 1
    assert out["events"][0]["type"] == "task_complete"


def test_pause_resume_emit_inbox_messages(two_worker_cfg) -> None:
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    pause_worker_impl(cfg=two_worker_cfg, project="alpha")
    msg = bus.pop_inbox()
    assert msg["type"] == "pause"
    resume_worker_impl(cfg=two_worker_cfg, project="alpha")
    msg2 = bus.pop_inbox()
    assert msg2["type"] == "resume"


def test_kill_worker_calls_manager(two_worker_cfg) -> None:
    mgr = FakeManager(two_worker_cfg, running={"alpha"})
    kill_worker_impl(cfg=two_worker_cfg, manager=mgr, project="alpha")
    assert mgr.kill_calls == ["alpha"]
