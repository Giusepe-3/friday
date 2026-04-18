# FRIDAY — Home Voice Assistant Design

**Date:** 2026-04-18
**Status:** Draft, pending user review
**Target ship:** MVP in one long session (~5–8h active build, excluding hardware shipping wait)

---

## 1. Overview

FRIDAY is a voice-only home assistant running on a Raspberry Pi 5 in a single room. It listens for the wake word "Friday", transcribes speech, routes the request through Claude Sonnet 4.6 with tool use, and responds via neural TTS on a local speaker. Personality modelled on Marvel's FRIDAY: dry, efficient, calls the user "boss" or "sir", English only. State — including long-term memory across conversations — persists in markdown files on the Pi.

The assistant ships four capabilities at v1: (1) voice-triggered Spotify playback, (2) voice-set alarms, (3) dictated note-taking to a markdown file, (4) voice-read daily briefing from a markdown file. A persistent memory layer means FRIDAY remembers facts and prior conversations across days.

---

## 2. Goals & Non-Goals

### Goals (v1)

- Wake word "Friday" triggers always-on listening
- Voice-initiated Spotify playback, pause, resume, skip, volume
- Voice-set alarms with spoken label; alarm fires and FRIDAY speaks the label
- Voice dictation appends timestamped notes to `~/friday/notes.md`
- "Friday, what's on today?" → reads `~/friday/today.md` aloud
- Persistent memory across sessions (facts + conversation summaries)
- FRIDAY personality — dry, efficient, "boss/sir"
- English only
- Runs headless as a systemd service, auto-starts on boot
- Single-room, single-device

### Non-Goals (v1)

