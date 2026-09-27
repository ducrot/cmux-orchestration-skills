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

from orchestrator_lib import delivery_text
from launch_wave import (
    SUBAGENT_MARKER_ENV,
    SUBAGENT_MARKER_VALUE,
    git_root,
    lane_argv,
    snapshot_identity,
)

SCRIPT = str(Path(__file__).parent / "pane_ctl.py")

from test_support import FAKE_CMUX


class PaneCtlCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name).resolve() / "run"
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
                "preflight": {"status": "passed", "trust": {"status": "passed", "repository": "/test/repo", "source": "/test/trust"}},
                "entitlement": {"status": "unverified"},
                "environment": {SUBAGENT_MARKER_ENV: SUBAGENT_MARKER_VALUE},
            })
            entry["argv"] = lane_argv(lane, entry)
        wave = {
            "repository": "/test/repo",
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
                "workflow": "grilling", "layout_version": 1, "max_rounds": 4,
                "run_id": "test-run", "workspace_id": "WS-UUID",
                "slug": "checkout-refactor", "launch_wave": pointer,
            }),
            encoding="utf-8",
        )
        from render_prompt import render_session
        (self.run_dir / "task.md").write_text("Research task")
        (self.run_dir / "prompts").mkdir()
        for lane in profiles:
            (self.run_dir / "prompts" / f"session-{lane}.md").write_text(render_session(
                lane, {"run_id": "test-run", "max_rounds": 4, "task_file": "task.md"}, self.run_dir))
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
            json.dumps({"workflow": "grilling", "layout_version": 1, "max_rounds": 4, "workspace_id": None}), encoding="utf-8"
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
        self.assertEqual(verbs, ["send", "send-key"])
        command = self.cmux_calls()[0][-1]
        # The marker is what keeps the lane pane out of the human's notification centre.
        self.assertTrue(command.startswith("CMUX_AGENT_MANAGED_SUBAGENT=1 codex "), command)
        self.assertIn("approvals_reviewer=auto_review", command)
        self.assertIn("--model gpt-6-astra", command)

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.starting", "worker.launch_sent"])
        self.assertEqual(events[0]["data"]["command"], command)

    def test_prompt_attached_as_single_last_argument_and_launch_fields(self):
        for lane in ("codebase", "codebase2", "docs", "web"):
            proc = self.run_ctl("start-agent", "--run-dir", str(self.run_dir),
                                "--surface", "SURF-UUID", "--lane", lane)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(len(proc.stdout.splitlines()), 1)
            starting, launch = self.events()[-2:]
            self.assertEqual(starting["data"], launch["data"])
            data = launch["data"]
            wave = json.loads((self.run_dir / "launch-waves/wave.json").read_text())
            expected = wave["resolved_profiles"][lane]["argv"]
            self.assertEqual(shlex.split(data["command"]),
                             ["CMUX_AGENT_MANAGED_SUBAGENT=1", *expected, data["text"]])
            self.assertEqual(data["text"], delivery_text("session", data["prompt_path_relative"]))
            self.assertEqual((git_root(Path.cwd()) / data["prompt_path_relative"]).resolve(), Path(data["prompt_path"]))
            self.assertGreater(data["start_time_ns"], 0)
            for key in ("launch_id", "surface_id", "prompt_path", "marker_path"):
                self.assertEqual(result[key], data[key])
            self.assertIn("--session", result["next"])
            self.assertEqual(Path(data["marker_path"]), self.run_dir / "artifacts" / f"session-{lane}" / "started")
        self.assertEqual([call[0] for call in self.cmux_calls()], ["send", "send-key"] * 4)

    def test_missing_session_prompt_refuses_before_cmux(self):
        (self.run_dir / "prompts/session-web.md").unlink()
        proc = self.run_ctl("start-agent", "--run-dir", str(self.run_dir), "--surface", "SURF-UUID", "--lane", "web")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Missing session prompt", proc.stderr)
        self.assertEqual(self.cmux_calls(), [])
        self.assertEqual(self.events(), [])

    def test_four_lane_session_cli_flow(self):
        scripts = Path(__file__).parent
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text())
        state["task_file"] = "task.md"
        state_path.write_text(json.dumps(state))
        launch_ids = {}
        for lane in ("codebase", "codebase2", "docs", "web"):
            rendered = subprocess.run([sys.executable, str(scripts / "render_prompt.py"), "session",
                "--run-dir", str(self.run_dir), "--lane", lane], capture_output=True, text=True)
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            started = self.run_ctl("start-agent", "--run-dir", str(self.run_dir),
                                  "--lane", lane, "--surface", f"UUID-{lane}")
            self.assertEqual(started.returncode, 0, started.stderr)
            data = json.loads(started.stdout)
            launch_ids[lane] = data["launch_id"]
            # Simulate each worker following the actual rendered First Step.
            prompt = Path(data["prompt_path"]).read_text()
            marker = Path(prompt.split("create or overwrite `", 1)[1].split("`", 1)[0])
            self.assertEqual(str(marker), data["marker_path"])
            marker.parent.mkdir(parents=True)
            marker.write_text("adopted")
        args = [sys.executable, str(scripts / "await_reports.py"), "--run-dir", str(self.run_dir), "--session"]
        for lane in launch_ids:
            args += ["--lane-surface", f"{lane}=UUID-{lane}"]
        watched = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(watched.returncode, 0, watched.stderr)
        self.assertIn("not_started=none", watched.stdout)
        confirmed = [e["data"] for e in self.events() if e["type"] == "worker.started"]
        self.assertEqual({e["lane"]: e["launch_id"] for e in confirmed}, launch_ids)
        self.assertEqual([call[0] for call in self.cmux_calls()], ["send", "send-key"] * 4)

    def test_claude_lane_gets_the_marker_too(self):
        proc = self.run_ctl(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self.cmux_calls()[0][-1],
            "CMUX_AGENT_MANAGED_SUBAGENT=1 claude --model sonnet --effort medium "
            "--permission-mode auto " + shlex.quote(delivery_text("session", os.path.relpath(
                self.run_dir / "prompts" / "session-web.md", git_root(Path.cwd())))),
        )


