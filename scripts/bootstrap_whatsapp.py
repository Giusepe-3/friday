"""One-shot: open WhatsApp Web in a persistent Chromium profile so the
user can scan the QR code. The session cookie is then reused by the
``send_whatsapp`` MCP tool without further interaction.

Run once after ``playwright install chromium``. Re-run if the session
ever expires (WhatsApp logs out linked devices after long inactivity).
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


PROFILE_DIR = Path.home() / "friday" / ".whatsapp_profile"


def main() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
        )
        page = ctx.new_page()
        page.goto("https://web.whatsapp.com")
        print(f"WhatsApp Web opened. Profile at {PROFILE_DIR}.")
        input("Press Enter after QR scan complete...")
        ctx.close()
    print("Bootstrap done — send_whatsapp can now reuse this profile.")


if __name__ == "__main__":
    main()
