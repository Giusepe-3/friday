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
import json
import signal
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    query,
)

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src import audio
from src import config as cfg_mod
from src.brain import _yield_sentences
from src.memory import Memory
from src.scheduler import AlarmScheduler
from src.session import State, is_close_phrase
from src.stt import STT
from src.tools import ALLOWED_TOOL_NAMES, build_server
from src.tools import state as tool_state
from src.orchestrator.manager import WorkerManager
from src.tts import TTS, speak_streaming
from src.vad import VAD
from src.wake import listen_for_wake

try:
    from src.research.storage import ResearchStorage
except Exception as _e:
    print(f"[shim] research.storage unavailable: {_e}")
    ResearchStorage = None


REPO_ROOT = Path(__file__).resolve().parent


_HALLUCINATION_SHORT = {
    "thank you", "thank you.", "thanks", "thanks.", "bye", "bye.",
    "you", "you.", "thanks for watching", "thanks for watching.",
    "okay", "okay.", "ok", "ok.", ".", "",
}


SUMMARY_PROMPT = (
    "Summarise the following conversation in 3-5 bullet points. "
    "Cover: decisions made, facts learned, requests left pending. "
    "Be terse. No preamble, just bullets."
)


class _CloseSession(Exception):
    """Raised by the conversation loop when the close phrase fires."""


def _append_turn_log(home: Path, role: str, text: str) -> None:
    """Append one turn as JSONL under ~/friday/logs/YYYY-MM-DD.jsonl."""
    logs_dir = home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"{datetime.now().date().isoformat()}.jsonl"
    line = json.dumps(
        {"ts": datetime.now().isoformat(timespec="seconds"), "role": role, "text": text},
        ensure_ascii=False,
    )
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[shim] turn-log write failed: {e}", flush=True)


