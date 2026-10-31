#!/usr/bin/env python3
"""Create and append cmux-grilling run state."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from artifact_pair import (ASSUMPTION_REVIEW, PREMISE_CORRECTION_REVIEW, extension_summary, markdown_path,
                           render_review, single_line, validate_extension, validate_extension_data,
                           validate_review)
from transcribe_artifact import decision_outcome, transcribe
from render_artifact import render_protocol

from run_briefing import BoardPublication, publish_board
from run_commit import capture_baseline
from agents_config import (
    ConfigError,
    add_override_options,
    add_probe_options,
    durable_publish,
    git_root,
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
    read_json,
    read_run_state,
    read_text,
    run_identifier,
    utc_now,
    write_json,
)


# Must stay in sync with parse_research_report.py's gate values.
GATE_DECISIONS = ["advance", "stop", "blocked", "hitl", "pending"]

GRILLING_DIRNAME = "grilling"
TRACKER_ROOT = ".scratch"

# open_decisions schema (SKILL.md, Finalize and Artifact). A decision is a fork the research
# deliberately cannot close; an assumption is settled. Statuses are exhaustive.
DECISION_STATUSES = ["open", "decided", "deferred"]
DECISION_WHY_OPEN = ["product", "spec-deviation", "tie"]
CUSTOM_DECISION_MARK = "[custom] "
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


RUN_SUBDIRS = ("prompts", "reports", "drafts", "synthesis")


REVIEW_COMMANDS = {
    "assumption-review": (ASSUMPTION_REVIEW, "grill.assumptions_triaged"),
    "premise-correction-review": (PREMISE_CORRECTION_REVIEW, "grill.premise_corrections_triaged"),
}


PUBLISHING_COMMANDS = ("init", "event", "gate", "snapshot", "complete", "decision", *REVIEW_COMMANDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create run directory and initial state")
    init.add_argument("--commit-mode", choices=["commit", "propose"], default=None)
    task_source = init.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task", help="Task text: the plan plus its fixed constraints")
    task_source.add_argument("--task-file", help="File containing the task text")
    init.add_argument("--feature", help="Approved YYYY-MM-DD-<slug> folder directly in repository .scratch/")
    init.add_argument("--run-id", help="Stable run id. Defaults to YYYY-MM-DD-HHMM-grill-<slug> (local time)")
    init.add_argument("--runs-root", default=f"{TRACKER_ROOT}/orchestrator/runs")
    init.add_argument("--max-rounds", type=int, default=4, help="Round budget; each round asks the whole frontier")
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
    complete.add_argument("--markdown", required=True, help="Frozen <feature>/grilling/<timestamp>.md path")
    complete.add_argument("--json", required=True, help="Frozen <feature>/grilling/<timestamp>.json path")
    complete.add_argument("--message", default="grilling session complete")
    complete.add_argument("--data", help="Optional JSON object, e.g. artifact paths and stop reason")

    decision = subparsers.add_parser("decision", help="Record the outcome of one open decision in the artifact JSON")
    decision.add_argument("--run-dir", required=True)
    decision.add_argument("--artifact", required=True, help="Path to the artifact JSON holding open_decisions")
    decision.add_argument("--id", required=True, help='Decision id, e.g. "D1"')
    decision.add_argument("--status", choices=["decided", "deferred"], required=True)
    decision.add_argument("--decision", required=True, help="Selection traceability only: decided requires an exact option label or '[custom] <choice>'; deferred is free text. This does not prove the chosen option resolves missing facts")

    for command, (review_list, _) in REVIEW_COMMANDS.items():
        item = review_list.item_name
        review = subparsers.add_parser(command, help=f"Record one human {item} review and print its Markdown line")
        review.add_argument("--run-dir", required=True)
        review.add_argument("--artifact", required=True)
        review.add_argument("--index", type=int, required=True, help=f"One-based {item} index")
        review.add_argument("--outcome", choices=["confirmed", "corrected", "discarded"], required=True)
        review.add_argument("--corrected-text", default="")
        review.add_argument("--reason", default="")

    validate = subparsers.add_parser("validate-artifact", help="Check decisions and the review/open-fact Markdown+JSON pair")
    validate.add_argument("--artifact", required=True)

    transcribe = subparsers.add_parser("transcribe-artifact", help="Validate and transcribe recorded JSON outcomes into Markdown")
    transcribe.add_argument("--artifact", required=True)

    render = subparsers.add_parser("render-artifact", help="Render the Markdown protocol from JSON and round syntheses")
    render.add_argument("--run-dir", required=True)
    render.add_argument("--artifact", required=True)
    render.add_argument("--title", help="Protocol title; defaults to the task")
    render.add_argument("--overwrite", action="store_true", help="Explicitly replace an existing Markdown protocol")

    subparsers.add_parser(
        "pending-decisions",
        help="Print unfinished walkthrough items from the newest artifact across all .scratch/*/grilling/ feature directories",
    )

    status = subparsers.add_parser("status", help="Inspect state read-only, including legacy runs")
    status.add_argument("--run-dir", required=True)

    for name in PUBLISHING_COMMANDS:
        subparsers.choices[name].add_argument("--cmux-cmd", help=argparse.SUPPRESS)
    return parser


def run_command(args: argparse.Namespace) -> int:
    if args.command == "status":
        run_dir = Path(args.run_dir)
        state = read_json(run_dir / "state.json")
        if isinstance(state, dict):
            state.setdefault("commit_mode", "propose")
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
    if args.command in REVIEW_COMMANDS:
        return record_review(args, *REVIEW_COMMANDS[args.command])
    if args.command == "validate-artifact":
        return validate_artifact(args)
    if args.command == "transcribe-artifact":
        return transcribe_artifact(args)
    if args.command == "render-artifact":
        return render_artifact(args)
    if args.command == "pending-decisions":
        return print_pending_decisions(args)
    raise AssertionError(args.command)


def run(args: argparse.Namespace) -> int:
    if args.command not in PUBLISHING_COMMANDS:
        return run_command(args)
    run_dir = Path(args.run_dir) if args.command != "init" else None
    with BoardPublication(run_dir, args.cmux_cmd, publisher=publish_board) as args._board_publication:
        return run_command(args)


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        print(f"run state operation failed: {error}", file=sys.stderr)
        return 1


def refuse_runs_root_in_skill(runs_root: Path) -> None:
    skill = Path(__file__).resolve().parent.parent
    if runs_root.resolve().is_relative_to(skill):
        raise SystemExit(
            f"runs root {runs_root.resolve()} lies inside the skill directory {skill}; "
            "run init from the target repository root, not from the skill directory"
        )


def ensure_runs_root_ignored(runs_root: Path, repository: Path) -> None:
    """Ignore all standard orchestrator internals, or only a custom runs root."""
    runs_root = runs_root.resolve()
    standard = (repository / ".scratch" / "orchestrator" / "runs").resolve()
    ignore_root = runs_root.parent if runs_root == standard else runs_root
    runs_root.mkdir(parents=True, exist_ok=True)
    ignore = ignore_root / ".gitignore"
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


def checked_feature(repository: Path, value: str) -> tuple[Path, str]:
    raw = Path(value)
    if ".." in raw.parts:
        raise ConfigError("--feature must not contain path traversal")
    candidate = (repository / ".scratch" / raw if len(raw.parts) == 1
                 else raw if raw.is_absolute() else repository / raw)
    feature = candidate.resolve()
    scratch = repository / ".scratch"
    if (scratch.resolve() != scratch or feature.parent != scratch
            or candidate.is_symlink()):
        raise ConfigError("--feature must be a direct folder in repository .scratch/")
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)", feature.name)
    if not match or len(match[2]) > 30:
        raise ConfigError("--feature must be YYYY-MM-DD-<slug>, with a lowercase kebab-case slug of at most 30 characters")
    try:
        date.fromisoformat(match[1])
    except ValueError as error:
        raise ConfigError("--feature must contain a valid calendar date") from error
    return feature, match[2]


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
    if args.max_rounds < 1:
        raise SystemExit("--max-rounds must be >= 1")
    workspace_id = resolve_workspace_id(args)
    task_text = read_text(Path(args.task_file)) if args.task_file else args.task
    task_text = task_text.strip()
    if not task_text:
        raise SystemExit("Task text is empty")
    if args.feature is None:
        raise ConfigError("init requires --feature")
    repository = git_root(Path.cwd())
    feature, slug = checked_feature(repository, args.feature)
    if feature.exists() and not feature.is_dir():
        raise ConfigError("--feature must name a folder, not a file")
    now = utc_now()
    timestamp = datetime.fromisoformat(now).astimezone().strftime("%Y-%m-%d-%H%M")
    # YYYY-MM-DD-HHMM-grill-<slug> (local time): readable and chronologically sortable.
    run_id = args.run_id or run_identifier("grill", slug, now)
    runs_root = Path(args.runs_root)
    refuse_runs_root_in_skill(runs_root)
    run_dir = runs_root / run_id
    args._board_publication.bind(run_dir)
    overrides = parse_overrides(args, workflow=WORKFLOW)
    # Idempotent: re-running init on an existing run must not clobber its state or crash.
    if (run_dir / "state.json").is_file():
        existing = read_run_state(run_dir)
        if existing.get("feature_dir") != str(feature):
            raise ConfigError("re-initialization cannot change the feature folder")
        stored_mode = existing.get("commit_mode", "propose")
        if args.commit_mode is not None and args.commit_mode != stored_mode:
            raise SystemExit(
                f"run {run_id} already exists with commit mode {stored_mode}; "
                f"--commit-mode {args.commit_mode} cannot change it"
            )
        # A grilling run has one immutable wave. Accepting these inputs here would pretend
        # to apply them while retaining the old cohort, so require a new run instead.
        if supplied_configuration_inputs(args, workflow=WORKFLOW):
            raise LaunchWaveError(
                f"run {run_id} already exists; configuration, typed-override, and live-probe "
                "inputs require a new grilling run"
            )
        ensure_runs_root_ignored(runs_root, repository)
        for name in RUN_SUBDIRS:
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        print(run_dir)
        return 0
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
    try:
        commit_baseline = capture_baseline(Path.cwd())
    except ValueError as error:
        raise SystemExit(f"cannot record the commit baseline: {error}") from error
    ensure_runs_root_ignored(runs_root, repository)
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in RUN_SUBDIRS:
        (run_dir / name).mkdir(exist_ok=True)
    (run_dir / "task.md").write_text(task_text + "\n", encoding="utf-8")
    launch_wave_pointer = persist_launch_wave(run_dir, launch_wave)
    state = {
        "run_id": run_id,
        "workflow": "grilling",
        "commit_baseline": commit_baseline,
        "working_directory": str(Path.cwd()),
        "commit_mode": args.commit_mode or "propose",
        "layout_version": 2,
        "deliverables": {},
        "created_at": now,
        "workspace_id": workspace_id,
        "task_file": "task.md",
        "slug": slug,
        "max_rounds": args.max_rounds,
        "feature_dir": str(feature),
        "timestamp": timestamp,
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
            "message": "prepared the reusable four-lane launch wave from validated configuration",
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
    if args.type.startswith("commit."):
        raise SystemExit("commit events are recorded by run_commit.py")
    read_run_state(Path(args.run_dir))
    data = json.loads(args.data) if args.data else {}
    if not isinstance(data, dict):
        raise SystemExit("--data must be a JSON object")
    if args.type == "report.reformat_requested":
        from watch_deadlines import reformat_data
        from worker_readiness import read_events
        from orchestrator_lib import round_report_path
        identity = {"round": data.get("round"), "lane": data.get("lane")}
        if (identity["lane"] not in LANES
                or type(identity["round"]) is not int or identity["round"] < 1):
            raise SystemExit("report.reformat_requested requires a positive round and valid lane")
        report = round_report_path(Path(args.run_dir), identity["round"], identity["lane"])
        try:
            data.update(reformat_data(read_events(Path(args.run_dir)), identity, report))
        except ValueError as error:
            raise SystemExit(str(error)) from error
    if args.type == "grill.question":
        from round_context import recorded_questions, validate_question
        from worker_readiness import read_events
        events = read_events(Path(args.run_dir))
        try:
            validate_question(data, events)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        if recorded_questions(events, data["round"], data["id"]):
            raise SystemExit(f"grill.question R{data['round']}{data['id']} is already recorded; use a new id")
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


UNTRACKED_HASH_LIMIT_BYTES = 8 * 1024 * 1024


def untracked_content(repository: Path, raw: bytes) -> tuple[list[tuple[str, str]], dict[str, dict[str, str]], bytes]:
    """Parse NUL-delimited status and hash bounded untracked content without decoding file bytes.

    Vendored identically across the three independently installed skills.
    Rename/copy source tokens are paths, never independent status entries.
    """
    tokens = raw.split(b"\0")
    entries = []
    states = {}
    hashed = []
    index = 0
    while index < len(tokens) and tokens[index]:
        token = tokens[index]
        if len(token) < 4 or token[2:3] != b" ":
            raise ValueError("git status returned an unparseable porcelain entry")
        code = token[:2].decode("ascii")
        path_bytes = token[3:]
        path = os.fsdecode(path_bytes)
        entries.append((code, path))
        index += 1
        if "R" in code or "C" in code:
            if index >= len(tokens) or not tokens[index]:
                raise ValueError("git status rename/copy entry is incomplete")
            entries.append((code, os.fsdecode(tokens[index])))
            index += 1
        if code != "??":
            continue
        absolute = os.path.join(os.fsencode(repository), path_bytes)
        # Fail closed: an unreadable or vanished path is never silently treated as skipped.
        try:
            info = os.lstat(absolute)
            if stat.S_ISLNK(info.st_mode):
                content = os.readlink(absolute)
            elif stat.S_ISREG(info.st_mode):
                if info.st_size > UNTRACKED_HASH_LIMIT_BYTES:
                    states[path] = {"skipped": "size exceeds 8 MiB limit"}
                    continue
                with open(absolute, "rb") as stream:
                    content = stream.read(UNTRACKED_HASH_LIMIT_BYTES + 1)
                if len(content) > UNTRACKED_HASH_LIMIT_BYTES:
                    states[path] = {"skipped": "size exceeds 8 MiB limit"}
                    continue
            else:
                states[path] = {"skipped": "unsupported file type"}
                continue
        except OSError as error:
            raise ValueError(
                f"cannot hash untracked path {path!r}: {error.strerror or error}; integrity capture is "
                "incomplete, so restore read access or remove the path and retry"
            ) from error
        digest = hashlib.sha256(content).hexdigest()
        states[path] = {"content_sha256": digest}
        hashed.append((path_bytes, digest.encode("ascii")))
    block = b"".join(path + b"\0" + digest + b"\n" for path, digest in sorted(hashed))
    return entries, states, block


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
    repository = Path(os.fsdecode(git("rev-parse", "--show-toplevel").removesuffix(b"\n")))
    status = git("-C", str(repository), "status", "--porcelain=v1", "-z", "--untracked-files=all")
    try:
        entries, untracked, untracked_block = untracked_content(repository, status)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    # Raw binary diffs and bounded untracked content cover Git-visible tree changes.
    diff = git("diff", "--binary", "--no-ext-diff")
    cached_diff = git("diff", "--cached", "--binary", "--no-ext-diff")
    digest = hashlib.sha256()
    for block in (status, diff, cached_diff, untracked_block):
        digest.update(block)
    fingerprint = digest.hexdigest()[:16]

    data = json.loads(args.data) if args.data else {}
    if not isinstance(data, dict):
        raise SystemExit("--data must be a JSON object")
    data.update({
        "head": head, "fingerprint": fingerprint,
        "dirty_paths": len({path for _, path in entries}),
        "staged_paths": sorted({path for code, path in entries if code[0] not in " ?"}),
        "staged_diff_sha256": hashlib.sha256(cached_diff).hexdigest(),
        "untracked_hashed": sum("content_sha256" in value for value in untracked.values()),
        "untracked_skipped": [
            {"path": path, "reason": value["skipped"]}
            for path, value in sorted(untracked.items()) if "skipped" in value
        ],
    })
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
    if "feature_dir" not in state or "timestamp" not in state:
        raise SystemExit(f"unsupported legacy layout in {run_dir}; inspect read-only and restart the run")
    feature = Path(state["feature_dir"])
    output_dir = feature / GRILLING_DIRNAME
    if feature.is_symlink() or output_dir.is_symlink():
        raise SystemExit("the frozen feature folder and its grilling/ directory must not be symlinks")
    deliverables = {"markdown": str(Path(args.markdown).resolve()), "json": str(Path(args.json).resolve())}
    expected = {key: str((output_dir / (state["timestamp"] + suffix)).resolve())
                for key, suffix in (("markdown", ".md"), ("json", ".json"))}
    if deliverables != expected:
        raise SystemExit("--markdown and --json must match the frozen feature folder and timestamp pair")
    if any(not Path(path).is_file() for path in deliverables.values()):
        raise SystemExit("the frozen artifact pair must exist before complete")
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
    if args.status == "decided":
        labels = [option["label"] for option in entry["options"]]
        custom = args.decision.startswith(CUSTOM_DECISION_MARK) and args.decision[len(CUSTOM_DECISION_MARK):].strip()
        if args.decision not in labels and not custom:
            raise SystemExit(
                f"Decision {args.id}: selection traceability requires an exact option label "
                f"(known labels: {', '.join(repr(label) for label in labels)}) "
                "or '[custom] <non-empty choice>'"
            )
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
    if publication := getattr(args, "_board_publication", None):
        publication.force = True
    # Printed ready to paste: the Markdown half of the pair is transcribed, not recomposed.
    print(f"{args.id} {args.status}\n{decision_outcome(entry)}")
    return 0


def check_artifact_json(artifact: object, separator: str) -> None:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("open_decisions"), list):
        raise ValueError("artifact must contain an open_decisions list")
    if problems := decision_problems(artifact["open_decisions"]) + validate_extension_data(artifact):
        raise ValueError(separator.join(problems))


def markdown_target(target: object) -> Path:
    if not single_line(target):
        raise ValueError("markdownPath must be a non-empty path")
    return Path(target).expanduser()


def render_artifact(args: argparse.Namespace) -> int:
    artifact_path = Path(args.artifact)
    try:
        read_run_state(Path(args.run_dir))
        artifact = read_json(artifact_path)
        check_artifact_json(artifact, "\n")
        path = markdown_target(markdown_path(artifact, artifact_path))
        if path.resolve() == artifact_path.resolve():
            raise ValueError("markdownPath must differ from the JSON path")
        if path.exists() and not args.overwrite:
            raise ValueError("Markdown already exists; pass --overwrite to replace recorded edits")
        candidate = render_protocol(artifact, Path(args.run_dir), args.title)
        if problems := validate_extension(artifact, artifact_path, candidate):
            raise ValueError("\n".join(problems))
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        # A hard-link publication refuses a racing creation too; overwrite is opt-in.
        durable_publish(path, candidate.encode("utf-8"), mode=mode, suffix=".tmp",
                        publish=os.replace if args.overwrite else os.link)
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as error:
        raise SystemExit(f"rendering refused: {error}") from error
    validate_artifact(args)
    print(f"markdown={path} rendered valid")
    return 0


def transcribe_artifact(args: argparse.Namespace) -> int:
    artifact_path = Path(args.artifact)
    artifact = read_json(artifact_path)
    try:
        # Validate JSON before rendering; Markdown disagreements are expected at this point.
        check_artifact_json(artifact, "; ")
        path = markdown_target(markdown_path(artifact, artifact_path))
        original = path.read_bytes()
        candidate = transcribe(artifact, original.decode("utf-8"))
        if problems := validate_extension(artifact, artifact_path, candidate):
            raise ValueError("; ".join(problems))
        payload = candidate.encode("utf-8")
        if payload != original:
            durable_publish(path, payload, mode=stat.S_IMODE(path.stat().st_mode),
                            suffix=".tmp", publish=os.replace)
    except (ValueError, UnicodeError) as error:
        raise SystemExit(f"transcription refused: {error}") from error
    print(f"markdown={path} transcribed valid")
    return 0


def record_review(args: argparse.Namespace, review_list, event_type: str) -> int:
    """Persist a review before transcription; pair validation detects an interrupted edit."""
    run_dir = Path(args.run_dir)
    read_run_state(run_dir)
    artifact_path = Path(args.artifact)
    artifact = read_json(artifact_path)
    texts = artifact.get(review_list.texts_name)
    reviews = artifact.get(review_list.name)
    if not isinstance(texts, list) or not 1 <= args.index <= len(texts):
        raise SystemExit(f"Unknown {review_list.item_name} index {args.index} in {artifact_path}")
    if not isinstance(reviews, list) or len(reviews) != len(texts):
        raise SystemExit(f"{review_list.name} must have one entry per {review_list.item_name}")
    for index, entry in enumerate(reviews, 1):
        if problems := validate_review(entry, index, review_list):
            raise SystemExit("; ".join(problems))
    if args.corrected_text and args.outcome != "corrected":
        raise SystemExit(f"--corrected-text is only valid with --outcome corrected, not {args.outcome}")
    text = texts[args.index - 1]
    if not single_line(text):
        raise SystemExit(f"{review_list.texts_name} entry {args.index}: must be a non-empty single-line string")
    now = utc_now()
    review = {"index": args.index, "outcome": args.outcome,
              "corrected_text": args.corrected_text, "reason": args.reason, "reviewed_at": now}
    if problems := validate_review(review, args.index, review_list):
        raise SystemExit("; ".join(problems))
    line = render_review(text, review, review_list)
    reviews[args.index - 1] = review
    write_json(artifact_path, artifact)
    append_jsonl(run_dir / "events.jsonl", {
        "time": now, "type": event_type,
        "message": f"{review_list.item_name.capitalize()} {args.index}: {args.outcome}",
        "data": dict(review, artifact=str(artifact_path)),
    })
    if publication := getattr(args, "_board_publication", None):
        publication.force = True
    print(line)
    return 0


def validate_artifact(args: argparse.Namespace) -> int:
    """Check every open_decisions entry where they are authored: at finalize.

    Enforcing the schema only when an answer is recorded would surface a thin entry mid
    walkthrough, when the rounds are gone and nobody can repair it.
    """
    artifact_path = Path(args.artifact)
    artifact = read_json(artifact_path)
    decisions = artifact.get("open_decisions")
    if not isinstance(decisions, list):
        raise SystemExit(f"{artifact_path} has no open_decisions list")
    problems = decision_problems(decisions)
    problems.extend(validate_extension(artifact, artifact_path))
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"open_decisions={len(decisions)}{extension_summary(artifact)} valid")
    return 0


def decision_problems(decisions: list) -> list[str]:
    return [
        f"{entry.get('id') if isinstance(entry, dict) else f'entry {index}'}: {problem}"
        for index, entry in enumerate(decisions)
        for problem in validate_decision(entry)
    ]


def load_artifact(path: Path) -> dict | None:
    """The artifact data, or None if this JSON file is not an artifact at all."""
    try:
        data = read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("open_decisions"), list):
        return None
    return data


def print_pending_decisions(args: argparse.Namespace) -> int:
    """Report the newest artifact's unfinished walkthrough items at session start.

    Deferred decisions stay separate because they must not be re-asked.
    """
    artifacts = {path: data for path in Path(TRACKER_ROOT).glob(f"*/{GRILLING_DIRNAME}/*.json")
                 if path.is_file() and (data := load_artifact(path)) is not None}
    newest = max(artifacts, key=lambda path: (path.stat().st_mtime, path.name), default=None)

    def ids(field: str, status: str, *, status_key: str = "status", id_key: str = "id") -> str:
        items = artifacts[newest].get(field) if newest is not None else None
        listed = [str(item[id_key]) for item in (items if isinstance(items, list) else [])
                  if isinstance(item, dict) and item.get(status_key) == status and id_key in item]
        return ",".join(listed) if listed else "none"

    print(f"dir={newest.parent if newest is not None else 'none'} artifact={newest or 'none'} "
          f"open={ids('open_decisions', 'open')} deferred={ids('open_decisions', 'deferred')} "
          f"unreviewed_assumptions={ids('assumption_review', 'unreviewed', status_key='outcome', id_key='index')} "
          f"open_facts={ids('open_facts', 'open')} "
          f"unreviewed_premise_corrections={ids('premise_correction_review', 'unreviewed', status_key='outcome', id_key='index')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
