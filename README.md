# FRIDAY

Personal home voice assistant. Wake word "Hey Jarvis" (OpenWakeWord), Groq Whisper STT, Claude Sonnet 4.6 via the Claude Agent SDK, Piper TTS.

**Status:** Windows-laptop beta. Raspberry Pi 5 deployment deferred to a later plan.

## Quick start

1. Fill `config/.env` from `config/.env.example`.
2. Place Piper binary (`piper/piper.exe` + DLLs) and voice (`voices/en_GB-alan-medium.onnx` + `.json`).
3. `python -m venv .venv` then `.venv/Scripts/python -m pip install -r requirements.txt`.
4. `claude login` (uses your Claude Max subscription).
5. `.venv/Scripts/python -c "import openwakeword.utils; openwakeword.utils.download_models()"` (one-time).
6. `.venv/Scripts/python friday.py`.

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
