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
