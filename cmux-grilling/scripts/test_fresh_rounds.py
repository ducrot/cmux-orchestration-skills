"""Fresh-round CLI regression tests; subprocesses use a fake cmux and simulated workers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

from test_pane_ctl import PaneCtlCase
from orchestrator_lib import LANES, append_jsonl
from run_briefing import project_board


class FreshRounds(PaneCtlCase):
    def test_open_round_is_a_single_json_result(self):
        proc = self.run_ctl('open-round', '--run-dir', str(self.run_dir), '--round', '1', '--anchor', 'ORCHESTRATOR-UUID')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        surfaces = json.loads(proc.stdout)
        self.assertEqual(set(surfaces), set(LANES))
        self.assertEqual(len(set(surfaces.values())), 4)

    def event(self, kind, data, message=""):
        append_jsonl(self.run_dir / 'events.jsonl', {'type': kind, 'data': data, 'message': message})

    def script(self, name, *args):
        if name == 'run_state.py':
            args = (*args, '--cmux-cmd', self.cmux_cmd)
        return subprocess.run([sys.executable, str(Path(__file__).parent / name), *args],
                              capture_output=True, text=True, timeout=10,
                              env={**os.environ, 'FAKE_CMUX_LOG': str(self.log)})

    def snapshot(self, label):
        proc = self.script('run_state.py', 'snapshot', '--run-dir', str(self.run_dir), '--label', label)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def prepare(self, number):
        state_path = self.run_dir / 'state.json'
        state = json.loads(state_path.read_text())
        state['task_file'] = 'task.md'
        state_path.write_text(json.dumps(state))
        self.event('grill.question', {'round': number, 'id': 'Q1', 'question': 'What exists?',
                                     'depends_on': [] if number == 1 else ['R1Q1']})
        for lane in LANES:
            proc = self.script('render_prompt.py', 'round', '--run-dir', str(self.run_dir), '--lane', lane,
                               '--round', str(number), '--question', 'What exists?')
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def open_round(self, number):
        proc = self.run_ctl('open-round', '--run-dir', str(self.run_dir), '--round', str(number),
                            *(['--anchor', 'ORCHESTRATOR-UUID'] if number == 1 else []))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def start_round(self, number):
        self.snapshot(f'launched round-{number}')
        proc = self.run_ctl('start-round', '--run-dir', str(self.run_dir), '--round', str(number))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_two_round_cli_flow_and_readiness_replacement(self):
        previous = None
        for number in (1, 2):
            self.prepare(number)
            surfaces = self.open_round(number)
            if previous:
                self.assertFalse(set(previous.values()) & set(surfaces.values()))
                events = self.events()
                new = [i for i, e in enumerate(events) if e['type'] == 'pane.launched' and e['data']['round'] == 2]
                closed = [i for i, e in enumerate(events) if e['type'] == 'pane.closed']
                self.assertLess(max(new), min(closed))
                for e in (events[i] for i in new):
                    self.assertEqual(e['data']['anchor'], previous[e['data']['lane']])
                # Old observations and ready events cannot survive replacement.
                proc = self.run_ctl('observe', '--run-dir', str(self.run_dir), '--lane', 'web', '--surface', previous['web'])
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn('replaced', proc.stderr)
                proc = self.run_ctl('deliver', '--run-dir', str(self.run_dir), '--lane', 'web', '--surface', surfaces['web'], '--text', 'follow up')
                self.assertNotEqual(proc.returncode, 0)
            launches = self.start_round(number)
            for lane, launch in launches.items():
                prompt = Path(launch['prompt_path']).read_text()
                marker = Path(prompt.split('create or overwrite `', 1)[1].split('`', 1)[0])
                self.assertEqual(str(marker), launch['marker_path'])
                marker.parent.mkdir(parents=True)
                marker.write_text('started')
                report = self.run_dir / 'reports' / f'round-{number}-{lane}.md'
                report.write_text('## Q1\n### Result\nNO ANSWER\n\n### Answer\nNo applicable evidence.\n\n### Sources\n- None\n\n### Method\n- Read task; outside this lane.\n\n### Blockers\n- None\n\n### Plan Drift\n- None\n')
            args = ['--run-dir', str(self.run_dir), '--round', str(number), '--questions', '1']
            for lane, surface in surfaces.items():
                args += ['--lane-surface', f'{lane}={surface}']
            # Extend a real prompt-attached round; fresh sessions must not lose the
            # persisted extension or grant a second one in the same round.
            watched = self.script('await_reports.py', *args, '--deadline-minutes', '0')
            self.assertEqual(watched.returncode, 0, watched.stderr)
            clocks = lambda: [e['data']['watch_clock'] for e in self.events()
                              if e.get('data', {}).get('round') == number
                              and 'watch_clock' in e.get('data', {})]
            original = clocks()[-1]
            extended = self.script('await_reports.py', *args, '--extend', '--reason', 'round research',
                                   '--deadline-minutes', '.001')
            self.assertEqual(extended.returncode, 0, extended.stderr)
            current = clocks()[-1]
            self.assertEqual(current['extension'], 1)
            self.assertGreater(current['deadline'], original['deadline'])
            self.assertEqual(current['start_deadline'], original['start_deadline'])
            before = (self.run_dir / 'events.jsonl').read_bytes()
            refused = self.script('await_reports.py', *args, '--extend', '--reason', 'again',
                                  '--deadline-minutes', '.001')
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('already recorded for this round', refused.stderr)
            self.assertEqual((self.run_dir / 'events.jsonl').read_bytes(), before)
            board = project_board(json.loads((self.run_dir / 'state.json').read_text()), self.events())
            self.assertEqual(board[0], 'running')
            self.assertTrue(board[3].startswith(f'Round {number}/'), board)
            for _ in range(2):
                watched = self.script('await_reports.py', *args)
                self.assertEqual(watched.returncode, 0, watched.stderr)
            self.assertEqual(clocks(), [original, current])
            confirmed = [e for e in self.events() if e['type'] == 'worker.started' and e['data']['round'] == number]
            self.assertEqual(len(confirmed), 4)
            self.snapshot(f'reports-captured round-{number}')
            for lane in LANES:
                parsed = self.script('parse_research_report.py', str(self.run_dir / 'reports' / f'round-{number}-{lane}.md'), '--questions', '1')
                self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
                gate = self.script('run_state.py', 'gate', '--run-dir', str(self.run_dir), '--stage', f'round-{number}-{lane}', '--decision', 'advance', '--reason', 'validated report',
                                   *(['--next-stage', 'round-2'] if number == 1 and lane == 'web' else []))
                self.assertEqual(gate.returncode, 0, gate.stderr)
            if number == 1:
                common = ['--run-dir', str(self.run_dir), '--lane', 'web', '--surface', surfaces['web']]
                observed = self.run_ctl('observe', *common)
                self.assertEqual(observed.returncode, 0, observed.stderr)
                assessed = self.run_ctl('assess', *common, '--observation', json.loads(observed.stdout)['observation_id'], '--state', 'ready', '--reason', 'idle worker')
                self.assertEqual(assessed.returncode, 0, assessed.stderr)
                synthesis = self.run_dir / 'synthesis' / 'round-1.json'
                synthesis.parent.mkdir()
                synthesis.write_text(json.dumps({'round': 1, 'questions': [{'id': 'Q1', 'question': 'What exists?', 'answer': 'A task.', 'confidence': 'high', 'sources': ['task.md'], 'reasoning': 'Observed', 'reasoning_for_context': False, 'findings': {'web': 'private lane detail'}}]}))
            previous = surfaces
        for lane, surface in previous.items():
            proc = self.run_ctl('close', '--run-dir', str(self.run_dir), '--round', '2', '--lane', lane, '--surface', surface)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        snapshots = [e['data'] for e in self.events() if e['type'] == 'tree.snapshot']
        for field in ('head', 'staged_paths', 'staged_diff_sha256'):
            self.assertTrue(all(s[field] == snapshots[0][field] for s in snapshots))

    def test_start_refuses_absent_wrong_or_stale_snapshot_without_input(self):
        self.prepare(1)
        self.open_round(1)
        for label in (None, 'reports-captured round-1', 'launched round-1'):
            if label:
                self.snapshot(label)
            if label == 'launched round-1':
                self.event('pane.labeled', {'round': 1})
            before = self.cmux_calls()
            proc = self.run_ctl('start-round', '--run-dir', str(self.run_dir), '--round', '1')
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('tree.snapshot', proc.stderr)
            self.assertEqual(self.cmux_calls(), before)

    def test_failed_start_reports_started_and_unstarted_without_rollback(self):
        self.prepare(1)
        self.open_round(1)
        (self.run_dir / 'prompts/round-1-docs.md').unlink()
        self.snapshot('launched round-1')
        proc = self.run_ctl('start-round', '--run-dir', str(self.run_dir), '--round', '1')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('"started": ["codebase", "codebase2"]', proc.stderr)
        self.assertIn('"unstarted": ["docs", "web"]', proc.stderr)
        self.assertFalse(any(e['type'] == 'pane.closed' for e in self.events()))

    def test_open_next_round_refuses_missing_capture_or_gates(self):
        self.open_round(1)
        for snapshot in (False, True):
            if snapshot:
                self.snapshot('reports-captured round-1')
            calls = self.cmux_calls()
            proc = self.run_ctl('open-round', '--run-dir', str(self.run_dir), '--round', '2')
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(self.cmux_calls(), calls)

    def test_open_failure_names_surfaces_and_stops_without_rollback(self):
        fake = Path(self._tmp.name) / 'fake_cmux.py'
        source = fake.read_text()
        fake.write_text(source.replace('if "new-split" in args:', '''if "rename-tab" in args and sum("rename-tab" in json.loads(line) for line in open(os.environ["FAKE_CMUX_LOG"])) == 2:
    raise SystemExit("injected labeling failure")
if "new-split" in args:'''))
        proc = self.run_ctl('open-round', '--run-dir', str(self.run_dir), '--round', '1', '--anchor', 'ORCHESTRATOR-UUID')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('injected labeling failure', proc.stderr)
        self.assertIn('"launched": ["SURF-UUID", "SURF-UUID-2"]', proc.stderr)
        self.assertIn('"closed": []', proc.stderr)
        self.assertIn('"orphaned": ["SURF-UUID", "SURF-UUID-2"]', proc.stderr)
        self.assertEqual(len(self.cmux_calls()), 4)

    def test_repeated_open_and_start_are_refused(self):
        self.prepare(1)
        self.open_round(1)
        self.start_round(1)
        for verb in ('open-round', 'start-round'):
            before = self.cmux_calls()
            proc = self.run_ctl(verb, '--run-dir', str(self.run_dir), '--round', '1')
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(self.cmux_calls(), before)

    def test_recovery_verbs_refuse_positional_surface_identity(self):
        for verb, arguments in (
                ('launch', ['--anchor', 'surface:5']),
                ('start-agent', ['--surface', 'surface:5', '--round', '1']),
                ('close', ['--surface', 'surface:5'])):
            with self.subTest(verb=verb):
                proc = self.run_ctl(verb, '--run-dir', str(self.run_dir), '--lane', 'web', *arguments)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn('stable surface UUIDs', proc.stderr)
                self.assertEqual(self.cmux_calls(), [])

    def test_open_next_round_force_closes_live_captured_lanes(self):
        old = self.open_round(1)
        self.snapshot('reports-captured round-1')
        for lane in LANES:
            append_jsonl(self.run_dir / 'events.jsonl', {'type': 'gate', 'stage': f'round-1-{lane}', 'decision': 'advance'})
        proc = self.run_ctl('open-round', '--run-dir', str(self.run_dir), '--round', '2', FAKE_CMUX_CONFIRM='1')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        forced = [call[-2] for call in self.cmux_calls() if call[0] == 'close-surface' and call[-1] == '--force']
        self.assertEqual(set(forced), set(old.values()))
        closes = [e for e in self.events() if e['type'] == 'pane.closed']
        self.assertEqual([e['data']['forced'] for e in closes], [True] * 4)

    def test_close_failure_preserves_new_layout_and_reports_partial_closure(self):
        old = self.open_round(1)
        self.snapshot('reports-captured round-1')
        for lane in LANES:
            append_jsonl(self.run_dir / 'events.jsonl', {'type': 'gate', 'stage': f'round-1-{lane}', 'decision': 'advance'})
        fake = Path(self._tmp.name) / 'fake_cmux.py'
        source = fake.read_text()
        fake.write_text(source.replace('if "new-split" in args:', '''if "close-surface" in args and sum("close-surface" in json.loads(line) for line in open(os.environ["FAKE_CMUX_LOG"])) == 2:
    raise SystemExit("injected close failure")
if "new-split" in args:'''))
        proc = self.run_ctl('open-round', '--run-dir', str(self.run_dir), '--round', '2')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('injected close failure', proc.stderr)
        detail = json.loads(proc.stderr.split('; ', 1)[1])
        self.assertEqual(detail['closed'], [old['codebase']])
        self.assertEqual(len(detail['launched']), 4)
        self.assertEqual(set(detail['orphaned']), set(old.values()) - {old['codebase']})
        closes = [e for e in self.events() if e['type'] == 'pane.closed']
        self.assertEqual(len(closes), 1)
        self.assertEqual(sum(call[0] == 'close-surface' for call in self.cmux_calls()), 2)
