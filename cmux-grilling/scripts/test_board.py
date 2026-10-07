"""Grilling board projection and real CLI transition regressions."""
import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import run_briefing as briefing
import run_state
import test_launch_wave as wave


class Board(unittest.TestCase):
    setUp = wave.PreparedLaunchWaveCli.setUp
    tearDown = wave.PreparedLaunchWaveCli.tearDown
    env = wave.PreparedLaunchWaveCli.env
    run_state = wave.PreparedLaunchWaveCli.run_state
    initialize_config = wave.PreparedLaunchWaveCli.initialize_config
    init_for = wave.PreparedLaunchWaveCli.init_for
    cmux_calls = wave.PreparedLaunchWaveCli.cmux_calls

    def assert_board(self, status, label, value, detail=None):
        calls = self.cmux_calls()
        self.assertIn(f'grilling · {status} · ', calls[-2][4])
        if detail:
            self.assertIn(detail, calls[-2][4])
        self.assertEqual(calls[-1], ['set-progress', str(float(value)), '--label', label, '--workspace', 'WORKSPACE'])

    def command(self, *args, fail=False):
        self.cmux_log.unlink(missing_ok=True)
        result = self.run_state(*args, env=self.env(BOARD_FAIL='1' if fail else '0'))
        self.assertEqual(result.returncode, 0, result.stderr)
        if fail:
            self.assertEqual(len(self.cmux_calls()), 1)
            self.assertEqual(result.stderr.count('sidebar board not updated'), 1)
            self.assertEqual(len(result.stderr.splitlines()), 1)
        return result

    def test_cli_rounds_walkthrough_and_recap(self):
        # Run the entire sequence with both working and failing decoration.
        self.cmux.write_text(self.cmux.read_text().replace('args = sys.argv[1:]', 'if os.environ.get("BOARD_FAIL") == "1": sys.exit(7)\nargs = sys.argv[1:]'))
        for fail in (False, True):
            run_id = 'board-' + str(fail)
            self.command('init', '--task', 'Board', '--run-id', run_id, '--runs-root', str(self.runs_root), '--workspace-id', 'WORKSPACE', fail=fail)
            directory = self.runs_root / run_id
            if not fail:
                self.assert_board('running', 'Round 1/4', 0)
            def gate(stage, decision='advance', next_stage=None):
                extra = ['--next-stage', next_stage] if next_stage else []
                self.command('gate', '--run-dir', str(directory), '--stage', stage, '--decision', decision, '--reason', 'test', *extra, fail=fail)
            gate('round-1-codebase')
            if not fail: self.assert_board('running', 'Round 1/4', 0)
            gate('round-1-web', next_stage='round-2')
            if not fail: self.assert_board('running', 'Round 2/4', .25)
            gate('round-2-web', 'blocked')
            if not fail: self.assert_board('blocked', 'Round 2/4', .25)
            gate('round-2-web', next_stage='finalize')
            if not fail: self.assert_board('running', 'Round 2/4', .5, 'finalize')
            gate('finalize')
            if not fail: self.assert_board('waiting', 'Round 2/4', 1)
            state = json.loads((directory / 'state.json').read_text())
            output = self.repo / state['output_dir']
            output.mkdir(parents=True, exist_ok=True)
            artifact = output / (run_id + '.json')
            entry = dict(id='D1', question='Which?', why_open='product', context='context', evidence=['source'], options=[dict(label='a', implication='a'), dict(label='b', implication='b')], recommendation='a', rationale='r', status='open')
            artifact.write_text(json.dumps({'open_decisions': [entry]}))
            markdown = output / (run_id + '.md')
            markdown.write_text('Result')
            self.command('complete', '--run-dir', str(directory), '--markdown', str(markdown), '--json', str(artifact), fail=fail)
            if not fail: self.assert_board('waiting', 'Round 2/4', 1, '1 open decisions')
            self.command('decision', '--run-dir', str(directory), '--artifact', str(artifact), '--id', 'D1', '--status', 'decided', '--decision', 'a', fail=fail)
            if not fail: self.assert_board('waiting', 'Round 2/4', 1, '0 open decisions')
            self.assertEqual(json.loads(artifact.read_text())['open_decisions'][0]['status'], 'decided')
            self.assertIn('grill.decision_recorded', (directory / 'events.jsonl').read_text())
            for command, extra in [('status', ['--run-dir', str(directory)]), ('pending-decisions', ['--output-dir', str(output)]), ('validate-artifact', ['--artifact', str(artifact)]), ('event', ['--run-dir', str(directory), '--type', 'grill.assumptions_triaged', '--message', 'reviewed'])]:
                self.command(command, *extra)
                self.assertEqual(self.cmux_calls(), [])
            recap = directory / 'recap.md'
            recap.write_text('Session complete.\n')
            self.cmux_log.unlink(missing_ok=True)
            result = subprocess.run([sys.executable, str(Path(briefing.__file__)), 'recap-show', '--run-dir', str(directory)], cwd=self.repo, env=self.env(BOARD_FAIL='1' if fail else '0'), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('run.recap', (directory / 'events.jsonl').read_text())
            if not fail: self.assert_board('done', 'Round 2/4', 1, '2 rounds, 0 open decisions')
            else:
                self.assertEqual(result.stderr.count('sidebar board not updated'), 1)
                self.assertEqual(sum(c[0] == 'workspace-action' for c in self.cmux_calls()), 1)

    def test_nonzero_after_state_write_still_publishes(self):
        self.assertEqual(self.init_for('partial').returncode, 0)
        directory = self.runs_root / 'partial'
        args = run_state.build_parser().parse_args(['gate', '--run-dir', str(directory), '--stage', 'round-1-web', '--decision', 'advance', '--reason', 'ok'])
        def partial(args):
            run_state.append_gate(args)
            raise SystemExit(3)
        with patch.object(run_state, 'run_command', side_effect=partial), patch.object(run_state, 'publish_board') as publish:
            with self.assertRaises(SystemExit) as error:
                run_state.run(args)
            self.assertEqual(error.exception.code, 3)
            publish.assert_called_once_with(directory, None)

    def test_failed_publisher_preserves_command_outputs_and_files(self):
        self.assertEqual(self.init_for('preserved').returncode, 0)
        directory = self.runs_root / 'preserved'
        state_path = directory / 'state.json'
        before = state_path.read_bytes()
        events = directory / 'events.jsonl'
        events_before = events.read_bytes()
        artifact = self.root / 'decision.json'
        outputs = []
        for failed in (False, True):
            state_path.write_bytes(before)
            events.write_bytes(events_before)
            args = run_state.build_parser().parse_args(['gate', '--run-dir', str(directory), '--stage', 'round-1-web', '--decision', 'advance', '--reason', 'ok'])
            def persist(args):
                result = run_state.append_gate(args)
                artifact.write_text('{"open_decisions": []}')
                print('persisted progress')
                return 3
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(run_state, 'run_command', side_effect=persist), patch.object(run_state, 'utc_now', return_value='2026-09-30T00:00:00+00:00'), patch.object(briefing, 'cmux', return_value='failed' if failed else None) as cmux, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = run_state.run(args)
            outputs.append((code, stdout.getvalue(), state_path.read_bytes(), events.read_bytes(), artifact.read_bytes()))
            self.assertEqual(cmux.call_count, 1 if failed else 2)
            self.assertEqual(stderr.getvalue(), 'sidebar board not updated: failed\n' if failed else '')
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0][0], 3)

    def test_projection_priority(self):
        base = dict(workflow='grilling', slug='topic', max_rounds=4)
        artifact = {'open_decisions': [{'status': 'open'}, {'status': 'deferred'}]}
        for decision in ('hitl', 'stop', 'advance', 'blocked'):
            gate = dict(type='gate', stage='round-3-web', decision=decision, reason='reason')
            state = dict(base, current_stage='round-3-web', gate_decisions=[gate])
            result = briefing.project_board(state, [gate], artifact)
            self.assertEqual((result[0], result[2], result[3]), ('blocked' if decision == 'blocked' else 'running', .5, 'Round 3/4'))
            if decision != 'blocked': self.assertEqual(result[1], 'topic')
            for outcome, status in [('done', 'done'), ('halted', briefing.board_status(decision))]:
                if outcome == 'halted' and decision == 'advance': continue
                recap = dict(type='run.recap', data={'outcome': dict(status=outcome, stage=gate['stage'], decision=decision)})
                result = briefing.project_board(state, [gate, recap], artifact)
                self.assertEqual((result[0], result[2]), (status, 1 if outcome == 'done' else .75))
        self.assertEqual(briefing.project_board(dict(base, current_stage='done'), [], artifact)[:3], ('waiting', 'assumptions review and decision walkthrough, 1 open decisions', 1))

    def test_bad_artifact_is_fail_soft(self):
        self.assertEqual(self.init_for('bad').returncode, 0)
        directory = self.runs_root / 'bad'
        state_path = directory / 'state.json'
        state = json.loads(state_path.read_text())
        artifact = self.root / 'bad.json'
        state['deliverables'] = {'json': str(artifact)}
        state_path.write_text(json.dumps(state))
        for contents in (None, '{', 'null', '[]', '{}', '{"open_decisions": [null]}'):
            if contents is not None: artifact.write_text(contents)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), patch.object(briefing, 'cmux') as cmux:
                briefing.publish_board(directory)
            self.assertEqual(stderr.getvalue().count('sidebar board not updated'), 1)
            cmux.assert_not_called()

    def test_documented_contract(self):
        text = (Path(__file__).parents[1] / 'SKILL.md').read_text()
        for phrase in ('publish the board automatically at transitions', 'stderr note', 'never a stop', '--no-status` suppresses pill and board', '--clear-status` clears both'):
            self.assertIn(phrase, text)


if __name__ == '__main__':
    unittest.main()
