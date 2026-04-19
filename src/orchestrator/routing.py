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
    norm_words = norm.split()
    for project, w in workers_cfg.items():
        for alias in w.get("aliases", []):
            alias_norm = normalize(alias)
            alias_words = alias_norm.split()
            # Check if all words of the alias appear in the text (in order, but not necessarily consecutive)
            if alias_words and all(word in norm_words for word in alias_words):
                return project
    return None
