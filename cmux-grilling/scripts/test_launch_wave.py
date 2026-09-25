#!/usr/bin/env python3
"""Prepared grilling launch-wave regression tests. Run: python3 scripts/test_launch_wave.py"""

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


SCRIPT_DIR = Path(__file__).resolve().parent
AGENTS_CONFIG = SCRIPT_DIR / "agents_config.py"
RUN_STATE = SCRIPT_DIR / "run_state.py"
PANE_CTL = SCRIPT_DIR / "pane_ctl.py"

PROBE_SENTINEL = "CMUX_PROFILE_PROBE_OK_V1"

FAKE_HARNESS = r'''#!/usr/bin/env python3
import json, os, sys, time
with open(os.environ["FAKE_HARNESS_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"program": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}) + "\n")
args = sys.argv[1:]
mode = os.environ.get("FAKE_HARNESS_FAILURE", "")
program = os.path.basename(sys.argv[0])
if args == ["--version"]:
    if mode == "version" and program == "codex":
        raise SystemExit(9)
    print(program + " 99.1-test")
elif args == ["--help"]:
    if mode == "help" and program == "codex":
        print("--model login")
    else:
        print("--model --sandbox --config --ask-for-approval --effort login auth")
        print("--safe-mode --print --no-session-persistence --permission-mode --tools")
elif args == ["exec", "--help"]:
    if mode == "probe-help" and program == "codex":
        print("--model --config")
    else:
        print("--ephemeral --skip-git-repo-check --sandbox --model --config")
elif args in (["login", "--help"], ["auth", "--help"]):
    print("status")
elif args in (["login", "status"], ["auth", "status"]):
    if mode == "auth" and program == "codex":
        raise SystemExit(7)
    print("authenticated test account token=must-not-be-audited")
elif "CMUX_PROFILE_PROBE_OK_V1" in " ".join(args):
    safe = (
        (program == "codex" and "exec" in args and "read-only" in args
            and 'approval_policy="never"' in args and "--ephemeral" in args)
        or (program == "claude" and "--safe-mode" in args and "--print" in args
            and "--no-session-persistence" in args and "--permission-mode" in args
            and "plan" in args and "--tools" in args and args[args.index("--tools") + 1] == "")
    )
    if not safe and os.environ.get("FAKE_HARNESS_WRITE_MARKER"):
        open(os.environ["FAKE_HARNESS_WRITE_MARKER"], "w", encoding="utf-8").write("unsafe")
    if mode == "provider":
        print("provider diagnostic token=must-not-be-audited", file=sys.stderr)
        raise SystemExit(12)
    if mode == "timeout":
        time.sleep(2)
    if mode == "wrong-sentinel":
        print("WRONG")
    elif mode == "malformed":
        print("CMUX_PROFILE_PROBE_OK_V1 extra")
    else:
        print("CMUX_PROFILE_PROBE_OK_V1")
else:
    raise SystemExit("unexpected fake harness invocation: " + repr(args))
'''

from test_support import FAKE_CMUX


