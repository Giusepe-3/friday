# FRIDAY

A voice-first personal assistant that runs on my own laptop. Wake word, speech to text, a Claude Agent SDK brain with its own tool set, then speech back out. On top of that loop sit two subsystems that make it more than a smart speaker: an orchestrator that runs coding agents inside my own repos, and a research assistant with scheduled jobs and a paper fetcher.

Pure Python. No web framework, no app server, no cloud state. Around 163 pytest tests cover the parts that are worth covering.

**Status:** working beta on a Windows laptop. The Raspberry Pi 5 deployment is deferred.

---

## The voice loop

```
  mic ──► wake word ──► VAD ──► STT ──► brain (Claude Agent SDK + tools) ──► TTS ──► speakers
           OpenWakeWord   webrtcvad   Groq Whisper        MCP tool servers        Coqui XTTS v2
           "hey jarvis"               (local fallback)
```

1. `src/wake.py` listens continuously for the wake word with OpenWakeWord.
2. `src/vad.py` decides when I have stopped talking, so there is no fixed record length.
3. `src/stt.py` transcribes with Groq Whisper Large v3 and falls back to a local faster-whisper tiny model when the API is unreachable.
4. `src/brain.py` wraps the Claude Agent SDK. Tools are exposed as in-process MCP servers built in `src/tools/__init__.py`.
5. `src/tts.py` speaks the reply through Coqui XTTS v2, with playback gain and a time-stretch factor applied so replies come back faster than natural speech.
6. `src/session.py` is the state machine for an open conversation: it keeps the mic live after a reply, re-arms silently after a silence timeout, and closes on a configured phrase.

`CLAUDE.md` is the persona file and doubles as the system prompt. The hard rule in it is one sentence per reply, because everything is heard rather than read. `src/personality.py` enforces the parts that can be checked in code.

## Tools the assistant can call

| Tool module | What it does |
|---|---|
| `tools/alarm_tool.py` | Set, list and cancel alarms. Natural language times via dateparser. Alarms survive a restart. |
| `tools/notes_tool.py` | Append-only dictation notes with `HH:MM` stamps. |
| `tools/briefing_tool.py` | Reads the day's briefing file aloud. |
| `tools/memory_tool.py` | Writes standing facts to a flat key-value file. |
| `tools/spotify_tool.py` | Playback control through spotipy. |
| `tools/whatsapp_tool.py` | Sends a WhatsApp message by driving WhatsApp Web with Playwright against a bootstrapped browser profile. |
| `tools/util_tool.py` | Clock. |
| `tools/orchestrator_tool.py` | Thin wrappers that let the voice loop start, steer and query coding workers. |

## Orchestrator: coding agents in my own repos

`src/orchestrator/` lets me say "ask the thesis worker to rerun the ASHA pilot" and have a separate agent do it inside that repository while the voice loop stays free.

- **Process model.** `manager.py` spawns one worker subprocess per project. Liveness is checked against both the tracked process handle and an on-disk pidfile, so a crash on the assistant side cannot orphan a worker silently.
- **Transport is the filesystem.** `bus.py` defines a small protocol inside each target repo under `.friday/`: request files in, status and result files out, pidfile for liveness. No sockets, no broker, and the whole conversation with a worker is inspectable with `cat` after the fact.
- **Routing by speech.** `routing.py` maps what I actually say to a project using alias substring matching, because "the paper", "draft" and "verification" all mean the same repo.
- **A human checkpoint on risky actions.** `checkpoint_gate.py` builds the `can_use_tool` callback handed to the SDK. Commands matching per-project regexes, for example `^git push`, `runpod` or `wandb init`, are held and surfaced to me for a spoken yes or no before they run. Cost and irreversibility are the two things an autonomous loop should not decide alone.
- **Model and effort resolution** lives in `models.py` so a spoken "use high effort" maps to real SDK options.

## Research mode

`src/research/` is the part that runs without me asking.

- `scheduler.py` registers APScheduler cron jobs from plain config strings such as `09:00` or `SUN 18:00`, and has a first-wake catchup window so a job missed while the laptop was closed still fires once when it opens.
- `fetch.py` fetches and summarises a paper from a URL. It enforces a domain allowlist (arXiv, OpenReview, ACL Anthology, Semantic Scholar, NeurIPS, PMLR), blocks SSRF targets, re-validates every redirect hop, caps the response size, and handles both PDF and HTML.
- `storage.py` does atomic writes for every record type, so an interrupted write cannot leave a half-written note.
- `audit.py` keeps an append-only log of every write a research tool makes.
- `review.py` gathers the last seven days of inputs and asks the brain to synthesise a weekly review.

## Running it

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
# torch and torchaudio need the CUDA wheels:
# pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

cp config/.env.example config/.env      # fill in the keys
claude login                            # the Agent SDK uses the Claude subscription
.venv/Scripts/python -c "import openwakeword.utils; openwakeword.utils.download_models()"
.venv/Scripts/python friday.py
```

`config/friday.yaml` holds models, wake threshold, playback settings, research schedules and the worker project list. The worker repo paths in it are absolute paths on my machine, so change those first if you clone this.

Smoke scripts for each hardware stage live in `scripts/`: `smoke_audio.py`, `smoke_wake.py`, `smoke_stt.py`, `smoke_tts.py`. Run them in that order when the microphone or the voice stops behaving.

## Tests

```bash
pytest
```

Around 163 tests. The heaviest coverage is where the failure modes are quiet rather than loud: the filesystem bus, research storage and the paper fetcher. HTTP is mocked with respx, async paths with pytest-asyncio, and audio hardware is never touched in the suite.

## Repo map

```
friday.py                  main entry point: voice loop, tools, research schedules, catchup
friday_voice.py            leaner voice shim, one long-lived SDK client per session
src/
  wake.py vad.py stt.py tts.py audio.py    the audio pipeline
  brain.py personality.py session.py       the conversation
  memory.py                                persistent facts and daily summaries
  tools/                                   MCP tool servers
  orchestrator/                            worker processes, filesystem bus, checkpoint gate
  research/                                schedules, paper fetch, storage, audit, review
config/friday.yaml                         all runtime configuration
scripts/                                   hardware smoke tests and bootstrapping
tests/                                     pytest suite
```

## Runtime state

Everything the assistant remembers is plain text under `~/friday/`: dictated notes, the daily briefing, per-day session summaries, standing facts, active alarms and the runtime log. Nothing is stored in a database, so any of it can be read or edited by hand.

## Honest limits

- Windows laptop only at the moment. Paths and the Piper and XTTS binaries are not abstracted for Linux.
- One user, one microphone. No speaker identification.
- The WhatsApp tool drives the web client through a real browser profile, so it breaks whenever that UI changes.
- Worker projects are configured by hand in YAML rather than discovered.
