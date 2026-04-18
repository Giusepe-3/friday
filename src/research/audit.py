"""Simple append-only audit log for research tool writes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.tools.state import get as state_get


def audit(tool_name: str, **meta: object) -> None:
    state = state_get()
    if state.cfg is None:
        return
    log_path: Path = state.cfg.paths.logs_dir / "research.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        kv = " ".join(f"{k}={v}" for k, v in meta.items())
        line = f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')} {tool_name} {kv}\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
