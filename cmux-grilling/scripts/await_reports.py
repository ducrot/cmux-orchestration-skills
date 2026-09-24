#!/usr/bin/env python3
"""Watch a round's lane reports; exit 0=all reports exist, 7=lane pane dead, 8=deadline.

Designed to run under the harness Monitor tool (persistent), so the orchestrator is
re-invoked deterministically when the watch ends. One watcher per round, not per lane:
a round synthesizes only when all four lanes delivered, so a per-lane wake-up would
mostly mean "keep waiting". The report files are ground truth; a pane's state only
matters while its report is still missing — a lane whose pane exits right after writing
its report has delivered, not died. No screen-content heuristics: a static-looking pane
(a lane mid-thought, or one already finished) is alive.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
from pathlib import Path

from orchestrator_lib import LANES, append_jsonl, read_json, read_run_state, round_wait_minutes, utc_now

EXIT_REPORTS = 0    # every lane report exists — parse them next; NOT an advance verdict
EXIT_PANE_DEAD = 7  # a lane surface with a pending report is gone per surface-health
EXIT_DEADLINE = 8   # deadline exceeded with the pending panes alive/unknown
# 1 = crash, 2 = argparse usage; 3-6 belong to parse_research_report.py. Skill-wide unique.


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--round", dest="round_number", type=int, required=True)
    parser.add_argument(
        "--lanes",
        default=",".join(LANES),
        help="Comma-separated lanes to await (default: all four)",
    )
    parser.add_argument(
        "--lane-surface",
        action="append",
        default=[],
        metavar="LANE=SURFACE",
        help="Repeatable. Lanes without a surface are watched file-only (no health checks)",
    )
    parser.add_argument(
        "--workspace",
        help="cmux workspace id override (tests). Defaults to the run's pinned workspace_id "
        "from state.json; no env fallback — an unresolvable workspace is a usage error.",
    )
    parser.add_argument(
        "--questions",
        type=int,
        required=True,
        help="Questions in the round; scales the default deadline (15 min + 5 per extra question)",
    )
    parser.add_argument(
        "--deadline-minutes",
        type=float,
        help="Override the round minimum wait (the one documented extension)",
    )
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--health-interval-seconds", type=float, default=60)
    parser.add_argument("--heartbeat-seconds", type=float, default=300)
    parser.add_argument("--health-cmd", help="Override the surface-health command (tests)")
    return parser


def parse_lanes(args: argparse.Namespace) -> list[str]:
    lanes = [name.strip() for name in args.lanes.split(",") if name.strip()]
    if not lanes:
        raise SystemExit("--lanes is empty")
    unknown = [name for name in lanes if name not in LANES]
    if unknown:
        raise SystemExit(f"unknown lanes: {', '.join(unknown)}")
    return lanes


def parse_lane_surfaces(pairs: list[str], lanes: list[str]) -> dict[str, str]:
    surfaces: dict[str, str] = {}
    for pair in pairs:
        lane, separator, surface = pair.partition("=")
        if not separator or not lane.strip() or not surface.strip():
            raise SystemExit(f"--lane-surface expects LANE=SURFACE, got: {pair}")
        lane, surface = lane.strip(), surface.strip()
        if lane not in lanes:
            raise SystemExit(f"--lane-surface for a lane not being awaited: {lane}")
        surfaces[lane] = surface
    return surfaces


def report_path(run_dir: Path, round_number: int, lane: str) -> Path:
    # Must match render_prompt.py's report stem.
    return run_dir / "reports" / f"round-{round_number}-{lane}.md"


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


def live_surfaces(health_output: str) -> set[str]:
    """Surface refs AND ids from a successful health listing.

    Pinned to real output (captured 2026-07-25): a closed pane's surface simply
    disappears from the listing; there are no dead/exited markers. With
    `--id-format both`, JSON carries `{"surfaces": [{"ref": "surface:465",
    "id": "<UUID>", ...}]}` — the health command must request both, because
    `pane_ctl.py launch` hands out UUIDs and a UUID can never match a ref-only
    listing (the ISSUE-013 pilot's false "all lanes dead" alarm). Plain text is
    one `surface:465  type=terminal in_window=true` line per surface. Membership
    must be exact — a substring check makes `surface:46` match `surface:465`.
    """
    try:
        payload = json.loads(health_output)
    except ValueError:
        return {line.split()[0] for line in health_output.splitlines() if line.strip()}
    entries = payload.get("surfaces", [])
    return {entry.get("ref") for entry in entries} | {
        entry["id"] for entry in entries if entry.get("id")
    }


def check_health(cmd: list[str], surfaces: dict[str, str]) -> tuple[str, list[str], str]:
    """Returns (status, dead_lanes, detail); status is 'dead' | 'alive' | 'unknown'.

    A failing health command is 'unknown' and never ends the wait — a transient CLI
    error must not kill a 15-minute round watch.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        return "unknown", [], str(error)
    if result.returncode != 0:
        return "unknown", [], result.stderr.strip() or f"exit {result.returncode}"
    live = live_surfaces(result.stdout)
    dead = sorted(lane for lane, surface in surfaces.items() if surface not in live)
    if dead:
        detail = ", ".join(f"{lane}={surfaces[lane]}" for lane in dead)
        return "dead", dead, f"surfaces not healthy in listing: {detail}"
    return "alive", [], ""


def waiting_event(run_dir: Path, message: str, data: dict) -> None:
    append_jsonl(
        run_dir / "events.jsonl",
        {"time": utc_now(), "type": "worker.waiting", "message": message, "data": data},
    )


def join(lanes: list[str]) -> str:
    return ",".join(lanes) if lanes else "none"


def watch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    run_dir = Path(args.run_dir)
    read_run_state(run_dir)
    if args.questions < 1:
        raise SystemExit("--questions must be >= 1")
    lanes = parse_lanes(args)
    surfaces = parse_lane_surfaces(args.lane_surface, lanes)
    reports = {lane: report_path(run_dir, args.round_number, lane) for lane in lanes}
    deadline_minutes = args.deadline_minutes if args.deadline_minutes is not None else round_wait_minutes(args.questions)
    # File-only mode (no lane surfaces) never shells out, so it needs no workspace.
    cmd = health_command(args, parser) if surfaces else []
    start = time.monotonic()
    deadline = start + deadline_minutes * 60
    next_health = start
    next_heartbeat = start + args.heartbeat_seconds
    health_status, health_detail, dead_lanes = "unchecked", "", []

    def delivered() -> list[str]:
        return [lane for lane in lanes if reports[lane].is_file()]

    def base_data(done: list[str]) -> dict:
        pending = [lane for lane in lanes if lane not in done]
        return {
            "round": args.round_number,
            "lanes": lanes,
            "delivered_lanes": done,
            "missing_lanes": pending,
            "surface_ids": {lane: surfaces[lane] for lane in pending if lane in surfaces},
            "elapsed_seconds": round(time.monotonic() - start, 1),
            "deadline_minutes": deadline_minutes,
            "health": health_status,
        }

    def finish(outcome: str, code: int, message: str, done: list[str]) -> int:
        data = base_data(done)
        data["outcome"] = outcome
        if dead_lanes:
            data["dead_lanes"] = dead_lanes
        if health_detail:
            data["health_detail"] = health_detail
        waiting_event(run_dir, message, data)
        print(
            f"outcome={outcome} round={args.round_number} "
            f"elapsed_seconds={data['elapsed_seconds']} "
            f"delivered={join(data['delivered_lanes'])} "
            f"missing={join(data['missing_lanes'])} dead={join(dead_lanes)}"
        )
        return code

    while True:
        done = delivered()
        pending = [lane for lane in lanes if lane not in done]
        if not pending:
            return finish("reports", EXIT_REPORTS, f"all {len(lanes)} lane reports captured", done)
        now = time.monotonic()
        if now >= deadline:
            return finish("deadline", EXIT_DEADLINE, f"deadline of {deadline_minutes} minutes exceeded", done)
        # Health only for lanes still owing a report: a lane whose pane exits right after
        # writing its report has delivered, and must not read as a dead pane.
        pending_surfaces = {lane: surfaces[lane] for lane in pending if lane in surfaces}
        if pending_surfaces and now >= next_health:
            health_status, dead_lanes, health_detail = check_health(cmd, pending_surfaces)
            next_health = now + args.health_interval_seconds
            if health_status == "dead":
                return finish("pane_dead", EXIT_PANE_DEAD, f"lane pane dead: {health_detail}", done)
        if now >= next_heartbeat:
            waiting_event(run_dir, "lane reports pending; lanes still running", base_data(done))
            next_heartbeat = now + args.heartbeat_seconds
        time.sleep(min(args.poll_seconds, max(deadline - time.monotonic(), 0.01)))


def main() -> int:
    parser = build_parser()
    return watch(parser.parse_args(), parser)


if __name__ == "__main__":
    raise SystemExit(main())
