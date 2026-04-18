"""FRIDAY voice shim for Claude Code.

Lean replacement for friday.py:
- Wake word + VAD + STT + TTS reuses the existing src/* pipeline
- Brain is a persistent `ClaudeSDKClient` per FRIDAY-session. The SDK speaks
  stream-json over stdin/stdout to one long-lived Claude Code CLI subprocess
  for the whole session — follow-up turns skip subprocess + MCP cold-start.
- Personality + memory + tools come from CLAUDE.md + .mcp.json (auto-loaded
  by Claude Code when ``cwd`` is the repo root).

Keeps `friday.py` untouched so you can compare runtimes side-by-side."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
)

from src import audio
from src import config as cfg_mod
from src.brain import _yield_sentences
from src.session import State, is_close_phrase
from src.stt import STT
from src.tts import TTS, speak_streaming
from src.vad import VAD
from src.wake import listen_for_wake


REPO_ROOT = Path(__file__).resolve().parent


_HALLUCINATION_SHORT = {
    "thank you", "thank you.", "thanks", "thanks.", "bye", "bye.",
    "you", "you.", "thanks for watching", "thanks for watching.",
    "okay", "okay.", "ok", "ok.", ".", "",
}


def _looks_like_hallucination(t: str) -> bool:
    norm = t.strip().lower()
    if norm in _HALLUCINATION_SHORT:
        return True
    words = [w for w in norm.replace(".", "").split() if w]
    if len(words) <= 2 and norm.rstrip(".") in {"thank you", "bye", "thanks", "you"}:
        return True
    return False


async def record_until_silence(vad: VAD, max_s: int, min_speech_frames: int = 10) -> bytes:
    """Capture PCM bounded by VAD end-of-speech.

    Returns b"" if (a) VAD never detected speech, or (b) total speech frames
    are fewer than ``min_speech_frames`` (default 10 frames ≈ 300 ms —
    filters tiny blips that Whisper hallucinates on like 'Bye.' / 'Thank you.').
    Suppresses downstream STT calls that would waste ~1s on nothing."""
    buf = bytearray()
    speech_seen = False
    speech_frames = 0
    silent = 0
    max_frames = (max_s * 1000) // vad.frame_ms
    frames = 0
    async for frame in audio.mic_stream(vad.frame_samples):
        buf.extend(frame)
        frames += 1
        if vad.is_speech(frame):
            speech_seen = True
            speech_frames += 1
            silent = 0
        elif speech_seen:
            silent += 1
            if silent >= vad.silence_frames_needed:
                break
        if frames >= max_frames:
            break
    if not speech_seen or speech_frames < min_speech_frames:
        return b""
    return bytes(buf)


class ShimBrain:
    """Persistent ClaudeSDKClient per FRIDAY-session.

    Options leave ``mcp_servers`` and ``system_prompt`` unset so Claude Code
    auto-loads ``.mcp.json`` + ``CLAUDE.md`` from ``cwd``. ``setting_sources``
    defaults to ``['user', 'project']`` inside the SDK."""

    def __init__(self, cwd: Path, model: str = "haiku") -> None:
        self._cwd = str(cwd)
        self._model = model
        self._client: ClaudeSDKClient | None = None

    async def start(self) -> None:
        await self.stop()
        options = ClaudeAgentOptions(
            model=self._model,
            cwd=self._cwd,
            permission_mode="bypassPermissions",
            include_partial_messages=True,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()

    async def ask(self, user_text: str) -> str:
        if self._client is None:
            raise RuntimeError("ShimBrain.ask called before start()")
        await self._client.query(user_text)
        final = ""
        async for msg in self._client.receive_response():
            if isinstance(msg, ResultMessage):
                final = getattr(msg, "result", "") or final
        return final

    async def ask_streaming(self, user_text: str):
        """Yield sentence chunks as Claude generates them."""
        if self._client is None:
            raise RuntimeError("ShimBrain.ask_streaming called before start()")
        await self._client.query(user_text)
        buffer = ""
        async for msg in self._client.receive_response():
            if isinstance(msg, StreamEvent):
                evt = msg.event or {}
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta", {}) or {}
                    if delta.get("type") == "text_delta":
                        buffer += delta.get("text", "")
                        sentences, buffer = _yield_sentences(buffer)
                        for s in sentences:
                            yield s
            elif isinstance(msg, ResultMessage):
                pass
        tail = buffer.strip()
        if tail:
            yield tail

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None


async def main() -> None:
    cfg = cfg_mod.load()
    tts = TTS(
        voice_reference=cfg.voice_reference,
        voice_speaker=cfg.voice_speaker,
        language=cfg.voice_language,
        playback_gain=cfg.playback_gain,
    )
    stt = STT(cfg.groq_api_key)
    vad = VAD()
    brain = ShimBrain(cwd=REPO_ROOT, model=cfg.shim_model)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass

    print(f"[shim] ready — persistent ClaudeSDKClient, model={cfg.shim_model}, CLAUDE.md+.mcp.json auto-loaded from cwd", flush=True)

    while not stop.is_set():
        print(f"[shim] awaiting wake word '{cfg.wake_model}'", flush=True)
        await listen_for_wake(cfg.wake_model, cfg.wake_threshold)
        print("[shim] wake fired", flush=True)
        tts.speak("Yes, boss.")

        print("[shim] starting persistent brain session…", flush=True)
        await brain.start()
        print("[shim] brain ready", flush=True)
        session_start = datetime.now()

        try:
            while True:
                # safety timeout per session
                if (datetime.now() - session_start).total_seconds() > cfg.silence_timeout_s:
                    tts.speak("Closing out, boss.")
                    break

                print("[shim] listening (VAD-bounded)…", flush=True)
                pcm = await record_until_silence(vad, cfg.max_recording_s)
                if not pcm:
                    print("[shim] no speech, skipping", flush=True)
                    continue

                transcript = await stt.transcribe(pcm, cfg.sample_rate)
                print(f"[shim] transcript: {transcript!r}", flush=True)
                if not transcript.strip():
                    continue
                if _looks_like_hallucination(transcript):
                    print("[shim] filtered hallucination", flush=True)
                    continue
                if is_close_phrase(transcript, cfg.close_phrases):
                    tts.speak("Done, boss.")
                    break

                t0 = datetime.now()
                reply = await speak_streaming(tts, brain.ask_streaming(transcript))
                dt = (datetime.now() - t0).total_seconds()
                print(f"[shim] full reply ({dt:.1f}s): {reply}", flush=True)
        finally:
            await brain.stop()


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[shim] interrupted", flush=True)
    except Exception as e:
        print(f"[shim] FATAL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
