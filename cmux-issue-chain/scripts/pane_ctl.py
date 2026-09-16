#!/usr/bin/env python3
"""Deterministic cmux control, scoped to the run's pinned workspace.

Every cmux call this skill makes goes through here so the workspace scope always
comes from the run's state.json (pinned at `run_state.py init`), never from the
focused workspace or an environment fallback. Verbs:

  workspace  print the pinned workspace id
  cmux       generic passthrough that injects --workspace into any cmux command
  launch      prepared-snapshot check + new-split + label + pane.launched/pane.labeled events
  start-agent send the prepared stage snapshot's launch command + worker.launch_sent event
  deliver     send + send-key enter + read-screen echo + worker.prompt_sent event
              (--prompt hands over a rendered prompt with the skill's own wording;
               --text is for follow-ups)
  close       close-surface + pane.closed event

`launch`/`start-agent`/`deliver`/`close` are mechanical lifecycle verbs only. Judging what a
worker's screen means (started? stuck at a prompt?) stays with the orchestrator.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from orchestrator_lib import ROLE_LABELS, append_jsonl, delivery_text, read_json, read_run_state, utc_now
from worker_snapshot import (
    SnapshotError,
    load_launchable_snapshot,
    snapshot_launch_record,
    snapshot_shell_command,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmux-cmd", help="Override the cmux executable (tests)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    workspace = subparsers.add_parser("workspace", help="Print the run's pinned workspace id")
    workspace.add_argument("--run-dir", required=True)

    passthrough = subparsers.add_parser(
        "cmux",
        help="Run any cmux command with --workspace injected from the pinned workspace",
    )
    passthrough.add_argument("--run-dir", required=True)
    passthrough.add_argument("args", nargs=argparse.REMAINDER, help="cmux command and arguments (after --)")

    launch = subparsers.add_parser(
        "launch",
        help="Split a new worker pane once its stage snapshot validates, label it, record events",
    )
    launch.add_argument("--run-dir", required=True)
    launch.add_argument("--role", required=True, choices=sorted(ROLE_LABELS))
    launch.add_argument("--pass", dest="pass_num", type=int, required=True)
    launch.add_argument("--anchor", required=True, help="Surface id to split from (previous worker pane)")
    launch.add_argument("--direction", default="right", choices=["left", "right", "up", "down"])

    start = subparsers.add_parser(
        "start-agent",
        help="Start the role's worker in its pane from the prepared stage snapshot",
    )
    start.add_argument("--run-dir", required=True)
    start.add_argument("--surface", required=True)
    start.add_argument("--role", required=True, choices=sorted(ROLE_LABELS))
    start.add_argument("--pass", dest="pass_num", type=int, required=True)
    start.add_argument("--settle-seconds", type=float, default=8.0, help="Wait before read-screen")
    start.add_argument("--read-lines", type=int, default=40)

    deliver = subparsers.add_parser("deliver", help="Send text to a pane, submit with Enter, echo the screen")
    deliver.add_argument("--run-dir", required=True)
    deliver.add_argument("--surface", required=True)
    payload = deliver.add_mutually_exclusive_group(required=True)
    payload.add_argument("--prompt", help="Prompt path to hand over; the skill supplies the wording")
    payload.add_argument("--text", help="Follow-up text (re-emission requests, clarifications)")
    deliver.add_argument("--role", choices=sorted(ROLE_LABELS))
    deliver.add_argument("--pass", dest="pass_num", type=int)
    deliver.add_argument("--settle-seconds", type=float, default=3.0, help="Wait before read-screen")
    deliver.add_argument("--read-lines", type=int, default=40)

    close = subparsers.add_parser("close", help="Close a worker pane and record pane.closed")
    close.add_argument("--run-dir", required=True)
    close.add_argument("--surface", required=True)
    close.add_argument("--role", required=True, choices=sorted(ROLE_LABELS))
    close.add_argument("--pass", dest="pass_num", type=int, required=True)

    return parser


def pinned_workspace(run_dir: Path) -> str:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise SystemExit(f"No state.json under {run_dir} — run run_state.py init first")
    workspace_id = read_run_state(run_dir).get("workspace_id")
    if not workspace_id:
        raise SystemExit(
            f"{state_path} has no pinned workspace_id — re-init the run from a cmux pane "
            "(or with --workspace-id); pane control refuses to fall back to the focused workspace"
        )
    return workspace_id


def cmux_base(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.cmux_cmd) if args.cmux_cmd else ["cmux"]


def run_cmux(args: argparse.Namespace, argv: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    result = subprocess.run(cmux_base(args) + argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise SystemExit(
            f"cmux {' '.join(argv)} failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def record_event(run_dir: Path, event_type: str, message: str, data: dict) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": utc_now(), "type": event_type, "message": message, "data": data},
    )


def worker_label(role: str, pass_num: int, issue_id: str) -> str:
    return f"{ROLE_LABELS[role]} {pass_num} - {issue_id}"


def cmd_workspace(args: argparse.Namespace) -> int:
    print(pinned_workspace(Path(args.run_dir)))
    return 0


def cmd_cmux(args: argparse.Namespace) -> int:
    passthrough = list(args.args)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    if not passthrough:
        raise SystemExit("No cmux command given (use: pane_ctl.py cmux --run-dir <dir> -- <command> ...)")
    if "--workspace" in passthrough:
        raise SystemExit("Do not pass --workspace here; the pinned workspace is injected automatically")
    workspace_id = pinned_workspace(Path(args.run_dir))
    # Global flags (--json, --id-format ...) precede the command word; --workspace is a
    # command option and must come after it.
    command_index = next((i for i, token in enumerate(passthrough) if not token.startswith("-")), None)
    if command_index is None:
        raise SystemExit(f"No cmux command word found in: {' '.join(passthrough)}")
    argv = (
        passthrough[: command_index + 1]
        + ["--workspace", workspace_id]
        + passthrough[command_index + 1 :]
    )
    result = subprocess.run(cmux_base(args) + argv)
    return result.returncode


def cmd_launch(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    # Snapshot validation happens before even resolving cmux, so an invalid
    # configuration/preflight state can never create an empty worker pane.
    load_launchable_snapshot(run_dir, args.role, args.pass_num)
    workspace_id = pinned_workspace(run_dir)
    state = read_run_state(run_dir)
    issue_id = (state.get("issue") or {}).get("id", "unknown-issue")
    split = run_cmux(
        args,
        [
            "--json",
            "--id-format",
            "both",
            "new-split",
            args.direction,
            "--workspace",
            workspace_id,
            "--surface",
            args.anchor,
            "--focus",
            "false",
        ],
    )
    try:
        created = json.loads(split.stdout)
    except ValueError:
        raise SystemExit(f"new-split returned no parseable JSON: {split.stdout.strip()}")
    surface_id = created.get("surface_id") or created.get("surface_ref")
    if not surface_id:
        raise SystemExit(f"new-split output carries no surface id: {split.stdout.strip()}")
    label = worker_label(args.role, args.pass_num, issue_id)
    launch_data = {
        "role": args.role,
        "pass": args.pass_num,
        "surface_id": surface_id,
        "surface_ref": created.get("surface_ref"),
        "pane_id": created.get("pane_id") or created.get("pane_ref"),
        "direction": args.direction,
        "anchor": args.anchor,
    }
    record_event(run_dir, "pane.launched", f"launched {label}", launch_data)
    run_cmux(args, ["rename-tab", "--workspace", workspace_id, "--surface", surface_id, label])
    record_event(run_dir, "pane.labeled", f"labeled {label}", {**launch_data, "label": label})
    print(json.dumps({"surface_id": surface_id, "surface_ref": created.get("surface_ref"), "label": label}))
    return 0


def send_submit_echo(
    args: argparse.Namespace, text: str, event_type: str, message: str, data: dict
) -> None:
    run_dir = Path(args.run_dir)
    target = ["--workspace", pinned_workspace(run_dir), "--surface", args.surface]
    run_cmux(args, ["send", *target, text])
    # A trailing \n does not submit in the Codex/Claude TUIs; Enter must be its own key event.
    run_cmux(args, ["send-key", *target, "enter"])
    record_event(run_dir, event_type, message, data)
    time.sleep(args.settle_seconds)
    screen = run_cmux(args, ["read-screen", *target, "--lines", str(args.read_lines)])
    print(screen.stdout, end="")


def cmd_start_agent(args: argparse.Namespace) -> int:
    snapshot = load_launchable_snapshot(Path(args.run_dir), args.role, args.pass_num)
    command = snapshot_shell_command(snapshot)
    send_submit_echo(
        args,
        command,
        "worker.launch_sent",
        "launch command sent; started-confirmation is the orchestrator's call",
        {
            "role": args.role,
            "pass": args.pass_num,
            "surface_id": args.surface,
            "command": command,
            **snapshot_launch_record(snapshot),
        },
    )
    return 0


def cmd_deliver(args: argparse.Namespace) -> int:
    text = delivery_text(args.prompt) if args.prompt else args.text
    send_submit_echo(
        args,
        text,
        "worker.prompt_sent",
        "text sent and submitted; started-confirmation is the orchestrator's call",
        {
            "role": args.role,
            "pass": args.pass_num,
            "surface_id": args.surface,
            "prompt_path": args.prompt,
            "text": text,
        },
    )
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    workspace_id = pinned_workspace(run_dir)
    run_cmux(args, ["close-surface", "--workspace", workspace_id, "--surface", args.surface])
    record_event(
        run_dir,
        "pane.closed",
        f"closed {args.role}-{args.pass_num} pane",
        {"role": args.role, "pass": args.pass_num, "surface_id": args.surface},
    )
    return 0


COMMANDS = {
    "workspace": cmd_workspace,
    "cmux": cmd_cmux,
    "launch": cmd_launch,
    "start-agent": cmd_start_agent,
    "deliver": cmd_deliver,
    "close": cmd_close,
}


def main() -> int:
    args = build_parser().parse_args()
    try:
        return COMMANDS[args.command](args)
    except SnapshotError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
