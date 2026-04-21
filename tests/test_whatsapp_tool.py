"""Tests for send_whatsapp MCP tool.

Mocks sync_playwright so no browser launches. Verifies:
- phone sanitization (digits only) + URL encoding of message
- happy-path return shape {"ok": True, "error": None}
- selector timeout returns {"ok": False, "error": <str>}
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.tools import whatsapp_tool


def _make_playwright_mock(page_mock: MagicMock) -> MagicMock:
    """Build a mock that behaves like sync_playwright() context manager."""
    ctx = MagicMock()
    ctx.new_page.return_value = page_mock

    chromium = MagicMock()
    chromium.launch_persistent_context.return_value = ctx

    pw = MagicMock()
    pw.chromium = chromium

    spw = MagicMock()
    spw.__enter__.return_value = pw
    spw.__exit__.return_value = False
    return spw


@pytest.mark.asyncio
async def test_sanitizes_phone_and_url_encodes_message(monkeypatch):
    page = MagicMock()
    spw = _make_playwright_mock(page)
    monkeypatch.setattr(whatsapp_tool, "sync_playwright", lambda: spw)

    result = await whatsapp_tool.send_whatsapp.handler({
        "phone": "+1 555-123-4567",
        "message": "hi there",
    })

    assert page.goto.called, "page.goto must be called"
    url = page.goto.call_args.args[0]
    assert "phone=15551234567" in url
    assert "text=hi%20there" in url
    assert result == {"ok": True, "error": None}


@pytest.mark.asyncio
async def test_selector_timeout_returns_error(monkeypatch):
    page = MagicMock()
    # both primary and fallback selectors time out
    page.wait_for_selector.side_effect = Exception("Timeout 30000ms exceeded")
    spw = _make_playwright_mock(page)
    monkeypatch.setattr(whatsapp_tool, "sync_playwright", lambda: spw)

    result = await whatsapp_tool.send_whatsapp.handler({
        "phone": "5551234567",
        "message": "hello",
    })

    assert result["ok"] is False
    assert isinstance(result["error"], str)
    assert result["error"]
