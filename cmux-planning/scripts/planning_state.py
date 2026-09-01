#!/usr/bin/env python3
"""Initialize and advance the repository-grounded cmux-planning specification workflow."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from agents_config import (
    ConfigError,
    add_override_options,
    add_probe_options,
    atomic_initialize,
    config_path,
    git_root,
    is_legacy,
    load_validated,
    migration_preview,
    parse_json,
    read_config_bytes,
    resolved_display,
)
from grilling_input import (
    GrillingInputError,
    normalize_revalidation,
    parse_json_bytes,
    validate_pair,
)
from orchestrator_lib import (
    MINIMUM_WAIT_MINUTES,
    STAGES,
    append_event,
    append_jsonl,
    atomic_write,
    checkout_identity,
    integrity_boundary,
    read_json,
    read_planning_state,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_json,
)
from planning_recovery import (
    PASS_KEYS,
    recovery_context,
    shell_join,
    stage_pass,
    status_payload,
    unfinished_runs,
)
from spec_contract import (
    ContractError,
    sections,
    validate_author_report,
    validate_review_report,
    validate_spec,
)
from stage_snapshot import (
    WORKFLOW,
    SnapshotError,
    approved_spec_from_state,
    persist_snapshot,
    snapshot_from_args,
)
from tree_integrity import IntegrityError, capture_tree, compare_tree, snapshot_digest, verify
from tracker_contract import (
    stage_native_tracker,
    validate_native_tracker,
    validate_proposal,
    validate_ticket_author_report,
    validate_ticket_review_report,
)


RUN_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Persist planning input and prepare direct-task spec work")
    task = init.add_mutually_exclusive_group(required=True)
    task.add_argument("--task")
    task.add_argument("--task-file")
    task.add_argument("--conversation-summary")
    init.add_argument("--grilling-json")
    init.add_argument("--grilling-markdown")
    init.add_argument("--repo", default=".")
    init.add_argument("--run-id")
    init.add_argument("--runs-root", default=".scratch/orchestrator/planning-runs")
    init.add_argument("--config")
    init.add_argument(
        "--accept-config",
        action="store_true",
        help="accept a newly created schema-v2 default; never authorizes schema migration",
    )
    init.add_argument("--workspace-id")
    init.add_argument("--no-workspace", action="store_true")
    init.add_argument(
        "--new-run",
        action="store_true",
        help="deliberately start a new session even when this repository has an unfinished run",
    )
    add_override_options(init, workflow=WORKFLOW)
    add_probe_options(init)

    show = subparsers.add_parser("show-revalidation")
    show.add_argument("--run-dir", required=True)

    revalidate = subparsers.add_parser("revalidate")
    revalidate.add_argument("--run-dir", required=True)
    revalidate.add_argument("--outcomes", required=True)
    add_override_options(revalidate, workflow=WORKFLOW)
    add_probe_options(revalidate)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--run-dir", required=True)
    prepare.add_argument("--stage", choices=STAGES, required=True)
    prepare.add_argument("--pass", dest="pass_num", type=int, required=True)
    add_override_options(prepare, workflow=WORKFLOW)
    add_probe_options(prepare)

    author = subparsers.add_parser("accept-author")
    author.add_argument("--run-dir", required=True)
    add_override_options(author, workflow=WORKFLOW)
    add_probe_options(author)

    review = subparsers.add_parser("accept-review")
    review.add_argument("--run-dir", required=True)

    view = subparsers.add_parser("approval-view")
    view.add_argument("--run-dir", required=True)

    approval = subparsers.add_parser("approval")
    approval.add_argument("--run-dir", required=True)
    approval.add_argument("--decision", choices=("approve", "revise"), required=True)
    approval.add_argument("--reason", required=True)
    add_override_options(approval, workflow=WORKFLOW)
    add_probe_options(approval)

    ticket_view = subparsers.add_parser("ticket-approval-view")
    ticket_view.add_argument("--run-dir", required=True)

    ticket_approval = subparsers.add_parser("ticket-approval")
    ticket_approval.add_argument("--run-dir", required=True)
    ticket_approval.add_argument("--decision", choices=("approve", "revise"), required=True)
    ticket_approval.add_argument("--reason", required=True)
    ticket_approval.add_argument("--target")
    ticket_approval.add_argument(
        "--scope",
        choices=("tickets", "spec"),
        default="tickets",
        help="revision scope; use spec only when ticket review exposed an approved-spec defect",
    )
    add_override_options(ticket_approval, workflow=WORKFLOW)
    add_probe_options(ticket_approval)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--run-dir", required=True)

    status = subparsers.add_parser("status", help="Report exact persisted stage and next action")
    status.add_argument("--run-dir", required=True)
    status.add_argument("--cmux-cmd", default="cmux")

    context = subparsers.add_parser("context", help="List persisted recovery inputs and history")
    context.add_argument("--run-dir", required=True)

    resume = subparsers.add_parser("resume", help="Inspect or explicitly resume an interrupted run")
    resume.add_argument("--run-dir", required=True)
    resume.add_argument("--decision", choices=("rejoin", "extend", "relaunch"))
    resume.add_argument("--reason")
    resume.add_argument("--cmux-cmd", default="cmux")
    add_override_options(resume, workflow=WORKFLOW)
    add_probe_options(resume)
    return parser


def resolve_workspace(args: argparse.Namespace) -> str | None:
    if args.no_workspace:
        return None
    workspace = args.workspace_id or os.environ.get("CMUX_WORKSPACE_ID", "")
    if not workspace:
        raise ConfigError(
            "No cmux workspace to pin: pass --workspace-id, use CMUX_WORKSPACE_ID, "
            "or explicitly select --no-workspace for an offline run"
        )
    return workspace


def task_input(args: argparse.Namespace) -> tuple[bytes, str]:
    if args.task_file:
        path = Path(args.task_file).expanduser().resolve()
        payload = path.read_bytes()
        source = f"file:{path}"
    elif args.task is not None:
        payload = args.task.encode("utf-8")
        source = "explicit-text"
    else:
        payload = args.conversation_summary.encode("utf-8")
        source = "conversation-summary"
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError(f"task input is not UTF-8: {error}") from error
    if not text.strip():
        raise ConfigError("task input is empty")
    return payload, source


def ensure_runs_ignored(runs_root: Path) -> None:
    runs_root.mkdir(parents=True, exist_ok=True)
    ignore = runs_root / ".gitignore"
    # is_file, not exists: anything else at that path leaves every run directory git-visible,
    # which is the outcome this helper exists to prevent.
    if not ignore.is_file():
        atomic_write(ignore, b"*\n")


def planning_config(args: argparse.Namespace, repository: Path) -> tuple[Path, dict[str, Any], bool]:
    path = config_path(args.config, str(repository))
    created = False
    if not path.exists():
        atomic_initialize(path)
        created = True
    # Detection goes through the CLI's own parser and version sentinel so this checkpoint cannot
    # disagree with the loader below about what a version-one file is.
    try:
        parsed = parse_json(read_config_bytes(path, ConfigError), path, ConfigError)
    except ConfigError:
        parsed = None
    if is_legacy(parsed):
        try:
            preview = migration_preview(parsed, path)
        except ConfigError as cause:
            raise ConfigError(
                f"Planning initialization stopped: schema-v1 configuration at {path} cannot "
                f"produce a valid migration candidate: {cause}\n"
                "No configuration bytes, planning run, or launchable state were recorded."
            ) from cause
        raise ConfigError(
            f"{preview.render_guidance()}\nPlanning initialization stopped: configuration at {path} "
            "requires explicit shared-CLI migration. Run the preview command above, present that "
            "preview in the human's language, obtain explicit confirmation, then run the acceptance "
            "command above. "
            "--accept-config does not authorize schema migration. No configuration bytes, planning "
            "run, or launchable state were recorded."
        )
    data = load_validated(path)
    print(json.dumps(resolved_display(data, path), indent=2, sort_keys=True))
    # Only the create path can require this planning-specific acceptance; schema-v1 raised above.
    if created and not args.accept_config:
        raise ConfigError(
            f"configuration created at {path}; review all resolved workflows and rerun with "
            "--accept-config. No planning run or launchable state was recorded."
        )
    return path, data, created


def add_gate(
    state: dict[str, Any], stage: str, decision: str, reason: str, **data: Any
) -> dict[str, Any]:
    gate = {
        "time": utc_now(),
        "stage": stage,
        "decision": decision,
        "reason": reason,
        **data,
    }
    state.setdefault("gate_decisions", []).append(gate)
    return gate


def prepare_stage(args: argparse.Namespace, run_dir: Path, stage: str, pass_num: int) -> dict[str, Any]:
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    if state.get("current_stage") != stage:
        raise SnapshotError(f"cannot prepare {stage}: current stage is {state.get('current_stage')!r}")
    # Bound to the run's own pass, or a stale number would repoint the handoff paths at the
    # artifacts a previous pass preserved.
    pass_key = PASS_KEYS[stage]
    is_tickets = stage.startswith("tickets")
    # Runs created before recovery support used the author pass for its paired reviewer.
    if pass_key not in state:
        state[pass_key] = state["tickets_pass" if is_tickets else "spec_pass"]
    current_pass = stage_pass(state, stage)
    if pass_num != current_pass:
        raise SnapshotError(
            f"cannot prepare {stage} pass {pass_num}: the run is on pass {current_pass}"
        )
    if is_tickets:
        approved_spec_from_state(state, run_dir=run_dir)
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    write_json(state_path, state)
    _, snapshot = snapshot_from_args(
        args,
        run_dir=run_dir,
        run_id=state["run_id"],
        stage=stage,
        pass_num=pass_num,
        config_source=state["configuration_source"],
    )
    pointer = persist_snapshot(run_dir, snapshot)
    state = read_planning_state(state_path)
    if state.get("current_stage") != stage:
        raise SnapshotError(f"run moved stages while {stage}-{pass_num} was being prepared")
    state["prepared_stage"] = pointer
    state["tree_baseline"] = None
    state["updated_at"] = pointer["prepared_at"]
    write_json(state_path, state)
    append_event(
        run_dir,
        "stage.prepared",
        f"prepared immutable {stage}-{pass_num} snapshot",
        {**pointer, "role": snapshot["role"], "harness": snapshot["selected_worker"]["harness"]},
    )
    return pointer


def checked_run_id(value: str) -> str:
    """One directory name under the ignored runs root, never a path.

    An unchecked `--run-id` of `..` or an absolute path puts the run outside the runs root,
    where `ensure_runs_ignored` does not reach and the integrity detector sees the
    orchestrator's own writes as unauthorized worker changes."""
    if value in {"", ".", ".."} or value != RUN_ID_RE.sub("-", value).strip("-"):
        raise ConfigError(
            f"--run-id must be a single name of letters, digits, '.', '_' or '-': {value!r}"
        )
    return value


