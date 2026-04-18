"""Smoke test: record 3s from the default mic, echo it back through speakers."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import audio
from src import config as cfg_mod


FRAME_MS = 30
FRAME_SAMPLES = int(audio.SAMPLE_RATE * FRAME_MS / 1000)
RECORD_S = 3


async def main() -> None:
    cfg = cfg_mod.load()
    print(f"Recording {RECORD_S}s from default mic…")
    buf = bytearray()
    target_frames = RECORD_S * 1000 // FRAME_MS
    async for frame in audio.mic_stream(FRAME_SAMPLES):
        buf.extend(frame)
        if len(buf) >= target_frames * FRAME_SAMPLES * 2:
            break

    print(f"Playing back (gain {cfg.playback_gain})…")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.SAMPLE_RATE)
            w.writeframes(bytes(buf))
        audio.play_wav(out, gain=cfg.playback_gain)
    finally:
        out.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
