#!/usr/bin/env python3
"""Watcher regression tests. Run: python3 scripts/test_await_reports.py"""

from __future__ import annotations

import json
import os
import time
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from await_reports import (  # noqa: E402
    EXIT_NOT_STARTED,
    EXIT_DEADLINE,
    EXIT_PANE_DEAD,
    EXIT_REPORTS,
    check_health,
    live_surfaces,
    report_path,
)
from orchestrator_lib import LANE_WAIT_MINUTES, LANES, round_wait_minutes  # noqa: E402
from parse_research_report import EXIT_CODES as GATE_EXIT_CODES  # noqa: E402


def write_state(run_dir: str, **fields) -> None:
    (Path(run_dir) / "state.json").write_text(
        json.dumps({"workflow": "grilling", "layout_version": 1, "max_rounds": 4, **fields}), encoding="utf-8"
    )


class ReportPath(unittest.TestCase):
    def test_matches_render_prompt_stem(self):
        self.assertEqual(
            report_path(Path("/run"), 1, "web"),
            Path("/run/reports/round-1-web.md"),
        )


class ExitCodeVocabulary(unittest.TestCase):
    def test_watcher_codes_disjoint_from_gate_codes(self):
        """Skill-wide unique vocabulary: 0 ok, 1 crash, 2 usage, 3-6 gate, 7-9 watcher."""
        watcher = {EXIT_PANE_DEAD, EXIT_DEADLINE, EXIT_NOT_STARTED}
        self.assertEqual(len(watcher), 3)
        self.assertEqual(EXIT_NOT_STARTED, 9)
        self.assertFalse(watcher & set(GATE_EXIT_CODES.values()))
        self.assertFalse(watcher & {1, 2})
        self.assertEqual(EXIT_REPORTS, 0)  # "reports exist", intentionally shared with success

    def test_lane_wait_is_uniform(self):
        self.assertEqual(set(LANES), {"codebase", "codebase2", "docs", "web"})
        self.assertEqual(LANE_WAIT_MINUTES, 15)

    def test_round_wait_grows_five_minutes_per_extra_question(self):
        self.assertEqual([round_wait_minutes(n) for n in (1, 2, 4)], [15, 20, 30])


# Real output captured 2026-07-25 from `cmux --json --id-format both surface-health`
# (plain text from `cmux surface-health`).
HEALTH_PLAIN = """surface:23  type=terminal in_window=true
surface:470  type=terminal in_window=true
surface:465  type=terminal in_window=true
"""

UUID_465 = "85547E53-2894-4739-87C8-EE69BCBD1BAE"

HEALTH_JSON = json.dumps(
    {
        "surfaces": [
            {"id": "AAAA0001-0000-4000-8000-000000000001", "in_window": True, "index": 0, "ref": "surface:23", "type": "terminal"},
            {"id": "AAAA0002-0000-4000-8000-000000000002", "in_window": True, "index": 1, "ref": "surface:470", "type": "terminal"},
            {"id": UUID_465, "in_window": True, "index": 2, "ref": "surface:465", "type": "terminal"},
        ],
        "window_id": "04A95895-7E93-4DDB-A165-A0AFA37B7D51",
        "window_ref": "window:1",
        "workspace_ref": "workspace:16",
    }
)


class LiveSurfaces(unittest.TestCase):
    def test_listed_surfaces_parse_from_plain_and_json(self):
        refs = {"surface:23", "surface:470", "surface:465"}
        self.assertEqual(live_surfaces(HEALTH_PLAIN), refs)
        # JSON with --id-format both carries refs AND ids; both must count as live.
        self.assertLessEqual(refs, live_surfaces(HEALTH_JSON))
        self.assertIn(UUID_465, live_surfaces(HEALTH_JSON))

    def test_uuid_from_launch_counts_as_live(self):
        """Regression (ISSUE-013 pilot): pane_ctl launch hands out UUIDs; a ref-only
        comparison declared every UUID-watched lane dead after 0 seconds."""
        status, dead, _ = check_health(self.stub_json(), {"codebase": UUID_465})
        self.assertEqual(status, "alive")
        self.assertEqual(dead, [])

    def stub_json(self):
        return [sys.executable, "-c", f"print({HEALTH_JSON!r})"]

    def test_absent_surface_is_not_live(self):
        self.assertNotIn("surface:999", live_surfaces(HEALTH_PLAIN))
        self.assertNotIn("surface:999", live_surfaces(HEALTH_JSON))

    def test_prefix_of_listed_ref_does_not_count_as_live(self):
        """Regression: substring matching let `surface:46` ride on `surface:465`'s line."""
        self.assertNotIn("surface:46", live_surfaces(HEALTH_PLAIN))
        self.assertNotIn("surface:46", live_surfaces(HEALTH_JSON))

    def test_empty_listing_is_empty(self):
        self.assertEqual(live_surfaces(""), set())
        self.assertEqual(live_surfaces('{"surfaces": []}'), set())


