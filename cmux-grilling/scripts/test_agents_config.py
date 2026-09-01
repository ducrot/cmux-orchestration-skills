#!/usr/bin/env python3
"""Standalone worker configuration regression tests. Run: python3 scripts/test_agents_config.py

Vendored byte-identically into every skill, like the CLI it covers. Edit one copy and the parity
test below fails until all copies match."""

from __future__ import annotations

import copy
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPT_DIR / "agents_config.py"
SKILL_DIR = SCRIPT_DIR.parent
SIBLING_SCRIPT_DIRS = [
    path / "scripts"
    for path in sorted(SKILL_DIR.parent.glob("cmux-*"))
    if path.is_dir() and path != SKILL_DIR and (path / "scripts" / "agents_config.py").is_file()
]


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

    def legacy_default(self) -> tuple[Path, dict]:
        """The initialized default path plus a schema-v1 copy of its configuration."""
        path, current = self.init_default()
        legacy = copy.deepcopy(current)
        legacy["schema_version"] = 1
        del legacy["workflows"]["planning"]
        return path, legacy

    def assert_untouched(self, path: Path, original: bytes, before: os.stat_result) -> None:
        """Bytes, metadata, and path identity of a refused migration target."""
        self.assertEqual(path.read_bytes(), original)
        after = path.stat()
        for field in ("st_mode", "st_ino", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"):
            self.assertEqual(getattr(after, field), getattr(before, field), field)

    def test_init_from_subdirectory_writes_complete_default_at_git_root(self):
        subdir = self.repo / "some" / "nested" / "directory"
        subdir.mkdir(parents=True)

        proc = self.run_cli("init", cwd=subdir)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        path = self.repo / ".scratch" / "orchestrator" / "agents.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 2)
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
                "planning": {
                    "spec": "claude-opus-xhigh",
                    "tickets": "claude-opus-xhigh",
                    "reviewer": "codex-sol-xhigh",
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
            ("planning", "spec", "claude-code"),
            ("planning", "spec", "codex"),
            ("planning", "tickets", "claude-code"),
            ("planning", "tickets", "codex"),
            ("planning", "reviewer", "codex"),
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
        self.assertEqual(persisted["schema_version"], 2)
        self.assertEqual(len(persisted["profiles"]), 6)

    def test_version_one_inspection_and_preview_are_read_only(self):
        _, legacy = self.legacy_default()
        legacy["profiles"]["aaa-author"] = {
            "harness": "claude-code",
            "executable": "claude",
            "model": "custom-author",
            "effort": "medium",
        }
        legacy["workflows"]["issue-chain"]["implement"] = "aaa-author"
        path = self.write_config(legacy, "legacy.json")
        original = path.read_bytes()
        before = path.stat()

        for command in ("validate", "show-resolved", "migrate"):
            with self.subTest(command=command):
                proc = self.run_cli(command, "--config", str(path), cwd=self.tmp)
                self.assertNotEqual(proc.returncode, 0)
                output = proc.stdout + proc.stderr
                self.assertIn("Coordinated upgrade required", output)
                self.assertIn('"schema_version": 2', output)
                self.assertIn("agents_config.py migrate", output)
                self.assertIn("--accept", output)
                self.assert_untouched(path, original, before)

    def test_read_only_migration_emits_one_complete_guidance_block_on_stdout(self):
        _, legacy = self.legacy_default()
        path = self.write_config(legacy, "legacy-single-guidance.json")
        original = path.read_bytes()
        before = path.stat()

        proc = self.run_cli("migrate", "--config", str(path), cwd=self.tmp)

        self.assertNotEqual(proc.returncode, 0)
        digest_match = re.search(r"candidate SHA-256: ([0-9a-f]{64})", proc.stdout)
        self.assertIsNotNone(digest_match, proc.stdout)
        digest = digest_match.group(1)
        preview_command = shlex.join(
            ["python3", str(SCRIPT.resolve()), "migrate", "--config", str(path.resolve())]
        )
        acceptance_command = shlex.join(
            [
                "python3",
                str(SCRIPT.resolve()),
                "migrate",
                "--accept",
                "--expect-sha256",
                digest,
                "--config",
                str(path.resolve()),
            ]
        )
        self.assertEqual(proc.stdout.count("Read-only schema-v1 migration preview"), 1)
        self.assertEqual(proc.stdout.count(f"Validated schema-v2 candidate SHA-256: {digest}"), 1)
        self.assertEqual(proc.stdout.count(f"Preview command: {preview_command}"), 1)
        self.assertEqual(proc.stdout.count(f"Acceptance command: {acceptance_command}"), 1)
        self.assertEqual(
            proc.stderr.strip(),
            "migration preview completed without mutation; explicit acceptance is required",
        )
        self.assertNotIn(preview_command, proc.stderr)
        self.assertNotIn(acceptance_command, proc.stderr)
        self.assert_untouched(path, original, before)

    def test_version_one_is_migrated_only_with_acceptance(self):
        _, legacy = self.legacy_default()
        legacy["profiles"]["aaa-author"] = {
            "harness": "claude-code",
            "executable": "claude",
            "model": "custom-author",
            "effort": "medium",
        }
        legacy["workflows"]["issue-chain"]["implement"] = "aaa-author"
        path = self.write_config(legacy, "legacy-accepted.json")
        original = path.read_bytes()

        refused = self.run_cli("migrate", "--config", str(path), cwd=self.tmp)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(path.read_bytes(), original)

        proc = self.run_cli("migrate", "--accept", "--config", str(path), cwd=self.tmp)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        migrated = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["workflows"]["issue-chain"]["implement"], "aaa-author")
        self.assertEqual(
            migrated["workflows"]["planning"],
            {
                "spec": "claude-opus-xhigh",
                "tickets": "claude-opus-xhigh",
                "reviewer": "codex-sol-xhigh",
            },
        )
        once = path.read_bytes()
        identity = path.stat()
        again = self.run_cli("validate", "--config", str(path), cwd=self.tmp)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(path.read_bytes(), once, "version-two reads must be idempotent")
        accepted_again = self.run_cli("migrate", "--accept", "--config", str(path), cwd=self.tmp)
        self.assertEqual(accepted_again.returncode, 0, accepted_again.stderr)
        self.assertEqual(path.read_bytes(), once)
        self.assertEqual(path.stat().st_ino, identity.st_ino)

    def test_invalid_migration_digest_guidance_matches_preview_and_accept_modes(self):
        _, legacy = self.legacy_default()

        for accepting in (False, True):
            for index, value in enumerate(("", " \t\n ", "deadbeef", "z" * 64)):
                with self.subTest(accepting=accepting, value=value):
                    path = self.write_config(
                        legacy, f"legacy-invalid-digest-{accepting}-{index}.json"
                    )
                    original = path.read_bytes()
                    before = path.stat()

                    args = ["migrate"]
                    if accepting:
                        args.append("--accept")
                    args.extend(("--expect-sha256", value, "--config", str(path)))
                    refused = self.run_cli(*args, cwd=self.tmp)

                    self.assertNotEqual(refused.returncode, 0)
                    self.assertEqual(refused.stdout, "")
                    self.assertIn("invalid --expect-sha256 digest", refused.stderr)
                    expected = (
                        "omit --expect-sha256 to accept without digest binding"
                        if accepting
                        else "omit --expect-sha256 to run a read-only preview"
                    )
                    self.assertIn(expected, refused.stderr)
                    self.assert_untouched(path, original, before)

        omitted = self.write_config(legacy, "legacy-omitted-digest.json")
        accepted = self.run_cli("migrate", "--accept", "--config", str(omitted), cwd=self.tmp)

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(omitted.read_text(encoding="utf-8"))["schema_version"], 2)

    def test_version_one_migration_selects_fallbacks_and_never_overwrites_collision(self):
        _, legacy = self.legacy_default()
        legacy["profiles"].pop("claude-opus-xhigh")
        for name in list(legacy["profiles"]):
            if legacy["profiles"][name]["harness"] == "codex":
                legacy["profiles"].pop(name)
        legacy["profiles"]["codex-sol-xhigh"] = {
            "harness": "claude-code",
            "executable": "claude",
            "model": "collision-must-survive",
            "effort": "medium",
        }
        legacy["workflows"]["issue-chain"] = {
            worker: "claude-opus-medium" for worker in legacy["workflows"]["issue-chain"]
        }
        legacy["workflows"]["grilling"] = {
            worker: "claude-opus-medium" for worker in legacy["workflows"]["grilling"]
        }
        path = self.write_config(legacy, "legacy-collision.json")

        preview = self.run_cli("migrate", "--config", str(path), cwd=self.tmp)

        self.assertNotEqual(preview.returncode, 0)
        output = preview.stdout + preview.stderr
        self.assertIn("claude-opus-xhigh", output)
        self.assertIn("unavailable", output.lower())
        for fragment in ("claude-opus-medium", "claude-code", "opus", "medium"):
            self.assertIn(fragment, output)

        proc = self.run_cli("migrate", "--accept", "--config", str(path), cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        migrated = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["profiles"]["codex-sol-xhigh"]["model"], "collision-must-survive")
        self.assertEqual(migrated["workflows"]["planning"]["reviewer"], "codex-sol-xhigh-2")
        self.assertEqual(migrated["profiles"]["codex-sol-xhigh-2"]["harness"], "codex")
        self.assertEqual(migrated["workflows"]["planning"]["spec"], "claude-opus-medium")

    def test_invalid_version_one_migration_preserves_original_bytes(self):
        _, legacy = self.legacy_default()
        legacy["workflows"]["grilling"]["web"] = "codex-sol-xhigh"
        path = self.write_config(legacy, "legacy-invalid.json")
        original = path.read_bytes()

        proc = self.run_cli("migrate", "--accept", "--config", str(path), cwd=self.tmp)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("invalid version-one", proc.stderr)
        self.assertEqual(path.read_bytes(), original)

    def test_version_one_migration_writes_through_a_symlinked_default_path(self):
        default_path, legacy = self.legacy_default()
        shared = self.tmp / "shared-agents.json"
        shared.write_text(json.dumps(legacy), encoding="utf-8")
        default_path.unlink()
        default_path.symlink_to(shared)

        proc = self.run_cli("migrate", "--accept")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(default_path.is_symlink(), "a shared configuration link must survive")
        self.assertEqual(json.loads(shared.read_text(encoding="utf-8"))["schema_version"], 2)

    def test_acceptance_migrates_the_candidate_bound_to_the_previewed_digest(self):
        _, legacy = self.legacy_default()
        path = self.write_config(legacy, "legacy-previewed-digest.json")

        preview = self.run_cli("migrate", "--config", str(path), cwd=self.tmp)
        self.assertNotEqual(preview.returncode, 0)
        output = preview.stdout + preview.stderr
        digest = re.search(r"candidate SHA-256: ([0-9a-f]{64})", output).group(1)

        accepted = self.run_cli(
            "migrate",
            "--accept",
            "--expect-sha256",
            f"  {digest.upper()}  ",
            "--config",
            str(path),
            cwd=self.tmp,
        )

        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 2)

    def test_acceptance_refuses_a_candidate_the_preview_did_not_display(self):
        _, legacy = self.legacy_default()
        path = self.write_config(legacy, "legacy-restaged.json")

        preview = self.run_cli("migrate", "--config", str(path), cwd=self.tmp)
        self.assertNotEqual(preview.returncode, 0)
        output = preview.stdout + preview.stderr
        digest = re.search(r"candidate SHA-256: ([0-9a-f]{64})", output).group(1)
        self.assertIn(f"--expect-sha256 {digest}", output)

        legacy["profiles"]["zzz-late-edit"] = {
            "harness": "codex",
            "executable": "codex",
            "model": "gpt-late",
            "effort": "medium",
        }
        edited = json.dumps(legacy).encode("utf-8")
        path.write_bytes(edited)
        original = path.read_bytes()
        before = path.stat()

        stale = self.run_cli(
            "migrate", "--accept", "--expect-sha256", digest, "--config", str(path), cwd=self.tmp
        )

        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("preview again", stale.stderr)
        self.assert_untouched(path, original, before)

    def test_version_one_migration_refuses_read_only_target_even_with_writable_parent(self):
        _, legacy = self.legacy_default()
        path = self.write_config(legacy, "read-only.json")
        path.chmod(0o444)
        original = path.read_bytes()
        before = path.stat()

        proc = self.run_cli("migrate", "--accept", "--config", str(path), cwd=self.tmp)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no write bit", proc.stderr.lower())
        self.assert_untouched(path, original, before)

    def test_version_one_migration_refuses_hard_linked_target(self):
        _, legacy = self.legacy_default()
        path = self.write_config(legacy, "hard-linked.json")
        sibling = self.tmp / "hard-linked-peer.json"
        os.link(path, sibling)
        original = path.read_bytes()
        before = path.stat()

        proc = self.run_cli("migrate", "--accept", "--config", str(path), cwd=self.tmp)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("hard link", proc.stderr.lower())
        self.assert_untouched(path, original, before)
        self.assertEqual(sibling.read_bytes(), original)
        self.assertEqual(path.stat().st_nlink, 2)

    def test_symlink_migration_applies_target_filesystem_guards(self):
        default_path, legacy = self.legacy_default()
        shared = self.tmp / "shared-read-only.json"
        shared.write_text(json.dumps(legacy), encoding="utf-8")
        shared.chmod(0o444)
        original = shared.read_bytes()
        default_path.unlink()
        default_path.symlink_to(shared)

        proc = self.run_cli("migrate", "--accept")

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no write bit", proc.stderr.lower())
        self.assertTrue(default_path.is_symlink())
        self.assertEqual(shared.read_bytes(), original)

        shared.chmod(0o644)
        peer = self.tmp / "shared-hard-link.json"
        os.link(shared, peer)
        hard_linked = self.run_cli("migrate", "--accept")
        self.assertNotEqual(hard_linked.returncode, 0)
        self.assertIn("hard link", hard_linked.stderr.lower())
        self.assertTrue(default_path.is_symlink())
        self.assertEqual(shared.read_bytes(), original)
        self.assertEqual(peer.read_bytes(), original)

    def test_planning_reviewer_must_use_codex(self):
        _, current = self.init_default()
        current["workflows"]["planning"]["reviewer"] = "claude-opus-xhigh"
        path = self.write_config(current, "non-codex-reviewer.json")

        proc = self.run_cli("validate", "--config", str(path), cwd=self.tmp)

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("workflow=planning worker=reviewer", proc.stderr)
        self.assertIn("not compatible", proc.stderr)

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
        self.assertEqual(
            set(agents_config.WORKFLOW_SCHEMA_VERSION),
            set(agents_config.COMPATIBLE_HARNESSES),
            "a workflow without a schema version silently lands in the legacy migration view",
        )
        for workflow, workers in agents_config.COMPATIBLE_HARNESSES.items():
            self.assertEqual(
                agents_config.WORKFLOW_WORKERS[workflow],
                tuple(workers),
                f"{workflow} worker order must follow the compatibility rules",
            )
        self.assertEqual(agents_config.DEFAULT_CONFIG["workflows"].keys(), agents_config.COMPATIBLE_HARNESSES.keys())

    def test_independently_shipped_clis_remain_equivalent(self):
        if not SIBLING_SCRIPT_DIRS:
            self.skipTest("sibling skill is not present in this independent installation")
        own_test = Path(__file__).resolve()
        own_script_bytes = SCRIPT.read_bytes()
        own_test_bytes = own_test.read_bytes()
        first_path = self.tmp / "from-first.json"
        first = self.run_cli("init", "--config", str(first_path), cwd=self.tmp)
        self.assertEqual(first.returncode, 0, first.stderr)
        shown_first = self.run_cli("show-resolved", "--config", str(first_path), cwd=self.tmp)
        self.assertEqual(shown_first.returncode, 0, shown_first.stderr)
        for sibling_dir in SIBLING_SCRIPT_DIRS:
            sibling = sibling_dir / "agents_config.py"
            with self.subTest(sibling=sibling_dir.parent.name):
                self.assertEqual(own_script_bytes, sibling.read_bytes(), "vendored configuration CLIs drifted")
                self.assertEqual(own_test_bytes, (sibling_dir / own_test.name).read_bytes(), "vendored configuration tests drifted")
                shown_sibling = self.run_cli("show-resolved", "--config", str(first_path), cwd=self.tmp, script=sibling)
                self.assertEqual(shown_first.returncode, shown_sibling.returncode)
                self.assertEqual(shown_first.stdout, shown_sibling.stdout)
                self.assertEqual(shown_first.stderr, shown_sibling.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
