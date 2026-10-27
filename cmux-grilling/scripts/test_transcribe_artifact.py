"""Exercise outcome transcription through the real run-state CLI."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import test_run_state as fixtures
from artifact_pair import PREMISE_CORRECTION_REVIEW, render_assumption, render_review


class TranscribeArtifact(unittest.TestCase):
    setUp = fixtures.ReviewArtifactPair.setUp
    write_pair = fixtures.ReviewArtifactPair.write_pair
    write_json = fixtures.ReviewArtifactPair.write_json

    def cli(self, command='transcribe-artifact', cwd=None):
        return subprocess.run([sys.executable, str(Path(__file__).with_name('run_state.py').resolve()),
                               command, '--artifact', str(self.artifact)],
                              cwd=cwd, capture_output=True, text=True)

    def prepare(self):
        self.markdown = self.artifact.with_suffix(".md")
        self.data["markdownPath"] = str(self.markdown)
        self.write_pair()
        self.data['premise_corrections'] = ['Original correction.']
        self.data['premise_correction_review'] = [dict(self.data['assumption_review'][0])]
        self.data['open_decisions'] = [fixtures.valid_decision(id=f'D{i}', status=status, decision='A')
                                       for i, status in enumerate(('decided', 'deferred', 'open'), 1)]
        self.markdown.write_text(self.markdown.read_text() +
            '\n## Entscheidungen\n\n### D1 — First\nQuestion unchanged.\n- **Ausgang (deferred):** old\n\n'
            '### D2: Second\nMore context.\n\n### D3\nOpen context.\n\n'
            '## Prämissen-Korrekturen\n- Original correction.\n\n## Tail\nKeep *everything* here.\n')
        for name in ('assumption_review', 'premise_correction_review'):
            self.data[name][0].update(outcome='confirmed', reviewed_at='2026-10-27T05:00:00Z')
        self.data['open_facts'][0].update(status='answered', answer='42', answered_at='2026-10-27T05:00:00Z')
        self.write_json()

    def test_all_outcomes_exact_preservation_validation_and_repeat(self):
        self.prepare()
        before = self.markdown.read_text()
        old_assumption = before.splitlines()[1]
        old_fact = next(line for line in before.splitlines() if line.startswith('- {'))
        expected = before.replace(old_assumption, render_assumption(
            self.data['assumptions'][0], self.data['assumption_review'][0]))
        expected = expected.replace('- Original correction.', render_review('Original correction.',
            self.data['premise_correction_review'][0], PREMISE_CORRECTION_REVIEW))
        expected = expected.replace(old_fact, '- ' + json.dumps(self.data['open_facts'][0], ensure_ascii=False))
        expected = expected.replace('- **Ausgang (deferred):** old', 'Ausgang (decided): A')
        expected = expected.replace('More context.\n', 'More context.\nAusgang (deferred): A\n')
        json_before = self.artifact.read_bytes()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.markdown.read_text(), expected)
        self.assertEqual(self.artifact.read_bytes(), json_before)
        self.assertEqual(self.cli('validate-artifact').returncode, 0)
        first = self.markdown.read_bytes()
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(self.markdown.read_bytes(), first)

    def test_legacy_and_no_premise_fields(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                self.prepare()
                for name in ('premise_corrections', 'premise_correction_review'):
                    self.data.pop(name)
                if legacy:
                    for name in ('assumption_review', 'open_facts'):
                        self.data.pop(name)
                self.write_json()
                before = self.markdown.read_text()
                self.assertEqual(self.cli().returncode, 0)
                after = self.markdown.read_text()
                self.assertEqual(after.split('## Prämissen-Korrekturen')[1], before.split('## Prämissen-Korrekturen')[1])
                if legacy:
                    self.assertEqual(after.split('## Entscheidungen')[0], before.split('## Entscheidungen')[0])
                self.assertEqual(self.cli('validate-artifact').returncode, 0)

    def test_recorded_relative_path_and_sibling_resolution_preserve_crlf(self):
        for recorded in (True, False):
            with self.subTest(recorded=recorded):
                self.prepare()
                if recorded:
                    self.markdown = self.artifact.parent / 'other.md'
                    self.artifact.with_suffix('.md').rename(self.markdown)
                    self.data['markdownPath'] = 'other.md'
                else:
                    self.data.pop('markdownPath')
                self.write_json()
                self.markdown.write_bytes(self.markdown.read_bytes().replace(b'\n', b'\r\n'))
                result = self.cli(cwd=self.artifact.parent)
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = self.markdown.read_bytes()
                self.assertNotIn(b'\n', raw.replace(b'\r\n', b''))
                self.assertEqual(self.cli('validate-artifact', cwd=self.artifact.parent).returncode, 0)

    def test_refusals_leave_both_files_untouched(self):
        mutations = [
            lambda s: s + '\n## Definierte Annahmen\n',
            lambda s: s.replace('## Offene Fakten', '## Missing'),
            lambda s: s + '\n## Entscheidungen\n',
            lambda s: s + '\n## Prämissen-Korrekturen\n',
            lambda s: s.replace('## Prämissen-Korrekturen', '## Missing'),
            lambda s: s.replace('### D1 — First', '### D12 — First'),
            lambda s: s.replace('### D2: Second', '### D1: Duplicate'),
            lambda s: s.replace('More context.', 'Ausgang (decided): A\n*Ausgang (deferred):* B'),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.prepare()
                self.markdown.write_text(mutate(self.markdown.read_text()))
                before = (self.markdown.read_bytes(), self.artifact.read_bytes())
                result = self.cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('transcription refused', result.stderr)
                self.assertEqual((self.markdown.read_bytes(), self.artifact.read_bytes()), before)
        self.prepare()
        self.data['premise_correction_review'][0]['index'] = 9
        self.write_json()
        before = self.markdown.read_bytes()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('index must be 1', result.stderr)
        self.assertEqual(self.markdown.read_bytes(), before)

    def test_missing_entries_are_appended_and_empty_optional_section_is_not_invented(self):
        self.prepare()
        original = self.markdown.read_text()
        without_entries = '\n'.join(line for line in original.split('## Entscheidungen')[0].split('\n')
                                    if not line.startswith(('1. ', '- {')))
        self.markdown.write_text(without_entries + '## Entscheidungen' + original.split('## Entscheidungen', 1)[1])
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cli('validate-artifact').returncode, 0)
        self.data['premise_corrections'] = []
        self.data['premise_correction_review'] = []
        self.write_json()
        text = self.markdown.read_text()
        start, tail = text.split('## Prämissen-Korrekturen', 1)
        self.markdown.write_text(start + '## Tail' + tail.split('## Tail', 1)[1])
        self.assertEqual(self.cli().returncode, 0)
        self.assertNotIn('## Prämissen-Korrekturen', self.markdown.read_text())

    def test_candidate_validation_refusal_does_not_publish_partial_edits(self):
        self.prepare()
        self.data['open_facts'].append(dict(self.data['open_facts'][0]))
        self.write_json()
        before = self.markdown.read_bytes()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate id', result.stderr)
        self.assertEqual(self.markdown.read_bytes(), before)

    def test_heading_title_naming_another_id_and_unterminated_last_line(self):
        self.prepare()
        text = self.markdown.read_text().split('## Prämissen-Korrekturen')[0]
        text = text.replace('### D2: Second\nMore context.\n\n### D3\nOpen context.\n\n',
                            '### D3\nOpen context.\n\n### D2: Second, falls D1 scheitert\nMore context.')
        self.markdown.write_text(text.replace(
            '## Entscheidungen', '## Prämissen-Korrekturen\n- Original correction.\n\n## Entscheidungen'))
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.markdown.read_text().endswith('More context.\nAusgang (deferred): A\n'))

    def test_outcome_list_markers_and_emphasis(self):
        for line in ('* Ausgang (deferred): old', '+ **Ausgang** (deferred): old',
                     '1. _Ausgang (deferred):_ old', '**Ausgang (deferred)**: old',
                     'Ausgang: old'):
            with self.subTest(line=line):
                self.prepare()
                self.markdown.write_text(self.markdown.read_text().replace('- **Ausgang (deferred):** old', line))
                result = self.cli()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Ausgang (decided): A\n', self.markdown.read_text())
                self.assertNotIn(line, self.markdown.read_text())


if __name__ == '__main__':
    unittest.main()
