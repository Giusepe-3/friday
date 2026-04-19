"""WorkerBus: per-repo .friday/ filesystem protocol.

Each worker owns one .friday/ subdirectory inside its repo. FRIDAY reads and
writes the same files. Atomic writes use temp + os.replace (works on Windows
since Python 3.3). Inbox parsing tolerates malformed blocks — corrupt blocks
are logged to .friday/logs/parser_errors.log and skipped.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
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
