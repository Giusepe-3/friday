from datetime import datetime, timedelta

from src.memory import Memory


def test_facts_round_trip(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    m.append_fact("birthday", "oct 12")
    m.append_fact("favourite artist", "bowie")
    content = m.read_facts()
    assert "birthday: oct 12" in content
    assert "favourite artist: bowie" in content


def test_empty_facts_returns_empty_string(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    assert m.read_facts() == ""


def test_append_fact_trims_and_ignores_empty(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    m.append_fact("  key  ", "  value  ")
    m.append_fact("", "orphan")
    m.append_fact("missing", "")
    lines = m.read_facts().splitlines()
    assert lines == ["key: value"]


def test_summary_append_and_7_day_window(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    now = datetime.now()
    m.append_summary("today's summary", now)
    m.append_summary("three days ago", now - timedelta(days=3))
    combined = m.last_7_days(now)
    assert "today's summary" in combined
    assert "three days ago" in combined


def test_older_than_7_days_excluded(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    now = datetime.now()
    m.append_summary("ancient", now - timedelta(days=30))
    assert "ancient" not in m.last_7_days(now)


def test_same_day_multiple_summaries_accumulate(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    now = datetime.now()
    m.append_summary("first", now)
    m.append_summary("second", now)
    window = m.last_7_days(now)
    assert "first" in window
    assert "second" in window
