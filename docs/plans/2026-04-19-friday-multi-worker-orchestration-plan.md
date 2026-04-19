# FRIDAY Multi-Worker Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn FRIDAY from single-context voice assistant into conductor of three autonomous Claude Code workers (paper / thesis / research), each running in its own repo with file-bus communication.

**Architecture:** FRIDAY (Opus 4.7/max) holds 9 new MCP tools to dispatch tasks to per-project worker subprocesses (Opus 4.7/high). Workers each hold one `ClaudeSDKClient` and communicate with FRIDAY via per-repo `.friday/` directories (inbox.md, outbox.jsonl, state.json, checkpoints/). Risky actions (git commit, git push, cloud-GPU scripts) halt via SDK's `can_use_tool` permission callback and surface to FRIDAY for voice approval at conversational pause points.

**Tech Stack:** Python 3.11, `claude-agent-sdk`, asyncio, PyYAML, pytest, existing FRIDAY voice/STT/TTS pipeline. New code is pure-Python with no new external dependencies (uses stdlib subprocess, json, pathlib, uuid, re).

**Spec:** `docs/specs/2026-04-19-friday-multi-worker-orchestration-design.md`

---

## File structure

### New files

```
src/orchestrator/
├── __init__.py              # Package init
├── bus.py                   # WorkerBus — file-bus protocol (inbox/outbox/state/checkpoints/pid)
├── models.py                # MODEL_ALIASES, EFFORT_LEVELS, resolve()
├── routing.py               # Pure project-routing logic (alias substring match)
├── checkpoint_gate.py       # Factory: build can_use_tool callback per worker config
├── worker.py                # Worker harness: main loop, ClaudeSDKClient lifecycle
├── tools.py                 # 9 MCP tool wrappers (dispatch_task, query_worker, …)
├── manager.py               # FRIDAY-side worker process management (spawn/kill/track)
└── README.md                # Brief module docstring

scripts/
└── bootstrap_worker_repo.py # Per-repo .friday/ scaffold + .gitignore patch

tests/orchestrator/
├── __init__.py
├── test_bus.py              # File-bus protocol unit tests
├── test_models.py           # Alias resolution tests
├── test_routing.py          # Routing logic tests
├── test_checkpoint_gate.py  # can_use_tool callback tests (mocked SDK)
├── test_worker_harness.py   # Subprocess integration tests (real worker, tmp repo)
├── test_orchestrator_tools.py  # Tool wrappers against fake bus
└── test_manager.py          # Worker process lifecycle tests
```

### Modified files

| File                      | Reason                                                               |
| ------------------------- | -------------------------------------------------------------------- |
| `src/config.py`           | Add `WorkerConfig` dataclass + `workers` field + `friday_effort`     |
| `config/friday.yaml`      | Add `workers:` block, bump `claude_model` and `shim_model` to opus 4.7, add `friday_effort: max` |
| `src/tools/__init__.py`   | Register 9 orchestrator MCP tool names in ALLOWED list (failure-isolated) |
| `friday_voice.py`         | Opus 4.7/max for FRIDAY brain; autostart workers; add `_checkpoint_drain` task; queue interrupts between turns |
| `CLAUDE.md`               | Append "Multi-project orchestration" persona section                 |

---

## Phase 1: File-bus protocol (WorkerBus class + tests)

**Goal of phase:** Library code that owns the on-disk contract. No user-visible change. Other phases depend on this.

### Task 1.1: Scaffold orchestrator package

**Files:**
- Create: `src/orchestrator/__init__.py`
- Create: `tests/orchestrator/__init__.py`

- [ ] **Step 1: Create empty package init**

```python
# src/orchestrator/__init__.py
"""Multi-worker orchestration: WorkerBus, worker harness, MCP tools, routing."""
```

- [ ] **Step 2: Create empty test package init**

```python
# tests/orchestrator/__init__.py
```

- [ ] **Step 3: Verify imports**

Run: `.venv/Scripts/python -c "import src.orchestrator; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/orchestrator/__init__.py tests/orchestrator/__init__.py
git commit -m "feat(orchestrator): scaffold package"
```

### Task 1.2: WorkerBus skeleton + atomic write helper

**Files:**
- Create: `src/orchestrator/bus.py`
- Create: `tests/orchestrator/test_bus.py`

- [ ] **Step 1: Write failing test for atomic write**

