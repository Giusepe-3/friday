import json
from datetime import datetime, timedelta

import pytest

from src.scheduler import AlarmScheduler


@pytest.mark.asyncio
async def test_set_persists_to_json(tmp_path):
    sched = AlarmScheduler(tmp_path / "alarms.json", speak=lambda _s: None)
    await sched.start()
    future = datetime.now() + timedelta(hours=1)
    aid = sched.set(future, "take meds")
    data = json.loads((tmp_path / "alarms.json").read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == aid
    assert data[0]["label"] == "take meds"
    sched.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_removes(tmp_path):
    sched = AlarmScheduler(tmp_path / "alarms.json", speak=lambda _s: None)
    await sched.start()
    aid = sched.set(datetime.now() + timedelta(hours=1), "x")
    assert sched.cancel(aid) is True
    assert sched.cancel(aid) is False
    assert sched.list() == []
    sched.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reload_on_start(tmp_path):
    path = tmp_path / "alarms.json"
    sched1 = AlarmScheduler(path, speak=lambda _s: None)
    await sched1.start()
    sched1.set(datetime.now() + timedelta(hours=2), "survive")
    sched1.sched.shutdown(wait=False)

    sched2 = AlarmScheduler(path, speak=lambda _s: None)
    await sched2.start()
    assert any(a["label"] == "survive" for a in sched2.list())
    sched2.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_alarms_purged_on_start(tmp_path):
    path = tmp_path / "alarms.json"
    path.write_text(
        json.dumps(
            [
                {"id": "old", "when": (datetime.now() - timedelta(days=1)).isoformat(), "label": "stale"},
                {"id": "new", "when": (datetime.now() + timedelta(days=1)).isoformat(), "label": "keep"},
            ]
        ),
        encoding="utf-8",
    )
    sched = AlarmScheduler(path, speak=lambda _s: None)
    await sched.start()
    labels = [a["label"] for a in sched.list()]
    assert labels == ["keep"]
    sched.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_list_sorted_by_when(tmp_path):
    sched = AlarmScheduler(tmp_path / "alarms.json", speak=lambda _s: None)
    await sched.start()
    t_later = datetime.now() + timedelta(hours=5)
    t_sooner = datetime.now() + timedelta(hours=1)
    sched.set(t_later, "later")
    sched.set(t_sooner, "sooner")
    labels = [a["label"] for a in sched.list()]
    assert labels == ["sooner", "later"]
    sched.sched.shutdown(wait=False)
