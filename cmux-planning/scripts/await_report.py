#!/usr/bin/env python3
"""Armed planning-report watcher with stable CMUX surface health checks."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from artifact_manifest import (
    ArtifactIntegrityError,
    current_attempt,
    record_artifact,
    verify_or_gate,
)
from orchestrator_lib import (
    MINIMUM_WAIT_MINUTES,
    STAGES,
    append_event,
    planning_events,
    read_planning_state,
    sha256_file,
    validate_recorded_surface,
    write_json,
)
from stage_snapshot import load_prepared_snapshot


EXIT_REPORT = 0
EXIT_PANE_DEAD = 7
EXIT_DEADLINE = 8
EXIT_NOT_STARTED = 9
# 1 = crash, 2 = argparse usage. Outcomes stay clear of both so a usage error is never
# mistaken for a deadline.


def report_path(run_dir: Path, stage: str, pass_num: int) -> Path:
    snapshot = load_prepared_snapshot(run_dir, stage, pass_num)
    return Path(snapshot["allowed_worker_writes"]["report"])


def surface_is_dead(output: str, surface: str) -> bool:
    """Dead only when a successful health listing does not name the surface. An output shape
    this does not understand is not evidence of death."""
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        # The command is invoked with --json, so anything else is a shape this cannot read.
        # Guessing from whitespace tokens once reported a banner line as a missing surface.
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("surfaces"), list):
        return False
    surfaces = payload["surfaces"]
    if not all(isinstance(entry, dict) for entry in surfaces):
        return False
    return all(surface not in (entry.get("id"), entry.get("ref")) for entry in surfaces)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--pass", dest="pass_num", type=int, required=True)
    parser.add_argument("--surface", required=True)
    parser.add_argument("--cmux-cmd", default="cmux")
    parser.add_argument("--deadline-minutes", type=float)
    parser.add_argument("--start-minutes", type=float, default=5)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--health-seconds", type=float, default=60)
    parser.add_argument("--heartbeat-seconds", type=float, default=300)
    parser.add_argument("--extension", type=int, choices=(0, 1), default=0)
    return parser


def event(run_dir: Path, message: str, data: dict) -> None:
    append_event(run_dir, "worker.waiting", message, data)


def health_says_dead(command: list[str], surface: str) -> bool:
    """A failing or unreachable health command is unknown, never death: one transient CLI
    error must not end a 45-minute wait on a live worker."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and surface_is_dead(result.stdout, surface)


def watch(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    state = verify_or_gate(run_dir, stage=args.stage)
    attempt = current_attempt(state, args.stage, args.pass_num)
    events = planning_events(run_dir)
    surface = validate_recorded_surface(events, args.stage, args.pass_num, args.surface)
    report = report_path(run_dir, args.stage, args.pass_num)
    minutes = args.deadline_minutes if args.deadline_minutes is not None else MINIMUM_WAIT_MINUTES[args.stage]
    if minutes <= 0 or args.poll_seconds <= 0 or args.start_minutes <= 0:
        raise ValueError("wait durations must be positive")
    state = read_planning_state(run_dir / "state.json")
    workspace = state.get("workspace_id")
    if not workspace:
        raise ValueError("surface health checks require the run's pinned workspace")
    health_command = shlex.split(args.cmux_cmd) + [
        "--json", "--id-format", "both", "surface-health", "--workspace", workspace,
    ]
    started = time.monotonic()
    deadline = started + minutes * 60
    next_health = started
    next_heartbeat = started + args.heartbeat_seconds
    launches = [e["data"] for e in events if e.get("type") == "worker.launch_sent"
                and all(e.get("data", {}).get(k) == v for k, v in
                        {"stage": args.stage, "pass": args.pass_num, "surface_id": surface,
                         "attempt_id": attempt["attempt_id"]}.items())]
    launch = launches[-1] if launches else {}
    launch_id = launch.get("launch_id")
    start_pending = bool(launch.get("prompt_path")) and not any(
        e.get("type") == "worker.started" and e.get("data", {}).get("launch_id") == launch_id
        and e["data"].get("attempt_id") == attempt["attempt_id"] for e in events)
    marker = Path(attempt["paths"]["started"])
    start_deadline = started + args.start_minutes * 60
    settled: str | None = None
    while True:
        elapsed = round(time.monotonic() - started, 1)
        data = {
            "stage": args.stage,
            "pass": args.pass_num,
            "attempt": attempt["attempt"],
            "attempt_id": attempt["attempt_id"],
            "surface_id": surface,
            "elapsed_seconds": elapsed,
            "deadline_minutes": minutes,
            "extension": args.extension,
            "launch_id": launch_id,
        }
        if start_pending:
            fresh_marker = marker.is_file() and marker.stat().st_mtime_ns >= launch["start_time_ns"]
            report_present = report.is_file() and report.stat().st_size > 0
            if fresh_marker or report_present:
                append_event(run_dir, "worker.started", "planning assignment start confirmed", {
                    **{key: data[key] for key in ("stage", "pass", "attempt", "attempt_id",
                                                   "surface_id", "launch_id")},
                    "evidence": "marker" if fresh_marker else "report", "marker_path": str(marker),
                })
                start_pending = False
        # Workers write the report with their own non-atomic tools, so existence alone can mean
        # a half-written file. Requiring identical non-empty bytes twice avoids gating on a prefix.
        digest = sha256_file(report) if report.is_file() and report.stat().st_size else None
        if digest is not None and digest == settled:
            state = verify_or_gate(run_dir, stage=args.stage)
            attempt = current_attempt(state, args.stage, args.pass_num)
            entry = record_artifact(
                state,
                run_dir,
                report,
                kind="worker-report",
                stage=args.stage,
                pass_num=args.pass_num,
                attempt=attempt["attempt"],
                producer="worker.report_captured",
                expected_path=attempt["paths"]["report"],
            )
            state["current_attempt"]["report_manifest_id"] = entry["id"]
            write_json(run_dir / "state.json", state)
            event(
                run_dir,
                "planning report captured",
                {
                    **data,
                    "outcome": "report",
                    "report": str(report),
                    # The manifest identity, not the earlier poll digest: a worker that appended
                    # between the two would otherwise leave the event and the manifest disagreeing.
                    "report_sha256": entry["sha256"],
                    "report_manifest_id": entry["id"],
                },
            )
            print(f"outcome=report report={report}")
            return EXIT_REPORT
        settled = digest
        now = time.monotonic()
        if not start_pending and now >= deadline:
            event(run_dir, "planning report deadline exceeded", {**data, "outcome": "deadline"})
            print("outcome=deadline")
            return EXIT_DEADLINE
        if now >= next_health:
            if health_says_dead(health_command, surface):
                event(run_dir, "planning worker pane disappeared", {**data, "outcome": "pane_dead"})
                print("outcome=pane_dead")
                return EXIT_PANE_DEAD
            next_health = now + args.health_seconds
        if start_pending and now >= start_deadline:
            event(run_dir, "planning assignment did not start", {**data, "outcome": "not_started"})
            print("outcome=not_started")
            return EXIT_NOT_STARTED
        if now >= next_heartbeat:
            event(run_dir, "planning report pending", {**data, "outcome": "pending"})
            next_heartbeat = now + args.heartbeat_seconds
        time.sleep(min(args.poll_seconds, max((start_deadline if start_pending else deadline) - time.monotonic(), 0.01)))


def main() -> int:
    try:
        return watch(build_parser().parse_args())
    except (ArtifactIntegrityError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
