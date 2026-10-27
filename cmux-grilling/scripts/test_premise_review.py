"""Premise review recording and pair validation through the real CLI."""

import copy
import json
import unittest
from pathlib import Path

import test_assumption_review as command
from artifact_pair import validate_extension


class PremiseReview(unittest.TestCase):
    setUp = command.RecordAssumptionReview.setUp
    write_json = command.RecordAssumptionReview.write_json
    cli = command.RecordAssumptionReview.cli

    def prepare(self):
        command.RecordAssumptionReview.prepare(self)
        self.data.update(premise_corrections=['The "old" path [name] changed.'],
                         premise_correction_review=[dict(self.data['assumption_review'][0])])
        self.write_json()
        self.markdown.write_text(self.markdown.read_text() + '\n## Prämissen-Korrekturen\n'
                                 '- The "old" path [name] changed. [Prüfung: '
                                 '{"Ergebnis":"ungeprüft","Korrektur":"","Grund":""}]\n')

    write_pair = command.RecordAssumptionReview.write_pair

    def record(self, *args):
        return self.cli('premise-correction-review', '--run-dir', str(self.run_dir), *args)

    def test_record_transcribe_and_validate_each_outcome(self):
        for outcome in ('confirmed', 'corrected', 'discarded'):
            with self.subTest(outcome=outcome):
                self.prepare()
                valid = self.cli('validate-artifact')
                self.assertEqual(valid.returncode, 0, valid.stderr)
                self.assertIn('premise_correction_review=1', valid.stdout)
                correction = 'A "new" path [name].' if outcome == 'corrected' else ''
                reason = 'Human context.\nMore detail.' if outcome != 'confirmed' else ''
                result = self.record('--index', '1', '--outcome', outcome,
                                     '--corrected-text', correction, '--reason', reason)
                self.assertEqual(result.returncode, 0, result.stderr)
                actual = json.loads(self.artifact.read_text())
                review = actual['premise_correction_review'][0]
                self.assertEqual(actual['premise_corrections'], self.data['premise_corrections'])
                self.assertEqual(review['outcome'], outcome)
                self.assertEqual(review['corrected_text'], correction)
                self.assertEqual(review['reason'], reason)
                from artifact_pair import timestamp
                self.assertTrue(timestamp(review['reviewed_at']))
                events = [json.loads(line) for line in self.events.read_text().splitlines()]
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]['type'], 'grill.premise_corrections_triaged')
                self.assertEqual(events[0]['data'], dict(review, artifact=str(self.artifact)))
                self.assertEqual(events[0]['time'], review['reviewed_at'])
                mismatch = self.cli('validate-artifact')
                self.assertNotEqual(mismatch.returncode, 0)
                self.assertIn('premise_correction_review entry 1', mismatch.stderr)
                lines = result.stdout.splitlines()
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].startswith('- ' + self.data['premise_corrections'][0]))
                markdown = self.markdown.read_text()
                self.markdown.write_text(markdown.replace(markdown.splitlines()[-1], lines[0]))
                repaired = self.cli('validate-artifact')
                self.assertEqual(repaired.returncode, 0, repaired.stderr)

    def test_refusals_do_not_write_json_or_events(self):
        self.prepare()
        for args, diagnostic in (
            (('--index', '0', '--outcome', 'confirmed'), 'index'),
            (('--index', '2', '--outcome', 'confirmed'), 'index'),
            (('--index', '1', '--outcome', 'corrected', '--reason', 'why'), 'corrected_text'),
            (('--index', '1', '--outcome', 'corrected', '--corrected-text', 'new'), 'reason'),
            (('--index', '1', '--outcome', 'discarded'), 'reason'),
            (('--index', '1', '--outcome', 'confirmed', '--corrected-text', 'new'), 'corrected-text'),
            (('--index', '1', '--outcome', 'discarded', '--corrected-text', 'new', '--reason', 'why'), 'corrected-text'),
        ):
            with self.subTest(args=args):
                before = self.artifact.read_bytes(), self.events.read_bytes()
                result = self.record(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)
                self.assertEqual((self.artifact.read_bytes(), self.events.read_bytes()), before)

    def test_record_second_entry_preserves_first(self):
        self.prepare()
        self.data['premise_corrections'].append('Another path changed.')
        self.data['premise_correction_review'].append(dict(self.data['premise_correction_review'][0], index=2))
        self.write_json()
        result = self.record('--index', '2', '--outcome', 'confirmed')
        self.assertEqual(result.returncode, 0, result.stderr)
        actual = json.loads(self.artifact.read_text())
        self.assertEqual(actual['premise_correction_review'][0], self.data['premise_correction_review'][0])
        self.assertEqual(actual['premise_correction_review'][1]['index'], 2)
        self.assertEqual(actual['premise_correction_review'][1]['outcome'], 'confirmed')
        self.assertTrue(result.stdout.startswith('- Another path changed. [Prüfung:'))

    def test_invalid_entries_and_markdown_rejected_by_both_copies(self):
        self.prepare()
        import importlib.util
        sibling = Path(__file__).resolve().parents[2] / 'cmux-planning/scripts/grilling_review.py'
        if not sibling.is_file():
            self.skipTest('cmux-planning is absent from this independent installation')
        spec = importlib.util.spec_from_file_location('premise_vendored_review', sibling)
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        original = copy.deepcopy(self.data)
        markdown = self.markdown.read_text()
        cases = [
            (lambda d: d.pop('premise_corrections'), 'premise_corrections'),
            (lambda d: d.pop('premise_correction_review'), 'premise_correction_review'),
            (lambda d: d.update(premise_correction_review=None), 'premise_correction_review'),
            (lambda d: d.update(premise_correction_review=[]), 'length'),
            (lambda d: d.update(premise_correction_review=[None]), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(index=True), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(index=2), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(outcome='unknown'), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(reason=None), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(outcome='discarded'), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(outcome='corrected', reason='why'), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(reviewed_at='bad'), 'entry 1'),
            (lambda d: d['premise_correction_review'][0].update(outcome='confirmed', reviewed_at='bad'), 'entry 1'),
            (lambda d: d.update(premise_corrections=['']), 'entry 1'),
        ]
        for mutate, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic):
                data = copy.deepcopy(original)
                mutate(data)
                upstream = validate_extension(data, self.artifact)
                self.assertEqual(upstream, module.validate_extension(data, markdown))
                self.assertIn(diagnostic, '; '.join(upstream))
        for changed, diagnostic in (
            (markdown.rsplit(' [Prüfung:', 1)[0] + '\n', 'premise_correction_review entry 1'),
            (markdown.replace('## Prämissen-Korrekturen', '## Other'), 'Prämissen-Korrekturen'),
            (markdown + '- Extra correction.\n', 'line count'),
            (markdown.rsplit('ungeprüft', 1)[0] + 'bestätigt' + markdown.rsplit('ungeprüft', 1)[1], 'entry 1'),
        ):
            with self.subTest(markdown=changed):
                self.markdown.write_text(changed)
                upstream = validate_extension(original, self.artifact)
                self.assertEqual(upstream, module.validate_extension(original, changed))
                self.assertIn(diagnostic, '; '.join(upstream))

    def test_empty_and_legacy_pairs(self):
        self.prepare()
        self.data.update(premise_corrections=[], premise_correction_review=[])
        self.write_json()
        base = self.markdown.read_text().split('## Prämissen-Korrekturen')[0]
        for markdown in (base, base + '## Prämissen-Korrekturen\n'):
            self.markdown.write_text(markdown)
            result = self.cli('validate-artifact')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('premise_correction_review=0', result.stdout)
        for field in ('premise_corrections', 'premise_correction_review'):
            self.data.pop(field)
        self.write_json()
        result = self.cli('validate-artifact')
        self.assertEqual(result.stdout.strip(), 'open_decisions=0 assumption_review=1 open_facts=1 valid')


if __name__ == '__main__':
    unittest.main()
