"""FRIDAY entrypoint — Phase 9+: research tools + scheduled standups + catchup."""

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
from src.memory import Memory
from src.scheduler import AlarmScheduler
from src.session import Session, State, is_close_phrase
from src.stt import STT
from src.tts import TTS
from src.vad import VAD
from src.wake import listen_for_wake
from src.tools import state as tool_state

try:
    from src.research.storage import ResearchStorage
except Exception as _e:
    print(f"[friday] research.storage unavailable: {_e}")
    ResearchStorage = None

try:
    from src.research.scheduler import (
        default_jobs_from_config,
        register_jobs,
        catchup_due,
    )
except Exception as _e:
    print(f"[friday] research.scheduler unavailable: {_e}")
    default_jobs_from_config = None
    register_jobs = None
    catchup_due = None


SUMMARY_PROMPT = (
    "Summarise the following conversation in 3-5 bullet points. "
    "Cover: decisions made, facts learned, requests left pending. "
    "Be terse. No preamble, just bullets."
)


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


def _init_research(cfg):
    if ResearchStorage is None:
        return None
    try:
        return ResearchStorage(cfg.paths.home / "research")
    except Exception as e:
        print(f"[friday] research storage init failed: {e}")
        return None


async def record_until_silence(vad: VAD, max_s: int) -> bytes:
    """Return captured PCM, or b'' if VAD never detected real speech.

    Empty return suppresses downstream STT calls that would otherwise
    hallucinate ("Thank you." / "Bye." / etc.) on silent buffers."""
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


def _build_session_prompt(memory: Memory, research) -> str:
    research_state = research.state_summary() if research is not None else ""
    return personality.build(
        today=datetime.now().date().isoformat(),
        memory=memory.last_7_days(),
        facts=memory.read_facts(),
        research_state=research_state,
    )


_HALLUCINATION_SHORT = {
    "thank you", "thank you.", "thanks", "thanks.", "bye", "bye.",
    "you", "you.", "thanks for watching", "thanks for watching.",
    "okay", "okay.", "ok", "ok.", ".", "",
}


def _looks_like_hallucination(t: str) -> bool:
    norm = t.strip().lower()
    if norm in _HALLUCINATION_SHORT:
        return True
    # 1-2 word utterances that are common boilerplate
    words = [w for w in norm.replace(".", "").split() if w]
    if len(words) <= 2 and norm.rstrip(".") in {"thank you", "bye", "thanks", "you"}:
        return True
    return False


async def session_loop(cfg, brain, stt, vad, tts, memory, research, session: Session) -> None:
    while session.state is State.ACTIVE:
        print("[session] listening (VAD-bounded)…", flush=True)
        pcm = await record_until_silence(vad, cfg.max_recording_s)
        if not pcm:
            print("[session] no speech detected, skipping", flush=True)
            continue
        print(f"[session] got {len(pcm)} bytes of pcm, transcribing…", flush=True)
        transcript = await stt.transcribe(pcm, cfg.sample_rate)
        print(f"[session] transcript: {transcript!r}", flush=True)
        if not transcript.strip():
            print("[session] empty transcript, continuing", flush=True)
            continue
        if _looks_like_hallucination(transcript):
            print("[session] filtered hallucination, continuing", flush=True)
            continue
        if is_close_phrase(transcript, cfg.close_phrases):
            print("[session] close phrase detected", flush=True)
            tts.speak("Done, boss.")
            session.state = State.IDLE
            return
        session.turns.append({"user": transcript})
        session.state = State.SPEAKING
        print("[session] brain.ask…", flush=True)
        reply = await brain.ask(transcript)
        print(f"[session] brain reply: {reply[:80]!r}...", flush=True)
        session.turns.append({"friday": reply})
        if reply:
            tts.speak(reply)
        session.state = State.ACTIVE


async def summarise_session(brain: Brain, memory: Memory, session: Session) -> None:
    if not session.turns:
        return
    transcript_lines = []
    for turn in session.turns:
        if "user" in turn:
            transcript_lines.append(f"User: {turn['user']}")
        elif "friday" in turn:
            transcript_lines.append(f"FRIDAY: {turn['friday']}")
    transcript = "\n".join(transcript_lines)
    try:
        summary = await brain.ask_oneshot(transcript, SUMMARY_PROMPT)
    except Exception as e:
        print(f"[memory] summary failed: {e}")
        return
    if summary:
        memory.append_summary(summary)


async def main() -> None:
    cfg = cfg_mod.load()
    tts = TTS(
        voice_reference=cfg.voice_reference,
        voice_speaker=cfg.voice_speaker,
        language=cfg.voice_language,
        playback_gain=cfg.playback_gain,
    )
    brain = Brain(model=cfg.claude_model)
    stt = STT(cfg.groq_api_key)
    vad = VAD()
    sp = _init_spotify(cfg)
    memory = Memory(cfg.paths.memory_dir, cfg.paths.facts)
    research = _init_research(cfg)

    scheduler = AlarmScheduler(cfg.paths.alarms_json, speak=tts.speak)
    await scheduler.start()

    # Research schedules (no-op if research or its scheduler module unavailable).
    if research is not None and default_jobs_from_config is not None:
        jobs = default_jobs_from_config(cfg)
        register_jobs(scheduler.sched, jobs, research)
        for job in catchup_due(research, jobs, window_h=cfg.research_catchup_window_h):
            research.enqueue_pending_prompt(job.prompt, reason=f"catchup:{job.name}")
            research.record_job_fired(job.name, datetime.now(), "catchup_queued")
            print(f"[friday] catchup queued: {job.name}")

    tool_state.init(
        cfg=cfg,
        speak=tts.speak,
        spotify=sp,
        scheduler=scheduler,
        memory=memory,
        research=research,
    )

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass

    print(f"[friday] ready (research={'on' if research else 'off'}), listening for wake word")
    try:
        while not stop.is_set():
            pending = research.pop_pending_prompt() if research is not None else None
            if pending is None:
                print(f"[friday] awaiting wake word '{cfg.wake_model}' (threshold {cfg.wake_threshold})", flush=True)
                await listen_for_wake(cfg.wake_model, cfg.wake_threshold)
                print("[friday] wake fired — entering session", flush=True)
                tts.speak("Yes, boss.")
            else:
                print(f"[friday] draining pending prompt: {pending['reason']}", flush=True)
                tts.speak(pending["prompt"])

            sys_prompt = _build_session_prompt(memory, research)
            await brain.start_session(sys_prompt)
            session = Session(state=State.ACTIVE)

            try:
                if pending is not None:
                    session.turns.append({"user": pending["prompt"]})
                    reply = await brain.ask(pending["prompt"])
                    session.turns.append({"friday": reply})
                    if reply:
                        tts.speak(reply)

                try:
                    await asyncio.wait_for(
                        session_loop(cfg, brain, stt, vad, tts, memory, research, session),
                        timeout=cfg.silence_timeout_s,
                    )
                except asyncio.TimeoutError:
                    tts.speak("Closing out, boss.")
                    session.state = State.IDLE
            finally:
                await brain.end_session()

            await summarise_session(brain, memory, session)
    finally:
        scheduler.sched.shutdown(wait=False)


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[friday] interrupted by user", flush=True)
    except Exception as e:
        print(f"[friday] FATAL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
