"""APScheduler-backed alarm manager.

Alarms are persisted to a JSON file (``cfg.paths.alarms_json``) as a plain
list of ``{"id", "when", "label"}`` dicts. We do NOT use APScheduler's
jobstore — on :meth:`start`, we read the JSON and re-schedule any future
alarms. On fire, the callback calls ``speak(f"Boss — {label}.")`` directly,
bypassing Claude so alarms work offline."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


class AlarmScheduler:
    def __init__(
        self,
        alarms_path: Path,
        speak: Callable[[str], None],
    ) -> None:
        self.path = alarms_path
        self.speak = speak
        self.sched = AsyncIOScheduler()
        self.alarms: dict[str, dict] = {}

    async def start(self) -> None:
        self.sched.start()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8") or "[]")
            now = datetime.now()
            for a in data:
                when = datetime.fromisoformat(a["when"])
                if when > now:
                    self.alarms[a["id"]] = a
                    self._schedule(a["id"], when, a["label"])
            self._persist()

    def set(self, when: datetime, label: str) -> str:
        aid = uuid.uuid4().hex[:8]
        record = {"id": aid, "when": when.isoformat(), "label": label}
        self.alarms[aid] = record
        self._schedule(aid, when, label)
        self._persist()
        return aid

    def cancel(self, aid: str) -> bool:
        if aid not in self.alarms:
            return False
        try:
            self.sched.remove_job(aid)
        except Exception:
            pass
        del self.alarms[aid]
        self._persist()
        return True

    def list(self) -> list[dict]:
        return sorted(self.alarms.values(), key=lambda a: a["when"])

    def _schedule(self, aid: str, when: datetime, label: str) -> None:
        def _fire():
            try:
                self.speak(f"Boss — {label}.")
            finally:
                self.alarms.pop(aid, None)
                self._persist()

        self.sched.add_job(_fire, DateTrigger(run_date=when), id=aid)

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(list(self.alarms.values()), indent=2),
            encoding="utf-8",
        )
