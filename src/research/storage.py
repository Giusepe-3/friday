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
_ARXIV_RE = re.compile(r"(?:arxiv[:/]|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})", re.IGNORECASE)


def arxiv_id_from_ref(ref: str) -> str | None:
    match = _ARXIV_RE.search(ref or "")
    return match.group(1) if match else None


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

    def write_standup(
        self,
        yesterday: str,
        today: str,
        blockers: str,
        when: datetime | None = None,
    ) -> Path:
        when = when or datetime.now()
        path = self.standups_dir / f"{when.strftime('%Y-%m-%d')}.md"
        existed = path.exists()
        with path.open("a", encoding="utf-8") as f:
            if not existed:
                f.write(f"# Standup — {when.strftime('%Y-%m-%d')}\n\n")
                header = "Morning"
            else:
                header = "Mid-day"
            f.write(f"## {header} ({when.strftime('%H:%M')})\n\n")
            f.write(f"### Yesterday\n{yesterday.strip()}\n\n")
            f.write(f"### Today\n{today.strip()}\n\n")
            f.write(f"### Blockers\n{blockers.strip()}\n\n")
        return path

    def write_review(self, body: str, when: datetime | None = None) -> Path:
        when = when or datetime.now()
        path = self.reviews_dir / f"{when.strftime('%Y-%m-%d')}.md"
        _atomic_write_text(path, f"# Weekly review — {when.strftime('%Y-%m-%d')}\n\n{body}\n")
        return path

    def write_summary(
        self,
        ref: str,
        url: str,
        title: str,
        body: str,
        when: datetime | None = None,
    ) -> Path:
        when = when or datetime.now()
        arxiv = arxiv_id_from_ref(ref)
        if arxiv:
            stem = arxiv
        else:
            stem = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        path = self.summaries_dir / f"{stem}.md"
        content = (
            f"# {title}\n\n"
            f"**Ref:** {ref}\n"
            f"**URL:** {url}\n"
            f"**Summarized:** {when.strftime('%Y-%m-%d')}\n\n"
            f"{body.strip()}\n"
        )
        _atomic_write_text(path, content)
        return path

    def read_schedule_state(self) -> dict:
        if self.schedule_state_path.exists():
            return json.loads(self.schedule_state_path.read_text(encoding="utf-8") or "{}")
        return {}

    def write_schedule_state(self, data: dict) -> None:
        _atomic_write_json(self.schedule_state_path, data)

    def record_job_fired(self, job_name: str, fired_at: datetime, outcome: str) -> None:
        data = self.read_schedule_state()
        entry = data.get(job_name, {})
        entry["last_fired_at"] = fired_at.strftime("%Y-%m-%dT%H:%M:%S")
        entry["last_outcome"] = outcome
        data[job_name] = entry
        self.write_schedule_state(data)

    def enqueue_pending_prompt(self, prompt: str, reason: str) -> None:
        data = self.read_schedule_state()
        queue = data.get("pending_prompts", [])
        queue.append({
            "prompt": prompt,
            "reason": reason,
            "queued_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        data["pending_prompts"] = queue
        self.write_schedule_state(data)

    def pop_pending_prompt(self) -> dict | None:
        data = self.read_schedule_state()
        queue = data.get("pending_prompts", [])
        if not queue:
            return None
        first = queue.pop(0)
        data["pending_prompts"] = queue
        self.write_schedule_state(data)
        return first

    def state_summary(self, max_tokens_hint: int = 500) -> str:
        lines: list[str] = []
        open_preds = sorted(self.predictions_open(), key=lambda p: p.get("resolve_by", ""))[:3]
        if open_preds:
            lines.append("Open predictions (top 3 by nearest resolve_by):")
            for p in open_preds:
                lines.append(f"  - {p['id']} ({p['confidence']}%): {p['claim']} — resolves {p['resolve_by']}")
        else:
            lines.append("Open predictions: none")

        latest_standup = None
        for md in sorted(self.standups_dir.glob("*.md"), reverse=True):
            latest_standup = md
            break
        if latest_standup is not None:
            head = latest_standup.read_text(encoding="utf-8")[:800]
            lines.append(f"\nLast standup: {latest_standup.stem}")
            lines.append(head.strip())
        else:
            lines.append("\nLast standup: none yet")

        topics = self.list_topics()[:5]
        if topics:
            lines.append("\nRecent topics (last 7 days):")
            for t in topics:
                lines.append(f"  - {t['slug']} ({t.get('note_count', '?')} entries, last {t.get('last_updated', '?')})")
        else:
            lines.append("\nRecent topics: none")

        queue = self._read_paper_queue()
        statuses = {"queued": 0, "summarized": 0, "dropped": 0}
        for p in queue:
            statuses[p.get("status", "queued")] = statuses.get(p.get("status", "queued"), 0) + 1
        lines.append(f"\nPaper queue: {statuses['queued']} queued, {statuses['summarized']} summarised, {statuses['dropped']} dropped")

        out = "\n".join(lines)
        max_chars = max_tokens_hint * 4
        if len(out) > max_chars:
            out = out[:max_chars].rsplit("\n", 1)[0] + "\n... (truncated)"
        return out
