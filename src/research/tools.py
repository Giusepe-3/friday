"""Research-mode tool handlers registered with the Claude Agent SDK."""

from __future__ import annotations

from claude_agent_sdk import tool

from src.tools.state import get as state_get
from . import audit as audit_mod


def _require_research():
    storage = state_get().research
    if storage is None:
        return None, {"content": [{"type": "text", "text": "research storage not available"}]}
    return storage, None


@tool(
    "note_research",
    "Capture a research idea, observation, or claim into persistent notes under a topic. "
    "Call this whenever boss voices research content that should be remembered.",
    {"topic": str, "content": str},
)
async def note_research(args):
    storage, err = _require_research()
    if err:
        return err
    topic = args["topic"].strip()
    content = args["content"].strip()
    if not topic or not content:
        return {"content": [{"type": "text", "text": "empty topic or content, skipped"}]}
    storage.append_note(topic, content)
    from src.research.storage import slugify
    slug = slugify(topic)
    audit_mod.audit("note_research", topic=slug, content_bytes=len(content.encode("utf-8")))
    return {"content": [{"type": "text", "text": f"noted: {slug}"}]}


@tool(
    "paper_queue_add",
    "Add a paper to the research reading queue. `ref` accepts arxiv ids "
    "(e.g. arxiv:2410.12345), URLs, or plain citations. `why` records the reason.",
    {"ref": str, "why": str},
)
async def paper_queue_add(args):
    storage, err = _require_research()
    if err:
        return err
    ref = args["ref"].strip()
    why = args["why"].strip()
    if not ref:
        return {"content": [{"type": "text", "text": "empty ref, skipped"}]}
    pid = storage.paper_queue_add(ref, why)
    audit_mod.audit("paper_queue_add", ref=ref)
    return {"content": [{"type": "text", "text": f"queued {pid}: {ref}"}]}


@tool(
    "log_prediction",
    "Log a calibrated prediction for later resolution. `confidence` is 0-100. "
    "`resolve_by` accepts natural language (parsed with dateparser).",
    {"claim": str, "confidence": int, "resolve_by": str},
)
async def log_prediction(args):
    storage, err = _require_research()
    if err:
        return err
    import dateparser
    claim = args["claim"].strip()
    confidence = int(args["confidence"])
    when_str = args["resolve_by"]
    dt = dateparser.parse(when_str, settings={"PREFER_DATES_FROM": "future"})
    if dt is None:
        return {"content": [{"type": "text", "text": f"could not parse date: {when_str}"}]}
    resolve_by = dt.strftime("%Y-%m-%d")
    pid = storage.log_prediction(claim, confidence, resolve_by)
    audit_mod.audit("log_prediction", id=pid, confidence=confidence, resolve_by=resolve_by)
    return {
        "content": [
            {"type": "text", "text": f"logged {pid}: {confidence}% by {resolve_by}"}
        ]
    }


@tool(
    "daily_standup",
    "Record boss's daily standup (yesterday / today / blockers). Call this "
    "ONCE per standup, with all three fields populated. If the user has not "
    "yet spoken all three, ask for the missing one first — do not call this "
    "tool with placeholders.",
    {"yesterday": str, "today": str, "blockers": str},
)
async def daily_standup(args):
    storage, err = _require_research()
    if err:
        return err
    yesterday = args["yesterday"].strip()
    today = args["today"].strip()
    blockers = args["blockers"].strip()
    if not (yesterday and today and blockers):
        return {
            "content": [
                {
                    "type": "text",
                    "text": "all three fields required; ask user for missing one",
                }
            ]
        }
    path = storage.write_standup(yesterday=yesterday, today=today, blockers=blockers)
    audit_mod.audit("daily_standup", path=path.name)
    return {"content": [{"type": "text", "text": f"standup recorded: {path.name}"}]}


