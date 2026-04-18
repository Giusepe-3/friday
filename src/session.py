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
