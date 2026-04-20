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
class WorkerConfig:
    project: str
    repo: Path
    aliases: list[str]
    default_model: str
    default_effort: str
    autostart: bool
    pulse_interval_working_s: int
    pulse_interval_idle_s: int
    bash_regex: list[str]  # extracted from checkpoint_triggers.bash_regex


@dataclass(frozen=True)
class Config:
    paths: Paths
    wake_model: str
    wake_threshold: float
    voice_reference: Path | None
    voice_speaker: str
    voice_language: str
    groq_api_key: str
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    claude_model: str
    shim_model: str
    close_phrases: tuple[str, ...]
    silence_timeout_s: int
    max_recording_s: int
    sample_rate: int
    playback_gain: float
    playback_speed: float
    research_paper_fetch_allowlist: tuple
    research_paper_fetch_max_bytes: int
    research_paper_fetch_timeout_s: int
    research_schedules: dict
    research_catchup_window_h: int
    friday_effort: str
    workers: dict[str, WorkerConfig]


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

    ref_path_raw = data.get("voice_reference")
    ref_path = (repo / ref_path_raw) if ref_path_raw else None

    workers_raw = data.get("workers", {}) or {}
    workers: dict[str, WorkerConfig] = {}
    for project, w in workers_raw.items():
        triggers = w.get("checkpoint_triggers", {}) or {}
        workers[project] = WorkerConfig(
            project=project,
            repo=Path(w["repo"]),
            aliases=list(w.get("aliases", [])),
            default_model=str(w.get("default_model", "claude-opus-4-7")),
            default_effort=str(w.get("default_effort", "high")),
            autostart=bool(w.get("autostart", True)),
            pulse_interval_working_s=int(w.get("pulse_interval_working_s", 30)),
            pulse_interval_idle_s=int(w.get("pulse_interval_idle_s", 300)),
            bash_regex=list(triggers.get("bash_regex", [])),
        )

    _cached = Config(
        paths=paths,
        wake_model=data.get("wake_model", "hey_jarvis"),
        wake_threshold=float(data.get("wake_threshold", 0.5)),
        voice_reference=ref_path,
        voice_speaker=data.get("voice_speaker", "Claribel Dervla"),
        voice_language=data.get("voice_language", "en"),
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        spotify_client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        spotify_redirect_uri=os.environ.get(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback"
        ),
        claude_model=data.get("claude_model", "claude-sonnet-4-6"),
        shim_model=data.get("shim_model", "haiku"),
        close_phrases=tuple(data.get("close_phrases", [])),
        silence_timeout_s=int(data.get("silence_timeout_s", 300)),
        max_recording_s=int(data.get("max_recording_s", 15)),
        sample_rate=int(data.get("sample_rate", 16000)),
        playback_gain=float(data.get("playback_gain", 1.0)),
        playback_speed=float(data.get("playback_speed", 1.0)),
        research_paper_fetch_allowlist=tuple(
            (data.get("research") or {}).get("paper_fetch_allowlist") or []
        ),
        research_paper_fetch_max_bytes=int(
            (data.get("research") or {}).get("paper_fetch_max_bytes", 5_242_880)
        ),
        research_paper_fetch_timeout_s=int(
            (data.get("research") or {}).get("paper_fetch_timeout_s", 30)
        ),
        research_schedules=dict(
            (data.get("research") or {}).get("schedules") or {}
        ),
        research_catchup_window_h=int(
            (data.get("research") or {}).get("catchup_window_h", 12)
        ),
        friday_effort=str(data.get("friday_effort", "max")),
        workers=workers,
    )
    return _cached


def reset_cache() -> None:
    """Test hook — forget the cached config so ``load()`` re-reads."""
    global _cached
    _cached = None
