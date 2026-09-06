#!/usr/bin/env python3
"""pane_ctl regression tests. Run: python3 scripts/test_pane_ctl.py"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator_lib import delivery_text
from launch_wave import (
    SUBAGENT_MARKER_ENV,
    SUBAGENT_MARKER_VALUE,
    lane_argv,
    snapshot_identity,
)

SCRIPT = str(Path(__file__).parent / "pane_ctl.py")

from test_support import FAKE_CMUX


class PaneCtlCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.run_dir.mkdir()
        profiles = {
            "codebase": {
                "profile": "claude-opus-xhigh", "harness": "claude-code",
                "executable": "claude", "model": "opus", "effort": "xhigh",
            },
            "codebase2": {
                "profile": "codex-astra-xhigh", "harness": "codex",
                "executable": "codex", "model": "gpt-6-astra", "effort": "xhigh",
            },
            "docs": {
                "profile": "codex-luna-medium", "harness": "codex",
                "executable": "codex", "model": "gpt-5.6-luna", "effort": "medium",
            },
            "web": {
                "profile": "claude-sonnet-medium", "harness": "claude-code",
                "executable": "claude", "model": "sonnet", "effort": "medium",
            },
        }
        for lane, entry in profiles.items():
            entry.update({
                "lane": lane,
                "requested_executable": entry["executable"],
                "resolved_executable": f"/test/bin/{entry['executable']}",
                "detected_version": f"{entry['executable']} test",
                "preflight": {"status": "passed"},
                "entitlement": {"status": "unverified"},
                "environment": {SUBAGENT_MARKER_ENV: SUBAGENT_MARKER_VALUE},
            })
            entry["argv"] = lane_argv(lane, entry)
        wave = {
            "snapshot_version": 1,
            "run_id": "test-run",
            "status": "passed",
            "resolved_at": "2026-08-17T00:00:00+00:00",
            "config": {"source": "/test/agents.json", "sha256": "config-sha"},
            "effective_overrides": {},
            "resolved_profiles": profiles,
        }
        wave["snapshot_id"] = snapshot_identity(wave)
        wave_path = self.run_dir / "launch-waves" / "wave.json"
        wave_path.parent.mkdir()
        wave_path.write_text(json.dumps(wave), encoding="utf-8")
        pointer = {
            "path": "launch-waves/wave.json",
            "sha256": hashlib.sha256(wave_path.read_bytes()).hexdigest(),
            "snapshot_id": wave["snapshot_id"],
            "prepared_at": wave["resolved_at"],
        }
        (self.run_dir / "state.json").write_text(
            json.dumps({
                "run_id": "test-run", "workspace_id": "WS-UUID",
                "slug": "checkout-refactor", "launch_wave": pointer,
            }),
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
        self.assertEqual(out["label"], "Researcher Codebase2 - grill-checkout-refactor")

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

    def test_wave_edited_without_restamping_its_identity_is_refused(self):
        wave_path = self.run_dir / "launch-waves" / "wave.json"
        wave = json.loads(wave_path.read_text(encoding="utf-8"))
        wave["resolved_profiles"]["codebase2"]["detected_version"] = "0.0-tampered"
        wave_path.write_text(json.dumps(wave), encoding="utf-8")
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["launch_wave"]["sha256"] = hashlib.sha256(wave_path.read_bytes()).hexdigest()
        state_path.write_text(json.dumps(state), encoding="utf-8")

        proc = self.run_ctl(
            "launch", "--run-dir", str(self.run_dir),
            "--lane", "codebase2", "--anchor", "surface:5",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("snapshot identity", proc.stderr)
        self.assertEqual(self.cmux_calls(), [])

    def test_wave_rewritten_to_widen_the_codex_sandbox_is_refused(self):
        wave_path = self.run_dir / "launch-waves" / "wave.json"
        wave = json.loads(wave_path.read_text(encoding="utf-8"))
        wave["resolved_profiles"]["codebase2"]["argv"][1:3] = ["-s", "danger-full-access"]
        # Restamped as the most thorough tamper would, so only the argv rule can refuse it.
        wave["snapshot_id"] = snapshot_identity(wave)
        wave_path.write_text(json.dumps(wave), encoding="utf-8")
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["launch_wave"]["sha256"] = hashlib.sha256(wave_path.read_bytes()).hexdigest()
        state["launch_wave"]["snapshot_id"] = wave["snapshot_id"]
        state_path.write_text(json.dumps(state), encoding="utf-8")

        proc = self.run_ctl(
            "launch", "--run-dir", str(self.run_dir),
            "--lane", "codebase2", "--anchor", "surface:5",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("violates adapter policy", proc.stderr)
        self.assertEqual(self.cmux_calls(), [])

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
        self.assertIn("--model gpt-6-astra", command)

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.launch_sent"])
        self.assertEqual(events[0]["data"]["command"], command)

    def test_claude_lane_gets_the_marker_too(self):
        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self.cmux_calls()[0][-1],
            "CMUX_AGENT_MANAGED_SUBAGENT=1 claude --model sonnet --effort medium "
            "--permission-mode auto",
        )


class Deliver(PaneCtlCase):
    FOLLOW_UP = "re-emit the report per the Research Report Contract; fix the format, not the substance"

    def test_send_enter_readscreen_in_order(self):
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--text", self.FOLLOW_UP,
            "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PANE SCREEN", proc.stdout)

        verbs = [call[0] for call in self.cmux_calls()]
        self.assertEqual(verbs, ["send", "send-key", "read-screen"])
        send, send_key, _ = self.cmux_calls()
        self.assertEqual(send[-1], self.FOLLOW_UP)
        self.assertEqual(send_key[-1], "enter")

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.prompt_sent"])
        self.assertEqual(events[0]["data"]["lane"], "web")
        self.assertIsNone(events[0]["data"]["prompt_path"])
        self.assertIsNone(events[0]["data"]["kind"])

    def test_round_prompt_sends_the_skills_own_task_framing(self):
        prompt_path = "prompts/round-1-web.md"
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--prompt", prompt_path,
            "--kind", "round", "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        expected = delivery_text("round", prompt_path)
        self.assertEqual(self.cmux_calls()[0][-1], expected)
        events = self.events()
        self.assertEqual(events[0]["data"]["text"], expected)
        self.assertEqual(events[0]["data"]["prompt_path"], prompt_path)
        self.assertEqual(events[0]["data"]["kind"], "round")

    def test_round_is_the_default_kind(self):
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--prompt", "prompts/round-1-docs.md",
            "--lane", "docs", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.events()[0]["data"]["kind"], "round")

    def test_session_and_round_pull_in_opposite_directions(self):
        session = delivery_text("session", "prompts/session-codebase.md")
        round_text = delivery_text("round", "prompts/round-1-codebase.md")
        self.assertIn("wait idle for round prompts", session)
        self.assertIn("Answer it now", round_text)
        for text in (session, round_text):
            self.assertNotIn("report back", text)

    def test_text_and_prompt_are_mutually_exclusive(self):
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir), "--surface", "SURF-UUID",
            "--prompt", "prompts/round-1-web.md", "--text", "hi", "--settle-seconds", "0",
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_one_of_text_or_prompt_is_required(self):
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir), "--surface", "SURF-UUID",
            "--settle-seconds", "0",
        )
        self.assertNotEqual(proc.returncode, 0)


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