class CheckHealth(unittest.TestCase):
    def stub(self, output: str) -> list[str]:
        return [sys.executable, "-c", f"print({output!r})"]

    def test_reports_only_the_absent_lanes_as_dead(self):
        status, dead, detail = check_health(
            self.stub(HEALTH_PLAIN),
            {"codebase": "surface:465", "docs": "surface:999", "web": "surface:998"},
        )
        self.assertEqual(status, "dead")
        self.assertEqual(dead, ["docs", "web"])
        self.assertIn("surface:999", detail)

    def test_all_listed_is_alive(self):
        status, dead, _ = check_health(self.stub(HEALTH_JSON), {"codebase": "surface:465"})
        self.assertEqual(status, "alive")
        self.assertEqual(dead, [])

    def test_failing_command_is_unknown_never_dead(self):
        status, dead, detail = check_health(
            [sys.executable, "-c", "raise SystemExit(1)"], {"codebase": "surface:465"}
        )
        self.assertEqual(status, "unknown")
        self.assertEqual(dead, [])
        self.assertTrue(detail)

    def test_missing_command_is_unknown(self):
        status, _, _ = check_health(["/nonexistent-health-cmd"], {"codebase": "surface:465"})
        self.assertEqual(status, "unknown")


class Cli(unittest.TestCase):
    script = str(Path(__file__).parent / "await_reports.py")

    def run_cli(self, run_dir: str, *extra: str) -> subprocess.CompletedProcess:
        state = Path(run_dir) / "state.json"
        if not state.exists():
            write_state(run_dir)
        argv = [
            sys.executable, self.script,
            "--run-dir", run_dir, "--round", "1", "--questions", "1",
            "--poll-seconds", "0.05", "--heartbeat-seconds", "0.05",
            *extra,
        ]
        return subprocess.run(argv, capture_output=True, text=True, timeout=30)

    def write_report(self, run_dir: str, lane: str) -> Path:
        path = Path(run_dir) / "reports" / f"round-1-{lane}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## Result\nANSWERED\n", encoding="utf-8")
        return path

    def write_all(self, run_dir: str) -> None:
        for lane in LANES:
            self.write_report(run_dir, lane)

    def test_all_reports_present_exits_zero_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_all(tmp)
            proc = self.run_cli(tmp)
        self.assertEqual(proc.returncode, EXIT_REPORTS)
        self.assertIn("outcome=reports", proc.stdout)
        self.assertIn("missing=none", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_partial_reports_keep_waiting_until_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_report(tmp, "codebase")
            proc = self.run_cli(tmp, "--deadline-minutes", "0.005")
        self.assertEqual(proc.returncode, EXIT_DEADLINE)
        self.assertIn("outcome=deadline", proc.stdout)
        self.assertIn("delivered=codebase", proc.stdout)
        self.assertIn("missing=codebase2,docs,web", proc.stdout)

    def test_last_report_written_mid_wait_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            for lane in ("codebase", "codebase2", "docs"):
                self.write_report(tmp, lane)
            timer = threading.Timer(0.3, self.write_report, args=(tmp, "web"))
            timer.start()
            try:
                proc = self.run_cli(tmp, "--deadline-minutes", "0.5")
            finally:
                timer.cancel()
        self.assertEqual(proc.returncode, EXIT_REPORTS)

    def test_dead_pane_of_pending_lane_exits_seven(self):
        stub = f'{sys.executable} -c "print(\'surface:465 type=terminal in_window=true\')"'
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(
                tmp, "--lanes", "codebase,web",
                "--lane-surface", "codebase=surface:465", "--lane-surface", "web=surface:999",
                "--health-cmd", stub,
                "--health-interval-seconds", "0.05", "--deadline-minutes", "0.5",
            )
        self.assertEqual(proc.returncode, EXIT_PANE_DEAD)
        self.assertIn("outcome=pane_dead", proc.stdout)
        self.assertIn("dead=web", proc.stdout)

    def test_delivered_lane_with_closed_pane_is_not_dead(self):
        """The core round-watcher trap: a lane pane may exit right after writing its report."""
        stub = f'{sys.executable} -c "print(\'surface:465 type=terminal in_window=true\')"'
        with tempfile.TemporaryDirectory() as tmp:
            self.write_report(tmp, "web")  # web's surface:999 is gone from the listing
            proc = self.run_cli(
                tmp, "--lanes", "codebase,web",
                "--lane-surface", "codebase=surface:465", "--lane-surface", "web=surface:999",
                "--health-cmd", stub,
                "--health-interval-seconds", "0.05", "--deadline-minutes", "0.01",
            )
        self.assertEqual(proc.returncode, EXIT_DEADLINE)
        self.assertIn("dead=none", proc.stdout)

    def test_erroring_health_cmd_does_not_end_wait(self):
        stub = f'{sys.executable} -c "raise SystemExit(1)"'
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(
                tmp, "--lane-surface", "codebase=surface:465", "--health-cmd", stub,
                "--health-interval-seconds", "0.05", "--deadline-minutes", "0.01",
            )
        self.assertEqual(proc.returncode, EXIT_DEADLINE)

    def test_waiting_events_have_run_state_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_cli(tmp, "--deadline-minutes", "0.01")
            lines = (Path(tmp) / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            event = json.loads(line)
            self.assertEqual(sorted(event), ["data", "message", "time", "type"])
            self.assertEqual(event["type"], "worker.waiting")
            for key in ("round", "lanes", "delivered_lanes", "missing_lanes", "elapsed_seconds",
                        "deadline_minutes"):
                self.assertIn(key, event["data"])

    def test_default_deadline_scales_with_question_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_all(tmp)
            self.run_cli(tmp, "--questions", "4")
            event = json.loads((Path(tmp) / "events.jsonl").read_text().splitlines()[-1])
        self.assertEqual(event["data"]["deadline_minutes"], 30)

    def test_questions_flag_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_state(tmp)
            argv = [sys.executable, self.script, "--run-dir", tmp, "--round", "1"]
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--questions", proc.stderr)

    def test_questions_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp, "--questions", "0")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--questions must be >= 1", proc.stderr)

    def test_unknown_lane_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp, "--lanes", "codebase,frontend")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unknown lanes: frontend", proc.stderr)

    def test_malformed_lane_surface_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp, "--lane-surface", "surface:465")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("LANE=SURFACE", proc.stderr)

    def test_lane_surface_for_unawaited_lane_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self.run_cli(tmp, "--lanes", "codebase", "--lane-surface", "web=surface:465")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("not being awaited", proc.stderr)

    def test_missing_required_args_exit_two(self):
        proc = subprocess.run(
            [sys.executable, self.script, "--run-dir", "/tmp"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)


class SessionWatch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name)
        write_state(tmp.name, workspace_id="WS")
        self.start_ns = time.time_ns()
        self.events = self.run_dir / "events.jsonl"
        self.events.write_text("".join(json.dumps({"type": "worker.launch_sent", "data": {
            "lane": lane, "surface_id": f"UUID-{lane}", "launch_id": f"launch-{lane}",
            "start_time_ns": self.start_ns}}) + "\n" for lane in LANES))

    def marker(self, lane, ns=None):
        path = self.run_dir / "artifacts" / f"session-{lane}" / "started"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        ns = self.start_ns if ns is None else ns
        os.utime(path, ns=(ns, ns))
        return path

    def watch(self, *extra, lanes=None, dead=False):
        lanes = list(LANES) if lanes is None else lanes
        health = self.run_dir / "health.py"
        health.write_text("print(" + repr(json.dumps({"surfaces": [] if dead else [
            {"id": f"UUID-{lane}"} for lane in lanes]})) + ")")
        argv = [sys.executable, str(Path(__file__).parent / "await_reports.py"),
                "--run-dir", str(self.run_dir), "--session", "--start-minutes", "0.002",
                "--poll-seconds", "0.01", "--health-cmd", f"{sys.executable} {health}"]
        for lane in lanes:
            argv += ["--lane-surface", f"{lane}=UUID-{lane}"]
        return subprocess.run(argv + list(extra), capture_output=True, text=True, timeout=10)

    def recorded(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()]

    def test_all_four_markers_required_and_recorded_once(self):
        for lane in LANES:
            self.marker(lane)
        for _ in range(2):
            proc = self.watch()
            self.assertEqual(proc.returncode, 0, proc.stderr)
        events = [e["data"] for e in self.recorded() if e["type"] == "worker.started"]
        self.assertEqual(len(events), 4)
        for data in events:
            lane = data["lane"]
            self.assertEqual(data, {"lane": lane, "surface_id": f"UUID-{lane}",
                "launch_id": f"launch-{lane}", "evidence": "marker",
                "marker_path": str(self.run_dir / "artifacts" / f"session-{lane}" / "started")})

    def test_missing_lanes_named(self):
        self.marker("codebase")
        self.marker("docs")
        proc = self.watch()
        self.assertEqual(proc.returncode, 9, proc.stderr)
        self.assertIn("not_started=codebase2,web", proc.stdout)
        self.assertEqual(self.recorded()[-1]["data"]["outcome"], "not_started")

    def test_stale_and_same_second_older_markers_ignored(self):
        self.start_ns = (self.start_ns // 1_000_000_000) * 1_000_000_000 + 500_000_000
        events = self.recorded()
        for event in events:
            event["data"]["start_time_ns"] = self.start_ns
        self.events.write_text("".join(json.dumps(e) + "\n" for e in events))
        for age in (1, 2_000_000_000):
            with self.subTest(age=age):
                self.marker("web", self.start_ns - age)
                proc = self.watch(lanes=["web"])
                self.assertEqual(proc.returncode, 9, proc.stderr)

    def test_replaced_or_unconfirmed_launch_cannot_accept_marker(self):
        self.marker("web")
        baseline = self.events.read_text()
        replacements = (
            {"type": "worker.launch_sent", "data": {"lane": "web", "surface_id": "UUID-web", "launch_id": "new", "start_time_ns": self.start_ns + 1}},
            {"type": "worker.starting", "data": {"lane": "web", "surface_id": "UUID-web", "launch_id": "pending"}},
            {"type": "pane.launched", "data": {"lane": "web", "surface_id": "replacement-surface"}},
        )
        for event in replacements:
            with self.subTest(event=event["type"]):
                previous = {"type": "worker.started", "data": {
                    "lane": "web", "surface_id": "UUID-web", "launch_id": "launch-web", "evidence": "marker"}}
                self.events.write_text(baseline + json.dumps(previous) + "\n" + json.dumps(event) + "\n")
                self.assertEqual(self.watch(lanes=["web"]).returncode, 9)

    def test_legacy_launch_without_timestamp_stays_pending(self):
        self.marker("web")
        self.events.write_text(json.dumps({"type": "worker.launch_sent", "data": {
            "lane": "web", "surface_id": "UUID-web"}}) + "\n")
        self.assertEqual(self.watch(lanes=["web"]).returncode, 9)

    def test_default_start_window_and_surface_requirement(self):
        from await_reports import build_parser
        args = build_parser().parse_args(["--run-dir", str(self.run_dir), "--session"])
        self.assertEqual(args.start_minutes, 5)
        proc = self.watch(lanes=[])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--lane-surface", proc.stderr)

    def test_screen_confirmation_allows_rearming_without_marker(self):
        with self.events.open("a") as stream:
            stream.write(json.dumps({"type": "worker.started", "data": {
                "lane": "web", "surface_id": "UUID-web", "launch_id": "launch-web", "evidence": "screen"}}) + "\n")
        self.assertEqual(self.watch(lanes=["web"]).returncode, 0)

    def test_pane_death(self):
        self.assertEqual(self.watch(lanes=["web"], dead=True).returncode, 7)

    def test_session_refuses_round_arguments(self):
        for flag in ("--round", "--questions"):
            proc = self.watch(flag, "1")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("--session refuses", proc.stderr)

    def test_session_refuses_positional_surface_refs(self):
        proc = self.watch("--lane-surface", "codebase=surface:465", lanes=[])
        self.assertEqual(proc.returncode, 2)
        self.assertIn(
            "--session requires stable surface UUIDs, not positional surface:N refs",
            proc.stderr,
        )

    def test_round_watch_skips_start_phase_for_started_launch(self):
        self.marker("web")
        self.assertEqual(self.watch(lanes=["web"]).returncode, 0)
        reports = self.run_dir / "reports"
        reports.mkdir()
        (reports / "round-1-web.md").write_text("report")
        proc = subprocess.run([sys.executable, str(Path(__file__).parent / "await_reports.py"),
            "--run-dir", str(self.run_dir), "--round", "1", "--questions", "1", "--lanes", "web"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("outcome=reports", proc.stdout)
        self.assertEqual(sum(e["type"] == "worker.started" for e in self.recorded()), 1)


class WorkspaceResolution(unittest.TestCase):
    script = str(Path(__file__).parent / "await_reports.py")

    def test_surface_without_resolvable_workspace_is_usage_error(self):
        """No env fallback: lane surfaces without pinned or explicit workspace must refuse."""
        with tempfile.TemporaryDirectory() as tmp:
            write_state(tmp)
            proc = subprocess.run(
                [
                    sys.executable, self.script,
                    "--run-dir", tmp, "--round", "1", "--questions", "1",
                    "--lane-surface", "web=surface:465",
                    "--deadline-minutes", "0.01",
                ],
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("workspace", proc.stderr)

    def test_health_command_uses_pinned_workspace(self):
        from await_reports import build_parser, health_command

        with tempfile.TemporaryDirectory() as tmp:
            write_state(tmp, workspace_id="WS-UUID")
            parser = build_parser()
            args = parser.parse_args(["--run-dir", tmp, "--round", "1", "--questions", "1"])
            cmd = health_command(args, parser)
        # --id-format both is required: launch hands out UUIDs, and a ref-only
        # listing can never contain them.
        self.assertEqual(
            cmd,
            ["cmux", "--json", "--id-format", "both", "surface-health", "--workspace", "WS-UUID"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
