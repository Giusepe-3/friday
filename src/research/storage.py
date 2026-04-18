"""Research-mode storage: paths, atomic writes, CRUD across file types.

File shapes match ``docs/specs/2026-04-18-friday-research-mode-design.md`` §4."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s: str) -> str:
    lowered = s.lower().strip()
    collapsed = _SLUG_RE.sub("-", lowered)
    return collapsed.strip("-")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, indent=2))


class ResearchStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.notes_dir = self.root / "notes"
        self.summaries_dir = self.root / "summaries"
        self.standups_dir = self.root / "standups"
        self.reviews_dir = self.root / "reviews"
        self.paper_queue_path = self.root / "paper_queue.json"
        self.predictions_path = self.root / "predictions.json"
        self.index_path = self.root / "index.json"
        self.schedule_state_path = self.root / "schedule_state.json"
        for d in (self.notes_dir, self.summaries_dir, self.standups_dir, self.reviews_dir):
            d.mkdir(parents=True, exist_ok=True)

    def append_note(self, topic: str, content: str, when: datetime | None = None) -> Path:
        when = when or datetime.now()
        slug = slugify(topic)
        if not slug:
            raise ValueError(f"topic slug empty after normalisation: {topic!r}")
        path = self.notes_dir / f"{slug}.md"
        existed = path.exists()
        with path.open("a", encoding="utf-8") as f:
            if not existed:
                f.write(f"# {topic}\n\n")
            f.write(f"## {when.strftime('%Y-%m-%d %H:%M')}\n\n{content.strip()}\n\n")
        self._index_touch(slug=slug, display=topic, when=when)
        return path

    def list_topics(self) -> list[dict]:
        idx = self._read_index()
        return [
            {"slug": slug, **meta}
            for slug, meta in sorted(idx.items(), key=lambda kv: kv[1].get("last_updated", ""), reverse=True)
        ]

    def _read_index(self) -> dict:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        return {}

    def _index_touch(self, slug: str, display: str, when: datetime) -> None:
        idx = self._read_index()
        entry = idx.get(slug)
        ts = when.strftime("%Y-%m-%dT%H:%M")
        if entry is None:
            idx[slug] = {
                "display": display,
                "created_at": ts,
                "last_updated": ts,
                "note_count": 1,
            }
        else:
            entry["display"] = display
            entry["last_updated"] = ts
            entry["note_count"] = int(entry.get("note_count", 0)) + 1
            idx[slug] = entry
        _atomic_write_json(self.index_path, idx)