```python
# tests/orchestrator/test_bus.py
from pathlib import Path
import tempfile
from src.orchestrator.bus import _atomic_write_text


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
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: ImportError or `_atomic_write_text` missing

- [ ] **Step 3: Implement `_atomic_write_text`**

```python
# src/orchestrator/bus.py
"""WorkerBus: per-repo .friday/ filesystem protocol.

Each worker owns one .friday/ subdirectory inside its repo. FRIDAY reads and
writes the same files. Atomic writes use temp + os.replace (works on Windows
since Python 3.3). Inbox parsing tolerates malformed blocks — corrupt blocks
are logged to .friday/logs/parser_errors.log and skipped.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically: write to temp file in same dir, then os.replace.

    Same-dir temp file ensures os.replace is on the same filesystem (atomic
    rename guarantee). Creates parent dirs if missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/bus.py tests/orchestrator/test_bus.py
git commit -m "feat(orchestrator): atomic text write helper"
```

### Task 1.3: WorkerBus directory layout + state.json read/write

**Files:**
- Modify: `src/orchestrator/bus.py`
- Modify: `tests/orchestrator/test_bus.py`

- [ ] **Step 1: Write failing tests for state.json round-trip**

```python
# Append to tests/orchestrator/test_bus.py
import json
from src.orchestrator.bus import WorkerBus


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
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: ImportError on `WorkerBus`

- [ ] **Step 3: Implement WorkerBus skeleton + state methods**

```python
# Append to src/orchestrator/bus.py
import json


class WorkerBus:
    """File-bus interface for one worker's .friday/ directory.

    All file operations are atomic. State partial-updates merge into existing
    state on disk (read → merge → atomic write).
    """

    def __init__(self, friday_dir: Path) -> None:
        self.dir = Path(friday_dir)
        self.inbox_path = self.dir / "inbox.md"
        self.outbox_path = self.dir / "outbox.jsonl"
        self.state_path = self.dir / "state.json"
        self.pid_path = self.dir / "worker.pid"
        self.checkpoints_dir = self.dir / "checkpoints"
        self.resolved_dir = self.checkpoints_dir / "resolved"
        self.logs_dir = self.dir / "logs"

    def ensure_layout(self) -> None:
        for d in (self.dir, self.checkpoints_dir, self.resolved_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def read_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def write_state(self, **fields) -> None:
        """Merge `fields` into existing state; atomic rewrite."""
        self.ensure_layout()
        current = self.read_state()
        current.update(fields)
        _atomic_write_text(self.state_path, json.dumps(current, indent=2))
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/bus.py tests/orchestrator/test_bus.py
git commit -m "feat(orchestrator): WorkerBus layout + state read/write"
```

### Task 1.4: Outbox append + tail

**Files:**
- Modify: `src/orchestrator/bus.py`
- Modify: `tests/orchestrator/test_bus.py`

- [ ] **Step 1: Write failing tests for outbox**

```python
# Append to tests/orchestrator/test_bus.py
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
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: AttributeError on `append_outbox`

- [ ] **Step 3: Implement outbox methods**

```python
# Add to WorkerBus class in src/orchestrator/bus.py
from datetime import datetime


    def append_outbox(self, event: dict) -> None:
        """Append one event as a JSONL line. Auto-injects `ts` if missing."""
        self.ensure_layout()
        evt = dict(event)
        evt.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        line = json.dumps(evt, ensure_ascii=False) + "\n"
        with self.outbox_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def tail_outbox(self, limit: int = 10, types: list[str] | None = None) -> list[dict]:
        """Return last `limit` events (optionally filtered by `types`).

        Malformed lines are skipped silently and recorded to logs/parser_errors.log.
        """
        if not self.outbox_path.exists():
            return []
        events: list[dict] = []
        bad: list[str] = []
        with self.outbox_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    bad.append(line)
                    continue
                if types is None or evt.get("type") in types:
                    events.append(evt)
        if bad:
            self._log_parser_errors("outbox", bad)
        return events[-limit:]

    def _log_parser_errors(self, source: str, lines: list[str]) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / "parser_errors.log"
        with log_path.open("a", encoding="utf-8") as f:
            ts = datetime.now().isoformat(timespec="seconds")
            for line in lines:
                f.write(f"{ts}\t{source}\t{line}\n")
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/bus.py tests/orchestrator/test_bus.py
git commit -m "feat(orchestrator): outbox append + tail with type filter"
```

### Task 1.5: Inbox parser (YAML frontmatter blocks)

**Files:**
- Modify: `src/orchestrator/bus.py`
- Modify: `tests/orchestrator/test_bus.py`

- [ ] **Step 1: Write failing tests for inbox parsing**

```python
# Append to tests/orchestrator/test_bus.py
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
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: AttributeError on `pop_inbox`

- [ ] **Step 3: Implement inbox parser**

```python
# Add to top of src/orchestrator/bus.py
import yaml


# Add to WorkerBus class
    def pop_inbox(self, allowed_types: set[str] | None = None) -> dict | None:
        """Pop oldest inbox block matching `allowed_types` (or any type if None).

        Returns parsed dict with 'body' field for content. Atomically rewrites
        inbox without the popped block. Skipped malformed blocks are logged
        and dropped.
        """
        if not self.inbox_path.exists():
            return None
        text = self.inbox_path.read_text(encoding="utf-8")
        blocks, bad = _parse_inbox(text)
        if bad:
            self._log_parser_errors("inbox", bad)
        if not blocks:
            if text.strip():
                # All blocks were malformed; clear inbox
                _atomic_write_text(self.inbox_path, "")
            return None

        chosen_idx = None
        for i, block in enumerate(blocks):
            if allowed_types is None or block.get("type") in allowed_types:
                chosen_idx = i
                break
        if chosen_idx is None:
            return None

        chosen = blocks.pop(chosen_idx)
        new_text = _serialize_inbox(blocks)
        _atomic_write_text(self.inbox_path, new_text)
        return chosen


def _parse_inbox(text: str) -> tuple[list[dict], list[str]]:
    """Parse inbox text into [(block_dict, ...), bad_blocks].

    Block format:
        ---
        key: value
        ...
        ---
        body content (may span multiple lines)
    Blocks are separated by the next `---` on its own line.
    """
    blocks: list[dict] = []
    bad: list[str] = []
    # Split on lines that are exactly "---" — preserve content after each marker
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        # Skip blank lines between blocks
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break
        if lines[i].strip() != "---":
            # Stray content before a marker — collect as bad
            stray_start = i
            while i < n and lines[i].strip() != "---":
                i += 1
            bad.append("\n".join(lines[stray_start:i]))
            continue
        # Header marker
        i += 1
        header_start = i
        while i < n and lines[i].strip() != "---":
            i += 1
        if i >= n:
            bad.append("\n".join(lines[header_start - 1:]))
            break
        header_text = "\n".join(lines[header_start:i])
        i += 1  # skip closing marker
        # Body extends until next "---" marker (or EOF)
        body_start = i
        while i < n and lines[i].strip() != "---":
            i += 1
        body_text = "\n".join(lines[body_start:i])

        try:
            header = yaml.safe_load(header_text) or {}
        except yaml.YAMLError:
            bad.append(f"---\n{header_text}\n---\n{body_text}")
            continue
        if not isinstance(header, dict):
            bad.append(f"---\n{header_text}\n---\n{body_text}")
            continue
        header["body"] = body_text
        blocks.append(header)
    return blocks, bad


def _serialize_inbox(blocks: list[dict]) -> str:
    """Inverse of _parse_inbox: emit blocks back to inbox.md form."""
    parts: list[str] = []
    for b in blocks:
        body = b.get("body", "")
        header = {k: v for k, v in b.items() if k != "body"}
        header_text = yaml.safe_dump(header, sort_keys=False).strip()
        parts.append(f"---\n{header_text}\n---\n{body}")
    return "\n".join(parts) + ("\n" if parts else "")
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/bus.py tests/orchestrator/test_bus.py
git commit -m "feat(orchestrator): inbox parser with type filter + malformed-block tolerance"
```

### Task 1.6: Inbox writer + checkpoint files + pidfile

**Files:**
- Modify: `src/orchestrator/bus.py`
- Modify: `tests/orchestrator/test_bus.py`

- [ ] **Step 1: Write failing tests**

```python
# Append to tests/orchestrator/test_bus.py
import os


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
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: AttributeError on `append_inbox` etc.

- [ ] **Step 3: Implement inbox writer + checkpoint + pid methods**

```python
# Add to WorkerBus class in src/orchestrator/bus.py
    def append_inbox(self, header: dict, body: str = "") -> None:
        """Append a new block to the END of inbox.md (FIFO consumption)."""
        self.ensure_layout()
        new_block = dict(header)
        new_block["body"] = body
        existing_text = self.inbox_path.read_text(encoding="utf-8") if self.inbox_path.exists() else ""
        existing_blocks, _bad = _parse_inbox(existing_text)
        existing_blocks.append(new_block)
        _atomic_write_text(self.inbox_path, _serialize_inbox(existing_blocks))

    def write_checkpoint(self, checkpoint: dict) -> None:
        """Write checkpoint JSON to checkpoints/<id>.json."""
        self.ensure_layout()
        ck_id = checkpoint["id"]
        path = self.checkpoints_dir / f"{ck_id}.json"
        _atomic_write_text(path, json.dumps(checkpoint, indent=2))

    def archive_checkpoint(self, checkpoint_id: str, decision: str, reason: str = "") -> None:
        """Move checkpoints/<id>.json to checkpoints/resolved/<id>.json with decision recorded."""
        src = self.checkpoints_dir / f"{checkpoint_id}.json"
        if not src.exists():
            return
        data = json.loads(src.read_text(encoding="utf-8"))
        data["decision"] = decision
        data["decision_reason"] = reason
        data["resolved_at"] = datetime.now().isoformat(timespec="seconds")
        dst = self.resolved_dir / f"{checkpoint_id}.json"
        _atomic_write_text(dst, json.dumps(data, indent=2))
        src.unlink()

    def list_pending_checkpoints(self) -> list[dict]:
        """Return all unresolved checkpoint dicts (sorted by created_at if present)."""
        if not self.checkpoints_dir.exists():
            return []
        out: list[dict] = []
        for p in self.checkpoints_dir.glob("*.json"):
            if p.parent.name == "resolved":
                continue
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        out.sort(key=lambda c: c.get("created_at", ""))
        return out

    def write_pid(self, pid: int) -> None:
        self.ensure_layout()
        _atomic_write_text(self.pid_path, str(pid))

    def read_pid(self) -> int | None:
        if not self.pid_path.exists():
            return None
        try:
            return int(self.pid_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None

    def clear_pid(self) -> None:
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_bus.py -v`
Expected: 21 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/bus.py tests/orchestrator/test_bus.py
git commit -m "feat(orchestrator): inbox writer, checkpoint files, pidfile"
```

---

## Phase 2: Worker harness + checkpoint gate + bootstrap script

**Goal of phase:** Standalone worker process you can run by hand. After this phase you can manually `python -m src.orchestrator.worker --project paper`, write a task to inbox, watch outbox.

### Task 2.1: Models module (alias resolution)

**Files:**
- Create: `src/orchestrator/models.py`
- Create: `tests/orchestrator/test_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_models.py
import pytest
from src.orchestrator.models import resolve_model, resolve_effort, MODEL_ALIASES, EFFORT_LEVELS


def test_resolve_full_model_id_passthrough() -> None:
    assert resolve_model("claude-opus-4-7") == "claude-opus-4-7"
    assert resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_resolve_alias() -> None:
    assert resolve_model("opus") == "claude-opus-4-7"
    assert resolve_model("sonnet") == "claude-sonnet-4-6"
    assert resolve_model("haiku") == "claude-haiku-4-5-20251001"


def test_resolve_alias_case_insensitive() -> None:
    assert resolve_model("OPUS") == "claude-opus-4-7"
    assert resolve_model("Sonnet") == "claude-sonnet-4-6"


def test_resolve_unknown_model_raises() -> None:
    with pytest.raises(ValueError, match="unknown model"):
        resolve_model("gpt-5")


def test_resolve_effort_valid() -> None:
    assert resolve_effort("low") == "low"
    assert resolve_effort("medium") == "medium"
    assert resolve_effort("high") == "high"
    assert resolve_effort("max") == "max"


def test_resolve_effort_case_insensitive() -> None:
    assert resolve_effort("HIGH") == "high"
    assert resolve_effort("Max") == "max"


def test_resolve_effort_invalid_raises() -> None:
    with pytest.raises(ValueError, match="unknown effort"):
        resolve_effort("turbo")


def test_constants_consistent() -> None:
    assert "opus" in MODEL_ALIASES
    assert "sonnet" in MODEL_ALIASES
    assert EFFORT_LEVELS == {"low", "medium", "high", "max"}
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_models.py -v`
Expected: ImportError

- [ ] **Step 3: Implement models module**

```python
# src/orchestrator/models.py
"""Model + effort name resolution.

