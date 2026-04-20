"""Shared state for MCP tool handlers.

The ``@tool`` decorator from claude_agent_sdk registers handlers into an
out-of-process MCP server; closures over local variables do not survive the
registration boundary. Instead, the main loop calls :func:`init` at startup
to populate the singleton, and every handler calls :func:`get` to read it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class ToolState:
    cfg: Any = None
    scheduler: Any = None
    spotify: Any = None
    speak: Optional[Callable[[str], None]] = None
    memory: Any = None
    research: Any = None
    worker_manager: Any = None


_state = ToolState()


def init(
    cfg: Any = None,
    scheduler: Any = None,
    spotify: Any = None,
    speak: Optional[Callable[[str], None]] = None,
    memory: Any = None,
    research: Any = None,
    worker_manager: Any = None,
) -> None:
    _state.cfg = cfg
    _state.scheduler = scheduler
    _state.spotify = spotify
    _state.speak = speak
    _state.memory = memory
    _state.research = research
    _state.worker_manager = worker_manager


def get() -> ToolState:
    return _state


def reset() -> None:
    _state.cfg = None
    _state.scheduler = None
    _state.spotify = None
    _state.speak = None
    _state.memory = None
    _state.research = None
    _state.worker_manager = None