class Deliver(PaneCtlCase):
    def ready(self, worker):
        selector = ["--role", worker, "--pass", "1"] if hasattr(self, "prepare_snapshot") else ["--lane", worker]
        if hasattr(self, "prepare_snapshot"):
            self.prepare_snapshot(worker)
        common = ["--run-dir", str(self.run_dir), "--surface", "SURF-UUID", *selector]
        started = self.run_ctl("start-agent", *common, "--settle-seconds", "0")
        self.assertEqual(started.returncode, 0, started.stderr)
        observed = self.run_ctl("observe", *common)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        observation = json.loads(observed.stdout)["observation_id"]
        assessed = self.run_ctl("assess", *common, "--observation", observation,
                                "--state", "ready", "--reason", "fixture agent is idle")
        self.assertEqual(assessed.returncode, 0, assessed.stderr)
        self.log.unlink()
        self.delivery_event_offset = len(super().events())

    def events(self):
        return super().events()[getattr(self, "delivery_event_offset", 0):]

    FOLLOW_UP = "re-emit the report per the Research Report Contract; fix the format, not the substance"

    def test_send_enter_readscreen_in_order(self):
        self.ready("web")
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--text", self.FOLLOW_UP,
            "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("PANE SCREEN", proc.stdout)

        verbs = [call[0] for call in self.cmux_calls()]
        self.assertEqual(verbs, ["read-screen", "send", "send-key", "read-screen"])
        _, send, send_key, _ = self.cmux_calls()
        self.assertEqual(send[-1], self.FOLLOW_UP)
        self.assertEqual(send_key[-1], "enter")

        events = self.events()
        self.assertEqual([event["type"] for event in events], ["worker.readiness_consumed", "worker.delivery_attempted", "worker.prompt_sent"])
        self.assertEqual(events[-1]["data"]["lane"], "web")
        self.assertIsNone(events[-1]["data"]["prompt_path"])
        self.assertIsNone(events[-1]["data"]["kind"])

    def test_round_prompt_sends_the_skills_own_task_framing(self):
        self.ready("web")
        prompt_path = "prompts/round-1-web.md"
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--prompt", prompt_path,
            "--kind", "round", "--lane", "web", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        expected = delivery_text("round", prompt_path)
        self.assertEqual(self.cmux_calls()[1][-1], expected)
        events = self.events()
        self.assertEqual(events[-1]["data"]["text"], expected)
        self.assertEqual(events[-1]["data"]["prompt_path"], prompt_path)
        self.assertEqual(events[-1]["data"]["kind"], "round")

    def test_round_is_the_default_kind(self):
        self.ready("docs")
        proc = self.run_ctl(
            "deliver", "--run-dir", str(self.run_dir),
            "--surface", "SURF-UUID", "--prompt", "prompts/round-1-docs.md",
            "--lane", "docs", "--settle-seconds", "0",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.events()[-1]["data"]["kind"], "round")

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
