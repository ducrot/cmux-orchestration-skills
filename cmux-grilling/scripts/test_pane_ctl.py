#!/usr/bin/env python3
"""pane_ctl regression tests. Run: python3 scripts/test_pane_ctl.py"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SCRIPT = str(Path(__file__).parent / "pane_ctl.py")

FAKE_CMUX = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_CMUX_LOG"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if "new-split" in args:
    print(json.dumps({
        "pane_id": "PANE-UUID", "pane_ref": "pane:9",
        "surface_id": "SURF-UUID", "surface_ref": "surface:9",
        "type": "terminal", "workspace_id": "WS-UUID", "workspace_ref": "workspace:1",
    }))
elif "read-screen" in args:
    print("LANE SCREEN")
else:
    print("OK")
'''


class PaneCtlCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.run_dir.mkdir()
        (self.run_dir / "state.json").write_text(
            json.dumps({"workspace_id": "WS-UUID", "slug": "checkout-refactor"}),
            encoding="utf-8",
        )
        self.log = Path(self._tmp.name) / "cmux-calls.jsonl"
        fake = Path(self._tmp.name) / "fake_cmux.py"
        fake.write_text(FAKE_CMUX, encoding="utf-8")
        self.cmux_cmd = f"{sys.executable} {fake}"

    def tearDown(self):
        self._tmp.cleanup()

    def run_ctl(self, *argv: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, FAKE_CMUX_LOG=str(self.log))
        return subprocess.run(
            [sys.executable, SCRIPT, "--cmux-cmd", self.cmux_cmd, *argv],
            capture_output=True, text=True, timeout=30, env=env,
        )

    def cmux_calls(self) -> list[list[str]]:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def events(self) -> list[dict]:
        path = self.run_dir / "events.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Workspace(PaneCtlCase):
    def test_prints_pinned_workspace(self):
        proc = self.run_ctl("workspace", "--run-dir", str(self.run_dir))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "WS-UUID")

    def test_null_workspace_fails_loudly(self):
        (self.run_dir / "state.json").write_text(
            json.dumps({"workspace_id": None}), encoding="utf-8"
        )
        proc = self.run_ctl("workspace", "--run-dir", str(self.run_dir))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("workspace_id", proc.stderr)


class Injector(PaneCtlCase):
    def test_injects_workspace_after_command_word(self):
        proc = self.run_ctl("cmux", "--run-dir", str(self.run_dir), "--", "list-panes", "--json")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.cmux_calls(), [["list-panes", "--workspace", "WS-UUID", "--json"]])

    def test_refuses_explicit_workspace(self):
        proc = self.run_ctl(
            "cmux", "--run-dir", str(self.run_dir), "--", "list-panes", "--workspace", "other"
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.cmux_calls(), [])


class Launch(PaneCtlCase):
    def test_splits_labels_and_records_events(self):
        proc = self.run_ctl(
            "launch", "--run-dir", str(self.run_dir),
            "--lane", "codebase2", "--anchor", "surface:5",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["surface_id"], "SURF-UUID")
        self.assertEqual(out["label"], "Researcher Codebase2 (Codex) - grill-checkout-refactor")

        calls = self.cmux_calls()
        self.assertEqual(len(calls), 2)
        split, rename = calls
        self.assertIn("new-split", split)
        for expected in ("--workspace", "WS-UUID", "--surface", "surface:5", "--focus", "false"):
            self.assertIn(expected, split)
        # Stable UUIDs, not positional refs: refs shift when panes close.
        self.assertEqual(rename[:1], ["rename-tab"])
        self.assertIn("SURF-UUID", rename)

        types = [event["type"] for event in self.events()]
        self.assertEqual(types, ["pane.launched", "pane.labeled"])
        self.assertEqual(self.events()[0]["data"]["lane"], "codebase2")

    def test_unknown_lane_is_usage_error(self):
        proc = self.run_ctl(
            "launch", "--run-dir", str(self.run_dir),
            "--lane", "review", "--anchor", "surface:5",
        )
        self.assertEqual(proc.returncode, 2)


class StartAgent(PaneCtlCase):
    def test_sends_marked_launch_command(self):
        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--lane", "codebase2", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        verbs = [call[0] for call in self.cmux_calls()]
        self.assertEqual(verbs, ["send", "send-key", "read-screen"])
        command = self.cmux_calls()[0][-1]
        # The marker is what keeps the lane pane out of the human's notification centre.
        self.assertTrue(command.startswith("CMUX_AGENT_MANAGED_SUBAGENT=1 codex "), command)
        self.assertIn("approvals_reviewer=auto_review", command)

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.launch_sent"])
        self.assertEqual(events[0]["data"]["command"], command)

    def test_claude_lane_gets_the_marker_too(self):
        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.cmux_calls()[0][-1], "CMUX_AGENT_MANAGED_SUBAGENT=1 claude")


class Deliver(PaneCtlCase):
    def test_send_enter_readscreen_in_order(self):
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--text", "Read prompts/round-1-web.md and report back.",
            "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("LANE SCREEN", proc.stdout)

        verbs = [call[0] for call in self.cmux_calls()]
        self.assertEqual(verbs, ["send", "send-key", "read-screen"])
        send, send_key, _ = self.cmux_calls()
        self.assertEqual(send[-1], "Read prompts/round-1-web.md and report back.")
        self.assertEqual(send_key[-1], "enter")

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.prompt_sent"])
        self.assertEqual(events[0]["data"]["lane"], "web")


class Close(PaneCtlCase):
    def test_closes_and_records_event(self):
        proc = self.run_ctl(
            "close", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--lane", "docs",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.cmux_calls(), [
            ["close-surface", "--workspace", "WS-UUID", "--surface", "SURF-UUID"],
        ])
        events = self.events()
        self.assertEqual([event["type"] for event in events], ["pane.closed"])
        self.assertEqual(events[0]["data"]["lane"], "docs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
