#!/usr/bin/env python3
"""Standalone worker configuration regression tests. Run: python3 scripts/test_agents_config.py

Vendored byte-identically into both skills, like the CLI it covers. Edit one copy and the parity
test below fails until the other matches."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "agents_config.py"
SKILL_DIR = SCRIPT_DIR.parent
SIBLING_SKILL = "cmux-issue-chain" if SKILL_DIR.name == "cmux-grilling" else "cmux-grilling"
SIBLING_SCRIPT_DIR = SKILL_DIR.parent / SIBLING_SKILL / "scripts"
SIBLING_SCRIPT = SIBLING_SCRIPT_DIR / "agents_config.py"


class AgentsConfigCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(self.repo)],
            check=True,
            capture_output=True,
            text=True,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(
        self,
        *args: str,
        cwd: Path | None = None,
        script: Path = SCRIPT,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=cwd or self.repo,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def init_default(self) -> tuple[Path, dict]:
        proc = self.run_cli("init")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = self.repo / ".scratch" / "orchestrator" / "agents.json"
        self.assertTrue(path.is_file())
        return path, json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, data: object, name: str = "agents.json") -> Path:
        path = self.tmp / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_init_from_subdirectory_writes_complete_default_at_git_root(self):
        subdir = self.repo / "some" / "nested" / "directory"
        subdir.mkdir(parents=True)

        proc = self.run_cli("init", cwd=subdir)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = self.repo / ".scratch" / "orchestrator" / "agents.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(
            data["profiles"],
            {
                "claude-opus-medium": {
                    "harness": "claude-code",
                    "executable": "claude",
                    "model": "opus",
                    "effort": "medium",
                },
                "claude-opus-xhigh": {
                    "harness": "claude-code",
                    "executable": "claude",
                    "model": "opus",
                    "effort": "xhigh",
                },
                "claude-sonnet-medium": {
                    "harness": "claude-code",
                    "executable": "claude",
                    "model": "sonnet",
                    "effort": "medium",
                },
                "codex-sol-medium": {
                    "harness": "codex",
                    "executable": "codex",
                    "model": "gpt-5.6-sol",
                    "effort": "medium",
                },
                "codex-sol-xhigh": {
                    "harness": "codex",
                    "executable": "codex",
                    "model": "gpt-5.6-sol",
                    "effort": "xhigh",
                },
                "codex-luna-medium": {
                    "harness": "codex",
                    "executable": "codex",
                    "model": "gpt-5.6-luna",
                    "effort": "medium",
                },
            },
        )
        self.assertEqual(
            data["workflows"],
            {
                "issue-chain": {
                    "implement": "codex-sol-xhigh",
                    "simplify": "claude-opus-xhigh",
                    "review": "claude-opus-xhigh",
                    "test": "codex-sol-xhigh",
                },
                "grilling": {
                    "codebase": "claude-opus-xhigh",
                    "codebase2": "codex-sol-xhigh",
                    "docs": "codex-luna-medium",
                    "web": "claude-sonnet-medium",
                },
            },
        )
        self.assertFalse((self.repo / ".gitignore").exists())

    def test_explicit_path_works_outside_git_and_existing_file_is_never_changed(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        config = outside / "configuration" / "custom.json"

        first = self.run_cli("init", "--config", str(config), cwd=outside)
        self.assertEqual(first.returncode, 0, first.stderr)
        original = config.read_bytes()

        second = self.run_cli("init", "--config", str(config), cwd=outside)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already exists", second.stderr)
        self.assertEqual(config.read_bytes(), original)

    def test_default_path_fails_outside_git(self):
        outside = self.tmp / "outside"
        outside.mkdir()

        proc = self.run_cli("init", cwd=outside)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Git", proc.stderr)
        self.assertIn("--config", proc.stderr)

    def test_repo_option_targets_a_repository_without_changing_directory(self):
        outside = self.tmp / "outside"
        outside.mkdir()

        proc = self.run_cli("init", "--repo", str(self.repo), cwd=outside)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = self.repo / ".scratch" / "orchestrator" / "agents.json"
        self.assertTrue(expected.is_file())
        self.assertIn(str(expected), proc.stdout)

    def test_validate_and_show_resolved_are_provider_free_public_operations(self):
        path, data = self.init_default()

        valid = self.run_cli("validate", "--config", str(path), cwd=self.tmp)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn(str(path.resolve()), valid.stdout)

        shown = self.run_cli("show-resolved", "--config", str(path), cwd=self.tmp)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        resolved = json.loads(shown.stdout)
        self.assertEqual(resolved["profiles"], data["profiles"])
        self.assertEqual(resolved["assignments"], data["workflows"])
        worker = resolved["resolved_workflows"]["issue-chain"]["implement"]
        self.assertEqual(worker["profile"], "codex-sol-xhigh")
        self.assertEqual(worker["model"], "gpt-5.6-sol")
        self.assertEqual(worker["effort"], "xhigh")
        self.assertEqual(worker["source"], str(path.resolve()))
        lane = resolved["resolved_workflows"]["grilling"]["web"]
        self.assertEqual(lane["harness"], "claude-code")
        self.assertEqual(lane["profile"], "claude-sonnet-medium")

    def test_validation_rejects_all_strict_schema_and_compatibility_failures(self):
        _, default = self.init_default()

        cases: list[tuple[str, object, tuple[str, ...]]] = []

        changed = copy.deepcopy(default)
        changed["surprise"] = True
        cases.append(("unknown-top", changed, ("field=surprise", "unknown field")))

        changed = copy.deepcopy(default)
        changed["schema_version"] = 99
        cases.append(("schema-version", changed, ("field=schema_version", "unsupported")))

        changed = copy.deepcopy(default)
        del changed["profiles"]
        cases.append(("missing-top", changed, ("field=profiles", "required")))

        for forbidden in ("args", "environment", "capabilities", "safety"):
            changed = copy.deepcopy(default)
            changed["profiles"]["codex-sol-xhigh"][forbidden] = []
            cases.append(
                (
                    f"forbidden-{forbidden}",
                    changed,
                    ("profile=codex-sol-xhigh", f"field={forbidden}", "unknown field"),
                )
            )

        changed = copy.deepcopy(default)
        del changed["profiles"]["codex-sol-xhigh"]["model"]
        cases.append(
            ("missing-profile-value", changed, ("profile=codex-sol-xhigh", "field=model", "required"))
        )

        for harness, message in (
            ("pi", "not yet supported"),
            ("hermes", "not yet supported"),
            ("other", "unknown harness"),
        ):
            changed = copy.deepcopy(default)
            changed["profiles"]["codex-sol-xhigh"]["harness"] = harness
            cases.append(
                (f"harness-{harness}", changed, ("profile=codex-sol-xhigh", "field=harness", message))
            )

        for executable in ("codex --fast", "./codex", "bin/codex", ""):
            changed = copy.deepcopy(default)
            changed["profiles"]["codex-sol-xhigh"]["executable"] = executable
            cases.append(
                (
                    f"executable-{len(cases)}",
                    changed,
                    ("profile=codex-sol-xhigh", "field=executable", "program name or absolute path"),
                )
            )

        for model in ("", "two models", "--model"):
            changed = copy.deepcopy(default)
            changed["profiles"]["codex-sol-xhigh"]["model"] = model
            cases.append(
                (f"model-{len(cases)}", changed, ("profile=codex-sol-xhigh", "field=model", "syntax"))
            )

        changed = copy.deepcopy(default)
        changed["profiles"]["claude-opus-xhigh"]["effort"] = "ultra"
        cases.append(
            ("claude-effort", changed, ("profile=claude-opus-xhigh", "field=effort", "unsupported"))
        )

        changed = copy.deepcopy(default)
        changed["profiles"]["codex-sol-xhigh"]["effort"] = "extreme"
        cases.append(
            ("codex-effort", changed, ("profile=codex-sol-xhigh", "field=effort", "unsupported"))
        )

        changed = copy.deepcopy(default)
        changed["workflows"]["mystery"] = {}
        cases.append(("unknown-workflow", changed, ("workflow=mystery", "unknown workflow")))

        changed = copy.deepcopy(default)
        del changed["workflows"]["grilling"]
        cases.append(("missing-workflow", changed, ("workflow=grilling", "required")))

        changed = copy.deepcopy(default)
        changed["workflows"]["issue-chain"]["deploy"] = "codex-sol-xhigh"
        cases.append(
            ("unknown-worker", changed, ("workflow=issue-chain", "worker=deploy", "unknown worker"))
        )

        changed = copy.deepcopy(default)
        del changed["workflows"]["grilling"]["docs"]
        cases.append(("missing-worker", changed, ("workflow=grilling", "worker=docs", "required")))

        changed = copy.deepcopy(default)
        changed["workflows"]["issue-chain"]["implement"] = "missing-profile"
        cases.append(
            (
                "dangling-profile",
                changed,
                ("workflow=issue-chain", "worker=implement", "profile=missing-profile", "not defined"),
            )
        )

        changed = copy.deepcopy(default)
        changed["workflows"]["grilling"]["web"] = "codex-luna-medium"
        cases.append(
            (
                "incompatible-web",
                changed,
                ("workflow=grilling", "worker=web", "profile=codex-luna-medium", "not compatible"),
            )
        )

        for name, data, expected in cases:
            with self.subTest(name=name):
                path = self.write_config(data, f"{name}.json")
                proc = self.run_cli("validate", "--config", str(path), cwd=self.tmp)
                self.assertNotEqual(proc.returncode, 0, proc.stdout)
                self.assertIn(f"source={path.resolve()}", proc.stderr)
                for fragment in expected:
                    self.assertIn(fragment, proc.stderr)

    def test_all_documented_effort_values_validate(self):
        _, default = self.init_default()
        for harness, efforts in (
            ("claude-code", ("low", "medium", "high", "xhigh", "max")),
            ("codex", ("low", "medium", "high", "xhigh", "max", "ultra")),
        ):
            for effort in efforts:
                with self.subTest(harness=harness, effort=effort):
                    changed = copy.deepcopy(default)
                    profile = "claude-opus-xhigh" if harness == "claude-code" else "codex-sol-xhigh"
                    changed["profiles"][profile]["effort"] = effort
                    path = self.write_config(changed, f"{harness}-{effort}.json")
                    proc = self.run_cli("validate", "--config", str(path), cwd=self.tmp)
                    self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_models_are_syntax_checked_not_catalog_checked_and_absolute_executables_work(self):
        _, default = self.init_default()
        changed = copy.deepcopy(default)
        changed["profiles"]["codex-sol-xhigh"].update({
            "executable": "/opt/custom-tools/codex-v2",
            "model": "custom/provider:model@2026.08",
        })
        path = self.write_config(changed, "custom-model.json")

        proc = self.run_cli("validate", "--config", str(path), cwd=self.tmp)

        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_code_owned_compatibility_matrix_covers_every_worker_and_harness(self):
        _, default = self.init_default()
        allowed = {
            ("issue-chain", "implement", "claude-code"),
            ("issue-chain", "implement", "codex"),
            ("issue-chain", "simplify", "claude-code"),
            ("issue-chain", "simplify", "codex"),
            ("issue-chain", "review", "claude-code"),
            ("issue-chain", "review", "codex"),
            ("issue-chain", "test", "claude-code"),
            ("issue-chain", "test", "codex"),
            ("grilling", "codebase", "claude-code"),
            ("grilling", "codebase", "codex"),
            ("grilling", "codebase2", "claude-code"),
            ("grilling", "codebase2", "codex"),
            ("grilling", "docs", "claude-code"),
            ("grilling", "docs", "codex"),
            ("grilling", "web", "claude-code"),
        }
        for workflow, assignments in default["workflows"].items():
            for worker in assignments:
                for harness in ("claude-code", "codex"):
                    with self.subTest(workflow=workflow, worker=worker, harness=harness):
                        changed = copy.deepcopy(default)
                        changed["profiles"]["matrix-profile"] = {
                            "harness": harness,
                            "executable": "claude" if harness == "claude-code" else "codex",
                            "model": "custom/model-v1",
                            "effort": "medium",
                        }
                        changed["workflows"][workflow][worker] = "matrix-profile"
                        path = self.write_config(
                            changed,
                            f"matrix-{workflow}-{worker}-{harness}.json",
                        )
                        proc = self.run_cli("validate", "--config", str(path), cwd=self.tmp)
                        expected_allowed = (workflow, worker, harness) in allowed
                        self.assertEqual(proc.returncode == 0, expected_allowed, proc.stderr)
                        if not expected_allowed:
                            self.assertIn("not compatible", proc.stderr)

    def test_validation_aggregates_errors_with_context(self):
        _, default = self.init_default()
        changed = copy.deepcopy(default)
        changed["profiles"]["codex-sol-xhigh"]["args"] = ["--danger"]
        changed["workflows"]["issue-chain"]["deploy"] = "missing"
        path = self.write_config(changed, "several-errors.json")

        proc = self.run_cli("validate", "--config", str(path), cwd=self.tmp)

        self.assertNotEqual(proc.returncode, 0)
        self.assertGreaterEqual(proc.stderr.count("source="), 2)
        self.assertIn("profile=codex-sol-xhigh", proc.stderr)
        self.assertIn("workflow=issue-chain worker=deploy", proc.stderr)

    def test_duplicate_json_fields_are_rejected_instead_of_silently_replaced(self):
        _, default = self.init_default()
        config = self.tmp / "duplicate.json"
        worker_line = '"implement": "codex-sol-xhigh",'
        serialized = json.dumps(default, indent=2)
        serialized = serialized.replace(
            worker_line,
            f'{worker_line}\n      {worker_line}',
            1,
        )
        config.write_text(
            serialized,
            encoding="utf-8",
        )

        proc = self.run_cli("validate", "--config", str(config), cwd=self.tmp)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("workflow=issue-chain worker=implement", proc.stderr)
        self.assertIn("duplicate worker assignment", proc.stderr)

    def test_concurrent_initializers_publish_one_complete_file(self):
        config = self.tmp / "concurrent" / "agents.json"
        command = [sys.executable, str(SCRIPT), "init", "--config", str(config)]
        first = subprocess.Popen(command, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        second = subprocess.Popen(command, cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        first_stdout, first_stderr = first.communicate(timeout=30)
        second_stdout, second_stderr = second.communicate(timeout=30)

        self.assertEqual(sorted((first.returncode, second.returncode)), [0, 1])
        self.assertIn("initialized:", first_stdout + second_stdout)
        self.assertIn("already exists", first_stderr + second_stderr)
        persisted = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(persisted["schema_version"], 1)
        self.assertEqual(len(persisted["profiles"]), 6)

    def test_every_registered_workflow_is_fully_described(self):
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            import agents_config
        finally:
            sys.path.pop(0)

        self.assertEqual(
            set(agents_config.WORKFLOW_NOUN),
            set(agents_config.COMPATIBLE_HARNESSES),
            "a workflow without a noun breaks its CLI help and override errors",
        )
        for workflow, workers in agents_config.COMPATIBLE_HARNESSES.items():
            self.assertEqual(
                agents_config.WORKFLOW_WORKERS[workflow],
                tuple(workers),
                f"{workflow} worker order must follow the compatibility rules",
            )
        self.assertEqual(agents_config.DEFAULT_CONFIG["workflows"].keys(), agents_config.COMPATIBLE_HARNESSES.keys())

    def test_two_independently_shipped_clis_remain_equivalent(self):
        if not SIBLING_SCRIPT.is_file():
            self.skipTest("sibling skill is not present in this independent installation")

        self.assertEqual(
            SCRIPT.read_bytes(),
            SIBLING_SCRIPT.read_bytes(),
            "vendored configuration CLIs drifted",
        )
        own_test = Path(__file__).resolve()
        self.assertEqual(
            own_test.read_bytes(),
            (SIBLING_SCRIPT_DIR / own_test.name).read_bytes(),
            "vendored configuration tests drifted",
        )

        first_path = self.tmp / "from-first.json"
        second_path = self.tmp / "from-second.json"
        first = self.run_cli("init", "--config", str(first_path), cwd=self.tmp)
        second = self.run_cli(
            "init", "--config", str(second_path), cwd=self.tmp, script=SIBLING_SCRIPT
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(first_path.read_text()), json.loads(second_path.read_text()))

        shown_first = self.run_cli("show-resolved", "--config", str(first_path), cwd=self.tmp)
        shown_second = self.run_cli(
            "show-resolved", "--config", str(first_path), cwd=self.tmp, script=SIBLING_SCRIPT
        )
        self.assertEqual(shown_first.returncode, 0, shown_first.stderr)
        self.assertEqual(shown_second.returncode, 0, shown_second.stderr)
        self.assertEqual(shown_first.stdout, shown_second.stdout)

        invalid = json.loads(first_path.read_text())
        invalid["profiles"]["codex-sol-xhigh"]["effort"] = "impossible"
        invalid_path = self.write_config(invalid, "invalid-parity.json")
        invalid_first = self.run_cli("validate", "--config", str(invalid_path), cwd=self.tmp)
        invalid_second = self.run_cli(
            "validate", "--config", str(invalid_path), cwd=self.tmp, script=SIBLING_SCRIPT
        )
        self.assertEqual(invalid_first.returncode, invalid_second.returncode)
        self.assertEqual(invalid_first.stdout, invalid_second.stdout)
        self.assertEqual(invalid_first.stderr, invalid_second.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
