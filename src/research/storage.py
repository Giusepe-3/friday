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

    def paper_queue_add(self, ref: str, why: str, when: datetime | None = None) -> str:
        when = when or datetime.now()
        data = self._read_paper_queue()
        for entry in data:
            if entry["ref"] == ref:
                return entry["id"]
        pid = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:8]
        data.append({
            "id": pid,
            "ref": ref,
            "why": why,
            "added_at": when.strftime("%Y-%m-%dT%H:%M"),
            "status": "queued",
        })
        _atomic_write_json(self.paper_queue_path, data)
        return pid

    def paper_queue_mark_summarised(self, pid: str, summary_path: str, when: datetime | None = None) -> None:
        when = when or datetime.now()
        data = self._read_paper_queue()
        for entry in data:
            if entry["id"] == pid:
                entry["status"] = "summarized"
                entry["summary_path"] = summary_path
                entry["summarized_at"] = when.strftime("%Y-%m-%dT%H:%M")
                break
        else:
            raise KeyError(f"paper_queue id not found: {pid}")
        _atomic_write_json(self.paper_queue_path, data)

    def paper_queue_list(self, status: str | None = None) -> list[dict]:
        data = self._read_paper_queue()
        if status is None:
            return data
        return [p for p in data if p.get("status") == status]

    def _read_paper_queue(self) -> list[dict]:
        if self.paper_queue_path.exists():
            return json.loads(self.paper_queue_path.read_text(encoding="utf-8") or "[]")
        return []

    _OUTCOMES = ("true", "false", "ambiguous")

    def log_prediction(
        self,
        claim: str,
        confidence: int,
        resolve_by: str,
        when: datetime | None = None,
    ) -> str:
        if not (0 <= int(confidence) <= 100):
            raise ValueError(f"confidence must be 0-100, got {confidence}")
        when = when or datetime.now()
        pid = hashlib.sha256(f"{claim}|{when.isoformat()}".encode("utf-8")).hexdigest()[:8]
        data = self._read_predictions()
        data.append({
            "id": pid,
            "claim": claim,
            "confidence": int(confidence),
            "resolve_by": resolve_by,
            "created_at": when.strftime("%Y-%m-%dT%H:%M"),
            "resolved_at": None,
            "outcome": None,
        })
        _atomic_write_json(self.predictions_path, data)
        return pid

    def predictions_due(self, today: str | None = None) -> list[dict]:
        today = today or datetime.now().strftime("%Y-%m-%d")
        return [
            p for p in self._read_predictions()
            if p["resolved_at"] is None and p["resolve_by"] <= today
        ]

    def predictions_open(self) -> list[dict]:
        return [p for p in self._read_predictions() if p["resolved_at"] is None]

    def resolve_prediction(self, pid: str, outcome: str, when: str | None = None) -> bool:
        if outcome not in self._OUTCOMES:
            raise ValueError(f"outcome must be one of {self._OUTCOMES}, got {outcome!r}")
        data = self._read_predictions()
        for entry in data:
            if entry["id"] == pid:
                if entry["resolved_at"] is not None:
                    return False
                entry["outcome"] = outcome
                entry["resolved_at"] = when or datetime.now().strftime("%Y-%m-%dT%H:%M")
                _atomic_write_json(self.predictions_path, data)
                return True
        return False

    def brier_score(self) -> float | None:
        resolved = [
            p for p in self._read_predictions()
            if p["resolved_at"] is not None and p["outcome"] in ("true", "false")
        ]
        if not resolved:
            return None
        total = 0.0
        for p in resolved:
            prob = p["confidence"] / 100.0
            obs = 1.0 if p["outcome"] == "true" else 0.0
            total += (obs - prob) ** 2
        return total / len(resolved)

    def _read_predictions(self) -> list[dict]:
        if self.predictions_path.exists():
            return json.loads(self.predictions_path.read_text(encoding="utf-8") or "[]")
        return []
