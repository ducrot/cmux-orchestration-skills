#!/usr/bin/env python3
"""Resolve, preflight, persist, and validate issue-chain worker stage snapshots."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from agents_config import (
    COMPATIBLE_HARNESSES,
    DEFAULT_PROBE_TIMEOUT_SECONDS,
    HarnessError,
    SUBAGENT_MARKER_ENV,
    SUBAGENT_MARKER_VALUE,
    WORKFLOW_WORKERS,
    adapter_argv,
    audit_workers,
    parse_overrides,
    positive_finite,
    probe_options,
    probe_workers,
    resolve_config_source,
    resolve_workers,
    shell_command,
    snapshot_identity,
    valid_executable_syntax,
    valid_probe_record,
)
from orchestrator_lib import read_run_state
from orchestrator_lib import read_json, utc_now, write_json


WORKFLOW = "issue-chain"
ISSUE_WORKERS = WORKFLOW_WORKERS[WORKFLOW]
SNAPSHOT_VERSION = 1

# Workflow safety policy, not a per-run choice (SKILL.md, CMUX Control, explains what each flag
# buys). Applied to every Codex worker on top of its configured model and effort.
CODEX_SAFETY_ARGUMENTS = [
    "-s",
    "workspace-write",
    "-c",
    "sandbox_workspace_write.network_access=true",
    "-c",
    'sandbox_workspace_write.writable_roots=["~/.ddev"]',
    "--ask-for-approval",
    "on-request",
    "-c",
    "approvals_reviewer=auto_review",
    "-c",
    "check_for_update_on_startup=false",
]


# Shared with the harness runtime, so stage code catches preflight, launch, and probe failures
# alongside its own snapshot failures.
SnapshotError = HarnessError


def stage_argv(worker: str, profile: dict[str, Any]) -> list[str]:
    """Issue-chain's sandbox policy: every Codex worker gets the same one."""
    return adapter_argv(profile, codex_arguments=CODEX_SAFETY_ARGUMENTS)


