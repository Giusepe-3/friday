"""Audio input/output helpers built on ``sounddevice`` (PortAudio).

Two capabilities:

* :func:`mic_stream` — async generator yielding raw int16 mono PCM frames of a
  fixed size. The PortAudio callback runs on a background thread; we bridge
  to asyncio via ``loop.call_soon_threadsafe``.
* :func:`play_wav` — blocking WAV playback through the default output device.
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import AsyncIterator

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000  # OpenWakeWord + Whisper native


async def mic_stream(frame_samples: int) -> AsyncIterator[bytes]:
    """Yield int16 mono PCM frames of length ``frame_samples``.

    Each yielded value is ``frame_samples * 2`` bytes (int16). The generator
    runs forever — callers break out when they have what they need.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _callback(indata, frames, time_info, status):
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    stream = sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=frame_samples,
        dtype="int16",
        channels=1,
        callback=_callback,
    )
    stream.start()
    try:
        while True:
            yield await queue.get()
    finally:
        stream.stop()
        stream.close()


def play_wav(path: Path) -> None:
    """Play a WAV file through the default output device. Blocks until done."""
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())

    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[width]
    arr = np.frombuffer(frames, dtype=dtype)
    if channels > 1:
        arr = arr.reshape(-1, channels)

    sd.play(arr, rate)
    sd.wait()