def file_contents(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class PreparedLaunchWaveCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        for name in ("codex", "claude"):
            path = self.bin_dir / name
            path.write_text(FAKE_HARNESS, encoding="utf-8")
            path.chmod(0o755)
        self.cmux = self.root / "cmux"
        self.cmux.write_text(FAKE_CMUX, encoding="utf-8")
        self.cmux.chmod(0o755)
        self.harness_log = self.root / "harness.jsonl"
        self.cmux_log = self.root / "cmux.jsonl"
        self.write_marker = self.root / "probe-write"
        self.runs_root = self.repo / ".scratch" / "orchestrator" / "runs"
        self.config_path = self.repo / ".scratch" / "orchestrator" / "agents.json"
        initialized = self.initialize_config(self.config_path)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **changes: str) -> dict[str, str]:
        return {
            **os.environ,
            "PATH": str(self.bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "FAKE_HARNESS_LOG": str(self.harness_log),
            "FAKE_CMUX_LOG": str(self.cmux_log),
            "FAKE_HARNESS_WRITE_MARKER": str(self.write_marker),
            **changes,
        }

    def run_state(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RUN_STATE), *args],
            cwd=self.repo,
            env=env or self.env(),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def initialize_config(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(AGENTS_CONFIG), "init", "--config", str(path)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def init_for(
        self,
        run_id: str,
        *extra: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_state(
            "init",
            "--task", "Grill this prepared plan",
            "--run-id", run_id,
            "--runs-root", str(self.runs_root),
            "--workspace-id", "WORKSPACE",
            *extra,
            env=env,
        )

    def pane(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PANE_CTL), "--cmux-cmd", str(self.cmux), *args],
            cwd=self.repo,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def read_state(self, run_id: str) -> dict:
        return json.loads((self.run_dir(run_id) / "state.json").read_text(encoding="utf-8"))

    def read_wave(self, run_id: str) -> dict:
        state = self.read_state(run_id)
        return json.loads(
            (self.run_dir(run_id) / state["launch_wave"]["path"]).read_text(encoding="utf-8")
        )

    def cmux_calls(self) -> list[list[str]]:
        if not self.cmux_log.is_file():
            return []
        return [json.loads(line) for line in self.cmux_log.read_text(encoding="utf-8").splitlines()]

    def test_version_one_config_requires_explicit_migration_before_grilling_preparation(self):
        legacy = json.loads(self.config_path.read_text(encoding="utf-8"))
        legacy["schema_version"] = 1
        del legacy["workflows"]["planning"]
        legacy["workflows"]["grilling"]["docs"] = "codex-astra-medium"
        legacy_bytes = json.dumps(legacy).encode("utf-8")
        self.config_path.write_bytes(legacy_bytes)

        proc = self.init_for("migrated-v1")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.config_path.read_bytes(), legacy_bytes)
        self.assertIn("Read-only schema-v1 migration preview", proc.stderr)
        self.assertIn("Acceptance command:", proc.stderr)
        self.assertFalse((self.run_dir("migrated-v1") / "state.json").exists())
        self.assertFalse((self.run_dir("migrated-v1") / "launch-waves").exists())

        accepted = subprocess.run(
            [sys.executable, str(AGENTS_CONFIG), "migrate", "--accept", "--config", str(self.config_path)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        prepared = self.init_for("migrated-v1")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        wave = self.read_wave("migrated-v1")
        self.assertEqual(wave["resolved_profiles"]["docs"]["profile"], "codex-astra-medium")

    def test_init_creates_drafts_and_reinit_restores_directory(self):
        initialized = self.init_for("drafts")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        draft_dir = self.run_dir("drafts") / "drafts"
        self.assertTrue(draft_dir.is_dir())
        draft_dir.rmdir()
        reinitialized = self.init_for("drafts")
        self.assertEqual(reinitialized.returncode, 0, reinitialized.stderr)
        self.assertTrue(draft_dir.is_dir())

    def test_round_cli_prompt_rendering_and_parser_validation(self):
        initialized = self.init_for("draft-flow")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        run_dir = self.run_dir("draft-flow")

        def render(*args):
            return subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "render_prompt.py"), *args],
                cwd=self.repo, capture_output=True, text=True, timeout=30,
            )

        session = render("session", "--run-dir", str(run_dir), "--lane", "codebase2")
        self.assertEqual(session.returncode, 0, session.stderr)
        args = ("round", "--run-dir", str(run_dir), "--lane", "codebase2",
                "--round", "1", "--question", "What exists?")
        report = run_dir / "reports" / "round-1-codebase2.md"
        prompt_path = run_dir / "prompts" / "round-1-codebase2.md"
        state_before = (run_dir / "state.json").read_bytes()
        for invalid in (report, self.root / "outside.md", run_dir / "state.json",
                        run_dir / "reports" / "round-1-docs.md"):
            rejected = render(*args, "--draft-path", str(invalid))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(prompt_path.exists())
        self.assertEqual((run_dir / "state.json").read_bytes(), state_before)

        for override in (None, run_dir / "drafts" / "custom draft.md"):
            with self.subTest(override=override):
                rendered = render(*args, *(('--draft-path', str(override)) if override else ()))
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                draft = override or run_dir / "drafts" / "round-1-codebase2.md"
                prompt = prompt_path.read_text(encoding="utf-8")
                command = shlex.split(prompt.split("```bash\n", 1)[1].splitlines()[0])
                self.assertEqual(command[-3:], [str(draft), "--questions", "1"])
                draft.write_text(
                    "## Q1\n### Result\nNO ANSWER\n\n### Answer\nThe fixture has no product code.\n"
                    "\n### Sources\n- None\n\n### Method\n- Read the fixture task file.\n"
                    "\n### Blockers\n- None\n\n### Plan Drift\n- None\n",
                    encoding="utf-8",
                )
                validated = subprocess.run(
                    command, cwd=self.repo, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
                self.assertIn("gate=advance", validated.stdout)

    def test_default_identity_and_slug_override(self):
        result = self.run_state("init", "--task", "Task: Static teaser website for cmux Orchestration skills", "--no-workspace")
        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.repo / result.stdout.strip()
        self.assertRegex(run_dir.name, r"^grill-task-static-teaser-website-for-\d{4}-\d{2}-\d{2}-\d{4}$")
        state = json.loads((run_dir / "state.json").read_text())
        self.assertEqual(state["slug"], "task-static-teaser-website-for")
        self.assertLessEqual(len(state["slug"]), 30)
        self.assertEqual(state["workflow"], "grilling")
        self.assertEqual(state["layout_version"], 1)
        self.assertEqual(state["deliverables"], {})
        override = self.init_for("custom", "--slug", "chosen-slug")
        self.assertEqual(override.returncode, 0, override.stderr)
        self.assertEqual(self.read_state("custom")["slug"], "chosen-slug")
        for slug in ("", "Upper", "a--b", "../x", "x" * 31):
            invalid = self.init_for("invalid", "--slug", slug)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("--slug", invalid.stderr)
            self.assertFalse(self.run_dir("invalid").exists())

    def test_run_without_max_rounds_is_not_resumed(self):
        """Runs from before multi-question rounds carry max_questions and must be restarted."""
        self.assertEqual(self.init_for("old-budget").returncode, 0)
        run_dir = self.run_dir("old-budget")
        state = self.read_state("old-budget")
        self.assertEqual(state["max_rounds"], 4)
        self.assertNotIn("max_questions", state)
        del state["max_rounds"]
        state["max_questions"] = 10
        (run_dir / "state.json").write_text(json.dumps(state))
        result = self.run_state("event", "--run-dir", str(run_dir), "--type", "test", "--message", "test")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported legacy layout", result.stderr)

    def test_max_rounds_is_configurable_and_validated(self):
        self.assertEqual(self.init_for("rounds", "--max-rounds", "6").returncode, 0)
        self.assertEqual(self.read_state("rounds")["max_rounds"], 6)
        invalid = self.init_for("rounds-zero", "--max-rounds", "0")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("--max-rounds must be >= 1", invalid.stderr)

    def test_legacy_run_is_inspectable_but_cannot_continue_or_launch(self):
        self.assertEqual(self.init_for("legacy").returncode, 0)
        run_dir = self.run_dir("legacy")
        state = self.read_state("legacy")
        del state["workflow"]
        del state["layout_version"]
        (run_dir / "state.json").write_text(json.dumps(state))
        before = file_contents(run_dir)
        calls = [self.init_for("legacy"),
                 self.run_state("event", "--run-dir", str(run_dir), "--type", "test", "--message", "test"),
                 self.pane("launch", "--run-dir", str(run_dir), "--lane", "web", "--anchor", "ANCHOR")]
        for result in calls:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported legacy layout", result.stderr)
        inspected = self.run_state("status", "--run-dir", str(run_dir))
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertIn("unsupported legacy layout", inspected.stdout)
        self.assertEqual(before, file_contents(run_dir))
        self.assertFalse(self.cmux_log.exists())

    def test_init_uses_config_and_audits_all_four_lanes_in_one_wave(self):
        proc = self.init_for("wave")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        config_path = self.config_path
        self.assertTrue(config_path.is_file())
        state = self.read_state("wave")
        wave = self.read_wave("wave")
        self.assertEqual(state["configuration_source"], str(config_path.resolve()))
        self.assertEqual(wave["status"], "passed")
        self.assertEqual(wave["config"]["source"], str(config_path.resolve()))
        self.assertEqual(wave["config"]["sha256"], hashlib.sha256(config_path.read_bytes()).hexdigest())
        self.assertTrue(wave["resolved_at"])
        self.assertEqual(set(wave["resolved_profiles"]), {"codebase", "codebase2", "docs", "web"})

        lanes = wave["resolved_profiles"]
        self.assertEqual(
            {lane: (entry["harness"], entry["model"], entry["effort"]) for lane, entry in lanes.items()},
            {
                "codebase": ("claude-code", "opus", "high"),
                "codebase2": ("codex", "gpt-6-astra", "high"),
                "docs": ("codex", "gpt-5.6-luna", "medium"),
                "web": ("claude-code", "sonnet", "medium"),
            },
        )
        for lane, entry in lanes.items():
            with self.subTest(lane=lane):
                self.assertEqual(entry["preflight"]["status"], "passed")
                self.assertEqual(entry["entitlement"]["status"], "unverified")
                self.assertTrue(entry["requested_executable"])
                self.assertTrue(Path(entry["resolved_executable"]).is_absolute())
                self.assertTrue(entry["detected_version"])
                self.assertIsInstance(entry["argv"], list)
                self.assertEqual(entry["argv"][0], entry["requested_executable"])

        calls = [json.loads(line) for line in self.harness_log.read_text().splitlines()]
        self.assertEqual(sum(call["argv"] == ["--version"] for call in calls), 2)
        self.assertEqual(
            sum(call["argv"] in (["login", "status"], ["auth", "status"]) for call in calls),
            2,
        )
        audit = (self.run_dir("wave") / "events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("must-not-be-audited", json.dumps(wave))
        self.assertNotIn("must-not-be-audited", audit)
        self.assertNotIn("FAKE_HARNESS", audit)

    def test_exact_prepared_commands_launch_all_lanes_with_safe_quoting(self):
        initialized = self.init_for("commands")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        wave = self.read_wave("commands")

        for lane in ("codebase", "codebase2", "docs", "web"):
            run_dir = self.run_dir("commands")
            launched = self.pane(
                "launch", "--run-dir", str(run_dir), "--lane", lane, "--anchor", "anchor"
            )
            self.assertEqual(launched.returncode, 0, launched.stderr)
            started = self.pane(
                "start-agent", "--run-dir", str(run_dir), "--surface", f"surface-{lane}",
                "--lane", lane, "--settle-seconds", "0",
            )
            self.assertEqual(started.returncode, 0, started.stderr)

        sent = [call[-1] for call in self.cmux_calls() if call and call[0] == "send"]
        self.assertEqual(len(sent), 4)
        for lane, command in zip(("codebase", "codebase2", "docs", "web"), sent):
            self.assertEqual(
                shlex.split(command),
                ["CMUX_AGENT_MANAGED_SUBAGENT=1", *wave["resolved_profiles"][lane]["argv"]],
            )

        self.assertEqual(
            wave["resolved_profiles"]["codebase"]["argv"],
            [
                "claude", "--model", "opus", "--effort", "high",
                "--permission-mode", "auto",
            ],
        )
        codebase2 = wave["resolved_profiles"]["codebase2"]["argv"]
        docs = wave["resolved_profiles"]["docs"]["argv"]
        for argv in (codebase2, docs):
            self.assertIn("workspace-write", argv)
            self.assertIn("approvals_reviewer=auto_review", argv)
            self.assertIn("check_for_update_on_startup=false", argv)
            self.assertIn("tui.whimsy=false", argv)
        self.assertNotIn("sandbox_workspace_write.network_access=true", codebase2)
        self.assertIn("sandbox_workspace_write.network_access=true", docs)

    def test_live_probe_verifies_each_unique_frozen_profile_with_safe_fixed_requests(self):
        proc = self.init_for("probed", "--probe-profiles")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        wave = self.read_wave("probed")
        self.assertEqual(
            wave["live_profile_probe"],
            {"enabled": True, "timeout_seconds": 120.0},
        )
        for lane, entry in wave["resolved_profiles"].items():
            with self.subTest(lane=lane):
                entitlement = entry["entitlement"]
                self.assertEqual(entitlement["status"], "verified")
                self.assertEqual(entitlement["probe"]["status"], "passed")
                self.assertEqual(entitlement["probe"]["sentinel"], PROBE_SENTINEL)
                self.assertEqual(entitlement["probe"]["timeout_seconds"], 120.0)
                self.assertGreaterEqual(entitlement["probe"]["duration_ms"], 0)

        calls = [json.loads(line) for line in self.harness_log.read_text().splitlines()]
        probes = [call for call in calls if PROBE_SENTINEL in " ".join(call["argv"])]
        self.assertEqual(len(probes), 4)
        for call in probes:
            if call["program"] == "codex":
                self.assertIn("exec", call["argv"])
                self.assertIn("read-only", call["argv"])
                self.assertIn('approval_policy="never"', call["argv"])
                self.assertIn("tui.whimsy=false", call["argv"])
                self.assertIn("--ephemeral", call["argv"])
            else:
                self.assertIn("--print", call["argv"])
                self.assertIn("--safe-mode", call["argv"])
                self.assertIn("--no-session-persistence", call["argv"])
                self.assertEqual(call["argv"][call["argv"].index("--tools") + 1], "")
                self.assertIn("plan", call["argv"])
        self.assertFalse(self.write_marker.exists())
        serialized = json.dumps(wave)
        audit = (self.run_dir("probed") / "events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("must-not-be-audited", serialized)
        self.assertNotIn("must-not-be-audited", audit)
        self.assertNotIn("FAKE_HARNESS", audit)

    def test_live_probe_deduplicates_duplicate_lane_assignments(self):
        config = self.root / "duplicate-profiles.json"
        initialized = self.initialize_config(config)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        data = json.loads(config.read_text(encoding="utf-8"))
        data["workflows"]["grilling"]["codebase2"] = "codex-luna-medium"
        config.write_text(json.dumps(data), encoding="utf-8")
        before = (
            len(self.harness_log.read_text(encoding="utf-8").splitlines())
            if self.harness_log.is_file()
            else 0
        )

        proc = self.init_for("deduplicated", "--config", str(config), "--probe-profiles")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = [json.loads(line) for line in self.harness_log.read_text().splitlines()[before:]]
        probes = [call for call in calls if PROBE_SENTINEL in " ".join(call["argv"])]
        self.assertEqual(len(probes), 3)

    def test_live_probe_failures_and_timeout_leave_no_wave_or_pane(self):
        for mode, expected in (
            ("provider", "exit 12"),
            ("wrong-sentinel", "expected sentinel"),
            ("malformed", "expected sentinel"),
            ("timeout", "timed out"),
        ):
            with self.subTest(mode=mode):
                run_id = f"probe-{mode}"
                extra = ("--probe-profiles",)
                if mode == "timeout":
                    extra += ("--probe-timeout", "0.05")
                proc = self.init_for(
                    run_id, *extra, env=self.env(FAKE_HARNESS_FAILURE=mode)
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(expected, proc.stderr)
                self.assertIn("diagnostic failure", proc.stderr)
                self.assertIn("profile=", proc.stderr)
                self.assertNotIn("must-not-be-audited", proc.stderr)
                self.assertFalse((self.run_dir(run_id) / "state.json").exists())
                self.assertFalse((self.run_dir(run_id) / "launch-waves").exists())
                launched = self.pane(
                    "launch", "--run-dir", str(self.run_dir(run_id)),
                    "--lane", "codebase", "--anchor", "anchor",
                )
                self.assertNotEqual(launched.returncode, 0)

    def test_missing_probe_capability_is_reported_without_spending_a_provider_request(self):
        before = len(self.harness_log.read_text().splitlines()) if self.harness_log.is_file() else 0
        proc = self.init_for(
            "probe-capability", "--probe-profiles",
            env=self.env(FAKE_HARNESS_FAILURE="probe-help"),
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("probe capability check", proc.stderr)
        self.assertIn("--ephemeral", proc.stderr)
        calls = [json.loads(line) for line in self.harness_log.read_text().splitlines()[before:]]
        probes = [call for call in calls if PROBE_SENTINEL in " ".join(call["argv"])]
        self.assertEqual([call for call in probes if call["program"] == "codex"], [])
        self.assertFalse((self.run_dir("probe-capability") / "launch-waves").exists())

    def test_probe_timeout_is_positive_cli_only_operational_state(self):
        proc = self.init_for("bad-timeout", "--probe-timeout", "nan")

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--probe-timeout", proc.stderr)
        self.assertFalse((self.run_dir("bad-timeout") / "state.json").exists())

    def test_preflight_failure_blocks_every_lane_before_any_pane(self):
        for mode in ("version", "help", "auth"):
            with self.subTest(mode=mode):
                run_id = f"failed-{mode}"
                proc = self.init_for(run_id, env=self.env(FAKE_HARNESS_FAILURE=mode))
                self.assertNotEqual(proc.returncode, 0)
                self.assertFalse((self.run_dir(run_id) / "state.json").exists())
                self.assertFalse((self.run_dir(run_id) / "launch-waves").exists())
                launched = self.pane(
                    "launch", "--run-dir", str(self.run_dir(run_id)),
                    "--lane", "codebase", "--anchor", "anchor",
                )
                self.assertNotEqual(launched.returncode, 0)

        missing_run = "failed-executable"
        missing = self.init_for(
            missing_run,
            "--executable", "docs=/definitely/not/a/grilling-harness",
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("not an executable", missing.stderr)
        self.assertFalse((self.run_dir(missing_run) / "state.json").exists())
        launched = self.pane(
            "launch", "--run-dir", str(self.run_dir(missing_run)),
            "--lane", "web", "--anchor", "anchor",
        )
        self.assertNotEqual(launched.returncode, 0)
        self.assertEqual(self.cmux_calls(), [])

    def test_explicit_config_and_web_compatibility_failure(self):
        explicit = self.root / "configuration" / "agents-custom.json"
        initialized = self.initialize_config(explicit)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        created = self.init_for("explicit", "--config", str(explicit))
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(self.read_state("explicit")["configuration_source"], str(explicit.resolve()))

        config = json.loads(explicit.read_text(encoding="utf-8"))
        config["workflows"]["grilling"]["web"] = "codex-luna-medium"
        explicit.write_text(json.dumps(config), encoding="utf-8")
        rejected = self.init_for("incompatible", "--config", str(explicit))
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("not compatible", rejected.stderr)
        self.assertFalse((self.run_dir("incompatible") / "state.json").exists())
        self.assertEqual(self.cmux_calls(), [])

    def test_init_refuses_missing_default_configuration_without_bootstrapping(self):
        self.config_path.unlink()

        proc = self.init_for("missing-default")

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("configuration does not exist", proc.stderr)
        self.assertIn("agents_config.py init", proc.stderr)
        self.assertIn("review the workflow assignments", proc.stderr)
        self.assertFalse(self.config_path.exists())
        self.assertFalse((self.run_dir("missing-default") / "state.json").exists())
        self.assertFalse((self.run_dir("missing-default") / "launch-waves").exists())
        self.assertFalse(self.harness_log.exists())

    def test_init_refuses_missing_explicit_configuration_without_bootstrapping(self):
        explicit = self.root / "configuration" / "missing.json"

        proc = self.init_for("missing-explicit", "--config", str(explicit))

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(str(explicit.resolve()), proc.stderr)
        self.assertIn("configuration does not exist", proc.stderr)
        self.assertIn("agents_config.py init", proc.stderr)
        self.assertFalse(explicit.exists())
        self.assertFalse((self.run_dir("missing-explicit") / "state.json").exists())
        self.assertFalse((self.run_dir("missing-explicit") / "launch-waves").exists())
        self.assertFalse(self.harness_log.exists())

    def test_allowed_harness_overrides_use_the_lane_specific_adapters(self):
        proc = self.init_for(
            "alternate-harnesses",
            "--harness", "codebase=codex",
            "--executable", "codebase=codex",
            "--model", "codebase=custom/code-model",
            "--effort", "codebase=high",
            "--harness", "codebase2=claude-code",
            "--executable", "codebase2=claude",
            "--model", "codebase2=opus",
            "--effort", "codebase2=max",
            "--harness", "docs=claude-code",
            "--executable", "docs=claude",
            "--model", "docs=sonnet",
            "--effort", "docs=medium",
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        wave = self.read_wave("alternate-harnesses")
        self.assertEqual(wave["resolved_profiles"]["codebase"]["harness"], "codex")
        self.assertNotIn(
            "sandbox_workspace_write.network_access=true",
            wave["resolved_profiles"]["codebase"]["argv"],
        )
        self.assertEqual(
            wave["resolved_profiles"]["codebase2"]["argv"],
            [
                "claude", "--model", "opus", "--effort", "max",
                "--permission-mode", "auto",
            ],
        )
        self.assertEqual(
            wave["resolved_profiles"]["docs"]["argv"],
            [
                "claude", "--model", "sonnet", "--effort", "medium",
                "--permission-mode", "auto",
            ],
        )
        self.assertEqual(
            wave["effective_overrides"]["codebase"]["model"],
            "custom/code-model",
        )

    def test_reinit_refuses_configuration_inputs_that_cannot_replace_the_cohort(self):
        self.assertEqual(self.init_for("existing").returncode, 0)

        with_config = self.init_for(
            "existing", "--config", str(self.root / "replacement.json")
        )
        with_override = self.init_for("existing", "--model", "docs=replacement/model")

        for proc in (with_config, with_override):
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("require a new grilling run", proc.stderr)
        self.assertEqual(
            self.read_wave("existing")["resolved_profiles"]["docs"]["model"],
            "gpt-5.6-luna",
        )

    def test_live_config_edits_do_not_change_or_restart_persistent_lanes(self):
        initialized = self.init_for("immutable")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        before = self.read_wave("immutable")
        config_path = Path(self.read_state("immutable")["configuration_source"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["profiles"]["codex-astra-high"]["model"] = "changed/after-start"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        run_dir = self.run_dir("immutable")
        started = self.pane(
            "start-agent", "--run-dir", str(run_dir), "--surface", "persistent-surface",
            "--lane", "codebase2", "--settle-seconds", "0",
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        common = ["--run-dir", str(run_dir), "--surface", "persistent-surface", "--lane", "codebase2"]
        observed = self.pane("observe", *common)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        assessed = self.pane("assess", *common,
                             "--observation", json.loads(observed.stdout)["observation_id"],
                             "--state", "ready", "--reason", "persistent lane is idle for the next round")
        self.assertEqual(assessed.returncode, 0, assessed.stderr)
        delivered = self.pane(
            "deliver", "--run-dir", str(run_dir), "--surface", "persistent-surface",
            "--lane", "codebase2", "--text", "round two", "--settle-seconds", "0",
        )
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        sends = [call[-1] for call in self.cmux_calls() if call and call[0] == "send"]
        self.assertIn("gpt-6-astra", sends[0])
        self.assertNotIn("changed/after-start", sends[0])
        self.assertEqual(sends[1], "round two")
        self.assertEqual(before, self.read_wave("immutable"))

        next_run = self.init_for("next-run")
        self.assertEqual(next_run.returncode, 0, next_run.stderr)
        self.assertEqual(
            self.read_wave("next-run")["resolved_profiles"]["codebase2"]["model"],
            "changed/after-start",
        )

    def test_missing_failed_or_mismatched_wave_is_refused_without_cmux(self):
        for mode in ("missing", "failed", "mismatched"):
            with self.subTest(mode=mode):
                run_id = f"invalid-{mode}"
                initialized = self.init_for(run_id)
                self.assertEqual(initialized.returncode, 0, initialized.stderr)
                run_dir = self.run_dir(run_id)
                state_path = run_dir / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if mode == "missing":
                    state["launch_wave"] = None
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                else:
                    wave_path = run_dir / state["launch_wave"]["path"]
                    wave = json.loads(wave_path.read_text(encoding="utf-8"))
                    if mode == "failed":
                        wave["status"] = "failed"
                    else:
                        wave["resolved_profiles"]["codebase"]["lane"] = "web"
                    wave_path.write_text(json.dumps(wave), encoding="utf-8")
                    state["launch_wave"]["sha256"] = hashlib.sha256(wave_path.read_bytes()).hexdigest()
                    state_path.write_text(json.dumps(state), encoding="utf-8")

                started = self.pane(
                    "start-agent", "--run-dir", str(run_dir), "--surface", "SURFACE",
                    "--lane", "codebase", "--settle-seconds", "0",
                )
                self.assertNotEqual(started.returncode, 0)
        self.assertEqual(self.cmux_calls(), [])


class LaneVocabulary(unittest.TestCase):
    """LANES and the shared registry are separate sources keyed by the same lane names."""

    def test_lane_table_matches_the_registry(self):
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            import agents_config
            import orchestrator_lib
        finally:
            sys.path.pop(0)

        self.assertEqual(
            tuple(orchestrator_lib.LANES),
            agents_config.WORKFLOW_WORKERS["grilling"],
            "a lane missing from either side fails only when a wave is launched",
        )
        for lane, entry in orchestrator_lib.LANES.items():
            self.assertIsInstance(entry["label"], str, lane)
        import launch_wave
        self.assertLessEqual(
            launch_wave.CODEX_NETWORK_LANES,
            set(orchestrator_lib.LANES),
            "a network grant for an unknown lane would never be applied",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
