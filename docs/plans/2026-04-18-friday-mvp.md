# FRIDAY MVP (Windows Beta) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working Windows-laptop beta of FRIDAY voice assistant — wake word, STT, Claude brain with tool use, TTS, Spotify + notes + briefing + alarms + memory — end-to-end in one guided plan.

**Architecture:** Single asyncio Python 3.11 process. OpenWakeWord wake → webrtcvad end-of-speech → Groq Whisper → Claude Sonnet 4.6 via Claude Agent SDK (Max subscription auth, custom MCP tools) → Piper TTS → sounddevice. Flat-file persistence under `~/friday/`.

**Tech Stack:** Python 3.11, claude-agent-sdk, openwakeword, sounddevice, webrtcvad, httpx, faster-whisper, piper, spotipy, apscheduler, pytest.

**Wake-engine deviation:** Picovoice Porcupine required a company-email signup that blocked setup. Swapped to OpenWakeWord (MIT, no account) with the pre-trained `hey_jarvis` model. Wake phrase is now **"Hey Jarvis"** — FRIDAY personality stays in the brain. Training a custom "Friday" model is possible later but requires hours of synthetic-data generation; deferred.

---

## Preamble — context for executor

You are implementing a personal voice assistant named FRIDAY on a **Windows 11 laptop** as a beta before a future Raspberry Pi 5 deployment. Read this section before starting any task.

- **Windows-only beta.** Pi deployment (Phase 1) and systemd polish (Phase 7) from the design spec are **deferred** to a separate plan. Do not attempt them here. Field test (Phase 8) is also deferred.
- **Auth via Claude Max, not the Anthropic API.** The user has a Claude Max subscription and logs in via `claude login` at the CLI. The `claude-agent-sdk` Python package inherits that session through the Claude Code CLI. Do **not** rewrite brain code to use the raw `anthropic` SDK.
- **Review checkpoints between phases are mandatory.** The user manually tests at each checkpoint before the next phase starts. Do not chain phases into one auto-run. When a REVIEW CHECKPOINT section appears, stop and wait for explicit approval.
- **Commit after every task.** Each task ends with a `git commit` step. Messages use conventional-commit style (`feat:`, `chore:`, `test:`, `fix:`).
- **Deviation noted up front:** spec §7 says `set_volume` controls system volume via alsamixer. Alsamixer is Linux-only, and we're on Windows for the beta. This plan implements `set_volume` as Spotify client volume via `spotipy.Spotify.volume()` — cross-platform and sufficient for v1. Revisit on Pi if system-wide volume control becomes necessary.
- **Session model confirmed with user:** wake word opens an active session, not a single turn. Follow-ups need no re-wake. Session ends on an explicit close phrase (e.g. "thanks friday") or a 5-minute absolute silence safety timeout. On close, FRIDAY says "Done, boss.", Claude summarises the session, memory is persisted, Porcupine re-arms.
- **Working directory:** `C:\Users\leona\Documents\GitHub\friday` on the user's Windows laptop. Runtime state lives under `~/friday/` (resolved via `pathlib.Path.home()`), which on Windows is `C:\Users\leona\friday`.

---

## Testing philosophy

The user has explicitly asked **not to over-test**. Do not write unit tests for I/O-heavy code. ROI is bad on a personal project when tests would mock audio drivers, wake engines, or cloud APIs.

**Write pytest unit tests for pure logic only:**

- Session close-phrase matcher + state machine (`test_session.py`)
- Personality prompt builder with placeholder substitution (`test_personality.py`)
- Memory file round-trips and 7-day-window loader (`test_memory.py`)
- Alarm scheduler persistence, cancel, reload (`test_scheduler.py`)
- `get_time` util tool (`test_util_tool.py`)
- Notes tool line format (`test_notes_tool.py`)

**Use manual smoke scripts for I/O:**

- `scripts/smoke_piper.py` — TTS
- `scripts/smoke_audio.py` — mic + speaker
- `scripts/smoke_wake.py` — Porcupine wake detection
- `scripts/smoke_stt.py` — Groq STT round-trip

**Do not write:**

- Unit tests that mock `sounddevice`, `pvporcupine`, Groq HTTP, Piper subprocess, or `spotipy`
- Integration tests that spin up the full asyncio loop
- Tests for configuration loading beyond trivial cases

Pure-logic tests must pass before moving on. Smoke scripts are "runs cleanly, sounds right, wake fires" — user judges by ear and eye.

---

## File structure

The full repository layout. Create empty modules up front in Phase 0 only where noted; the rest are created task-by-task.

```
friday/
├─ friday.py                  # main asyncio entrypoint
├─ src/
│  ├─ __init__.py
│  ├─ config.py               # yaml + .env loader, singleton cache
│  ├─ audio.py                # sounddevice mic stream + WAV play
│  ├─ wake.py                 # Porcupine loop
│  ├─ vad.py                  # webrtcvad wrapper
│  ├─ stt.py                  # Groq httpx + faster-whisper fallback
│  ├─ tts.py                  # Piper subprocess + play_wav
│  ├─ brain.py                # Agent SDK query wrapper
│  ├─ personality.py          # system prompt template + builder
│  ├─ memory.py               # facts.md, daily summaries, 7-day loader
│  ├─ scheduler.py            # AlarmScheduler (APScheduler + json)
│  ├─ session.py              # State enum, Session dataclass, is_close_phrase
│  └─ tools/
│     ├─ __init__.py          # build_server, ALLOWED_TOOL_NAMES
│     ├─ state.py             # ToolState singleton for tool handlers
│     ├─ util_tool.py         # get_time
│     ├─ notes_tool.py        # write_note
│     ├─ briefing_tool.py     # read_briefing
│     ├─ spotify_tool.py      # play/pause/resume/skip/volume
│     ├─ alarm_tool.py        # set/cancel/list
│     └─ memory_tool.py       # remember_fact
├─ config/
│  ├─ friday.yaml
│  └─ .env.example
├─ voices/                    # piper .onnx + .json; openwakeword models cache in ~/.local/share/openwakeword or lazy-downloaded
├─ piper/                     # piper.exe + dlls (gitignored, Windows-only)
├─ scripts/
│  ├─ smoke_piper.py
│  ├─ smoke_audio.py
│  ├─ smoke_wake.py
│  └─ smoke_stt.py
├─ tests/
│  ├─ __init__.py
│  ├─ conftest.py             # tmp_friday_home fixture
│  ├─ test_personality.py
│  ├─ test_session.py         # close-phrase matcher + state machine
│  ├─ test_memory.py          # facts round-trip, 7-day loader
│  ├─ test_scheduler.py       # persistence + cancel
│  ├─ test_util_tool.py
│  └─ test_notes_tool.py
├─ requirements.txt
├─ pytest.ini
├─ .gitignore
└─ README.md
```

---

## Phase 0: Scaffold + Windows env setup + account prereqs + Piper smoke

Goal: repo layout in place, Python venv with all dependencies, config loader working, Piper speaks one sentence through the laptop speakers, accounts (Picovoice, Groq, Spotify) signed up and keys stored. After this phase, no voice assistant logic yet — just proof the foundation is solid.

### Task 0.1: Create directory skeleton and empty module files

**Files:**
- Create: `src/__init__.py`
- Create: `src/tools/__init__.py` (will hold build_server later — empty for now)
- Create: `tests/__init__.py`
- Create: `voices/.gitkeep`
- Create: `scripts/.gitkeep`

- [ ] **Step 1:** Open a terminal in `C:\Users\leona\Documents\GitHub\friday` (PowerShell or Git Bash; plan commands use Git Bash syntax).

- [ ] **Step 2:** Create directories.

```bash
mkdir -p src/tools tests scripts voices piper config docs/plans
```

- [ ] **Step 3:** Create empty `__init__.py` files and placeholder `.gitkeep` markers.

```bash
touch src/__init__.py src/tools/__init__.py tests/__init__.py
touch voices/.gitkeep scripts/.gitkeep
```

- [ ] **Step 4:** Commit.

```bash
git add src tests scripts voices
git commit -m "chore: scaffold package directories"
```

### Task 0.2: Write `.gitignore`

**Files:**
- Create: `.gitignore`

- [ ] **Step 1:** Write the file.

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.venv/
venv/
*.egg-info/

# Secrets
config/.env

