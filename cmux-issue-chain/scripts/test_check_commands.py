"""Ground-rule command selection and declaration boundaries."""
import unittest

from check_commands import applicable_commands


class CheckCommands(unittest.TestCase):
    def test_canonical_fallback_for_both_labels_and_all_roles(self):
        for suffix in ("", ", run as the baseline suite by every worker"):
            rules = f"- Canonical check commands{suffix}:\n  - `first`\n  - `second`\n- Other: `ignored`"
            for role in ("implement", "simplify", "review", "test", "triage"):
                self.assertEqual(applicable_commands(rules, role, require_canonical=True),
                                 [] if role == "triage" else ["first", "second"])

    def test_ignored_targeted_group_can_precede_canonical(self):
        command = "python3 -m unittest -p 'test_specific.py'"
        rules = ("* Targeted check commands for implement, simplify, and review:\n"
                 f"  * `{command}`\n\n  * `{command}`\n"
                 "* Canonical check commands:\n  * `full`\n* Other:\n  * `ignored`")
        self.assertEqual(applicable_commands(rules, "simplify"), ["full"])
        self.assertEqual(applicable_commands(rules, "test"), ["full"])

    def test_invalid_targeted_declaration_is_ignored_for_all_roles(self):
        for body in ("", "  - `<TODO: choose check>`\n"):
            rules = ("- Canonical check commands:\n  - `full`\n"
                     "- Targeted check commands for implement, simplify, and review:\n" + body)
            for role in ("implement", "simplify", "review"):
                self.assertEqual(applicable_commands(rules, role), ["full"])
            self.assertEqual(applicable_commands(rules, "test"), ["full"])
            self.assertEqual(applicable_commands(rules, "triage"), [])

    def test_invalid_canonical_declaration_still_fails_with_targeted_entry(self):
        for body in ("", "  - `<TODO: choose check>`\n", "  - `   `\n"):
            rules = ("- Canonical check commands:\n" + body
                     + "- Targeted check commands for implement, simplify, and review:\n  - `target`")
            for role in ("implement", "simplify", "review", "test"):
                with self.subTest(body=body, role=role):
                    with self.assertRaisesRegex(ValueError, "canonical check commands"):
                        applicable_commands(rules, role, require_canonical=True)
            self.assertEqual(applicable_commands(rules, "triage", require_canonical=True), [])

    def test_evidence_requires_canonical_declaration_even_with_targeted_entry(self):
        rules = "- Targeted check commands for implement, simplify, and review:\n  - `target`"
        with self.assertRaisesRegex(ValueError, "no canonical check commands"):
            applicable_commands(rules, "implement", require_canonical=True)


if __name__ == "__main__":
    unittest.main()
