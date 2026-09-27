#!/usr/bin/env python3
"""Resolve, preflight, persist, and validate one immutable grilling launch wave."""

from __future__ import annotations

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
    git_root,
    positive_finite,
    probe_workers,
    resolve_workers,
    shell_command,
    snapshot_identity,
    valid_executable_syntax,
    valid_probe_record,
    valid_trust_record,
)
from orchestrator_lib import read_json, read_run_state, utc_now, write_json


WORKFLOW = "grilling"
GRILLING_LANES = WORKFLOW_WORKERS[WORKFLOW]
SNAPSHOT_VERSION = 1

# Fixed grilling policy. Every Codex lane must be able to write its draft and report handoff, while only
# web-enabled lanes receive network access. No grilling lane receives ddev's writable root
# because these workers do not run project containers.
CODEX_SANDBOX_ARGUMENTS = [
    "-s",
    "workspace-write",
]
CODEX_NETWORK_ARGUMENTS = [
    "-c",
    "sandbox_workspace_write.network_access=true",
]
# Only the documentation lane needs to reach the network. The web lane is Claude Code-only
# by COMPATIBLE_HARNESSES and has no sandbox to grant, so this set is the whole grant.
CODEX_NETWORK_LANES = {"docs"}
CODEX_APPROVAL_ARGUMENTS = [
    "--ask-for-approval",
    "on-request",
    "-c",
    "approvals_reviewer=auto_review",
    "-c",
    "check_for_update_on_startup=false",
    "-c",
    "tui.whimsy=false",
]


# Shared with the harness runtime, so wave code catches preflight, launch, and probe failures
# alongside its own wave failures.
LaunchWaveError = HarnessError


def lane_argv(lane: str, profile: dict[str, Any]) -> list[str]:
    """Grilling's sandbox policy: only the documentation lane gets network access."""
    network = CODEX_NETWORK_ARGUMENTS if lane in CODEX_NETWORK_LANES else []
    return adapter_argv(
        profile,
        codex_arguments=[*CODEX_SANDBOX_ARGUMENTS, *network, *CODEX_APPROVAL_ARGUMENTS],
    )


def audit_lanes(
    resolved: dict[str, dict[str, str]], source: Path, repository: str
) -> dict[str, dict[str, Any]]:
    audited = audit_workers(resolved, source, workflow=WORKFLOW, argv_for=lane_argv, repository=repository)
    for lane, entry in audited.items():
        # The loader refuses an entry whose lane does not match where it was found.
        entry["lane"] = lane
    return audited


