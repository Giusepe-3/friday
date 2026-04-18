"""FRIDAY entrypoint — Phase 3 single-turn loop.

Flow: wait for wake word → record until silence → STT → brain → TTS → loop.
One turn per wake. Phase 3.5 will replace this with an active-session loop."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime

from src import audio
from src import config as cfg_mod
from src import personality
from src.brain import Brain
from src.stt import STT
from src.tts import TTS
from src.vad import VAD
from src.wake import listen_for_wake
from src.tools import state as tool_state


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
    return bytes(buf)


async def main() -> None:
    cfg = cfg_mod.load()
    tts = TTS(cfg.piper_exe, cfg.piper_voice)
    brain = Brain(model=cfg.claude_model)
    stt = STT(cfg.groq_api_key)
    vad = VAD()
    tool_state.init(cfg=cfg, speak=tts.speak)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass

    print("[friday] ready, listening for wake word")
    while not stop.is_set():
        await listen_for_wake(cfg.wake_model, cfg.wake_threshold)
        tts.speak("Yes, boss.")
        pcm = await record_until_silence(vad, cfg.max_recording_s)
        transcript = await stt.transcribe(pcm, cfg.sample_rate)
        if not transcript.strip():
            continue
        sys_prompt = personality.build(
            today=datetime.now().date().isoformat(),
            memory="",
            facts="",
        )
        reply, _ = await brain.ask(transcript, sys_prompt, None)
        if reply:
            tts.speak(reply)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
