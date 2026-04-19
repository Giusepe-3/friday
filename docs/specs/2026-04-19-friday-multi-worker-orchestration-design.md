# FRIDAY Multi-Worker Orchestration — Design Spec

**Date:** 2026-04-19
**Status:** Approved (pending user review)
**Owner:** Leo (sole developer)
**Related:** `2026-04-18-friday-research-mode-design.md` (Phase 9 research mode), `2026-04-18-friday-mvp.md` (MVP)

---

## 1. Goal

Turn FRIDAY from a single-context voice assistant into a **conductor** for multiple autonomous Claude Code workers, one per active research project. Voice-driven dispatch, voice-driven status queries, voice-driven checkpoint approvals — modeled on the JARVIS / Iron Man suit pattern (one conductor talks to many independent agents on the user's behalf).

Concrete success criteria (used as live-test gate):

1. Leo says _"Friday, how's the experiment going?"_ — FRIDAY routes to thesis worker, reads back current task + last log line + git status in one sentence.
2. Leo says _"Friday, tell the paper agent to add citations for the Lipton 2019 claim in §3"_ — paper worker receives task, runs autonomously, halts at git commit checkpoint, FRIDAY surfaces the pending approval at the next conversational pause.
3. Leo says _"Friday, opus max the thesis: refactor `DGM_outer.py` to support arbitrary outer-loop schedulers"_ — thesis worker spins up that one task with `claude-opus-4-7` + max effort.
4. Worker process crashes — FRIDAY surfaces the failure on next status query without dying herself.
5. Leo restarts FRIDAY — workers keep running; FRIDAY rebuilds context from on-disk state.
6. Leo opens a normal `claude` session in any worker repo — does not conflict with the worker.

## 2. Non-goals

- Multi-machine workers (cloud-GPU jobs are tracked via wandb but FRIDAY does not run remote workers).
- Auto-respawn of crashed workers. Surface, ask, let Leo decide.
- Auto-retry of failed SDK calls inside a worker.
- Cross-project coordination (paper worker triggering thesis worker tasks). Workers are independent.
- A worker GUI / dashboard. State.json + voice are sufficient.
- Workers reading/editing FRIDAY's own repo. Filesystem scope locked to each worker's `cwd`.

## 3. Scope of projects (initial)

| Key        | Repo (local)                                                   | Remote                                 | Default model       | Default effort |
| ---------- | -------------------------------------------------------------- | -------------------------------------- | ------------------- | -------------- |
| `paper`    | `C:/Users/leona/Documents/GitHub/Learning/Verification_Paper`  | `Giusepe-3/Verification_Paper`         | `claude-opus-4-7`   | high           |
| `thesis`   | `C:/Users/leona/Documents/GitHub/Learning/dgm_bachelor_thesis` | `Leonardo-Gianola/dgm_bachelor_thesis` | `claude-opus-4-7`   | high           |
| `research` | `C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project` | `Giusepe-3/AI-Research-Project`        | `claude-opus-4-7`   | high           |

**FRIDAY brain:** `claude-opus-4-7` / **max** effort.
**Per-task escalation:** workers default to opus/high; Leo can invoke opus/**max** by saying _"opus max the <project> on this one"_ or _"max effort on this one"_. Worker honors override for that one task only, then reverts to opus/high.

**Cost / latency trade-off acknowledged:** opus 4.7 max effort for FRIDAY's voice brain will add ~5-10s per voice turn vs sonnet/high baseline, and all three workers running opus/high is meaningfully more expensive than sonnet/high. Chosen deliberately for quality > speed given this is a research-assistant role where correctness beats snappiness.

## 4. Architecture

```
                         ┌──────────────────────────────┐
                         │  FRIDAY (voice, Opus 4.7/max)│
                         │  friday_voice.py             │
                         │  cwd = .../GitHub/friday     │
                         └──────────┬───────────────────┘
                                    │  MCP tools (new):
                                    │  dispatch_task, query_worker,
                                    │  list_workers, pop_checkpoint_request,
                                    │  approve_checkpoint, recent_outbox,
                                    │  pause_worker, resume_worker, kill_worker
                                    │
                    ┌───────────────┼─────────────────┐
                    │               │                 │
                    ▼               ▼                 ▼
           ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
           │ Paper worker   │ │ Thesis worker  │ │ Research worker│
           │ Opus 4.7/h     │ │ Opus 4.7/h     │ │ Opus 4.7/h     │
           │ Python proc    │ │ Python proc    │ │ Python proc    │
           │ cwd=Ver._Paper │ │ cwd=dgm_thesis │ │ cwd=AI-Research│
           │ ClaudeSDKClient│ │ ClaudeSDKClient│ │ ClaudeSDKClient│
           └───────┬────────┘ └───────┬────────┘ └───────┬────────┘
                   │                  │                  │
                   └──────────────────┼──────────────────┘
                                      │  file bus (each repo's .friday/)
                                      │  inbox.md, outbox.jsonl, state.json
                                      │
                         ┌────────────┴───────────────┐
                         │  FRIDAY reads state.json   │
                         │  + tails outbox.jsonl      │
                         │  for pulses + checkpoints  │
                         └────────────────────────────┘
```

Four process boundaries:

- 1 FRIDAY process (`friday_voice.py`)
- 3 worker processes (`python -m friday.orchestrator.worker --project <key>`)

Workers are persistent (spawned at FRIDAY start, stay alive across voice cycles). Each holds one `ClaudeSDKClient` for its repo. Communication is exclusively via per-repo `.friday/` directories — no sockets, no IPC, no shared memory.

Why file bus over in-process asyncio:

- Worker crash isolation (one worker hitting a weird SDK error doesn't kill FRIDAY's voice loop)
- Restart resilience (FRIDAY can crash and rebuild context from disk; workers can crash and FRIDAY notices via missing pulses)
- Observability (Leo can `cat .friday/state.json` from any terminal to see worker state)
- No conflict if Leo opens a manual `claude` session in a worker repo (file bus reads/writes a gitignored subdirectory)
- Matches existing FRIDAY pattern (research mode persists to `~/friday/research/` JSON files for the same reasons)

## 5. File-bus protocol

### 5.1 Directory layout per worker repo

```
<repo>/.friday/
├── inbox.md          ← FRIDAY writes; worker reads top-down and truncates consumed blocks.
├── outbox.jsonl      ← worker appends; FRIDAY tails. Append-only, never truncated.
├── state.json        ← worker atomic-rewrites on every status change.
├── worker.pid        ← worker writes PID on startup; checked to refuse duplicate workers.
├── checkpoints/      ← one JSON file per pending checkpoint (worker is paused).
│   └── resolved/     ← post-decision archive for audit.
├── logs/             ← worker's stdout/stderr per task (rotated daily).
└── README.md         ← bootstrap script writes this; explains the dir to humans.
```

`.friday/` is added to each repo's `.gitignore` by the bootstrap script.

### 5.2 Inbox messages

Format: blocks separated by `---\n`, each block is YAML frontmatter + body. Worker processes top-down, deletes consumed blocks via atomic rewrite.

```markdown
---
id: 550e8400-e29b-41d4-a716-446655440000
type: task
model: claude-opus-4-7
effort: high
scope_files: [paper/sec3.tex, paper/refs.bib]
created_at: 2026-04-19T16:00:00
---

Polish paper §3 — tighten the results table, don't touch the prose.
Commit per paragraph. Don't push.
```

Allowed `type` values:

| Type                  | Body                                                  | Worker behavior                                                   |
| --------------------- | ----------------------------------------------------- | ----------------------------------------------------------------- |
| `task`                | Free-form natural-language task                       | Spawn SDK query; stream result to outbox                          |
| `reset`               | Optional: reason                                      | Discard current SDK client; spawn fresh on next task              |
| `checkpoint_decision` | `id: <ckpt_id>\ndecision: approve\|deny\nreason: ...` | Resume or abort the paused tool call                              |
| `pause`               | (empty)                                               | Stop accepting new tasks; finish current; `state.status = paused` |
| `resume`              | (empty)                                               | Inverse of pause                                                  |
| `terminate`           | (empty)                                               | Cleanup, exit process                                             |

Defaults: `model = worker's default_model`, `effort = worker's default_effort`, `scope_files` omitted or `None` = no file-scope guardrail; non-empty list = scope enforced; empty list `[]` is treated as `None` (not "deny all writes").

### 5.3 Outbox events

Append-only JSONL. One JSON object per line, each with `ts` (ISO-8601), `type`, plus type-specific fields.

| `type`                | Fields                                                                                    | Frequency / trigger                                                                        |
| --------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `ack`                 | `task_id`                                                                                 | Immediately after consuming an inbox block                                                 |
| `pulse`               | `status`, `current_task_id`, `last_log_line`, `git: {branch, uncommitted, ahead, behind}` | Every 30s while `working`, every 5 min while `idle`                                        |
| `stream`              | `task_id`, `text`                                                                         | Optional — for live-streaming worker text to FRIDAY (off by default; opt-in via task flag) |
| `checkpoint_request`  | `id`, `task_id`, `tool`, `command`, `reason`, `context: {...}`                            | Worker halted via `can_use_tool` callback on a regex match                                 |
| `checkpoint_resolved` | `id`, `decision`, `reason`                                                                | After FRIDAY's decision processed                                                          |
| `task_complete`       | `task_id`, `summary`, `artifacts: [paths]`                                                | SDK ResultMessage received cleanly                                                         |
| `error`               | `task_id`, `error`, `traceback`                                                           | SDK call raised                                                                            |
| `terminated`          | `reason`                                                                                  | Worker shutting down                                                                       |

### 5.4 state.json

Canonical fast-read snapshot. Atomic write via `write temp → os.replace`. Schema:

```json
{
  "project": "paper",
  "status": "idle | working | blocked | paused | error | terminated",
  "current_task": "Polish paper §3 — tighten the results table",
  "current_task_id": "550e8400-...",
  "started_at": "2026-04-19T16:00:00",
  "last_pulse_at": "2026-04-19T16:02:00",
  "last_log_line": "Wrote paper/sec3.tex",
  "git": { "branch": "main", "uncommitted": 3, "ahead": 0, "behind": 0 },
  "pending_checkpoint_id": null,
  "model": "claude-opus-4-7",
  "effort": "high"
}
```

Status semantics:

- `idle` — worker alive, no current task, polling inbox.
- `working` — current task in progress.
- `blocked` — current task paused on a checkpoint; `pending_checkpoint_id` is set.
- `paused` — worker not accepting new tasks (after `pause` message); will not start anything until `resume`.
- `error` — last task ended in error; worker stays alive but won't auto-retry.
- `terminated` — worker process exiting.

### 5.5 Checkpoint files

When `can_use_tool` callback halts a tool call, worker writes `<repo>/.friday/checkpoints/<id>.json`:

```json
{
  "id": "ckpt-...",
  "task_id": "550e8400-...",
  "tool": "Bash",
  "command": "git commit -m 'polish §3 results table'",
  "reason": "pre-commit-approval",
  "context": {
    "diff_summary": "paper/sec3.tex: +12 -8\npaper/refs.bib: +2 -0",
    "files_changed": ["paper/sec3.tex", "paper/refs.bib"]
  },
  "created_at": "2026-04-19T16:05:00"
}
```

Worker awaits `checkpoint_decision` for this id (polls inbox every 1s with timeout = 1h). **While blocked on a checkpoint, worker only consumes `checkpoint_decision` and `terminate` messages from inbox; other messages (new tasks, pause, resume, reset) stay in inbox and are processed after checkpoint resolves.** On approval: `can_use_tool` returns `{"behavior": "allow"}`. On denial: returns `{"behavior": "deny", "message": <reason>}` — worker's SDK loop receives that as a tool error and adapts. On timeout: writes error event, marks state as `error`, deletes checkpoint file.

After resolution (either decision), checkpoint file is moved to `<repo>/.friday/checkpoints/resolved/<id>.json` for audit.

### 5.6 Checkpoint triggers (worker's `can_use_tool` callback)

Per-worker config (from `friday.yaml`) lists regex patterns to halt on:

```yaml
checkpoint_triggers:
  bash_regex:
    - "^git commit"
    - "^git push"
    - "runpod"
    - "bash setup_.*pod"
    - "wandb init"
```

Plus three hardcoded universal triggers (NOT configurable, applied even when not in regex list):

1. Any `git push` — always halt.
2. Any cloud GPU script invocation matching the global regex `runpod|wandb init|bash setup_.*pod|gcloud compute|aws ec2 run`.
3. Any file write outside `scope_files` (when `scope_files` is set on the task).

These three are always-on regardless of task or config.

## 6. FRIDAY orchestrator MCP tools

Added to `src/orchestrator/tools.py` (new module), registered alongside existing 20 tools via `src/tools/__init__.py` ALLOWED list. Failure-isolated import (try/except) so a bug in orchestrator doesn't break existing tools.

| Tool                     | Signature                                                                                         | Behavior                                                                                                                                                                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dispatch_task`          | `(project: str, task: str, model: str = None, effort: str = None, scope_files: list[str] = None)` | Append task block to `<repo>/.friday/inbox.md`. Returns `task_id`. `model=None` and `effort=None` mean "use worker default from yaml". If worker not running, spawn it first via `subprocess.Popen`. |
| `query_worker`           | `(project: str)`                                                                                  | Read `<repo>/.friday/state.json` + tail last 5 outbox events. Returns dict suitable for one-line voice readback.                                                                                     |
| `list_workers`           | `()`                                                                                              | Iterate all configured projects. One-line state per worker.                                                                                                                                          |
| `pop_checkpoint_request` | `(project: str = None)`                                                                           | Pop oldest pending checkpoint (any project if None). Returns checkpoint dict or None. Used by FRIDAY's interrupt loop.                                                                               |
| `approve_checkpoint`     | `(project: str, checkpoint_id: str, decision: "approve" \| "deny", reason: str = "")`             | Write `checkpoint_decision` to that worker's inbox; returns ack.                                                                                                                                     |
| `recent_outbox`          | `(project: str, limit: int = 10, types: list[str] = None)`                                        | Pull last N outbox events; useful for "what did the paper agent do in the last hour?"                                                                                                                |
| `pause_worker`           | `(project: str)`                                                                                  | Append `pause` message to inbox.                                                                                                                                                                     |
| `resume_worker`          | `(project: str)`                                                                                  | Append `resume` message.                                                                                                                                                                             |
| `kill_worker`            | `(project: str)`                                                                                  | SIGTERM the worker process; state preserved on disk.                                                                                                                                                 |

All tool names registered as `mcp__friday__<tool>` in ALLOWED. Total tools after this change: 20 (existing) + 9 (new) = 29.

## 7. Routing

`src/orchestrator/routing.py` — pure logic, no I/O.

```python
from typing import Optional
import re

_NORM = re.compile(r"[a-z']+")

def normalize(s: str) -> str:
    return " ".join(_NORM.findall(s.lower()))

def route(text: str, workers_cfg: dict) -> Optional[str]:
    """Return project key by alias hit, else None.

    Caller (FRIDAY's persona via brain) handles None case by either
    asking Leo or LLM-routing from broader context.
    """
    norm = normalize(text)
    for project, w in workers_cfg.items():
        for alias in w["aliases"]:
            if normalize(alias) in norm:
                return project
    return None
```

Behavior chain:

1. Persona (CLAUDE.md update) tells FRIDAY: when user issues a task, call `route()` first by inferring project from voice text. If routing returns a project, use it. If not, **either** ask user which project, **or** if context strongly implies one (Opus 4.7 judgment), proceed with high confidence.
2. Aliases handle ~95% of natural phrasings instantly. Routing module is just substring matching after normalization — no LLM call for the common case.

Config alias examples (final form in `friday.yaml`):

```yaml
workers:
  paper:
    aliases: [paper, draft, verification, "the paper"]
  thesis:
    aliases: [thesis, experiment, dgm, "darwin godel", "coding agent"]
  research:
    aliases: [research, literature, "lit review", progress, "the notes"]
```

## 8. Checkpoint voice UX

### 8.1 Polite-pause-point pattern

FRIDAY does NOT interrupt mid-turn (mid-TTS or mid-user-speech). Interrupts surface at conversational pauses.

Implementation (added to `friday_voice.py`):

1. New asyncio task `_checkpoint_drain_loop` started alongside FRIDAY's main wake-listen loop.
2. Every 5s, drain calls `pop_checkpoint_request()` across all workers, pushes to a `_pending_interrupts: asyncio.Queue`.
3. The conversation loop (the inner loop inside a wake cycle) checks `_pending_interrupts` between turns:
   - After current TTS playback completes
   - Before next `record_until_silence` call
4. If queue non-empty, FRIDAY speaks the interrupt:
   - _"Paper agent waiting on commit approval — three files changed in §3. Approve, deny, or want the diff?"_
5. Mini-flow handles response:
   - `approve` → call `approve_checkpoint(decision="approve")`
   - `deny [reason]` → call `approve_checkpoint(decision="deny", reason=reason)`
   - `show me` / `details` → call `query_worker` + `recent_outbox`, read summary, re-prompt
   - `later` → push back to queue, continue normal flow
6. While FRIDAY is between wake cycles (no active conversation), interrupts queue silently. Next wake → first thing FRIDAY says is the queued interrupt(s).

### 8.2 Severity escalation

Worker `error` events bypass the polite-pause rule **only if** the error is in a task Leo dispatched within the last 5 minutes (he's still actively waiting). FRIDAY interrupts immediately:

- _"Thesis agent failed on `DGM_outer.py` refactor — `ImportError: no module named torch_geometric`."_

Background errors (worker was running autonomously on something dispatched hours ago) wait for next pause.

### 8.3 Stark canonical reference

JARVIS interrupts only at conversational pauses unless catastrophic. Mirror.

## 9. Model + effort wiring

### 9.1 SDK passthrough

`ClaudeAgentOptions.extra_args` accepts CLI flags. Effort is intended to flow as `extra_args={"effort": "<level>"}` → CLI invocation: `claude --model claude-opus-4-7 --effort high ...`. Effort levels: `low | medium | high | max`.

**Phase 1 verification target:** confirm the SDK actually surfaces `--effort` via `extra_args` in the installed Claude Agent SDK version; if not, fallback options are (a) `extra_args={"max-thinking-tokens": "<int>"}` for budget-based control or (b) document a manual launch wrapper. If neither path works, this spec is updated and the model upgrade still ships (without effort tier control).

### 9.2 Per-component config

| Component          | Default model       | Default effort    | Configurable via                                                               |
| ------------------ | ------------------- | ----------------- | ------------------------------------------------------------------------------ |
| FRIDAY voice brain | `claude-opus-4-7`   | `max`             | `claude_model: claude-opus-4-7` and new `friday_effort: max` in `friday.yaml`  |
| Worker (default)   | `claude-opus-4-7`   | `high`            | per-worker `default_model` and `default_effort` in `workers:` block            |
| Per-task override  | (caller-supplied)   | (caller-supplied) | `dispatch_task(model=..., effort=...)`                                         |

### 9.3 Voice phrasing for escalation

Examples FRIDAY's persona (CLAUDE.md update) understands:

- _"opus max the thesis on this one"_ → `dispatch_task(project="thesis", model="claude-opus-4-7", effort="max", task=...)`
- _"max effort on the paper for this one"_ → `effort="max"` (model stays at worker default opus)
- _"sonnet medium for the research"_ (manual downgrade if Leo wants speed) → `model="claude-sonnet-4-6", effort="medium"`

`src/orchestrator/models.py` (new tiny module) maps short names → full IDs:

```python
MODEL_ALIASES = {
    "opus": "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}
EFFORT_LEVELS = {"low", "medium", "high", "max"}
```

## 10. Error handling + safety

| Failure                                                            | Handling                                                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Worker process crashes                                             | FRIDAY's pulse-tail detects no pulse for 2× expected interval (60s if working, 10min if idle), marks `state.status = "error"` (FRIDAY-side override of state file), surfaces on next `query_worker`. **No auto-respawn.** Leo decides via `dispatch_task` (which spawns if dead) or explicit restart command. |
| Worker stuck (pulses fire but no progress)                         | No automatic detection. Leo can see "current_task started 47 min ago" via `query_worker` and decide.                                                                                                                                                                                                          |
| FRIDAY crashes                                                     | Workers keep running. On FRIDAY restart, reads each worker's `state.json` to rebuild context. Pending checkpoints still in outbox + checkpoints/ dir.                                                                                                                                                         |
| Worker SDK call fails (network, model error)                       | Worker writes `error` event, marks `state.status = "error"`, halts. **No auto-retry.** Leo decides.                                                                                                                                                                                                           |
| Concurrent manual edit (Leo edits file while worker working on it) | Worker's `can_use_tool` callback inspects file mtime before write — if changed since worker last read, halts as a checkpoint with `reason: "file-conflict"`.                                                                                                                                                  |
| Cloud GPU spend blow-up                                            | Always-on regex (universal trigger #2 in §5.6) halts on cloud script invocation. Cannot be disabled by task flags.                                                                                                                                                                                            |
| Git push to main                                                   | Universal trigger #1. Always halts. Cannot be disabled.                                                                                                                                                                                                                                                       |
| Worker tries to edit FRIDAY's repo                                 | SDK `cwd` parameter scopes filesystem access to that repo. Shell commands touching other paths still pass through `can_use_tool` and hit the universal-trigger filter.                                                                                                                                        |
| Inbox/outbox file corruption                                       | Workers parse defensively, skip malformed lines, log to `.friday/logs/parser_errors.log`. State.json uses atomic write.                                                                                                                                                                                       |
| Two workers somehow start for same project                         | Worker checks `<repo>/.friday/worker.pid` on startup — if process exists, refuses to start. Stale pidfile removed if process not alive.                                                                                                                                                                       |

**Universal safety triggers** (cannot be overridden by `fire_and_forget` or task flags):

1. `git push` — always halt.
2. Cloud GPU scripts — always halt.
3. File writes outside declared `scope_files` — halt only if `scope_files` was provided to the task; if not provided, no scope guard.

## 11. Testing strategy

| Layer                    | Type                                    | Path                                            | Approx tests |
| ------------------------ | --------------------------------------- | ----------------------------------------------- | ------------ |
| Routing                  | Unit                                    | `tests/orchestrator/test_routing.py`            | ~10          |
| File-bus protocol        | Unit + property                         | `tests/orchestrator/test_worker_bus.py`         | ~15          |
| Checkpoint gate          | Unit (mock SDK)                         | `tests/orchestrator/test_checkpoint_gate.py`    | ~8           |
| Worker harness lifecycle | Integration (real subprocess, tmp repo) | `tests/orchestrator/test_worker_harness.py`     | ~5           |
| Orchestrator MCP tools   | Unit (fake bus)                         | `tests/orchestrator/test_orchestrator_tools.py` | ~12          |
| Voice flow               | Manual checklist                        | n/a (live test)                                 | —            |

Target: ~50 new automated tests, all green before Phase 6 (checkpoint voice UX) lands. Manual live-test checklist covers Phase 6 + end-to-end voice → SDK calls (too slow/costly for automation, same pattern as Phase 9.7).

## 12. Configuration changes

### 12.1 `config/friday.yaml` additions

```yaml
# Existing fields unchanged. New fields:
claude_model: claude-opus-4-7 # was claude-sonnet-4-6
shim_model: claude-opus-4-7 # was "sonnet" alias — use full ID for FRIDAY brain
friday_effort: max # NEW — CLI --effort passthrough (verify in Phase 1, see §9.1)

workers:
  paper:
    repo: C:/Users/leona/Documents/GitHub/Learning/Verification_Paper
    aliases: [paper, draft, verification, azr, "the paper"]
    default_model: claude-opus-4-7
    default_effort: high
    autostart: true
    pulse_interval_working_s: 30
    pulse_interval_idle_s: 300
    checkpoint_triggers:
      bash_regex:
        - "^git commit"
        - "^git push"
        - "runpod"
        - "bash setup_.*pod"
        - "wandb init"
  thesis:
    repo: C:/Users/leona/Documents/GitHub/Learning/dgm_bachelor_thesis
    aliases: [thesis, experiment, dgm, "darwin godel", "coding agent", polyglot]
    default_model: claude-opus-4-7
    default_effort: high
    autostart: true
    pulse_interval_working_s: 30
    pulse_interval_idle_s: 300
    checkpoint_triggers:
      bash_regex:
        - "^git commit"
        - "^git push"
        - "docker run"
  research:
    repo: C:/Users/leona/Documents/GitHub/Learning/AI-Research-Project
    aliases: [research, literature, "lit review", progress, "the notes"]
    default_model: claude-opus-4-7
    default_effort: high
    autostart: true
    pulse_interval_working_s: 30
    pulse_interval_idle_s: 300
    checkpoint_triggers:
      bash_regex:
        - "^git commit"
        - "^git push"
```

### 12.2 `src/config.py` additions

New dataclasses:

```python
@dataclass
class WorkerConfig:
    project: str
    repo: Path
    aliases: list[str]
    default_model: str
    default_effort: str
    autostart: bool
    pulse_interval_working_s: int
    pulse_interval_idle_s: int
    checkpoint_triggers: dict  # {"bash_regex": [str, ...]}

@dataclass
class Config:
    # ... existing fields ...
    friday_effort: str
    workers: dict[str, WorkerConfig]
```

### 12.3 CLAUDE.md persona additions

New section appended:

```markdown
## Multi-project orchestration

You conduct three workers — `paper`, `thesis`, `research` — each running
autonomously in its own repo with its own Claude Code session. You are the
voice interface; they are the hands.

- For project status questions ("how's the experiment going?"), call
  `query_worker(project)` and read back ONE sentence from the state.
- For task dispatch, call `dispatch_task(project, task, model=, effort=)`.
  Default model = `claude-opus-4-7`, effort = `high` (workers are opus by
  default). If Leo says "opus max" or "max effort", set `effort="max"`. If
  Leo explicitly downgrades ("sonnet medium for the research"), pass
  `model="claude-sonnet-4-6", effort="medium"`.
- If the user's intent is ambiguous about which project, ask once. Don't
  guess if confidence is low.
- When `pop_checkpoint_request` returns a pending checkpoint, surface it
  in one sentence with the action choices (approve / deny / show me / later).
- Never call worker tools mid-task without user instruction.
- Worker tool aliases (substring match in user text):
  - paper / draft / verification / azr / "the paper" → project=paper
  - thesis / experiment / dgm / coding agent / polyglot → project=thesis
  - research / literature / lit review / notes → project=research
```

### 12.4 Per-worker-repo bootstrap

Script `scripts/bootstrap_worker_repo.py` creates `<repo>/.friday/` and adds it to that repo's `.gitignore`. Idempotent.

## 13. Phase order

| #   | Phase                                                                                 | Days | What ships if you stop here                                                                                                                 |
| --- | ------------------------------------------------------------------------------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | File-bus protocol + `WorkerBus` class + tests                                         | 2    | Library code + tests. No user-visible change.                                                                                               |
| 2   | Worker harness (`src/orchestrator/worker.py`) with checkpoint gate + bootstrap script | 3    | Manually `python -m friday.orchestrator.worker --project paper`, write inbox by hand, watch outbox. Functional but no voice.                |
| 3   | FRIDAY orchestrator MCP tools (the 9 in §6)                                           | 2    | Use tools by typed prompt in FRIDAY's `claude` shell. Still no voice routing.                                                               |
| 4   | Routing module + persona update + Opus 4.7 model upgrade for FRIDAY                   | 1    | Voice routes to workers via aliases. Checkpoints surfaced only via explicit `pop_checkpoint_request` polling — no proactive interrupts yet. |
| 5   | Per-repo bootstrap of all 3 projects + autostart wiring in `friday_voice.py`          | 1    | All workers boot with FRIDAY. Real daily use possible.                                                                                      |
| 6   | Checkpoint voice interrupt UX (polite-pause-point pattern)                            | 1-2  | Workers proactively interrupt FRIDAY between turns. Full Stark mode.                                                                        |

Total: 10-11 working days.

After Phase 5: usable for real research work.
After Phase 6: ambient.

## 14. Open questions / explicit deferrals

- **Cross-machine cloud-GPU job tracking.** Workers can dispatch runpod scripts (with checkpoint) but cannot directly read remote job status. Option: a separate `wandb_status` MCP tool that polls wandb API. Defer until Leo hits the friction.
- **Worker context size limits.** Long-running workers accumulate SDK conversation context. Not handled in v1; Leo can `reset` a worker via inbox message when it gets stale. Auto-reset on token threshold deferred.
- **Multi-task queue per worker.** v1 worker processes inbox top-down sequentially, one task at a time. Parallel intra-worker tasks deferred.
- **Checkpoint auto-approval rules.** v1 always halts on regex match; no rules like "auto-approve git commits to non-main branches." Deferred.
- **Worker → worker messaging.** Cross-project coordination explicitly out of scope for v1.

## 15. References

- Existing FRIDAY MVP spec: `docs/specs/2026-04-18-friday-mvp.md`
- Research mode spec: `docs/specs/2026-04-18-friday-research-mode-design.md`
- Stark patterns memory: `~/.claude/projects/.../memory/project_friday_stark_patterns.md`
- Claude Agent SDK docs: `extra_args` for CLI passthrough; `can_use_tool` for permission callbacks.
