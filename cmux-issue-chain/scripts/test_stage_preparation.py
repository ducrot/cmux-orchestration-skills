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


def file_contents(root: Path) -> dict[Path, bytes]:
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class PreparedStageCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.trust_home = self.root / "trust-home"
        self.trust_home.mkdir()
        (self.trust_home / ".claude.json").write_text(json.dumps({
            "projects": {str(self.repo.resolve()): {"hasTrustDialogAccepted": True}}
        }))
        (self.trust_home / "config.toml").write_text(
            f'[projects.{json.dumps(str(self.repo.resolve()))}]\ntrust_level = "trusted"\n'
        )
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
            "HOME": str(self.trust_home),
            "CLAUDE_CONFIG_DIR": str(self.trust_home),
            "CODEX_HOME": str(self.trust_home),
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

    def test_version_one_config_requires_explicit_migration_before_launch_preparation(self):
        legacy = json.loads(self.config_path.read_text(encoding="utf-8"))
        legacy["schema_version"] = 1
        del legacy["workflows"]["planning"]
        legacy["workflows"]["issue-chain"]["implement"] = "codex-astra-medium"
        legacy_bytes = json.dumps(legacy).encode("utf-8")
        self.config_path.write_bytes(legacy_bytes)

        proc = self.init_for("migrated-v1")

        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self.config_path.read_bytes(), legacy_bytes)
        self.assertIn("Read-only schema-v1 migration preview", proc.stderr)
        self.assertIn("Acceptance command:", proc.stderr)
        self.assert_no_launchable_run(self.runs_root / "migrated-v1")

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
        state = json.loads((self.runs_root / "migrated-v1" / "state.json").read_text(encoding="utf-8"))
        snapshot = json.loads((self.runs_root / "migrated-v1" / state["prepared_stage"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(snapshot["selected_worker"]["profile"], "codex-astra-medium")

    def test_default_run_identity_and_deliverables(self):
        result = self.run_state("init", "--tracker", ".scratch/tracker", "--issue", "ISSUE-001", "--no-workspace")
        self.assertEqual(result.returncode, 0, result.stderr)
        run_dir = self.repo / result.stdout.strip()
        self.assertRegex(run_dir.name, r"^chain-issue-001-\d{4}-\d{2}-\d{2}-\d{4}$")
        state = json.loads((run_dir / "state.json").read_text())
        self.assertEqual(state["workflow"], "issue-chain")
        self.assertEqual(state["layout_version"], 1)
        self.assertEqual(state["deliverables"], {"tracker": ".scratch/tracker", "issue": ".scratch/tracker/issues/ISSUE-001-prepared.md"})

    def test_legacy_run_refuses_preparation_and_lifecycle_without_writes(self):
        self.assertEqual(self.init().returncode, 0)
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text())
        del state["workflow"]
        del state["layout_version"]
        state_path.write_text(json.dumps(state))
        before = file_contents(self.run_dir)
        for result in (self.init(), self.prepare("implement"),
                       self.run_state("complete", "--run-dir", str(self.run_dir)),
                       self.pane("launch", "--run-dir", str(self.run_dir), "--role", "implement", "--pass", "1", "--anchor", "ANCHOR")):
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported legacy layout", result.stderr)
        inspected = self.run_state("status", "--run-dir", str(self.run_dir))
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertIn("unsupported legacy layout", inspected.stdout)
        self.assertEqual(before, file_contents(self.run_dir))
        self.assertFalse(self.cmux_log.exists())
        state_path.write_text("[]")
        inspected = self.run_state("status", "--run-dir", str(self.run_dir))
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertIn("unsupported legacy layout", inspected.stdout)

    def script(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPT_DIR / name), *map(str, args)],
                              cwd=self.repo, env=self.env(), capture_output=True, text=True)

    def triage_fixture(self, *, followup=True, numeric=False):
        from test_parse_report import report, verdict, DRAFT
        tracker = self.repo / ".scratch" / "tracker"
        if numeric:
            (tracker / "issues" / "ISSUE-001-prepared.md").rename(tracker / "issues" / "01-prepared.md")
        self.assertEqual(self.init().returncode, 0)
        for stage, following in (("implement", "simplify"), ("simplify", "review"), ("review", "test")):
            self.assertEqual(self.gate(stage, following).returncode, 0)
        (self.repo / "a.py").write_text("print('fixture')\n")
        (self.run_dir / "reports" / "review-1.md").write_text(report(Recommendations=
            "- Counter-proposal: simplify-1 Not Applied 1; extract the duplicated helper.\n"
            "- Add a separate dashboard status view.\n- Human should remove the browser artifacts.\n"))
        (self.run_dir / "reports" / "simplify-1.md").write_text(report(**{"Not Applied": "- Keep the helper inline until measured."}))
        collected = self.script("collect_recommendations.py", "--run-dir", self.run_dir, "--pass", "1")
        self.assertEqual(collected.returncode, 0, collected.stderr)
        self.assertEqual(self.gate("test", "triage").returncode, 0)
        prepared = self.prepare("triage")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(len(self.read_snapshot()["resolved_profiles"]), 5)
        items = self.run_dir / "triage-items-1.md"
        rendered = self.script("render_prompt.py", "--tracker", tracker, "--issue", "ISSUE-001",
                               "--role", "triage", "--pass", "1", "--run-dir", self.run_dir, "--items-file", items,
                               "--context-file", self.run_dir / "reports" / "review-1.md")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        first = verdict(Files="`a.py`", Supersedes="simplify-1 Not Applied 1", **{
            "Verdict": "accepted" if followup else "recorded", "Follow-up eligible": "yes" if followup else "no"})
        second = verdict(Title='New "status" view', **{"Follow-up eligible": "no", "Files": "none"}).replace("- R1", "- R2")
        third = verdict(Verdict="for-the-human", **{"Follow-up eligible": "no", "Files": "none"}).replace("- R1", "- R3")
        (self.run_dir / "reports" / "triage-1.md").write_text(report(Verdicts=first+second+third))
        artifacts = self.run_dir / "artifacts" / "triage-1"
        artifacts.mkdir(parents=True)
        (artifacts / "issue-draft-R2.md").write_text(DRAFT.replace("# A useful change", '# New "status" view'))
        parsed = self.script("parse_report.py", self.run_dir / "reports" / "triage-1.md", "--items-file", items)
        self.assertEqual(parsed.returncode, 0, parsed.stdout+parsed.stderr)
        # Capture event fixture: no commits or index changes are needed for this CLI walk.
        captured = self.run_state("event", "--run-dir", str(self.run_dir), "--type", "tree.snapshot",
                                  "--message", "report-captured triage-1")
        self.assertEqual(captured.returncode, 0)
        return tracker

    def test_triage_modes_and_legacy_default(self):
        self.assertEqual(self.init().returncode, 0)
        state = self.read_state()
        self.assertEqual(state["triage_mode"], "autonomous")
        self.assertEqual(state["chain"], ["implement", "simplify", "review", "test", "triage"])
        self.assertEqual(self.read_snapshot()["resolved_profiles"]["triage"]["profile"], "claude-opus-high")
        before = file_contents(self.run_dir)
        self.assertNotEqual(self.init("--human-triage").returncode, 0)
        self.assertEqual(file_contents(self.run_dir), before)
        self.assertEqual(self.init_for("human", "--human-triage").returncode, 0)
        human = self.runs_root / "human"
        state = json.loads((human / "state.json").read_text())
        self.assertEqual(state["triage_mode"], "human")
        self.assertEqual(state["chain"], ["implement", "simplify", "review", "test"])
        for legacy in (False, True):
            if legacy:
                state.pop("triage_mode")
                (human / "state.json").write_text(json.dumps(state))
                self.run_state("event", "--run-dir", str(human), "--type", "decision.human", "--message", "authorize orchestrator triage")
            before = file_contents(human)
            refused = self.run_state("prepare", "--run-dir", str(human), "--stage", "triage", "--pass", "1")
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("human", refused.stderr)
            self.assertEqual(file_contents(human), before)
            shown = self.run_state("status", "--run-dir", str(human))
            self.assertEqual(json.loads(shown.stdout)["state"]["triage_mode"], "human")

    def test_publish_triage_end_to_end_and_followup_prompts(self):
        tracker = self.triage_fixture()
        proc = self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        publication = json.loads(proc.stdout)
        self.assertEqual(publication["next_stage"], "implement")
        self.assertEqual(publication["created_issues"], ["ISSUE-002"])
        issue = next((tracker / "issues").glob("ISSUE-002-*.md"))
        body = issue.read_text()
        self.assertIn('title: "New \'status\' view"', body)
        self.assertIn("id: ISSUE-002\n", body)
        self.assertIn("type: AFK\nstatus: todo\nlabels: [ready-for-agent]", body)
        self.assertEqual(sum(line.startswith("# ") for line in body.splitlines()), 1)
        ready = self.script("issue_state.py", "ready", "--tracker", tracker)
        self.assertEqual(ready.returncode, 0, ready.stderr)
        self.assertIn("ISSUE-002", ready.stdout)
        ledger = (tracker / "decisions.md").read_text()
        self.assertIn("[triage-worker verdict, run prepared-run, gate advance]", ledger)
        self.assertIn("FOR-THE-HUMAN (open)", ledger)
        self.assertIn("Supersedes: simplify-1 Not Applied 1.", ledger)
        audit = [json.loads(line) for line in (self.run_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e["type"] == "recommendations.triaged" for e in audit), 3)
        self.assertEqual(audit[-1]["type"], "triage.published")
        self.assertEqual(audit[-1]["data"]["counts"]["accepted"], 2)
        self.assertEqual(audit[-1]["data"]["for_the_human"], ["R3"])
        before = file_contents(self.repo)
        self.assertNotEqual(self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "1").returncode, 0)
        self.assertEqual(file_contents(self.repo), before)
        self.assertEqual(self.gate("triage", "implement").returncode, 0)
        self.assertEqual(self.prepare("implement", 2).returncode, 0)
        result = self.script("render_prompt.py", "--tracker", tracker, "--issue", "ISSUE-001", "--role", "implement",
                             "--pass", "2", "--run-dir", self.run_dir, "--followup-file", self.run_dir / "followup-items.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = (self.run_dir / "prompts" / "implement-2.md").read_text()
        self.assertIn("Counter-proposal: simplify-1", prompt)
        self.assertIn("Triage reason: Measured duplication", prompt)
        self.assertIn("```markdown\n- Counter-proposal: simplify-1", prompt)
        self.assertEqual(self.gate("implement", "review").returncode, 0)
        self.assertEqual(self.prepare("review", 2).returncode, 0)
        result = self.script("render_prompt.py", "--tracker", tracker, "--issue", "ISSUE-001", "--role", "review",
                             "--pass", "2", "--run-dir", self.run_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = (self.run_dir / "prompts" / "review-2.md").read_text()
        self.assertIn(ledger.strip(), prompt)
        self.assertIn("Only non-opted-out runs produce the marker", prompt)

    def test_publish_triage_two_completes_followup_cli_walk(self):
        self.triage_two_cli_walk(existing_followup=True)

    def test_publish_triage_two_does_not_create_followup_file(self):
        self.triage_two_cli_walk(existing_followup=False)

    def triage_two_cli_walk(self, *, existing_followup):
        from collect_recommendations import read_items
        from test_parse_report import report, verdict, DRAFT
        tracker = self.triage_fixture()
        published = self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "1")
        self.assertEqual(published.returncode, 0, published.stderr)
        self.assertEqual(json.loads(published.stdout)["next_stage"], "implement")
        followup = self.run_dir / "followup-items.md"
        original_followup = followup.read_bytes()
        self.assertEqual(self.gate("triage", "implement").returncode, 0)
        self.assertEqual(self.prepare("implement", 2).returncode, 0)
        implement = self.run_dir / "reports" / "implement-2.md"
        implement.write_text(report(**{"Not Applied": "- R1: helper has changed; keep current code."}))
        self.assertEqual(self.script("parse_report.py", implement).returncode, 0)
        self.assertEqual(self.gate("implement", "test").returncode, 0)
        self.assertEqual(self.prepare("test", 2).returncode, 0)
        test = self.run_dir / "reports" / "test-2.md"
        test.write_text(report(Recommendations="- Add a follow-up diagnostics view."))
        self.assertEqual(self.script("parse_report.py", test).returncode, 0)
        collected = self.script("collect_recommendations.py", "--run-dir", self.run_dir, "--pass", "2")
        self.assertEqual(collected.returncode, 0, collected.stderr)
        items = self.run_dir / "triage-items-2.md"
        parsed_items = read_items(items)
        self.assertEqual(parsed_items["scanned_reports"], [str(implement), str(test)])
        self.assertEqual([i["source"] for i in parsed_items["items"]], ["test-2"])
        self.assertIn("Add a follow-up diagnostics view.", parsed_items["items"][0]["text"])
        self.assertEqual(self.gate("test", "triage").returncode, 0)
        self.assertEqual(self.prepare("triage", 2).returncode, 0)
        contexts = sorted((self.run_dir / "reports").glob("*.md")) + [followup]
        rendered = self.script("render_prompt.py", "--tracker", tracker, "--issue", "ISSUE-001",
                               "--role", "triage", "--pass", "2", "--run-dir", self.run_dir, "--items-file", items,
                               *[arg for path in contexts for arg in ("--context-file", path)])
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        triage_report = self.run_dir / "reports" / "triage-2.md"
        triage_report.write_text(report(Verdicts=verdict(Source="test-2", **{"Follow-up eligible": "no", "Files": "none"})))
        artifacts = self.run_dir / "artifacts" / "triage-2"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "issue-draft-R1.md").write_text(DRAFT)
        self.assertEqual(self.script("parse_report.py", triage_report, "--items-file", items).returncode, 0)
        self.assertEqual(self.run_state("event", "--run-dir", str(self.run_dir), "--type", "tree.snapshot",
                                      "--message", "report-captured triage-2").returncode, 0)
        # Publication must neither overwrite an existing follow-up file nor create a new one.
        if not existing_followup:
            followup.unlink()
        published = self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "2")
        self.assertEqual(published.returncode, 0, published.stderr)
        result = json.loads(published.stdout)
        self.assertIsNone(result["next_stage"])
        self.assertIsNone(result["followup_file"])
        self.assertEqual(result["followup_items"], [])
        self.assertEqual(result["created_issues"], ["ISSUE-003"])
        if existing_followup:
            self.assertEqual(followup.read_bytes(), original_followup)
        else:
            self.assertFalse(followup.exists())
        ledger = (tracker / "decisions.md").read_text()
        self.assertIn("triage-2 R1 (test-2)", ledger)
        self.assertIn("[triage-worker verdict, run prepared-run, gate advance]", ledger)
        audit = [json.loads(line) for line in (self.run_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual(audit[-1]["type"], "triage.published")
        self.assertEqual(audit[-1]["data"]["pass"], 2)
        self.assertEqual(audit[-2]["type"], "recommendations.triaged")
        self.assertEqual(audit[-2]["data"]["issue"], "ISSUE-003")
        self.assertEqual(self.run_state("gate", "--run-dir", str(self.run_dir), "--stage", "triage",
                                      "--decision", "advance", "--reason", "triage-2 published").returncode, 0)
        self.assertEqual(self.run_state("complete", "--run-dir", str(self.run_dir)).returncode, 0)
        self.assertEqual(json.loads((self.run_dir / "state.json").read_text())["current_stage"], "done")
        before = file_contents(self.repo)
        self.assertNotEqual(self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "3").returncode, 0)
        self.assertEqual(file_contents(self.repo), before)

    def test_triage_items_cli_refusals_do_not_write(self):
        tracker = self.triage_fixture()
        before = file_contents(self.run_dir)
        for role, pass_num, items in (("triage", "1", []), ("triage", "2", ["--items-file", self.run_dir / "triage-items-1.md"]),
                                       ("implement", "1", ["--items-file", self.run_dir / "triage-items-1.md"])):
            result = self.script("render_prompt.py", "--tracker", tracker, "--issue", "ISSUE-001", "--role", role,
                                 "--pass", pass_num, "--run-dir", self.run_dir, *items)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(file_contents(self.run_dir), before)

    def test_publish_uses_maximum_number_and_refuses_duplicate_draft_slugs(self):
        from test_parse_report import report, verdict, DRAFT
        tracker = self.triage_fixture()
        (tracker / "issues" / "ISSUE-009-later.md").write_text(ISSUE.replace("ISSUE-001", "ISSUE-009"))
        report_path = self.run_dir / "reports" / "triage-1.md"
        saved = report_path.read_text()
        body = verdict(**{"Follow-up eligible": "no"})
        report_path.write_text(report(Verdicts=body.replace("- R1", "- R2")+body.replace("- R1", "- R3")+
            verdict(Files="`a.py`", Supersedes="simplify-1")))
        draft = self.run_dir / "artifacts" / "triage-1" / "issue-draft-R3.md"
        draft.write_text('# New "status" view\n' + DRAFT.split("\n", 1)[1])
        before = file_contents(self.repo)
        failed = self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "1")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("slug collision", failed.stderr)
        self.assertEqual(file_contents(self.repo), before)
        report_path.write_text(saved)
        success = self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "1")
        self.assertEqual(success.returncode, 0, success.stderr)
        self.assertEqual(json.loads(success.stdout)["created_issues"], ["ISSUE-010"])
        self.assertEqual(len(list((tracker / "issues").glob("ISSUE-010-*.md"))), 1)

    def test_publish_numeric_naming_and_no_followup(self):
        tracker = self.triage_fixture(followup=False, numeric=True)
        proc = self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNone(json.loads(proc.stdout)["next_stage"])
        self.assertEqual(len(list((tracker / "issues").glob("02-*.md"))), 1)
        self.assertFalse((self.run_dir / "followup-items.md").exists())

    def test_publish_failures_write_nothing(self):
        tracker = self.triage_fixture()
        baseline = file_contents(self.repo)
        report = self.run_dir / "reports" / "triage-1.md"
        draft = self.run_dir / "artifacts" / "triage-1" / "issue-draft-R2.md"
        def write_state(**changes):
            state = self.read_state()
            state.update(changes)
            (self.run_dir / "state.json").write_text(json.dumps(state))
        changes = {
            "non-advance": lambda: report.write_text(report.read_text().replace("NO FINDINGS", "FINDINGS")),
            "hash mismatch": lambda: (self.run_dir / "triage-items-1.md").write_text("tampered"),
            "capture": lambda: (self.run_dir / "events.jsonl").write_text("\n".join(line for line in (self.run_dir / "events.jsonl").read_text().splitlines() if 'report-captured triage-1' not in line)+"\n"),
            "human mode": lambda: write_state(triage_mode="human"),
            "wrong stage": lambda: write_state(current_stage="test"),
            "unknown blocker": lambda: draft.write_text(draft.read_text()+"\n## Blocked by\n- ISSUE-999\n"),
            "slug collision": lambda: draft.write_text(draft.read_text().replace('# New "status" view', '# Prepared')),
            "orphan target": lambda: (tracker / "issues" / "ISSUE-002-new-status-view.md").mkdir(),
        }
        for name, mutate in changes.items():
            with self.subTest(name=name):
                mutate()
                before = file_contents(self.repo)
                proc = self.run_state("publish-triage", "--run-dir", str(self.run_dir), "--pass", "1")
                self.assertNotEqual(proc.returncode, 0, proc.stdout)
                self.assertEqual(file_contents(self.repo), before)
                for path, content in baseline.items():
                    (self.repo / path).write_bytes(content)
                target = tracker / "issues" / "ISSUE-002-new-status-view.md"
                if target.is_dir():
                    target.rmdir()

    def test_missing_trust_fails_before_snapshot_or_pane(self):
        (self.trust_home / "config.toml").write_text("")
        result = self.init()
        self.assertNotEqual(result.returncode, 0)
        for value in ("codex", str(self.repo.resolve()), str(self.trust_home / "config.toml"), "field=preflight"):
            self.assertIn(value, result.stderr)
        self.assertFalse((self.run_dir / "state.json").exists())
        self.assertFalse((self.run_dir / "stage-snapshots").exists())
        self.assertFalse(self.cmux_log.exists())

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
        self.assertEqual(set(snapshot["resolved_profiles"]), {"implement", "simplify", "review", "test", "triage"})
        selected = snapshot["selected_worker"]
        self.assertEqual(selected["profile"], "codex-astra-xhigh")
        self.assertEqual(selected["model"], "gpt-6-astra")
        self.assertEqual(selected["effort"], "xhigh")
        self.assertEqual(selected["detected_version"], "codex 99.1-test")
        self.assertEqual(selected["entitlement"]["status"], "unverified")
        self.assertEqual(selected["argv"][0], "codex")
        self.assertEqual(selected["requested_executable"], "codex")
        self.assertEqual(selected["resolved_executable"], str(self.bin_dir / "codex"))
        self.assertEqual(
            selected["argv"][1:],
            [
                "-s", "workspace-write",
                "-c", "sandbox_workspace_write.network_access=true",
                "-c", 'sandbox_workspace_write.writable_roots=["~/.ddev"]',
                "--ask-for-approval", "on-request",
                "-c", "approvals_reviewer=auto_review",
                "-c", "check_for_update_on_startup=false",
                "-c", "tui.whimsy=false",
                "--model", "gpt-6-astra",
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
        self.assertEqual(len(probes), 3, "duplicate worker assignments must share one profile probe")
        self.assertEqual({call["program"] for call in probes}, {"claude", "codex"})
        codex = next(call["argv"] for call in probes if call["program"] == "codex")
        claude = next(call["argv"] for call in probes if call["program"] == "claude")
        self.assertIn("exec", codex)
        self.assertIn("read-only", codex)
        self.assertIn('approval_policy="never"', codex)
        self.assertIn("tui.whimsy=false", codex)
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

    def test_launch_identity_and_preflight_both_keep_the_name_the_harness_was_found_as(self):
        alias_dir = self.root / "linked"
        alias_dir.mkdir()
        alias = alias_dir / "claude"
        alias.symlink_to(self.bin_dir / "claude")

        proc = self.init("--executable", f"review={alias}")

        self.assertEqual(proc.returncode, 0, proc.stderr)
        review = self.read_snapshot()["resolved_profiles"]["review"]
        self.assertEqual(review["argv"][0], str(alias))
        self.assertEqual(review["requested_executable"], str(alias))
        # Version-manager shims dispatch on the name they were invoked under, so neither the
        # launch nor the preflight may substitute the realpath. It is kept as audit data only.
        self.assertEqual(review["resolved_executable"], str(alias))
        self.assertEqual(review["real_path"], str((self.bin_dir / "claude").resolve()))

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
        from orchestrator_lib import delivery_text
        from render_prompt import render
        prompt = self.run_dir / "prompts/simplify-1.md"
        prompt.parent.mkdir(exist_ok=True)
        prompt.write_text(render("simplify", "ISSUE-001", "# Test issue", {},
                                 prompt_path=prompt,
                                 artifact_path=self.run_dir / "artifacts/simplify-1"))
        started = self.pane(
            "start-agent", "--run-dir", str(self.run_dir),
            "--surface", "SURFACE", "--role", "simplify", "--pass", "1",
            "--settle-seconds", "0",
        )

        self.assertEqual(started.returncode, 0, started.stderr)
        cmux_calls = [json.loads(line) for line in self.cmux_log.read_text().splitlines()]
        command = cmux_calls[0][-1]
        self.assertEqual(shlex.split(command), ["CMUX_AGENT_MANAGED_SUBAGENT=1", *prepared_argv,
                                               delivery_text(str(prompt.relative_to(self.repo)))])
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
            [
                str(self.bin_dir / "claude"),
                "--model", "test/model", "--effort", "max",
                "--permission-mode", "auto",
            ],
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
        self.assertEqual(self.read_snapshot()["selected_worker"]["model"], "gpt-6-astra")
        self.assertEqual(self.read_snapshot()["effective_overrides"], {})

    def test_incompatible_override_invalidates_previous_snapshot_before_pane_creation(self):
        initialized = self.init()
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(self.gate("implement", "simplify").returncode, 0)

        # Every issue-chain worker accepts every supported harness, so the refusal that must
        # precede pane creation is an unsupported adapter rather than a worker mismatch.
        prepared = self.prepare("simplify", 1, "--harness", "simplify=hermes")

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
        self.assertEqual(self.read_snapshot()["selected_worker"]["model"], "gpt-6-astra")

    def test_init_records_the_invocation_and_reinit_keeps_it(self):
        prompt = "/cmux-issue-chain .scratch/tracker ISSUE-001 bitte Tests zuerst"
        self.assertEqual(self.init("--invocation", prompt).returncode, 0)
        self.assertEqual(self.read_state()["invocation"], prompt)

        self.assertEqual(self.init("--invocation", prompt).returncode, 0)
        changed = self.init("--invocation", "/cmux-issue-chain other")

        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("different --invocation", changed.stderr)
        self.assertEqual(self.read_state()["invocation"], prompt)

    def test_reinit_adopts_an_invocation_the_run_never_recorded(self):
        self.assertEqual(self.init().returncode, 0)
        self.assertIsNone(self.read_state()["invocation"])

        adopted = self.init("--invocation", "/cmux-issue-chain later")

        self.assertEqual(adopted.returncode, 0, adopted.stderr)
        self.assertEqual(self.read_state()["invocation"], "/cmux-issue-chain later")
        events = (self.run_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"type": "run.invocation"', events)

    def test_reinit_restores_a_deleted_runs_root_ignore(self):
        self.assertEqual(self.init().returncode, 0)
        ignore = self.runs_root / ".gitignore"
        ignore.unlink()

        again = self.init()

        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(ignore.read_text(encoding="utf-8").strip(), "*")


if __name__ == "__main__":
    unittest.main(verbosity=2)
