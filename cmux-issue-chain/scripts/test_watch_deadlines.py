"""The persisted clock and report settlement contracts are identical in each standalone skill."""
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from watch_deadlines import arm, settled_report, wait_key


class DurableClock(unittest.TestCase):
    def setUp(self):
        self.events = []

    def arm(self, now, minutes=1, reason=None):
        with patch("watch_deadlines.time.time", return_value=now):
            return arm(self.events, "launch", minutes, 0.5, reason,
                       lambda data: self.events.append({"type": "worker.waiting", "data": data}))

    def test_rearm_retains_both_deadlines_even_if_flags_change(self):
        first = self.arm(1000)
        self.assertEqual(self.arm(1040, minutes=20), first)
        self.assertEqual(first["deadline"], 1060)
        self.assertEqual(first["start_deadline"], 1030)
        self.assertEqual(len(self.events), 1)

    def test_extension_moves_once_and_records_reason(self):
        self.arm(1000)
        extension = self.arm(1070, minutes=2, reason="still working")
        self.assertEqual(extension["deadline"], 1190)
        self.assertEqual(extension["start_deadline"], 1030)
        self.assertEqual(self.arm(1100, minutes=2, reason="still working"), extension)
        self.assertEqual(self.arm(1150), extension)
        self.assertEqual(len(self.events), 2)
        with self.assertRaisesRegex(ValueError, "already recorded"):
            self.arm(1200, minutes=3, reason="again")
        with self.assertRaisesRegex(ValueError, "non-empty"):
            self.arm(1200, reason=" ")

    def test_only_new_launch_or_recorded_recovery_changes_identity(self):
        target = {"role": "review", "surface_id": "surface"}
        events = [{"type": "worker.launch_sent", "data": {**target, "launch_id": "one"}}]
        def key():
            return wait_key(events, {"pass": 1}, [target])
        initial = key()
        for kind, data in (("worker.waiting", {"outcome": "not_started"}),
                           ("worker.started", {"evidence": "marker"}),
                           ("worker.started", {"evidence": "report"})):
            events.append({"type": kind, "data": {**target, **data}})
            self.assertEqual(key(), initial)
        for kind, data in (("worker.dialog_response", {}), ("worker.prompt_sent", {}),
                           ("worker.started", {"evidence": "screen"}),
                           ("worker.launch_sent", {"launch_id": "two"})):
            if kind in ("worker.dialog_response", "worker.started"):
                events.append({"type": "worker.waiting", "data": {**target, "outcome": "not_started"}})
            before = key()
            events.append({"type": kind, "data": {**target, **data}})
            self.assertNotEqual(key(), before)

    def test_screen_confirmation_without_exit_nine_does_not_renew_wait(self):
        target = {"stage": "spec", "pass": 1, "surface_id": "surface"}
        events = [{"type": "worker.launch_sent", "data": {**target, "launch_id": "one"}}]
        key = wait_key(events, {}, [target])
        events.append({"type": "worker.started", "data": {**target, "evidence": "screen"}})
        self.assertEqual(wait_key(events, {}, [target]), key)

    def test_session_exit_nine_recovery_is_scoped_to_pending_lanes(self):
        target = {"lane": "web", "surface_id": "surface"}
        events = [{"type": "worker.launch_sent", "data": {**target, "launch_id": "one"}}]
        key = wait_key(events, {}, [target])
        events.append({"type": "worker.waiting", "data": {
            "session": True, "not_started": ["docs"], "surface_ids": {"docs": "other"},
            "outcome": "not_started"}})
        events.append({"type": "worker.dialog_response", "data": target})
        self.assertEqual(wait_key(events, {}, [target]), key)
        events.append({"type": "worker.waiting", "data": {
            "session": True, "not_started": ["web"], "surface_ids": {"web": "surface"},
            "outcome": "not_started"}})
        events.append({"type": "worker.dialog_response", "data": target})
        self.assertNotEqual(wait_key(events, {}, [target]), key)

    def test_standalone_copies_match(self):
        root = Path(__file__).resolve().parents[2]
        paths = [root / skill / "scripts/watch_deadlines.py" for skill in
                 ("cmux-issue-chain", "cmux-planning", "cmux-grilling")]
        if all(p.is_file() for p in paths):
            self.assertEqual(len({p.read_bytes() for p in paths}), 1)


class ReportSettlement(unittest.TestCase):
    def test_only_consecutive_identical_nonempty_bytes_settle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            previous = None
            for content, expected in ((b"draft", False), (b"final", False), (b"final", True),
                                      (b"", False), (b"final", False), (b"final", True),
                                      (None, False), (b"final", False), (b"final", True)):
                with self.subTest(content=content, expected=expected):
                    if content is None:
                        path.unlink()
                    else:
                        path.write_bytes(content)
                    previous, settled = settled_report(path, None, previous)
                    self.assertEqual(settled, expected)
                    self.assertEqual(previous is None, not content)

    def test_stale_report_resets_previous_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_bytes(b"final")
            stamp = path.stat().st_mtime_ns
            previous, _ = settled_report(path, None, None)
            self.assertEqual(settled_report(path, {"start_time_ns": stamp + 1}, previous),
                             (None, False))
            os.utime(path, ns=(stamp, stamp))
            self.assertTrue(settled_report(path, {"start_time_ns": stamp}, previous)[1])

    def test_disappearing_or_truncated_report_is_not_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.md"
            path.write_bytes(b"final")
            for result in (FileNotFoundError(), b""):
                kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with self.subTest(result=result), patch.object(Path, "read_bytes", **kwargs):
                    self.assertEqual(settled_report(path, None, "previous"), (None, False))
