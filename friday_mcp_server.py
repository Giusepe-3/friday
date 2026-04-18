"""FRIDAY custom tools exposed as an MCP stdio server.

Loaded by Claude Code via ``.mcp.json`` when `claude` is run in this repo.
Wraps the 16 domain-specific Python handlers from ``src/tools/`` and
``src/research/`` using FastMCP. Redundant-with-Claude-Code tools (get_time,
write_note, read_briefing, remember_fact) are dropped — Claude Code uses its
native Read/Write/Bash for those."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP

from src import config as cfg_mod
from src.research.storage import ResearchStorage, arxiv_id_from_ref
from src.research import fetch as fetch_mod
from src.research.review import generate_weekly_review


mcp = FastMCP("friday-tools")

_cfg = None
_research = None


def _init():
    global _cfg, _research
    if _cfg is None:
        _cfg = cfg_mod.load()
        _research = ResearchStorage(_cfg.paths.home / "research")


# ───────────────────── Spotify ─────────────────────

def _sp():
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    _init()
    if not (_cfg.spotify_client_id and _cfg.spotify_client_secret):
        return None
    cache_path = _cfg.paths.home / ".spotipy_cache"
    if not cache_path.exists():
        # No cached token; MCP server must not start an interactive OAuth
        # flow (would hang waiting for browser callback). Bail fast.
        return None
    auth = SpotifyOAuth(
        client_id=_cfg.spotify_client_id,
        client_secret=_cfg.spotify_client_secret,
        redirect_uri=_cfg.spotify_redirect_uri,
        scope="user-modify-playback-state user-read-playback-state",
        cache_path=str(cache_path),
        open_browser=False,
    )
    # Refresh token if expired, but never trigger interactive flow.
    if auth.get_cached_token() is None:
        return None
    return spotipy.Spotify(auth_manager=auth)


def _sp_or_err():
    sp = _sp()
    if sp is None:
        return None, "spotify not configured or OAuth cache missing — run friday.py once interactively to bootstrap"
    return sp, None


@mcp.tool()
def play_spotify(query: str) -> str:
    """Search Spotify and start playback of the top result on the active device."""
    sp, err = _sp_or_err()
    if err:
        return err
    results = sp.search(q=query, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return "no match"
    t = items[0]
    sp.start_playback(uris=[t["uri"]])
    artist = t["artists"][0]["name"] if t.get("artists") else "?"
    return f"playing {t['name']} by {artist}"


@mcp.tool()
def pause_spotify() -> str:
    """Pause Spotify playback."""
    sp, err = _sp_or_err()
    if err:
        return err
    sp.pause_playback()
    return "paused"


@mcp.tool()
def resume_spotify() -> str:
    """Resume Spotify playback."""
    sp, err = _sp_or_err()
    if err:
        return err
    sp.start_playback()
    return "resumed"


@mcp.tool()
def skip_track() -> str:
    """Skip to the next track on Spotify."""
    sp, err = _sp_or_err()
    if err:
        return err
    sp.next_track()
    return "skipped"


@mcp.tool()
def set_volume(level: int) -> str:
    """Set Spotify client volume 0-100."""
    sp, err = _sp_or_err()
    if err:
        return err
    level = max(0, min(100, int(level)))
    sp.volume(level)
    return f"volume {level}"


# ───────────────────── Alarms ─────────────────────
# Alarms require an AsyncIOScheduler. Running one inside an MCP stdio
# server is viable but adds complexity; for this lean server we persist
# to alarms.json and rely on the voice shim's scheduler to fire them.

import json
import uuid
from datetime import datetime


def _alarms_path() -> Path:
    _init()
    return _cfg.paths.alarms_json


def _read_alarms() -> list[dict]:
    p = _alarms_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8") or "[]")
    return []


def _write_alarms(data: list[dict]) -> None:
    p = _alarms_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


@mcp.tool()
def set_alarm(when: str, label: str) -> str:
    """Set an alarm. `when` is natural language ('7:30 tomorrow', 'in 15 minutes'). `label` is spoken at fire time."""
    import dateparser
    dt = dateparser.parse(when, settings={"PREFER_DATES_FROM": "future"})
    if dt is None:
        return f"could not parse time: {when}"
    aid = uuid.uuid4().hex[:8]
    data = _read_alarms()
    data.append({
        "id": aid,
        "when": dt.isoformat(),
        "label": label.strip() or "alarm",
    })
    _write_alarms(data)
    return f"alarm {aid} set for {dt.strftime('%a %H:%M')}: {label}"


@mcp.tool()
def cancel_alarm(id: str) -> str:
    """Cancel an alarm by its id."""
    data = _read_alarms()
    before = len(data)
    data = [a for a in data if a["id"] != id]
    if len(data) == before:
        return "no alarm with that id"
    _write_alarms(data)
    return "cancelled"


@mcp.tool()
def list_alarms() -> str:
    """List all pending alarms."""
    data = _read_alarms()
    if not data:
        return "no alarms"
    data = sorted(data, key=lambda a: a["when"])
    return "\n".join(f"{a['id']}: {a['when']} — {a['label']}" for a in data)


# ───────────────────── Research accelerator ─────────────────────

@mcp.tool()
def note_research(topic: str, content: str) -> str:
    """Capture a research idea or observation into persistent notes under a topic."""
    _init()
    topic = topic.strip()
    content = content.strip()
    if not topic or not content:
        return "empty topic or content, skipped"
    _research.append_note(topic, content)
    from src.research.storage import slugify
    return f"noted: {slugify(topic)}"


@mcp.tool()
def paper_queue_add(ref: str, why: str) -> str:
    """Add a paper to the research reading queue. `ref` = arxiv id, URL, or citation."""
    _init()
    ref = ref.strip()
    if not ref:
        return "empty ref, skipped"
    pid = _research.paper_queue_add(ref, why.strip())
    return f"queued {pid}: {ref}"


@mcp.tool()
def fetch_and_summarize_paper(url: str) -> str:
    """Fetch paper at URL (allowlist + size + timeout capped), return extracted text for Claude to summarise."""
    _init()
    import asyncio
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return "url must start with http:// or https://"
    fc = fetch_mod.FetchConfig(
        allowlist=_cfg.research_paper_fetch_allowlist,
        max_bytes=_cfg.research_paper_fetch_max_bytes,
        timeout_s=_cfg.research_paper_fetch_timeout_s,
    )
    result = asyncio.run(fetch_mod.fetch_and_extract_text(url, fc))
    if not result.ok:
        return f"fetch failed: {result.error}"
    arxiv_id = arxiv_id_from_ref(url) or arxiv_id_from_ref(result.final_url)
    ref_out = f"arxiv:{arxiv_id}" if arxiv_id else url
    pid = _research.paper_queue_add(ref=ref_out, why="auto: fetched for summary")
    stub = _research.write_summary(
        ref=ref_out,
        url=result.final_url or url,
        title="(pending — Claude to fill)",
        body="(paper text fetched; write 3-5 para summary in next turn, call note_research to cross-link)\n\n"
             "## Extracted text (truncated)\n\n" + result.text[:40_000],
    )
    _research.paper_queue_mark_summarised(pid, summary_path=str(stub.relative_to(_research.root)))
    return (
        f"fetched {ref_out} ({result.content_type}, {len(result.text)} chars). "
        f"Stub at {stub.name}. Summary follows — render 3-5 paras, list key claims, cross-link via note_research.\n\n"
        f"EXTRACTED TEXT (truncated to 40k chars):\n\n{result.text[:40_000]}"
    )


@mcp.tool()
def daily_standup(yesterday: str, today: str, blockers: str) -> str:
    """Record Leo's daily standup. Call ONCE with all three fields; ask for missing ones in dialog first."""
    _init()
    yesterday = yesterday.strip()
    today = today.strip()
    blockers = blockers.strip()
    if not (yesterday and today and blockers):
        return "all three fields required; ask user for missing one"
    path = _research.write_standup(yesterday, today, blockers)
    return f"standup recorded: {path.name}"


