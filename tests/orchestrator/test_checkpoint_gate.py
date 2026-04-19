import asyncio
from pathlib import Path
import pytest
from src.orchestrator.bus import WorkerBus
from src.orchestrator.checkpoint_gate import build_checkpoint_gate


UNIVERSAL_REGEX = [
    r"^git push",
    r"runpod",
    r"wandb init",
    r"bash setup_.*pod",
]


def _gate_for(bus: WorkerBus, extra: list[str] | None = None, scope_files=None, task_id="t1"):
    return build_checkpoint_gate(
        bus=bus,
        bash_regex=extra or [],
        universal_regex=UNIVERSAL_REGEX,
        scope_files=scope_files,
        task_id=task_id,
        decision_poll_interval_s=0.05,
        decision_timeout_s=2,
    )


def test_gate_allows_safe_bash(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    gate = _gate_for(bus, extra=[r"^git commit"])
    result = asyncio.run(gate("Bash", {"command": "ls -la"}, {"task_id": "t1"}))
    assert result == {"behavior": "allow", "updatedInput": {"command": "ls -la"}}


def test_gate_halts_on_extra_regex_then_approve(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    gate = _gate_for(bus, extra=[r"^git commit"])

    async def caller():
        async def approve_after_delay():
            await asyncio.sleep(0.1)
            pending = bus.list_pending_checkpoints()
            assert len(pending) == 1
            bus.append_inbox(
                {"id": "dec1", "type": "checkpoint_decision", "checkpoint_id": pending[0]["id"]},
                body="approve\n",
            )

        gate_task = asyncio.create_task(
            gate("Bash", {"command": "git commit -m x"}, {"task_id": "t1"})
        )
        approve_task = asyncio.create_task(approve_after_delay())
        await approve_task
        return await gate_task

    result = asyncio.run(caller())
    assert result["behavior"] == "allow"
    # Checkpoint archived after resolution
    resolved = list((tmp_path / ".friday" / "checkpoints" / "resolved").glob("*.json"))
    assert len(resolved) == 1


def test_gate_universal_regex_always_halts(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    gate = _gate_for(bus, extra=[])

    async def caller():
        async def deny_after_delay():
            await asyncio.sleep(0.1)
            pending = bus.list_pending_checkpoints()
            bus.append_inbox(
                {"id": "dec1", "type": "checkpoint_decision", "checkpoint_id": pending[0]["id"]},
                body="deny\nnot pushing today",
            )

        gate_task = asyncio.create_task(
            gate("Bash", {"command": "git push origin main"}, {"task_id": "t1"})
        )
        deny_task = asyncio.create_task(deny_after_delay())
        await deny_task
        return await gate_task

    result = asyncio.run(caller())
    assert result["behavior"] == "deny"
    assert "not pushing" in result["message"]


def test_gate_scope_files_blocks_out_of_scope_write(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    gate = _gate_for(bus, extra=[], scope_files=["paper/sec3.tex"])

    async def caller():
        async def deny_after_delay():
            await asyncio.sleep(0.1)
            pending = bus.list_pending_checkpoints()
            bus.append_inbox(
                {"id": "d", "type": "checkpoint_decision", "checkpoint_id": pending[0]["id"]},
                body="deny\nout of scope",
            )

        gate_task = asyncio.create_task(
            gate("Edit", {"file_path": "paper/sec4.tex", "old_string": "x", "new_string": "y"}, {"task_id": "t1"})
        )
        await asyncio.create_task(deny_after_delay())
        return await gate_task

    result = asyncio.run(caller())
    assert result["behavior"] == "deny"


def test_gate_scope_files_allows_in_scope_write(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    gate = _gate_for(bus, extra=[], scope_files=["paper/sec3.tex"])
    result = asyncio.run(
        gate("Edit", {"file_path": "paper/sec3.tex", "old_string": "x", "new_string": "y"}, {"task_id": "t1"})
    )
    assert result["behavior"] == "allow"


def test_gate_timeout_returns_deny(tmp_path: Path) -> None:
    bus = WorkerBus(tmp_path / ".friday")
    gate = _gate_for(bus, extra=[r"^git commit"])
    # Don't append a decision — let it time out
    result = asyncio.run(gate("Bash", {"command": "git commit -m x"}, {"task_id": "t1"}))
    assert result["behavior"] == "deny"
    assert "timeout" in result["message"].lower()
