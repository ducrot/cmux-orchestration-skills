`planning_state.py init` creates a missing config or detects a valid schema-v1 or schema-v2 file, then displays
every resolved workflow. For those it strictly validates and previews the complete schema-v3
candidate without changing the original bytes, emits the compatibility warning above, and exits
before a run exists. The shared `agents_config.py migrate` command is the read-only preview interface.
Present its complete preview in the human's language and ask the human to accept exactly that proposal.
Its stable output contract writes the complete migration guidance once on stdout; stderr contains only
the short read-only refusal and does not repeat either command. A schema-v1 or schema-v2 planning initialization leaves
stdout empty and emits one complete actionable guidance block on stderr, including the candidate digest
and exact preview and acceptance commands once each.
On confirmation, invoke its displayed `agents_config.py migrate --accept` command including its digest
argument, then rerun planning
initialization; `--accept-config` never authorizes schema migration. When `claude-fable-high` is absent,
the preview identifies it as unavailable and displays the lexicographically first compatible fallback's
profile name, harness, model, and effort without inferring relative quality. Migration preserves existing
profiles and assignments, assigns a missing `issue-chain.triage` to `claude-opus-high`, and leaves
original bytes untouched on failure. It refuses targets with no
write bit or more than one hard link, preserves a symlink path, and applies both guards to its resolved
target. `atomic_initialize` remains create-only.

