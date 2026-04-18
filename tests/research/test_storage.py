from datetime import datetime, timedelta
import json

import pytest

from src.research.storage import ResearchStorage, slugify


def test_slugify_basic():
    assert slugify("Verification") == "verification"


def test_slugify_spaces_to_hyphens():
    assert slugify("RSI Verification") == "rsi-verification"


def test_slugify_collapses_non_alphanumeric():
    assert slugify("Gradient hacking!!!") == "gradient-hacking"
    assert slugify("  foo   bar  ") == "foo-bar"


def test_slugify_drops_leading_trailing_hyphens():
    assert slugify("--foo--") == "foo"


def test_storage_creates_directory_tree(tmp_path):
    root = tmp_path / "research"
    ResearchStorage(root)
    assert (root / "notes").is_dir()
    assert (root / "summaries").is_dir()
    assert (root / "standups").is_dir()
    assert (root / "reviews").is_dir()


def test_storage_paths(tmp_research):
    assert tmp_research.paper_queue_path.name == "paper_queue.json"
    assert tmp_research.predictions_path.name == "predictions.json"
    assert tmp_research.index_path.name == "index.json"
    assert tmp_research.schedule_state_path.name == "schedule_state.json"


def test_append_note_creates_topic_file(tmp_research):
    tmp_research.append_note("Verification", "first thought")
    topic_path = tmp_research.notes_dir / "verification.md"
    assert topic_path.exists()
    body = topic_path.read_text(encoding="utf-8")
    assert body.startswith("# Verification\n")
    assert "first thought" in body


def test_append_note_timestamp_header(tmp_research):
    tmp_research.append_note("Verification", "body")
    body = (tmp_research.notes_dir / "verification.md").read_text(encoding="utf-8")
    import re
    assert re.search(r"## \d{4}-\d{2}-\d{2} \d{2}:\d{2}", body)


def test_append_note_appends_on_second_call(tmp_research):
    tmp_research.append_note("Verification", "first")
    tmp_research.append_note("Verification", "second")
    body = (tmp_research.notes_dir / "verification.md").read_text(encoding="utf-8")
    assert "first" in body
    assert "second" in body


def test_append_note_updates_index(tmp_research):
    tmp_research.append_note("Verification", "body")
    idx = json.loads(tmp_research.index_path.read_text(encoding="utf-8"))
    assert "verification" in idx
    assert idx["verification"]["display"] == "Verification"
    assert idx["verification"]["note_count"] == 1


def test_append_note_index_increments(tmp_research):
    tmp_research.append_note("Verification", "a")
    tmp_research.append_note("Verification", "b")
    idx = json.loads(tmp_research.index_path.read_text(encoding="utf-8"))
    assert idx["verification"]["note_count"] == 2


def test_list_topics(tmp_research):
    tmp_research.append_note("Verification", "a")
    tmp_research.append_note("Alignment", "b")
    topics = tmp_research.list_topics()
    slugs = {t["slug"] for t in topics}
    assert slugs == {"verification", "alignment"}
