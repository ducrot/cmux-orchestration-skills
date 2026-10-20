# Default assignments at initialization

`compare-defaults` lists every worker assignment of `issue-chain`, `grilling`, and `planning` that
differs from the skill defaults. Profile contents are not compared.

1. Before the question, list every difference in the chat as `workflow.worker: current → default`
   and name every `added_profiles` entry.
2. Ask one single-select question as the last question of the commit-mode `AskUserQuestion` call,
   or alone when the commit mode is already named: "Set these worker assignments to the skill
   defaults?" / "Sollen diese Worker-Zuweisungen auf die Skill-Defaults gesetzt werden?" Offer
   "Set to defaults" / "Auf Defaults setzen" first and recommended, and "Keep local assignments" /
   "Lokale Zuweisungen behalten" second.
3. On adoption, run the reported `acceptance_command` unchanged before init. It sets every listed
   assignment, copies missing default profiles in, and never overwrites a local profile. If it
   refuses because the file changed, compare and ask again. Drop any `--keep-assignments` from the
   invocation.
4. On keep, continue with the file unchanged and set ` --keep-assignments <differences_sha256>` in
   `--invocation`, replacing an earlier value, so the next-run prompt carries it.

The digest covers only the listed differences: later profile edits keep the answer, while a changed
assignment or skill default asks again.
