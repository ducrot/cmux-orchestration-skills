"""Static contract for the interpreted sidebar and the shared board vocabulary."""

import re
import unittest
from pathlib import Path


BOARD = Path(__file__).parent / "cmux-sidebar" / "orchestrator-board.swift"

SKILLS = {"issue-chain", "planning", "grilling"}
LANES = {"wait": {"hitl", "blocked", "waiting"}, "done": {"done", "halted"}}


class OrchestratorBoardContract(unittest.TestCase):
    def setUp(self):
        self.source = BOARD.read_text()
        self.code = re.sub(r"//[^\n]*", "", self.source)

    def helper(self, name):
        if f"func {name}(" not in self.code:
            self.fail(f"Missing helper {name}")
        return self.code.split(f"func {name}(", 1)[1].split("\n}", 1)[0]

    def test_vocabulary_and_state_normalization(self):
        skills = set(re.findall(r'hasPrefix\("([\w-]+)"\)\s*\{\s*return\s*"\1"', self.helper("skillOf")))
        self.assertEqual(skills, SKILLS)
        state = self.helper("stateOf")
        states = set(re.findall(r'contains\("(\w+)"\)\s*\{\s*return\s*"\1"', state))
        self.assertEqual(states, set().union(*LANES.values()))
        self.assertTrue(state.rstrip().endswith('return "running"'))

    def test_lane_mapping_and_titles(self):
        lane = self.helper("laneOf")
        mapping = {target: set(re.findall(r'laneState == "(\w+)"', conditions))
                   for conditions, target in re.findall(r'if (laneState ==[^{]+)\{\s*return "(\w+)"', lane)}
        self.assertEqual(mapping, LANES)
        self.assertTrue(lane.rstrip().endswith('return "run"'))
        for variable, value, title in (("laneWait", "wait", "Needs you"),
                                       ("laneRun", "run", "Running"),
                                       ("laneDone", "done", "Done")):
            self.assertIn(f'let {variable} = workspaces.filter {{ laneOf($0) == "{value}" }}', self.code)
            self.assertRegex(self.code, rf'laneHeader\("[^"]+", "{title}", {variable}\.count,')
            self.assertIn(f'ForEach({variable}) {{ w in card(w) }}', self.code)

    def test_interpreter_constraints(self):
        self.assertNotRegex(self.code, r'==\s*nil|\bvar\b|\.padding\(\.')
        self.assertIn('if let descriptionText = w.description', self.helper("descParts"))
        self.assertIn('split(separator: "·")', self.helper("descParts"))
        bindings = re.findall(r'\blet\s+(\w+)\s*=', self.code)
        self.assertEqual(len(bindings), len(set(bindings)), "Local bindings must be unique")

    def test_card_and_session_contract(self):
        for skill, color in (("issue-chain", "#0a84ff"), ("planning", "#af52de"), ("grilling", "#ff9500")):
            self.assertIn(f'if s == "{skill}" {{ return "{color}" }}', self.helper("skillColor"))
        for expression in ('ProgressView(value: pr.value)', 'Text(lbl)', 'Text(detailOf(w))',
                           'Text(agentSummary(w))', 'Text(agoLabel(w))', 'Text(projectOf(w))',
                           'cmux("workspace.select", workspace_id: w.id)'):
            self.assertIn(expression, self.helper("card"))
        self.assertIn('w.directory.split(separator: "/")', self.helper("projectOf"))
        self.assertIn('"Sessions without run"', self.code)
        self.assertIn('workspaces without agent', self.code)
        self.assertIn('ForEach(laneAgents) { w in agentRow(w) }', self.code)


if __name__ == "__main__":
    unittest.main()
