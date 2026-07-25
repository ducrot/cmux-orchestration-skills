#!/usr/bin/env python3
"""Create and append cmux-grilling run state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from orchestrator_lib import (
    LANE_WAIT_MINUTES,
    LANES,
    append_jsonl,
    first_line,
    read_json,
    read_text,
    slugify,
    utc_now,
    write_json,
)


RUN_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# Must stay in sync with parse_research_report.py's gate values.
GATE_DECISIONS = ["advance", "stop", "blocked", "hitl", "pending"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create run directory and initial state")
    task_source = init.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task", help="Task text: the Vorhaben plus its fixed constraints")
    task_source.add_argument("--task-file", help="File containing the task text")
    init.add_argument("--run-id", help="Stable run id. Defaults to grill-<slug>-<YYYY-MM-DD>-<HHMM> (UTC)")
    init.add_argument("--runs-root", default=".scratch/orchestrator/runs")
    init.add_argument("--max-questions", type=int, default=10)
    init.add_argument("--output-dir", default="grill-sessions", help="Where the final artifact pair lands")
    init.add_argument("--workspace-id", help="cmux workspace UUID to pin. Defaults to $CMUX_WORKSPACE_ID")
    init.add_argument(
        "--no-workspace",
        action="store_true",
        help="Pin no workspace (offline runs outside cmux; cmux-scoped scripts will refuse to run)",
    )

    event = subparsers.add_parser("event", help="Append an event to run log")
    event.add_argument("--run-dir", required=True)
    event.add_argument("--type", required=True)
    event.add_argument("--message", required=True)
    event.add_argument("--data", help="Optional JSON object")

    gate = subparsers.add_parser("gate", help="Record a gate decision")
    gate.add_argument("--run-dir", required=True)
    gate.add_argument("--stage", required=True, help='e.g. "round-1-web" or "finalize"')
    gate.add_argument("--decision", choices=GATE_DECISIONS, required=True)
    gate.add_argument("--reason", required=True)
    gate.add_argument("--next-stage", help="Stage to move to. Only meaningful with --decision advance")

    snapshot = subparsers.add_parser("snapshot", help="Record a working-tree fingerprint as a tree.snapshot event")
    snapshot.add_argument("--run-dir", required=True)
    snapshot.add_argument("--label", required=True, help='e.g. "reports-captured round-1"')
    snapshot.add_argument("--data", help="Optional JSON object merged into the event data")

    complete = subparsers.add_parser("complete", help="Close a run: set current_stage=done")
    complete.add_argument("--run-dir", required=True)
    complete.add_argument("--message", default="grilling session complete")
    complete.add_argument("--data", help="Optional JSON object, e.g. artifact paths and stop reason")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init":
        return init_run(args)
    if args.command == "event":
        return append_event(args)
    if args.command == "gate":
        return append_gate(args)
    if args.command == "snapshot":
        return append_snapshot(args)
    if args.command == "complete":
        return complete_run(args)
    raise AssertionError(args.command)


def ensure_runs_root_ignored(runs_root: Path) -> None:
    """Run state is ephemeral lifecycle data; keep it out of git in every target repo."""
    ignore = runs_root / ".gitignore"
    if not ignore.is_file():
        runs_root.mkdir(parents=True, exist_ok=True)
        ignore.write_text("*\n", encoding="utf-8")


def resolve_workspace_id(args: argparse.Namespace) -> str | None:
    """Pin the run's cmux workspace at init; every later cmux call uses this value.

    Resolution is flag > env > hard error. There is deliberately no fallback to the
    focused workspace (`cmux identify`): an empty value silently degrading to whatever
    the human is looking at is exactly the bug this pin exists to prevent.
    """
    if args.no_workspace:
        return None
    workspace_id = args.workspace_id or os.environ.get("CMUX_WORKSPACE_ID", "")
    if not workspace_id:
        raise SystemExit(
            "No cmux workspace to pin: pass --workspace-id, run init from a cmux pane "
            "(CMUX_WORKSPACE_ID), or opt out explicitly with --no-workspace."
        )
    return workspace_id


def init_run(args: argparse.Namespace) -> int:
    if args.max_questions < 1:
        raise SystemExit("--max-questions must be >= 1")
    workspace_id = resolve_workspace_id(args)
    task_text = read_text(Path(args.task_file)) if args.task_file else args.task
    task_text = task_text.strip()
    if not task_text:
        raise SystemExit("Task text is empty")
    slug = slugify(first_line(task_text))
    now = utc_now()
    # grill-<slug>-<YYYY-MM-DD>-<HHMM> (UTC): readable, sortable, never reused across runs.
    run_id = args.run_id or RUN_ID_RE.sub("-", f"grill-{slug}-{now[:10]}-{now[11:13]}{now[14:16]}").strip("-")
    runs_root = Path(args.runs_root)
    ensure_runs_root_ignored(runs_root)
    run_dir = runs_root / run_id
    # Idempotent: re-running init on an existing run must not clobber its state or crash.
    if (run_dir / "state.json").is_file():
        for name in ("prompts", "reports", "synthesis"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        print(run_dir)
        return 0
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("prompts", "reports", "synthesis"):
        (run_dir / name).mkdir(exist_ok=True)
    (run_dir / "task.md").write_text(task_text + "\n", encoding="utf-8")
    state = {
        "run_id": run_id,
        "created_at": now,
        "workspace_id": workspace_id,
        "task_file": "task.md",
        "slug": slug,
        "max_questions": args.max_questions,
        "output_dir": args.output_dir,
        "lanes": {name: dict(config) for name, config in LANES.items()},
        "chain": ["research", "finalize"],
        "worker_wait_policy": {
            "missing_report_gate": "pending",
            "wait_mechanism": "armed watcher (await_reports.py under Monitor), not polling",
            "minimum_wait_minutes": {name: LANE_WAIT_MINUTES for name in LANES},
            "extension_policy": "extend once when the pane shows plausible activity",
            "exhausted_wait_decision": "hitl",
            # No empty-finding degradation: a dead or silent lane is a HITL stop.
            "degradation": "none",
        },
        "current_stage": "research",
        "gate_decisions": [],
    }
    write_json(run_dir / "state.json", state)
    append_jsonl(run_dir / "events.jsonl", {"time": now, "type": "run.init", "state": state})
    print(run_dir)
    return 0


def append_event(args: argparse.Namespace) -> int:
    data = json.loads(args.data) if args.data else {}
    if not isinstance(data, dict):
        raise SystemExit("--data must be a JSON object")
    append_jsonl(
        Path(args.run_dir) / "events.jsonl",
        {"time": utc_now(), "type": args.type, "message": args.message, "data": data},
    )
    return 0


def append_gate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    event = {
        "time": utc_now(),
        "type": "gate",
        "stage": args.stage,
        "decision": args.decision,
        "reason": args.reason,
    }
    append_jsonl(run_dir / "events.jsonl", event)
    write_json(run_dir / "gate-decisions" / f"{args.stage}-{event['time'].replace(':', '')}.json", event)

    # Keep state.json current; a reader must not see a stage the run left long ago.
    state_path = run_dir / "state.json"
    if state_path.is_file():
        state = read_json(state_path)
        state.setdefault("gate_decisions", []).append(event)
        state["current_stage"] = args.next_stage or args.stage
        state["updated_at"] = event["time"]
        write_json(state_path, state)
    return 0


def append_snapshot(args: argparse.Namespace) -> int:
    def git(*argv: str) -> str:
        result = subprocess.run(["git", *argv], capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f"git {' '.join(argv)} failed: {result.stderr.strip()}")
        return result.stdout

    head = git("rev-parse", "HEAD").strip()
    status = git("status", "--porcelain")
    # Covers tracked-file changes plus the untracked-file listing; untracked *content* is not hashed.
    diff = git("diff") + git("diff", "--cached")
    fingerprint = hashlib.sha256((status + diff).encode("utf-8")).hexdigest()[:16]

    data = json.loads(args.data) if args.data else {}
    if not isinstance(data, dict):
        raise SystemExit("--data must be a JSON object")
    data.update({"head": head, "fingerprint": fingerprint, "dirty_paths": len(status.splitlines())})
    append_jsonl(
        Path(args.run_dir) / "events.jsonl",
        {"time": utc_now(), "type": "tree.snapshot", "message": args.label, "data": data},
    )
    print(f"fingerprint={fingerprint} head={head[:12]} dirty_paths={data['dirty_paths']}")
    return 0


def complete_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state_path = run_dir / "state.json"
    state = read_json(state_path)
    now = utc_now()
    data = json.loads(args.data) if args.data else {}
    if not isinstance(data, dict):
        raise SystemExit("--data must be a JSON object")
    state["current_stage"] = "done"
    state["updated_at"] = now
    write_json(state_path, state)
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": now, "type": "run.completed", "message": args.message, "data": data},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
