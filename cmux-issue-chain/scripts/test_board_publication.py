"""Command decoration remains fail-soft even when the state snapshot cannot be read."""
import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_briefing
import run_state


class BoardPublicationTests(unittest.TestCase):
    def test_init_board_uses_the_created_run_directory(self):
        for explicit in (None, "chosen-run"):
            with self.subTest(explicit=explicit), tempfile.TemporaryDirectory() as directory:
                args = run_state.build_parser().parse_args([
                    "init", "--tracker", "/elsewhere/2024-02-29-orders-export",
                    "--issue", "ISSUE-001", "--runs-root", directory,
                    *(["--run-id", explicit] if explicit else []),
                ])
                tracker = Path(args.tracker)
                issue = SimpleNamespace(id="ISSUE-001", type="HITL", path=str(tracker / "issues/ISSUE-001.md"),
                                        to_dict=lambda: {"id": "ISSUE-001", "type": "HITL"})
                with patch.object(run_state, "load_issues", return_value={"ISSUE-001": issue}), \
                        patch.object(run_state, "resolve_workspace_id", return_value=None), \
                        patch.object(run_state, "capture_baseline", return_value={}), \
                        patch.object(run_state, "blocker_status", return_value={}), \
                        patch.object(run_state, "issue_ready", return_value=False), \
                        patch.object(run_briefing, "publish_board") as publish, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(run_state.run_command(args), 0)
                run_dir = Path(output.getvalue().strip())
                self.assertTrue((run_dir / "state.json").is_file())
                publish.assert_called_once_with(run_dir, args.cmux_cmd)
                if explicit:
                    self.assertEqual(run_dir.name, explicit)
                else:
                    self.assertTrue(run_dir.name.endswith("-chain-orders-export-issue-001"))

    def test_unreadable_initial_snapshot_preserves_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state.json').write_text('{}')
            args = argparse.Namespace(command='prepare', run_dir=directory, cmux_cmd=None)
            output, errors = io.StringIO(), io.StringIO()
            def command(args):
                print('original output')
                (root / 'events.jsonl').write_text('original event\n')
                return 7
            with patch.object(Path, 'read_bytes', side_effect=PermissionError('snapshot denied')), \
                    patch.object(run_state, 'dispatch_command', side_effect=command) as dispatch, \
                    patch.object(run_briefing, 'publish_board') as publish, \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(run_state.run_command(args), 7)
            dispatch.assert_called_once_with(args)
            publish.assert_not_called()
            self.assertEqual(output.getvalue(), 'original output\n')
            self.assertEqual(errors.getvalue(), 'sidebar board not updated: snapshot denied\n')
            self.assertEqual((root / 'state.json').read_text(), '{}')
            self.assertEqual((root / 'events.jsonl').read_text(), 'original event\n')

    def test_change_no_change_late_binding_and_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'state.json'
            for mode in ('unchanged', 'changed', 'late', 'force', 'explicit'):
                with self.subTest(mode=mode):
                    path.write_text('before')
                    with patch.object(run_briefing, 'publish_board') as publish:
                        with run_briefing.BoardPublication(None if mode == 'late' else root) as board:
                            if mode == 'late':
                                board.bind(root)
                            if mode in ('changed', 'late', 'explicit'):
                                path.write_text('after')
                            if mode == 'force':
                                board.force = True
                            if mode == 'explicit':
                                board.publish()
                                board.publish()
                        self.assertEqual(publish.call_count, int(mode != 'unchanged'))

    def test_post_read_and_publish_failures_preserve_original_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state.json').write_text('before')
            for where in ('read', 'publish'):
                with self.subTest(where=where):
                    errors = io.StringIO()
                    original = SystemExit(9)
                    with patch.object(run_briefing, 'publish_board', side_effect=SystemExit('offline')) as publish, \
                            contextlib.redirect_stderr(errors):
                        with self.assertRaises(SystemExit) as caught:
                            with run_briefing.BoardPublication(root) as board:
                                if where == 'read':
                                    board._read = lambda: (_ for _ in ()).throw(PermissionError('denied'))
                                else:
                                    board.force = True
                                raise original
                    self.assertIs(caught.exception, original)
                    self.assertEqual(errors.getvalue(), 'sidebar board not updated: ' + ('denied' if where == 'read' else 'offline') + '\n')
                    self.assertEqual(publish.call_count, int(where == 'publish'))


if __name__ == '__main__':
    unittest.main()
