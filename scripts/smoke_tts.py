"""Smoke test: synthesise one line with XTTS v2 and play through speakers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as cfg_mod
from src.tts import TTS


def main() -> None:
    cfg = cfg_mod.load()
    print(f"Loading XTTS v2 (reference={cfg.voice_reference}, speaker={cfg.voice_speaker})…")
    tts = TTS(
        voice_reference=cfg.voice_reference,
        voice_speaker=cfg.voice_speaker,
        language=cfg.voice_language,
    )
    tts.speak("Hello, boss. Voice cloning is online.")


if __name__ == "__main__":
    main()
