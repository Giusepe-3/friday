"""Text-to-speech via the Piper binary.

Pipes text to ``piper.exe`` which writes a WAV. We then play the WAV through
``audio.play_wav``. Temporary files are cleaned up in ``finally``."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import audio


class TTS:
    def __init__(self, piper_exe: Path, voice: Path) -> None:
        self.piper_exe = piper_exe
        self.voice = voice

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = Path(tmp.name)
        try:
            subprocess.run(
                [
                    str(self.piper_exe),
                    "--model",
                    str(self.voice),
                    "--output_file",
                    str(out),
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                check=True,
            )
            audio.play_wav(out)
        finally:
            out.unlink(missing_ok=True)
