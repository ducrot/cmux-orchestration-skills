#!/usr/bin/env python3
"""Watcher regression tests. Run: python3 scripts/test_await_report.py"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from await_report import (  # noqa: E402
    EXIT_DEADLINE,
    EXIT_PANE_DEAD,
    EXIT_REPORT,
    build_parser,
    check_health,
    health_command,
    report_path,
    surface_is_dead,
)
from orchestrator_lib import MINIMUM_WAIT_MINUTES  # noqa: E402
from parse_report import EXIT_CODES as GATE_EXIT_CODES  # noqa: E402


class ReportPath(unittest.TestCase):
    def test_matches_render_prompt_stem(self):
        self.assertEqual(
            report_path(Path("/run"), "review", 1),
            Path("/run/reports/review-1.md"),
        )


class ExitCodeVocabulary(unittest.TestCase):
    def test_watcher_codes_disjoint_from_gate_codes(self):
        """Skill-wide unique vocabulary: 0 ok, 1 crash, 2 usage, 3-6 gate, 7-8 watcher."""
        watcher = {EXIT_PANE_DEAD, EXIT_DEADLINE}
        self.assertFalse(watcher & set(GATE_EXIT_CODES.values()))
        self.assertFalse(watcher & {1, 2})
        self.assertEqual(EXIT_REPORT, 0)  # "report exists", intentionally shared with success

    def test_deadline_defaults_cover_all_roles(self):
        self.assertEqual(set(MINIMUM_WAIT_MINUTES), {"implement", "simplify", "test", "review"})


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


class SurfaceIsDead(unittest.TestCase):
    def test_listed_surface_is_alive_plain_and_json(self):
        self.assertFalse(surface_is_dead(HEALTH_PLAIN, "surface:465"))
        self.assertFalse(surface_is_dead(HEALTH_JSON, "surface:465"))

    def test_uuid_from_launch_is_alive_in_json(self):
        """Regression (ISSUE-013 pilot): pane_ctl launch hands out UUIDs; a ref-only
        comparison declared every UUID-watched pane dead after 0 seconds."""
        self.assertFalse(surface_is_dead(HEALTH_JSON, UUID_465))

    def test_absent_uuid_is_dead_in_json(self):
        self.assertTrue(surface_is_dead(HEALTH_JSON, "BBBB0000-0000-4000-8000-000000000000"))

    def test_absent_surface_is_dead_plain_and_json(self):
        self.assertTrue(surface_is_dead(HEALTH_PLAIN, "surface:999"))
        self.assertTrue(surface_is_dead(HEALTH_JSON, "surface:999"))

    def test_prefix_of_listed_ref_does_not_count_as_alive(self):
        """Regression: substring matching let `surface:46` ride on `surface:465`'s line."""
        self.assertTrue(surface_is_dead(HEALTH_PLAIN, "surface:46"))
        self.assertTrue(surface_is_dead(HEALTH_JSON, "surface:46"))

    def test_empty_listing_is_dead(self):
        self.assertTrue(surface_is_dead("", "surface:465"))
        self.assertTrue(surface_is_dead('{"surfaces": []}', "surface:465"))


class CheckHealth(unittest.TestCase):
    def test_failing_command_is_unknown_never_dead(self):
        status, detail = check_health([sys.executable, "-c", "raise SystemExit(1)"], "surface:465")
        self.assertEqual(status, "unknown")
        self.assertTrue(detail)

    def test_missing_command_is_unknown(self):
        status, _ = check_health(["/nonexistent-health-cmd"], "surface:465")
        self.assertEqual(status, "unknown")


