"""FRIDAY-side worker process management.

Spawns workers as subprocesses, tracks them by project key, kills cleanly
on shutdown. Survives FRIDAY-side bugs by using the bus's pidfile as
authoritative — `is_running` checks both the tracked Popen handle AND the
on-disk PID.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from .bus import WorkerBus


class WorkerManager:
    def __init__(self, workers_cfg: dict, test_fast_pulse: bool = False) -> None:
        self.cfg = workers_cfg
        self.test_fast_pulse = test_fast_pulse
        self._procs: dict[str, subprocess.Popen] = {}

    def spawn(self, project: str) -> None:
        if project not in self.cfg:
            raise KeyError(f"unknown project: {project}")
        if self.is_running(project):
            return
        w = self.cfg[project]
        cmd = [
            sys.executable, "-m", "src.orchestrator.worker",
            "--project", project,
            "--repo", str(w["repo"]),
            "--default-model", str(w["default_model"]),
            "--default-effort", str(w["default_effort"]),
        ]
        for r in w.get("bash_regex", []):
            cmd.extend(["--bash-regex", r])
        if self.test_fast_pulse:
            cmd.append("--test-fast-pulse")
        proc = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).resolve().parents[2]),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self._procs[project] = proc

    def is_running(self, project: str) -> bool:
        proc = self._procs.get(project)
        if proc is not None and proc.poll() is None:
            return True
        # Fall back to pidfile (covers FRIDAY restart while worker survived)
        if project not in self.cfg:
            return False
        bus = WorkerBus(Path(self.cfg[project]["repo"]) / ".friday")
        pid = bus.read_pid()
        if pid is None:
            return False
        return _pid_alive(pid)

    def kill(self, project: str) -> None:
        proc = self._procs.pop(project, None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            return
        # Try pidfile-based kill (worker survived FRIDAY restart)
        if project not in self.cfg:
            return
        bus = WorkerBus(Path(self.cfg[project]["repo"]) / ".friday")
        pid = bus.read_pid()
        if pid and _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def kill_all(self) -> None:
        for project in list(self._procs.keys()):
            self.kill(project)
        for project in self.cfg.keys():
            if self.is_running(project):
                self.kill(project)


def _pid_alive(pid: int) -> bool:
    # os.kill(pid, 0) is the portable liveness probe, but on Windows CPython
    # can surface a SystemError when the underlying handle reports an
    # unexpected exit code — treat any raised exception as "not alive" since
    # a healthy live process returns cleanly.
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False
