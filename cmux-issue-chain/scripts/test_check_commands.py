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

    def test_targeted_group_can_precede_canonical_and_preserves_exact_commands(self):
        command = "python3 -m unittest -p 'test_specific.py'"
        rules = ("* Targeted check commands for implement, simplify, and review:\n"
                 f"  * `{command}`\n\n  * `{command}`\n"
                 "* Canonical check commands:\n  * `full`\n* Other:\n  * `ignored`")
        self.assertEqual(applicable_commands(rules, "simplify"), [command])
        self.assertEqual(applicable_commands(rules, "test"), ["full"])

    def test_invalid_targeted_declaration_fails_closed_for_applicable_roles(self):
        for body in ("", "  - `<TODO: choose check>`\n"):
            rules = ("- Canonical check commands:\n  - `full`\n"
                     "- Targeted check commands for implement, simplify, and review:\n" + body)
            for role in ("implement", "simplify", "review"):
                with self.assertRaisesRegex(ValueError, "targeted check commands"):
                    applicable_commands(rules, role)
            self.assertEqual(applicable_commands(rules, "test"), ["full"])
            self.assertEqual(applicable_commands(rules, "triage"), [])

    def test_evidence_requires_canonical_declaration_even_with_targeted_entry(self):
        rules = "- Targeted check commands for implement, simplify, and review:\n  - `target`"
        with self.assertRaisesRegex(ValueError, "no canonical check commands"):
            applicable_commands(rules, "implement", require_canonical=True)


if __name__ == "__main__":
    unittest.main()
