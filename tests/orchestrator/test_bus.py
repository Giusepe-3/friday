from pathlib import Path
import json
import os
import tempfile
from src.orchestrator.bus import _atomic_write_text, WorkerBus


def test_atomic_write_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    _atomic_write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_atomic_write_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "x.txt"
    target.write_text("first")
    _atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"


def test_atomic_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "x.txt"
    _atomic_write_text(target, "deep")
    assert target.read_text(encoding="utf-8") == "deep"


def test_workerbus_creates_layout(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.ensure_layout()
    assert (tmp_path / ".friday").is_dir()
    assert (tmp_path / ".friday" / "checkpoints").is_dir()
    assert (tmp_path / ".friday" / "checkpoints" / "resolved").is_dir()
    assert (tmp_path / ".friday" / "logs").is_dir()


def test_state_default(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    assert bus.read_state() == {}


def test_state_write_then_read(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.write_state(project="paper", status="idle", model="claude-opus-4-7")
    state = bus.read_state()
    assert state["project"] == "paper"
    assert state["status"] == "idle"
    assert state["model"] == "claude-opus-4-7"


def test_state_partial_update_preserves_other_fields(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.write_state(project="paper", status="idle", model="claude-opus-4-7")
    bus.write_state(status="working", current_task="x")
    state = bus.read_state()
    assert state["project"] == "paper"           # preserved
    assert state["model"] == "claude-opus-4-7"   # preserved
    assert state["status"] == "working"          # updated
    assert state["current_task"] == "x"          # added


def test_outbox_append_then_tail(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.append_outbox({"type": "ack", "task_id": "abc"})
    bus.append_outbox({"type": "pulse", "status": "working"})
    events = bus.tail_outbox(limit=10)
    assert len(events) == 2
    assert events[0]["type"] == "ack"
    assert events[1]["type"] == "pulse"
    # ts auto-injected
    assert "ts" in events[0]


def test_outbox_tail_limit(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    for i in range(5):
        bus.append_outbox({"type": "pulse", "i": i})
    events = bus.tail_outbox(limit=2)
    assert len(events) == 2
    assert events[0]["i"] == 3
    assert events[1]["i"] == 4


def test_outbox_tail_filter_by_type(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.append_outbox({"type": "ack", "task_id": "a"})
    bus.append_outbox({"type": "pulse"})
    bus.append_outbox({"type": "ack", "task_id": "b"})
    events = bus.tail_outbox(limit=10, types=["ack"])
    assert len(events) == 2
    assert all(e["type"] == "ack" for e in events)


def test_outbox_skips_malformed_lines(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.ensure_layout()
    # Manually write a corrupt line
    bus.outbox_path.write_text(
        '{"type":"ack","task_id":"a","ts":"x"}\n'
        "this is not json\n"
        '{"type":"pulse","ts":"y"}\n',
        encoding="utf-8",
    )
    events = bus.tail_outbox(limit=10)
    assert len(events) == 2
    assert events[0]["type"] == "ack"
    assert events[1]["type"] == "pulse"


def test_inbox_pop_empty(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    assert bus.pop_inbox() is None


def test_inbox_pop_single_block(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.ensure_layout()
    bus.inbox_path.write_text(
        "---\n"
        "id: abc-123\n"
        "type: task\n"
        "model: claude-opus-4-7\n"
        "effort: high\n"
        "---\n"
        "Polish §3 of the paper.\n",
        encoding="utf-8",
    )
    msg = bus.pop_inbox()
    assert msg is not None
    assert msg["id"] == "abc-123"
    assert msg["type"] == "task"
    assert msg["model"] == "claude-opus-4-7"
    assert msg["effort"] == "high"
    assert msg["body"].strip() == "Polish §3 of the paper."
    # Inbox now empty
    assert bus.pop_inbox() is None


def test_inbox_pop_multiple_blocks_returns_oldest(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.ensure_layout()
    bus.inbox_path.write_text(
        "---\nid: first\ntype: task\n---\nfirst body\n"
        "---\nid: second\ntype: task\n---\nsecond body\n",
        encoding="utf-8",
    )
    msg1 = bus.pop_inbox()
    assert msg1["id"] == "first"
    msg2 = bus.pop_inbox()
    assert msg2["id"] == "second"
    assert bus.pop_inbox() is None


def test_inbox_pop_with_filter_skips_non_matching(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.ensure_layout()
    bus.inbox_path.write_text(
        "---\nid: t1\ntype: task\n---\nbody\n"
        "---\nid: c1\ntype: checkpoint_decision\n---\napprove\n",
        encoding="utf-8",
    )
    # Caller wants only checkpoint_decision; task block stays in inbox
    msg = bus.pop_inbox(allowed_types={"checkpoint_decision"})
    assert msg["id"] == "c1"
    # Now task block should still be there
    msg2 = bus.pop_inbox()
    assert msg2["id"] == "t1"


def test_inbox_pop_skips_malformed_block(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.ensure_layout()
    bus.inbox_path.write_text(
        "---\nnot valid yaml: [oops\n---\nbody1\n"
        "---\nid: good\ntype: task\n---\nbody2\n",
        encoding="utf-8",
    )
    msg = bus.pop_inbox()
    assert msg["id"] == "good"


def test_append_inbox_then_pop_round_trip(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.append_inbox({"id": "x1", "type": "task", "model": "claude-opus-4-7"}, body="do thing")
    msg = bus.pop_inbox()
    assert msg["id"] == "x1"
    assert msg["body"].strip() == "do thing"


def test_write_checkpoint(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    ckpt = {"id": "ck1", "task_id": "t1", "tool": "Bash", "command": "git commit", "reason": "x"}
    bus.write_checkpoint(ckpt)
    assert (tmp_path / ".friday" / "checkpoints" / "ck1.json").exists()
    loaded = json.loads((tmp_path / ".friday" / "checkpoints" / "ck1.json").read_text())
    assert loaded["id"] == "ck1"


def test_archive_checkpoint(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.write_checkpoint({"id": "ck1", "task_id": "t1", "tool": "Bash", "command": "git commit", "reason": "x"})
    bus.archive_checkpoint("ck1", decision="approve")
    assert not (tmp_path / ".friday" / "checkpoints" / "ck1.json").exists()
    archived = tmp_path / ".friday" / "checkpoints" / "resolved" / "ck1.json"
    assert archived.exists()
    loaded = json.loads(archived.read_text())
    assert loaded["decision"] == "approve"


def test_list_pending_checkpoints(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.write_checkpoint({"id": "ck1", "task_id": "t", "tool": "Bash", "command": "x", "reason": "y"})
    bus.write_checkpoint({"id": "ck2", "task_id": "t", "tool": "Bash", "command": "z", "reason": "y"})
    pending = bus.list_pending_checkpoints()
    ids = sorted(c["id"] for c in pending)
    assert ids == ["ck1", "ck2"]


def test_pid_round_trip(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    bus.write_pid(12345)
    assert bus.read_pid() == 12345
    bus.clear_pid()
    assert bus.read_pid() is None
