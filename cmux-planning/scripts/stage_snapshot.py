#!/usr/bin/env python3
"""Resolve and validate immutable cmux-planning spec-stage launch snapshots."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from agents_config import (
    COMPATIBLE_HARNESSES,
    DEFAULT_PROBE_TIMEOUT_SECONDS,
    SUBAGENT_MARKER_ENV,
    SUBAGENT_MARKER_VALUE,
    HarnessError,
    adapter_argv,
    audit_workers,
    parse_overrides,
    probe_options,
    probe_workers,
    resolve_config_source,
    resolve_workers,
    shell_command,
    snapshot_identity,
    valid_executable_syntax,
)
from orchestrator_lib import integrity_boundary, read_json, sha256_file, utc_now, write_json


WORKFLOW = "planning"
STAGE_ROLE = {"spec": "spec", "spec-review": "reviewer"}
SNAPSHOT_VERSION = 1
CODEX_SAFETY_ARGUMENTS = [
    "-s",
    "workspace-write",
    "-c",
    "sandbox_workspace_write.network_access=false",
    "--ask-for-approval",
    "on-request",
    "-c",
    "approvals_reviewer=auto_review",
    "-c",
    "check_for_update_on_startup=false",
]


SnapshotError = HarnessError


def stage_argv(role: str, profile: dict[str, Any]) -> list[str]:
    argv = adapter_argv(profile, codex_arguments=CODEX_SAFETY_ARGUMENTS)
    if profile["harness"] == "claude-code":
        argv.extend(["--permission-mode", "acceptEdits"])
    return argv


def handoff_paths(run_dir: Path, stage: str, pass_num: int) -> dict[str, str]:
    if stage == "spec":
        return {
            "draft": str((run_dir / "artifacts" / f"spec-{pass_num}.md").resolve()),
            "report": str((run_dir / "reports" / f"spec-{pass_num}.md").resolve()),
        }
    if stage == "spec-review":
        return {
            "candidate": str((run_dir / "artifacts" / f"spec-reviewed-{pass_num}.md").resolve()),
            "report": str((run_dir / "reports" / f"spec-review-{pass_num}.md").resolve()),
        }
    raise SnapshotError(f"unknown planning stage: {stage}")


def build_stage_snapshot(
    *,
    run_dir: Path,
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
    if stage not in STAGE_ROLE:
        raise SnapshotError(f"unknown planning stage: {stage}")
    if pass_num < 1:
        raise SnapshotError("stage pass must be a positive integer")
    resolved = resolve_workers(data, source, overrides, workflow=WORKFLOW)
    audited = audit_workers(resolved, source, workflow=WORKFLOW, argv_for=stage_argv)
    if audited["reviewer"]["harness"] != "codex":
        raise SnapshotError("planning reviewer must resolve to the Codex harness")
    if probe_profiles:
        probe_workers(audited, source, workflow=WORKFLOW, timeout_seconds=probe_timeout_seconds)
    selected_role = STAGE_ROLE[stage]
    snapshot: dict[str, Any] = {
        "snapshot_version": SNAPSHOT_VERSION,
        "run_id": run_id,
        "stage": stage,
        "role": selected_role,
        "pass": pass_num,
        "status": "passed",
        "resolved_at": utc_now(),
        "config": {"source": str(source), "sha256": config_sha256},
        "effective_overrides": copy.deepcopy(overrides),
        "live_profile_probe": {
            "enabled": probe_profiles,
            "timeout_seconds": probe_timeout_seconds,
        },
        "resolved_profiles": audited,
        "selected_worker": copy.deepcopy(audited[selected_role]),
        "allowed_worker_writes": handoff_paths(run_dir, stage, pass_num),
        "integrity_detector": integrity_boundary(),
    }
    snapshot["snapshot_id"] = snapshot_identity(snapshot)
    return snapshot


def snapshot_from_args(
    args: Any,
    *,
    run_dir: Path,
    run_id: str,
    stage: str,
    pass_num: int,
    config_source: str,
) -> tuple[Path, dict[str, Any]]:
    overrides = parse_overrides(args, workflow=WORKFLOW)
    probe_profiles, probe_timeout = probe_options(args)
    source, data, digest = resolve_config_source(config_source)
    return source, build_stage_snapshot(
        run_dir=run_dir,
        run_id=run_id,
        stage=stage,
        pass_num=pass_num,
        source=source,
        config_sha256=digest,
        data=data,
        overrides=overrides,
        probe_profiles=probe_profiles,
        probe_timeout_seconds=probe_timeout,
    )


def persist_snapshot(run_dir: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    relative = Path("stage-snapshots") / (
        f"{snapshot['stage']}-{snapshot['pass']}-{snapshot['snapshot_id'][:16]}.json"
    )
    destination = run_dir / relative
    write_json(destination, snapshot)
    return {
        "stage": snapshot["stage"],
        "pass": snapshot["pass"],
        "path": str(relative),
        "sha256": sha256_file(destination),
        "snapshot_id": snapshot["snapshot_id"],
        "prepared_at": snapshot["resolved_at"],
    }


def load_prepared_snapshot(
    run_dir: Path, stage: str, pass_num: int, *, require_baseline: bool = True
) -> dict[str, Any]:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise SnapshotError(f"No state.json under {run_dir}")
    state = read_json(state_path)
    pointer = state.get("prepared_stage")
    if state.get("current_stage") != stage:
        raise SnapshotError(f"run current_stage is {state.get('current_stage')!r}, not {stage!r}")
    if not isinstance(pointer, dict) or pointer.get("stage") != stage or pointer.get("pass") != pass_num:
        raise SnapshotError("no matching prepared stage snapshot is active")
    relative = Path(pointer.get("path", ""))
    if relative.is_absolute() or ".." in relative.parts:
        raise SnapshotError("prepared stage snapshot path is unsafe")
    path = run_dir / relative
    if not path.is_file():
        raise SnapshotError("prepared stage snapshot is missing or changed")
    # Hash and parse one buffer. A second read could return bytes the digest never covered.
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != pointer.get("sha256"):
        raise SnapshotError("prepared stage snapshot is missing or changed")
    try:
        snapshot = json.loads(payload.decode("utf-8"))
    except ValueError as error:
        raise SnapshotError(f"prepared stage snapshot is unreadable: {error}") from error
    if snapshot_identity(snapshot) != snapshot.get("snapshot_id") or snapshot["snapshot_id"] != pointer.get("snapshot_id"):
        raise SnapshotError("prepared stage snapshot identity is invalid")
    role = STAGE_ROLE[stage]
    checks = {
        "snapshot version": snapshot.get("snapshot_version") == SNAPSHOT_VERSION,
        "snapshot status": snapshot.get("status") == "passed",
        "run id": snapshot.get("run_id") == state.get("run_id"),
        "role": snapshot.get("role") == role,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SnapshotError("prepared stage snapshot failed validation: " + ", ".join(failed))
    selected = snapshot.get("selected_worker")
    if not isinstance(selected, dict) or selected.get("harness") not in COMPATIBLE_HARNESSES[WORKFLOW][role]:
        raise SnapshotError(f"prepared {role} has no compatible selected worker")
    if selected.get("preflight", {}).get("status") != "passed":
        raise SnapshotError("prepared stage snapshot has no successful selected-worker preflight")
    if selected.get("environment") != {SUBAGENT_MARKER_ENV: SUBAGENT_MARKER_VALUE}:
        raise SnapshotError("prepared stage lost its managed-subagent launch environment")
    argv = selected.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
        raise SnapshotError("prepared stage snapshot has an invalid final argument vector")
    if argv[0] != selected.get("requested_executable") or not valid_executable_syntax(argv[0]):
        raise SnapshotError("prepared stage snapshot launches an invalid program name")
    try:
        expected_argv = stage_argv(role, selected)
    except (KeyError, TypeError, SnapshotError) as error:
        raise SnapshotError("prepared stage snapshot has incomplete adapter data") from error
    # argv[1:] is workflow sandbox policy that configuration cannot supply, and snapshot_id is an
    # unkeyed self-hash anyone editing the run directory can recompute. Re-deriving the vector is
    # what stops a restamped snapshot from widening the sandbox it launches under.
    if argv != expected_argv:
        raise SnapshotError("prepared stage snapshot argument vector violates adapter policy")
    if require_baseline:
        baseline = state.get("tree_baseline")
        if not isinstance(baseline, dict) or baseline.get("stage") != stage or baseline.get("pass") != pass_num:
            raise SnapshotError("stage is prepared but not launchable until its tree baseline is captured")
        if baseline.get("snapshot_id") != snapshot["snapshot_id"]:
            raise SnapshotError("tree baseline is not bound to the active prepared snapshot")
        prompt_path = Path(baseline.get("prompt_path", ""))
        if not prompt_path.is_file() or sha256_file(prompt_path) != baseline.get("prompt_sha256"):
            raise SnapshotError("rendered stage prompt is missing or changed after the tree baseline")
    return snapshot


def snapshot_shell_command(snapshot: dict[str, Any]) -> str:
    selected = snapshot["selected_worker"]
    return shell_command(selected["environment"], selected["argv"])


def snapshot_launch_record(snapshot: dict[str, Any]) -> dict[str, Any]:
    selected = snapshot["selected_worker"]
    return {
        "stage_snapshot_id": snapshot["snapshot_id"],
        "profile": selected["profile"],
        "harness": selected["harness"],
        "model": selected["model"],
        "effort": selected["effort"],
        "allowed_worker_writes": snapshot["allowed_worker_writes"],
    }
