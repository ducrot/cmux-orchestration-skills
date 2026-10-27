#!/usr/bin/env python3

from __future__ import annotations

import ast
import unittest
from pathlib import Path


def definitions(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = ast.dump(node)
    return found


class VendoredReviewDefinitionsTest(unittest.TestCase):
    def test_review_list_definitions_match_the_sibling_source(self):
        sibling = Path(__file__).resolve().parents[2] / "cmux-grilling" / "scripts" / "artifact_pair.py"
        if not sibling.is_file():
            self.skipTest("cmux-grilling is absent from this independent installation")
        vendored = definitions(Path(__file__).parent / "grilling_review.py")
        upstream = definitions(sibling)
        for name in ("ReviewList", "ASSUMPTION_REVIEW", "PREMISE_CORRECTION_REVIEW", "REVIEW_LISTS",
                     "REVIEW_LABELS", "review_line_prefix", "render_review", "review_marker",
                     "validate_review", "validate_review_list", "review_lines", "validate_review_markdown",
                     "validate_fact", "json_equals", "section_lines"):
            with self.subTest(definition=name):
                self.assertIn(name, vendored)
                self.assertEqual(vendored[name], upstream.get(name))


if __name__ == "__main__":
    unittest.main()
