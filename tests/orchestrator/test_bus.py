from pathlib import Path
import json
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