@mcp.tool()
def log_prediction(claim: str, confidence: int, resolve_by: str) -> str:
    """Log a calibrated prediction. `confidence` 0-100. `resolve_by` natural language."""
    _init()
    import dateparser
    dt = dateparser.parse(resolve_by, settings={"PREFER_DATES_FROM": "future"})
    if dt is None:
        return f"could not parse date: {resolve_by}"
    rb = dt.strftime("%Y-%m-%d")
    pid = _research.log_prediction(claim.strip(), int(confidence), rb)
    return f"logged {pid}: {confidence}% by {rb}"


@mcp.tool()
def check_predictions() -> str:
    """List predictions due for resolution. Narrate each, ask outcome, call resolve_prediction per item."""
    _init()
    due = _research.predictions_due()
    brier = _research.brier_score()
    if not due:
        if brier is None:
            return "no predictions due. (no resolved history yet.)"
        return f"no predictions due. current brier {brier:.3f}."
    lines = [f"{len(due)} due:"]
    for p in due:
        lines.append(f"- {p['id']} ({p['confidence']}%): {p['claim']} [resolve_by {p['resolve_by']}]")
    if brier is not None:
        lines.append(f"current brier: {brier:.3f}")
    return "\n".join(lines)


@mcp.tool()
def resolve_prediction(id: str, outcome: str) -> str:
    """Mark prediction resolved. outcome ∈ {true, false, ambiguous}."""
    _init()
    outcome = outcome.strip().lower()
    try:
        ok = _research.resolve_prediction(id.strip(), outcome)
    except ValueError as e:
        return str(e)
    if not ok:
        return f"could not resolve {id}: not found or already resolved"
    return f"resolved {id} as {outcome}"


@mcp.tool()
def weekly_research_review() -> str:
    """Generate a weekly synthesis from last 7 days of notes + standups + summaries + resolved predictions."""
    _init()
    # weekly_research_review needs a Brain to synthesise. Under Claude Code,
    # we return the gathered inputs and ask Claude (the caller) to write the
    # synthesis in its next turn — then call write_review via a follow-up.
    from src.research.review import _collect_inputs
    inputs = _collect_inputs(_research)
    return (
        "INPUTS FOR WEEKLY REVIEW (last 7 days). Write a review with exactly these "
        "section headings: '## Threads emerging', '## Gaps', '## Suggested focus "
        "next week'. Be terse, no preamble, 2-4 bullets per section. After writing, "
        "use Write tool to save to ~/friday/research/reviews/<today>.md with a leading "
        "'# Weekly review — <today>' line.\n\n"
        f"{inputs}"
    )


if __name__ == "__main__":
    mcp.run()