def build_stage_snapshot(
    *,
    run_id: str,
    stage: str,
    pass_num: int,
    source: Path,
    config_sha256: str,
    data: dict[str, Any],
    overrides: dict[str, dict[str, str]],
    probe_profiles: bool = False,
    probe_timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if stage not in ISSUE_WORKERS:
        raise SnapshotError(f"unknown issue-chain stage: {stage}")
    if pass_num < 1:
        raise SnapshotError("stage pass must be a positive integer")
    resolved = resolve_workers(data, source, overrides, workflow=WORKFLOW)
    audited = audit_workers(resolved, source, workflow=WORKFLOW, argv_for=stage_argv)
    if probe_profiles:
        probe_workers(
            audited, source, workflow=WORKFLOW, timeout_seconds=probe_timeout_seconds
        )

    resolved_at = utc_now()
    snapshot: dict[str, Any] = {
        "snapshot_version": SNAPSHOT_VERSION,
        "run_id": run_id,
        "stage": stage,
        "pass": pass_num,
        "status": "passed",
        "resolved_at": resolved_at,
        "config": {
            "source": str(source),
            "sha256": config_sha256,
        },
        "effective_overrides": copy.deepcopy(overrides),
        "live_profile_probe": {
            "enabled": probe_profiles,
            "timeout_seconds": probe_timeout_seconds,
        },
        "resolved_profiles": audited,
        "selected_worker": copy.deepcopy(audited[stage]),
    }
    snapshot["snapshot_id"] = snapshot_identity(snapshot)
    return snapshot


def snapshot_from_args(
    args: argparse.Namespace,
    *,
    run_id: str,
    stage: str,
    pass_num: int,
    config_source: str | None,
) -> tuple[Path, dict[str, Any]]:
    """The one path from CLI inputs to a validated, preflighted, launchable stage snapshot."""
    overrides = parse_overrides(args, workflow=WORKFLOW)
    probe_profiles, probe_timeout = probe_options(args)
    source, data, config_sha256 = resolve_config_source(config_source)
    snapshot = build_stage_snapshot(
        run_id=run_id,
        stage=stage,
        pass_num=pass_num,
        source=source,
        config_sha256=config_sha256,
        data=data,
        overrides=overrides,
        probe_profiles=probe_profiles,
        probe_timeout_seconds=probe_timeout,
    )
    return source, snapshot


def persist_snapshot(run_dir: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    name = f"{snapshot['stage']}-{snapshot['pass']}-{snapshot['snapshot_id'][:16]}.json"
    relative = Path("stage-snapshots") / name
    destination = run_dir / relative
    write_json(destination, snapshot)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "stage": snapshot["stage"],
        "pass": snapshot["pass"],
        "path": str(relative),
        "sha256": digest,
        "snapshot_id": snapshot["snapshot_id"],
        "prepared_at": snapshot["resolved_at"],
    }


def validate_probe_audit(snapshot: dict[str, Any]) -> None:
    operational = snapshot.get("live_profile_probe")
    # Snapshot v1 predates opt-in probes. Its unverified entitlement is equivalent to disabled.
    if operational is None:
        operational = {
            "enabled": False,
            "timeout_seconds": DEFAULT_PROBE_TIMEOUT_SECONDS,
        }
    if not isinstance(operational, dict) or not isinstance(operational.get("enabled"), bool):
        raise SnapshotError("prepared stage snapshot has invalid live-probe operational state")
    timeout = operational.get("timeout_seconds")
    if not positive_finite(timeout):
        raise SnapshotError("prepared stage snapshot has invalid live-probe timeout state")
    resolved = snapshot.get("resolved_profiles")
    if not isinstance(resolved, dict) or set(resolved) != set(ISSUE_WORKERS):
        raise SnapshotError("prepared stage snapshot does not contain exactly all issue-chain workers")
    expected_status = "verified" if operational["enabled"] else "unverified"
    for worker in ISSUE_WORKERS:
        entry = resolved[worker]
        entitlement = entry.get("entitlement") if isinstance(entry, dict) else None
        if not isinstance(entitlement, dict) or entitlement.get("status") != expected_status:
            raise SnapshotError(
                f"prepared stage snapshot worker {worker} has inconsistent entitlement state"
            )
        if operational["enabled"] and not valid_probe_record(entitlement.get("probe"), timeout):
            raise SnapshotError(
                f"prepared stage snapshot worker {worker} has invalid live-probe audit data"
            )


def load_launchable_snapshot(run_dir: Path, role: str, pass_num: int) -> dict[str, Any]:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise SnapshotError(f"No state.json under {run_dir} — run run_state.py init first")
    state = read_run_state(run_dir)
    pointer = state.get("prepared_stage")
    if not isinstance(pointer, dict):
        raise SnapshotError("no prepared stage snapshot is active; run run_state.py prepare first")
    if state.get("current_stage") != role:
        raise SnapshotError(
            f"prepared stage is stale: run current_stage is {state.get('current_stage')!r}, not {role!r}"
        )
    if pointer.get("stage") != role or pointer.get("pass") != pass_num:
        raise SnapshotError(
            f"prepared stage mismatch: requested {role}-{pass_num}, pointer is "
            f"{pointer.get('stage')}-{pointer.get('pass')}"
        )
    relative_text = pointer.get("path")
    if not isinstance(relative_text, str) or not relative_text:
        raise SnapshotError("prepared stage pointer has no snapshot path")
    relative = Path(relative_text)
    if relative.is_absolute():
        raise SnapshotError("prepared stage snapshot path must be relative to the run directory")
    root = run_dir.resolve()
    path = (run_dir / relative).resolve()
    if root not in path.parents:
        raise SnapshotError("prepared stage snapshot path escapes the run directory")
    if not path.is_file():
        raise SnapshotError(f"prepared stage snapshot is missing: {path}")
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise SnapshotError(f"prepared stage snapshot is unreadable: {error}") from error
    # Hash and parse one buffer. A second read could return bytes the digest never covered.
    if hashlib.sha256(payload).hexdigest() != pointer.get("sha256"):
        raise SnapshotError("prepared stage snapshot hash mismatch")
    try:
        snapshot = json.loads(payload.decode("utf-8"))
    except ValueError as error:
        raise SnapshotError(f"prepared stage snapshot is unreadable: {error}") from error
    checks = {
        "snapshot version": snapshot.get("snapshot_version") == SNAPSHOT_VERSION,
        "snapshot status": snapshot.get("status") == "passed",
        "run id": snapshot.get("run_id") == state.get("run_id"),
        "stage": snapshot.get("stage") == role,
        "pass": snapshot.get("pass") == pass_num,
        "snapshot id": snapshot.get("snapshot_id") == pointer.get("snapshot_id"),
        "snapshot identity": snapshot_identity(snapshot) == snapshot.get("snapshot_id"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SnapshotError("prepared stage snapshot failed validation: " + ", ".join(failed))
    validate_probe_audit(snapshot)
    selected = snapshot.get("selected_worker")
    if not isinstance(selected, dict) or selected.get("preflight", {}).get("status") != "passed":
        raise SnapshotError("prepared stage snapshot has no successful selected-worker preflight")
    if not selected.get("resolved_executable") or not selected.get("detected_version"):
        raise SnapshotError("prepared stage snapshot has no executable audit record")
    argv = selected.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
        raise SnapshotError("prepared stage snapshot has an invalid final argument vector")
    if argv[0] != selected.get("requested_executable"):
        raise SnapshotError("prepared stage snapshot executable does not match its argument vector")
    # argv[0] is the launch identity, so re-check its syntax here too: preparation validated the
    # configured value, but only this check binds what a pane is actually told to run.
    if not valid_executable_syntax(argv[0]):
        raise SnapshotError("prepared stage snapshot launches an invalid program name")
    if selected.get("environment") != {SUBAGENT_MARKER_ENV: SUBAGENT_MARKER_VALUE}:
        raise SnapshotError("prepared stage snapshot has invalid managed-agent settings")
    if selected.get("harness") not in COMPATIBLE_HARNESSES[WORKFLOW][role]:
        raise SnapshotError("prepared stage snapshot has an incompatible harness")
    try:
        expected_argv = stage_argv(role, selected)
    except (KeyError, TypeError, SnapshotError) as error:
        raise SnapshotError("prepared stage snapshot has incomplete adapter data") from error
    # argv[1:] is workflow safety policy that configuration cannot supply. Re-deriving it here
    # is what stops a restamped snapshot from widening the sandbox it launches under.
    if argv != expected_argv:
        raise SnapshotError("prepared stage snapshot argument vector violates adapter policy")
    return snapshot


def snapshot_shell_command(snapshot: dict[str, Any]) -> str:
    selected = snapshot["selected_worker"]
    return shell_command(selected["environment"], selected["argv"])


def snapshot_launch_record(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Audit fields for a launch event, so callers never walk the snapshot schema themselves."""
    selected = snapshot["selected_worker"]
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "argv": list(selected["argv"]),
        # argv[0] is a program name the pane resolves itself, so the event carries what preflight
        # actually inspected.
        "resolved_executable": selected["resolved_executable"],
        "detected_version": selected["detected_version"],
    }