def build_launch_wave(
    *,
    run_id: str,
    source: Path,
    config_sha256: str,
    data: dict[str, Any],
    overrides: dict[str, dict[str, str]],
    probe_profiles: bool = False,
    probe_timeout_seconds: float = DEFAULT_PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    resolved = resolve_workers(data, source, overrides, workflow=WORKFLOW)
    repository = str(git_root(Path.cwd()))
    audited = audit_lanes(resolved, source, repository)
    if probe_profiles:
        probe_workers(
            audited, source, workflow=WORKFLOW, timeout_seconds=probe_timeout_seconds
        )
    resolved_at = utc_now()
    snapshot: dict[str, Any] = {
        "repository": repository,
        "snapshot_version": SNAPSHOT_VERSION,
        "run_id": run_id,
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
    }
    snapshot["snapshot_id"] = snapshot_identity(snapshot)
    return snapshot


def persist_launch_wave(run_dir: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    name = f"launch-wave-{snapshot['snapshot_id'][:16]}.json"
    relative = Path("launch-waves") / name
    destination = run_dir / relative
    write_json(destination, snapshot)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return {
        "path": str(relative),
        "sha256": digest,
        "snapshot_id": snapshot["snapshot_id"],
        "prepared_at": snapshot["resolved_at"],
    }


def _load_wave_bytes(run_dir: Path, pointer: dict[str, Any]) -> bytes:
    relative_text = pointer.get("path")
    if not isinstance(relative_text, str) or not relative_text:
        raise LaunchWaveError("prepared launch-wave pointer has no snapshot path")
    relative = Path(relative_text)
    if relative.is_absolute():
        raise LaunchWaveError("prepared launch-wave snapshot path must be relative to the run directory")
    root = run_dir.resolve()
    path = (run_dir / relative).resolve()
    if root not in path.parents:
        raise LaunchWaveError("prepared launch-wave snapshot path escapes the run directory")
    if not path.is_file():
        raise LaunchWaveError(f"prepared launch-wave snapshot is missing: {path}")
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise LaunchWaveError(f"prepared launch-wave snapshot is unreadable: {error}") from error
    if hashlib.sha256(payload).hexdigest() != pointer.get("sha256"):
        raise LaunchWaveError("prepared launch-wave snapshot hash mismatch")
    return payload


def _validate_lane_entry(lane: str, entry: object, probe_state: dict[str, Any], repository: object) -> None:
    if not isinstance(entry, dict):
        raise LaunchWaveError(f"prepared launch wave has no valid entry for lane {lane}")
    if entry.get("lane") != lane:
        raise LaunchWaveError(f"prepared launch-wave lane mismatch for {lane}")
    if not valid_trust_record(entry, repository):
        raise LaunchWaveError(f"prepared launch-wave lane {lane} has no valid trust preflight; prepare again")
    preflight = entry.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("status") != "passed":
        raise LaunchWaveError(f"prepared launch-wave lane {lane} has no successful preflight")
    if not entry.get("resolved_executable") or not entry.get("detected_version"):
        raise LaunchWaveError(f"prepared launch-wave lane {lane} has no executable audit record")
    argv = entry.get("argv")
    if not isinstance(argv, list) or not argv or not all(
        isinstance(value, str) and value for value in argv
    ):
        raise LaunchWaveError(f"prepared launch-wave lane {lane} has an invalid argument vector")
    if argv[0] != entry.get("requested_executable"):
        raise LaunchWaveError(
            f"prepared launch-wave lane {lane} executable does not match its argument vector"
        )
    if not valid_executable_syntax(argv[0]):
        raise LaunchWaveError(f"prepared launch-wave lane {lane} launches an invalid program name")
    if entry.get("environment") != {SUBAGENT_MARKER_ENV: SUBAGENT_MARKER_VALUE}:
        raise LaunchWaveError(f"prepared launch-wave lane {lane} has invalid managed-agent settings")
    if entry.get("harness") not in COMPATIBLE_HARNESSES[WORKFLOW][lane]:
        raise LaunchWaveError(f"prepared launch-wave lane {lane} has an incompatible harness")
    entitlement = entry.get("entitlement")
    expected_status = "verified" if probe_state["enabled"] else "unverified"
    if not isinstance(entitlement, dict) or entitlement.get("status") != expected_status:
        raise LaunchWaveError(
            f"prepared launch-wave lane {lane} has inconsistent entitlement state"
        )
    if probe_state["enabled"] and not valid_probe_record(
        entitlement.get("probe"), probe_state["timeout_seconds"]
    ):
        raise LaunchWaveError(
            f"prepared launch-wave lane {lane} has invalid live-probe audit data"
        )
    try:
        expected_argv = lane_argv(lane, entry)
    except (KeyError, TypeError, LaunchWaveError) as error:
        raise LaunchWaveError(
            f"prepared launch-wave lane {lane} has incomplete adapter data"
        ) from error
    if argv != expected_argv:
        raise LaunchWaveError(f"prepared launch-wave lane {lane} argument vector violates adapter policy")


def load_launchable_lane(run_dir: Path, lane: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if lane not in GRILLING_LANES:
        raise LaunchWaveError(f"unknown grilling lane: {lane}")
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise LaunchWaveError(f"No state.json under {run_dir} — run run_state.py init first")
    state = read_run_state(run_dir)
    pointer = state.get("launch_wave")
    if not isinstance(pointer, dict):
        raise LaunchWaveError("no prepared launch wave is active; start a new grilling run")
    payload = _load_wave_bytes(run_dir, pointer)
    try:
        snapshot = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise LaunchWaveError(f"prepared launch-wave snapshot is unreadable: {error}") from error
    checks = {
        "snapshot version": snapshot.get("snapshot_version") == SNAPSHOT_VERSION,
        "snapshot status": snapshot.get("status") == "passed",
        "run id": snapshot.get("run_id") == state.get("run_id"),
        "snapshot id": snapshot.get("snapshot_id") == pointer.get("snapshot_id"),
        "snapshot identity": snapshot_identity(snapshot) == snapshot.get("snapshot_id"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise LaunchWaveError("prepared launch-wave snapshot failed validation: " + ", ".join(failed))
    resolved = snapshot.get("resolved_profiles")
    if not isinstance(resolved, dict) or set(resolved) != set(GRILLING_LANES):
        raise LaunchWaveError("prepared launch wave does not contain exactly all four lanes")
    probe_state = snapshot.get("live_profile_probe")
    # Snapshot v1 predates opt-in probes. Its unverified entitlement is equivalent to disabled.
    if probe_state is None:
        probe_state = {
            "enabled": False,
            "timeout_seconds": DEFAULT_PROBE_TIMEOUT_SECONDS,
        }
    if not isinstance(probe_state, dict) or not isinstance(probe_state.get("enabled"), bool):
        raise LaunchWaveError("prepared launch wave has invalid live-probe operational state")
    if not positive_finite(probe_state.get("timeout_seconds")):
        raise LaunchWaveError("prepared launch wave has invalid live-probe timeout state")
    for prepared_lane in GRILLING_LANES:
        _validate_lane_entry(prepared_lane, resolved[prepared_lane], probe_state, snapshot.get("repository"))
    return snapshot, copy.deepcopy(resolved[lane])


def lane_shell_command(entry: dict[str, Any], *extra_args: str) -> str:
    return shell_command(entry["environment"], [*entry["argv"], *extra_args])


def lane_launch_record(snapshot: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "argv": list(entry["argv"]),
        "resolved_executable": entry["resolved_executable"],
        "detected_version": entry["detected_version"],
    }
