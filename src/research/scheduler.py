"""Research scheduler: cron jobs + first-wake-catchup."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


_DAY_NAMES = {"MON": "mon", "TUE": "tue", "WED": "wed", "THU": "thu",
              "FRI": "fri", "SAT": "sat", "SUN": "sun"}

_CRON_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_CRON_DAY_HHMM = re.compile(r"^([A-Za-z]{3})\s+(\d{1,2}):(\d{2})$")


@dataclass(frozen=True)
class JobSpec:
    name: str
    trigger_str: str
    prompt: str
    reason: str


def parse_cron(spec: str) -> CronTrigger:
    """Accept 'HH:MM' (daily) or 'DAY HH:MM' (weekly)."""
    spec = spec.strip()
    m = _CRON_HHMM.match(spec)
    if m:
        return CronTrigger(hour=int(m.group(1)), minute=int(m.group(2)))
    m = _CRON_DAY_HHMM.match(spec)
    if m:
        day = _DAY_NAMES.get(m.group(1).upper())
        if day is None:
            raise ValueError(f"unknown day: {m.group(1)}")
        return CronTrigger(day_of_week=day, hour=int(m.group(2)), minute=int(m.group(3)))
    raise ValueError(f"cannot parse schedule: {spec!r}")


def nominal_last_fire(trigger_str: str, now: datetime) -> datetime | None:
    try:
        tr = parse_cron(trigger_str)
    except ValueError:
        return None
    last = None
    cursor = now - timedelta(days=14)
    for _ in range(2000):
        nxt = tr.get_next_fire_time(None, cursor)
        if nxt is None:
            break
        # Strip tzinfo to compare with naive now
        if nxt.tzinfo is not None:
            nxt = nxt.replace(tzinfo=None)
        if nxt > now:
            break
        last = nxt
        cursor = nxt + timedelta(seconds=1)
    return last


def catchup_due(
    storage,
    jobs: Iterable[JobSpec],
    window_h: int,
    now: datetime | None = None,
) -> list[JobSpec]:
    now = now or datetime.now()
    state = storage.read_schedule_state()
    due: list[JobSpec] = []
    for job in jobs:
        nominal = nominal_last_fire(job.trigger_str, now)
        if nominal is None:
            continue
        job_state = state.get(job.name, {})
        last_fired_s = job_state.get("last_fired_at")
        if last_fired_s:
            last_fired = datetime.strptime(last_fired_s, "%Y-%m-%dT%H:%M:%S")
            if last_fired >= nominal:
                continue
        if (now - nominal) > timedelta(hours=window_h):
            continue
        due.append(job)
    return due


def register_jobs(
    sched: AsyncIOScheduler,
    jobs: Iterable[JobSpec],
    storage,
) -> None:
    for job in jobs:
        try:
            trigger = parse_cron(job.trigger_str)
        except ValueError as e:
            print(f"[research.scheduler] skip {job.name}: {e}")
            continue

        def _make_callback(j: JobSpec):
            def _fire():
                storage.enqueue_pending_prompt(j.prompt, reason=j.reason)
                storage.record_job_fired(j.name, datetime.now(), "queued")
            return _fire

        sched.add_job(_make_callback(job), trigger, id=f"research_{job.name}")


def default_jobs_from_config(cfg) -> list[JobSpec]:
    sched_map = getattr(cfg, "research_schedules", {}) or {}
    specs: list[JobSpec] = []
    if "daily_standup" in sched_map:
        specs.append(JobSpec(
            name="daily_standup",
            trigger_str=sched_map["daily_standup"],
            prompt="Boss — ready for the standup? Let's do yesterday, today, blockers.",
            reason="scheduled:daily_standup",
        ))
    if "check_predictions" in sched_map:
        specs.append(JobSpec(
            name="check_predictions",
            trigger_str=sched_map["check_predictions"],
            prompt="Boss — any predictions due for resolution today? Run check_predictions.",
            reason="scheduled:check_predictions",
        ))
    if "weekly_research_review" in sched_map:
        specs.append(JobSpec(
            name="weekly_research_review",
            trigger_str=sched_map["weekly_research_review"],
            prompt="Boss — time for the weekly review. Run weekly_research_review and speak the output.",
            reason="scheduled:weekly_research_review",
        ))
    return specs