class Cli(unittest.TestCase):
    script = str(Path(__file__).parent / "await_report.py")

    def run_cli(self, run_dir: str, *extra: str) -> subprocess.CompletedProcess:
        state = Path(run_dir) / "state.json"
        if not state.exists():
            state.write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
        argv = [
            sys.executable, self.script,
            "--run-dir", run_dir, "--role", "review", "--pass", "1",
            "--poll-seconds", "0.05", "--heartbeat-seconds", "0.05",
            *extra,
        ]
        return subprocess.run(argv, capture_output=True, text=True, timeout=30)

    def write_report(self, run_dir: str) -> Path:
        path = Path(run_dir) / "reports" / "review-1.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## Result\nNO FINDINGS\n", encoding="utf-8")
        return path

    def test_existing_report_exits_zero_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            self.write_report(tmp)
            proc = self.run_cli(tmp)
        self.assertEqual(proc.returncode, EXIT_REPORT)
        self.assertIn("outcome=report", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_file_only_mode_hits_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            proc = self.run_cli(tmp, "--deadline-minutes", "0.005")
        self.assertEqual(proc.returncode, EXIT_DEADLINE)
        self.assertIn("outcome=deadline", proc.stdout)

    def test_report_written_mid_wait_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            timer = threading.Timer(0.3, self.write_report, args=(tmp,))
            timer.start()
            try:
                proc = self.run_cli(tmp, "--deadline-minutes", "0.5")
            finally:
                timer.cancel()
        self.assertEqual(proc.returncode, EXIT_REPORT)

    def test_dead_pane_exits_seven(self):
        stub = f'{sys.executable} -c "print(\'surface:999 running\')"'
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            proc = self.run_cli(
                tmp, "--surface", "surface:465", "--health-cmd", stub,
                "--health-interval-seconds", "0.05", "--deadline-minutes", "0.5",
            )
        self.assertEqual(proc.returncode, EXIT_PANE_DEAD)
        self.assertIn("outcome=pane_dead", proc.stdout)

    def test_erroring_health_cmd_does_not_end_wait(self):
        stub = f'{sys.executable} -c "raise SystemExit(1)"'
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            proc = self.run_cli(
                tmp, "--surface", "surface:465", "--health-cmd", stub,
                "--health-interval-seconds", "0.05", "--deadline-minutes", "0.01",
            )
        self.assertEqual(proc.returncode, EXIT_DEADLINE)

    def test_waiting_events_have_run_state_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            self.run_cli(tmp, "--deadline-minutes", "0.01")
            lines = (Path(tmp) / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(lines)
        for line in lines:
            event = json.loads(line)
            self.assertEqual(sorted(event), ["data", "message", "time", "type"])
            self.assertEqual(event["type"], "worker.waiting")
            for key in ("role", "pass", "surface_id", "elapsed_seconds", "deadline_minutes"):
                self.assertIn(key, event["data"])

    def test_missing_required_args_exit_two(self):
        proc = subprocess.run(
            [sys.executable, self.script, "--run-dir", "/tmp"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)

    def test_surface_without_resolvable_workspace_is_usage_error(self):
        """No env fallback: --surface without pinned or explicit workspace must refuse."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            proc = self.run_cli(tmp, "--surface", "surface:465", "--deadline-minutes", "0.01")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("workspace", proc.stderr)


class WorkspaceResolution(unittest.TestCase):
    def make_args(self, run_dir: str, *extra: str):
        parser = build_parser()
        return parser, parser.parse_args(
            ["--run-dir", run_dir, "--role", "review", "--pass", "1", *extra]
        )

    def test_health_command_uses_pinned_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            (Path(tmp) / "state.json").write_text(
                json.dumps({"workflow": "issue-chain", "layout_version": 1, "workspace_id": "WS-UUID"}), encoding="utf-8"
            )
            parser, args = self.make_args(tmp)
            cmd = health_command(args, parser)
        # --id-format both is required: launch hands out UUIDs, and a ref-only
        # listing can never contain them.
        self.assertEqual(
            cmd,
            ["cmux", "--json", "--id-format", "both", "surface-health", "--workspace", "WS-UUID"],
        )

    def test_explicit_workspace_flag_beats_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            (Path(tmp) / "state.json").write_text(
                json.dumps({"workflow": "issue-chain", "layout_version": 1, "workspace_id": "WS-UUID"}), encoding="utf-8"
            )
            parser, args = self.make_args(tmp, "--workspace", "OVERRIDE")
            cmd = health_command(args, parser)
        self.assertIn("OVERRIDE", cmd)
        self.assertNotIn("WS-UUID", cmd)

    def test_null_pinned_workspace_is_usage_error(self):
        """A --no-workspace run has workspace_id null; health checks must refuse, not unscope."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1}))
            (Path(tmp) / "state.json").write_text(
                json.dumps({"workflow": "issue-chain", "layout_version": 1, "workspace_id": None}), encoding="utf-8"
            )
            parser, args = self.make_args(tmp)
            with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
                health_command(args, parser)
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