# Binary assets (licensed / large)
voices/*.ppn
voices/*.onnx
voices/*.onnx.json
piper/

# Runtime state (user home, not repo — but belt and braces)
friday_home/

# OS
.DS_Store
Thumbs.db

# Editors
.vscode/
.idea/
```

- [ ] **Step 2:** Commit.

```bash
git add .gitignore
git commit -m "chore: add gitignore"
```

### Task 0.3: Write `requirements.txt` and create venv

**Files:**
- Create: `requirements.txt`

- [ ] **Step 1:** Write the file.

```
claude-agent-sdk>=0.1.60
openwakeword>=0.6.0
sounddevice>=0.4.7
numpy>=1.26
webrtcvad-wheels>=2.0.14
httpx>=0.27
faster-whisper>=1.0
pyyaml>=6.0
python-dotenv>=1.0
spotipy>=2.24
apscheduler>=3.10
dateparser>=1.2
pytest>=8.0
pytest-asyncio>=0.24
```

- [ ] **Step 2:** Create virtualenv and install dependencies.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -r requirements.txt
```

Expected: pip prints a long install log ending in `Successfully installed ...`. No error output. `faster-whisper` pulls CUDA libs on some systems; CPU install is fine.

- [ ] **Step 3:** Verify imports work.

```bash
.venv/Scripts/python -c "import claude_agent_sdk, openwakeword, sounddevice, webrtcvad, httpx, faster_whisper, yaml, dotenv, spotipy, apscheduler, dateparser; print('ok')"
```

Expected: prints `ok` and exits 0.

- [ ] **Step 4:** Commit.

```bash
git add requirements.txt
git commit -m "chore: pin dependencies"
```

### Task 0.4: Write `pytest.ini`

**Files:**
- Create: `pytest.ini`

- [ ] **Step 1:** Write the file.

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 2:** Commit.

```bash
git add pytest.ini
git commit -m "chore: configure pytest asyncio auto mode"
```

### Task 0.5: Write `config/friday.yaml` and `config/.env.example`

**Files:**
- Create: `config/friday.yaml`
- Create: `config/.env.example`

- [ ] **Step 1:** Write `config/friday.yaml`.

```yaml
claude_model: claude-sonnet-4-6
wake_model: hey_jarvis
wake_threshold: 0.5
piper_exe: piper/piper.exe
piper_voice: voices/en_GB-alan-medium.onnx
sample_rate: 16000
silence_timeout_s: 300
max_recording_s: 15
close_phrases:
  - "that's all friday"
  - "thats all friday"
  - "thanks friday"
  - "thank you friday"
  - "fine friday"
  - "goodbye friday"
  - "bye friday"
  - "we're done friday"
  - "were done friday"
```

- [ ] **Step 2:** Write `config/.env.example`.

```
GROQ_API_KEY=
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

- [ ] **Step 3:** Copy example to real `.env` (user fills it in next tasks).

```bash
cp config/.env.example config/.env
```

- [ ] **Step 4:** Commit.

```bash
git add config/friday.yaml config/.env.example
git commit -m "chore: add config template and env example"
```

### Task 0.6: Sign up for accounts and record keys

**Files:**
- Modify: `config/.env` (local only, not committed)

This task is **manual** and requires review by the user. No code to write.

- [ ] **Step 1: Groq (STT).** Go to https://console.groq.com/, sign up. Create an API key at `API Keys`. Paste into `config/.env` as `GROQ_API_KEY=...`.

- [ ] **Step 2: Spotify Developer app.** Go to https://developer.spotify.com/dashboard. Create an app: name `FRIDAY local`, redirect URI `http://127.0.0.1:8080/callback`. Copy Client ID and Secret into `config/.env` as `SPOTIFY_CLIENT_ID=...` and `SPOTIFY_CLIENT_SECRET=...`.

- [ ] **Step 3: Claude Max auth.** In the same terminal, run:

```bash
claude login
```

Follow the browser prompt. After login, the `claude-agent-sdk` will inherit this session.

- [ ] **Step 4: OpenWakeWord model download.** No account needed. OpenWakeWord ships with tflite models by default; on Windows we use the ONNX backend (onnxruntime is already installed as a transitive dep of faster-whisper). Download all default models (alexa, hey_jarvis, hey_mycroft, etc. — we'll use `hey_jarvis`):

```bash
.venv/Scripts/python -c "import openwakeword.utils; openwakeword.utils.download_models()"
.venv/Scripts/python -c "from openwakeword.model import Model; m = Model(wakeword_models=['hey_jarvis'], inference_framework='onnx'); print('ok')"
```

Expected: first command downloads ~10 MB of `.onnx` / `.tflite` files into the package's `resources/models/` directory. Second command prints `ok`.

- [ ] **Step 5:** Verify `.env` is NOT tracked by git.

```bash
git status --ignored config/
```

Expected: `config/.env` appears under "Ignored files" (not "Untracked").

No commit — `.env` is gitignored and the `.ppn` file is too.

### Task 0.7: Download Piper binary and voice model

**Files:**
- Create: `piper/piper.exe` (downloaded)
- Create: `piper/*.dll` (downloaded alongside exe)
- Create: `voices/en_GB-alan-medium.onnx` (downloaded)
- Create: `voices/en_GB-alan-medium.onnx.json` (downloaded)

- [ ] **Step 1:** Download Piper Windows release from https://github.com/rhasspy/piper/releases (latest). Pick `piper_windows_amd64.zip`. Extract contents (piper.exe + required DLLs) into `piper/`.

- [ ] **Step 2:** Download voice from https://github.com/rhasspy/piper/blob/master/VOICES.md. Pick `en_GB-alan-medium`. Two files: `.onnx` and `.onnx.json`. Save both to `voices/`.

- [ ] **Step 3:** Verify Piper runs.

```bash
echo "Hello, boss." | piper/piper.exe --model voices/en_GB-alan-medium.onnx --output_file piper/hello.wav
```

Expected: no errors; `piper/hello.wav` created.

- [ ] **Step 4:** Both `piper/` and `voices/*.onnx*` are gitignored — no commit.

### Task 0.8: Write `src/config.py`

**Files:**
- Create: `src/config.py`

- [ ] **Step 1:** Write the module.

```python
"""Configuration loader for FRIDAY.

Reads ``config/friday.yaml`` and ``config/.env`` once per process, returns a
frozen :class:`Config` dataclass. All paths resolve relative to the repo
root (for asset paths) or ``~/friday/`` (for runtime state)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class Paths:
    home: Path
    notes: Path
    today: Path
    memory_dir: Path
    facts: Path
    alarms_json: Path
    conversation_jsonl: Path
    logs_dir: Path
    log_file: Path


@dataclass(frozen=True)
class Config:
    paths: Paths
    picovoice_access_key: str
    porcupine_keyword_path: Path
    piper_exe: Path
    piper_voice: Path
    groq_api_key: str
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    claude_model: str
    close_phrases: tuple[str, ...]
    silence_timeout_s: int
    max_recording_s: int
    sample_rate: int


_cached: Config | None = None


def load() -> Config:
    global _cached
    if _cached is not None:
        return _cached

    repo = Path(__file__).resolve().parents[1]
    load_dotenv(repo / "config" / ".env")

    yaml_path = repo / "config" / "friday.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    home = Path.home() / "friday"
    paths = Paths(
        home=home,
        notes=home / "notes.md",
        today=home / "today.md",
        memory_dir=home / "memory",
        facts=home / "memory" / "facts.md",
        alarms_json=home / "alarms.json",
        conversation_jsonl=home / "conversation.jsonl",
        logs_dir=home / "logs",
        log_file=home / "logs" / "friday.log",
    )
    for p in (home, paths.memory_dir, paths.logs_dir):
        p.mkdir(parents=True, exist_ok=True)

    _cached = Config(
        paths=paths,
        picovoice_access_key=os.environ.get("PICOVOICE_ACCESS_KEY", ""),
        porcupine_keyword_path=repo / data["porcupine_keyword_path"],
        piper_exe=repo / data["piper_exe"],
        piper_voice=repo / data["piper_voice"],
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        spotify_client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        spotify_redirect_uri=os.environ.get(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback"
        ),
        claude_model=data.get("claude_model", "claude-sonnet-4-6"),
        close_phrases=tuple(data.get("close_phrases", [])),
        silence_timeout_s=int(data.get("silence_timeout_s", 300)),
        max_recording_s=int(data.get("max_recording_s", 15)),
        sample_rate=int(data.get("sample_rate", 16000)),
    )
    return _cached


def reset_cache() -> None:
    """Test hook — forget the cached config so ``load()`` re-reads."""
    global _cached
    _cached = None
```

- [ ] **Step 2:** Sanity-check load.

```bash
.venv/Scripts/python -c "from src import config; c = config.load(); print(c.claude_model, c.paths.home)"
```

Expected: prints `claude-sonnet-4-6 C:\Users\leona\friday` (or similar). Directories created under `~/friday/`.

- [ ] **Step 3:** Commit.

```bash
git add src/config.py
git commit -m "feat(config): yaml + env loader with singleton cache"
```

### Task 0.9: Write `scripts/smoke_piper.py`

**Files:**
- Create: `scripts/smoke_piper.py`

- [ ] **Step 1:** Write the script.

```python
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
```

- [ ] **Step 2:** Run it.

```bash
.venv/Scripts/python scripts/smoke_piper.py
```

Expected: you hear *"Hello, boss. Piper works."* spoken through the default output device.

- [ ] **Step 3:** Commit.

```bash
git add scripts/smoke_piper.py
git commit -m "chore: smoke script for piper tts"
```

---

## REVIEW CHECKPOINT — Phase 0

**Stop. Manually verify before continuing.**

- [ ] `python -c "from src import config; config.load()"` works with no errors.
- [ ] `scripts/smoke_piper.py` plays the line clearly through your laptop speakers.
- [ ] `config/.env` contains real values for `PICOVOICE_ACCESS_KEY`, `GROQ_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`.
- [ ] `voices/friday.ppn` is present (Porcupine custom keyword).
- [ ] `piper/piper.exe` + DLLs are present.
- [ ] `~/friday/`, `~/friday/memory/`, `~/friday/logs/` exist.
- [ ] `git status` is clean (only ignored files untracked).

If any box fails, fix it before Phase 2a. When all pass, approve and continue.

---

## Phase 2a: Audio I/O (sounddevice)

Goal: a reusable async mic-stream helper and a blocking WAV-player helper. Isolated from the rest of the stack so we can smoke-test audio before touching any cloud APIs. (Phase 1 — Pi bootstrap — is deferred; we jump from Phase 0 to Phase 2a.)

### Task 2a.1: Write `src/audio.py`

**Files:**
- Create: `src/audio.py`

- [ ] **Step 1:** Write the module.

```python
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

SAMPLE_RATE = 16000  # Porcupine + Whisper native


async def mic_stream(frame_samples: int) -> AsyncIterator[bytes]:
    """Yield int16 mono PCM frames of length ``frame_samples``.

    Each yielded value is ``frame_samples * 2`` bytes (int16). The generator
    runs forever — callers break out when they have what they need.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _callback(indata, frames, time_info, status):
        # ``indata`` is a CFFI buffer; bytes() copies it so it survives the
        # callback return.
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
```

- [ ] **Step 2:** Commit.

```bash
git add src/audio.py
git commit -m "feat(audio): async mic stream + blocking wav playback"
```

### Task 2a.2: Write `scripts/smoke_audio.py`

**Files:**
- Create: `scripts/smoke_audio.py`

- [ ] **Step 1:** Write the script.

```python
"""Smoke test: record 3s from the default mic, echo it back through speakers."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import audio


FRAME_MS = 30
FRAME_SAMPLES = int(audio.SAMPLE_RATE * FRAME_MS / 1000)
RECORD_S = 3


async def main() -> None:
    print(f"Recording {RECORD_S}s from default mic…")
    buf = bytearray()
    target_frames = RECORD_S * 1000 // FRAME_MS
    async for frame in audio.mic_stream(FRAME_SAMPLES):
        buf.extend(frame)
        if len(buf) >= target_frames * FRAME_SAMPLES * 2:
            break

    print("Playing back…")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.SAMPLE_RATE)
            w.writeframes(bytes(buf))
        audio.play_wav(out)
    finally:
        out.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2:** Run it and speak during the 3-second window.

```bash
.venv/Scripts/python scripts/smoke_audio.py
```

Expected: terminal prints "Recording 3s…", then "Playing back…", and you hear your own voice.

- [ ] **Step 3:** Commit.

```bash
git add scripts/smoke_audio.py
git commit -m "chore: smoke script for mic+speaker echo"
```

---

## REVIEW CHECKPOINT — Phase 2a

**Stop. Manually verify before continuing.**

- [ ] `scripts/smoke_audio.py` records clearly and plays your voice back recognisably.
- [ ] No PortAudio errors in the terminal. If mic input is silent, check Windows sound settings and the default input device.

When pass, approve and continue to Phase 2b.

---

## Phase 2b: Wake word (OpenWakeWord — `hey_jarvis`)

Goal: OpenWakeWord listens on the mic stream and returns when confidence on the chosen model crosses the threshold. We use the pre-trained `hey_jarvis` model — wake phrase is "Hey Jarvis" (FRIDAY personality stays in the brain). No account or license key needed.

**Chunk size:** OpenWakeWord expects 1280-sample int16 chunks at 16 kHz (80 ms). Matches our sample rate.

**Prereq:** Task 0.6 Step 4 (model auto-download).

### Task 2b.1: Write `src/wake.py`

**Files:**
- Create: `src/wake.py`

- [ ] **Step 1:** Write the module.

```python
"""OpenWakeWord wake-word listener.

Returns as soon as the configured model's confidence crosses ``threshold``
on a consecutive frame. Chunk size is 1280 samples (80 ms at 16 kHz),
which is what OpenWakeWord internally expects."""

from __future__ import annotations

import numpy as np
from openwakeword.model import Model

from . import audio

CHUNK_SAMPLES = 1280  # 80 ms at 16 kHz — openwakeword native


async def listen_for_wake(model_name: str, threshold: float = 0.5) -> None:
    """Block until the configured wake model fires above ``threshold``.

    Uses ONNX backend because tflite-runtime has no Windows wheel on PyPI.
    ``onnxruntime`` comes in transitively via ``faster-whisper``."""
    ww = Model(wakeword_models=[model_name], inference_framework="onnx")
    async for frame_bytes in audio.mic_stream(CHUNK_SAMPLES):
        samples = np.frombuffer(frame_bytes, dtype=np.int16)
        scores = ww.predict(samples)
        if scores.get(model_name, 0.0) >= threshold:
            return
```

- [ ] **Step 2:** Commit.

```bash
git add src/wake.py
git commit -m "feat(wake): openwakeword listener"
```

### Task 2b.2: Write `scripts/smoke_wake.py`

**Files:**
- Create: `scripts/smoke_wake.py`

- [ ] **Step 1:** Write the script.

```python
"""Smoke test: wait for wake word, print a line, exit."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config as cfg_mod
from src import wake


async def main() -> None:
    cfg = cfg_mod.load()
    print(f"Listening for wake word '{cfg.wake_model}' (threshold {cfg.wake_threshold})…")
    await wake.listen_for_wake(cfg.wake_model, cfg.wake_threshold)
    print("Wake word detected.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2:** Run it and say "Hey Jarvis" clearly.

```bash
.venv/Scripts/python scripts/smoke_wake.py
```

Expected: prints "Listening for wake word 'hey_jarvis'…", then "Wake word detected." within a second of speaking. Try two or three times to gauge reliability.

- [ ] **Step 3:** Commit.

```bash
git add scripts/smoke_wake.py
git commit -m "chore: smoke script for openwakeword"
```

---

## REVIEW CHECKPOINT — Phase 2b

**Stop. Manually verify before continuing.**

- [ ] `scripts/smoke_wake.py` fires reliably on "Hey Jarvis" from ~1–2 m away.
- [ ] No false fires during normal speech (speak a few sentences without saying the wake word — it should stay silent).
- [ ] If detection is noisy, raise `wake_threshold` in `config/friday.yaml` from 0.5 to 0.6–0.7.
- [ ] If detection is unreliable, lower to 0.3–0.4, or speak closer to the mic.

When pass, approve and continue to Phase 2c.

---

## Phase 2c: VAD + STT (Groq primary, faster-whisper fallback)

Goal: detect end-of-speech with WebRTC VAD, capture the PCM, transcribe via Groq Whisper Large v3. On any exception (network, quota, 5xx), lazy-load `faster-whisper tiny` and run locally. After this phase the stack can answer "you said X".

### Task 2c.1: Write `src/vad.py`

**Files:**
- Create: `src/vad.py`

- [ ] **Step 1:** Write the module.

```python
"""Voice activity detection wrapper around webrtcvad.

Attributes exposed for the main recorder loop:

* ``frame_ms`` — frame duration in milliseconds (must be 10, 20, or 30).
* ``frame_samples`` — samples per frame at ``sample_rate``.
* ``frame_bytes`` — bytes per frame (``frame_samples * 2`` for int16).
* ``silence_frames_needed`` — consecutive non-speech frames that signal EoS.
"""

from __future__ import annotations

import webrtcvad


class VAD:
    def __init__(
        self,
        aggressiveness: int = 2,
        frame_ms: int = 30,
        sample_rate: int = 16000,
        silence_ms: int = 800,
    ) -> None:
        if frame_ms not in (10, 20, 30):
            raise ValueError("webrtcvad only supports 10/20/30 ms frames")
        self._vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self.frame_bytes = self.frame_samples * 2
        self.silence_frames_needed = silence_ms // frame_ms

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, self.sample_rate)
```

- [ ] **Step 2:** Commit.

```bash
git add src/vad.py
git commit -m "feat(vad): webrtcvad wrapper with end-of-speech config"
```

### Task 2c.2: Write `src/stt.py`

**Files:**
- Create: `src/stt.py`

- [ ] **Step 1:** Write the module.

```python
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
        except Exception as e:  # network, 5xx, rate-limit — all fall back
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
            from faster_whisper import WhisperModel  # heavy import, keep lazy
            _local_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = _local_model.transcribe(arr, language="en")
        return " ".join(s.text for s in segments).strip()
```

- [ ] **Step 2:** Commit.

```bash
git add src/stt.py
git commit -m "feat(stt): groq whisper client + faster-whisper fallback"
```

### Task 2c.3: Write `scripts/smoke_stt.py`

**Files:**
- Create: `scripts/smoke_stt.py`

- [ ] **Step 1:** Write the script.

```python
"""Smoke test: VAD-bounded mic capture → Groq STT → print transcript."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import audio, config as cfg_mod, stt as stt_mod, vad as vad_mod


async def main() -> None:
    cfg = cfg_mod.load()
    if not cfg.groq_api_key:
        raise SystemExit("GROQ_API_KEY missing from config/.env")
    vad = vad_mod.VAD()
    stt = stt_mod.STT(cfg.groq_api_key)

    print("Speak when ready. Recording until you go silent…")
    buf = bytearray()
    speech_seen = False
    silent = 0
    max_frames = cfg.max_recording_s * 1000 // vad.frame_ms
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

    print(f"Captured {len(buf)} bytes of PCM, transcribing…")
    text = await stt.transcribe(bytes(buf), cfg.sample_rate)
    print(f"Transcript: {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2:** Run it, say a sentence, pause.

```bash
.venv/Scripts/python scripts/smoke_stt.py
```

Expected: prints "Recording until you go silent…", captures a reasonable PCM blob, prints a transcript that matches what you said.

- [ ] **Step 3:** Commit.

```bash
git add scripts/smoke_stt.py
git commit -m "chore: smoke script for vad-bounded stt"
```

---

## REVIEW CHECKPOINT — Phase 2c

**Stop. Manually verify before continuing.**

- [ ] `scripts/smoke_stt.py` returns an accurate transcript of a short sentence.
- [ ] VAD cuts off within ~1s of you stopping talking — not instantly, not after 15s.
- [ ] If Groq is unavailable (disconnect WiFi as a test), fallback kicks in and still returns text (slower, may be rougher — it's the tiny model).

When pass, approve and continue to Phase 3.

---

## Phase 3: Brain + personality + TTS + util tool (`get_time`)

Goal: end-to-end single-turn voice round trip. Say "Friday, what time is it?" and hear FRIDAY speak the current time. The pieces: TTS (Piper), personality prompt builder, tool state singleton, util tool (get_time), MCP server builder, brain wrapper, basic main loop.

### Task 3.1: Write `src/tts.py`

**Files:**
- Create: `src/tts.py`

- [ ] **Step 1:** Write the module.

```python
"""Text-to-speech via the Piper binary.

Pipes text to ``piper.exe`` which writes a WAV. We then play the WAV through
``audio.play_wav``. Temporary files are cleaned up in ``finally``."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import audio


class TTS:
    def __init__(self, piper_exe: Path, voice: Path) -> None:
        self.piper_exe = piper_exe
        self.voice = voice

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out = Path(tmp.name)
        try:
            subprocess.run(
                [
                    str(self.piper_exe),
                    "--model",
                    str(self.voice),
                    "--output_file",
                    str(out),
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                check=True,
            )
            audio.play_wav(out)
        finally:
            out.unlink(missing_ok=True)
```

- [ ] **Step 2:** Commit.

```bash
git add src/tts.py
git commit -m "feat(tts): piper subprocess wrapper"
```

### Task 3.2: Write `src/personality.py`

**Files:**
- Create: `src/personality.py`

- [ ] **Step 1:** Write the module.

```python
"""FRIDAY personality system prompt.

The prompt text matches the design spec §8 verbatim. Three placeholders are
filled at each session: ``date``, ``memory``, ``facts``. Empty memory or
facts render as a user-visible "(no recent memory)" / "(no standing facts)"
so Claude sees a consistent shape."""

from __future__ import annotations

SYSTEM_PROMPT = """You are FRIDAY, a home voice assistant modelled on the Marvel AI of the same name.

Voice and style:
- Dry, efficient, occasionally sardonic. Never chipper.
- Address the user as "boss" or "sir" sparingly — not every turn.
- British-adjacent phrasing where natural; American English otherwise.
- Brief by default. One or two sentences. Expand only when asked.
- No "I'd be happy to", no "Certainly!", no pleasantries. Acknowledge, act, report.
- If a tool call succeeds, confirm in under 10 words.
- If a tool fails, say what failed in plain language. No jargon unless user is technical.
- Never narrate what you are about to do. Do it, then report.

Capabilities:
- Play, pause, skip, volume on Spotify.
- Set and cancel alarms.
- Take dictated notes.
- Read today's briefing.
- Remember facts the user tells you to remember.
- Recall things from prior conversations when relevant.

When a request is ambiguous, ask one short clarifying question. Do not assume.

Current date: {date}
Recent memory (last 7 days of summaries): {memory}
Standing facts about the user: {facts}
"""


def build(today: str, memory: str, facts: str) -> str:
    return SYSTEM_PROMPT.format(
        date=today,
        memory=memory if memory.strip() else "(no recent memory)",
        facts=facts if facts.strip() else "(no standing facts)",
    )
```

- [ ] **Step 2:** Commit.

```bash
git add src/personality.py
git commit -m "feat(personality): system prompt builder"
```

### Task 3.3: Write `tests/test_personality.py`

**Files:**
- Create: `tests/test_personality.py`

- [ ] **Step 1:** Write the failing test.

```python
from src import personality


def test_placeholders_filled():
    prompt = personality.build(today="2026-04-18", memory="m1 body", facts="f1 body")
    assert "2026-04-18" in prompt
    assert "m1 body" in prompt
    assert "f1 body" in prompt
    assert "FRIDAY" in prompt


def test_empty_memory_defaults():
    prompt = personality.build(today="2026-04-18", memory="", facts="")
    assert "(no recent memory)" in prompt
    assert "(no standing facts)" in prompt


def test_whitespace_only_defaults():
    prompt = personality.build(today="2026-04-18", memory="   \n", facts="\t")
    assert "(no recent memory)" in prompt
    assert "(no standing facts)" in prompt
```

- [ ] **Step 2:** Run.

```bash
.venv/Scripts/python -m pytest tests/test_personality.py -v
```

Expected: 3 passed.

- [ ] **Step 3:** Commit.

```bash
git add tests/test_personality.py
git commit -m "test(personality): cover prompt builder placeholders"
```

### Task 3.4: Write `src/tools/state.py`

**Files:**
- Create: `src/tools/state.py`

- [ ] **Step 1:** Write the module. The @tool decorator runs in a separate process context and forbids closures over runtime state, so we expose a module-level singleton that handlers read with `get()`.

```python
"""Shared state for MCP tool handlers.

The ``@tool`` decorator from claude_agent_sdk registers handlers into an
out-of-process MCP server; closures over local variables do not survive the
registration boundary. Instead, the main loop calls :func:`init` at startup
to populate the singleton, and every handler calls :func:`get` to read it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolState:
    cfg: Any = None
    scheduler: Any = None
    spotify: Any = None
    speak: Optional[Callable[[str], None]] = None
    memory: Any = None


_state = ToolState()


def init(
    cfg: Any = None,
    scheduler: Any = None,
    spotify: Any = None,
    speak: Optional[Callable[[str], None]] = None,
    memory: Any = None,
) -> None:
    _state.cfg = cfg
    _state.scheduler = scheduler
    _state.spotify = spotify
    _state.speak = speak
    _state.memory = memory


def get() -> ToolState:
    return _state


def reset() -> None:
    _state.cfg = None
    _state.scheduler = None
    _state.spotify = None
    _state.speak = None
    _state.memory = None
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/state.py
git commit -m "feat(tools): shared state singleton for handlers"
```

### Task 3.5: Write `src/tools/util_tool.py`

**Files:**
- Create: `src/tools/util_tool.py`

- [ ] **Step 1:** Write the module.

```python
"""Utility tools for FRIDAY. Currently: ``get_time``."""

from __future__ import annotations

from datetime import datetime

from claude_agent_sdk import tool


@tool("get_time", "Return the current local time in ISO 8601 format.", {})
async def get_time(_args):
    now = datetime.now().isoformat(timespec="seconds")
    return {"content": [{"type": "text", "text": now}]}
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/util_tool.py
git commit -m "feat(tools): get_time util tool"
```

### Task 3.6: Write `tests/test_util_tool.py`

**Files:**
- Create: `tests/test_util_tool.py`

- [ ] **Step 1:** Write the test. The `@tool` decorator returns an object with a `handler` attribute; we call it directly.

```python
from datetime import datetime

import pytest

from src.tools import util_tool


@pytest.mark.asyncio
async def test_get_time_returns_parseable_iso():
    result = await util_tool.get_time.handler({})
    text = result["content"][0]["text"]
    parsed = datetime.fromisoformat(text)
    delta = abs((datetime.now() - parsed).total_seconds())
    assert delta < 5, f"get_time drift too large: {delta}s"
```

- [ ] **Step 2:** Run.

```bash
.venv/Scripts/python -m pytest tests/test_util_tool.py -v
```

Expected: 1 passed. If the SDK exposes the handler under a different attribute name (e.g. `fn`), adjust here — check `dir(util_tool.get_time)` in a REPL.

- [ ] **Step 3:** Commit.

```bash
git add tests/test_util_tool.py
git commit -m "test(tools): cover get_time handler"
```

### Task 3.7: Write `src/tools/__init__.py` with `build_server` and `ALLOWED_TOOL_NAMES` (Phase 3 scope)

**Files:**
- Modify: `src/tools/__init__.py`

- [ ] **Step 1:** Write the initial version — only `get_time` is registered at this phase. Later phases will add more tools.

```python
"""MCP server factory + allowed-tool list for FRIDAY.

Tools are added progressively across the build phases. The allowed-tool name
format is ``mcp__friday__<tool_name>`` — this is the convention the Agent
SDK uses to address tools inside a named MCP server."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import util_tool


ALLOWED_TOOL_NAMES = [
    "mcp__friday__get_time",
]


def build_server():
    return create_sdk_mcp_server(
        name="friday",
        version="1.0.0",
        tools=[
            util_tool.get_time,
        ],
    )
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/__init__.py
git commit -m "feat(tools): MCP server factory with get_time"
```

### Task 3.8: Write `src/brain.py`

**Files:**
- Create: `src/brain.py`

- [ ] **Step 1:** Write the module.

```python
"""Claude Agent SDK wrapper.

Calls :func:`claude_agent_sdk.query` with our MCP server and allowed-tool
list. Iterates yielded messages, capturing the session id from the init
SystemMessage and the final text from the ResultMessage.

Auth note: the SDK inherits the active ``claude login`` session — no API
key is passed here; the user's Claude Max subscription provides quota."""

from __future__ import annotations

from typing import Optional

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    query,
)

from . import personality  # noqa: F401 — re-exported for convenience
from .tools import ALLOWED_TOOL_NAMES, build_server


class Brain:
    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model
        self.server = build_server()

    async def ask(
        self,
        user_text: str,
        system_prompt: str,
        session_id: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        options = ClaudeAgentOptions(
            model=self.model,
            system_prompt=system_prompt,
            mcp_servers={"friday": self.server},
            allowed_tools=ALLOWED_TOOL_NAMES,
            setting_sources=[],  # do NOT auto-load .claude/ skills
            permission_mode="bypassPermissions",
            resume=session_id,
        )

        new_session_id = session_id
        final_text = ""

        async for msg in query(prompt=user_text, options=options):
            if isinstance(msg, SystemMessage) and getattr(msg, "subtype", None) == "init":
                data = getattr(msg, "data", None) or {}
                if isinstance(data, dict) and "session_id" in data:
                    new_session_id = data["session_id"]
            elif isinstance(msg, ResultMessage):
                final_text = getattr(msg, "result", "") or ""

        return final_text, new_session_id
```

- [ ] **Step 2:** Commit.

```bash
git add src/brain.py
git commit -m "feat(brain): claude agent sdk query wrapper"
```

### Task 3.9: Write `friday.py` — single-turn end-to-end loop

**Files:**
- Create: `friday.py`

- [ ] **Step 1:** Write the entrypoint. This Phase 3 version does wake → record → STT → brain → TTS → back to wake, one turn per wake. Phase 3.5 upgrades to proper sessions.

```python
"""FRIDAY entrypoint — Phase 3 single-turn loop.

Flow: wait for wake word → record until silence → STT → brain → TTS → loop.
One turn per wake. Phase 3.5 will replace this with an active-session loop."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime

from src import config as cfg_mod
from src import audio
from src.brain import Brain
from src import personality
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
        # Windows asyncio lacks add_signal_handler — Ctrl+C still works via
        # KeyboardInterrupt in asyncio.run().
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
```

- [ ] **Step 2:** Run it.

```bash
.venv/Scripts/python friday.py
```

Say *"Friday"*. Expect the "Yes, boss." confirmation. Then ask *"What time is it?"* and let the recorder detect end of speech.

Expected: FRIDAY speaks back the current time (e.g. *"It's 14:32, boss."* — exact wording depends on Claude, but it calls `get_time` and reports the result).

- [ ] **Step 3:** Stop with Ctrl+C. Commit.

```bash
git add friday.py
git commit -m "feat: single-turn voice loop with claude brain + get_time"
```

---

## REVIEW CHECKPOINT — Phase 3

**Stop. Manually verify before continuing.**

- [ ] Wake word fires, FRIDAY says "Yes, boss.", captures question, transcribes, invokes `get_time`, and speaks the answer.
- [ ] Personality "feels right" — dry, terse. If Claude is chatty, re-read `src/personality.py` and compare to spec §8.
- [ ] No stack traces from the Agent SDK. If you see `setting_sources` or `permission_mode` errors, your installed `claude-agent-sdk` may be older than 0.2.111 — upgrade.
- [ ] `tests/test_personality.py` and `tests/test_util_tool.py` pass: `.venv/Scripts/python -m pytest -v`.

When pass, approve and continue to Phase 3.5.

---

## Phase 3.5: Session state machine + close-phrase matcher

Goal: upgrade the one-shot flow to a proper active session. Wake word starts an `ACTIVE` session; follow-ups do not need re-wake; session ends on an explicit close phrase ("thanks friday" etc.) or a safety timeout (default 5 min). On close, FRIDAY says "Done, boss." and (eventually) summarises the session; Phase 6 adds the summary — here we just close cleanly and return to wake.

### Task 3.5.1: Write `src/session.py`

**Files:**
- Create: `src/session.py`

- [ ] **Step 1:** Write the module.

```python
"""Active-session state machine and close-phrase detection.

Normalisation: we lowercase, keep only ``[a-z']`` character runs, then
collapse whitespace. This makes "That's all, Friday!" match "that's all
friday" even with punctuation and capitalisation variation.

Close detection: a phrase matches if its normalised form appears as a
substring of the normalised transcript. ``close_phrases`` is configurable
via ``config/friday.yaml`` — keep both apostrophe and no-apostrophe
variants because STT punctuation is inconsistent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

_WORD_RE = re.compile(r"[a-z']+")


class State(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    SPEAKING = "speaking"


@dataclass
class Session:
    state: State = State.IDLE
    turns: list[dict] = field(default_factory=list)
    sdk_session_id: Optional[str] = None


def normalize(s: str) -> str:
    return " ".join(_WORD_RE.findall(s.lower()))


def is_close_phrase(transcript: str, phrases: Iterable[str]) -> bool:
    t = normalize(transcript)
    if not t:
        return False
    for p in phrases:
        n = normalize(p)
        if n and n in t:
            return True
    return False
```

- [ ] **Step 2:** Commit.

```bash
git add src/session.py
git commit -m "feat(session): state machine + close-phrase matcher"
```

### Task 3.5.2: Write `tests/test_session.py`

**Files:**
- Create: `tests/test_session.py`

- [ ] **Step 1:** Write the failing tests.

```python
from src.session import Session, State, is_close_phrase, normalize


CLOSE = [
    "that's all friday",
    "thats all friday",
    "thanks friday",
    "thank you friday",
    "fine friday",
    "goodbye friday",
    "bye friday",
    "we're done friday",
    "were done friday",
]


def test_normalize_keeps_apostrophes():
    assert normalize("That's all, Friday!") == "that's all friday"


def test_normalize_collapses_punctuation():
    assert normalize("Hey — Friday. Thanks!") == "hey friday thanks"


def test_empty_transcript_not_close():
    assert not is_close_phrase("", CLOSE)
    assert not is_close_phrase("   ", CLOSE)


def test_exact_close_phrases():
    for p in CLOSE:
        assert is_close_phrase(p, CLOSE), f"failed: {p!r}"


def test_close_embedded_in_longer_utterance():
    assert is_close_phrase("Okay thanks Friday, that was useful", CLOSE)


def test_apostrophe_dropped_variant():
    assert is_close_phrase("thats all friday", CLOSE)


def test_non_close_question_not_matched():
    assert not is_close_phrase("Friday what time is it", CLOSE)
    assert not is_close_phrase("Hey Friday, play Bowie", CLOSE)


def test_session_defaults():
    s = Session()
    assert s.state is State.IDLE
    assert s.turns == []
    assert s.sdk_session_id is None


def test_session_mutable():
    s = Session()
    s.state = State.ACTIVE
    s.turns.append({"user": "hi"})
    assert s.state is State.ACTIVE
    assert len(s.turns) == 1
```

- [ ] **Step 2:** Run.

```bash
.venv/Scripts/python -m pytest tests/test_session.py -v
```

Expected: 9 passed.

- [ ] **Step 3:** Commit.

```bash
git add tests/test_session.py
git commit -m "test(session): close-phrase matcher + state machine"
```

### Task 3.5.3: Update `friday.py` to use the session loop

**Files:**
- Modify: `friday.py`

- [ ] **Step 1:** Replace the contents of `friday.py` entirely.

```python
"""FRIDAY entrypoint — Phase 3.5 session loop.

Flow: wake → say "Yes, boss." → enter ACTIVE session → loop (record → STT →
close phrase? ack+exit : brain → TTS) → on close or timeout, re-arm wake."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime

from src import audio
from src import config as cfg_mod
from src import personality
from src.brain import Brain
from src.session import Session, State, is_close_phrase
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


async def session_loop(
    cfg,
    brain: Brain,
    stt: STT,
    vad: VAD,
    tts: TTS,
    session: Session,
) -> None:
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
        session = Session(state=State.ACTIVE)
        try:
            await asyncio.wait_for(
                session_loop(cfg, brain, stt, vad, tts, session),
                timeout=cfg.silence_timeout_s,
            )
        except asyncio.TimeoutError:
            tts.speak("Closing out, boss.")
            session.state = State.IDLE


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 2:** Run.

```bash
.venv/Scripts/python friday.py
```

Say "Friday" → "Yes, boss." Ask "what time is it?" Hear the answer. Without re-waking, say "and what day is it?" — FRIDAY should answer without needing a fresh wake. Finally say "thanks Friday" — FRIDAY says "Done, boss." and returns to wake listening.

- [ ] **Step 3:** Commit.

```bash
git add friday.py
git commit -m "feat(session): upgrade main loop to active-session model"
```

---

## REVIEW CHECKPOINT — Phase 3.5

**Stop. Manually verify before continuing.**

- [ ] Multi-turn within one wake works: ask two questions in a row without saying "Friday" again.
- [ ] Close phrase terminates the session: "thanks friday" → "Done, boss." → re-armed for wake.
- [ ] Safety timeout works: after wake, stay silent for five minutes; FRIDAY says "Closing out, boss." and re-arms. (If you don't want to wait 5 min, temporarily set `silence_timeout_s: 30` in `config/friday.yaml` and revert afterwards.)
- [ ] `.venv/Scripts/python -m pytest -v` — all tests still pass.

When pass, approve and continue to Phase 4.

---

## Phase 4: Domain tools — Spotify, notes, briefing

Goal: three user-visible capabilities wired as MCP tools. "Friday, play Bowie." "Friday, take a note: buy coffee." "Friday, what's on today?" All work end-to-end.

**Deviation from spec §7:** `set_volume` controls the **Spotify client** (via `spotipy.Spotify.volume()`), not OS-level volume. Spec said alsamixer, which is Linux-only. On Windows we don't have a clean cross-platform system-volume hook without shelling out to `nircmd` or friends — skipping that for v1. Revisit on Pi.

### Task 4.1: Spotify OAuth bootstrap

**Files:**
- Modify: `config/.env` (already has Spotify client id/secret from Task 0.6)

- [ ] **Step 1:** Verify your Spotify account has at least one active device. Open Spotify on your laptop (or phone) and start playing anything for five seconds, then pause. This registers a "device" that the Web API can control.

- [ ] **Step 2:** First-run OAuth. `spotipy` opens a browser on first use; the redirect URI must match what you set in the Spotify developer dashboard (`http://127.0.0.1:8080/callback`). Run this one-liner to trigger the OAuth flow and cache the token:

```bash
.venv/Scripts/python -c "import os, spotipy; from spotipy.oauth2 import SpotifyOAuth; from dotenv import load_dotenv; load_dotenv('config/.env'); sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=os.environ['SPOTIFY_CLIENT_ID'], client_secret=os.environ['SPOTIFY_CLIENT_SECRET'], redirect_uri=os.environ.get('SPOTIFY_REDIRECT_URI','http://127.0.0.1:8080/callback'), scope='user-modify-playback-state user-read-playback-state', open_browser=True, cache_path='.spotipy_cache')); print(sp.me()['display_name'])"
```

Expected: browser opens → you approve access → the terminal prints your Spotify display name. A `.spotipy_cache` file appears in the repo root (add to `.gitignore` in next step).

- [ ] **Step 3:** Add the cache file to `.gitignore`.

```bash
echo ".spotipy_cache" >> .gitignore
git add .gitignore
git commit -m "chore: gitignore spotipy token cache"
```

### Task 4.2: Write `src/tools/spotify_tool.py`

**Files:**
- Create: `src/tools/spotify_tool.py`

- [ ] **Step 1:** Write the module.

```python
"""Spotify playback tools.

All handlers reach the shared ``spotipy.Spotify`` client through
``tool_state.get().spotify``. If no client is registered (user opted out or
Spotify init failed), handlers return a clear error message Claude can
surface to the user."""

from __future__ import annotations

from claude_agent_sdk import tool

from .state import get


def _require_sp():
    sp = get().spotify
    if sp is None:
        return None, {"content": [{"type": "text", "text": "spotify not configured"}]}
    return sp, None


@tool(
    "play_spotify",
    "Search Spotify and start playback of the top result on the active device.",
    {"query": str},
)
async def play_spotify(args):
    sp, err = _require_sp()
    if err:
        return err
    results = sp.search(q=args["query"], type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return {"content": [{"type": "text", "text": "no match"}]}
    track = items[0]
    sp.start_playback(uris=[track["uri"]])
    artist = track["artists"][0]["name"] if track.get("artists") else "?"
    return {
        "content": [
            {"type": "text", "text": f"playing {track['name']} by {artist}"}
        ]
    }


@tool("pause_spotify", "Pause Spotify playback.", {})
async def pause_spotify(_args):
    sp, err = _require_sp()
    if err:
        return err
    sp.pause_playback()
    return {"content": [{"type": "text", "text": "paused"}]}


@tool("resume_spotify", "Resume Spotify playback.", {})
async def resume_spotify(_args):
    sp, err = _require_sp()
    if err:
        return err
    sp.start_playback()
    return {"content": [{"type": "text", "text": "resumed"}]}


@tool("skip_track", "Skip to the next track on Spotify.", {})
async def skip_track(_args):
    sp, err = _require_sp()
    if err:
        return err
    sp.next_track()
    return {"content": [{"type": "text", "text": "skipped"}]}


@tool(
    "set_volume",
    "Set the Spotify client volume (0-100).",
    {"level": int},
)
async def set_volume(args):
    sp, err = _require_sp()
    if err:
        return err
    level = max(0, min(100, int(args["level"])))
    sp.volume(level)
    return {"content": [{"type": "text", "text": f"volume {level}"}]}
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/spotify_tool.py
git commit -m "feat(tools): spotify play/pause/resume/skip/volume"
```

### Task 4.3: Write `src/tools/notes_tool.py`

**Files:**
- Create: `src/tools/notes_tool.py`

- [ ] **Step 1:** Write the module.

```python
"""Dictation notes — append-only markdown with ``HH:MM`` timestamps."""

from __future__ import annotations

from datetime import datetime

from claude_agent_sdk import tool

from .state import get


@tool(
    "write_note",
    "Append a timestamped note to ~/friday/notes.md.",
    {"content": str},
)
async def write_note(args):
    state = get()
    content = args["content"].strip()
    if not content:
        return {"content": [{"type": "text", "text": "empty note, skipped"}]}
    now = datetime.now()
    line = f"- [{now.strftime('%H:%M')}] {content}\n"
    path = state.cfg.paths.notes
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
    return {"content": [{"type": "text", "text": "noted"}]}
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/notes_tool.py
git commit -m "feat(tools): write_note to notes.md"
```

### Task 4.4: Write `tests/test_notes_tool.py`

**Files:**
- Create: `tests/test_notes_tool.py`

- [ ] **Step 1:** Write the test. It uses the ToolState singleton — we inject a mock config whose `paths.notes` points into `tmp_path`.

```python
import re
from types import SimpleNamespace

import pytest

from src.tools import notes_tool
from src.tools import state as tool_state


@pytest.fixture(autouse=True)
def _reset_state():
    tool_state.reset()
    yield
    tool_state.reset()


@pytest.mark.asyncio
async def test_note_line_format(tmp_path):
    notes = tmp_path / "notes.md"
    cfg = SimpleNamespace(paths=SimpleNamespace(notes=notes))
    tool_state.init(cfg=cfg)

    result = await notes_tool.write_note.handler({"content": "buy coffee"})

    assert result["content"][0]["text"] == "noted"
    lines = notes.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert re.match(r"^- \[\d{2}:\d{2}\] buy coffee$", lines[0])


@pytest.mark.asyncio
async def test_note_append_preserves_prior(tmp_path):
    notes = tmp_path / "notes.md"
    notes.write_text("- [09:00] earlier\n", encoding="utf-8")
    cfg = SimpleNamespace(paths=SimpleNamespace(notes=notes))
    tool_state.init(cfg=cfg)

    await notes_tool.write_note.handler({"content": "later"})

    body = notes.read_text(encoding="utf-8")
    assert "earlier" in body
    assert "later" in body


@pytest.mark.asyncio
async def test_empty_note_skipped(tmp_path):
    notes = tmp_path / "notes.md"
    cfg = SimpleNamespace(paths=SimpleNamespace(notes=notes))
    tool_state.init(cfg=cfg)

    result = await notes_tool.write_note.handler({"content": "   "})

    assert result["content"][0]["text"] == "empty note, skipped"
    assert not notes.exists()
```

- [ ] **Step 2:** Run.

```bash
.venv/Scripts/python -m pytest tests/test_notes_tool.py -v
```

Expected: 3 passed.

- [ ] **Step 3:** Commit.

```bash
git add tests/test_notes_tool.py
git commit -m "test(tools): cover notes tool formatting + append"
```

### Task 4.5: Write `src/tools/briefing_tool.py`

**Files:**
- Create: `src/tools/briefing_tool.py`

- [ ] **Step 1:** Write the module.

```python
"""Daily briefing reader — returns the text of ~/friday/today.md."""

from __future__ import annotations

from claude_agent_sdk import tool

from .state import get


@tool(
    "read_briefing",
    "Read today's briefing from ~/friday/today.md so FRIDAY can speak it.",
    {},
)
async def read_briefing(_args):
    state = get()
    path = state.cfg.paths.today
    if not path.exists():
        return {"content": [{"type": "text", "text": "no briefing for today"}]}
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        return {"content": [{"type": "text", "text": "briefing file is empty"}]}
    return {"content": [{"type": "text", "text": body}]}
```

- [ ] **Step 2:** Create a sample briefing file for the live test.

```bash
mkdir -p "$HOME/friday"
printf "Dentist at 3pm. Pick up parcel before 6. Gym is closed today.\n" > "$HOME/friday/today.md"
```

- [ ] **Step 3:** Commit.

```bash
git add src/tools/briefing_tool.py
git commit -m "feat(tools): read_briefing from today.md"
```

### Task 4.6: Register the new tools in `src/tools/__init__.py`

**Files:**
- Modify: `src/tools/__init__.py`

- [ ] **Step 1:** Replace the file contents with the Phase 4 version.

```python
"""MCP server factory + allowed-tool list for FRIDAY.

Phase 4: adds Spotify, notes, briefing tools."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import briefing_tool, notes_tool, spotify_tool, util_tool


ALLOWED_TOOL_NAMES = [
    "mcp__friday__get_time",
    "mcp__friday__play_spotify",
    "mcp__friday__pause_spotify",
    "mcp__friday__resume_spotify",
    "mcp__friday__skip_track",
    "mcp__friday__set_volume",
    "mcp__friday__write_note",
    "mcp__friday__read_briefing",
]


def build_server():
    return create_sdk_mcp_server(
        name="friday",
        version="1.0.0",
        tools=[
            util_tool.get_time,
            spotify_tool.play_spotify,
            spotify_tool.pause_spotify,
            spotify_tool.resume_spotify,
            spotify_tool.skip_track,
            spotify_tool.set_volume,
            notes_tool.write_note,
            briefing_tool.read_briefing,
        ],
    )
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/__init__.py
git commit -m "feat(tools): register spotify, notes, briefing with MCP server"
```

### Task 4.7: Update `friday.py` to initialise Spotify and pass to `tool_state`

**Files:**
- Modify: `friday.py`

- [ ] **Step 1:** Replace `friday.py` with the Phase 4 version.

```python
"""FRIDAY entrypoint — Phase 4: Spotify + notes + briefing wired."""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import datetime

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src import audio
from src import config as cfg_mod
from src import personality
from src.brain import Brain
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
    tool_state.init(cfg=cfg, speak=tts.speak, spotify=sp)

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
        session = Session(state=State.ACTIVE)
        try:
            await asyncio.wait_for(
                session_loop(cfg, brain, stt, vad, tts, session),
                timeout=cfg.silence_timeout_s,
            )
        except asyncio.TimeoutError:
            tts.speak("Closing out, boss.")
            session.state = State.IDLE


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 2:** Run and test each capability.

```bash
.venv/Scripts/python friday.py
```

- Say "Friday, play Bowie." → Spotify starts a Bowie track on the active device.
- Say "Friday, take a note: pick up coffee tomorrow." → `~/friday/notes.md` gains a timestamped line.
- Say "Friday, what's on today?" → FRIDAY reads the text of `today.md` aloud.
- Say "Friday, volume 40." → Spotify client volume drops.
- Say "Friday, skip." → next track.
- Say "thanks Friday" → "Done, boss."

- [ ] **Step 3:** Commit.

```bash
git add friday.py
git commit -m "feat: wire spotify + notes + briefing into main loop"
```

---

## REVIEW CHECKPOINT — Phase 4

**Stop. Manually verify before continuing.**

- [ ] All five Spotify actions work (play, pause, resume, skip, volume).
- [ ] `write_note` appends correctly — inspect `~/friday/notes.md`.
- [ ] `read_briefing` reads `today.md` aloud in FRIDAY's voice (not just reports it silently).
- [ ] `.venv/Scripts/python -m pytest -v` passes, including new notes tool tests.
- [ ] If the first Spotify call errors with "No active device", make sure Spotify is open on at least one device and you've played/paused once.

When pass, approve and continue to Phase 5.

---

## Phase 5: Alarms + APScheduler

Goal: set, list, and cancel alarms by voice. Alarms persist across restarts via `~/friday/alarms.json`. When an alarm fires, FRIDAY speaks the label directly via Piper — **no Claude round-trip** — so alarms are dumb and reliable even if the API is down.

### Task 5.1: Write `src/scheduler.py`

**Files:**
- Create: `src/scheduler.py`

- [ ] **Step 1:** Write the module.

```python
"""APScheduler-backed alarm manager.

Alarms are persisted to a JSON file (``cfg.paths.alarms_json``) as a plain
list of ``{"id", "when", "label"}`` dicts. We do NOT use APScheduler's
jobstore — on :meth:`start`, we read the JSON and re-schedule any future
alarms. On fire, the callback calls ``speak(f"Boss — {label}.")`` directly,
bypassing Claude so alarms work offline."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


class AlarmScheduler:
    def __init__(
        self,
        alarms_path: Path,
        speak: Callable[[str], None],
    ) -> None:
        self.path = alarms_path
        self.speak = speak
        self.sched = AsyncIOScheduler()
        self.alarms: dict[str, dict] = {}

    async def start(self) -> None:
        self.sched.start()
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8") or "[]")
            now = datetime.now()
            for a in data:
                when = datetime.fromisoformat(a["when"])
                if when > now:
                    self.alarms[a["id"]] = a
                    self._schedule(a["id"], when, a["label"])
            # Purge any past alarms from the file.
            self._persist()

    def set(self, when: datetime, label: str) -> str:
        aid = uuid.uuid4().hex[:8]
        record = {"id": aid, "when": when.isoformat(), "label": label}
        self.alarms[aid] = record
        self._schedule(aid, when, label)
        self._persist()
        return aid

    def cancel(self, aid: str) -> bool:
        if aid not in self.alarms:
            return False
        try:
            self.sched.remove_job(aid)
        except Exception:
            pass
        del self.alarms[aid]
        self._persist()
        return True

    def list(self) -> list[dict]:
        return sorted(self.alarms.values(), key=lambda a: a["when"])

    def _schedule(self, aid: str, when: datetime, label: str) -> None:
        def _fire():
            try:
                self.speak(f"Boss — {label}.")
            finally:
                self.alarms.pop(aid, None)
                self._persist()

        self.sched.add_job(_fire, DateTrigger(run_date=when), id=aid)

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(list(self.alarms.values()), indent=2),
            encoding="utf-8",
        )
```

- [ ] **Step 2:** Commit.

```bash
git add src/scheduler.py
git commit -m "feat(scheduler): apscheduler alarm manager with json persistence"
```

### Task 5.2: Write `tests/test_scheduler.py`

**Files:**
- Create: `tests/test_scheduler.py`

- [ ] **Step 1:** Write the tests.

```python
import json
from datetime import datetime, timedelta

import pytest

from src.scheduler import AlarmScheduler


@pytest.mark.asyncio
async def test_set_persists_to_json(tmp_path):
    sched = AlarmScheduler(tmp_path / "alarms.json", speak=lambda _s: None)
    await sched.start()
    future = datetime.now() + timedelta(hours=1)
    aid = sched.set(future, "take meds")
    data = json.loads((tmp_path / "alarms.json").read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == aid
    assert data[0]["label"] == "take meds"
    sched.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_cancel_removes(tmp_path):
    sched = AlarmScheduler(tmp_path / "alarms.json", speak=lambda _s: None)
    await sched.start()
    aid = sched.set(datetime.now() + timedelta(hours=1), "x")
    assert sched.cancel(aid) is True
    assert sched.cancel(aid) is False
    assert sched.list() == []
    sched.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_reload_on_start(tmp_path):
    path = tmp_path / "alarms.json"
    sched1 = AlarmScheduler(path, speak=lambda _s: None)
    await sched1.start()
    sched1.set(datetime.now() + timedelta(hours=2), "survive")
    sched1.sched.shutdown(wait=False)

    sched2 = AlarmScheduler(path, speak=lambda _s: None)
    await sched2.start()
    assert any(a["label"] == "survive" for a in sched2.list())
    sched2.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_past_alarms_purged_on_start(tmp_path):
    path = tmp_path / "alarms.json"
    path.write_text(
        json.dumps(
            [
                {"id": "old", "when": (datetime.now() - timedelta(days=1)).isoformat(), "label": "stale"},
                {"id": "new", "when": (datetime.now() + timedelta(days=1)).isoformat(), "label": "keep"},
            ]
        ),
        encoding="utf-8",
    )
    sched = AlarmScheduler(path, speak=lambda _s: None)
    await sched.start()
    labels = [a["label"] for a in sched.list()]
    assert labels == ["keep"]
    sched.sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_list_sorted_by_when(tmp_path):
    sched = AlarmScheduler(tmp_path / "alarms.json", speak=lambda _s: None)
    await sched.start()
    t_later = datetime.now() + timedelta(hours=5)
    t_sooner = datetime.now() + timedelta(hours=1)
    sched.set(t_later, "later")
    sched.set(t_sooner, "sooner")
    labels = [a["label"] for a in sched.list()]
    assert labels == ["sooner", "later"]
    sched.sched.shutdown(wait=False)
```

- [ ] **Step 2:** Run.

```bash
.venv/Scripts/python -m pytest tests/test_scheduler.py -v
```

Expected: 5 passed.

- [ ] **Step 3:** Commit.

```bash
git add tests/test_scheduler.py
git commit -m "test(scheduler): persistence, cancel, reload, ordering"
```

### Task 5.3: Write `src/tools/alarm_tool.py`

**Files:**
- Create: `src/tools/alarm_tool.py`

- [ ] **Step 1:** Write the module. Natural-language time strings ("7:30 tomorrow", "in 15 minutes", "friday at 9am") are parsed with `dateparser`. When parsing fails, the tool returns an error message that Claude will relay to the user.

```python
"""Alarm tools: set, cancel, list. Natural-language times via dateparser."""

from __future__ import annotations

import dateparser
from claude_agent_sdk import tool

from .state import get


def _require_scheduler():
    sch = get().scheduler
    if sch is None:
        return None, {"content": [{"type": "text", "text": "scheduler not running"}]}
    return sch, None


@tool(
    "set_alarm",
    (
        "Set an alarm. `when` accepts natural language such as "
        "'7:30 tomorrow' or 'in 15 minutes'. `label` is what FRIDAY will "
        "speak when the alarm fires."
    ),
    {"when": str, "label": str},
)
async def set_alarm(args):
    sch, err = _require_scheduler()
    if err:
        return err
    when_str = args["when"]
    label = args["label"].strip() or "alarm"
    dt = dateparser.parse(when_str, settings={"PREFER_DATES_FROM": "future"})
    if dt is None:
        return {
            "content": [
                {"type": "text", "text": f"could not parse time: {when_str}"}
            ]
        }
    aid = sch.set(dt, label)
    pretty = dt.strftime("%a %H:%M")
    return {
        "content": [
            {"type": "text", "text": f"alarm {aid} set for {pretty}: {label}"}
        ]
    }


@tool("cancel_alarm", "Cancel an alarm by its id.", {"id": str})
async def cancel_alarm(args):
    sch, err = _require_scheduler()
    if err:
        return err
    ok = sch.cancel(args["id"])
    return {
        "content": [
            {"type": "text", "text": "cancelled" if ok else "no alarm with that id"}
        ]
    }


@tool("list_alarms", "List all pending alarms.", {})
async def list_alarms(_args):
    sch, err = _require_scheduler()
    if err:
        return err
    items = sch.list()
    if not items:
        return {"content": [{"type": "text", "text": "no alarms"}]}
    lines = [
        f"{a['id']}: {a['when']} — {a['label']}" for a in items
    ]
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/alarm_tool.py
git commit -m "feat(tools): alarm set/cancel/list with dateparser"
```

### Task 5.4: Register alarm tools in `src/tools/__init__.py`

**Files:**
- Modify: `src/tools/__init__.py`

- [ ] **Step 1:** Replace with the Phase 5 version.

```python
"""MCP server factory + allowed-tool list for FRIDAY.

Phase 5: adds alarm tools."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import alarm_tool, briefing_tool, notes_tool, spotify_tool, util_tool


ALLOWED_TOOL_NAMES = [
    "mcp__friday__get_time",
    "mcp__friday__play_spotify",
    "mcp__friday__pause_spotify",
    "mcp__friday__resume_spotify",
    "mcp__friday__skip_track",
    "mcp__friday__set_volume",
    "mcp__friday__write_note",
    "mcp__friday__read_briefing",
    "mcp__friday__set_alarm",
    "mcp__friday__cancel_alarm",
    "mcp__friday__list_alarms",
]


def build_server():
    return create_sdk_mcp_server(
        name="friday",
        version="1.0.0",
        tools=[
            util_tool.get_time,
            spotify_tool.play_spotify,
            spotify_tool.pause_spotify,
            spotify_tool.resume_spotify,
            spotify_tool.skip_track,
            spotify_tool.set_volume,
            notes_tool.write_note,
            briefing_tool.read_briefing,
            alarm_tool.set_alarm,
            alarm_tool.cancel_alarm,
            alarm_tool.list_alarms,
        ],
    )
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/__init__.py
git commit -m "feat(tools): register alarm tools with MCP server"
```

### Task 5.5: Update `friday.py` to start the scheduler and register it in tool state

**Files:**
- Modify: `friday.py`

- [ ] **Step 1:** Replace `friday.py` with the Phase 5 version.

```python
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
```

- [ ] **Step 2:** Run and test.

```bash
.venv/Scripts/python friday.py
```

- Say "Friday, set an alarm in two minutes called testing." → FRIDAY confirms. Check `~/friday/alarms.json` has one entry.
- Say "Friday, list my alarms." → FRIDAY reads back the one alarm.
- Wait up to two minutes → FRIDAY speaks "Boss — testing." (no wake word, no session needed).
- Restart `friday.py` before a future alarm fires — the alarm persists.
- Say "Friday, cancel alarm [id]" → FRIDAY confirms cancellation.

- [ ] **Step 3:** Commit.

```bash
git add friday.py
git commit -m "feat: bring alarms online in main loop"
```

---

## REVIEW CHECKPOINT — Phase 5

**Stop. Manually verify before continuing.**

- [ ] An alarm set for ~2 min fires and FRIDAY speaks the label correctly.
- [ ] Alarms survive a full process restart (`Ctrl+C`, `python friday.py`).
- [ ] `list_alarms` and `cancel_alarm` both round-trip via voice.
- [ ] Cancelling a non-existent id returns a clear message ("no alarm with that id").
- [ ] `.venv/Scripts/python -m pytest -v` — all tests pass.

When pass, approve and continue to Phase 6.

---

## Phase 6: Memory layer (facts + daily summaries + 7-day injection)

Goal: three-tier memory from spec §6. Session ends → Claude summarises the conversation → summary appended to `~/friday/memory/YYYY-MM-DD.md`. Next session's system prompt includes the last 7 days of summaries + `facts.md` contents. `remember_fact` tool lets FRIDAY (or user-directed) persist durable facts. After this phase, the MVP is complete for this plan.

### Task 6.1: Write `src/memory.py`

**Files:**
- Create: `src/memory.py`

- [ ] **Step 1:** Write the module.

```python
"""Persistent memory for FRIDAY.

Three surfaces (spec §6):

* **Short-term** — in-session conversation turns, held by ``Session`` (not
  here).
* **Medium-term** — per-day markdown files of session summaries, loaded as
  a 7-day window into each new session's system prompt.
* **Long-term** — ``facts.md``, a flat ``key: value`` file that is always
  injected verbatim.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


class Memory:
    def __init__(self, memory_dir: Path, facts_path: Path) -> None:
        self.memory_dir = memory_dir
        self.facts_path = facts_path
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.facts_path.parent.mkdir(parents=True, exist_ok=True)

    def append_summary(self, summary: str, when: datetime | None = None) -> None:
        when = when or datetime.now()
        path = self.memory_dir / f"{when.date().isoformat()}.md"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {when.isoformat(timespec='minutes')}\n\n{summary.strip()}\n")

    def last_7_days(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        parts: list[str] = []
        for i in range(7):
            d = (now - timedelta(days=i)).date()
            p = self.memory_dir / f"{d.isoformat()}.md"
            if p.exists():
                parts.append(
                    f"### {d.isoformat()}\n{p.read_text(encoding='utf-8').strip()}"
                )
        return "\n\n".join(parts)

    def read_facts(self) -> str:
        if self.facts_path.exists():
            return self.facts_path.read_text(encoding="utf-8")
        return ""

    def append_fact(self, key: str, value: str) -> None:
        key = key.strip()
        value = value.strip()
        if not key or not value:
            return
        with self.facts_path.open("a", encoding="utf-8") as f:
            f.write(f"{key}: {value}\n")
```

- [ ] **Step 2:** Commit.

```bash
git add src/memory.py
git commit -m "feat(memory): facts + daily summaries + 7-day window"
```

### Task 6.2: Write `tests/test_memory.py`

**Files:**
- Create: `tests/test_memory.py`

- [ ] **Step 1:** Write the tests.

```python
from datetime import datetime, timedelta

from src.memory import Memory


def test_facts_round_trip(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    m.append_fact("birthday", "oct 12")
    m.append_fact("favourite artist", "bowie")
    content = m.read_facts()
    assert "birthday: oct 12" in content
    assert "favourite artist: bowie" in content


def test_empty_facts_returns_empty_string(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    assert m.read_facts() == ""


def test_append_fact_trims_and_ignores_empty(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    m.append_fact("  key  ", "  value  ")
    m.append_fact("", "orphan")
    m.append_fact("missing", "")
    lines = m.read_facts().splitlines()
    assert lines == ["key: value"]


def test_summary_append_and_7_day_window(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    now = datetime.now()
    m.append_summary("today's summary", now)
    m.append_summary("three days ago", now - timedelta(days=3))
    combined = m.last_7_days(now)
    assert "today's summary" in combined
    assert "three days ago" in combined


def test_older_than_7_days_excluded(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    now = datetime.now()
    m.append_summary("ancient", now - timedelta(days=30))
    assert "ancient" not in m.last_7_days(now)


def test_same_day_multiple_summaries_accumulate(tmp_path):
    m = Memory(tmp_path / "mem", tmp_path / "mem" / "facts.md")
    now = datetime.now()
    m.append_summary("first", now)
    m.append_summary("second", now)
    window = m.last_7_days(now)
    assert "first" in window
    assert "second" in window
```

- [ ] **Step 2:** Run.

```bash
.venv/Scripts/python -m pytest tests/test_memory.py -v
```

Expected: 6 passed.

- [ ] **Step 3:** Commit.

```bash
git add tests/test_memory.py
git commit -m "test(memory): facts round-trip + 7-day loader"
```

### Task 6.3: Write `src/tools/memory_tool.py`

**Files:**
- Create: `src/tools/memory_tool.py`

- [ ] **Step 1:** Write the module.

```python
"""Memory tools. Currently just ``remember_fact``.

Recall is not a tool: the last 7 days and full facts.md are injected into
the system prompt, so Claude can reference them directly."""

from __future__ import annotations

from claude_agent_sdk import tool

from .state import get


@tool(
    "remember_fact",
    "Save a durable fact about the user to facts.md so it persists across sessions.",
    {"key": str, "value": str},
)
async def remember_fact(args):
    state = get()
    if state.memory is None:
        return {"content": [{"type": "text", "text": "memory not initialised"}]}
    state.memory.append_fact(args["key"], args["value"])
    return {"content": [{"type": "text", "text": "remembered"}]}
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/memory_tool.py
git commit -m "feat(tools): remember_fact persists to facts.md"
```

### Task 6.4: Register `remember_fact` in `src/tools/__init__.py`

**Files:**
- Modify: `src/tools/__init__.py`

- [ ] **Step 1:** Replace with the Phase 6 version.

```python
"""MCP server factory + allowed-tool list for FRIDAY.

Phase 6: full tool roster."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server

from . import (
    alarm_tool,
    briefing_tool,
    memory_tool,
    notes_tool,
    spotify_tool,
    util_tool,
)


ALLOWED_TOOL_NAMES = [
    "mcp__friday__get_time",
    "mcp__friday__play_spotify",
    "mcp__friday__pause_spotify",
    "mcp__friday__resume_spotify",
    "mcp__friday__skip_track",
    "mcp__friday__set_volume",
    "mcp__friday__write_note",
    "mcp__friday__read_briefing",
    "mcp__friday__set_alarm",
    "mcp__friday__cancel_alarm",
    "mcp__friday__list_alarms",
    "mcp__friday__remember_fact",
]


def build_server():
    return create_sdk_mcp_server(
        name="friday",
        version="1.0.0",
        tools=[
            util_tool.get_time,
            spotify_tool.play_spotify,
            spotify_tool.pause_spotify,
            spotify_tool.resume_spotify,
            spotify_tool.skip_track,
            spotify_tool.set_volume,
            notes_tool.write_note,
            briefing_tool.read_briefing,
            alarm_tool.set_alarm,
            alarm_tool.cancel_alarm,
            alarm_tool.list_alarms,
            memory_tool.remember_fact,
        ],
    )
```

- [ ] **Step 2:** Commit.

```bash
git add src/tools/__init__.py
git commit -m "feat(tools): register remember_fact with MCP server"
```

### Task 6.5: Update `friday.py` — inject memory into prompt, summarise on close

**Files:**
- Modify: `friday.py`

- [ ] **Step 1:** Replace `friday.py` with the final Phase 6 version.

```python
"""FRIDAY entrypoint — Phase 6: memory layer complete.

Memory flow:
* Every session's system prompt includes the last 7 days of summaries and
  the full ``facts.md`` contents.
* On session close (explicit phrase or safety timeout), we ask Claude to
  summarise the turns in 3–5 bullet points and append to today's memory
  markdown file.
"""

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


def _build_session_prompt(memory: Memory) -> str:
    return personality.build(
        today=datetime.now().date().isoformat(),
        memory=memory.last_7_days(),
        facts=memory.read_facts(),
    )


async def session_loop(cfg, brain, stt, vad, tts, memory, session: Session) -> None:
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
        sys_prompt = _build_session_prompt(memory)
        session.state = State.SPEAKING
        reply, new_sid = await brain.ask(
            transcript, sys_prompt, session.sdk_session_id
        )
        session.sdk_session_id = new_sid
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
        summary, _ = await brain.ask(transcript, SUMMARY_PROMPT, None)
    except Exception as e:
        print(f"[memory] summary failed: {e}")
        return
    if summary:
        memory.append_summary(summary)


async def main() -> None:
    cfg = cfg_mod.load()
    tts = TTS(cfg.piper_exe, cfg.piper_voice)
    brain = Brain(model=cfg.claude_model)
    stt = STT(cfg.groq_api_key)
    vad = VAD()
    sp = _init_spotify(cfg)
    memory = Memory(cfg.paths.memory_dir, cfg.paths.facts)

    scheduler = AlarmScheduler(cfg.paths.alarms_json, speak=tts.speak)
    await scheduler.start()

    tool_state.init(
        cfg=cfg,
        speak=tts.speak,
        spotify=sp,
        scheduler=scheduler,
        memory=memory,
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
                    session_loop(cfg, brain, stt, vad, tts, memory, session),
                    timeout=cfg.silence_timeout_s,
                )
            except asyncio.TimeoutError:
                tts.speak("Closing out, boss.")
                session.state = State.IDLE
            await summarise_session(brain, memory, session)
    finally:
        scheduler.sched.shutdown(wait=False)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 2:** Run and exercise the memory path.

```bash
.venv/Scripts/python friday.py
```

Session 1:

- Say "Friday, remember my favourite artist is Bowie."
- Say "thanks Friday" to close.

After "Done, boss." FRIDAY asks Claude to summarise and writes to `~/friday/memory/<today>.md`. Verify the file exists and contains bullet points.

Session 2 (without restart or with restart — either works):

- Say "Friday, who's my favourite artist?" → FRIDAY answers "Bowie" (from `facts.md`).
- Say "Friday, what did we talk about earlier today?" → FRIDAY references the prior session summary.

- [ ] **Step 3:** Commit.

```bash
git add friday.py
git commit -m "feat(memory): inject 7-day window + summarise on close"
```

### Task 6.6: Write a short `README.md`

**Files:**
- Create: `README.md`

- [ ] **Step 1:** Write a minimal README (full version ships in deferred Phase 7).

```markdown
# FRIDAY

Personal home voice assistant. Wake word "Friday", Groq Whisper STT, Claude Sonnet 4.6 via the Claude Agent SDK, Piper TTS.

**Status:** Windows-laptop beta. Raspberry Pi 5 deployment deferred to a later plan.

## Quick start

1. Fill `config/.env` from `config/.env.example`.
2. Drop `voices/friday.ppn` (Porcupine custom keyword) and the Piper voice files.
3. `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`.
4. `claude login` (uses your Claude Max subscription).
5. `python friday.py`.

## Design spec

See `docs/specs/2026-04-18-friday-design.md`.

## Implementation plan

See `docs/plans/2026-04-18-friday-mvp.md`.

## Data on disk

All runtime state lives under `~/friday/`:

- `notes.md` — dictated notes
- `today.md` — user-written daily briefing (FRIDAY reads this aloud on request)
- `memory/YYYY-MM-DD.md` — per-day session summaries
- `memory/facts.md` — standing facts (`key: value` per line)
- `alarms.json` — active alarms, survives restart
- `logs/friday.log` — runtime log
```

- [ ] **Step 2:** Commit.

```bash
git add README.md
git commit -m "docs: minimal readme for windows beta"
```

---

## REVIEW CHECKPOINT — Phase 6

**Stop. Manually verify before continuing.**

- [ ] After saying "remember X is Y", `~/friday/memory/facts.md` gains a `X: Y` line.
- [ ] On session close, a summary appears in `~/friday/memory/YYYY-MM-DD.md` with bullet points.
- [ ] A second session recalls the fact without needing to remind FRIDAY.
- [ ] A second session references the prior session's topic.
- [ ] `.venv/Scripts/python -m pytest -v` — all tests pass across the repo.

When pass, the Windows beta MVP is complete for the scope of this plan.

---

## Self-review

### Spec §2 goals — coverage

| Goal | Covered by |
|---|---|
| Wake word "Friday" triggers always-on listening | Phase 2b (`src/wake.py`, `friday.py` main loop) |
| Voice-initiated Spotify play/pause/resume/skip/volume | Phase 4 Task 4.2 |
| Voice-set alarms; alarm fires + FRIDAY speaks label | Phase 5 Tasks 5.1 and 5.3 |
| Voice dictation appends timestamped notes | Phase 4 Task 4.3 |
| "What's on today" reads `today.md` aloud | Phase 4 Task 4.5 |
| Persistent memory across sessions | Phase 6 Task 6.1 + Task 6.5 |
| FRIDAY personality | Phase 3 Task 3.2 (verbatim spec §8 prompt) |
| English only | Groq call pins `language=en`; Piper voice is `en_GB-alan-medium` |
| Headless systemd auto-start | **Deferred** — spec Phase 7, not in this plan |
| Single-room / single-device | Implicit — no multi-device code path |

### Spec §7 tools — coverage

| Tool | Implementing task |
|---|---|
| `play_spotify` | Task 4.2 |
| `pause_spotify` | Task 4.2 |
| `resume_spotify` | Task 4.2 |
| `skip_track` | Task 4.2 |
| `set_volume` | Task 4.2 (deviation: Spotify client volume, not alsamixer — see Preamble) |
| `write_note` | Task 4.3 |
| `read_briefing` | Task 4.5 |
| `set_alarm` | Task 5.3 |
| `cancel_alarm` | Task 5.3 |
| `list_alarms` | Task 5.3 |
| `remember_fact` | Task 6.3 |
| `get_time` | Task 3.5 |

### Spec §11 phase map

| Spec phase | This plan |
|---|---|
| 1. Pi bootstrap | **Deferred** (separate plan) |
| 2. Wake + STT | Phase 2a (audio I/O) + 2b (wake) + 2c (VAD + STT) |
| 3. Claude brain + personality | Phase 3 + Phase 3.5 (session model) |
| 4. Spotify + notes + briefing | Phase 4 |
| 5. Alarms | Phase 5 |
| 6. Memory layer | Phase 6 |
| 7. Systemd + polish | **Deferred** (separate plan) |
| 8. Field test | **Deferred** (separate plan) |

### Deviations called out

- `set_volume` uses `spotipy.Spotify.volume()` instead of alsamixer (Linux-only). Revisit on Pi if OS-level volume control is needed.
- Wake word triggers an **active session** (multi-turn), not a single turn, per session model confirmed with user. Close phrase or 5-min silence timeout ends the session.
- `claude-agent-sdk` + Claude Max subscription (`claude login`) used instead of raw Anthropic API — reduces running cost to zero for personal use within TOS.
- `faster-whisper` local fallback is lazy-loaded on first STT failure, so the import overhead only happens when actually needed.

### Placeholder scan

- No "TBD", "TODO", or "implement similar to" strings in any code block.
- Every task's steps include complete code, exact commands, and expected output.
- `src/tools/__init__.py` is rewritten in full at Tasks 3.7, 4.6, 5.4, 6.4 — the engineer doesn't need to diff; each version is self-contained.
- `friday.py` is rewritten in full at Tasks 3.9, 3.5.3, 4.7, 5.5, 6.5 — same reason.

### Type/name consistency

- `AlarmScheduler` exposes `.set(when, label)`, `.cancel(id)`, `.list()`, `.start()`, `._persist()`, `.sched` (the APScheduler). Used consistently by alarm_tool and friday.py.
- `Memory` exposes `.append_summary(summary, when=None)`, `.last_7_days(now=None)`, `.read_facts()`, `.append_fact(key, value)`. Used by friday.py and memory_tool.
- `ToolState` fields: `cfg`, `scheduler`, `spotify`, `speak`, `memory`. Set by `tool_state.init(...)` in `friday.py`; read via `tool_state.get()` in every tool module.
- Config field names (`picovoice_access_key`, `porcupine_keyword_path`, `piper_exe`, `piper_voice`, `groq_api_key`, `spotify_client_id`, etc.) are the same across `config.py`, `friday.py`, and smoke scripts.
- Tool name format is `mcp__friday__<tool_name>` everywhere.

---

## Execution handoff

Plan complete and saved to `docs/plans/2026-04-18-friday-mvp.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?

