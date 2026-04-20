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
import yaml
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

    def _log_parser_errors(self, source: str, lines: list[str]) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / "parser_errors.log"
        with log_path.open("a", encoding="utf-8") as f:
            ts = datetime.now().isoformat(timespec="seconds")
            for line in lines:
                f.write(f"{ts}\t{source}\t{line}\n")

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
        """Write process ID to worker.pid."""
        self.ensure_layout()
        _atomic_write_text(self.pid_path, str(pid))

    def read_pid(self) -> int | None:
        """Read process ID from worker.pid, or None if not present."""
        if not self.pid_path.exists():
            return None
        try:
            return int(self.pid_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return None

    def clear_pid(self) -> None:
        """Delete worker.pid file."""
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass


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
