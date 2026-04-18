"""Speech-to-text: Groq Whisper Large v3 (primary), faster-whisper tiny (fallback).

The caller provides raw int16 mono PCM bytes at ``sample_rate`` Hz. We wrap
the PCM in an in-memory WAV before uploading to Groq. On any exception we
fall back to the local model, lazily loaded on first use."""

from __future__ import annotations

import io
import wave

import httpx
import numpy as np

_local_model = None  # lazy-loaded faster_whisper.WhisperModel


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class STT:
    def __init__(self, groq_api_key: str) -> None:
        self.groq_api_key = groq_api_key

    async def transcribe(self, pcm: bytes, sample_rate: int = 16000) -> str:
        try:
            return await self._groq(pcm, sample_rate)
        except Exception as e:
            print(f"[stt] groq failed: {e}; using local faster-whisper")
            return self._local(pcm, sample_rate)

    async def _groq(self, pcm: bytes, sample_rate: int) -> str:
        wav_bytes = _pcm_to_wav(pcm, sample_rate)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.groq_api_key}"},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": "whisper-large-v3", "language": "en"},
            )
            resp.raise_for_status()
            return resp.json().get("text", "").strip()

    def _local(self, pcm: bytes, sample_rate: int) -> str:
        global _local_model
        if _local_model is None:
            from faster_whisper import WhisperModel
            _local_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = _local_model.transcribe(arr, language="en")
        return " ".join(s.text for s in segments).strip()
