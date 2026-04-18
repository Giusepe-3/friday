"""Persistent memory for FRIDAY.

Three surfaces (spec §6):

* **Short-term** — in-session conversation turns, held by ``Session`` (not
  here).
* **Medium-term** — per-day markdown files of session summaries, loaded as
  a 7-day window into each new session's system prompt.
* **Long-term** — ``facts.md``, a flat ``key: value`` file that is always
  injected verbatim.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


class Memory:
    def __init__(self, memory_dir: Path, facts_path: Path) -> None:
        self.memory_dir = memory_dir
        self.facts_path = facts_path
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.facts_path.parent.mkdir(parents=True, exist_ok=True)

    def append_summary(self, summary: str, when: datetime | None = None) -> None:
        when = when or datetime.now()
        path = self.memory_dir / f"{when.date().isoformat()}.md"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {when.isoformat(timespec='minutes')}\n\n{summary.strip()}\n")

    def last_7_days(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        parts: list[str] = []
        for i in range(7):
            d = (now - timedelta(days=i)).date()
            p = self.memory_dir / f"{d.isoformat()}.md"
            if p.exists():
                parts.append(
                    f"### {d.isoformat()}\n{p.read_text(encoding='utf-8').strip()}"
                )
        return "\n\n".join(parts)

    def read_facts(self) -> str:
        if self.facts_path.exists():
            return self.facts_path.read_text(encoding="utf-8")
        return ""

    def append_fact(self, key: str, value: str) -> None:
        key = key.strip()
        value = value.strip()
        if not key or not value:
            return
        with self.facts_path.open("a", encoding="utf-8") as f:
            f.write(f"{key}: {value}\n")
