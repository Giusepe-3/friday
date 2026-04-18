"""Smoke test: VAD-bounded mic capture → Groq STT → print transcript."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import audio, config as cfg_mod, stt as stt_mod, vad as vad_mod


async def main() -> None:
    cfg = cfg_mod.load()
    if not cfg.groq_api_key:
        raise SystemExit("GROQ_API_KEY missing from config/.env")
    vad = vad_mod.VAD()
    stt = stt_mod.STT(cfg.groq_api_key)

    print("Speak when ready. Recording until you go silent…")
    buf = bytearray()
    speech_seen = False
    silent = 0
    max_frames = cfg.max_recording_s * 1000 // vad.frame_ms
    frames = 0
    async for frame in audio.mic_stream(vad.frame_samples):
        buf.extend(frame)
        frames += 1
        if vad.is_speech(frame):
            speech_seen = True
            silent = 0
        elif speech_seen:
            silent += 1
            if silent >= vad.silence_frames_needed:
                break
        if frames >= max_frames:
            break

    print(f"Captured {len(buf)} bytes of PCM, transcribing…")
    text = await stt.transcribe(bytes(buf), cfg.sample_rate)
    print(f"Transcript: {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
