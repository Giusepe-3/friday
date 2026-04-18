"""FRIDAY voice shim for Claude Code CLI.

Lean replacement for friday.py:
- Wake word + VAD + STT + TTS reuses the existing src/* pipeline
- Brain is `claude -p <text> --session-id/--resume <uuid>` subprocess
- Personality + memory + tools come from CLAUDE.md + .mcp.json (auto-loaded
  by Claude Code when invoked in this repo's cwd)

Keeps `friday.py` untouched so you can compare runtimes side-by-side."""

from __future__ import annotations

import asyncio
import json
import re
import signal
import uuid
from datetime import datetime

from src import audio
from src import config as cfg_mod
from src.session import State, is_close_phrase
from src.stt import STT
from src.tts import TTS
from src.vad import VAD
from src.wake import listen_for_wake


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


async def record_until_silence(vad: VAD, max_s: int) -> bytes:
    buf = bytearray()
    speech_seen = False
    silent = 0
    max_frames = (max_s * 1000) // vad.frame_ms
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
    return bytes(buf) if speech_seen else b""


async def _claude_ask(
    prompt: str,
    session_id: str,
    first_turn: bool,
    timeout_s: int = 90,
) -> str:
    """Call `claude -p` and return the response text.

    Uses --session-id on first turn to create the session; --resume on
    subsequent turns to continue it. Prints debug to stderr."""
    if first_turn:
        args = ["claude", "-p", prompt,
                "--session-id", session_id,
                "--output-format", "json",
                "--permission-mode", "bypassPermissions"]
    else:
        args = ["claude", "-p", prompt,
                "--resume", session_id,
                "--output-format", "json",
                "--permission-mode", "bypassPermissions"]

    print(f"[shim] claude -p (session={session_id[:8]}, first={first_turn})", flush=True)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        return "Brain timed out, boss."

    if proc.returncode != 0:
        err_tail = (stderr or b"")[-400:].decode("utf-8", errors="replace")
        print(f"[shim] claude exit {proc.returncode}: {err_tail}", flush=True)
        return "Brain's offline. Try again."

    raw = stdout.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: take raw text as reply
        return raw.strip()

    for key in ("result", "response", "content", "text"):
        if isinstance(payload.get(key), str):
            return payload[key].strip()
    return str(payload)


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

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass

    print("[shim] ready — claude CLI backend, CLAUDE.md persona, .mcp.json tools", flush=True)

    while not stop.is_set():
        print(f"[shim] awaiting wake word '{cfg.wake_model}'", flush=True)
        await listen_for_wake(cfg.wake_model, cfg.wake_threshold)
        print("[shim] wake fired", flush=True)
        tts.speak("Yes, boss.")

        session_id = str(uuid.uuid4())
        first_turn = True
        session_start = datetime.now()

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

            reply = await _claude_ask(transcript, session_id, first_turn)
            first_turn = False
            print(f"[shim] reply: {reply[:80]!r}…", flush=True)
            if reply:
                tts.speak(reply)


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[shim] interrupted", flush=True)
    except Exception as e:
        print(f"[shim] FATAL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
