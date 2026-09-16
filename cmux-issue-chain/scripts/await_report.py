#!/usr/bin/env python3
"""Watch for a worker report; exit 0=report exists, 7=pane dead, 8=deadline exceeded.

Designed to run under the harness Monitor tool (persistent), so the orchestrator is
re-invoked deterministically when the watch ends. The report file is ground truth;
the pane state only matters when it is affirmatively dead. No screen-content
heuristics: a static-looking pane (a worker mid-thought, or one already finished) is alive.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
from pathlib import Path

from orchestrator_lib import MINIMUM_WAIT_MINUTES, append_jsonl, read_json, read_run_state, utc_now

EXIT_REPORT = 0     # report file exists — parse it next; NOT an advance verdict
EXIT_PANE_DEAD = 7  # surface affirmatively gone/dead per surface-health
EXIT_DEADLINE = 8   # deadline exceeded with the pane alive/unknown
# 1 = crash, 2 = argparse usage; 3-6 belong to parse_report.py. Skill-wide unique.


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--role", required=True, choices=sorted(MINIMUM_WAIT_MINUTES))
    parser.add_argument("--pass", dest="pass_num", type=int, required=True)
    parser.add_argument("--surface", help="cmux surface id; omit for file-only mode (no health checks)")
    parser.add_argument(
        "--workspace",
        help="cmux workspace id override (tests). Defaults to the run's pinned workspace_id "
        "from state.json; no env fallback — an unresolvable workspace is a usage error.",
    )
    parser.add_argument(
        "--deadline-minutes",
        type=float,
        help="Override the role-derived minimum wait (the one documented extension)",
    )
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--health-interval-seconds", type=float, default=60)
    parser.add_argument("--heartbeat-seconds", type=float, default=300)
    parser.add_argument("--health-cmd", help="Override the surface-health command (tests)")
    return parser


def report_path(run_dir: Path, role: str, pass_num: int) -> Path:
    # Must match render_prompt.py's report stem.
    return run_dir / "reports" / f"{role}-{pass_num}.md"


def pinned_workspace(run_dir: Path) -> str | None:
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        return None
    return read_run_state(run_dir).get("workspace_id") or None


def health_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[str]:
    if args.health_cmd:
        return shlex.split(args.health_cmd)
    workspace = args.workspace or pinned_workspace(Path(args.run_dir))
    if not workspace:
        # Unscoped surface-health resolves against the focused workspace — the silent
        # wrong-workspace fallback this skill removed. Refuse instead of guessing.
        parser.error(
            "no cmux workspace: the run's state.json has no workspace_id and no "
            "--workspace was given (re-init the run, or pass --workspace explicitly)"
        )
    return ["cmux", "--json", "--id-format", "both", "surface-health", "--workspace", workspace]


def surface_is_dead(health_output: str, surface: str) -> bool:
    """Dead only when the surface is absent from a successful health listing.

    Pinned to real output (captured 2026-07-25): a closed pane's surface simply
    disappears from the listing; there are no dead/exited markers. With
    `--id-format both`, JSON carries `{"surfaces": [{"ref": "surface:465",
    "id": "<UUID>", ...}]}` — the health command must request both, because
    `pane_ctl.py launch` hands out UUIDs and a UUID can never match a ref-only
    listing (the pilot's false "all panes dead" alarm). Plain text is one
    `surface:465  type=terminal in_window=true` line per surface. Matching must
    be exact — a substring check makes `surface:46` match `surface:465`.
    """
    try:
        payload = json.loads(health_output)
    except ValueError:
        tokens = {line.split()[0] for line in health_output.splitlines() if line.strip()}
        return surface not in tokens
    return all(
        surface not in (entry.get("ref"), entry.get("id"))
        for entry in payload.get("surfaces", [])
    )


def check_health(cmd: list[str], surface: str) -> tuple[str, str]:
    """Returns (status, detail); status is 'dead' | 'alive' | 'unknown'.

    A failing health command is 'unknown' and never ends the wait — a transient
    CLI error must not kill a 90-minute review watch.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        return "unknown", str(error)
    if result.returncode != 0:
        return "unknown", result.stderr.strip() or f"exit {result.returncode}"
    if surface_is_dead(result.stdout, surface):
        return "dead", f"surface {surface} not healthy in listing"
    return "alive", ""


def waiting_event(run_dir: Path, message: str, data: dict) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": utc_now(), "type": "worker.waiting", "message": message, "data": data},
    )


def watch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    run_dir = Path(args.run_dir)
    read_run_state(run_dir)
    report = report_path(run_dir, args.role, args.pass_num)
    deadline_minutes = (
        args.deadline_minutes if args.deadline_minutes is not None else MINIMUM_WAIT_MINUTES[args.role]
    )
    # File-only mode (no --surface) never shells out, so it needs no workspace.
    cmd = health_command(args, parser) if args.surface else []
    start = time.monotonic()
    deadline = start + deadline_minutes * 60
    next_health = start
    next_heartbeat = start + args.heartbeat_seconds
    health_status, health_detail = "unchecked", ""

    def base_data() -> dict:
        return {
            "role": args.role,
            "pass": args.pass_num,
            "surface_id": args.surface,
            "elapsed_seconds": round(time.monotonic() - start, 1),
            "deadline_minutes": deadline_minutes,
            "health": health_status,
        }

    def finish(outcome: str, code: int, message: str) -> int:
        data = base_data()
        data["outcome"] = outcome
        if health_detail:
            data["health_detail"] = health_detail
        waiting_event(run_dir, message, data)
        print(f"outcome={outcome} elapsed_seconds={data['elapsed_seconds']} report={report}")
        return code

    while True:
        if report.is_file():
            return finish("report", EXIT_REPORT, f"report captured: {report}")
        now = time.monotonic()
        if now >= deadline:
            return finish("deadline", EXIT_DEADLINE, f"deadline of {deadline_minutes} minutes exceeded")
        if args.surface and now >= next_health:
            health_status, health_detail = check_health(cmd, args.surface)
            next_health = now + args.health_interval_seconds
            if health_status == "dead":
                return finish("pane_dead", EXIT_PANE_DEAD, f"worker pane dead: {health_detail}")
        if now >= next_heartbeat:
            waiting_event(run_dir, "report pending; worker still running", base_data())
            next_heartbeat = now + args.heartbeat_seconds
        time.sleep(min(args.poll_seconds, max(deadline - time.monotonic(), 0.01)))


def main() -> int:
    parser = build_parser()
    return watch(parser.parse_args(), parser)


if __name__ == "__main__":
    raise SystemExit(main())