Voice phrasings ("opus", "sonnet") expand to full Anthropic model IDs.
Effort levels are constrained to the four CLI-supported values.
"""

from __future__ import annotations

MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}

EFFORT_LEVELS: set[str] = {"low", "medium", "high", "max"}


def resolve_model(name: str) -> str:
    """Return canonical model ID. Accept either full ID or short alias."""
    if not name:
        raise ValueError("model name required")
    norm = name.lower()
    if norm in MODEL_ALIASES:
        return MODEL_ALIASES[norm]
    # Full IDs we know of pass through unchanged
    known_full = set(MODEL_ALIASES.values())
    if name in known_full:
        return name
    # Permissive: any well-formed Anthropic-style ID passes through
    if name.startswith("claude-"):
        return name
    raise ValueError(f"unknown model: {name!r}")


def resolve_effort(level: str) -> str:
    """Return canonical effort level. Reject anything outside EFFORT_LEVELS."""
    if not level:
        raise ValueError("effort level required")
    norm = level.lower()
    if norm not in EFFORT_LEVELS:
        raise ValueError(f"unknown effort: {level!r}, expected one of {sorted(EFFORT_LEVELS)}")
    return norm
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_models.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/models.py tests/orchestrator/test_models.py
git commit -m "feat(orchestrator): model + effort alias resolution"
```

### Task 2.2: Routing module

**Files:**
- Create: `src/orchestrator/routing.py`
- Create: `tests/orchestrator/test_routing.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_routing.py
from src.orchestrator.routing import normalize, route


WORKERS_CFG = {
    "paper": {"aliases": ["paper", "draft", "verification", "azr", "the paper"]},
    "thesis": {"aliases": ["thesis", "experiment", "dgm", "darwin godel", "coding agent", "polyglot"]},
    "research": {"aliases": ["research", "literature", "lit review", "progress", "the notes"]},
}


def test_normalize_lowercases_and_strips_punctuation() -> None:
    assert normalize("How's the Paper going?") == "how's the paper going"
    assert normalize("DGM!! refactor.") == "dgm refactor"


def test_route_paper_alias() -> None:
    assert route("Friday, how's the paper going?", WORKERS_CFG) == "paper"
    assert route("draft a new section", WORKERS_CFG) == "paper"


def test_route_thesis_alias() -> None:
    assert route("how's the experiment going?", WORKERS_CFG) == "thesis"
    assert route("ask the DGM agent to refactor X", WORKERS_CFG) == "thesis"


def test_route_research_alias() -> None:
    assert route("update the lit review", WORKERS_CFG) == "research"
    assert route("check progress on RSI papers", WORKERS_CFG) == "research"


def test_route_no_match_returns_none() -> None:
    assert route("what time is it?", WORKERS_CFG) is None


def test_route_first_match_wins() -> None:
    # "draft" is paper alias; "experiment" is thesis alias.
    # If both appear, first project iteration order wins (deterministic).
    text = "draft results from the experiment"
    result = route(text, WORKERS_CFG)
    assert result in {"paper", "thesis"}  # first encountered wins; both legitimate
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_routing.py -v`
Expected: ImportError

- [ ] **Step 3: Implement routing**

```python
# src/orchestrator/routing.py
"""Project routing by alias substring match.

