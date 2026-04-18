"""Text-to-speech via Coqui XTTS v2 (voice cloning).

Loads the XTTS v2 model once at startup and keeps it in memory. On
``speak()`` we synth a WAV to a temp file, then play through ``audio.play_wav``.

Two ways to pick the speaker:

* ``voice_reference`` — path to a 6–10 s reference WAV for voice cloning
  (e.g. a Kerry Condon clip). Takes precedence when present.
* ``voice_speaker`` — name of an XTTS v2 built-in speaker (e.g.
  ``"Claribel Dervla"`` for Irish-lilt female). Used when no reference is set.

GPU is used automatically when available; CUDA on the 3070Ti makes
inference well under a second per sentence."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncIterator, Optional

# Auto-accept the Coqui public model license (CPML) so first-run is
# non-interactive. Personal/non-commercial use is permitted.
os.environ.setdefault("COQUI_TOS_AGREED", "1")

import torch
from TTS.api import TTS as CoquiTTS

from . import audio

XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"


class TTS:
    def __init__(
        self,
        voice_reference: Optional[Path] = None,
        voice_speaker: str = "Claribel Dervla",
        language: str = "en",
        playback_gain: float = 1.0,
        playback_speed: float = 1.0,
    ) -> None:
        self.voice_reference = voice_reference if voice_reference and voice_reference.exists() else None
        self.voice_speaker = voice_speaker
        self.language = language
        self.playback_gain = playback_gain
        self.playback_speed = playback_speed
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._engine = CoquiTTS(model_name=XTTS_MODEL).to(device)

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = Path(tmp.name)
        try:
            kwargs = {
                "text": text,
                "file_path": str(out),
                "language": self.language,
            }
            if self.voice_reference is not None:
                kwargs["speaker_wav"] = str(self.voice_reference)
            else:
                kwargs["speaker"] = self.voice_speaker
            self._engine.tts_to_file(**kwargs)
            audio.play_wav(out, gain=self.playback_gain, speed=self.playback_speed)
        finally:
            out.unlink(missing_ok=True)


async def speak_streaming(
    tts: "TTS",
    sentence_iter: AsyncIterator[str],
    echo: bool = True,
) -> str:
    """Consume an async iterator of sentences, speaking each through ``tts``.

    Producer (brain) and consumer (TTS) run concurrently — the first
    sentence hits the speaker while later sentences are still being
    generated. Returns the accumulated full text.

    ``tts.speak`` is blocking; we bridge through ``asyncio.to_thread`` so
    the producer keeps emitting tokens while playback happens on a worker.

    When ``echo`` is True (default), each sentence is printed to stdout as
    it arrives so you can watch the full reply in the terminal."""
    queue: asyncio.Queue = asyncio.Queue()
    collected: list[str] = []

    async def producer() -> None:
        try:
            async for sentence in sentence_iter:
                collected.append(sentence)
                if echo:
                    print(f"[reply] {sentence}", flush=True)
                await queue.put(sentence)
        finally:
            await queue.put(None)

    async def consumer() -> None:
        while True:
            s = await queue.get()
            if s is None:
                break
            await asyncio.to_thread(tts.speak, s)

    await asyncio.gather(producer(), consumer())
    return " ".join(collected)
