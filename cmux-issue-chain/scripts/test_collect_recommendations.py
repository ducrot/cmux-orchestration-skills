#!/usr/bin/env python3
"""Collector CLI regression tests in an isolated Git repository."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collect_recommendations import diff_files, read_items

SCRIPT = Path(__file__).with_name("collect_recommendations.py")


class CollectorCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / ".gitignore").write_text("run/\n")
        self.run = self.repo / "run"
        (self.run / "reports").mkdir(parents=True)
        (self.run / "state.json").write_text(json.dumps({"workflow": "issue-chain", "layout_version": 1,
            "run_id": "test-run", "issue": {"id": "ISSUE-001"}}))

    def cli(self, pass_num=1):
        return subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(self.run), "--pass", str(pass_num)],
                              cwd=self.repo, capture_output=True, text=True)

    def write_report(self, stem, text):
        (self.run / "reports" / (stem + ".md")).write_text(text)

    def contents(self):
        return {p.relative_to(self.run): p.read_bytes() for p in self.run.rglob("*") if p.is_file()}

    def test_verbatim_order_counter_proposals_and_roundtrip(self):
        entry = "- Keep this exact text.\n  Continuation with `literal`.\n  - Nested item\n\n"
        self.write_report("implement-1", "## Recommendations\nLeading prose.\n\n" + entry + "* Another item\n+ Plus\n1. Numbered\n## Notes\nnot collected\n")
        self.write_report("simplify-1", "## Not Applied\n- Keep validators separate: evidence.\n\n## Recommendations\n- None\n")
        self.write_report("review-1", "## Recommendations\n- Counter-proposal: simplify-1 keep validators.\n- Counter-proposal: simplify-10 only.\n")
        self.write_report("test-1", "## Recommendations\nN/A\n")
        self.write_report("implement-2", "## Recommendations\n" + entry)
        self.write_report("triage-1", "## Recommendations\n- Do not collect me\n")
        self.write_report("notes", "## Recommendations\n- Nor me\n")
        (self.repo / "new file.txt").write_text("untracked")
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["item_count"], 8)
        path = self.run / "triage-items-1.md"
        items = read_items(path)
        self.assertEqual([i["id"] for i in items["items"]], [f"R{n}" for n in range(1, 9)])
        self.assertEqual([i["source"] for i in items["items"]], ["implement-1"]*5 + ["review-1"]*2 + ["implement-2"])
        self.assertIn(entry, items["items"][1]["text"])
        self.assertIn(entry, items["items"][7]["text"])
        self.assertIn("Leading prose.\n\n", items["items"][0]["text"])
        self.assertIn("## Not Applied\n- Keep validators separate: evidence.\n\n", items["items"][5]["text"])
        self.assertEqual(items["items"][5]["kind"], "counter-proposal")
        self.assertIn("Earlier decision: not resolved by the collector", items["items"][6]["text"])
        self.assertIn("new file.txt", items["diff_files"])
        before = self.contents()
        again = self.cli()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout), data)
        self.assertEqual(self.contents(), before)
        path.write_text(path.read_text() + "tamper")
        before = self.contents()
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.contents(), before)

    def test_zero_items_is_idempotent_and_other_passes_refuse_without_writes(self):
        self.write_report("test-1", "## Recommendations\n- None\n")
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["item_count"], 0)
        self.assertIsNone(data["items_path"])
        self.assertIsNone(data["items_sha256"])
        self.assertFalse((self.run / "triage-items-1.md").exists())
        before = self.contents()
        self.assertEqual(self.cli().returncode, 0)
        for number in (0, 2, 3):
            self.assertNotEqual(self.cli(number).returncode, 0)
        self.assertEqual(self.contents(), before)
        audit = [json.loads(line) for line in (self.run / "events.jsonl").read_text().splitlines()]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["type"], "triage.collected")
        self.assertEqual(audit[0]["data"], data)

    def test_pass_two_only_scans_new_reports_and_keeps_counterproposal_context(self):
        self.write_report("simplify-1", "## Not Applied\n- Keep it separate.\n")
        self.write_report("review-1", "## Recommendations\n- Original item\n")
        self.assertEqual(self.cli().returncode, 0)
        self.write_report("implement-2", "## Not Applied\n- Cannot apply: changed context.\n")
        self.write_report("test-2", "## Recommendations\n- Counter-proposal: simplify-1 reconsider.\n")
        self.write_report("triage-1", "## Recommendations\n- Ignore triage\n")
        # Different run-dir spelling must not rescan the pass-1 reports.
        result = subprocess.run([sys.executable, str(SCRIPT), "--run-dir", "run", "--pass", "2"],
                                cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["item_count"], 1)
        self.assertEqual([Path(p).name for p in data["scanned_reports"]], ["implement-2.md", "test-2.md"])
        path = self.run / "triage-items-2.md"
        items = read_items(path)
        self.assertEqual(items["pass"], 2)
        self.assertFalse(items["followup_allowed"])
        self.assertIn("Follow-up pass allowed: no", path.read_text())
        self.assertIn("## Not Applied\n- Keep it separate.", items["items"][0]["text"])
        before = self.contents()
        self.assertEqual(self.cli(2).returncode, 0)
        self.assertNotEqual(self.cli(3).returncode, 0)
        self.assertEqual(before, self.contents())
        path.write_text(path.read_text() + "tamper")
        before = self.contents()
        self.assertNotEqual(self.cli(2).returncode, 0)
        self.assertEqual(before, self.contents())

    def test_pass_two_not_applied_alone_does_not_trigger_triage(self):
        self.write_report("review-1", "## Recommendations\n- Original item\n")
        self.assertEqual(self.cli().returncode, 0)
        self.write_report("implement-2", "## Not Applied\n- Cannot apply: changed context.\n")
        self.write_report("test-2", "## Recommendations\n- None\n")
        result = self.cli(2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["item_count"], 0)
        self.assertFalse((self.run / "triage-items-2.md").exists())
        before = self.contents()
        self.assertEqual(self.cli(2).returncode, 0)
        self.assertEqual(before, self.contents())

    def test_other_run_dir_spelling_still_matches_the_event(self):
        self.write_report("test-1", "## Recommendations\n- Keep me\n")
        self.assertEqual(self.cli().returncode, 0)
        before = self.contents()
        for spelling in ["run", "./run", str(self.repo / "run" / ".." / "run")]:
            result = subprocess.run([sys.executable, str(SCRIPT), "--run-dir", spelling, "--pass", "1"],
                                    cwd=self.repo, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.contents(), before)

    def test_orphan_items_file_refuses_without_writes(self):
        (self.run / "triage-items-1.md").write_text("orphan")
        before = self.contents()
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertEqual(self.contents(), before)

    def test_nul_status_keeps_both_rename_paths(self):
        # Exercise the porcelain seam without changing any index/HEAD, even in a fixture repo.
        status = subprocess.CompletedProcess([], 0, stdout=b"R  new name\0old name\0?? untracked\0 M changed\0")
        with patch("collect_recommendations.subprocess.run", return_value=status) as command:
            self.assertEqual(diff_files(), ["changed", "new name", "old name", "untracked"])
            self.assertEqual(command.call_args.args[0], ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"])


if __name__ == "__main__":
    unittest.main()
