import time
from pathlib import Path

import pytest

from src.orchestrator.manager import WorkerManager
from src.orchestrator.bus import WorkerBus


def _make_repo(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    import subprocess
    subprocess.run(["git", "init", "--quiet"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    (repo / "x").write_text("x")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-m", "init", "--quiet"], cwd=str(repo), check=True)
    return repo


@pytest.fixture
def two_worker_cfg(tmp_path: Path) -> dict:
    return {
        "alpha": {
            "repo": _make_repo(tmp_path, "alpha"),
            "default_model": "claude-opus-4-7",
            "default_effort": "high",
            "bash_regex": [],
        },
        "beta": {
            "repo": _make_repo(tmp_path, "beta"),
            "default_model": "claude-opus-4-7",
            "default_effort": "high",
            "bash_regex": [],
        },
    }


def test_spawn_then_kill(two_worker_cfg) -> None:
    mgr = WorkerManager(two_worker_cfg, test_fast_pulse=True)
    mgr.spawn("alpha")
    # Wait for state.json
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    deadline = time.time() + 10
    while time.time() < deadline:
        state = bus.read_state()
        if state.get("status") == "idle":
            break
        time.sleep(0.2)
    else:
        pytest.fail("worker did not reach idle")
    assert mgr.is_running("alpha")
    mgr.kill("alpha")
    deadline = time.time() + 10
    while time.time() < deadline:
        if not mgr.is_running("alpha"):
            break
        time.sleep(0.2)
    else:
        pytest.fail("worker did not exit after kill")


def test_spawn_idempotent(two_worker_cfg) -> None:
    mgr = WorkerManager(two_worker_cfg, test_fast_pulse=True)
    mgr.spawn("alpha")
    bus = WorkerBus(two_worker_cfg["alpha"]["repo"] / ".friday")
    deadline = time.time() + 10
    while time.time() < deadline:
        if bus.read_state().get("status") == "idle":
            break
        time.sleep(0.2)
    # Second spawn should be no-op (already running)
    mgr.spawn("alpha")
    assert mgr.is_running("alpha")
    mgr.kill("alpha")


def test_kill_all(two_worker_cfg) -> None:
    mgr = WorkerManager(two_worker_cfg, test_fast_pulse=True)
    mgr.spawn("alpha")
    mgr.spawn("beta")
    time.sleep(2)  # let them start
    mgr.kill_all()
    deadline = time.time() + 10
    while time.time() < deadline:
        if not mgr.is_running("alpha") and not mgr.is_running("beta"):
            return
        time.sleep(0.2)
    pytest.fail("workers did not all exit")
