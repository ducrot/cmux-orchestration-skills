"""Frozen diagnostics and rendered output of the assumption review contract."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import artifact_pair as contract
import test_assumption_review as command_fixtures
import test_run_state as fixtures


class ReviewContractCharacterization(unittest.TestCase):
    setUp = fixtures.ReviewArtifactPair.setUp
    write_pair = fixtures.ReviewArtifactPair.write_pair
    write_json = fixtures.ReviewArtifactPair.write_json

    def diagnostic_examples(self):
        self.write_pair()
        original = copy.deepcopy(self.data)
        examples = {}

        def record(name, data=None, markdown=None):
            self.data = copy.deepcopy(original if data is None else data)
            self.write_pair()
            if markdown is not None:
                self.markdown.write_text(markdown)
            examples[name] = contract.validate_extension(self.data, self.artifact)

        # Invalid shapes must not pass through the fixture renderer.
        for field in ('assumptions', 'assumption_review', 'open_facts'):
            data = dict(original, **{field: None})
            examples['list-' + field] = contract.validate_extension(data, self.artifact)
        for name, value in [('length', []), ('object', [None])]:
            examples[name] = contract.validate_extension(dict(original, assumption_review=value), self.artifact)
        for value in ('', 'two\nlines', 3):
            examples['text-' + repr(value)] = contract.validate_extension(dict(original, assumptions=[value]), self.artifact)
        review = original['assumption_review'][0]
        for name, changes in {
            'index': {'index': True}, 'outcome': {'outcome': []},
            'strings': {'corrected_text': None, 'reason': None, 'reviewed_at': None},
            'corrected': {'outcome': 'corrected'}, 'discarded': {'outcome': 'discarded'},
            'unreviewed': {'reason': 'unexpected'},
            'timestamp': {'outcome': 'confirmed', 'reviewed_at': '2026-10-26T09:00:00'},
        }.items():
            data = dict(original, assumption_review=[dict(review, **changes)])
            examples['review-' + name] = contract.validate_extension(data, self.artifact)
        fact = original['open_facts'][0]
        for name, value in {
            'object': None, 'required': {},
            'strings': dict(fact, answer=None, answered_at=None),
            'answered': dict(fact, status='answered'),
            'open': dict(fact, answer='unexpected', answered_at='unexpected'),
            'status': dict(fact, status='unknown'),
        }.items():
            examples['fact-' + name] = contract.validate_extension(dict(original, open_facts=[value]), self.artifact)
        examples['fact-duplicate'] = contract.validate_extension(dict(original, open_facts=[fact, fact]), self.artifact)
        examples['path-empty'] = contract.validate_extension(dict(original, markdownPath=''), self.artifact)
        with patch.object(Path, 'read_text', side_effect=OSError('unreadable')):
            examples['path-unreadable'] = contract.validate_extension(dict(original, markdownPath='pair.md'), self.artifact)
        self.data = copy.deepcopy(original)
        self.write_pair()
        markdown = self.markdown.read_text()
        for name, value in {
            'assumption-section': markdown.replace('## Definierte Annahmen', '## Other'),
            'fact-section': markdown.replace('## Offene Fakten', '## Other'),
            'duplicate-section': markdown + '\n## Definierte Annahmen\n',
            'assumption-count': markdown.replace('1. Neutral premise.', 'ignored Neutral premise.'),
            'assumption-marker': markdown.replace('ungeprüft', 'bestätigt'),
            'assumption-text': markdown.replace('Neutral premise.', 'Other text.'),
            'fact-count': markdown + '- {}\n',
            'fact-marker': markdown.replace('"status": "open"', '"status": "answered"'),
        }.items():
            record('markdown-' + name, markdown=value)
        return examples

    def test_frozen_diagnostics(self):
        expected = json.loads(Path(__file__).with_name('review_contract_diagnostics.json').read_text())
        self.assertEqual(self.diagnostic_examples(), expected)

    def test_rendered_line_quotes_brackets_and_all_outcomes(self):
        for outcome, label in [('unreviewed', 'ungeprüft'), ('confirmed', 'bestätigt'),
                               ('corrected', 'korrigiert'), ('discarded', 'verworfen')]:
            with self.subTest(outcome=outcome):
                review = dict(index=2, outcome=outcome, corrected_text='Neu "Zitat" [Text]', reason='Grund [A]\nB')
                expected = ('2. Eine "Annahme" [A] [Prüfung: {"Ergebnis": "' + label
                            + '", "Korrektur": "Neu \\"Zitat\\" [Text]", "Grund": "Grund [A]\\nB"}]')
                self.assertEqual(contract.render_assumption('Eine "Annahme" [A]', review), expected)

    def test_cli_summary_for_all_existing_pair_forms(self):
        cli = [sys.executable, str(Path(__file__).with_name('run_state.py')),
               'validate-artifact', '--artifact', str(self.artifact)]
        def check(expected):
            result = subprocess.run(cli, capture_output=True, text=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected + '\n', ''))
        for outcome in ('unreviewed', 'confirmed', 'corrected', 'discarded'):
            for status in ('open', 'answered'):
                self.data['assumption_review'][0].update(
                    outcome=outcome, corrected_text='New.' if outcome == 'corrected' else '',
                    reason='Why.' if outcome in ('corrected', 'discarded') else '',
                    reviewed_at='' if outcome == 'unreviewed' else '2026-10-26T09:00:00Z')
                self.data['open_facts'][0].update(status=status, answer='Value.' if status == 'answered' else '',
                                                 answered_at='2026-10-26T09:00:00Z' if status == 'answered' else '')
                self.write_pair()
                check('open_decisions=0 assumption_review=1 open_facts=1 valid')
        self.data.update(assumptions=[], assumption_review=[], open_facts=[])
        self.write_pair()
        check('open_decisions=0 assumption_review=0 open_facts=0 valid')
        self.artifact.write_text(json.dumps({'open_decisions': []}))
        self.markdown.unlink()
        check('open_decisions=0 valid')


class AssumptionCommandCharacterization(unittest.TestCase):
    setUp = fixtures.ReviewArtifactPair.setUp
    write_pair = fixtures.ReviewArtifactPair.write_pair
    write_json = fixtures.ReviewArtifactPair.write_json
    prepare = command_fixtures.RecordAssumptionReview.prepare
    cli = command_fixtures.RecordAssumptionReview.cli
    record = command_fixtures.RecordAssumptionReview.record

    def test_cli_preserves_exact_line_json_and_event(self):
        self.data['assumptions'] = ['Eine "Annahme" [A]']
        self.prepare()
        result = self.record('--index', '1', '--outcome', 'corrected',
                             '--corrected-text', 'Neu "Zitat" [Text]', '--reason', 'Why [A]')
        expected_line = ('1. Eine "Annahme" [A] [Prüfung: {"Ergebnis": "korrigiert", '
                         '"Korrektur": "Neu \\"Zitat\\" [Text]", "Grund": "Why [A]"}]\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected_line, ''))
        actual = json.loads(self.artifact.read_text())
        recorded_at = actual['assumption_review'][0]['reviewed_at']
        self.assertTrue(contract.timestamp(recorded_at))
        review = dict(index=1, outcome='corrected', corrected_text='Neu "Zitat" [Text]',
                      reason='Why [A]', reviewed_at=recorded_at)
        self.assertEqual(actual, dict(self.data, assumption_review=[review]))
        self.assertEqual([json.loads(line) for line in self.events.read_text().splitlines()], [{
            'time': recorded_at, 'type': 'grill.assumptions_triaged',
            'message': 'Assumption 1: corrected', 'data': dict(review, artifact=str(self.artifact)),
        }])


if __name__ == '__main__':
    unittest.main()
