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

from orchestrator_lib import (
    MINIMUM_WAIT_MINUTES,
    STAGES,
    append_event,
    read_planning_state,
    sha256_file,
    utc_now,
)
from stage_snapshot import load_prepared_snapshot


EXIT_REPORT = 0
EXIT_PANE_DEAD = 7
EXIT_DEADLINE = 8
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
    parser.add_argument("--surface")
    parser.add_argument("--cmux-cmd", default="cmux")
    parser.add_argument("--deadline-minutes", type=float)
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
    report = report_path(run_dir, args.stage, args.pass_num)
    minutes = args.deadline_minutes if args.deadline_minutes is not None else MINIMUM_WAIT_MINUTES[args.stage]
    if minutes <= 0 or args.poll_seconds <= 0:
        raise ValueError("wait durations must be positive")
    state = read_planning_state(run_dir / "state.json")
    workspace = state.get("workspace_id")
    if args.surface and not workspace:
        raise ValueError("surface health checks require the run's pinned workspace")
    health_command = shlex.split(args.cmux_cmd) + [
        "--json", "--id-format", "both", "surface-health", "--workspace", workspace or "",
    ]
    started = time.monotonic()
    deadline = started + minutes * 60
    next_health = started
    next_heartbeat = started + args.heartbeat_seconds
    settled: str | None = None
    while True:
        elapsed = round(time.monotonic() - started, 1)
        data = {
            "stage": args.stage,
            "pass": args.pass_num,
            "surface_id": args.surface,
            "elapsed_seconds": elapsed,
            "deadline_minutes": minutes,
            "extension": args.extension,
        }
        # Workers write the report with their own non-atomic tools, so existence alone can mean
        # a half-written file. Requiring identical non-empty bytes twice avoids gating on a prefix.
        digest = sha256_file(report) if report.is_file() and report.stat().st_size else None
        if digest is not None and digest == settled:
            event(
                run_dir,
                "planning report captured",
                {
                    **data,
                    "outcome": "report",
                    "report": str(report),
                    "report_sha256": digest,
                },
            )
            print(f"outcome=report report={report}")
            return EXIT_REPORT
        settled = digest
        now = time.monotonic()
        if now >= deadline:
            event(run_dir, "planning report deadline exceeded", {**data, "outcome": "deadline"})
            print("outcome=deadline")
            return EXIT_DEADLINE
        if args.surface and now >= next_health:
            if health_says_dead(health_command, args.surface):
                event(run_dir, "planning worker pane disappeared", {**data, "outcome": "pane_dead"})
                print("outcome=pane_dead")
                return EXIT_PANE_DEAD
            next_health = now + args.health_seconds
        if now >= next_heartbeat:
            event(run_dir, "planning report pending", {**data, "outcome": "pending"})
            next_heartbeat = now + args.heartbeat_seconds
        time.sleep(min(args.poll_seconds, max(deadline - time.monotonic(), 0.01)))


def main() -> int:
    try:
        return watch(build_parser().parse_args())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
