#!/usr/bin/env python3
"""Prepared-stage regression tests. Run: python3 scripts/test_stage_preparation.py"""

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

ISSUE = """---
id: ISSUE-001
title: Prepared workers
type: AFK
status: todo
---

# ISSUE-001 — Prepared workers

## Blocked by

- None

## Acceptance Criteria

- [ ] Prepared launch
"""

PROBE_SENTINEL = "CMUX_PROFILE_PROBE_OK_V1"

FAKE_HARNESS = '''#!/usr/bin/env python3
import json, os, sys, time

log = os.environ.get("FAKE_HARNESS_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"program": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}) + "\\n")

# Simulates a gate landing while this slow preflight is still running.
advance = os.environ.get("FAKE_HARNESS_ADVANCE_STAGE")
if advance:
    state_path, next_stage = advance.split("|", 1)
    with open(state_path, encoding="utf-8") as handle:
        state = json.load(handle)
    state["current_stage"] = next_stage
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)

args = sys.argv[1:]
mode = os.environ.get("FAKE_HARNESS_FAILURE", "")
program = os.path.basename(sys.argv[0])
if args == ["--version"]:
    if mode == "version" and program == "codex":
        raise SystemExit(9)
    print(program + " 99.1-test")
elif args == ["--help"]:
    if mode == "help-lookalikes":
        print("pre--model --sandboxed pre--config --ask-for-approval-later --effortless loginless unauthorized")
    elif mode == "help" and program == "codex":
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
    print("prestatus statuspage" if mode == "auth-help-lookalikes" else "status")
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


class PreparedStageCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        issue_dir = self.repo / ".scratch" / "tracker" / "issues"
        issue_dir.mkdir(parents=True)
        (issue_dir / "ISSUE-001-prepared.md").write_text(ISSUE, encoding="utf-8")

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
        self.run_dir = self.runs_root / "prepared-run"
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

    def run_state(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
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

    def init(self, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.init_for("prepared-run", *extra, env=env)

    def init_for(
        self,
        run_id: str,
        *extra: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_state(
            "init",
            "--tracker", ".scratch/tracker",
            "--issue", "ISSUE-001",
            "--run-id", run_id,
            "--runs-root", str(self.runs_root),
            "--workspace-id", "WORKSPACE",
            *extra,
            env=env,
        )

    def gate(self, stage: str, next_stage: str) -> subprocess.CompletedProcess[str]:
        return self.run_state(
            "gate", "--run-dir", str(self.run_dir),
            "--stage", stage, "--decision", "advance", "--reason", "test",
            "--next-stage", next_stage,
        )

    def prepare(
        self,
        stage: str,
        pass_num: int = 1,
        *extra: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_state(
            "prepare", "--run-dir", str(self.run_dir),
            "--stage", stage, "--pass", str(pass_num), *extra,
            env=env,
        )

    def pane(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(PANE_CTL), "--cmux-cmd", str(self.cmux), *args,
            ],
            cwd=self.repo,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_pane_launch_refused(self, run_dir: Path, role: str = "implement", pass_num: int = 1) -> None:
        pane = self.pane(
            "launch", "--run-dir", str(run_dir),
            "--role", role, "--pass", str(pass_num), "--anchor", "anchor",
        )
        self.assertNotEqual(pane.returncode, 0)
        self.assertFalse(self.cmux_log.exists())

    def assert_no_launchable_run(self, failed_dir: Path) -> None:
        self.assertFalse((failed_dir / "state.json").exists())
        self.assertFalse((failed_dir / "stage-snapshots").exists())
        self.assert_pane_launch_refused(failed_dir)

    def read_state(self) -> dict:
        return json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))

    def read_snapshot(self) -> dict:
        state = self.read_state()
        return json.loads((self.run_dir / state["prepared_stage"]["path"]).read_text(encoding="utf-8"))

    def test_init_uses_config_preflights_all_roles_and_prepares_implement(self):
        proc = self.init()

        self.assertEqual(proc.returncode, 0, proc.stderr)
        config = self.config_path
        self.assertTrue(config.is_file())
        snapshot = self.read_snapshot()
        self.assertEqual(snapshot["status"], "passed")
        self.assertEqual(snapshot["stage"], "implement")
        self.assertEqual(snapshot["config"]["source"], str(config.resolve()))
        self.assertEqual(snapshot["config"]["sha256"], hashlib.sha256(config.read_bytes()).hexdigest())
        self.assertEqual(set(snapshot["resolved_profiles"]), {"implement", "simplify", "review", "test"})
        selected = snapshot["selected_worker"]
        self.assertEqual(selected["profile"], "codex-sol-xhigh")
        self.assertEqual(selected["model"], "gpt-5.6-sol")
        self.assertEqual(selected["effort"], "xhigh")
        self.assertEqual(selected["detected_version"], "codex 99.1-test")
        self.assertEqual(selected["entitlement"]["status"], "unverified")
        self.assertEqual(selected["argv"][0], "codex")
        self.assertEqual(selected["requested_executable"], "codex")
        self.assertEqual(selected["resolved_executable"], str((self.bin_dir / "codex").resolve()))
        self.assertEqual(
            selected["argv"][1:],
            [
                "-s", "workspace-write",
                "-c", "sandbox_workspace_write.network_access=true",
                "-c", 'sandbox_workspace_write.writable_roots=["~/.ddev"]',
                "--ask-for-approval", "on-request",
                "-c", "approvals_reviewer=auto_review",
                "-c", "check_for_update_on_startup=false",
                "--model", "gpt-5.6-sol",
                "-c", "model_reasoning_effort=xhigh",
            ],
        )
        serialized = json.dumps(snapshot)
        self.assertNotIn("must-not-be-audited", serialized)
        self.assertNotIn(
            "must-not-be-audited",
            (self.run_dir / "events.jsonl").read_text(encoding="utf-8"),
        )
        calls = [json.loads(line) for line in self.harness_log.read_text().splitlines()]
        # Four workers, two distinct executables: the audit depends only on the executable.
        self.assertEqual(sum(call["argv"] == ["--version"] for call in calls), 2)
        self.assertEqual(sum(call["argv"] in (["login", "status"], ["auth", "status"]) for call in calls), 2)

    def test_init_accepts_a_preinitialized_explicit_configuration_path(self):
        explicit = self.root / "configuration" / "agents-custom.json"
        initialized = self.initialize_config(explicit)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

        proc = self.init("--config", str(explicit))

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.read_state()["configuration_source"], str(explicit.resolve()))
        self.assertEqual(self.read_snapshot()["config"]["source"], str(explicit.resolve()))

    def test_init_refuses_missing_default_configuration_without_bootstrapping(self):
        self.config_path.unlink()

        proc = self.init()

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("configuration does not exist", proc.stderr)
        self.assertIn("agents_config.py init", proc.stderr)
        self.assertIn("review the workflow assignments", proc.stderr)
        self.assertFalse(self.config_path.exists())
        self.assertFalse((self.run_dir / "state.json").exists())
        self.assertFalse((self.run_dir / "stage-snapshots").exists())
        self.assertFalse(self.harness_log.exists())

    def test_init_refuses_missing_explicit_configuration_without_bootstrapping(self):
        explicit = self.root / "configuration" / "missing.json"

        proc = self.init("--config", str(explicit))

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(str(explicit.resolve()), proc.stderr)
        self.assertIn("configuration does not exist", proc.stderr)
        self.assertIn("agents_config.py init", proc.stderr)
        self.assertFalse(explicit.exists())
        self.assertFalse((self.run_dir / "state.json").exists())
        self.assertFalse((self.run_dir / "stage-snapshots").exists())
        self.assertFalse(self.harness_log.exists())

    def test_live_probe_verifies_unique_resolved_profiles_once_with_safe_fixed_requests(self):
        proc = self.init("--probe-profiles")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        snapshot = self.read_snapshot()
        self.assertEqual(
            snapshot["live_profile_probe"],
            {"enabled": True, "timeout_seconds": 120.0},
        )
        for worker, entry in snapshot["resolved_profiles"].items():
            with self.subTest(worker=worker):
                entitlement = entry["entitlement"]
                self.assertEqual(entitlement["status"], "verified")
                self.assertEqual(entitlement["probe"]["status"], "passed")
                self.assertEqual(entitlement["probe"]["sentinel"], PROBE_SENTINEL)
                self.assertEqual(entitlement["probe"]["timeout_seconds"], 120.0)
                self.assertGreaterEqual(entitlement["probe"]["duration_ms"], 0)
                self.assertTrue(entitlement["probe"]["started_at"])
                self.assertTrue(entitlement["probe"]["completed_at"])

        calls = [json.loads(line) for line in self.harness_log.read_text().splitlines()]
        probes = [call for call in calls if PROBE_SENTINEL in " ".join(call["argv"])]
        self.assertEqual(len(probes), 2, "duplicate worker assignments must share one profile probe")
        self.assertEqual({call["program"] for call in probes}, {"claude", "codex"})
        codex = next(call["argv"] for call in probes if call["program"] == "codex")
        claude = next(call["argv"] for call in probes if call["program"] == "claude")
        self.assertIn("exec", codex)
        self.assertIn("read-only", codex)
        self.assertIn('approval_policy="never"', codex)
        self.assertIn("--ephemeral", codex)
        self.assertIn("--print", claude)
        self.assertIn("--safe-mode", claude)
        self.assertIn("--no-session-persistence", claude)
        self.assertEqual(claude[claude.index("--tools") + 1], "")
        self.assertIn("plan", claude)
        self.assertFalse(self.write_marker.exists())
        audit = (self.run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("FAKE_HARNESS", audit)
        self.assertNotIn("must-not-be-audited", audit)

    def test_live_probe_distinguishes_resolved_overrides_and_stage_preparation_reloads(self):
        self.assertEqual(self.init().returncode, 0)
        before = len(self.harness_log.read_text(encoding="utf-8").splitlines())

        prepared = self.prepare(
            "implement", 2,
            "--probe-profiles",
            "--model", "implement=overridden/model",
        )

        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        calls = [json.loads(line) for line in self.harness_log.read_text().splitlines()[before:]]
        probes = [call for call in calls if PROBE_SENTINEL in " ".join(call["argv"])]
        self.assertEqual(len(probes), 3)
        self.assertTrue(any("overridden/model" in call["argv"] for call in probes))
        self.assertEqual(self.read_snapshot()["selected_worker"]["entitlement"]["status"], "verified")

    def test_live_probe_failures_and_timeout_block_before_snapshot_or_pane(self):
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
                self.assert_no_launchable_run(self.runs_root / run_id)

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
        self.assert_no_launchable_run(self.runs_root / "probe-capability")

    def test_probe_timeout_is_positive_cli_only_operational_state(self):
        proc = self.init("--probe-timeout", "0")

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("--probe-timeout", proc.stderr)
        self.assertFalse((self.run_dir / "state.json").exists())

    def test_launch_identity_is_the_configured_executable_not_the_preflighted_realpath(self):
        alias_dir = self.root / "linked"
        alias_dir.mkdir()
        alias = alias_dir / "claude"
        alias.symlink_to(self.bin_dir / "claude")

        proc = self.init("--executable", f"review={alias}")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        review = self.read_snapshot()["resolved_profiles"]["review"]
        self.assertEqual(review["argv"][0], str(alias))
        self.assertEqual(review["requested_executable"], str(alias))
        self.assertEqual(review["resolved_executable"], str((self.bin_dir / "claude").resolve()))

    def test_capability_version_and_auth_failures_leave_no_launchable_run_or_pane(self):
        for mode in ("help", "version", "auth"):
            with self.subTest(mode=mode):
                run_id = f"failed-{mode}"
                failed_dir = self.runs_root / run_id
                proc = self.init_for(run_id, env=self.env(FAKE_HARNESS_FAILURE=mode))
                self.assertNotEqual(proc.returncode, 0)
                self.assert_no_launchable_run(failed_dir)

        missing_dir = self.runs_root / "failed-executable"
        missing = self.init_for(
            "failed-executable",
            "--executable", "implement=/definitely/not/a/worker",
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("not an executable", missing.stderr)
        self.assertFalse((missing_dir / "state.json").exists())

    def test_help_lookalikes_fail_before_snapshot_or_pane(self):
        claude_implement = (
            "--harness", "implement=claude-code",
            "--executable", "implement=claude",
            "--model", "implement=opus",
            "--effort", "implement=xhigh",
        )
        scenarios = (
            (
                "codex-root-help-lookalikes",
                "help-lookalikes",
                (),
                ("--model", "--sandbox", "--config", "--ask-for-approval", "login"),
            ),
            (
                "claude-root-help-lookalikes",
                "help-lookalikes",
                claude_implement,
                ("--model", "--effort", "auth"),
            ),
            ("codex-auth-help-lookalikes", "auth-help-lookalikes", (), ("status",)),
            (
                "claude-auth-help-lookalikes",
                "auth-help-lookalikes",
                claude_implement,
                ("status",),
            ),
        )
        for run_id, mode, overrides, missing_capabilities in scenarios:
            with self.subTest(run_id=run_id):
                failed_dir = self.runs_root / run_id

                proc = self.init_for(
                    run_id,
                    *overrides,
                    env=self.env(FAKE_HARNESS_FAILURE=mode),
                )

                self.assertNotEqual(proc.returncode, 0)
                for missing_capability in missing_capabilities:
                    self.assertIn(missing_capability, proc.stderr)
                self.assert_no_launchable_run(failed_dir)

    def test_schema_failure_leaves_no_snapshot(self):
        explicit = self.root / "invalid.json"
        explicit.write_text('{"schema_version": 999}', encoding="utf-8")

        proc = self.init("--config", str(explicit))

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("schema_version", proc.stderr)
        self.assertFalse((self.run_dir / "state.json").exists())
        self.assertFalse((self.run_dir / "stage-snapshots").exists())

    def test_prepare_reloads_live_config_but_start_uses_only_the_prepared_snapshot(self):
        initialized = self.init()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        config_path = self.repo / ".scratch" / "orchestrator" / "agents.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["profiles"]["claude-next"] = {
            "harness": "claude-code",
            "executable": "claude",
            "model": "next-model",
            "effort": "high",
        }
        config["workflows"]["issue-chain"]["simplify"] = "claude-next"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(self.gate("implement", "simplify").returncode, 0)

        prepared = self.prepare("simplify")

        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        snapshot = self.read_snapshot()
        self.assertEqual(snapshot["selected_worker"]["profile"], "claude-next")
        self.assertEqual(snapshot["selected_worker"]["model"], "next-model")
        self.assertEqual(snapshot["config"]["sha256"], hashlib.sha256(config_path.read_bytes()).hexdigest())
        prepared_argv = snapshot["selected_worker"]["argv"]
        preflight_calls = len(self.harness_log.read_text(encoding="utf-8").splitlines())

        config["profiles"]["claude-next"]["model"] = "changed-after-prepare"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        started = self.pane(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURFACE", "--role", "simplify", "--pass", "1",
            "--settle-seconds", "0",
        )

        self.assertEqual(started.returncode, 0, started.stderr)
        cmux_calls = [json.loads(line) for line in self.cmux_log.read_text().splitlines()]
        command = cmux_calls[0][-1]
        self.assertEqual(shlex.split(command), ["CMUX_AGENT_MANAGED_SUBAGENT=1", *prepared_argv])
        self.assertIn("next-model", command)
        self.assertNotIn("changed-after-prepare", command)
        self.assertEqual(
            len(self.harness_log.read_text(encoding="utf-8").splitlines()),
            preflight_calls,
            "pane start must not reload or probe the mutable live configuration",
        )

    def test_each_later_stage_must_be_freshly_prepared(self):
        initialized = self.init()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        expected_harness = {
            "simplify": "claude-code",
            "review": "claude-code",
            "test": "codex",
        }
        previous = "implement"
        for stage in ("simplify", "review", "test"):
            with self.subTest(stage=stage):
                self.assertEqual(self.gate(previous, stage).returncode, 0)
                self.assert_pane_launch_refused(self.run_dir, stage)

                prepared = self.prepare(stage)
                self.assertEqual(prepared.returncode, 0, prepared.stderr)
                snapshot = self.read_snapshot()
                self.assertEqual(snapshot["stage"], stage)
                self.assertEqual(snapshot["selected_worker"]["harness"], expected_harness[stage])
                previous = stage

    def test_overrides_resolve_in_order_reject_duplicates_and_do_not_persist(self):
        proc = self.init(
            "--profile", "implement=codex-luna-medium",
            "--model", "implement=custom/model-v2",
            "--effort", "implement=high",
            "--executable", f"implement={self.bin_dir / 'codex'}",
            "--harness", "test=claude-code",
            "--model", "test=test/model",
            "--effort", "test=max",
            "--executable", f"test={self.bin_dir / 'claude'}",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        snapshot = self.read_snapshot()
        selected = snapshot["selected_worker"]
        self.assertEqual(selected["profile"], "codex-luna-medium")
        self.assertEqual(selected["model"], "custom/model-v2")
        self.assertEqual(selected["effort"], "high")
        self.assertEqual(
            snapshot["effective_overrides"]["implement"],
            {
                "profile": "codex-luna-medium",
                "model": "custom/model-v2",
                "effort": "high",
                "executable": str(self.bin_dir / "codex"),
            },
        )
        test_worker = snapshot["resolved_profiles"]["test"]
        self.assertEqual(test_worker["harness"], "claude-code")
        self.assertEqual(test_worker["model"], "test/model")
        self.assertEqual(
            test_worker["argv"],
            [str(self.bin_dir / "claude"), "--model", "test/model", "--effort", "max"],
        )

        duplicate = self.init_for(
            "duplicate-run",
            "--model", "implement=first", "--model", "implement=second",
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("duplicate --model", duplicate.stderr)
        self.assertFalse((self.runs_root / "duplicate-run" / "state.json").exists())

        first_refresh = self.prepare("implement", 2, "--model", "implement=temporary/model")
        self.assertEqual(first_refresh.returncode, 0, first_refresh.stderr)
        self.assertEqual(self.read_snapshot()["selected_worker"]["model"], "temporary/model")
        second_refresh = self.prepare("implement", 3)
        self.assertEqual(second_refresh.returncode, 0, second_refresh.stderr)
        self.assertEqual(self.read_snapshot()["selected_worker"]["model"], "gpt-5.6-sol")
        self.assertEqual(self.read_snapshot()["effective_overrides"], {})

    def test_incompatible_override_invalidates_previous_snapshot_before_pane_creation(self):
        initialized = self.init()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(self.gate("implement", "simplify").returncode, 0)

        # Every issue-chain worker accepts both supported harnesses, so the refusal that must
        # precede pane creation is an unsupported adapter rather than a worker mismatch.
        prepared = self.prepare("simplify", 1, "--harness", "simplify=pi")

        self.assertNotEqual(prepared.returncode, 0)
        self.assertIn("unsupported harness", prepared.stderr)
        self.assertIsNone(self.read_state()["prepared_stage"])
        self.assert_pane_launch_refused(self.run_dir, "simplify")

    def test_a_stage_change_during_preflight_neither_publishes_nor_is_overwritten(self):
        self.assertEqual(self.init().returncode, 0)
        self.assertEqual(self.gate("implement", "simplify").returncode, 0)
        moved = self.env(FAKE_HARNESS_ADVANCE_STAGE=f"{self.run_dir / 'state.json'}|review")

        prepared = self.prepare("simplify", 1, env=moved)

        self.assertNotEqual(prepared.returncode, 0)
        self.assertIn("while simplify was being prepared", prepared.stderr)
        state = self.read_state()
        self.assertEqual(state["current_stage"], "review")
        self.assertIsNone(state["prepared_stage"])

    def test_reinit_refuses_configuration_inputs_it_would_silently_drop(self):
        self.assertEqual(self.init().returncode, 0)

        with_config = self.init("--config", str(self.root / "other.json"))
        with_override = self.init("--model", "implement=ignored/model")

        for proc in (with_config, with_override):
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("already exists", proc.stderr)
        self.assertEqual(self.read_snapshot()["selected_worker"]["model"], "gpt-5.6-sol")

    def test_reinit_restores_a_deleted_runs_root_ignore(self):
        self.assertEqual(self.init().returncode, 0)
        ignore = self.runs_root / ".gitignore"
        ignore.unlink()

        again = self.init()

        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(ignore.read_text(encoding="utf-8").strip(), "*")


if __name__ == "__main__":
    unittest.main(verbosity=2)