def finish_input_validation(run_dir: Path) -> dict[str, Any]:
    """Complete the durable input checkpoint without repeating input or profile validation."""
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    if state.get("current_stage") != "input":
        raise ConfigError(
            f"input recovery is available only from the input stage, not {state.get('current_stage')!r}"
        )
    initialization = state.get("initialization")
    if not isinstance(initialization, dict):
        raise ConfigError("input recovery metadata is missing")
    target = initialization.get("target_stage")
    pointer = initialization.get("prepared_stage")
    if target == "spec":
        if not isinstance(pointer, dict):
            raise ConfigError("validated direct input has no prepared specification snapshot")
        relative = Path(pointer.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise ConfigError("validated input snapshot path is unsafe")
        snapshot_path = run_dir / relative
        if not snapshot_path.is_file() or sha256_file(snapshot_path) != pointer.get("sha256"):
            raise ConfigError("validated input snapshot is missing or changed")
    elif target == "awaiting-grilling-revalidation":
        if pointer is not None:
            raise ConfigError("grilling input must not prepare a worker before revalidation")
    else:
        raise ConfigError(f"validated input has unknown target stage {target!r}")

    now = utc_now()
    state["current_stage"] = target
    state["prepared_stage"] = pointer
    state["initialization"] = {**initialization, "status": "complete", "completed_at": now}
    state["updated_at"] = pointer.get("prepared_at", now) if isinstance(pointer, dict) else now
    write_json(state_path, state)
    if isinstance(pointer, dict):
        append_event(run_dir, "stage.prepared", "prepared immutable spec-1 snapshot", pointer)
    else:
        append_event(
            run_dir,
            "input.validated",
            "validated and persisted grilling input; explicit human revalidation is required",
            {"next_stage": target},
            time=now,
        )
    return state


def init_run(args: argparse.Namespace) -> int:
    repository = git_root(Path(args.repo))
    task_bytes, task_source = task_input(args)
    runs_root = Path(args.runs_root)
    if not args.new_run:
        unfinished = unfinished_runs(runs_root, repository)
        if unfinished:
            latest = unfinished[0]
            print(
                json.dumps(
                    {
                        "unfinished_run": latest,
                        "recommended_next": {
                            "action": "inspect and resume the newest unfinished planning run",
                            "command": shell_join(
                                [
                                    "python3",
                                    Path(__file__).resolve(),
                                    "resume",
                                    "--run-dir",
                                    latest["run_dir"],
                                ]
                            ),
                        },
                        "new_run_override": "rerun init with --new-run",
                    },
                    sort_keys=True,
                )
            )
            return 3
    grilling = None
    if args.grilling_markdown and not args.grilling_json:
        raise ConfigError("--grilling-markdown requires --grilling-json")
    if args.grilling_json:
        grilling = validate_pair(
            Path(args.grilling_json),
            Path(args.grilling_markdown) if args.grilling_markdown else None,
            repository,
            cwd=repository,
        )
    workspace = resolve_workspace(args)
    now = utc_now()
    seed = task_bytes.decode("utf-8").strip().splitlines()[0][:48]
    run_id = (
        checked_run_id(args.run_id)
        if args.run_id
        else RUN_ID_RE.sub("-", f"plan-{seed}-{now[:10]}-{now[11:13]}{now[14:16]}").strip("-")
    )
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise ConfigError(f"planning run already exists: {run_dir}")

    # Last of the checks: creating the shared configuration is durable and must not happen for an
    # init that then fails on its own inputs. Migration is a separate shared-CLI action.
    configuration_source, _, changed = planning_config(args, repository)

    # Preflight direct input before any run state is published. Grilling input cannot preflight
    # until its explicit human revalidation is recorded.
    prepared_snapshot = None
    if grilling is None:
        _, prepared_snapshot = snapshot_from_args(
            args,
            run_dir=run_dir,
            run_id=run_id,
            stage="spec",
            pass_num=1,
            config_source=str(configuration_source),
        )

    ensure_runs_ignored(runs_root)
    for name in ("artifacts", "inputs", "prompts", "reports", "stage-snapshots", "tree-snapshots"):
        (run_dir / name).mkdir(parents=True, exist_ok=True)
    task_path = run_dir / "task.md"
    atomic_write(task_path, task_bytes)
    grilling_state = None
    if grilling is not None:
        json_copy = run_dir / "inputs" / "grilling-source.json"
        markdown_copy = run_dir / "inputs" / "grilling-source.md"
        atomic_write(json_copy, grilling["json_bytes"])
        atomic_write(markdown_copy, grilling["markdown_bytes"])
        grilling_state = {
            "source_json": str(grilling["json_path"]),
            "source_json_sha256": grilling["json_sha256"],
            "source_markdown": str(grilling["markdown_path"]),
            "source_markdown_sha256": grilling["markdown_sha256"],
            "copied_json": "inputs/grilling-source.json",
            "copied_markdown": "inputs/grilling-source.md",
            "premise_corrections": grilling["premise_corrections"],
        }
    initial_pointer = persist_snapshot(run_dir, prepared_snapshot) if prepared_snapshot is not None else None
    target_stage = "awaiting-grilling-revalidation" if grilling else "spec"
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": now,
        "repository": str(repository),
        "checkout_at_init": checkout_identity(repository),
        "workspace_id": workspace,
        "configuration_source": str(configuration_source),
        "configuration_created_and_accepted": changed,
        "task": {
            "path": "task.md",
            "source": task_source,
            "sha256": sha256_bytes(task_bytes),
        },
        "grilling_import": grilling_state,
        "grilling_revalidation": None,
        "normalized_grilling_input": None,
        "current_stage": "input",
        "spec_pass": 1,
        "spec_review_pass": 1,
        "tickets_pass": 1,
        "tickets_review_pass": 1,
        "prepared_stage": None,
        "tree_baseline": None,
        "reviewed_spec": None,
        "approved_spec": None,
        "spec_revision_feedback": None,
        "author_tickets": None,
        "reviewed_tickets": None,
        "approved_tickets": None,
        "ticket_revision_feedback": None,
        "staged_tracker": None,
        "published_tracker": None,
        "gate_decisions": [],
        "worker_wait_policy": {
            "watcher": "await_report.py",
            "missing_report_gate": "pending",
            "minimum_wait_minutes": MINIMUM_WAIT_MINUTES,
            "maximum_extensions": 1,
            "stable_pane_identity_required": True,
        },
        "integrity_boundary": integrity_boundary(),
        "initialization": {
            "status": "validated",
            "target_stage": target_stage,
            "prepared_stage": initial_pointer,
        },
    }
    write_json(run_dir / "state.json", state)
    append_event(
        run_dir,
        "run.init",
        "persisted validated input at a recoverable initialization checkpoint",
        {"state": state},
    )
    finish_input_validation(run_dir)
    print(run_dir)
    return 0


