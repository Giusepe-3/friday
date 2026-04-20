"""Model + effort name resolution.

Voice phrasings ("opus", "sonnet") expand to full Anthropic model IDs.
Effort levels are constrained to the four CLI-supported values.
"""

from __future__ import annotations

MODEL_ALIASES: dict[str, str] = {
    "opus": "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}

EFFORT_LEVELS: set[str] = {"low", "medium", "high", "max"}


def resolve_model(name: str) -> str:
    """Return canonical model ID. Accept either full ID or short alias."""
    if not name:
        raise ValueError("model name required")
    norm = name.lower()
    if norm in MODEL_ALIASES:
        return MODEL_ALIASES[norm]
    # Full IDs we know of pass through unchanged
    known_full = set(MODEL_ALIASES.values())
    if name in known_full:
        return name
    # Permissive: any well-formed Anthropic-style ID passes through
    if name.startswith("claude-"):
        return name
    raise ValueError(f"unknown model: {name!r}")


def resolve_effort(level: str) -> str:
    """Return canonical effort level. Reject anything outside EFFORT_LEVELS."""
    if not level:
        raise ValueError("effort level required")
    norm = level.lower()
    if norm not in EFFORT_LEVELS:
        raise ValueError(f"unknown effort: {level!r}, expected one of {sorted(EFFORT_LEVELS)}")
    return norm
