#!/usr/bin/env python3
"""Readiness regressions, including each installed skill's real pane CLI."""
import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker_readiness import Gate, ReadinessError, begin_start, read_events, readiness_status, screen_fingerprint, screen_hash


class Readiness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = argparse.Namespace(run_dir=str(self.root), surface="UUID-1", lane="codebase2",
                                       command="observe", reason="expected agent idle", state="ready", key="enter")
        self.screen = "OpenAI Codex — project /test — idle composer"
        self.calls = []
        self.gate = Gate(self.args, "WS-1", self.call, self.record)
        self.record(self.root, "worker.launch_sent", "", {"lane": "codebase2", "surface_id": "UUID-1", "launch_id": "launch-1"})

    def record(self, root, kind, message, data):
        with (root / "events.jsonl").open("a") as handle:
            handle.write(json.dumps({"type": kind, "message": message, "data": data}) + "\n")

    def call(self, args, argv):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=self.screen, stderr="")

    def observe(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.gate.observe()
        data = json.loads(output.getvalue())
        self.args.observation = data["observation_id"]
        return data

    def assess(self, state="ready"):
        self.args.state = state
        with contextlib.redirect_stdout(io.StringIO()):
            self.gate.assess()

    def ready(self):
        self.observe()
        self.assess()

    def test_dialog_loading_login_shell_and_unknown_block_without_ready(self):
        for screen, state in [
            ("Do you trust the contents of this directory?", "prompt"),
            ("Claude Code: trust this folder?", "prompt"),
            ("OpenAI Codex model: loading > Ask anything", "loading"),
            ("Claude Code: sign in to continue", "prompt"),
            ("command not found: codex; shell $", "failed"),
            ("unexpected startup screen", "unknown"),
        ]:
            with self.subTest(screen=screen):
                self.screen = screen
                self.observe()
                self.assess(state)
                with self.assertRaises(ReadinessError):
                    self.gate.consume()
        self.assertTrue(all(call[0] == "read-screen" for call in self.calls))

    def test_slow_start_becomes_ready_only_after_new_observation(self):
        self.screen = "loading"
        self.observe()
        self.assess("loading")
        self.screen = "Claude Code — project /test — idle composer"
        self.ready()
        self.gate.consume()
        with self.assertRaises(ReadinessError):
            self.gate.consume()

    def test_delivery_rechecks_screen_and_consumes_once(self):
        self.ready()
        self.screen = "Update available: choose a version"
        with self.assertRaisesRegex(ReadinessError, "screen changed"):
            self.gate.consume()
        self.assertNotEqual(readiness_status(read_events(self.root), {"lane": "codebase2"}, "UUID-1"), "ready")

    def test_expired_observation_is_not_ready(self):
        with patch("worker_readiness.time.time", return_value=1000):
            self.ready()
        with patch("worker_readiness.time.time", return_value=1061):
            with self.assertRaises(ReadinessError):
                self.gate.consume()

    def test_new_observation_invalidates_old_ready_and_old_token(self):
        self.ready()
        old = self.args.observation
        self.observe()
        with self.assertRaises(ReadinessError):
            self.gate.consume()
        self.args.observation = old
        with self.assertRaises(ReadinessError):
            self.assess()

    def test_start_attempt_close_and_replacement_invalidate_ready(self):
        for kind, data in [
            ("worker.starting", {"lane": "codebase2", "surface_id": "UUID-1"}),
            ("worker.launch_sent", {"lane": "codebase2", "surface_id": "UUID-1", "launch_id": "new"}),
            ("pane.closed", {"lane": "codebase2", "surface_id": "UUID-1"}),
            ("pane.launched", {"lane": "codebase2", "surface_id": "UUID-2"}),
            ("worker.launch_sent", {"lane": "web", "surface_id": "UUID-1", "launch_id": "other"}),
        ]:
            with self.subTest(kind=kind, data=data):
                baseline = (self.root / "events.jsonl").read_text()
                self.ready()
                self.record(self.root, kind, "", data)
                with self.assertRaises(ReadinessError):
                    self.gate.consume()
                (self.root / "events.jsonl").write_text(baseline)

    def test_dialog_response_requires_prompt_assessment_and_reinspection(self):
        self.screen = "Do you trust /test? 1. Yes 2. No"
        self.observe()
        with self.assertRaises(ReadinessError):
            self.gate.respond()
        self.assess("prompt")
        self.args.reason = "confirm authorized /test directory trust"
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.gate.respond()
        new = json.loads(output.getvalue())
        self.assertNotEqual(new["observation_id"], self.args.observation)
        self.assertEqual([c for c in self.calls if c[0] == "send-key"],
                         [["send-key", "--workspace", "WS-1", "--surface", "UUID-1", "enter"]])
        with self.assertRaises(ReadinessError):
            self.gate.consume()
        with self.assertRaises(ReadinessError):
            self.gate.respond()

    def test_failed_response_still_invalidates_ready(self):
        self.observe()
        self.assess("prompt")
        def fail(args, argv):
            if argv[0] == "send-key":
                raise OSError("lost terminal")
            return self.call(args, argv)
        self.gate.call = fail
        with self.assertRaises(OSError):
            self.gate.respond()
        with self.assertRaises(ReadinessError):
            self.gate.consume()

    def test_screens_not_persisted_and_calls_are_scoped(self):
        self.ready()
        self.assertNotIn(self.screen, (self.root / "events.jsonl").read_text())
        for call in self.calls:
            self.assertIn("WS-1", call)
            self.assertIn("UUID-1", call)

    def test_legacy_launch_needs_observation_and_assessment(self):
        (self.root / "events.jsonl").unlink()
        self.record(self.root, "worker.launch_sent", "", {"lane": "codebase2", "surface_id": "UUID-1"})
        with self.assertRaises(ReadinessError):
            self.gate.consume()
        self.ready()
        self.gate.consume()

    def test_codex_decorative_particles_preserve_semantic_fingerprint(self):
        frames = [
            "OpenAI Codex (v0.154.0)\nmodel: gpt-6-astra\ndirectory: /test\nWarning: unchanged\n \n⠁ ⠈ ⢀ ⠐\n› Ask Codex to do anything⡀ ⠂\n ⠄ ⠠ ⡀\nContext 0% used\n",
            "OpenAI Codex (v0.154.0)\nmodel: gpt-6-astra\ndirectory: /test\nWarning: unchanged\n \n⠐ ⡀ ⠂ ⠁\n›⠁Ask Codex to do anything ⢀ ⠄\n ⠁ ⠈ ⠂\nContext 0% used\n",
        ]
        self.assertNotEqual(screen_hash(frames[0]), screen_hash(frames[1]))
        self.assertEqual(screen_fingerprint(frames[0]), screen_fingerprint(frames[1]))
        self.screen = frames[0]
        self.observe()
        self.screen = frames[1]
        self.assess("ready")
        self.screen = frames[0]
        self.gate.consume()
        with self.assertRaises(ReadinessError):
            self.gate.consume()

    def test_particle_filter_preserves_dialogs_warnings_loading_paths_and_input(self):
        original = "OpenAI Codex (v0.154.0)\nmodel: loaded\ndirectory: /test\nWarning: old\n⠁  ⠂\n› Ask Codex to do anything ⠄\n⠈ ⠐\nContext 0% used\n"
        for changed in [original.replace("loaded", "loading"), original.replace("/test", "/other"),
                        original.replace("old", "new"), original + "Do you trust this directory?\n",
                        original.replace("Ask Codex to do anything", "run a command"),
                        original.replace("Ask Codex to do anything", "Ask Codex to do anything x"),
                        original.replace("Context 0%", "Context 1%")]:
            with self.subTest(changed=changed):
                self.assertNotEqual(screen_fingerprint(original), screen_fingerprint(changed))
                self.screen = original
                self.ready()
                self.screen = changed
                with self.assertRaises(ReadinessError):
                    self.gate.consume()
        # Braille in actual content or in another application is never stripped globally.
        self.assertNotEqual(screen_fingerprint(original + "Braille: ⠁"), screen_fingerprint(original + "Braille: ⠂"))
        self.assertNotEqual(screen_fingerprint("Claude Code\n⠁\n› Ask Codex to do anything"),
                            screen_fingerprint("Claude Code\n⠂\n› Ask Codex to do anything"))

    def test_non_ready_assessment_can_describe_a_changing_startup_frame(self):
        for state in ("loading", "unknown", "prompt", "failed"):
            self.screen = "frame 1: startup spinner"
            self.observe()
            self.screen = "frame 2: changed startup spinner"
            self.assess(state)
            with self.assertRaises(ReadinessError):
                self.gate.consume()
            if state == "prompt":
                with self.assertRaises(ReadinessError):
                    self.gate.respond()
        self.assertTrue(all(call[0] == "read-screen" for call in self.calls))

    def test_vendored_code_and_protocol_match(self):
        script = Path(__file__).resolve()
        for name in ("cmux-planning", "cmux-issue-chain", "cmux-grilling"):
            sibling = script.parents[2] / name
            if sibling.is_dir():
                for relative in ("scripts/worker_readiness.py", "scripts/test_worker_readiness.py", "references/worker-readiness.md"):
                    self.assertEqual((script.parents[1] / relative).read_bytes(), (sibling / relative).read_bytes())


class PaneIntegration(unittest.TestCase):
    def test_trust_dialog_cannot_receive_task_then_ready_can(self):
        skill = Path(__file__).resolve().parents[1].name
        if skill == "cmux-planning":
            import test_planning_flow as fixture
            case = fixture.PlanningFlow()
        else:
            import test_pane_ctl as fixture
            case = fixture.PaneCtlCase()
        case.setUp()
        self.addCleanup(case.tearDown)
        if skill == "cmux-planning":
            self.assertEqual(case.init_direct().returncode, 0)
            case.render_and_baseline("spec")
            common = ["--run-dir", str(case.run_dir), "--stage", "spec", "--pass", "1"]
            def ctl(verb, *tail):
                return case.cli(fixture.PANE, "--cmux-cmd", str(case.cmux), verb, *common, *tail)
            self.assertEqual(ctl("launch", "--anchor", "CALLER").returncode, 0)
            common += ["--surface", "SURF-1"]
            fake = case.cmux
            log = case.cmux_log
            screen_text = "worker screen"
            prompt = str(case.run_dir / "prompts/spec-1.md")
        else:
            if skill == "cmux-issue-chain":
                case.prepare_snapshot("implement")
                identity = ["--role", "implement", "--pass", "1"]
            else:
                identity = ["--lane", "codebase2"]
            common = ["--run-dir", str(case.run_dir), "--surface", "SURF-UUID", *identity]
            def ctl(verb, *tail):
                return case.run_ctl(verb, *common, *tail)
            fake = Path(case._tmp.name) / "fake_cmux.py"
            log = case.log
            screen_text = "PANE SCREEN"
            prompt = "/tmp/task.md"
        # Exercise actual CLI subprocesses, with no live harness or provider requests.
        fake.write_text(fake.read_text().replace(screen_text, "Do you trust the contents of this directory?"))
        self.assertEqual(ctl("start-agent", "--settle-seconds", "0").returncode, 0)
        before = log.read_text()
        blocked = ctl("deliver", "--prompt", prompt, "--settle-seconds", "0")
        self.assertNotEqual(blocked.returncode, 0, blocked.stdout)
        self.assertEqual(log.read_text(), before)
        observed = json.loads(ctl("observe").stdout)
        self.assertIn("Do you trust", observed["screen"])
        assessed = ctl("assess", "--observation", observed["observation_id"], "--state", "prompt", "--reason", "trust dialog")
        self.assertEqual(assessed.returncode, 0, assessed.stderr)
        self.assertNotEqual(ctl("deliver", "--prompt", prompt, "--settle-seconds", "0").returncode, 0)
        if skill == "cmux-planning":
            status = json.loads(case.cli(fixture.STATE, "status", "--run-dir", str(case.run_dir), "--cmux-cmd", str(case.cmux)).stdout)
            self.assertEqual(status["pane"]["startup_state"], "prompt")
            self.assertIn("observe", status["recommended_next"]["command"])
        fake.write_text(fake.read_text().replace("Do you trust the contents of this directory?", "Expected agent fully loaded; idle empty composer"))
        observation = json.loads(ctl("observe").stdout)["observation_id"]
        assessed = ctl("assess", "--observation", observation, "--state", "ready", "--reason", "correct project; agent idle")
        self.assertEqual(assessed.returncode, 0, assessed.stderr)
        delivered = ctl("deliver", "--prompt", prompt, "--settle-seconds", "0")
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        self.assertNotEqual(ctl("deliver", "--prompt", prompt, "--settle-seconds", "0").returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
