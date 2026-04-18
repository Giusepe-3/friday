"""Regenerate ~/friday/memory/recent.md from the last 7 days of per-day files.

CLAUDE.md @imports this file so Claude Code picks up recent session summaries
without loading all history. Run from cron/scheduler, or manually."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as cfg_mod


def main() -> None:
    cfg = cfg_mod.load()
    memory_dir = cfg.paths.memory_dir
    recent = memory_dir / "recent.md"
    parts = ["# Recent session summaries (last 7 days)\n"]
    now = datetime.now()
    any_found = False
    for i in range(7):
        d = (now - timedelta(days=i)).date().isoformat()
        path = memory_dir / f"{d}.md"
        if path.exists():
            parts.append(f"\n## {d}\n\n{path.read_text(encoding='utf-8').strip()}\n")
            any_found = True
    if not any_found:
        parts.append("\n(no recent sessions)\n")
    recent.parent.mkdir(parents=True, exist_ok=True)
    recent.write_text("".join(parts), encoding="utf-8")
    print(f"[recent] wrote {recent} ({recent.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
