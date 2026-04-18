"""Tool handler tests for all 8 research tools."""
import json
import re
from types import SimpleNamespace

import pytest

from src.research.storage import ResearchStorage
from src.research import tools as research_tools
from src.tools import state as tool_state


@pytest.fixture(autouse=True)
def _reset_state():
    tool_state.reset()
    yield
    tool_state.reset()


# ------------------ note_research ------------------

@pytest.mark.asyncio
async def test_note_research_writes(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.note_research.handler(
        {"topic": "Verification", "content": "recursive self-improvement gap"}
    )
    assert r["content"][0]["text"] == "noted: verification"
    body = (s.notes_dir / "verification.md").read_text(encoding="utf-8")
    assert "recursive self-improvement gap" in body


@pytest.mark.asyncio
async def test_note_research_no_storage():
    tool_state.init(research=None)
    r = await research_tools.note_research.handler({"topic": "x", "content": "y"})
    assert "not available" in r["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_note_research_rejects_empty(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.note_research.handler(
        {"topic": "verification", "content": "   "}
    )
    assert "empty" in r["content"][0]["text"].lower()


# ------------------ paper_queue_add ------------------

@pytest.mark.asyncio
async def test_paper_queue_add_tool(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.paper_queue_add.handler(
        {"ref": "arxiv:2410.12345", "why": "foundational"}
    )
    assert "queued" in r["content"][0]["text"]
    data = json.loads(s.paper_queue_path.read_text(encoding="utf-8"))
    assert data[0]["ref"] == "arxiv:2410.12345"


@pytest.mark.asyncio
async def test_paper_queue_add_empty_ref(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.paper_queue_add.handler({"ref": "", "why": "x"})
    assert "empty" in r["content"][0]["text"].lower()


# ------------------ log_prediction ------------------

@pytest.mark.asyncio
async def test_log_prediction_tool(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.log_prediction.handler(
        {"claim": "paper 1 done", "confidence": 70, "resolve_by": "2026-06-01"}
    )
    text = r["content"][0]["text"]
    assert "70%" in text and "2026-06-01" in text


@pytest.mark.asyncio
async def test_log_prediction_bad_date(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.log_prediction.handler(
        {"claim": "x", "confidence": 50, "resolve_by": "some garbage"}
    )
    assert "could not parse" in r["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_log_prediction_natural_date(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.log_prediction.handler(
        {"claim": "x", "confidence": 50, "resolve_by": "in 30 days"}
    )
    assert re.search(r"\d{4}-\d{2}-\d{2}", r["content"][0]["text"])


# ------------------ daily_standup ------------------

@pytest.mark.asyncio
async def test_daily_standup_writes(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.daily_standup.handler(
        {"yesterday": "a", "today": "b", "blockers": "c"}
    )
    assert "recorded" in r["content"][0]["text"]


@pytest.mark.asyncio
async def test_daily_standup_missing_field(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.daily_standup.handler(
        {"yesterday": "a", "today": "b", "blockers": ""}
    )
    assert "required" in r["content"][0]["text"].lower()


# ------------------ check_predictions / resolve_prediction ------------------

@pytest.mark.asyncio
async def test_check_predictions_empty(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.check_predictions.handler({})
    assert "no predictions due" in r["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_check_predictions_due_list(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    pid = s.log_prediction("claim", 60, "2020-01-01")
    r = await research_tools.check_predictions.handler({})
    assert "1 due" in r["content"][0]["text"]
    assert pid in r["content"][0]["text"]


@pytest.mark.asyncio
async def test_resolve_prediction_tool(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    pid = s.log_prediction("x", 50, "2020-01-01")
    r = await research_tools.resolve_prediction.handler({"id": pid, "outcome": "true"})
    assert "resolved" in r["content"][0]["text"]


@pytest.mark.asyncio
async def test_resolve_prediction_invalid_outcome(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    pid = s.log_prediction("x", 50, "2020-01-01")
    r = await research_tools.resolve_prediction.handler({"id": pid, "outcome": "maybe"})
    assert "outcome" in r["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_resolve_prediction_missing_id(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    tool_state.init(research=s)
    r = await research_tools.resolve_prediction.handler({"id": "nope", "outcome": "true"})
    assert "could not resolve" in r["content"][0]["text"].lower()
