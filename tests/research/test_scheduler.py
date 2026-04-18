"""Research scheduler tests — parse_cron, nominal_last_fire, catchup_due."""
from datetime import datetime, timedelta

import pytest

from src.research.storage import ResearchStorage
from src.research.scheduler import (
    parse_cron,
    nominal_last_fire,
    catchup_due,
    JobSpec,
)


def test_parse_cron_daily():
    assert parse_cron("09:00") is not None


def test_parse_cron_weekly():
    assert parse_cron("SUN 18:00") is not None


def test_parse_cron_invalid():
    with pytest.raises(ValueError):
        parse_cron("nonsense")


def test_nominal_last_fire_daily_after():
    now = datetime(2026, 4, 18, 10, 0)
    last = nominal_last_fire("09:00", now)
    assert last == datetime(2026, 4, 18, 9, 0)


def test_nominal_last_fire_daily_before():
    now = datetime(2026, 4, 18, 8, 30)
    last = nominal_last_fire("09:00", now)
    assert last == datetime(2026, 4, 17, 9, 0)


def test_catchup_within_window(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    job = JobSpec("daily_standup", "09:00", prompt="p", reason="r")
    now = datetime(2026, 4, 18, 10, 0)
    due = catchup_due(s, [job], window_h=12, now=now)
    assert [j.name for j in due] == ["daily_standup"]


def test_catchup_outside_window(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    job = JobSpec("daily_standup", "09:00", prompt="p", reason="r")
    now = datetime(2026, 4, 18, 22, 1)  # 13h+ after 09:00
    due = catchup_due(s, [job], window_h=12, now=now)
    assert due == []


def test_catchup_already_fired(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    s.record_job_fired("daily_standup", datetime(2026, 4, 18, 9, 1), "queued")
    job = JobSpec("daily_standup", "09:00", prompt="p", reason="r")
    now = datetime(2026, 4, 18, 10, 0)
    due = catchup_due(s, [job], window_h=12, now=now)
    assert due == []
