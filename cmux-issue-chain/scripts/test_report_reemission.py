"""Exercise the standalone event -> re-emission watcher CLI contract in each skill."""
import contextlib
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SKILL = Path(__file__).resolve().parents[1]
GRILLING = SKILL.name == "cmux-grilling"


class ReportReemission(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name)
        (self.run / "state.json").write_text(json.dumps({
            "workflow": "grilling" if GRILLING else "issue-chain",
            "layout_version": 2, "max_rounds": 4,
        }))
        self.module = importlib.import_module("await_reports" if GRILLING else "await_report")
        self.identity = {"round": 1, "lane": "web"} if GRILLING else {"role": "review", "pass": 1}

    def report(self, content=b"rejected", lane="web"):
        stem = f"round-1-{lane}" if GRILLING else "review-1"
        path = self.run / "reports" / f"{stem}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
        return path

    def fill_reports(self):
        if GRILLING:
            for lane in ("codebase", "codebase2", "docs"):
                self.report(b"other lane", lane)
        return self.report()

    def events(self):
        path = self.run / "events.jsonl"
        return list(map(json.loads, path.read_text().splitlines())) if path.exists() else []

    def clocks(self):
        return [e["data"]["watch_clock"] for e in self.events() if "watch_clock" in e.get("data", {})]

    def watcher_args(self, *extra):
        scope = ["--round", "1", "--questions", "1"] if GRILLING else [
            "--role", "review", "--pass", "1", "--cmux-cmd", "/usr/bin/true"]
        return ["--run-dir", str(self.run), *scope, "--poll-seconds", ".01",
                "--heartbeat-seconds", "0", "--deadline-minutes", ".05", *extra]

    def cli(self, *extra):
        return subprocess.run([sys.executable, str(Path(self.module.__file__)),
                               *self.watcher_args(*extra)], capture_output=True, text=True, timeout=10)

    def request(self, identity=None):
        return subprocess.run([
            sys.executable, str(SKILL / "scripts/run_state.py"), "event", "--run-dir", str(self.run),
            "--type", "report.reformat_requested", "--message", "format correction requested",
            "--data", json.dumps(self.identity if identity is None else identity),
            "--cmux-cmd", "/usr/bin/true",
        ], capture_output=True, text=True, timeout=10)

    def expire(self):
        result = self.cli("--deadline-minutes", "0")
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertEqual(len(self.clocks()), 1)

    def test_immediate_rewrite_opens_fresh_window_without_extension(self):
        self.expire()
        report = self.fill_reports()
        result = self.request({**self.identity, "report_sha256": "untrusted supplied digest"})
        self.assertEqual(result.returncode, 0, result.stderr)
        request = next(e for e in self.events() if e["type"] == "report.reformat_requested")
        self.assertEqual(request["data"]["report_sha256"], hashlib.sha256(b"rejected").hexdigest())
        report.write_bytes(b"corrected")  # Rewritten before the watcher is even armed.
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        before, after = self.clocks()
        self.assertNotEqual(before["key"], after["key"])
        self.assertGreater(after["deadline"], before["deadline"])
        self.assertEqual(after["extension"], 0)

    def test_old_digest_waits_several_polls_and_new_bytes_must_settle(self):
        self.expire()
        report = self.fill_reports()
        result = self.request()
        self.assertEqual(result.returncode, 0, result.stderr)
        parser = self.module.build_parser()
        args = parser.parse_args(self.watcher_args())
        polls = []

        def poll(_seconds):
            polls.append(self.events()[-1]["data"])
            self.assertLessEqual(len(polls), 5, "rewritten bytes never settled")
            self.assertNotIn(polls[-1].get("outcome"), ("report", "reports"))
            if len(polls) == 2:
                report.write_bytes(b"rejected")  # New mtime alone cannot satisfy re-emission.
            if len(polls) == 4:
                report.write_bytes(b"corrected")

        with patch.object(self.module.time, "sleep", side_effect=poll), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.watch(args, parser), 0)
        self.assertEqual(len(polls), 5, "old report was accepted or new bytes did not settle")
        if GRILLING:
            self.assertEqual(polls[1]["delivered_lanes"], ["codebase", "codebase2", "docs"])
        self.assertEqual(report.read_bytes(), b"corrected")

    def test_unchanged_reemission_deadline_is_persisted_on_rearm(self):
        self.fill_reports()
        self.assertEqual(self.request().returncode, 0)
        first = self.cli("--deadline-minutes", ".001")
        self.assertEqual(first.returncode, 8, first.stderr)
        clocks = self.clocks()
        second = self.cli()
        self.assertEqual(second.returncode, 8, second.stderr)
        self.assertEqual(self.clocks(), clocks)

    def test_reemission_preserves_the_available_extension(self):
        self.expire()
        self.fill_reports()
        self.assertEqual(self.request().returncode, 0)
        self.assertEqual(self.cli("--deadline-minutes", "0").returncode, 8)
        self.assertEqual([c["extension"] for c in self.clocks()], [0, 0])
        result = self.cli("--deadline-reason", "worker still correcting", "--deadline-minutes", ".001")
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertEqual([c["extension"] for c in self.clocks()], [0, 0, 1])

    def test_reemission_does_not_restore_a_spent_extension(self):
        self.expire()
        self.assertEqual(self.cli("--deadline-reason", "worker active", "--deadline-minutes", "0").returncode, 8)
        self.fill_reports()
        self.assertEqual(self.request().returncode, 0)
        self.assertEqual(self.cli("--deadline-minutes", "0").returncode, 8)
        before = (self.run / "events.jsonl").read_bytes()
        result = self.cli("--deadline-reason", "again", "--deadline-minutes", ".001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already recorded", result.stderr)
        self.assertEqual((self.run / "events.jsonl").read_bytes(), before)

    def test_second_request_is_hitl_and_cannot_create_a_third_window(self):
        self.expire()
        report = self.fill_reports()
        self.assertEqual(self.request().returncode, 0)
        report.write_bytes(b"corrected")
        self.assertEqual(self.cli().returncode, 0)
        before = (self.run / "events.jsonl").read_bytes()
        second = self.request()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("HITL", second.stderr)
        self.assertEqual((self.run / "events.jsonl").read_bytes(), before)
        self.assertEqual(len(self.clocks()), 2)

    def test_duplicate_or_legacy_event_requires_hitl_before_arming(self):
        self.fill_reports()
        self.assertEqual(self.request().returncode, 0)
        request = next(e for e in self.events() if e["type"] == "report.reformat_requested")
        for requests in ([request, request], [{**request, "data": self.identity}]):
            with self.subTest(requests=requests):
                (self.run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in requests))
                before = (self.run / "events.jsonl").read_bytes()
                result = self.cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("HITL", result.stderr)
                self.assertEqual((self.run / "events.jsonl").read_bytes(), before)

    def test_request_identity_and_nonempty_report_are_required(self):
        self.fill_reports()
        for identity in ({}, {**self.identity, "round" if GRILLING else "pass": 0},
                         {**self.identity, "lane" if GRILLING else "role": "unknown"}):
            with self.subTest(identity=identity):
                self.assertNotEqual(self.request(identity).returncode, 0)
                self.assertFalse(any(e["type"] == "report.reformat_requested" for e in self.events()))
        self.report(b"")
        self.assertNotEqual(self.request().returncode, 0)
        self.report().unlink()
        self.assertNotEqual(self.request().returncode, 0)

    def test_other_pass_or_round_request_does_not_renew_this_clock(self):
        self.expire()
        identity = {**self.identity, "round" if GRILLING else "pass": 2}
        stem = "round-2-web" if GRILLING else "review-2"
        path = self.run / "reports" / f"{stem}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"other report")
        self.assertEqual(self.request(identity).returncode, 0)
        clocks = self.clocks()
        self.assertEqual(self.cli().returncode, 8)
        self.assertEqual(self.clocks(), clocks)

    def test_expired_rearm_allows_exactly_one_settling_poll(self):
        for content in ("unchanged", "changing", "missing"):
            with self.subTest(content=content):
                events = self.run / "events.jsonl"
                events.unlink(missing_ok=True)
                for report in (self.run / "reports").glob("*.md"):
                    report.unlink()
                self.expire()
                report = self.fill_reports() if content != "missing" else None
                parser = self.module.build_parser()
                args = parser.parse_args(self.watcher_args())
                polls = []

                def poll(_seconds):
                    polls.append(_seconds)
                    self.assertEqual(len(polls), 1, "expired deadline gained extra polls")
                    if content == "changing":
                        report.write_bytes(b"still changing")

                with patch.object(self.module.time, "sleep", side_effect=poll), contextlib.redirect_stdout(io.StringIO()):
                    result = self.module.watch(args, parser)
                self.assertEqual(result, 0 if content == "unchanged" else 8)
                self.assertEqual(len(polls), 0 if content == "missing" else 1)

    def test_recovery_documentation_pins_wait_and_baseline_contract(self):
        reference = "gate-recovery.md" if GRILLING else "report-recovery.md"
        text = " ".join((SKILL / "references" / reference).read_text().split())
        vocabulary = (SKILL / "references/event-vocabulary.md").read_text()
        for phrase in ("arm the watcher immediately", "gate on the report the watcher returns",
                       "before sending", "report_sha256", "second request", "HITL",
                       "one settling poll"):
            self.assertIn(phrase, text)
        self.assertIn("report_sha256", vocabulary)
        self.assertIn("await_reports.py" if GRILLING else "await_report.py", text)
        self.assertLessEqual((SKILL / "SKILL.md").stat().st_size,
                             (75894 if GRILLING else 109325) * .7)


if __name__ == "__main__":
    unittest.main()
