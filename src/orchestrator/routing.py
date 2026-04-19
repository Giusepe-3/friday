"""Project routing by alias substring match.

Returns project key on first hit (insertion order of workers_cfg). Returns
None on no match — caller (FRIDAY's persona) decides whether to ask the
user or LLM-route from broader context.
"""

from __future__ import annotations

import re

_NORM = re.compile(r"[a-z']+")


def normalize(s: str) -> str:
    """Lowercase, keep [a-z'] runs, single-space joined."""
    return " ".join(_NORM.findall(s.lower()))


def route(text: str, workers_cfg: dict) -> str | None:
    """Return project key on first alias substring hit. None if no alias matches."""
    norm = normalize(text)
    for project, w in workers_cfg.items():
        for alias in w.get("aliases", []):
            alias_norm = normalize(alias)
            if alias_norm and alias_norm in norm:
                return project
    return None
