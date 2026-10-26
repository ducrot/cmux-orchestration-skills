"""The shared contract can operate on a separately named list without assumptions."""

import unittest

import artifact_pair


class NamedReviewList(unittest.TestCase):
    def test_named_list_validation_rendering_and_section_reading(self):
        from artifact_pair import ReviewList, render_review, review_lines, validate_review_list, validate_review_markdown

        contract = ReviewList(name='example_review', texts_name='examples', item_name='example',
                              heading='Examples', entry_marker='- {index}: ',
                              marker='Review')
        review = dict(index=1, outcome='unreviewed', corrected_text='', reason='', reviewed_at='')
        data = {'examples': ['Quoted "text" [A]'], 'example_review': [review]}
        line = '- 1: Quoted "text" [A] [Review: {"Ergebnis": "ungeprüft", "Korrektur": "", "Grund": ""}]'
        self.assertEqual(render_review(data['examples'][0], review, contract), line)
        self.assertEqual(validate_review_list(data, contract), [])
        markdown = '## Examples\nProse\n' + line + '  \n## Other\n- 2: ignored\n'
        lines = review_lines(markdown, contract)
        self.assertEqual(lines, [line])
        self.assertEqual(validate_review_markdown(lines, data['examples'], data['example_review'], contract), [])
        self.assertEqual(validate_review_markdown([], data['examples'], [review], contract),
                         ['example_review Markdown: example line count disagrees'])
        self.assertEqual(validate_review_markdown([line.replace('[A]', '[B]')], data['examples'], [review], contract),
                         ['example_review entry 1: Markdown text or review marker disagrees'])
        self.assertEqual(validate_review_list(dict(data, example_review=[]), contract),
                         ['example_review: length must match examples (one entry per example)'])
        self.assertEqual(validate_review_list(dict(data, examples=['']), contract),
                         ['examples entry 1: must be a non-empty single-line string'])
        self.assertEqual(validate_review_list({}, contract),
                         ['examples: must be a list', 'example_review: must be a list'])
        self.assertEqual(validate_review_list(dict(data, example_review=[None]), contract),
                         ['example_review entry 1: must be an object'])
        self.assertEqual(artifact_pair.validate_review(dict(review, index=2), 1, contract),
                         ['example_review entry 1: index must be 1 (one-based, in example order)'])
        with self.assertRaisesRegex(ValueError, 'Markdown: expected exactly one ## Examples section'):
            review_lines('## Other\n', contract)


if __name__ == '__main__':
    unittest.main()
