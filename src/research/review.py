"""Weekly research review — gathers last-7-days inputs, asks Brain to synthesise."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


_REVIEW_PROMPT = """You are preparing a weekly research review for boss.

The inputs below are the last 7 days of captured notes, summarised papers, standup entries, and prediction outcomes.

Write a crisp review with these exact section headings, in markdown:

## Threads emerging
(2-4 bullets. Name threads in 3-8 words each, one-sentence gloss.)

## Gaps
(2-3 bullets. What important question did boss NOT engage with this week?)

## Suggested focus next week
(2-3 bullets. Specific, actionable.)

## Raw inputs reviewed
(machine-generated list of files — will be appended after your output.)

Be terse. No preamble. No "here is the review". Start directly at "## Threads emerging".
"""


def _collect_inputs(storage, now: datetime | None = None) -> str:
    now = now or datetime.now()
    parts: list[str] = []
    cutoff = now - timedelta(days=7)
    parts.append("=== NOTES (last 7 days) ===")
    for md in sorted(storage.notes_dir.glob("*.md")):
        body = md.read_text(encoding="utf-8")
        parts.append(f"\n--- {md.name} ---\n{body}")
    parts.append("\n=== STANDUPS (last 7 days) ===")
    for i in range(7):
        d = (now - timedelta(days=i)).date().isoformat()
        path = storage.standups_dir / f"{d}.md"
        if path.exists():
            parts.append(f"\n--- {path.name} ---\n{path.read_text(encoding='utf-8')}")
    parts.append("\n=== SUMMARIES (last 7 days) ===")
    for md in sorted(storage.summaries_dir.glob("*.md")):
        if md.stat().st_mtime > cutoff.timestamp():
            parts.append(f"\n--- {md.name} ---\n{md.read_text(encoding='utf-8')[:2000]}")
    parts.append("\n=== PREDICTIONS (resolved this week) ===")
    for p in storage._read_predictions():
        if p["resolved_at"] and p["resolved_at"] >= cutoff.strftime("%Y-%m-%dT%H:%M"):
            parts.append(f"- {p['id']} conf={p['confidence']} outcome={p['outcome']} claim={p['claim']}")
    return "\n".join(parts)


def _input_inventory(storage) -> str:
    notes = sorted(storage.notes_dir.glob("*.md"))
    summaries = sorted(storage.summaries_dir.glob("*.md"))
    standups = sorted(storage.standups_dir.glob("*.md"))
    brier = storage.brier_score()
    lines = []
    for md in notes:
        idx = storage._read_index().get(md.stem, {})
        count = idx.get("note_count", "?")
        lines.append(f"- {md.name} ({count} entries)")
    for md in standups:
        lines.append(f"- standups/{md.name}")
    for md in summaries:
        lines.append(f"- summaries/{md.name}")
    if brier is not None:
        lines.append(f"- predictions.json (brier {brier:.3f} across resolved history)")
    return "\n".join(lines) if lines else "(none)"


async def generate_weekly_review(storage, brain) -> tuple[str, Path]:
    """Return (body, path). `brain` is a Brain instance. Writes file; returns path."""
    inputs = _collect_inputs(storage)
    user_text = f"INPUTS:\n\n{inputs}"
    reply = await brain.ask_oneshot(user_text, _REVIEW_PROMPT)
    inventory = _input_inventory(storage)
    full_body = f"{reply}\n\n## Raw inputs reviewed\n{inventory}\n"
    path = storage.write_review(full_body)
    return full_body, path
