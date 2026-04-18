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


def test_paper_queue_add(tmp_research):
    pid = tmp_research.paper_queue_add("arxiv:2410.12345", "relevant to verification")
    data = json.loads(tmp_research.paper_queue_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == pid
    assert data[0]["ref"] == "arxiv:2410.12345"
    assert data[0]["why"] == "relevant to verification"
    assert data[0]["status"] == "queued"
    assert "added_at" in data[0]


def test_paper_queue_dedupes_on_ref(tmp_research):
    a = tmp_research.paper_queue_add("arxiv:2410.12345", "first reason")
    b = tmp_research.paper_queue_add("arxiv:2410.12345", "second reason")
    assert a == b
    data = json.loads(tmp_research.paper_queue_path.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_paper_queue_list_statuses(tmp_research):
    p1 = tmp_research.paper_queue_add("arxiv:2410.12345", "x")
    p2 = tmp_research.paper_queue_add("arxiv:2411.00001", "y")
    tmp_research.paper_queue_mark_summarised(p1, summary_path="summaries/2410.12345.md")
    queued = tmp_research.paper_queue_list(status="queued")
    summarised = tmp_research.paper_queue_list(status="summarized")
    assert [p["id"] for p in queued] == [p2]
    assert [p["id"] for p in summarised] == [p1]


def test_prediction_log(tmp_research):
    pid = tmp_research.log_prediction("paper 1 done by June 1", 70, "2026-06-01")
    data = json.loads(tmp_research.predictions_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    p = data[0]
    assert p["id"] == pid
    assert p["confidence"] == 70
    assert p["claim"] == "paper 1 done by June 1"
    assert p["resolve_by"] == "2026-06-01"
    assert p["resolved_at"] is None
    assert p["outcome"] is None


def test_prediction_due(tmp_research):
    past_id = tmp_research.log_prediction("was yesterday", 50, "2026-04-17")
    future_id = tmp_research.log_prediction("much later", 50, "2027-01-01")
    due = tmp_research.predictions_due(today="2026-04-18")
    assert [p["id"] for p in due] == [past_id]


def test_prediction_resolve(tmp_research):
    pid = tmp_research.log_prediction("claim", 50, "2026-04-17")
    ok = tmp_research.resolve_prediction(pid, "true", when="2026-04-18T09:00")
    assert ok is True
    data = json.loads(tmp_research.predictions_path.read_text(encoding="utf-8"))
    assert data[0]["outcome"] == "true"
    assert data[0]["resolved_at"] == "2026-04-18T09:00"


def test_prediction_resolve_missing_id(tmp_research):
    assert tmp_research.resolve_prediction("does-not-exist", "true") is False


def test_prediction_resolve_already_resolved(tmp_research):
    pid = tmp_research.log_prediction("claim", 50, "2026-04-17")
    tmp_research.resolve_prediction(pid, "true")
    assert tmp_research.resolve_prediction(pid, "false") is False


def test_prediction_resolve_rejects_invalid_outcome(tmp_research):
    pid = tmp_research.log_prediction("claim", 50, "2026-04-17")
    with pytest.raises(ValueError):
        tmp_research.resolve_prediction(pid, "maybe")


def test_prediction_brier_score(tmp_research):
    tmp_research.log_prediction("a", 80, "2026-04-17")
    tmp_research.log_prediction("b", 30, "2026-04-17")
    resolved_ids = [p["id"] for p in tmp_research.predictions_due(today="2026-04-18")]
    tmp_research.resolve_prediction(resolved_ids[0], "true")
    tmp_research.resolve_prediction(resolved_ids[1], "false")
    brier = tmp_research.brier_score()
    assert abs(brier - 0.065) < 1e-9