- Multi-room / multi-device sync
- Smart-home control (lights, thermostat, etc.)
- Messaging (text, WhatsApp, voice messages)
- Morning wake-up music on a schedule (voice-triggered only; alarms can play sounds)
- Italian or bilingual support
- Visual UI of any kind (no screen, no app)
- Voice cloning of actual Kerry Condon (dropped in favour of Piper's stock voice)
- On-device LLM (brain is Claude API; all other components local)
- Automatic calendar sync (user writes `today.md` manually — calendar integration deferred)

---

## 3. Hardware

| Item | Suggested | Notes |
|---|---|---|
| SBC | Raspberry Pi 5 8GB | 4GB also fine; 8GB gives headroom |
| Case | Official Pi 5 Active Cooler case | Fan matters for always-on |
| SD card | 32GB+ A2-rated SanDisk Extreme | Slow cards = painful boot + Piper load |
| Power supply | Official Pi 5 27W USB-C PSU | Cheap PSUs cause undervoltage |
| USB microphone | Jabra Speak 410, ReSpeaker 2-Mic HAT, or MiniDSP UMA-8 | Needs decent far-field pickup; cheapest viable: any USB conference mic |
| Speaker | Any 3.5mm / USB speaker ≥3W | Jabra Speak doubles as mic + speaker — simplest |
| Network | 2.4GHz WiFi or ethernet | API calls need stable connection |
| Total hardware cost | ~$130–$200 one-time | Jabra Speak 410 used ≈ $40 and covers mic+speaker |

**Recommendation:** start with a Jabra Speak 410 (USB speakerphone, combined mic+speaker, noise-suppressed, plug-and-play). Eliminates driver headaches.

---

## 4. Stack

| Layer | Choice | Reason |
|---|---|---|
| Wake word | Picovoice Porcupine | "Friday" custom keyword, free for personal, ~5% CPU on Pi 5 |
| STT | Groq Whisper Large v3 API | <1s latency, free tier sufficient for personal use |
| LLM brain | Claude Sonnet 4.6 via Anthropic API | Native tool use, good personality, prompt caching for memory |
| TTS | Piper — `en_GB-alan-medium` (default) | Runs locally on Pi 5, ~200ms latency, offline |
| Scheduler | APScheduler (Python) | In-process alarm scheduling |
| Music | Spotify Web API via `spotipy` | Requires Premium for playback control |
| Persistence | Flat markdown + JSON files | No database — simple, greppable, user-editable |
| Process supervisor | systemd unit | Auto-start on boot, auto-restart on crash |
| Async runtime | Python 3.11 `asyncio` | Single event loop for all I/O |

---

## 5. Architecture — Monolithic Async

A single Python process on the Pi runs all components in one `asyncio` event loop. Modules are separate files but share process state. Systemd auto-restarts the service if it crashes.

### 5.1 Main loop flow

```
[always running]
Porcupine listens for "Friday" on mic input stream
    │
    ▼ (wake detected)
Start recording audio until VAD (voice activity detection) reports end of speech, max 15s
    │
    ▼
Send audio to Groq Whisper Large v3 → transcript (en)
    │
    ▼
Build messages = [system prompt, memory summary, conversation turn, user transcript]
    │
    ▼
Claude Sonnet 4.6 with tool schema
    │
    ▼
Response contains tool_use blocks?
    ├── yes → execute tools locally → append tool_result → loop back to Claude
    └── no  → final text response
    │
    ▼
Piper TTS synth → aplay → speaker
    │
    ▼
Append turn to conversation buffer + trigger memory write if session-end
    │
    ▼ (silence >2 min or explicit "goodbye")
Summarize session via Claude → append to ~/friday/memory/YYYY-MM-DD.md
Return to wake-word listening
```

### 5.2 Module boundaries

```
friday/
├─ friday.py                  # entrypoint, event loop wiring
├─ src/
│  ├─ wake.py                 # Porcupine stream consumer, emits WakeEvent
│  ├─ stt.py                  # Groq Whisper API client, handles audio buffer → text
│  ├─ vad.py                  # Voice activity detection (WebRTC VAD or Silero)
│  ├─ brain.py                # Claude API client, tool-call loop, message builder
│  ├─ tts.py                  # Piper binary wrapper, returns WAV → aplay
│  ├─ memory.py               # Read/write memory files, session summarization
│  ├─ scheduler.py            # APScheduler bootstrap, alarm persistence
│  ├─ personality.py          # FRIDAY system prompt + conversation framing
│  └─ tools/
│     ├─ __init__.py          # tool registry (name → schema + handler)
│     ├─ spotify_tool.py      # play/pause/resume/skip/volume via spotipy
│     ├─ notes_tool.py        # append_note(content)
│     ├─ briefing_tool.py     # read_briefing()
│     ├─ alarm_tool.py        # set_alarm / cancel_alarm / list_alarms
│     ├─ memory_tool.py       # remember_fact / recall_fact
│     └─ util_tool.py         # get_time / set_volume
├─ config/
│  ├─ friday.yaml             # non-secret config
│  └─ .env                    # API keys (gitignored)
├─ voices/
│  └─ en_GB-alan-medium.onnx  # Piper voice model
├─ requirements.txt
├─ systemd/
│  └─ friday.service
├─ README.md
└─ docs/
   └─ specs/2026-04-18-friday-design.md
```

Each module has one clear purpose: `wake.py` produces wake events, `stt.py` converts audio to text, `brain.py` runs the Claude loop, and so on. Tools in `src/tools/` are independently testable Python functions — each exposes a `schema` dict (Claude tool schema) and a `handler(async)` coroutine. Registry pattern: tools self-register by import order; `brain.py` reads the registry and passes the schema to Claude.

### 5.3 State surfaces

| File | Purpose | Format |
|---|---|---|
| `~/friday/notes.md` | Dictated notes, timestamped append-only | Markdown |
| `~/friday/today.md` | User-written daily briefing (user edits manually) | Markdown |
| `~/friday/memory/YYYY-MM-DD.md` | Daily conversation summaries | Markdown |
| `~/friday/memory/facts.md` | Standing facts FRIDAY has been told to remember | Markdown, key:value per line |
| `~/friday/alarms.json` | Active alarms (persisted so survive restart) | JSON |
| `~/friday/conversation.jsonl` | Raw conversation buffer (last 24h) | JSON Lines |
| `~/friday/logs/friday.log` | Runtime log | Text |

---

## 6. Conversation & Memory

Persistent memory is the design's biggest nuance. Three surfaces:

### 6.1 Short-term (same session)

Claude receives the full current session (last N turns, bounded by token budget). Session ends after 2 min silence or explicit "goodbye, Friday".

### 6.2 Medium-term (recent days)

After each session ends, Claude summarizes the session via a single API call: *"Summarize this conversation in 3–5 bullet points: decisions made, facts learned, requests pending."* Summary appends to `~/friday/memory/YYYY-MM-DD.md`.

Each new session's system prompt includes the **last 7 days** of summaries verbatim. Uses prompt caching so the memory block is a cache hit 99% of the time (cheap + fast).

### 6.3 Long-term (facts)

Separate `facts.md` file. When the user says "remember X" or when FRIDAY detects a durable fact ("my sister's birthday is Oct 12"), the `remember_fact(key, value)` tool writes to this file. `facts.md` is loaded into **every** session's system prompt (also cached).

### 6.4 Overflow strategy

When memory files grow past ~20k tokens, run a compaction job: Claude re-summarizes older entries into denser form. Runs weekly via APScheduler. V1: just grow; revisit at 1–3 months.

### 6.5 What is NOT stored

- No raw audio recorded to disk.
- No STT transcripts kept beyond the session buffer (deleted after summarization).
- API keys never go into memory files.

---

## 7. Tools Exposed to Claude

Each tool has a JSON schema (Claude tool-use format) and an async handler.

| Tool | Signature | Behaviour |
|---|---|---|
| `play_spotify` | `(query: str)` | Search Spotify, play top result on active device. Returns track name. |
| `pause_spotify` | `()` | Pause current playback. |
| `resume_spotify` | `()` | Resume playback. |
| `skip_track` | `()` | Next track. |
| `set_volume` | `(level: int 0-100)` | Adjust system volume (alsamixer wrapper). |
| `write_note` | `(content: str)` | Append `- [HH:MM] content` to `~/friday/notes.md`. |
| `read_briefing` | `()` | Return text of `~/friday/today.md`. FRIDAY reads it back. |
| `set_alarm` | `(time: str ISO8601, label: str)` | Schedule APScheduler job; persist to `alarms.json`. |
| `cancel_alarm` | `(id: str)` | Remove scheduled job + persisted entry. |
| `list_alarms` | `()` | Return upcoming alarms. |
| `remember_fact` | `(key: str, value: str)` | Append to `facts.md`. |
| `get_time` | `()` | Return current local time ISO8601. |

When an alarm fires, the callback triggers a synthesized speech line via Piper directly (bypassing Claude): *"Boss — [label]."* and plays a short chime. No Claude round-trip needed; alarms are dumb and reliable.

---

## 8. Personality System Prompt

```
You are FRIDAY, a home voice assistant modelled on the Marvel AI of the same name.

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

Current date: {injected_date}
Recent memory (last 7 days of summaries): {injected_memory}
Standing facts about the user: {injected_facts}
```

---

## 9. Error Handling

| Failure | Behaviour |
|---|---|
| Groq API down | Fall back to local `faster-whisper` tiny model (pre-installed); speak "Cloud's down, boss — running local." |
| Claude API down | Speak "Brain's offline. Try again in a bit." Log incident. No retry storm. |
| Spotify API error | Surface error text to Claude as tool_result; Claude tells user (e.g., "No active device."). |
| Piper voice file missing | Fall back to `espeak` at startup with warning logged. |
| Microphone disconnected | Systemd restarts service; on restart failure loop, log and stop. |
| Porcupine license expired | Log, keep running in push-to-talk mode via a GPIO button (future). |
| Disk full | Rotate logs, warn user aloud. |
| Network fully offline | Speak "No network. Alarms still work." Continue listening; retry APIs on next wake. |

All errors log to `~/friday/logs/friday.log` with ISO timestamps.

---

## 10. Security & Privacy

- API keys live in `config/.env`, never committed.
- Pi-side filesystem permissions: `~/friday/` is `700`; logs `600`.
- No audio written to disk at any point.
- STT transcripts deleted after session summarization.
- User has one-command wipe: `rm -rf ~/friday/memory/` removes all memory.
- Outbound traffic: Anthropic API, Groq API, Spotify API, Picovoice (wake init only). Pin these domains in a README "data leaves device" section.

---

## 11. Milestones — MVP Build Sequence

Targets assume hardware is already on hand. If hardware is shipping, do Phases 1 & 7 last.

| Phase | Duration | Deliverable |
|---|---|---|
| 1. Pi bootstrap | 60 min | Raspberry Pi OS Lite 64-bit flashed, SSH enabled, Python 3.11, PortAudio, Piper binary, `faster-whisper` tiny model (fallback) installed. Speaker says "Hello boss" via Piper from CLI. |
| 2. Wake + STT | 60 min | Porcupine listens for "Friday". On wake, records 5s, sends to Groq, prints transcript. |
| 3. Claude brain + personality | 60 min | Prompt → Claude → text response → Piper speaks it. Personality feels right. `get_time` tool works end-to-end. |
| 4. Spotify + notes + briefing tools | 90 min | Three domain tools wired. Can say "play Bowie", "take a note: buy coffee", "what's on today". |
| 5. Alarms + APScheduler | 60 min | Set, list, cancel alarms by voice. Alarm fires and FRIDAY speaks label. Survives restart. |
| 6. Memory layer | 75 min | Session end triggers summary. Summary appended. Next session loads last 7 days into system prompt. `remember_fact` works. |
| 7. Systemd + polish | 45 min | `friday.service` enabled, auto-starts on boot, auto-restarts on crash. Logging rotated. README written. |
| 8. Field test | open-ended | Run for a day. Fix whatever breaks. |

**Total active build: ~7.5h** (plus test time). If pinched for time in one session, Phase 6 (memory) can defer to v1.1.

---

## 12. Cost Estimate

### One-time
- Hardware (Pi 5 8GB + case + PSU + SD + USB speakerphone): **≈ $150**

### Recurring
- Anthropic Claude API (Sonnet 4.6, with prompt caching): estimate **$2–5/month** for personal use.
- Groq Whisper API: free tier likely sufficient (100k tokens/day-ish). **$0/month** unless heavy usage.
- Picovoice Porcupine: free for personal non-commercial use. **$0**.
- Spotify Premium: **$10/month** (required for playback control). Skip if you already have it.
- Electricity (Pi 5 24/7 at ~5W avg): **≈ $0.50/month**.

**Total running cost: ~$3–16/month** depending on Spotify.

---

## 13. Open Questions / Deferred

Not blocking v1. Capture here to avoid forgetting.

- **Push-to-talk backup** — add a GPIO button in case wake word misfires in a noisy room.
- **Multi-user voice ID** — not needed for one person; add if FRIDAY moves to a shared space.
- **Calendar sync** — auto-populate `today.md` from Google Calendar. Worth ~2h work post-MVP.
- **Phone push notifications** — "Boss, you have an alarm in 5 min" sent to phone. Needs a push service (ntfy.sh is free and simple).
- **Morning schedule** — user wanted scheduled morning music as original idea, dropped for v1. Revisit once alarms are solid; trivial to add as a cron-like entry.
- **Compaction job** — weekly memory summarization. Defer until memory files grow past 20k tokens.
- **Italian support** — deferred; Whisper handles it, Piper has Italian voices, Claude speaks it. Tech is ready; just scope punt.

---

## 14. Success Criteria

v1 ships when all of the following hold for a full 24h:

1. Wake word reliably triggers from across a small room (~3m).
2. "Friday, play [artist/track]" starts Spotify within 3s of end-of-speech.
3. "Friday, set an alarm for 7:30" creates an alarm; the alarm fires on time; FRIDAY speaks the label.
4. "Friday, take a note: [text]" appends to `notes.md` with correct timestamp.
5. "Friday, what's on today?" reads `today.md` aloud.
6. Session ends trigger memory summarization; next session reflects the prior one ("earlier you asked me to...").
7. `remember_fact` works — next day FRIDAY recalls the fact.
8. Service auto-restarts after crash or reboot.
9. Personality feels like FRIDAY and not a generic assistant.

---

## 15. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Far-field mic pickup is poor | Medium | Buy Jabra Speak 410 up front; has beamforming + echo cancel. |
| Piper voice sounds too robotic, kills vibe | Medium | Try 2–3 Piper voices during Phase 1; if none work, switch to ElevenLabs cloud voice-clone for ~$5/mo. |
| Groq free tier rate-limits | Low | Fall back to local `faster-whisper tiny`. |
| Memory file grows and blows token budget | Low (not for months) | Weekly compaction job. Deferred until needed. |
| Wake word false-positives from TV dialogue | Medium | Porcupine's sensitivity tunable; if bad, add simple "only active if FRIDAY not currently speaking" gate. |
| User loses interest once built | High 🙂 | Ship it working, stop there. Don't over-engineer. |

---

## 16. Definition of Done

Spec is approved by user → writing-plans skill generates a step-by-step implementation plan keyed to the 8 milestones in §11 → implementation proceeds phase by phase with review checkpoints.