@tool(
    "check_predictions",
    "Return the list of predictions due for resolution (resolve_by <= today). "
    "Read-only. After calling this, narrate each due prediction to boss, ask "
    "for outcome (true/false/ambiguous), then call resolve_prediction(id, outcome) per item.",
    {},
)
async def check_predictions(_args):
    storage, err = _require_research()
    if err:
        return err
    due = storage.predictions_due()
    brier = storage.brier_score()
    if not due:
        if brier is None:
            return {"content": [{"type": "text", "text": "no predictions due. (no resolved history yet.)"}]}
        return {"content": [{"type": "text", "text": f"no predictions due. current brier {brier:.3f}."}]}
    lines = [f"{len(due)} due:"]
    for p in due:
        lines.append(f"- {p['id']} ({p['confidence']}%): {p['claim']} [resolve_by {p['resolve_by']}]")
    if brier is not None:
        lines.append(f"current brier: {brier:.3f}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "resolve_prediction",
    "Mark a prediction resolved. `outcome` must be one of: true, false, ambiguous. "
    "Call this once per prediction after boss has answered.",
    {"id": str, "outcome": str},
)
async def resolve_prediction(args):
    storage, err = _require_research()
    if err:
        return err
    pid = args["id"].strip()
    outcome = args["outcome"].strip().lower()
    try:
        ok = storage.resolve_prediction(pid, outcome)
    except ValueError as e:
        return {"content": [{"type": "text", "text": str(e)}]}
    if not ok:
        return {"content": [{"type": "text", "text": f"could not resolve {pid}: not found or already resolved"}]}
    audit_mod.audit("resolve_prediction", id=pid, outcome=outcome)
    return {"content": [{"type": "text", "text": f"resolved {pid} as {outcome}"}]}


@tool(
    "weekly_research_review",
    "Generate a weekly research review from the last 7 days of notes, standups, "
    "summaries, and resolved predictions. Claude synthesises threads/gaps/focus "
    "via a sub-call; result is written to reviews/ and returned for speaking.",
    {},
)
async def weekly_research_review(_args):
    storage, err = _require_research()
    if err:
        return err
    from src.brain import Brain
    from src.config import load as load_cfg
    brain = Brain(model=load_cfg().claude_model)
    from src.research.review import generate_weekly_review
    body, path = await generate_weekly_review(storage, brain)
    audit_mod.audit("weekly_research_review", path=path.name, body_chars=len(body))
    return {
        "content": [
            {"type": "text", "text": f"weekly review saved: {path.name}\n\n{body}"}
        ]
    }


@tool(
    "fetch_and_summarize_paper",
    "Fetch a paper at the given URL (bounded: allowlisted domains only, size + "
    "timeout capped), extract text, and ask Claude for a 3-5 paragraph summary. "
    "Writes summary to ~/friday/research/summaries/ and cross-links to notes.",
    {"url": str},
)
async def fetch_and_summarize_paper(args):
    storage, err = _require_research()
    if err:
        return err
    cfg = state_get().cfg
    if cfg is None:
        return {"content": [{"type": "text", "text": "config not available"}]}
    url = args["url"].strip()
    if not url.startswith(("http://", "https://")):
        return {"content": [{"type": "text", "text": "url must start with http:// or https://"}]}

    from src.research import fetch as fetch_mod
    from src.research.storage import arxiv_id_from_ref

    fetch_cfg = fetch_mod.FetchConfig(
        allowlist=cfg.research_paper_fetch_allowlist,
        max_bytes=cfg.research_paper_fetch_max_bytes,
        timeout_s=cfg.research_paper_fetch_timeout_s,
    )
    result = await fetch_mod.fetch_and_extract_text(url, fetch_cfg)
    if not result.ok:
        audit_mod.audit("fetch_and_summarize_paper", url=url, status="fail", error=result.error)
        return {"content": [{"type": "text", "text": f"fetch failed: {result.error}"}]}

    trimmed = result.text[:40_000]
    arxiv_id = arxiv_id_from_ref(url) or arxiv_id_from_ref(result.final_url)
    ref_out = f"arxiv:{arxiv_id}" if arxiv_id else url

    pid = storage.paper_queue_add(ref=ref_out, why="auto: fetched for summary")
    stub_path = storage.write_summary(
        ref=ref_out,
        url=result.final_url or url,
        title="(pending — Claude to fill)",
        body="(paper text fetched; summary will be written in follow-up turn)\n\n"
             "## Extracted text (truncated)\n\n" + trimmed,
    )
    storage.paper_queue_mark_summarised(pid, summary_path=str(stub_path.relative_to(storage.root)))
    audit_mod.audit(
        "fetch_and_summarize_paper",
        url=url, final_url=result.final_url, status="ok",
        ctype=result.content_type, bytes=len(result.text),
    )

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"fetched {ref_out} ({result.content_type}, {len(result.text)} chars). "
                    f"Stub saved at {stub_path.name}. Summary follows — please render 3-5 paragraphs, "
                    f"list key claims, and cross-link to relevant topics via note_research.\n\n"
                    f"EXTRACTED TEXT (truncated to 40k chars):\n\n{trimmed}"
                ),
            }
        ]
    }
