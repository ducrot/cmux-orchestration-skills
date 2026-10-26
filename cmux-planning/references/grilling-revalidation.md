## Revalidate optional grilling input

Show every item that the human must consider:

```bash
python3 scripts/planning_state.py show-revalidation --run-dir <run-dir>
```

Explain that freshness is a human judgment. Show the artifact task and repository, current HEAD and
status identity, Markdown premise corrections, every assumption, and every open, decided, or deferred
decision. For new-form pairs, show each recorded grilling review outcome and value (including any
corrected text and reason), and all open facts. Show these as context and never pre-apply them: require
a fresh human outcome for every assumption, including previously reviewed and unreviewed assumptions.
Unanswered facts are missing information for the specification author. Record a JSON outcomes file
with this unchanged shape:

```json
{
  "accepted": true,
  "premise_corrections": [
    {"index": 1, "outcome": "confirmed", "reason": ""}
  ],
  "assumptions": [
    {"index": 1, "outcome": "corrected", "value": "Corrected statement", "reason": "Why"}
  ],
  "decisions": [
    {"id": "D1", "status": "decided", "decision": "Chosen option", "reason": "Why"}
  ]
}
```

Each premise correction and assumption is `confirmed`, `corrected`, or `discarded`; corrected and
discarded entries need reasons, and corrected entries need replacement text. Cover every source
decision with `open`, `decided`, or `deferred`; resolved entries need outcome text. Refusal uses
`{"accepted": false}` and remains at the same stage with no prepared worker. Interruption preserves
the copied pair plus the latest partial outcomes without creating launchable state.

```bash
python3 scripts/planning_state.py revalidate --run-dir <run-dir> --outcomes <outcomes.json>
```

Workers consume only the resulting complete `grilling-input.json`, never the incomplete source pair.
Every supplied outcomes checkpoint is atomically preserved before normalization, so an interrupted
walkthrough can resume the same copied pair and recorded partial outcomes. Only a complete normalized
handoff prepares `spec-1`; partial or refused outcomes never make a worker launchable.

