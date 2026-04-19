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
