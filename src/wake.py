"""OpenWakeWord wake-word listener.

Returns as soon as the configured model's confidence crosses ``threshold``
on a frame. Chunk size is 1280 samples (80 ms at 16 kHz), which is what
OpenWakeWord internally expects.

We pin ``inference_framework='onnx'`` because the default tflite backend
has no pre-built Windows wheel. ``onnxruntime`` comes in as a transitive
dependency of ``faster-whisper``, so it's already installed."""

from __future__ import annotations

import numpy as np
from openwakeword.model import Model

from . import audio

CHUNK_SAMPLES = 1280  # 80 ms at 16 kHz — openwakeword native


async def listen_for_wake(model_name: str, threshold: float = 0.5) -> None:
    """Block until ``model_name`` fires above ``threshold`` on one frame."""
    ww = Model(wakeword_models=[model_name], inference_framework="onnx")
    async for frame_bytes in audio.mic_stream(CHUNK_SAMPLES):
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        scores = ww.predict(samples)
        if scores.get(model_name, 0.0) >= threshold:
            return
