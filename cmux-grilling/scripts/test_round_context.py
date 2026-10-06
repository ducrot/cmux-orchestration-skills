"""Dependency validation and bounded synthesis projection."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from orchestrator_lib import append_jsonl
from round_context import render_context, validate_question


class Context(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name)
        self.question(1, 'Q1', 'First?')
        self.question(1, 'Q2', 'Second?')
        self.question(2, 'Q1', 'Next?', ['R1Q1'])
        (self.run / 'synthesis').mkdir()
        self.items = [dict(id='Q1', question='First?', answer='Answer one', confidence='medium', sources=['source-one'], reasoning='Lanes disagree on a caveat.', reasoning_for_context=True, findings={'web': 'SECRET'}), dict(id='Q2', question='Second?', answer='Do not project me', confidence='high', sources=['source-two'], reasoning='Verified', reasoning_for_context=False)]
        self.synthesis()

    def question(self, number, identifier, text, deps=None):
        append_jsonl(self.run / 'events.jsonl', {'type': 'grill.question', 'data': {
            'round': number, 'id': identifier, 'question': text, 'depends_on': deps or []}})

    def synthesis(self):
        (self.run / 'synthesis/round-1.json').write_text(json.dumps({'round': 1, 'questions': self.items}))

    def render(self, **kwargs):
        return render_context(self.run, 2, ['Next?'], **kwargs).read_text()

    def test_projects_dependencies_and_indexes_every_other_settled_question(self):
        text = self.render()
        for phrase in ('R1Q1', 'Answer one', 'source-one', 'medium', 'caveat', 'R1Q2: Second?', 'synthesis/round-1.json'):
            self.assertIn(phrase, text)
        for phrase in ('SECRET', 'findings', 'Do not project me', 'source-two'):
            self.assertNotIn(phrase, text)
        self.assertLessEqual(len(text.encode()), 16384)

    def test_missing_duplicate_or_mismatched_metadata_fails_closed(self):
        events = self.run / 'events.jsonl'
        original = events.read_text()
        for replacement in ('', original + original, original.replace('Next?', 'Wrong?'), original.replace('"depends_on": ["R1Q1"]', '"legacy": []')):
            with self.subTest(replacement=replacement):
                events.write_text(replacement)
                with self.assertRaises(ValueError):
                    self.render()
        events.write_text(original)
        (self.run / 'synthesis/round-1.json').unlink()
        with self.assertRaisesRegex(ValueError, 'missing synthesis'):
            self.render()

    def test_cap_is_utf8_and_authored_digest_is_explicit_recovery(self):
        self.items[0]['answer'] = 'é' * 8200
        self.synthesis()
        with self.assertRaisesRegex(ValueError, '16 KiB'):
            self.render()
        digest = self.run / 'neutral.md'
        digest.write_text('A neutral digest with caveats and source references.')
        self.assertEqual(self.render(digest=digest), digest.read_text())
        digest.write_text('é' * 8192)
        self.assertEqual(len(self.render(digest=digest).encode()), 16384)
        digest.write_text('é' * 8193)
        with self.assertRaisesRegex(ValueError, '16 KiB'):
            self.render(digest=digest)
        digest.write_text('Legacy neutral digest')
        events = self.run / 'events.jsonl'
        events.write_text(events.read_text().replace('"depends_on": ["R1Q1"]', '"legacy": []'))
        self.assertEqual(self.render(digest=digest), digest.read_text())

    def test_dependency_ids_require_explicit_array_and_valid_earlier_question(self):
        from worker_readiness import read_events
        base = {'round': 2, 'id': 'Q1', 'question': 'Next?'}
        for deps in (None, 'R1Q1', ['Q1'], ['R2Q1'], ['R1Q99'], ['R1Q1', 'R1Q1'], [1]):
            with self.subTest(deps=deps), self.assertRaises(ValueError):
                validate_question({**base, 'depends_on': deps}, read_events(self.run))
        validate_question({**base, 'depends_on': []}, read_events(self.run))

    def test_event_cli_refuses_missing_dependencies(self):
        (self.run / 'state.json').write_text(json.dumps({'workflow': 'grilling', 'layout_version': 1, 'max_rounds': 4}))
        command = [sys.executable, str(Path(__file__).parent / 'run_state.py'), 'event', '--run-dir', str(self.run), '--type', 'grill.question', '--message', 'question', '--data']
        for data, expected in (({'round': 3, 'id': 'Q1', 'question': 'Valid?'}, 1), ({'round': 3, 'id': 'Q1', 'question': 'Valid?', 'depends_on': ['R1Q1']}, 0)):
            proc = subprocess.run(command + [json.dumps(data)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, expected, proc.stderr)
        duplicate = {'round': 3, 'id': 'Q1', 'question': 'Valid?', 'depends_on': []}
        proc = subprocess.run(command + [json.dumps(duplicate)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn('already recorded', proc.stderr)

    def test_reasoning_is_classified_by_author_not_english_keywords(self):
        self.items[0]['reasoning'] = 'Die Quellen widersprechen sich.'
        self.items[0]['confidence'] = 'high'
        self.synthesis()
        self.assertIn('Die Quellen widersprechen sich.', self.render())
        self.items[0]['reasoning_for_context'] = False
        self.synthesis()
        self.assertNotIn('Die Quellen widersprechen sich.', self.render())
        del self.items[0]['reasoning_for_context']
        self.synthesis()
        with self.assertRaisesRegex(ValueError, 'reasoning_for_context'):
            self.render()

    def test_missing_projection_field_has_actionable_digest_refusal(self):
        del self.items[0]['answer']
        self.synthesis()
        with self.assertRaisesRegex(ValueError, '--context-digest'):
            self.render()

    def test_overflow_and_missing_dependency_offer_only_digest_recovery(self):
        for scenario, expected in (
            ('overflow', 'round context exceeds 16 KiB UTF-8; supply --context-digest'),
            ('missing', 'missing synthesis metadata for R1Q1; supply --context-digest'),
        ):
            with self.subTest(scenario=scenario):
                if scenario == 'overflow':
                    self.items[0]['answer'] = 'é' * 8200
                else:
                    self.items = self.items[1:]
                self.synthesis()
                with self.assertRaises(ValueError) as refusal:
                    self.render()
                self.assertEqual(str(refusal.exception), expected)
