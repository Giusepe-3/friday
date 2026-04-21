"""WhatsApp Web send tool via Playwright.

One-time setup:
    1. ``playwright install chromium`` (installs the browser binary).
    2. ``python scripts/bootstrap_whatsapp.py`` (scan QR — caches the
       WhatsApp session in the persistent profile at
       ``~/friday/.whatsapp_profile``).

Afterwards ``send_whatsapp(phone, message)`` reuses the cached session
non-interactively (the browser still opens visibly so the user can watch).
"""

from __future__ import annotations

import urllib.parse
from pathlib import Path

from claude_agent_sdk import tool
from playwright.sync_api import sync_playwright


PROFILE_DIR = Path.home() / "friday" / ".whatsapp_profile"


def _sanitize_phone(phone: str) -> str:
    """Strip everything but digits (drops +, spaces, dashes, parens)."""
    return "".join(c for c in phone if c.isdigit())


def _wait_with_fallback(page, primary: str, fallback: str, timeout_ms: int):
    """Wait for primary selector; on failure, fall back to the alternate."""
    try:
        return page.wait_for_selector(primary, timeout=timeout_ms)
    except Exception:
        return page.wait_for_selector(fallback, timeout=10_000)


@tool(
    "send_whatsapp",
    "Send a WhatsApp message by opening WhatsApp Web in a persistent "
    "Chromium profile, clicking the send button, and waiting for the "
    "outgoing tick. Requires one-time `playwright install chromium` + "
    "`scripts/bootstrap_whatsapp.py` QR scan.",
    {"phone": str, "message": str},
)
async def send_whatsapp(args):
    phone = args["phone"]
    message = args["message"]
    digits = _sanitize_phone(phone)
    url = (
        "https://web.whatsapp.com/send?"
        f"phone={digits}&text={urllib.parse.quote(message)}"
    )

    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
            )
            try:
                page = ctx.new_page()
                page.goto(url)
                send_btn = _wait_with_fallback(
                    page,
                    'button[aria-label="Send"]',
                    '[data-testid="send"]',
                    60_000,
                )
                send_btn.click()
                _wait_with_fallback(
                    page,
                    'span[data-testid="msg-dblcheck"]',
                    '[data-testid="msg-check"]',
                    30_000,
                )
            finally:
                ctx.close()
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}
