import re
from types import SimpleNamespace

import pytest

from src.tools import notes_tool
from src.tools import state as tool_state


@pytest.fixture(autouse=True)
def _reset_state():
    tool_state.reset()
    yield
    tool_state.reset()


@pytest.mark.asyncio
async def test_note_line_format(tmp_path):
    notes = tmp_path / "notes.md"
    cfg = SimpleNamespace(paths=SimpleNamespace(notes=notes))
    tool_state.init(cfg=cfg)

    result = await notes_tool.write_note.handler({"content": "buy coffee"})

    assert result["content"][0]["text"] == "noted"
    lines = notes.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert re.match(r"^- \[\d{2}:\d{2}\] buy coffee$", lines[0])


@pytest.mark.asyncio
async def test_note_append_preserves_prior(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("- [09:00] earlier\n", encoding="utf-8")
    cfg = SimpleNamespace(paths=SimpleNamespace(notes=notes))
    tool_state.init(cfg=cfg)

    await notes_tool.write_note.handler({"content": "later"})

    body = notes.read_text(encoding="utf-8")
    assert "earlier" in body
    assert "later" in body


@pytest.mark.asyncio
async def test_empty_note_skipped(tmp_path):
    notes = tmp_path / "notes.md"
    cfg = SimpleNamespace(paths=SimpleNamespace(notes=notes))
    tool_state.init(cfg=cfg)

    result = await notes_tool.write_note.handler({"content": "   "})

    assert result["content"][0]["text"] == "empty note, skipped"
    assert not notes.exists()
