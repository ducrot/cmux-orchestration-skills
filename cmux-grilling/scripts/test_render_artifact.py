"""Render and review a protocol using the real CLI, with a fixed expected output."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_launch_wave import file_contents

HERE = Path(__file__).resolve().parent


class RenderArtifact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run'
        (self.run / 'synthesis').mkdir(parents=True)
        self.state = {'run_id': 'neutral-run', 'created_at': '2026-10-28T20:00:00Z',
                      'workflow': 'grilling', 'layout_version': 2, 'max_rounds': 4}
        self.write_state()
        self.artifact = self.root / 'artifact.json'
        self.markdown = self.root / 'protocol.md'
        self.data = json.loads((HERE / 'fixtures/render-artifact.json').read_text())
        self.data['markdownPath'] = str(self.markdown)
        self.write_json()
        self.synthesis = self.run / 'synthesis/round-1.json'
        self.synthesis.write_text(json.dumps({'round': 1, 'questions': self.data['qa'],
            'deferred': [{'id': 'Q2', 'question': 'Which fallback?\n## Entscheidungen',
                          'reason': 'The evidence is incomplete.\n## Offene Fakten'}]}))

    def write_json(self):
        self.artifact.write_text(json.dumps(self.data))

    def write_state(self, **changes):
        (self.run / 'state.json').write_text(json.dumps(self.state | changes))

    def cli(self, command='render-artifact', *extra):
        args = [sys.executable, str(HERE / 'run_state.py'), command, '--artifact', str(self.artifact)]
        if command == 'render-artifact':
            args += ['--run-dir', str(self.run)]
        return subprocess.run(args + list(extra), text=True, capture_output=True)

    def test_expected_protocol_and_review_transcription(self):
        result = self.cli('render-artifact', '--title', 'Protocol')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = (HERE / 'fixtures/render-artifact.md').read_text()
        self.assertEqual(self.markdown.read_text(), expected)
        self.assertEqual(self.cli('validate-artifact').returncode, 0)
        self.data['assumption_review'][0].update(outcome='corrected', corrected_text='Revised premise.',
            reason='Human context.\n## Offene Fakten', reviewed_at='2026-10-28T21:00:00Z')
        self.data['premise_correction_review'][0].update(outcome='confirmed', reviewed_at='2026-10-28T21:00:00Z')
        self.data['open_facts'][0].update(status='answered', answer='Value\n## Entscheidungen',
                                       answered_at='2026-10-28T21:00:00Z')
        self.data['open_decisions'][0].update(status='decided', decision='A')
        self.write_json()
        result = self.cli('transcribe-artifact')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cli('validate-artifact').returncode, 0)
        self.assertIn('Ausgang (decided): A', self.markdown.read_text())
        self.assertEqual(self.markdown.read_text().count('\n## Offene Fakten\n'), 1)
        self.assertEqual(self.markdown.read_text().split('## Definierte Annahmen')[0],
                         expected.split('## Definierte Annahmen')[0])

    def test_default_title_and_explicit_overwrite(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.markdown.read_text().startswith('# Task ## Offene Fakten\n'))
        self.markdown.write_text('Recorded human edits.\n')
        before = self.artifact.read_bytes()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--overwrite', result.stderr)
        self.assertEqual(self.markdown.read_text(), 'Recorded human edits.\n')
        self.assertEqual(self.artifact.read_bytes(), before)
        self.assertEqual(self.cli('render-artifact', '--overwrite').returncode, 0)
        self.assertEqual(self.cli('validate-artifact').returncode, 0)

    def test_legacy_layout_refuses_rendering_but_remains_inspectable(self):
        self.write_state(layout_version=1)
        before = file_contents(self.root)
        diagnostic = f'unsupported legacy layout in {self.run}; inspect read-only and restart the run'
        result = self.cli()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr.strip(), diagnostic)
        self.assertFalse(self.markdown.exists())
        self.assertEqual(file_contents(self.root), before)
        status = subprocess.run([sys.executable, str(HERE / 'run_state.py'), 'status',
                                 '--run-dir', str(self.run)], text=True, capture_output=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn('neutral-run', status.stdout)
        self.assertIn(diagnostic, status.stdout)
        self.markdown.write_text('Recorded human edits.\n')
        result = self.cli('render-artifact', '--overwrite')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr.strip(), diagnostic)
        self.assertEqual(self.markdown.read_text(), 'Recorded human edits.\n')

    def test_unreadable_state_is_refused_without_traceback(self):
        (self.run / 'state.json').write_text('{broken')
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith('rendering refused:'), result.stderr)
        (self.run / 'state.json').unlink()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.startswith('rendering refused:'), result.stderr)
        self.assertFalse(self.markdown.exists())

    def test_empty_lists_and_later_round_with_only_deferrals(self):
        self.data.update(roundsRun=2, maxRounds=2)
        for key in ('assumptions', 'assumption_review', 'premise_corrections',
                    'premise_correction_review', 'open_facts'):
            self.data[key] = []
        self.data['open_decisions'][1].update(status='deferred', decision='Need human context.')
        (self.run / 'synthesis/round-2.json').write_text(json.dumps({
            'round': 2, 'questions': [], 'deferred': [
                {'id': 'Q1', 'question': 'Another question?', 'reason': 'Incomplete evidence.'}]}))
        self.write_json()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('### Runde 2', self.markdown.read_text())
        self.assertIn('> Q1: Another question?', self.markdown.read_text())
        self.assertIn('Ausgang (deferred): Need human context.', self.markdown.read_text())
        self.assertEqual(self.cli('validate-artifact').returncode, 0)

    def test_invalid_json_reports_validator_diagnostics_and_writes_nothing(self):
        self.data['assumption_review'][0]['index'] = 7
        self.data['open_decisions'][0].pop('context')
        self.write_json()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('index must be 1', result.stderr)
        self.assertIn('missing or empty field: context', result.stderr)
        self.assertFalse(self.markdown.exists())
        self.artifact.write_text('{')
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse(self.markdown.exists())

    def test_invalid_paths_metadata_and_question_identity_write_nothing(self):
        original = json.loads(json.dumps(self.data))
        for update, diagnostic in (
                ({'markdownPath': ''}, 'markdownPath'),
                ({'markdownPath': str(self.artifact)}, 'differ from the JSON path'),
                ({'questionsAsked': 2}, 'exactly questionsAsked'),
                ({'roundsRun': 2}, 'within maxRounds'),
                ({'qa': [dict(self.data['qa'][0], round=0)]}, 'round within roundsRun'),
                ({'qa': [dict(self.data['qa'][0], sources='reference.md:1')]}, 'list of strings'),
                ({'questionsAsked': 2, 'qa': self.data['qa'] * 2}, 'duplicate qa entry')):
            with self.subTest(update=update):
                self.data = dict(original, **update)
                self.write_json()
                result = self.cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)
                self.assertFalse(self.markdown.exists())
        self.data = original
        self.write_json()
        self.synthesis.unlink()
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse(self.markdown.exists())
        self.write_state(run_id='other-run')
        self.assertIn('different run_id', self.cli().stderr)
        self.assertFalse(self.markdown.exists())
        self.state.pop('created_at')
        self.write_state()
        self.assertIn('created_at', self.cli().stderr)
        self.assertFalse(self.markdown.exists())

    def test_bad_synthesis_and_unrenderable_outcome_do_not_replace_existing_file(self):
        self.markdown.write_text('Human edits')
        self.synthesis.write_text(json.dumps({'round': 1, 'questions': [], 'deferred': [{'id': 'Q2'}]}))
        result = self.cli('render-artifact', '--overwrite')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('deferred', result.stderr)
        self.assertEqual(self.markdown.read_text(), 'Human edits')
        self.synthesis.write_text(json.dumps({'round': 1, 'questions': [], 'deferred': []}))
        self.data['open_decisions'][1]['decision'] = 'A\n## Offene Fakten'
        self.write_json()
        self.assertNotEqual(self.cli('render-artifact', '--overwrite').returncode, 0)
        self.assertEqual(self.markdown.read_text(), 'Human edits')


if __name__ == '__main__':
    unittest.main()
