## Verification

Run the planning suite and both sibling regression suites:

```bash
python3 -m unittest discover -s cmux-planning/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-issue-chain/scripts -p 'test_*.py'
python3 -m unittest discover -s cmux-grilling/scripts -p 'test_*.py'
```

The dependency-free end-to-end smoke path is:

```bash
python3 scripts/test_planning_flow.py -v -k offline_smoke
python3 scripts/test_worker_readiness.py
```

It uses fake workers and fake CMUX to cover a direct task, both author/reviewer stages, a safe
`pass_with_fixes`, both human approvals, publication, and initialization of the first ready issue
through the sibling issue-chain source when this development repository contains it.
