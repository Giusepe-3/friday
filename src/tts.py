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

import os
import tempfile
from pathlib import Path
from typing import Optional

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
    ) -> None:
        self.voice_reference = voice_reference if voice_reference and voice_reference.exists() else None
        self.voice_speaker = voice_speaker
        self.language = language
        self.playback_gain = playback_gain
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
            audio.play_wav(out, gain=self.playback_gain)
        finally:
            out.unlink(missing_ok=True)
