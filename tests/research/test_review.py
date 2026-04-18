"""weekly_research_review orchestration — mocked Brain."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.research.storage import ResearchStorage
from src.research.review import generate_weekly_review


@pytest.mark.asyncio
async def test_generate_weekly_review(tmp_path):
    s = ResearchStorage(tmp_path / "research")
    s.append_note("Verification", "first thought")
    s.append_note("Alignment", "second")
    pid = s.log_prediction("c", 60, "2020-01-01")
    s.resolve_prediction(pid, "true")

    brain = AsyncMock()
    brain.ask_oneshot.return_value = (
        "## Threads emerging\n- x\n\n## Gaps\n- y\n\n## Suggested focus next week\n- z\n"
    )

    body, path = await generate_weekly_review(s, brain)
    assert path.exists()
    full = path.read_text(encoding="utf-8")
    assert "Threads emerging" in full
    assert "Raw inputs reviewed" in full
    brain.ask_oneshot.assert_called_once()
