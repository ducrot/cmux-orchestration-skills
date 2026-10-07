# Default assignments at initialization

`compare-defaults` lists every worker assignment of `issue-chain`, `grilling`, and `planning` that
differs from the skill defaults. Profile contents are not compared.

1. List every difference as `workflow.worker: current → default` and name every `added_profiles`
   entry.
2. Ask one single-select question, in the same `AskUserQuestion` call as the commit-mode question
   when that one is asked too: "Set these worker assignments to the skill defaults?" / "Sollen diese
   Worker-Zuweisungen auf die Skill-Defaults gesetzt werden?" Offer "Set to defaults" / "Auf
   Defaults setzen" first and recommended, and "Keep local assignments" / "Lokale Zuweisungen
   behalten" second.
3. On adoption, run the reported `acceptance_command` unchanged before init. It sets every listed
   assignment, copies missing default profiles in, and never overwrites a local profile. If it
   refuses because the file changed, compare and ask again.
4. On keep, continue with the file unchanged.

Ask on every fresh init with differences; never store the answer.
