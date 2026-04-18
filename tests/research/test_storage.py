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
