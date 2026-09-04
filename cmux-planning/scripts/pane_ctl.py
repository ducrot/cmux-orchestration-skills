#!/usr/bin/env python3
"""Launch fresh visible planning workers in the run's pinned CMUX workspace."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from orchestrator_lib import (
    ROLE_LABELS,
    STAGES,
    append_event,
    delivery_text,
    planning_events,
    read_planning_state,
    surface_event_recorded,
    validate_recorded_surface,
)
from stage_snapshot import (
    SnapshotError,
    load_prepared_snapshot,
    snapshot_launch_record,
    snapshot_shell_command,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmux-cmd", help="override cmux executable for tests")
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage_pass = argparse.ArgumentParser(add_help=False)
    stage_pass.add_argument("--run-dir", required=True)
    stage_pass.add_argument("--stage", choices=STAGES, required=True)
    stage_pass.add_argument("--pass", dest="pass_num", type=int, required=True)
    # Every verb but launch addresses an already-launched pane, so --surface lives on this
    # shared parent and run() validates it once for all of them.
    launched_pane = argparse.ArgumentParser(add_help=False, parents=[stage_pass])
    launched_pane.add_argument("--surface", required=True)
    launch = subparsers.add_parser("launch", parents=[stage_pass])
    launch.add_argument("--anchor", required=True)
    launch.add_argument("--direction", choices=("left", "right", "up", "down"), default="right")
    start = subparsers.add_parser("start-agent", parents=[launched_pane])
    start.add_argument("--settle-seconds", type=float, default=8)
    deliver = subparsers.add_parser("deliver", parents=[launched_pane])
    deliver.add_argument("--prompt", required=True)
    deliver.add_argument("--settle-seconds", type=float, default=3)
    subparsers.add_parser("mark-started", parents=[launched_pane])
    subparsers.add_parser("close", parents=[launched_pane])
    return parser


def cmux_base(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.cmux_cmd) if args.cmux_cmd else ["cmux"]


def pinned_workspace(state: dict) -> str:
    value = state.get("workspace_id")
    if not value:
        raise SnapshotError("run has no pinned workspace; pane control will not use focused-workspace fallback")
    return value


def workspace(run_dir: Path) -> str:
    return pinned_workspace(read_planning_state(run_dir / "state.json"))


def cmux(args: argparse.Namespace, argv: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmux_base(args) + argv, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise SnapshotError(result.stderr.strip() or f"cmux exited {result.returncode}")
    return result


def event(run_dir: Path, kind: str, message: str, data: dict) -> None:
    append_event(run_dir, kind, message, data)


def send(args: argparse.Namespace, surface: str, text: str, kind: str, data: dict) -> None:
    run_dir = Path(args.run_dir)
    target = ["--workspace", workspace(run_dir), "--surface", surface]
    cmux(args, ["send", *target, text])
    cmux(args, ["send-key", *target, "enter"])
    event(run_dir, kind, "sent and submitted text to stable planning pane", data)
    time.sleep(args.settle_seconds)
    screen = cmux(args, ["read-screen", *target, "--lines", "40"])
    print(screen.stdout, end="")


def run(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if args.command == "launch":
        snapshot = load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        state = read_planning_state(run_dir / "state.json")
        pinned = pinned_workspace(state)
        result = cmux(
            args,
            [
                "--json",
                "--id-format",
                "both",
                "new-split",
                args.direction,
                "--workspace",
                pinned,
                "--surface",
                args.anchor,
                "--focus",
                "false",
            ],
        )
        try:
            created = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise SnapshotError("cmux new-split did not return JSON") from error
        surface = created.get("surface_id")
        if not isinstance(surface, str) or not surface:
            raise SnapshotError("cmux new-split returned no stable surface identity")
        label = f"{ROLE_LABELS[args.stage]} {args.pass_num} - {state['run_id']}"
        data = {
            "stage": args.stage,
            "pass": args.pass_num,
            "surface_id": surface,
            "surface_ref": created.get("surface_ref"),
            "pane_id": created.get("pane_id") or created.get("pane_ref"),
            "label": label,
            **snapshot_launch_record(snapshot),
        }
        # Recorded before labeling, so a failing rename never orphans a pane whose identity
        # was never written down.
        event(run_dir, "pane.launched", "launched fresh planning worker", data)
        cmux(args, ["rename-tab", "--workspace", pinned, "--surface", surface, label])
        event(run_dir, "pane.labeled", "labeled fresh planning worker", data)
        print(json.dumps(data, sort_keys=True))
        return 0
    # One choke point for every post-launch verb: a positional ref or any other identity stops
    # here, before the first cmux call, and a later verb cannot forget to check.
    events = planning_events(run_dir)
    # close is the accepted recovery exception: it may reach any pane this stage pass launched,
    # so a pane orphaned by a failed or retried launch stays closable. Work verbs stay latest-only.
    surface = validate_recorded_surface(
        events, args.stage, args.pass_num, args.surface, any_launch=args.command == "close"
    )
    if args.command == "start-agent":
        snapshot = load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        send(
            args,
            surface,
            snapshot_shell_command(snapshot),
            "worker.launch_sent",
            {"stage": args.stage, "pass": args.pass_num, "surface_id": surface, **snapshot_launch_record(snapshot)},
        )
        return 0
    if args.command == "deliver":
        load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        # The baseline pinned and digest-verified exactly one prompt file. Delivering any other
        # path hands the pane an unaudited work order that every later gate still calls verified.
        verified = read_planning_state(run_dir / "state.json")["tree_baseline"]["prompt_path"]
        if Path(args.prompt).resolve() != Path(verified).resolve():
            raise SnapshotError(f"--prompt is not the baseline-verified prompt: {verified}")
        send(
            args,
            surface,
            delivery_text(args.prompt),
            "worker.prompt_sent",
            {"stage": args.stage, "pass": args.pass_num, "surface_id": surface, "prompt": args.prompt},
        )
        return 0
    if args.command == "mark-started":
        snapshot = load_prepared_snapshot(run_dir, args.stage, args.pass_num)
        already_recorded = surface_event_recorded(
            events, "worker.started", args.stage, args.pass_num, surface
        )
        if not already_recorded:
            event(
                run_dir,
                "worker.started",
                "orchestrator confirmed the deterministic assignment started in the visible pane",
                {
                    "stage": args.stage,
                    "pass": args.pass_num,
                    "surface_id": surface,
                    **snapshot_launch_record(snapshot),
                },
            )
        print(
            json.dumps(
                {
                    "already_recorded": already_recorded,
                    "stage": args.stage,
                    "pass": args.pass_num,
                    "surface_id": surface,
                    "started": True,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command != "close":
        raise SnapshotError(f"unhandled command: {args.command}")
    cmux(args, ["close-surface", "--workspace", workspace(run_dir), "--surface", surface])
    event(
        run_dir,
        "pane.closed",
        "closed planning worker pane",
        {"stage": args.stage, "pass": args.pass_num, "surface_id": surface},
    )
    return 0


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except (SnapshotError, OSError, KeyError, ValueError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
