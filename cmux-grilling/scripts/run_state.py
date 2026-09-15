#!/usr/bin/env python3
"""Create and append cmux-grilling run state."""

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
    durable_publish,
    parse_overrides,
    probe_options,
    resolve_config_source,
    supplied_configuration_inputs,
)
from launch_wave import (
    LaunchWaveError,
    WORKFLOW,
    build_launch_wave,
    persist_launch_wave,
)
from orchestrator_lib import (
    LANE_WAIT_MINUTES,
    LANES,
    append_jsonl,
    first_line,
    read_json,
    read_run_state,
    read_text,
    run_identifier,
    slugify,
    utc_now,
    write_json,
)


# Must stay in sync with parse_research_report.py's gate values.
GATE_DECISIONS = ["advance", "stop", "blocked", "hitl", "pending"]

# Artifacts live next to the tracker's issues/, so a workspace keeps one place for its
# orchestration output. Without a tracker the run still needs a home.
GRILLING_DIRNAME = "grilling"
TRACKER_ROOT = ".scratch"
NO_TRACKER_OUTPUT_DIR = f"{TRACKER_ROOT}/{GRILLING_DIRNAME}"

# open_decisions schema (SKILL.md, Finalize and Artifact). A decision is a fork the research
# deliberately cannot close; an assumption is settled. Statuses are exhaustive.
DECISION_STATUSES = ["open", "decided", "deferred"]
DECISION_WHY_OPEN = ["product", "spec-deviation", "tie"]
DECISION_REQUIRED_FIELDS = (
    "id",
    "question",
    "why_open",
    "context",
    "evidence",
    "options",
    "recommendation",
    "rationale",
    "status",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create run directory and initial state")
    task_source = init.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task", help="Task text: the plan plus its fixed constraints")
    task_source.add_argument("--task-file", help="File containing the task text")
    init.add_argument("--slug", help="Artifact slug: lowercase words separated by hyphens, at most 30 characters")
    init.add_argument("--run-id", help="Stable run id. Defaults to grill-<slug>-<YYYY-MM-DD>-<HHMM> (UTC)")
    init.add_argument("--runs-root", default=f"{TRACKER_ROOT}/orchestrator/runs")
    init.add_argument("--max-questions", type=int, default=10)
    init.add_argument("--tracker", help=f"Tracker directory, e.g. {TRACKER_ROOT}/<tracker>. Autodetected when omitted")
    init.add_argument("--output-dir", help="Override where the final artifact pair lands. Default <tracker>/grilling")
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
    complete.add_argument("--markdown", required=True, help="Final Markdown path under output_dir")
    complete.add_argument("--json", required=True, help="Final JSON path under output_dir")
    complete.add_argument("--message", default="grilling session complete")
    complete.add_argument("--data", help="Optional JSON object, e.g. artifact paths and stop reason")

    decision = subparsers.add_parser("decision", help="Record the outcome of one open decision in the artifact JSON")
    decision.add_argument("--run-dir", required=True)
    decision.add_argument("--artifact", required=True, help="Path to the artifact JSON holding open_decisions")
    decision.add_argument("--id", required=True, help='Decision id, e.g. "D1"')
    decision.add_argument("--status", choices=["decided", "deferred"], required=True)
    decision.add_argument("--decision", required=True, help="What the human chose, or why it was deferred")

    validate = subparsers.add_parser("validate-artifact", help="Check an artifact's open_decisions against the schema")
    validate.add_argument("--artifact", required=True)

    pending = subparsers.add_parser(
        "pending-decisions",
        help="Print unresolved decisions of the newest artifact. Resolves its directory like init",
    )
    pending.add_argument("--tracker", help="Tracker directory. Autodetected when omitted")
    pending.add_argument("--output-dir", help="Override the directory to look in")

    status = subparsers.add_parser("status", help="Inspect state read-only, including legacy runs")
    status.add_argument("--run-dir", required=True)

    return parser


def run_command(args: argparse.Namespace) -> int:
    if args.command == "status":
        run_dir = Path(args.run_dir)
        state = read_json(run_dir / "state.json")
        try:
            read_run_state(run_dir)
            diagnostic = None
        except SystemExit as error:
            diagnostic = str(error)
        print(json.dumps({"state": state, "unsupported_layout": diagnostic}, indent=2))
        return 0
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
    if args.command == "decision":
        return record_decision(args)
    if args.command == "validate-artifact":
        return validate_artifact(args)
    if args.command == "pending-decisions":
        return print_pending_decisions(args)
    raise AssertionError(args.command)


def main() -> int:
    try:
        return run_command(build_parser().parse_args())
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        print(f"run state operation failed: {error}", file=sys.stderr)
        return 1


def ensure_runs_root_ignored(runs_root: Path) -> None:
    """Run state is ephemeral lifecycle data; keep it out of git in every target repo."""
    runs_root.mkdir(parents=True, exist_ok=True)
    ignore = runs_root / ".gitignore"
    # Keep the is_file guard: a directory here must fail, not leave runs git-visible.
    if not ignore.is_file():
        durable_publish(ignore, b"*\n", mode=0o644, suffix=".tmp", publish=os.replace)


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


def detect_tracker(root: Path) -> Path | None:
    """Autodetect the tracker as a convenience, never as a guess.

    Exactly one `.scratch/*/issues/` is unambiguous. Several are not, and picking one would
    scatter artifacts across trackers, so that case is a hard stop asking for --tracker.
    """
    candidates = sorted(path.parent for path in root.glob(f"{TRACKER_ROOT}/*/issues") if path.is_dir())
    if len(candidates) > 1:
        listed = ", ".join(str(path) for path in candidates)
        raise SystemExit(f"Several trackers found ({listed}); pass --tracker to pick one.")
    return candidates[0] if candidates else None


def resolve_output(args: argparse.Namespace, root: Path = Path(".")) -> tuple[Path | None, Path]:
    """Return (tracker, output_dir). --output-dir > --tracker > autodetect > no-tracker fallback.

    Grilling a free-standing plan without any tracker must stay possible, hence the fallback.
    """
    tracker = Path(args.tracker) if args.tracker else None
    if args.output_dir:
        return tracker, Path(args.output_dir)
    tracker = tracker or detect_tracker(root)
    if tracker is None:
        return None, Path(NO_TRACKER_OUTPUT_DIR)
    return tracker, tracker / GRILLING_DIRNAME


def validate_decision(entry: object) -> list[str]:
    """Check one open_decisions entry against the schema; returns the problems found."""
    if not isinstance(entry, dict):
        return ["entry is not an object"]
    problems = []
    for field in DECISION_REQUIRED_FIELDS:
        if not entry.get(field):
            problems.append(f"missing or empty field: {field}")
    if entry.get("why_open") and entry["why_open"] not in DECISION_WHY_OPEN:
        problems.append(f"why_open must be one of {'|'.join(DECISION_WHY_OPEN)}")
    if entry.get("status") and entry["status"] not in DECISION_STATUSES:
        problems.append(f"status must be one of {'|'.join(DECISION_STATUSES)}")
    evidence = entry.get("evidence")
    if evidence is not None and (not isinstance(evidence, list) or not all(isinstance(item, str) and item.strip() for item in evidence)):
        problems.append("evidence must be a list of non-empty strings")
    options = entry.get("options")
    if options is not None:
        if not isinstance(options, list) or len(options) < 2:
            problems.append("options must be a list with at least two entries")
        else:
            for index, option in enumerate(options):
                if not isinstance(option, dict) or not option.get("label") or not option.get("implication"):
                    problems.append(f"option {index} needs a label and an implication")
    if entry.get("status") in ("decided", "deferred") and not entry.get("decision"):
        problems.append("a decided or deferred entry needs a decision")
    return problems


def init_run(args: argparse.Namespace) -> int:
    if args.max_questions < 1:
        raise SystemExit("--max-questions must be >= 1")
    workspace_id = resolve_workspace_id(args)
    task_text = read_text(Path(args.task_file)) if args.task_file else args.task
    task_text = task_text.strip()
    if not task_text:
        raise SystemExit("Task text is empty")
    slug = args.slug if args.slug is not None else slugify(first_line(task_text))
    if len(slug) > 30 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise SystemExit("--slug must match [a-z0-9]+(?:-[a-z0-9]+)* and be at most 30 characters")
    now = utc_now()
    # grill-<slug>-<YYYY-MM-DD>-<HHMM> (UTC): readable, sortable, never reused across runs.
    run_id = args.run_id or run_identifier("grill", slug, now)
    runs_root = Path(args.runs_root)
    run_dir = runs_root / run_id
    overrides = parse_overrides(args, workflow=WORKFLOW)
    # Idempotent: re-running init on an existing run must not clobber its state or crash.
    if (run_dir / "state.json").is_file():
        read_run_state(run_dir)
        # A grilling run has one immutable wave. Accepting these inputs here would pretend
        # to apply them while retaining the old cohort, so require a new run instead.
        if supplied_configuration_inputs(args, workflow=WORKFLOW):
            raise LaunchWaveError(
                f"run {run_id} already exists; configuration, typed-override, and live-probe "
                "inputs require a new grilling run"
            )
        ensure_runs_root_ignored(runs_root)
        for name in ("prompts", "reports", "drafts", "synthesis"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        print(run_dir)
        return 0
    # After the idempotent exit: a re-init must not re-detect, let alone stop on an ambiguity
    # that appeared after this run already recorded its output directory.
    tracker, output_dir = resolve_output(args)
    probe_profiles, probe_timeout = probe_options(args)
    source, agents, config_sha256 = resolve_config_source(args.config)
    launch_wave = build_launch_wave(
        run_id=run_id,
        source=source,
        config_sha256=config_sha256,
        data=agents,
        overrides=overrides,
        probe_profiles=probe_profiles,
        probe_timeout_seconds=probe_timeout,
    )

    # Publish only after every lane has resolved and every unique assigned executable has
    # passed local preflight. A failure above leaves no launchable state for pane_ctl.py.
    ensure_runs_root_ignored(runs_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in ("prompts", "reports", "drafts", "synthesis"):
        (run_dir / name).mkdir(exist_ok=True)
    (run_dir / "task.md").write_text(task_text + "\n", encoding="utf-8")
    launch_wave_pointer = persist_launch_wave(run_dir, launch_wave)
    state = {
        "run_id": run_id,
        "workflow": "grilling",
        "layout_version": 1,
        "deliverables": {},
        "created_at": now,
        "workspace_id": workspace_id,
        "task_file": "task.md",
        "slug": slug,
        "max_questions": args.max_questions,
        "tracker": str(tracker) if tracker else None,
        "output_dir": str(output_dir),
        "lanes": {name: dict(config) for name, config in LANES.items()},
        "configuration_source": str(source),
        "launch_wave": launch_wave_pointer,
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
    append_jsonl(
        run_dir / "events.jsonl",
        {
            "time": launch_wave_pointer["prepared_at"],
            "type": "launch_wave.prepared",
            "message": "prepared all four persistent research lanes from validated configuration",
            "data": {
                "snapshot_id": launch_wave_pointer["snapshot_id"],
                "snapshot_sha256": launch_wave_pointer["sha256"],
                "config_sha256": launch_wave["config"]["sha256"],
                "lanes": list(LANES),
            },
        },
    )
    print(run_dir)
    return 0


def append_event(args: argparse.Namespace) -> int:
    read_run_state(Path(args.run_dir))
    data = json.loads(args.data) if args.data else {}
    if not isinstance(data, dict):
        raise SystemExit("--data must be a JSON object")
    append_jsonl(
        Path(args.run_dir) / "events.jsonl",
        {"time": utc_now(), "type": args.type, "message": args.message, "data": data},
    )
    return 0


def append_gate(args: argparse.Namespace) -> int:
    read_run_state(Path(args.run_dir))
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
        state = read_run_state(run_dir)
        state.setdefault("gate_decisions", []).append(event)
        state["current_stage"] = args.next_stage or args.stage
        state["updated_at"] = event["time"]
        write_json(state_path, state)
    return 0


def append_snapshot(args: argparse.Namespace) -> int:
    read_run_state(Path(args.run_dir))
    def git(*argv: str) -> bytes:
        # Diffs can contain non-UTF-8 bytes; replacement decoding loses fingerprint input.
        result = subprocess.run(["git", *argv], capture_output=True)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise SystemExit(f"git {' '.join(argv)} failed: {detail}")
        return result.stdout

    head = git("rev-parse", "HEAD").decode("ascii").strip()
    status = git("status", "--porcelain")
    # Covers tracked-file changes plus the untracked-file listing; untracked *content* is not hashed.
    diff = git("diff") + git("diff", "--cached")
    fingerprint = hashlib.sha256(status + diff).hexdigest()[:16]

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
    state = read_run_state(run_dir)
    now = utc_now()
    data = json.loads(args.data) if args.data else {}
    if not isinstance(data, dict):
        raise SystemExit("--data must be a JSON object")
    output_dir = Path(state["output_dir"]).resolve()
    deliverables = {"markdown": str(Path(args.markdown).resolve()), "json": str(Path(args.json).resolve())}
    if any(not Path(path).is_relative_to(output_dir) or Path(path) == output_dir for path in deliverables.values()):
        raise SystemExit("--markdown and --json must resolve under the run output_dir")
    state["deliverables"] = deliverables
    data["deliverables"] = deliverables
    state["current_stage"] = "done"
    state["updated_at"] = now
    write_json(state_path, state)
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": now, "type": "run.completed", "message": args.message, "data": data},
    )
    return 0


def record_decision(args: argparse.Namespace) -> int:
    """Write one decision outcome into the artifact JSON and log it.

    The artifact pair is written before the walkthrough, so this edits a finished file:
    id must exist, and the entry must still validate afterwards.
    """
    read_run_state(Path(args.run_dir))
    artifact_path = Path(args.artifact)
    artifact = read_json(artifact_path)
    decisions = artifact.get("open_decisions")
    if not isinstance(decisions, list):
        raise SystemExit(f"{artifact_path} has no open_decisions list")
    entry = next((item for item in decisions if isinstance(item, dict) and item.get("id") == args.id), None)
    if entry is None:
        known = ", ".join(str(item.get("id")) for item in decisions if isinstance(item, dict)) or "none"
        raise SystemExit(f"No decision {args.id} in {artifact_path} (known ids: {known})")
    now = utc_now()
    entry["status"] = args.status
    entry["decision"] = args.decision
    entry["decided_at"] = now
    problems = validate_decision(entry)
    if problems:
        raise SystemExit(f"Decision {args.id} violates the schema: {'; '.join(problems)}")
    write_json(artifact_path, artifact)
    append_jsonl(
        Path(args.run_dir) / "events.jsonl",
        {
            "time": now,
            "type": "grill.decision_recorded",
            "message": f"{args.id}: {args.status}",
            "data": {"id": args.id, "status": args.status, "decision": args.decision, "artifact": str(artifact_path)},
        },
    )
    # Printed ready to paste: the Markdown half of the pair is transcribed, not recomposed.
    print(f"{args.id} {args.status}\nAusgang ({args.status}): {args.decision}")
    return 0


def validate_artifact(args: argparse.Namespace) -> int:
    """Check every open_decisions entry where they are authored: at finalize.

    Enforcing the schema only when an answer is recorded would surface a thin entry mid
    walkthrough, when the rounds are gone and nobody can repair it.
    """
    artifact_path = Path(args.artifact)
    decisions = read_json(artifact_path).get("open_decisions")
    if not isinstance(decisions, list):
        raise SystemExit(f"{artifact_path} has no open_decisions list")
    problems = [
        f"{entry.get('id') if isinstance(entry, dict) else f'entry {index}'}: {problem}"
        for index, entry in enumerate(decisions)
        for problem in validate_decision(entry)
    ]
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"open_decisions={len(decisions)} valid")
    return 0


def artifact_decisions(path: Path) -> list | None:
    """The artifact's decisions, or None if this JSON file is not an artifact at all."""
    try:
        data = read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("open_decisions"), list):
        return None
    return data["open_decisions"]


def print_pending_decisions(args: argparse.Namespace) -> int:
    """Report unresolved decisions of the newest artifact, for the resume offer at session start.

    `open` and `deferred` stay apart: a deferred point was closed on purpose, so only the
    open ones make the offer urgent.
    """
    _, output_dir = resolve_output(args)
    artifacts = {path: decisions for path in output_dir.glob("*.json") if (decisions := artifact_decisions(path)) is not None}
    if not artifacts:
        print(f"dir={output_dir} artifact=none open=none deferred=none")
        return 0
    newest = max(artifacts, key=lambda path: (path.stat().st_mtime, path.name))

    def ids(status: str) -> str:
        listed = [item["id"] for item in artifacts[newest] if isinstance(item, dict) and item.get("status") == status]
        return ",".join(listed) if listed else "none"

    print(f"dir={output_dir} artifact={newest} open={ids('open')} deferred={ids('deferred')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
