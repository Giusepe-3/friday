"""Smoke test: wait for wake word, print a line, exit."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as cfg_mod
from src import wake


async def main() -> None:
    cfg = cfg_mod.load()
    print(f"Listening for wake word '{cfg.wake_model}' (threshold {cfg.wake_threshold})…")
    await wake.listen_for_wake(cfg.wake_model, cfg.wake_threshold)
    print("Wake word detected.")


if __name__ == "__main__":
    asyncio.run(main())