async def _summarise_to_recent(turns: list[dict], memory_dir: Path, model: str) -> None:
    """One-shot summary via fresh SDK query; append to memory_dir/recent.md.

    Skips trivial cycles (<2 turns). Uses ``setting_sources=[]`` so the
    summary call gets no CLAUDE.md persona / MCP tools — clean bullet output."""
    if len(turns) < 2:
        return
    lines: list[str] = []
    for t in turns:
        if "user" in t:
            lines.append(f"User: {t['user']}")
        elif "friday" in t:
            lines.append(f"FRIDAY: {t['friday']}")
    transcript = "\n".join(lines)
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=SUMMARY_PROMPT,
        permission_mode="bypassPermissions",
        setting_sources=[],
    )
    summary = ""
    try:
        async for msg in query(prompt=transcript, options=options):
            if isinstance(msg, ResultMessage):
                summary = getattr(msg, "result", "") or summary
    except Exception as e:
        print(f"[shim] summary failed: {e}", flush=True)
        return
    summary = summary.strip()
    if not summary:
        return
    recent = memory_dir / "recent.md"
    recent.parent.mkdir(parents=True, exist_ok=True)
    header = f"\n## {datetime.now().isoformat(timespec='minutes')}\n\n"
    try:
        with recent.open("a", encoding="utf-8") as f:
            f.write(header + summary + "\n")
        print(f"[shim] summary appended to {recent}", flush=True)
    except Exception as e:
        print(f"[shim] recent.md write failed: {e}", flush=True)


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
        self._server = build_server()

    async def start(self, effort: str = "high") -> None:
        await self.stop()
        options = ClaudeAgentOptions(
            model=self._model,
            cwd=self._cwd,
            permission_mode="bypassPermissions",
            include_partial_messages=True,
            setting_sources=["user", "project"],
            mcp_servers={"friday": self._server},
            allowed_tools=ALLOWED_TOOL_NAMES,
            effort=effort,
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


def _init_spotify(cfg):
    """Construct a Spotipy client from cached OAuth token.

    Never triggers interactive browser flow inside the shim — run
    ``scripts/bootstrap_spotify.py`` once to cache the token."""
    if not (cfg.spotify_client_id and cfg.spotify_client_secret):
        return None
    cache_path = cfg.paths.home / ".spotipy_cache"
    if not cache_path.exists():
        print("[shim] spotify cache missing — run scripts/bootstrap_spotify.py once")
        return None
    auth = SpotifyOAuth(
        client_id=cfg.spotify_client_id,
        client_secret=cfg.spotify_client_secret,
        redirect_uri=cfg.spotify_redirect_uri,
        scope="user-modify-playback-state user-read-playback-state",
        cache_path=str(cache_path),
        open_browser=False,
    )
    if auth.get_cached_token() is None:
        print("[shim] spotify token cache unreadable — re-run bootstrap_spotify.py")
        return None
    return spotipy.Spotify(auth_manager=auth)


async def main() -> None:
    cfg = cfg_mod.load()
    tts = TTS(
        voice_reference=cfg.voice_reference,
        voice_speaker=cfg.voice_speaker,
        language=cfg.voice_language,
        playback_gain=cfg.playback_gain,
        playback_speed=cfg.playback_speed,
    )
    stt = STT(cfg.groq_api_key)
    vad = VAD()
    brain = ShimBrain(cwd=REPO_ROOT, model=cfg.shim_model)

    sp = _init_spotify(cfg)
    memory = Memory(cfg.paths.memory_dir, cfg.paths.facts)
    research = None
    if ResearchStorage is not None:
        try:
            research = ResearchStorage(cfg.paths.home / "research")
        except Exception as e:
            print(f"[shim] research init failed: {e}")
    scheduler = AlarmScheduler(cfg.paths.alarms_json, speak=tts.speak)
    await scheduler.start()
    # Build worker manager from cfg.workers (convert WorkerConfig → dict shape
    # the Phase 3 WorkerManager expects: {"repo": Path, "default_model": str,
    # "default_effort": str, "bash_regex": list[str]})
    workers_cfg_for_mgr = {
        project: {
            "repo": w.repo,
            "default_model": w.default_model,
            "default_effort": w.default_effort,
            "bash_regex": w.bash_regex,
        }
        for project, w in cfg.workers.items()
    }
    worker_manager = WorkerManager(workers_cfg_for_mgr)

    tool_state.init(
        cfg=cfg,
        speak=tts.speak,
        spotify=sp,
        scheduler=scheduler,
        memory=memory,
        research=research,
        worker_manager=worker_manager,
    )
    print(f"[shim] tool_state wired — spotify={'on' if sp else 'off'}, research={'on' if research else 'off'}, alarms=on, workers={len(cfg.workers)}", flush=True)

    # Autostart any worker with autostart=True
    for project, w in cfg.workers.items():
        if w.autostart:
            worker_manager.spawn(project)
            print(f"[shim] autostarted worker: {project}", flush=True)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    try:
        loop.add_signal_handler(signal.SIGINT, stop.set)
        loop.add_signal_handler(signal.SIGTERM, stop.set)
    except NotImplementedError:
        pass

    print(f"[shim] ready — persistent ClaudeSDKClient, model={cfg.shim_model}, CLAUDE.md+.mcp.json auto-loaded from cwd", flush=True)

    print("[shim] starting persistent brain session…", flush=True)
    await brain.start(effort=cfg.friday_effort)
    print("[shim] brain ready — persists across wake cycles, fresh on process restart", flush=True)

    try:
        while not stop.is_set():
            print(f"[shim] awaiting wake word '{cfg.wake_model}'", flush=True)
            await listen_for_wake(cfg.wake_model, cfg.wake_threshold)
            print(f"[shim] wake fired — {cfg.silence_timeout_s}s idle timeout, close with 'terminate jarvis'", flush=True)
            tts.speak("Online, boss.")

            turns: list[dict] = []
            closed = False
            try:
                await _conversation_loop(brain, stt, vad, tts, cfg, turns, cfg.paths.home)
            except _CloseSession:
                closed = True

            await _summarise_to_recent(turns, cfg.paths.home / "memory", cfg.shim_model)

            if closed:
                break
    finally:
        await brain.stop()
        worker_manager.kill_all()
        print("[shim] all workers terminated", flush=True)


async def _conversation_loop(brain, stt, vad, tts, cfg, turns: list[dict], home: Path) -> None:
    """Inner loop: VAD-bounded record → STT → brain → TTS, until idle timeout.

    Returns normally on idle timeout (silent re-arm to outer wake loop).
    Raises ``_CloseSession`` on close-phrase to exit the whole process."""
    last_activity = datetime.now()
    while True:
        idle_s = (datetime.now() - last_activity).total_seconds()
        if idle_s > cfg.silence_timeout_s:
            print(f"[shim] idle {idle_s:.0f}s > {cfg.silence_timeout_s}s, re-arming wake", flush=True)
            return
        print("[shim] listening (VAD-bounded)…", flush=True)
        pcm = await record_until_silence(vad, cfg.max_recording_s)
        if not pcm:
            continue
        transcript = await stt.transcribe(pcm, cfg.sample_rate)
        print(f"[shim] transcript: {transcript!r}", flush=True)
        if not transcript.strip():
            continue
        if _looks_like_hallucination(transcript):
            print("[shim] filtered hallucination", flush=True)
            continue
        _append_turn_log(home, "user", transcript)
        turns.append({"user": transcript})
        if is_close_phrase(transcript, cfg.close_phrases):
            tts.speak("Terminating, boss.")
            raise _CloseSession()
        last_activity = datetime.now()
        t0 = datetime.now()
        reply = await speak_streaming(tts, brain.ask_streaming(transcript))
        dt = (datetime.now() - t0).total_seconds()
        print(f"[shim] full reply ({dt:.1f}s): {reply}", flush=True)
        _append_turn_log(home, "friday", reply)
        turns.append({"friday": reply})
        last_activity = datetime.now()


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[shim] interrupted", flush=True)
    except Exception as e:
        print(f"[shim] FATAL: {type(e).__name__}: {e}", flush=True)
        traceback.print_exc()
