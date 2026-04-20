"""Per-repo .friday/ scaffold.

Idempotent: safe to re-run. Creates .friday/ + subdirs, adds .friday/ to
the repo's .gitignore if missing, writes README.md describing the dir.

Usage:
    python scripts/bootstrap_worker_repo.py --repo /path/to/repo --project paper
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

README_TEXT = """\
# .friday/ — FRIDAY worker scratch directory

This directory is owned by FRIDAY's per-project worker process. It is
gitignored — nothing in here should be checked in.

Files:
- inbox.md       FRIDAY → worker task queue
- outbox.jsonl   worker → FRIDAY events (append-only)
- state.json     current worker status snapshot
- worker.pid     worker process ID (for duplicate detection)
- checkpoints/   pending tool-approval requests (resolved/ archives them)
- logs/          per-task stdout/stderr + parser_errors.log

To inspect this worker's state:
    cat .friday/state.json
    tail -f .friday/outbox.jsonl

See: docs/specs/2026-04-19-friday-multi-worker-orchestration-design.md
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold .friday/ in a worker repo")
    parser.add_argument("--repo", required=True, help="Absolute path to the worker repo")
    parser.add_argument("--project", required=True, help="Project key (paper/thesis/research)")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: repo path does not exist: {repo}", file=sys.stderr)
        return 2

    friday_dir = repo / ".friday"
    for sub in (friday_dir, friday_dir / "checkpoints", friday_dir / "checkpoints" / "resolved", friday_dir / "logs"):
        sub.mkdir(parents=True, exist_ok=True)

    # Empty inbox/outbox/state if missing
    inbox = friday_dir / "inbox.md"
    if not inbox.exists():
        inbox.write_text("", encoding="utf-8")
    outbox = friday_dir / "outbox.jsonl"
    if not outbox.exists():
        outbox.write_text("", encoding="utf-8")
    state = friday_dir / "state.json"
    if not state.exists():
        state.write_text('{"project": "%s", "status": "idle"}\n' % args.project, encoding="utf-8")

    # README
    readme = friday_dir / "README.md"
    readme.write_text(README_TEXT, encoding="utf-8")

    # Patch .gitignore
    gitignore = repo / ".gitignore"
    line = ".friday/"
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8").splitlines()
        if line not in existing and ".friday" not in existing:
            with gitignore.open("a", encoding="utf-8") as f:
                if not gitignore.read_text(encoding="utf-8").endswith("\n"):
                    f.write("\n")
                f.write(f"{line}\n")
            print(f"[bootstrap] added '{line}' to {gitignore}")
        else:
            print(f"[bootstrap] {gitignore} already contains .friday entry")
    else:
        gitignore.write_text(f"{line}\n", encoding="utf-8")
        print(f"[bootstrap] created {gitignore}")

    print(f"[bootstrap] {friday_dir} ready for project={args.project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
