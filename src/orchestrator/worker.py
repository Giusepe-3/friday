"""Per-project worker harness.

One worker = one Python process pinned to one repo. Holds a
ClaudeSDKClient (one query() per task — fresh client per task is simpler
than mutating model/effort on a long-lived client). Halts on checkpoint
triggers via can_use_tool callback. Communicates exclusively via
<repo>/.friday/.

Run: python -m src.orchestrator.worker --project paper --repo /path
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

from .bus import WorkerBus
from .checkpoint_gate import build_checkpoint_gate
from .models import resolve_effort, resolve_model


UNIVERSAL_BASH_REGEX = [
    r"^git push",
    r"runpod",
    r"wandb init",
    r"bash setup_.*pod",
    r"gcloud compute",
    r"aws ec2 run",
]


class WorkerStop(Exception):
    """Raised internally to break the main loop on terminate inbox message."""


async def _pulse_loop(
    bus: WorkerBus,
    repo: Path,
    pulse_working_s: float,
    pulse_idle_s: float,
    state_ref: dict,
) -> None:
    while True:
        status = state_ref.get("status", "idle")
        interval = pulse_working_s if status == "working" else pulse_idle_s
        await asyncio.sleep(interval)
        git_info = _git_status(repo)
        bus.append_outbox({
            "type": "pulse",
            "status": status,
            "current_task_id": state_ref.get("current_task_id"),
            "last_log_line": state_ref.get("last_log_line"),
            "git": git_info,
        })
        bus.write_state(last_pulse_at=datetime.now().isoformat(timespec="seconds"))


def _git_status(repo: Path) -> dict:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo), capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo), capture_output=True, text=True, timeout=5,
        ).stdout.splitlines()
        uncommitted = len([l for l in porcelain if l.strip()])
        ahead_behind = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...@{u}"],
            cwd=str(repo), capture_output=True, text=True, timeout=5,
        ).stdout.strip().split()
        ahead = int(ahead_behind[0]) if len(ahead_behind) >= 1 and ahead_behind[0].isdigit() else 0
        behind = int(ahead_behind[1]) if len(ahead_behind) >= 2 and ahead_behind[1].isdigit() else 0
        return {"branch": branch, "uncommitted": uncommitted, "ahead": ahead, "behind": behind}
    except (subprocess.SubprocessError, OSError, ValueError):
        return {"branch": None, "uncommitted": 0, "ahead": 0, "behind": 0}


async def _inbox_loop(
    bus: WorkerBus,
    repo: Path,
    default_model: str,
    default_effort: str,
    bash_regex: list[str],
    state_ref: dict,
) -> None:
    while True:
        msg = bus.pop_inbox()
        if msg is None:
            await asyncio.sleep(2)
            continue
        msg_type = msg.get("type")
        print(f"[worker] inbox msg: type={msg_type!r} id={msg.get('id')!r}", flush=True)
        if msg_type == "terminate":
            raise WorkerStop()
        if msg_type == "pause":
            state_ref["status"] = "paused"
            bus.write_state(status="paused")
            continue
        if msg_type == "resume":
            state_ref["status"] = "idle"
            bus.write_state(status="idle")
            continue
        if msg_type == "reset":
            # No persistent state to reset since we use one-shot query() per task.
            bus.append_outbox({"type": "ack", "task_id": msg.get("id"), "note": "reset noop"})
            continue
        if msg_type == "task":
            if state_ref.get("status") == "paused":
                # Push back; ignore until resumed
                bus.append_inbox({k: v for k, v in msg.items() if k != "body"}, body=msg.get("body", ""))
                await asyncio.sleep(2)
                continue
            await _run_task(bus, repo, msg, default_model, default_effort, bash_regex, state_ref)
            continue
        # Unknown type — ack with warning
        bus.append_outbox({"type": "error", "error": f"unknown inbox type: {msg_type}"})


async def _run_task(
    bus: WorkerBus,
    repo: Path,
    msg: dict,
    default_model: str,
    default_effort: str,
    bash_regex: list[str],
    state_ref: dict,
) -> None:
    task_id = msg.get("id") or str(uuid.uuid4())
    task_text = (msg.get("body") or "").strip()
    model = resolve_model(msg.get("model") or default_model)
    effort = resolve_effort(msg.get("effort") or default_effort)
    scope_files = msg.get("scope_files") or None
    if isinstance(scope_files, list) and len(scope_files) == 0:
        scope_files = None

    state_ref.update({
        "status": "working",
        "current_task": task_text[:200],
        "current_task_id": task_id,
        "model": model,
        "effort": effort,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    })
    bus.write_state(**state_ref)
    bus.append_outbox({"type": "ack", "task_id": task_id})

    gate = build_checkpoint_gate(
        bus=bus,
        bash_regex=bash_regex,
        universal_regex=UNIVERSAL_BASH_REGEX,
        scope_files=scope_files,
        task_id=task_id,
    )
    options = ClaudeAgentOptions(
        model=model,
        cwd=str(repo),
        permission_mode="default",
        can_use_tool=gate,
        effort=effort,
        setting_sources=["user", "project"],
    )

    summary = ""
    try:
        async with ClaudeSDKClient(options=options) as client:
            await client.query(task_text)
            async for event in client.receive_response():
                if isinstance(event, ResultMessage):
                    summary = getattr(event, "result", "") or summary
        bus.append_outbox({"type": "task_complete", "task_id": task_id, "summary": summary})
        state_ref.update({"status": "idle", "current_task": None, "current_task_id": None})
        bus.write_state(**state_ref)
    except BaseException as e:
        # BaseException so CancelledError / SDK-raised non-Exception errors still land in outbox.
        import traceback
        tb = traceback.format_exc()
        bus.append_outbox({
            "type": "error",
            "task_id": task_id,
            "error": f"{type(e).__name__}: {e}",
            "traceback": tb,
        })
        state_ref["status"] = "error"
        bus.write_state(status="error")
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise


def _check_duplicate_and_claim(bus: WorkerBus) -> None:
    existing = bus.read_pid()
    if existing is not None and _pid_alive(existing):
        print(f"[worker] another worker already running (pid={existing})", file=sys.stderr)
        sys.exit(2)
    if existing is not None:
        # Stale pidfile
        bus.clear_pid()
    bus.write_pid(os.getpid())


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


async def _amain(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"[worker] repo path does not exist: {repo}", file=sys.stderr)
        return 2
    bus = WorkerBus(repo / ".friday")
    bus.ensure_layout()
    _check_duplicate_and_claim(bus)

    default_model = resolve_model(args.default_model)
    default_effort = resolve_effort(args.default_effort)
    bash_regex = list(args.bash_regex or [])

    pulse_working_s = float(os.environ.get("FRIDAY_WORKER_PULSE_WORKING_S", "30"))
    pulse_idle_s = float(os.environ.get("FRIDAY_WORKER_PULSE_IDLE_S", "300"))
    if args.test_fast_pulse:
        pulse_working_s = 1.0
        pulse_idle_s = 1.0

    state_ref: dict = {}
    state_ref.update({
        "project": args.project,
        "status": "idle",
        "model": default_model,
        "effort": default_effort,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    })
    bus.write_state(**state_ref)
    bus.append_outbox({"type": "ack", "note": "worker_started", "project": args.project})
    print(f"[worker] started project={args.project} model={default_model} effort={default_effort}", flush=True)

    pulse_task = asyncio.create_task(
        _pulse_loop(bus, repo, pulse_working_s, pulse_idle_s, state_ref)
    )
    inbox_task = asyncio.create_task(
        _inbox_loop(bus, repo, default_model, default_effort, bash_regex, state_ref)
    )

    stop_event = asyncio.Event()

    def _request_stop(*_a):
        stop_event.set()

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _request_stop)
        loop.add_signal_handler(signal.SIGTERM, _request_stop)
    except (NotImplementedError, AttributeError):
        # Windows: signal.SIGTERM handler not supported via add_signal_handler
        pass

    async def _stop_watcher():
        await stop_event.wait()
        raise WorkerStop()

    stop_task = asyncio.create_task(_stop_watcher())

    try:
        done, pending = await asyncio.wait(
            {inbox_task, stop_task}, return_when=asyncio.FIRST_EXCEPTION
        )
        for t in done:
            exc = t.exception()
            name = "inbox_task" if t is inbox_task else "stop_task"
            print(f"[worker] task {name} finished; exc={type(exc).__name__ if exc else 'None'}: {exc}", flush=True)
            if isinstance(exc, WorkerStop):
                pass
            elif exc is not None:
                raise exc
    except WorkerStop:
        pass
    finally:
        for t in (pulse_task, inbox_task, stop_task):
            t.cancel()
        bus.append_outbox({"type": "terminated", "reason": "shutdown"})
        bus.write_state(status="terminated")
        bus.clear_pid()
        print("[worker] shutdown complete", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FRIDAY orchestrator worker")
    parser.add_argument("--project", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--default-model", default="claude-opus-4-7")
    parser.add_argument("--default-effort", default="high")
    parser.add_argument("--bash-regex", action="append", default=[])
    parser.add_argument("--test-fast-pulse", action="store_true",
                        help="Use 1s pulse intervals for testing")
    args = parser.parse_args(argv)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