def imported_from_state(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    imported = state.get("grilling_import")
    if not isinstance(imported, dict):
        raise GrillingInputError("run has no grilling input")
    json_path = run_dir / imported["copied_json"]
    markdown_path = run_dir / imported["copied_markdown"]
    json_bytes = json_path.read_bytes()
    markdown_bytes = markdown_path.read_bytes()
    if sha256_bytes(json_bytes) != imported["source_json_sha256"]:
        raise GrillingInputError("copied grilling JSON no longer matches its recorded digest")
    if sha256_bytes(markdown_bytes) != imported["source_markdown_sha256"]:
        raise GrillingInputError("copied grilling Markdown no longer matches its recorded digest")
    return {
        "data": parse_json_bytes(json_bytes, json_path),
        "json_path": Path(imported["source_json"]),
        "markdown_path": Path(imported["source_markdown"]),
        "json_bytes": json_bytes,
        "markdown_bytes": markdown_bytes,
        "json_sha256": imported["source_json_sha256"],
        "markdown_sha256": imported["source_markdown_sha256"],
        "premise_corrections": imported["premise_corrections"],
    }


def show_revalidation(run_dir: Path) -> int:
    state = read_planning_state(run_dir / "state.json")
    imported = imported_from_state(run_dir, state)
    data = imported["data"]
    progress = state.get("grilling_revalidation")
    recorded_outcomes = None
    if isinstance(progress, dict):
        relative = Path(progress.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts:
            raise GrillingInputError("recorded revalidation progress path is unsafe")
        progress_path = run_dir / relative
        if not progress_path.is_file() or sha256_file(progress_path) != progress.get("sha256"):
            raise GrillingInputError("recorded revalidation progress is missing or changed")
        recorded_outcomes = read_json(progress_path)
    print(
        json.dumps(
            {
                "freshness_notice": (
                    "Structural/path/digest validation proves integrity, not freshness; "
                    "the human must confirm applicability to this task and checkout."
                ),
                "artifact_task": data["task"],
                "artifact_repository": data["codebasePath"],
                "current_checkout": checkout_identity(Path(state["repository"])),
                "premise_corrections": imported["premise_corrections"],
                "assumptions": data["assumptions"],
                "decisions": data["open_decisions"],
                "recorded_outcomes": recorded_outcomes,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def revalidate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    if state.get("current_stage") != "awaiting-grilling-revalidation":
        raise GrillingInputError("run is not awaiting grilling revalidation")
    imported = imported_from_state(run_dir, state)
    outcomes = read_json(Path(args.outcomes))
    if not isinstance(outcomes, dict):
        raise GrillingInputError("revalidation outcomes root must be an object")
    # Save every human walkthrough checkpoint before complete normalization. A compacted or
    # interrupted conversation can therefore resume the same copied pair without replaying
    # already recorded outcomes, while only the complete validator can advance the run.
    progress_path = run_dir / "inputs" / "grilling-revalidation-progress.json"
    write_json(progress_path, outcomes)
    state["grilling_revalidation"] = {
        "path": "inputs/grilling-revalidation-progress.json",
        "sha256": sha256_file(progress_path),
        "status": "in-progress",
        "updated_at": utc_now(),
    }
    state["updated_at"] = state["grilling_revalidation"]["updated_at"]
    write_json(state_path, state)
    append_event(
        run_dir,
        "grilling.revalidation_progress",
        "preserved the latest partial human revalidation walkthrough",
        state["grilling_revalidation"],
    )
    normalized = normalize_revalidation(
        imported,
        outcomes,
        task_path=run_dir / state["task"]["path"],
        repository=Path(state["repository"]),
    )
    if normalized is None:
        state = read_planning_state(state_path)
        state["grilling_revalidation"]["status"] = "refused"
        write_json(state_path, state)
        append_event(
            run_dir,
            "grilling.revalidation_refused",
            "human refused artifact applicability; no worker was prepared",
            {},
        )
        print("revalidation=refused stage=awaiting-grilling-revalidation")
        return 2
    normalized_path = run_dir / "grilling-input.json"
    write_json(normalized_path, normalized)
    state["normalized_grilling_input"] = {
        "path": "grilling-input.json",
        "sha256": sha256_file(normalized_path),
        "event_id": normalized["revalidation_event_id"],
    }
    state["grilling_revalidation"]["status"] = "complete"
    state["current_stage"] = "spec"
    state["updated_at"] = normalized["revalidated_at"]
    write_json(state_path, state)
    append_event(
        run_dir,
        "grilling.revalidated",
        "recorded complete normalized grilling handoff",
        state["normalized_grilling_input"],
    )
    pointer = prepare_stage(args, run_dir, "spec", state["spec_pass"])
    print(json.dumps({"normalized": str(normalized_path), "prepared": pointer}, sort_keys=True))
    return 0


def integrity_gate(run_dir: Path, stage: str, pass_num: int) -> bool:
    result = verify(run_dir, stage, pass_num)
    if result["ok"]:
        return True
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    event = add_gate(
        state,
        stage,
        "hitl",
        "unauthorized Git-visible worker delta",
        unauthorized_paths=result["unauthorized_paths"],
        head_moved=result["head_moved"],
        head_before=result["head_before"],
        head_after=result["head_after"],
    )
    state["current_stage"] = "integrity-violation"
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    write_json(state_path, state)
    append_event(run_dir, "gate", "integrity violation requires human resolution", event)
    return False


def ensure_integrity_resolved(run_dir: Path, state: dict[str, Any]) -> None:
    """Do not let a new pass adopt the unauthorized delta that caused HITL."""
    gates = state.get("gate_decisions", [])
    gate = gates[-1] if gates and isinstance(gates[-1], dict) else None
    stage = gate.get("stage") if gate else None
    if stage not in STAGES:
        raise IntegrityError("integrity violation has no recoverable stage identity")
    pass_num = stage_pass(state, stage)
    before_path = run_dir / "tree-snapshots" / f"{stage}-{pass_num}-before.json"
    if not before_path.is_file():
        raise IntegrityError("integrity violation has no preserved launch baseline")
    before = read_json(before_path)
    seals = state.get("tree_baseline_seals")
    expected_digest = seals.get(f"{stage}-{pass_num}") if isinstance(seals, dict) else None
    if not isinstance(expected_digest, str) or snapshot_digest(before) != expected_digest:
        raise IntegrityError("integrity violation launch baseline is missing or changed")
    result = compare_tree(
        before,
        capture_tree(Path(state["repository"])),
        allowed_paths=[],
    )
    if not result["ok"]:
        raise IntegrityError(
            "resolve the unauthorized working-tree delta and restore the armed baseline before preparing a recovery pass"
        )


def ensure_relaunch_tree_safe(
    run_dir: Path, state: dict[str, Any], stage: str, pass_num: int
) -> None:
    """A dead worker must not make its product edits the next pass's trusted baseline."""
    pointer = state.get("tree_baseline")
    if (
        not isinstance(pointer, dict)
        or pointer.get("stage") != stage
        or pointer.get("pass") != pass_num
    ):
        raise IntegrityError("dead worker recovery has no matching preserved launch baseline")
    before_relative = Path(pointer.get("path", ""))
    if before_relative.is_absolute() or ".." in before_relative.parts:
        raise IntegrityError("dead worker recovery has an unsafe launch baseline path")
    before_path = run_dir / before_relative
    if not before_path.is_file():
        raise IntegrityError("dead worker recovery launch baseline is missing")
    before = read_json(before_path)
    if snapshot_digest(before) != pointer.get("sha256"):
        raise IntegrityError("dead worker recovery launch baseline changed")
    result = compare_tree(
        before,
        capture_tree(Path(state["repository"])),
        allowed_paths=[],
    )
    if not result["ok"]:
        raise IntegrityError(
            "resolve the dead worker's Git-visible product delta before preparing a recovery pass"
        )


def accept_spec_author(args: argparse.Namespace, run_dir: Path, state: dict[str, Any]) -> int:
    pass_num = state["spec_pass"]
    if not integrity_gate(run_dir, "spec", pass_num):
        print("gate=hitl reason=integrity-violation")
        return 2
    draft = run_dir / "artifacts" / f"spec-{pass_num}.md"
    report = run_dir / "reports" / f"spec-{pass_num}.md"
    result = validate_author_report(report, draft)
    if result["result"] == "BLOCKED":
        state = read_planning_state(run_dir / "state.json")
        state["current_stage"] = "spec-blocked"
        state["prepared_stage"] = None
        state["tree_baseline"] = None
        gate = add_gate(state, "spec", "blocked", "spec author reported a blocker")
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "gate", "spec author reported a blocker", gate)
        return 2
    state = read_planning_state(run_dir / "state.json")
    state["author_spec"] = result
    state["current_stage"] = "spec-review"
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    gate = add_gate(
        state,
        "spec",
        "advance",
        "author report validated; independent review required",
        draft_sha256=result["draft_sha256"],
    )
    write_json(run_dir / "state.json", state)
    append_event(run_dir, "gate", "author report validated; independent review required", gate)
    review_pass = stage_pass(state, "spec-review")
    pointer = prepare_stage(args, run_dir, "spec-review", review_pass)
    print(json.dumps(pointer, sort_keys=True))
    return 0


def accept_tickets_author(
    args: argparse.Namespace, run_dir: Path, state: dict[str, Any]
) -> int:
    pass_num = state["tickets_pass"]
    if not integrity_gate(run_dir, "tickets", pass_num):
        print("gate=hitl reason=integrity-violation")
        return 2
    approved = state.get("approved_spec")
    if not isinstance(approved, dict):
        raise ContractError("tickets author gate has no approved specification")
    proposal = run_dir / "artifacts" / f"tickets-{pass_num}.json"
    summary = run_dir / "artifacts" / f"tickets-{pass_num}.md"
    report = run_dir / "reports" / f"tickets-{pass_num}.md"
    result = validate_ticket_author_report(
        report,
        proposal,
        summary,
        expected_spec=Path(approved["path"]),
        expected_spec_sha256=approved["sha256"],
    )
    state = read_planning_state(run_dir / "state.json")
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    if result["result"] == "BLOCKED":
        state["current_stage"] = "tickets-blocked"
        gate = add_gate(state, "tickets", "blocked", "tickets author reported a blocker")
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "gate", "tickets author reported a blocker", gate)
        print("gate=blocked")
        return 2
    state["author_tickets"] = result
    state["current_stage"] = "tickets-review"
    gate = add_gate(
        state,
        "tickets",
        "advance",
        "ticket proposal validated; independent review required",
        proposal_sha256=result["proposal_sha256"],
        summary_sha256=result["summary_sha256"],
        ticket_count=result["ticket_count"],
        ready_frontier=result["ready_frontier"],
    )
    write_json(run_dir / "state.json", state)
    append_event(run_dir, "gate", "ticket proposal validated; independent review required", gate)
    review_pass = stage_pass(state, "tickets-review")
    pointer = prepare_stage(args, run_dir, "tickets-review", review_pass)
    print(json.dumps(pointer, sort_keys=True))
    return 0


def accept_spec_review(args: argparse.Namespace, run_dir: Path, state: dict[str, Any]) -> int:
    pass_num = stage_pass(state, "spec-review")
    if not integrity_gate(run_dir, "spec-review", pass_num):
        print("gate=hitl reason=integrity-violation")
        return 2
    author = state.get("author_spec")
    draft = Path(author["draft"]) if isinstance(author, dict) and author.get("draft") else None
    candidate = run_dir / "artifacts" / f"spec-reviewed-{pass_num}.md"
    report = run_dir / "reports" / f"spec-review-{pass_num}.md"
    # Fail closed: `expected_input_sha256=None` means "skip the binding check", so a missing
    # author gate would silently let a reviewer certify a draft it rewrote itself.
    if not isinstance(author, dict) or not author.get("draft_sha256") or draft is None:
        raise ContractError("review cannot be accepted without the author gate's draft digest")
    result = validate_review_report(
        report,
        draft,
        candidate,
        expected_input_sha256=author["draft_sha256"],
    )
    state = read_planning_state(run_dir / "state.json")
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    if result["verdict"] == "blocked":
        state["current_stage"] = "spec-review-blocked"
        gate = add_gate(state, "spec-review", "blocked", "review requires a human-owned decision")
        write_json(run_dir / "state.json", state)
        append_event(run_dir, "gate", "review requires a human-owned decision", {**gate, **result})
        print("gate=blocked")
        return 2
    state["reviewed_spec"] = result
    state["current_stage"] = "awaiting-spec-approval"
    gate = add_gate(
        state,
        "spec-review",
        "advance",
        "reviewed candidate validated; explicit human approval required",
        verdict=result["verdict"],
        candidate_sha256=result["candidate_sha256"],
    )
    write_json(run_dir / "state.json", state)
    append_event(
        run_dir,
        "gate",
        "reviewed candidate validated; explicit human approval required",
        gate,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


def accept_tickets_review(args: argparse.Namespace, run_dir: Path, state: dict[str, Any]) -> int:
    pass_num = stage_pass(state, "tickets-review")
    if not integrity_gate(run_dir, "tickets-review", pass_num):
        print("gate=hitl reason=integrity-violation")
        return 2
    approved = state.get("approved_spec")
    author = state.get("author_tickets")
    if not isinstance(approved, dict) or not isinstance(author, dict):
        raise ContractError("tickets review gate requires approved spec and author identities")
    proposal = Path(author["proposal"])
    summary = Path(author["summary"])
    if not summary.is_file() or sha256_file(summary) != author["summary_sha256"]:
        raise ContractError("human-readable ticket summary changed after the author gate")
    candidate = run_dir / "artifacts" / f"tickets-reviewed-{pass_num}.json"
    report = run_dir / "reports" / f"tickets-review-{pass_num}.md"
    result = validate_ticket_review_report(
        report,
        proposal,
        candidate,
        expected_input_sha256=author["proposal_sha256"],
        expected_spec=Path(approved["path"]),
        expected_spec_sha256=approved["sha256"],
    )
    state = read_planning_state(run_dir / "state.json")
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    if result["verdict"] == "blocked":
        state["current_stage"] = "tickets-review-blocked"
        gate = add_gate(
            state,
            "tickets-review",
            "blocked",
            "ticket review requires a human-owned decision or approved-spec correction",
        )
        write_json(run_dir / "state.json", state)
        append_event(
            run_dir,
            "gate",
            "ticket review requires a human-owned decision or approved-spec correction",
            {**gate, **result},
        )
        print("gate=blocked")
        return 2
    state["reviewed_tickets"] = result
    state["current_stage"] = "awaiting-ticket-approval"
    gate = add_gate(
        state,
        "tickets-review",
        "advance",
        "reviewed tracker candidate validated; explicit human approval required",
        verdict=result["verdict"],
        candidate_sha256=result["candidate_sha256"],
        ticket_count=result["ticket_count"],
        ready_frontier=result["ready_frontier"],
    )
    write_json(run_dir / "state.json", state)
    append_event(
        run_dir,
        "gate",
        "reviewed tracker candidate validated; explicit human approval required",
        gate,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


AUTHOR_GATES = {"spec": accept_spec_author, "tickets": accept_tickets_author}
REVIEW_GATES = {"spec-review": accept_spec_review, "tickets-review": accept_tickets_review}


def _accept(args: argparse.Namespace, gates: dict[str, Any], label: str) -> int:
    run_dir = Path(args.run_dir)
    state = read_planning_state(run_dir / "state.json")
    stage = state.get("current_stage")
    if stage not in gates:
        raise ContractError(f"cannot accept {label} from stage {stage!r}")
    return gates[stage](args, run_dir, state)


def accept_author(args: argparse.Namespace) -> int:
    return _accept(args, AUTHOR_GATES, "author report")


def accept_review(args: argparse.Namespace) -> int:
    return _accept(args, REVIEW_GATES, "review")


def approval_view(run_dir: Path) -> int:
    state = read_planning_state(run_dir / "state.json")
    if state.get("current_stage") != "awaiting-spec-approval":
        raise ContractError("approval walkthrough is available only after a valid review")
    reviewed = state["reviewed_spec"]
    pass_num = state["spec_pass"]
    review_pass = stage_pass(state, "spec-review")
    draft = Path(state["author_spec"]["draft"])
    candidate = Path(reviewed["candidate"])
    draft_text = draft.read_text(encoding="utf-8")
    candidate_text = candidate.read_text(encoding="utf-8")
    candidate_contract = validate_spec(candidate, require_closed_decisions=True)
    if candidate_contract["sha256"] != reviewed.get("candidate_sha256"):
        raise ContractError("reviewed specification candidate changed before approval walkthrough")
    if sha256_file(draft) != state["author_spec"].get("draft_sha256"):
        raise ContractError("author specification changed before approval walkthrough")
    author_report = sections((run_dir / "reports" / f"spec-{pass_num}.md").read_text(encoding="utf-8"))
    review_report = sections((run_dir / "reports" / f"spec-review-{review_pass}.md").read_text(encoding="utf-8"))
    normalized_pointer = state.get("normalized_grilling_input")
    normalized = read_json(run_dir / normalized_pointer["path"]) if normalized_pointer else None
    payload = {
        "verdict": reviewed["verdict"],
        "candidate_path": str(candidate),
        "candidate_sha256": candidate_contract["sha256"],
        "no_open_decisions": not candidate_contract["has_open_decisions"],
        "corrections": review_report["Corrections"],
        "proposed_test_seams": author_report["Proposed Test Seams"],
        "assumptions": normalized["assumptions"] if normalized else candidate_contract["sections"]["Assumptions"],
        "decisions": normalized["decisions"] if normalized else [],
        "out_of_scope": candidate_contract["sections"]["Out of Scope"],
        "diff": "".join(
            difflib.unified_diff(
                draft_text.splitlines(keepends=True),
                candidate_text.splitlines(keepends=True),
                fromfile=str(draft),
                tofile=str(candidate),
            )
        ),
        "specification": candidate_text,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def discard_staging(run_dir: Path) -> None:
    """A partially staged tracker would otherwise block every later approval forever."""
    shutil.rmtree(run_dir / "publication-stage", ignore_errors=True)


def checked_staging_path(run_dir: Path, value: Any) -> Path:
    if not isinstance(value, str):
        raise ContractError("recorded staged tracker path is missing")
    staged = Path(value).resolve()
    canonical = run_dir.resolve() / "publication-stage"
    if staged != canonical:
        raise ContractError("recorded staged tracker path is outside the planning run's staging area")
    return staged


def reset_ticket_state(state: dict[str, Any]) -> None:
    state["approved_spec"] = None
    state["author_tickets"] = None
    state["reviewed_tickets"] = None
    state["approved_tickets"] = None
    state["ticket_revision_feedback"] = None
    state["staged_tracker"] = None


def approval(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    if args.decision == "approve":
        if state.get("current_stage") != "awaiting-spec-approval" and isinstance(
            state.get("approved_spec"), dict
        ):
            approved = state["approved_spec"]
            reviewed = state.get("reviewed_spec")
            candidate = Path(approved["path"])
            validated = validate_spec(candidate, require_closed_decisions=True)
            if (
                validated["sha256"] != approved.get("sha256")
                or not isinstance(reviewed, dict)
                or reviewed.get("candidate_sha256") != approved.get("sha256")
            ):
                raise ContractError(
                    "recorded specification approval is stale because its digest-bound candidate changed"
                )
            print(json.dumps({"approved_spec": approved, "idempotent": True}, sort_keys=True))
            return 0
        if state.get("current_stage") != "awaiting-spec-approval":
            raise ContractError("spec approval is available only after a valid independent review")
        reviewed = state.get("reviewed_spec")
        if not isinstance(reviewed, dict):
            raise ContractError("run has no reviewed specification candidate")
        candidate = Path(reviewed["candidate"])
        validated = validate_spec(candidate, require_closed_decisions=True)
        if validated["sha256"] != reviewed["candidate_sha256"]:
            raise ContractError("reviewed candidate changed after review")
        event = {
            "time": utc_now(),
            "type": "spec.approved",
            "reason": args.reason,
            "path": str(candidate),
            "sha256": validated["sha256"],
            "verdict": reviewed["verdict"],
        }
        state["approved_spec"] = {
            "path": str(candidate),
            "sha256": validated["sha256"],
            "approved_at": event["time"],
        }
        state["current_stage"] = "tickets"
        state["prepared_stage"] = None
        state["tree_baseline"] = None
        state["updated_at"] = event["time"]
        write_json(state_path, state)
        append_jsonl(run_dir / "events.jsonl", event)
        pointer = prepare_stage(args, run_dir, "tickets", state["tickets_pass"])
        print(json.dumps({"approved_spec": state["approved_spec"], "prepared": pointer}, sort_keys=True))
        return 0

    if state.get("current_stage") not in {
        "awaiting-spec-approval",
        "spec-blocked",
        "spec-review-blocked",
        "integrity-violation",
    }:
        raise ContractError(f"revision is not available from stage {state.get('current_stage')!r}")
    if state.get("current_stage") == "integrity-violation":
        ensure_integrity_resolved(run_dir, state)
    old_pass = state["spec_pass"]
    state["spec_pass"] = old_pass + 1
    state["spec_review_pass"] = state.get("spec_review_pass", old_pass) + 1
    state["current_stage"] = "spec"
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    state["author_spec"] = None
    state["reviewed_spec"] = None
    state["spec_revision_feedback"] = args.reason
    # A revision from an integrity violation can arrive after the spec boundary, and a new spec pass
    # invalidates every ticket artifact derived from the old approved spec.
    old_tickets = state["tickets_pass"] if state.get("approved_spec") else None
    if old_tickets is not None:
        state["tickets_pass"] = old_tickets + 1
        state["tickets_review_pass"] = state.get("tickets_review_pass", old_tickets) + 1
        reset_ticket_state(state)
    state["updated_at"] = utc_now()
    write_json(state_path, state)
    discard_staging(run_dir)
    append_event(
        run_dir,
        "spec.revision_requested",
        "preserved rejected artifacts and required a fresh author plus fresh review",
        {
            "from_pass": old_pass,
            "to_pass": state["spec_pass"],
            "invalidated_tickets_pass": old_tickets,
            "reason": args.reason,
        },
    )
    pointer = prepare_stage(args, run_dir, "spec", state["spec_pass"])
    print(json.dumps(pointer, sort_keys=True))
    return 0


def bound_proposal(approved_spec: dict, path: Path, digest: str, mismatch: str) -> dict:
    proposal = validate_proposal(
        path,
        expected_spec=Path(approved_spec["path"]),
        expected_spec_sha256=approved_spec["sha256"],
    )
    if proposal["sha256"] != digest:
        raise ContractError(mismatch)
    return proposal


def ticket_approval_view(run_dir: Path) -> int:
    state = read_planning_state(run_dir / "state.json")
    if state.get("current_stage") != "awaiting-ticket-approval":
        raise ContractError("ticket approval walkthrough is available only after a valid review")
    reviewed = state.get("reviewed_tickets")
    approved = state.get("approved_spec")
    author = state.get("author_tickets")
    if not all(isinstance(value, dict) for value in (reviewed, approved, author)):
        raise ContractError("ticket approval state is incomplete")
    candidate = Path(reviewed["candidate"])
    proposal = bound_proposal(
        approved, candidate, reviewed["candidate_sha256"], "reviewed ticket candidate changed after review"
    )
    author_proposal = Path(author["proposal"])
    if not author_proposal.is_file() or sha256_file(author_proposal) != author["proposal_sha256"]:
        raise ContractError("ticket author proposal changed after its own gate")
    author_text = json.dumps(read_json(author_proposal), indent=2, sort_keys=True) + "\n"
    candidate_text = json.dumps(read_json(candidate), indent=2, sort_keys=True) + "\n"
    review_pass = stage_pass(state, "tickets-review")
    review_report = sections(
        (run_dir / "reports" / f"tickets-review-{review_pass}.md").read_text(encoding="utf-8")
    )
    payload = {
        "verdict": reviewed["verdict"],
        "candidate_path": str(candidate.resolve()),
        "candidate_sha256": proposal["sha256"],
        "source_spec_sha256": proposal["source_spec_sha256"],
        "tracker_slug": proposal["tracker"]["slug"],
        "ticket_count": proposal["ticket_count"],
        "ready_frontier": proposal["ready_frontier"],
        "tickets": [
            {
                "id": ticket["id"],
                "title": ticket["title"],
                "delivered_behavior": ticket["delivered_behavior"],
                "acceptance_criteria": ticket["acceptance_criteria"],
                "blocked_by": ticket["blocked_by"],
                "merge_split_rationale": ticket["merge_split_rationale"],
                "wide_refactor": ticket["wide_refactor"],
            }
            for ticket in proposal["tickets"]
        ],
        "blocking_edges": [
            {"blocked": ticket["id"], "prerequisite": blocker}
            for ticket in proposal["tickets"]
            for blocker in ticket["blocked_by"]
        ],
        "wide_refactor_exceptions": proposal["wide_refactor"],
        "corrections": review_report["Corrections"],
        "diff": "".join(
            difflib.unified_diff(
                author_text.splitlines(keepends=True),
                candidate_text.splitlines(keepends=True),
                fromfile=str(author_proposal),
                tofile=str(candidate),
            )
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def checked_publication_target(
    repository: Path, value: str, slug: str, *, allow_existing: bool = False
) -> Path:
    raw = Path(value)
    if ".." in raw.parts:
        raise ContractError("publication target contains path traversal")
    target = (raw if raw.is_absolute() else repository / raw).resolve()
    repository = repository.resolve()
    try:
        relative = target.relative_to(repository)
    except ValueError as error:
        raise ContractError("publication target escapes the target repository") from error
    if not relative.parts:
        raise ContractError("publication target must be one tracker directory below the repository")
    if target.name != slug:
        raise ContractError(
            f"publication target basename must match approved tracker slug {slug!r}"
        )
    if target.exists() and not allow_existing:
        raise ContractError(f"publication target already exists: {target}")
    return target


def ticket_approval(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    if args.decision == "revise":
        if state.get("current_stage") not in {
            "awaiting-ticket-approval",
            "tickets-blocked",
            "tickets-review-blocked",
        }:
            raise ContractError(f"ticket revision is not available from {state.get('current_stage')!r}")
        if args.scope == "spec":
            old_spec = state["spec_pass"]
            old_tickets = state["tickets_pass"]
            state["spec_pass"] = old_spec + 1
            state["spec_review_pass"] = state.get("spec_review_pass", old_spec) + 1
            state["tickets_pass"] = old_tickets + 1
            state["tickets_review_pass"] = state.get("tickets_review_pass", old_tickets) + 1
            state["current_stage"] = "spec"
            state["author_spec"] = None
            state["reviewed_spec"] = None
            state["spec_revision_feedback"] = args.reason
            reset_ticket_state(state)
            event_type = "tickets.spec_revision_requested"
            event_data = {
                "from_spec_pass": old_spec,
                "to_spec_pass": state["spec_pass"],
                "invalidated_tickets_pass": old_tickets,
                "next_tickets_pass": state["tickets_pass"],
                "reason": args.reason,
            }
            next_stage = "spec"
            next_pass = state["spec_pass"]
        else:
            old_tickets = state["tickets_pass"]
            state["tickets_pass"] = old_tickets + 1
            state["tickets_review_pass"] = state.get("tickets_review_pass", old_tickets) + 1
            state["current_stage"] = "tickets"
            state["author_tickets"] = None
            state["reviewed_tickets"] = None
            state["approved_tickets"] = None
            state["ticket_revision_feedback"] = args.reason
            event_type = "tickets.revision_requested"
            event_data = {
                "from_pass": old_tickets,
                "to_pass": state["tickets_pass"],
                "reason": args.reason,
            }
            next_stage = "tickets"
            next_pass = state["tickets_pass"]
        state["prepared_stage"] = None
        state["tree_baseline"] = None
        state["staged_tracker"] = None
        state["updated_at"] = utc_now()
        write_json(state_path, state)
        discard_staging(run_dir)
        append_event(
            run_dir,
            event_type,
            "preserved rejected artifacts and required fresh author plus fresh review",
            event_data,
        )
        pointer = prepare_stage(args, run_dir, next_stage, next_pass)
        print(json.dumps(pointer, sort_keys=True))
        return 0

    if args.decision == "approve" and state.get("current_stage") in {"ready-to-publish", "complete"}:
        approved_spec = state.get("approved_spec")
        approved_tickets = state.get("approved_tickets")
        if not isinstance(approved_spec, dict) or not isinstance(approved_tickets, dict):
            raise ContractError("recorded ticket approval is incomplete")
        spec_path = Path(approved_spec["path"])
        if not spec_path.is_file() or sha256_file(spec_path) != approved_spec.get("sha256"):
            raise ContractError("recorded ticket approval is stale because the approved spec changed")
        proposal = bound_proposal(
            approved_spec,
            Path(approved_tickets["path"]),
            approved_tickets["sha256"],
            "recorded ticket approval is stale because its digest-bound proposal changed",
        )
        if args.target:
            repeated_target = (Path(args.target) if Path(args.target).is_absolute() else Path(state["repository"]) / args.target).resolve()
            if repeated_target != Path(approved_tickets["target"]).resolve():
                raise ContractError("idempotent ticket approval cannot change the publication target")
        if state.get("current_stage") == "ready-to-publish":
            staged_state = state.get("staged_tracker")
            if not isinstance(staged_state, dict):
                raise ContractError("recorded ticket approval has no staged tracker")
            validated = validate_native_tracker(
                checked_staging_path(run_dir, staged_state.get("path")),
                expected_spec_sha256=approved_spec["sha256"],
                expected_ticket_ids=proposal["ticket_ids"],
            )
            if validated["artifacts"] != staged_state.get("artifacts"):
                raise ContractError("recorded staged tracker changed after ticket approval")
        print(
            json.dumps(
                {
                    "approved": approved_tickets,
                    "staged": state.get("staged_tracker"),
                    "idempotent": True,
                },
                sort_keys=True,
            )
        )
        return 0

    if state.get("current_stage") != "awaiting-ticket-approval":
        raise ContractError("ticket approval is available only after a valid independent review")
    if args.scope != "tickets":
        raise ContractError("--scope spec is valid only with --decision revise")
    if not args.target:
        raise ContractError("ticket approval requires the explicit --target tracker path")
    reviewed = state.get("reviewed_tickets")
    approved_spec = state.get("approved_spec")
    if not isinstance(reviewed, dict) or not isinstance(approved_spec, dict):
        raise ContractError("ticket approval state is incomplete")
    candidate = Path(reviewed["candidate"])
    proposal = bound_proposal(
        approved_spec,
        candidate,
        reviewed["candidate_sha256"],
        "reviewed ticket candidate changed after review",
    )
    target = checked_publication_target(
        Path(state["repository"]), args.target, proposal["tracker"]["slug"]
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = run_dir.resolve() / "publication-stage"
    if staged.exists() and staged.resolve() != staged:
        raise ContractError("publication staging path resolves outside the planning run")
    if staged.exists():
        try:
            native = validate_native_tracker(
                staged,
                expected_spec_sha256=approved_spec["sha256"],
                expected_ticket_ids=proposal["ticket_ids"],
            )
        except Exception as error:
            append_event(
                run_dir,
                "publication.staging_recovery_failed",
                "unrecorded staging is incomplete or changed; preserved it for human inspection",
                {"target": str(target), "staged": str(staged), "error": str(error)},
            )
            raise
    else:
        try:
            native = stage_native_tracker(
                staged, proposal, approved_spec=Path(approved_spec["path"])
            )
        except Exception as error:
            discard_staging(run_dir)
            append_event(
                run_dir,
                "publication.staging_failed",
                "tracker staging or native validation failed; publication target is unchanged",
                {"target": str(target), "staged": str(staged), "error": str(error)},
            )
            raise
    now = utc_now()
    state = read_planning_state(state_path)
    state["approved_tickets"] = {
        "path": str(candidate.resolve()),
        "sha256": proposal["sha256"],
        "source_spec_sha256": proposal["source_spec_sha256"],
        "approved_at": now,
        "target": str(target),
    }
    state["staged_tracker"] = {
        "path": str(staged.resolve()),
        "validated_at": now,
        "ticket_ids": native["ticket_ids"],
        "ready_frontier": native["ready_frontier"],
        "artifacts": native["artifacts"],
    }
    state["current_stage"] = "ready-to-publish"
    state["updated_at"] = now
    write_json(state_path, state)
    append_event(
        run_dir,
        "tickets.approved",
        "froze the reviewed proposal and validated a complete staged native tracker",
        {
            "reason": args.reason,
            "approved_tickets": state["approved_tickets"],
            "staged_tracker": state["staged_tracker"],
        },
    )
    print(json.dumps({"approved": state["approved_tickets"], "staged": state["staged_tracker"]}, sort_keys=True))
    return 0


def publish_tracker(run_dir: Path) -> int:
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    if state.get("current_stage") == "complete":
        raise ContractError("this planning run already published its approved tracker")
    if state.get("current_stage") != "ready-to-publish":
        raise ContractError("publication requires an approved and validated staged tracker")
    approved_spec = state.get("approved_spec")
    approved_tickets = state.get("approved_tickets")
    staged_state = state.get("staged_tracker")
    if not all(isinstance(value, dict) for value in (approved_spec, approved_tickets, staged_state)):
        raise ContractError("publication state is incomplete")
    spec_path = Path(approved_spec["path"])
    if not spec_path.is_file() or sha256_file(spec_path) != approved_spec["sha256"]:
        raise ContractError("approved specification identity changed before publication")
    proposal = bound_proposal(
        approved_spec,
        Path(approved_tickets["path"]),
        approved_tickets["sha256"],
        "approved ticket proposal identity changed before publication",
    )
    target = checked_publication_target(
        Path(state["repository"]),
        approved_tickets["target"],
        proposal["tracker"]["slug"],
        allow_existing=True,
    )
    staged = checked_staging_path(run_dir, staged_state.get("path"))
    if target.exists():
        if staged.exists():
            raise ContractError(
                "publication is inconsistent: both the staged tracker and target exist; refusing a duplicate or partial overwrite"
            )
        published = validate_native_tracker(
            target,
            expected_spec_sha256=approved_spec["sha256"],
            expected_ticket_ids=proposal["ticket_ids"],
        )
        if published["artifacts"] != staged_state["artifacts"]:
            raise ContractError("existing publication target does not match the approved staged tracker")
        now = utc_now()
        state["published_tracker"] = {
            "path": str(target),
            "published_at": now,
            "ticket_ids": published["ticket_ids"],
            "ready_frontier": published["ready_frontier"],
            "artifacts": published["artifacts"],
            "recovered": True,
        }
        state["current_stage"] = "complete"
        state["updated_at"] = now
        write_json(state_path, state)
        append_event(
            run_dir,
            "tracker.publication_recovered",
            "verified an already moved tracker and completed interrupted publication state",
            state["published_tracker"],
        )
        print(json.dumps(state["published_tracker"], sort_keys=True))
        return 0

    validated = validate_native_tracker(
        staged,
        expected_spec_sha256=approved_spec["sha256"],
        expected_ticket_ids=proposal["ticket_ids"],
    )
    if validated["artifacts"] != staged_state["artifacts"]:
        raise ContractError("staged tracker changed after ticket approval")
    if staged.stat().st_dev != target.parent.stat().st_dev:
        raise ContractError("staged tracker and publication target are on different filesystems")
    os.rename(staged, target)
    published = validate_native_tracker(
        target,
        expected_spec_sha256=approved_spec["sha256"],
        expected_ticket_ids=proposal["ticket_ids"],
    )
    now = utc_now()
    state["published_tracker"] = {
        "path": str(target),
        "published_at": now,
        "ticket_ids": published["ticket_ids"],
        "ready_frontier": published["ready_frontier"],
        "artifacts": published["artifacts"],
    }
    state["current_stage"] = "complete"
    state["updated_at"] = now
    write_json(state_path, state)
    append_event(
        run_dir,
        "tracker.published",
        "atomically published the complete native tracker",
        state["published_tracker"],
    )
    print(json.dumps(state["published_tracker"], sort_keys=True))
    return 0


def resume_inputs(run_dir: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    """Freeze the useful prior handoffs into the new prompt without copying or rewriting them."""
    candidates: list[tuple[str, str]] = []
    for key, label, path_key in (
        ("author_spec", "prior specification author handoff", "draft"),
        ("reviewed_spec", "prior reviewed specification candidate", "candidate"),
        ("approved_spec", "approved specification", "path"),
        ("author_tickets", "prior ticket author proposal", "proposal"),
        ("reviewed_tickets", "prior reviewed ticket candidate", "candidate"),
    ):
        pointer = state.get(key)
        if isinstance(pointer, dict) and isinstance(pointer.get(path_key), str):
            candidates.append((label, pointer[path_key]))
    for directory in (run_dir / "reports", run_dir / "artifacts"):
        if directory.is_dir():
            candidates.extend(("preserved run handoff", str(path)) for path in sorted(directory.iterdir()) if path.is_file())
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    root = run_dir.resolve()
    for label, value in candidates:
        path = Path(value).resolve()
        if str(path) in seen or not path.is_file():
            continue
        try:
            path.relative_to(root)
        except ValueError:
            continue
        seen.add(str(path))
        result.append({"label": label, "path": str(path), "sha256": sha256_file(path)})
    return result


def resume_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    payload = status_payload(run_dir, cmux_cmd=args.cmux_cmd)
    if args.decision == "rejoin" and payload["classification"] == "input-validation":
        finish_input_validation(run_dir)
        print(json.dumps(status_payload(run_dir, cmux_cmd=args.cmux_cmd), indent=2, sort_keys=True))
        return 0
    if args.decision is None or args.decision == "rejoin":
        if args.decision == "rejoin" and payload["classification"] in {"hitl", "inconsistent"}:
            raise ContractError(
                "this run cannot be rejoined safely; inspect the persisted context and make an explicit relaunch or revision decision"
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.decision == "extend":
        if not args.reason:
            raise ContractError("--decision extend requires a human-authored --reason")
        stage = payload["stage"]["current"]
        if stage not in STAGES or payload["pane"]["status"] != "deadline":
            raise ContractError("a watcher extension is available only after the first live-pane deadline")
        append_event(
            run_dir,
            "worker.waiting",
            "human approved the run's one watcher deadline extension",
            {
                "stage": stage,
                "pass": payload["stage"]["pass"],
                "surface_id": payload["pane"]["surface_id"],
                "outcome": "extension_approved",
                "extension": 1,
                "reason": args.reason,
            },
        )
        print(json.dumps(status_payload(run_dir, cmux_cmd=args.cmux_cmd), indent=2, sort_keys=True))
        return 0

    if not args.reason:
        raise ContractError("--decision relaunch requires a human-authored --reason")
    state_path = run_dir / "state.json"
    state = read_planning_state(state_path)
    stage = state.get("current_stage")
    if stage in {"awaiting-spec-approval", "awaiting-ticket-approval"}:
        raise ContractError(
            "approval recovery reuses the same digest-bound walkthrough; use the approval view or an explicit revision command"
        )
    if stage in {"ready-to-publish", "complete"}:
        raise ContractError("publication recovery never relaunches a worker")
    target = stage
    if stage in {"spec-blocked", "spec-review-blocked"}:
        target = "spec"
    elif stage in {"tickets-blocked", "tickets-review-blocked"}:
        target = "tickets"
    elif stage == "integrity-violation":
        ensure_integrity_resolved(run_dir, state)
        gates = state.get("gate_decisions", [])
        source = gates[-1].get("stage") if gates and isinstance(gates[-1], dict) else None
        target = "tickets" if isinstance(source, str) and source.startswith("tickets") else "spec"
    elif stage not in STAGES:
        raise ContractError(f"cannot relaunch from planning stage {stage!r}")
    elif payload["pane"]["status"] not in {"dead", "watcher-expired"}:
        raise ContractError(
            "a fresh pass requires recorded pane death or watcher expiry; rejoin the existing assignment otherwise"
        )

    if stage in STAGES:
        ensure_relaunch_tree_safe(run_dir, state, stage, stage_pass(state, stage))

    old_pass = (
        stage_pass(state, stage)
        if stage in STAGES
        else state["tickets_pass"]
        if isinstance(stage, str) and stage.startswith("tickets")
        else state["spec_pass"]
    )
    prior = resume_inputs(run_dir, state)
    now = utc_now()
    if target == "spec-review":
        state["spec_review_pass"] = state.get("spec_review_pass", state["spec_pass"]) + 1
        next_pass = state["spec_review_pass"]
        state["reviewed_spec"] = None
    elif target == "tickets-review":
        state["tickets_review_pass"] = state.get("tickets_review_pass", state["tickets_pass"]) + 1
        next_pass = state["tickets_review_pass"]
        state["reviewed_tickets"] = None
    elif target == "spec":
        state["spec_pass"] += 1
        state["spec_review_pass"] = state.get("spec_review_pass", old_pass) + 1
        next_pass = state["spec_pass"]
        state["author_spec"] = None
        state["reviewed_spec"] = None
        state["spec_revision_feedback"] = args.reason
        if state.get("approved_spec") is not None:
            state["tickets_pass"] += 1
            state["tickets_review_pass"] = state.get("tickets_review_pass", state["tickets_pass"] - 1) + 1
            reset_ticket_state(state)
            discard_staging(run_dir)
    else:
        state["tickets_pass"] += 1
        state["tickets_review_pass"] = state.get("tickets_review_pass", old_pass) + 1
        next_pass = state["tickets_pass"]
        state["author_tickets"] = None
        state["reviewed_tickets"] = None
        state["approved_tickets"] = None
        state["staged_tracker"] = None
        state["ticket_revision_feedback"] = args.reason
        discard_staging(run_dir)

    state["current_stage"] = target
    state["prepared_stage"] = None
    state["tree_baseline"] = None
    state["resume_context"] = {
        "recorded_at": now,
        "reason": args.reason,
        "from_stage": stage,
        "from_pass": old_pass,
        "to_stage": target,
        "to_pass": next_pass,
        "prior_handoffs": prior,
    }
    state["updated_at"] = now
    write_json(state_path, state)
    append_event(
        run_dir,
        "run.relaunch_approved",
        "human approved one fresh numbered recovery pass; prior panes and handoffs were preserved",
        state["resume_context"],
        time=now,
    )
    pointer = prepare_stage(args, run_dir, target, next_pass)
    print(json.dumps({"resume": state["resume_context"], "prepared": pointer}, sort_keys=True))
    return 0


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        return init_run(args)
    if args.command == "show-revalidation":
        return show_revalidation(Path(args.run_dir))
    if args.command == "revalidate":
        return revalidate(args)
    if args.command == "prepare":
        pointer = prepare_stage(args, Path(args.run_dir), args.stage, args.pass_num)
        print(json.dumps(pointer, sort_keys=True))
        return 0
    if args.command == "accept-author":
        return accept_author(args)
    if args.command == "accept-review":
        return accept_review(args)
    if args.command == "approval-view":
        return approval_view(Path(args.run_dir))
    if args.command == "approval":
        return approval(args)
    if args.command == "ticket-approval-view":
        return ticket_approval_view(Path(args.run_dir))
    if args.command == "ticket-approval":
        return ticket_approval(args)
    if args.command == "publish":
        run_dir = Path(args.run_dir)
        try:
            return publish_tracker(run_dir)
        except (ContractError, OSError, ValueError, KeyError) as error:
            if (run_dir / "state.json").is_file():
                append_event(
                    run_dir,
                    "publication.failed",
                    "publication precondition or validation failed",
                    {"error": str(error)},
                )
            raise
    if args.command == "status":
        print(json.dumps(status_payload(Path(args.run_dir), cmux_cmd=args.cmux_cmd), indent=2, sort_keys=True))
        return 0
    if args.command == "context":
        run_dir = Path(args.run_dir).resolve()
        print(
            json.dumps(
                recovery_context(run_dir, read_planning_state(run_dir / "state.json")),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "resume":
        return resume_run(args)
    raise AssertionError(args.command)


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except (ConfigError, SnapshotError, ContractError, GrillingInputError, IntegrityError, OSError, ValueError, KeyError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
