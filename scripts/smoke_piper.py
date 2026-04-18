"""Smoke test: synthesise one line with Piper and play it through speakers."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as cfg_mod


def main() -> None:
    cfg = cfg_mod.load()
    text = "Hello, boss. Piper works."
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        subprocess.run(
            [str(cfg.piper_exe), "--model", str(cfg.piper_voice), "--output_file", str(out)],
            input=text.encode("utf-8"),
            check=True,
        )
        with wave.open(str(out), "rb") as w:
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
        arr = np.frombuffer(frames, dtype=np.int16)
        sd.play(arr, rate)
        sd.wait()
    finally:
        out.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
