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
