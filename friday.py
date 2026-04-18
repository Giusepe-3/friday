"""FRIDAY entrypoint — Phase 5: alarms online."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src import audio
from src import config as cfg_mod
from src import personality
from src.brain import Brain
from src.scheduler import AlarmScheduler
from src.session import Session, State, is_close_phrase
from src.stt import STT
from src.tts import TTS
from src.vad import VAD
from src.wake import listen_for_wake
from src.tools import state as tool_state


def _init_spotify(cfg):
    if not (cfg.spotify_client_id and cfg.spotify_client_secret):
        return None
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=cfg.spotify_client_id,
            client_secret=cfg.spotify_client_secret,
            redirect_uri=cfg.spotify_redirect_uri,
            scope="user-modify-playback-state user-read-playback-state",
            cache_path=str((cfg.paths.home / ".spotipy_cache")),
            open_browser=True,
        )
    )


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


async def session_loop(cfg, brain, stt, vad, tts, session: Session) -> None:
    while session.state is State.ACTIVE:
        pcm = await record_until_silence(vad, cfg.max_recording_s)
        transcript = await stt.transcribe(pcm, cfg.sample_rate)
        if not transcript.strip():
            continue
        if is_close_phrase(transcript, cfg.close_phrases):
            tts.speak("Done, boss.")
            session.state = State.IDLE
            return
        session.turns.append({"user": transcript})
        sys_prompt = personality.build(
            today=datetime.now().date().isoformat(),
            memory="",
            facts="",
        )
        session.state = State.SPEAKING
        reply, new_sid = await brain.ask(
            transcript, sys_prompt, session.sdk_session_id
        )
        session.sdk_session_id = new_sid
        session.turns.append({"friday": reply})
        if reply:
            tts.speak(reply)
        session.state = State.ACTIVE


async def main() -> None:
    cfg = cfg_mod.load()
    tts = TTS(cfg.piper_exe, cfg.piper_voice)
    brain = Brain(model=cfg.claude_model)
    stt = STT(cfg.groq_api_key)
    vad = VAD()
    sp = _init_spotify(cfg)

    scheduler = AlarmScheduler(cfg.paths.alarms_json, speak=tts.speak)
    await scheduler.start()

    tool_state.init(
        cfg=cfg,
        speak=tts.speak,
        spotify=sp,
        scheduler=scheduler,
    )

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass

    print("[friday] ready, listening for wake word")
    try:
        while not stop.is_set():
            await listen_for_wake(cfg.wake_model, cfg.wake_threshold)
            tts.speak("Yes, boss.")
            session = Session(state=State.ACTIVE)
            try:
                await asyncio.wait_for(
                    session_loop(cfg, brain, stt, vad, tts, session),
                    timeout=cfg.silence_timeout_s,
                )
            except asyncio.TimeoutError:
                tts.speak("Closing out, boss.")
                session.state = State.IDLE
    finally:
        scheduler.sched.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
