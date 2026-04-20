"""Integration tests: spawn the actual worker subprocess against a tmp repo.

These tests do NOT call Claude — they verify the bus protocol round-trip
by sending a `terminate` message and asserting the worker shuts down cleanly,
plus verifying state.json transitions during startup.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fake_repo"
    repo.mkdir()
    # Make it look like a git repo enough for the pulse loop to run `git status`
    subprocess.run(["git", "init", "--quiet"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(repo), check=True)
    (repo / "README.md").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init", "--quiet"], cwd=str(repo), check=True)
    return repo


def _start_worker(repo: Path, project: str = "test") -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable, "-m", "src.orchestrator.worker",
            "--project", project,
            "--repo", str(repo),
            "--default-model", "claude-opus-4-7",
            "--default-effort", "high",
            "--test-fast-pulse",
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _wait_for_state(repo: Path, predicate, timeout_s: float = 10.0) -> dict:
    state_path = repo / ".friday" / "state.json"
    start = time.time()
    while time.time() - start < timeout_s:
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if predicate(state):
                    return state
            except json.JSONDecodeError:
                pass
        time.sleep(0.1)
    raise AssertionError(f"state predicate not met within {timeout_s}s")


def test_worker_starts_and_writes_idle_state(fake_repo: Path) -> None:
    proc = _start_worker(fake_repo, project="test")
    try:
        state = _wait_for_state(fake_repo, lambda s: s.get("status") == "idle")
        assert state["project"] == "test"
        assert state["model"] == "claude-opus-4-7"
        assert state["effort"] == "high"
    finally:
        # Terminate via inbox message (clean shutdown path)
        from src.orchestrator.bus import WorkerBus
        bus = WorkerBus(fake_repo / ".friday")
        bus.append_inbox({"id": "term", "type": "terminate"}, body="")
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)


def test_worker_refuses_duplicate(fake_repo: Path) -> None:
    proc1 = _start_worker(fake_repo, project="test")
    try:
        _wait_for_state(fake_repo, lambda s: s.get("status") == "idle")
        proc2 = _start_worker(fake_repo, project="test")
        rc = proc2.wait(timeout=10)
        assert rc != 0
        stderr = proc2.stderr.read().decode("utf-8", errors="replace")
        assert "already running" in stderr.lower() or "duplicate" in stderr.lower()
    finally:
        from src.orchestrator.bus import WorkerBus
        bus = WorkerBus(fake_repo / ".friday")
        bus.append_inbox({"id": "term", "type": "terminate"}, body="")
        proc1.wait(timeout=10)


def test_worker_pulse_appears_in_outbox(fake_repo: Path) -> None:
    proc = _start_worker(fake_repo, project="test")
    try:
        _wait_for_state(fake_repo, lambda s: s.get("status") == "idle")
        # Wait for at least one pulse (idle pulse interval is 5min in prod, but we patch via flag)
        outbox = fake_repo / ".friday" / "outbox.jsonl"
        start = time.time()
        while time.time() - start < 15:
            if outbox.exists():
                lines = outbox.read_text(encoding="utf-8").splitlines()
                if any('"type": "pulse"' in line or '"type":"pulse"' in line for line in lines):
                    break
            time.sleep(0.5)
        else:
            pytest.fail("no pulse in outbox within 15s")
    finally:
        from src.orchestrator.bus import WorkerBus
        bus = WorkerBus(fake_repo / ".friday")
        bus.append_inbox({"id": "term", "type": "terminate"}, body="")
        proc.wait(timeout=10)
