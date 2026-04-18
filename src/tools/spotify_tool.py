"""Spotify playback tools.

All handlers reach the shared ``spotipy.Spotify`` client through
``tool_state.get().spotify``. If no client is registered (user opted out or
Spotify init failed), handlers return a clear error message Claude can
surface to the user."""

from __future__ import annotations

from claude_agent_sdk import tool

from .state import get


def _require_sp():
    sp = get().spotify
    if sp is None:
        return None, {"content": [{"type": "text", "text": "spotify not configured"}]}
    return sp, None


@tool(
    "play_spotify",
    "Search Spotify and start playback of the top result on the active device.",
    {"query": str},
)
async def play_spotify(args):
    sp, err = _require_sp()
    if err:
        return err
    results = sp.search(q=args["query"], type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return {"content": [{"type": "text", "text": "no match"}]}
    track = items[0]
    sp.start_playback(uris=[track["uri"]])
    artist = track["artists"][0]["name"] if track.get("artists") else "?"
    return {
        "content": [
            {"type": "text", "text": f"playing {track['name']} by {artist}"}
        ]
    }


@tool("pause_spotify", "Pause Spotify playback.", {})
async def pause_spotify(_args):
    sp, err = _require_sp()
    if err:
        return err
    sp.pause_playback()
    return {"content": [{"type": "text", "text": "paused"}]}


@tool("resume_spotify", "Resume Spotify playback.", {})
async def resume_spotify(_args):
    sp, err = _require_sp()
    if err:
        return err
    sp.start_playback()
    return {"content": [{"type": "text", "text": "resumed"}]}


@tool("skip_track", "Skip to the next track on Spotify.", {})
async def skip_track(_args):
    sp, err = _require_sp()
    if err:
        return err
    sp.next_track()
    return {"content": [{"type": "text", "text": "skipped"}]}


@tool(
    "set_volume",
    "Set the Spotify client volume (0-100).",
    {"level": int},
)
async def set_volume(args):
    sp, err = _require_sp()
    if err:
        return err
    level = max(0, min(100, int(args["level"])))
    sp.volume(level)
    return {"content": [{"type": "text", "text": f"volume {level}"}]}
