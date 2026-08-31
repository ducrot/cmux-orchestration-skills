#!/usr/bin/env python3
"""Create and append cmux-issue-chain run state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from agents_config import (
    ConfigError,
    add_override_options,
    add_probe_options,
    supplied_configuration_inputs,
)
from orchestrator_lib import (
    MINIMUM_WAIT_MINUTES,
    append_jsonl,
    blocker_status,
    issue_ready,
    load_issues,
    read_json,
    utc_now,
    write_json,
)
from worker_snapshot import (
    ISSUE_WORKERS,
    SnapshotError,
    WORKFLOW,
    persist_snapshot,
    snapshot_from_args,
)


RUN_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# Must stay in sync with parse_report.py's gate values.
GATE_DECISIONS = ["advance", "stop", "blocked", "hitl", "pending"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create run directory and initial state")
    init.add_argument("--tracker", required=True, help="Tracker directory, e.g. .scratch/<tracker>")
    init.add_argument("--issue", required=True)
    init.add_argument("--run-id", help="Stable run id. Defaults to <issue-id>-<YYYY-MM-DD>-<HHMM> (UTC)")
    init.add_argument("--runs-root", default=".scratch/orchestrator/runs")
    init.add_argument(
        "--config",
        help=(
            "Existing agents.json path "
            "(default: <git-root>/.scratch/orchestrator/agents.json)"
        ),
    )
    init.add_argument("--workspace-id", help="cmux workspace UUID to pin. Defaults to $CMUX_WORKSPACE_ID")
    init.add_argument(
        "--no-workspace",
        action="store_true",
        help="Pin no workspace (offline runs outside cmux; cmux-scoped scripts will refuse to run)",
    )
    add_override_options(init, workflow=WORKFLOW)
    add_probe_options(init)

    prepare = subparsers.add_parser(
        "prepare",
        help="Reload configuration, preflight every role, and prepare one immutable stage snapshot",
    )
    prepare.add_argument("--run-dir", required=True)
    prepare.add_argument("--stage", required=True, choices=ISSUE_WORKERS)
    prepare.add_argument("--pass", dest="pass_num", required=True, type=int)
    add_override_options(prepare, workflow=WORKFLOW)
    add_probe_options(prepare)

    event = subparsers.add_parser("event", help="Append an event to run log")
    event.add_argument("--run-dir", required=True)
    event.add_argument("--type", required=True)
    event.add_argument("--message", required=True)
    event.add_argument("--data", help="Optional JSON object")

    gate = subparsers.add_parser("gate", help="Record a gate decision")
    gate.add_argument("--run-dir", required=True)
    gate.add_argument("--stage", required=True)
    gate.add_argument("--decision", choices=GATE_DECISIONS, required=True)
    gate.add_argument("--reason", required=True)
    gate.add_argument("--next-stage", help="Stage to move to. Only meaningful with --decision advance")

    snapshot = subparsers.add_parser("snapshot", help="Record a working-tree fingerprint as a tree.snapshot event")
    snapshot.add_argument("--run-dir", required=True)
    snapshot.add_argument("--label", required=True, help='e.g. "report-captured review-1"')
    snapshot.add_argument("--data", help="Optional JSON object merged into the event data")

    complete = subparsers.add_parser("complete", help="Close a run: set current_stage=done, refresh the issue snapshot")
    complete.add_argument("--run-dir", required=True)
    complete.add_argument("--message", default="chain complete")

    return parser


def run_command(args: argparse.Namespace) -> int:
    if args.command == "init":
        return init_run(args)
    if args.command == "prepare":
        return prepare_stage(args)
    if args.command == "event":
        return append_event(args)
    if args.command == "gate":
        return append_gate(args)
    if args.command == "snapshot":
        return append_snapshot(args)
    if args.command == "complete":
        return complete_run(args)
    raise AssertionError(args.command)


def main() -> int:
    args = build_parser().parse_args()
    try:
        return run_command(args)
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        print(f"run state operation failed: {error}", file=sys.stderr)
        return 1


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
    tracker = Path(args.tracker)
    workspace_id = resolve_workspace_id(args)
    issues = load_issues(tracker)
    if args.issue not in issues:
        raise SystemExit(f"Unknown issue: {args.issue}")
    issue = issues[args.issue]
    now = utc_now()
    # Issue first so runs group per issue in a sorted listing; minute granularity
    # keeps ids unique across re-runs without the mangled-timezone noise.
    run_id = args.run_id or RUN_ID_RE.sub("-", f"{issue.id}-{now[:10]}-{now[11:13]}{now[14:16]}").strip("-")
    runs_root = Path(args.runs_root)
    run_dir = runs_root / run_id
    # Idempotent: re-running init on an existing run must not clobber its state or crash.
    if (run_dir / "state.json").is_file():
        # It also re-prepares nothing, so configuration inputs would be silently dropped.
        if supplied_configuration_inputs(args, workflow=WORKFLOW):
            raise SnapshotError(
                f"run {run_id} already exists; configuration, typed-override, and live-probe "
                "inputs belong to run_state.py prepare, not to re-initialization"
            )
        ensure_runs_root_ignored(runs_root)
        (run_dir / "prompts").mkdir(parents=True, exist_ok=True)
        (run_dir / "reports").mkdir(parents=True, exist_ok=True)
        print(run_dir)
        return 0
    # HITL issues get no worker chain: the orchestrator may assist (checklists,
    # verification, events), but every acting step belongs to the human.
    is_hitl = issue.type.upper() == "HITL"
    prepared_snapshot = None
    configuration_source = None
    if not is_hitl:
        source, prepared_snapshot = snapshot_from_args(
            args,
            run_id=run_id,
            stage="implement",
            pass_num=1,
            config_source=args.config,
        )
        configuration_source = str(source)

    ensure_runs_root_ignored(runs_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompts").mkdir(exist_ok=True)
    (run_dir / "reports").mkdir(exist_ok=True)
    prepared_pointer = persist_snapshot(run_dir, prepared_snapshot) if prepared_snapshot else None
    state = {
        "run_id": run_id,
        "created_at": now,
        "workspace_id": workspace_id,
        "tracker": str(tracker),
        "issue": issue.to_dict(),
        "blocker_status": blocker_status(issue, issues),
        "ready": issue_ready(issue, issues),
        "chain": [] if is_hitl else ["implement", "simplify", "review", "test"],
        "configuration_source": configuration_source,
        "prepared_stage": prepared_pointer,
        "review_strategy": {
            "mode": "self_fix",
            "command": "/code-review medium --fix",
            "delegate_findings_to_implementer": False,
            "unresolved_must_fix_decision": "hitl",
        },
        "worker_wait_policy": {
            "missing_report_gate": "pending",
            "watcher": "await_report.py",
            "file_poll_seconds": 15,
            "health_check_seconds": 60,
            "minimum_wait_minutes": MINIMUM_WAIT_MINUTES,
            "review_note": "Claude Code /code-review medium --fix can legitimately run 15+ minutes.",
            "exhausted_wait_decision": "hitl",
        },
        "current_stage": "hitl" if is_hitl else "implement",
        "gate_decisions": [],
    }
    write_json(run_dir / "state.json", state)
    append_jsonl(run_dir / "events.jsonl", {"time": now, "type": "run.init", "state": state})
    if prepared_pointer:
        append_prepared_event(run_dir, prepared_pointer, prepared_snapshot)
    print(run_dir)
    return 0


def append_prepared_event(run_dir: Path, pointer: dict, snapshot: dict) -> None:
    """Audit trail for a stage that became launchable."""
    stage = pointer["stage"]
    pass_num = pointer["pass"]
    append_jsonl(
        run_dir / "events.jsonl",
        {
            "time": pointer["prepared_at"],
            "type": "stage.prepared",
            "message": f"prepared {stage}-{pass_num} from validated live configuration",
            "data": {
                "stage": stage,
                "pass": pass_num,
                "snapshot_id": pointer["snapshot_id"],
                "snapshot_sha256": pointer["sha256"],
                "config_sha256": snapshot["config"]["sha256"],
            },
        },
    )


def prepare_stage(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise SnapshotError(f"No state.json under {run_dir} — run run_state.py init first")
    state = read_json(state_path)
    if state.get("current_stage") != args.stage:
        raise SnapshotError(
            f"cannot prepare {args.stage}: run current_stage is {state.get('current_stage')!r}"
        )
    if args.pass_num < 1:
        raise SnapshotError("stage pass must be a positive integer")
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise SnapshotError("run has no run id and cannot prepare a worker stage")
    source_text = state.get("configuration_source")
    if not isinstance(source_text, str) or not source_text:
        raise SnapshotError("run has no configuration source and cannot prepare a worker stage")

    # Invalidate first. A failed refresh must never leave a previous snapshot launchable.
    state["prepared_stage"] = None
    state["updated_at"] = utc_now()
    write_json(state_path, state)

    _, snapshot = snapshot_from_args(
        args,
        run_id=run_id,
        stage=args.stage,
        pass_num=args.pass_num,
        config_source=source_text,
    )
    pointer = persist_snapshot(run_dir, snapshot)
    # Preflight spans minutes of external probes, so re-read instead of writing the dict this
    # command started from: a gate recorded meanwhile must not be erased, and a stage the run has
    # already left must not become launchable.
    state = read_json(state_path)
    if state.get("current_stage") != args.stage:
        raise SnapshotError(
            f"run moved to {state.get('current_stage')!r} while {args.stage} was being prepared; "
            "prepare the current stage instead"
        )
    state["prepared_stage"] = pointer
    state["updated_at"] = pointer["prepared_at"]
    write_json(state_path, state)
    append_prepared_event(run_dir, pointer, snapshot)
    print(json.dumps(pointer, sort_keys=True))
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
    # Refresh the issue snapshot; state.json must not keep claiming todo/0-of-n forever.
    issues = load_issues(Path(state["tracker"]))
    issue_id = state["issue"]["id"]
    if issue_id in issues:
        state["issue"] = issues[issue_id].to_dict()
        state["blocker_status"] = blocker_status(issues[issue_id], issues)
    state["current_stage"] = "done"
    state["updated_at"] = now
    write_json(state_path, state)
    append_jsonl(
        run_dir / "events.jsonl",
        {
            "time": now,
            "type": "run.completed",
            "message": args.message,
            "data": {
                "issue": issue_id,
                "status": state["issue"]["status"],
                "progress": state["issue"]["progress"],
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