Returns project key on first hit (insertion order of workers_cfg). Returns
None on no match — caller (FRIDAY's persona) decides whether to ask the
user or LLM-route from broader context.
"""

from __future__ import annotations

import re

_NORM = re.compile(r"[a-z']+")


def normalize(s: str) -> str:
    """Lowercase, keep [a-z'] runs, single-space joined."""
    return " ".join(_NORM.findall(s.lower()))


def route(text: str, workers_cfg: dict) -> str | None:
    """Return project key on first alias substring hit. None if no alias matches."""
    norm = normalize(text)
    for project, w in workers_cfg.items():
        for alias in w.get("aliases", []):
            alias_norm = normalize(alias)
            if alias_norm and alias_norm in norm:
                return project
    return None
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_routing.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/routing.py tests/orchestrator/test_routing.py
git commit -m "feat(orchestrator): alias-based project routing"
```

### Task 2.3: Checkpoint gate (can_use_tool callback factory)

**Files:**
- Create: `src/orchestrator/checkpoint_gate.py`
- Create: `tests/orchestrator/test_checkpoint_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_checkpoint_gate.py
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
        # Trigger checkpoint, then approve from "the other side"
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
    # Empty extras — universal alone should still halt git push
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
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_checkpoint_gate.py -v`
Expected: ImportError

- [ ] **Step 3: Implement checkpoint gate factory**

```python
# src/orchestrator/checkpoint_gate.py
"""Build the `can_use_tool` callback the worker passes to ClaudeAgentOptions.

Halt rules (first match wins):
  1. Bash command matches `bash_regex` (per-task config).
  2. Bash command matches `universal_regex` (always-on, cannot be disabled).
  3. File-write tool (Write/Edit) targets a path outside `scope_files` if scope_files set.

Halt path: write checkpoint to bus.checkpoints/, poll inbox for matching
checkpoint_decision, archive on resolution. Timeout → deny + error.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from .bus import WorkerBus


CanUseToolFn = Callable[[str, dict, dict], Awaitable[dict]]

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}


def _bash_command(tool_input: dict) -> str:
    return str(tool_input.get("command", ""))


def _write_target(tool_name: str, tool_input: dict) -> str | None:
    if tool_name not in WRITE_TOOLS:
        return None
    return tool_input.get("file_path") or tool_input.get("notebook_path")


def build_checkpoint_gate(
    bus: WorkerBus,
    bash_regex: list[str],
    universal_regex: list[str],
    scope_files: list[str] | None = None,
    task_id: str | None = None,
    decision_poll_interval_s: float = 1.0,
    decision_timeout_s: float = 3600.0,
) -> CanUseToolFn:
    """Construct the `can_use_tool` callback for one worker task.

    `task_id` is captured in closure (the SDK's context dict does not carry
    a worker-side task id — we know it because we built the gate inside
    _run_task with the active task_id in scope).
    """
    extra_compiled = [re.compile(p) for p in bash_regex]
    universal_compiled = [re.compile(p) for p in universal_regex]
    scope_set = set(scope_files) if scope_files else None
    captured_task_id = task_id

    async def can_use_tool(tool_name: str, tool_input: dict, context: dict) -> dict:
        reason: str | None = None
        if tool_name == "Bash":
            cmd = _bash_command(tool_input)
            if any(p.search(cmd) for p in universal_compiled):
                reason = "universal-trigger"
            elif any(p.search(cmd) for p in extra_compiled):
                reason = "configured-trigger"
        if reason is None:
            wt = _write_target(tool_name, tool_input)
            if wt is not None and scope_set is not None and wt not in scope_set:
                reason = "out-of-scope-write"
        if reason is None:
            return {"behavior": "allow", "updatedInput": tool_input}

        # Halt and request approval
        ck_id = f"ck-{uuid.uuid4()}"
        bus.write_checkpoint({
            "id": ck_id,
            "task_id": captured_task_id,
            "tool": tool_name,
            "command": _bash_command(tool_input) if tool_name == "Bash" else None,
            "file_path": _write_target(tool_name, tool_input),
            "reason": reason,
            "context": dict(context) if context else {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        decision = await _await_decision(
            bus, ck_id,
            poll_interval_s=decision_poll_interval_s,
            timeout_s=decision_timeout_s,
        )
        if decision is None:
            bus.archive_checkpoint(ck_id, decision="deny", reason="timeout")
            return {"behavior": "deny", "message": f"checkpoint timeout after {decision_timeout_s}s"}
        verdict, message = decision
        bus.archive_checkpoint(ck_id, decision=verdict, reason=message)
        if verdict == "approve":
            return {"behavior": "allow", "updatedInput": tool_input}
        return {"behavior": "deny", "message": message or "denied"}

    return can_use_tool


async def _await_decision(
    bus: WorkerBus,
    ck_id: str,
    poll_interval_s: float,
    timeout_s: float,
) -> tuple[str, str] | None:
    """Poll inbox for checkpoint_decision matching ck_id. Returns (verdict, reason) or None on timeout."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        msg = bus.pop_inbox(allowed_types={"checkpoint_decision"})
        if msg is not None and msg.get("checkpoint_id") == ck_id:
            body = (msg.get("body") or "").strip()
            verdict_line, _, rest = body.partition("\n")
            verdict = verdict_line.strip().lower()
            if verdict not in {"approve", "deny"}:
                verdict = "deny"
            return verdict, rest.strip()
        if msg is not None:
            # Wrong ckpt id — push back to inbox END so we don't lose it
            bus.append_inbox({k: v for k, v in msg.items() if k != "body"}, body=msg.get("body", ""))
        await asyncio.sleep(poll_interval_s)
    return None
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_checkpoint_gate.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/checkpoint_gate.py tests/orchestrator/test_checkpoint_gate.py
git commit -m "feat(orchestrator): can_use_tool checkpoint gate with universal + extra regex + scope_files"
```

### Task 2.4: Worker harness (main loop, SDK integration, lifecycle)

**Files:**
- Create: `src/orchestrator/worker.py`
- Create: `tests/orchestrator/test_worker_harness.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/orchestrator/test_worker_harness.py
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
        # Wait for at least one pulse (idle pulse interval is 5min in prod, but we patch via env)
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
```

Note: integration tests need the worker to honor a fast-pulse env var for testing. We'll add `FRIDAY_WORKER_PULSE_IDLE_S` env override in the implementation.

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_worker_harness.py -v`
Expected: error / can't find `src.orchestrator.worker`

- [ ] **Step 3: Implement worker harness**

```python
# src/orchestrator/worker.py
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

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

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
        extra_args={"effort": effort},
        setting_sources=["user", "project"],
    )

    summary = ""
    try:
        async for event in query(prompt=task_text, options=options):
            if isinstance(event, ResultMessage):
                summary = getattr(event, "result", "") or summary
        bus.append_outbox({"type": "task_complete", "task_id": task_id, "summary": summary})
        state_ref.update({"status": "idle", "current_task": None, "current_task_id": None})
        bus.write_state(**state_ref)
    except Exception as e:
        bus.append_outbox({"type": "error", "task_id": task_id, "error": f"{type(e).__name__}: {e}"})
        state_ref["status"] = "error"
        bus.write_state(status="error")


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
```

- [ ] **Step 4: Run tests — verify pass**

Update test fixture to add `--test-fast-pulse` to `_start_worker`:

```python
# In tests/orchestrator/test_worker_harness.py, modify _start_worker:
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
```

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_worker_harness.py -v`
Expected: 3 passed (may be slow — ~30s total)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/worker.py tests/orchestrator/test_worker_harness.py
git commit -m "feat(orchestrator): worker harness with checkpoint gate, pulse loop, lifecycle"
```

### Task 2.5: Bootstrap script for per-repo .friday/ scaffold

**Files:**
- Create: `scripts/bootstrap_worker_repo.py`

- [ ] **Step 1: Implement script (no test — manual idempotent script)**

```python
# scripts/bootstrap_worker_repo.py
"""Per-repo .friday/ scaffold.

Idempotent: safe to re-run. Creates .friday/ + subdirs, adds .friday/ to
the repo's .gitignore if missing, writes README.md describing the dir.

Usage:
    python scripts/bootstrap_worker_repo.py --repo /path/to/repo --project paper
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

README_TEXT = """\
# .friday/ — FRIDAY worker scratch directory

This directory is owned by FRIDAY's per-project worker process. It is
gitignored — nothing in here should be checked in.

Files:
- inbox.md       FRIDAY → worker task queue
- outbox.jsonl   worker → FRIDAY events (append-only)
- state.json     current worker status snapshot
- worker.pid     worker process ID (for duplicate detection)
- checkpoints/   pending tool-approval requests (resolved/ archives them)
- logs/          per-task stdout/stderr + parser_errors.log

To inspect this worker's state:
    cat .friday/state.json
    tail -f .friday/outbox.jsonl

See: docs/specs/2026-04-19-friday-multi-worker-orchestration-design.md
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold .friday/ in a worker repo")
    parser.add_argument("--repo", required=True, help="Absolute path to the worker repo")
    parser.add_argument("--project", required=True, help="Project key (paper/thesis/research)")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: repo path does not exist: {repo}", file=sys.stderr)
        return 2

    friday_dir = repo / ".friday"
    for sub in (friday_dir, friday_dir / "checkpoints", friday_dir / "checkpoints" / "resolved", friday_dir / "logs"):
        sub.mkdir(parents=True, exist_ok=True)

    # Empty inbox/outbox/state if missing
    inbox = friday_dir / "inbox.md"
    if not inbox.exists():
        inbox.write_text("", encoding="utf-8")
    outbox = friday_dir / "outbox.jsonl"
    if not outbox.exists():
        outbox.write_text("", encoding="utf-8")
    state = friday_dir / "state.json"
    if not state.exists():
        state.write_text('{"project": "%s", "status": "idle"}\n' % args.project, encoding="utf-8")

    # README
    readme = friday_dir / "README.md"
    readme.write_text(README_TEXT, encoding="utf-8")

    # Patch .gitignore
    gitignore = repo / ".gitignore"
    line = ".friday/"
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8").splitlines()
        if line not in existing and ".friday" not in existing:
            with gitignore.open("a", encoding="utf-8") as f:
                if not gitignore.read_text(encoding="utf-8").endswith("\n"):
                    f.write("\n")
                f.write(f"{line}\n")
            print(f"[bootstrap] added '{line}' to {gitignore}")
        else:
            print(f"[bootstrap] {gitignore} already contains .friday entry")
    else:
        gitignore.write_text(f"{line}\n", encoding="utf-8")
        print(f"[bootstrap] created {gitignore}")

    print(f"[bootstrap] {friday_dir} ready for project={args.project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test against tmp dir**

```bash
mkdir /tmp/fakerepo && cd /tmp/fakerepo && git init --quiet
.venv/Scripts/python scripts/bootstrap_worker_repo.py --repo /tmp/fakerepo --project test
ls -la /tmp/fakerepo/.friday/
cat /tmp/fakerepo/.gitignore
```

Expected: `.friday/`, subdirs, README, and `.friday/` line in `.gitignore`.

- [ ] **Step 3: Re-run to verify idempotency**

```bash
.venv/Scripts/python scripts/bootstrap_worker_repo.py --repo /tmp/fakerepo --project test
```

Expected: prints "already contains .friday entry"; nothing duplicated.

- [ ] **Step 4: Commit**

```bash
git add scripts/bootstrap_worker_repo.py
git commit -m "feat(orchestrator): bootstrap script for per-repo .friday/ scaffold"
```

---

## Phase 3: FRIDAY orchestrator MCP tools

**Goal of phase:** 9 new MCP tools added to FRIDAY. After this you can run `claude` in `friday/`, type "dispatch_task to paper: do X", and the orchestrator side works (still no voice integration yet — that's Phase 4-5).

### Task 3.1: Worker process manager (FRIDAY-side spawn/kill/track)

**Files:**
- Create: `src/orchestrator/manager.py`
- Create: `tests/orchestrator/test_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_manager.py
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
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_manager.py -v`
Expected: ImportError

- [ ] **Step 3: Implement WorkerManager**

```python
# src/orchestrator/manager.py
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
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_manager.py -v`
Expected: 3 passed (slow, ~30s)

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/manager.py tests/orchestrator/test_manager.py
git commit -m "feat(orchestrator): WorkerManager spawn/kill/is_running with pidfile fallback"
```

### Task 3.2: Orchestrator MCP tools (the 9 functions)

**Files:**
- Create: `src/orchestrator/tools.py`
- Create: `tests/orchestrator/test_orchestrator_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/orchestrator/test_orchestrator_tools.py
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
    assert statuses["beta"] in ("not_running", "idle")  # beta has no state.json


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
```

- [ ] **Step 2: Run tests — verify fail**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_orchestrator_tools.py -v`
Expected: ImportError

- [ ] **Step 3: Implement tool functions (impl layer — MCP wiring next task)**

```python
# src/orchestrator/tools.py
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
```

- [ ] **Step 4: Run tests — verify pass**

Run: `.venv/Scripts/python -m pytest tests/orchestrator/test_orchestrator_tools.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator/tools.py tests/orchestrator/test_orchestrator_tools.py
git commit -m "feat(orchestrator): 9 tool implementations (dispatch/query/list/checkpoint/lifecycle)"
```

### Task 3.3: Wire orchestrator tools into MCP server (existing build_server)

**Files:**
- Modify: `src/tools/__init__.py`
- Read first: `src/tools/__init__.py` (to see how research tools are registered)

- [ ] **Step 1: Read existing tools __init__.py**

Run: `.venv/Scripts/python -c "from src.tools import ALLOWED_TOOL_NAMES, build_server; print(ALLOWED_TOOL_NAMES)"`
Expected: list with mcp__friday__* names from MVP + research tools.

Read `src/tools/__init__.py` end-to-end. Identify the `ALLOWED` list and the `build_server()` function — note the failure-isolated try/except pattern around research-tool registration.

- [ ] **Step 2: Add orchestrator tool definitions mirroring the existing research-tools pattern**

Open `src/tools/__init__.py` and find the research-tools registration block (the failure-isolated `try:` that ends with `_RESEARCH_TOOLS = [...]` and extends `ALLOWED_TOOL_NAMES`). Note the **exact** schema syntax used by `@tool(...)` for those tools — that is what the SDK expects, and it is the only authoritative reference. Do not invent a new schema syntax.

Append a parallel block for orchestrator tools, using the **same** schema syntax as the research tools. The scaffold below shows the structure and which impl function each tool calls; replace the schema dict with whatever format the research tools use (likely a JSON-schema-shaped dict with `"type"` keys, or a Python-type dict).

```python
# === Orchestrator tools (multi-worker) ===
import json as _json_orch
try:
    from claude_agent_sdk import tool
    from src.orchestrator import tools as _orch_impl
    from src.tools import state as _ts  # existing tool_state module

    # NOTE: replace each schema dict below with the SAME shape used by the
    # research tools above. The function bodies are correct as-is.

    @tool("dispatch_task", "Dispatch a task to a project worker", {SCHEMA_FOR_dispatch_task})
    async def dispatch_task(args: dict) -> dict:
        out = _orch_impl.dispatch_task_impl(
            cfg=_ts.cfg.workers, manager=_ts.worker_manager,
            project=args["project"], task=args["task"],
            model=args.get("model"), effort=args.get("effort"),
            scope_files=args.get("scope_files"),
        )
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("query_worker", "Read worker state + recent events", {SCHEMA_FOR_query_worker})
    async def query_worker(args: dict) -> dict:
        out = _orch_impl.query_worker_impl(cfg=_ts.cfg.workers, project=args["project"])
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("list_workers", "One-line state per worker", {SCHEMA_FOR_list_workers})
    async def list_workers(args: dict) -> dict:
        out = _orch_impl.list_workers_impl(cfg=_ts.cfg.workers)
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("pop_checkpoint_request", "Pop oldest pending checkpoint (any project if project omitted)", {SCHEMA_FOR_pop_checkpoint_request})
    async def pop_checkpoint_request(args: dict) -> dict:
        out = _orch_impl.pop_checkpoint_request_impl(cfg=_ts.cfg.workers, project=args.get("project"))
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("approve_checkpoint", "Approve or deny a pending checkpoint", {SCHEMA_FOR_approve_checkpoint})
    async def approve_checkpoint(args: dict) -> dict:
        out = _orch_impl.approve_checkpoint_impl(
            cfg=_ts.cfg.workers, project=args["project"],
            checkpoint_id=args["checkpoint_id"], decision=args["decision"],
            reason=args.get("reason") or "",
        )
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("recent_outbox", "Tail recent outbox events for a project", {SCHEMA_FOR_recent_outbox})
    async def recent_outbox(args: dict) -> dict:
        out = _orch_impl.recent_outbox_impl(
            cfg=_ts.cfg.workers, project=args["project"],
            limit=args.get("limit") or 10, types=args.get("types"),
        )
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("pause_worker", "Pause worker (no new tasks accepted)", {SCHEMA_FOR_pause_worker})
    async def pause_worker(args: dict) -> dict:
        out = _orch_impl.pause_worker_impl(cfg=_ts.cfg.workers, project=args["project"])
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("resume_worker", "Resume a paused worker", {SCHEMA_FOR_resume_worker})
    async def resume_worker(args: dict) -> dict:
        out = _orch_impl.resume_worker_impl(cfg=_ts.cfg.workers, project=args["project"])
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    @tool("kill_worker", "SIGTERM the worker process", {SCHEMA_FOR_kill_worker})
    async def kill_worker(args: dict) -> dict:
        out = _orch_impl.kill_worker_impl(
            cfg=_ts.cfg.workers, manager=_ts.worker_manager, project=args["project"],
        )
        return {"content": [{"type": "text", "text": _json_orch.dumps(out)}]}

    _ORCH_TOOLS = [
        dispatch_task, query_worker, list_workers, pop_checkpoint_request,
        approve_checkpoint, recent_outbox, pause_worker, resume_worker, kill_worker,
    ]
    _ORCH_TOOL_NAMES = [
        "mcp__friday__dispatch_task", "mcp__friday__query_worker",
        "mcp__friday__list_workers", "mcp__friday__pop_checkpoint_request",
        "mcp__friday__approve_checkpoint", "mcp__friday__recent_outbox",
        "mcp__friday__pause_worker", "mcp__friday__resume_worker", "mcp__friday__kill_worker",
    ]
    ALLOWED_TOOL_NAMES.extend(_ORCH_TOOL_NAMES)
    print(f"[tools] orchestrator tools registered: {len(_ORCH_TOOLS)}")
except Exception as _e:
    _ORCH_TOOLS = []
    print(f"[tools] orchestrator tools UNAVAILABLE: {_e}")
```

Schema parameters per tool (replace the `{SCHEMA_FOR_*}` placeholders):

| Tool | Required args | Optional args |
|---|---|---|
| `dispatch_task` | `project: str`, `task: str` | `model: str`, `effort: str`, `scope_files: list[str]` |
| `query_worker` | `project: str` | — |
| `list_workers` | — | — |
| `pop_checkpoint_request` | — | `project: str` |
| `approve_checkpoint` | `project: str`, `checkpoint_id: str`, `decision: str` | `reason: str` |
| `recent_outbox` | `project: str` | `limit: int`, `types: list[str]` |
| `pause_worker`, `resume_worker`, `kill_worker` | `project: str` | — |

Then update `build_server()` to include `_ORCH_TOOLS` in the tool list passed to the SDK's `create_sdk_mcp_server` (same way it already includes research tools).

- [ ] **Step 3: Verify tool names appear in ALLOWED**

Run: `.venv/Scripts/python -c "from src.tools import ALLOWED_TOOL_NAMES; print('mcp__friday__dispatch_task' in ALLOWED_TOOL_NAMES)"`
Expected: `True`

- [ ] **Step 4: Verify build_server doesn't crash**

Run: `.venv/Scripts/python -c "from src.tools import build_server; s = build_server(); print('ok')"`
Expected: `ok` (with possibly a "[tools] orchestrator tools UNAVAILABLE: ..." warning if `_ts.cfg.workers` doesn't exist yet — that's resolved in Phase 4 when config is updated).

- [ ] **Step 5: Commit**

```bash
git add src/tools/__init__.py
git commit -m "feat(orchestrator): register 9 MCP tools in build_server (failure-isolated)"
```

---

## Phase 4: Routing module + persona update + Opus 4.7 model upgrade for FRIDAY

### Task 4.1: Extend Config with WorkerConfig + friday_effort

**Files:**
- Modify: `src/config.py`
- Modify: `config/friday.yaml`

- [ ] **Step 1: Read current src/config.py to see Config dataclass + load() function**

Use Read tool on `src/config.py`. Note the existing dataclass shape and YAML loader.

- [ ] **Step 2: Add WorkerConfig dataclass + workers field**

Edit `src/config.py` — add near other dataclasses:

```python
@dataclass
class WorkerConfig:
    project: str
    repo: Path
    aliases: list[str]
    default_model: str
    default_effort: str
    autostart: bool
    pulse_interval_working_s: int
    pulse_interval_idle_s: int
    bash_regex: list[str]  # extracted from checkpoint_triggers.bash_regex
```

Add to existing `Config` dataclass:

```python
    friday_effort: str
    workers: dict[str, WorkerConfig]
```

In `load()`, after reading `data: dict` from YAML, add:

```python
    workers_raw = data.get("workers", {}) or {}
    workers: dict[str, WorkerConfig] = {}
    for project, w in workers_raw.items():
        triggers = w.get("checkpoint_triggers", {}) or {}
        workers[project] = WorkerConfig(
            project=project,
            repo=Path(w["repo"]),
            aliases=list(w.get("aliases", [])),
            default_model=str(w.get("default_model", "claude-opus-4-7")),
            default_effort=str(w.get("default_effort", "high")),
            autostart=bool(w.get("autostart", True)),
            pulse_interval_working_s=int(w.get("pulse_interval_working_s", 30)),
            pulse_interval_idle_s=int(w.get("pulse_interval_idle_s", 300)),
            bash_regex=list(triggers.get("bash_regex", [])),
        )
```

And pass to Config constructor:

```python
        friday_effort=str(data.get("friday_effort", "max")),
        workers=workers,
```

- [ ] **Step 3: Update config/friday.yaml**

Edit `config/friday.yaml` — bump model + add workers block:

```yaml
claude_model: claude-opus-4-7        # was claude-sonnet-4-6 — FRIDAY brain upgrade
shim_model: claude-opus-4-7          # was "sonnet" — FRIDAY voice brain
friday_effort: max                   # NEW

# ... existing fields unchanged ...

workers:
  paper:
    repo: C:/Users/leona/Documents/GitHub/Learning/Verification_Paper
    aliases: [paper, draft, verification, azr, "the paper"]
    default_model: claude-opus-4-7
    default_effort: high
    autostart: true
    pulse_interval_working_s: 30
    pulse_interval_idle_s: 300
    checkpoint_triggers:
      bash_regex:
        - '^git commit'
        - '^git push'
        - 'runpod'
        - 'bash setup_.*pod'
        - 'wandb init'
  thesis:
    repo: C:/Users/leona/Documents/GitHub/Learning/dgm_bachelor_thesis
    aliases: [thesis, experiment, dgm, "darwin godel", "coding agent", polyglot]
    default_model: claude-opus-4-7
    default_effort: high
    autostart: true
    pulse_interval_working_s: 30
    pulse_interval_idle_s: 300
    checkpoint_triggers:
      bash_regex:
        - '^git commit'
        - '^git push'
        - 'docker run'
  research:
    repo: C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project
    aliases: [research, literature, "lit review", progress, "the notes"]
    default_model: claude-opus-4-7
    default_effort: high
    autostart: true
    pulse_interval_working_s: 30
    pulse_interval_idle_s: 300
    checkpoint_triggers:
      bash_regex:
        - '^git commit'
        - '^git push'
```

- [ ] **Step 4: Verify config loads**

Run: `.venv/Scripts/python -c "from src import config; c = config.load(); print(list(c.workers.keys())); print(c.friday_effort)"`
Expected: `['paper', 'thesis', 'research']` and `max`.

- [ ] **Step 5: Commit**

```bash
git add src/config.py config/friday.yaml
git commit -m "feat(config): add workers block + friday_effort, bump models to opus 4.7"
```

### Task 4.2: Wire WorkerManager into tool_state init

**Files:**
- Modify: `src/tools/state.py` (or wherever `tool_state.init` lives)
- Modify: `src/tools/__init__.py` (the orchestrator tools block already references `_ts.worker_manager`)

- [ ] **Step 1: Read current `src/tools/state.py`**

Note its existing fields (cfg, speak, spotify, scheduler, memory, research) and the `init()` signature.

- [ ] **Step 2: Add worker_manager field — mirror the existing pattern**

The existing `state` module already exposes globals like `cfg`, `speak`, `spotify`, `scheduler`, `memory`, `research` via an `init(...)` function. Mirror the exact pattern used there for the new `worker_manager` field.

Concretely:

1. Add `worker_manager = None` at module top alongside the other module-level defaults.
2. Add `worker_manager=None` to the `init(...)` keyword-only signature alongside the existing kwargs.
3. Inside `init`, assign it the same way the other fields are assigned (likely via `globals()["worker_manager"] = worker_manager` or a `global worker_manager` statement followed by `worker_manager = ...` — whichever the existing fields use).

Do **not** invent a new pattern. If `cfg` is set via `globals()["cfg"] = cfg`, do that. If it uses `global cfg; cfg = cfg_arg` (with a renamed parameter), match it.

After editing, the import `from src.tools import state` should let `state.worker_manager` be readable and writable from outside.

- [ ] **Step 3: Verify import chain**

Run: `.venv/Scripts/python -c "from src.tools import state; print(hasattr(state, 'worker_manager'))"`
Expected: `True`

- [ ] **Step 4: Commit**

```bash
git add src/tools/state.py
git commit -m "feat(orchestrator): expose worker_manager via tool_state for MCP tools"
```

### Task 4.3: Update CLAUDE.md with multi-project orchestration persona

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read current CLAUDE.md to see existing structure**

- [ ] **Step 2: Append new section after existing capabilities section**

Append to `CLAUDE.md`:

```markdown
## Multi-project orchestration

You conduct three project workers — `paper`, `thesis`, `research` — each
running autonomously in its own repo with its own Claude Code session.
You are the voice; they are the hands.

**Project routing.** Match aliases substring-wise in user text:

- `paper` / `draft` / `verification` / `azr` / "the paper" → `project="paper"`
- `thesis` / `experiment` / `dgm` / `coding agent` / `polyglot` / "darwin godel" → `project="thesis"`
- `research` / `literature` / `lit review` / `progress` / "the notes" → `project="research"`

If no alias matches and the project is ambiguous, ask the user which one
before calling any worker tool. Do not guess on low confidence.

**Status questions** ("how's the experiment going?", "what's the paper
agent doing?"): call `query_worker(project)` and read back ONE sentence
covering current task + last log line + git status. Don't dump JSON.

**Task dispatch:** call `dispatch_task(project, task, model=, effort=)`.

- Default `model="claude-opus-4-7"`, `effort="high"`.
- If the user says "opus max" or "max effort", set `effort="max"`.
- If the user explicitly downgrades ("sonnet medium for the research"),
  pass `model="claude-sonnet-4-6", effort="medium"`.
- If the user names files in the task, set `scope_files=[...]` to lock
  the worker to those files.

**Checkpoint approvals.** Periodically (between conversation turns)
check `pop_checkpoint_request()` (no project = any). If a checkpoint is
returned, surface it in ONE sentence with the action choices, e.g.
"Paper agent waiting on commit approval — three files changed in §3.
Approve, deny, or want the diff?" Then map user reply to
`approve_checkpoint(project, checkpoint_id, decision, reason=...)`.

**Safety.** Never call `dispatch_task` mid-task without an explicit user
instruction. Never auto-approve checkpoints. Workers' git push and cloud
GPU spend always halt — that's by design, not a bug.

**Worker lifecycle:** `pause_worker` / `resume_worker` / `kill_worker`
are user-initiated only.
```

- [ ] **Step 3: Verify CLAUDE.md still parses (no markdown issues)**

Visual review or `.venv/Scripts/python -c "open('CLAUDE.md').read()"` to make sure it loads.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "feat(persona): multi-project orchestration section for CLAUDE.md"
```

---

## Phase 5: Per-repo bootstrap + autostart wiring in friday_voice.py

### Task 5.1: Run bootstrap script against all 3 worker repos

**Files:** No code changes; manual execution.

- [ ] **Step 1: Bootstrap paper repo**

```bash
.venv/Scripts/python scripts/bootstrap_worker_repo.py \
  --repo "C:/Users/leona/Documents/GitHub/Learning/Verification_Paper" \
  --project paper
```

Expected: `.friday/` created, `.gitignore` patched.

- [ ] **Step 2: Bootstrap thesis repo**

```bash
.venv/Scripts/python scripts/bootstrap_worker_repo.py \
  --repo "C:/Users/leona/Documents/GitHub/Learning/dgm_bachelor_thesis" \
  --project thesis
```

- [ ] **Step 3: Bootstrap research repo**

```bash
.venv/Scripts/python scripts/bootstrap_worker_repo.py \
  --repo "C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project" \
  --project research
```

- [ ] **Step 4: Verify all three**

```bash
ls "C:/Users/leona/Documents/GitHub/Learning/Verification_Paper/.friday/"
ls "C:/Users/leona/Documents/GitHub/Learning/dgm_bachelor_thesis/.friday/"
ls "C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project/.friday/"
```

Expected each: `inbox.md outbox.jsonl state.json checkpoints/ logs/ README.md`.

- [ ] **Step 5: No commit (changes are in worker repos, not friday repo).**

### Task 5.2: Smoke test single worker by hand

**Files:** No code changes; smoke test.

- [ ] **Step 1: Spawn paper worker manually**

```bash
.venv/Scripts/python -m src.orchestrator.worker \
  --project paper \
  --repo "C:/Users/leona/Documents/GitHub/Learning/Verification_Paper" \
  --default-model claude-opus-4-7 \
  --default-effort high \
  --bash-regex '^git commit' \
  --bash-regex '^git push' \
  --bash-regex 'runpod' \
  --bash-regex 'wandb init' &
```

(In a second terminal — leave the worker running.)

- [ ] **Step 2: Inspect state**

```bash
cat "C:/Users/leona/Documents/GitHub/Learning/Verification_Paper/.friday/state.json"
```

Expected: `{"project": "paper", "status": "idle", "model": "claude-opus-4-7", ...}`.

- [ ] **Step 3: Send a no-op task via inbox**

```bash
.venv/Scripts/python -c "
from pathlib import Path
from src.orchestrator.bus import WorkerBus
bus = WorkerBus(Path('C:/Users/leona/Documents/GitHub/Learning/Verification_Paper/.friday'))
bus.append_inbox({'id':'smoke-1','type':'task','model':'claude-opus-4-7','effort':'high'}, body='Echo back: smoke test ok')
"
```

- [ ] **Step 4: Wait ~30-60s and check outbox**

```bash
tail -5 "C:/Users/leona/Documents/GitHub/Learning/Verification_Paper/.friday/outbox.jsonl"
```

Expected: `ack` event followed by `task_complete` event with summary.

- [ ] **Step 5: Terminate worker**

```bash
.venv/Scripts/python -c "
from pathlib import Path
from src.orchestrator.bus import WorkerBus
bus = WorkerBus(Path('C:/Users/leona/Documents/GitHub/Learning/Verification_Paper/.friday'))
bus.append_inbox({'id':'term','type':'terminate'}, body='')
"
```

Worker process exits within ~3s.

### Task 5.3: Wire WorkerManager + autostart into friday_voice.py

**Files:**
- Modify: `friday_voice.py`

- [ ] **Step 1: Read current friday_voice.py main() to see init order**

- [ ] **Step 2: Add WorkerManager construction + autostart loop after tool_state.init**

Edit `friday_voice.py`:

```python
# Near the top imports
from src.orchestrator.manager import WorkerManager
```

In `main()`, after `tool_state.init(...)`:

```python
    # Build worker manager from cfg.workers (dataclass dicts)
    workers_cfg_for_mgr = {
        project: {
            "repo": w.repo,
            "default_model": w.default_model,
            "default_effort": w.default_effort,
            "bash_regex": w.bash_regex,
        }
        for project, w in cfg.workers.items()
    }
    worker_manager = WorkerManager(workers_cfg_for_mgr)
    # Re-init tool_state so the orchestrator tools see the manager
    tool_state.init(
        cfg=cfg, speak=tts.speak, spotify=sp, scheduler=scheduler,
        memory=memory, research=research, worker_manager=worker_manager,
    )

    # Autostart any worker with autostart=True
    for project, w in cfg.workers.items():
        if w.autostart:
            worker_manager.spawn(project)
            print(f"[shim] autostarted worker: {project}", flush=True)
```

In the `finally:` block of `main()` (where `await brain.stop()` is called), add:

```python
    finally:
        await brain.stop()
        worker_manager.kill_all()
        print("[shim] all workers terminated", flush=True)
```

Also bump model in the ShimBrain construction site:

```python
    brain = ShimBrain(cwd=REPO_ROOT, model=cfg.shim_model)
```

This already reads `cfg.shim_model` which we set to `claude-opus-4-7`. The `friday_effort` should also be wired into ShimBrain — modify ShimBrain.start():

```python
    async def start(self, effort: str = "high") -> None:
        await self.stop()
        options = ClaudeAgentOptions(
            model=self._model,
            cwd=self._cwd,
            permission_mode="bypassPermissions",
            include_partial_messages=True,
            setting_sources=["user", "project"],
            mcp_servers={"friday": self._server},
            allowed_tools=ALLOWED_TOOL_NAMES,
            extra_args={"effort": effort},
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
```

Update the call site in `main()`:

```python
    await brain.start(effort=cfg.friday_effort)
```

- [ ] **Step 3: Smoke test FRIDAY startup**

Run: `.venv/Scripts/python friday_voice.py`

Expected initial logs:
- `[shim] tool_state wired ...`
- `[shim] autostarted worker: paper`
- `[shim] autostarted worker: thesis`
- `[shim] autostarted worker: research`
- `[shim] starting persistent brain session...`
- `[shim] brain ready ...`
- `[shim] awaiting wake word ...`

After ~5s, verify all three workers wrote state.json:

```bash
for r in Verification_Paper dgm_bachelor_thesis AI-Research-Project; do
  cat "C:/Users/leona/Documents/GitHub/Learning/$r/.friday/state.json"
  echo "---"
done
```

Expected each: `{"project": "...", "status": "idle", ...}`.

Ctrl-C FRIDAY, verify all workers terminated:

```bash
for r in Verification_Paper dgm_bachelor_thesis AI-Research-Project; do
  cat "C:/Users/leona/Documents/GitHub/Learning/$r/.friday/state.json"
  echo "---"
done
```

Expected each: `"status": "terminated"`.

- [ ] **Step 4: Commit**

```bash
git add friday_voice.py
git commit -m "feat(orchestrator): autostart all workers with FRIDAY; opus 4.7/max for FRIDAY brain"
```

### Task 5.4: First end-to-end voice test (no checkpoint UX yet)

**Files:** None. Live manual test.

- [ ] **Step 1: Start FRIDAY, say wake word**

Voice interaction:
- Wake word: "Hey JARVIS"
- "List workers"

Expected: FRIDAY calls `list_workers`, replies one sentence with all 3 worker statuses.

- [ ] **Step 2: Status query**

Voice: "How's the paper going?"

Expected: FRIDAY routes via "paper" alias → `query_worker(project="paper")` → reads state in one sentence.

- [ ] **Step 3: Trivial dispatch**

Voice: "Tell the research agent to add a one-line note in progress about today's date and the multi-worker rollout"

Expected: FRIDAY calls `dispatch_task(project="research", task="...")`. Within ~30-60s the research worker writes a note, returns `task_complete` to outbox.

- [ ] **Step 4: Verify research repo touched**

```bash
ls "C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project/progress/"
git -C "C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project" status
```

Expected: a new file or modified one in `progress/`. Uncommitted (because git commit triggers checkpoint, which is not surfaced yet — Phase 6).

- [ ] **Step 5: No commit (manual test).**

---

## Phase 6: Checkpoint voice interrupt UX

### Task 6.1: Add `_checkpoint_drain` task + `_pending_interrupts` queue to friday_voice.py

**Files:**
- Modify: `friday_voice.py`

- [ ] **Step 1: Add module-level queue + drain task**

In `friday_voice.py`, add helper:

```python
async def _checkpoint_drain_loop(
    workers_cfg: dict,
    pending_q: asyncio.Queue,
    poll_interval_s: float = 5.0,
    stop: asyncio.Event | None = None,
) -> None:
    """Poll all workers' checkpoints. Push new ones to pending_q.

    Tracks already-queued IDs to avoid duplicate pushes.
    """
    seen_ids: set[str] = set()
    while True:
        if stop is not None and stop.is_set():
            return
        for project in workers_cfg.keys():
            try:
                bus_dir = Path(workers_cfg[project]["repo"]) / ".friday"
                from src.orchestrator.bus import WorkerBus
                bus = WorkerBus(bus_dir)
                for ck in bus.list_pending_checkpoints():
                    if ck["id"] in seen_ids:
                        continue
                    seen_ids.add(ck["id"])
                    await pending_q.put({"project": project, "checkpoint": ck})
            except Exception as e:
                print(f"[shim] checkpoint drain error ({project}): {e}", flush=True)
        await asyncio.sleep(poll_interval_s)
```

- [ ] **Step 2: Spawn the drain task in main()**

Inside `main()`, after worker autostart:

```python
    pending_interrupts: asyncio.Queue = asyncio.Queue()
    drain_task = asyncio.create_task(_checkpoint_drain_loop(
        workers_cfg=workers_cfg_for_mgr,
        pending_q=pending_interrupts,
        poll_interval_s=5.0,
        stop=stop,
    ))
```

In the `finally:` block, cancel it:

```python
    finally:
        drain_task.cancel()
        await brain.stop()
        worker_manager.kill_all()
```

- [ ] **Step 3: Pass queue into _conversation_loop**

Modify the existing `_conversation_loop` signature to accept `pending_interrupts`:

```python
async def _conversation_loop(brain, stt, vad, tts, cfg, turns, home, pending_interrupts):
    last_activity = datetime.now()
    while True:
        # NEW: drain interrupts at the top of each iteration
        await _drain_interrupts(pending_interrupts, brain, tts, stt, vad, cfg, turns, home)

        idle_s = (datetime.now() - last_activity).total_seconds()
        if idle_s > cfg.silence_timeout_s:
            print(f"[shim] idle {idle_s:.0f}s > {cfg.silence_timeout_s}s, re-arming wake", flush=True)
            return
        # ... rest unchanged ...
```

Update its call site in main() to pass `pending_interrupts`.

- [ ] **Step 4: Implement `_drain_interrupts`**

Add to `friday_voice.py`:

```python
async def _drain_interrupts(
    pending_q: asyncio.Queue, brain, tts, stt, vad, cfg, turns, home,
) -> None:
    """Surface one pending checkpoint per call (FIFO). 'later' pushes back."""
    if pending_q.empty():
        return
    item = await pending_q.get()
    project = item["project"]
    ck = item["checkpoint"]
    # Speak the interrupt via the brain so phrasing matches persona
    interrupt_prompt = (
        f"INTERRUPT: A worker checkpoint is pending. Surface it to Leo in ONE sentence "
        f"with action choices (approve, deny, show me, later).\n\n"
        f"project={project}\n"
        f"tool={ck.get('tool')}\n"
        f"command={ck.get('command')}\n"
        f"file_path={ck.get('file_path')}\n"
        f"reason={ck.get('reason')}\n"
        f"context={ck.get('context')}"
    )
    spoken = await speak_streaming(tts, brain.ask_streaming(interrupt_prompt))
    _append_turn_log(home, "friday_interrupt", spoken)

    # Capture user response — short-window VAD
    pcm = await record_until_silence(vad, cfg.max_recording_s)
    if not pcm:
        # No reply — push back and continue
        await pending_q.put(item)
        return
    transcript = await stt.transcribe(pcm, cfg.sample_rate)
    if not transcript.strip() or _looks_like_hallucination(transcript):
        await pending_q.put(item)
        return
    _append_turn_log(home, "user_interrupt_reply", transcript)

    decision_prompt = (
        f"User responded to the interrupt: {transcript!r}\n"
        f"For checkpoint id={ck['id']!r} on project={project!r}, take ONE of:\n"
        f"- approve → call mcp__friday__approve_checkpoint(project, checkpoint_id={ck['id']!r}, decision='approve')\n"
        f"- deny → call with decision='deny' and pass user's reason\n"
        f"- show me → call mcp__friday__query_worker and read back details, then re-ask\n"
        f"- later → reply 'noted, I'll re-surface it' and don't call any tool\n"
        f"Reply in ONE sentence."
    )
    reply = await speak_streaming(tts, brain.ask_streaming(decision_prompt))
    _append_turn_log(home, "friday_interrupt_action", reply)

    # If user said "later" or response was ambiguous, push back so we resurface
    if "later" in transcript.lower() or "wait" in transcript.lower():
        await pending_q.put(item)
```

- [ ] **Step 5: Smoke test the interrupt flow**

Manual test:
1. Start FRIDAY (`python friday_voice.py`)
2. Wake: "Hey JARVIS"
3. Voice: "Tell the research agent to commit a small change to progress/test.md"
4. Wait — research worker tries `git commit`, hits checkpoint
5. Within 5s of checkpoint write, FRIDAY interrupts: "Research agent waiting on commit approval — one file in progress/. Approve, deny, or want the diff?"
6. Voice: "approve"
7. FRIDAY calls `approve_checkpoint`, worker's commit completes
8. Verify: `git -C "C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project" log -1`

Expected: new commit by worker.

- [ ] **Step 6: Commit**

```bash
git add friday_voice.py
git commit -m "feat(orchestrator): proactive checkpoint interrupts at conversation pauses"
```

### Task 6.2: Mid-task error escalation

**Files:**
- Modify: `friday_voice.py` (add error event subscription)

- [ ] **Step 1: Extend `_checkpoint_drain_loop` to also surface fresh `error` events**

Modify the drain loop:

```python
async def _checkpoint_drain_loop(workers_cfg, pending_q, poll_interval_s=5.0, stop=None):
    seen_ck_ids: set[str] = set()
    seen_error_ts: dict[str, str] = {}  # project → last seen error ts
    while True:
        if stop is not None and stop.is_set():
            return
        for project in workers_cfg.keys():
            try:
                bus_dir = Path(workers_cfg[project]["repo"]) / ".friday"
                from src.orchestrator.bus import WorkerBus
                bus = WorkerBus(bus_dir)
                # Checkpoints
                for ck in bus.list_pending_checkpoints():
                    if ck["id"] in seen_ck_ids:
                        continue
                    seen_ck_ids.add(ck["id"])
                    await pending_q.put({"kind": "checkpoint", "project": project, "checkpoint": ck})
                # Errors (only the most recent, per project)
                errs = bus.tail_outbox(limit=5, types=["error"])
                if errs:
                    last = errs[-1]
                    last_ts = last.get("ts", "")
                    if last_ts and seen_error_ts.get(project) != last_ts:
                        seen_error_ts[project] = last_ts
                        await pending_q.put({"kind": "error", "project": project, "error": last})
            except Exception as e:
                print(f"[shim] checkpoint drain error ({project}): {e}", flush=True)
        await asyncio.sleep(poll_interval_s)
```

- [ ] **Step 2: Update `_drain_interrupts` to handle both kinds**

```python
async def _drain_interrupts(pending_q, brain, tts, stt, vad, cfg, turns, home):
    if pending_q.empty():
        return
    item = await pending_q.get()
    if item["kind"] == "checkpoint":
        await _surface_checkpoint(item, brain, tts, stt, vad, cfg, turns, home, pending_q)
    elif item["kind"] == "error":
        await _surface_error(item, brain, tts, home)


async def _surface_error(item, brain, tts, home):
    err = item["error"]
    project = item["project"]
    prompt = (
        f"INTERRUPT: A worker hit an error. Surface to Leo in ONE sentence.\n"
        f"project={project}\n"
        f"task_id={err.get('task_id')}\n"
        f"error={err.get('error')}\n"
    )
    spoken = await speak_streaming(tts, brain.ask_streaming(prompt))
    _append_turn_log(home, "friday_interrupt_error", spoken)
```

(Move the existing checkpoint surface logic from previous task into a `_surface_checkpoint` function that takes the same args.)

- [ ] **Step 3: Smoke test by inducing an error**

Manual:
1. Start FRIDAY
2. From a Python shell, inject a deliberately-failing task:

```python
from pathlib import Path
from src.orchestrator.bus import WorkerBus
bus = WorkerBus(Path("C:/Users/leona/Documents/GitHub/Learning/Verification_Paper/.friday"))
bus.append_inbox({"id":"err-1","type":"task","model":"not-a-real-model","effort":"high"}, body="x")
```

3. Worker tries to use `not-a-real-model`, raises, writes error event
4. Within 5s FRIDAY interrupts: "Paper agent failed on `not-a-real-model` task — `<error message>`."

- [ ] **Step 4: Commit**

```bash
git add friday_voice.py
git commit -m "feat(orchestrator): surface worker errors via same interrupt path as checkpoints"
```

### Task 6.3: Live test checklist (no code; verification gate)

**Files:** None.

- [ ] Wake word fires, FRIDAY says "Online, boss."
- [ ] All 3 workers visible via "list workers"
- [ ] "How's the paper going?" → routes to paper, reads state in one sentence
- [ ] "Tell the thesis agent to add a TODO comment in `coding_agent.py:1`" → dispatch works
- [ ] Thesis worker hits commit checkpoint → FRIDAY interrupts at next pause → "approve" → worker commits
- [ ] "opus max the research on this one: write a 3-sentence summary of …" → dispatched with model=opus, effort=max
- [ ] Worker error (induce by bad task) → FRIDAY surfaces error in one sentence
- [ ] Idle 90s → FRIDAY silently re-arms to wake
- [ ] Restart FRIDAY → workers stay alive, FRIDAY rebuilds context, all 3 still visible via "list workers"
- [ ] "Terminate JARVIS" → FRIDAY says "Terminating, boss" → all workers cleanly stop

If any item fails, branch into bugfix and re-run that step.

---

## Self-review checks

After completing all phases, run the full test suite:

```bash
.venv/Scripts/python -m pytest tests/orchestrator/ -v
```

Expected: ~50 tests pass. If anything fails, fix before declaring done.

Then run the full FRIDAY test suite to confirm no regression:

```bash
.venv/Scripts/python -m pytest tests/ -v
```

Expected: existing 107 tests + ~50 new = ~157 passed.
