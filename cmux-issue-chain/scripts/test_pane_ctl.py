#!/usr/bin/env python3
"""pane_ctl regression tests. Run: python3 scripts/test_pane_ctl.py"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents_config import SUBAGENT_MARKER_ENV, SUBAGENT_MARKER_VALUE
from orchestrator_lib import delivery_text
from worker_snapshot import snapshot_identity, stage_argv

SCRIPT = str(Path(__file__).parent / "pane_ctl.py")

from test_support import FAKE_CMUX


class PaneCtlCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.run_dir.mkdir()
        (self.run_dir / "state.json").write_text(
            json.dumps({
                "run_id": "RUN-1",
                "workspace_id": "WS-UUID",
                "issue": {"id": "ISSUE-001"},
                "current_stage": "implement",
                "prepared_stage": None,
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

    def prepare_snapshot(self, role: str, pass_num: int = 1, *, status: str = "passed") -> Path:
        profile = (
            {"profile": "claude-opus-xhigh", "harness": "claude-code",
             "requested_executable": "claude", "model": "opus", "effort": "xhigh"}
            if role in {"review", "simplify"}
            else {"profile": "codex-sol-xhigh", "harness": "codex",
                  "requested_executable": "codex", "model": "gpt-5.6-sol", "effort": "xhigh"}
        )
        selected = {
            **profile,
            # Deliberately different from argv[0]: the realpath is audit data, not the launch identity.
            "resolved_executable": f"/audit/realpath/{profile['requested_executable']}",
            "detected_version": "99.1-test",
            "preflight": {"status": "passed"},
            "entitlement": {"status": "unverified"},
            "environment": {SUBAGENT_MARKER_ENV: SUBAGENT_MARKER_VALUE},
        }
        # Derived, so the fixture cannot drift from the safety policy the loader re-derives.
        selected["argv"] = stage_argv(role, selected)
        snapshot = {
            "snapshot_version": 1,
            "run_id": "RUN-1",
            "stage": role,
            "pass": pass_num,
            "status": status,
            "resolved_profiles": {
                worker: {"entitlement": {"status": "unverified"}}
                for worker in ("implement", "simplify", "review", "test")
            },
            "selected_worker": selected,
        }
        snapshot["snapshot_id"] = snapshot_identity(snapshot)
        relative = Path("stage-snapshots") / f"{role}-{pass_num}.json"
        path = self.run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        state["current_stage"] = role
        state["prepared_stage"] = {
            "stage": role,
            "pass": pass_num,
            "path": str(relative),
            "sha256": digest,
            "snapshot_id": snapshot["snapshot_id"],
        }
        (self.run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        return path

    def restamp(self, path: Path, snapshot: dict) -> None:
        """Rewrite a snapshot, its self-hash, and its pointer, as the most thorough tamper would.
        Leaves only the content rule under test to refuse the launch."""
        snapshot["snapshot_id"] = snapshot_identity(snapshot)
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["prepared_stage"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        state["prepared_stage"]["snapshot_id"] = snapshot["snapshot_id"]
        state_path.write_text(json.dumps(state), encoding="utf-8")

    def assert_launch_refused(self, fragment: str, pass_num: int = 1) -> None:
        proc = self.run_ctl(
            "launch", "--run-dir", str(self.run_dir),
            "--role", "implement", "--pass", str(pass_num), "--anchor", "surface:5",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(fragment, proc.stderr)
        self.assertEqual(self.cmux_calls(), [])


class Workspace(PaneCtlCase):
    def test_prints_pinned_workspace(self):
        proc = self.run_ctl("workspace", "--run-dir", str(self.run_dir))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "WS-UUID")

    def test_missing_state_fails(self):
        proc = self.run_ctl("workspace", "--run-dir", str(self.run_dir / "nope"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("state.json", proc.stderr)

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

    def test_global_flags_stay_before_command_word(self):
        proc = self.run_ctl(
            "cmux", "--run-dir", str(self.run_dir), "--", "--json", "list-panes"
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.cmux_calls(), [["--json", "list-panes", "--workspace", "WS-UUID"]])

    def test_refuses_explicit_workspace(self):
        proc = self.run_ctl(
            "cmux", "--run-dir", str(self.run_dir), "--", "list-panes", "--workspace", "other"
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.cmux_calls(), [])

    def test_refuses_empty_command(self):
        proc = self.run_ctl("cmux", "--run-dir", str(self.run_dir), "--")
        self.assertNotEqual(proc.returncode, 0)


class Launch(PaneCtlCase):
    def test_splits_labels_and_records_events(self):
        self.prepare_snapshot("review")
        proc = self.run_ctl(
            "launch", "--run-dir", str(self.run_dir),
            "--role", "review", "--pass", "1", "--anchor", "surface:5",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["surface_id"], "SURF-UUID")
        self.assertEqual(out["label"], "Reviewer 1 - ISSUE-001")

        calls = self.cmux_calls()
        self.assertEqual(len(calls), 2)
        split, rename = calls
        self.assertIn("new-split", split)
        self.assertIn("right", split)
        for expected in ("--workspace", "WS-UUID", "--surface", "surface:5", "--focus", "false"):
            self.assertIn(expected, split)
        # Stable UUIDs, not positional refs: refs shift when panes close.
        self.assertEqual(rename[:1], ["rename-tab"])
        self.assertIn("SURF-UUID", rename)
        self.assertIn("Reviewer 1 - ISSUE-001", rename)

        types = [event["type"] for event in self.events()]
        self.assertEqual(types, ["pane.launched", "pane.labeled"])
        launched = self.events()[0]["data"]
        self.assertEqual(launched["surface_id"], "SURF-UUID")
        self.assertEqual(launched["role"], "review")

    def test_unknown_role_is_usage_error(self):
        proc = self.run_ctl(
            "launch", "--run-dir", str(self.run_dir),
            "--role", "griller", "--pass", "1", "--anchor", "surface:5",
        )
        self.assertEqual(proc.returncode, 2)

    def test_missing_snapshot_fails_before_cmux_creates_a_pane(self):
        self.assert_launch_refused("no prepared stage snapshot")

    def test_tampered_snapshot_fails_before_cmux_creates_a_pane(self):
        path = self.prepare_snapshot("implement")
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        self.assert_launch_refused("hash mismatch")

    def test_stale_stage_mismatch_fails_before_cmux_creates_a_pane(self):
        self.prepare_snapshot("implement")
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_stage"] = "simplify"
        state_path.write_text(json.dumps(state), encoding="utf-8")

        self.assert_launch_refused("stale")

    def test_pass_mismatch_fails_before_cmux_creates_a_pane(self):
        self.prepare_snapshot("implement", pass_num=1)

        self.assert_launch_refused("mismatch", pass_num=2)

    def test_snapshot_rewritten_to_launch_the_audited_realpath_is_refused(self):
        path = self.prepare_snapshot("implement")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["selected_worker"]["argv"][0] = snapshot["selected_worker"]["resolved_executable"]
        self.restamp(path, snapshot)

        self.assert_launch_refused("does not match its argument vector")

    def test_snapshot_with_an_unusable_program_name_is_refused(self):
        path = self.prepare_snapshot("implement")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["selected_worker"]["argv"][0] = "-c"
        snapshot["selected_worker"]["requested_executable"] = "-c"
        self.restamp(path, snapshot)

        self.assert_launch_refused("invalid program name")

    def test_snapshot_edited_without_restamping_its_identity_is_refused(self):
        path = self.prepare_snapshot("implement")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["selected_worker"]["detected_version"] = "0.0-tampered"
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["prepared_stage"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        state_path.write_text(json.dumps(state), encoding="utf-8")

        self.assert_launch_refused("snapshot identity")

    def test_snapshot_rewritten_to_widen_the_codex_sandbox_is_refused(self):
        path = self.prepare_snapshot("implement")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["selected_worker"]["argv"][1:3] = ["-s", "danger-full-access"]
        self.restamp(path, snapshot)

        self.assert_launch_refused("violates adapter policy")

    def test_snapshot_without_an_executable_audit_record_is_refused(self):
        path = self.prepare_snapshot("implement")
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        del snapshot["selected_worker"]["detected_version"]
        self.restamp(path, snapshot)

        self.assert_launch_refused("audit record")


class StartAgent(PaneCtlCase):
    def test_sends_marked_launch_command(self):
        self.prepare_snapshot("implement")
        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--role", "implement", "--pass", "1",
            "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        verbs = [call[0] for call in self.cmux_calls()]
        self.assertEqual(verbs, ["send", "send-key", "read-screen"])
        command = self.cmux_calls()[0][-1]
        # The marker is what keeps the worker pane out of the human's notification centre.
        self.assertTrue(command.startswith("CMUX_AGENT_MANAGED_SUBAGENT=1 codex "), command)
        self.assertIn("network_access=true", command)

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.launch_sent"])
        self.assertEqual(events[0]["data"]["command"], command)

    def test_claude_role_gets_the_marker_too(self):
        self.prepare_snapshot("review")
        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--role", "review", "--pass", "1",
            "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self.cmux_calls()[0][-1],
            "CMUX_AGENT_MANAGED_SUBAGENT=1 claude --model opus --effort xhigh",
        )

    def test_argument_vector_is_shell_quoted_without_losing_boundaries(self):
        # The policy argv carries JSON quoting the shell would otherwise eat.
        path = self.prepare_snapshot("implement")
        argv = json.loads(path.read_text(encoding="utf-8"))["selected_worker"]["argv"]

        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--role", "implement", "--pass", "1",
            "--settle-seconds", "0",
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        command = self.cmux_calls()[0][-1]
        self.assertIn('sandbox_workspace_write.writable_roots=["~/.ddev"]', argv)
        self.assertEqual(shlex.split(command), ["CMUX_AGENT_MANAGED_SUBAGENT=1", *argv])

    def test_failed_snapshot_refuses_start_without_any_cmux_call(self):
        self.prepare_snapshot("implement", status="failed")

        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--role", "implement", "--pass", "1",
            "--settle-seconds", "0",
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("snapshot status", proc.stderr)
        self.assertEqual(self.cmux_calls(), [])


class Deliver(PaneCtlCase):
    FOLLOW_UP = "re-emit the report per the Worker Report Contract; fix the format, not the substance"

    def test_send_enter_readscreen_in_order(self):
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--text", self.FOLLOW_UP,
            "--role", "review", "--pass", "1", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PANE SCREEN", proc.stdout)

        verbs = [call[0] for call in self.cmux_calls()]
        self.assertEqual(verbs, ["send", "send-key", "read-screen"])
        send, send_key, read_screen = self.cmux_calls()
        self.assertEqual(send[-1], self.FOLLOW_UP)
        self.assertEqual(send_key[-1], "enter")
        for call in (send, send_key, read_screen):
            self.assertIn("WS-UUID", call)
            self.assertIn("SURF-UUID", call)

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.prompt_sent"])
        self.assertEqual(events[0]["data"]["text"], self.FOLLOW_UP)
        self.assertIsNone(events[0]["data"]["prompt_path"])

    def test_prompt_mode_sends_the_skills_own_task_framing(self):
        prompt_path = "prompts/review-1.md"
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--prompt", prompt_path,
            "--role", "review", "--pass", "1", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        expected = delivery_text(prompt_path)
        self.assertEqual(self.cmux_calls()[0][-1], expected)
        events = self.events()
        self.assertEqual(events[0]["data"]["text"], expected)
        self.assertEqual(events[0]["data"]["prompt_path"], prompt_path)

    def test_delivery_text_frames_the_prompt_as_work_not_reading(self):
        text = delivery_text("prompts/simplify-1.md")
        self.assertIn("prompts/simplify-1.md", text)
        self.assertIn("Execute it now", text)
        self.assertNotIn("report back", text)

    def test_text_and_prompt_are_mutually_exclusive(self):
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir), "--surface", "SURF-UUID",
            "--prompt", "prompts/review-1.md", "--text", "hi", "--settle-seconds", "0",
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
            "--surface", "SURF-UUID", "--role", "test", "--pass", "1",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.cmux_calls(), [
            ["close-surface", "--workspace", "WS-UUID", "--surface", "SURF-UUID"],
        ])
        events = self.events()
        self.assertEqual([event["type"] for event in events], ["pane.closed"])
        self.assertEqual(events[0]["data"]["role"], "test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
