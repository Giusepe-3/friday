from datetime import datetime

import pytest

from src.tools import util_tool


@pytest.mark.asyncio
async def test_get_time_returns_parseable_iso():
    result = await util_tool.get_time.handler({})
    text = result["content"][0]["text"]
    parsed = datetime.fromisoformat(text)
    delta = abs((datetime.now() - parsed).total_seconds())
    assert delta < 5, f"get_time drift too large: {delta}s"
